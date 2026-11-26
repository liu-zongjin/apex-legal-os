"""Article annotations and the case reading-note links."""

from __future__ import annotations

import datetime
import json
import sqlite3
from io import BytesIO
from typing import Any, Callable, Dict, Optional
from urllib.parse import quote

import openpyxl
from fastapi import APIRouter, Form, HTTPException, Request


def _decode_note_selection_anchor(value: Any) -> Optional[Dict[str, Any]]:
    if isinstance(value, dict):
        return value
    if not value:
        return None
    try:
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, dict) else None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _encode_note_selection_anchor(value: Any) -> Optional[str]:
    anchor = _decode_note_selection_anchor(value)
    if not anchor:
        return None
    # 锚点只应包含少量偏移和上下文，限制体积避免异常表单写入数据库。
    encoded = json.dumps(anchor, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > 12 * 1024:
        raise HTTPException(status_code=400, detail="笔记定位信息过大")
    return encoded


def create_router(
    get_db: Callable[[], sqlite3.Connection],
    *,
    load_fada_notes: Callable[[], list],
    safe_export_filename: Callable[..., str],
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/notes/all")
    def get_all_notes():
        """获取所有笔记（知识库文章 + 法答网精选答问）"""
        conn = get_db()
        rows = conn.execute(
            """SELECT n.id, n.article_id, n.content, n.selected_text, n.created_at, a.title as article_title
           FROM notes n
           JOIN articles a ON n.article_id = a.id
           ORDER BY n.created_at DESC"""
        ).fetchall()
        conn.close()

        notes = []
        for r in rows:
            notes.append({
                "id": r["id"],
                "source_type": "article",
                "article_id": r["article_id"],
                "article_title": r["article_title"],
                "content": r["content"],
                "selected_text": r["selected_text"],
                "created_at": r["created_at"]
            })

        notes.extend(load_fada_notes())
        notes.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return {"notes": notes}


    @router.get("/api/notes/search")
    def search_notes(q: str = ""):
        """搜索笔记内容、选中文本及关联文章正文"""
        import logging
        logger = logging.getLogger(__name__)

        conn = get_db()
        if not q:
            conn.close()
            return {"notes": []}

        like_q = f"%{q}%"

        # 搜索范围：笔记内容(content) + 用户选中的文章片段(selected_text) + 关联文章正文(articles.content)
        rows = conn.execute(
            """SELECT n.id, n.article_id, n.content, n.selected_text, n.created_at, a.title
           FROM notes n
           JOIN articles a ON n.article_id = a.id
           WHERE n.content LIKE ?
              OR n.selected_text LIKE ?
              OR a.content LIKE ?
           ORDER BY n.created_at DESC""",
            (like_q, like_q, like_q)
        ).fetchall()
        logger.info(f"search_notes: query={q}, result_count={len(rows)}")
        conn.close()

        notes = []
        for r in rows:
            notes.append({
                "id": r["id"],
                "source_type": "article",
                "article_id": r["article_id"],
                "article_title": r["title"],
                "content": r["content"],
                "selected_text": r["selected_text"],
                "created_at": r["created_at"]
            })

        q_lower = q.casefold()
        for note in load_fada_notes():
            searchable = "\n".join([
                note.get("content", ""),
                note.get("article_title", ""),
                note.get("source_title", ""),
                note.get("selected_text", ""),
            ]).casefold()
            if q_lower in searchable:
                notes.append(note)

        notes.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return {"notes": notes}


    @router.get("/api/notes/{article_id}")
    def get_notes(article_id: int):
        """获取文章的所有笔记"""
        conn = get_db()
        rows = conn.execute(
            "SELECT id, content, selected_text, selection_anchor, created_at FROM notes WHERE article_id=? ORDER BY created_at ASC",
            (article_id,)
        ).fetchall()
        conn.close()
        return [{
            "id": r["id"],
            "content": r["content"],
            "selected_text": r["selected_text"],
            "selection_anchor": _decode_note_selection_anchor(r["selection_anchor"]),
            "created_at": r["created_at"],
        } for r in rows]


    @router.get("/api/reading-note-links/{note_id}")
    def get_reading_note_links(note_id: int):
        conn = get_db()
        try:
            if not conn.execute("SELECT 1 FROM notes WHERE id=?", (note_id,)).fetchone():
                raise HTTPException(status_code=404, detail="笔记不存在")
            return [r[0] for r in conn.execute("SELECT case_id FROM case_reading_notes WHERE note_id=?", (note_id,))]
        finally:
            conn.close()


    @router.put("/api/reading-note-links/{note_id}")
    async def put_reading_note_links(note_id: int, request: Request):
        body = await request.json()
        ids = body.get("case_ids")
        if not isinstance(ids, list) or any(type(i) is not int or i <= 0 for i in ids):
            raise HTTPException(status_code=400, detail="案件列表无效")
        ids = list(set(ids))
        conn = get_db()
        try:
            if not conn.execute("SELECT 1 FROM notes WHERE id=?", (note_id,)).fetchone():
                raise HTTPException(status_code=404, detail="笔记不存在")
            for case_id in ids:
                if not conn.execute("SELECT 1 FROM case_manager_cases WHERE id=? AND COALESCE(deleted_at, '')=''", (case_id,)).fetchone():
                    raise HTTPException(status_code=400, detail="案件不存在或已删除")
            conn.execute("DELETE FROM case_reading_notes WHERE note_id=?", (note_id,))
            conn.executemany("INSERT INTO case_reading_notes(note_id, case_id) VALUES (?, ?)", [(note_id, i) for i in ids])
            conn.commit()
            return {"case_ids": ids}
        finally:
            conn.close()


    @router.get("/api/case-reading-notes/{case_id}")
    def get_case_reading_notes(case_id: int):
        conn = get_db()
        try:
            return [dict(r) for r in conn.execute("""SELECT n.id, n.article_id, n.content, n.selected_text, n.created_at, a.title
            FROM case_reading_notes l JOIN notes n ON n.id=l.note_id
            JOIN articles a ON a.id=n.article_id WHERE l.case_id=? ORDER BY n.created_at DESC, n.id DESC""", (case_id,))]
        finally:
            conn.close()


    @router.delete("/api/case-reading-notes/{case_id}/{note_id}")
    def unlink_case_reading_note(case_id: int, note_id: int):
        conn = get_db()
        try:
            result = conn.execute("DELETE FROM case_reading_notes WHERE case_id=? AND note_id=?", (case_id, note_id))
            if not result.rowcount:
                raise HTTPException(status_code=404, detail="该案件未关联此笔记")
            conn.commit()
            return {"success": True}
        finally:
            conn.close()


    @router.get("/api/case-reading-notes/{case_id}/export")
    def export_case_reading_notes(case_id: int):
        from fastapi.responses import StreamingResponse
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter

        conn = get_db()
        try:
            case = conn.execute("SELECT title FROM case_manager_cases WHERE id=? AND COALESCE(deleted_at, '')=''", (case_id,)).fetchone()
            if not case:
                raise HTTPException(status_code=404, detail="案件不存在")
            entries = get_case_reading_notes(case_id)
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "阅读笔记"
            ws.append(["序号", "案件名称", "来源文章", "笔记内容", "原文摘录", "创建时间"])
            for cell in ws[1]:
                cell.font = Font(bold=True, color="111827")
                cell.fill = PatternFill("solid", fgColor="F3F4F6")
            for index, item in enumerate(entries, 1):
                ws.append([index, case["title"], item["title"], item["content"], item["selected_text"] or "", item["created_at"]])
                for cell in ws[ws.max_row]:
                    if isinstance(cell.value, str):
                        cell.data_type = "s"
            for index, width in enumerate([8, 34, 40, 65, 70, 22], 1):
                ws.column_dimensions[get_column_letter(index)].width = width
            for row in ws.iter_rows():
                for cell in row:
                    cell.alignment = Alignment(vertical="top", wrap_text=True)
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            out = BytesIO()
            wb.save(out)
            filename = f"{safe_export_filename(case['title'], '案件')}-阅读笔记.xlsx"
            return StreamingResponse(BytesIO(out.getvalue()), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})
        finally:
            conn.close()


    @router.post("/api/notes")
    def create_note(
        article_id: int = Form(...),
        content: str = Form(...),
        selected_text: str = Form(default=''),
        selection_anchor: str = Form(default=''),
    ):
        """为文章创建新笔记"""
        content = (content or "").strip()
        if not content:
            raise HTTPException(status_code=400, detail="笔记内容不能为空")
        stored_anchor = _encode_note_selection_anchor(selection_anchor)
        conn = get_db()
        now = datetime.datetime.now().isoformat()
        cursor = conn.execute(
            "INSERT INTO notes (article_id, content, selected_text, selection_anchor, created_at) VALUES (?, ?, ?, ?, ?)",
            (article_id, content, selected_text, stored_anchor, now)
        )
        conn.commit()
        note_id = cursor.lastrowid
        conn.close()
        return {
            "id": note_id,
            "content": content,
            "selected_text": selected_text,
            "selection_anchor": _decode_note_selection_anchor(stored_anchor),
            "created_at": now,
        }


    @router.put("/api/notes/{note_id}")
    async def update_note(note_id: int, request: Request):
        """更新已保存的阅读笔记内容。笔记存储在本地 SQLite 数据库中。"""
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            body = await request.json()
            content = body.get("content", "")
        else:
            form = await request.form()
            content = form.get("content", "")

        content = (content or "").strip()
        if not content:
            raise HTTPException(status_code=400, detail="笔记内容不能为空")

        conn = get_db()
        row = conn.execute("SELECT id, article_id, selected_text, selection_anchor, created_at FROM notes WHERE id=?", (note_id,)).fetchone()
        if not row:
            conn.close()
            raise HTTPException(status_code=404, detail="笔记不存在")

        conn.execute("UPDATE notes SET content=? WHERE id=?", (content, note_id))
        conn.commit()
        conn.close()
        return {
            "success": True,
            "id": row["id"],
            "article_id": row["article_id"],
            "content": content,
            "selected_text": row["selected_text"],
            "selection_anchor": _decode_note_selection_anchor(row["selection_anchor"]),
            "created_at": row["created_at"],
        }


    @router.delete("/api/notes/{note_id}")
    def delete_note(note_id: int):
        """删除笔记"""
        conn = get_db()
        conn.execute("DELETE FROM notes WHERE id=?", (note_id,))
        conn.commit()
        conn.close()
        return {"success": True}

    return router
