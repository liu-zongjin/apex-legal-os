"""Exercise the actual frozen Windows service using a disposable anonymous profile."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time
import uuid
import requests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('executable', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='stella-windows-smoke-') as directory:
        root = Path(directory)
        token = uuid.uuid4().hex
        shutdown = root / ('stop-' + token)
        ready = root / ('server-ready-' + token)
        with (root / 'diagnostic.log').open('w') as log:
            child = subprocess.Popen([str(args.executable.resolve()), '--runtime', str(root),
                '--app-build', '1', '--ready-token', token, '--shutdown-file', str(shutdown)], stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 120
                while not ready.exists():
                    if child.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError((root / 'diagnostic.log').read_text(errors='replace')[-8000:])
                    time.sleep(0.25)
                checked = []
                for route in ('/', '/api/platform-capabilities', '/api/case-manager/judicial-messages/settings',
                              '/api/case-manager/cases', '/ai-api-manager'):
                    response = requests.get('http://127.0.0.1:18865' + route, timeout=15)
                    assert response.status_code == 200, (route, response.status_code, response.text[:200])
                    checked.append(route)
                capabilities = requests.get('http://127.0.0.1:18865/api/platform-capabilities', timeout=10).json()
                assert capabilities['judicial_message_input'] == 'manual'
                import sqlite3
                with sqlite3.connect(root / 'legal_kb.db') as db:
                    assert db.execute('SELECT count(*) FROM case_manager_cases').fetchone()[0] == 0
                    assert db.execute('SELECT count(*) FROM articles').fetchone()[0] == 0
                db.close()
                Path('build/windows-smoke-result.json').write_text(json.dumps({'passed': True, 'routes': checked, 'anonymous_profile': True}))
            finally:
                shutdown.touch()
                try:
                    child.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    child.terminate()  # Disposable CI database only; never production shutdown policy.
                    child.wait(timeout=10)
                    raise


if __name__ == '__main__':
    main()
