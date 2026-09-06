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


MIGRATIONS: tuple[Migration, ...] = ((1, "baseline_pre_numbered_schema", _baseline),)


def _backup_database(db_path: Path, version: int, backup_root: Path | None = None) -> Path | None:
    if not db_path.exists() or db_path.stat().st_size == 0:
        return None
    root = backup_root or db_path.parent / "data" / "schema_backups"
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
