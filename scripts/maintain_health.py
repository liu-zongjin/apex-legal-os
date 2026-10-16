#!/usr/bin/env python3
"""Explicit, backed-up maintenance. Default invocation only reports counts."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.health_maintenance import preserve_orphans
from backend.migrations import migrate_database, _backup_database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--repair-orphans', action='store_true')
    parser.add_argument('--compact', action='store_true')
    args = parser.parse_args()
    path = args.db.resolve()
    if not path.is_file():
        parser.error('Database does not exist')
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    before = {'bytes':path.stat().st_size, 'violations':len(conn.execute('PRAGMA foreign_key_check').fetchall()),
              'quick_check':conn.execute('PRAGMA quick_check').fetchone()[0]}
    conn.close()
    result = {'before':before, 'applied':False}
    if args.apply:
        if before['quick_check'] != 'ok':
            raise RuntimeError('结构检查失败，未执行维护')
        backup = _backup_database(path, 24)
        result['backup'] = str(backup)
        migrate_database(path)
        conn = sqlite3.connect(path)
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=30000')
        try:
            if args.repair_orphans:
                result['repair'] = preserve_orphans(conn)
            if args.compact:
                conn.execute("INSERT INTO articles_fts(articles_fts) VALUES('optimize')")
                conn.commit()
                conn.execute('VACUUM')
            result['after'] = {'bytes':path.stat().st_size,
                'violations':len(conn.execute('PRAGMA foreign_key_check').fetchall()),
                'quick_check':conn.execute('PRAGMA quick_check').fetchone()[0]}
            result['applied'] = True
        finally:
            conn.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
