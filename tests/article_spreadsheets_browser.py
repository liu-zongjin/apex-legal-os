"""Anonymous end-to-end workbook and body-table interaction checks."""
import socket
import tempfile
import threading
from pathlib import Path

import uvicorn
from fastapi.staticfiles import StaticFiles
from playwright.sync_api import sync_playwright

from tests.test_article_spreadsheets import env

ROOT=Path(__file__).resolve().parents[1]


def run(browser, base):
    page=browser.new_page(viewport={'width':1440,'height':900})
    errors=[]
    page.on('pageerror',lambda error: errors.append(str(error)))
    page.goto(base+'/article-spreadsheet?article_id=1')
    page.wait_for_selector('#grid td')
    page.locator('#grid td[data-row="2"][data-col="1"]').click()
    page.locator('#value').fill('浏览器编辑')
    page.locator('#apply').click()
    page.locator('#area').fill('A1:C3')
    page.get_by_role('button',name='虚线',exact=True).click()
    assert page.locator('#grid td[data-row="2"][data-col="1"]').evaluate('(e)=>getComputedStyle(e).borderLeftStyle')=='dashed'
    page.locator('#height').fill('40')
    page.locator('#set-height').click()
    page.locator('#width').fill('25')
    page.locator('#set-width').click()
    page.locator('#sheet-name').fill('浏览器新表')
    page.locator('#add-sheet').click()
    page.locator('#save').click()
    page.wait_for_function("document.getElementById('notice').textContent.startsWith('已保存')")
    page.reload()
    page.wait_for_selector('#grid td')
    assert page.locator('#grid td[data-row="2"][data-col="1"]').inner_text()=='浏览器编辑'
    assert page.locator('#grid td[data-row="2"][data-col="1"]').evaluate('(e)=>getComputedStyle(e).borderLeftStyle')=='dashed'
    assert page.locator('#grid tbody tr').nth(1).evaluate('(e)=>e.getBoundingClientRect().height')>=53
    page.get_by_role('button',name='浏览器新表',exact=True).click()
    page.wait_for_function("document.getElementById('position').textContent.startsWith('浏览器新表')")
    page.locator('#value').fill('未保存草稿')
    page.locator('#next').click()
    assert '请先保存' in page.locator('#notice').inner_text()
    assert page.evaluate('ApexWorkbook.hasChanges()')
    page.locator('#discard').click();page.locator('#discard').click()
    page.wait_for_function('!ApexWorkbook.hasChanges()')
    page.locator('#value').fill('<img src=x onerror=alert(1)>')
    page.locator('#save').click()
    page.wait_for_function("document.getElementById('notice').textContent.startsWith('已保存')")
    assert page.locator('#grid img').count()==0
    assert '<img' in page.locator('#grid td').first.inner_text()
    for width,height,theme in ((1440,900,'light'),(1024,768,'dark')):
        page.set_viewport_size({'width':width,'height':height});page.emulate_media(color_scheme=theme)
        assert page.locator('body').evaluate('(e)=>e.scrollWidth<=innerWidth')
    assert errors==[],errors
    page.close()


def body_tables(browser,base):
    page=browser.new_page()
    page.goto(base+'/article-spreadsheet?article_id=1')
    page.set_content('<link rel="stylesheet" href="'+base+'/static/article-tables.css"><div id="edit-body-modal"><div class="format-toolbar"></div><div id="body-editor" contenteditable="true"><p>匿名正文</p></div></div>')
    source=(ROOT/'frontend/app.js').read_text()
    start=source.index('function sanitizeBodyHtml(')
    end=source.index('\nfunction ',start+10)
    sanitizer=source[start:end]
    page.add_script_tag(content='''let _bodyEditorSavedRange=null;function _restoreBodyEditorSelection(){const s=getSelection();if(_bodyEditorSavedRange){s.removeAllRanges();s.addRange(_bodyEditorSavedRange);}}function showToast(text){window.lastToast=text;}function _onBodyEditorInput(){window.inputCount=(window.inputCount||0)+1;}'''+sanitizer)
    page.add_script_tag(url=base+'/static/article-tables.js')
    page.evaluate('''()=>{const r=document.createRange();r.selectNodeContents(document.querySelector('#body-editor p'));r.collapse(false);getSelection().removeAllRanges();getSelection().addRange(r);_bodyEditorSavedRange=r.cloneRange();openArticleTableTools();}''')
    page.get_by_role('button',name='添加表格',exact=True).click()
    assert page.locator('#body-editor table tr').count()==3
    page.locator('#body-editor td').first.click()
    page.locator('#article-table-height').fill('50')
    page.locator('#article-table-spacing').fill('2')
    page.get_by_role('button',name='应用行高与行距').click()
    assert page.locator('#body-editor td').first.evaluate('(e)=>e.style.height')=='50px'
    assert page.locator('#body-editor td').first.evaluate('(e)=>e.style.lineHeight')=='2'
    page.get_by_role('button',name='虚线',exact=True).click()
    assert page.locator('#body-editor td').first.evaluate('(e)=>e.style.borderTopStyle')=='dashed'
    page.get_by_role('button',name='添加行',exact=True).click()
    assert page.locator('#body-editor table tr').count()==4
    page.get_by_role('button',name='添加列',exact=True).click()
    assert page.locator('#body-editor table tr').first.locator('td').count()==4
    cleaned=page.evaluate("sanitizeBodyHtml(document.getElementById('body-editor').innerHTML)")
    assert 'height: 50px' in cleaned and 'line-height: 2' in cleaned and 'dashed' in cleaned
    page.evaluate('(html)=>document.getElementById("body-editor").innerHTML=html',cleaned)
    assert page.locator('#body-editor td').first.evaluate('(e)=>e.style.lineHeight')=='2'
    page.evaluate("""()=>{
      window.tabState={tabs:[{id:'first',data:{articleId:1,article:{content:'old'}}},{id:'second',data:{articleId:2,article:{content:'other'}}}]};
      window.state={currentArticle:tabState.tabs[0].data.article};
      document.body.insertAdjacentHTML('beforeend','<div hidden id="tab-detail-body-first">old</div><div hidden id="tab-detail-body-second">other</div><iframe class="article-workbook-frame" data-article-id="1"></iframe>');
      const frame=document.querySelector('iframe.article-workbook-frame');
      window.dispatchEvent(new MessageEvent('message',{origin:location.origin,source:frame.contentWindow,data:{type:'apex:article-workbook-saved',articleId:1,content:'saved'}}));
    }""")
    assert page.locator('#tab-detail-body-first').text_content()=='saved'
    assert page.locator('#tab-detail-body-second').text_content()=='other'
    page.close()


def main():
    with tempfile.TemporaryDirectory(prefix='article-sheet-test-') as temporary:
        client,connection,_,_,_=env.__wrapped__(Path(temporary))
        app=client.app
        app.mount('/static',StaticFiles(directory=ROOT/'frontend'))
        (Path(temporary)/'article-spreadsheet.html').write_text((ROOT/'frontend/article-spreadsheet.html').read_text())
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        server=uvicorn.Server(uvicorn.Config(app,log_level='error'))
        thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
        import time
        for _ in range(100):
            if server.started:break
            time.sleep(.02)
        try:
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
                run(browser,f'http://127.0.0.1:{port}');body_tables(browser,f'http://127.0.0.1:{port}');browser.close()
                print('Chrome: workbook save/reload, styles, new sheet, draft guard, XSS, light/dark + article body table controls passed')
                with connection() as conn:
                    conn.execute('DELETE FROM app_preferences')
                    conn.execute("UPDATE articles SET content='旧文本' WHERE id=1")
                browser=playwright.webkit.launch(headless=True)
                run(browser,f'http://127.0.0.1:{port}');body_tables(browser,f'http://127.0.0.1:{port}');browser.close()
                print('WebKit: same workbook and body-table workflows passed')
        finally:
            server.should_exit=True;thread.join(timeout=5);sock.close()


if __name__=='__main__':main()
