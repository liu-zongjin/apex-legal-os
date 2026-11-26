"""Immutable calculator snapshots owned by existing case memo entries."""
import datetime
import json
import sqlite3
from contextlib import closing
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

TITLES = {
    "interest": "利息计算",
    "litigation_arbitration": "诉讼仲裁费计算",
    "risk_agency": "风险代理律师费计算",
}


def add_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS calculator_memo_snapshots (
            memo_id INTEGER PRIMARY KEY REFERENCES research_case_memo_entries(id) ON DELETE CASCADE,
            case_id INTEGER NOT NULL,
            request_id TEXT NOT NULL,
            snapshot TEXT NOT NULL,
            UNIQUE(case_id, request_id)
        );
        CREATE TRIGGER IF NOT EXISTS delete_calculator_memo_snapshot
        AFTER DELETE ON research_case_memo_entries
        BEGIN
            DELETE FROM calculator_memo_snapshots WHERE memo_id=OLD.id;
        END;
    """)


class CalculationSnapshot(BaseModel):
    requestId: UUID
    type: Literal["interest", "litigation_arbitration", "risk_agency"]
    parameters: dict
    details: str = Field(min_length=1, max_length=400_000)


def create_router(get_db, ensure_project):
    router = APIRouter(tags=["calculator-memos"])

    @router.post("/api/case-research/cases/{case_id}/calculator-memos")
    def link_calculation(case_id: int, payload: CalculationSnapshot):
        try:
            snapshot = json.dumps({
                "type": payload.type,
                "parameters": payload.parameters,
                "details": payload.details,
            }, ensure_ascii=False, allow_nan=False)
        except (ValueError, TypeError, RecursionError):
            raise HTTPException(400, "计算快照格式无效") from None
        if len(snapshot) > 500_000:
            raise HTTPException(413, "计算明细过长，无法关联到案件")
        request_id = str(payload.requestId)
        now = datetime.datetime.now().isoformat(timespec="seconds")
        with closing(get_db()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            case = conn.execute("SELECT source_status FROM case_manager_cases WHERE id=?", (case_id,)).fetchone()
            if not case or case["source_status"] == "deleted":
                raise HTTPException(404, "案件不存在或已删除")
            row = conn.execute(
                "SELECT memo_id, snapshot FROM calculator_memo_snapshots WHERE case_id=? AND request_id=?",
                (case_id, request_id),
            ).fetchone()
            if row:
                if row["snapshot"] != snapshot:
                    raise HTTPException(409, "此关联请求已保存其他计算结果")
                return {"id": row["memo_id"], "existing": True}
            project_id = ensure_project(conn, case_id)
            memo_id = conn.execute(
                """INSERT INTO research_case_memo_entries
                   (project_id, title, content, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (project_id, TITLES[payload.type], payload.details, now, now),
            ).lastrowid
            conn.execute("INSERT INTO calculator_memo_snapshots VALUES (?, ?, ?, ?)",
                         (memo_id, case_id, request_id, snapshot))
            conn.execute("UPDATE research_projects SET updated_at=? WHERE id=?", (now, project_id))
        return {"id": memo_id, "existing": False}

    @router.get("/api/calculator-memos/{memo_id}")
    def get_calculation(memo_id: int):
        with closing(get_db()) as conn:
            row = conn.execute(
                """SELECT s.snapshot, m.created_at FROM calculator_memo_snapshots s
                   JOIN research_case_memo_entries m ON m.id=s.memo_id
                   JOIN research_projects p ON p.id=m.project_id
                   JOIN case_manager_cases c ON c.id=p.case_id AND c.id=s.case_id
                   WHERE s.memo_id=? AND COALESCE(c.source_status, 'active')<>'deleted'""",
                (memo_id,),
            ).fetchone()
        if not row:
            raise HTTPException(404, "计算记录不存在或所属案件已删除")
        return {**json.loads(row["snapshot"]), "createdAt": row["created_at"]}

    return router
