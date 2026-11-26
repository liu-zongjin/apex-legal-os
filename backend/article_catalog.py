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
        if stats_file.exists():
            async with aiofiles.open(str(stats_file), mode="r", encoding="utf-8") as f:
                stats_html = await f.read()
        else:
            stats_html = KB_STATS_HTML
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


KB_STATS_HTML = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>知识库可视化统计 - 示例律师事务所（虚构）</title>
  <link rel="stylesheet" href="/static/style.css?v=202604142250">
  <style>
    /* 覆盖主应用全局的 overflow:hidden，允许本页面独立滚动 */
    html, body { overflow: auto !important; }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --primary: #8b1a1a;
      --bg: #f8f8f8;
      --bg-card: #ffffff;
      --text: #1a1a1a;
      --text-secondary: #666;
      --border: #e8e8e8;
      --chart-red: #c0392b;
      --chart-orange: #e67e22;
      --chart-yellow: #f1c40f;
      --chart-green: #27ae60;
      --chart-blue: #2980b9;
      --chart-purple: #8e44ad;
      --chart-pink: #e91e63;
      --chart-teal: #00897b;
      --chart-indigo: #3949ab;
      --chart-lime: #7cb342;
    }
    body.dark-mode {
      --bg: #181818;
      --bg-card: #222222;
      --text: #e8e8e8;
      --text-secondary: #888;
      --border: #2e2e2e;
      --chart-red: #e74c3c;
      --chart-orange: #e67e22;
      --chart-yellow: #f39c12;
      --chart-green: #2ecc71;
      --chart-blue: #3498db;
      --chart-purple: #9b59b6;
      --chart-pink: #e91e63;
      --chart-teal: #1abc9c;
      --chart-indigo: #5c6bc0;
      --chart-lime: #9ccc65;
    }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      padding: 0;
      line-height: 1.6;
    }
    .page-wrapper {
      padding: 20px 24px;
      max-width: 1400px;
      margin: 0 auto;
    }
    .page-header {
      margin-bottom: 20px;
      padding-bottom: 16px;
      border-bottom: 2px solid var(--primary);
    }
    .page-header h1 {
      font-size: 20px;
      font-weight: 700;
      color: var(--primary);
      display: inline-block;
      letter-spacing: -0.02em;
    }
    .last-update {
      font-size: 12px;
      color: var(--text-secondary);
      float: right;
      margin-top: 6px;
    }
    .section-title {
      font-size: 13px;
      font-weight: 600;
      color: var(--text);
      margin-bottom: 12px;
      padding-bottom: 8px;
      border-bottom: 1px solid var(--border);
    }
    .stats-row {
      display: flex;
      gap: 0;
      background: var(--bg-card);
      margin-bottom: 20px;
      border-radius: 10px;
      overflow: hidden;
      box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    }
    .stat-item {
      flex: 1;
      padding: 16px 20px;
      cursor: pointer;
      transition: background 0.15s;
      position: relative;
      border-right: 1px solid var(--border);
      display: flex;
      align-items: baseline;
      gap: 6px;
    }
    .stat-item:first-child { padding-left: 28px; }
    .stat-item:last-child { border-right: none; padding-right: 28px; }
    .stat-item:hover { background: #fef5f5; }
    body.dark-mode .stat-item:hover { background: #2a2020; }
    .stat-value {
      font-size: 28px;
      font-weight: 700;
      color: var(--primary);
      line-height: 1;
      flex-shrink: 0;
    }
    .stat-label {
      font-size: 12px;
      color: var(--text-secondary);
      white-space: nowrap;
    }
    /* 主图表区：4列 */
    .charts-grid {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 16px;
      margin-bottom: 16px;
    }
    /* 次图表区：3列 */
    .charts-grid-3 {
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 16px;
      margin-bottom: 16px;
    }
    .chart-card {
      background: var(--bg-card);
      border-radius: 10px;
      padding: 16px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    }
    /* SVG 图表容器 */
    .chart-svg-wrap {
      width: 100%;
      position: relative;
    }
    /* 饼图 */
    .pie-wrap {
      display: flex;
      align-items: center;
      gap: 16px;
    }
    .pie-legend {
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .pie-legend-item {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 12px;
      color: var(--text);
      cursor: pointer;
      padding: 4px 6px;
      border-radius: 4px;
      transition: background 0.15s;
    }
    .pie-legend-item:hover { background: var(--bg); color: var(--primary); }
    .pie-legend-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      flex-shrink: 0;
    }
    .pie-legend-label { flex: 1; font-weight: 500; }
    .pie-legend-val { font-weight: 600; color: var(--text-secondary); }
    /* 玫瑰图 */
    .rose-wrap { position: relative; }
    .rose-svg-wrap { width: 100%; }
    /* 月度柱状图 */
    .bar-chart-wrap { width: 100%; }
    /* 甘特热力图 */
    .heatmap-wrap { width: 100%; overflow: hidden; }
    .heatmap-grid {
      display: grid;
      gap: 3px;
    }
    .heatmap-cell {
      border-radius: 3px;
      transition: opacity 0.2s;
      cursor: default;
    }
    .heatmap-cell:hover { opacity: 0.7; }
    .heatmap-labels {
      display: flex;
      justify-content: space-between;
      margin-top: 6px;
      font-size: 10px;
      color: var(--text-secondary);
    }
    /* 作者柱状图 */
    .author-bar-wrap { width: 100%; }
    /* 文章长度 */
    .len-bar-wrap { width: 100%; }
    /* 通用柱状条 */
    .h-bar-item {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 8px;
      cursor: pointer;
    }
    .h-bar-item:hover .h-bar-label { color: var(--primary); }
    .h-bar-label {
      width: 56px;
      font-size: 11px;
      color: var(--text-secondary);
      text-align: right;
      transition: color 0.15s;
      flex-shrink: 0;
      font-weight: 500;
    }
    .h-bar-track {
      flex: 1;
      height: 18px;
      background: var(--border);
      position: relative;
      border-radius: 4px;
      overflow: hidden;
    }
    .h-bar-fill {
      height: 100%;
      display: flex;
      align-items: center;
      padding-left: 8px;
      border-radius: 4px;
      transition: width 0.3s ease;
    }
    .h-bar-val {
      font-size: 10px;
      font-weight: 600;
      color: white;
      white-space: nowrap;
    }
    /* 来源域名 & 收藏列表 */
    .bottom-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }
    .list-card {
      background: var(--bg-card);
      border-radius: 10px;
      padding: 16px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    }
    .list-item {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 10px 8px;
      border-radius: 6px;
      cursor: pointer;
      transition: all 0.15s;
    }
    .list-item:hover { background: #fef5f5; padding-left: 12px; }
    body.dark-mode .list-item:hover { background: #2a2020; }
    .rank {
      width: 22px;
      height: 22px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 11px;
      font-weight: 700;
      color: white;
      flex-shrink: 0;
    }
    .rank.gold { background: linear-gradient(135deg, #f59e0b, #d97706); }
    .rank.silver { background: linear-gradient(135deg, #94a3b8, #64748b); }
    .rank.bronze { background: linear-gradient(135deg, #d97706, #b45309); }
    .rank.default { background: var(--border); color: var(--text-secondary); }
    .item-name {
      flex: 1;
      font-size: 12px;
      color: var(--text);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      font-weight: 500;
    }
    .item-count {
      font-size: 12px;
      font-weight: 700;
      color: var(--primary);
    }
    .star-icon { font-size: 12px; color: #f59e0b; }
    .empty {
      text-align: center;
      padding: 32px;
      color: var(--text-secondary);
      font-size: 12px;
    }
    .chart-footer {
      font-size: 11px;
      color: var(--text-secondary);
      margin-top: 8px;
      padding-top: 8px;
      border-top: 1px solid var(--border);
    }
    .chart-footer b { color: var(--primary); font-weight: 600; }
    /* 词云容器 */
    .word-cloud-wrap {
      width: 100%;
      min-height: 180px;
      padding: 12px 8px;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: center;
      gap: 10px 14px;
      line-height: 1.5;
    }
    .word-cloud-tag {
      display: inline-block;
      cursor: pointer;
      font-weight: 700;
      letter-spacing: -0.01em;
      transition: transform 0.2s, opacity 0.2s;
      user-select: none;
    }
    .word-cloud-tag:hover {
      transform: scale(1.18) !important;
      opacity: 0.85;
    }
    @media (max-width: 1100px) {
      .charts-grid { grid-template-columns: repeat(2, 1fr); }
      .charts-grid-3 { grid-template-columns: 1fr 1fr; }
    }
    @media (max-width: 700px) {
      .stats-row { flex-wrap: wrap; }
      .stat-item { min-width: 33.33%; }
      .charts-grid { grid-template-columns: 1fr; }
      .charts-grid-3 { grid-template-columns: 1fr; }
      .bottom-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="page-wrapper">
    <div class="page-header">
      <h1>知识库可视化统计</h1>
      <span class="last-update" id="lastUpdate">加载中...</span>
    </div>

    <!-- 数据概览 -->
    <div class="stats-row" id="statsGrid">
      <div class="stat-item"><div class="stat-value">--</div><div class="stat-label">加载中...</div></div>
    </div>

    <!-- 第一行：4个图表 -->
    <div class="charts-grid">
      <!-- 饼图：文章来源 -->
      <div class="chart-card">
        <div class="section-title">文章来源</div>
        <div id="sourcePieChart"><div class="empty">加载中...</div></div>
      </div>
      <!-- 玫瑰图：专业领域 -->
      <div class="chart-card">
        <div class="section-title">专业领域分布</div>
        <div id="domainRoseChart"><div class="empty">加载中...</div></div>
      </div>
      <!-- 甘特热力图：每日新增 -->
      <div class="chart-card">
        <div class="section-title">每日新增（近30天）</div>
        <div id="dailyHeatmap"><div class="empty">加载中...</div></div>
      </div>
      <!-- 月度柱状图 -->
      <div class="chart-card">
        <div class="section-title">月度趋势</div>
        <div id="monthlyBarChart"><div class="empty">加载中...</div></div>
      </div>
    </div>

    <!-- 第二行：3个图表 -->
    <div class="charts-grid-3">
      <!-- 作者分布 -->
      <div class="chart-card">
        <div class="section-title">作者 Top10</div>
        <div id="authorBarChart"><div class="empty">加载中...</div></div>
      </div>
      <!-- 文章长度分布 -->
      <div class="chart-card">
        <div class="section-title">文章长度分布</div>
        <div id="lenBarChart"><div class="empty">加载中...</div></div>
      </div>
      <!-- 来源域名 Top10 -->
      <div class="chart-card">
        <div class="section-title">来源域名 Top10</div>
        <div id="sourceDomains"><div class="empty">加载中...</div></div>
      </div>
    </div>

    <!-- 第三行：领域标签云 -->
    <div class="bottom-grid">
      <div class="list-card">
        <div class="section-title">领域标签云</div>
        <div id="domainTagCloud" class="word-cloud-wrap"></div>
      </div>
    </div>
  </div>

  <script>
    // 颜色序列
    const COLORS = [
      'var(--chart-red)','var(--chart-orange)','var(--chart-yellow)',
      'var(--chart-green)','var(--chart-blue)','var(--chart-purple)',
      'var(--chart-pink)','var(--chart-teal)','var(--chart-indigo)',
      'var(--chart-lime)'
    ];

    const isDark = localStorage.getItem('darkMode') === 'true';
    if (isDark) document.body.classList.add('dark-mode');
    document.getElementById('lastUpdate').textContent = new Date().toLocaleString('zh-CN');

    // 监听主应用主题变化
    window.addEventListener('message', (e) => {
      if (e.data && e.data.type === 'theme') {
        document.body.classList.toggle('dark-mode', e.data.dark);
      }
    });

    async function loadStats() {
      try {
        const res = await fetch('/api/kb-stats');
        const data = await res.json();
        renderOverview(data.overview);
        renderSourcePie(data.source_distribution);
        renderDomainRose(data.domain_distribution);
        renderDailyHeatmap(data.daily_trend);
        renderMonthlyBar(data.monthly_trend);
        renderAuthorBar(data.author_distribution);
        renderLenBar(data.content_length_buckets);
        renderSourceDomains(data.source_domains);
        renderDomainTagCloud(data.domain_distribution);
      } catch (e) {
        console.error(e);
      }
    }

    function renderOverview(ov) {
      const items = [
        { v: ov.total, l: '文章总数' },
        { v: ov.url_count, l: '网页来源' },
        { v: ov.file_count, l: '文件上传' },
        { v: ov.note_count, l: '笔记总数' },
        { v: ov.articles_with_notes, l: '有笔记文章' }
      ];
      document.getElementById('statsGrid').innerHTML = items.map(item => `
        <div class="stat-item">
          <div class="stat-value">${Number(item.v).toLocaleString()}</div>
          <div class="stat-label">${item.l}</div>
        </div>
      `).join('');
    }

    // ── 饼图 ──────────────────────────────────────────────
    function renderSourcePie(data) {
      const el = document.getElementById('sourcePieChart');
      if (!data || data.length === 0) { el.innerHTML = '<div class="empty">暂无数据</div>'; return; }
      const total = data.reduce((s, d) => s + d.count, 0);
      const cx = 56, cy = 56, r = 50;
      let startAngle = 0;
      const paths = data.map((d, i) => {
        const angle = (d.count / total) * 360;
        const endAngle = startAngle + angle;
        const x1 = cx + r * Math.cos((startAngle - 90) * Math.PI / 180);
        const y1 = cy + r * Math.sin((startAngle - 90) * Math.PI / 180);
        const x2 = cx + r * Math.cos((endAngle - 90) * Math.PI / 180);
        const y2 = cy + r * Math.sin((endAngle - 90) * Math.PI / 180);
        const large = angle > 180 ? 1 : 0;
        const path = angle >= 360
          ? `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${COLORS[i]}" stroke-width="18"/>`
          : `<path d="M${cx},${cy} L${x1},${y1} A${r},${r} 0 ${large},1 ${x2},${y2} Z" fill="${COLORS[i]}"/>`;
        startAngle = endAngle;
        return `<g onclick="window.parent.postMessage({type:'filter',view:'${d.type}'},'*')" style="cursor:pointer">${path}</g>`;
      }).join('');
      const legendHtml = data.map((d, i) => {
        const label = d.type === 'url' ? '网页' : d.type === 'file' ? '文件' : d.type;
        const pct = ((d.count / total) * 100).toFixed(0);
        return `<div class="pie-legend-item">
          <span class="pie-legend-dot" style="background:${COLORS[i]}"></span>
          <span class="pie-legend-label">${label}</span>
          <span class="pie-legend-val">${d.count} (${pct}%)</span>
        </div>`;
      }).join('');
      el.innerHTML = `<div class="pie-wrap">
        <svg width="112" height="112" viewBox="0 0 112 112">${paths}</svg>
        <div class="pie-legend">${legendHtml}</div>
      </div>`;
    }

    // ── 专业领域横向柱状图 ──────────────────────────────────
    function renderDomainRose(data) {
      const el = document.getElementById('domainRoseChart');
      if (!data || data.length === 0) { el.innerHTML = '<div class="empty">暂无数据</div>'; return; }
      const top10 = data.slice(0, 10);
      const max = Math.max(...top10.map(d => d.count), 1);
      const total = top10.reduce((s, d) => s + d.count, 0);
      el.innerHTML = top10.map((d, i) => {
        const pct = (d.count / max) * 100;
        const color = COLORS[i % COLORS.length];
        return `<div class="h-bar-item">
          <span class="h-bar-label">${d.domain}</span>
          <div class="h-bar-track">
            <div class="h-bar-fill" style="width:${pct}%;background:${color}">
              <span class="h-bar-val">${d.count}篇</span>
            </div>
          </div>
        </div>`;
      }).join('') + `<div class="chart-footer">共覆盖 <b>${data.length}</b> 个领域 · Top10合计 <b>${total}</b> 篇</div>`;
    }

    // ── 甘特热力图 ─────────────────────────────────────────
    function renderDailyHeatmap(data) {
      const el = document.getElementById('dailyHeatmap');
      if (!data || data.length === 0) { el.innerHTML = '<div class="empty">暂无数据</div>'; return; }
      const total = data.reduce((s, d) => s + d.count, 0);
      const max = Math.max(...data.map(d => d.count), 1);
      // 近30天按周分组
      const weeks = [];
      let week = [];
      data.forEach((d, i) => {
        week.push(d);
        if (week.length === 7 || i === data.length - 1) {
          weeks.push(week);
          week = [];
        }
      });
      const getColor = (count) => {
        const ratio = count / max;
        if (ratio === 0) return 'var(--border)';
        if (ratio < 0.25) return '#fde8e8';
        if (ratio < 0.5) return '#f9a0a0';
        if (ratio < 0.75) return '#ef5350';
        return 'var(--chart-red)';
      };
      const bodyDark = document.body.classList.contains('dark-mode');
      const gridHtml = weeks.map(week => `
        <div style="display:flex;gap:2px">
          ${week.map(d => {
            const day = d.day ? d.day.slice(5) : '';
            return `<div class="heatmap-cell" style="width:14px;height:14px;background:${bodyDark ? darkGetColor(d.count, max) : getColor(d.count)}" title="${day} ${d.count}篇"></div>`;
          }).join('')}
        </div>
      `).join('');
      el.innerHTML = `<div class="heatmap-wrap">
        <div class="heatmap-grid" style="grid-template-columns:repeat(${Math.max(...weeks.map(w=>w.length))},auto)">${gridHtml}</div>
        <div class="heatmap-labels"><span>30天前</span><span>今天</span></div>
      </div><div class="chart-footer">累计 <b>${total}</b> 篇 · 日均 <b>${(total/data.length).toFixed(1)}</b> 篇</div>`;
    }
    function darkGetColor(count, max) {
      const ratio = count / Math.max(max, 1);
      if (ratio === 0) return '#333';
      if (ratio < 0.25) return '#5c2b2b';
      if (ratio < 0.5) return '#8b3a3a';
      if (ratio < 0.75) return '#b04040';
      return '#e74c3c';
    }

    // ── 月度柱状图（带标签）──────────────────────────────────
    function renderMonthlyBar(data) {
      const el = document.getElementById('monthlyBarChart');
      if (!data || data.length === 0) { el.innerHTML = '<div class="empty">暂无数据</div>'; return; }
      const arr = [...data].reverse().slice(-12);
      const total = arr.reduce((s, d) => s + d.count, 0);
      const max = Math.max(...arr.map(d => d.count), 1);
      const h = 90, labelH = 20;
      const containerW = el.clientWidth || 300;
      const n = arr.length;
      const barW = Math.max(14, Math.floor((containerW - 20) / n) - 6);
      const totalW = n * (barW + 6);
      const bars = arr.map((d, i) => {
        const barH = Math.max(4, (d.count / max) * (h - labelH - 10));
        const x = i * (barW + 6) + 3;
        const y = h - labelH - barH;
        const label = d.month ? d.month.slice(2).replace('-', '/') : '';
        const opacity = 0.5 + 0.5 * (d.count / max);
        return `<g>
          <rect x="${x}" y="${y}" width="${barW}" height="${barH}" rx="3" fill="var(--primary)" opacity="${opacity}" title="${d.month} ${d.count}篇"/>
          <text x="${x + barW/2}" y="${h - 4}" text-anchor="middle" font-size="9" fill="var(--text-secondary)">${label}</text>
        </g>`;
      }).join('');
      el.innerHTML = `<div class="bar-chart-wrap">
        <svg width="100%" height="${h}" viewBox="0 0 ${totalW} ${h}" preserveAspectRatio="xMidYMid meet">
          ${bars}
        </svg>
      </div><div class="chart-footer">近12个月共 <b>${total}</b> 篇 · 月均 <b>${Math.round(total/12)}</b> 篇</div>`;
    }

    // ── 作者横向柱状图（带排名）──────────────────────────────
    function renderAuthorBar(data) {
      const el = document.getElementById('authorBarChart');
      if (!data || data.length === 0) { el.innerHTML = '<div class="empty">暂无作者数据</div>'; return; }
      const top10 = data.slice(0, 10);
      const max = Math.max(...top10.map(d => d.count), 1);
      const total = top10.reduce((s, d) => s + d.count, 0);
      el.innerHTML = top10.map((d, i) => {
        const pct = (d.count / max) * 100;
        const color = COLORS[i % COLORS.length];
        const rank = i + 1;
        const rankClass = rank === 1 ? 'gold' : rank === 2 ? 'silver' : rank === 3 ? 'bronze' : 'default';
        return `<div class="h-bar-item">
          <span class="rank ${rankClass}" style="min-width:22px">${rank}</span>
          <span class="h-bar-label">${d.author.length > 8 ? d.author.slice(0,8) + '…' : d.author}</span>
          <div class="h-bar-track">
            <div class="h-bar-fill" style="width:${pct}%;background:${color}">
              <span class="h-bar-val">${d.count}</span>
            </div>
          </div>
        </div>`;
      }).join('') + `<div class="chart-footer">Top10作者共发布 <b>${total}</b> 篇</div>`;
    }

    // ── 文章长度分布 ────────────────────────────────────────
    function renderLenBar(data) {
      const el = document.getElementById('lenBarChart');
      if (!data || data.length === 0) { el.innerHTML = '<div class="empty">暂无数据</div>'; return; }
      const max = Math.max(...data.map(d => d.count), 1);
      const LEN_COLORS = ['#3b82f6','#10b981','#f59e0b','#8b5cf6','#e91e63','#00897b'];
      el.innerHTML = data.map((d, i) => {
        const pct = (d.count / max) * 100;
        const label = d.bucket ? d.bucket.replace(/^\d\./, '') : d.bucket;
        return `<div class="h-bar-item">
          <span class="h-bar-label" style="width:50px">${label}</span>
          <div class="h-bar-track">
            <div class="h-bar-fill" style="width:${pct}%;background:${LEN_COLORS[i] || 'var(--primary)'}">
              <span class="h-bar-val">${d.count}</span>
            </div>
          </div>
        </div>`;
      }).join('');
    }

    // ── 来源域名 ────────────────────────────────────────────
    function renderSourceDomains(data) {
      const el = document.getElementById('sourceDomains');
      if (!data || data.length === 0) { el.innerHTML = '<div class="empty">暂无数据</div>'; return; }
      el.innerHTML = data.slice(0, 10).map((d, i) => `
        <div class="list-item" onclick="window.parent.postMessage({type:'filterByDomain',domain:'${d.domain}'},'*')">
          <span class="rank ${i===0?'gold':i===1?'silver':i===2?'bronze':'default'}">${i+1}</span>
          <span class="item-name">${d.domain}</span>
          <span class="item-count">${d.count}</span>
        </div>
      `).join('');
    }

    // ── 领域标签云（词云风格）──────────────────────────────
    function renderDomainTagCloud(data) {
      const el = document.getElementById('domainTagCloud');
      if (!data || data.length === 0) { el.innerHTML = '<div class="empty">暂无领域</div>'; return; }

      // 词云颜色池（参考词云图鲜艳多彩风格，适配浅色主题）
      const cloudColors = [
        '#c0392b','#8e1a1a','#e74c3c',   // 红系
        '#2980b9','#1a5276','#3498db',   // 蓝系
        '#8e44ad','#6c3483','#9b59b6',   // 紫系
        '#16a085','#0e6655','#1abc9c',   // 青系
        '#d35400','#ba4a00','#e67e22',   // 橙系
        '#1e8449','#196f3d','#27ae60',   // 绿系
        '#2c3e50','#566573',             // 深色
      ];

      const max = Math.max(...data.map(d => d.count), 1);
      const min = Math.min(...data.map(d => d.count), 1);
      const range = Math.max(max - min, 1);

      // 打乱顺序，词云不按固定顺序排列更自然
      const shuffled = [...data].sort(() => Math.random() - 0.48);

      // 随机旋转角度池（仅少量词倾斜，大部分水平）
      const rotations = [0, 0, 0, 0, 0, 0, -15, 15, -10, 10, -20, 20];

      el.innerHTML = shuffled.map((d, i) => {
        const ratio = (d.count - min) / range;
        // 字号：12px（最小）~ 38px（最大），三级分层
        const size = ratio < 0.2 ? 12 + ratio * 20
                   : ratio < 0.6 ? 16 + ratio * 22
                   :                22 + ratio * 16;
        const color = cloudColors[i % cloudColors.length];
        const rot = rotations[Math.floor(Math.random() * rotations.length)];
        const weight = ratio > 0.5 ? 800 : ratio > 0.2 ? 700 : 600;
        return `<span class="word-cloud-tag"
          style="font-size:${size.toFixed(1)}px;color:${color};font-weight:${weight};transform:rotate(${rot}deg)"
          onclick="window.parent.postMessage({type:'filterByDomain',domain:'${d.domain}'},'*')"
          title="${d.domain} · ${d.count}篇"
        >${d.domain}</span>`;
      }).join('');
    }

    loadStats();
  </script>
</body>
</html>'''
