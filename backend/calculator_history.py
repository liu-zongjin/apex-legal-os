"""Local SQLite history storage for litigation/arbitration and risk-agency fee calculators."""

from __future__ import annotations

import datetime
import json
import sqlite3
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

CALCULATOR_HISTORY_TYPES = {"litigation_arbitration", "risk_agency"}


def add_schema(conn: sqlite3.Connection) -> None:
    """Create the calculator_history table and lookup index if missing."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS calculator_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            calculator_type TEXT NOT NULL CHECK(calculator_type IN ('litigation_arbitration', 'risk_agency')),
            amount REAL NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            note TEXT NOT NULL DEFAULT '',
            pinned INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_calculator_history_type_created
            ON calculator_history(calculator_type, created_at DESC);
        """
    )


class CalculatorHistoryCreateRequest(BaseModel):
    calculatorType: str
    amount: float
    payload: Dict[str, Any] = {}


class CalculatorHistoryUpdateRequest(BaseModel):
    note: Optional[str] = None
    pinned: Optional[bool] = None


def _calculator_history_row(row: sqlite3.Row) -> dict:
    try:
        payload = json.loads(row["payload_json"] or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        payload = {}
    return {
        "id": row["id"],
        "calculatorType": row["calculator_type"],
        "amount": row["amount"],
        "payload": payload if isinstance(payload, dict) else {},
        "note": row["note"] or "",
        "pinned": bool(row["pinned"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _validate_calculator_history_type(calculator_type: str) -> str:
    normalized = (calculator_type or "").strip()
    if normalized not in CALCULATOR_HISTORY_TYPES:
        raise HTTPException(status_code=400, detail="无效的计算记录类型")
    return normalized


def create_router(get_db: Callable[[], sqlite3.Connection]) -> APIRouter:
    """Create the APIRouter exposing calculator history endpoints."""
    router = APIRouter(tags=["calculator-history"])

    @router.get("/api/calculator-history/{calculator_type}")
    async def get_calculator_history(calculator_type: str, limit: int = Query(200, ge=1, le=500)):
        """读取保存在本机 SQLite 中的计算工具历史记录。"""
        calculator_type = _validate_calculator_history_type(calculator_type)
        with get_db() as conn:
            rows = conn.execute(
                """SELECT id, calculator_type, amount, payload_json, note, pinned, created_at, updated_at
                   FROM calculator_history
                   WHERE calculator_type = ?
                   ORDER BY pinned DESC, created_at DESC, id DESC
                   LIMIT ?""",
                (calculator_type, limit),
            ).fetchall()
        return {"history": [_calculator_history_row(row) for row in rows]}

    @router.post("/api/calculator-history")
    async def create_calculator_history(request: CalculatorHistoryCreateRequest):
        """保存一条诉讼仲裁费或风险代理律师费计算记录到本机 SQLite。"""
        calculator_type = _validate_calculator_history_type(request.calculatorType)
        if not (0 < request.amount < 1e15):
            raise HTTPException(status_code=400, detail="标的金额应大于0且不超过100万亿元")
        try:
            payload_json = json.dumps(request.payload or {}, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="历史记录数据格式无效") from exc
        if len(payload_json) > 20000:
            raise HTTPException(status_code=400, detail="历史记录内容过大")
        now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        with get_db() as conn:
            cursor = conn.execute(
                """INSERT INTO calculator_history
                   (calculator_type, amount, payload_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (calculator_type, request.amount, payload_json, now, now),
            )
            row = conn.execute(
                """SELECT id, calculator_type, amount, payload_json, note, pinned, created_at, updated_at
                   FROM calculator_history WHERE id = ?""",
                (cursor.lastrowid,),
            ).fetchone()
            conn.commit()
        return {"history": _calculator_history_row(row)}

    @router.put("/api/calculator-history/{record_id}")
    async def update_calculator_history(record_id: int, request: CalculatorHistoryUpdateRequest):
        """更新本机计算历史的备注或保存状态。"""
        fields, params = [], []
        if request.note is not None:
            fields.append("note = ?")
            params.append(str(request.note).strip()[:200])
        if request.pinned is not None:
            fields.append("pinned = ?")
            params.append(1 if request.pinned else 0)
        if not fields:
            raise HTTPException(status_code=400, detail="没有需要更新的内容")
        fields.append("updated_at = ?")
        params.append(datetime.datetime.now().astimezone().isoformat(timespec="seconds"))
        params.append(record_id)
        with get_db() as conn:
            cursor = conn.execute(
                f"UPDATE calculator_history SET {', '.join(fields)} WHERE id = ?", params
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="历史记录不存在")
            row = conn.execute(
                """SELECT id, calculator_type, amount, payload_json, note, pinned, created_at, updated_at
                   FROM calculator_history WHERE id = ?""",
                (record_id,),
            ).fetchone()
            conn.commit()
        return {"history": _calculator_history_row(row)}

    @router.delete("/api/calculator-history/{record_id}")
    async def delete_calculator_history(record_id: int):
        """删除一条本机计算历史记录。"""
        with get_db() as conn:
            cursor = conn.execute("DELETE FROM calculator_history WHERE id = ?", (record_id,))
            conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="历史记录不存在")
        return {"ok": True}

    @router.delete("/api/calculator-history")
    async def clear_calculator_history(
        calculator_type: str = Query(..., alias="calculatorType"),
        include_pinned: bool = Query(False, alias="includePinned"),
    ):
        """清空指定类型的本机计算历史；默认保留用户保存的记录。"""
        calculator_type = _validate_calculator_history_type(calculator_type)
        query = "DELETE FROM calculator_history WHERE calculator_type = ?"
        if not include_pinned:
            query += " AND pinned = 0"
        with get_db() as conn:
            cursor = conn.execute(query, (calculator_type,))
            conn.commit()
        return {"ok": True, "deleted": cursor.rowcount}

    return router
