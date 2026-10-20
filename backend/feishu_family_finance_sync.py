"""Pull family finance submissions from Feishu Bitable into Personal Center.

The Bitable form remains usable while APEX is offline.  This synchronizer runs
on startup and periodically afterwards, keeping an idempotent local ledger so
the same Feishu row can never create duplicate deposits or income records.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx
from fastapi import HTTPException

from .personal_center import (
    SHANGHAI_TZ,
    _income_types,
    _normalize_date,
    _save_deposit_record,
    _save_income_record,
    _text,
)


ROOT_DIR = Path(os.environ.get("LEGAL_KB_CONFIG_DIR", str(Path(__file__).resolve().parent.parent)))
CONFIG_PATH = ROOT_DIR / "local_feishu_family_finance_config.json"
APP_CONFIG_PATH = ROOT_DIR / "local_feishu_expense_config.json"
FIELDS = {
    "member": "填写人",
    "kind": "记录类型",
    "date": "填写时间",
    "cash": "现金存款金额",
    "fund": "公积金存款金额",
    "income_type": "收入类型",
    "income_amount": "收入金额",
    "status": "同步状态",
    "synced_at": "同步时间",
    "note": "同步说明",
}


def _now() -> str:
    return dt.datetime.now(SHANGHAI_TZ).isoformat(timespec="seconds")


def _sync_interval_seconds() -> float:
    try:
        return max(15.0, min(float(os.environ.get("FEISHU_FAMILY_FINANCE_SYNC_INTERVAL_SECONDS", "60")), 300.0))
    except ValueError:
        return 60.0


def _read_json(path: Path) -> Dict[str, str]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {str(key): _text(value) for key, value in raw.items()}
    except Exception:
        return {}


def _config() -> Dict[str, str]:
    # The approved Feishu application is already used for prepaid-expense
    # sync.  Reuse its credentials without duplicating the App Secret.
    config = _read_json(CONFIG_PATH)
    app_config = _read_json(APP_CONFIG_PATH)
    config.setdefault("app_id", app_config.get("app_id", ""))
    config.setdefault("app_secret", app_config.get("app_secret", ""))
    return config


def _configured(config: Optional[Dict[str, str]] = None) -> bool:
    config = config or _config()
    return all(config.get(key) for key in ("app_id", "app_secret", "app_token", "table_id"))


def _choice(value: Any) -> str:
    if isinstance(value, list):
        return _choice(value[0]) if value else ""
    if isinstance(value, dict):
        for key in ("name", "text", "value"):
            if key in value:
                return _choice(value[key])
    return _text(value)


def _number(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        raise ValueError("金额格式不正确")
    if number < 0:
        raise ValueError("金额不能为负数")
    return number


def _record_date(value: Any) -> str:
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit() and len(value.strip()) >= 11):
        return dt.datetime.fromtimestamp(float(value) / 1000, tz=SHANGHAI_TZ).date().isoformat()
    return _normalize_date(_text(value))


def ensure_schema(get_db: Callable[[], Any]) -> None:
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS pc_feishu_family_imports (
                source_record_id TEXT PRIMARY KEY,
                record_kind TEXT NOT NULL,
                local_record_id INTEGER NOT NULL,
                source_payload_hash TEXT NOT NULL,
                imported_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pc_feishu_family_sync_issues (
                source_record_id TEXT PRIMARY KEY,
                source_payload_hash TEXT NOT NULL,
                error_message TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pc_feishu_family_sync_state (
                id INTEGER PRIMARY KEY CHECK(id=1),
                last_attempt_at TEXT DEFAULT '', last_success_at TEXT DEFAULT '',
                last_result_json TEXT DEFAULT '{}', last_error TEXT DEFAULT '', updated_at TEXT NOT NULL
            );
        """)
        conn.execute("""INSERT OR IGNORE INTO pc_feishu_family_sync_state
            (id,last_attempt_at,last_success_at,last_result_json,last_error,updated_at)
            VALUES (1,'','','{}','',?)""", (_now(),))
        conn.commit()


class FeishuFamilyFinanceSync:
    def __init__(self, get_db: Callable[[], Any]):
        self.get_db = get_db
        self.lock: Optional[asyncio.Lock] = None
        self.token, self.token_expires_at = "", 0.0

    @staticmethod
    def _response(response: httpx.Response, fallback: str) -> Dict[str, Any]:
        try:
            payload = response.json()
        except Exception:
            payload = {}
        if response.status_code >= 400 or payload.get("code") not in (None, 0):
            raise RuntimeError(_text(payload.get("msg")) or fallback)
        return payload

    async def _token_for(self, client: httpx.AsyncClient, config: Dict[str, str]) -> str:
        now = asyncio.get_running_loop().time()
        if self.token and now < self.token_expires_at - 300:
            return self.token
        payload = self._response(
            await client.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": config["app_id"], "app_secret": config["app_secret"]},
            ),
            "飞书身份验证失败",
        )
        self.token = _text(payload.get("tenant_access_token"))
        if not self.token:
            raise RuntimeError("飞书未返回访问凭证")
        self.token_expires_at = now + int(payload.get("expire") or 7200)
        return self.token

    async def _records(self, client: httpx.AsyncClient, token: str, config: Dict[str, str]) -> List[Dict[str, Any]]:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{config['app_token']}/tables/{config['table_id']}/records/search"
        records: List[Dict[str, Any]] = []
        page_token = ""
        while True:
            params: Dict[str, Any] = {"page_size": 500}
            if page_token:
                params["page_token"] = page_token
            payload = self._response(
                await client.post(url, headers={"Authorization": f"Bearer {token}"}, params=params, json={"automatic_fields": True}),
                "无法读取飞书家庭财务记录",
            ).get("data", {})
            records.extend(payload.get("items") or [])
            if not payload.get("has_more"):
                return records
            page_token = _text(payload.get("page_token"))
            if not page_token:
                return records

    async def _writeback(self, client: httpx.AsyncClient, token: str, config: Dict[str, str], updates: List[Dict[str, Any]]) -> None:
        if not updates:
            return
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{config['app_token']}/tables/{config['table_id']}/records/batch_update"
        for index in range(0, len(updates), 500):
            self._response(
                await client.post(url, headers={"Authorization": f"Bearer {token}"}, json={"records": updates[index:index + 500]}),
                "无法回写飞书同步状态",
            )

    @staticmethod
    def _update(record_id: str, status: str, note: str) -> Dict[str, Any]:
        return {"record_id": record_id, "fields": {
            FIELDS["status"]: status,
            FIELDS["synced_at"]: int(dt.datetime.now(SHANGHAI_TZ).timestamp() * 1000),
            FIELDS["note"]: note[:500],
        }}

    def _save_issue(self, record_id: str, fingerprint: str, message: str) -> None:
        with self.get_db() as conn:
            conn.execute("""INSERT INTO pc_feishu_family_sync_issues
                (source_record_id,source_payload_hash,error_message,updated_at) VALUES (?,?,?,?)
                ON CONFLICT(source_record_id) DO UPDATE SET source_payload_hash=excluded.source_payload_hash,
                error_message=excluded.error_message,updated_at=excluded.updated_at""", (record_id, fingerprint, message, _now()))
            conn.commit()

    def _remember_import(self, record_id: str, kind: str, local_id: int, fingerprint: str) -> None:
        with self.get_db() as conn:
            conn.execute("""INSERT OR REPLACE INTO pc_feishu_family_imports
                (source_record_id,record_kind,local_record_id,source_payload_hash,imported_at) VALUES (?,?,?,?,?)""",
                (record_id, kind, local_id, fingerprint, _now()))
            conn.execute("DELETE FROM pc_feishu_family_sync_issues WHERE source_record_id=?", (record_id,))
            conn.commit()

    def _existing_legacy_import(self, record_id: str, kind: str) -> int:
        note = f"飞书记录 {record_id}"
        table, date_column = ("pc_deposit_records", "record_date") if kind == "存款" else ("pc_income_records", "income_date")
        with self.get_db() as conn:
            row = conn.execute(f"SELECT id FROM {table} WHERE note=? ORDER BY {date_column} DESC,id DESC LIMIT 1", (note,)).fetchone()
        return int(row["id"]) if row else 0

    def _member_id(self, name: str) -> int:
        with self.get_db() as conn:
            row = conn.execute("SELECT id FROM pc_family_members WHERE name=? AND active=1", (name,)).fetchone()
        if not row:
            raise ValueError(f"家庭成员“{name or '未填写'}”不存在或已停用，请先在 APEX 成员管理中维护")
        return int(row["id"])

    def _import(self, record_id: str, fields: Dict[str, Any], fingerprint: str) -> str:
        member_name = _choice(fields.get(FIELDS["member"]))
        kind = _choice(fields.get(FIELDS["kind"]))
        date = _record_date(fields.get(FIELDS["date"]))
        if kind not in ("存款", "收入"):
            raise ValueError("记录类型只能选择“存款”或“收入”")
        member_id = self._member_id(member_name)
        legacy_id = self._existing_legacy_import(record_id, kind)
        if legacy_id:
            self._remember_import(record_id, kind, legacy_id, fingerprint)
            return f"已导入 APEX {kind}记录 #{legacy_id}"
        if kind == "存款":
            cash, fund = _number(fields.get(FIELDS["cash"])), _number(fields.get(FIELDS["fund"]))
            if cash <= 0 and fund <= 0:
                raise ValueError("请至少填写现金存款金额或公积金存款金额")
            saved = _save_deposit_record(self.get_db, {
                "record_date": date, "note": f"飞书记录 {record_id}",
                "members": [{"name": member_name, "cash": cash, "fund": fund}],
            }, source="feishu")
        else:
            income_label = _choice(fields.get(FIELDS["income_type"]))
            amount = _number(fields.get(FIELDS["income_amount"]))
            if amount <= 0:
                raise ValueError("收入金额必须大于 0")
            type_by_label = {item["label"]: item["key"] for item in _income_types(self.get_db)}
            income_type = type_by_label.get(income_label)
            if not income_type:
                raise ValueError(f"收入类型“{income_label or '未填写'}”尚未在 APEX 中建立")
            saved = _save_income_record(self.get_db, {
                "income_date": date, "income_type": income_type, "amount": amount,
                "member_id": member_id, "note": f"飞书记录 {record_id}",
            }, source="feishu")
        local_id = int(saved["id"])
        self._remember_import(record_id, kind, local_id, fingerprint)
        return f"已导入 APEX {kind}记录 #{local_id}"

    async def sync(self) -> Dict[str, Any]:
        if self.lock is None:
            self.lock = asyncio.Lock()
        if self.lock.locked():
            return {"ok": True, "busy": True, "message": "家庭财务正在同步"}
        async with self.lock:
            config = _config()
            if not _configured(config):
                return {"ok": False, "configured": False, "message": "家庭财务飞书表单尚未配置"}
            result = {"imported": 0, "existing": 0, "invalid": 0, "writeback": 0}
            with self.get_db() as conn:
                conn.execute("UPDATE pc_feishu_family_sync_state SET last_attempt_at=?,updated_at=? WHERE id=1", (_now(), _now()))
                conn.commit()
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    token = await self._token_for(client, config)
                    updates: List[Dict[str, Any]] = []
                    for record in await self._records(client, token, config):
                        record_id, fields = _text(record.get("record_id")), record.get("fields") or {}
                        if not record_id:
                            continue
                        # A Bitable may contain empty rows that were never
                        # submitted through the form.  They are not finance
                        # entries and must neither be imported nor marked as
                        # needing correction.
                        if not _choice(fields.get(FIELDS["kind"])):
                            continue
                        fingerprint = hashlib.sha256(json.dumps(fields, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
                        with self.get_db() as conn:
                            imported = conn.execute("SELECT local_record_id,record_kind FROM pc_feishu_family_imports WHERE source_record_id=?", (record_id,)).fetchone()
                            issue = conn.execute("SELECT source_payload_hash,error_message FROM pc_feishu_family_sync_issues WHERE source_record_id=?", (record_id,)).fetchone()
                        if imported:
                            result["existing"] += 1
                            updates.append(self._update(record_id, "已同步", f"已导入 APEX {imported['record_kind']}记录 #{imported['local_record_id']}"))
                            continue
                        if issue and issue["source_payload_hash"] == fingerprint:
                            result["invalid"] += 1
                            updates.append(self._update(record_id, "需修正", _text(issue["error_message"])))
                            continue
                        try:
                            note = self._import(record_id, fields, fingerprint)
                            result["imported"] += 1
                            updates.append(self._update(record_id, "已同步", note))
                        except (ValueError, HTTPException) as exc:
                            message = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
                            self._save_issue(record_id, fingerprint, message)
                            result["invalid"] += 1
                            updates.append(self._update(record_id, "需修正", message))
                    await self._writeback(client, token, config, updates)
                    result["writeback"] = len(updates)
                stamp = _now()
                with self.get_db() as conn:
                    conn.execute("UPDATE pc_feishu_family_sync_state SET last_success_at=?,last_result_json=?,last_error='',updated_at=? WHERE id=1", (stamp, json.dumps(result, ensure_ascii=False), stamp))
                    conn.commit()
                return {"ok": True, **result}
            except Exception as exc:
                message = str(exc)[:500] or "飞书同步失败"
                with self.get_db() as conn:
                    conn.execute("UPDATE pc_feishu_family_sync_state SET last_result_json=?,last_error=?,updated_at=? WHERE id=1", (json.dumps(result, ensure_ascii=False), message, _now()))
                    conn.commit()
                return {"ok": False, "message": message, **result}


def register_feishu_family_finance_sync(app: Any, get_db: Callable[[], Any]) -> None:
    ensure_schema(get_db)
    syncer = FeishuFamilyFinanceSync(get_db)
    scheduler_task: Optional[asyncio.Task] = None

    @app.post("/api/personal-center/family/feishu-sync")
    async def sync_family_finance():
        return await syncer.sync()

    @app.get("/api/personal-center/family/feishu-sync-status")
    def sync_family_finance_status():
        with get_db() as conn:
            row = conn.execute("SELECT * FROM pc_feishu_family_sync_state WHERE id=1").fetchone()
        return dict(row) if row else {}

    async def scheduler_loop() -> None:
        await asyncio.sleep(1)
        while True:
            try:
                if _configured():
                    await syncer.sync()
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            await asyncio.sleep(_sync_interval_seconds())

    @app.on_event("startup")
    async def start_scheduler() -> None:
        nonlocal scheduler_task
        if scheduler_task is None or scheduler_task.done():
            scheduler_task = asyncio.create_task(scheduler_loop())

    @app.on_event("shutdown")
    async def stop_scheduler() -> None:
        nonlocal scheduler_task
        if scheduler_task:
            scheduler_task.cancel()
            try:
                await scheduler_task
            except asyncio.CancelledError:
                pass
            scheduler_task = None
