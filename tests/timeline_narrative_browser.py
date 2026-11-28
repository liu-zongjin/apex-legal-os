import os,sys,tempfile,subprocess,time,socket,sqlite3,shutil
from pathlib import Path
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parents[1]

def check_review_columns(editor):
 rows=editor.locator('.timeline-review-row').evaluate_all('''rows => rows.map(row => {
   const [label, control] = row.children;
   const bounds = label.getBoundingClientRect();
   const field = control.getBoundingClientRect();
   return {label:bounds.x, control:field.x, y:bounds.y-field.y};
 })''')
 assert len(rows)==6, rows
 assert len({row['label'] for row in rows})==len({row['control'] for row in rows})==1, rows
 assert all(row['control'] > row['label'] and abs(row['y']) <= 1 for row in rows), rows

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
   if os.environ.get('STELLA_TEST_WEBKIT') == '1':
    browser=play.webkit.launch(headless=True)
   else:
    browser=play.chromium.launch(headless=True,channel="chrome")
   page=browser.new_page(viewport={'width':1440,'height':900});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(f'http://127.0.0.1:{port}/case-workflows?case_id=1')
   page.locator('.timeline-entry').first.wait_for(timeout=30000)
   assert page.locator('.side-client').count()==1
   assert page.locator('.side-other').count()==1
   assert page.locator('.timeline-entry').first.bounding_box()['y']<600
   assert page.locator('.timeline-legend strong').all_text_contents()==['我方材料','对方材料']
   assert page.locator('.timeline-legend').evaluate("el=>getComputedStyle(el).position")=='sticky'
   page.wait_for_function('''() => {
     const nav = document.querySelector('.case-bar').getBoundingClientRect();
     const legend = document.querySelector('.timeline-legend').getBoundingClientRect();
     return Math.abs(nav.left) < 1 && Math.abs(nav.right - innerWidth) < 1 && Math.abs(legend.top - nav.bottom) < 2;
   }''')
   assert page.locator('.case-bar').evaluate("el=>getComputedStyle(el).borderRadius")=='0px'
   assert page.locator('.timeline-legend').evaluate("el=>getComputedStyle(el).backgroundColor") not in ('transparent', 'rgba(0, 0, 0, 0)')
   assert page.locator('.case-fused-legend').count()==0
   assert page.evaluate('''() => {
     const lanes = [...document.querySelectorAll('.timeline-legend .timeline-lane')];
     const colors = lanes.map(node => getComputedStyle(node).color);
     window.applyKnowledgeColorTheme('blue');
     const distinct = colors[0] !== colors[1] && lanes.every((node, i) => getComputedStyle(node).color === colors[i]);
     window.applyKnowledgeColorTheme('red');
     return distinct;
   }''')
   assert page.locator('.timeline-heading,.timeline-card-meta').count()==0
   assert page.locator('#caseTitleName').inner_text()=='匿名合同纠纷'
   assert page.locator('#caseTitleSuffix').inner_text()=='案件中台'
   heading=page.locator('.case-bar-title h1').bounding_box()
   knowledge=page.locator('#knowledgePlus').bounding_box()
   navigation=page.locator('.case-navigation').bounding_box()
   actions=page.locator('.case-actions').bounding_box()
   assert knowledge['x'] >= heading['x'] + heading['width']
   assert navigation['y'] >= heading['y'] + heading['height']
   assert actions['y'] >= heading['y'] + heading['height']
   page.locator('#caseTitleSwitch').click()
   assert page.get_by_label('搜索或切换案件').is_visible()
   assert page.locator('#caseResults').is_visible()
   page.keyboard.press('Escape')
   assert page.locator('#casePickerPopover').is_hidden()
   assert page.locator('#caseTitleSwitch').evaluate('el=>el===document.activeElement')
   page.wait_for_function('''() => {
     const index = document.querySelector('.timeline-mini').getBoundingClientRect();
     const header = document.querySelector('.case-bar').getBoundingClientRect();
     return Math.abs(index.y + index.height/2 - (header.bottom + 8 + innerHeight)/2) < 3;
   }''')
   assert page.locator('.timeline-list').evaluate("el=>getComputedStyle(el,'::before').width")=='3px'
   assert page.locator('.timeline-entry').first.evaluate("el=>getComputedStyle(el,'::before').height")=='2px'
   desc=page.locator('.timeline-event-description').first
   assert desc.evaluate("el=>parseFloat(getComputedStyle(el).fontSize)")>=15
   assert desc.evaluate("el=>Number(getComputedStyle(el).fontWeight)")>=550
   assert page.locator('.timeline-editor').is_hidden()
   page.locator('.side-client [data-time-event]').click()
   editor=page.locator('.timeline-editor');button=editor.locator('#saveTimelineReview')
   check_review_columns(editor)
   assert editor.get_by_label('主体',exact=True).input_value()=='甲'
   axis=page.locator('.timeline-list').bounding_box();panel=editor.bounding_box()
   assert panel['x']>=axis['x']+axis['width']/2-2, (axis,panel)
   assert button.inner_text()=='保存'
   first=button.bounding_box();assert first['y']>=panel['y'] and first['y']+first['height']<=panel['y']+panel['height']+1, (first,panel)
   editor.locator('.timeline-review-body').evaluate('(el)=>el.scrollTop=el.scrollHeight')
   last=button.bounding_box();assert abs(first['y']-last['y'])<=2, (first,last)
   page.locator('#closeTimelineReview').click()
   page.locator('.side-other [data-time-event]').click()
   assert editor.get_by_label('主体',exact=True).input_value()=='乙'
   panel=editor.bounding_box();assert panel['x']+panel['width']<=axis['x']+axis['width']/2+2, (axis,panel)
   page.locator('#closeTimelineReview').click()
   assert page.locator('.timeline-mini [data-mini-target]').count()==2
   page.set_viewport_size({'width':1440,'height':500})
   page.locator('.timeline-mini [data-mini-target]').last.click()
   page.wait_for_function("document.querySelector('.timeline-mini [data-mini-target]:last-child').getAttribute('aria-current')==='true'")
   page.evaluate('''() => {
     const list = document.querySelector('.timeline-list');
     for (let i = 0; i < 6; i++) {
       const row = list.firstElementChild.cloneNode(true);
       for (const button of row.querySelectorAll('[data-time-event]')) button.removeAttribute('data-time-event');
       list.append(row);
     }
     window.scrollTo(0, 200);
   }''')
   page.wait_for_function('''() => {
     const header = document.querySelector('.case-bar').getBoundingClientRect();
     const legend = document.querySelector('.timeline-legend').getBoundingClientRect();
     return header.top <= 1 && Math.abs(legend.top - header.bottom) < 2;
   }''')
   nav=page.locator('.case-bar').bounding_box();legend=page.locator('.timeline-legend').bounding_box()
   assert abs(nav['y']) <= 1 and abs(legend['y']-nav['y']-nav['height'])<2, (nav,legend)
   page.wait_for_function('''() => {
     const index = document.querySelector('.timeline-mini').getBoundingClientRect();
     const header = document.querySelector('.case-bar').getBoundingClientRect();
     return Math.abs(index.y + index.height/2 - (header.bottom + 8 + innerHeight)/2) < 3;
   }''')
   assert page.locator('#refresh').inner_text().strip()=='筛选'
   page.locator('#timelineMore').focus()
   page.keyboard.press('Enter')
   assert page.locator('#topTimelineAdd').evaluate('el => el === document.activeElement')
   page.keyboard.press('ArrowDown')
   assert page.locator('#topTimelineManual').evaluate('el => el === document.activeElement')
   page.keyboard.press('Escape')
   assert page.locator('#timelineMore').evaluate('el => el === document.activeElement')
   page.locator('#refresh').click()
   assert page.locator('#timelineTopFilters').is_visible()
   assert page.locator('#timelineTopMenu').is_hidden()
   popup=page.locator('#timelineTopFilters').bounding_box()
   assert abs((popup['x']+popup['width'])-(nav['x']+nav['width']-17))<30
   assert popup['y'] >= nav['y']+nav['height']-12
   page.mouse.click(5,450)
   assert page.locator('#timelineTopFilters').is_hidden()
   page.locator('[data-time-event]').last.click()
   editor=page.locator('.timeline-editor');assert editor.is_visible()
   check_review_columns(editor)
   editor.locator('[data-time-field=review_note]').fill('暂存的复核意见')
   page.mouse.click(5,450)
   assert editor.is_hidden()
   page.locator('[data-time-event]').last.click()
   assert editor.locator('[data-time-field=review_note]').input_value()=='暂存的复核意见'
   editor.locator('[data-time-field=review_note]').fill('')
   page.locator('#closeTimelineReview').click()
   page.evaluate('window.scrollTo(0,0)')
   page.wait_for_function("Math.abs(document.querySelector('.timeline-legend').getBoundingClientRect().top - document.querySelector('.case-bar').getBoundingClientRect().bottom) < 2")
   assert '具体日期' not in page.locator('.timeline-list').inner_text()
   assert page.locator('.timeline-event .timeline-badge').count()>0
   page.locator('.timeline-workbench').evaluate("el => el.classList.add('timeline-animate')")
   assert .4 <= page.locator('.timeline-entry').first.evaluate("el => parseFloat(getComputedStyle(el).animationDuration)") <= .5
   page.emulate_media(reduced_motion='reduce')
   assert page.locator('.timeline-entry').first.evaluate("el => getComputedStyle(el).animationName")=='none'
   page.emulate_media(reduced_motion='no-preference')
   page.locator('.timeline-workbench').evaluate("el => el.classList.remove('timeline-animate')")
   page.evaluate("window.postMessage({type:'apex:page-visibility',version:1,active:false}, location.origin)")
   page.wait_for_function("!window.ApexLifecycle.active")
   page.evaluate("window.postMessage({type:'apex:page-visibility',version:1,active:true}, location.origin)")
   page.wait_for_function("window.ApexLifecycle.active && document.querySelector('.timeline-workbench').classList.contains('timeline-animate')")
   page.set_viewport_size({'width':1440,'height':900})
   page.screenshot(path=str(p/'timeline-desktop.png'))
   page.locator('[data-time-event]').first.click();assert page.locator('.timeline-editor').is_visible()
   page.locator('.timeline-editor [data-time-source]').first.click();page.frame_locator('#sourcePreview').locator('#page').wait_for();page.keyboard.press('Escape')
   page.locator('#closeTimelineReview').click();page.locator('#refresh').click();assert page.locator('[data-time-category]').first.is_visible()
   page.locator('[data-time-party="原告方"]').click();assert page.locator('.timeline-entry').count()==1
   page.set_viewport_size({'width':390,'height':844});page.locator('#refresh').click() if page.locator('#timelineTopFilters').is_visible() else None
   assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
   page.locator('[data-time-event]').first.click()
   editor=page.locator('.timeline-editor');assert editor.is_visible()
   check_review_columns(editor)
   box=editor.bounding_box();bar=page.locator('.case-bar').bounding_box()
   assert box['x']>=0 and box['x']+box['width']<=390 and box['y']>=bar['y']+bar['height'], (box,bar)
   assert editor.locator('[data-time-field=actors]').input_value()=='甲'
   editor.locator('[data-time-status=confirmed]').click()
   editor.locator('#saveTimelineReview').click()
   page.locator('.timeline-actor').filter(has_text='甲').wait_for()
   assert editor.locator('[data-time-field=actors]').get_attribute('data-source-default') is None
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
   unselected=browser.new_page(viewport={'width':390,'height':844})
   unselected.goto(f'http://127.0.0.1:{port}/case-workflows')
   assert unselected.locator('#caseTitleSwitch').inner_text().strip()=='案件中台'
   unselected.locator('#caseTitleSwitch').click()
   unselected.get_by_label('搜索或切换案件').fill('匿名合同')
   unselected.locator('#caseResults [role=option]').filter(has_text='匿名合同纠纷').click()
   assert unselected.locator('#caseTitleName').inner_text()=='匿名合同纠纷'
   assert unselected.locator('#casePickerPopover').is_hidden()
   assert unselected.evaluate('document.documentElement.scrollWidth <= innerWidth')
   unselected.close()
   long_title='甲方建筑工程有限公司、乙方房地产有限公司、丙方投资管理有限公司、丁方建设发展有限公司、建设工程施工合同纠纷'
   title_page=browser.new_page(viewport={'width':2200,'height':900})
   title_page.route('**/api/case-workflows/cases/1',lambda route:route.fulfill(json={'id':1,'title':long_title,'case_type':'建设工程施工合同纠纷'}))
   title_page.goto(f'http://127.0.0.1:{port}/case-workflows?case_id=1')
   title_page.wait_for_function('(name)=>document.getElementById("caseTitleName").textContent===name',arg=long_title)
   title_page.set_viewport_size({'width':650,'height':900})
   title_page.wait_for_function('document.getElementById("caseTitleName").textContent.includes("等建设工程施工合同纠纷")')
   shortened=title_page.locator('#caseTitleName').inner_text()
   assert shortened in [long_title.split('、')[0]+'等建设工程施工合同纠纷',
                        '、'.join(long_title.split('、')[:2])+'等建设工程施工合同纠纷',
                        '、'.join(long_title.split('、')[:3])+'等建设工程施工合同纠纷'],shortened
   assert long_title in title_page.locator('#caseTitleSwitch').get_attribute('aria-label')
   title_page.set_viewport_size({'width':2200,'height':900})
   title_page.wait_for_function('(name)=>document.getElementById("caseTitleName").textContent===name',arg=long_title)
   title_page.unroute('**/api/case-workflows/cases/1')
   suit_title='甲方建筑工程有限公司 诉 乙方房地产有限公司 诉 丙方投资管理有限公司 诉 丁方建设发展有限公司 之间的建设工程施工合同纠纷'
   title_page.route('**/api/case-workflows/cases/1',lambda route:route.fulfill(json={'id':1,'title':suit_title}))
   title_page.reload()
   title_page.wait_for_function('(name)=>document.getElementById("caseTitleName").textContent===name',arg=suit_title)
   title_page.set_viewport_size({'width':650,'height':900})
   title_page.wait_for_function('document.getElementById("caseTitleName").textContent.includes("等建设工程施工合同纠纷")')
   assert '之间的' not in title_page.locator('#caseTitleName').inner_text()
   title_page.close()
   browser.close()
  print('Narrative timeline browser check passed')
 finally:proc.terminate();proc.wait(timeout=10)
