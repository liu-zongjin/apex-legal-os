"""Numbered, repeat-safe SQLite migrations for APEX."""

from __future__ import annotations

import datetime as dt
import os
import shutil
import sqlite3
from pathlib import Path
from typing import Callable, Tuple

Migration = Tuple[int, str, Callable[[sqlite3.Connection], None]]


def _baseline(_connection: sqlite3.Connection) -> None:
    """The pre-migration schema is accepted as version 1 without altering it."""


def _add_series_detail_field_mappings(connection: sqlite3.Connection) -> None:
    """Persist series-table-to-detail mappings when the series feature exists."""
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='case_manager_series_profiles'"
    ).fetchone()
    if not exists:
        return
    columns = {row[1] for row in connection.execute("PRAGMA table_info(case_manager_series_profiles)")}
    if "detail_field_mappings_json" not in columns:
        connection.execute(
            "ALTER TABLE case_manager_series_profiles "
            "ADD COLUMN detail_field_mappings_json TEXT DEFAULT '[]'"
        )


MIGRATIONS: tuple[Migration, ...] = (
    (1, "baseline_pre_numbered_schema", _baseline),
    (2, "series_detail_field_mappings", _add_series_detail_field_mappings),
)


def _backup_database(db_path: Path, version: int, backup_root: Path | None = None) -> Path | None:
    if not db_path.exists() or db_path.stat().st_size == 0:
        return None
    # Keep every update-created snapshot in one application-owned location.
    # Storage management exposes this directory as "历史备份文件", so users can
    # inspect and remove old rollback points without mistaking them for source
    # code or active data. The old ``data/schema_backups`` location remains
    # readable for snapshots created by earlier versions.
    root = backup_root or db_path.parent / "data" / "history_backups"
    root.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = root / f"{db_path.stem}-before-v{version}-{stamp}.db"
    source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    return target


def migrate_database(db_path: str | os.PathLike[str], backup_root: str | os.PathLike[str] | None = None) -> list[int]:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existed_with_data = path.exists() and path.stat().st_size > 0
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA busy_timeout = 5000")
        migration_table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone() is not None
        if existed_with_data and not migration_table_exists:
            # The first migration marker is itself a schema change, so preserve
            # the original database before creating that marker table.
            _backup_database(path, MIGRATIONS[-1][0], Path(backup_root) if backup_root else None)
        connection.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                   version INTEGER PRIMARY KEY,
                   name TEXT NOT NULL,
                   applied_at TEXT NOT NULL
               )"""
        )
        connection.commit()
        applied = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
        pending = [migration for migration in MIGRATIONS if migration[0] not in applied]
        if pending and migration_table_exists:
            _backup_database(path, pending[-1][0], Path(backup_root) if backup_root else None)
        completed: list[int] = []
        for version, name, callback in pending:
            try:
                connection.execute("BEGIN IMMEDIATE")
                callback(connection)
                connection.execute(
                    "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                    (version, name, dt.datetime.now(dt.timezone.utc).isoformat()),
                )
                connection.commit()
                completed.append(version)
            except Exception:
                connection.rollback()
                raise
        return completed
    finally:
        connection.close()
