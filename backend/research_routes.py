"""Research projects, case research records, and research exports."""

import datetime
import json
import re
import sqlite3
import zipfile
from io import BytesIO
from typing import Callable, NamedTuple, Optional, Tuple, Type
from urllib.parse import quote

import openpyxl
from bs4 import BeautifulSoup
from fastapi import APIRouter, Form, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from . import ai_config as ai_config_module


class ResearchProjectPayload(BaseModel):
    case_id: Optional[int] = None
    name: str
    client: str = ""
    case_info: str = ""
    issues: str = ""
    status: str = "active"
    notes: str = ""


class ResearchMemoPayload(BaseModel):
    question: str = ""
    title: str = ""
    markdown: str = ""


class LinkedAskQuestionPayload(BaseModel):
    question: str
    answer: str
    model: str = ""
    sources: list = []
    cited_sources: list = []
    reasoning: str = ""
    is_reasoning_model: bool = False
    created_at: str = ""
    source_ref: str = ""


def _case_timeline_export_text(content: str) -> str:
    """Keep readable record paragraphs and source URLs in spreadsheet exports."""
    if not re.match(r"\s*<(?:p|div|h[1-6]|ul|ol|li|blockquote|pre|table|br|span|strong|b|em|i|u|s|a|code|img|sup|sub)\b", content or "", re.I):
        return content or ""
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if href.startswith(("https://", "http://")) and href not in link.get_text():
            link.append(f"（{href}）")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for block in soup.find_all(["p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "blockquote", "pre"]):
        if block.name == "li" and block.get("data-list-label"):
            block.insert(0, block["data-list-label"] + " ")
        block.append("\n")
    return re.sub(r"\n{3,}", "\n\n", soup.get_text()).strip()


def _case_timeline_xlsx_bytes(case_title: str, entries: list, label: str) -> bytes:
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = label[:31]
    headers = ["序号", "案件名称", "时间节点", "标题", "内容", "提交时间", "更新时间"]
    ws.append(headers)
    header_fill = PatternFill("solid", fgColor="F3F4F6")
    header_font = Font(bold=True, color="111827")
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    if entries:
        for idx, item in enumerate(entries, 1):
            ws.append([
                idx,
                case_title,
                item.get("happened_at") or "",
                item.get("title") or "",
                _case_timeline_export_text(item.get("content") or ""),
                item.get("created_at") or "",
                item.get("updated_at") or "",
            ])
    else:
        ws.append([1, case_title, "", "", "暂无记录", "", ""])
    widths = [8, 34, 14, 30, 72, 21, 21]
    for idx, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(idx)].width = width
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


class ResearchRoutes(NamedTuple):
    router: APIRouter
    add_article_to_project: Callable[..., dict]


def create_router(
    get_db: Callable[[], sqlite3.Connection],
    *,
    timeline_entry_payload: Type[BaseModel],
    ensure_case_research_project,
    case_client_names,
    timeline_public_entry,
    save_timeline_entry,
    delete_timeline_entry,
    escape_like_pattern,
    resolve_model,
    ask_question,
    answer_with_paragraphs,
    build_questions_markdown,
    render_questions_docx,
    safe_export_filename,
    utf8_bom_markdown_bytes,
    add_article_to_docx,
    article_docx_bytes,
) -> ResearchRoutes:
    router = APIRouter()

    def _row_to_project(row, conn=None) -> dict:
        data = dict(row)
        data["article_count"] = 0
        if conn:
            data["article_count"] = conn.execute(
                "SELECT COUNT(*) FROM research_project_articles WHERE project_id=?",
                (row["id"],)
            ).fetchone()[0]
        return data


    def _case_to_research_case(conn, row, include_children: bool = True) -> dict:
        item = dict(row)
        project = conn.execute(
            "SELECT id FROM research_projects WHERE case_id=? ORDER BY updated_at DESC, id DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
        project_id = project["id"] if project else None
        item["project_id"] = project_id
        item["client_names"] = case_client_names(conn, row["id"])
        item["article_count"] = 0
        item["ledger_count"] = 0
        item["memo_entry_count"] = 0
        if project_id:
            item["article_count"] = conn.execute(
                "SELECT COUNT(*) FROM research_project_articles WHERE project_id=?",
                (project_id,),
            ).fetchone()[0]
            item["ledger_count"] = conn.execute(
                "SELECT COUNT(*) FROM research_case_ledgers WHERE project_id=?",
                (project_id,),
            ).fetchone()[0]
            item["memo_entry_count"] = conn.execute(
                "SELECT COUNT(*) FROM research_case_memo_entries WHERE project_id=?",
                (project_id,),
            ).fetchone()[0]
        item["series_children"] = []
        if include_children and item.get("case_kind") == "series":
            children = conn.execute(
                """SELECT * FROM case_manager_cases
               WHERE parent_series_id=? AND case_kind='series_child'
                 AND COALESCE(source_status,'active')='active'
               ORDER BY series_order,id""",
                (row["id"],),
            ).fetchall()
            item["series_children"] = [_case_to_research_case(conn, child, False) for child in children]
            item["article_count"] += sum(int(child.get("article_count") or 0) for child in item["series_children"])
            item["ledger_count"] += sum(int(child.get("ledger_count") or 0) for child in item["series_children"])
            item["memo_entry_count"] += sum(int(child.get("memo_entry_count") or 0) for child in item["series_children"])
        return item


    def _case_research_detail(conn, case_id: int) -> dict:
        project_id = ensure_case_research_project(conn, case_id)
        case = conn.execute("SELECT * FROM case_manager_cases WHERE id=?", (case_id,)).fetchone()
        detail = _project_detail(conn, project_id)
        detail["case"] = _case_to_research_case(conn, case)
        detail["ledgers"] = [
            timeline_public_entry(r)
            for r in conn.execute(
                """
            SELECT * FROM research_case_ledgers
            WHERE project_id=?
            ORDER BY COALESCE(NULLIF(happened_at, ''), created_at) DESC, id DESC
            """,
                (project_id,),
            ).fetchall()
        ]
        detail["memo_entries"] = [
            timeline_public_entry(r)
            for r in conn.execute(
                """
            SELECT m.*, EXISTS(SELECT 1 FROM calculator_memo_snapshots s WHERE s.memo_id=m.id)
                       AS has_calculation FROM research_case_memo_entries m
            WHERE project_id=?
            ORDER BY COALESCE(NULLIF(happened_at, ''), created_at) DESC, id DESC
            """,
                (project_id,),
            ).fetchall()
        ]
        if case["case_kind"] == "series":
            child_projects = conn.execute(
                """SELECT rp.id,c.series_code,c.series_display_name,c.title
               FROM research_projects rp
               JOIN case_manager_cases c ON c.id=rp.case_id
               WHERE c.parent_series_id=? AND c.case_kind='series_child'
                 AND COALESCE(c.source_status,'active')<>'deleted'
               ORDER BY c.series_order,c.id""",
                (case_id,),
            ).fetchall()
            project_labels = {project_id: "系列事项"}
            for row in child_projects:
                project_labels[int(row["id"])] = " · ".join(
                    part for part in [row["series_code"] or "", row["series_display_name"] or row["title"] or ""] if part
                )
            project_ids = list(project_labels)
            article_map = {}
            for linked_project_id in project_ids:
                for article in _project_linked_articles_full(conn, linked_project_id):
                    existing = article_map.get(int(article["id"]))
                    if existing:
                        existing["linked_project_ids"].append(linked_project_id)
                        existing["series_case_labels"].append(project_labels[linked_project_id])
                    else:
                        article["linked_project_id"] = linked_project_id
                        article["linked_project_ids"] = [linked_project_id]
                        article["series_case_labels"] = [project_labels[linked_project_id]]
                        article_map[int(article["id"])] = article
            detail["articles"] = sorted(article_map.values(), key=lambda item: item.get("added_at") or "", reverse=True)
            marks = ",".join("?" for _ in project_ids)
            detail["ledgers"] = [
                {**timeline_public_entry(row), "series_case_label": project_labels.get(int(row["project_id"]), "系列事项")}
                for row in conn.execute(
                    f"""SELECT * FROM research_case_ledgers WHERE project_id IN ({marks})
                    ORDER BY COALESCE(NULLIF(happened_at, ''), created_at) DESC,id DESC""",
                    project_ids,
                ).fetchall()
            ]
            detail["memo_entries"] = [
                {**timeline_public_entry(row), "series_case_label": project_labels.get(int(row["project_id"]), "系列事项")}
                for row in conn.execute(
                    f"""SELECT m.*, EXISTS(SELECT 1 FROM calculator_memo_snapshots s WHERE s.memo_id=m.id)
                       AS has_calculation FROM research_case_memo_entries m WHERE project_id IN ({marks})
                    ORDER BY COALESCE(NULLIF(happened_at, ''), created_at) DESC,id DESC""",
                    project_ids,
                ).fetchall()
            ]
        return detail


    def _project_linked_articles_full(conn, project_id: int) -> list:
        rows = conn.execute(
            """
        SELECT a.id, a.title, a.summary, a.content, a.domains, a.tags,
               a.source_type, a.source_url, a.source_filename, a.created_at,
               a.pinned, rpa.added_from, rpa.created_at AS added_at
        FROM research_project_articles rpa
        JOIN articles a ON a.id = rpa.article_id
        WHERE rpa.project_id=?
        ORDER BY rpa.created_at DESC
        """,
            (project_id,),
        ).fetchall()
        articles = []
        for row in rows:
            item = dict(row)
            item["domains"] = json.loads(item.get("domains") or "[]")
            item["tags"] = json.loads(item.get("tags") or "[]")
            item["pinned"] = bool(item.get("pinned", 0))
            articles.append(item)
        return articles


    def _case_research_detail_for_offline(conn, case_id: int) -> dict:
        detail = _case_research_detail(conn, case_id)
        project_id = detail.get("project", {}).get("id")
        if project_id:
            if detail.get("case", {}).get("case_kind") != "series":
                detail["articles"] = _project_linked_articles_full(conn, project_id)
            questions = conn.execute(
                "SELECT * FROM research_project_questions WHERE project_id=? ORDER BY created_at ASC",
                (project_id,),
            ).fetchall()
            detail["questions"] = []
            for row in questions:
                item = dict(row)
                item["sources"] = json.loads(item.pop("sources_json") or "[]")
                item["cited_sources"] = json.loads(item.pop("cited_sources_json") or "[]")
                detail["questions"].append(item)
            memos = conn.execute(
                "SELECT * FROM research_memos WHERE project_id=? ORDER BY updated_at DESC",
                (project_id,),
            ).fetchall()
            detail["memos"] = []
            for row in memos:
                item = dict(row)
                item["sources"] = json.loads(item.pop("sources_json") or "[]")
                detail["memos"].append(item)
        return detail


    def _get_project_article_ids(conn, project_id: int) -> list:
        return [
            r["article_id"]
            for r in conn.execute(
                "SELECT article_id FROM research_project_articles WHERE project_id=?",
                (project_id,)
            ).fetchall()
        ]


    def _project_detail(conn, project_id: int) -> dict:
        project = conn.execute("SELECT * FROM research_projects WHERE id=?", (project_id,)).fetchone()
        if not project:
            raise HTTPException(status_code=404, detail="研究项目不存在")
        articles = conn.execute(
            """
        SELECT a.id, a.title, a.summary, a.domains, a.source_type, a.source_url,
               a.source_filename, a.created_at, rpa.added_from, rpa.created_at AS added_at
        FROM research_project_articles rpa
        JOIN articles a ON a.id = rpa.article_id
        WHERE rpa.project_id=?
        ORDER BY rpa.created_at DESC
        """,
            (project_id,)
        ).fetchall()
        notes = conn.execute(
            "SELECT id, content, created_at FROM research_project_notes WHERE project_id=? ORDER BY created_at DESC",
            (project_id,)
        ).fetchall()
        memos = conn.execute(
            "SELECT id, title, question, created_at, updated_at FROM research_memos WHERE project_id=? ORDER BY updated_at DESC",
            (project_id,)
        ).fetchall()
        ledgers = conn.execute(
            "SELECT * FROM research_case_ledgers WHERE project_id=? ORDER BY COALESCE(NULLIF(happened_at, ''), created_at) DESC, id DESC",
            (project_id,)
        ).fetchall()
        memo_entries = conn.execute(
            "SELECT * FROM research_case_memo_entries WHERE project_id=? ORDER BY COALESCE(NULLIF(happened_at, ''), created_at) DESC, id DESC",
            (project_id,)
        ).fetchall()
        return {
            "project": _row_to_project(project, conn),
            "articles": [dict(r) for r in articles],
            "notes": [dict(r) for r in notes],
            "memos": [dict(r) for r in memos],
            "ledgers": [timeline_public_entry(r) for r in ledgers],
            "memo_entries": [timeline_public_entry(r) for r in memo_entries],
        }


    @router.get("/api/research-projects")
    def list_research_projects():
        conn = get_db()
        rows = conn.execute("SELECT * FROM research_projects ORDER BY updated_at DESC, id DESC").fetchall()
        projects = [_row_to_project(r, conn) for r in rows]
        conn.close()
        return {"projects": projects}


    @router.post("/api/research-projects")
    def create_research_project(payload: ResearchProjectPayload):
        if not payload.name.strip():
            raise HTTPException(status_code=400, detail="项目名称不能为空")
        now = datetime.datetime.now().isoformat()
        conn = get_db()
        cur = conn.execute(
            """
        INSERT INTO research_projects (case_id, name, client, case_info, issues, status, notes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (payload.case_id, payload.name.strip(), payload.client, payload.case_info, payload.issues, payload.status or "active", payload.notes, now, now)
        )
        conn.commit()
        project_id = cur.lastrowid
        detail = _project_detail(conn, project_id)
        conn.close()
        return detail


    @router.get("/api/research-projects/{project_id}")
    def get_research_project(project_id: int):
        conn = get_db()
        detail = _project_detail(conn, project_id)
        conn.close()
        return detail


    @router.put("/api/research-projects/{project_id}")
    def update_research_project(project_id: int, payload: ResearchProjectPayload):
        now = datetime.datetime.now().isoformat()
        conn = get_db()
        cur = conn.execute(
            """
        UPDATE research_projects
        SET case_id=COALESCE(?, case_id), name=?, client=?, case_info=?, issues=?, status=?, notes=?, updated_at=?
        WHERE id=?
        """,
            (payload.case_id, payload.name.strip(), payload.client, payload.case_info, payload.issues, payload.status or "active", payload.notes, now, project_id)
        )
        if cur.rowcount == 0:
            conn.close()
            raise HTTPException(status_code=404, detail="研究项目不存在")
        conn.commit()
        detail = _project_detail(conn, project_id)
        conn.close()
        return detail


    @router.delete("/api/research-projects/{project_id}")
    def delete_research_project(project_id: int):
        conn = get_db()
        conn.execute("DELETE FROM research_projects WHERE id=?", (project_id,))
        conn.commit()
        conn.close()
        return {"success": True}


    @router.get("/api/case-research/cases")
    def list_case_research_cases(q: str = "", limit: int = 500):
        query = (q or "").strip()
        limit = max(20, min(int(limit or 500), 1000))
        conn = get_db()
        where = ["COALESCE(source_status, 'active')='active'", "COALESCE(case_kind, 'ordinary')<>'series_child'"]
        params: list = []
        if query:
            like = f"%{escape_like_pattern(query)}%"
            where.append(
                """(
                title LIKE ? ESCAPE '\\'
                OR case_type LIKE ? ESCAPE '\\'
                OR memo LIKE ? ESCAPE '\\'
                OR EXISTS (
                    SELECT 1 FROM case_manager_parties p
                    WHERE p.case_id=case_manager_cases.id AND p.name LIKE ? ESCAPE '\\'
                )
                OR EXISTS (
                    SELECT 1 FROM case_manager_case_numbers n
                    WHERE n.case_id=case_manager_cases.id AND n.case_no LIKE ? ESCAPE '\\'
                )
                OR EXISTS (
                    SELECT 1 FROM case_manager_cases sc
                    WHERE sc.parent_series_id=case_manager_cases.id AND sc.case_kind='series_child'
                      AND (sc.title LIKE ? ESCAPE '\\' OR sc.series_code LIKE ? ESCAPE '\\'
                           OR sc.series_display_name LIKE ? ESCAPE '\\' OR sc.memo LIKE ? ESCAPE '\\')
                )
                OR EXISTS (
                    SELECT 1 FROM case_manager_cases sc
                    JOIN case_manager_parties sp ON sp.case_id=sc.id
                    WHERE sc.parent_series_id=case_manager_cases.id AND sp.name LIKE ? ESCAPE '\\'
                )
                OR EXISTS (
                    SELECT 1 FROM case_manager_cases sc
                    JOIN case_manager_case_numbers sn ON sn.case_id=sc.id
                    WHERE sc.parent_series_id=case_manager_cases.id AND sn.case_no LIKE ? ESCAPE '\\'
                )
            )"""
            )
            params.extend([like] * 11)
        rows = conn.execute(
            f"""
        SELECT * FROM case_manager_cases
        WHERE {' AND '.join(where)}
        ORDER BY updated_at DESC, id DESC
        LIMIT ?
        """,
            (*params, limit),
        ).fetchall()
        cases = [_case_to_research_case(conn, r) for r in rows]
        conn.close()
        return {"cases": cases}


    @router.get("/api/case-research/offline-snapshot")
    def case_research_offline_snapshot(limit: int = 500):
        """案件研究离线快照：案件台账、案件备忘录、关联文章和研究备忘录。"""
        max_items = max(20, min(int(limit or 500), 1000))
        conn = get_db()
        rows = conn.execute(
            """
        SELECT * FROM case_manager_cases
        WHERE COALESCE(source_status, 'active')='active'
          AND COALESCE(case_kind, 'ordinary')<>'series_child'
        ORDER BY updated_at DESC, id DESC
        LIMIT ?
        """,
            (max_items,),
        ).fetchall()
        cases = []
        details = {}
        project_to_case = {}
        memo_to_case = {}
        linked_articles = {}
        for row in rows:
            case_item = _case_to_research_case(conn, row)
            cases.append(case_item)
            detail = _case_research_detail_for_offline(conn, row["id"])
            details[str(row["id"])] = detail
            project_id = detail.get("project", {}).get("id")
            if project_id:
                project_to_case[str(project_id)] = row["id"]
            for memo in detail.get("memos", []) or []:
                memo_to_case[str(memo.get("id"))] = row["id"]
            for article in detail.get("articles", []) or []:
                linked_articles[str(article.get("id"))] = article
        conn.commit()
        conn.close()
        return {
            "version": 1,
            "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "limit": max_items,
            "cases": cases,
            "details": details,
            "project_to_case": project_to_case,
            "memo_to_case": memo_to_case,
            "linked_articles": linked_articles,
        }


    @router.get("/api/case-research/cases/{case_id}")
    def get_case_research(case_id: int):
        conn = get_db()
        detail = _case_research_detail(conn, case_id)
        conn.commit()
        conn.close()
        return detail


    @router.post("/api/case-research/cases/{case_id}/articles/{article_id}")
    def add_article_to_case_research(case_id: int, article_id: int, added_from: str = Form(default="manual")):
        now = datetime.datetime.now().isoformat()
        conn = get_db()
        project_id = ensure_case_research_project(conn, case_id)
        if not conn.execute("SELECT id FROM articles WHERE id=?", (article_id,)).fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail="文章不存在")
        conn.execute(
            "INSERT OR IGNORE INTO research_project_articles (project_id, article_id, added_from, created_at) VALUES (?, ?, ?, ?)",
            (project_id, article_id, added_from or "manual", now),
        )
        conn.execute("UPDATE research_projects SET updated_at=? WHERE id=?", (now, project_id))
        conn.commit()
        conn.close()
        return {"success": True, "project_id": project_id}


    @router.post("/api/case-research/cases/{case_id}/questions/import")
    def import_question_to_case_research(case_id: int, payload: LinkedAskQuestionPayload):
        """把知识库 AI增强关联到案件研究；source_ref 保证重复点击不会产生副本。"""
        question = (payload.question or "").strip()
        answer = (payload.answer or "").strip()
        if not question or not answer:
            raise HTTPException(status_code=400, detail="问题和回答不能为空")
        now = datetime.datetime.now().isoformat()
        created_at = (payload.created_at or "").strip() or now
        source_ref = (payload.source_ref or "").strip()[:160]
        conn = get_db()
        project_id = ensure_case_research_project(conn, case_id)
        existing = None
        if source_ref:
            existing = conn.execute(
                "SELECT id FROM research_project_questions WHERE project_id=? AND source_ref=?",
                (project_id, source_ref),
            ).fetchone()
        if existing:
            question_id = int(existing["id"])
        else:
            cur = conn.execute(
                """
            INSERT INTO research_project_questions
            (project_id, question, answer, model, sources_json, cited_sources_json,
             reasoning, is_reasoning_model, source_type, source_ref, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'knowledge_ai_ask', ?, ?)
            """,
                (
                    project_id,
                    question,
                    answer,
                    (payload.model or "").strip(),
                    json.dumps(payload.sources or [], ensure_ascii=False),
                    json.dumps(payload.cited_sources or [], ensure_ascii=False),
                    payload.reasoning or "",
                    int(bool(payload.is_reasoning_model)),
                    source_ref,
                    created_at,
                ),
            )
            question_id = int(cur.lastrowid)
            conn.execute("UPDATE research_projects SET updated_at=? WHERE id=?", (now, project_id))
        conn.commit()
        conn.close()
        return {
            "success": True,
            "case_id": case_id,
            "project_id": project_id,
            "question_id": question_id,
            "already_linked": bool(existing),
        }


    @router.post("/api/case-research/projects/{project_id}/ledgers")
    def create_case_ledger(project_id: int, payload: timeline_entry_payload):
        return save_timeline_entry("research_case_ledgers", project_id, payload)


    @router.put("/api/case-research/ledgers/{entry_id}")
    def update_case_ledger(entry_id: int, payload: timeline_entry_payload):
        conn = get_db()
        row = conn.execute("SELECT project_id FROM research_case_ledgers WHERE id=?", (entry_id,)).fetchone()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="台账不存在")
        return save_timeline_entry("research_case_ledgers", row["project_id"], payload, entry_id)


    @router.delete("/api/case-research/ledgers/{entry_id}")
    def delete_case_ledger(entry_id: int):
        return delete_timeline_entry("research_case_ledgers", entry_id)


    @router.post("/api/case-research/projects/{project_id}/memo-entries")
    def create_case_memo_entry(project_id: int, payload: timeline_entry_payload):
        return save_timeline_entry("research_case_memo_entries", project_id, payload)


    @router.put("/api/case-research/memo-entries/{entry_id}")
    def update_case_memo_entry(entry_id: int, payload: timeline_entry_payload):
        conn = get_db()
        row = conn.execute("SELECT project_id FROM research_case_memo_entries WHERE id=?", (entry_id,)).fetchone()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="备忘录不存在")
        return save_timeline_entry("research_case_memo_entries", row["project_id"], payload, entry_id)


    @router.delete("/api/case-research/memo-entries/{entry_id}")
    def delete_case_memo_entry(entry_id: int):
        return delete_timeline_entry("research_case_memo_entries", entry_id)


    @router.post("/api/research-projects/{project_id}/articles/{article_id}")
    def add_article_to_research_project(project_id: int, article_id: int, added_from: str = Form(default="manual")):
        now = datetime.datetime.now().isoformat()
        conn = get_db()
        if not conn.execute("SELECT id FROM research_projects WHERE id=?", (project_id,)).fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail="研究项目不存在")
        if not conn.execute("SELECT id FROM articles WHERE id=?", (article_id,)).fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail="文章不存在")
        conn.execute(
            "INSERT OR IGNORE INTO research_project_articles (project_id, article_id, added_from, created_at) VALUES (?, ?, ?, ?)",
            (project_id, article_id, added_from or "manual", now)
        )
        conn.execute("UPDATE research_projects SET updated_at=? WHERE id=?", (now, project_id))
        conn.commit()
        conn.close()
        return {"success": True}


    @router.delete("/api/research-projects/{project_id}/articles/{article_id}")
    def remove_article_from_research_project(project_id: int, article_id: int):
        conn = get_db()
        conn.execute("DELETE FROM research_project_articles WHERE project_id=? AND article_id=?", (project_id, article_id))
        conn.commit()
        conn.close()
        return {"success": True}


    @router.get("/api/research-projects/{project_id}/questions")
    def get_research_project_questions(project_id: int):
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM research_project_questions WHERE project_id=? ORDER BY created_at ASC",
            (project_id,)
        ).fetchall()
        conn.close()
        result = []
        for r in rows:
            item = dict(r)
            item["sources"] = json.loads(item.pop("sources_json") or "[]")
            item["cited_sources"] = json.loads(item.pop("cited_sources_json") or "[]")
            item["is_reasoning_model"] = bool(item.get("is_reasoning_model"))
            result.append(item)
        return {"questions": result}


    def _load_research_question_exports(*, project_id: int = 0, question_id: int = 0) -> Tuple[dict, list]:
        """读取案件资料问答；AI增强页关联进来的记录与原生记录使用同一张表。"""
        conn = get_db()
        if question_id:
            question_row = conn.execute(
                "SELECT * FROM research_project_questions WHERE id=?", (question_id,)
            ).fetchone()
            if not question_row:
                conn.close()
                raise HTTPException(status_code=404, detail="案件资料问答记录不存在")
            project_id = int(question_row["project_id"])
        project_row = conn.execute(
            """
        SELECT rp.*, cc.title AS case_title
        FROM research_projects rp
        LEFT JOIN case_manager_cases cc ON cc.id=rp.case_id
        WHERE rp.id=?
        """,
            (project_id,),
        ).fetchone()
        if not project_row:
            conn.close()
            raise HTTPException(status_code=404, detail="案件研究不存在")
        if question_id:
            rows = [question_row]
        else:
            rows = conn.execute(
                "SELECT * FROM research_project_questions WHERE project_id=? ORDER BY created_at ASC, id ASC",
                (project_id,),
            ).fetchall()
        conn.close()
        records = []
        for row in rows:
            item = dict(row)
            try:
                sources = json.loads(item.get("cited_sources_json") or "[]") or []
            except (TypeError, ValueError):
                sources = []
            if not sources:
                try:
                    sources = json.loads(item.get("sources_json") or "[]") or []
                except (TypeError, ValueError):
                    sources = []
            item["sources"] = sources
            records.append(item)
        if not records:
            raise HTTPException(status_code=404, detail="该案件尚无可导出的问答记录")
        return dict(project_row), records


    def _research_question_export_response(project: dict, records: list, file_format: str, layout: str = "legal_standard"):
        from fastapi.responses import StreamingResponse

        fmt = (file_format or "md").strip().lower()
        if fmt not in {"md", "docx"}:
            raise HTTPException(status_code=400, detail="仅支持 md 和 docx 格式")
        case_title = project.get("case_title") or project.get("name") or "案件"
        suffix = "全部案件资料问答" if len(records) > 1 else str(records[0].get("question") or "案件资料问答")[:48]
        filename = f"{safe_export_filename(case_title, '案件')}-{safe_export_filename(suffix, '案件资料问答')}.{fmt}"
        headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
        if fmt == "md":
            return Response(
                content=utf8_bom_markdown_bytes(build_questions_markdown(project, records)),
                media_type="text/markdown",
                headers=headers,
            )
        return StreamingResponse(
            BytesIO(render_questions_docx(project, records, layout=layout)),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers=headers,
        )


    @router.get("/api/research-project-questions/{question_id}/export")
    def export_research_project_question(
        question_id: int,
        file_format: str = Query("md", alias="format"),
        layout: str = Query("legal_standard"),
    ):
        project, records = _load_research_question_exports(question_id=question_id)
        return _research_question_export_response(project, records, file_format, layout=layout)


    @router.get("/api/research-projects/{project_id}/questions/export")
    def export_research_project_questions(
        project_id: int,
        file_format: str = Query("md", alias="format"),
        layout: str = Query("legal_standard"),
    ):
        project, records = _load_research_question_exports(project_id=project_id)
        return _research_question_export_response(project, records, file_format, layout=layout)


    @router.post("/api/research-projects/{project_id}/ask")
    async def ask_research_project(project_id: int, question: str = Form(...), model: str = Form("")):
        if not question.strip():
            raise HTTPException(status_code=400, detail="问题不能为空")
        model = resolve_model(model)
        conn = get_db()
        project_row = conn.execute("SELECT * FROM research_projects WHERE id=?", (project_id,)).fetchone()
        if not project_row:
            conn.close()
            raise HTTPException(status_code=404, detail="研究项目不存在")
        article_ids = _get_project_article_ids(conn, project_id)
        conn.close()
        if not article_ids:
            raise HTTPException(status_code=400, detail="当前案件尚未关联文章，请先添加案件资料")

        # 案件资料问答与主知识库 AI增强共用同一套检索、提示词、续写和引用核验流程，
        # 仅把检索范围限定为当前案件关联的全部文章。
        data = await ask_question(
            question=question.strip(),
            model=model,
            article_ids=",".join(str(article_id) for article_id in article_ids),
            source_mode="hybrid",
            case_search=False,
        )
        now = datetime.datetime.now().isoformat()
        conn = get_db()
        cur = conn.execute(
            """
        INSERT INTO research_project_questions
        (project_id, question, answer, model, sources_json, cited_sources_json,
         reasoning, is_reasoning_model, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                project_id,
                question.strip(),
                data["answer"],
                data["model_used"],
                json.dumps(data.get("sources", []), ensure_ascii=False),
                json.dumps(data.get("cited_sources", []), ensure_ascii=False),
                data.get("reasoning") or "",
                int(bool(data.get("is_reasoning_model"))),
                now,
            )
        )
        conn.execute("UPDATE research_projects SET updated_at=? WHERE id=?", (now, project_id))
        conn.commit()
        data["id"] = cur.lastrowid
        data["question"] = question.strip()
        data["created_at"] = now
        conn.close()
        return data


    def _memo_markdown(project: dict, question: str, answer: str, cited_sources: list, sources: list) -> str:
        refs = cited_sources or []
        src_lines = []
        for i, s in enumerate(sources or [], 1):
            src_lines.append(f"{i}. 《{s.get('title','')}》{(' - ' + s.get('source','')) if s.get('source') else ''}")
        quote_lines = []
        for i, cs in enumerate(refs, 1):
            para = f"第 {cs.get('paragraph_index')} 段" if cs.get("paragraph_index") else "文章级引用"
            quote_lines.append(f"{i}. 《{cs.get('title','')}》{para}：{cs.get('quote') or cs.get('excerpt','')}")
        return f"""# {project.get('name', '研究项目')} 检索备忘录

## 检索问题
{question or '（未填写）'}

## 检索范围
项目资料库；客户/案件：{project.get('client','')} {project.get('case_info','')}

## 核心结论
{answer}

## 依据与引用
{chr(10).join(quote_lines) if quote_lines else '暂无可验证引用。'}

## 争议焦点分析
{project.get('issues') or '暂无争议焦点，可在项目信息中补充。'}

## 风险提示
以上结论基于当前项目已绑定资料生成；若涉及最新法规、地方裁判口径或未入库材料，应继续补充检索。

## 后续检索建议
- 补充同类案由的高院/最高院案例。
- 检索最新司法解释、会议纪要和主管部门规范性文件。
- 对相反观点和例外情形进行二次核验。

## 参考资料清单
{chr(10).join(src_lines) if src_lines else '暂无参考资料。'}
"""


    @router.post("/api/research-projects/{project_id}/memo/generate")
    async def generate_research_memo(project_id: int, payload: ResearchMemoPayload):
        conn = get_db()
        project_row = conn.execute("SELECT * FROM research_projects WHERE id=?", (project_id,)).fetchone()
        if not project_row:
            conn.close()
            raise HTTPException(status_code=404, detail="研究项目不存在")
        project = dict(project_row)
        question = (payload.question or project.get("issues") or project.get("name") or "项目法律问题").strip()
        article_ids = _get_project_article_ids(conn, project_id)
        try:
            data = await answer_with_paragraphs(question, ai_config_module.effective_purpose_model("research_memo"), conn, article_ids=article_ids, project=project)
            answer = data["answer"]
            sources = data.get("sources", [])
            cited = data.get("cited_sources", [])
        except Exception as e:
            answer = f"自动分析暂不可用：{e}"
            sources, cited = [], []
        markdown = payload.markdown or _memo_markdown(project, question, answer, cited, sources)
        now = datetime.datetime.now().isoformat()
        title = payload.title or f"{project.get('name','研究项目')}检索备忘录"
        cur = conn.execute(
            """
        INSERT INTO research_memos (project_id, title, question, markdown, sources_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (project_id, title, question, markdown, json.dumps(cited or sources, ensure_ascii=False), now, now)
        )
        conn.commit()
        memo_id = cur.lastrowid
        conn.close()
        return {"id": memo_id, "project_id": project_id, "title": title, "question": question, "markdown": markdown, "sources": cited or sources, "created_at": now, "updated_at": now}


    @router.get("/api/research-projects/{project_id}/memos")
    def list_research_memos(project_id: int):
        conn = get_db()
        rows = conn.execute("SELECT id, project_id, title, question, created_at, updated_at FROM research_memos WHERE project_id=? ORDER BY updated_at DESC", (project_id,)).fetchall()
        conn.close()
        return {"memos": [dict(r) for r in rows]}


    @router.get("/api/research-memos/{memo_id}")
    def get_research_memo(memo_id: int):
        conn = get_db()
        row = conn.execute("SELECT * FROM research_memos WHERE id=?", (memo_id,)).fetchone()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="备忘录不存在")
        data = dict(row)
        data["sources"] = json.loads(data.pop("sources_json") or "[]")
        return data


    @router.put("/api/research-memos/{memo_id}")
    def update_research_memo(memo_id: int, payload: ResearchMemoPayload):
        now = datetime.datetime.now().isoformat()
        conn = get_db()
        cur = conn.execute(
            "UPDATE research_memos SET title=COALESCE(NULLIF(?, ''), title), question=?, markdown=?, updated_at=? WHERE id=?",
            (payload.title or "", payload.question or "", payload.markdown or "", now, memo_id)
        )
        if cur.rowcount == 0:
            conn.close()
            raise HTTPException(status_code=404, detail="备忘录不存在")
        conn.commit()
        conn.close()
        return {"success": True, "updated_at": now}


    @router.get("/api/research-memos/{memo_id}/download.md")
    def download_research_memo_md(memo_id: int):
        from fastapi.responses import Response as FastAPIResponse
        memo = get_research_memo(memo_id)
        filename = re.sub(r'[\\/:*?"<>|]+', '_', memo["title"]) + ".md"
        return FastAPIResponse(
            utf8_bom_markdown_bytes(memo["markdown"]),
            media_type="text/markdown",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
        )


    def _generate_memo_docx(title: str, markdown: str) -> bytes:
        from io import BytesIO
        from docx import Document
        from docx.shared import Pt
        from docx.oxml.ns import qn
        doc = Document()
        style = doc.styles['Normal']
        style.font.name = '宋体'
        style._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
        style.font.size = Pt(11)
        doc.add_heading(title, level=1)
        for line in (markdown or "").splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("# "):
                doc.add_heading(line[2:].strip(), level=1)
            elif line.startswith("## "):
                doc.add_heading(line[3:].strip(), level=2)
            elif re.match(r'^[-*]\s+', line):
                doc.add_paragraph(re.sub(r'^[-*]\s+', '', line), style='List Bullet')
            elif re.match(r'^\d+\.\s+', line):
                doc.add_paragraph(re.sub(r'^\d+\.\s+', '', line), style='List Number')
            else:
                doc.add_paragraph(line)
        buf = BytesIO()
        doc.save(buf)
        return buf.getvalue()


    @router.get("/api/research-memos/{memo_id}/download.docx")
    def download_research_memo_docx(memo_id: int):
        from io import BytesIO
        from fastapi.responses import StreamingResponse
        memo = get_research_memo(memo_id)
        content = _generate_memo_docx(memo["title"], memo["markdown"])
        filename = re.sub(r'[\\/:*?"<>|]+', '_', memo["title"]) + ".docx"
        return StreamingResponse(
            BytesIO(content),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
        )


    def _case_articles_docx_bytes(case_title: str, articles: list) -> bytes:
        from docx import Document

        doc = Document()
        doc.add_heading(f"{case_title or '案件'}关联文章", level=0)
        for idx, article in enumerate(articles):
            if idx:
                doc.add_page_break()
            add_article_to_docx(doc, article, case_title)
        buf = BytesIO()
        doc.save(buf)
        return buf.getvalue()


    def _case_research_articles(conn, case_id: int) -> tuple:
        project_id = ensure_case_research_project(conn, case_id)
        case = conn.execute("SELECT * FROM case_manager_cases WHERE id=?", (case_id,)).fetchone()
        articles = [
            dict(r)
            for r in conn.execute(
                """
            SELECT a.id, a.title, a.content, a.summary, a.source_type, a.source_url,
                   a.source_filename, a.source_localpath, a.created_at, rpa.created_at AS linked_at
            FROM research_project_articles rpa
            JOIN articles a ON a.id = rpa.article_id
            WHERE rpa.project_id=?
            ORDER BY rpa.created_at ASC, a.id ASC
            """,
                (project_id,),
            ).fetchall()
        ]
        return case, articles


    def _case_research_timeline_entries(conn, case_id: int, entry_type: str) -> tuple:
        table_map = {
            "ledger": "research_case_ledgers",
            "memo": "research_case_memo_entries",
        }
        table = table_map.get(entry_type)
        if not table:
            raise HTTPException(status_code=400, detail="记录类型不正确")
        project_id = ensure_case_research_project(conn, case_id)
        case = conn.execute("SELECT * FROM case_manager_cases WHERE id=?", (case_id,)).fetchone()
        entries = [
            dict(r)
            for r in conn.execute(
                f"""
            SELECT * FROM {table}
            WHERE project_id=?
            ORDER BY COALESCE(NULLIF(happened_at, ''), created_at) DESC, id DESC
            """,
                (project_id,),
            ).fetchall()
        ]
        return case, entries


    @router.get("/api/case-research/cases/{case_id}/articles/export")
    def export_case_research_articles(case_id: int):
        from fastapi.responses import StreamingResponse

        conn = get_db()
        case, articles = _case_research_articles(conn, case_id)
        conn.close()
        if not articles:
            raise HTTPException(status_code=404, detail="该案件尚未关联文章")
        case_title = case["title"] if case else "案件"
        safe_case = safe_export_filename(case_title, "案件")
        if len(articles) <= 2:
            content = _case_articles_docx_bytes(case_title, articles)
            filename = f"{safe_case}-关联文章.docx"
            return StreamingResponse(
                BytesIO(content),
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
            )
        zip_buf = BytesIO()
        folder = f"{safe_case}-关联文章"
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            index_lines = [f"{case_title}关联文章清单", ""]
            for idx, article in enumerate(articles, 1):
                title = article.get("title") or f"文章{idx}"
                docx_name = f"{idx:02d}-{safe_export_filename(title, f'文章{idx}')}.docx"
                zf.writestr(f"{folder}/{docx_name}", article_docx_bytes(article, case_title))
                index_lines.append(f"{idx}. {title}")
            zf.writestr(f"{folder}/关联文章清单.txt", "\n".join(index_lines))
        zip_buf.seek(0)
        filename = f"{safe_case}-关联文章.zip"
        return StreamingResponse(
            zip_buf,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
        )


    @router.get("/api/case-research/cases/{case_id}/ledgers/export")
    def export_case_research_ledgers(case_id: int):
        from fastapi.responses import StreamingResponse

        conn = get_db()
        case, entries = _case_research_timeline_entries(conn, case_id, "ledger")
        conn.commit()
        conn.close()
        case_title = case["title"] if case else "案件"
        content = _case_timeline_xlsx_bytes(case_title, entries, "案件台账")
        filename = f"{safe_export_filename(case_title, '案件')}-案件台账.xlsx"
        return StreamingResponse(
            BytesIO(content),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
        )


    @router.get("/api/case-research/cases/{case_id}/memo-entries/export")
    def export_case_research_memo_entries(case_id: int):
        from fastapi.responses import StreamingResponse

        conn = get_db()
        case, entries = _case_research_timeline_entries(conn, case_id, "memo")
        conn.commit()
        conn.close()
        case_title = case["title"] if case else "案件"
        content = _case_timeline_xlsx_bytes(case_title, entries, "案件备忘录")
        filename = f"{safe_export_filename(case_title, '案件')}-案件备忘录.xlsx"
        return StreamingResponse(
            BytesIO(content),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
        )

    return ResearchRoutes(router, add_article_to_research_project)
