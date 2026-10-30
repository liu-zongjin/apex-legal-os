"""Run the source host protocol on a disposable GitHub Windows runner."""
import json, os, subprocess, sys, time, urllib.request
import requests
from playwright.sync_api import sync_playwright
from pathlib import Path
p = subprocess.Popen([sys.executable, 'scripts/windows/source_worker.py', 'launch'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
try:
    line = p.stdout.readline()
    event = json.loads(line)
    assert event.get('event') == 'ready', event
    assert urllib.request.urlopen(event['url'], timeout=10).status == 200
    base = event['url'].rstrip('/')
    for route in ['/api/case-manager/court-online/status', '/api/case-manager/court-online/settings',
                  '/api/automated-filing/jobs', '/api/automated-filing/reference-data', '/api/case-manager/cases']:
        response = requests.get(base + route, timeout=20)
        assert response.status_code == 200, (route, response.status_code, response.text[:300])
    saved = requests.post(base + '/api/case-manager/cases', json={'title':'CI anonymous case','require_new_case':True}, timeout=20)
    assert saved.status_code == 200, saved.text[:300]
    assert any(item.get('title') == 'CI anonymous case' for item in requests.get(base + '/api/case-manager/cases', timeout=20).json().get('cases', []))
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        for route in ['/case-manager', '/automation-filing']:
            page = browser.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            response = page.goto(base + route, wait_until='networkidle', timeout=45000)
            assert response.status == 200, (route, response.status)
            assert not errors, (route, errors)
            page.close()
        browser.close()
    duplicate = subprocess.run([sys.executable, 'scripts/windows/source_worker.py', 'launch'], capture_output=True, text=True, timeout=30)
    assert json.loads(duplicate.stdout)['event'] == 'error'
    p.stdin.write('stop\n'); p.stdin.flush()
    assert p.wait(timeout=90) == 0
    assert Path(os.environ['LOCALAPPDATA'], 'StellaSource', 'legal_kb.db').exists()
finally:
    if p.poll() is None:
        p.kill(); p.wait()
