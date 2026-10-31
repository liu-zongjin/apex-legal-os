"""Exercise source-app replacement using two isolated checkouts and a disposable profile."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

original = Path(os.environ['STELLA_SOURCE_APP_DIR'])
candidate = Path(os.environ['STELLA_SOURCE_CANDIDATE_APP'])
backup = original.with_name('Stella Source Previous.app')
base = 'http://127.0.0.1:18866'
runner_temp = Path(os.environ['RUNNER_TEMP']).resolve()
if original.parent.resolve() != runner_temp or candidate.parent.resolve() != runner_temp:
    raise RuntimeError('Update test may only move apps in the runner temporary directory')


def request(path, data=None):
    payload = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(base + path, data=payload,
                                 headers={'Content-Type': 'application/json'} if payload else {})
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.status, response.read()


def run_client(runtime, write_case):
    env = dict(os.environ, STELLA_SOURCE_RUNTIME=str(runtime), STELLA_SOURCE_TEST_AUTO_QUIT='75')
    child = subprocess.Popen([str(original / 'Contents/MacOS/Stella')], env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(120):
            if child.poll() is not None:
                raise RuntimeError('Client exited before startup')
            try:
                status, body = request('/')
                if status == 200 and b'<html' in body.lower():
                    break
            except (OSError, urllib.error.URLError):
                time.sleep(1)
        else:
            raise RuntimeError('Client startup timed out')
        if write_case:
            status, _ = request('/api/case-manager/cases', {'title': 'Anonymous update case',
                                                            'require_new_case': True})
            assert status == 200
        _, body = request('/api/case-manager/cases')
        assert any(row['title'] == 'Anonymous update case' for row in json.loads(body)['items'])
        assert child.wait(timeout=150) == 0
    except Exception:
        log = runtime / 'server.log'
        if log.exists():
            print(log.read_text(encoding='utf-8', errors='replace')[-16000:], flush=True)
        raise
    finally:
        if child.poll() is None:
            child.kill()  # Disposable CI profile only.
            child.wait()


with tempfile.TemporaryDirectory(prefix='stella-update-profile-') as directory:
    runtime = Path(directory)
    assert original.is_dir() and candidate.is_dir() and not backup.exists()
    run_client(runtime, True)
    original.rename(backup)
    try:
        candidate.rename(original)
        run_client(runtime, False)
        assert list((runtime / 'data/history_backups').glob('before-source-start-*.db'))
        print('Updated client preserved anonymous case and backed up its database.', flush=True)
    finally:
        if original.exists():
            original.rename(candidate)
        backup.rename(original)
