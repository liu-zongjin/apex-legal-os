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
                page.locator('[data-knowledge-open]').click()
                assert page.locator('[data-article-context] details').get_attribute('open') is not None
                page.locator('[data-knowledge-source]').first.click()
                assert page.locator('#preview').is_visible()
                page.keyboard.press('Escape')
                page.locator('[data-knowledge-add]').click()
                page.get_by_text('已加入案件研究',exact=True).wait_for()
                page.locator('[data-knowledge-add]').click()  # Existing API is idempotent.
                page.locator('.knowledge-method > summary').click()
                page.locator('#knowledgeQuestions').fill('付款凭证与合同约定的对应关系')
                page.locator('#knowledgeQuestions').blur()
                page.locator('.knowledge-method > summary').click()
                page.wait_for_function('!document.getElementById("toast").classList.contains("visible")')
                for width,height in [(1440,900),(1024,768)]:
                    page.set_viewport_size({'width':width,'height':height})
                    for dark in [False,True]:
                        page.evaluate('(d)=>{document.documentElement.classList.toggle("dark-mode",d);document.documentElement.dataset.theme=d?"dark":"light"}',dark)
                        page.evaluate('window.scrollTo(0,0)')
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                        page.screenshot(path=str(output/f'案件关联知识-{width}-{"dark" if dark else "light"}.png'),full_page=True,animations="disabled")
                        # Wait for theme transitions before checking button contrast.
                        page.wait_for_timeout(220)
                        assert page.evaluate("""() => {
                          const lum=color=>{const rgb=color.match(/[\d.]+/g).slice(0,3).map(Number).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4});return .2126*rgb[0]+.7152*rgb[1]+.0722*rgb[2]};
                          const s=getComputedStyle(document.getElementById('refresh'));const a=lum(s.color),b=lum(s.backgroundColor);return (Math.max(a,b)+.05)/(Math.min(a,b)+.05)>=4.5;
                        }""")
                links=page.locator('#detail > .downloads a').evaluate_all('(links)=>links.map(a=>({url:a.getAttribute("href"),name:a.textContent}))')
                assert len(links)==2
                for link in links:
                    response=page.request.get(base+link['url']);assert response.ok
                    (output/link['name']).write_bytes(response.body())
                page.locator('.knowledge-method > summary').click()
                page.locator('#rerunKnowledge').click()
                page.wait_for_function('document.querySelectorAll("#tasks [data-job]").length===2')
                page.locator('.knowledge-card').wait_for(timeout=20000)
                assert not errors,errors
                # Isolated renderer: exercise >10 rows, escaping, draft retention,
                # no-result state and hidden-host fetch suppression without DB writes.
                isolated=browser.new_page()
                isolated.set_content('<div id="detail"></div>')
                isolated.add_script_tag(url=base+'/static/case-knowledge.js')
                result=isolated.evaluate("""async () => {
                  const row={article_id:1,title:'<img src=x onerror=alert(1)>',types:['risk'],topic_ids:['1'],reason:'具体用途',limits:'待核对',article_evidence:[],case_evidence:[]};
                  const job={id:'renderer-fixture',kind:'knowledge_match',status:'completed',knowledge_topics:[{id:'1',question:'研究问题',terms:[]}],knowledge_recommendations:Array.from({length:12},(_,i)=>({...row,article_id:i+1}))};
                  const mount=()=>document.getElementById('detail').innerHTML=StellaCaseKnowledge.render(job);
                  const ctx={job,busy:false,render:mount,current:()=>true,api:async()=>{throw Error('inactive fetch')}};
                  mount();
                  if(document.querySelectorAll('.knowledge-card').length!==10||document.querySelector('.knowledge-card img'))throw Error('initial count or escaping');
                  const field=document.getElementById('knowledgeQuestions');field.value='保留修改后的问题';field.dispatchEvent(new Event('input',{bubbles:true}));
                  await StellaCaseKnowledge.handle({target:document.getElementById('moreKnowledge')},ctx);
                  if(document.querySelectorAll('.knowledge-card').length!==12||document.getElementById('knowledgeQuestions').value!=='保留修改后的问题')throw Error('expansion lost draft');
                  await StellaCaseKnowledge.handle({target:document.getElementById('moreKnowledge')},ctx);
                  if(document.querySelectorAll('.knowledge-card').length!==10)throw Error('collapse');
                  window.ApexLifecycle={active:false};await StellaCaseKnowledge.hydrate(ctx);
                  if(document.querySelector('[data-article-state]').textContent.includes('读取失败'))throw Error('inactive fetch attempted');
                  job.knowledge_recommendations=[];mount();
                  if(!document.querySelector('.empty-state'))throw Error('empty result missing');
                  return true;
                }""")
                assert result
                isolated.close()
                browser.close()
        finally:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()
    print('knowledge-match browser interactions passed')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    run(parser.parse_args().output)
