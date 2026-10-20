/* Isolated announcement UI checks. No live app/server/credentials are used. */
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),http=require('http'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
const output=path.join(root,'.tmp/system-messages-ui');fs.mkdirSync(output,{recursive:true});
const fixture={id:'b5307a71-6eb1-4484-b0a8-381a8733ff86',title:'Stella 功能更新通知',body:'这是仅用于本地验证的系统消息。\n新的下载中心支持按大小与时间筛选文件。\n<img src=x onerror="window.injected=true">',published_at:1792440000,withdrawn_at:null};
let items=[fixture],failed=false,requests=0;
const server=http.createServer((req,res)=>{
 const url=new URL(req.url,'http://local');
 if(url.pathname==='/'){
  res.setHeader('Content-Type','text/html; charset=utf-8');
  res.end(`<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><meta name="stella-system-messages" content="https://messages.example.test/v1/messages"><link rel="stylesheet" href="/apex-design-tokens.css"><link rel="stylesheet" href="/apex-system-messages.css"><style>body{margin:0;background:var(--apex-surface-muted);font:14px var(--apex-font-sans);color:var(--apex-text)}nav{padding:16px 28px;display:flex;justify-content:space-between;background:var(--apex-glass);border-bottom:1px solid var(--apex-border-subtle)}.tab-bar-actions{display:flex;gap:20px}.tab-bar-action-btn{background:none;border:0;color:inherit;min-width:32px;min-height:32px;cursor:pointer}.welcome{padding:64px}h1{font-size:32px}</style><script src="/apex-system-messages.js" defer></script></head><body><nav><strong>Stella</strong><div class="tab-bar-actions"><button class="tab-bar-action-btn" id="download-center-btn">下载中心</button></div></nav><main class="welcome"><h1>工作，从容开始。</h1><p>本地界面验证 · 不包含用户数据</p></main></body></html>`);return;
 }
 if(url.pathname==='/admin'){res.setHeader('Content-Type','text/html; charset=utf-8');res.end(fs.readFileSync(path.join(root,'services/public-admin/public/index.html')));return;}
 if(url.pathname==='/api/summary'){res.setHeader('Content-Type','application/json');res.end(JSON.stringify({as_of:1792440000,installations:0,online:0,active_month:0,downloads:null,versions:[],days:[]}));return;}
 if(url.pathname==='/api/messages' && req.method==='GET'){res.setHeader('Content-Type','application/json');res.end(JSON.stringify({messages:items,has_more:false}));return;}
 if(url.pathname==='/api/messages' && req.method==='POST'){
  let content='';req.on('data',chunk=>content+=chunk);req.on('end',()=>{const data=JSON.parse(content);items=[{...fixture,...data}];res.setHeader('Content-Type','application/json');res.end(JSON.stringify(items[0]));});return;
 }
 if(url.pathname.endsWith('/withdraw')){items=items.map(i=>({...i,withdrawn_at:1792440300}));res.setHeader('Content-Type','application/json');res.end('{"ok":true}');return;}
 const file=path.basename(url.pathname);
 const candidate=['apex-system-messages.js','apex-system-messages.css','apex-design-tokens.css'].includes(file)?path.join(root,'frontend',file):path.join(root,'services/public-admin/public',file);
 if(fs.existsSync(candidate) && fs.statSync(candidate).isFile()){res.setHeader('Content-Type',file.endsWith('.css')?'text/css':file.endsWith('.js')?'text/javascript':'text/html');res.end(fs.readFileSync(candidate));return;}
 res.writeHead(404);res.end();
});
(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const origin='http://127.0.0.1:'+server.address().port;
 const browser=await chromium.launch({channel:'chrome',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(()=>{window.testHidden=false;Object.defineProperty(document,'hidden',{get:()=>window.testHidden});});
  await page.route('https://messages.example.test/v1/messages',async route=>{
   requests++;
   if(failed){await route.abort();return;}
   await route.fulfill({json:{messages:items.filter(i=>!i.withdrawn_at).map(({withdrawn_at,...i})=>i)},headers:{'Access-Control-Allow-Origin':'*'}});
  });
  await page.goto(origin);await page.getByRole('button',{name:'系统消息，1 条未读'}).waitFor();
  await page.locator('#system-messages-btn').click();
  await page.locator('.stella-message summary').click();
  await page.waitForFunction(()=>document.getElementById('system-messages-btn').getAttribute('aria-label')==='系统消息');
  assert.equal(await page.evaluate(()=>window.injected),undefined);
  assert.equal(await page.locator('.stella-message-body img').count(),0);
  assert.ok((await page.locator('.stella-message-body').innerText()).includes('<img src=x'));
  for(const width of [1440,1024,390]){
   await page.setViewportSize({width,height:width===390?844:900});
   for(const dark of [false,true]){
    await page.evaluate(d=>document.body.classList.toggle('dark-mode',d),dark);
    await page.screenshot({path:path.join(output,`client-${width}-${dark?'dark':'light'}.png`)});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
   }
  }
  await page.keyboard.press('Escape');assert.equal(await page.evaluate(()=>document.activeElement.id),'system-messages-btn');
  await page.reload();await page.locator('#system-messages-btn').waitFor();
  await page.waitForFunction(()=>document.getElementById('system-messages-status').textContent.startsWith('已同步'));
  await page.waitForFunction(()=>document.getElementById('system-messages-btn').getAttribute('aria-label')==='系统消息');
  await page.clock.install();
  await page.evaluate(()=>{window.testHidden=true;document.dispatchEvent(new Event('visibilitychange'));});
  const before=requests;await page.clock.fastForward(600001);assert.equal(requests,before);
  failed=true;
  await page.evaluate(()=>{window.testHidden=false;document.dispatchEvent(new Event('visibilitychange'));});
  await page.locator('#system-messages-btn').click();
  await page.getByText('暂时无法同步，显示上次获取的消息').waitFor();assert.equal(await page.locator('.stella-message').count(),1);
  failed=false;items=[];
  await page.evaluate(()=>window.dispatchEvent(new Event('online')));await page.getByText('暂无系统消息',{exact:true}).waitFor();
  assert.equal(await page.locator('.stella-message').count(),0);
  // Admin authoring, preview, explicit publish, retract and responsive layout.
  await page.clock.resume();await page.setViewportSize({width:1440,height:900});await page.goto(origin+'/admin');
  await page.getByRole('button',{name:'发布消息',exact:true}).click();
  await page.locator('#message-title').fill('服务维护提示');await page.locator('#message-body').fill('本地验证消息\n请稍后重试。');
  await page.getByRole('button',{name:'预览消息',exact:true}).click();
  await page.locator('#message-preview').waitFor();assert.equal(items.length,0);
  await page.screenshot({path:path.join(output,'admin-preview.png')});
  await page.getByRole('button',{name:'确认发布给所有用户'}).click();
  await page.getByText('已发布，用户联网后将自动获取。').waitFor();assert.equal(items[0].title,'服务维护提示');
  for(const width of [1440,1024,390]){
   await page.setViewportSize({width,height:900});
   for(const dark of [false,true]){
    await page.emulateMedia({colorScheme:dark?'dark':'light',reducedMotion:'reduce'});
    await page.screenshot({path:path.join(output,`admin-${width}-${dark?'dark':'light'}.png`)});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
   }
  }
  await page.getByRole('button',{name:'撤回',exact:true}).click();assert.equal(items[0].withdrawn_at,null);
  await page.getByRole('button',{name:'确认撤回',exact:true}).click();await page.getByText(/已撤回 ·/).waitFor();assert.ok(items[0].withdrawn_at);
  assert.deepEqual(errors,[]);console.log('SYSTEM_MESSAGES_UI_OK: publish/preview/withdraw, text safety, read persistence, offline cache, hidden pause, modal keyboard, light/dark responsive');
 }finally{await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
