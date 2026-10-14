const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const source = fs.readFileSync('frontend/app.js','utf8');
function extract(name) {
  const start = source.indexOf('function '+name+'(');
  assert(start >= 0);
  return source.slice(start, source.indexOf('\nfunction ', start+1));
}
const context = vm.createContext({URLSearchParams});
vm.runInContext(extract('normaliseCaseDatabaseCitation')+extract('cleanCaseAiContent'), context);
const sourceData = {source_type:'case_database', record_count:5, excerpt:'[{"id":1460,"title":"开庭","case_id":54,"case_title":"匿名甲案件"},{"id":222,"case_id":16,"case_title":"匿名乙案件","notes":"被截断'};
const result = context.normaliseCaseDatabaseCitation(sourceData);
assert.equal(result.case_links.length,2);
assert.equal(result.case_links[0].case_id,54);
assert.equal(result.case_links[0].case_title,'匿名甲案件');
assert(!result.case_links.some(link=>link.case_id===1460));
assert(!result.excerpt.includes('case_id'));
const content = context.cleanCaseAiContent('[citation:1] has_more=false court_contact current_stage pending');
assert.equal(content,'【依据1】 结果已完整返回 案件联系人 当前阶段 未完成');
assert.equal(sourceData.excerpt[0],'[');
const formatted = '### 内部分析\n\n- 漏项约400万元。【依据1】\n- 申请对数。';
assert.equal(context.cleanCaseAiContent(JSON.stringify({answer:formatted})),formatted);
assert.equal(context.cleanCaseAiContent('```json\n'+JSON.stringify({answer:formatted})+'\n```'),formatted);
assert.equal(context.cleanCaseAiContent(JSON.stringify({answer:JSON.stringify({answer:formatted})})),formatted);
assert.equal(context.cleanCaseAiContent(formatted),formatted);
vm.runInContext(extract('escapeHtml')+extract('renderAskMarkdown'), context);
const rendered = context.renderAskMarkdown(context.cleanCaseAiContent(JSON.stringify({answer:formatted})));
assert(rendered.includes('<h3>内部分析</h3>'));
assert(rendered.includes('<ul><li>'));
assert(!rendered.includes('\\n'));
assert(context.renderAskMarkdown('2. 第二项\n\n- 子项\n\n3. 第三项').includes('<ol start="3">'));
assert(context.renderAskMarkdown('<script>alert(1)</script>').includes('&lt;script&gt;'));

assert.equal(context.cleanCaseAiContent('普通正文 {保留原文}'), '普通正文 {保留原文}');
console.log('Case AI UI compatibility checks passed');

vm.runInContext(extract('caseManagerFrameSrc'),context);
const frameUrl = context.caseManagerFrameSrc({id:'tab_1',data:{viewState:{caseId:54}}});
assert.equal(new URLSearchParams(frameUrl.split('?')[1]).get('case_id'),'54');
vm.runInContext("var tabState={tabs:[]}; var TAB_TYPES={CASE_MANAGER:'case_manager'}; var selected=null; function openCaseManagerTab(view){selected=view.caseId;} function switchTab(id){selected=id;}"+extract('openCaseDatabaseCitationCase'),context);
context.openCaseDatabaseCitationCase(54);
assert.equal(vm.runInContext('selected',context),54);
console.log('Case detail navigation checks passed');

// Exercise scope changes and mode isolation without a live database or AI call.
const shortcutStart = source.indexOf('let caseAiShortcutDays =');
const shortcutEnd = source.indexOf('// ── 渲染历史记录到聊天区', shortcutStart);
const controls = [{dataset:{caseAiDays:'7'},setAttribute(key,value){this[key]=value;}}, {dataset:{caseAiDays:'30'},setAttribute(key,value){this[key]=value;}}];
let draft = '', drawerRemoved = false;
const drawer = {open:true,remove(){drawerRemoved=true;}};
context.document = {querySelector(){return null;},querySelectorAll(selector){return selector==='[data-case-ai-days]' ? controls : [];},getElementById(){return drawer;}};
context.useAskSuggestion = text => {draft=text;};
vm.runInContext("var askContext={type:'case_database'};"+source.slice(shortcutStart,shortcutEnd),context);
context.setCaseAiShortcutScope('days',7);
context.useCaseAiShortcut('hearings');
assert(draft.includes('未来7天'));
assert(draft.includes('仅在办案件'));
assert.equal(drawer.open,false);
assert.equal(controls[0]['aria-pressed'],'true');
assert.equal(controls[1]['aria-pressed'],'false');
context.setCaseAiShortcutScope('archived',true);
context.setCaseAiShortcutScope('days',90);
context.useCaseAiShortcut('delivery');
assert(draft.includes('最近90天'));
assert(draft.includes('全部在办及已归档案件'));
assert(draft.includes('未关联的记录另行列示'));
assert(draft.includes('同步时间'));
context.useCaseAiShortcut('fees');
assert(draft.includes('不将空值视为零'));
context.setCaseAiShortcutScope('days',-1);
context.useCaseAiShortcut('hearings');
assert(draft.includes('未来90天'));
const validDraft = draft;
context.useCaseAiShortcut('unknown');
assert.equal(draft,validDraft);
vm.runInContext("askContext={type:'article'}",context);
context.useCaseAiShortcut('today');
assert.equal(draft,validDraft);
context.updateCaseAiShortcutToolbar();
assert(drawerRemoved);
console.log('Shortcut scope, court records and ordinary AI isolation checks passed');

// Welcome and conversation toolbar must be mutually exclusive.
vm.runInContext("askContext={type:'case_database'}", context);
let hasMessages = false, currentDrawer = null, drawerCreations = 0;
context.document.querySelector = selector => selector === '#ask-chat-area .ask-msg' ? (hasMessages ? {} : null) : {before(element){currentDrawer=element;drawerCreations++;}};
context.document.getElementById = () => currentDrawer;
context.document.createElement = () => ({remove(){currentDrawer=null;}});
context.updateCaseAiShortcutToolbar();
assert.equal(currentDrawer,null);
hasMessages=true;
context.updateCaseAiShortcutToolbar();
assert(currentDrawer);
assert.equal(drawerCreations,1);
context.updateCaseAiShortcutToolbar();
assert.equal(drawerCreations,1);
hasMessages=false;
context.updateCaseAiShortcutToolbar();
assert.equal(currentDrawer,null);
hasMessages=true;
context.updateCaseAiShortcutToolbar();
vm.runInContext("askContext={type:'article'}", context);
context.updateCaseAiShortcutToolbar();
assert.equal(currentDrawer,null);
console.log('Empty, active and switched conversation shortcut lifecycle checks passed');

vm.runInContext(extract('buildCaseAiFocusedQuestion') + extract('getAskBaseHistoryKey'), context);
const focused = {type:'case_database',caseId:54,caseTitle:'匿名甲案件'};
assert(context.buildCaseAiFocusedQuestion('进展如何',focused).includes('案件ID：54'));
assert(context.buildCaseAiFocusedQuestion('进展如何',focused).includes('未确认匹配须说明'));
assert.equal(context.buildCaseAiFocusedQuestion('全部案件',{type:'case_database'}),'全部案件');
assert.notEqual(context.getAskBaseHistoryKey(focused),context.getAskBaseHistoryKey({type:'case_database',caseId:55}));
assert.equal(context.getAskBaseHistoryKey({type:'case_database'}),'ask_history_case_database');
assert(source.includes("requestSourceMode === 'case_database' ? buildCaseAiFocusedQuestion(question, requestContext) : question"));
assert(source.includes("tab.type === TAB_TYPES.CASE_AI && askContext?.type !== 'case_database'"));

assert(source.includes("formData.append('focus_case_id', String(Number(requestContext.caseId)))"));

const draftStart=source.indexOf('function caseAiTodoPayload(');
const draftEnd=source.indexOf('// 案件工作快捷入口：',draftStart);
vm.runInContext(source.slice(draftStart,draftEnd),context);
(async () => {
  const overlay={dataset:{mode:'todo',caseId:'54',caseTitle:'匿名甲案件'},querySelectorAll:()=>Object.values(fields).filter(item=>'disabled' in item)};
  const button={disabled:false,textContent:''};
  const fields={'case-ai-draft-title':{value:'准备证据原件',disabled:false},'case-ai-draft-date':{value:'',disabled:false},'case-ai-draft-notes':{value:'核对依据',disabled:false},'case-ai-work-overlay':overlay,'case-ai-work-save':button};
  context.document.getElementById=id=>fields[id];
  let calls=0, release;
  context.apiFetch=async (url,options)=>{calls++;assert.equal(url,'/api/case-manager/todos');const body=JSON.parse(options.body);assert.equal(body.case_id,54);assert.equal(body.remind_at,'');assert(!('status' in body));await new Promise(resolve=>{release=resolve;});};
  context.ApexCasePicker={get:()=>({close(){}})};
  context.showToast=()=>{};
  context.closeCaseAiWorkModal=()=>{};
  const payload=context.caseAiTodoPayload(overlay);
  assert.equal(payload.todo_title,'准备证据原件');
  overlay.dataset.caseId=''; assert.throws(()=>context.caseAiTodoPayload(overlay));
  await context.confirmCaseAiWork(); assert.equal(calls,0);
  overlay.dataset.caseId='54'; fields['case-ai-draft-title'].value='';
  await context.confirmCaseAiWork(); assert.equal(calls,0);
  fields['case-ai-draft-title'].value='准备证据原件';
  const first=context.confirmCaseAiWork();
  await context.confirmCaseAiWork(); assert.equal(calls,1);
  assert.equal(fields['case-ai-draft-title'].disabled,true);
  assert.equal(fields['case-ai-draft-date'].disabled,true);
  assert.equal(fields['case-ai-draft-notes'].disabled,true);
  release();await first;
  assert.equal(overlay.dataset.saving,'false');
  for (const control of overlay.querySelectorAll()) control.disabled=false;
  context.apiFetch=async ()=>{throw new Error('offline');};
  await context.confirmCaseAiWork();assert.equal(button.disabled,false);assert.equal(overlay.dataset.saving,'false');
  assert.equal(fields['case-ai-draft-title'].disabled,false);
  assert.equal(fields['case-ai-draft-date'].disabled,false);
  assert.equal(fields['case-ai-draft-notes'].disabled,false);
  // Loading must succeed before changing scope; an intervening page change wins.
  const focusStart=source.indexOf('async function setCaseAiFocus(');
  const focusEnd=source.indexOf('\nfunction closeCaseAiWorkModal',focusStart);
  vm.runInContext("var askIsLoading=false, askActiveHistoryKey='existing', askActiveHistoryBaseKey='existing'; askContext={type:'case_database',caseId:54};"+source.slice(focusStart,focusEnd),context);
  context.ensureAskHistoryLoaded=async()=>{throw new Error('offline');};
  await context.setCaseAiFocus({id:55,title:'匿名乙案件'});
  assert.equal(vm.runInContext('askContext.caseId',context),54);
  assert.equal(vm.runInContext('askActiveHistoryKey',context),'existing');
  context.ensureAskHistoryLoaded=()=>new Promise(resolve=>{release=resolve;});
  const switching=context.setCaseAiFocus({id:55,title:'匿名乙案件'});
  vm.runInContext("askContext={type:'article',id:7}",context);
  release();await switching;
  assert.equal(vm.runInContext('askContext.type',context),'article');

  context.ensureAskHistoryLoaded=async()=>{};
  context.syncAskContextToActiveTab=()=>{};context.saveTabsState=()=>{};
  context.updateAskSourceModeUI=()=>{};context.renderAskHistory=()=>{};context.renderAskHistoryIndex=()=>{};
  vm.runInContext("askContext={type:'case_database',caseId:54}",context);
  await context.setCaseAiFocus({id:55,title:'匿名乙案件'});
  assert.equal(vm.runInContext('askContext.caseId',context),55);
  assert.equal(vm.runInContext('askActiveHistoryKey',context),'');

  // Use the actual modal functions with anonymous DOM and picker fixtures.
  const modalContext=vm.createContext({
    askContext:{type:'case_database'},askIsLoading:false,
    escapeHtml:value=>value,cleanCaseAiContent:value=>value,showToast:()=>{},
    loadAskHistory:()=>[{id:'answer',role:'ai',content:'完整回答',askContext:{caseId:54,caseTitle:'匿名甲案件'}}]
  });
  let mounted=null,pickerOptions,focusCalls=0;
  const modalFields={
    'case-ai-work-search':{focus(){focusCalls++;}},
    'case-ai-work-list':{},'case-ai-work-status':{},'case-ai-work-save':{disabled:false},
    'case-ai-draft-title':{focus(){focusCalls++;}},'case-ai-draft-notes':{}
  };
  modalContext.document={
    getElementById:id=>id==='case-ai-work-overlay'?mounted:modalFields[id],
    querySelector:()=>({focus(){focusCalls++;}}),
    createElement:()=>({dataset:{},addEventListener(){},remove(){mounted=null;}}),
    body:{appendChild(element){mounted=element;}}
  };
  const picker={destroy(){},close(){},setValue(value){this.value=value;},async open(){}};
  modalContext.ApexCasePicker={get:()=>picker,attach:options=>{pickerOptions=options;return picker;}};
  const selectedNode={parentElement:{closest:()=>({dataset:{msgId:'answer'}})}};
  modalContext.window={getSelection:()=>({anchorNode:selectedNode,focusNode:selectedNode,toString:()=>focusCalls?'':'选中摘录'})};
  const modalStart=source.indexOf('function closeCaseAiWorkModal(');
  const modalEnd=source.indexOf('\nfunction caseAiTodoPayload',modalStart);
  vm.runInContext(source.slice(modalStart,modalEnd),modalContext);
  await modalContext.openCaseAiWorkModal('todo','answer');
  assert.equal(modalFields['case-ai-draft-notes'].value,'待核对的 AI 回答摘录：\n选中摘录');
  assert.equal(mounted.dataset.caseId,'54');
  pickerOptions.onInput('匿名乙');
  assert.equal(mounted.dataset.caseId,'');
  assert.equal(modalFields['case-ai-work-save'].disabled,true);
  assert.equal(picker.value,null);
  pickerOptions.onSelect({id:55,title:'匿名乙案件'});
  assert.equal(mounted.dataset.caseId,'55');
  assert.equal(modalFields['case-ai-work-save'].disabled,false);
  mounted.dataset.saving='true';
  pickerOptions.onSelect({id:54,title:'匿名甲案件'});
  modalContext.closeCaseAiWorkModal();
  assert.equal(mounted.dataset.caseId,'55');
  assert(mounted);
  console.log('Scope failure/race, selected excerpts and case re-selection regression checks passed');
  console.log('Focused history, explicit draft save, double-click and error recovery checks passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
