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
from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('executable', type=Path)
    args = parser.parse_args()
    subprocess.run([str(args.executable.resolve()), '--self-test-components'], check=True, timeout=120)
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
                        raise RuntimeError((root / 'diagnostic.log').read_text(encoding='utf-8', errors='replace')[-8000:])
                    time.sleep(0.25)
                checked = []
                # Build manifest is retained beside the frozen business modules.
                manifest = json.loads((args.executable.resolve().parent / '_internal/backend/packaged-resources.json').read_text(encoding='utf-8'))
                for route in manifest['pages'] + manifest['assets']:
                    response = requests.get('http://127.0.0.1:18865' + route, timeout=15)
                    assert response.status_code == 200, (route, response.status_code)
                    if route in manifest['pages']:
                        assert 'text/html' in response.headers.get('content-type', ''), route
                    checked.append(route)
                catalog = requests.get('http://127.0.0.1:18865/api/fada-items', timeout=15)
                assert catalog.status_code == 200 and catalog.json().get('items')
                item = catalog.json()['items'][0]
                response = requests.post('http://127.0.0.1:18865/api/fada-notes',
                    json={'id': item['id'], 'content': '匿名升级保留测试'}, timeout=15)
                assert response.status_code == 200
                exported = requests.post('http://127.0.0.1:18865/api/fada-word',
                    json={key: item[key] for key in ('question', 'answer', 'batch', 'url')}, timeout=20)
                assert exported.status_code == 200 and exported.content.startswith(b'PK')
                browser_results = []
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    for route in manifest['pages']:
                        page = browser.new_page()
                        errors, missing = [], []
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.on('response', lambda response: missing.append(response.url)
                            if '/static/' in response.url and response.status >= 400 else None)
                        page.goto('http://127.0.0.1:18865' + route, wait_until='domcontentloaded', timeout=45000)
                        page.wait_for_timeout(400)
                        if route == '/fada-wang':
                            page.wait_for_function('Array.isArray(window.qaData) && window.qaData.length > 0')
                        browser_results.append({'route': route, 'javascript_errors': errors, 'missing_assets': missing})
                        assert not errors and not missing, browser_results[-1]
                        page.close()
                    browser.close()
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
                (root / 'uploads/anonymous-keep.txt').write_text('recipient attachment', encoding='utf-8')
                shutdown.touch()
                child.wait(timeout=45)
                shutdown.unlink()
                ready.unlink(missing_ok=True)
                child = subprocess.Popen([str(args.executable.resolve()), '--runtime', str(root),
                    '--app-build', '2', '--ready-token', token, '--shutdown-file', str(shutdown)], stdout=log, stderr=log)
                deadline = time.monotonic() + 120
                while not ready.exists():
                    if child.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError('Anonymous upgrade did not become ready')
                    time.sleep(0.25)
                saved = requests.get('http://127.0.0.1:18865/api/fada-notes', params={'id': item['id']}, timeout=15)
                assert saved.json()['content'] == '匿名升级保留测试'
                assert (root / 'uploads/anonymous-keep.txt').read_text(encoding='utf-8') == 'recipient attachment'
                assert list((root / 'data/history_backups').glob('before-app-2-*.db'))
                with sqlite3.connect(root / 'legal_kb.db') as db:
                    assert db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
                db.close()
                Path('build/windows-smoke-result.json').write_text(json.dumps({'passed': True, 'routes': checked,
                    'browser_pages': browser_results, 'anonymous_profile': True, 'notes_and_attachment_preserved': True,
                    'upgrade_backup': True, 'fada_word_export': True}), encoding='utf-8')
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
