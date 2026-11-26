"""Routes for the article library's professional domains and review queue."""

import datetime
import json
import re
import sqlite3
from typing import Callable, Iterable

from fastapi import APIRouter, Body, HTTPException, Query

from . import domain_taxonomy as domain_taxonomy_module


def create_router(
    get_db: Callable[[], sqlite3.Connection],
    *,
    legal_domains: Iterable[str],
    rule_domain_proposal: Callable[[sqlite3.Connection, sqlite3.Row], dict],
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/domains")
    def get_domains():
        """Return legacy fields plus the approved two-level taxonomy."""
        conn = get_db()
        try:
            domain_taxonomy_module.ensure_roots(conn, legal_domains)
            conn.commit()
            return domain_taxonomy_module.category_rows(conn)
        finally:
            conn.close()

    @router.get("/api/domains/pending-count")
    def get_pending_domain_count():
        conn = get_db()
        try:
            row = conn.execute("SELECT COUNT(*) FROM domain_classification_jobs WHERE status='needs_review'").fetchone()
            return {"count": row[0]}
        finally:
            conn.close()

    @router.post("/api/domains/categories")
    def create_domain_category(payload: dict = Body(...)):
        name = str(payload.get("name") or "").strip()
        parent_id = payload.get("parent_id")
        keywords = payload.get("keywords") or []
        if not 2 <= len(name) <= 40 or domain_taxonomy_module.is_source_label(name):
            raise HTTPException(status_code=400, detail="请输入有效的主题分类名称")
        if not isinstance(keywords, list) or any(not isinstance(word, str) for word in keywords) or len(keywords) > 8:
            raise HTTPException(status_code=400, detail="识别词最多8个")
        conn = get_db()
        try:
            if parent_id is not None:
                parent = conn.execute("SELECT id,parent_id FROM domain_taxonomy WHERE id=?", (parent_id,)).fetchone()
                if not parent or parent["parent_id"] is not None:
                    raise HTTPException(status_code=400, detail="二级分类只能建在专业领域下")
            siblings = conn.execute("SELECT name FROM domain_taxonomy WHERE parent_id IS ?", (parent_id,)).fetchall()
            normalize = lambda value: re.sub(r"(法|法律|纠纷|争议)$", "", value.strip())
            if any(normalize(row[0]) == normalize(name) for row in siblings):
                raise HTTPException(status_code=409, detail="已有相同或近义分类")
            cur = conn.execute(
                "INSERT INTO domain_taxonomy(name,parent_id,keywords_json,created_at) VALUES (?,?,?,?)",
                (name, parent_id, json.dumps([word.strip()[:30] for word in keywords if word.strip()], ensure_ascii=False), datetime.datetime.now().isoformat()),
            )
            if parent_id is not None:
                conn.execute("DELETE FROM domain_taxonomy_suppressed_children WHERE parent_id=? AND name=?", (parent_id, name))
            parent_name = conn.execute("SELECT name FROM domain_taxonomy WHERE id=?", (parent_id,)).fetchone()[0] if parent_id else None
            for article in conn.execute("SELECT id,domains FROM articles").fetchall():
                if parent_name is None or parent_name in domain_taxonomy_module._items(article["domains"]):
                    conn.execute("""INSERT INTO domain_classification_jobs(article_id,status,updated_at)
                                VALUES (?,'queued',?) ON CONFLICT(article_id) DO UPDATE SET status='queued',updated_at=excluded.updated_at""",
                                 (article["id"], datetime.datetime.now().isoformat()))
            conn.commit()
            return {"id": cur.lastrowid, "name": name, "parent_id": parent_id}
        finally:
            conn.close()

    @router.delete("/api/domains/categories/{category_id}")
    def delete_domain_subcategory(category_id: int):
        conn = get_db()
        try:
            child = conn.execute(
                "SELECT id,name,parent_id FROM domain_taxonomy WHERE id=?", (category_id,)
            ).fetchone()
            if child is None:
                raise HTTPException(status_code=404, detail="子分类不存在")
            if child["parent_id"] is None:
                raise HTTPException(status_code=400, detail="此处只能删除二级子分类")
            affected = conn.execute(
                "SELECT COUNT(*) FROM article_subcategory_choices WHERE subcategory_id=? AND mode<>'excluded'",
                (category_id,),
            ).fetchone()[0]
            conn.execute(
                "INSERT OR IGNORE INTO domain_taxonomy_suppressed_children(parent_id,name) VALUES (?,?)",
                (child["parent_id"], child["name"]),
            )
            conn.execute(
                "UPDATE domain_suggestions SET status='dismissed' WHERE parent_id=? AND name=? AND status='pending'",
                (child["parent_id"], child["name"]),
            )
            conn.execute("DELETE FROM domain_taxonomy WHERE id=?", (category_id,))
            conn.commit()
            return {"ok": True, "affected_articles": affected}
        finally:
            conn.close()

    @router.put("/api/domains/categories/{category_id}/rename")
    def rename_domain_subcategory(category_id: int, payload: dict = Body(...)):
        name = str(payload.get("name") or "").strip()
        if not 2 <= len(name) <= 40 or domain_taxonomy_module.is_source_label(name):
            raise HTTPException(status_code=400, detail="请输入有效的主题分类名称")
        conn = get_db()
        try:
            child = conn.execute("SELECT name,parent_id FROM domain_taxonomy WHERE id=?", (category_id,)).fetchone()
            if not child:
                raise HTTPException(status_code=404, detail="子分类不存在")
            if child["parent_id"] is None:
                raise HTTPException(status_code=400, detail="此处只能重命名二级子分类")
            normalize = lambda value: re.sub(r"(法|法律|纠纷|争议)$", "", value.strip())
            siblings = conn.execute("SELECT name FROM domain_taxonomy WHERE parent_id=? AND id<>?", (child["parent_id"], category_id))
            if any(normalize(row[0]) == normalize(name) for row in siblings):
                raise HTTPException(status_code=409, detail="已有相同或近义分类")
            if name != child["name"]:
                conn.execute("INSERT OR IGNORE INTO domain_taxonomy_suppressed_children(parent_id,name) VALUES (?,?)", (child["parent_id"], child["name"]))
                conn.execute("DELETE FROM domain_taxonomy_suppressed_children WHERE parent_id=? AND name=?", (child["parent_id"], name))
                conn.execute("UPDATE domain_suggestions SET status='dismissed' WHERE parent_id=? AND name=? AND status='pending'", (child["parent_id"], child["name"]))
                conn.execute("UPDATE domain_taxonomy SET name=? WHERE id=?", (name, category_id))
            conn.commit()
            return {"id": category_id, "name": name}
        finally:
            conn.close()

    @router.post("/api/domains/categories/reorder")
    def reorder_domain_subcategories(payload: dict = Body(...)):
        parent_id = payload.get("parent_id")
        ids = payload.get("ids")
        if not isinstance(parent_id, int) or not isinstance(ids, list) or any(not isinstance(value, int) for value in ids):
            raise HTTPException(status_code=400, detail="子分类顺序格式不正确")
        conn = get_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = [row[0] for row in conn.execute(
                "SELECT id FROM domain_taxonomy WHERE parent_id=? ORDER BY sort_order,id", (parent_id,)
            )]
            if not existing or len(ids) != len(existing) or set(ids) != set(existing):
                raise HTTPException(status_code=409, detail="子分类已发生变化，请刷新后重试")
            for index, child_id in enumerate(ids):
                conn.execute("UPDATE domain_taxonomy SET sort_order=? WHERE id=?", (index, child_id))
            conn.commit()
            return {"ids": ids}
        finally:
            conn.close()

    @router.get("/api/domains/suggestions")
    def list_domain_suggestions():
        conn = get_db()
        try:
            rows = conn.execute("""SELECT s.id,s.name,s.parent_id,s.keywords_json,s.article_id,s.created_at,
                                   p.name AS parent_name,a.title AS article_title,
                                   (SELECT COUNT(*) FROM domain_suggestion_articles e WHERE e.suggestion_id=s.id) AS support_count
                            FROM domain_suggestions s
                            LEFT JOIN domain_taxonomy p ON p.id=s.parent_id
                            LEFT JOIN articles a ON a.id=s.article_id
                            WHERE s.status='pending'
                              AND length(s.name)<=CASE WHEN s.parent_id IS NULL THEN 8 ELSE 12 END
                              AND (SELECT COUNT(*) FROM domain_suggestion_articles e WHERE e.suggestion_id=s.id)>=2
                            ORDER BY support_count DESC,s.id DESC LIMIT 100""").fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    @router.get("/api/domains/suggestions/page")
    def page_domain_suggestions(q: str = "", filter: str = "all", offset: int = Query(0, ge=0),
                                limit: int = Query(20, ge=1, le=50)):
        """Bounded review list for large historical classification batches."""
        if filter not in {"all", "supported", "roots"}:
            raise HTTPException(status_code=400, detail="建议筛选条件无效")
        conn = get_db()
        try:
            conditions = ["s.status='pending'",
                          "length(s.name)<=CASE WHEN s.parent_id IS NULL THEN 8 ELSE 12 END",
                          "(SELECT COUNT(*) FROM domain_suggestion_articles e WHERE e.suggestion_id=s.id)>=2"]
            params: list = []
            keyword = "".join(q.split())[:80]
            if keyword:
                conditions.append("(REPLACE(s.name,' ','') LIKE ? ESCAPE '\\' OR REPLACE(p.name,' ','') LIKE ? ESCAPE '\\')")
                escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                params.extend([f"%{escaped}%", f"%{escaped}%"])
            if filter == "roots":
                conditions.append("s.parent_id IS NULL")
            base = " FROM domain_suggestions s LEFT JOIN domain_taxonomy p ON p.id=s.parent_id WHERE " + " AND ".join(conditions)
            total = conn.execute("SELECT COUNT(*)" + base, params).fetchone()[0]
            rows = conn.execute("""SELECT s.id,s.name,s.parent_id,s.article_id,s.created_at,
                                p.name AS parent_name,a.title AS article_title,
                                (SELECT COUNT(*) FROM domain_suggestion_articles e WHERE e.suggestion_id=s.id) AS support_count"""
                                + base.replace(" WHERE ", " LEFT JOIN articles a ON a.id=s.article_id WHERE ", 1)
                                + " ORDER BY support_count DESC,s.id DESC LIMIT ? OFFSET ?", [*params, limit, offset]).fetchall()
            return {"total": total, "items": [dict(row) for row in rows], "has_more": offset + len(rows) < total}
        finally:
            conn.close()

    @router.get("/api/domains/discovery-status")
    def domain_discovery_status():
        conn = get_db()
        try:
            total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
            queued = conn.execute("SELECT COUNT(*) FROM domain_classification_jobs WHERE status='queued'").fetchone()[0]
            pending = conn.execute("""SELECT COUNT(*) FROM domain_suggestions s WHERE s.status='pending'
            AND length(s.name)<=CASE WHEN s.parent_id IS NULL THEN 8 ELSE 12 END
            AND (SELECT COUNT(*) FROM domain_suggestion_articles e WHERE e.suggestion_id=s.id)>=2""").fetchone()[0]
            return {"total": total, "queued": queued, "processed": total - queued, "pending_suggestions": pending}
        finally:
            conn.close()

    @router.post("/api/domains/discover")
    def restart_domain_discovery():
        """Explicitly retry content analysis after the user changes AI settings."""
        conn = get_db()
        try:
            conn.execute("""INSERT INTO domain_classification_jobs(article_id,status,updated_at)
                        SELECT id,'queued',datetime('now') FROM articles WHERE content IS NOT NULL
                        ON CONFLICT(article_id) DO UPDATE SET status='queued',updated_at=excluded.updated_at""")
            count = conn.execute("SELECT COUNT(*) FROM domain_classification_jobs WHERE status='queued'").fetchone()[0]
            conn.commit()
            return {"queued": count}
        finally:
            conn.close()

    @router.post("/api/domains/suggestions/{suggestion_id}/approve")
    def approve_domain_suggestion(suggestion_id: int):
        conn = get_db()
        try:
            row = conn.execute("SELECT * FROM domain_suggestions WHERE id=? AND status='pending'", (suggestion_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="建议不存在或已处理")
            support = conn.execute("SELECT COUNT(*) FROM domain_suggestion_articles WHERE suggestion_id=?", (suggestion_id,)).fetchone()[0]
            if support < 2 or len(row["name"]) > (8 if row["parent_id"] is None else 12):
                raise HTTPException(status_code=409, detail="分类建议需有至少两篇文章支持，且名称应为简明主题")
            siblings = conn.execute("SELECT id,name FROM domain_taxonomy WHERE parent_id IS ?", (row["parent_id"],)).fetchall()
            if any(item["name"] == row["name"] for item in siblings):
                raise HTTPException(status_code=409, detail="该分类已存在")
            node_id = conn.execute(
                "INSERT INTO domain_taxonomy(name,parent_id,keywords_json,created_at) VALUES (?,?,?,?)",
                (row["name"], row["parent_id"], row["keywords_json"], datetime.datetime.now().isoformat()),
            ).lastrowid
            conn.execute("UPDATE domain_suggestions SET status='approved' WHERE id=?", (suggestion_id,))
            # Re-evaluate affected articles against the newly accepted vocabulary.
            parent_name = None
            if row["parent_id"] is not None:
                parent = conn.execute("SELECT name FROM domain_taxonomy WHERE id=?", (row["parent_id"],)).fetchone()
                parent_name = parent[0] if parent else None
            affected = conn.execute("SELECT id,domains FROM articles").fetchall()
            for article in affected:
                if parent_name is None or parent_name in domain_taxonomy_module._items(article["domains"]):
                    conn.execute("""INSERT INTO domain_classification_jobs(article_id,status,updated_at)
                                VALUES (?,'queued',?) ON CONFLICT(article_id) DO UPDATE SET status='queued',updated_at=excluded.updated_at""",
                                 (article["id"], datetime.datetime.now().isoformat()))
            conn.commit()
            return {"id": node_id, "name": row["name"], "parent_id": row["parent_id"]}
        finally:
            conn.close()

    @router.post("/api/domains/suggestions/{suggestion_id}/dismiss")
    def dismiss_domain_suggestion(suggestion_id: int):
        conn = get_db()
        try:
            cur = conn.execute("UPDATE domain_suggestions SET status='dismissed' WHERE id=? AND status='pending'", (suggestion_id,))
            conn.commit()
            if not cur.rowcount:
                raise HTTPException(status_code=404, detail="建议不存在或已处理")
            return {"ok": True}
        finally:
            conn.close()

    def _domain_reclassification_diff(conn: sqlite3.Connection, article: sqlite3.Row, proposal: dict) -> dict:
        target = domain_taxonomy_module.classification_target(
            conn, article, proposal["domains"], proposal["subcategories"])
        existing = domain_taxonomy_module._items(article["domains"])
        current = {row["subcategory_id"] for row in conn.execute(
            "SELECT subcategory_id FROM article_subcategory_choices WHERE article_id=? AND mode<>'excluded'",
            (article["id"],)) if target["child_parents"].get(row["subcategory_id"]) in existing}
        labels = {row["id"]: row["name"] for row in conn.execute("SELECT id,name FROM domain_taxonomy")}
        added = sorted(target["children"] - current)
        removed = sorted(current - target["children"])
        add = [name for name in target["roots"] if name not in existing]
        remove = [name for name in existing if name not in target["roots"]]
        return {"add": add, "remove": remove, "proposed": target["roots"],
                "subcategory_add": [labels[cid] for cid in added],
                "subcategory_remove": [labels[cid] for cid in removed],
                "has_changes": bool(add or remove or added or removed)}

    @router.get("/api/domains/reclassify/preview")
    def preview_domain_reclassification(after_id: int = 0, limit: int = Query(50, ge=1, le=100)):
        conn = get_db()
        try:
            articles = conn.execute("""SELECT id,title,summary,content,domains,manual_domains,excluded_auto_domains
                                   FROM articles WHERE id>? ORDER BY id LIMIT ?""", (after_id, limit)).fetchall()
            changes = []
            for article in articles:
                proposal = rule_domain_proposal(conn, article)
                existing = domain_taxonomy_module._items(article["domains"])
                diff = _domain_reclassification_diff(conn, article, proposal)
                suggestions = proposal["suggestions"] + [dict(row) for row in conn.execute(
                    """SELECT s.id,s.name,s.parent_id FROM domain_suggestions s
                   JOIN domain_suggestion_articles e ON e.suggestion_id=s.id
                   WHERE e.article_id=? AND s.status='pending'""", (article["id"],),
                )]
                suggestions = list({(item["parent_id"], item["name"]): item for item in suggestions}.values())
                changes.append({"id": article["id"], "title": article["title"], "existing": existing,
                                **diff,
                                "subcategories": proposal["subcategories"], "suggestions": suggestions,
                                "needs_ai": proposal["needs_ai"]})
            return {"items": changes, "next_after_id": articles[-1]["id"] if articles else None}
        finally:
            conn.close()

    @router.post("/api/domains/reclassify/apply")
    def apply_domain_reclassification(payload: dict = Body(...)):
        after_id = max(0, int(payload.get("after_id") or 0))
        limit = min(100, max(1, int(payload.get("limit") or 50)))
        conn = get_db()
        try:
            articles = conn.execute("SELECT id,title,summary,content,domains,manual_domains,excluded_auto_domains FROM articles WHERE id>? ORDER BY id LIMIT ?",
                                    (after_id, limit)).fetchall()
            processed = 0
            for article in articles:
                proposal = rule_domain_proposal(conn, article)
                if not _domain_reclassification_diff(conn, article, proposal)["has_changes"]:
                    continue
                processed += 1
                for candidate in proposal["suggestions"]:
                    domain_taxonomy_module.suggest(conn, candidate["name"], candidate["parent_id"], article["id"],
                                                   candidate["keywords"])
                domain_taxonomy_module.apply_classification(
                    conn, article["id"], proposal["domains"], proposal["subcategories"],
                    status="queued" if proposal["needs_ai"] else "done",
                )
            conn.commit()
            return {"processed": processed, "scanned": len(articles), "next_after_id": articles[-1]["id"] if articles else None}
        finally:
            conn.close()

    @router.put("/api/domains/rename")
    def rename_domain(payload: dict = Body(...)):
        """重命名专业领域：同步更新所有文章，避免留下孤立标签。"""
        old = str(payload.get("old") or "").strip()
        new = str(payload.get("new") or "").strip()
        if not old or not new:
            raise HTTPException(status_code=400, detail="缺少旧名称或新名称")
        if old == new:
            return {"ok": True, "updated": 0}
        conn = get_db()
        updated = 0
        try:
            if conn.execute("SELECT 1 FROM domain_taxonomy WHERE parent_id IS NULL AND name=? AND name<>?", (new, old)).fetchone():
                raise HTTPException(status_code=409, detail="同名专业领域已存在")
            rows = conn.execute("SELECT id, domains FROM articles").fetchall()
            if any(new in set(json.loads(row["domains"] or "[]")) for row in rows):
                raise HTTPException(status_code=409, detail="同名专业领域已存在")
            for row in rows:
                domains = json.loads(row["domains"] or "[]")
                if old not in domains:
                    continue
                merged = []
                for item in domains:
                    value = new if item == old else item
                    if value not in merged:
                        merged.append(value)
                conn.execute(
                    "UPDATE articles SET domains=? WHERE id=?",
                    (json.dumps(merged, ensure_ascii=False), row["id"]),
                )
                updated += 1
            conn.execute("UPDATE domain_taxonomy SET name=? WHERE name=? AND parent_id IS NULL", (new, old))
            domain_taxonomy_module.update_job_domain_names(conn, {old: new}, set())
            conn.execute("INSERT OR IGNORE INTO domain_taxonomy_suppressed_roots(name) VALUES (?)", (old,))
            conn.execute("DELETE FROM domain_taxonomy_suppressed_roots WHERE name=?", (new,))
            for column in ("manual_domains", "excluded_auto_domains"):
                for article in conn.execute(f"SELECT id,{column} FROM articles"):
                    values = domain_taxonomy_module._items(article[column])
                    if old in values:
                        conn.execute(f"UPDATE articles SET {column}=? WHERE id=?",
                                     (json.dumps([new if value == old else value for value in values], ensure_ascii=False), article["id"]))
            conn.commit()
        finally:
            conn.close()
        return {"ok": True, "updated": updated}

    @router.delete("/api/domains/{name}")
    def delete_domain(name: str):
        """从所有文章中移除某个专业领域。"""
        target = str(name or "").strip()
        if not target:
            raise HTTPException(status_code=400, detail="缺少名称")
        conn = get_db()
        updated = 0
        try:
            rows = conn.execute("SELECT id, domains FROM articles").fetchall()
            for row in rows:
                domains = json.loads(row["domains"] or "[]")
                if target not in domains:
                    continue
                remaining = [item for item in domains if item != target]
                conn.execute(
                    "UPDATE articles SET domains=? WHERE id=?",
                    (json.dumps(remaining, ensure_ascii=False), row["id"]),
                )
                updated += 1
            conn.execute("DELETE FROM domain_taxonomy WHERE name=? AND parent_id IS NULL", (target,))
            domain_taxonomy_module.update_job_domain_names(conn, {}, {target})
            conn.execute("INSERT OR IGNORE INTO domain_taxonomy_suppressed_roots(name) VALUES (?)", (target,))
            for column in ("manual_domains", "excluded_auto_domains"):
                for article in conn.execute(f"SELECT id,{column} FROM articles"):
                    values = domain_taxonomy_module._items(article[column])
                    if target in values:
                        conn.execute(f"UPDATE articles SET {column}=? WHERE id=?",
                                     (json.dumps([value for value in values if value != target], ensure_ascii=False), article["id"]))
            conn.commit()
        finally:
            conn.close()
        return {"ok": True, "updated": updated}

    return router
