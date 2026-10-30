"""Exercise the source update button with an isolated native bridge fixture."""
from pathlib import Path
from playwright.sync_api import sync_playwright

script = Path('frontend/apex-windows-updates.js').read_text(encoding='utf-8')
revision = 'a' * 40
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page()
    page.set_content('<div class="tab-bar-actions"></div>')
    page.evaluate('''revision => {
      window.updateCalls=[];
      window.StellaWindows={invoke: async (name, args) => {
        if(name==='check_stella_update') return {source:true,available:true,version:'源码 aaaaaaaa',build:revision};
        window.updateCalls.push({name,args});
      }};
    }''', revision)
    page.add_script_tag(content=script)
    page.get_by_role('button', name='更新至 源码 aaaaaaaa').click()
    page.get_by_role('button', name='已保存，前往更新').click()
    page.wait_for_function("window.updateCalls.some(x => x.name === 'update_source')")
    calls = page.evaluate('window.updateCalls')
    assert next(call for call in calls if call['name'] == 'update_source')['args']['expectedRevision'] == revision
    browser.close()
print('Source update user interface: OK')
