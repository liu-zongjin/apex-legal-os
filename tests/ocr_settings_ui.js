/* Synthetic credentials and mocked OCR; never contacts SCNet or a live database. */
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),http=require('http'),assert=require('node:assert/strict'),acorn=require('acorn');
const root=path.resolve(__dirname,'..'),out=path.join(root,'.tmp/ocr-settings-ui');fs.mkdirSync(out,{recursive:true});
const app=fs.readFileSync(path.join(root,'frontend/app.js'),'utf8'),tree=acorn.parse(app,{ecmaVersion:'latest'});
const entryFunction=tree.body.find(n=>n.type==='FunctionDeclaration'&&n.id.name==='openOcrSettingsFromSettings');assert(entryFunction);
assert.match(app,/const SETTINGS_TAB_TYPES = new Set\(\[[\s\S]*?TAB_TYPES\.OCR_SETTINGS/);
assert.match(app,/\(type === TAB_TYPES\.OCR_SETTINGS\) \|\|/);
assert.match(app,/case TAB_TYPES\.OCR_SETTINGS:[\s\S]*?src="\/ocr-settings"/);
const index=fs.readFileSync(path.join(root,'frontend/index.html'),'utf8');
const entry=index.match(/<button class="settings-list-item"[^>]+onclick="openOcrSettingsFromSettings\(\)"[\s\S]*?<\/button>/)[0];
const config={provider:'SCNet · 超算互联网',api_url:'https://api.scnet.cn/api/llm/v1/ocr/recognize',ocr_type:'GENERAL',key_mode:'shared',configured:true,key_masked:'••••TEST',has_dedicated_key:false,managed_mode:false,managed_key:false,test:null};
let tests=0,fail=false,saves=[],delayedGet=null;
function json(res,value){res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify(value));}
const server=http.createServer(async(req,res)=>{
 const url=new URL(req.url,'http://fixture');
 if(url.pathname==='/settings'){
  res.setHeader('Content-Type','text/html; charset=utf-8');res.end(`<meta charset="utf-8">${entry}<script>const TAB_TYPES={OCR_SETTINGS:'ocr_settings'};let settingsReturnTabType;function closeSettingsModal(){}function openTab(type,title){const frame=document.createElement('iframe');frame.src='/ocr-settings';frame.title=title;frame.style='width:100%;height:100vh;border:0';document.body.append(frame);}${app.slice(entryFunction.start,entryFunction.end)}</script>`);return;
 }
 if(url.pathname==='/api/ocr-settings'){
  if(req.method==='PUT'){
   let raw='';for await(const part of req)raw+=part;const body=JSON.parse(raw);saves.push(body);
   config.key_mode=body.key_mode;config.configured=true;config.test=null;
   if(body.api_key){config.key_masked='••••OCR';config.has_dedicated_key=true;}
  }
  if(req.method==='GET'&&delayedGet){const snapshot={...config};const release=delayedGet;delayedGet=null;release(()=>json(res,snapshot));return;}
  json(res,config);return;
 }
 if(url.pathname==='/api/ocr-settings/test'){
  tests++;config.test={ok:!fail,message:fail?'OCR 服务返回 435：SCNet OCR 处理异常；请求编号 fixture-123':'OCR 识别正常',text:fail?'':'STELLA OCR TEST 123456',latency_ms:32,tested_at:'2026-10-25T07:00:00Z'};json(res,config.test);return;
 }
 const file=url.pathname==='/ocr-settings'?'frontend/ocr-settings.html':url.pathname.startsWith('/static/')?'frontend/'+url.pathname.slice(8):'';
 if(file&&fs.existsSync(path.join(root,file))){res.setHeader('Content-Type',file.endsWith('.css')?'text/css':file.endsWith('.js')?'application/javascript':'text/html; charset=utf-8');res.end(fs.readFileSync(path.join(root,file)));return;}
 res.writeHead(404);res.end();
});
(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const origin='http://127.0.0.1:'+server.address().port;
 const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto(origin+'/settings');await page.locator('[onclick="openOcrSettingsFromSettings()"]').click();
  await page.frameLocator('iframe').locator('#test-button:not([disabled])').waitFor();assert.equal(tests,0);
  assert.equal(await page.locator('iframe').getAttribute('title'),'OCR 配置与测试');
  await page.goto(origin+'/ocr-settings');await page.locator('#test-button:not([disabled])').waitFor();
  await page.locator('#test-button').click();await page.getByText('OCR 识别正常',{exact:true}).waitFor();assert.equal(tests,1);
  await page.locator('[data-mode="dedicated"]').click();await page.locator('#api-key').fill('FAKE-OCR-KEY');
  assert.equal(await page.locator('#test-button').isDisabled(),true);
  await page.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));
  assert.equal(await page.locator('#api-key').inputValue(),'FAKE-OCR-KEY');
  await page.locator('#save-button').click();await page.getByText('配置已保存，新的 OCR 请求立即生效。',{exact:true}).waitFor();
  assert.deepEqual(saves.at(-1),{key_mode:'dedicated',api_key:'FAKE-OCR-KEY'});
  assert.equal(await page.locator('#api-key').inputValue(),'');assert.equal(tests,1);
  fail=true;await page.locator('#test-button').click();await page.getByText(/OCR 服务返回 435/).waitFor();
  assert.equal(await page.locator('#test-text').isVisible(),false);assert.equal(tests,2);
  assert.match(await page.locator('#test-state').innerText(),/失败/);
  // A focus refresh that completes while the user types must not erase the draft.
  let complete;const intercepted=new Promise(resolve=>{delayedGet=release=>{complete=release;resolve();};});
  await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await intercepted;
  await page.locator('#api-key').fill('UNSAVED-DRAFT');complete();await page.waitForTimeout(100);
  assert.equal(await page.locator('#api-key').inputValue(),'UNSAVED-DRAFT');
  await page.locator('[data-mode="shared"]').click();await page.locator('#save-button').click();
  await page.getByText('配置已保存，新的 OCR 请求立即生效。',{exact:true}).waitFor();assert.equal(saves.at(-1).key_mode,'shared');
  for(const width of [1440,1024,390])for(const dark of [false,true]){
   await page.setViewportSize({width,height:900});await page.evaluate(d=>{localStorage.setItem('theme',d?'dark':'light');window.dispatchEvent(new Event('storage'));},dark);
   assert.equal(await page.evaluate(()=>document.body.classList.contains('dark-mode')),dark);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
   await page.screenshot({path:path.join(out,`ocr-${width}-${dark?'dark':'light'}.png`),fullPage:true});
  }
  config.managed_mode=config.managed_key=true;await page.reload();await page.locator('#test-button:not([disabled])').waitFor();
  assert.equal(await page.locator('[data-mode="dedicated"]').isDisabled(),true);
  assert.deepEqual(errors,[]);console.log('OCR_SETTINGS_UI_OK: navigation, save/test, drafts, errors, theme, narrow screens, managed credentials');
 }finally{await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
