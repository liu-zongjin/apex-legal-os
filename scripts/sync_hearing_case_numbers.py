"""Preview or back up and apply the additive repair to existing hearing records."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import sqlite3
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.hearing_case_numbers import sync_hearing_case_numbers


def repair(database: Path, apply: bool = False, case_id: int = 0):
    database = database.resolve(strict=True)
    source = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=30)
    backup_path = ""
    if apply:
        folder = database.parent / "data" / "backups"
        folder.mkdir(parents=True, exist_ok=True)
        backup = folder / ("before-hearing-case-numbers-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8] + ".sqlite3")
        with sqlite3.connect(backup) as target:
            source.backup(target)
        backup_path = str(backup)
        connection = sqlite3.connect(database, timeout=30)
    else:
        connection = sqlite3.connect(":memory:")
        source.backup(connection)
    source.close()
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute(
            """SELECT h.* FROM case_manager_hearings h JOIN case_manager_cases c ON c.id=h.case_id
               WHERE COALESCE(c.source_status,'active')<>'deleted' AND TRIM(COALESCE(h.case_no,''))<>''
               AND (?=0 OR h.case_id=?) ORDER BY h.id""", (case_id, case_id)
        ).fetchall()
        changes = []
        for row in rows:
            updates = sync_hearing_case_numbers(connection, dict(row))
            if updates:
                changes.append({"hearing_id": row["id"], "case_id": row["case_id"], "changes": len(updates)})
        if apply:
            connection.commit()
        else:
            connection.rollback()
        return {"applied": apply, "backup": backup_path, "scanned_hearings": len(rows),
                "changed_hearings": len(changes), "changed_cases": len({row["case_id"] for row in changes}), "items": changes}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--case-id", type=int, default=0)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(repair(args.db, args.apply, args.case_id), ensure_ascii=False, indent=2))
