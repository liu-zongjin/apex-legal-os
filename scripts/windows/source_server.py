"""Run the source checkout with an isolated, persistent Windows user profile."""
import argparse
import asyncio
from contextlib import closing
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
import uuid
import webbrowser

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.distribution.preview_entry import configure
from scripts.windows.bootstrap_engine import InstallError, exclusive_lock
from scripts.windows.proactor_shutdown import install as install_shutdown_recovery


def source_revision():
    try:
        result = subprocess.check_output(
            ['git', 'status', '--porcelain=v2', '--branch', '--untracked-files=normal'],
            cwd=ROOT, stderr=subprocess.DEVNULL, timeout=15,
        )
        revision = None
        for line in result.splitlines():
            if line.startswith(b'# branch.oid '):
                revision = line[len(b'# branch.oid '):]
            elif not line.startswith(b'# '):
                return None
        if revision and len(revision) == 40 and all(c in b'0123456789abcdef' for c in revision):
            return revision.decode('ascii')
        return None
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
    os.environ['STELLA_SOURCE_STATISTICS'] = '1'
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


def open_workspace(port):
    url = f'http://127.0.0.1:{port}/'
    print(f'Stella 已就绪。若浏览器没有打开，请访问 {url} 。在服务窗口按 Ctrl+C 可退出。', flush=True)
    try:
        webbrowser.open(url)
    except (OSError, webbrowser.Error):
        pass


def is_running_workspace(runtime, port):
    import psutil

    try:
        for connection in psutil.net_connections(kind='tcp4'):
            if connection.status != psutil.CONN_LISTEN or connection.laddr != ('127.0.0.1', port) or connection.pid is None:
                continue
            arguments = psutil.Process(connection.pid).cmdline()
            if len(arguments) < 4 or Path(arguments[1]).resolve() != Path(__file__).resolve():
                return False
            index = arguments.index('--runtime', 2)
            return Path(arguments[index + 1]).resolve() == runtime
    except (psutil.Error, OSError, IndexError, ValueError):
        pass
    return False


def serve(runtime, port, open_browser):
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', port))
        except OSError as exc:
            raise InstallError(f'无法使用本机端口 {port}。请确认是否已有 Stella 或其他应用在运行。') from exc
    revision = source_revision()
    prepare_runtime(runtime, port, revision)
    os.environ['STELLA_SOURCE_BROWSER_MODE'] = '1'
    os.chdir(ROOT)
    if os.name == 'nt':
        install_shutdown_recovery()
    import uvicorn

    class Server(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            if self.started:
                mark_source_ready(runtime, revision)
                if open_browser:
                    await asyncio.to_thread(open_workspace, port)

    server = Server(uvicorn.Config('backend.main:app', host='127.0.0.1', port=port, workers=1))
    server.run()
    return 0 if server.started else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--port', type=int, default=18865)
    parser.add_argument('--open-browser', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('port must be between 1 and 65535')
    runtime = args.runtime.resolve()
    try:
        with exclusive_lock(runtime / 'source.lock'):
            return serve(runtime, args.port, args.open_browser)
    except InstallError as exc:
        if args.open_browser and is_running_workspace(runtime, args.port):
            open_workspace(args.port)
            return 0
        print(exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
