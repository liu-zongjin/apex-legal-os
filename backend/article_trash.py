"""Recoverable article deletion backed by per-article SQLite snapshots."""

from __future__ import annotations

import base64
import datetime as dt
import json
import sqlite3
from typing import Any, Iterable


RETENTION_DAYS = 30


class TrashRestoreConflict(Exception):
    """The original article can no longer be restored without data loss."""


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _stamp(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _encode_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"__sqlite_blob_base64__": base64.b64encode(value).decode("ascii")}
    return value


def _decode_value(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"__sqlite_blob_base64__"}:
        return base64.b64decode(value["__sqlite_blob_base64__"])
    return value


def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: _encode_value(row[key]) for key in row.keys()}


def _cascade_tables(connection: sqlite3.Connection) -> list[tuple[str, str]]:
    """Find rows SQLite itself would remove when an article is deleted."""
    relations = []
    for (table,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        if table.startswith("sqlite_"):
            continue
        for fk in connection.execute(f"PRAGMA foreign_key_list({_quote(table)})"):
            if fk[2] == "articles" and fk[4] == "id" and fk[6].upper() == "CASCADE":
                relations.append((table, fk[3]))
    return relations


def _insert_row(connection: sqlite3.Connection, table: str, values: dict[str, Any]) -> None:
    available = {row[1] for row in connection.execute(f"PRAGMA table_info({_quote(table)})")}
    columns = [column for column in values if column in available]
    if not columns:
        return
    placeholders = ",".join("?" for _ in columns)
    connection.execute(
        f"INSERT INTO {_quote(table)} ({','.join(_quote(column) for column in columns)}) "
        f"VALUES ({placeholders})",
        [_decode_value(values[column]) for column in columns],
    )


def move_articles(
    connection: sqlite3.Connection, article_ids: Iterable[int], now: dt.datetime | None = None
) -> dict[str, Any]:
    """Snapshot each article and its cascading rows, then remove it from active data.

    The caller owns one transaction covering every requested article.
    """
    ids = list(dict.fromkeys(int(value) for value in article_ids if int(value) > 0))
    if not ids:
        return {"deleted_count": 0, "missing_article_ids": [], "items": []}
    removed_at = now or _utc_now()
    deleted_at = _stamp(removed_at)
    expires_at = _stamp(removed_at + dt.timedelta(days=RETENTION_DAYS))
    relations = _cascade_tables(connection)
    moved = []
    missing = []
    for article_id in ids:
        article = connection.execute("SELECT * FROM articles WHERE id=?", (article_id,)).fetchone()
        if article is None:
            missing.append(article_id)
            continue
        snapshot = {"version": 1, "article": _row_dict(article), "related": {}}
        for table, column in relations:
            rows = connection.execute(
                f"SELECT * FROM {_quote(table)} WHERE {_quote(column)}=?", (article_id,)
            ).fetchall()
            if rows:
                snapshot["related"][table] = [_row_dict(row) for row in rows]
        cursor = connection.execute(
            """INSERT INTO article_trash(article_id,title,source_type,deleted_at,expires_at,snapshot_json)
               VALUES (?,?,?,?,?,?)""",
            (
                article_id,
                article["title"],
                article["source_type"],
                deleted_at,
                expires_at,
                json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
            ),
        )
        connection.execute("DELETE FROM articles WHERE id=?", (article_id,))
        moved.append({"id": cursor.lastrowid, "article_id": article_id, "expires_at": expires_at})
    return {"deleted_count": len(moved), "missing_article_ids": missing, "items": moved}


def restore_articles(
    connection: sqlite3.Connection, trash_ids: Iterable[int], now: dt.datetime | None = None
) -> dict[str, Any]:
    ids = list(dict.fromkeys(int(value) for value in trash_ids if int(value) > 0))
    current_time = _stamp(now or _utc_now())
    allowed_relations = {table for table, _ in _cascade_tables(connection)}
    restored = []
    missing = []
    skipped_related_rows = 0
    for trash_id in ids:
        row = connection.execute("SELECT * FROM article_trash WHERE id=?", (trash_id,)).fetchone()
        if row is None or row["expires_at"] <= current_time:
            missing.append(trash_id)
            continue
        snapshot = json.loads(row["snapshot_json"])
        if snapshot.get("version") != 1 or not isinstance(snapshot.get("article"), dict):
            raise TrashRestoreConflict("回收站中的文章快照无法识别")
        try:
            _insert_row(connection, "articles", snapshot["article"])
        except sqlite3.IntegrityError as exc:
            raise TrashRestoreConflict("原文章编号或来源已被占用，无法直接恢复") from exc
        for table, entries in snapshot.get("related", {}).items():
            if table not in allowed_relations or not isinstance(entries, list):
                continue
            for entry in entries:
                connection.execute("SAVEPOINT article_trash_related")
                try:
                    _insert_row(connection, table, entry)
                    connection.execute("RELEASE SAVEPOINT article_trash_related")
                except sqlite3.IntegrityError as exc:
                    connection.execute("ROLLBACK TO SAVEPOINT article_trash_related")
                    connection.execute("RELEASE SAVEPOINT article_trash_related")
                    if table == "notes":
                        raise TrashRestoreConflict("文章笔记恢复失败，已取消本次恢复") from exc
                    skipped_related_rows += 1
        connection.execute("DELETE FROM article_trash WHERE id=?", (trash_id,))
        restored.append(row["article_id"])
    return {
        "restored_count": len(restored),
        "article_ids": restored,
        "missing_trash_ids": missing,
        "skipped_related_rows": skipped_related_rows,
    }


def purge_expired(connection: sqlite3.Connection, now: dt.datetime | None = None) -> int:
    cursor = connection.execute(
        "DELETE FROM article_trash WHERE expires_at<=?", (_stamp(now or _utc_now()),)
    )
    return cursor.rowcount


def purge_articles(connection: sqlite3.Connection, trash_ids: Iterable[int] | None = None) -> int:
    if trash_ids is None:
        return connection.execute("DELETE FROM article_trash").rowcount
    ids = list(dict.fromkeys(int(value) for value in trash_ids if int(value) > 0))
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    return connection.execute(
        f"DELETE FROM article_trash WHERE id IN ({placeholders})", ids
    ).rowcount


def list_articles(connection: sqlite3.Connection, limit: int, offset: int) -> dict[str, Any]:
    total = connection.execute("SELECT COUNT(*) FROM article_trash").fetchone()[0]
    rows = connection.execute(
        """SELECT id,article_id,title,source_type,deleted_at,expires_at
           FROM article_trash ORDER BY deleted_at DESC,id DESC LIMIT ? OFFSET ?""",
        (limit, offset),
    ).fetchall()
    return {"total": total, "items": [dict(row) for row in rows], "retention_days": RETENTION_DAYS}
