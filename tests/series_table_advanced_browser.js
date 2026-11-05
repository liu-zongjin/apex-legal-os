/* Advanced controls and exact comparisons, against anonymous in-memory fixtures. */
const fs=require('fs'),path=require('path'),assert=require('assert'),acorn=require('acorn');
const {chromium,webkit}=require(process.env.STELLA_PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'..'),source=fs.readFileSync(path.join(root,'frontend/case-manager.js'),'utf8'),ast=acorn.parse(source,{ecmaVersion:'latest'});
const funcs=['showSeriesSide','closeSeriesSide','seriesMatchesColumnFilter'].map(name=>{const node=ast.body.find(n=>n.type==='FunctionDeclaration'&&n.id.name===name);assert(node,name);return source.slice(node.start,node.end)}).join('\n');
(async()=>{for(const engine of [chromium,webkit]){
 const browser=await engine.launch(engine===chromium?{headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'}:{headless:true}),page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.setContent('<div id="seriesChildTableHost"></div><aside class="series-side" id="seriesSide"><h2 id="seriesSideTitle"></h2><p id="seriesSideSubtitle"></p><div class="series-side-body" id="seriesSideBody"></div><footer id="seriesSideFoot"></footer></aside>');
 await page.addStyleTag({content:fs.readFileSync(path.join(root,'frontend/case-manager.css'),'utf8')});
 await page.addScriptTag({content:`const $=id=>document.getElementById(id);const state={seriesWorkspace:{id:1,title:'匿名系列',children:[{id:101,custom_money:'9007199254740993.01',memo:'甲'},{id:102,custom_money:'9007199254740993.02',memo:'乙'}]},seriesColumnFilters:{},seriesSortRules:[],seriesUndoStack:[],seriesAdvancedCells:[]};
let columns=[{key:'custom_money',label:'金额',field_type:'text',validation:{type:'amount'},width:160},{key:'memo',label:'备注',width:160}],settings={freeze_columns:0,freeze_rows:0};
function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
const currentSeriesColumns=()=>columns,currentSeriesVisibleColumns=()=>columns.filter(c=>!c.hidden),currentSeriesSettings=()=>settings,requireOnlineAction=()=>true,flushSeriesTableEditors=async()=>{},seriesCellValue=(item,key)=>item[key],seriesFilterValue=(item,key)=>String(item[key]??''),seriesCellEditable=()=>true;
const seriesSelectedCellModels=()=>state.seriesWorkspace.children.map((item,row)=>({item,row,column:0,columnDef:columns[0]}));
function renderSeriesChildTable(){}function activateSeriesLookups(){}function toast(message){window.lastMessage=message}function pushSeriesHistory(entry){state.seriesUndoStack.push(entry)}
async function persistSeriesColumns(next,deleted,nextSettings){columns=JSON.parse(JSON.stringify(next));settings=JSON.parse(JSON.stringify(nextSettings));return true}
async function saveSeriesCellBatch(updates){updates.forEach(u=>state.seriesWorkspace.children.find(item=>item.id===u.childId)[u.field]=u.value)}
`+funcs});
 await page.addScriptTag({content:fs.readFileSync(path.join(root,'frontend/series-table-advanced.js'),'utf8')});
 const exact=await page.evaluate(()=>{
   state.seriesSortRules=[{key:'custom_money',direction:'desc'},{key:'memo',direction:'asc'}];
   return {compare:seriesCompareDecimals('9007199254740993.01','9007199254740993.02'),sorted:seriesSortItems(state.seriesWorkspace.children,columns).map(item=>item.id),inRange:seriesConditionMatches('9007199254740993.01',{kind:'number',min:'9007199254740993.02',max:''}),leap:seriesValidDate('2025-02-29'),filter:seriesMatchesColumnFilter(state.seriesWorkspace.children[0],'memo',{values:['甲'],condition:{kind:'contains',value:'乙'}})};
 });
 assert.deepEqual(exact,{compare:-1,sorted:[102,101],inRange:false,leap:false,filter:false});
 for(const mode of [{width:1440,height:900,dark:false},{width:1024,height:768,dark:true}]){
 await page.setViewportSize({width:mode.width,height:mode.height});await page.evaluate(dark=>document.documentElement.classList.toggle('dark-mode',dark),mode.dark);await page.evaluate(()=>openSeriesAdvancedPanel());
 await page.locator('#seriesRowHeight').fill('120');await page.locator('#seriesColumnWidth').fill('240');await page.getByRole('button',{name:'应用尺寸',exact:true}).click();
 assert.equal(await page.evaluate(()=>settings.row_heights[101]),120);assert.equal(await page.evaluate(()=>columns[0].width),240);
 await page.locator('#seriesConditionMin').fill('9007199254740993.02');await page.getByRole('button',{name:'金额范围',exact:true}).click();assert.equal(await page.evaluate(()=>state.seriesColumnFilters.custom_money.condition.min),'9007199254740993.02');
 await page.locator('#seriesRuleValue').fill('9007199254740993.01');await page.getByRole('button',{name:'大于金额标黄',exact:true}).click();assert((await page.evaluate(()=>seriesConditionalClass(state.seriesWorkspace.children[1],columns[0]))).includes('yellow'));
 await page.locator('#seriesViewName').fill('金额视图');await page.getByRole('button',{name:'保存当前视图',exact:true}).click();assert.equal(await page.evaluate(()=>settings.views['金额视图'].columns[0].width),240);
 await page.getByRole('button',{name:'应用',exact:true}).click();assert.equal(await page.evaluate(()=>state.seriesUndoStack.at(-1).afterView.sorts.length),2);
 await page.locator('#seriesValidationChoices').fill('候选甲\n候选乙');await page.getByRole('button',{name:'候选值',exact:true}).click();assert.equal(await page.evaluate(()=>columns[0].validation.type),'choice');
 await page.evaluate(()=>openSeriesChoicePanel(101,'custom_money'));await page.locator('#seriesChoiceSearch').fill('乙');await page.getByRole('button',{name:'候选乙',exact:true}).click();assert.equal(await page.evaluate(()=>state.seriesWorkspace.children[0].custom_money),'候选乙');
 await page.evaluate(()=>{columns[0].validation={type:'amount'};state.seriesWorkspace.children[0].custom_money='9007199254740993.01'});
 assert(await page.locator('#seriesSide').evaluate(el=>el.scrollWidth<=el.clientWidth+1));
 }
 assert.deepEqual(errors,[]);await browser.close();console.log(engine.name()+': advanced sorting, filtering, dimensions, validation, views and choices passed');
}})().catch(error=>{console.error(error);process.exit(1)});
