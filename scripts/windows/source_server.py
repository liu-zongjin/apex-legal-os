"""Run the source checkout with an isolated, persistent Windows user profile."""
import argparse
import os
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.distribution.preview_entry import configure


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--port', type=int, default=18865)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('port must be between 1 and 65535')
    runtime = configure(args.runtime)
    os.environ['PORT'] = str(args.port)
    os.environ['JUDICIAL_SMS_SCHEDULER_DISABLED'] = '1'
    database = runtime / 'legal_kb.db'
    if database.exists():
        backups = runtime / 'data' / 'history_backups'
        backups.mkdir(parents=True, exist_ok=True)
        backup = backups / ('before-source-start-' + time.strftime('%Y%m%d-%H%M%S') + '.db')
        with sqlite3.connect(f'file:{database.as_posix()}?mode=ro', uri=True) as source:
            with sqlite3.connect(backup) as target:
                source.backup(target)
    os.chdir(ROOT)
    import uvicorn
    uvicorn.run('backend.main:app', host='127.0.0.1', port=args.port, workers=1)


if __name__ == '__main__':
    main()
