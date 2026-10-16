const fs = require('fs');
const assert = require('assert');
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({headless:true, channel:process.env.STELLA_UI_BROWSER || 'chrome'});
  const page = await browser.newPage({viewport:{width:1440,height:900}});
  let state = {enabled:true,auto_save:true,items:[]}, nextId = 1, failNext = false;
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.route('http://memory.test/api/user-memory**', async route => {
    if (failNext) { failNext = false; return route.fulfill({status:500,json:{detail:'保存失败，请重试'}}); }
    const request = route.request(), method = request.method();
    const path = new URL(request.url()).pathname.replace('/api/user-memory','');
    const body = request.postDataJSON();
    if (method === 'POST') state.items.unshift({id:nextId++,content:body.content,kind:'personal',case_id:0,status:'active',version:1,source:'manual',updated_at:'2026-10-12 10:00:00'});
    if (method === 'PUT' && path === '/settings') Object.assign(state,body);
    if (method === 'PUT' && path !== '/settings') state.items.find(item=>item.id===Number(path.slice(1))).content = body.content;
    if (method === 'DELETE') state.items = path ? state.items.filter(item=>item.id!==Number(path.slice(1))) : [];
    await route.fulfill({status:200,json:state});
  });
  await page.route('http://memory.test/', route => route.fulfill({status:200,contentType:'text/html',body:'<html><head><meta charset="utf-8"></head><body><button id="entry" onclick="openUserMemory()">长期记忆</button></body></html>'}));
  await page.goto('http://memory.test/');
  for (const file of ['apex-design-tokens.css','style.css','user-memory.css']) await page.addStyleTag({content:fs.readFileSync('frontend/'+file,'utf8').replace(/@import[^;]+;/g,'')});
  await page.addScriptTag({content:fs.readFileSync('frontend/user-memory.js','utf8')});
  await page.click('#entry');
  await page.waitForFunction(()=>document.querySelector('#memory-status').textContent==='');
  if (!(await page.locator('.memory-compose').evaluate(n=>n.open))) await page.locator('.memory-compose > summary').click();
  await page.fill('#memory-content','称呼我为小林');
  await page.click('#memory-editor button[type="submit"]');
  await page.waitForFunction(()=>document.querySelector('#memory-status').textContent==='记忆已保存。');
  assert.equal(state.items.length,1);
  await page.click('[data-action="edit"]'); await page.fill('#memory-content','先给结论，再列依据');
  await page.click('#memory-editor button[type="submit"]');
  await page.waitForFunction(()=>document.querySelector('#memory-list').textContent.includes('先给结论'));
  await page.fill('#memory-search','无匹配');
  assert((await page.textContent('#memory-list')).includes('没有匹配'));
  await page.fill('#memory-search','');
  // User text is displayed literally, including hostile HTML.
  if (!(await page.locator('.memory-compose').evaluate(n=>n.open))) await page.locator('.memory-compose > summary').click();
  await page.fill('#memory-content','<img src=x onerror="window.memoryXss=1">');
  await page.click('#memory-editor button[type="submit"]');
  await page.waitForFunction(()=>document.querySelectorAll('.user-memory-item').length===2);
  assert.equal(await page.locator('#memory-list img').count(),0);
  await page.click('#memory-enabled');
  await page.waitForFunction(()=>document.querySelector('#memory-status').textContent==='设置已保存。');
  assert.equal(state.enabled,false); assert(await page.isDisabled('#memory-auto'));
  assert.equal(state.items.length,2);
  await page.click('#memory-enabled');
  await page.waitForFunction(()=>!document.querySelector('#memory-auto').disabled);
  await page.click('[data-action="clear"]'); await page.click('[data-action="cancel-delete"]');
  assert.equal(state.items.length,2);
  await page.click('[data-action="clear"]'); await page.click('[data-action="confirm-delete"]');
  await page.waitForFunction(()=>document.querySelector('#memory-status').textContent==='已删除记忆。');
  assert.equal(state.items.length,0);
  failNext = true; await page.locator('.memory-compose > summary').click(); await page.fill('#memory-content','错误后保留草稿');
  await page.click('#memory-editor button[type="submit"]');
  await page.waitForFunction(()=>document.querySelector('#memory-status').textContent==='保存失败，请重试');
  assert.equal(await page.inputValue('#memory-content'),'错误后保留草稿');
  assert(!(await page.isDisabled('#memory-content')));
  // Layout QA uses anonymous fixtures only.
  state.items = [{id:4,content:'称呼我为小林。回答时先给结论，再列依据。',kind:'personal',case_id:0,status:'active',version:1,source:'manual',updated_at:'2026-10-12 10:00:00'}];
  await page.click('[data-action="close"]'); await page.click('#entry');
  await page.waitForFunction(()=>document.querySelector('#memory-list').textContent.includes('小林'));
  fs.mkdirSync('outputs/user-memory',{recursive:true});
  for (const size of [{width:1440,height:900},{width:1024,height:768}]) {
    await page.setViewportSize(size);
    for (const dark of [false,true]) {
      await page.evaluate(d=>document.body.classList.toggle('dark-mode',d),dark);
      await page.screenshot({animations:'disabled',path:`outputs/user-memory/${size.width}-${dark?'dark':'light'}.png`});
      assert(await page.locator('#user-memory-panel .user-memory-modal').evaluate(el=>el.scrollWidth<=el.clientWidth+1));
    }
  }
  await page.setViewportSize({width:390,height:844});
  assert(await page.locator('#user-memory-panel .user-memory-modal').evaluate(el=>el.scrollWidth<=el.clientWidth+1));
  await page.evaluate(()=>document.querySelector('[data-action="close"]').focus());
  await page.keyboard.press('Shift+Tab');
  assert.equal(await page.evaluate(()=>document.activeElement.dataset.action),'clear');
  await page.keyboard.press('Escape');
  assert.equal(await page.evaluate(()=>document.activeElement.id),'entry');
  assert.equal(errors.length,0,errors.join('\n'));
  await browser.close();
  console.log('Memory UI: CRUD, search, errors, safe text, settings, confirmations, focus and responsive light/dark layout passed');
})().catch(error=>{console.error(error);process.exit(1);});
