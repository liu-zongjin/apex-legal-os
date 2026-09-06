from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import threading
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse

SHANGHAI_TZ = dt.timezone(dt.timedelta(hours=8), name="Asia/Shanghai")

INCOME_TYPES = [
    {"key": "draft_award", "label": "起草裁决"},
    {"key": "quarter_bonus", "label": "季度奖金"},
    {"key": "year_end_bonus", "label": "年底奖金"},
    {"key": "salary", "label": "月工资"},
    {"key": "housing_fund", "label": "公积金"},
]
INCOME_TYPE_KEYS = {item["key"] for item in INCOME_TYPES}
INCOME_TYPE_LABELS = {item["key"]: item["label"] for item in INCOME_TYPES}
SCHEDULABLE_INCOME_TYPES = {"salary", "housing_fund"}

SESSION_TTL_SECONDS = 30 * 60
BIOMETRIC_CHALLENGE_TTL_SECONDS = 120
PASSWORD_ITERATIONS = 120_000
MAX_PASSWORD_LENGTH = 64
MIN_PASSWORD_LENGTH = 4

# 与 native-shell 的 Swift 代码共享的校验密钥。
# 作用：只有通过系统 Touch ID 验证的 native-shell 才能凭此密钥把挑战兑换为会话，
# 页面 JavaScript 无法伪造指纹验证结果。
_BIOMETRIC_BRIDGE_SECRET = os.environ.get("PC_BIOMETRIC_BRIDGE_SECRET", "apex-personal-center-biometric-2026-v1")

_sessions: Dict[str, float] = {}
_sessions_lock = threading.Lock()
_biometric_challenges: Dict[str, float] = {}
_challenges_lock = threading.Lock()


def _now_iso() -> str:
    return dt.datetime.now(SHANGHAI_TZ).isoformat(timespec="seconds")


def _today_iso() -> str:
    return dt.datetime.now(SHANGHAI_TZ).date().isoformat()


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _amount_to_cents(value: Any, *, allow_zero: bool = True) -> int:
    try:
        amount = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, AttributeError, ValueError):
        raise HTTPException(status_code=400, detail="金额格式不正确")
    if not amount.is_finite():
        raise HTTPException(status_code=400, detail="金额格式不正确")
    if amount < 0:
        raise HTTPException(status_code=400, detail="金额不能为负数")
    if not allow_zero and amount <= 0:
        raise HTTPException(status_code=400, detail="金额必须大于 0")
    quantized = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if amount != quantized:
        raise HTTPException(status_code=400, detail="金额最多保留两位小数")
    cents = int(quantized * 100)
    if cents > 9_999_999_999_99:
        raise HTTPException(status_code=400, detail="金额超出允许范围")
    return cents


def _normalize_date(value: Any, fallback: str = "") -> str:
    if value in (None, ""):
        return fallback or _today_iso()
    raw = _text(value).replace("/", "-").replace("年", "-").replace("月", "-").replace("日", "")
    raw = raw[:10]
    try:
        return dt.date.fromisoformat(raw).isoformat()
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式不正确")


def _row_dict(row: Any) -> Dict[str, Any]:
    return dict(row) if row else {}


def _hash_password(password: str, salt: str) -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_ITERATIONS,
    )
    return digest.hex()


def _new_session_token() -> str:
    return secrets.token_urlsafe(32)


def _issue_session() -> Dict[str, Any]:
    token = _new_session_token()
    deadline = dt.datetime.now(SHANGHAI_TZ).timestamp() + SESSION_TTL_SECONDS
    with _sessions_lock:
        _sessions[token] = deadline
    return {
        "token": token,
        "expires_at": dt.datetime.fromtimestamp(deadline, SHANGHAI_TZ).isoformat(timespec="seconds"),
        "ttl_seconds": SESSION_TTL_SECONDS,
    }


def _validate_session(token: str) -> bool:
    token = _text(token)
    if not token:
        return False
    now = dt.datetime.now(SHANGHAI_TZ).timestamp()
    with _sessions_lock:
        deadline = _sessions.get(token)
        if deadline is None:
            return False
        if deadline < now:
            _sessions.pop(token, None)
            return False
        _sessions[token] = now + SESSION_TTL_SECONDS
        return True


def _revoke_session(token: str) -> None:
    token = _text(token)
    if token:
        with _sessions_lock:
            _sessions.pop(token, None)


def ensure_personal_center_schema(get_db: Callable[[], Any]) -> None:
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS pc_security (
                id INTEGER PRIMARY KEY CHECK(id=1),
                password_hash TEXT NOT NULL DEFAULT '',
                password_salt TEXT NOT NULL DEFAULT '',
                biometric_enabled INTEGER NOT NULL DEFAULT 0,
                remember_session INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pc_family_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                role TEXT DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pc_deposit_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_date TEXT NOT NULL,
                total_cents INTEGER NOT NULL,
                cash_cents INTEGER NOT NULL DEFAULT 0,
                fund_cents INTEGER NOT NULL DEFAULT 0,
                note TEXT DEFAULT '',
                source TEXT NOT NULL DEFAULT 'manual',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_pc_deposit_records_date
                ON pc_deposit_records(record_date DESC, id DESC);
            CREATE TABLE IF NOT EXISTS pc_deposit_record_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id INTEGER NOT NULL,
                member_id INTEGER,
                member_name TEXT NOT NULL,
                cash_cents INTEGER NOT NULL DEFAULT 0,
                fund_cents INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(record_id) REFERENCES pc_deposit_records(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_pc_deposit_record_members_record
                ON pc_deposit_record_members(record_id);
            CREATE TABLE IF NOT EXISTS pc_income_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                income_date TEXT NOT NULL,
                income_type TEXT NOT NULL,
                amount_cents INTEGER NOT NULL,
                member_id INTEGER,
                case_id INTEGER,
                case_title TEXT DEFAULT '',
                note TEXT DEFAULT '',
                source TEXT NOT NULL DEFAULT 'manual',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_pc_income_records_date
                ON pc_income_records(income_date DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_pc_income_records_type
                ON pc_income_records(income_type);
            CREATE TABLE IF NOT EXISTS pc_income_types (
                type_key TEXT PRIMARY KEY,
                label TEXT NOT NULL UNIQUE,
                is_default INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pc_income_schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                schedule_key TEXT NOT NULL UNIQUE,
                member_id INTEGER,
                enabled INTEGER NOT NULL DEFAULT 1,
                day_of_month INTEGER NOT NULL DEFAULT 15,
                default_amount_cents INTEGER NOT NULL DEFAULT 0,
                note TEXT DEFAULT '',
                last_run_month TEXT DEFAULT '',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pc_income_member_schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id INTEGER NOT NULL,
                schedule_key TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 0,
                day_of_month INTEGER NOT NULL DEFAULT 15,
                default_amount_cents INTEGER NOT NULL DEFAULT 0,
                note TEXT DEFAULT '',
                last_run_month TEXT DEFAULT '',
                updated_at TEXT NOT NULL,
                UNIQUE(member_id, schedule_key),
                FOREIGN KEY(member_id) REFERENCES pc_family_members(id) ON DELETE CASCADE
            );
            """
        )
        conn.execute(
            """INSERT OR IGNORE INTO pc_security (id,password_hash,password_salt,biometric_enabled,updated_at)
               VALUES (1,'','',0,?)""",
            (_now_iso(),),
        )
        security_columns = {row["name"] for row in conn.execute("PRAGMA table_info(pc_security)").fetchall()}
        if "remember_session" not in security_columns:
            conn.execute("ALTER TABLE pc_security ADD COLUMN remember_session INTEGER NOT NULL DEFAULT 1")
        income_columns = {row["name"] for row in conn.execute("PRAGMA table_info(pc_income_records)").fetchall()}
        if "member_id" not in income_columns:
            conn.execute("ALTER TABLE pc_income_records ADD COLUMN member_id INTEGER")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pc_income_records_member ON pc_income_records(member_id)")
        schedule_columns = {row["name"] for row in conn.execute("PRAGMA table_info(pc_income_schedules)").fetchall()}
        if "member_id" not in schedule_columns:
            conn.execute("ALTER TABLE pc_income_schedules ADD COLUMN member_id INTEGER")
        # 旧版收入没有成员维度；首次升级时统一归入本人，确保“示丁某”视图可直接查看完整历史。
        legacy_income_count = conn.execute(
            "SELECT COUNT(*) FROM pc_income_records WHERE member_id IS NULL"
        ).fetchone()[0]
        if legacy_income_count:
            member_row = conn.execute(
                "SELECT id FROM pc_family_members WHERE name=?", ("示丁某",)
            ).fetchone()
            if member_row:
                owner_member_id = int(member_row["id"])
                conn.execute(
                    "UPDATE pc_family_members SET active=1,updated_at=? WHERE id=?",
                    (_now_iso(), owner_member_id),
                )
            else:
                next_order = conn.execute(
                    "SELECT COALESCE(MAX(sort_order),-1)+1 FROM pc_family_members"
                ).fetchone()[0]
                cursor = conn.execute(
                    """INSERT INTO pc_family_members (name,role,active,sort_order,created_at,updated_at)
                       VALUES (?, '本人', 1, ?, ?, ?)""",
                    ("示丁某", int(next_order), _now_iso(), _now_iso()),
                )
                owner_member_id = int(cursor.lastrowid)
            conn.execute(
                "UPDATE pc_income_records SET member_id=? WHERE member_id IS NULL",
                (owner_member_id,),
            )
            conn.execute(
                "UPDATE pc_income_schedules SET member_id=? WHERE member_id IS NULL",
                (owner_member_id,),
            )
        for index, item in enumerate(INCOME_TYPES):
            conn.execute(
                """INSERT OR IGNORE INTO pc_income_types
                   (type_key,label,is_default,sort_order,created_at) VALUES (?,?,?,?,?)""",
                (item["key"], item["label"], 1, index, _now_iso()),
            )
        for key, label in (("salary", "月工资"), ("housing_fund", "公积金")):
            conn.execute(
                """INSERT OR IGNORE INTO pc_income_schedules
                   (schedule_key,enabled,day_of_month,default_amount_cents,note,last_run_month,updated_at)
                   VALUES (?,1,15,0,?,'',?)""",
                (key, f"{label}自动记录", _now_iso()),
            )
        # 将旧的全局工资/公积金计划迁移到对应成员；新表允许每位成员拥有独立设置。
        conn.execute(
            """INSERT OR IGNORE INTO pc_income_member_schedules
               (member_id,schedule_key,enabled,day_of_month,default_amount_cents,note,last_run_month,updated_at)
               SELECT member_id,schedule_key,enabled,day_of_month,default_amount_cents,note,last_run_month,updated_at
               FROM pc_income_schedules WHERE member_id IS NOT NULL"""
        )
        conn.commit()


def _income_types(get_db: Callable[[], Any]) -> List[Dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT type_key,label,is_default,sort_order FROM pc_income_types
               ORDER BY is_default DESC,sort_order ASC,label COLLATE NOCASE ASC"""
        ).fetchall()
    return [
        {
            "key": _text(row["type_key"]),
            "label": _text(row["label"]),
            "is_default": bool(row["is_default"]),
        }
        for row in rows
    ]


def _income_type_labels(get_db: Callable[[], Any]) -> Dict[str, str]:
    return {item["key"]: item["label"] for item in _income_types(get_db)}


def _create_income_type(get_db: Callable[[], Any], payload: Any) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="收入类型格式不正确")
    label = _text(payload.get("label"))
    if not label or len(label) > 30:
        raise HTTPException(status_code=400, detail="收入类型名称需为 1 到 30 个字符")
    with get_db() as conn:
        exists = conn.execute("SELECT 1 FROM pc_income_types WHERE label=? COLLATE NOCASE", (label,)).fetchone()
        if exists:
            raise HTTPException(status_code=400, detail="该收入类型已存在")
        type_key = f"custom_{secrets.token_hex(8)}"
        conn.execute(
            """INSERT INTO pc_income_types (type_key,label,is_default,sort_order,created_at)
               VALUES (?,?,0,0,?)""",
            (type_key, label, _now_iso()),
        )
        conn.commit()
    return _income_types(get_db)


def _delete_income_type(get_db: Callable[[], Any], type_key: str) -> List[Dict[str, Any]]:
    with get_db() as conn:
        item = conn.execute(
            "SELECT type_key,is_default FROM pc_income_types WHERE type_key=?", (type_key,)
        ).fetchone()
        if not item:
            raise HTTPException(status_code=404, detail="收入类型不存在")
        if bool(item["is_default"]):
            raise HTTPException(status_code=400, detail="默认收入类型不可删除")
        in_use = conn.execute(
            "SELECT 1 FROM pc_income_records WHERE income_type=? LIMIT 1", (type_key,)
        ).fetchone()
        if in_use:
            raise HTTPException(status_code=400, detail="该类型已有收入记录，暂不能删除")
        conn.execute("DELETE FROM pc_income_types WHERE type_key=?", (type_key,))
        conn.commit()
    return _income_types(get_db)


def _security_row(get_db: Callable[[], Any]) -> Dict[str, Any]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM pc_security WHERE id=1").fetchone()
    return _row_dict(row)


def _security_status(get_db: Callable[[], Any]) -> Dict[str, Any]:
    row = _security_row(get_db)
    password_set = bool(row.get("password_hash"))
    biometric_enabled = bool(row.get("biometric_enabled"))
    remember_session = bool(row.get("remember_session", 1))
    return {
        "password_set": password_set,
        "biometric_enabled": biometric_enabled,
        "remember_session": remember_session,
        "protected": password_set or biometric_enabled,
        "needs_setup": not password_set and not biometric_enabled,
    }


def _require_authenticated(get_db: Callable[[], Any], request: Request) -> str:
    status = _security_status(get_db)
    if not status["protected"]:
        return ""
    raw_token = _text(request.headers.get("x-pc-token"))
    if not raw_token:
        authorization = _text(request.headers.get("authorization"))
        if authorization.lower().startswith("bearer "):
            raw_token = authorization[7:].strip()
    if not _validate_session(raw_token):
        raise HTTPException(status_code=401, detail="需要先通过密码或指纹验证")
    return raw_token


def _set_password(get_db: Callable[[], Any], password: str, old_password: str = "") -> Dict[str, Any]:
    password = password or ""
    if not (MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH):
        raise HTTPException(status_code=400, detail=f"密码长度需在 {MIN_PASSWORD_LENGTH} 到 {MAX_PASSWORD_LENGTH} 位之间")
    row = _security_row(get_db)
    if row.get("password_hash"):
        if not old_password:
            raise HTTPException(status_code=400, detail="已设置过密码，请先输入当前密码")
        if not hmac.compare_digest(_hash_password(old_password, row["password_salt"] or ""), row["password_hash"]):
            raise HTTPException(status_code=400, detail="当前密码不正确")
    salt = secrets.token_hex(16)
    password_hash = _hash_password(password, salt)
    with get_db() as conn:
        conn.execute(
            """UPDATE pc_security SET password_hash=?,password_salt=?,updated_at=? WHERE id=1""",
            (password_hash, salt, _now_iso()),
        )
        conn.commit()
    with _sessions_lock:
        _sessions.clear()
    return {"ok": True, "message": "密码已设置" if not row.get("password_hash") else "密码已更新"}


def _verify_password(get_db: Callable[[], Any], password: str) -> Optional[Dict[str, Any]]:
    row = _security_row(get_db)
    if not row.get("password_hash"):
        return None
    if hmac.compare_digest(_hash_password(_text(password), row["password_salt"] or ""), row["password_hash"]):
        return _issue_session()
    return None


def _set_biometric_enabled(get_db: Callable[[], Any], enabled: bool) -> Dict[str, Any]:
    with get_db() as conn:
        conn.execute(
            "UPDATE pc_security SET biometric_enabled=?,updated_at=? WHERE id=1",
            (1 if enabled else 0, _now_iso()),
        )
        conn.commit()
    return {"ok": True, "biometric_enabled": bool(enabled)}


def _set_remember_session(get_db: Callable[[], Any], enabled: bool) -> Dict[str, Any]:
    with get_db() as conn:
        conn.execute(
            "UPDATE pc_security SET remember_session=?,updated_at=? WHERE id=1",
            (1 if enabled else 0, _now_iso()),
        )
        conn.commit()
    return {"ok": True, "remember_session": bool(enabled)}


def _new_biometric_challenge() -> str:
    challenge = secrets.token_urlsafe(24)
    deadline = dt.datetime.now(SHANGHAI_TZ).timestamp() + BIOMETRIC_CHALLENGE_TTL_SECONDS
    with _challenges_lock:
        _biometric_challenges[challenge] = deadline
    return challenge


def _consume_biometric_challenge(challenge: str, secret: str) -> bool:
    challenge = _text(challenge)
    if not challenge or not hmac.compare_digest(_text(secret), _BIOMETRIC_BRIDGE_SECRET):
        return False
    now = dt.datetime.now(SHANGHAI_TZ).timestamp()
    with _challenges_lock:
        deadline = _biometric_challenges.pop(challenge, None)
    return bool(deadline and deadline >= now)


def _family_members(get_db: Callable[[], Any], include_inactive: bool = False) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM pc_family_members"
    if not include_inactive:
        sql += " WHERE active=1"
    sql += " ORDER BY sort_order,id"
    with get_db() as conn:
        rows = conn.execute(sql).fetchall()
    return [_row_dict(row) for row in rows]


def _normalize_members_payload(payload: Any) -> List[Dict[str, Any]]:
    if not isinstance(payload, list):
        raise HTTPException(status_code=400, detail="家庭成员明细格式不正确")
    normalized: List[Dict[str, Any]] = []
    seen_names = set()
    for item in payload:
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="家庭成员明细格式不正确")
        name = _text(item.get("name"))[:40]
        if not name:
            continue
        if name in seen_names:
            raise HTTPException(status_code=400, detail=f"家庭成员“{name}”重复填写")
        seen_names.add(name)
        normalized.append(
            {
                "name": name,
                "cash_cents": _amount_to_cents(item.get("cash")),
                "fund_cents": _amount_to_cents(item.get("fund")),
            }
        )
    if not normalized:
        raise HTTPException(status_code=400, detail="请至少填写一位家庭成员的存款信息")
    return normalized


def _save_deposit_record(
    get_db: Callable[[], Any],
    payload: Dict[str, Any],
    *,
    record_id: int = 0,
    source: str = "manual",
) -> Dict[str, Any]:
    member_items = _normalize_members_payload(payload.get("members"))
    record_date = _normalize_date(payload.get("record_date"))
    note = _text(payload.get("note"))[:300]
    total_cents = sum(item["cash_cents"] + item["fund_cents"] for item in member_items)
    cash_cents = sum(item["cash_cents"] for item in member_items)
    fund_cents = sum(item["fund_cents"] for item in member_items)
    stamp = _now_iso()
    with get_db() as conn:
        if record_id:
            existing = conn.execute("SELECT id FROM pc_deposit_records WHERE id=?", (record_id,)).fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail="家庭存款记录不存在")
            conn.execute(
                """UPDATE pc_deposit_records
                   SET record_date=?,total_cents=?,cash_cents=?,fund_cents=?,note=?,updated_at=?
                   WHERE id=?""",
                (record_date, total_cents, cash_cents, fund_cents, note, stamp, record_id),
            )
            conn.execute("DELETE FROM pc_deposit_record_members WHERE record_id=?", (record_id,))
            saved_id = record_id
        else:
            cursor = conn.execute(
                """INSERT INTO pc_deposit_records
                   (record_date,total_cents,cash_cents,fund_cents,note,source,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (record_date, total_cents, cash_cents, fund_cents, note, source, stamp, stamp),
            )
            saved_id = int(cursor.lastrowid)
        for item in member_items:
            member_row = conn.execute(
                "SELECT id FROM pc_family_members WHERE name=? AND active=1", (item["name"],)
            ).fetchone()
            conn.execute(
                """INSERT INTO pc_deposit_record_members
                   (record_id,member_id,member_name,cash_cents,fund_cents)
                   VALUES (?,?,?,?,?)""",
                (
                    saved_id,
                    int(member_row["id"]) if member_row else None,
                    item["name"],
                    item["cash_cents"],
                    item["fund_cents"],
                ),
            )
        conn.commit()
        row = conn.execute("SELECT * FROM pc_deposit_records WHERE id=?", (saved_id,)).fetchone()
        member_rows = conn.execute(
            """SELECT member_name,cash_cents,fund_cents FROM pc_deposit_record_members
               WHERE record_id=? ORDER BY id""",
            (saved_id,),
        ).fetchall()
    return _serialize_deposit_record(_row_dict(row), member_rows)


def _serialize_deposit_record(row: Dict[str, Any], member_rows: Optional[List[Any]] = None) -> Dict[str, Any]:
    item = dict(row)
    for key in ("total_cents", "cash_cents", "fund_cents"):
        item[key.replace("_cents", "")] = int(item.get(key) or 0) / 100
    if member_rows is not None:
        members = []
        for member_row in member_rows:
            member = _row_dict(member_row)
            members.append(
                {
                    "name": _text(member.get("member_name")),
                    "cash": int(member.get("cash_cents") or 0) / 100,
                    "fund": int(member.get("fund_cents") or 0) / 100,
                }
            )
        item["members"] = members
    item["source_label"] = "自动记录" if item.get("source") == "auto" else "手动记录"
    return item


def _query_deposit_records(
    get_db: Callable[[], Any],
    *,
    date_from: str = "",
    date_to: str = "",
    member_id: str = "",
    q: str = "",
    limit: int = 2000,
) -> List[Dict[str, Any]]:
    selected_member_name = ""
    if member_id:
        try:
            normalized_member_id = int(member_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="家庭成员不正确")
        with get_db() as conn:
            member_row = conn.execute(
                "SELECT name FROM pc_family_members WHERE id=? AND active=1", (normalized_member_id,)
            ).fetchone()
        if not member_row:
            raise HTTPException(status_code=400, detail="家庭成员不存在或已停用")
        selected_member_name = _text(member_row["name"])
    where = ["1=1"]
    args: List[Any] = []
    if date_from:
        where.append("r.record_date>=?")
        args.append(_normalize_date(date_from))
    if date_to:
        where.append("r.record_date<=?")
        args.append(_normalize_date(date_to))
    if q:
        token = f"%{_text(q)}%"
        where.append("(r.note LIKE ? OR EXISTS (SELECT 1 FROM pc_deposit_record_members m WHERE m.record_id=r.id AND m.member_name LIKE ?))")
        args.extend([token, token])
    sql = f"""SELECT r.* FROM pc_deposit_records r
              WHERE {' AND '.join(where)}
              ORDER BY r.record_date DESC,r.id DESC
              LIMIT ?"""
    args.append(max(1, min(int(limit), 5000)))
    with get_db() as conn:
        rows = conn.execute(sql, args).fetchall()
        member_rows = conn.execute(
            """SELECT record_id,member_name,cash_cents,fund_cents FROM pc_deposit_record_members
               WHERE record_id IN (SELECT id FROM pc_deposit_records ORDER BY record_date DESC,id DESC LIMIT 5000)
               ORDER BY id"""
        ).fetchall()
    by_record: Dict[int, List[Any]] = {}
    for member_row in member_rows:
        by_record.setdefault(int(member_row["record_id"]), []).append(member_row)
    items = [_serialize_deposit_record(_row_dict(row), by_record.get(int(row["id"]), [])) for row in rows]
    if not selected_member_name:
        return items
    selected_items: List[Dict[str, Any]] = []
    for item in items:
        member = next((entry for entry in item.get("members", []) if entry.get("name") == selected_member_name), None)
        if not member:
            continue
        item["members"] = [member]
        item["cash"] = member["cash"]
        item["fund"] = member["fund"]
        item["total"] = member["cash"] + member["fund"]
        selected_items.append(item)
    return selected_items


def _save_income_record(
    get_db: Callable[[], Any],
    payload: Dict[str, Any],
    *,
    record_id: int = 0,
    source: str = "manual",
) -> Dict[str, Any]:
    income_type = _text(payload.get("income_type"))
    amount_cents = _amount_to_cents(payload.get("amount"), allow_zero=False)
    income_date = _normalize_date(payload.get("income_date"))
    note = _text(payload.get("note"))[:300]
    raw_member_id = payload.get("member_id")
    member_id = None
    if raw_member_id not in (None, "", 0):
        try:
            member_id = int(raw_member_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="家庭成员不正确")
    case_id = payload.get("case_id")
    case_title = ""
    with get_db() as conn:
        if member_id is not None:
            member_row = conn.execute(
                "SELECT id FROM pc_family_members WHERE id=? AND active=1", (member_id,)
            ).fetchone()
            if not member_row:
                raise HTTPException(status_code=400, detail="家庭成员不存在或已停用")
        type_row = conn.execute(
            "SELECT type_key FROM pc_income_types WHERE type_key=?", (income_type,)
        ).fetchone()
        if not type_row:
            raise HTTPException(status_code=400, detail="收入类型不正确")
        if case_id not in (None, "", 0):
            case_row = conn.execute(
                "SELECT id,title FROM case_manager_cases WHERE id=?", (int(case_id),)
            ).fetchone()
            if not case_row:
                raise HTTPException(status_code=400, detail="关联案件不存在")
            case_id = int(case_row["id"])
            case_title = _text(case_row["title"])[:300]
        else:
            case_id = None
        stamp = _now_iso()
        if record_id:
            existing = conn.execute("SELECT id FROM pc_income_records WHERE id=?", (record_id,)).fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail="家庭收入记录不存在")
            conn.execute(
                """UPDATE pc_income_records
                   SET income_date=?,income_type=?,amount_cents=?,member_id=?,case_id=?,case_title=?,note=?,updated_at=?
                   WHERE id=?""",
                (income_date, income_type, amount_cents, member_id, case_id, case_title, note, stamp, record_id),
            )
            saved_id = record_id
        else:
            cursor = conn.execute(
                """INSERT INTO pc_income_records
                   (income_date,income_type,amount_cents,member_id,case_id,case_title,note,source,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (income_date, income_type, amount_cents, member_id, case_id, case_title, note, source, stamp, stamp),
            )
            saved_id = int(cursor.lastrowid)
        conn.commit()
        row = conn.execute("SELECT * FROM pc_income_records WHERE id=?", (saved_id,)).fetchone()
    return _serialize_income_record(_row_dict(row), _income_type_labels(get_db))


def _serialize_income_record(row: Dict[str, Any], labels: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    item = dict(row)
    item["amount"] = int(item.get("amount_cents") or 0) / 100
    item["income_type_label"] = (labels or INCOME_TYPE_LABELS).get(item.get("income_type"), item.get("income_type") or "")
    item["source_label"] = "自动记录" if item.get("source") == "auto" else "手动记录"
    item["member_name"] = _text(item.get("member_name"))
    return item


def _query_income_records(
    get_db: Callable[[], Any],
    *,
    date_from: str = "",
    date_to: str = "",
    income_type: str = "",
    member_id: str = "",
    q: str = "",
    limit: int = 2000,
) -> List[Dict[str, Any]]:
    where = ["1=1"]
    args: List[Any] = []
    if date_from:
        where.append("income_date>=?")
        args.append(_normalize_date(date_from))
    if date_to:
        where.append("income_date<=?")
        args.append(_normalize_date(date_to))
    if income_type:
        if income_type not in _income_type_labels(get_db):
            raise HTTPException(status_code=400, detail="收入类型不正确")
        where.append("income_type=?")
        args.append(income_type)
    if member_id:
        try:
            normalized_member_id = int(member_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="家庭成员不正确")
        if normalized_member_id <= 0:
            raise HTTPException(status_code=400, detail="家庭成员不正确")
        where.append("r.member_id=?")
        args.append(normalized_member_id)
    if q:
        token = f"%{_text(q)}%"
        where.append("(case_title LIKE ? OR note LIKE ?)")
        args.extend([token, token])
    sql = f"""SELECT r.*,m.name AS member_name FROM pc_income_records r
              LEFT JOIN pc_family_members m ON m.id=r.member_id
              WHERE {' AND '.join(where)}
              ORDER BY r.income_date DESC,r.id DESC
              LIMIT ?"""
    args.append(max(1, min(int(limit), 5000)))
    with get_db() as conn:
        rows = conn.execute(sql, args).fetchall()
    labels = _income_type_labels(get_db)
    return [_serialize_income_record(_row_dict(row), labels) for row in rows]


def _income_schedules(get_db: Callable[[], Any]) -> List[Dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT m.id AS member_id,m.name AS member_name,k.schedule_key,
                      COALESCE(s.enabled,0) AS enabled,COALESCE(s.day_of_month,15) AS day_of_month,
                      COALESCE(s.default_amount_cents,0) AS default_amount_cents,
                      COALESCE(s.note,'') AS note,COALESCE(s.last_run_month,'') AS last_run_month
               FROM pc_family_members m
               CROSS JOIN (SELECT 'salary' AS schedule_key UNION ALL SELECT 'housing_fund') k
               LEFT JOIN pc_income_member_schedules s ON s.member_id=m.id AND s.schedule_key=k.schedule_key
               WHERE m.active=1 ORDER BY m.sort_order,m.id,k.schedule_key"""
        ).fetchall()
    labels = _income_type_labels(get_db)
    items: List[Dict[str, Any]] = []
    for row in rows:
        item = _row_dict(row)
        item["default_amount"] = int(item.get("default_amount_cents") or 0) / 100
        item["income_type_label"] = labels.get(item.get("schedule_key"), item.get("schedule_key") or "")
        item["enabled"] = bool(item.get("enabled"))
        items.append(item)
    return items


def _save_income_schedules(get_db: Callable[[], Any], payload: Any) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("schedules"), list):
        raise HTTPException(status_code=400, detail="自动记录设置格式不正确")
    allowed_keys = {"salary", "housing_fund"}
    seen = set()
    with get_db() as conn:
        for item in payload["schedules"]:
            if not isinstance(item, dict):
                raise HTTPException(status_code=400, detail="自动记录设置格式不正确")
            key = _text(item.get("schedule_key"))
            if key not in allowed_keys:
                raise HTTPException(status_code=400, detail="自动记录类型不正确")
            raw_member_id = item.get("member_id")
            if raw_member_id in (None, "", 0):
                raise HTTPException(status_code=400, detail="自动记录需指定家庭成员")
            try:
                member_id = int(raw_member_id)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="家庭成员不正确")
            marker = (member_id, key)
            if marker in seen:
                raise HTTPException(status_code=400, detail="自动记录类型重复")
            seen.add(marker)
            member_row = conn.execute(
                "SELECT id FROM pc_family_members WHERE id=? AND active=1", (member_id,)
            ).fetchone()
            if not member_row:
                raise HTTPException(status_code=400, detail="家庭成员不存在或已停用")
            day_of_month = int(item.get("day_of_month") or 15)
            if not 1 <= day_of_month <= 28:
                raise HTTPException(status_code=400, detail="自动记录日期需在 1 到 28 日之间")
            default_amount_cents = _amount_to_cents(item.get("default_amount"))
            conn.execute(
                """INSERT INTO pc_income_member_schedules
                   (member_id,schedule_key,enabled,day_of_month,default_amount_cents,note,last_run_month,updated_at)
                   VALUES (?,?,?,?,?,'','',?)
                   ON CONFLICT(member_id,schedule_key) DO UPDATE SET
                   enabled=excluded.enabled,day_of_month=excluded.day_of_month,
                   default_amount_cents=excluded.default_amount_cents,updated_at=excluded.updated_at""",
                (
                    member_id,
                    key,
                    1 if bool(item.get("enabled", True)) else 0,
                    day_of_month,
                    default_amount_cents,
                    _now_iso(),
                ),
            )
        conn.commit()
    return _income_schedules(get_db)


def _auto_run_due_schedules(get_db: Callable[[], Any]) -> Dict[str, Any]:
    """把已到期但尚未记录的月工资/公积金账期补录为收入记录。"""
    today = dt.datetime.now(SHANGHAI_TZ).date()
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM pc_income_member_schedules WHERE enabled=1").fetchall()
    created: List[Dict[str, Any]] = []
    for row in rows:
        schedule = _row_dict(row)
        schedule_key = schedule.get("schedule_key")
        if schedule_key not in SCHEDULABLE_INCOME_TYPES:
            continue
        day_of_month = max(1, min(28, int(schedule.get("day_of_month") or 15)))
        default_cents = int(schedule.get("default_amount_cents") or 0)
        if default_cents <= 0:
            continue
        last_run_month = _text(schedule.get("last_run_month"))[:7]
        if last_run_month:
            cursor_month = _next_month(last_run_month)
        else:
            cursor_month = _month_before_last_run(get_db, schedule_key, schedule.get("member_id")) or today.strftime("%Y-%m")
        limit_month = today.strftime("%Y-%m")
        guard = 0
        while cursor_month and cursor_month <= limit_month and guard < 24:
            guard += 1
            try:
                year, month = int(cursor_month[:4]), int(cursor_month[5:7])
                target_date = dt.date(year, month, min(day_of_month, 28))
            except ValueError:
                cursor_month = _next_month(cursor_month)
                continue
            if today >= target_date:
                saved = _save_income_record(
                    get_db,
                    {
                        "income_type": schedule_key,
                        "amount": default_cents / 100,
                        "income_date": target_date.isoformat(),
                        "member_id": schedule.get("member_id"),
                        "note": f"自动记录 · {INCOME_TYPE_LABELS.get(schedule_key, '')}（每月 {day_of_month} 日）",
                    },
                    source="auto",
                )
                created.append(saved)
                last_run_month = cursor_month
            cursor_month = _next_month(cursor_month)
        if last_run_month and last_run_month != schedule.get("last_run_month"):
            with get_db() as conn:
                conn.execute(
                    "UPDATE pc_income_member_schedules SET last_run_month=?,updated_at=? WHERE id=?",
                    (last_run_month, _now_iso(), schedule.get("id")),
                )
                conn.commit()
    return {"ok": True, "created": created}


def _next_month(month: str) -> str:
    try:
        year, value = int(month[:4]), int(month[5:7])
        if value == 12:
            return f"{year + 1}-01"
        return f"{year}-{value + 1:02d}"
    except ValueError:
        return ""


def _month_before_last_run(get_db: Callable[[], Any], schedule_key: str, member_id: Any = None) -> str:
    """没有账期记录时，从最近一条同类自动收入的下一个月开始补录。"""
    with get_db() as conn:
        row = conn.execute(
            """SELECT income_date FROM pc_income_records
               WHERE income_type=? AND source='auto' AND member_id IS ?
               ORDER BY income_date DESC,id DESC LIMIT 1""",
            (schedule_key, member_id),
        ).fetchone()
    if row:
        try:
            date = dt.date.fromisoformat(_text(row["income_date"])[:10])
            return _next_month(date.strftime("%Y-%m"))
        except ValueError:
            pass
    return ""


def _family_stats(get_db: Callable[[], Any], member_id: str = "") -> Dict[str, Any]:
    records = _query_deposit_records(get_db, member_id=member_id, limit=5000)
    records_asc = list(reversed(records))
    latest = records[0] if records else None
    members = _family_members(get_db)
    return {
        "latest": latest,
        "latest_total": (latest or {}).get("total", 0),
        "latest_cash": (latest or {}).get("cash", 0),
        "latest_fund": (latest or {}).get("fund", 0),
        "record_count": len(records),
        "members": members,
        "selected_member_id": member_id,
        "series": [
            {
                "record_date": item["record_date"],
                "total": item["total"],
                "cash": item["cash"],
                "fund": item["fund"],
            }
            for item in records_asc
        ],
    }


def _income_stats(get_db: Callable[[], Any], member_id: str = "", date_from: str = "", date_to: str = "") -> Dict[str, Any]:
    conditions: List[str] = []
    args: List[Any] = []
    if member_id:
        try:
            normalized_member_id = int(member_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="家庭成员不正确")
        if normalized_member_id <= 0:
            raise HTTPException(status_code=400, detail="家庭成员不正确")
        conditions.append("member_id=?")
        args.append(normalized_member_id)
    if date_from:
        conditions.append("income_date>=?")
        args.append(date_from)
    if date_to:
        conditions.append("income_date<=?")
        args.append(date_to)
    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    condition_sql = " AND ".join(conditions) if conditions else ""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT income_type,SUM(amount_cents) AS cents,COUNT(*) AS count
               FROM pc_income_records%s GROUP BY income_type""" % where, args
        ).fetchall()
        month_rows = conn.execute(
            """SELECT substr(income_date,1,7) AS month,SUM(amount_cents) AS cents
               FROM pc_income_records%s GROUP BY substr(income_date,1,7)
               ORDER BY month""" % where, args
        ).fetchall()
        auto_rows = conn.execute(
            """SELECT income_type,income_date FROM pc_income_records
               WHERE source='auto'%s ORDER BY income_date DESC,id DESC""" % (f" AND {condition_sql}" if condition_sql else ""), args
        ).fetchall()
        total = conn.execute("SELECT COALESCE(SUM(amount_cents),0) FROM pc_income_records" + where, args).fetchone()[0]
        month = dt.datetime.now(SHANGHAI_TZ).strftime("%Y-%m")
        month_total = conn.execute(
            "SELECT COALESCE(SUM(amount_cents),0) FROM pc_income_records WHERE substr(income_date,1,7)=?" + (f" AND {condition_sql}" if condition_sql else ""),
            [month, *args],
        ).fetchone()[0]
        if date_from or date_to:
            try:
                start = dt.date.fromisoformat(str(date_from)) if date_from else dt.date.fromisoformat(str(date_to))
                end = dt.date.fromisoformat(str(date_to)) if date_to else dt.date.fromisoformat(str(date_from))
            except ValueError:
                start = end = dt.date.today()
            if start > end:
                start, end = end, start
        else:
            range_row = conn.execute(
                "SELECT MIN(income_date) AS min_date, MAX(income_date) AS max_date FROM pc_income_records" + where, args
            ).fetchone()
            try:
                start = dt.date.fromisoformat(str(range_row["min_date"])) if range_row["min_date"] else dt.date.today()
                end = dt.date.fromisoformat(str(range_row["max_date"])) if range_row["max_date"] else dt.date.today()
            except ValueError:
                start = end = dt.date.today()
        period_months = max(1, (end.year - start.year) * 12 + (end.month - start.month) + 1)
        member_where = " WHERE member_id=?" if member_id else ""
        member_args = [normalized_member_id] if member_id else []
        available_rows = conn.execute(
            """SELECT DISTINCT substr(income_date,1,7) AS month
               FROM pc_income_records%s ORDER BY month DESC""" % member_where, member_args
        ).fetchall()
    by_type = {
        _row_dict(row)["income_type"]: {
            "amount": int(_row_dict(row)["cents"] or 0) / 100,
            "count": int(_row_dict(row)["count"] or 0),
        }
        for row in rows
    }
    return {
        "total": int(total or 0) / 100,
        "month_total": int(month_total or 0) / 100,
        "month": month,
        "by_type": by_type,
        "monthly": [
            {"month": _row_dict(row)["month"], "amount": int(_row_dict(row)["cents"] or 0) / 100}
            for row in month_rows
        ],
        "period_total": int(total or 0) / 100,
        "period_months": period_months,
        "period_average": round((int(total or 0) / 100) / period_months, 2),
        "available_months": [str(_row_dict(row)["month"]) for row in available_rows],
        "last_auto": (
            {
                "income_type": _row_dict(auto_rows[0])["income_type"],
                "income_date": _row_dict(auto_rows[0])["income_date"],
            }
            if auto_rows
            else None
        ),
    }


def register_personal_center_routes(app: Any, get_db: Callable[[], Any], frontend_dir: Path) -> None:
    ensure_personal_center_schema(get_db)
    scheduler_task: Optional[asyncio.Task] = None

    @app.get("/personal-center")
    def personal_center_page():
        return FileResponse(
            str(frontend_dir / "personal-center.html"),
            headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
        )

    @app.get("/api/personal-center/security/status")
    def get_security_status():
        return _security_status(get_db)

    @app.post("/api/personal-center/security/set-password")
    async def set_security_password(request: Request):
        body = await request.json()
        return _set_password(get_db, _text(body.get("password")), _text(body.get("old_password")))

    @app.post("/api/personal-center/security/biometric/enable")
    async def enable_biometric(request: Request):
        """录入指纹：必须先用密码验证身份，且由 native-shell 通过 Touch ID 验证后调用。"""
        body = await request.json()
        row = _security_row(get_db)
        if row.get("password_hash"):
            verified = _verify_password(get_db, _text(body.get("password")))
            if not verified:
                raise HTTPException(status_code=400, detail="当前密码不正确")
        return _set_biometric_enabled(get_db, True)

    @app.post("/api/personal-center/security/biometric/disable")
    async def disable_biometric(request: Request):
        body = await request.json()
        if _security_status(get_db).get("password_set"):
            verified = _verify_password(get_db, _text(body.get("password")))
            if not verified:
                raise HTTPException(status_code=400, detail="当前密码不正确")
        return _set_biometric_enabled(get_db, False)

    @app.post("/api/personal-center/security/session-preference")
    async def set_session_preference(request: Request):
        body = await request.json()
        return _set_remember_session(get_db, bool(body.get("remember_session", True)))

    @app.post("/api/personal-center/verify/password")
    async def verify_password(request: Request):
        body = await request.json()
        session = _verify_password(get_db, _text(body.get("password")))
        if not session:
            raise HTTPException(status_code=401, detail="密码不正确")
        return {"ok": True, **session}

    @app.get("/api/personal-center/biometric/challenge")
    def get_biometric_challenge():
        """一次性挑战，由 native-shell 在 Touch ID 验证通过后兑换会话。"""
        return {"challenge": _new_biometric_challenge()}

    @app.post("/api/personal-center/verify/biometric")
    async def verify_biometric(request: Request):
        """由 native-shell(Swift)在 Touch ID 验证通过后调用，携带一次性挑战。"""
        body = await request.json()
        if not _consume_biometric_challenge(body.get("challenge"), body.get("secret")):
            raise HTTPException(status_code=401, detail="指纹验证凭证无效或已过期")
        return {"ok": True, **_issue_session()}

    @app.post("/api/personal-center/logout")
    async def logout(request: Request):
        _revoke_session(_text(request.headers.get("x-pc-token") or ""))
        return {"ok": True}

    @app.get("/api/personal-center/family/members")
    def list_family_members(request: Request):
        _require_authenticated(get_db, request)
        return {"items": _family_members(get_db, include_inactive=True)}

    @app.post("/api/personal-center/family/members")
    async def save_family_members(request: Request):
        _require_authenticated(get_db, request)
        body = await request.json()
        if not isinstance(body, dict) or not isinstance(body.get("items"), list):
            raise HTTPException(status_code=400, detail="家庭成员列表格式不正确")
        existing_names: Dict[str, int] = {}
        with get_db() as conn:
            for row in conn.execute("SELECT id,name FROM pc_family_members").fetchall():
                existing_names[_text(row["name"])] = int(row["id"])
        stamp = _now_iso()
        with get_db() as conn:
            seen = set()
            for index, item in enumerate(body["items"]):
                if not isinstance(item, dict):
                    raise HTTPException(status_code=400, detail="家庭成员格式不正确")
                name = _text(item.get("name"))[:40]
                if not name:
                    continue
                if name in seen:
                    raise HTTPException(status_code=400, detail=f"家庭成员“{name}”重复")
                seen.add(name)
                role = _text(item.get("role"))[:40]
                if name in existing_names:
                    conn.execute(
                        """UPDATE pc_family_members SET name=?,role=?,active=1,sort_order=?,updated_at=?
                           WHERE id=?""",
                        (name, role, index, stamp, existing_names[name]),
                    )
                else:
                    conn.execute(
                        """INSERT INTO pc_family_members (name,role,active,sort_order,created_at,updated_at)
                           VALUES (?,?,1,?,?,?)""",
                        (name, role, index, stamp, stamp),
                    )
            for name, member_id in existing_names.items():
                if name not in seen:
                    conn.execute(
                        "UPDATE pc_family_members SET active=0,updated_at=? WHERE id=?",
                        (stamp, member_id),
                    )
            conn.commit()
        return {"items": _family_members(get_db, include_inactive=True)}

    @app.get("/api/personal-center/family/records")
    def list_deposit_records(
        request: Request,
        date_from: str = "",
        date_to: str = "",
        member_id: str = "",
        q: str = "",
        limit: int = 2000,
    ):
        _require_authenticated(get_db, request)
        return {"items": _query_deposit_records(get_db, date_from=date_from, date_to=date_to, member_id=member_id, q=q, limit=limit)}

    @app.get("/api/personal-center/family/stats")
    def get_family_stats(request: Request, member_id: str = ""):
        _require_authenticated(get_db, request)
        return _family_stats(get_db, member_id=member_id)

    @app.post("/api/personal-center/family/records")
    async def create_deposit_record(request: Request):
        _require_authenticated(get_db, request)
        return _save_deposit_record(get_db, await request.json())

    @app.put("/api/personal-center/family/records/{record_id}")
    async def update_deposit_record(record_id: int, request: Request):
        _require_authenticated(get_db, request)
        return _save_deposit_record(get_db, await request.json(), record_id=record_id)

    @app.delete("/api/personal-center/family/records/{record_id}")
    def delete_deposit_record(record_id: int, request: Request):
        _require_authenticated(get_db, request)
        with get_db() as conn:
            existing = conn.execute("SELECT id FROM pc_deposit_records WHERE id=?", (record_id,)).fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail="家庭存款记录不存在")
            conn.execute("DELETE FROM pc_deposit_records WHERE id=?", (record_id,))
            conn.commit()
        return {"ok": True}

    @app.get("/api/personal-center/income/records")
    def list_income_records(
        request: Request,
        date_from: str = "",
        date_to: str = "",
        income_type: str = "",
        member_id: str = "",
        q: str = "",
        limit: int = 2000,
    ):
        _require_authenticated(get_db, request)
        return {
            "items": _query_income_records(
                get_db, date_from=date_from, date_to=date_to, income_type=income_type,
                member_id=member_id, q=q, limit=limit
            )
        }

    @app.get("/api/personal-center/income/stats")
    def get_income_stats(request: Request, member_id: str = "", date_from: str = "", date_to: str = ""):
        _require_authenticated(get_db, request)
        return _income_stats(get_db, member_id=member_id, date_from=date_from, date_to=date_to)

    @app.get("/api/personal-center/income/types")
    def get_income_types(request: Request):
        _require_authenticated(get_db, request)
        return {"items": _income_types(get_db)}

    @app.post("/api/personal-center/income/types")
    async def create_income_type(request: Request):
        _require_authenticated(get_db, request)
        return {"items": _create_income_type(get_db, await request.json())}

    @app.delete("/api/personal-center/income/types/{type_key}")
    def delete_income_type(type_key: str, request: Request):
        _require_authenticated(get_db, request)
        return {"items": _delete_income_type(get_db, type_key)}

    @app.post("/api/personal-center/income/records")
    async def create_income_record(request: Request):
        _require_authenticated(get_db, request)
        return _save_income_record(get_db, await request.json())

    @app.put("/api/personal-center/income/records/{record_id}")
    async def update_income_record(record_id: int, request: Request):
        _require_authenticated(get_db, request)
        return _save_income_record(get_db, await request.json(), record_id=record_id)

    @app.delete("/api/personal-center/income/records/{record_id}")
    def delete_income_record(record_id: int, request: Request):
        _require_authenticated(get_db, request)
        with get_db() as conn:
            existing = conn.execute("SELECT id FROM pc_income_records WHERE id=?", (record_id,)).fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail="家庭收入记录不存在")
            conn.execute("DELETE FROM pc_income_records WHERE id=?", (record_id,))
            conn.commit()
        return {"ok": True}

    @app.get("/api/personal-center/income/schedules")
    def get_income_schedules(request: Request):
        _require_authenticated(get_db, request)
        return {"items": _income_schedules(get_db)}

    @app.put("/api/personal-center/income/schedules")
    async def put_income_schedules(request: Request):
        _require_authenticated(get_db, request)
        return {"items": _save_income_schedules(get_db, await request.json())}

    async def scheduler_loop() -> None:
        await asyncio.sleep(5)
        while True:
            try:
                _auto_run_due_schedules(get_db)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            await asyncio.sleep(60)

    @app.on_event("startup")
    async def start_personal_center_scheduler():
        nonlocal scheduler_task
        if scheduler_task is None or scheduler_task.done():
            scheduler_task = asyncio.create_task(scheduler_loop())

    @app.on_event("shutdown")
    async def stop_personal_center_scheduler():
        nonlocal scheduler_task
        if scheduler_task:
            scheduler_task.cancel()
            try:
                await scheduler_task
            except asyncio.CancelledError:
                pass
            scheduler_task = None
