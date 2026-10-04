"""Shared SQLite connection policy for Stella runtime modules."""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path


_RUNTIME_CONFIG_LOCK = threading.Lock()
_RUNTIME_CONFIGURED_PATHS: set[str] = set()


def connect_database(path: str | os.PathLike[str]) -> sqlite3.Connection:
    """Open one short-lived application connection with consistent safety.

    Stella intentionally keeps request-scoped SQLite connections. WAL negotiation
    is persistent and therefore performed only once for each database path.
    """
    resolved = Path(path).expanduser().resolve()
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
