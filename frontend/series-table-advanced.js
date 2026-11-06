/* Optional series-table views and validation; business writes stay in the existing adapters. */
function seriesDecimalParts(value){
  const text=String(value??'').trim().replace(/[,，\s￥¥]/g,'');
  if(text.length>1000||!/^[-+]?\d+(?:\.\d+)?$/.test(text))return null;
  const negative=text.startsWith('-'),parts=text.replace(/^[-+]/,'').split('.'),fraction=parts[1]||'';
  return {value:BigInt(parts[0]+fraction)*(negative?-1n:1n),scale:fraction.length};
}
function seriesCompareDecimals(a,b){
  const left=seriesDecimalParts(a),right=seriesDecimalParts(b);if(!left||!right)return null;
  const scale=Math.max(left.scale,right.scale),x=left.value*10n**BigInt(scale-left.scale),y=right.value*10n**BigInt(scale-right.scale);
  return x<y?-1:x>y?1:0;
}
function seriesValidDate(value){
  const text=String(value??'');if(!/^\d{4}-\d{2}-\d{2}$/.test(text))return false;
  const date=new Date(text+'T00:00:00Z');return Number.isFinite(date.getTime())&&date.toISOString().slice(0,10)===text;
}
function seriesConditionMatches(value,condition){
  const text=String(value??'');if(!condition)return true;
  if(condition.kind==='empty')return !text.trim();
  if(condition.kind==='nonempty')return !!text.trim();
  if(condition.kind==='contains')return text.toLocaleLowerCase().includes(String(condition.value||'').toLocaleLowerCase());
  if(condition.kind==='number'){
    if(!seriesDecimalParts(text))return false;
    const low=condition.min!==''&&condition.min!==undefined?seriesCompareDecimals(text,condition.min):0;
    const high=condition.max!==''&&condition.max!==undefined?seriesCompareDecimals(text,condition.max):0;
    return low!==null&&high!==null&&low>=0&&high<=0;
  }
  if(condition.kind==='date')return seriesValidDate(text)&&(!condition.min||text>=condition.min)&&(!condition.max||text<=condition.max);
  return true;
}
function seriesSortItems(items,columns){
  const rules=currentSeriesSortRules();
  if(!rules.length)return items;
  return items.map((item,index)=>({item,index})).sort((a,b)=>{
    for(const rule of rules){
      const column=columns.find(column=>column.key===rule.key);if(!column)continue;
      const x=seriesCellValue(a.item,rule.key),y=seriesCellValue(b.item,rule.key);
      let result=null;
      if(column.semantic_type==='amount'||['number','amount'].includes(column.field_type)||['number','amount'].includes(column.validation?.type))result=seriesCompareDecimals(x,y);
      if(result===null)result=String(x??'').localeCompare(String(y??''),'zh-CN',{numeric:true});
      if(result)return result*(rule.direction==='desc'?-1:1);
    }
    return a.index-b.index;
  }).map(entry=>entry.item);
}
function seriesColumnValidationMessage(value,column){
  const rule=column.validation;if(!rule)return '';
  const text=String(value??'').trim();if(!text)return rule.required?'此列不允许空白':'';
  if(['number','amount'].includes(rule.type)&&!/^[-+]?\d+(?:\.\d+)?$/.test(text.replace(/,/g,'')))return '请输入普通数字，不使用单位或科学计数法';
  if(rule.type==='date'&&!seriesValidDate(text))return '日期应为 YYYY-MM-DD';
  if(rule.type==='choice'&&!rule.values?.includes(text))return '请选择此列候选值';
  return '';
}
function seriesConditionalClass(item,column){
  let yellow=false,red=!!seriesColumnValidationMessage(seriesCellValue(item,column.key),column);
  for(const rule of currentSeriesSettings().conditional_rules||[]){
    if(rule.key!==column.key)continue;
    const value=String(seriesCellValue(item,column.key)??'');
    const compare=['greater','less'].includes(rule.kind)?seriesCompareDecimals(value,rule.value):null;
    const match=rule.kind==='contains'?value.includes(rule.value):rule.kind==='empty'?!value.trim():rule.kind==='greater'?compare!==null&&compare>0:rule.kind==='less'?compare!==null&&compare<0:rule.kind==='date_before'?seriesValidDate(value)&&seriesValidDate(rule.value)&&value<rule.value:false;
    if(match){if(rule.color==='red')red=true;else yellow=true;}
  }
  return (yellow?' series-cell-background-yellow':'')+(red?' series-cell-rule-red':'');
}
function seriesRowHeightStyle(item){
  const height=currentSeriesSettings().row_heights?.[String(item.id)];return height?`height:${height}px;--series-row-height:${height}px;`:'';
}
async function saveSeriesTablePreferences(settings,label='更新表格设置',columns=currentSeriesColumns()){
  const before=currentSeriesColumns().map(column=>({...column})),beforeSettings=JSON.parse(JSON.stringify(currentSeriesSettings()));
  if(await persistSeriesColumns(columns,[],settings,{recordHistory:false})){
    pushSeriesHistory({type:'columns',label,before,after:columns.map(column=>({...column})),beforeSettings,afterSettings:JSON.parse(JSON.stringify(settings))});return true;
  }
  return false;
}
async function openSeriesAdvancedPanel(section='sort'){
  if(!requireOnlineAction())return;
  try{await flushSeriesTableEditors();}catch(e){return toast(e.message);}
  state.seriesAdvancedCells=seriesSelectedCellModels().map(model=>({childId:model.item.id,field:model.columnDef.key}));
  state.seriesAdvancedColumnKey='';
  const columns=currentSeriesVisibleColumns();
  const views=Object.keys(currentSeriesSettings().views||{});
  const tabs=[['sort','排序'],['filter','筛选与高亮'],['columns','列与尺寸'],['views','模板与打印']];
  const targetColumns=columns.filter(column=>seriesAdvancedKeys().includes(column.key)).map(column=>column.label);
  showSeriesSide('视图与列设置','仅影响当前系列。',`<div class="series-view-settings">
    <nav class="series-view-settings-nav" aria-label="设置分类">${tabs.map(([key,label])=>`
      <button class="btn" type="button" data-series-settings-tab="${key}" aria-pressed="false" onclick="selectSeriesSettingsSection('${key}')">${label}</button>`).join('')}</nav>
    <div data-series-settings-panel="sort" hidden>
      <section class="series-detail-block"><h3>排序优先级</h3><p>从第一项开始比较，值相同时使用下一项。</p>
        <div id="seriesSortEditor">${seriesSortEditorHtml()}</div>
      </section>
    </div>
    <div data-series-settings-panel="filter" hidden>
      <section class="series-detail-block"><h3>应用到</h3>
        <details><summary id="seriesAdvancedColumnLabel">${esc(targetColumns.length?targetColumns.join('、'):'选择目标列')}</summary>
          <div class="series-view-column-options">${columns.map((column,index)=>`<button class="btn" type="button" onclick="selectSeriesAdvancedColumn(${index})">${esc(column.label)}</button>`).join('')}</div>
        </details>
      </section>
      <section class="series-detail-block"><h3>筛选条件</h3><label>下限或开始日期<input class="input" id="seriesConditionMin" placeholder="最小金额或开始日期 YYYY-MM-DD"></label><label>上限或结束日期<input class="input" id="seriesConditionMax" placeholder="最大金额或结束日期 YYYY-MM-DD"></label><label>包含文字<input class="input" id="seriesConditionText" placeholder="包含的文字"></label><div class="series-view-settings-controls"><button class="btn" onclick="applySeriesAdvancedFilter('number')">金额范围</button><button class="btn" onclick="applySeriesAdvancedFilter('date')">日期范围</button><button class="btn" onclick="applySeriesAdvancedFilter('contains')">包含文字</button><button class="btn" onclick="applySeriesAdvancedFilter('empty')">空白</button><button class="btn" onclick="applySeriesAdvancedFilter('nonempty')">非空白</button><button class="btn" onclick="applySeriesAdvancedFilter('clear')">清除所选列条件</button></div></section>
      <section class="series-detail-block"><h3>条件高亮</h3><label>匹配值<input class="input" id="seriesRuleValue" placeholder="匹配文字、金额阈值或日期"></label><div class="series-view-settings-controls"><button class="btn" onclick="addSeriesConditionalRule('contains','red')">包含文字标红</button><button class="btn" onclick="addSeriesConditionalRule('greater','yellow')">大于金额标黄</button><button class="btn" onclick="addSeriesConditionalRule('less','yellow')">小于金额标黄</button><button class="btn" onclick="addSeriesConditionalRule('date_before','yellow')">早于日期标黄</button><button class="btn" onclick="addSeriesConditionalRule('empty','yellow')">空白标黄</button><button class="btn" onclick="clearSeriesConditionalRules()">清除所选列规则</button></div></section>
    </div>
    <div data-series-settings-panel="columns" hidden>
      <p>当前选区：${esc(targetColumns.join('、')||'未选中列')}。尺寸和校验应用于打开面板时的选区。</p>
      <div><button class="btn" type="button" onclick="openSeriesColumnManager()">管理列与冻结</button></div>
      <section class="series-detail-block"><h3>所选行列尺寸</h3><label>行高（像素）<input class="input" id="seriesRowHeight" type="number" min="80" max="600" placeholder="行高 80—600"></label><label>列宽（像素）<input class="input" id="seriesColumnWidth" type="number" min="80" max="420" placeholder="列宽 80—420"></label><div class="series-view-settings-controls"><button class="btn" onclick="setSeriesSelectedDimensions(false)">应用尺寸</button><button class="btn" onclick="setSeriesSelectedDimensions(true)">恢复自动适配</button></div></section>
      <section class="series-detail-block"><h3>列校验</h3><label><input id="seriesValidationRequired" type="checkbox"> 不允许空白</label><label>候选值（每行一个）<textarea class="input" id="seriesValidationChoices"></textarea></label><div class="series-view-settings-controls"><button class="btn" onclick="setSeriesColumnValidation('text')">文本</button><button class="btn" onclick="setSeriesColumnValidation('number')">数字</button><button class="btn" onclick="setSeriesColumnValidation('amount')">金额</button><button class="btn" onclick="setSeriesColumnValidation('date')">日期</button><button class="btn" onclick="setSeriesColumnValidation('choice')">候选值</button><button class="btn" onclick="setSeriesColumnValidation(null)">取消校验</button></div><p>数字、金额和日期校验只用于自定义列；案号和子案编号始终保留文本。</p></section>
    </div>
    <div data-series-settings-panel="views" hidden>
      <section class="series-detail-block"><h3>视图模板</h3><label>模板名称<input class="input" id="seriesViewName" maxlength="80" placeholder="模板名称"></label><button class="btn" onclick="saveSeriesViewTemplate()">保存当前视图</button>${views.map((name,i)=>`<div class="series-view-settings-controls"><strong>${esc(name)}</strong><button class="btn" onclick="applySeriesViewTemplate(${i})">应用</button><button class="btn" onclick="deleteSeriesViewTemplate(${i})">删除模板</button></div>`).join('')}</section>
      <section class="series-detail-block"><h3>选区打印</h3><p>仅打印打开设置时选中的行列内容。</p><button class="btn" onclick="printSeriesSelection()">打印所选区域</button></section>
    </div>
  </div>`);
  selectSeriesSettingsSection(section);
}
function selectSeriesSettingsSection(section){
  const panel=$('seriesSideBody');
  panel.querySelectorAll('[data-series-settings-tab]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.seriesSettingsTab===section)));
  panel.querySelectorAll('[data-series-settings-panel]').forEach(content=>content.hidden=content.dataset.seriesSettingsPanel!==section);
}
function seriesAdvancedKeys(){return [...new Set((state.seriesAdvancedCells||[]).map(cell=>cell.field))];}
function seriesAdvancedConditionKeys(){
  return state.seriesAdvancedColumnKey?[state.seriesAdvancedColumnKey]:seriesAdvancedKeys();
}
function selectSeriesAdvancedColumn(index){
  const column=currentSeriesVisibleColumns()[index];
  if(!column)return;
  state.seriesAdvancedColumnKey=column.key;
  const summary=$('seriesAdvancedColumnLabel');
  summary.textContent=column.label;
  summary.closest('details').open=false;
  summary.focus();
}
function currentSeriesSortRules(){
  return state.seriesSortRules?.length?state.seriesSortRules:state.seriesSortKey?[{key:state.seriesSortKey,direction:state.seriesSortDirection}]:[];
}
function seriesSortEditorHtml(){
  const columns=currentSeriesVisibleColumns(),rules=currentSeriesSortRules();
  const available=columns.filter(column=>!rules.some(rule=>rule.key===column.key));
  return `${rules.length?`<ol class="series-view-sort-rules">${rules.map((rule,index)=>{
    const label=columns.find(column=>column.key===rule.key)?.label||rule.key;
    return `<li><div><strong>${esc(label)}</strong><div class="series-view-settings-controls">
      <button class="btn" onclick="editSeriesSortRule(${index},'direction')" aria-label="${esc(label)}：${rule.direction==='desc'?'降序':'升序'}，点击反转">${rule.direction==='desc'?'降序':'升序'}</button>
      <button class="btn" onclick="editSeriesSortRule(${index},'up')" aria-label="上移 ${esc(label)}" ${index===0?'disabled':''}>↑</button>
      <button class="btn" onclick="editSeriesSortRule(${index},'down')" aria-label="下移 ${esc(label)}" ${index===rules.length-1?'disabled':''}>↓</button>
      <button class="btn" onclick="editSeriesSortRule(${index},'remove')" aria-label="移除 ${esc(label)}">移除</button>
    </div></div></li>`;
  }).join('')}</ol>`:'<p>当前按原始行顺序显示。</p>'}
  <div class="series-view-settings-controls">
    ${available.length&&rules.length<10?`<details><summary>添加排序字段</summary><div class="series-view-column-options">${available.map(column=>`<button class="btn" onclick="addSeriesSortRule(${columns.indexOf(column)})">${esc(column.label)}</button>`).join('')}</div></details>`:''}
    ${rules.length?'<button class="btn" onclick="updateSeriesSortRules([])">清除全部</button>':''}
  </div>`;
}
function updateSeriesSortRules(rules){
  state.seriesSortRules=rules;
  state.seriesSortKey='';
  renderSeriesChildTable();
  $('seriesSortEditor').innerHTML=seriesSortEditorHtml();
}
function addSeriesSortRule(index){
  const column=currentSeriesVisibleColumns()[index],rules=currentSeriesSortRules();
  if(!column||rules.length>=10||rules.some(rule=>rule.key===column.key))return;
  updateSeriesSortRules([...rules,{key:column.key,direction:'asc'}]);
}
function editSeriesSortRule(index,action){
  const rules=currentSeriesSortRules().slice(),rule=rules[index];
  if(!rule)return;
  if(action==='direction')rules[index]={...rule,direction:rule.direction==='desc'?'asc':'desc'};
  else if(action==='remove')rules.splice(index,1);
  else {
    const adjacent=index+(action==='up'?-1:1);
    if(!rules[adjacent])return;
    [rules[index],rules[adjacent]]=[rules[adjacent],rule];
  }
  updateSeriesSortRules(rules);
}
function applySeriesAdvancedFilter(kind){
  const keys=seriesAdvancedConditionKeys();if(!keys.length)return toast('请选择目标列');
  const condition={kind,min:$('seriesConditionMin').value.trim(),max:$('seriesConditionMax').value.trim(),value:$('seriesConditionText').value};
  if(kind==='number'&&[condition.min,condition.max].some(value=>value&&!seriesDecimalParts(value)))return toast('金额范围应为普通数字');
  if(kind==='date'&&[condition.min,condition.max].some(value=>value&&!seriesValidDate(value)))return toast('日期应为有效的 YYYY-MM-DD');
  if(condition.min&&condition.max&&(kind==='number'?seriesCompareDecimals(condition.min,condition.max)>0:kind==='date'?condition.min>condition.max:false))return toast('范围起点不能大于终点');
  for(const key of keys){const filter=typeof state.seriesColumnFilters[key]==='object'?{...state.seriesColumnFilters[key]}:{};if(kind==='clear')delete filter.condition;else filter.condition={...condition};if(Object.keys(filter).length)state.seriesColumnFilters[key]=filter;else delete state.seriesColumnFilters[key];}
  renderSeriesChildTable();
}
async function setSeriesSelectedDimensions(reset){
  const cells=state.seriesAdvancedCells||[];if(!cells.length)return toast('请先选中行列，再打开设置');
  const rawHeight=$('seriesRowHeight').value,rawWidth=$('seriesColumnWidth').value,height=Number(rawHeight),width=Number(rawWidth);
  if(!reset&&((rawHeight&&(!Number.isInteger(height)||height<80||height>600))||(rawWidth&&(!Number.isInteger(width)||width<80||width>420))))return toast('请使用有效范围内的整数尺寸');
  if(!reset&&!rawHeight&&!rawWidth)return toast('请填写行高或列宽');
  const settings=JSON.parse(JSON.stringify(currentSeriesSettings())),heights={...(settings.row_heights||{})},ids=[...new Set(cells.map(cell=>cell.childId))],keys=seriesAdvancedKeys();
  if(reset||rawHeight)for(const id of ids){if(reset)delete heights[id];else heights[id]=height;}
  settings.row_heights=heights;
  const columns=currentSeriesColumns().map(column=>keys.includes(column.key)&&(reset||rawWidth)?{...column,...(reset?{manual_width:false}:{width,manual_width:true})}:column);
  if(await saveSeriesTablePreferences(settings,reset?'恢复自动行高列宽':'设置行高列宽',columns))toast('已更新尺寸，可撤销');
}
async function setSeriesColumnValidation(type){
  const keys=seriesAdvancedKeys();if(!keys.length)return toast('请先选中目标列，再打开设置');
  const values=[...new Set($('seriesValidationChoices').value.split(/\r?\n/).map(value=>value.trim()).filter(Boolean))];
  if(type==='choice'&&(!values.length||values.length>1000||values.some(value=>value.length>500)))return toast('请填写 1 至 1000 个候选值，每项不超过 500 字符');
  const columns=currentSeriesColumns().map(column=>{
    if(!keys.includes(column.key)||column.source==='derived'||column.field_type==='readonly')return column;
    if(type&&!['text','choice'].includes(type)&&!column.key.startsWith('custom_'))return column;
    const next={...column};if(!type)delete next.validation;else next.validation={type,required:$('seriesValidationRequired').checked,...(type==='choice'?{values}: {})};
    return next;
  });
  if(JSON.stringify(columns)===JSON.stringify(currentSeriesColumns()))return toast('没有可修改的列；数字和日期校验仅支持自定义列');
  if(await saveSeriesTablePreferences(currentSeriesSettings(),'设置列校验',columns))toast('已设置校验；已有数据不会自动改写，不符合规则的值会标红');
}
async function addSeriesConditionalRule(kind,color){
  const keys=seriesAdvancedConditionKeys(),value=$('seriesRuleValue').value;
  if(!keys.length)return toast('请先选中目标列');
  if(['greater','less'].includes(kind)&&!seriesDecimalParts(value))return toast('请输入有效金额阈值');
  if(kind==='date_before'&&!seriesValidDate(value))return toast('日期应为 YYYY-MM-DD');
  if(kind==='contains'&&!value)return toast('请输入匹配文字');
  const settings=currentSeriesSettings(),rules=[...(settings.conditional_rules||[]),...keys.map(key=>({key,kind,value,color}))];
  if(rules.length>200)return toast('当前系列最多设置 200 条高亮规则，请先清理旧规则');
  if(await saveSeriesTablePreferences({...settings,conditional_rules:rules},'添加条件高亮'))toast('已添加条件高亮，可撤销');
}
async function clearSeriesConditionalRules(){const keys=seriesAdvancedConditionKeys(),settings=currentSeriesSettings();if(!keys.length)return toast('请选择目标列');await saveSeriesTablePreferences({...settings,conditional_rules:(settings.conditional_rules||[]).filter(rule=>!keys.includes(rule.key))},'清除条件高亮');}
async function saveSeriesViewTemplate(){
  const name=$('seriesViewName').value.trim();if(!name||['__proto__','constructor','prototype'].includes(name))return toast('请使用其他模板名称');
  const settings=currentSeriesSettings(),views={...(settings.views||{})};if(!views[name]&&Object.keys(views).length>=10)return toast('当前系列最多保存 10 个视图模板');
  views[name]={columns:currentSeriesColumns().map(({key,width,manual_width,hidden})=>({key,width,manual_width,hidden})),sorts:state.seriesSortRules?.length?state.seriesSortRules:state.seriesSortKey?[{key:state.seriesSortKey,direction:state.seriesSortDirection}]:[],filters:JSON.parse(JSON.stringify(state.seriesColumnFilters))};
  if(await saveSeriesTablePreferences({...settings,views},'保存视图模板')){toast('已保存视图模板');await openSeriesAdvancedPanel('views');}
}
async function applySeriesViewTemplate(index){
  const settings=currentSeriesSettings(),view=Object.values(settings.views||{})[index];if(!view)return;
  const current=currentSeriesColumns(),lookup=new Map(current.map(column=>[column.key,column])),columns=[];
  for(const config of view.columns||[]){const column=lookup.get(config.key);if(column){columns.push({...column,...config});lookup.delete(config.key);}}
  columns.push(...lookup.values());
  if(!columns.some(column=>!column.hidden))return toast('模板没有可显示的列，请调整列设置');
  const beforeView={sorts:JSON.parse(JSON.stringify(state.seriesSortRules?.length?state.seriesSortRules:state.seriesSortKey?[{key:state.seriesSortKey,direction:state.seriesSortDirection}]:[])),filters:JSON.parse(JSON.stringify(state.seriesColumnFilters||{}))};
  if(await saveSeriesTablePreferences(settings,'应用视图模板',columns)){
    const keys=new Set(columns.map(column=>column.key));state.seriesSortKey='';state.seriesSortRules=(view.sorts||[]).filter(rule=>keys.has(rule.key));state.seriesColumnFilters=Object.fromEntries(Object.entries(view.filters||{}).filter(([key])=>keys.has(key)));const entry=state.seriesUndoStack[state.seriesUndoStack.length-1];if(entry){entry.beforeView=beforeView;entry.afterView={sorts:JSON.parse(JSON.stringify(state.seriesSortRules)),filters:JSON.parse(JSON.stringify(state.seriesColumnFilters))};}renderSeriesChildTable();toast('已应用视图模板');
  }
}
async function deleteSeriesViewTemplate(index){const settings=currentSeriesSettings(),views={...(settings.views||{})},name=Object.keys(views)[index];if(!name)return;delete views[name];if(await saveSeriesTablePreferences({...settings,views},'删除视图模板'))await openSeriesAdvancedPanel('views');}
let seriesPrintFrame=null;
async function printSeriesSelection(){
  try{await flushSeriesTableEditors();}catch(e){return toast(e.message);}
  const cells=state.seriesAdvancedCells||[],keys=new Set(cells.map(cell=>cell.field)),ids=new Set(cells.map(cell=>cell.childId)),columns=currentSeriesVisibleColumns().filter(column=>keys.has(column.key)),items=seriesFilteredItems(currentSeriesVisibleColumns()).filter(item=>ids.has(item.id));
  if(!columns.length||!items.length)return toast('请先选择需要打印的区域');
  const selected=new Set(cells.map(cell=>`${cell.childId}:${cell.field}`));
  seriesPrintFrame?.remove();const frame=document.createElement('iframe');seriesPrintFrame=frame;frame.setAttribute('title','所选区域打印');frame.style.cssText='position:fixed;width:1px;height:1px;right:0;bottom:0;border:0;opacity:0;';
  frame.onload=()=>{const target=frame.contentWindow;if(!target)return;target.addEventListener('afterprint',()=>{frame.remove();if(seriesPrintFrame===frame)seriesPrintFrame=null},{once:true});target.focus();target.print();};
  frame.srcdoc=`<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>${esc(state.seriesWorkspace.title||'系列案件')}</title><style>body{font:12px -apple-system,sans-serif;color:#111;background:white}h1{font-size:18px}table{width:100%;border-collapse:collapse}th,td{border:1px solid #888;padding:6px;text-align:left;vertical-align:top;white-space:pre-wrap;overflow-wrap:anywhere}thead{display:table-header-group}tr{break-inside:avoid}.series-rich-bold{font-weight:700}.series-rich-italic{font-style:italic}.series-rich-underline{text-decoration:underline}.series-rich-red{color:#a00}.series-rich-highlight{background:#ffeb80}@page{size:landscape;margin:12mm}</style><h1>${esc(state.seriesWorkspace.title||'系列案件')}</h1><table><thead><tr>${columns.map(column=>`<th>${esc(column.label)}</th>`).join('')}</tr></thead><tbody>${items.map(item=>`<tr>${columns.map(column=>`<td>${selected.has(`${item.id}:${column.key}`)?seriesRichTextHtml(String(seriesCellValue(item,column.key)??''),item.cell_formats?.[column.key]):''}</td>`).join('')}</tr>`).join('')}</tbody></table></html>`;
  document.body.append(frame);
}
window.StellaSeriesAdvanced={sortItems:seriesSortItems,conditionMatches:seriesConditionMatches,cellClass:seriesConditionalClass,rowHeightStyle:seriesRowHeightStyle,sortSymbol:key=>{const index=(state.seriesSortRules||[]).findIndex(rule=>rule.key===key);return index<0?'':`${state.seriesSortRules[index].direction==='desc'?'↓':'↑'}${index+1}`;}};

async function openSeriesChoicePanel(childId,key){
  try{await flushSeriesTableEditors();}catch(e){return toast(e.message);}
  const column=currentSeriesColumns().find(column=>column.key===key),item=state.seriesWorkspace?.children.find(item=>Number(item.id)===childId);
  if(!column||!item||column.validation?.type!=='choice'||!seriesCellEditable(column))return;
  state.seriesChoiceTarget={seriesId:state.seriesWorkspace.id,childId,key};
  showSeriesSide(column.label+' · 选择候选值','选择后只写入当前单元格，可撤销。',`<div class="series-tools-panel"><input class="input" id="seriesChoiceSearch" placeholder="搜索候选值" oninput="renderSeriesChoiceOptions()"><div id="seriesChoiceOptions"></div></div>`,'<button class="btn" onclick="closeSeriesSide()">取消</button>');
  renderSeriesChoiceOptions();
}
function renderSeriesChoiceOptions(){
  const target=state.seriesChoiceTarget,column=currentSeriesColumns().find(column=>column.key===target?.key),host=$('seriesChoiceOptions');if(!host||!column)return;
  const query=$('seriesChoiceSearch').value.toLocaleLowerCase(),values=column.validation.values||[],matches=values.map((value,index)=>({value,index})).filter(entry=>entry.value.toLocaleLowerCase().includes(query));
  host.innerHTML=matches.slice(0,100).map(entry=>`<button class="btn" type="button" onclick="chooseSeriesColumnValue(${entry.index})">${esc(entry.value)}</button>`).join('')+`<p>匹配 ${matches.length} 项${matches.length>100?'，请搜索缩小范围':''}</p>`;
}
async function chooseSeriesColumnValue(index){
  const target=state.seriesChoiceTarget;if(!target||state.seriesWorkspace?.id!==target.seriesId)return;
  const column=currentSeriesColumns().find(column=>column.key===target.key),value=column?.validation?.values?.[index];if(typeof value!=='string')return;
  try{await saveSeriesCellBatch([{childId:target.childId,field:target.key,value}],{label:'选择候选值'});closeSeriesSide();}catch(e){toast(e.message);}
}
