/* Anonymous browser review: actual dialog implementation and production styles. */
const fs=require('fs'),path=require('path'),assert=require('assert');
const {chromium,webkit}=require('playwright');
const engine=process.env.CASE_ENTRY_BROWSER==='webkit'?webkit:chromium;
const root=path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(root,'frontend/case-manager.js'),'utf8');
const dialogSource=source.slice(source.indexOf('let caseEntryDialog = null;'),source.indexOf('async function deleteCaseResearchEntry('));
const css=['apex-design-tokens.css','case-manager.css','apex-case-record-editor.css','apex-record-typography.css'].map(name=>fs.readFileSync(path.join(root,'frontend',name),'utf8')).join('\n');
const output=process.env.CASE_ENTRY_REVIEW_OUTPUT;
if(output)fs.mkdirSync(output,{recursive:true});
(async()=>{
 const browser=await engine.launch({headless:true,...(engine===chromium && process.env.CASE_ENTRY_CHROME ? {executablePath:process.env.CASE_ENTRY_CHROME}: {})});
 const page=await browser.newPage();
 const errors=[];page.on('pageerror',error=>errors.push(error.message));
 await page.setContent(`<style>${css}</style><button id="launcher">案件记录</button>`);
 await page.addScriptTag({content:`
 const state={caseResearch:{section:'memo',projectId:10,caseId:42,data:{memo_entries:[],ledgers:[]}}};
 const fixture={id:7,title:'庭前沟通与材料核对',content:'已核对合同、往来函件与付款凭证。\\n\\n下一步安排\\n补充签收凭证，整理开庭所需材料。',happened_at:'2026-10-16',created_at:'2026-10-16',updated_at:'version-one'};
 state.caseResearch.data.memo_entries=[fixture];state.caseResearch.data.ledgers=[fixture];
 let stored=[{id:'a'.repeat(32),kind:'upload',name:'材料核对清单.pdf',exists:true,size:1024},{id:'b'.repeat(32),kind:'folder',name:'案件沟通纪要与补充材料清单'.repeat(12)+'.docx',path:'/匿名案件/'.repeat(35)+'沟通纪要与补充材料清单.docx',exists:true}];
 let failSave=false,savedPayload=null,notices=[];
 function $(id){return document.getElementById(id)}
 function esc(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
 function dateOnly(value){return String(value||'').slice(0,10)}
 function caseResearchLabel(section){return section==='memo'?'案件备忘录':'案件台账'}
 function caseResearchItems(){return state.caseResearch.section==='memo'?state.caseResearch.data.memo_entries:state.caseResearch.data.ledgers}
 function requireOnlineAction(){return true}function toast(value){notices.push(value)}
 async function reloadCaseResearchWorkspace(){}
 async function api(url,options={}){
   if(url.includes('/with-resources')){
     if(failSave)throw new Error('模拟网络中断');
     savedPayload=JSON.parse(options.body.get('payload'));
     stored=stored.filter(item=>savedPayload.keep_resource_ids.includes(item.id));
     const files=options.body.getAll('files');
     stored.push(...files.map((file,index)=>({id:('c'+index).padEnd(32,'0'),name:file.name,kind:'upload',exists:true})));
     return {...fixture,...savedPayload,id:7};
   }
   if(url.includes('/resources/select'))return {path:'/匿名案件/新材料.txt',name:'新材料.txt',kind:'file'};
   return {items:stored.map(item=>({...item})),local_available:true};
 }
 ${dialogSource}`});
 await page.addScriptTag({content: 'window.ApexRecordEditor={render:value=>esc(value).replace(/\\n/g, "<br>")};'});
 await page.addScriptTag({content:fs.readFileSync(path.join(root,'frontend/apex-case-record-editor.js'),'utf8')});
 await page.addScriptTag({content:fs.readFileSync(path.join(root,'frontend/apex-date-picker.js'),'utf8')});
 const geometry=()=>page.evaluate(()=>Object.fromEntries(['.case-timeline-modal','.case-entry-title input','.case-entry-date','.case-entry-content textarea:not([hidden]),.case-entry-content .case-record-preview:not([hidden])','.case-entry-resources'].map(selector=>{const r=document.querySelector(selector).getBoundingClientRect();return[selector,[r.x,r.y,r.width,r.height]]})));
 for(const [width,height] of [[1440,900],[1024,768]]){
  await page.setViewportSize({width,height});
  for(const theme of ['light','dark']){
   await page.evaluate(theme=>document.body.classList.toggle('dark-mode',theme==='dark'),theme);
   let reference;
   for(const section of ['memo','ledger']){
    await page.evaluate(async section=>{state.caseResearch.section=section;await openCaseResearchEntryView(7)},section);
    await page.waitForTimeout(30);
    const view=await geometry();
    const overflow=await page.evaluate(()=>{
      const body=document.querySelector('.case-timeline-modal-body'), frame=body.getBoundingClientRect();
      return {width:body.clientWidth,scrollWidth:body.scrollWidth,
        clipped:[...body.querySelectorAll('.case-entry-title,.case-entry-content,.case-entry-resources,.case-entry-resource-row')].filter(el=>{const r=el.getBoundingClientRect();return r.left<frame.left-1||r.right>frame.right+1}).map(el=>el.className)};
    });
    if(output)await page.screenshot({path:path.join(output,`${section}-view-${width}-${theme}.png`)});
    assert(overflow.scrollWidth<=overflow.width+1,JSON.stringify(overflow));
    assert.deepEqual(overflow.clipped,[],'Content must stay inside the dialog');
    assert.equal(await page.locator('#caseResearchEntryContent').getAttribute('readonly'),'');
    if(reference)assert.deepEqual(view,reference);else reference=view;
    await page.getByRole('button',{name:'编辑',exact:true}).click();
    await page.waitForFunction(()=>!caseEntryDialog.loading);
    await page.waitForTimeout(30);
    const edit=await geometry();assert.deepEqual(edit,view,'Reading and editing geometry must match');
    assert.equal(await page.locator('.case-timeline-modal-body').evaluate(el=>el.scrollWidth<=el.clientWidth+1),true);
    assert.equal(await page.locator('#caseResearchEntryContent').evaluate(el=>el.scrollWidth<=el.clientWidth+1),true);
    assert.equal(await page.locator('#caseResearchEntryContent').getAttribute('readonly'),null);
    if(output)await page.screenshot({path:path.join(output,`${section}-edit-${width}-${theme}.png`)});
   }
  }
 }
 // Cancel must reload persisted bindings after draft removal.
 await page.evaluate(()=>openCaseResearchEntryEditor(7));
 await page.getByRole('button',{name:/解除绑定：/}).click();
 assert.equal(await page.locator('.case-entry-resource-row').count(),1);
 await page.getByRole('button',{name:'取消',exact:true}).click();
 await page.waitForFunction(()=>!caseEntryDialog.loading);
 assert.equal(await page.locator('.case-entry-resource-row').count(),2);
 // Upload is held in the draft; failed save retains text, file and retry ability.
 await page.getByRole('button',{name:'编辑',exact:true}).click();
 await page.waitForFunction(()=>!caseEntryDialog.loading);
 await page.locator('.case-record-preview').fill('这是修改后的记录');
 await page.locator('#caseEntryFileInput').setInputFiles({name:'新增附件.txt',mimeType:'text/plain',buffer:Buffer.from('anonymous')});
 assert.equal(await page.locator('.case-entry-resource-row').count(),3);
 await page.evaluate(()=>{failSave=true});
 await page.getByRole('button',{name:'保存',exact:true}).click();
 assert.equal(await page.locator('#caseResearchEntryContent').inputValue(),'这是修改后的记录');
 assert.equal(await page.locator('.case-entry-resource-row').count(),3);
 assert.equal(await page.locator('#caseEntrySave').isEnabled(),true);
 await page.evaluate(()=>{failSave=false});
 await page.getByRole('button',{name:'保存',exact:true}).click();
 await page.waitForFunction(()=>caseEntryDialog && !caseEntryDialog.editing && !caseEntryDialog.loading);
 assert.equal(await page.locator('.case-entry-resource-row').count(),3);
 assert.equal(await page.evaluate(()=>savedPayload.content),'这是修改后的记录');
 await page.keyboard.press('Escape');
 assert.equal(await page.locator('#caseResearchTimelineModal').evaluate(el=>el.classList.contains('show')),false);
 // Small-screen layout and reduced transparency remain usable.
 await page.setViewportSize({width:390,height:844});
 await page.emulateMedia({reducedMotion:'reduce'});
 await page.evaluate(()=>openCaseResearchEntryEditor(7));
 await page.waitForFunction(()=>!caseEntryDialog.loading);
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 assert.equal(await page.locator('.case-timeline-modal-body').evaluate(el=>el.scrollWidth<=el.clientWidth+1),true);
 if(output)await page.screenshot({path:path.join(output,'mobile-edit.png')});
 assert.deepEqual(errors,[]);
 await browser.close();console.log('Case entry browser checks passed: consistent geometry in 16 views, long attachment containment, cancel, upload, save failure, retry, keyboard and mobile.');
})().catch(error=>{console.error(error);process.exit(1)});
