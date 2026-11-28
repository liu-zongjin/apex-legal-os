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
   assert page.locator('.timeline-mini [data-mini-target]').count()==2
   assert page.locator('.case-bar .segmented[aria-label=办理事项]').bounding_box()['x'] < page.locator('#caseSearch').bounding_box()['x']
   page.set_viewport_size({'width':1440,'height':500})
   page.locator('.timeline-mini [data-mini-target]').last.click()
   page.wait_for_function("document.querySelector('.timeline-mini [data-mini-target]:last-child').getAttribute('aria-current')==='true'")
   nav=page.locator('.case-bar').bounding_box();legend=page.locator('.timeline-legend').bounding_box()
   assert abs(legend['y']-(nav['y']+nav['height'])) <= 2, (nav,legend)
   assert '到日' not in page.locator('.timeline-list').inner_text()
   page.locator('.timeline-workbench').evaluate("el => el.classList.add('timeline-animate')")
   assert page.locator('.timeline-pair').first.evaluate("el => parseFloat(getComputedStyle(el).animationDuration)") >= .6
   page.locator('.timeline-workbench').evaluate("el => el.classList.remove('timeline-animate')")
   page.set_viewport_size({'width':1440,'height':900})
   page.screenshot(path=str(p/'timeline-desktop.png'))
   page.locator('[data-time-event]').first.click();assert page.locator('.timeline-editor').is_visible()
   page.locator('[data-time-source]').first.click();page.frame_locator('#sourcePreview').locator('#page').wait_for();page.keyboard.press('Escape')
   page.locator('#closeTimelineReview').click();page.locator('.case-actions').hover();page.locator('.timeline-tools > summary').click();assert page.locator('[data-time-category]').first.is_visible()
   page.locator('[data-time-party="原告方"]').click();assert page.locator('.timeline-entry').count()==1
   page.set_viewport_size({'width':390,'height':844});page.locator('.case-actions').hover();page.locator('.timeline-tools > summary').click() if page.locator('.timeline-tools').get_attribute('open') is not None else None
   assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
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
