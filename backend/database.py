"""Shared SQLite connection policy for APEX runtime modules."""

from __future__ import annotations

import os
import sqlite3
import threading
import contextvars
from contextlib import contextmanager
from pathlib import Path


_RUNTIME_CONFIG_LOCK = threading.Lock()
_RUNTIME_CONFIGURED_PATHS: set[str] = set()
_READ_SNAPSHOT = contextvars.ContextVar('stella_read_snapshot', default=None)


class _BorrowedConnection:
    def __init__(self, connection): self.connection = connection
    def __getattr__(self, name): return getattr(self.connection, name)
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def close(self): pass
    def commit(self): pass
    def rollback(self): pass


def snapshot_active():
    return _READ_SNAPSHOT.get() is not None


@contextmanager
def read_snapshot(get_db):
    connection = get_db()
    path = connection.execute('PRAGMA database_list').fetchone()[2]
    connection.execute('PRAGMA query_only=ON')
    connection.execute('BEGIN')
    token = _READ_SNAPSHOT.set((str(Path(path).resolve()), _BorrowedConnection(connection)))
    try:
        yield
    finally:
        _READ_SNAPSHOT.reset(token)
        connection.rollback()
        connection.close()


def connect_database(path: str | os.PathLike[str]) -> sqlite3.Connection:
    """Open one short-lived application connection with consistent safety.

    APEX intentionally keeps request-scoped SQLite connections. WAL negotiation
    is persistent and therefore performed only once for each database path.
    """
    resolved = Path(path).expanduser().resolve()
    snapshot = _READ_SNAPSHOT.get()
    if snapshot is not None and snapshot[0] == str(resolved):
        return snapshot[1]
    connection = sqlite3.connect(str(resolved))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    wal_enabled = os.environ.get("LEGAL_KB_SQLITE_WAL", "1").strip().lower() not in {
        "0", "false", "no", "off"
    }
    if wal_enabled:
        with _RUNTIME_CONFIG_LOCK:
            key = str(resolved)
            if key not in _RUNTIME_CONFIGURED_PATHS:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute("PRAGMA synchronous = NORMAL")
                _RUNTIME_CONFIGURED_PATHS.add(key)
    return connection


def reset_runtime_configuration_for_tests() -> None:
    """Clear process-local negotiation state; never changes database data."""
    with _RUNTIME_CONFIG_LOCK:
        _RUNTIME_CONFIGURED_PATHS.clear()
