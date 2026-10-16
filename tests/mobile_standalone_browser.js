// Optional real-worker QA with anonymous data and a fresh standalone storage context.
const {chromium,webkit}=require(process.env.STELLA_PLAYWRIGHT_MODULE || 'playwright');
const http=require('http'),fs=require('fs'),path=require('path'),assert=require('assert');
const phoneHeight=Number(process.env.STELLA_QA_HEIGHT||844);
const root=process.cwd(),version=/SHELL_VERSION = '(\d+)'/.exec(fs.readFileSync(path.join(root,'frontend/case-manager-sw.js'),'utf8'))[1];
const fixtures={'/api/domains':[], '/api/authors':[], '/api/tag-categories':[], '/api/custom-tags':[], '/api/articles':{articles:[],total:0,page:1,page_size:10},'/api/saved-views':[], '/api/brand':{custom:false,revision:'default',configured:false},'/api/server-status':{status:'current'}, '/api/case-manager/dashboard':{counts:{}}, '/api/case-manager/cases':[], '/api/case-manager/todos':[], '/api/case-manager/hearings':[], '/api/case-manager/preservations':[], '/api/case-manager/appeals':[], '/api/case-manager/offline-snapshot':{cases:{active:[],trash:[]},todos:[],hearings:[],preservations:[],appeals:[],snapshot_version:1,generated_at:new Date().toISOString()}};
const sampleCase={id:1,title:'测试案件：'+ '较长的案件名称与当事人信息'.repeat(8),case_type:'民事',parties:[],case_numbers:[],todos:[],hearings:[],preservations:[],appeals:[],audit_logs:[]};
fixtures['/api/case-manager/cases']={items:[sampleCase]};
fixtures['/api/case-manager/cases/1']=sampleCase;
fixtures['/api/case-manager/offline-snapshot'].cases={active:[sampleCase],trash:[]};
for(const tab of ['todos','hearings','preservations','appeals'])fixtures['/api/case-manager/'+tab]={items:[]};
let serverUnavailable=false;
const server=http.createServer((req,res)=>{
 if(serverUnavailable){req.socket.destroy();return;}
 const u=new URL(req.url,'http://localhost');
 const signedIn=(req.headers.cookie||'').includes('fixture_session=yes');
 if(req.method==='POST'&&u.pathname==='/login'){res.writeHead(303,{'Set-Cookie':'fixture_session=yes; Path=/; HttpOnly; SameSite=Lax','Location':'/'});return res.end();}
 if(u.pathname==='/'&&!signedIn || u.pathname==='/login'){res.setHeader('Content-Type','text/html');return res.end('<meta charset="utf-8"><title>登录法律操作系统</title><form action="/login" method="post"><input name="username"><input name="password"><button>登录</button></form>');}
 if(u.pathname==='/api/pwa/session-status'){res.setHeader('Content-Type','application/json');return res.end(JSON.stringify({server_reachable:true,authenticated:signedIn,shell_version:version}));}
 if(u.pathname.startsWith('/api/')&&!signedIn&&!['/api/brand','/api/server-status'].includes(u.pathname)){res.writeHead(401,{'Content-Type':'application/json'});return res.end('{"detail":"login required"}');}
 if(u.pathname==='/api/case-manager/cases'&&u.searchParams.has('case_id')){res.setHeader('Content-Type','application/json');return res.end(JSON.stringify(sampleCase));}
 if(u.pathname.startsWith('/api/')){res.setHeader('Content-Type','application/json');return res.end(JSON.stringify(fixtures[u.pathname]||{}));}
 let file=(u.pathname==='/'||u.pathname==='/app-shell')?'index.html':u.pathname==='/case-manager'?'case-manager.html':u.pathname==='/brand-logo.png'?'stella-brand.png':u.pathname.replace(/^\/static\//,'').slice(u.pathname.startsWith('/static/')?0:1);
 if(u.pathname==='/case-manager-sw.js')file='case-manager-sw.js';
 if(u.pathname.includes('manifest')){res.setHeader('Content-Type','application/manifest+json');return res.end(JSON.stringify({id:'/case-manager',start_url:'/',name:'Stella',display:'standalone'}));}
 const f=path.join(root,'frontend',file);if(!fs.existsSync(f)||fs.statSync(f).isDirectory()){res.statusCode=404;return res.end();}
 res.setHeader('Content-Type',({'.js':'application/javascript','.css':'text/css','.html':'text/html','.png':'image/png'})[path.extname(f)]||'application/octet-stream');
 if(file==='index.html'||file==='case-manager.html')res.setHeader('X-APEX-Shell-Version',version);
 if(file==='case-manager-sw.js')res.setHeader('Service-Worker-Allowed','/');res.end(fs.readFileSync(f));
});
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin='http://127.0.0.1:'+server.address().port;
const useWebKit=process.env.STELLA_QA_WEBKIT==='1';
const browser=await (useWebKit?webkit:chromium).launch(useWebKit?{headless:true,timeout:30000}:{headless:true,executablePath:process.env.STELLA_CHROME_EXECUTABLE || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const context=await browser.newContext({viewport:{width:390,height:phoneHeight},hasTouch:process.env.STELLA_QA_TOUCH==='1',reducedMotion:'reduce'});
await context.addInitScript(()=>Object.defineProperty(navigator,'standalone',{get:()=>true}));
const page=await context.newPage();const errors=[],transportErrors=[];
page.on('pageerror',e=>{
 // WebKit reports cancelled navigation requests and disconnected fixture API requests as transport events.
 if(useWebKit && /127\.0\.0\.1:\d+\/api\//.test(e.message) && e.message.includes('due to access control checks'))transportErrors.push(e.message);
 else errors.push(e.message);
});
// A Home Screen app with no Safari cookies or caches must offer login, not offline-only cases.
await page.goto(origin+'/case-manager'); await page.waitForFunction(()=>document.title==='登录法律操作系统');
assert.equal(await page.locator('#tab-bar').count(),0);await page.locator('button').click();
await page.waitForURL(origin+'/');
await page.goto(origin+'/');await page.waitForFunction(async()=>{const names=await caches.keys(); for(const name of names){if(name.startsWith('legal-kb-app-shell-v')){const c=await caches.open(name);if(await c.match('/__stella_home_ready__/'+name.split('-v').pop()))return true;}} return false;},{},{timeout:30000});
await page.waitForFunction(()=>!!navigator.serviceWorker.controller); // Expired cookie inside a case iframe must move the entire app to login.
await context.clearCookies();await page.evaluate(()=>openCaseManagerTab());
await page.waitForURL('**/login?next=*');assert.equal(await page.title(),'登录法律操作系统');
await page.locator('button').click();await page.waitForURL(origin+'/');
await page.waitForFunction(()=>!!navigator.serviceWorker.controller);
await page.waitForFunction(()=>typeof initKnowledgeDirectory==='function' && appStartupComplete);
if(process.env.STELLA_QA_EFFICIENCY==='1'){await require('./mobile_efficiency_menu_ui')(page,useWebKit?'webkit':'chrome');assert.deepEqual(errors,[]);await browser.close();server.close();return;}

for(const width of (process.env.STELLA_QA_WIDTH?[Number(process.env.STELLA_QA_WIDTH)]:[320,375,390,430,768])){
 await page.setViewportSize({width,height:phoneHeight});
 for(const dark of [false,true]){
  await page.evaluate(dark=>document.body.classList.toggle('dark-mode',dark),dark);
  for(const section of ['workspace','appearance','security','system','backup']){
   await page.evaluate(section=>openSettingsModal(section),section);
   const overflow=await page.locator('.settings-modal').evaluate(n=>({width:n.clientWidth,scroll:n.scrollWidth,bodyWidth:n.querySelector('.modal-body').clientWidth,bodyScroll:n.querySelector('.modal-body').scrollWidth,bodyOffset:n.querySelector('.modal-body').offsetWidth}));

   assert(overflow.width>0 && overflow.scroll<=overflow.width+2 && overflow.bodyScroll<=overflow.bodyOffset+2,JSON.stringify({width,dark,section,overflow}));
  }
  await page.evaluate(()=>closeSettingsModal());
  for(const [open,selector,close] of [['openOfflineCacheManager','.offline-cache-modal','closeOfflineCacheManager'],['openPagesOverview','#open-pages-overview','closeOpenPagesOverview'],['openAskPanel','#ask-panel','closeAskPanel']]){
   await page.evaluate(name=>window[name](),open);await page.locator(selector).waitFor({state:'visible'});await page.waitForTimeout(300);
   const bounds=await page.locator(selector).evaluate(n=>{const r=n.getBoundingClientRect();return {left:r.left,right:r.right,width:n.clientWidth,scroll:n.scrollWidth};});

   assert(bounds.left>=-2&&bounds.right<=width+2&&bounds.scroll<=bounds.width+2,JSON.stringify({width,dark,selector,bounds}));
   if(process.env.STELLA_MOBILE_QA_OUTPUT){fs.mkdirSync(process.env.STELLA_MOBILE_QA_OUTPUT,{recursive:true});await page.screenshot({path:path.join(process.env.STELLA_MOBILE_QA_OUTPUT,`${useWebKit?'webkit':'chrome'}-${open}-${width}-${dark?'dark':'light'}.png`)});}
   await page.evaluate(name=>window[name](),close);
  }

 }
}
await page.setViewportSize({width:390,height:phoneHeight});
await page.evaluate(()=>openCaseManagerTab());await page.waitForFunction(()=>document.querySelector('.tab-page.active iframe[src*="case-manager"]'));
// Exercise the actual mobile case screens at narrow and wide phone widths.
const frame=await (await page.locator('.tab-page.active iframe[src*="case-manager"]').elementHandle()).contentFrame();
await frame.waitForFunction(()=>window.__apexCaseManagerInteractive===true);
assert(await frame.evaluate(()=>syncOfflineSnapshot(false)));
for(const width of (process.env.STELLA_QA_WIDTH?[Number(process.env.STELLA_QA_WIDTH)]:[320,375,390,430,768])){
 await page.setViewportSize({width,height:phoneHeight});
 for(const dark of [false,true]){
 await frame.evaluate(dark=>{document.documentElement.classList.toggle('dark-mode',dark);document.body.classList.toggle('dark-mode',dark);},dark);
 for(const tab of ['cases','todos','hearings','preservations','appeals','judicialMessages','caseCalendar','import']){
  await frame.evaluate(tab=>switchTab(tab),tab);await page.waitForTimeout(100);
  const overflow=await frame.evaluate(()=>[...document.querySelectorAll('.topbar,.main,.drawer.show')].map(n=>({class:n.className,width:n.clientWidth,scroll:n.scrollWidth})).filter(n=>n.scroll>n.width+2));
  assert.deepEqual(overflow,[],JSON.stringify({width,tab,overflow}));
  if(['cases','todos','hearings','preservations','appeals'].includes(tab)){await frame.evaluate(tab=>openEditor(tab),tab);await frame.locator('#drawer.show').waitFor({state:'visible'});await page.waitForTimeout(350);
   const clipped=await frame.locator('#drawer').evaluate(n=>[...n.querySelectorAll('button,input,textarea')].filter(e=>{const r=e.getBoundingClientRect();return r.width&&r.height&&(r.left<0||r.right>innerWidth+2)}).map(e=>({text:e.textContent.slice(0,40),class:e.className})));
   assert.deepEqual(clipped,[],JSON.stringify({width,tab,clipped}));
   if(tab==='cases') {
    // Check the new-case actions as well as an existing long-title case.
    await frame.evaluate(()=>openDetail('cases',1));await page.waitForTimeout(350);
    const detail=await frame.locator('#drawer').evaluate(n=>[...n.querySelectorAll('button')].filter(e=>{const r=e.getBoundingClientRect();return r.width&&(r.left<0||r.right>innerWidth+2)}).map(e=>e.textContent));
    assert.deepEqual(detail,[],JSON.stringify({width,detail}));
    assert(await frame.locator('#drawerTitle').evaluate(n=>n.getBoundingClientRect().height<60),'long title must leave room for content');
    await frame.evaluate(()=>toast('离线缓存已更新'));
    assert(await frame.locator('#toast').evaluate(n=>n.getBoundingClientRect().bottom<innerHeight-122),'toast must clear floating navigation');
    if(process.env.STELLA_MOBILE_QA_OUTPUT){await frame.locator('#drawer').screenshot({path:path.join(process.env.STELLA_MOBILE_QA_OUTPUT,`${useWebKit?'webkit':'chrome'}-case-${width}-${dark?'dark':'light'}.png`)});}
   }

   await frame.evaluate(()=>closeEditor());
  }
 }
}
}
await page.setViewportSize({width:390,height:phoneHeight});
await frame.evaluate(()=>switchTab('cases'));

await page.evaluate(()=>writeArticleOfflineSnapshot({articles:[{id:77,title:'离线文章测试',content:'<p>离线正文测试</p>'}],generated_at:new Date().toISOString()}));
await frame.evaluate(()=>enqueueCaseOp({action:'upsert',id:-100,payload:{title:'离线待同步测试'}}));
if(useWebKit)serverUnavailable=true;else await context.setOffline(true);await page.goto(origin+'/case-manager');assert.equal(new URL(page.url()).pathname,'/');await page.waitForFunction(()=>document.querySelector('.tab-page.active iframe[src*="case-manager"]'),{},{timeout:20000});


const offlineFrame=await (await page.locator('.tab-page.active iframe[src*="case-manager"]').elementHandle()).contentFrame();
await offlineFrame.waitForFunction(()=>window.__apexCaseManagerInteractive===true);
assert((await offlineFrame.evaluate(()=>offlineCaseById(1).title)).startsWith('测试案件'));
const bar=page.locator('#tab-bar');assert(await bar.isVisible());const rect=await bar.boundingBox();assert(rect.y>phoneHeight-144&&rect.y+rect.height<=phoneHeight,'existing floating bar must stay at bottom');
await page.locator('#tab-bar-home-btn').click();await page.waitForFunction(()=>document.querySelector('#tab-page-main').classList.contains('active'));assert(await bar.isVisible());
await page.reload();await page.waitForTimeout(2000);assert(await bar.isVisible());await page.locator('#tab-bar-home-btn').click();assert(await page.locator('#tab-page-main').isVisible());
await page.waitForFunction(()=>appStartupComplete && articleOfflineReady);
assert.equal(await page.evaluate(()=>offlineArticleDetail('/api/articles/77').title),'离线文章测试');
assert(await page.evaluate(()=>JSON.parse(localStorage.getItem('case-manager-pending-case-ops')).some(op=>op.id===-100)));
assert.deepEqual(errors,[],'unexpected browser errors: '+JSON.stringify(errors));
await page.screenshot({path:path.join(require('os').tmpdir(),'stella-safari-standalone-mobile.png')});console.log(JSON.stringify({engine:useWebKit?'WebKit':'Chrome',passed:true,bar:rect,pageErrors:errors,expectedTransportEvents:transportErrors.length}));await browser.close();server.close();
})().catch(e=>{console.error(e);server.close();process.exit(1)});
