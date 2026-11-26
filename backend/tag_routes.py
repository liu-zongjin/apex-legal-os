"""Routes for the article library's custom tag directory and editor."""

import datetime
import json
import sqlite3
from typing import Callable, List, Optional

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

from . import domain_taxonomy as domain_taxonomy_module
from .article_metadata import _get_purged_tag_names, _set_purged_tag_names


class TagCategoryCreate(BaseModel):
    name: str


class TagCategoryRename(BaseModel):
    name: str


class TagCategoryReorder(BaseModel):
    ids: List[int]


class TagGroupCreate(BaseModel):
    name: str
    category_id: Optional[int] = None  # 不传则放到默认二级目录


class TagGroupRename(BaseModel):
    name: str


class TagGroupReorder(BaseModel):
    ids: List[int]
    category_id: Optional[int] = None


class TagGroupMove(BaseModel):
    category_id: int  # 目标二级目录


def create_router(get_db: Callable[[], sqlite3.Connection]) -> APIRouter:
    router = APIRouter()

    @router.get("/api/tags/custom")
    def get_custom_tags():
        """获取所有自定义标签及文章数量（排除作者标签）"""
        conn = get_db()
        rows = conn.execute("SELECT tags FROM articles").fetchall()
        conn.close()
        tag_count = {}
        for row in rows:
            tags = json.loads(row["tags"] or "[]")
            for tag in set(tags):
                if not tag.startswith("作者:"):
                    tag_count[tag] = tag_count.get(tag, 0) + 1
        result = [{"tag": k, "count": v} for k, v in sorted(tag_count.items(), key=lambda x: -x[1])]
        return result

    @router.post("/api/tag-editor/save")
    def save_tag_editor(body: dict = Body(...)):
        """原子保存标签管理页的排序、重命名及领域/作者变更。"""
        conn = get_db()
        try:
            categories_payload = body.get("categories")
            facets_payload = body.get("facets")
            if not isinstance(categories_payload, list) or not isinstance(facets_payload, dict):
                raise HTTPException(status_code=400, detail="标签管理数据格式不正确")

            category_rows = conn.execute(
                "SELECT id, name FROM tag_categories ORDER BY id"
            ).fetchall()
            category_by_id = {int(row["id"]): row for row in category_rows}
            if len(categories_payload) != len(category_by_id):
                raise HTTPException(status_code=409, detail="标签组已发生变化，请刷新后重试")

            category_updates = []
            category_ids = []
            category_names = set()
            tag_updates = []
            tag_ids = []
            tag_names = set()
            tag_renames = {}

            for category in categories_payload:
                if not isinstance(category, dict):
                    raise HTTPException(status_code=400, detail="标签组数据格式不正确")
                category_id = category.get("id")
                if isinstance(category_id, bool) or not isinstance(category_id, int):
                    raise HTTPException(status_code=400, detail="标签组编号不正确")
                current_category = category_by_id.get(category_id)
                if not current_category or category_id in category_ids:
                    raise HTTPException(status_code=409, detail="标签组已发生变化，请刷新后重试")
                name = str(category.get("name") or "").strip()
                if not name:
                    raise HTTPException(status_code=400, detail="标签组名称不能为空")
                if name in category_names:
                    raise HTTPException(status_code=409, detail="标签组名称不能重复")
                category_names.add(name)
                category_ids.append(category_id)
                category_updates.append((category_id, current_category["name"], name))

                tags = category.get("tags")
                if not isinstance(tags, list):
                    raise HTTPException(status_code=400, detail="标签数据格式不正确")
                for tag in tags:
                    if not isinstance(tag, dict):
                        raise HTTPException(status_code=400, detail="标签数据格式不正确")
                    tag_id = tag.get("id")
                    if isinstance(tag_id, bool) or not isinstance(tag_id, int):
                        raise HTTPException(status_code=400, detail="标签编号不正确")
                    tag_row = conn.execute(
                        "SELECT id, name, category_id FROM tag_groups WHERE id = ?",
                        (tag_id,),
                    ).fetchone()
                    if not tag_row or int(tag_row["category_id"]) != category_id or tag_id in tag_ids:
                        raise HTTPException(status_code=409, detail="标签已发生变化，请刷新后重试")
                    tag_name = str(tag.get("name") or "").strip()
                    if not tag_name:
                        raise HTTPException(status_code=400, detail="标签名称不能为空")
                    if tag_name in tag_names:
                        raise HTTPException(status_code=409, detail="标签名称不能重复")
                    tag_names.add(tag_name)
                    tag_ids.append(tag_id)
                    tag_updates.append((tag_id, tag_row["name"], tag_name, category_id))
                    if tag_row["name"] != tag_name:
                        tag_renames[tag_row["name"]] = tag_name

            if set(category_ids) != set(category_by_id):
                raise HTTPException(status_code=409, detail="标签组已发生变化，请刷新后重试")
            all_category_names = {row["name"] for row in category_rows}
            for _, old_name, new_name in category_updates:
                if new_name != old_name and new_name in all_category_names:
                    raise HTTPException(status_code=409, detail="不能直接改为其他现有标签组名称，请先分步修改")

            tag_rows = conn.execute("SELECT id, name, category_id FROM tag_groups").fetchall()
            tag_by_id = {int(row["id"]): row for row in tag_rows}
            if set(tag_ids) != set(tag_by_id):
                raise HTTPException(status_code=409, detail="标签已发生变化，请刷新后重试")
            all_tag_names = {row["name"] for row in tag_rows}
            for tag_id, old_name, new_name, _ in tag_updates:
                if new_name != old_name and new_name in all_tag_names:
                    raise HTTPException(status_code=409, detail="不能直接改为其他现有标签名称，请先分步修改")

            facet_changes = {}
            facet_renames = {}
            facet_deletes = {}
            for kind in ("domain", "author"):
                section = facets_payload.get(kind)
                if not isinstance(section, dict):
                    raise HTTPException(status_code=400, detail="专业领域或作者数据格式不正确")
                facet_rows = section.get("rows")
                deletes = section.get("deletes")
                if not isinstance(facet_rows, list) or not isinstance(deletes, list):
                    raise HTTPException(status_code=400, detail="专业领域或作者数据格式不正确")

                article_rows = conn.execute("SELECT domains, tags FROM articles").fetchall()
                if kind == "domain":
                    existing_names = {
                        value
                        for row in article_rows
                        for value in json.loads(row["domains"] or "[]")
                    }
                else:
                    existing_names = {
                        tag.replace("作者:", "", 1)
                        for row in article_rows
                        for tag in set(json.loads(row["tags"] or "[]"))
                        if tag.startswith("作者:")
                    }

                seen_originals = set()
                seen_names = set()
                rows_for_kind = []
                renames_for_kind = {}
                for item in facet_rows:
                    if not isinstance(item, dict):
                        raise HTTPException(status_code=400, detail="专业领域或作者数据格式不正确")
                    old_name = str(item.get("original") or "").strip()
                    new_name = str(item.get("name") or "").strip()
                    if not old_name or not new_name:
                        raise HTTPException(status_code=400, detail="专业领域或作者名称不能为空")
                    if old_name not in existing_names or old_name in seen_originals:
                        raise HTTPException(status_code=409, detail="专业领域或作者已发生变化，请刷新后重试")
                    if new_name in seen_names:
                        raise HTTPException(status_code=409, detail="专业领域或作者名称不能重复")
                    if new_name != old_name and new_name in existing_names:
                        raise HTTPException(status_code=409, detail="不能直接改为其他现有名称，请先分步修改")
                    seen_originals.add(old_name)
                    seen_names.add(new_name)
                    rows_for_kind.append({"original": old_name, "name": new_name})
                    if old_name != new_name:
                        renames_for_kind[old_name] = new_name

                delete_names = {str(name or "").strip() for name in deletes}
                if "" in delete_names or len(delete_names) != len(deletes):
                    raise HTTPException(status_code=400, detail="待删除名称不正确")
                if not delete_names.isdisjoint(seen_originals) or not delete_names.issubset(existing_names):
                    raise HTTPException(status_code=409, detail="专业领域或作者已发生变化，请刷新后重试")
                if seen_originals | delete_names != existing_names:
                    raise HTTPException(status_code=409, detail="专业领域或作者已发生变化，请刷新后重试")

                facet_changes[kind] = rows_for_kind + [{"original": name, "deleted": True} for name in sorted(delete_names)]
                facet_renames[kind] = renames_for_kind
                facet_deletes[kind] = delete_names

            # 先完成名称更新，再写入顺序；所有操作仍处于同一个事务中。
            for category_id, _, name in category_updates:
                conn.execute("UPDATE tag_categories SET name = ? WHERE id = ?", (name, category_id))
            for sort_order, category_id in enumerate(category_ids):
                conn.execute("UPDATE tag_categories SET sort_order = ? WHERE id = ?", (sort_order, category_id))

            for tag_id, _, name, _ in tag_updates:
                conn.execute("UPDATE tag_groups SET name = ? WHERE id = ?", (name, tag_id))
            for category in categories_payload:
                for tag_sort_order, tag in enumerate(category["tags"]):
                    conn.execute(
                        "UPDATE tag_groups SET sort_order = ? WHERE id = ?",
                        (tag_sort_order, tag["id"]),
                    )

            if tag_renames:
                articles = conn.execute("SELECT id, tags FROM articles").fetchall()
                for article in articles:
                    tags = json.loads(article["tags"] or "[]")
                    merged = []
                    for tag in tags:
                        value = tag_renames.get(tag, tag)
                        if value not in merged:
                            merged.append(value)
                    if merged != tags:
                        conn.execute(
                            "UPDATE articles SET tags = ? WHERE id = ?",
                            (json.dumps(merged, ensure_ascii=False), article["id"]),
                        )

            if facet_renames["domain"] or facet_deletes["domain"]:
                articles = conn.execute("SELECT id, domains FROM articles").fetchall()
                for article in articles:
                    domains = json.loads(article["domains"] or "[]")
                    merged = []
                    for domain in domains:
                        if domain in facet_deletes["domain"]:
                            continue
                        value = facet_renames["domain"].get(domain, domain)
                        if value not in merged:
                            merged.append(value)
                    if merged != domains:
                        conn.execute(
                            "UPDATE articles SET domains = ? WHERE id = ?",
                            (json.dumps(merged, ensure_ascii=False), article["id"]),
                        )
                for old_name, new_name in facet_renames["domain"].items():
                    conn.execute("UPDATE domain_taxonomy SET name=? WHERE name=? AND parent_id IS NULL", (new_name, old_name))
                    conn.execute("INSERT OR IGNORE INTO domain_taxonomy_suppressed_roots(name) VALUES (?)", (old_name,))
                    conn.execute("DELETE FROM domain_taxonomy_suppressed_roots WHERE name=?", (new_name,))
                for name in facet_deletes["domain"]:
                    conn.execute("DELETE FROM domain_taxonomy WHERE name=? AND parent_id IS NULL", (name,))
                    conn.execute("INSERT OR IGNORE INTO domain_taxonomy_suppressed_roots(name) VALUES (?)", (name,))
                domain_taxonomy_module.update_job_domain_names(conn, facet_renames["domain"], facet_deletes["domain"])
                for column in ("manual_domains", "excluded_auto_domains"):
                    for article in conn.execute(f"SELECT id,{column} FROM articles"):
                        values = domain_taxonomy_module._items(article[column])
                        changed = [facet_renames["domain"].get(value, value) for value in values if value not in facet_deletes["domain"]]
                        if changed != values:
                            conn.execute(f"UPDATE articles SET {column}=? WHERE id=?", (json.dumps(changed, ensure_ascii=False), article["id"]))

            if facet_renames["author"] or facet_deletes["author"]:
                articles = conn.execute("SELECT id, tags FROM articles").fetchall()
                for article in articles:
                    tags = json.loads(article["tags"] or "[]")
                    merged = []
                    for tag in tags:
                        if tag.startswith("作者:"):
                            author = tag.replace("作者:", "", 1)
                            if author in facet_deletes["author"]:
                                continue
                            if author in facet_renames["author"]:
                                tag = f"作者:{facet_renames['author'][author]}"
                        if tag not in merged:
                            merged.append(tag)
                    if merged != tags:
                        conn.execute(
                            "UPDATE articles SET tags = ? WHERE id = ?",
                            (json.dumps(merged, ensure_ascii=False), article["id"]),
                        )

            conn.commit()
            return {"ok": True, "facet_changes": facet_changes}
        except HTTPException:
            conn.rollback()
            raise
        except sqlite3.IntegrityError:
            conn.rollback()
            raise HTTPException(status_code=409, detail="标签名称冲突，请刷新后重试")
        except Exception:
            conn.rollback()
            raise HTTPException(status_code=500, detail="保存标签管理变更失败")
        finally:
            conn.close()

    @router.get("/api/tag-categories")
    def get_tag_categories():
        """获取所有二级目录（含其下的三级标签列表），自动发现并注册孤儿标签"""
        conn = get_db()
        cats = conn.execute(
            "SELECT id, name, sort_order FROM tag_categories ORDER BY sort_order ASC, id ASC"
        ).fetchall()
        # 统计每个标签对应的文章数
        rows = conn.execute("SELECT id, tags FROM articles").fetchall()
        tag_count: dict = {}
        for row in rows:
            for t in set(json.loads(row["tags"] or "[]")):
                if not t.startswith("作者:") and not domain_taxonomy_module.is_source_label(t[3:] if t.startswith("来源:") else t):
                    tag_count[t] = tag_count.get(t, 0) + 1
        purged_tag_names = _get_purged_tag_names(conn)

        # ── 自动发现孤儿标签（在 articles.tags 中但不在 tag_groups 表中）──
        all_tag_names_in_db = set()
        for cat in cats:
            tags = conn.execute(
                "SELECT id, name, sort_order FROM tag_groups WHERE category_id = ? ORDER BY sort_order ASC, id ASC",
                (cat["id"],)
            ).fetchall()
            for t in tags:
                all_tag_names_in_db.add(t["name"])

        orphan_tags = [
            name for name in tag_count
            if name not in all_tag_names_in_db and name not in purged_tag_names
        ]

        # 把孤儿标签注册到"待定义标签"目录（cat_id=11），避免每次都重新发现
        if orphan_tags:
            default_cat = conn.execute("SELECT id FROM tag_categories WHERE id = 11").fetchone()
            if default_cat:
                # 一次性查出当前最大 sort_order（避免在游标活跃时写入）
                max_sort = (conn.execute(
                    "SELECT MAX(sort_order) FROM tag_groups WHERE category_id = 11"
                ).fetchone()[0] or 0)
                # 一次性查出所有已有标签名
                existing = {r["name"] for r in conn.execute("SELECT name FROM tag_groups").fetchall()}
                to_insert = [name for name in orphan_tags if name not in existing]
                for idx, name in enumerate(to_insert):
                    conn.execute(
                        "INSERT INTO tag_groups (name, category_id, sort_order, created_at) VALUES (?, 11, ?, ?)",
                        (name, max_sort + idx + 1, datetime.datetime.now().isoformat())
                    )
                conn.commit()

        result = []
        for cat in cats:
            tags = conn.execute(
                "SELECT id, name, sort_order FROM tag_groups WHERE category_id = ? ORDER BY sort_order ASC, id ASC",
                (cat["id"],)
            ).fetchall()
            tag_list = [{"id": t["id"], "name": t["name"], "sort_order": t["sort_order"], "count": tag_count.get(t["name"], 0)}
                        for t in tags if not domain_taxonomy_module.is_source_label(t["name"][3:] if t["name"].startswith("来源:") else t["name"])]
            tag_names = {item["name"] for item in tag_list}
            cat_count = sum(
                1 for row in rows
                if tag_names.intersection(
                    tag for tag in json.loads(row["tags"] or "[]") if not tag.startswith("作者:")
                )
            )
            result.append({
                "id": cat["id"],
                "name": cat["name"],
                "sort_order": cat["sort_order"],
                "tags": tag_list,
                "count": cat_count,  # 该二级目录下所有标签的文章总数（去重）
            })
        conn.close()
        return result

    @router.post("/api/tag-categories")
    def create_tag_category(body: TagCategoryCreate):
        """新建二级目录"""
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="名称不能为空")
        conn = get_db()
        if conn.execute("SELECT id FROM tag_categories WHERE name = ?", (name,)).fetchone():
            conn.close()
            raise HTTPException(status_code=409, detail="同名二级目录已存在")
        max_order = conn.execute("SELECT MAX(sort_order) FROM tag_categories").fetchone()[0]
        now = datetime.datetime.now().isoformat()
        conn.execute("INSERT INTO tag_categories (name, sort_order, created_at) VALUES (?, ?, ?)",
                     (name, (max_order or 0) + 1, now))
        conn.commit()
        new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        return {"id": new_id, "name": name, "tags": [], "count": 0}

    @router.put("/api/tag-categories/{cat_id}/rename")
    def rename_tag_category(cat_id: int, body: TagCategoryRename):
        """重命名二级目录"""
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="名称不能为空")
        conn = get_db()
        cat = conn.execute("SELECT id FROM tag_categories WHERE id = ?", (cat_id,)).fetchone()
        if not cat:
            conn.close()
            raise HTTPException(status_code=404, detail="二级目录不存在")
        if conn.execute("SELECT id FROM tag_categories WHERE name = ? AND id != ?", (name, cat_id)).fetchone():
            conn.close()
            raise HTTPException(status_code=409, detail="同名二级目录已存在")
        conn.execute("UPDATE tag_categories SET name = ? WHERE id = ?", (name, cat_id))
        conn.commit()
        conn.close()
        return {"ok": True}

    @router.delete("/api/tag-categories/{cat_id}")
    def delete_tag_category(cat_id: int):
        """删除二级目录（同时删除其下所有三级标签及文章关联）"""
        conn = get_db()
        cat = conn.execute("SELECT name FROM tag_categories WHERE id = ?", (cat_id,)).fetchone()
        if not cat:
            conn.close()
            raise HTTPException(status_code=404, detail="二级目录不存在")
        # 找到该二级目录下所有标签
        tags_in_cat = conn.execute("SELECT name FROM tag_groups WHERE category_id = ?", (cat_id,)).fetchall()
        tag_names = {r["name"] for r in tags_in_cat}
        # 从所有文章中移除这些标签
        articles = conn.execute("SELECT id, tags FROM articles").fetchall()
        for art in articles:
            tags = json.loads(art["tags"] or "[]")
            new_tags = [t for t in tags if t not in tag_names]
            if len(new_tags) != len(tags):
                conn.execute("UPDATE articles SET tags = ? WHERE id = ?",
                             (json.dumps(new_tags, ensure_ascii=False), art["id"]))
        conn.execute("DELETE FROM tag_groups WHERE category_id = ?", (cat_id,))
        conn.execute("DELETE FROM tag_categories WHERE id = ?", (cat_id,))
        conn.commit()
        conn.close()
        return {"ok": True}

    @router.post("/api/tag-categories/reorder")
    def reorder_tag_categories(body: TagCategoryReorder):
        conn = get_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = {row[0] for row in conn.execute("SELECT id FROM tag_categories")}
            if len(body.ids) != len(existing) or set(body.ids) != existing:
                raise HTTPException(status_code=409, detail="标签组已发生变化，请刷新后重试")
            for idx, cid in enumerate(body.ids):
                conn.execute("UPDATE tag_categories SET sort_order=? WHERE id=?", (idx, cid))
            conn.commit()
            return {"ok": True}
        finally:
            conn.close()

    @router.get("/api/tag-groups")
    def get_tag_groups():
        """兼容旧接口：返回所有三级标签（平铺），每个含 category_id"""
        conn = get_db()
        groups = conn.execute(
            "SELECT id, name, category_id, sort_order FROM tag_groups ORDER BY category_id ASC, sort_order ASC, id ASC"
        ).fetchall()
        rows = conn.execute("SELECT tags FROM articles").fetchall()
        conn.close()
        tag_count = {}
        for row in rows:
            for t in set(json.loads(row["tags"] or "[]")):
                if not t.startswith("作者:"):
                    tag_count[t] = tag_count.get(t, 0) + 1
        return [{"id": g["id"], "name": g["name"], "category_id": g["category_id"],
                 "sort_order": g["sort_order"], "count": tag_count.get(g["name"], 0)} for g in groups]

    @router.get("/api/tag-groups/suggestions")
    def get_tag_suggestions(q: str = ""):
        """根据关键字返回匹配的既有标签名称列表（用于输入框自动补全）"""
        q = q.strip()
        conn = get_db()
        # 从 tag_groups 表中匹配
        rows = conn.execute(
            "SELECT DISTINCT name FROM tag_groups WHERE name LIKE ? ORDER BY name LIMIT 20",
            (f"%{q}%",)
        ).fetchall()
        conn.close()
        names = [r["name"] for r in rows]
        return {"suggestions": names}

    @router.post("/api/tag-groups")
    def create_tag_group(body: TagGroupCreate):
        """新建三级标签"""
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="标签名称不能为空")
        conn = get_db()
        # 默认二级目录（取 sort_order 最小的）
        if body.category_id:
            cat_id = body.category_id
        else:
            default = conn.execute("SELECT id FROM tag_categories ORDER BY sort_order, id LIMIT 1").fetchone()
            cat_id = default["id"] if default else 1
        if conn.execute("SELECT id FROM tag_groups WHERE name = ?", (name,)).fetchone():
            conn.close()
            raise HTTPException(status_code=409, detail="同名标签已存在")
        purged_tag_names = _get_purged_tag_names(conn)
        if name in purged_tag_names:
            purged_tag_names.remove(name)
            _set_purged_tag_names(conn, purged_tag_names)
        max_order = conn.execute("SELECT MAX(sort_order) FROM tag_groups WHERE category_id = ?", (cat_id,)).fetchone()[0]
        now = datetime.datetime.now().isoformat()
        conn.execute("INSERT INTO tag_groups (name, category_id, sort_order, created_at) VALUES (?, ?, ?, ?)",
                     (name, cat_id, (max_order or 0) + 1, now))
        conn.commit()
        new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        return {"id": new_id, "name": name, "category_id": cat_id, "count": 0}

    @router.put("/api/tag-groups/{group_id}/rename")
    def rename_tag_group(group_id: int, body: TagGroupRename):
        """重命名三级标签，并同步更新所有关联文章的标签"""
        new_name = body.name.strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="标签名称不能为空")
        conn = get_db()
        group = conn.execute("SELECT name, category_id FROM tag_groups WHERE id = ?", (group_id,)).fetchone()
        if not group:
            conn.close()
            raise HTTPException(status_code=404, detail="标签不存在")
        old_name = group["name"]
        cat_id = group["category_id"]
        if old_name == new_name:
            conn.close()
            return {"ok": True}
        if conn.execute("SELECT id FROM tag_groups WHERE name = ? AND id != ?",
                        (new_name, group_id)).fetchone():
            conn.close()
            raise HTTPException(status_code=409, detail="同名标签已存在")
        conn.execute("UPDATE tag_groups SET name = ? WHERE id = ?", (new_name, group_id))
        articles = conn.execute("SELECT id, tags FROM articles").fetchall()
        updated = 0
        for art in articles:
            tags = json.loads(art["tags"] or "[]")
            if old_name in tags:
                tags = [new_name if t == old_name else t for t in tags]
                conn.execute("UPDATE articles SET tags = ? WHERE id = ?",
                             (json.dumps(tags, ensure_ascii=False), art["id"]))
                updated += 1
        conn.commit()
        conn.close()
        return {"ok": True, "updated_articles": updated}

    @router.delete("/api/tag-groups/{group_id}")
    def delete_tag_group(group_id: int):
        """删除三级标签，同时从所有文章中移除该标签"""
        conn = get_db()
        group = conn.execute("SELECT name FROM tag_groups WHERE id = ?", (group_id,)).fetchone()
        if not group:
            conn.close()
            raise HTTPException(status_code=404, detail="标签不存在")
        name = group["name"]
        articles = conn.execute("SELECT id, tags FROM articles").fetchall()
        for art in articles:
            tags = json.loads(art["tags"] or "[]")
            if name in tags:
                tags = [t for t in tags if t != name]
                conn.execute("UPDATE articles SET tags = ? WHERE id = ?",
                             (json.dumps(tags, ensure_ascii=False), art["id"]))
        conn.execute("DELETE FROM tag_groups WHERE id = ?", (group_id,))
        purged_tag_names = _get_purged_tag_names(conn)
        if name in purged_tag_names:
            purged_tag_names.remove(name)
            _set_purged_tag_names(conn, purged_tag_names)
        conn.commit()
        conn.close()
        return {"ok": True}

    @router.delete("/api/tag-groups/{group_id}/purge")
    def purge_tag_group(group_id: int):
        """仅删除标签本身（从标签库中移除），不从文章中移除该标签"""
        conn = get_db()
        group = conn.execute("SELECT name FROM tag_groups WHERE id = ?", (group_id,)).fetchone()
        if not group:
            conn.close()
            raise HTTPException(status_code=404, detail="标签不存在")
        purged_tag_names = _get_purged_tag_names(conn)
        purged_tag_names.add(group["name"])
        conn.execute("DELETE FROM tag_groups WHERE id = ?", (group_id,))
        _set_purged_tag_names(conn, purged_tag_names)
        conn.commit()
        conn.close()
        return {"ok": True}

    @router.put("/api/tag-groups/{group_id}/move")
    def move_tag_group(group_id: int, body: TagGroupMove):
        """将三级标签移动到另一个二级目录"""
        conn = get_db()
        group = conn.execute("SELECT name FROM tag_groups WHERE id = ?", (group_id,)).fetchone()
        if not group:
            conn.close()
            raise HTTPException(status_code=404, detail="标签不存在")
        cat = conn.execute("SELECT id FROM tag_categories WHERE id = ?", (body.category_id,)).fetchone()
        if not cat:
            conn.close()
            raise HTTPException(status_code=404, detail="目标二级目录不存在")
        # 检查目标二级目录下是否有同名标签
        conflict = conn.execute("SELECT id FROM tag_groups WHERE name = ? AND category_id = ? AND id != ?",
                                (group["name"], body.category_id, group_id)).fetchone()
        if conflict:
            conn.close()
            raise HTTPException(status_code=409, detail="目标二级目录下已有同名标签")
        max_order = conn.execute("SELECT MAX(sort_order) FROM tag_groups WHERE category_id = ?",
                                 (body.category_id,)).fetchone()[0]
        conn.execute("UPDATE tag_groups SET category_id = ?, sort_order = ? WHERE id = ?",
                     (body.category_id, (max_order or 0) + 1, group_id))
        conn.commit()
        conn.close()
        return {"ok": True}

    @router.post("/api/tag-groups/reorder")
    def reorder_tag_groups(body: TagGroupReorder):
        conn = get_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            rows = [row for row in conn.execute("SELECT id,category_id,name FROM tag_groups")
                    if not domain_taxonomy_module.is_source_label(row["name"][3:] if row["name"].startswith("来源:") else row["name"])]
            parents = {row[1] for row in rows if row[0] in body.ids}
            parent = body.category_id
            if parent is None and len(parents) == 1:
                parent = next(iter(parents))
            if parent is not None and not conn.execute("SELECT 1 FROM tag_categories WHERE id=?", (parent,)).fetchone():
                raise HTTPException(status_code=409, detail="标签组已发生变化，请刷新后重试")
            existing = {row[0] for row in rows if parent is None or row[1] == parent}
            if len(body.ids) != len(existing) or set(body.ids) != existing:
                raise HTTPException(status_code=409, detail="标签已发生变化，请刷新后重试")
            for idx, gid in enumerate(body.ids):
                conn.execute("UPDATE tag_groups SET sort_order=? WHERE id=?", (idx, gid))
            conn.commit()
            return {"ok": True}
        finally:
            conn.close()

    @router.post("/api/tag-groups/{group_id}/add-article/{article_id}")
    def add_article_to_group(group_id: int, article_id: int):
        """将文章添加到指定三级标签（为文章加上该标签名）"""
        conn = get_db()
        group = conn.execute("SELECT name FROM tag_groups WHERE id = ?", (group_id,)).fetchone()
        if not group:
            conn.close()
            raise HTTPException(status_code=404, detail="标签不存在")
        tag_name = group["name"]
        article = conn.execute("SELECT tags FROM articles WHERE id = ?", (article_id,)).fetchone()
        if not article:
            conn.close()
            raise HTTPException(status_code=404, detail="文章不存在")
        tags = json.loads(article["tags"] or "[]")
        if tag_name not in tags:
            tags.append(tag_name)
            conn.execute("UPDATE articles SET tags = ? WHERE id = ?",
                         (json.dumps(tags, ensure_ascii=False), article_id))
            conn.commit()
        conn.close()
        return {"ok": True}

    @router.delete("/api/tag-groups/{group_id}/remove-article/{article_id}")
    def remove_article_from_group(group_id: int, article_id: int):
        """将文章从指定三级标签中移除"""
        conn = get_db()
        group = conn.execute("SELECT name FROM tag_groups WHERE id = ?", (group_id,)).fetchone()
        if not group:
            conn.close()
            raise HTTPException(status_code=404, detail="标签不存在")
        tag_name = group["name"]
        article = conn.execute("SELECT tags FROM articles WHERE id = ?", (article_id,)).fetchone()
        if not article:
            conn.close()
            raise HTTPException(status_code=404, detail="文章不存在")
        tags = json.loads(article["tags"] or "[]")
        if tag_name in tags:
            tags = [t for t in tags if t != tag_name]
            conn.execute("UPDATE articles SET tags = ? WHERE id = ?",
                         (json.dumps(tags, ensure_ascii=False), article_id))
            conn.commit()
        conn.close()
        return {"ok": True}

    return router
