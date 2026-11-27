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
    failure = browser.new_page()
    failure.set_content('<div class="tab-bar-actions"></div>')
    failure.evaluate("""() => {
      window.StellaWindows={source:true,invoke:async () => { throw 'Stella 找不到 Git'; }};
      Object.defineProperty(navigator,'clipboard',{value:{
        writeText: async (value) => { window.copiedPrompt=value; }
      }});
    }""")
    failure.add_script_tag(content=script)
    failure.get_by_role('button', name='重试检查更新').wait_for()
    assert failure.get_by_role('dialog').count() == 0
    failure.get_by_role('button', name='重试检查更新').click()
    dialog = failure.get_by_role('dialog', name='暂时无法检查源码更新')
    assert dialog.get_by_text('Stella 找不到 Git').is_visible()
    dialog.get_by_role('button', name='复制更新指令').click()
    failure.wait_for_function("window.copiedPrompt?.includes('WINDOWS_SOURCE_DEPLOYMENT.md')")
    failure.evaluate("() => { navigator.clipboard.writeText=async()=>{throw Error('denied')}; }")
    dialog.get_by_role('button', name='已复制更新指令').click()
    box = dialog.get_by_role('textbox', name='AI 更新指令')
    assert 'WINDOWS_SOURCE_DEPLOYMENT.md' in box.input_value()
    box.press('Escape')
    assert dialog.count() == 0
    browser.close()
print('Source update user interface: OK')
