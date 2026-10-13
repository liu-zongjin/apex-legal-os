"""Real browser interactions against a disposable anonymous fixture server."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]


def run(output):
    output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='stella-workflow-browser-') as tmp:
        runtime=Path(tmp)
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        process=subprocess.Popen([sys.executable,str(ROOT/'scripts/case_workflow_preview.py'),'--port',str(port),'--runtime',str(runtime)],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        try:
            base=f'http://127.0.0.1:{port}'
            for _ in range(100):
                try:
                    urllib.request.urlopen(base+'/case-workflows',timeout=1).close();break
                except Exception:time.sleep(.1)
            else:raise RuntimeError('fixture server did not start')
            with sync_playwright() as p:
                try:browser=p.chromium.launch(headless=True)
                except Exception:browser=p.chromium.launch(headless=True,channel='chrome')
                page=browser.new_page(viewport={'width':1440,'height':900})
                errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(base+'/case-workflows?case_id=1')
                frame=page.frame_locator('#filePicker')
                frame.locator('.file-row').first.wait_for()
                # Choose two PDFs as fact sources using the actual embedded file browser.
                frame.locator('.file-row').filter(has_text='01_合同.pdf').click()
                frame.locator('.file-row').filter(has_text='02_付款凭证.pdf').click(modifiers=['Meta'])
                frame.locator('#archiveAssignBtn').click()
                frame.locator('[data-code="source"]').click()
                page.locator('#sources .source-row').nth(1).wait_for()
                page.locator('#draft').fill('价款为10000元。付款日期为2026年1月1日。已支付全部价款。')
                page.locator('#submit').click()
                page.locator('#saveReview').wait_for(timeout=20000)
                assert page.locator('[data-result]').count()==3
                page.locator('[data-result="1"] [data-review="confirmed"]').click()
                page.locator('#saveReview').click()
                page.get_by_text('当前成果版本：2',exact=False).wait_for()
                page.locator('[data-source]').first.click()
                assert page.locator('#preview').is_visible()
                page.keyboard.press('Escape')
                assert not page.locator('#preview').is_visible()
                page.screenshot(path=str(output/'事实核对-1440-light.png'),full_page=True)
                # Evidence selection and actual PDF/Office artifacts.
                page.locator('#bookMode').click()
                frame.locator('.file-row').filter(has_text='01_合同.pdf').click()
                frame.locator('.file-row').filter(has_text='02_付款凭证.pdf').click(modifiers=['Meta'])
                frame.locator('#archiveAssignBtn').click();frame.locator('[data-code="evidence"]').click()
                page.locator('[data-entry="1"]').wait_for()
                page.locator('[data-entry="0"] textarea').fill('证明价款及付款日期')
                page.locator('[data-entry="1"] textarea').fill('证明履行付款义务')
                page.locator('[data-entry="1"] [data-entry-action="up"]').click()
                assert '02_付款凭证.pdf' in page.locator('[data-entry="0"]').inner_text()
                page.locator('#bookConfirmed').check();page.locator('#submit').click()
                page.get_by_text('证据册已生成，请检查页码和目录。',exact=True).wait_for(timeout=20000)
                page.screenshot(path=str(output/'证据册-1440-light.png'),full_page=True)
                # Download artifacts through actual registered routes.
                for link in page.locator('#detail .downloads a').all():
                    response=page.request.get(base + link.get_attribute('href'))
                    assert response.ok
                    (output/link.inner_text()).write_bytes(response.body())
                page.set_viewport_size({'width':1024,'height':768})
                page.evaluate("document.documentElement.classList.add('dark-mode'); document.documentElement.dataset.theme='dark'")
                frame.locator('html.dark-mode').wait_for()
                page.wait_for_function("getComputedStyle(document.getElementById('refresh')).backgroundColor === 'rgb(25, 31, 42)'")
                page.screenshot(path=str(output/'证据册-1024-dark.png'),full_page=True)
                page.set_viewport_size({'width':1440,'height':900})
                page.screenshot(path=str(output/'证据册-1440-dark.png'),full_page=True)
                page.locator('#tasks [data-job]').last.click()
                page.screenshot(path=str(output/'事实核对-1440-dark.png'),full_page=True)
                page.set_viewport_size({'width':1024,'height':768})
                page.screenshot(path=str(output/'事实核对-1024-dark.png'),full_page=True)
                page.evaluate("document.documentElement.classList.remove('dark-mode'); document.documentElement.dataset.theme='light'")
                frame.locator('html:not(.dark-mode)').wait_for()
                page.wait_for_function("getComputedStyle(document.getElementById('refresh')).backgroundColor === 'rgb(255, 255, 255)'")
                page.screenshot(path=str(output/'事实核对-1024-light.png'),full_page=True)
                page.locator('#tasks [data-job]').first.click()
                page.screenshot(path=str(output/'证据册-1024-light.png'),full_page=True)
                assert not errors,errors
                browser.close()
            (output/'browser-result.json').write_text(json.dumps({'passed':True,'console_errors':errors,'fixture_model':True,'scenarios':['真实文件选择','事实初核','人工复核及版本','原文打开','证据顺序调整','PDF和Office导出','1440和1024明暗页面']},ensure_ascii=False,indent=2))
            print('Browser workflow scenarios passed; screenshots and artifacts:',output)
        finally:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=Path(tempfile.gettempdir())/'stella-workflow-ui-qa');args=parser.parse_args();run(args.output)
