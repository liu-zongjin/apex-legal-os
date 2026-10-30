"""Run the source checkout with an isolated, persistent Windows user profile."""
import argparse
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.distribution.preview_entry import configure


def source_revision():
    try:
        result = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=normal'], cwd=ROOT,
                                capture_output=True, text=True, timeout=15, check=True)
        if result.stdout.strip():
            return None
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                                           stderr=subprocess.DEVNULL, text=True, timeout=15).strip()
        return revision if len(revision) == 40 and all(c in '0123456789abcdef' for c in revision) else None
    except (OSError, subprocess.SubprocessError):
        return None


def mark_source_ready(runtime, revision):
    if revision:
        marker = runtime / 'source-ready-revision'
        temporary = runtime / 'source-ready-revision.tmp'
        temporary.write_text(revision, encoding='ascii')
        os.replace(temporary, marker)


def prepare_runtime(path, port, revision=None):
    runtime = configure(path)
    os.environ['PORT'] = str(port)
    os.environ['JUDICIAL_SMS_SCHEDULER_DISABLED'] = '1'
    database = runtime / 'legal_kb.db'
    marker = runtime / 'source-ready-revision'
    try:
        previous = marker.read_text(encoding='ascii').strip() if marker.is_file() else None
    except (OSError, UnicodeError):
        previous = None
    if database.exists() and (not revision or revision != previous):
        backups = runtime / 'data' / 'history_backups'
        backups.mkdir(parents=True, exist_ok=True)
        backup = backups / ('before-source-start-' + time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex + '.db')
        with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as source:
            with closing(sqlite3.connect(backup)) as target:
                source.backup(target)
                if target.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Database backup integrity check failed')
    return runtime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--port', type=int, default=18865)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('port must be between 1 and 65535')
    revision = source_revision()
    runtime = prepare_runtime(args.runtime, args.port, revision)
    os.chdir(ROOT)
    import uvicorn
    class Server(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            if self.started:
                mark_source_ready(runtime, revision)
    Server(uvicorn.Config('backend.main:app', host='127.0.0.1', port=args.port, workers=1)).run()


if __name__ == '__main__':
    main()
