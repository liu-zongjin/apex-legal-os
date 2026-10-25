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
                # Layout and menu geometry use anonymous materials at both required widths.
                for width,height in [(1440,900),(1024,768)]:
                    page.set_viewport_size({'width':width,'height':height})
                    page.evaluate('window.scrollTo(0,0)')
                    cards=[page.locator(selector).bounding_box() for selector in ['.materials','.form']]
                    assert abs(cards[0]['y']-cards[1]['y'])<1
                    assert abs(cards[0]['width']-cards[1]['width'])<1
                    controls=[page.locator(selector).bounding_box() for selector in ['#caseSearch','.case-bar .segmented']]
                    assert controls[1]['y'] >= controls[0]['y'] + controls[0]['height'] + 8
                    assert abs(controls[0]['x']-controls[1]['x'])<2
                    assert page.locator('.workflow-guide').bounding_box()['height']<115
                    assert cards[0]['y']<440  # Separate case context and ordered navigation rows.
                    for dark in [False,True]:
                        page.evaluate('(dark)=>{document.documentElement.classList.toggle("dark-mode",dark);document.documentElement.dataset.theme=dark?"dark":"light"}',dark)
                        frame.locator('.file-row').filter(has_text='01_合同.pdf').click()
                        frame.locator('#archiveAssignBtn').click()
                        assert '付款凭证' in frame.locator('[data-code="source"]').inner_text()
                        assert '选一份' in frame.locator('[data-code="draft"]').inner_text()
                        assert frame.locator('#archiveAssignmentMenu').evaluate('(menu)=>{const r=menu.getBoundingClientRect();return r.left>=7&&r.top>=7&&r.right<=innerWidth-7&&r.bottom<=innerHeight-7}')
                        page.screenshot(path=str(output/f'材料选择-{width}-{"dark" if dark else "light"}.png'))
                        frame.locator('[data-code="draft"]').press('ArrowDown')
                        assert frame.locator('[data-code="source"]').evaluate('(el)=>el===document.activeElement')
                        frame.locator('[data-code="source"]').press('Escape')
                        assert not frame.locator('#archiveAssignmentMenu').is_visible()
                        assert frame.locator('#archiveAssignBtn').evaluate('(el)=>el===document.activeElement')
                page.evaluate("document.documentElement.classList.remove('dark-mode');document.documentElement.dataset.theme='light'")
                page.set_viewport_size({'width':1440,'height':900})
                # Tiny iframe: menu remains in bounds and can scroll; resizing repositions it.
                page.locator('#filePicker').evaluate('(el)=>{el.style.minHeight="150px";el.style.height="150px";el.style.flex="none"}')
                frame.locator('#archiveAssignBtn').click()
                assert frame.locator('#archiveAssignmentMenu').evaluate('(el)=>{const r=el.getBoundingClientRect();return r.left>=7&&r.top>=7&&r.right<=innerWidth-7&&r.bottom<=innerHeight-7}')
                frame.locator('[data-code="draft"]').press('Escape')
                page.locator('#filePicker').evaluate('(el)=>el.removeAttribute("style")')
                for mode,label in [('timelineMode','从这些材料提取事件'),('bookMode','把这些材料列为候选证据'),('factMode','用这些材料核对文书')]:
                    page.locator('#'+mode).click()
                    frame.locator('#archiveAssignBtn').click()
                    assert label in frame.locator('[data-code="source"]').inner_text()
                    frame.locator('[data-code="source"]').press('Escape')
                # Choose two PDFs as fact sources using the actual embedded file browser.
                frame.locator('.file-row').filter(has_text='01_合同.pdf').click()
                frame.locator('.file-row').filter(has_text='02_付款凭证.pdf').click(modifiers=['Meta'])
                frame.locator('#archiveAssignBtn').click()
                frame.locator('[data-code="draft"]').click()
                page.wait_for_function("document.getElementById('toast').textContent.includes('请选择一份法律文书')")
                assert not page.locator('#draftFile').inner_text()
                assert '2' in frame.locator('#archiveSelectionCount').inner_text()
                frame.locator('#archiveAssignBtn').click()
                frame.locator('[data-code="source"]').press('Space')
                page.locator('#sources .source-row').nth(1).wait_for()
                assert not frame.locator('#previewMask').evaluate('(el)=>el.classList.contains("show")')
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
                downloads=page.locator('#detail > .downloads a').evaluate_all('(links)=>links.map(link=>({url:link.getAttribute("href"),name:link.textContent}))')
                for download in downloads:
                    assert download['name']
                    response=page.request.get(base+download['url']);assert response.ok
                    (output/download['name']).write_bytes(response.body())
                # Carry the reviewed document/materials into the planning workflow.
                page.locator('#useForBook').click()
                assert page.locator('#bookMode').get_attribute('aria-pressed')=='true'
                page.locator('#submit').click()
                page.locator('#planPanel:not([hidden])').wait_for(timeout=20000)
                page.locator('[data-entry-select="1"]').wait_for()
                page.wait_for_function("!document.getElementById('compileBook').disabled")
                # AI has drafted objective summaries; the lawyer adjusts purposes/source/group.
                assert page.locator('[data-entry="0"] [data-field="summary"]').input_value()
                page.locator('[data-entry="0"] [data-field="purpose"]').fill('证明合同价款及付款日期')
                page.locator('[data-entry="0"] [data-field="origin"]').fill('当事人提供')
                page.locator('[data-entry="0"] [data-field="group"]').fill('合同与履行')
                page.locator('[data-entry-select="1"]').click()
                page.locator('[data-entry="1"] [data-field="purpose"]').fill('证明履行付款义务')
                page.locator('[data-entry-select="0"]').click()
                assert page.locator('[data-entry="0"] [data-field="purpose"]').input_value()=='证明合同价款及付款日期'
                page.locator('[data-entry="0"] [data-preview-material]').click()
                assert page.locator('#inlinePreview').get_attribute('src')
                original=page.frame_locator('#inlinePreview')
                original.locator('#page').wait_for()
                original.locator('#page').evaluate('(image)=>image.decode()')
                assert original.locator('#page').evaluate('(image)=>image.naturalWidth')>0
                page.locator('[data-entry="0"] [data-entry-action="merge"]').click()
                assert page.locator('[data-entry-select]').count()==1
                assert page.locator('[data-entry="0"] [data-material]').count()==2
                page.locator('[data-entry="0"] [data-entry-action="split"]').click()
                assert page.locator('[data-entry-select]').count()==2
                assert page.locator('[data-entry="0"] [data-field="purpose"]').input_value()==''
                page.locator('[data-entry="0"] [data-field="purpose"]').fill('证明合同约定')
                page.locator('[data-entry="0"] [data-claim="1"]').check()
                page.locator('[data-entry="0"] [data-claim="2"]').check()
                page.locator('[data-entry-select="1"]').click()
                page.locator('[data-entry="1"] [data-field="summary"]').fill('付款凭证载明付款金额与日期')
                page.locator('[data-entry="1"] [data-field="purpose"]').fill('证明履行付款义务')
                page.locator('[data-entry="1"] [data-claim="3"]').check()
                page.locator('[data-entry="1"] [data-entry-action="up"]').click()
                assert '02_付款凭证.pdf' in page.locator('[data-entry="0"]').inner_text()
                page.locator('[data-entry="0"] [data-pages]').fill('99')
                assert page.locator('#compileBook').is_disabled()
                page.locator('[data-entry="0"] [data-pages]').fill('1')
                page.locator('[data-entry-select="1"]').click()
                page.locator('[data-entry="1"] [data-pages]').fill('99')
                page.locator('[data-entry-select="0"]').click()
                assert page.locator('#compileBook').is_disabled()  # Invalid pages in an inactive item still block export.
                page.locator('[data-entry-select="1"]').click()
                page.locator('[data-entry="1"] [data-pages]').fill('')
                page.locator('[data-entry-select="0"]').click()
                page.locator('#savePlan').click()
                page.wait_for_function("document.getElementById('toast').textContent.includes('编排草稿已保存')")
                page.locator('[data-entry="0"] [data-field="summary"]').fill('这条修改不应保留')
                page.locator('#restorePlan').click()
                page.wait_for_function("document.getElementById('toast').textContent.includes('已载入最后保存')")
                assert page.locator('[data-entry="0"] [data-field="summary"]').input_value()=='付款凭证载明付款金额与日期'
                page.screenshot(path=str(output/'证据编排-1440-light.png'),full_page=True)
                page.locator('#planPanel').scroll_into_view_if_needed()
                page.screenshot(path=str(output/'证据编排-阅读视图.png'))
                # Persisted editing survives an actual page reload.
                page.reload();frame=page.frame_locator('#filePicker');frame.locator('.file-row').first.wait_for()
                page.locator('#tasks [data-job]').first.click()
                page.locator('#planPanel:not([hidden])').wait_for()
                assert page.locator('[data-entry="0"] [data-field="summary"]').input_value()=='付款凭证载明付款金额与日期'
                page.wait_for_function("!document.getElementById('compileBook').disabled")
                page.locator('#bookConfirmed').check()
                page.locator('#gapsAcknowledged').check()
                page.locator('#compileBook').click()
                page.get_by_text('证据册已生成，请检查页码和目录。',exact=True).wait_for(timeout=20000)
                page.screenshot(path=str(output/'证据册-1440-light.png'),full_page=True)
                # Download artifacts through actual registered routes.
                downloads=page.locator('#detail > .downloads a').evaluate_all('(links)=>links.map(link=>({url:link.getAttribute("href"),name:link.textContent}))')
                for download in downloads:
                    assert download['name']
                    response=page.request.get(base+download['url']);assert response.ok
                    (output/download['name']).write_bytes(response.body())
                page.set_viewport_size({'width':1024,'height':768})
                page.evaluate("document.documentElement.classList.add('dark-mode'); document.documentElement.dataset.theme='dark'")
                frame.locator('html.dark-mode').wait_for()
                page.wait_for_function("getComputedStyle(document.getElementById('refresh')).backgroundColor === 'rgb(25, 31, 42)'")
                page.screenshot(path=str(output/'证据册-1024-dark.png'),full_page=True)
                page.set_viewport_size({'width':1440,'height':900})
                page.screenshot(path=str(output/'证据册-1440-dark.png'),full_page=True)
                page.locator('#tasks [data-job]').last.click()
                assert page.locator('#planPanel').is_hidden()
                assert page.locator('#factMode').get_attribute('aria-pressed')=='true'
                page.screenshot(path=str(output/'事实核对-1440-dark.png'),full_page=True)
                page.set_viewport_size({'width':1024,'height':768})
                page.screenshot(path=str(output/'事实核对-1024-dark.png'),full_page=True)
                page.evaluate("document.documentElement.classList.remove('dark-mode'); document.documentElement.dataset.theme='light'")
                frame.locator('html:not(.dark-mode)').wait_for()
                page.wait_for_function("getComputedStyle(document.getElementById('refresh')).backgroundColor === 'rgb(255, 255, 255)'")
                page.screenshot(path=str(output/'事实核对-1024-light.png'),full_page=True)
                page.locator('#tasks [data-job]').first.click()
                page.screenshot(path=str(output/'证据册-1024-light.png'),full_page=True)
                page.locator('#tasks [data-job]').nth(1).click()
                page.wait_for_function("!document.getElementById('compileBook').disabled")
                page.emulate_media(reduced_motion='reduce')
                page.evaluate("document.documentElement.classList.add('dark-mode'); document.documentElement.dataset.theme='dark'")
                page.locator('#planPanel').scroll_into_view_if_needed()
                page.frame_locator('#inlinePreview').locator('#page').evaluate('(image)=>image.decode()')
                page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
                page.screenshot(path=str(output/'证据编排-1024-dark.png'),animations='disabled')
                page.set_viewport_size({'width':1440,'height':900})
                page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
                page.screenshot(path=str(output/'证据编排-1440-dark.png'),animations='disabled')
                # Material-only chronology, source viewing, reviewed versions and manual additions.
                page.locator('#timelineMode').click()
                page.locator('#draft').fill('')
                page.locator('#submit').click()
                page.locator('#saveTimeline').wait_for(timeout=20000)
                assert page.locator('[data-time-event]').count()==2
                page.locator('[data-time-status="confirmed"]').click()
                page.locator('#saveTimeline').click()
                page.get_by_text('当前成果版本：2',exact=False).wait_for()
                page.locator('[data-time-field="date_text"]').fill('2026年1月2日')
                page.locator('[data-time-field="review_note"]').fill('匿名复核：日期修订测试')
                page.locator('#saveTimeline').click()
                page.get_by_text('当前成果版本：3',exact=False).wait_for()
                page.locator('[data-time-source]').first.click()
                page.frame_locator('#sourcePreview').locator('#page').wait_for()
                page.keyboard.press('Escape')
                page.locator('[data-time-field="description"]').fill('未保存修改')
                page.locator('#restoreTimeline').click()
                page.wait_for_function("document.querySelector('[data-time-field=description]').value !== '未保存修改'")
                page.locator('details:has(#loadTimeFragments) > summary').click()
                page.locator('#loadTimeFragments').click()
                page.locator('[data-time-fragment]').first.wait_for()
                page.locator('[data-time-fragment]').first.click()
                quote=page.locator('#manualSourceText').inner_text()
                page.locator('#manualTimeQuote').fill(quote)
                page.locator('#manualTimeDescription').fill('人工补录匿名事件')
                page.locator('#saveTimeline').click()
                assert page.locator('#manualTimeDescription').input_value()=='人工补录匿名事件'
                page.locator('#addTimeEvent').click()
                page.get_by_text('当前成果版本：4',exact=False).wait_for()
                assert page.locator('[data-time-event]').count()==3
                # Switch styles and hide/show citations before producing immutable exports.
                page.locator('[data-export-style="cards"]').click()
                page.locator('#timelineEvidence').uncheck()
                page.locator('.export-preview > summary').click()
                image=page.locator('.export-paper img')
                image.evaluate('(image)=>image.decode()')
                assert image.evaluate('(image)=>image.naturalWidth')>0
                assert 'style=cards' in image.get_attribute('src')
                assert 'include_evidence=false' in image.get_attribute('src')
                page.locator('#saveTimeline').click()
                page.get_by_text('当前成果版本：5',exact=False).wait_for()
                page.reload();page.locator('#tasks [data-job]').first.wait_for();page.locator('#tasks [data-job]').first.click();page.locator('#saveTimeline').wait_for()
                assert page.locator('[data-export-style="cards"]').get_attribute('aria-pressed')=='true'
                assert not page.locator('#timelineEvidence').is_checked()
                page.locator('[data-export-style="table"]').click()
                page.locator('#timelineEvidence').check()
                page.locator('#saveTimeline').click()
                page.get_by_text('当前成果版本：6',exact=False).wait_for()
                page.locator('.export-preview > summary').click()
                page.locator('.export-paper img').evaluate('(image)=>image.decode()')
                page.screenshot(path=str(output/'时间轴-样式选择与预览.png'),full_page=True)
                page.evaluate('window.scrollTo(0,0)');page.screenshot(path=str(output/'时间轴-1440-dark.png'),full_page=True)
                page.evaluate("document.documentElement.classList.remove('dark-mode'); document.documentElement.dataset.theme='light'")
                page.set_viewport_size({'width':1440,'height':900})
                page.locator('#detailPanel').scroll_into_view_if_needed()
                page.evaluate('window.scrollTo(0,0)');page.screenshot(path=str(output/'时间轴-1440-light.png'),full_page=True)
                downloads=page.locator('#detail > .downloads a').evaluate_all('(links)=>links.map(link=>({url:link.getAttribute("href"),name:link.textContent}))')
                assert len(downloads)==6
                for download in downloads:
                    response=page.request.get(base+download['url']);assert response.ok
                    (output/download['name']).write_bytes(response.body())
                page.set_viewport_size({'width':1024,'height':768})
                page.evaluate('window.scrollTo(0,0)');page.screenshot(path=str(output/'时间轴-1024-light.png'),full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.locator('#detailPanel').scroll_into_view_if_needed()
                assert page.locator('.case-bar').bounding_box()['y']<30
                page.screenshot(path=str(output/'时间轴-1024-阅读视图.png'))
                page.reload()
                page.locator('#tasks [data-job]').first.wait_for()
                page.locator('#tasks [data-job]').first.click()
                page.locator('#saveTimeline').wait_for()
                assert page.locator('[data-time-event]').count()==3
                # The same menu still accepts archive categories without descriptions.
                page.locator('#inputStage').evaluate('(el)=>el.open=true')
                archive=page.locator('#filePicker')
                archive.evaluate('(el)=>el.src=el.src.replace("workflow_picker=1","archive_picker=1")')
                frame.locator('.file-row').first.wait_for()
                archive.evaluate('(el)=>el.contentWindow.postMessage({type:"apex:archive-status",version:1,caseId:1,statuses:{},categories:[{code:"evidence",name:"证据材料"},{code:"pleading",name:"诉讼文书"}]},location.origin)')
                frame.locator('.file-row').filter(has_text='01_合同.pdf').click()
                frame.locator('#archiveAssignBtn').click()
                assert frame.locator('[data-code="evidence"]').inner_text()=='证据材料'
                assert frame.locator('#archiveAssignmentMenu').evaluate('(el)=>{const r=el.getBoundingClientRect();return r.left>=7&&r.right<=innerWidth-7}')
                page.evaluate('window.archiveAssignment=null;window.addEventListener("message",event=>{if(event.origin===location.origin&&event.data?.type==="apex:archive-assign")window.archiveAssignment=event.data})')
                frame.locator('[data-code="evidence"]').press('Enter')
                page.wait_for_function('window.archiveAssignment!==null')
                assert page.evaluate('window.archiveAssignment.itemCode')=='evidence'
                assert page.evaluate('window.archiveAssignment.paths')==['01_合同.pdf']
                assert not errors,errors
                browser.close()
            (output/'browser-result.json').write_text(json.dumps({'passed':True,'console_errors':errors,'fixture_model':True,'scenarios':['真实文件选择','事实初核','人工复核及版本','原文打开','定稿文书与证据关联','AI摘要建议','合并与拆分','选页边界','草稿保存及刷新恢复','证据顺序调整','PDF和Office导出','1440和1024明暗页面','时间轴逐字出处及修订保存','时间轴补录与刷新恢复','六种时间轴导出','三种导出样式及实际预览','隐藏依据后保存与刷新恢复']},ensure_ascii=False,indent=2))
            print('Browser workflow scenarios passed; screenshots and artifacts:',output)
        finally:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=Path(tempfile.gettempdir())/'stella-workflow-ui-qa');args=parser.parse_args();run(args.output)
