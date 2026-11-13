# coding: utf-8
import sqlite3, tempfile, threading, socket, time
from pathlib import Path
from contextlib import contextmanager
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from playwright.sync_api import sync_playwright
import backend.personal_center as pc

with tempfile.TemporaryDirectory() as temp:
    keys = {}
    pc._vault_read_key = lambda: keys.get('key', '')
    pc._vault_write_key = lambda value: keys.update(key=value)
    @contextmanager
    def db():
        conn = sqlite3.connect(str(Path(temp)/'isolated.sqlite')); conn.row_factory = sqlite3.Row
        try:
            yield conn; conn.commit()
        except Exception:
            conn.rollback(); raise
        finally: conn.close()
    app = FastAPI(); pc.register_personal_center_routes(app, db, Path('frontend')); app.mount('/static', StaticFiles(directory='frontend'), name='static')
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error'))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started: break
        time.sleep(.05)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
        page = browser.new_page(viewport={'width': 1440, 'height': 900}); calls = []
        page.on('request', lambda r: calls.append(r.url) if not r.url.startswith('http://127.0.0.1:') else None)
        page.goto('http://127.0.0.1:%d/personal-center' % port)
        page.fill('#setupPassword1', 'local-test'); page.fill('#setupPassword2', 'local-test'); page.get_by_role('button', name='设置密码').click()
        page.wait_for_selector('.vault-workspace'); assert page.locator('.vault-hero').count() == 0
        page.locator('#topActions').get_by_role('button', name='添加账号').click()
        assert page.locator('.vault-modal').is_visible() and not page.locator('#drawer').evaluate("e => e.classList.contains('show')")
        page.fill('#vaultPaste', '平台：示例站点\n网址：https://example.test/login\n账号：first-user\n密码：Secret!42')
        page.click('#vaultRecognizeButton'); assert page.locator('#vaultPreview').is_visible()
        assert page.input_value('#vaultAccount') == '' and 'Secret!42' not in page.locator('#vaultPreview').inner_text()
        page.click('#vaultPreviewToggle'); assert 'Secret!42' in page.locator('#vaultPreview').inner_text()
        page.click('#vaultApplyRecognition'); assert page.input_value('#vaultSite') == '示例站点' and page.input_value('#vaultAccount') == 'first-user' and page.input_value('#vaultPassword') == 'Secret!42' and page.input_value('#vaultUrl') == 'https://example.test/login'
        page.fill('#vaultUrl', 'javascript:alert(1)'); page.click('#vaultSaveButton'); assert page.locator('#vaultEditorMask').count() == 1
        page.fill('#vaultUrl', 'https://example.test/login'); page.click('#vaultSaveButton'); page.wait_for_selector('.vault-entry'); assert 'Secret!42' not in page.locator('#vaultList').inner_text()
        page.fill('#vaultSearchAccount', 'first'); page.fill('#vaultSearchPassword', 'secret'); page.fill('#vaultSearchSite', 'example.test'); assert page.locator('.vault-entry').count() == 1
        page.fill('#vaultSearchSite', '不匹配'); assert page.locator('.vault-entry').count() == 0
        page.get_by_role('button', name='清除筛选').click(); page.fill('#vaultSearch', 'Secret!42'); assert page.locator('.vault-entry').count() == 1
        page.get_by_role('button', name='清除筛选').click(); page.fill('#vaultSearch', 'first 示例 Secret'); assert page.locator('.vault-entry').count() == 1; page.get_by_role('button', name='清除筛选').click()
        page.evaluate("window.open = (url, target, features) => { window.__testOpen = { url, target, features }; }")
        page.get_by_role('button', name='打开 示例站点 的网址').click()
        assert page.evaluate('window.__testOpen.url') == 'https://example.test/login'
        assert page.evaluate('window.__testOpen.target') == '_blank'
        page.context.grant_permissions(['clipboard-read', 'clipboard-write'])
        page.get_by_role('button', name='复制 示例站点 的账号').click(); assert page.evaluate('navigator.clipboard.readText()') == 'first-user'
        page.get_by_role('button', name='复制 示例站点 的密码').click(); assert page.evaluate('navigator.clipboard.readText()') == 'Secret!42'
        page.get_by_role('button', name='显示 示例站点 的密码').click(); assert 'Secret!42' in page.locator('#vaultList').inner_text()
        page.locator('.vault-entry').get_by_role('button', name='编辑').click(); assert page.locator('.vault-modal').is_visible(); page.fill('#vaultSite', '示例站点更新'); assert page.input_value('#vaultUrl') == 'https://example.test/login'; page.click('#vaultSaveButton'); page.wait_for_selector('text=示例站点更新')
        page.locator('#topActions').get_by_role('button', name='添加账号').click()
        page.fill('#vaultPaste', 'test-account\nP@ss-example'); page.click('#vaultRecognizeButton')
        assert '按两行的先后顺序推测' in page.locator('#vaultPreview').inner_text()
        assert 'test-account' in page.locator('#vaultPreview').inner_text()
        page.click('#vaultSwapRecognition')
        assert 'P@ss-example' in page.locator('#vaultPreview').inner_text()
        assert 'test-account' not in page.locator('#vaultPreview').inner_text()
        page.click('#vaultApplyRecognition'); assert page.input_value('#vaultAccount') == 'P@ss-example' and page.input_value('#vaultPassword') == 'test-account'
        page.fill('#vaultAccount', ''); page.fill('#vaultPassword', '')
        page.fill('#vaultPaste', '账号：one\n账号：two\n密码：abc'); page.click('#vaultRecognizeButton'); assert '发现多个账号' in page.locator('#vaultPreview').inner_text()
        page.click('#vaultApplyRecognition'); assert page.input_value('#vaultAccount') == '' and page.input_value('#vaultPassword') == 'abc'
        page.keyboard.press('Escape'); assert page.locator('#vaultEditorMask').count() == 0
        page.evaluate("localStorage.setItem('theme','dark')"); page.reload(); page.wait_for_selector('.vault-entry')
        page.set_viewport_size({'width': 1024, 'height': 768}); assert page.locator('.vault-filters').is_visible()
        page.set_viewport_size({'width': 390, 'height': 844}); page.locator('#topActions').get_by_role('button', name='添加账号').click()
        assert page.locator('.vault-modal').bounding_box()['width'] <= 390
        page.keyboard.press('Escape')
        page.locator('.vault-entry').get_by_role('button', name='删除').click(); page.locator('#confirmButton').click(); page.wait_for_selector('text=从这里，收好第一个账号')
        assert not calls, 'Unexpected external network request'
        print('Isolated browser checks passed: recognition preview, ambiguity, combined filters, encryption, dark and mobile layouts')
        browser.close()
    server.should_exit = True
