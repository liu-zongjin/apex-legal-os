const fs=require('fs'),path=require('path'),acorn=require('acorn'),assert=require('assert');
const {chromium,webkit}=require(process.env.STELLA_PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'..'),src=fs.readFileSync(path.join(root,'frontend/case-manager.js'),'utf8'),ast=acorn.parse(src,{ecmaVersion:'latest'});
const names=['seriesWorkspaceMainToolsHtml','seriesSheetBarHtml','applySeriesCellSelectionStyles','seriesSelectionBounds','seriesMultiCellKey','cancelSeriesTableClipboard','toggleSeriesTableEditMode','seriesWorkspaceRibbonTabsHtml','setSeriesRibbonTab','switchSeriesWorkspaceTab','closeSeriesActionsMenu','toggleSeriesActionsMenu','renderSeriesWorkspace','archiveSeries','openCaseActionDialog','closeCaseDeleteDialog','confirmCaseDelete','actionButtons'];
const pageHtml=fs.readFileSync(path.join(root,'frontend/case-manager.html'),'utf8');
const caseDialog=pageHtml.slice(pageHtml.indexOf('  <div class="complete-dialog-mask" id="caseDeleteDialogMask"'),pageHtml.indexOf('  <div class="mobile-record-action-mask"'));
const clipboardEscape=ast.body.find(n=>n.type==='ExpressionStatement'&&src.slice(n.start,n.end).includes('&&cancelSeriesTableClipboard()'));
assert(clipboardEscape);
const code=names.map(name=>{const n=ast.body.find(n=>n.type==='FunctionDeclaration'&&n.id.name===name);assert(n,name);return src.slice(n.start,n.end)}).join('\n')+'\n'+src.slice(clipboardEscape.start,clipboardEscape.end);
(async()=>{for(const engine of [chromium,webkit]){const b=await engine.launch(engine===chromium?{headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'}:{headless:true}),p=await b.newPage({viewport:{width:1440,height:900}}),errors=[];p.on('pageerror',e=>errors.push(e.message));
await p.setContent('<section class="series-workspace show" id="seriesWorkspace"><header class="series-workspace-head"><div class="series-workspace-title"><h1 id="seriesWorkspaceTitle"></h1><p id="seriesWorkspaceSubtitle"></p></div><div class="series-workspace-ribbon-slot" id="seriesWorkspaceRibbonTabs"></div><div id="seriesWorkspaceActions" class="series-workspace-actions"></div></header><main id="seriesWorkspaceBody" class="series-workspace-body"></main></section><input id="seriesImportFile" type="file">'+caseDialog);
await p.addStyleTag({content:fs.readFileSync(path.join(root,'frontend/case-manager.css'),'utf8')});
await p.addScriptTag({content:`const $=id=>document.getElementById(id),seriesPendingCellSaves=new Set();const state={seriesWorkspace:{id:12,title:'示例系列案件',case_type:'合同纠纷',children:[],stats:{total:0,stage_distribution:{}}},seriesWorkspaceTab:'children',seriesTableEditMode:true,seriesSelectedChildIds:new Set(),seriesUndoStack:[],seriesRedoStack:[],seriesChildQuery:'',seriesCellMultiSelection:new Set()};function esc(s){return String(s)}function isOfflineReadonly(){return false}function seriesStageText(){return '待补充'}function renderSeriesChildTable(){
  document.getElementById('seriesChildTableHost').innerHTML='<div class="series-table-wrap" style="height:200px"><table><tbody><tr><td data-series-row-index="0" data-series-column-index="0">匿名主表</td></tr></tbody></table></div>';
  applySeriesCellSelectionStyles();
}function scheduleSeriesMobileLayoutSync(){}function syncSeriesTableStickyOffset(){}function currentSeriesVisibleColumns(){return [{key:'memo'}]}function seriesFilteredItems(){return [{id:1}]}function seriesSelectedCellModels(){return []}function seriesParseAmount(){return NaN}function notifyCaseManagerContext(){}function seriesSelectionRangeLabel(){return 'A1'}function captureSeriesTablePosition(){}function restoreSeriesTablePosition(){}function toast(message){window.lastMessage=message}
function closeSeriesWorkspace(){window.lastAction='back';state.seriesWorkspace=null;$('seriesWorkspace').classList.remove('show')}
function requireOnlineAction(){return true}
function refreshAll(){window.refreshCount=(window.refreshCount||0)+1}
async function api(url,options){
  window.archiveRequests=(window.archiveRequests||[]).concat({url,method:options.method,body:JSON.parse(options.body)});
  if(window.failArchive)throw new Error('暂时无法归档');
}function exportSeriesWorkbook(){window.lastAction='export'}function openSeriesImportHistory(){}function openSeriesBatchPanel(){}function deleteSeries(){}async function flushSeriesTableEditors(){}function closeSeriesFilterPopover(){}function persistSeriesHash(){}function notifySeriesWorkspaceContext(){}function resizeSeriesPublicInlineEditor(){}function prepareSeriesPublicFieldOrder(){}function activateSeriesLookups(){}function seriesPublicInfoHtml(){return '<section>公共信息内容</section>'}${code} renderSeriesWorkspace();`});
for(const mode of [{width:1440,dark:false},{width:1024,dark:true},{width:700,dark:false},{width:320,dark:true}]){await p.setViewportSize({width:mode.width,height:900});await p.evaluate(dark=>document.documentElement.classList.toggle('dark-mode',dark),mode.dark);assert.equal(await p.locator('.series-title-text').textContent(),'示例系列案件');await p.getByRole('button',{name:'系列操作'}).click();assert.equal(await p.locator('#seriesActionsToggle').getAttribute('aria-expanded'),'true');assert.equal(await p.getByRole('menuitem',{name:/导出 Excel/}).count(),1);await p.getByRole('menuitem',{name:/导出 Excel/}).click();assert.equal(await p.evaluate(()=>window.lastAction),'export');assert(await p.locator('#seriesActionsMenu').isHidden());await p.getByRole('tab',{name:'数据'}).click();assert.equal(await p.locator('[data-ribbon-panel]:visible').getAttribute('data-ribbon-panel'),'data');assert(await p.locator('.series-workspace-head').evaluate(el=>el.scrollWidth<=el.clientWidth+1));
const header=await p.locator('.series-workspace-head').boundingBox(),tabs=await p.locator('.series-ribbon-tabs').boundingBox();
assert(Math.abs(header.x+header.width/2-tabs.x-tabs.width/2)<=1);
const before=(await p.locator('.series-table-wrap').boundingBox()).y;
await p.getByRole('button',{name:'完成编辑'}).click();
assert.equal((await p.locator('.series-table-wrap').boundingBox()).y,before);
await p.getByRole('button',{name:'编辑主表'}).click();
assert.equal((await p.locator('.series-table-wrap').boundingBox()).y,before);
await p.getByRole('tab',{name:'开始'}).click();
assert.equal((await p.locator('.series-table-wrap').boundingBox()).y,before);
}
await p.setViewportSize({width:1440,height:900});
await p.evaluate(()=>{document.documentElement.classList.remove('dark-mode');state.seriesTableClipboard={seriesId:12,source_ids:[1],source_keys:['memo']};applySeriesCellSelectionStyles()});
assert.equal(await p.locator('td.series-copy-top').count(),1);
await p.locator('#seriesFormulaInput').press('Escape');
assert.equal(await p.locator('td.series-copy-top').count(),0);
assert(await p.locator('#seriesCancelClipboard').isHidden());
assert.equal(await p.evaluate(()=>state.seriesTableClipboard),null);
await p.evaluate(()=>{state.seriesTableClipboard={seriesId:12,source_ids:[1],source_keys:['memo']};applySeriesCellSelectionStyles()});
await p.getByRole('button',{name:'取消复制'}).click();
assert.equal(await p.evaluate(()=>state.seriesTableClipboard),null);
await p.locator('.series-title-toggle').press('Enter');
assert.equal(await p.locator('.series-title-view').innerText(),'系列案公共信息 ⇄');
assert.equal(await p.locator('.series-ribbon-tabs').count(),0);
await p.locator('.series-title-toggle').click();
assert.equal(await p.locator('.series-title-view').innerText(),'子案信息主表 ⇄');
assert(await p.getByRole('tab',{name:'数据'}).isVisible());
await p.screenshot({path:'/tmp/stella-series-compact-header.png',clip:{x:0,y:0,width:1440,height:155},animations:'disabled'});
const rowActions=await p.evaluate(()=>{
  const item={id:12,title:'示例系列案件'};
  const buttons=document.createElement('div');
  const result=[];
  for(const kind of ['ordinary','series']){
    buttons.innerHTML=actionButtons('cases',{...item,case_kind:kind});
    result.push([...buttons.querySelectorAll('button')].map(button=>[button.textContent,button.getAttribute('onclick')]));
  }
  return result;
});
assert.deepEqual(rowActions[0],rowActions[1]);
assert.deepEqual(rowActions[1].map(([label])=>label),['案件文件','案卷归档','查看']);

const dialog=p.getByRole('dialog',{name:'结案并归档？'});
const openArchive=async()=>{
  await p.getByRole('button',{name:'系列操作'}).click();
  await p.getByRole('menuitem',{name:/结案归档/}).click();
  assert(await dialog.isVisible());
  assert(await p.locator('#seriesWorkspace').isVisible());
};
await openArchive();
assert((await dialog.innerText()).includes('仍在办的子案也将一并结案归档'));
await dialog.getByRole('button',{name:'取消'}).click();
assert(await dialog.isHidden());
assert.equal(await p.evaluate(()=>window.archiveRequests),undefined);
await openArchive();
await p.evaluate(()=>{window.failArchive=true});
await dialog.getByRole('button',{name:'确认结案'}).click();
assert(await dialog.isVisible());
assert(await dialog.getByRole('button',{name:'确认结案'}).isEnabled());
assert.equal(await p.evaluate(()=>window.lastMessage),'暂时无法归档');
await p.evaluate(()=>{window.failArchive=false});
await dialog.getByRole('button',{name:'确认结案'}).click();
assert(await dialog.isHidden());
assert(await p.locator('#seriesWorkspace').isHidden());
assert.equal(await p.evaluate(()=>window.refreshCount),1);

await p.evaluate(()=>{
  state.seriesWorkspace={id:41,title:'原系列'};
  archiveSeries();
  state.seriesWorkspace={id:42,title:'另一系列'};
});
await dialog.getByRole('button',{name:'确认结案'}).click();
assert.equal(await p.evaluate(()=>state.seriesWorkspace.id),42);
assert.deepEqual(await p.evaluate(()=>window.archiveRequests),[12,12,41].map(id=>({
  url:'/api/case-manager/series/'+id+'/archive',method:'POST',body:{force:true},
})));
assert.deepEqual(errors,[]);await b.close();console.log(engine.name()+': title switching, stable table position, clipboard cancellation and layouts passed');}})().catch(e=>{console.error(e);process.exit(1)});
