"""Article catalog, offline snapshots, trash, and library statistics."""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Callable, List, NamedTuple, Optional

import aiofiles
from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from . import knowledge_search
from .article_trash import (
    TrashRestoreConflict,
    list_articles as list_trashed_articles,
    move_articles as move_articles_to_trash,
    purge_articles as purge_trashed_articles,
    purge_expired as purge_expired_articles,
    restore_articles as restore_trashed_articles,
)
from .search_index import case_order_expression, search_article_ids


ARTICLE_OFFLINE_MAX_CONTENT_BYTES = 800 * 1024


class ArticleTrashSelection(BaseModel):
    trash_ids: List[int] = Field(default_factory=list)
    clear_all: bool = False


class BulkArticleDelete(BaseModel):
    article_ids: List[int]


def article_subcategory_labels(conn, article_ids):
    """Resolve confirmed choices in one query; excluded choices are not labels."""
    result = {article_id: [] for article_id in article_ids}
    if not article_ids:
        return result
    placeholders = ",".join("?" for _ in article_ids)
    rows = conn.execute(f"""
        SELECT choice.article_id, child.id, child.name, child.parent_id, parent.name AS domain
        FROM article_subcategory_choices choice
        JOIN domain_taxonomy child ON child.id=choice.subcategory_id
        JOIN domain_taxonomy parent ON parent.id=child.parent_id
        WHERE choice.article_id IN ({placeholders}) AND choice.mode<>'excluded'
        ORDER BY parent.sort_order,parent.id,child.sort_order,child.id
    """, article_ids)
    for row in rows:
        result[row["article_id"]].append({key: row[key] for key in ("id", "name", "parent_id", "domain")})
    return result


class ArticleCatalog(NamedTuple):
    router: APIRouter
    list_articles: Callable[..., dict]


def create_router(
    get_db: Callable[[], sqlite3.Connection],
    *,
    save_article: Callable[..., int],
    load_fada_notes: Callable[[], list],
    frontend_dir: Path,
) -> ArticleCatalog:
    router = APIRouter()
    _article_trash_cleanup_task: Optional[asyncio.Task] = None

    @router.get("/api/articles")
    def list_articles(
        q: Optional[str] = None,
        fuzzy: bool = True,
        semantic: bool = False,
        domain: Optional[str] = None,
        subcategory_id: Optional[int] = None,
        classification_status: Optional[str] = None,
        author: Optional[str] = None,
        custom_tag: Optional[str] = None,
        custom_tags: Optional[str] = None,   # 逗号分隔的多个标签名（二级目录筛选）
        source_type: Optional[str] = None,
        search_scope: Optional[str] = None,  # 搜索范围：all/title/summary/content/tags/notes
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
        tag_group_id: Optional[int] = None,  # 标签组ID，支持按标签组返回置顶状态
        pin_scope: Optional[str] = None,     # 当前文章列表置顶作用域
    ):
        """获取文章列表，支持搜索和筛选（包括笔记内容）"""
        conn = get_db()
        conditions = []
        params = []
        scope = "all"  # 搜索范围默认值

        # ── 搜索范围映射 ──
        # scope → (字段列表, 是否需要子查询 notes)
        SCOPE_FIELDS = {
            "title":   ["title"],
            "summary": ["summary"],
            "content": ["content"],
            "tags":    ["tags"],
            "notes":   [],       # 特殊处理：走子查询
            "all":     ["title", "content", "summary"],
        }

        # 作者搜索特殊处理：精确匹配标签前缀 "作者:query"
        # 不走 SCOPE_FIELDS，在下方独立处理
        is_author_scope = (search_scope == "author")
        fts_ids = []

        if q:
            # 移除搜索词前后的空格
            q = q.strip()
            if semantic and knowledge_search.is_exact_lookup(q):
                fuzzy = False
                if (q[0], q[-1]) in {('"', '"'), ('“', '”')}:
                    q = q[1:-1]
            escaped_q = q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')

            if is_author_scope:
                # 作者范围只匹配作者标签，不额外要求作者名出现在标题或正文中。
                scope = "author"
                conditions.append("tags LIKE ? ESCAPE '\\'")
                params.append(f"%作者:{escaped_q}%")
            else:
                scope = search_scope if search_scope in SCOPE_FIELDS else "all"
                fields = SCOPE_FIELDS[scope]
                if fuzzy and scope != "notes":
                    fts_columns = None if scope == "all" else fields
                    fts_ids = search_article_ids(conn, q, columns=fts_columns)

            if is_author_scope:
                pass
            elif scope == "notes":
                # 仅搜索笔记
                like = f"%{escaped_q}%"
                conditions.append("""
                id IN (
                    SELECT DISTINCT article_id FROM notes
                    WHERE content LIKE ? ESCAPE '\\' OR selected_text LIKE ? ESCAPE '\\'
                )
            """)
                params += [like, like]
            else:
                # 按指定字段搜索（可能含笔记子查询）
                like_parts = []
                like = f"%{escaped_q}%"
                for field in fields:
                    like_parts.append(f"{field} LIKE ? ESCAPE '\\'")
                    params.append(like)
                # "全部"模式下也搜索笔记
                if scope == "all":
                    like_parts.append("""
                    id IN (
                        SELECT DISTINCT article_id FROM notes
                        WHERE content LIKE ? ESCAPE '\\' OR selected_text LIKE ? ESCAPE '\\'
                    )
                """)
                    params += [like, like]
                if fts_ids:
                    like_parts.append("id IN (" + ",".join("?" * len(fts_ids)) + ")")
                    params += fts_ids
                conditions.append("(" + " OR ".join(like_parts) + ")")

        text_condition_count, text_param_count = len(conditions), len(params)

        if domain:
            conditions.append("EXISTS (SELECT 1 FROM json_each(articles.domains) d WHERE d.value=?)")
            params.append(domain)

        if subcategory_id is not None:
            conditions.append("articles.id IN (SELECT article_id FROM article_subcategory_choices WHERE subcategory_id=? AND mode<>'excluded')")
            params.append(subcategory_id)

        if classification_status == "needs_review":
            conditions.append("id IN (SELECT article_id FROM domain_classification_jobs WHERE status='needs_review')")

        if author:
            conditions.append("tags LIKE ?")
            params.append(f'%作者:{author}%')

        if custom_tag:
            conditions.append("tags LIKE ?")
            params.append(f'%"{custom_tag}"%')

        if custom_tags:
            # 多个标签名（OR 关系，匹配任一标签即可）
            tag_list = [t.strip() for t in custom_tags.split(',') if t.strip()]
            if tag_list:
                sub_conditions = ["tags LIKE ?"] * len(tag_list)
                conditions.append("(" + " OR ".join(sub_conditions) + ")")
                params += [f'%"{t}"%' for t in tag_list]

        if source_type:
            conditions.append("source_type = ?")
            params.append(source_type)

        search_hits, exact_ids = {}, []
        search_info = {"method": "keywords", "notice": ""}
        if q and fuzzy and semantic and knowledge_search.supports_semantics(q) and scope in knowledge_search.FIELDS + ("all",):
            # Scope/category/tag filters apply before either independent recall channel.
            filters = conditions[text_condition_count:]
            filter_params = params[text_param_count:]
            eligible_where = " WHERE " + " AND ".join(filters) if filters else ""
            eligible = [row[0] for row in conn.execute("SELECT id FROM articles" + eligible_where, filter_params)]
            hits, search_info = knowledge_search.retrieve(conn, q, "article", eligible, scope)
            search_hits = {hit["id"]: hit for hit in hits}
            if hits:
                hit_ids = list(search_hits)
                conditions[0] = "(" + conditions[0] + " OR articles.id IN (" + ",".join("?" for _ in hit_ids) + "))"
                params[text_param_count:text_param_count] = hit_ids
                fts_ids = hit_ids + [i for i in fts_ids if i not in search_hits]
            # Full literal matches retain priority over approximate topic similarity.
            exact_fields = SCOPE_FIELDS[scope]
            exact_sql = " OR ".join(field + " LIKE ? ESCAPE '\\'" for field in exact_fields)
            exact_ids = [row[0] for row in conn.execute("SELECT id FROM articles WHERE (" + exact_sql + ")" + (" AND " + " AND ".join(filters) if filters else ""), [like] * len(exact_fields) + filter_params)]

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        total = conn.execute(f"SELECT COUNT(*) FROM articles {where}", params).fetchone()[0]

        offset = (page - 1) * page_size
        fts_order = case_order_expression(fts_ids)
        if exact_ids:
            fts_order = case_order_expression(exact_ids) + (", " + fts_order if fts_order else "")
        if not pin_scope:
            if tag_group_id is not None:
                pin_scope = f"tag_group:{tag_group_id}"
            elif domain:
                pin_scope = f"domain:{domain}"
            elif author:
                pin_scope = f"author:{author}"
            elif custom_tag:
                pin_scope = f"tag:{custom_tag}"
            elif custom_tags:
                pin_scope = "custom_tags:" + hashlib.sha1(custom_tags.encode("utf-8")).hexdigest()
            elif source_type:
                pin_scope = f"source:{source_type}"
            else:
                pin_scope = "view:all"
        if pin_scope:
            pin_scope = pin_scope.strip()[:200]

        # ── 置顶状态计算逻辑 ──
        # pin_scope 表示当前文章列表；置顶只在该列表作用域内生效。
        if pin_scope:
            select_cols = "articles.id, articles.title, articles.summary, articles.content, articles.domains, articles.source_type, articles.source_url, articles.source_filename, articles.source_localpath, articles.created_at, articles.tags, articles.pinned"
            query = f"""
            SELECT {select_cols},
                   COALESCE(list_pin.pinned, 0) AS effective_pinned
            FROM articles
            LEFT JOIN article_list_pins list_pin
                   ON list_pin.article_id = articles.id
                   AND list_pin.list_key = ?
            {where}
            ORDER BY effective_pinned DESC{', ' + fts_order if fts_order else ''}, articles.created_at DESC
            LIMIT ? OFFSET ?
        """
            rows = conn.execute(query, [pin_scope] + params + [page_size, offset]).fetchall()
        else:
            rows = []
        child_labels = article_subcategory_labels(conn, [row["id"] for row in rows])
        conn.close()

        def extract_content_snippets(content: str, keyword: str, context: int = 60) -> list:
            """从正文中提取关键词命中的上下文片段列表（不限数量）"""
            if not keyword or not content:
                return []
            # 先剥离 HTML 标签，避免片段中包含 <p>、</p> 等裸标签
            import re as _re
            plain = _re.sub(r'<[^>]+>', '', content)
            # 还原常见 HTML 实体
            plain = plain.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>') \
                         .replace('&quot;', '"').replace('&#039;', "'").replace('&nbsp;', ' ')
            kw_lower = keyword.lower()
            text_lower = plain.lower()
            snippets = []
            start = 0
            while True:
                idx = text_lower.find(kw_lower, start)
                if idx == -1:
                    break
                s = max(0, idx - context)
                e = min(len(plain), idx + len(keyword) + context)
                prefix = '…' if s > 0 else ''
                suffix = '…' if e < len(plain) else ''
                snippets.append({
                    "text": prefix + plain[s:e] + suffix,
                    "offset": idx   # 关键词在纯文本中的字符偏移，供前端定位
                })
                start = idx + len(keyword)
            return snippets

        articles = []
        for r in rows:
            a = dict(r)
            a["domains"] = json.loads(a["domains"] or "[]")
            a["tags"] = json.loads(a["tags"] or "[]")
            a["subcategories"] = child_labels.get(a["id"], [])
            a["subcategory_ids"] = [child["id"] for child in a["subcategories"]]
            hit = search_hits.get(a["id"])
            if hit:
                a["search_match"] = {key: hit[key] for key in ("channels", "field", "label", "text", "offset")}
            # 列表置顶优先：若查询中有 effective_pinned 字段则用它，否则用 articles.pinned
            if "effective_pinned" in a:
                a["pinned"] = bool(a.pop("effective_pinned"))
            else:
                a["pinned"] = bool(a.get("pinned", 0))
            # 当有搜索词且正文命中时，附加上下文片段
            # 仅在搜索范围包含"正文"（scope=all 或 scope=content）时提取
            if q and a.get("content") and scope in ("all", "content"):
                a["content_snippets"] = extract_content_snippets(a["content"], q)
            else:
                a["content_snippets"] = []
            del a["content"]  # 不在列表接口中返回全文
            articles.append(a)

        return {"total": total, "page": page, "page_size": page_size, "articles": articles, "search_info": search_info}


    @router.get("/api/articles/offline-snapshot")
    def articles_offline_snapshot(limit: int = 100):
        """最近文章离线快照：排除超大正文，避免浏览器离线缓存占用过多内存。"""
        max_items = max(1, min(int(limit or 100), 200))
        conn = get_db()
        rows = conn.execute(
            """SELECT * FROM articles
           WHERE length(CAST(content AS BLOB)) <= ?
           ORDER BY datetime(created_at) DESC, id DESC
           LIMIT ?""",
            (ARTICLE_OFFLINE_MAX_CONTENT_BYTES, max_items),
        ).fetchall()
        excluded_oversized = conn.execute(
            "SELECT COUNT(*) FROM articles WHERE length(CAST(content AS BLOB)) > ?",
            (ARTICLE_OFFLINE_MAX_CONTENT_BYTES,),
        ).fetchone()[0]
        children = {}
        snapshot_ids = [row["id"] for row in rows]
        placeholders = ",".join("?" for _ in snapshot_ids) or "NULL"
        for row in conn.execute(f"SELECT article_id,subcategory_id FROM article_subcategory_choices WHERE mode<>'excluded' AND article_id IN ({placeholders})", snapshot_ids):
            children.setdefault(row[0], []).append(row[1])
        statuses = {row[0]: row[1] for row in conn.execute(f"SELECT article_id,status FROM domain_classification_jobs WHERE article_id IN ({placeholders})", snapshot_ids)}
        conn.close()
        articles = []
        allowed_fields = {
            "id",
            "title",
            "content",
            "summary",
            "domains",
            "source_type",
            "source_url",
            "source_filename",
            "created_at",
            "tags",
            "pinned",
        }
        for row in rows:
            raw = dict(row)
            a = {key: raw.get(key) for key in allowed_fields}
            a["domains"] = json.loads(a["domains"] or "[]")
            a["tags"] = json.loads(a["tags"] or "[]")
            a["pinned"] = bool(a.get("pinned", 0))
            a["subcategory_ids"] = children.get(a["id"], [])
            a["classification_status"] = statuses.get(a["id"], "done")
            articles.append(a)
        return {
            "version": 3,
            "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "limit": max_items,
            "max_content_bytes": ARTICLE_OFFLINE_MAX_CONTENT_BYTES,
            "excluded_oversized": excluded_oversized,
            "articles": articles,
        }


    @router.get("/api/articles/trash")
    def get_article_trash(limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
        """List recoverable articles; each item expires 30 days after deletion."""
        conn = get_db()
        try:
            purge_expired_articles(conn)
            conn.commit()
            return list_trashed_articles(conn, limit, offset)
        finally:
            conn.close()


    @router.post("/api/articles/trash/restore")
    def restore_article_trash(body: ArticleTrashSelection):
        ids = list(dict.fromkeys(article_id for article_id in body.trash_ids if article_id > 0))
        if not ids or len(ids) > 500:
            raise HTTPException(status_code=400, detail="请选择1至500篇待恢复文章")
        conn = get_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            purge_expired_articles(conn)
            result = restore_trashed_articles(conn, ids)
            conn.commit()
            return {"success": True, **result}
        except TrashRestoreConflict as exc:
            conn.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            conn.rollback()
            raise HTTPException(status_code=500, detail=f"恢复文章失败: {exc}") from exc
        finally:
            conn.close()


    @router.delete("/api/articles/trash")
    def purge_article_trash(body: ArticleTrashSelection):
        ids = list(dict.fromkeys(article_id for article_id in body.trash_ids if article_id > 0))
        if not body.clear_all and (not ids or len(ids) > 500):
            raise HTTPException(status_code=400, detail="请选择1至500篇待彻底删除文章")
        conn = get_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            purge_expired_articles(conn)
            deleted_count = purge_trashed_articles(conn, None if body.clear_all else ids)
            conn.commit()
            return {"success": True, "deleted_count": deleted_count}
        except Exception as exc:
            conn.rollback()
            raise HTTPException(status_code=500, detail=f"清理回收站失败: {exc}") from exc
        finally:
            conn.close()


    def _cleanup_expired_article_trash() -> int:
        conn = get_db()
        try:
            count = purge_expired_articles(conn)
            conn.commit()
            return count
        finally:
            conn.close()


    async def _article_trash_cleanup_loop():
        while True:
            try:
                await run_in_threadpool(_cleanup_expired_article_trash)
            except Exception as exc:
                print(f"[article-trash] cleanup failed: {exc}")
            await asyncio.sleep(3600)


    @router.on_event("startup")
    async def start_article_trash_cleanup():
        nonlocal _article_trash_cleanup_task
        if _article_trash_cleanup_task is None or _article_trash_cleanup_task.done():
            _article_trash_cleanup_task = asyncio.create_task(_article_trash_cleanup_loop())


    @router.on_event("shutdown")
    async def stop_article_trash_cleanup():
        nonlocal _article_trash_cleanup_task
        if _article_trash_cleanup_task:
            _article_trash_cleanup_task.cancel()
            _article_trash_cleanup_task = None


    @router.get("/api/articles/{article_id}")
    def get_article(article_id: int):
        """获取文章详情"""
        conn = get_db()
        row = conn.execute("SELECT * FROM articles WHERE id=?", (article_id,)).fetchone()
        if not row:
            conn.close()
            raise HTTPException(status_code=404, detail="文章不存在")
        a = dict(row)
        a["domains"] = json.loads(a["domains"] or "[]")
        a["tags"] = json.loads(a["tags"] or "[]")
        a["subcategories"] = article_subcategory_labels(conn, [article_id])[article_id]
        a["subcategory_ids"] = [child["id"] for child in a["subcategories"]]
        classification = conn.execute("SELECT status FROM domain_classification_jobs WHERE article_id=?", (article_id,)).fetchone()
        a["classification_status"] = classification[0] if classification else "done"
        a.pop("starred", None)  # 兼容旧数据库列，但不再向客户端暴露已移除功能
        a["pinned"] = bool(a.get("pinned", 0))
        conn.close()
        return a


    @router.post("/api/articles/blank")
    async def create_blank_article(request: Request):
        """Create a user-authored knowledge item without importing a source file."""
        body = await request.json()
        title = str(body.get("title") or "未命名知识").strip()[:200] or "未命名知识"
        # source_hash has a database uniqueness constraint. Give every new blank article
        # an invisible seed so users can create more than one empty knowledge item.
        blank_content = f'<p style="--manual-article-seed:{uuid.uuid4().hex}"><br></p>'
        article_id = save_article(
            title=title,
            content=blank_content,
            summary="",
            domains=[],
            source_type="manual",
            tags=[],
            check_duplicate=False,
        )
        return {"success": True, "id": article_id, "title": title}


    @router.delete("/api/articles/bulk")
    def bulk_delete_articles(body: BulkArticleDelete):
        """将多篇文章及其关联数据移入可恢复的回收站。"""
        article_ids = list(dict.fromkeys(article_id for article_id in body.article_ids if article_id > 0))
        if not article_ids:
            raise HTTPException(status_code=400, detail="请至少选择一篇文章")
        if len(article_ids) > 500:
            raise HTTPException(status_code=400, detail="单次最多删除500篇文章")

        conn = get_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            result = move_articles_to_trash(conn, article_ids)
            conn.commit()
            return {"success": True, **result}
        except Exception as e:
            conn.rollback()
            raise HTTPException(status_code=500, detail=f"批量删除文章失败: {str(e)}")
        finally:
            conn.close()


    @router.delete("/api/articles/{article_id}")
    def delete_article(article_id: int):
        """将文章移入30天回收站。"""
        conn = get_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            result = move_articles_to_trash(conn, [article_id])
            conn.commit()
            return {"success": True, **result}
        except Exception as exc:
            conn.rollback()
            raise HTTPException(status_code=500, detail=f"删除文章失败: {exc}") from exc
        finally:
            conn.close()


    @router.get("/api/stats")
    def get_stats():
        """统计数据"""
        conn = get_db()
        total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        url_count = conn.execute("SELECT COUNT(*) FROM articles WHERE source_type='url'").fetchone()[0]
        file_count = conn.execute("SELECT COUNT(*) FROM articles WHERE source_type='file'").fetchone()[0]
        note_count, articles_with_notes = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT article_id) FROM notes"
        ).fetchone()
        conn.close()
        fada_note_count = len(load_fada_notes())
        return {
            "total": total,
            "url_count": url_count,
            "file_count": file_count,
            "note_count": note_count + fada_note_count,
            "articles_with_notes": articles_with_notes + fada_note_count,
        }


    @router.get("/api/kb-stats")
    def get_kb_stats():
        """知识库可视化统计 - 多维度数据"""
        import json
        from collections import Counter
        from urllib.parse import urlparse

        conn = get_db()

        # 1. 基础统计
        total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        url_count = conn.execute("SELECT COUNT(*) FROM articles WHERE source_type='url'").fetchone()[0]
        file_count = conn.execute("SELECT COUNT(*) FROM articles WHERE source_type='file'").fetchone()[0]

        # 2. 来源类型分布
        source_dist = conn.execute("""
        SELECT source_type, COUNT(*) as count
        FROM articles GROUP BY source_type
    """).fetchall()

        # 3. 最近7天/30天/总文章数趋势（按月份）
        monthly_stats = conn.execute("""
        SELECT
            strftime('%Y-%m', created_at) as month,
            COUNT(*) as count
        FROM articles
        GROUP BY month
        ORDER BY month DESC
        LIMIT 24
    """).fetchall()

        # 4. 专业领域分布（解析 domains JSON）
        all_articles = conn.execute("SELECT domains FROM articles WHERE domains IS NOT NULL").fetchall()
        domain_counter = Counter()
        for row in all_articles:
            try:
                domains = json.loads(row[0]) if row[0] else []
                for d in domains:
                    if d and d.strip():
                        domain_counter[d.strip()] += 1
            except:
                pass

        # 5. 笔记数量统计
        note_stats = conn.execute("""
        SELECT COUNT(*) as total_notes,
               COUNT(DISTINCT article_id) as articles_with_notes
        FROM notes
    """).fetchone()

        # 7. 平均文章长度
        avg_content_len = conn.execute("""
        SELECT AVG(LENGTH(content)) FROM articles WHERE content IS NOT NULL
    """).fetchone()[0] or 0

        # 8. 来源域名分布（提取URL域名）
        url_articles = conn.execute("""
        SELECT source_url FROM articles WHERE source_type='url' AND source_url IS NOT NULL
    """).fetchall()
        domain_counter2 = Counter()
        for row in url_articles:
            url = row[0] or ''
            parsed = urlparse(url)
            domain = parsed.netloc or (url.split('://')[1].split('/')[0] if '://' in url else '')
            if domain:
                domain_counter2[domain] += 1

        # 9. 每日新增趋势（最近90天，前端可切换 7/30/90）
        daily_stats = conn.execute("""
        SELECT
            date(created_at) as day,
            COUNT(*) as count
        FROM articles
        WHERE created_at >= date('now', '-90 days')
        GROUP BY day
        ORDER BY day ASC
    """).fetchall()

        # 10. 作者分布 Top15
        author_rows = conn.execute("""
        SELECT j.value as author, COUNT(*) as cnt
        FROM articles a
        JOIN json_each(a.tags) j
        WHERE a.tags IS NOT NULL AND j.value LIKE '作者:%'
        GROUP BY j.value
        ORDER BY cnt DESC
        LIMIT 15
    """).fetchall()

        # 11. 文章长度分段
        len_rows = conn.execute("""
        SELECT
            CASE
                WHEN LENGTH(content) < 500 THEN '1.<500字'
                WHEN LENGTH(content) < 2000 THEN '2.500-2K'
                WHEN LENGTH(content) < 5000 THEN '3.2K-5K'
                WHEN LENGTH(content) < 10000 THEN '4.5K-1万'
                WHEN LENGTH(content) < 30000 THEN '5.1-3万'
                ELSE '6.>3万'
            END as bucket,
            COUNT(*) as cnt
        FROM articles
        WHERE content IS NOT NULL
        GROUP BY bucket
        ORDER BY
            CASE bucket
                WHEN '1.<500字' THEN 1
                WHEN '2.500-2K' THEN 2
                WHEN '3.2K-5K' THEN 3
                WHEN '4.5K-1万' THEN 4
                WHEN '5.1-3万' THEN 5
                ELSE 6
            END
    """).fetchall()

        # 12. 质量与活跃度指标
        all_rows = conn.execute("""
        SELECT id, title, content, summary, domains, tags, source_type, created_at
        FROM articles
    """).fetchall()

        content_lengths = []
        uncategorized_count = 0
        no_author_count = 0
        no_summary_count = 0
        domain_total_mentions = 0
        recent_7_count = 0
        recent_30_count = 0
        active_day_set = set()
        today = datetime.datetime.now().date()
        longest_articles = []
        needs_summary_articles = []
        uncategorized_articles = []
        no_author_articles = []

        def article_brief(row, content_len=None):
            content_len = len(row["content"] or "") if content_len is None else content_len
            return {
                "id": row["id"],
                "title": (row["title"] or "")[:80],
                "created_at": row["created_at"],
                "source_type": row["source_type"],
                "length": content_len,
            }

        for row in all_rows:
            content = row["content"] or ""
            content_len = len(content)
            content_lengths.append(content_len)
            longest_articles.append({"id": row["id"], "title": row["title"] or "", "length": content_len})

            try:
                domains = json.loads(row["domains"] or "[]")
            except Exception:
                domains = []
            if not domains:
                uncategorized_count += 1
                uncategorized_articles.append(article_brief(row, content_len))
            domain_total_mentions += len(domains)

            try:
                tags = json.loads(row["tags"] or "[]")
            except Exception:
                tags = []
            missing_author = not any(str(t).startswith("作者:") and str(t).strip() not in ("作者:", "作者:未知") for t in tags)
            if missing_author:
                no_author_count += 1
                no_author_articles.append(article_brief(row, content_len))

            if not (row["summary"] or "").strip():
                no_summary_count += 1
                needs_summary_articles.append(article_brief(row, content_len))

            created_raw = (row["created_at"] or "")[:10]
            try:
                created_day = datetime.datetime.strptime(created_raw, "%Y-%m-%d").date()
                delta_days = (today - created_day).days
                if 0 <= delta_days <= 6:
                    recent_7_count += 1
                if 0 <= delta_days <= 29:
                    recent_30_count += 1
                    active_day_set.add(created_raw)
            except Exception:
                pass

        content_lengths.sort()
        median_content_len = 0
        if content_lengths:
            mid = len(content_lengths) // 2
            if len(content_lengths) % 2:
                median_content_len = content_lengths[mid]
            else:
                median_content_len = (content_lengths[mid - 1] + content_lengths[mid]) / 2

        coverage = {
            "summary_rate": round((total - no_summary_count) / total * 100, 1) if total else 0,
            "note_article_rate": round((note_stats[1] if note_stats else 0) / total * 100, 1) if total else 0,
            "categorized_rate": round((total - uncategorized_count) / total * 100, 1) if total else 0,
            "known_author_rate": round((total - no_author_count) / total * 100, 1) if total else 0,
        }

        freshness = {
            "recent_7_count": recent_7_count,
            "recent_30_count": recent_30_count,
            "active_days_30": len(active_day_set),
            "avg_daily_30": round(recent_30_count / 30, 2),
        }

        # 补齐近90天无新增的日期，让前端热力图更科学
        daily_map = {str(r[0]): r[1] for r in daily_stats}
        daily_filled = []
        for i in range(89, -1, -1):
            day = today - datetime.timedelta(days=i)
            day_key = day.isoformat()
            daily_filled.append({"day": day_key, "count": daily_map.get(day_key, 0)})

        longest_articles = sorted(longest_articles, key=lambda x: x["length"], reverse=True)[:8]
        needs_summary_articles = sorted(needs_summary_articles, key=lambda x: x["length"], reverse=True)[:8]
        uncategorized_articles = sorted(uncategorized_articles, key=lambda x: x["created_at"] or "", reverse=True)[:8]
        no_author_articles = sorted(no_author_articles, key=lambda x: x["created_at"] or "", reverse=True)[:8]

        recent_rows = conn.execute("""
        SELECT id, title, created_at, source_type, LENGTH(content) AS content_len
        FROM articles
        ORDER BY created_at DESC
        LIMIT 8
    """).fetchall()
        recent_articles = [{
            "id": r["id"],
            "title": (r["title"] or "")[:80],
            "created_at": r["created_at"],
            "source_type": r["source_type"],
            "length": r["content_len"] or 0,
        } for r in recent_rows]

        noted_rows = conn.execute("""
        SELECT a.id, a.title, a.created_at, a.source_type, LENGTH(a.content) AS content_len,
               COUNT(n.id) AS note_count, MAX(n.created_at) AS latest_note_at
        FROM articles a
        JOIN notes n ON n.article_id = a.id
        GROUP BY a.id
        ORDER BY latest_note_at DESC
        LIMIT 8
    """).fetchall()
        noted_articles = [{
            "id": r["id"],
            "title": (r["title"] or "")[:80],
            "created_at": r["latest_note_at"] or r["created_at"],
            "source_type": r["source_type"],
            "length": r["content_len"] or 0,
            "note_count": r["note_count"] or 0,
        } for r in noted_rows]

        conn.close()

        return {
            "overview": {
                "total": total,
                "url_count": url_count,
                "file_count": file_count,
                "note_count": note_stats[0] if note_stats else 0,
                "articles_with_notes": note_stats[1] if note_stats else 0,
                "avg_content_length": round(avg_content_len, 0),
                "median_content_length": round(median_content_len, 0),
                "domain_count": len(domain_counter),
                "avg_domains_per_article": round(domain_total_mentions / total, 2) if total else 0,
                "uncategorized_count": uncategorized_count,
                "no_author_count": no_author_count,
                "no_summary_count": no_summary_count,
            },
            "coverage": coverage,
            "freshness": freshness,
            "source_distribution": [{"type": r[0] or "unknown", "count": r[1]} for r in source_dist],
            "monthly_trend": [{"month": r[0], "count": r[1]} for r in monthly_stats],
            "domain_distribution": [{"domain": k, "count": v} for k, v in domain_counter.most_common(15)],
            "source_domains": [{"domain": k, "count": v} for k, v in domain_counter2.most_common(10)],
            "daily_trend": daily_filled,
            "author_distribution": [{"author": (r[0] or "").replace("作者:", "", 1), "count": r[1]} for r in author_rows],
            "content_length_buckets": [{"bucket": r[0], "count": r[1]} for r in len_rows],
            "longest_articles": longest_articles,
            "action_lists": {
                "needs_summary": needs_summary_articles,
                "uncategorized": uncategorized_articles,
                "no_author": no_author_articles,
                "recent": recent_articles,
                "noted": noted_articles,
            },
        }

    @router.get("/kb-stats")
    async def kb_stats_page():
        """知识库可视化统计页面"""
        stats_file = frontend_dir / "kb-stats.html"
        if not stats_file.is_file():
            stats_file = frontend_dir / "kb-stats-fallback.html"
        if not stats_file.is_file():
            raise HTTPException(status_code=404, detail="知识库统计页面不存在")
        async with aiofiles.open(str(stats_file), mode="r", encoding="utf-8") as f:
            stats_html = await f.read()
        return Response(
            content=stats_html,
            media_type="text/html",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
                "Vary": "Accept-Encoding",
            }
        )

    return ArticleCatalog(router, list_articles)
