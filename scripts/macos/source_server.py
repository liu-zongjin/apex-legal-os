"""macOS source client backend, using a separate user profile and lifecycle lock."""
import argparse
import fcntl
import os
from pathlib import Path
import sys
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.windows.source_server import mark_source_ready, prepare_runtime, source_revision


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--ready-token', required=True)
    args = parser.parse_args()
    token = str(uuid.UUID(args.ready_token))
    runtime = args.runtime.expanduser().resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / 'source.lock').open('a+b') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        revision = source_revision()
        prepare_runtime(runtime, 18866, revision)
        os.environ['LEGAL_KB_CORS_ORIGINS'] = 'http://localhost:18866,http://127.0.0.1:18866'
        os.chdir(ROOT)
        import uvicorn
        ready = runtime / ('server-ready-' + token)
        class Server(uvicorn.Server):
            async def startup(self, sockets=None):
                await super().startup(sockets=sockets)
                if self.started:
                    mark_source_ready(runtime, revision)
                    ready.touch()
        try:
            Server(uvicorn.Config('backend.main:app', host='127.0.0.1', port=18866,
                                  access_log=False, log_level='warning')).run()
        finally:
            ready.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
