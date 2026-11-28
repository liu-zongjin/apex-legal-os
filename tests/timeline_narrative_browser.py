import sys,tempfile,subprocess,time,socket,sqlite3,shutil
from pathlib import Path
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='timeline-layout-') as d:
 p=Path(d)
 with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
 proc=subprocess.Popen([sys.executable,str(root/'scripts/case_workflow_preview.py'),'--port',str(port),'--runtime',str(p)],cwd=root,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 try:
  import urllib.request
  for i in range(100):
   try:urllib.request.urlopen(f'http://127.0.0.1:{port}/case-workflows',timeout=1).close();break
   except Exception:time.sleep(.1)
  with sqlite3.connect(p/'fixture.db') as c:
   c.execute('CREATE TABLE case_manager_parties(case_id INTEGER,name TEXT,role TEXT,party_group TEXT,sort_order INTEGER,id INTEGER)')
   c.executemany('INSERT INTO case_manager_parties VALUES(?,?,?,?,?,?)',[(1,'甲','原告','client',0,1),(1,'乙','被告','other',1,2)])
  case=p/'匿名材料'
  for folder,name,source in [('原告方材料','民事起诉状.pdf','01_合同.pdf'),('被告方材料','民事答辩状.pdf','02_付款凭证.pdf')]:
   (case/folder).mkdir();shutil.copyfile(case/source,case/folder/name)
  with sync_playwright() as play:
   browser=play.chromium.launch(headless=True,channel="chrome")
   page=browser.new_page(viewport={'width':1440,'height':900});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(f'http://127.0.0.1:{port}/case-workflows?case_id=1')
   page.locator('.timeline-entry').first.wait_for(timeout=30000)
   assert page.locator('.side-client').count()==1
   assert page.locator('.side-other').count()==1
   assert page.locator('.timeline-entry').first.bounding_box()['y']<600
   assert page.locator('.timeline-editor').is_hidden()
   page.locator('.side-client [data-time-event]').click()
   editor=page.locator('.timeline-editor');button=editor.locator('#saveTimelineReview')
   page.wait_for_timeout(100)
   axis=page.locator('.timeline-list').bounding_box();panel=editor.bounding_box()
   assert panel['x']>=axis['x']+axis['width']/2-2, (axis,panel)
   assert button.inner_text()=='保存'
   first=button.bounding_box();assert first['y']>=panel['y'] and first['y']+first['height']<=panel['y']+panel['height']+1, (first,panel)
   editor.evaluate('(el)=>el.scrollTop=el.scrollHeight')
   last=button.bounding_box();assert abs(first['y']-last['y'])<=2, (first,last)
   page.locator('#closeTimelineReview').click()
   page.locator('.side-other [data-time-event]').click()
   panel=editor.bounding_box();assert panel['x']+panel['width']<=axis['x']+axis['width']/2+2, (axis,panel)
   page.locator('#closeTimelineReview').click()
   assert page.locator('.timeline-mini [data-mini-target]').count()==2
   assert page.locator('.case-bar .segmented[aria-label=办理事项]').bounding_box()['x'] < page.locator('#caseSearch').bounding_box()['x']
   page.set_viewport_size({'width':1440,'height':500})
   page.locator('.timeline-mini [data-mini-target]').last.click()
   page.wait_for_function("document.querySelector('.timeline-mini [data-mini-target]:last-child').getAttribute('aria-current')==='true'")
   nav=page.locator('.case-bar').bounding_box();legend=page.locator('.timeline-legend').bounding_box()
   assert abs(legend['y']-(nav['y']+nav['height'])) <= 2, (nav,legend)
   page.wait_for_function("document.body.classList.contains('timeline-fused')")
   fused=page.locator('.case-fused-legend').bounding_box()
   assert abs(nav['y']) <= 1 and abs(fused['y']-(nav['y']+nav['height']))<=2, (nav,fused)
   assert abs(fused['x']-nav['x'])<=2 and abs(fused['width']-nav['width'])<=2
   page.wait_for_timeout(350)
   assert float(page.locator('.timeline-rail h2').evaluate('(el)=>getComputedStyle(el).opacity'))<.05
   mini=page.locator('.timeline-mini').bounding_box()
   assert abs(mini['y']+mini['height']/2-250)<4, mini
   assert page.locator('#refresh').inner_text()=='筛选'
   page.locator('#refresh').click()
   assert page.locator('.timeline-tools-panel').is_visible()
   assert page.locator('#timelineTopMenu').is_hidden()
   popup=page.locator('.timeline-tools-panel').bounding_box()
   assert abs((popup['x']+popup['width'])-(nav['x']+nav['width']-17))<30
   assert popup['y'] >= nav['y']+nav['height']-12
   page.mouse.click(5,450)
   assert page.locator('.timeline-tools').get_attribute('open') is None
   page.locator('[data-time-event]').last.click()
   page.wait_for_function("document.body.classList.contains('timeline-fused')")
   editor=page.locator('.timeline-editor');assert editor.is_visible()
   fused=page.locator('.case-fused-legend').bounding_box();panel=editor.bounding_box()
   assert panel['y']>=fused['y']+fused['height'], (fused,panel)
   row=editor.locator('.timeline-review-row').first
   assert row.locator('input').bounding_box()['x']>row.locator('span').first.bounding_box()['x']
   editor.locator('[data-time-field=review_note]').fill('暂存的复核意见')
   page.mouse.click(5,450)
   assert editor.is_hidden()
   page.locator('[data-time-event]').last.click()
   assert editor.locator('[data-time-field=review_note]').input_value()=='暂存的复核意见'
   editor.locator('[data-time-field=review_note]').fill('')
   page.locator('#closeTimelineReview').click()
   page.evaluate('window.scrollTo(0,0)')
   page.wait_for_function("!document.body.classList.contains('timeline-fused')")
   assert '具体日期' not in page.locator('.timeline-list').inner_text()
   assert page.locator('.timeline-event .timeline-badge').count()>0
   page.locator('.timeline-workbench').evaluate("el => el.classList.add('timeline-animate')")
   assert page.locator('.timeline-pair').first.evaluate("el => parseFloat(getComputedStyle(el).animationDuration)") >= .6
   page.locator('.timeline-workbench').evaluate("el => el.classList.remove('timeline-animate')")
   page.set_viewport_size({'width':1440,'height':900})
   page.screenshot(path=str(p/'timeline-desktop.png'))
   page.locator('[data-time-event]').first.click();assert page.locator('.timeline-editor').is_visible()
   page.locator('.timeline-editor [data-time-source]').first.click();page.frame_locator('#sourcePreview').locator('#page').wait_for();page.keyboard.press('Escape')
   page.locator('#closeTimelineReview').click();page.locator('#refresh').click();assert page.locator('[data-time-category]').first.is_visible()
   page.locator('[data-time-party="原告方"]').click();assert page.locator('.timeline-entry').count()==1
   page.set_viewport_size({'width':390,'height':844});page.locator('#refresh').click() if page.locator('.timeline-tools').get_attribute('open') is not None else None
   assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
   page.locator('[data-time-event]').first.click()
   editor=page.locator('.timeline-editor');assert editor.is_visible()
   box=editor.bounding_box();bar=page.locator('.case-bar').bounding_box()
   assert box['x']>=0 and box['x']+box['width']<=390 and box['y']>=bar['y']+bar['height'], (box,bar)
   page.locator('#closeTimelineReview').click()
   page.screenshot(path=str(p/'timeline-mobile.png'))
   page.set_viewport_size({'width':1440,'height':500})
   page.evaluate('''() => {
      const list=document.querySelector('.timeline-list'), mini=document.querySelector('.timeline-mini');
      const card=list.querySelector('.timeline-pair'), marker=mini.querySelector('button');
      for(let i=0;i<30;i++){const next=card.cloneNode(true), button=next.querySelector('[data-time-event]');button.dataset.timeEvent='fixture-'+i;list.append(next);const dot=marker.cloneNode(true);dot.dataset.miniTarget='fixture-'+i;dot.removeAttribute('aria-current');mini.append(dot);}
   }''')
   page.locator('[data-time-event="fixture-29"]').evaluate('(node)=>node.scrollIntoView({block:"center"})')
   page.wait_for_function("document.querySelector('[data-mini-target=fixture-29]').getAttribute('aria-current')==='true'")
   assert page.locator('.timeline-mini').evaluate('(node)=>node.scrollTop>0')
   assert not errors,errors
   browser.close()
  print('Narrative timeline browser check passed')
 finally:proc.terminate();proc.wait(timeout=10)
