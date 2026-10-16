const fs = require('fs');
const assert = require('assert');
const {chromium} = require('playwright');
(async () => {
  const browser = await chromium.launch({headless:true,channel:process.env.STELLA_UI_BROWSER || 'chrome'});
  const page = await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[]; page.on('pageerror',e=>errors.push(e.message));
  let rebuilds=0, source=null;
  let state={history_key:'ask_history_fixture',version:2,case_id:901,recall_enabled:1,excluded_json:'[]',summary:'目标：追索本金80万元。用户提供签订日2026年10月1日。待核验付款记录。',summary_version:3,summary_sources:[{id:'u1',role:'user',content:'合同本金80万元'}],jobs:[{state:'complete',error:''}]};
  const usage={history_key:state.history_key,enabled:true,items:[{type:'memory',id:1,kind:'personal',content:'回答时先给结论，再列依据。',source_key:state.history_key,source_message_id:'u1'},{type:'summary',version:3,content:state.summary},{type:'recall',id:'u2',history_key:'ask_history_other',content:'用户提供：合同本金80万元，争议为逾期利息。'}]};
  await page.route('http://context.test/api/ai-context**',async route=>{
    const req=route.request();
    if(req.method()==='PUT') {const body=req.postDataJSON();assert.equal(body.version,state.version);state={...state,recall_enabled:body.recall_enabled,excluded_json:JSON.stringify(body.excluded),summary:body.summary??state.summary,version:state.version+1};}
    if(req.method()==='POST') {rebuilds++;state.jobs=[{state:'pending',error:''}];}
    await route.fulfill({json:state});
  });
  await page.route('http://context.test/',route=>route.fulfill({contentType:'text/html',body:'<html><head><meta charset="utf-8"></head><body><button id="entry" onclick="openAiContext()">上下文</button></body></html>'}));
  await page.goto('http://context.test/');
  for(const file of ['apex-design-tokens.css','style.css','user-memory.css']) await page.addStyleTag({content:fs.readFileSync('frontend/'+file,'utf8').replace(/@import[^;]+;/g,'')});
  await page.evaluate(({usage})=>{window.getAiContextLocation=()=>({historyKey:'ask_history_fixture',caseId:901,usage});window.openAiContextSource=(key,mid)=>window.fixtureSource={key,mid};window.setAiContextVersion=(key,version)=>window.fixtureVersion=version;},{usage});
  await page.addScriptTag({content:fs.readFileSync('frontend/user-memory.js','utf8')});
  await page.click('#entry');await page.waitForFunction(()=>document.querySelector('#context-status').textContent==='整理完成');
  assert.equal(await page.locator('#context-items article').count(),3);
  await page.locator('#context-items summary').first().click();
  await page.check('[data-exclude="memory:1"]');await page.uncheck('#context-recall');
  await page.fill('#context-summary','更正：本金80万元，需核验原始合同。');
  await page.click('[data-context-action="save"]');await page.waitForFunction(()=>document.querySelector('#context-status').textContent==='整理完成' && document.querySelector('#context-summary').value.startsWith('更正'));
  assert.equal(state.version,3);assert.equal(await page.evaluate(()=>window.fixtureVersion),undefined);
  assert.equal(state.recall_enabled,false);assert(JSON.parse(state.excluded_json).includes('memory:1'));assert(state.summary.startsWith('更正'));
  await page.click('[data-context-action="rebuild"]');await page.waitForFunction(()=>document.querySelector('#context-status').textContent==='等待整理');assert.equal(rebuilds,1);
  fs.mkdirSync('outputs/ai-context',{recursive:true});
  for(const width of [1440,1024,390]) {
    await page.setViewportSize({width,height:width===390?844:1000});
    for(const dark of [false,true]) {
      await page.evaluate(d=>document.body.classList.toggle('dark-mode',d),dark);
      await page.screenshot({path:`outputs/ai-context/${width}-${dark?'dark':'light'}.png`,animations:'disabled'});
      const visible=page.locator('.user-memory-modal:visible');assert(await visible.evaluate(el=>el.scrollWidth<=el.clientWidth+1));
    }
  }
  await page.focus('[data-context-action="close"]');await page.keyboard.press('Shift+Tab');
  assert.equal(await page.evaluate(()=>document.activeElement.dataset.contextAction),'save');
  await page.keyboard.press('Escape');assert.equal(await page.evaluate(()=>document.activeElement.id),'entry');
  await page.click('#entry');await page.waitForFunction(()=>document.querySelector('#context-items article'));
  await page.locator('#context-items summary').first().click();
  await page.locator('#context-items button').first().click();
  source=await page.evaluate(()=>window.fixtureSource);assert.equal(source.mid,'u1');
  assert.equal(errors.length,0,errors.join('\n'));
  await browser.close();console.log('Context UI passed: usage, provenance, exclusions, summary edit, recall toggle, retry, keyboard and responsive light/dark.');
})().catch(e=>{console.error(e);process.exit(1);});
