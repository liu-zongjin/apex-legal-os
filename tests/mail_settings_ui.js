/* Anonymous, isolated browser checks; no real mailbox or credentials. */
const { chromium } = require('playwright');
const fs = require('fs'), path = require('path'), http = require('http'), assert = require('node:assert/strict'), acorn = require('acorn');
const root = path.resolve(__dirname, '..'), output = path.join(root, '.tmp/mail-settings-ui');
fs.mkdirSync(output, {recursive:true});
const app = fs.readFileSync(path.join(root,'frontend/app.js'),'utf8');
const tree = acorn.parse(app,{ecmaVersion:'latest'});
const functions = ['openMcpManagerTab','openMailConfigFromSettings','openMcpManagerFromSettings'].map(name=>{const node=tree.body.find(n=>n.type==='FunctionDeclaration'&&n.id.name===name);assert(node);return app.slice(node.start,node.end);}).join('\n');
const index=fs.readFileSync(path.join(root,'frontend/index.html'),'utf8');
const entries=[...index.matchAll(/<button class="settings-list-item"[^>]+onclick="openMailConfigFromSettings\('[^']+'\)"[\s\S]*?<\/button>/g)].map(m=>m[0]).join('');
assert.equal((entries.match(/openMailConfigFromSettings/g)||[]).length,3);
const names={qq_exmail:'腾讯企业邮箱',netease_exmail:'网易企业邮箱',qq_mail:'QQ邮箱'};
const configs=Object.keys(names).map(id=>({id,name:names[id],caption:'邮箱连接',description:'匿名测试',protocol:'imap_mail',url:'',url_label:'邮箱地址',key_label:'客户端授权码',needs_key:true,tools:['查收邮件'],color:'#64748b',managed_url:false,managed_key:false,has_key:false,optional_key_name:id==='qq_exmail'?'':'WEB_COOKIE',portal_url:'https://example.test',configured:false,usable:false}));
const saves=[],tests=[];
function json(res,data,status=200){res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify(data));}
const server=http.createServer(async(req,res)=>{
 const url=new URL(req.url,'http://fixture');
 if(url.pathname==='/settings'){
  res.setHeader('Content-Type','text/html; charset=utf-8');res.end(`<meta charset="utf-8"><style>iframe{width:100%;height:850px}button{padding:12px}</style>${entries}<button id="generic" onclick="openMcpManagerFromSettings()">全部 MCP 服务</button><script>const TAB_TYPES={MCP_MANAGER:'mcp_manager'};let settingsReturnTabType;function closeSettingsModal(){}function openTab(){if(!document.querySelector('iframe')){const f=document.createElement('iframe');f.className='mcp-manager-frame';f.src='/mcp-manager';document.body.append(f);}}${functions}</script>`);return;
 }
 if(url.pathname==='/api/mcp-servers'){json(res,{servers:configs,total_count:3,configured_count:configs.filter(x=>x.configured).length,pending_auth_count:3});return;}
 const match=url.pathname.match(/^\/api\/mcp-servers\/(qq_exmail|netease_exmail|qq_mail)(\/test)?$/);
 if(match){let raw='';for await(const chunk of req)raw+=chunk;const item=configs.find(x=>x.id===match[1]);if(match[2]){tests.push(item.id);json(res,{latency_ms:12});return;}const payload=JSON.parse(raw);saves.push({id:item.id,payload});item.url=payload.url;item.configured=item.usable=true;if(payload.api_key){item.has_key=true;item.key_masked='••••TEST';}json(res,{ok:true});return;}
 const file=url.pathname==='/mcp-manager'?'frontend/mcp-manager.html':url.pathname.startsWith('/static/')?'frontend/'+url.pathname.slice(8):'';
 if(file&&fs.existsSync(path.join(root,file))){res.setHeader('Content-Type',file.endsWith('.css')?'text/css':file.endsWith('.js')?'application/javascript':'text/html; charset=utf-8');res.end(fs.readFileSync(path.join(root,file)));return;}
 res.writeHead(404);res.end();
});
(async()=>{await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const origin='http://127.0.0.1:'+server.address().port;
 const browser=await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
 try{const page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(origin+'/settings');
 for(const account of Object.keys(names)){
  await page.locator(`[onclick="openMailConfigFromSettings('${account}')"]`).click();
  const frame=page.frameLocator('iframe');await frame.locator('#drawerBackdrop.open').waitFor();
  assert((await page.locator('iframe').getAttribute('src')).endsWith('?mail='+account));
  assert.equal(await frame.locator('[data-edit]').count(),1);
  assert.equal(await frame.locator('[data-edit]').getAttribute('data-edit'),account);
  assert.match(await frame.locator('#mailDrawerGuide').innerText(),/三步完成邮箱配置/);
  assert.equal(await frame.locator('.overview').isVisible(),false);
  assert.equal(await frame.locator('#apiUrl').inputValue(),'');
  await frame.locator('#apiUrl').fill(account+'@example.test');await frame.locator('#apiKey').fill('FAKE-ONLY-'+account);
  await frame.locator('#saveBtn').click();await frame.locator('#drawerBackdrop.open').waitFor({state:'hidden'});
  assert.equal(saves.at(-1).id,account);assert.equal(saves.at(-1).payload.api_key,'FAKE-ONLY-'+account);
  await frame.locator('[data-test]').click();await frame.locator('#toast').filter({hasText:'连接正常'}).waitFor();assert.equal(tests.at(-1),account);
  await frame.locator('[data-edit]').click();await frame.locator('#drawerBackdrop.open').waitFor();assert.equal(await frame.locator('#apiKey').inputValue(),'');assert.match(await frame.locator('#maskedKey').innerText(),/TEST/);
  await frame.locator('#apiUrl').fill(account+'@example.test');await frame.locator('#saveBtn').click();await frame.locator('#drawerBackdrop.open').waitFor({state:'hidden'});assert.equal(saves.at(-1).payload.api_key,undefined);
 }
 await page.locator('#generic').click();const frame=page.frameLocator('iframe');await frame.locator('[data-edit="qq_exmail"]').waitFor();assert.equal(await frame.locator('[data-edit]').count(),3);assert.equal(await page.locator('iframe').getAttribute('src'),'/mcp-manager');
 await frame.locator('[data-edit="qq_exmail"]').click();await frame.locator('#drawerBackdrop.open').waitFor();assert.equal(await frame.locator('#mailDrawerGuide').isVisible(),true);
 await frame.locator('#saveBtn').focus();await page.keyboard.press('Tab');assert.equal(await frame.locator('#closeDrawer').evaluate(el=>el===document.activeElement),true);await page.keyboard.press('Escape');await frame.locator('#drawerBackdrop.open').waitFor({state:'hidden'});
 for(const width of [1440,1024,390])for(const dark of [false,true]){
  await page.setViewportSize({width,height:900});await page.goto(origin+'/mcp-manager?mail=qq_mail');await page.locator('#drawerBackdrop.open').waitFor();await page.evaluate(d=>document.body.classList.toggle('dark',d),dark);
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.waitForTimeout(350);await page.screenshot({path:path.join(output,`${width}-${dark?'dark':'light'}.png`)});
 }
 await page.goto(origin+'/mcp-manager?mail=unknown');await page.locator('[data-edit="qq_mail"]').waitFor();assert.equal(await page.locator('[data-edit]').count(),3);
 assert.deepEqual(errors,[]);console.log('MAIL_SETTINGS_UI_OK: three settings entries, isolated provider views, shared save/masking/test, generic return, keyboard, light/dark and responsive layouts');
 }finally{await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
