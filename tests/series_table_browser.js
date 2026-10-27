/* Anonymous production-render checks; no live case data or backend writes. */
const fs=require('fs'),path=require('path'),assert=require('assert'),acorn=require('acorn');
const {chromium,webkit}=require(process.env.STELLA_PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'..'),source=fs.readFileSync(path.join(root,'frontend/case-manager.js'),'utf8');
const tree=acorn.parse(source,{ecmaVersion:'latest'});
const names=['seriesTableViewport','captureSeriesTablePosition','restoreSeriesTablePosition','toggleSeriesTableEditMode','renderSeriesChildTable','seriesStickyColumnStyle','seriesFrozenRowStyle','prepareSeriesCellLayout','seriesAutoGrowCell','seriesCellHtml','seriesCellVerticalAlignStyle','seriesCellBackgroundClass','seriesRichTextHtml','seriesRichFormatSegments','seriesPlainTextFromFragment','seriesRichEditorValue','saveSeriesRichCell','persistSeriesRichCell'];
const funcs=names.map(name=>{const n=tree.body.find(n=>n.type==='FunctionDeclaration'&&n.id.name===name);assert(n,name);return source.slice(n.start,n.end)}).join('\n');
(async()=>{
 for(const engine of [chromium,webkit]){
 const browser=await engine.launch(engine===chromium?{headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'}:{headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.setContent('<div id="seriesWorkspace"><div id="seriesWorkspaceBody" style="height:780px;overflow:auto"></div></div>');
 await page.addStyleTag({content:fs.readFileSync(path.join(root,'frontend/case-manager.css'),'utf8')});
 await page.addScriptTag({content:`
 const $=id=>document.getElementById(id),seriesPendingCellSaves=new Set();
 const state={seriesWorkspace:{id:1,children:Array.from({length:60},(_,i)=>({id:i+1,case_no:'（2026）示例初字'+i+'号\\n（2026）示例终字'+i+'号',memo:'匿名长文字材料。'.repeat(i%4+1),source_status:'active'}))},seriesTableEditMode:false,seriesColumnFilters:{},seriesSelectedChildIds:new Set(),seriesCellMultiSelection:new Set()};
 let freeze=0,calls=[],failSave=false,outerScroll=false;
 const columns=Array.from({length:8},(_,i)=>({key:i===0?'case_no':'memo'+i,label:i===0?'案号':'匿名列'+i,width:210}));
 function currentSeriesSettings(){return{freeze_columns:freeze,freeze_rows:freeze}}
 function currentSeriesVisibleColumns(){return columns} function seriesFilteredItems(){return state.seriesWorkspace.children}
 function seriesColumnsWithSmartWidths(c){return c} function isSeriesMobileCardMode(){return false}
 function seriesCellValue(item,key){return item[key]??item.memo} function seriesCellEditable(){return true} function seriesDetailDisplayColumn(){return false}
 function isOfflineReadonly(){return false} function activateSeriesLookups(){} function applySeriesCellSelectionStyles(){} function updateSeriesSelectionSummary(){} function selectSeriesCellFromEditor(){} function beginSeriesEditorSelection(){} function startSeriesCellSelection(){} function extendSeriesCellSelection(){}
 function syncSeriesTableStickyOffset(){document.querySelector('.series-table-wrap')?.style.setProperty('--series-table-sticky-top','0px')} function toast(){} function pushSeriesHistory(){} function scheduleSeriesViewStateSync(){}
 function esc(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
 async function api(url,options){calls.push(JSON.parse(options.body));await new Promise(r=>setTimeout(r,30));if(failSave)throw Error('匿名保存失败');const id=Number(url.split('/').at(-2)),item=state.seriesWorkspace.children.find(x=>x.id===id);return {...item,[calls.at(-1).field]:calls.at(-1).value,cell_formats:{}}}
 function renderSeriesWorkspace(){ $('seriesWorkspaceBody').innerHTML='<div class="series-workspace-tabs" style="height:60px">主表<button id="mode" onclick="toggleSeriesTableEditMode()">编辑</button></div><div class="series-toolbar" style="position:static;height:'+(state.seriesTableEditMode?100:30)+'px">工具栏</div><div id="seriesChildTableHost"></div>';renderSeriesChildTable();if(outerScroll)document.querySelector('.series-table-wrap').style.maxHeight='none';}
 `+funcs});
 for(const appearance of [{width:1440,height:900,dark:false},{width:1024,height:768,dark:true}]){
 await page.setViewportSize({width:appearance.width,height:appearance.height});
 await page.evaluate(dark=>document.documentElement.classList.toggle("dark-mode",dark),appearance.dark);
 for(const frozen of [0,1]){
  await page.evaluate(frozen=>{freeze=frozen;state.seriesTableEditMode=false;renderSeriesWorkspace()},frozen);
  await page.waitForTimeout(80);
  await page.evaluate(()=>{const table=document.querySelector('.series-table-wrap');table.scrollTop=1120;table.scrollLeft=530});
  const initial=await page.evaluate(()=>captureSeriesTablePosition());
  for(let i=0;i<6;i++){
   await page.evaluate(()=>toggleSeriesTableEditMode());await page.waitForTimeout(80);
   const next=await page.evaluate(()=>captureSeriesTablePosition());
   assert.equal(next.rowId,initial.rowId,engine.name()+' row freeze='+frozen);
   assert(Math.abs(next.offset-initial.offset)<2,JSON.stringify({initial,next}));
   assert.equal(next.columnKey,initial.columnKey);
   assert(Math.abs(next.columnOffset-initial.columnOffset)<2,JSON.stringify({initial,next}));
  }
 }
 }
 await page.setViewportSize({width:1440,height:900});
 // Outer workspace scrolling and local table rerenders retain the reading row.
 await page.evaluate(()=>{freeze=0;outerScroll=true;renderSeriesWorkspace()});await page.waitForTimeout(80);
 await page.evaluate(()=>{$('seriesWorkspaceBody').scrollTop=1450});
 const outer=await page.evaluate(()=>captureSeriesTablePosition());
 for(let i=0;i<4;i++){
  await page.evaluate(()=>toggleSeriesTableEditMode());await page.waitForTimeout(80);
  const next=await page.evaluate(()=>captureSeriesTablePosition());
  assert.equal(next.rowId,outer.rowId);assert(Math.abs(next.offset-outer.offset)<2);
 }
 await page.evaluate(()=>{outerScroll=false;renderSeriesWorkspace()});await page.waitForTimeout(80);
 await page.evaluate(()=>{const el=document.querySelector('.series-table-wrap');el.scrollTop=950;el.scrollLeft=500});
 const beforeRender=await page.evaluate(()=>captureSeriesTablePosition());
 await page.evaluate(()=>renderSeriesChildTable());await page.waitForTimeout(80);
 assert.deepEqual(await page.evaluate(()=>captureSeriesTablePosition()),beforeRender);
 // A blur save must finish before the completed-view DOM is rendered.
 await page.evaluate(()=>{freeze=0;state.seriesTableEditMode=true;renderSeriesWorkspace()});await page.waitForTimeout(80);
 const editor=page.locator('.series-cell-rich-input').first();
 await editor.fill('（2026）示例初字999号\n（2026）示例终字888号');
 await page.locator('#mode').click();await page.waitForTimeout(100);
 assert.equal(await page.evaluate(()=>state.seriesTableEditMode),false);
 assert.equal(await page.locator('.series-cell-display').first().innerText(),'（2026）示例初字999号\n（2026）示例终字888号');
 await page.evaluate(()=>toggleSeriesTableEditMode());await page.waitForTimeout(80);
 await page.locator('.series-cell-rich-input').first().fill('保存失败时保留输入');
 await page.evaluate(()=>{failSave=true});await page.locator('#mode').click();await page.waitForTimeout(100);
 assert.equal(await page.evaluate(()=>state.seriesTableEditMode),true);
 assert.equal(await page.locator('.series-cell-rich-input').first().innerText(),'保存失败时保留输入');
 await page.evaluate(()=>{failSave=false});await page.locator('#mode').click();await page.waitForTimeout(100);
 assert.equal(await page.evaluate(()=>state.seriesTableEditMode),false);
 assert.equal(await page.locator('.series-cell-display').first().innerText(),'保存失败时保留输入');
 assert.deepEqual(errors,[]);await browser.close();
 console.log(engine.name()+': production table toggles, frozen rows/columns, multiline blur save and failure retention passed');
 }
})().catch(e=>{console.error(e);process.exit(1)});
