/* Real tool-panel controls against anonymous fixtures, no live server writes. */
const fs=require('fs'),path=require('path'),assert=require('assert'),acorn=require('acorn');
const {chromium,webkit}=require(process.env.STELLA_PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'..'),source=fs.readFileSync(path.join(root,'frontend/case-manager.js'),'utf8'),ast=acorn.parse(source,{ecmaVersion:'latest'});
const names=['flushSeriesTableEditors','openSeriesToolsPanel','seriesToolModels','seriesFindMatches','findSeriesText','replaceSeriesText','seriesSequenceValue','fillSeriesCells','pasteSeriesSpecial','showSeriesSide','closeSeriesSide'];
const funcs=names.map(name=>{const n=ast.body.find(n=>n.type==='FunctionDeclaration'&&n.id.name===name);assert(n,name);return source.slice(n.start,n.end)}).join('\n');
(async()=>{for(const engine of [chromium,webkit]){const browser=await engine.launch(engine===chromium?{headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'}:{headless:true});const page=await browser.newPage();let errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.setContent('<div id="seriesChildTableHost"></div><aside class="series-side" id="seriesSide"><h2 id="seriesSideTitle"></h2><p id="seriesSideSubtitle"></p><div class="series-side-body" id="seriesSideBody"></div><footer id="seriesSideFoot"></footer></aside>');
await page.addStyleTag({content:fs.readFileSync(path.join(root,'frontend/case-manager.css'),'utf8')});
await page.addScriptTag({content:`const $=id=>document.getElementById(id),seriesPendingCellSaves=new Set(),items=[{id:101,memo:'匿名.*甲'},{id:102,memo:'匿名.*乙'}],columns=[{key:'memo',label:'备注'}];
const state={seriesWorkspace:{id:1,children:items},seriesCellMultiSelection:new Set()};
const requireOnlineAction=()=>true,currentSeriesVisibleColumns=()=>columns,seriesFilteredItems=()=>items,seriesCellValue=(item,key)=>item[key],seriesCellEditable=()=>true,seriesSelectedCellModels=()=>items.map((item,row)=>({item,row,column:0,columnDef:columns[0],value:item.memo})),cloneSeriesCellFormat=f=>JSON.parse(JSON.stringify(f||{}));
function activateSeriesLookups(){}function applySeriesCellSelectionStyles(){}function seriesCellAddress(row,col){return 'A'+(row+1)}function toast(m){window.lastMessage=m}
async function saveSeriesCellBatch(updates){window.lastUpdates=updates;updates.forEach(u=>items.find(item=>item.id===u.childId)[u.field]=u.value)}
async function saveSeriesCellFormatBatch(updates){window.lastFormats=updates}function renderSeriesChildTable(){}
`+funcs});
for(const {width,height,dark} of [{width:1440,height:900,dark:false},{width:1024,height:768,dark:true}]){
await page.setViewportSize({width,height});await page.evaluate(dark=>document.documentElement.classList.toggle('dark-mode',dark),dark);await page.evaluate(()=>openSeriesToolsPanel());
await page.locator('#seriesFindText').fill('.*');await page.getByRole('button',{name:'下一处',exact:true}).click();assert((await page.locator('#seriesFindFeedback').textContent()).includes('1 / 2'));
await page.locator('#seriesReplaceText').fill('$1');await page.getByRole('button',{name:'替换全部',exact:true}).click();assert.equal(await page.evaluate(()=>items[0].memo),'匿名$1甲');
await page.locator('#seriesFillOverwrite').check();await page.locator('#seriesSequenceStart').fill('0001');await page.locator('#seriesSequenceStep').fill('2');await page.getByRole('button',{name:'按行递增',exact:true}).click();assert.equal(await page.evaluate(()=>items[1].memo),'0003');
assert(await page.locator('#seriesSide').evaluate(el=>el.scrollWidth<=el.clientWidth+1));
// Reset anonymous text for the next appearance.
await page.evaluate(()=>{items[0].memo='匿名.*甲';items[1].memo='匿名.*乙'});
}
assert.deepEqual(errors,[]);await browser.close();console.log(engine.name()+': real tool panel find/replace, exact sequence and narrow-layout checks passed')}
})().catch(e=>{console.error(e);process.exit(1)});
