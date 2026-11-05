/* Native copy/cut events and table paste against anonymous, in-memory records. */
const fs=require('fs'),path=require('path'),assert=require('assert'),acorn=require('acorn');
const {chromium,webkit}=require(process.env.STELLA_PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'..'),source=fs.readFileSync(path.join(root,'frontend/case-manager.js'),'utf8'),ast=acorn.parse(source,{ecmaVersion:'latest'});
const names=['seriesSelectionBounds','seriesSelectedCellKeySet','seriesMultiCellKey','seriesSelectedCellModels','seriesSelectedCellMatrix','seriesClipboardTableHtml','seriesRichFormatSegments','cloneSeriesCellFormat','seriesClipboardHasTable','seriesClipboardIsGrid','seriesClipboardMatrix','handleSeriesTableCopy','handleSeriesTableCut','handleSeriesTablePaste','persistSeriesTablePaste','seriesSelectionAnchorBounds','seriesEditorHasTextSelection','saveSeriesCellBatch','persistSeriesCellBatch'];
const code=names.map(name=>{const n=ast.body.find(n=>n.type==='FunctionDeclaration'&&n.id.name===name);assert(n,name);return source.slice(n.start,n.end)}).join('\n');
(async()=>{for(const engine of [chromium,webkit]){const browser=await engine.launch(engine===chromium?{headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'}:{headless:true});const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.setContent('<div id="seriesChildTableHost"><div class="series-table-wrap" tabindex="0" oncopy="handleSeriesTableCopy(event)" oncut="handleSeriesTableCut(event)">匿名表格</div></div>');
await page.addScriptTag({content:`const $=id=>document.getElementById(id),seriesPendingCellSaves=new Set(),columns=[{key:'memo'},{key:'case_no'}],items=[{id:101,memo:'首行\\n次行',case_no:'00123',folder:'anonymous-A',cell_formats:{memo:{runs:[{start:0,end:2,bold:true,color:'red'}]}}},{id:102,memo:'目标',case_no:'00456',folder:'anonymous-B'}];
const state={seriesWorkspace:{id:1,children:items},seriesTableEditMode:true,seriesCellSelection:{startRow:0,endRow:0,startColumn:0,endColumn:0},seriesCellMultiSelection:new Set()};
const currentSeriesVisibleColumns=()=>columns,currentSeriesColumns=()=>columns,seriesFilteredItems=()=>state.seriesWorkspace.children,seriesCellValue=(item,key)=>item[key],seriesCellEditable=()=>true,isOfflineReadonly=()=>false;
function currentSeriesSettings(){return{freeze_columns:0,freeze_rows:0}}async function persistSeriesColumns(next){columns.splice(0,columns.length,...next);return true}
function esc(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
let history=[],calls=[],lastMessage='';function toast(value){lastMessage=value}function pushSeriesHistory(entry){history.push(entry)}
async function reloadSeriesWorkspace(){}async function applySeriesRowOrder(ids){state.seriesWorkspace.children=ids.map(id=>state.seriesWorkspace.children.find(item=>item.id===id))}
async function api(url,options){const body=JSON.parse(options.body);calls.push({url,body});if(url.endsWith('/table/paste')){body.updates=body.matrix.flatMap((row,r)=>row.map((value,c)=>({childId:body.row_ids[body.row+r],field:body.keys[body.column+c],value,...(body.formats?{format:body.formats[r][c]}:{})})));}else if(!url.endsWith('/cells/batch'))throw Error('Unexpected API');for(const update of body.updates){const item=state.seriesWorkspace.children.find(item=>item.id===update.childId);if('value' in update)item[update.field]=update.value;if('format' in update)item.cell_formats={...item.cell_formats,[update.field]:update.format}}return{ok:true,undo_token:'anonymous-token'}}
${code}
let captured={};document.addEventListener('copy',e=>{const original=e.clipboardData.setData.bind(e.clipboardData);e.clipboardData.setData=(type,value)=>{captured[type]=value;return original(type,value)}},true);
document.addEventListener('cut',e=>{const original=e.clipboardData.setData.bind(e.clipboardData);e.clipboardData.setData=(type,value)=>{captured[type]=value;return original(type,value)}},true);
async function pasteCaptured(row,col){state.seriesCellSelection={startRow:row,endRow:row,startColumn:col,endColumn:col};const data=new DataTransfer();for(const [type,value]of Object.entries(captured))data.setData(type,value);await handleSeriesTablePaste({clipboardData:data,preventDefault(){}})}
`});
await page.locator('.series-table-wrap').focus();await page.keyboard.press('Meta+c');
assert.equal(await page.evaluate(()=>captured['text/plain']),'首行\n次行');assert((await page.evaluate(()=>captured['text/html'])).includes('font-weight:700'));
await page.evaluate(()=>{items[0].memo='复制后修改';});assert.equal(await page.evaluate(()=>state.seriesTableClipboard.snapshot.rows[0].values.memo),'首行\n次行');
await page.evaluate(()=>pasteCaptured(1,0));assert.equal(await page.evaluate(()=>items[1].memo),'首行\n次行');assert.equal(await page.evaluate(()=>items[1].cell_formats.memo.runs[0].color),'red');
assert.equal(await page.evaluate(()=>history[0].type),'paste_transaction');assert.equal(await page.evaluate(()=>history[0].token),'anonymous-token');
// Cutting a full row reorders stable identities rather than clearing business values.
await page.evaluate(()=>{state.seriesCellSelection={startRow:1,endRow:1,startColumn:0,endColumn:1};});await page.locator('.series-table-wrap').focus();await page.keyboard.press('Meta+x');
assert.equal(await page.evaluate(()=>state.seriesWorkspace.children[1].memo),'首行\n次行');
await page.evaluate(()=>pasteCaptured(0,0));assert.deepEqual(await page.evaluate(()=>state.seriesWorkspace.children.map(item=>[item.id,item.folder])),[[102,'anonymous-B'],[101,'anonymous-A']]);
// Whole-column cut preserves fields and values while moving their presentation order.
await page.evaluate(()=>{state.seriesCellSelection={startRow:0,endRow:1,startColumn:1,endColumn:1};});await page.locator('.series-table-wrap').focus();await page.keyboard.press('Meta+x');
await page.evaluate(()=>pasteCaptured(0,0));assert.deepEqual(await page.evaluate(()=>columns.map(column=>column.key)),['case_no','memo']);
assert.deepEqual(await page.evaluate(()=>state.seriesWorkspace.children.map(item=>item.case_no)),['00456','00123']);
// Sparse diagonal regions cannot silently overwrite their unselected holes.
await page.evaluate(()=>{state.seriesCellSelection=null;state.seriesCellMultiSelection=new Set(['0:0','1:1']);});await page.keyboard.press('Meta+x');assert.equal(await page.evaluate(()=>state.seriesCut),null);assert((await page.evaluate(()=>lastMessage)).includes('完整的行列组合'));
// A pending save must cancel copy without creating a new cut state.
await page.evaluate(()=>{seriesPendingCellSaves.add(Promise.resolve(true));state.seriesCut=null;});await page.keyboard.press('Meta+x');assert.equal(await page.evaluate(()=>state.seriesCut),null);
assert.deepEqual(errors,[]);await browser.close();console.log(engine.name()+': native copy/cut, copied snapshot, multiline/style paste and stable row move passed');
}})().catch(e=>{console.error(e);process.exit(1)});
