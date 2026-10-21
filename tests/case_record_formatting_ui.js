/* Anonymous browser checks using the production article editor and record adapter. */
const fs=require('fs'),path=require('path'),assert=require('assert'),acorn=require('acorn');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),read=name=>fs.readFileSync(path.join(root,name),'utf8');
const app=read('frontend/app.js'),tree=acorn.parse(app,{ecmaVersion:'latest'});
const declarations=tree.body.filter(n=>n.type==='FunctionDeclaration'||(n.type==='VariableDeclaration'&&n.start>=app.indexOf('let _bodyEditorInitialHtml')&&n.start<app.indexOf('async function saveBody('))).map(n=>app.slice(n.start,n.end)).join('\n');
const api=app.slice(app.indexOf('window.ApexRecordEditor = {'));
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CASE_ENTRY_CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 const html=read('frontend/index.html').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'').replace(/<link\b[^>]*>/gi,'');
 await page.setContent(html);
 await page.addStyleTag({content:read('frontend/apex-design-tokens.css')+read('frontend/style.css')+read('frontend/apex-case-record-editor.css')+read('frontend/apex-record-typography.css')});
 await page.addScriptTag({content:declarations+`\nconst $=id=>document.getElementById(id);const state={currentArticle:null};const tabState={activeTabId:'case-test'};let calls=[];apiFetch=async(...args)=>{calls.push(args);throw Error('Unexpected article API')};showToast=()=>{};`+api});
 await page.addScriptTag({content:read('frontend/apex-case-record-editor.js')});
 await page.evaluate(()=>{document.body.insertAdjacentHTML('beforeend','<section id="fixture" style="position:fixed;inset:0;z-index:500;background:white"><input id="recordTitle" value="匿名记录"><textarea id="record"></textarea></section>');document.querySelector('#record').value='### 争议焦点\n\n**合同效力**与付款凭证\n\n- 第一项\n- 第二项';ApexCaseRecordEditor.mount(document.querySelector('#record'),{titleInput:document.querySelector('#recordTitle')});});
 // New drafts must contain no placeholder text, including after advanced editing.
 await page.evaluate(()=>{document.querySelector('#record').value='';document.querySelector('#record').dispatchEvent(new Event('input'));});
 await page.waitForFunction(()=>document.querySelector('.case-record-preview').dataset.empty==='true');
 assert.equal(await page.locator('.case-record-preview').textContent(),'');
 assert.equal(await page.locator('#record').inputValue(),'');
 assert.match(await page.locator('.case-record-preview').evaluate(el=>getComputedStyle(el,'::before').content),/开始记录/);
 assert.equal(await page.evaluate(()=>ApexRecordEditor.render('')),'');
 await page.getByRole('button',{name:'高级格式设置',exact:true}).click();
 assert.equal((await page.locator('#body-editor').textContent()).trim(),'');
 await page.getByRole('button',{name:'应用格式',exact:true}).click();
 assert.doesNotMatch(await page.locator('#record').inputValue(),/暂无正文|开始记录/);
 await page.evaluate(()=>{document.querySelector('#record').value='### 争议焦点\n\n**合同效力**与付款凭证\n\n- 第一项\n- 第二项';document.querySelector('#record').dispatchEvent(new Event('input'));});
 await page.waitForFunction(()=>document.querySelector('.case-record-preview strong'));
 assert.match(await page.locator('.case-record-preview').textContent(),/争议焦点/);
 assert.equal(await page.locator('.case-record-preview strong').textContent(),'合同效力');
 await page.getByRole('button',{name:'高级格式设置',exact:true}).click();
 await page.waitForSelector('#edit-body-modal.open');
 await page.waitForTimeout(350);await page.screenshot({path:path.join(root,'.tmp/case-format-editor.png')});
 assert.equal(await page.locator('#body-editor strong').textContent(),'合同效力');
 const typography=await page.evaluate(()=>{
  const properties=['fontFamily','fontSize','lineHeight','letterSpacing','textIndent'];
  return ['#body-editor','.case-record-preview'].map(selector=>Object.fromEntries(properties.map(key=>[key,getComputedStyle(document.querySelector(selector))[key]])));
 });assert.deepEqual(typography[0],typography[1],'Inline record and full editor must share typography');
 await page.locator('#body-editor').evaluate(el=>{el.innerHTML='<h2>核对结果</h2><p><strong>已完成</strong> <span style="color: rgb(180, 30, 30)">重点</span></p>';el.dispatchEvent(new InputEvent('input',{bubbles:true}));});
 await page.getByRole('button',{name:'应用格式',exact:true}).click();
 assert.equal(await page.locator('#edit-body-modal').evaluate(el=>el.classList.contains('open')),false);
 assert.match(await page.locator('#record').inputValue(),/<strong>已完成<\/strong>/);
 assert.match(await page.locator('.case-record-preview').textContent(),/核对结果/);
 assert.equal(await page.evaluate(()=>calls.length),0,'Formatting must not write article APIs');
 await page.locator('.case-record-preview').fill('直接编辑的记录');
 assert.match(await page.locator('#record').inputValue(),/直接编辑的记录/);
 const saved=await page.locator('#record').inputValue();
 await page.getByRole('button',{name:'高级格式设置',exact:true}).click();
 await page.locator('#body-editor').fill('取消的修改');
 await page.locator('#edit-body-modal .editor-cancel-btn').click();
 assert.equal(await page.locator('#record').inputValue(),saved);
 await page.evaluate(()=>{document.querySelector('#record').value='### 安全\n\n<script>window.injected=true</script>\n\n[危险](javascript:alert(1))';document.querySelector('#record').dispatchEvent(new Event('input'));});
 assert.equal(await page.evaluate(()=>!!window.injected),false);
 assert.equal(await page.locator('.case-record-preview script,.case-record-preview [href^="javascript:"]').count(),0);
 // Preserve the paragraph at the reading position across advanced-format transitions.
 await page.evaluate(()=>{document.querySelector('#record').value=Array.from({length:35},(_,i)=>'<p>第'+i+'段：'+('匿名案件材料与分析。'.repeat(5))+'</p>').join('');document.querySelector('#record').dispatchEvent(new Event('input'));});
 await page.waitForTimeout(100);
 await page.locator('.case-record-preview').evaluate(el=>{el.scrollTop=600;});
 const opening=await page.evaluate(()=>ApexRecordEditor.captureScroll(document.querySelector('.case-record-preview'),document.querySelector('.case-record-preview')));
 for(const action of ['cancel','apply']) {
  await page.getByRole('button',{name:'高级格式设置',exact:true}).click();
  await page.waitForTimeout(200);
  const inside=await page.evaluate(()=>ApexRecordEditor.captureScroll(document.querySelector('#body-editor'),document.querySelector('#content-editor-wrapper')));
  assert.equal(inside.blockText,opening.blockText,'Advanced editor must open at the same paragraph');
  assert(Math.abs(inside.blockProgress-opening.blockProgress)<.05);
  await page.locator(action==='cancel'?'#edit-body-modal .editor-cancel-btn':'#edit-body-modal .editor-save-btn').click();
  await page.waitForTimeout(100);
  const returned=await page.evaluate(()=>ApexRecordEditor.captureScroll(document.querySelector('.case-record-preview'),document.querySelector('.case-record-preview')));
  assert.equal(returned.blockText,opening.blockText,'Returning must retain the visible paragraph');
  assert(Math.abs(returned.blockProgress-opening.blockProgress)<.05);
 }
 // Removed drafts cannot receive an application from an old editor session.
 await page.getByRole('button',{name:'高级格式设置',exact:true}).click();
 await page.evaluate(()=>document.querySelector('#record').remove());
 assert.equal(await page.evaluate(()=>saveBody()),false);
 await page.evaluate(()=>closeEditBodyModal(true));
 assert.deepEqual(errors,[]);
 const series=read('frontend/case-manager.js');
 const funcs=['captureSeriesTablePosition','restoreSeriesTablePosition','toggleSeriesTableEditMode'].map(name=>{const node=acorn.parse(series,{ecmaVersion:'latest'}).body.find(n=>n.type==='FunctionDeclaration'&&n.id.name===name);return series.slice(node.start,node.end)}).join('\n');
 const table=await browser.newPage();await table.setContent('<div id="seriesWorkspaceBody" style="height:500px;overflow:auto"><div id="seriesStageFilter"></div><div id="seriesChildTableHost"></div></div>');
 await table.addScriptTag({content:`const $=id=>document.getElementById(id);const state={seriesTableEditMode:false,seriesSelectedChildIds:new Set(),seriesCellMultiSelection:new Set()};function isOfflineReadonly(){return false}function syncSeriesTableStickyOffset(){}function toast(){}function renderSeriesChildTable(){}function renderSeriesWorkspace(){document.querySelector('#seriesChildTableHost').innerHTML='<div class="series-table-wrap" style="width:700px;height:420px;overflow:auto"><table style="width:1600px"><thead style="position:sticky;top:0;background:white"><tr><th style="height:40px">主表</th></tr></thead><tbody>'+Array.from({length:60},(_,i)=>'<tr data-series-child-id="'+i+'"><td style="height:'+(state.seriesTableEditMode?100:75)+'px">子案 '+i+'</td></tr>').join('')+'</tbody></table></div>';}`+funcs});
 await table.evaluate(()=>{renderSeriesWorkspace();const el=document.querySelector('.series-table-wrap');el.scrollTop=1620;el.scrollLeft=430;});
 const original=await table.evaluate(()=>captureSeriesTablePosition());
 for(let i=0;i<4;i++){
  await table.evaluate(()=>toggleSeriesTableEditMode());await table.waitForTimeout(60);
  const after=await table.evaluate(()=>captureSeriesTablePosition());
  assert.equal(after.rowId,original.rowId);assert(Math.abs(after.offset-original.offset)<2);assert.equal(after.left,original.left);
 }
 // The workspace body is the scroller when the table grows to its full height.
 await table.evaluate(()=>{document.querySelector('.series-table-wrap').style.height='auto';document.querySelector('#seriesWorkspaceBody').scrollTop=1650;});
 const outer=await table.evaluate(()=>captureSeriesTablePosition());
 await table.evaluate(()=>{const original=renderSeriesWorkspace;renderSeriesWorkspace=()=>{original();document.querySelector('.series-table-wrap').style.height='auto';};});
 for(let i=0;i<2;i++){
  await table.evaluate(()=>toggleSeriesTableEditMode());await table.waitForTimeout(60);
  const after=await table.evaluate(()=>captureSeriesTablePosition());assert.equal(after.rowId,outer.rowId);assert(Math.abs(after.offset-outer.offset)<2);
 }
 // A stale cached adapter without the new text helper must keep the list usable.
 const listFunction=acorn.parse(series,{ecmaVersion:'latest'}).body.find(n=>n.type==='FunctionDeclaration'&&n.id.name==='caseResearchEntriesHtml');
 await table.addScriptTag({content:`window.ApexCaseRecordEditor={mount(){}};function caseResearchFilteredItems(){return[{id:1,title:'匿名记录',content:'历史内容'}]}function caseResearchLabel(){return '案件备忘录'}function esc(value){return String(value||'')}function dateOnly(){return '2026-10-21'};state.caseResearch={section:'memo'};`+series.slice(listFunction.start,listFunction.end)});
 assert.match(await table.evaluate(()=>caseResearchEntriesHtml()),/历史内容/);
 await browser.close();console.log('Case formatting: Markdown, shared full editor, formatting apply/cancel, sanitization, stale drafts and no article writes passed; series row anchor and horizontal position passed in both directions.');
})().catch(e=>{console.error(e);process.exit(1)});
