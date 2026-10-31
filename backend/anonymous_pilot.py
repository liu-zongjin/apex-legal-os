"""Safeguards and fictional starter data for the disposable APEX mobile pilot."""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


PILOT_MODE_ENV = "APEX_ANONYMOUS_PILOT"
PILOT_DB_FILENAME = "apex-anonymous-pilot.db"
_REQUIRED_ENV = (
    "LEGAL_KB_RUNTIME_DIR",
    "LEGAL_KB_DB_PATH",
    "LEGAL_KB_UPLOAD_DIR",
    "LEGAL_KB_ARTICLE_IMAGE_DIR",
    "LEGAL_KB_DATA_DIR",
    "LEGAL_KB_ACCESS_PASSWORD",
    "LEGAL_KB_SESSION_SECRET",
)
_SECRET_SUFFIXES = ("_API_KEY", "_API_SECRET", "_ACCESS_TOKEN", "_AUTHORIZATION")
_PILOT_CREDENTIALS = {"LEGAL_KB_ACCESS_PASSWORD", "LEGAL_KB_SESSION_SECRET"}
_PLACEHOLDER_VALUES = {"", "change-me", "replace-me", "replace-with-a-random-secret"}


@dataclass(frozen=True)
class AnonymousPilotPaths:
    runtime_dir: Path
    database: Path
    uploads: Path
    article_images: Path
    service_data: Path


def _enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def validate_anonymous_pilot_environment(env: Mapping[str, str] | None = None) -> AnonymousPilotPaths:
    """Validate that a pilot cannot silently reuse a normal APEX data location."""
    values = os.environ if env is None else env
    if not _enabled(values.get(PILOT_MODE_ENV)):
        raise RuntimeError(f"{PILOT_MODE_ENV}=1 is required for the anonymous pilot")
    missing = [name for name in _REQUIRED_ENV if not str(values.get(name, "")).strip()]
    if missing:
        raise RuntimeError("匿名测试环境缺少配置：" + ", ".join(missing))

    runtime_dir = Path(str(values["LEGAL_KB_RUNTIME_DIR"])).expanduser().resolve()
    database = Path(str(values["LEGAL_KB_DB_PATH"])).expanduser().resolve()
    uploads = Path(str(values["LEGAL_KB_UPLOAD_DIR"])).expanduser().resolve()
    article_images = Path(str(values["LEGAL_KB_ARTICLE_IMAGE_DIR"])).expanduser().resolve()
    service_data = Path(str(values["LEGAL_KB_DATA_DIR"])).expanduser().resolve()
    for label, path in {
        "数据库": database,
        "上传目录": uploads,
        "图片目录": article_images,
        "服务数据目录": service_data,
    }.items():
        if path != runtime_dir and runtime_dir not in path.parents:
            raise RuntimeError(f"匿名测试{label}必须位于 LEGAL_KB_RUNTIME_DIR 内")
    if database.name != PILOT_DB_FILENAME:
        raise RuntimeError(f"匿名测试数据库必须命名为 {PILOT_DB_FILENAME}")

    for name, value in values.items():
        if not value or name in _PILOT_CREDENTIALS:
            continue
        if name.endswith(_SECRET_SUFFIXES):
            raise RuntimeError(f"匿名测试环境不允许设置外部服务密钥：{name}")
    for name in _PILOT_CREDENTIALS:
        if str(values.get(name, "")).strip().lower() in _PLACEHOLDER_VALUES:
            raise RuntimeError(f"匿名测试环境必须把 {name} 替换为随机值")
    return AnonymousPilotPaths(runtime_dir, database, uploads, article_images, service_data)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _insert(connection: sqlite3.Connection, table: str, values: Mapping[str, object]) -> int:
    columns = _table_columns(connection, table)
    accepted = {name: value for name, value in values.items() if name in columns}
    names = list(accepted)
    placeholders = ", ".join("?" for _ in names)
    connection.execute(
        f"INSERT OR IGNORE INTO {table} ({', '.join(names)}) VALUES ({placeholders})",
        [accepted[name] for name in names],
    )
    row = connection.execute(f"SELECT id FROM {table} WHERE rowid = last_insert_rowid()").fetchone()
    return int(row[0]) if row else 0


def seed_anonymous_pilot_data(connection: sqlite3.Connection) -> bool:
    """Add a small, clearly fictional workspace once without overwriting edits."""
    required_tables = {
        "app_preferences",
        "case_manager_clients",
        "case_manager_cases",
        "case_manager_parties",
        "case_manager_todos",
        "case_manager_hearings",
    }
    present = {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    missing = sorted(required_tables - present)
    if missing:
        raise RuntimeError("Stella 数据库尚未完成初始化：" + ", ".join(missing))
    marker = connection.execute(
        "SELECT 1 FROM app_preferences WHERE preference_key=?",
        ("apex.anonymous_pilot.seed_version",),
    ).fetchone()
    if marker:
        return False

    stamp = _now()
    clients = (
        ("云杉科技（虚构）", "示例联系人", "13800000301"),
        ("海岚贸易（虚构）", "演示联系人", "13800000402"),
    )
    client_ids: dict[str, int] = {}
    for name, contact, phone in clients:
        client_id = _insert(
            connection,
            "case_manager_clients",
            {
                "client_type": "单位",
                "name": name,
                "contact_person": contact,
                "phone": phone,
                "contacts_json": "[]",
                "data_source": "Stella 匿名测试样例",
                "created_at": stamp,
                "updated_at": stamp,
            },
        )
        if not client_id:
            row = connection.execute("SELECT id FROM case_manager_clients WHERE name=?", (name,)).fetchone()
            client_id = int(row[0]) if row else 0
        client_ids[name] = client_id

    cases = (
        ("云杉科技合同履行争议（虚构）", "合同纠纷", "一审", "云杉科技（虚构）", "准备答辩材料"),
        ("海岚贸易应收账款事项（虚构）", "买卖合同纠纷", "调解中", "海岚贸易（虚构）", "核对对账单与付款记录"),
    )
    case_ids: dict[str, int] = {}
    for title, case_type, stage, client_name, memo in cases:
        case_id = _insert(
            connection,
            "case_manager_cases",
            {
                "title": title,
                "case_type": case_type,
                "current_stage": stage,
                "memo": memo,
                "source_status": "active",
                "pinned": 1,
                "created_at": stamp,
                "updated_at": stamp,
            },
        )
        if not case_id:
            row = connection.execute("SELECT id FROM case_manager_cases WHERE title=?", (title,)).fetchone()
            case_id = int(row[0]) if row else 0
        case_ids[title] = case_id
        _insert(
            connection,
            "case_manager_parties",
            {
                "case_id": case_id,
                "client_id": client_ids[client_name],
                "party_group": "client",
                "role": "委托人",
                "name": client_name,
                "sort_order": 0,
                "created_at": stamp,
                "updated_at": stamp,
            },
        )

    first_case = case_ids[cases[0][0]]
    second_case = case_ids[cases[1][0]]
    _insert(
        connection,
        "case_manager_todos",
        {
            "case_id": first_case,
            "title": cases[0][0],
            "todo_title": "核对匿名测试材料清单",
            "remind_at": "2030-06-18T10:00:00",
            "status": "pending",
            "created_at": stamp,
            "updated_at": stamp,
        },
    )
    _insert(
        connection,
        "case_manager_hearings",
        {
            "case_id": second_case,
            "title": cases[1][0],
            "reminder_type": "演示日程",
            "hearing_at": "2030-06-20T14:30:00",
            "location": "线上演示会议室",
            "created_at": stamp,
            "updated_at": stamp,
        },
    )
    connection.execute(
        "INSERT INTO app_preferences(preference_key, value_json, updated_at) VALUES (?, ?, ?)",
        ("apex.anonymous_pilot.seed_version", '"2026.09.07"', stamp),
    )
    connection.commit()
    return True


def prepare_anonymous_pilot() -> AnonymousPilotPaths:
    """Initialise the isolated runtime and its fictional records before serving it."""
    settings = validate_anonymous_pilot_environment()
    for directory in (settings.runtime_dir, settings.uploads, settings.article_images, settings.service_data):
        directory.mkdir(parents=True, exist_ok=True)
    # Importing the application applies its normal numbered migrations and schema setup
    # against the isolated pilot database selected above.
    from backend.main import get_db

    with get_db() as connection:
        seed_anonymous_pilot_data(connection)
    return settings
