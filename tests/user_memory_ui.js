const fs=require('fs'),assert=require('assert');
const {chromium}=require('playwright');
(async()=>{
  const browser=await chromium.launch({headless:true,channel:process.env.STELLA_UI_BROWSER || 'chrome'});
  const page=await browser.newPage({viewport:{width:1440,height:900}});
  let state={enabled:true,auto_save:true,revision:0,items:[]},nextId=1,failWrite=false,failRead=false,holdRead=false;
  const errors=[],caseRequests=[],writes=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('http://memory.test/api/user-memory**',async route=>{
    const req=route.request(),method=req.method(),url=new URL(req.url()),path=url.pathname.replace('/api/user-memory',''),body=req.postDataJSON();
    if(method!=='GET')writes.push({method,path,body});
    if(method!=='GET' && failWrite){failWrite=false;return route.fulfill({status:500,json:{detail:'保存失败，请重试'}});}
    if(method==='GET' && failRead){failRead=false;return route.fulfill({status:500,json:{detail:'列表暂不可用'}});}
    if(method==='GET' && holdRead){await new Promise(r=>setTimeout(r,150));}
    if(method==='POST')state.items.unshift({id:nextId++,content:body.content,kind:body.kind,case_id:body.case_id,status:'active',version:1,source:'manual',subject:'',updated_at:'2026-10-28 15:00:00'});
    if(method==='PUT' && path==='/settings'){Object.assign(state,body);state.revision++;}
    else if(method==='PUT'){const item=state.items.find(i=>i.id===Number(path.split('/')[1]));Object.assign(item,body);item.version++;state.revision++;}
    if(method==='DELETE'){state.items=path ? state.items.filter(i=>i.id!==Number(path.slice(1))) : [];state.revision++;}
    if(method==='GET' && path.endsWith('/versions'))return route.fulfill({json:{items:[{version:1,content:'匿名旧版本的完整内容。'}]}});
    const cid=Number(url.searchParams.get('case_id') || 0),kind=url.searchParams.get('kind') || 'personal',q=url.searchParams.get('q') || '',offset=Number(url.searchParams.get('offset') || 0),limit=40;
    if(method==='GET')caseRequests.push(cid);
    const inScope=i=>i.kind==='personal' || cid>0 && i.case_id===cid;
    const counts={personal:state.items.filter(i=>i.kind==='personal').length,case:state.items.filter(i=>i.kind==='case' && i.case_id===cid && cid>0).length,pending:state.items.filter(i=>inScope(i) && ['pending','conflict'].includes(i.status)).length};
    const visible=state.items.filter(i=>kind==='pending' ? inScope(i) && ['pending','conflict'].includes(i.status) : i.kind===kind && (kind!=='case' || cid>0 && i.case_id===cid)).filter(i=>i.content.includes(q));
    await route.fulfill({json:{...state,items:visible.slice(offset,offset+limit),counts,total:visible.length,has_more:visible.length>offset+limit,content_limit:4000,scope:{case_id:cid,case_available:cid>0,case_title:cid>0 ? '匿名案件甲' : ''}}});
  });
  await page.route('http://memory.test/',r=>r.fulfill({contentType:'text/html',body:'<html><head><meta charset="utf-8"></head><body><button id="entry" onclick="openUserMemory()">长期记忆</button><script>window.currentCase=8;window.getAiContextLocation=()=>({caseId:window.currentCase});</script></body></html>'}));
  await page.goto('http://memory.test/');
  for(const name of ['apex-design-tokens.css','style.css','user-memory.css'])await page.addStyleTag({content:fs.readFileSync('frontend/'+name,'utf8').replace(/@import[^;]+;/g,'')});
  await page.addScriptTag({content:fs.readFileSync('frontend/user-memory.js','utf8')});
  const waitStatus=txt=>page.waitForFunction(s=>document.querySelector('#memory-status').textContent===s,txt);
  const click=a=>page.locator('#user-memory-panel [data-action="'+a+'"]').filter({visible:true}).first().click();
  await page.click('#entry');await waitStatus('');
  await click('add');await page.fill('#memory-content','称呼我为小林');await page.click('#memory-editor button[type=submit]');await waitStatus('记忆已保存。');assert.equal(state.items.length,1);
  await click('edit');await page.fill('#memory-content','先给结论，再列依据');await page.click('#memory-editor button[type=submit]');await waitStatus('记忆已保存。');
  await page.fill('#memory-search','无匹配');await page.waitForFunction(()=>document.querySelector('#memory-list').textContent.includes('没有匹配'));
  await page.fill('#memory-search','');await page.waitForFunction(()=>document.querySelector('#memory-list').textContent.includes('先给结论'));
  await click('add');await page.fill('#memory-content','<img src=x onerror="window.memoryXss=1">');await page.click('#memory-editor button[type=submit]');await waitStatus('记忆已保存。');assert.equal(await page.locator('#memory-list img').count(),0);
  // Editor never discards changes without an explicit action.
  await click('edit');await page.fill('#memory-content','未保存的修改');await click('close');assert(await page.isVisible('#memory-confirm'));await click('cancel-delete');assert.equal(await page.inputValue('#memory-content'),'未保存的修改');
  failWrite=true;await page.click('#memory-editor button[type=submit]');await waitStatus('保存失败，请重试');assert.equal(await page.inputValue('#memory-content'),'未保存的修改');assert(!(await page.isDisabled('#memory-content')));
  await click('cancel-edit');await click('confirm-delete');
  // Pinned scope: changing the underlying chat does not move an open memory editor.
  await page.evaluate(()=>window.currentCase=9);await page.click('[data-filter=case]');await waitStatus('');assert.equal(caseRequests.at(-1),8);
  await click('add');await page.fill('#memory-content','当前案件专属的匿名背景');await page.click('#memory-editor button[type=submit]');await waitStatus('记忆已保存。');assert.equal(writes.at(-1).body.case_id,8);
  await page.click('[data-action=settings]');await page.click('#memory-enabled');await waitStatus('设置已保存。');assert.equal(state.enabled,false);assert(await page.isDisabled('#memory-auto'));assert.equal(state.items.length,3);
  await page.click('#memory-enabled');await waitStatus('设置已保存。');
  await click('clear');assert((await page.textContent('#memory-confirm-text')).includes('所有案件'));await click('cancel-delete');assert.equal(state.items.length,3);
  await click('clear');await click('confirm-delete');await waitStatus('已删除记忆。');assert.equal(state.items.length,0);
  // A successful write followed by a failed refresh is not offered as a failed save.
  await page.click('[data-filter=personal]');await waitStatus('');await click('add');await page.fill('#memory-content','保存成功而刷新失败');failRead=true;await page.click('#memory-editor button[type=submit]');await page.waitForFunction(()=>document.querySelector('#memory-status').textContent.includes('记忆已保存。 列表未能刷新'));assert.equal(state.items.length,1);
  assert(await page.isDisabled('[data-action=add]'));await page.click('#memory-retry');await waitStatus('已刷新。');
  // Full content remains in the DOM; the compact preview only affects layout.
  state.items=[{id:60,subject:'研究与工作方式',content:'你偏好严谨的分析、可核验的依据与清晰的表达。\n\n'+('这是一条完整的匿名工作偏好，不应被页面或保存操作截断。'.repeat(20))+'\n文末条件：先核对再下结论。',kind:'personal',case_id:0,status:'active',version:2,source:'manual',updated_at:'2026-10-28 15:00:00'}, {id:61,subject:'写作习惯',content:'先给结论，再列明依据。涉及不同意见时，说明适用条件。',kind:'personal',case_id:0,status:'inactive',version:1,source:'manual',updated_at:'2026-10-28 14:00:00'}];
  await click('refresh');await waitStatus('已刷新。');assert((await page.textContent('#memory-list')).includes('文末条件'));await click('expand');assert.equal(await page.locator('.memory-collapsed').count(),0);
  await click('versions');await page.waitForFunction(()=>document.querySelector('#memory-versions').textContent.includes('匿名旧版本'));await click('back');await click('expand');
  fs.mkdirSync('outputs/user-memory',{recursive:true});
  for(const size of [{width:1440,height:900},{width:1024,height:768},{width:390,height:844}]){
    await page.setViewportSize(size);
    for(const dark of [false,true]){
      await page.evaluate(v=>document.body.classList.toggle('dark-mode',v),dark);
      await page.screenshot({animations:'disabled',path:`outputs/user-memory/${size.width}-${dark?'dark':'light'}.png`});
      for(const selector of ['.user-memory-modal','.memory-main','.memory-nav'])assert(await page.locator('#user-memory-panel '+selector).evaluate(n=>n.scrollWidth<=n.clientWidth+1));
    }
  }
  await page.evaluate(()=>document.querySelector('[data-action=close]').focus());await page.keyboard.press('Shift+Tab');assert.notEqual(await page.evaluate(()=>document.activeElement.id),'entry');await page.keyboard.press('Escape');assert.equal(await page.evaluate(()=>document.activeElement.id),'entry');
  // A delayed response from a closed panel cannot replace the next opening's scope.
  holdRead=true;await page.click('#entry');await page.keyboard.press('Escape');await page.evaluate(()=>window.currentCase=0);await page.click('#entry');await waitStatus('');await page.click('[data-filter=case]');await waitStatus('');assert((await page.textContent('#memory-list')).includes('尚未关联案件'));assert(await page.isDisabled('[data-action=add]'));holdRead=false;
  assert.equal(errors.length,0,errors.join('\n'));await browser.close();console.log('Memory UI passed: CRUD, preserved drafts, pinned scope, settings, clear confirmation, refresh recovery, full text, versions, stale response, keyboard, responsive light/dark.');
})().catch(e=>{console.error(e);process.exit(1);});
