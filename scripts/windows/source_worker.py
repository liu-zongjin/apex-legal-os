"""Source-mode adapter for the existing Windows Tauri host's worker protocol."""
import json
import os
from pathlib import Path
import socket
import sys
import threading

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def check_source_update(root):
    import re
    import shutil
    import subprocess

    def error(message):
        return {'event': 'error', 'message': message}

    def git(*args, timeout=15):
        result = subprocess.run(
            [executable, *args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, errors="replace", timeout=timeout,
            stdin=subprocess.DEVNULL, check=False,
            env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'},
        )
        return result.stdout.strip() if result.returncode == 0 else ''

    if not root.is_dir():
        return error('找不到 Stella 连接的源码目录。请检查目录是否已移动或删除。')
    executable = shutil.which('git')
    if not executable:
        return error('Stella 找不到 Git。请检查 Git for Windows 是否已安装并加入 PATH，重新打开 Stella 后再试。')
    try:
        if not git('--version'):
            return error('Stella 无法运行 Git。请检查 Git for Windows 是否可用。')
    except (OSError, subprocess.SubprocessError):
        return error('Stella 无法运行 Git。请检查 Git for Windows 是否可用。')

    if not (root / '.git').exists():
        return error('源码目录缺少 Git 仓库信息（.git）。请让 AI 检查原安装并按源码更新步骤恢复。')
    try:
        current = git('-C', str(root), 'rev-parse', 'HEAD')
    except (OSError, subprocess.SubprocessError):
        current = ''
    if not re.fullmatch(r'[0-9a-f]{40}', current):
        return error('无法读取本地源码版本。请检查源码目录权限和 Git 仓库是否完整。')

    try:
        remote, _, _ = git('ls-remote', '--refs', 'https://github.com/liu-zongjin/apex-legal-os.git',
                           'refs/heads/main', timeout=30).partition('\t')
    except (OSError, subprocess.SubprocessError):
        remote = ''
    if not re.fullmatch(r'[0-9a-f]{40}', remote):
        return error('无法从 GitHub 读取主分支版本。请检查 GitHub 网络连接或代理设置。')
    return {'event': 'check', 'source': True, 'available': current != remote,
            'version': '源码 ' + remote[:8], 'build': remote}


def main():
    action = sys.argv[1] if len(sys.argv) == 2 else ''
    emit = lambda **data: print(json.dumps(data, ensure_ascii=True), flush=True)
    if action == 'probe':
        emit(event='probe', supported=True, installed=True, source=True)
        return
    if action == 'check':
        emit(**check_source_update(ROOT))
        return
    if action != 'launch':
        emit(event='error', message='源码模式请通过部署说明维护，暂不支持此操作。')
        return
    import ctypes
    import msvcrt
    desktop = ctypes.create_unicode_buffer(260)
    if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, desktop) == 0:
        shortcut = Path(desktop.value) / "Stella Source.lnk"
        if shortcut.is_file():
            os.environ["STELLA_WORKBUDDY_LAUNCHER"] = str(shortcut)
    from scripts.windows.proactor_shutdown import install as install_shutdown_recovery
    from scripts.windows.source_server import prepare_runtime, source_revision, mark_source_ready
    install_shutdown_recovery()
    runtime = Path(os.environ['LOCALAPPDATA']) / 'StellaSource'
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / 'source.lock').open('a+b') as lock:
        try:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            emit(event='error', message='源码工作空间已在运行，请先关闭它。')
            return
        try:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 18865))
        except OSError:
            emit(event='error', message='端口 18865 已被占用，请先关闭占用它的应用。')
            return
        pipe = sys.stdout
        with (runtime / 'source-client.log').open('a', encoding='utf-8') as log:
            sys.stdout = sys.stderr = log
            def event(**data):
                pipe.write(json.dumps(data, ensure_ascii=True) + '\n')
                pipe.flush()
            try:
                print('Preparing source profile', file=log, flush=True)
                revision = source_revision()
                prepare_runtime(runtime, 18865, revision)
                print('Source profile ready', file=log, flush=True)
                os.chdir(ROOT)
                import uvicorn
                from backend.main import app
                class Server(uvicorn.Server):
                    async def startup(self, sockets=None):
                        await super().startup(sockets=sockets)
                        if self.started:
                            mark_source_ready(runtime, revision)
                            event(event='ready', url='http://127.0.0.1:18865/')
                server = Server(uvicorn.Config(app, host='127.0.0.1', port=18865, workers=1, log_level='warning'))
                def monitor():
                    for line in sys.stdin:
                        if line.strip() == 'stop':
                            break
                    print('Source shutdown requested', file=log, flush=True)
                    if os.environ.get('STELLA_SOURCE_TEST_DIAGNOSTICS') == '1':
                        import faulthandler
                        faulthandler.dump_traceback_later(40, file=log)
                    server.should_exit = True
                threading.Thread(target=monitor, daemon=True).start()
                print('Starting source server', file=log, flush=True)
                server.run()
                if os.environ.get('STELLA_SOURCE_TEST_DIAGNOSTICS') == '1':
                    import faulthandler
                    faulthandler.cancel_dump_traceback_later()
                print('Source server stopped', file=log, flush=True)
            except Exception:
                import traceback
                traceback.print_exc(file=log)
                event(event='error', message='源码工作空间启动失败，请查看本机 source-client.log。')


if __name__ == '__main__':
    main()
