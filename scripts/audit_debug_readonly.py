#!/usr/bin/env python3
"""只读检查法律操作系统的数据完整性、用户数据指纹与正文结构质量。"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sqlite3
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from audit_kb_data import classify  # noqa: E402
from scripts.audit_article_structure import inspect_article  # noqa: E402


USER_TABLES = (
    "articles",
    "notes",
    "case_manager_cases",
    "research_projects",
    "research_memos",
    "knowledge_claims",
)


def table_fingerprint(conn: sqlite3.Connection, table: str) -> dict:
    rows = [dict(row) for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid')]
    payload = json.dumps(
        rows, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")
    ).encode("utf-8")
    return {"count": len(rows), "sha256": hashlib.sha256(payload).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(PROJECT_ROOT / "legal_kb.db"))
    parser.add_argument("--pretty", action="store_true", help="缩进输出 JSON")
    args = parser.parse_args()
    db_path = Path(args.db).resolve()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    integrity = [row[0] for row in conn.execute("PRAGMA integrity_check")]
    foreign_keys = [tuple(row) for row in conn.execute("PRAGMA foreign_key_check")]
    fingerprints = {}
    for table in USER_TABLES:
        try:
            fingerprints[table] = table_fingerprint(conn, table)
        except sqlite3.Error as exc:
            fingerprints[table] = {"error": str(exc)}

    articles = conn.execute(
        "SELECT id,title,summary,content,source_type,source_url,source_filename,tags,created_at FROM articles ORDER BY id"
    ).fetchall()
    flagged = []
    structure_totals = collections.Counter()
    for row in articles:
        reasons = classify(row)
        if reasons:
            flagged.append({"id": row["id"], "title": row["title"], "reasons": reasons})
        counts, _examples = inspect_article(row)
        structure_totals.update(counts)

    duplicate_sources = [
        dict(row)
        for row in conn.execute(
            """SELECT source_url,COUNT(*) AS count,GROUP_CONCAT(id) AS article_ids
               FROM articles WHERE TRIM(COALESCE(source_url,''))<>''
               GROUP BY source_url HAVING COUNT(*)>1 ORDER BY COUNT(*) DESC"""
        )
    ]
    conn.close()
    result = {
        "database": str(db_path),
        "read_only": True,
        "integrity": integrity,
        "foreign_key_violation_count": len(foreign_keys),
        "foreign_key_violations": foreign_keys,
        "user_data_fingerprints": fingerprints,
        "flagged_articles": flagged,
        "duplicate_sources": duplicate_sources,
        "structure_issue_totals": dict(structure_totals),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0 if integrity == ["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
