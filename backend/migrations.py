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


def _add_knowledge_learning_tables(connection: sqlite3.Connection) -> None:
    """Add local learning and usage state for the Knowledge Center redesign."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS knowledge_learning_state (
            claim_id INTEGER PRIMARY KEY,
            is_favorite INTEGER NOT NULL DEFAULT 0,
            is_suspended INTEGER NOT NULL DEFAULT 0,
            mastery_level INTEGER NOT NULL DEFAULT 0,
            streak INTEGER NOT NULL DEFAULT 0,
            interval_days INTEGER NOT NULL DEFAULT 0,
            next_review_at TEXT,
            last_reviewed_at TEXT,
            review_count INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (claim_id) REFERENCES knowledge_claims(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_learning_due
            ON knowledge_learning_state(next_review_at, is_suspended, mastery_level);

        CREATE TABLE IF NOT EXISTS knowledge_review_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id INTEGER NOT NULL,
            grade TEXT NOT NULL CHECK(grade IN ('forgot','fuzzy','mastered')),
            case_id INTEGER,
            previous_interval_days INTEGER NOT NULL DEFAULT 0,
            next_interval_days INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (claim_id) REFERENCES knowledge_claims(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_review_events_claim
            ON knowledge_review_events(claim_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS knowledge_usage_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            claim_id INTEGER,
            issue_id INTEGER,
            case_id INTEGER,
            result_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (claim_id) REFERENCES knowledge_claims(id) ON DELETE SET NULL,
            FOREIGN KEY (issue_id) REFERENCES knowledge_issues(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_usage_events_time
            ON knowledge_usage_events(event_type, created_at DESC);
        """
    )


def _add_mingsi_chapter_tables(connection: sqlite3.Connection) -> None:
    """Store short-lived generated 所函 artifacts and idempotent submissions."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS document_bundle_artifacts (
            artifact_id TEXT PRIMARY KEY,
            request_hash TEXT NOT NULL,
            suohan_filename TEXT NOT NULL,
            suohan_content BLOB NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            consumed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_document_bundle_artifacts_expiry
            ON document_bundle_artifacts(expires_at);

        CREATE TABLE IF NOT EXISTS mingsi_chapter_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artifact_id TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            account_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            project_name TEXT NOT NULL DEFAULT '',
            copies INTEGER NOT NULL,
            chapter_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            next_approver_id TEXT NOT NULL DEFAULT '',
            next_approver_name TEXT NOT NULL DEFAULT '',
            next_approver_candidates_json TEXT NOT NULL DEFAULT '[]',
            message TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(artifact_id, project_id, copies)
        );
        CREATE INDEX IF NOT EXISTS idx_mingsi_chapter_submissions_account_time
            ON mingsi_chapter_submissions(account_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_mingsi_chapter_submissions_status
            ON mingsi_chapter_submissions(status, updated_at DESC);
        """
    )


def _add_series_import_history(connection: sqlite3.Connection) -> None:
    """Store recoverable pre-import snapshots for series child tables."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS case_manager_series_history (
            history_id INTEGER PRIMARY KEY AUTOINCREMENT,
            series_case_id INTEGER NOT NULL,
            operation TEXT NOT NULL DEFAULT 'excel_import',
            summary_json TEXT NOT NULL DEFAULT '{}',
            snapshot_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(series_case_id) REFERENCES case_manager_cases(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_series_history_series_time
            ON case_manager_series_history(series_case_id, created_at DESC, history_id DESC);
        """
    )


MIGRATIONS: tuple[Migration, ...] = (
    (1, "baseline_pre_numbered_schema", _baseline),
    (2, "series_detail_field_mappings", _add_series_detail_field_mappings),
    (3, "knowledge_learning_and_usage", _add_knowledge_learning_tables),
    (4, "mingsi_chapter_artifacts_and_submissions", _add_mingsi_chapter_tables),
    (5, "series_import_history", _add_series_import_history),
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
