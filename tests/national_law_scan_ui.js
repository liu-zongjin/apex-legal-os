/* Anonymous fixtures: exercise the real scan renderer without touching local data. */
const fs=require('fs'), assert=require('assert/strict'), acorn=require('acorn');
const {chromium}=require(process.env.STELLA_PLAYWRIGHT_MODULE||'playwright');
const source=fs.readFileSync('frontend/app.js','utf8');
const tree=acorn.parse(source,{ecmaVersion:'latest'});
function fn(name){const n=tree.body.find(x=>x.type==='FunctionDeclaration'&&x.id.name===name);assert(n,name);return source.slice(n.start,n.end)}
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try{
  for(const [width,dark] of [[1440,false],[1024,false],[1440,true],[1024,true]]){
   const page=await browser.newPage({viewport:{width,height:900},reducedMotion:'no-preference'});const errors=[];
   page.on('pageerror',e=>errors.push(e.message));
   await page.setContent('<main style="width:min(100%,1020px);margin:auto"><div id="national-law-scan"><div id="national-law-scan-glow" class="national-law-scan-glow" hidden></div><div id="national-law-scan-summary"></div><div id="national-law-scan-items" class="national-law-scan-items"></div><div id="national-law-apply-bar"></div></div></main>');
   for(const file of ['frontend/apex-design-tokens.css','frontend/style.css'])await page.addStyleTag({content:fs.readFileSync(file,'utf8')});
   await page.evaluate(dark=>{if(dark)document.body.classList.add('dark-mode');window.$=id=>document.getElementById(id);window.escapeHtml=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));window.nationalLawMeta=()=>'';},dark);
   await page.addScriptTag({content:[fn('startSummaryGenerationGlow'),'let nationalLawScanGlow = null;',fn('nationalLawItemLabel'),fn('syncNationalLawScanGlow'),fn('renderNationalLawScan'),fn('updateNationalLawCandidatePreview')].join('\n')});
   await page.evaluate(()=>renderNationalLawScan({scan:{status:'running',total:2,processed:0},items:[]}));
   assert.equal(await page.locator('#national-law-scan-glow canvas').count(),1);
   assert.equal(await page.getByRole('progressbar').getAttribute('aria-valuenow'),'0');
   assert.equal(await page.getByRole('button',{name:'停止检测'}).count(),1);
   assert(!((await page.locator('#national-law-scan-items').innerText()).includes('尚无')));
   if(width===1024&&!dark){await page.waitForTimeout(650);await page.screenshot({path:'/tmp/stella-national-law-running.png'});}
   await page.evaluate(()=>renderNationalLawScan({scan:{status:'running',total:2,processed:1},items:[]}));
   assert.equal(await page.locator('#national-law-scan-glow canvas').count(),1);
   assert.equal(await page.getByRole('progressbar').getAttribute('aria-valuenow'),'50');
   await page.evaluate(()=>renderNationalLawScan({scan:{status:'completed',total:1,processed:1,failed_count:1},items:[{id:2,article_id:3,status:'unmatched',local_title:'示例法院工作指引',detail:{}}]}));
   await page.waitForTimeout(750);
   assert.equal(await page.locator('#national-law-scan-glow').isVisible(),false);
   assert.equal(await page.getByRole('button',{name:'检索候选'}).count(),1);
   assert.equal(await page.getByRole('button',{name:'查找公开来源'}).count(),1);
   assert.match(await page.locator('#national-law-scan-items').innerText(),/不代表文件失效/);
   await page.evaluate(()=>renderNationalLawScan({scan:{status:'completed',total:1,processed:1},items:[{id:2,article_id:3,status:'pending_match',local_title:'示例地方条例',candidates:[{bbbs:'example',title:'示例地方条例（修订）',issuer:'示例机关',status_label:'有效',published_at:'2020-01-01'}],detail:{}}]}));
   await page.selectOption('#national-law-candidate-2','example');
   assert.match(await page.locator('#national-law-preview-2').innerText(),/示例机关/);
   assert.match(await page.locator('#national-law-preview-2 a').getAttribute('href'),/^https:\/\/flk\.npc\.gov\.cn\/detail\?id=example/);
   assert.equal(await page.locator('#national-law-confirm-2').isChecked(),false);
   assert.deepEqual(errors,[]);
   if(width===1024&&!dark)await page.screenshot({path:'/tmp/stella-unmatched-ui.png'});
   await page.close();
  }
  console.log('national law scan UI: 4 layouts passed');
 } finally {await browser.close()}
})().catch(err=>{console.error(err);process.exit(1)});
