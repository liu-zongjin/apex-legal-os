"""Source-mode adapter for the existing Windows Tauri host's worker protocol."""
import json
import os
from pathlib import Path
import socket
import sys
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    action = sys.argv[1] if len(sys.argv) == 2 else ''
    emit = lambda **data: print(json.dumps(data, ensure_ascii=True), flush=True)
    if action == 'probe':
        emit(event='probe', supported=True, installed=True, source=True)
        return
    if action != 'launch':
        emit(event='error', message='源码模式请通过部署说明维护，暂不支持此操作。')
        return
    import msvcrt
    from scripts.windows.source_server import prepare_runtime
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
                prepare_runtime(runtime, 18865)
                print('Source profile ready', file=log, flush=True)
                os.chdir(ROOT)
                import uvicorn
                class Server(uvicorn.Server):
                    async def startup(self, sockets=None):
                        await super().startup(sockets=sockets)
                        if self.started:
                            event(event='ready', url='http://127.0.0.1:18865/')
                server = Server(uvicorn.Config('backend.main:app', host='127.0.0.1', port=18865, workers=1, log_level='warning'))
                def monitor():
                    for line in sys.stdin:
                        if line.strip() == 'stop':
                            break
                    server.should_exit = True
                threading.Thread(target=monitor, daemon=True).start()
                print('Starting source server', file=log, flush=True)
                server.run()
                print('Source server stopped', file=log, flush=True)
            except Exception:
                import traceback
                traceback.print_exc(file=log)
                event(event='error', message='源码工作空间启动失败，请查看本机 source-client.log。')


if __name__ == '__main__':
    main()
