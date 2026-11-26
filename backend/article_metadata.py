"""Article tag and subcategory edits using the shared taxonomy and tag preferences."""

from __future__ import annotations

import datetime
import json
import sqlite3
from typing import Callable, List

from fastapi import APIRouter, Body, Form, HTTPException
from pydantic import BaseModel

from . import domain_taxonomy as domain_taxonomy_module


class BulkArticleTagsUpdate(BaseModel):
    article_ids: List[int]
    tags: List[str]


PURGED_TAG_NAMES_PREFERENCE_KEY = "tag_group_purged_names_v1"


def _get_purged_tag_names(conn) -> set[str]:
    row = conn.execute(
        "SELECT value_json FROM app_preferences WHERE preference_key = ?",
        (PURGED_TAG_NAMES_PREFERENCE_KEY,),
    ).fetchone()
    if not row:
        return set()
    try:
        value = json.loads(row["value_json"] or "[]")
    except (TypeError, json.JSONDecodeError):
        return set()
    return {item for item in value if isinstance(item, str) and item}


def _set_purged_tag_names(conn, names: set[str]) -> None:
    conn.execute(
        """INSERT INTO app_preferences (preference_key, value_json, updated_at)
           VALUES (?, ?, ?)
           ON CONFLICT(preference_key) DO UPDATE SET
             value_json=excluded.value_json,
             updated_at=excluded.updated_at""",
        (
            PURGED_TAG_NAMES_PREFERENCE_KEY,
            json.dumps(sorted(names), ensure_ascii=False),
            datetime.datetime.now().isoformat(),
        ),
    )


def create_router(
    get_db: Callable[[], sqlite3.Connection],
    *,
    domain_assignment_state: Callable,
) -> APIRouter:
    router = APIRouter()

    @router.put("/api/articles/{article_id}/tags")
    async def update_article_tags(
        article_id: int,
        tags: str = Form(...),
        domains: str = Form(None),
        new_tags: str = Form(None),   # 前端传来的"本次新增"标签列表，用于同步到自定义库
    ):
        """更新文章标签和领域"""
        conn = get_db()

        # 验证文章是否存在
        row = conn.execute("SELECT id, title, content FROM articles WHERE id=?", (article_id,)).fetchone()
        if not row:
            conn.close()
            raise HTTPException(status_code=404, detail="文章不存在")

        try:
            # 解析标签JSON
            tags_list = json.loads(tags)

            # 保留作者标签（如果已存在）
            existing_row = conn.execute("SELECT tags FROM articles WHERE id=?", (article_id,)).fetchone()
            existing_tags = json.loads(existing_row["tags"] or "[]")
            author_tags = [t for t in existing_tags if t.startswith('作者:')]

            # 合并标签（作者标签 + 新的自定义标签）
            final_tags = author_tags + [t for t in tags_list if not t.startswith('作者:')]

            # 解析领域 JSON，并将人工选择与自动分类结果分开持久化。
            # 服务器重启后可以重新运行分类器，但不会再覆盖人工添加/移除的领域。
            requested_domains = json.loads(domains) if domains else []
            domains_list, manual_domains, excluded_domains = domain_assignment_state(
                (row["title"] or "") + " " + (row["content"] or ""),
                selected_domains=requested_domains,
            )
            classification = conn.execute(
                "SELECT auto_domains_json,content_hash FROM domain_classification_jobs WHERE article_id=?",
                (article_id,),
            ).fetchone()
            if classification and classification["content_hash"]:
                auto_roots = domain_taxonomy_module._items(classification["auto_domains_json"])
                domains_list = list(dict.fromkeys(requested_domains))
                manual_domains = [name for name in domains_list if name not in auto_roots]
                excluded_domains = [name for name in auto_roots if name not in domains_list]

            # 更新文章标签
            conn.execute(
                """UPDATE articles
               SET tags=?, domains=?, manual_domains=?, excluded_auto_domains=?
               WHERE id=?""",
                (
                    json.dumps(final_tags, ensure_ascii=False),
                    json.dumps(domains_list, ensure_ascii=False),
                    json.dumps(manual_domains, ensure_ascii=False),
                    json.dumps(excluded_domains, ensure_ascii=False),
                    article_id,
                )
            )
            for child in conn.execute("""SELECT child.id,root.name AS parent_name FROM domain_taxonomy child
                                     JOIN domain_taxonomy root ON root.id=child.parent_id"""):
                if child["parent_name"] not in domains_list:
                    conn.execute("UPDATE article_subcategory_choices SET mode='excluded' WHERE article_id=? AND subcategory_id=?",
                                 (article_id, child["id"]))

            # ── 将用户本次新输入的标签同步到自定义库（tag_groups 表）──
            # new_tags 仅包含用户在编辑标签弹窗中手动输入的新标签，不含系统自动标签
            if new_tags:
                new_tags_list = [t for t in json.loads(new_tags) if t and not t.startswith('作者:')]
                if new_tags_list:
                    # 获取第一个二级目录（sort_order 最小）
                    default_cat = conn.execute(
                        "SELECT id FROM tag_categories ORDER BY sort_order ASC, id ASC LIMIT 1"
                    ).fetchone()
                    if default_cat:
                        default_cat_id = default_cat["id"]
                        now_ts = datetime.datetime.now().isoformat()
                        purged_tag_names = _get_purged_tag_names(conn)
                        for tag_name in new_tags_list:
                            # 该标签名在 tag_groups 任意目录下均不存在时才插入
                            exists = conn.execute(
                                "SELECT id FROM tag_groups WHERE name = ?", (tag_name,)
                            ).fetchone()
                            if not exists:
                                purged_tag_names.discard(tag_name)
                                max_order = conn.execute(
                                    "SELECT MAX(sort_order) FROM tag_groups WHERE category_id = ?",
                                    (default_cat_id,)
                                ).fetchone()[0]
                                conn.execute(
                                    "INSERT INTO tag_groups (name, category_id, sort_order, created_at) VALUES (?, ?, ?, ?)",
                                    (tag_name, default_cat_id, (max_order or 0) + 1, now_ts)
                                )
                        _set_purged_tag_names(conn, purged_tag_names)

            conn.commit()
            conn.close()

            return {"success": True, "tags": final_tags, "domains": domains_list}
        except json.JSONDecodeError:
            conn.close()
            raise HTTPException(status_code=400, detail="标签或领域格式错误")
        except Exception as e:
            conn.close()
            raise HTTPException(status_code=500, detail=f"更新标签失败: {str(e)}")


    @router.post("/api/articles/bulk/tags")
    def bulk_add_article_tags(body: BulkArticleTagsUpdate):
        """为多篇文章追加自定义标签，保留各文章已有标签。"""
        article_ids = list(dict.fromkeys(article_id for article_id in body.article_ids if article_id > 0))
        tags = list(dict.fromkeys(tag.strip() for tag in body.tags if tag.strip()))

        if not article_ids:
            raise HTTPException(status_code=400, detail="请至少选择一篇文章")
        if not tags:
            raise HTTPException(status_code=400, detail="请至少添加一个标签")
        if any(tag.startswith("作者:") for tag in tags):
            raise HTTPException(status_code=400, detail="作者标签由系统自动生成，不能手动添加")
        if len(tags) > 50 or any(len(tag) > 100 for tag in tags):
            raise HTTPException(status_code=400, detail="单次最多添加50个标签，且每个标签不超过100个字符")

        conn = get_db()
        try:
            updated = 0
            unchanged = 0
            missing_ids = []
            for article_id in article_ids:
                article = conn.execute("SELECT tags FROM articles WHERE id = ?", (article_id,)).fetchone()
                if not article:
                    missing_ids.append(article_id)
                    continue
                existing_tags = json.loads(article["tags"] or "[]")
                final_tags = existing_tags + [tag for tag in tags if tag not in existing_tags]
                if final_tags == existing_tags:
                    unchanged += 1
                    continue
                conn.execute(
                    "UPDATE articles SET tags = ? WHERE id = ?",
                    (json.dumps(final_tags, ensure_ascii=False), article_id),
                )
                updated += 1

            # 新输入的标签同时登记到自定义标签库，方便后续筛选和复用。
            default_cat = conn.execute(
                "SELECT id FROM tag_categories ORDER BY sort_order ASC, id ASC LIMIT 1"
            ).fetchone()
            if default_cat:
                default_cat_id = default_cat["id"]
                max_order = conn.execute(
                    "SELECT MAX(sort_order) FROM tag_groups WHERE category_id = ?", (default_cat_id,)
                ).fetchone()[0] or 0
                now_ts = datetime.datetime.now().isoformat()
                next_order = max_order + 1
                purged_tag_names = _get_purged_tag_names(conn)
                for tag in tags:
                    exists = conn.execute("SELECT id FROM tag_groups WHERE name = ?", (tag,)).fetchone()
                    if not exists:
                        purged_tag_names.discard(tag)
                        conn.execute(
                            "INSERT INTO tag_groups (name, category_id, sort_order, created_at) VALUES (?, ?, ?, ?)",
                            (tag, default_cat_id, next_order, now_ts),
                        )
                        next_order += 1
                _set_purged_tag_names(conn, purged_tag_names)

            conn.commit()
            return {
                "success": True,
                "updated_articles": updated,
                "unchanged_articles": unchanged,
                "missing_article_ids": missing_ids,
                "tags": tags,
            }
        except (json.JSONDecodeError, TypeError):
            conn.rollback()
            raise HTTPException(status_code=500, detail="部分文章的标签数据格式错误")
        except HTTPException:
            conn.rollback()
            raise
        except Exception as e:
            conn.rollback()
            raise HTTPException(status_code=500, detail=f"批量添加标签失败: {str(e)}")
        finally:
            conn.close()


    @router.put("/api/articles/{article_id}/subcategories")
    def update_article_subcategories(article_id: int, payload: dict = Body(...)):
        selected = payload.get("ids")
        if not isinstance(selected, list) or any(not isinstance(value, int) for value in selected):
            raise HTTPException(status_code=400, detail="子分类 ID 格式不正确")
        conn = get_db()
        try:
            article = conn.execute("SELECT domains,manual_domains FROM articles WHERE id=?", (article_id,)).fetchone()
            if not article:
                raise HTTPException(status_code=404, detail="文章不存在")
            rows = conn.execute("""SELECT child.id,root.name AS parent_name FROM domain_taxonomy child
                               JOIN domain_taxonomy root ON root.id=child.parent_id""").fetchall()
            valid = {row["id"]: row["parent_name"] for row in rows}
            if any(value not in valid for value in selected):
                raise HTTPException(status_code=400, detail="子分类不存在")
            selected_set = set(selected)
            existing = {row["subcategory_id"] for row in conn.execute(
                "SELECT subcategory_id FROM article_subcategory_choices WHERE article_id=?", (article_id,)
            )}
            for child_id in existing | selected_set:
                conn.execute("""INSERT INTO article_subcategory_choices(article_id,subcategory_id,mode)
                            VALUES (?,?,?) ON CONFLICT(article_id,subcategory_id) DO UPDATE SET mode=excluded.mode""",
                             (article_id, child_id, "manual" if child_id in selected_set else "excluded"))
            domains = domain_taxonomy_module._items(article["domains"])
            manual = domain_taxonomy_module._items(article["manual_domains"])
            for child_id in selected_set:
                parent_name = valid[child_id]
                if parent_name not in domains:
                    domains.append(parent_name)
                if parent_name not in manual:
                    manual.append(parent_name)
            conn.execute("UPDATE articles SET domains=?,manual_domains=? WHERE id=?",
                         (json.dumps(domains, ensure_ascii=False), json.dumps(manual, ensure_ascii=False), article_id))
            conn.commit()
            return {"ids": selected, "domains": domains}
        finally:
            conn.close()

    return router
