"""Check an update candidate with a disposable profile before switching shortcuts."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import urllib.request

root = Path(sys.argv[1]).resolve()
python = root / '.venv' / 'Scripts' / 'python.exe'
worker = root / 'scripts' / 'windows' / 'source_worker.py'
with tempfile.TemporaryDirectory(prefix='stella-source-update-check-') as profile:
    env = dict(os.environ, LOCALAPPDATA=profile)
    child = subprocess.Popen([str(python), str(worker), 'launch'], cwd=str(root), env=env,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        output = queue.Queue()
        threading.Thread(target=lambda: output.put(child.stdout.readline()), daemon=True).start()
        try:
            event = json.loads(output.get(timeout=120))
        except queue.Empty as exc:
            raise RuntimeError('候选版本启动超时') from exc
        if event.get('event') != 'ready' or event.get('url') != 'http://127.0.0.1:18865/':
            raise RuntimeError('候选版本未就绪：' + str(event.get('message', event)))
        with urllib.request.urlopen(event['url'], timeout=15) as response:
            if response.status != 200 or b'<html' not in response.read().lower():
                raise RuntimeError('候选版本首页不可用')
        child.stdin.write('stop\n')
        child.stdin.flush()
        if child.wait(timeout=90) != 0:
            raise RuntimeError('候选版本未能正常退出')
    finally:
        if child.poll() is None:
            subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            child.wait(timeout=30)
print('候选版本启动和退出检查通过。')
