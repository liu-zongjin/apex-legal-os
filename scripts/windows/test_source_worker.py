"""Run the source host protocol on a disposable GitHub Windows runner."""
import json, os, subprocess, sys, time, urllib.request
from pathlib import Path
p = subprocess.Popen([sys.executable, 'scripts/windows/source_worker.py', 'launch'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
try:
    line = p.stdout.readline()
    event = json.loads(line)
    assert event.get('event') == 'ready', event
    assert urllib.request.urlopen(event['url'], timeout=10).status == 200
    duplicate = subprocess.run([sys.executable, 'scripts/windows/source_worker.py', 'launch'], capture_output=True, text=True, timeout=30)
    assert json.loads(duplicate.stdout)['event'] == 'error'
    p.stdin.write('stop\n'); p.stdin.flush()
    assert p.wait(timeout=90) == 0
    assert Path(os.environ['LOCALAPPDATA'], 'StellaSource', 'legal_kb.db').exists()
finally:
    if p.poll() is None:
        p.kill(); p.wait()
