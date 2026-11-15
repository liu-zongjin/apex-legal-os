const fs=require('fs'),path=require('path'),assert=require('assert'),{chromium}=require('playwright');
(async()=>{
const browser=await chromium.launch({headless:true,channel:'chrome'});const page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[];
page.on('pageerror',e=>errors.push(e.message));
await page.route('http://fada-ui.test/**',async route=>{
 const u=new URL(route.request().url()),p=u.pathname;
 if(p.startsWith('/api/')){
  let json={};
  if(p==='/api/ai-ask/history')json={conversations:[]};
  if(p==='/api/ai-ask-models')json={default_model:'deepseek-flash',groups:[{provider:'deepseek',label:'DeepSeek',models:[{value:'deepseek-flash',label:'DeepSeek V4.1 Flash 1017'}]}]};
  if(p==='/api/skills')json={skills:[]};
  if(p==='/api/articles')json={items:[],articles:[],total:0,has_more:false};
  if(p==='/api/ai-ask/history/save')json={version:1};
  if(p==='/api/ai-providers/deepseek/balance')json={ok:true,balance:1,currency:'CNY'};
  if(p==='/api/ai-ask/presets')json={presets:[]};
  if(p==='/api/fada-items')json={items:[],total:0,facets:{topics:[],batches:[],legal_basis:[],procedures:[],experts:[]}};
  return route.fulfill({json});
 }
 let file=p==='/'?'frontend/index.html':p==='/fada-wang'?'fada-wang/fada_wang_search.html':p.startsWith('/static/')?'frontend/'+p.slice(8):null;
 if(file&&fs.existsSync(file))return route.fulfill({path:path.resolve(file),contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.html')?'text/html':'image/png'});
 return route.fulfill({status:404,body:''});
});
await page.goto('http://fada-ui.test/');await page.waitForFunction(()=>typeof openFadaWangTab==='function');
await page.evaluate(()=>openFadaWangTab());
const frame=page.frameLocator('iframe[src="/fada-wang"]');await frame.locator('#fadaAiBtn').click();
await page.waitForFunction(()=>document.querySelector('#ask-panel-title')?.textContent==='法答网 AI增强');
assert.equal(await page.locator('#ask-source-mode-text').innerText(),'仅基于所选法答网精选答问原文回答');
assert.equal(await page.locator('#ask-mcp-source-picker').isVisible(),false);
assert(await page.locator('#ask-skill-btn').isVisible());assert(await page.locator('#ask-preset-btn').isVisible());
assert(await page.locator('#ask-local-files-btn').isVisible());assert(await page.locator('#ask-case-files-btn').isVisible());
await page.waitForTimeout(350);if(process.env.STELLA_FADA_SCREENSHOTS)await page.screenshot({path:process.env.STELLA_FADA_SCREENSHOTS+'/workspace-light.png'});
await page.emulateMedia({colorScheme:'dark'});await page.setViewportSize({width:1024,height:768});await page.evaluate(()=>toggleAskHistorySidebar(false));await page.waitForTimeout(350);
if(process.env.STELLA_FADA_SCREENSHOTS)await page.screenshot({path:process.env.STELLA_FADA_SCREENSHOTS+'/workspace-compact.png'});
assert.deepEqual(errors,[]);console.log('Fada iframe opens the shared AI workspace with common controls and no page errors');await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
