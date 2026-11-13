/* Exercise sticky headers against sticky cells using anonymous fixtures. */
const fs=require('fs'), path=require('path'), assert=require('node:assert/strict'), acorn=require('acorn');
const {chromium,webkit}=require(process.env.STELLA_PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'..'), read=f=>fs.readFileSync(path.join(root,f),'utf8');
const source=read('frontend/case-manager.js'), tree=acorn.parse(source,{ecmaVersion:'latest'});
const declarations=tree.body.filter(n=>(n.type==='FunctionDeclaration'&&!['api','esc','toast'].includes(n.id.name))||(n.type==='VariableDeclaration'&&n.declarations.some(d=>d.id.name==='CONTACT_CATEGORIES'))).map(n=>source.slice(n.start,n.end)).join('\n');
(async()=>{
 for(const [name,engine,options] of [['chromium',chromium,{headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'}],['webkit',webkit,{headless:true}]]) {
  const browser=await engine.launch(options);
  try {
   const page=await browser.newPage({viewport:{width:900,height:800}});
   await page.setContent(`<style>${read('frontend/apex-design-tokens.css')}\n${read('frontend/case-manager.css')}</style><main class="drawer show" style="position:static;width:auto;height:auto;transform:none;padding:24px"><section class="detail-section contact-section"><h3 class="case-section-head"><span>联系与备忘</span></h3><div id="mount" style="display:contents"></div></section></main>`);
   await page.addScriptTag({content:`const state={};function toast(){} function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))} ${declarations}`});
   await page.evaluate(()=>{const records=Array.from({length:9},(_,i)=>({name:`匿名联系人${i}`,phone:'020-12345678',organization:'示例单位',department:'示例部门'})); document.querySelector('#mount').innerHTML=contactTableHtml({litigation:records},{},{editable:false,includeMemo:false})});
   for(const dark of [false,true]) for(const horizontal of [0,180]) {
    await page.evaluate(({dark,horizontal})=>{document.body.classList.toggle('dark-mode',dark);const wrap=document.querySelector('.contact-table-wrap');wrap.scrollLeft=horizontal;wrap.scrollTop=95},{dark,horizontal});
    const results=await page.evaluate(()=>{const wrap=document.querySelector('.contact-table-wrap'), name=wrap.querySelector('thead th.contact-col-name'), rect=name.getBoundingClientRect();const hit=document.elementFromPoint(rect.left+Math.min(20,rect.width/2),rect.top+rect.height/2);return {scrollTop:wrap.scrollTop,hitHeader:!!hit?.closest('thead th'),z:getComputedStyle(name).zIndex,bg:getComputedStyle(name).backgroundColor};});
    assert(results.scrollTop>0);assert(results.hitHeader,`${name}: sticky row covers header`);assert(Number(results.z)>=5);assert(!/rgba\([^)]*,\s*(?:0?\.)/.test(results.bg),`${name}: header background must be opaque: ${results.bg}`);
   }
   await page.getByRole('button',{name:'展开全部'}).click(); assert.equal(await page.locator('.contact-table-collapsed').count(),0);
   await page.getByRole('button',{name:'收起列表'}).click(); assert.equal(await page.locator('.contact-table-collapsed').count(),1);
   console.log(`${name}: collapsed scrolling, horizontal scrolling, themes and expansion passed`);
  } finally {await browser.close()}
 }
})().catch(e=>{console.error(e);process.exitCode=1});
