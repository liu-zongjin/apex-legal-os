const fs=require('fs'),assert=require('assert'),acorn=require('acorn'),{chromium}=require('playwright');
const source=fs.readFileSync('frontend/app.js','utf8');
const tree=acorn.parse(source,{ecmaVersion:'latest'});
const declarations=['loadCaseSearchSourceDefault','applyCaseSearchSourceDefault','setCaseSearchSourceDefault'].map(name=>{
 const node=tree.body.find(n=>n.type==='FunctionDeclaration'&&n.id.name===name);assert(node,name);return source.slice(node.start,node.end);
});
(async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.STELLA_UI_BROWSER||'chrome'});
 try{
  for(const width of [1440,1024,390]){
   const page=await browser.newPage({viewport:{width,height:900}});
   await page.setContent('<div id="ask-mcp-source-menu" class="ask-mcp-source-menu open"></div>');
   await page.evaluate(html=>{
    const doc=new DOMParser().parseFromString(html,'text/html');
    document.querySelector('#ask-mcp-source-menu').append(doc.querySelector('.ask-mcp-menu-footer'));
   },fs.readFileSync('frontend/index.html','utf8'));
   for(const name of ['apex-design-tokens.css','style.css'])await page.addStyleTag({content:fs.readFileSync('frontend/'+name,'utf8').replace(/@import[^;]+;/g,'')});
   await page.addStyleTag({content:'#ask-mcp-source-menu{display:block;position:static;width:min(920px,calc(100vw - 32px));max-height:none;transform:none}'});
   await page.addScriptTag({content:`const CASE_SEARCH_SOURCE_DEFAULTS={mcp:'mcp',public_web:'public_web',both:'both'};var selections=[],writes=[],toasts=[];function setAskSourceMode(mode){selections.push(mode)}function showToast(message,type){toasts.push(type)};async function fetch(url,options){if(options)writes.push(JSON.parse(options.body).value);return {ok:true,json:async()=>({value:options?JSON.parse(options.body).value:'public_web'})}};`+declarations.join('\n')});
   const modes=['hybrid','direct_ai','direct_ai_web','local_only','public_web_cases'];
   for(const mode of modes){await page.locator(`[data-source-mode="${mode}"]`).click();}
   assert.deepEqual(await page.evaluate(()=>selections),modes);
   await page.evaluate(()=>loadCaseSearchSourceDefault());
   assert.equal(await page.locator('[data-case-default="public_web"]').getAttribute('aria-checked'),'true');
   await page.locator('[data-case-default="both"]').focus();await page.keyboard.press('Enter');
   assert.deepEqual(await page.evaluate(()=>writes),['both']);
   assert.equal(await page.locator('[data-case-default][aria-checked="true"]').count(),1);
   for(const dark of [false,true]){
    await page.evaluate(d=>document.body.classList.toggle('dark-mode',d),dark);
    await page.emulateMedia({reducedMotion:'reduce'});
    const box=await page.locator('.ask-mcp-menu-footer').boundingBox();assert(box.x>=0&&box.x+box.width<=width+1);
    assert((await page.locator('[data-source-mode="public_web_cases"]').innerText()).includes('不调用案例 MCP'));
   }
   if(width===1024)await page.screenshot({path:'/tmp/stella-public-case-scope-review.png'});
   await page.close();
  }
  console.log('Public case scope, preserved direct modes, preference save, keyboard and responsive themes passed.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1)});
