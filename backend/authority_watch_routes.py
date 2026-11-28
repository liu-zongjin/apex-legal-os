"""Authority monitor compatibility routes backed by the existing radar pipeline."""

import asyncio
import datetime
import json
import sqlite3
from typing import Callable, NamedTuple

from anyio import from_thread
from fastapi import APIRouter, Form, HTTPException
from pydantic import BaseModel


class AuthorityWatchTaskPayload(BaseModel):
    name: str
    domains: list = []
    keywords: list = []
    sources: list = []
    frequency_hours: int = 24
    enabled: int = 1


class AuthorityWatchRoutes(NamedTuple):
    router: APIRouter
    import_result: Callable[[int], dict]


def create_router(
    get_db: Callable[[], sqlite3.Connection],
    *,
    run_radar_task,
    fetch_webpage,
    plain_article_text,
    classify_domains,
    extract_summary,
    save_article,
    is_meaningful_article_text,
    generate_and_store_ai_summary,
    add_article_to_research_project,
) -> AuthorityWatchRoutes:
    router = APIRouter()

    def _watch_task_to_dict(row) -> dict:
        data = dict(row)
        for key in ("domains", "keywords", "sources"):
            try:
                data[key] = json.loads(data.get(key) or "[]")
            except Exception:
                data[key] = []
        return data


    @router.get("/api/authority-watch/tasks")
    def list_authority_watch_tasks():
        conn = get_db()
        rows = conn.execute("SELECT * FROM authority_watch_tasks ORDER BY updated_at DESC").fetchall()
        tasks = [_watch_task_to_dict(r) for r in rows]
        if not tasks:
            now = datetime.datetime.now().isoformat()
            conn.execute(
                "INSERT INTO authority_watch_tasks (name, domains, keywords, sources, frequency_hours, enabled, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                ("默认权威来源监控", json.dumps(["公司法", "破产法", "建设工程"], ensure_ascii=False), json.dumps(["司法解释", "指导性案例", "裁判规则"], ensure_ascii=False), json.dumps([], ensure_ascii=False), 24, now, now)
            )
            conn.commit()
            rows = conn.execute("SELECT * FROM authority_watch_tasks ORDER BY updated_at DESC").fetchall()
            tasks = [_watch_task_to_dict(r) for r in rows]
        conn.close()
        return {"tasks": tasks}


    @router.post("/api/authority-watch/tasks")
    def create_authority_watch_task(payload: AuthorityWatchTaskPayload):
        now = datetime.datetime.now().isoformat()
        conn = get_db()
        cur = conn.execute(
            "INSERT INTO authority_watch_tasks (name, domains, keywords, sources, frequency_hours, enabled, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (payload.name, json.dumps(payload.domains, ensure_ascii=False), json.dumps(payload.keywords, ensure_ascii=False), json.dumps(payload.sources, ensure_ascii=False), payload.frequency_hours or 24, int(payload.enabled), now, now)
        )
        conn.commit()
        task = _watch_task_to_dict(conn.execute("SELECT * FROM authority_watch_tasks WHERE id=?", (cur.lastrowid,)).fetchone())
        conn.close()
        return task


    @router.put("/api/authority-watch/tasks/{task_id}")
    def update_authority_watch_task(task_id: int, payload: AuthorityWatchTaskPayload):
        now = datetime.datetime.now().isoformat()
        conn = get_db()
        cur = conn.execute(
            "UPDATE authority_watch_tasks SET name=?, domains=?, keywords=?, sources=?, frequency_hours=?, enabled=?, updated_at=? WHERE id=?",
            (payload.name, json.dumps(payload.domains, ensure_ascii=False), json.dumps(payload.keywords, ensure_ascii=False), json.dumps(payload.sources, ensure_ascii=False), payload.frequency_hours or 24, int(payload.enabled), now, task_id)
        )
        if cur.rowcount == 0:
            conn.close()
            raise HTTPException(status_code=404, detail="监控任务不存在")
        conn.commit()
        task = _watch_task_to_dict(conn.execute("SELECT * FROM authority_watch_tasks WHERE id=?", (task_id,)).fetchone())
        conn.close()
        return task


    @router.delete("/api/authority-watch/tasks/{task_id}")
    def delete_authority_watch_task(task_id: int):
        conn = get_db()
        conn.execute("DELETE FROM authority_watch_tasks WHERE id=?", (task_id,))
        conn.commit()
        conn.close()
        return {"success": True}


    @router.post("/api/authority-watch/tasks/{task_id}/run")
    async def run_authority_watch_task(task_id: int):
        """兼容旧入口，统一复用探索雷达流水线。"""
        return await run_radar_task(task_id)


    @router.get("/api/authority-watch/results")
    def list_authority_watch_results(status: str = ""):
        conn = get_db()
        where = []
        if status == "unread":
            where.append("is_read=0 AND is_ignored=0")
        elif status == "importable":
            where.append("is_imported=0 AND is_ignored=0")
        elif status == "imported":
            where.append("is_imported=1")
        elif status == "ignored":
            where.append("is_ignored=1")
        sql = "SELECT * FROM authority_watch_results"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC LIMIT 200"
        rows = conn.execute(sql).fetchall()
        conn.close()
        return {"results": [dict(r) for r in rows]}


    @router.post("/api/authority-watch/results/{result_id}/import")
    def import_authority_watch_result(result_id: int):
        conn = get_db()
        row = conn.execute("SELECT * FROM authority_watch_results WHERE id=?", (result_id,)).fetchone()
        if not row:
            conn.close()
            raise HTTPException(status_code=404, detail="监控结果不存在")
        if row["verification_level"] == "structured_data" or str(row["url"] or "").startswith("finchina://"):
            conn.close()
            raise HTTPException(status_code=400, detail="企业结构化情报用于风险跟踪，不作为法律操作系统正文入库")
        if row["is_imported"] and row["imported_article_id"]:
            conn.close()
            return {"success": True, "article_id": row["imported_article_id"], "already_imported": True}
        conn.close()
        try:
            article_data = fetch_webpage(row["url"])
            content = article_data.get("content") or row["body_text"] or row["summary"] or row["title"]
            title = article_data.get("title") or row["title"]
        except Exception:
            content = row["body_text"] or row["summary"] or row["title"]
            title = row["title"]
        domains = classify_domains(title + " " + plain_article_text(content))
        if domains == ["综合法律"]:
            domains = [row["domain"]] if row["domain"] else []
        summary = extract_summary(plain_article_text(content))
        try:
            article_id = save_article(title, content, summary, domains, "url", source_url=row["url"], tags=[row["source_name"]] if row["source_name"] else [])
        except ValueError:
            with get_db() as conn2:
                existing = conn2.execute("SELECT id FROM articles WHERE source_url=?", (row["url"],)).fetchone()
                article_id = existing["id"] if existing else None
        conn = get_db()
        conn.execute(
            "UPDATE authority_watch_results SET is_imported=1, imported_article_id=?, is_read=1 WHERE id=?",
            (article_id, result_id)
        )
        conn.commit()
        conn.close()
        if article_id:
            article_text = plain_article_text(content)
            if is_meaningful_article_text(article_text, min_len=80):
                def schedule_summary():
                    asyncio.create_task(generate_and_store_ai_summary(article_id, title, article_text, summary))

                # The legacy HTTP endpoints run in an AnyIO worker. Radar batch imports
                # call this same operation from the server loop.
                try:
                    asyncio.get_running_loop()
                except RuntimeError:
                    from_thread.run_sync(schedule_summary)
                else:
                    schedule_summary()
        return {"success": True, "article_id": article_id}


    @router.post("/api/authority-watch/results/{result_id}/add-to-project")
    def add_watch_result_to_project(result_id: int, project_id: int = Form(...)):
        imported = import_authority_watch_result(result_id)
        article_id = imported.get("article_id")
        if not article_id:
            raise HTTPException(status_code=500, detail="入库失败，无法加入项目")
        return add_article_to_research_project(project_id, article_id, added_from="authority_watch")

    return AuthorityWatchRoutes(router, import_authority_watch_result)
