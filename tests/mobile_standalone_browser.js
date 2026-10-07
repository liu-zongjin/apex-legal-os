// Optional real-worker QA with anonymous data and a fresh standalone storage context.
const {chromium,webkit}=require(process.env.STELLA_PLAYWRIGHT_MODULE || 'playwright');
const http=require('http'),fs=require('fs'),path=require('path'),assert=require('assert');
const root=process.cwd(),version='232';
const fixtures={'/api/domains':[], '/api/authors':[], '/api/tag-categories':[], '/api/custom-tags':[], '/api/articles':{articles:[],total:0,page:1,page_size:10},'/api/saved-views':[], '/api/brand':{custom:false,revision:'default',configured:false},'/api/server-status':{status:'current'}, '/api/case-manager/dashboard':{counts:{}}, '/api/case-manager/cases':[], '/api/case-manager/todos':[], '/api/case-manager/hearings':[], '/api/case-manager/preservations':[], '/api/case-manager/appeals':[], '/api/case-manager/offline-snapshot':{cases:[],todos:[],hearings:[],preservations:[],appeals:[],snapshot_version:1,generated_at:new Date().toISOString()}};
const server=http.createServer((req,res)=>{
 const u=new URL(req.url,'http://localhost');
 const signedIn=(req.headers.cookie||'').includes('fixture_session=yes');
 if(req.method==='POST'&&u.pathname==='/login'){res.writeHead(303,{'Set-Cookie':'fixture_session=yes; Path=/; HttpOnly; SameSite=Lax','Location':'/'});return res.end();}
 if(u.pathname==='/'&&!signedIn || u.pathname==='/login'){res.setHeader('Content-Type','text/html');return res.end('<meta charset="utf-8"><title>登录法律操作系统</title><form action="/login" method="post"><input name="username"><input name="password"><button>登录</button></form>');}
 if(u.pathname==='/api/pwa/session-status'){res.setHeader('Content-Type','application/json');return res.end(JSON.stringify({server_reachable:true,authenticated:signedIn,shell_version:version}));}
 if(u.pathname.startsWith('/api/')&&!signedIn&&!['/api/brand','/api/server-status'].includes(u.pathname)){res.writeHead(401,{'Content-Type':'application/json'});return res.end('{"detail":"login required"}');}
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
const context=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'});
await context.addInitScript(()=>Object.defineProperty(navigator,'standalone',{get:()=>true}));
const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
// A Home Screen app with no Safari cookies or caches must offer login, not offline-only cases.
await page.goto(origin+'/case-manager'); await page.waitForFunction(()=>document.title==='登录法律操作系统');
assert.equal(await page.locator('#tab-bar').count(),0);await page.locator('button').click();
await page.waitForURL(origin+'/');
await page.goto(origin+'/');await page.waitForFunction(async()=>{const c=await caches.open('legal-kb-app-shell-v232');return !!await c.match('/__stella_home_ready__/232');},{},{timeout:30000});
await page.waitForFunction(()=>!!navigator.serviceWorker.controller); // Expired cookie inside a case iframe must move the entire app to login.
await context.clearCookies();await page.evaluate(()=>openCaseManagerTab());
await page.waitForURL('**/login?next=*');assert.equal(await page.title(),'登录法律操作系统');
await page.locator('button').click();await page.waitForURL(origin+'/');
await page.waitForFunction(()=>!!navigator.serviceWorker.controller);
await context.setOffline(true);await page.goto(origin+'/case-manager');assert.equal(new URL(page.url()).pathname,'/');await page.waitForFunction(()=>document.querySelector('.tab-page.active iframe[src*="case-manager"]'),{},{timeout:20000});
const bar=page.locator('#tab-bar');assert(await bar.isVisible());const rect=await bar.boundingBox();assert(rect.y>700&&rect.y+rect.height<=844,'existing floating bar must stay at bottom');
await page.locator('#tab-bar-home-btn').click();await page.waitForFunction(()=>document.querySelector('#tab-page-main').classList.contains('active'));assert(await bar.isVisible());
await page.reload();await page.waitForTimeout(2000);assert(await bar.isVisible());await page.locator('#tab-bar-home-btn').click();assert(await page.locator('#tab-page-main').isVisible());
await page.screenshot({path:path.join(require('os').tmpdir(),'stella-safari-standalone-mobile.png')});console.log(JSON.stringify({engine:useWebKit?'WebKit':'Chrome',passed:true,bar:rect,pageErrors:errors}));await browser.close();server.close();
})().catch(e=>{console.error(e);server.close();process.exit(1)});
