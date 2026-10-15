"""Exercise knowledge-match UI only against the disposable anonymous preview."""
import argparse
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]


def run(output):
    output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='stella-knowledge-browser-') as tmp:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        process=subprocess.Popen([sys.executable,str(ROOT/'scripts/case_workflow_preview.py'),'--port',str(port),'--runtime',tmp],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            base=f'http://127.0.0.1:{port}'
            for _ in range(80):
                try:urllib.request.urlopen(base+'/case-workflows',timeout=1).close();break
                except Exception:time.sleep(.1)
            else:raise RuntimeError('anonymous fixture server did not start')
            with sync_playwright() as p:
                try:browser=p.chromium.launch(headless=True)
                except Exception:browser=p.chromium.launch(headless=True,channel='chrome')
                page=browser.new_page(viewport={'width':1440,'height':900});errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(base+'/case-workflows?case_id=1')
                page.locator('#knowledgeMode').click()
                assert page.locator('#knowledgeOptions').is_visible()
                assert '文章片段' in page.locator('#analysisDisclosure').inner_text()
                frame=page.frame_locator('#filePicker')
                frame.locator('.file-row').filter(has_text='01_合同.pdf').click()
                frame.locator('#archiveAssignBtn').click()
                assert '关联知识' in frame.locator('[data-code="source"]').inner_text()
                frame.locator('[data-code="source"]').click()
                page.locator('#sources .source-row').wait_for()
                page.locator('#knowledgePosition').fill('代理被告')
                page.locator('#submit').click()
                page.locator('.knowledge-card').wait_for(timeout=20000)
                assert page.locator('.knowledge-card').count()==1
                assert '支持论证' in page.locator('.knowledge-card').inner_text()
                assert '风险提示' in page.locator('.knowledge-card').inner_text()
                page.locator('[data-knowledge-details] > summary').click()
                page.locator('[data-article-context] details').wait_for()
                assert '一致' in page.locator('[data-article-state]').inner_text()
                page.locator('[data-article-context] summary').click()
                page.locator('[data-knowledge-source]').first.click()
                assert page.locator('#preview').is_visible()
                page.keyboard.press('Escape')
                page.locator('[data-knowledge-add]').click()
                page.get_by_text('已加入案件研究',exact=True).wait_for()
                page.locator('[data-knowledge-add]').click()  # Existing API is idempotent.
                page.locator('#knowledgeQuestions').fill('付款凭证与合同约定的对应关系')
                page.locator('#knowledgeQuestions').blur()
                page.wait_for_function('!document.getElementById("toast").classList.contains("visible")')
                for width,height in [(1440,900),(1024,768)]:
                    page.set_viewport_size({'width':width,'height':height})
                    for dark in [False,True]:
                        page.evaluate('(d)=>{document.documentElement.classList.toggle("dark-mode",d);document.documentElement.dataset.theme=d?"dark":"light"}',dark)
                        page.evaluate('window.scrollTo(0,0)')
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                        page.screenshot(path=str(output/f'案件关联知识-{width}-{"dark" if dark else "light"}.png'),full_page=True)
                links=page.locator('#detail > .downloads a').evaluate_all('(links)=>links.map(a=>({url:a.getAttribute("href"),name:a.textContent}))')
                assert len(links)==2
                for link in links:
                    response=page.request.get(base+link['url']);assert response.ok
                    (output/link['name']).write_bytes(response.body())
                page.locator('#rerunKnowledge').click()
                page.wait_for_function('document.querySelectorAll("#tasks [data-job]").length===2')
                page.locator('.knowledge-card').wait_for(timeout=20000)
                assert not errors,errors
                browser.close()
        finally:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()
    print('knowledge-match browser interactions passed')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    run(parser.parse_args().output)
