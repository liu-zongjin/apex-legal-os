/* Production styles/markup with anonymous long-content fixtures. No live APIs. */
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict'),acorn=require('acorn');
const {chromium,webkit}=require(process.env.STELLA_PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'..'),read=name=>fs.readFileSync(path.join(root,name),'utf8');
function markup(name){return read('frontend/'+name).replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'').replace(/<link\b[^>]*href=["']([^"']+)["'][^>]*>/gi,(_,url)=>{
 const name=path.basename(url.split('?')[0]),file=path.join(root,'frontend',name==='style.min.css'?'style.css':name);
 return name.endsWith('.css')&&fs.existsSync(file)?'<style>'+fs.readFileSync(file,'utf8')+'</style>':'';
});}
const long='Example_case_20261117_'.repeat(7),title='示例系列案件的长名称及其申请人与被申请人信息'.repeat(5);
const out=process.env.STELLA_DISPLAY_AUDIT_OUTPUT||'.tmp/frontend-display-audit-20261117/components';
const onlyChrome=process.env.STELLA_DISPLAY_CHROME_ONLY==='1';
(async()=>{fs.mkdirSync(out,{recursive:true});const failures=[],measurements=[];
 for(const engine of onlyChrome?[chromium]:[chromium,webkit]){
  const browser=await engine.launch(engine===chromium?{headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'}:{headless:true});
  try{const page=await browser.newPage();await page.route('**/*',r=>r.abort());
   async function load(file,width,dark){await page.goto('about:blank');await page.setViewportSize({width,height:900});await page.setContent(markup(file));await page.addStyleTag({content:'*,*::before,*::after{animation:none!important;transition:none!important}'});await page.evaluate(d=>{document.documentElement.classList.toggle('dark-mode',d);document.body.classList.toggle('dark-mode',d);},dark);}
   async function check(label,fn){try{await fn();}catch(e){failures.push({engine:engine.name(),width,dark,label,error:e.message});}}
   async function fits(selector,container){const result=await page.locator(selector).evaluate((el,parentSelector)=>{const parent=document.querySelector(parentSelector),r=el.getBoundingClientRect(),p=parent.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,parentLeft:p.left,parentRight:p.right,client:el.clientWidth,scroll:el.scrollWidth};},container);assert(result.left>=result.parentLeft-1&&result.right<=result.parentRight+1,JSON.stringify(result));return result;}
   let width,dark;
   for(width of (process.env.STELLA_DISPLAY_DESKTOP_ONLY==='1'?[960,1000,1001,1024,1280,1440,1920,2560]:[1440,1024,768,390,320]))for(dark of [false,true]){
    await check('case-file toolbar labels and long title',async()=>{
     await load('case-files.html',width,dark);await page.evaluate(({long,title})=>{document.querySelector('#caseTitle').textContent=title+' '+long;document.querySelector('#folderPath').textContent='/示例目录/'+long;},{long,title});
     await fits('.titlebar','body');await fits('#caseTitle','.titlebar');await fits('.connection','.titlebar');
     assert(await page.locator('#caseTitle').evaluate(el=>el.getBoundingClientRect().height<=parseFloat(getComputedStyle(el).lineHeight)*2+1),'title must leave space for files');
     const buttons=await page.locator('#toolbar .btn').evaluateAll(nodes=>nodes.map(n=>({label:n.textContent.trim(),width:n.clientWidth,scroll:n.scrollWidth})));assert(buttons.every(b=>b.scroll<=b.width+2),JSON.stringify(buttons));
     const last=page.locator('#trashBtn');await last.scrollIntoViewIfNeeded();await fits('#trashBtn','#toolbar');
     if(width===390&&!dark)await page.screenshot({path:path.join(out,engine.name()+'-case-files.png')});
    });
    await check('invoice actions wrap without clipping',async()=>{
     await load('invoice-center.html',width,dark);await page.evaluate(text=>document.querySelector('#status-hint').textContent=text,'正在扫描 '+long);
     const actions=await page.locator('.topbar > .btn').evaluateAll(nodes=>nodes.map(n=>({label:n.textContent.trim(),left:n.getBoundingClientRect().left,right:n.getBoundingClientRect().right,width:n.clientWidth,scroll:n.scrollWidth})));assert(actions.every(b=>b.left>=0&&b.right<=width+1&&b.scroll<=b.width+2),JSON.stringify(actions));
     assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
     if(width===390&&!dark)await page.screenshot({path:path.join(out,engine.name()+'-invoice.png')});
    });
    await check('scanner configuration and selected case',async()=>{
     await load('scanner-inbox.html',width,dark);for(const id of ['#username','#password'])await fits(id,'.config');
     assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
     await page.evaluate(({title,long})=>{document.querySelector('.workspace').classList.remove('hidden');const el=document.querySelector('#selected-case');el.classList.remove('hidden');el.innerHTML='<div><strong>'+title+' '+long+'</strong><span>/示例目录/'+long+'</span></div><button type="button">更换</button>';},{title,long});
     await fits('#selected-case','#selected-case');await fits('#selected-case button','#selected-case');await fits('#selected-case strong','#selected-case');
     assert(await page.locator('#selected-case').evaluate(el=>el.scrollWidth<=el.clientWidth+1));
     if(width===390&&!dark)await page.screenshot({path:path.join(out,engine.name()+'-scanner.png')});
    });
    await check('reminder card keeps its local-file action readable',async()=>{
     await load('case-manager.html',width,dark);
     const source=read('frontend/case-manager.js'),tree=acorn.parse(source,{ecmaVersion:'latest'}),node=tree.body.find(n=>n.type==='FunctionDeclaration'&&n.id.name==='recordList');
     await page.addScriptTag({content:`function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}function encodeMobileRecord(){return ''}${source.slice(node.start,node.end)}`});
     await page.evaluate(title=>{const drawer=document.querySelector('#drawer');drawer.classList.add('show','detail-mode');drawer.setAttribute('aria-hidden','false');document.querySelector('#drawerBody').innerHTML=recordList('开庭提醒',[{id:1,location:title}],r=>r.location,[]);},title);
     const size=await page.locator('.record-card-head > button').evaluate(el=>({width:el.getBoundingClientRect().width,height:el.getBoundingClientRect().height,font:parseFloat(getComputedStyle(el).fontSize)}));assert(size.width>=size.font*4+15&&size.height<=44,JSON.stringify(size));
     await fits('.record-card-head > button','.record-card');
     if(width===390&&!dark)await page.locator('#drawer').screenshot({path:path.join(out,engine.name()+'-reminder.png')});
    });
    await check('personal-center dialog header retains close action',async()=>{
     await load('personal-center.html',width,dark);await page.evaluate(long=>{document.querySelector('#dialogMask').classList.add('show');document.querySelector('#dialogTitle').textContent='示例资料 '+long;document.querySelector('#dialogSub').textContent='/示例目录/'+long;},long);
     await fits('.pc-dialog-head button','.pc-dialog');assert(await page.locator('.pc-dialog-head').evaluate(el=>el.scrollWidth<=el.clientWidth+1));
     const button=await page.locator('.pc-dialog-head button').evaluate(el=>({width:el.clientWidth,scroll:el.scrollWidth}));assert(button.scroll<=button.width+1,JSON.stringify(button));
    });
    await check('memory long URL stays inside its card',async()=>{
     await load('index.html',width,dark);await page.addStyleTag({content:read('frontend/user-memory.css')});
     await page.evaluate(long=>{window.fetch=async()=>new Response(JSON.stringify({enabled:true,auto_save:false,items:[{id:1,kind:'personal',status:'active',subject:'示例偏好',content:'https://example.test/'+long,source:'manual',updated_at:'2026-11-17 10:00:00'}],counts:{personal:1,case:0,pending:0},total:1,scope:{case_available:false}}),{headers:{'content-type':'application/json'}});window.getAiContextLocation=()=>({});},long);
     await page.addScriptTag({content:read('frontend/user-memory.js')});await page.evaluate(()=>openUserMemory());await page.locator('.user-memory-item').waitFor();
     const expand=page.locator('.memory-expand');if(await expand.count())await expand.click();
     assert(await page.locator('.memory-item-content').evaluate(el=>el.scrollWidth<=el.clientWidth+1));
     await fits('.memory-item-content','.user-memory-item');
     if(width===390&&!dark)await page.locator('#user-memory-panel').screenshot({path:path.join(out,engine.name()+'-memory.png')});
    });
    measurements.push({engine:engine.name(),width,dark});
   }
  }finally{await browser.close();}
 }
 fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({failures,measurements},null,2));assert.deepEqual(failures,[],JSON.stringify(failures,null,2));console.log('Display audit: 6 production surfaces, configured widths, light/dark and both browser engines passed');
})().catch(e=>{console.error(e);process.exit(1)});
