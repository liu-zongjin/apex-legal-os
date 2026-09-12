"""Short-lived local storage for the exact document-bundle output.

The generated 所函 is kept as a SQLite BLOB for a bounded period.  The
one-click MingSi flow therefore uploads exactly the bytes the user downloaded,
without regenerating a potentially different DOCX.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from typing import Any, Callable


ARTIFACT_TTL_HOURS = 24
MAX_CLEANUP_ROWS = 100


def canonical_request_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat()


def cleanup_expired(get_db: Callable[[], Any], *, now: dt.datetime | None = None) -> int:
    current = _iso(now or _utc_now())
    with get_db() as conn:
        rows = conn.execute(
            "SELECT artifact_id FROM document_bundle_artifacts WHERE expires_at <= ? ORDER BY expires_at LIMIT ?",
            (current, MAX_CLEANUP_ROWS),
        ).fetchall()
        ids = [str(row[0]) for row in rows]
        if ids:
            conn.executemany("DELETE FROM document_bundle_artifacts WHERE artifact_id = ?", ((item,) for item in ids))
            conn.commit()
    return len(ids)


def store_document_bundle_artifact(
    get_db: Callable[[], Any],
    content: bytes,
    filename: str,
    request_payload: Any,
    *,
    ttl_hours: int = ARTIFACT_TTL_HOURS,
) -> dict[str, str]:
    cleanup_expired(get_db)
    created = _utc_now()
    expires = created + dt.timedelta(hours=max(1, int(ttl_hours)))
    artifact_id = uuid.uuid4().hex
    request_hash = canonical_request_hash(request_payload)
    with get_db() as conn:
        conn.execute(
            """INSERT INTO document_bundle_artifacts
               (artifact_id, request_hash, suohan_filename, suohan_content, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (artifact_id, request_hash, str(filename), bytes(content), _iso(created), _iso(expires)),
        )
        conn.commit()
    return {
        "artifact_id": artifact_id,
        "request_hash": request_hash,
        "filename": str(filename),
        "sha256": hashlib.sha256(bytes(content)).hexdigest(),
        "expires_at": _iso(expires),
    }


def get_document_bundle_artifact(get_db: Callable[[], Any], artifact_id: str) -> dict[str, Any] | None:
    cleanup_expired(get_db)
    value = str(artifact_id or "").strip()
    if not value:
        return None
    with get_db() as conn:
        row = conn.execute(
            "SELECT artifact_id, request_hash, suohan_filename, suohan_content, created_at, expires_at, consumed_at "
            "FROM document_bundle_artifacts WHERE artifact_id = ?",
            (value,),
        ).fetchone()
    if row is None:
        return None
    item = dict(row) if hasattr(row, "keys") else {
        "artifact_id": row[0],
        "request_hash": row[1],
        "suohan_filename": row[2],
        "suohan_content": row[3],
        "created_at": row[4],
        "expires_at": row[5],
        "consumed_at": row[6],
    }
    item["suohan_content"] = bytes(item.get("suohan_content") or b"")
    item["sha256"] = hashlib.sha256(item["suohan_content"]).hexdigest()
    return item


def mark_artifact_consumed(get_db: Callable[[], Any], artifact_id: str) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE document_bundle_artifacts SET consumed_at = ? WHERE artifact_id = ? AND consumed_at IS NULL",
            (_iso(_utc_now()), str(artifact_id)),
        )
        conn.commit()
