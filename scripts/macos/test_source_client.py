"""Exercise a source app using an anonymous disposable profile on macOS."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

app = Path(os.environ['STELLA_SOURCE_APP_DIR']) / 'Contents/MacOS/Stella'
base = 'http://127.0.0.1:18866'


def request(path, data=None):
    payload = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(base + path, data=payload,
                                 headers={'Content-Type': 'application/json'} if payload else {})
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.status, response.read()


with tempfile.TemporaryDirectory(prefix='stella-source-profile-') as directory:
    runtime = Path(directory)
    for attempt in range(2):
        env = dict(os.environ, STELLA_SOURCE_RUNTIME=directory, STELLA_SOURCE_TEST_AUTO_QUIT='90')
        child = subprocess.Popen([str(app)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
            for path in ('/api/case-manager/cases', '/api/automated-filing/jobs',
                         '/api/case-manager/court-online/status'):
                print('Checking', path, flush=True)
                assert request(path)[0] == 200, path
            if attempt == 0:
                assert request('/api/case-manager/cases', {'title': 'Anonymous source QA case',
                                                          'require_new_case': True})[0] == 200
            _, body = request('/api/case-manager/cases')
            assert any(row['title'] == 'Anonymous source QA case' for row in json.loads(body)['items'])
            assert child.wait(timeout=150) == 0
            try:
                request('/')
                raise RuntimeError('Backend is still running after exit')
            except urllib.error.URLError:
                pass
            print('Client lifecycle and anonymous data verified:', attempt + 1, flush=True)
        except Exception:
            log = runtime / 'server.log'
            if log.exists():
                print(log.read_text(encoding='utf-8', errors='replace')[-16000:], flush=True)
            raise
        finally:
            if child.poll() is None:
                child.kill()  # Disposable CI profile only.
                child.wait()
