(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const icon = name => `<svg class="workflow-icon" aria-hidden="true"><use href="#wf-${name}"/></svg>`;
  const scrollBehavior = () => matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const state = {caseId: Number(new URLSearchParams(location.search).get('case_id') || 0), kind: 'timeline', caseTitle:'', sources: [], entries: [], draftPath: '', tasks: [], job: null, busy: false, sequence: 0, timelineSequence:0, timer: null, drafts: new Map(), reviewDirty: false, plan:null, planDirty:false, pageCounts:{}, factReference:null, activeEntry:0, exportPreviewOpen:true};
  const displayTime=value=>{const date=new Date(value);return Number.isNaN(date.getTime())?String(value||''):date.toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});};
  const statusNames = {queued:'排队中',running:'办理中',completed:'已交付',failed:'失败',cancelled:'已停止',interrupted:'已中断'};
  const resultNames = {supported:'AI初核支持',contradicted:'AI初核矛盾',not_found:'未找到出处',inference:'推断／待核'};
  const reviewNames = {pending:'待复核',confirmed:'确认初核',rejected:'否定初核',amended:'需修改'};
  let timelineGlow = null, timelineGlowHost = null, timelineGlowGeneration = 0;
  let timelineGlowStopped = Promise.resolve(), timelineCompletionTransition = null;
  async function api(url, options = {}) {
    const response = await fetch(url, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `操作失败（${response.status}）`);
    return data;
  }
  const send = (url, method, body) => api(url, {method, headers:{'Content-Type':'application/json'},body:JSON.stringify(body || {})});
  const base = (id = state.caseId) => `/api/case-workflows/cases/${id}/tasks`;
  function toast(text) { $('toast').textContent = text; $('toast').classList.add('visible'); clearTimeout(toast.timer); toast.timer = setTimeout(() => $('toast').classList.remove('visible'), 4000); }
  function busy(value) { $('agentMode').disabled=value; state.busy = value; $('submit').disabled = value || !state.caseId; $('caseSearch').disabled = value; $('caseTitleSwitch').disabled = value; $('factMode').disabled = value; $('bookMode').disabled = value;$('timelineMode').disabled=value;$('knowledgeMode').disabled=value;$('knowledgePosition').disabled=value;$('knowledgeFocus').disabled=value; $('draft').disabled=value;$('ocrConsent').disabled=value;$('savePlan').disabled=value;$('restorePlan').disabled=value;$('bookConfirmed').disabled=value;$('gapsAcknowledged').disabled=value;document.querySelectorAll('#entries input,#entries textarea,#entries button,#detail input,#detail textarea,#detail button').forEach(el=>{if(value){el.dataset.busyDisabled=String(el.disabled);el.disabled=true;}else if(el.dataset.busyDisabled!==undefined){el.disabled=el.dataset.busyDisabled==='true';delete el.dataset.busyDisabled;}});if(value)$('compileBook').disabled=true;else if(state.plan)updateLayout();syncTimelineToolbar(); }
  const picker = ApexCasePicker.attach({input:$('caseSearch'),menu:$('caseResults'),value:state.caseId,onSelect:item => selectCase(item)});
  function closeCasePicker(restoreFocus = false) {
    const open = !$('casePickerPopover').hidden;
    $('casePickerPopover').hidden = true;
    $('caseTitleSwitch').setAttribute('aria-expanded', 'false');
    picker.close();
    $('caseSearch').value = state.caseTitle;
    picker.setValue(state.caseId);
    if (open && restoreFocus) $('caseTitleSwitch').focus({preventScroll:true});
  }
  $('caseTitleSwitch').addEventListener('click', () => {
    if (!$('casePickerPopover').hidden) return closeCasePicker();
    $('casePickerPopover').hidden = false;
    $('caseTitleSwitch').setAttribute('aria-expanded', 'true');
    $('caseSearch').focus();
  });
  $('caseSearch').addEventListener('focus', () => { if (state.caseId) $('caseSearch').select(); });
  $('caseSearch').addEventListener('keydown', event => {
    if (event.key === 'Escape' && !event.defaultPrevented) {
      closeCasePicker(true);
      event.preventDefault();
    }
  });
  for (const type of ['pointerdown', 'focusin']) {
    document.addEventListener(type, event => {
      if (event.target.closest('#caseTitleSwitch,#casePickerPopover,#caseResults')) return;
      if (!$('casePickerPopover').hidden) closeCasePicker();
    });
  }
  $('knowledgePlus').addEventListener('click', () => {
    if (!state.caseId) return toast('请先选择案件');
    if (parent === window) return toast('请在 Stella 主窗口中使用知识库+');
    parent.postMessage({type:'apex:case-hub-knowledge',version:1,caseId:state.caseId,caseTitle:state.caseTitle}, location.origin);
  });
  const contextBar=document.querySelector('.case-bar');
  let titleCause = '';
  let titleFrame = 0;
  function updateCaseTitle() {
    const field = $('caseTitleName');
    if (!state.caseTitle || !field.isConnected || !field.clientWidth) return;
    field.textContent = state.caseTitle;
    if (field.scrollWidth <= field.clientWidth + 1) return;

    let parties = state.caseTitle;
    let cause = '';
    const between = parties.match(/\s*(?:之间的|间的)\s*(.+)$/);
    if (between) {
      cause = between[1].trim();
      parties = parties.slice(0, between.index);
    } else if (titleCause && parties.endsWith(titleCause)) {
      cause = titleCause;
      parties = parties.slice(0, -titleCause.length).replace(/[、，,\s]+$/, '');
    }
    const pieces = parties.split(/(\s*(?:诉|、|，|,)\s*)/);
    const count = Math.ceil(pieces.length / 2);
    if (count < 2) return;
    const space = /\s/.test(pieces[1]) ? ' ' : '';
    for (let omitted = 1; omitted <= Math.min(3, count - 1); omitted++) {
      const retained = pieces.slice(0, (count - omitted) * 2 - 1).join('').trimEnd();
      field.textContent = retained + space + '等' + cause;
      if (field.scrollWidth <= field.clientWidth + 1) return;
    }
  }
  function scheduleCaseTitle() {
    cancelAnimationFrame(titleFrame);
    titleFrame = requestAnimationFrame(updateCaseTitle);
  }
  new ResizeObserver(scheduleCaseTitle).observe(document.querySelector('.case-bar-title'));
  document.fonts?.ready.then(scheduleCaseTitle);
  const timelineLaneLabels = `
    <div class="timeline-lane lane-client"><strong>我方材料</strong></div>
    <div class="timeline-lane lane-other"><strong>对方材料</strong><small>含其他方及待确认来源</small></div>`;
  function updateContextOffset(){
    const style=getComputedStyle(contextBar);
    const offset=style.position==='sticky'?Math.ceil(contextBar.getBoundingClientRect().height+(parseFloat(style.top)||0)+16):16;
    document.documentElement.style.setProperty('--workflow-context-offset',`${offset}px`);
    requestAnimationFrame(syncTimelinePosition);
  }
  function syncTimelinePosition() {
    const active = state.kind === 'timeline' && !$('detailPanel').hidden;
    const bar = contextBar.getBoundingClientRect();
    const railHeight = active && $('detail').querySelector('.timeline-rail')?.offsetHeight;
    const bounds = active && $('detail').querySelector('.timeline-list')?.getBoundingClientRect();
    const style = document.documentElement.style;
    style.setProperty('--timeline-editor-offset', `${Math.max(8, Math.ceil(bar.bottom + 8))}px`);
    if (railHeight) style.setProperty('--timeline-index-height', `${railHeight}px`);
    if (bounds) {
      style.setProperty('--timeline-editor-left', `${Math.max(12, Math.round(bounds.left))}px`);
      style.setProperty('--timeline-editor-right', `${Math.max(12, Math.round(innerWidth - bounds.right))}px`);
      style.setProperty('--timeline-editor-lane', `${Math.max(220, Math.floor(bounds.width / 2 - 12))}px`);
    }
  }
  new ResizeObserver(updateContextOffset).observe(contextBar);
  addEventListener('resize',syncTimelinePosition,{passive:true});
  let positionFrame=0;addEventListener('scroll',()=>{if(positionFrame)return;positionFrame=requestAnimationFrame(()=>{positionFrame=0;syncTimelinePosition();});},{passive:true});
  function captureEntries() {
    $('entries').querySelectorAll('[data-entry]').forEach(el=>{const entry=state.entries[Number(el.dataset.entry)];if(!entry)return;
      el.querySelectorAll('[data-field]').forEach(input=>entry[input.dataset.field]=input.value);
      entry.claim_ids=[...el.querySelectorAll('[data-claim]:checked')].map(input=>input.dataset.claim);
      el.querySelectorAll('[data-material]').forEach(part=>{entry.materials[Number(part.dataset.material)].pages=part.querySelector('[data-pages]').value;});
    });
  }
  function selectCase(item) {
    if(state.reviewDirty||state.planDirty){closeCasePicker(true);return toast('请先保存复核意见或编排草稿，再切换案件');}
    stopTimelineGlow();
    document.body.classList.remove('timeline-progress-active');
    captureEntries();
    if (state.caseId) state.drafts.set(state.caseId, {sources:state.sources,entries:state.entries,draftPath:state.draftPath,draft:$('draft').value,knowledgePosition:$('knowledgePosition').value,knowledgeFocus:$('knowledgeFocus').value,plan:state.plan,pageCounts:state.pageCounts});
    state.factReference=null;state.activeEntry=0;state.pageCounts={};document.body.classList.remove('reviewing-plan');state.caseId = Number(item.id); state.plan=null;state.planDirty=false;$('planPanel').hidden=true;state.sequence++; state.job = null; state.reviewDirty = false;
    const saved = state.drafts.get(state.caseId) || {sources:[],entries:[],draftPath:'',draft:''};
    Object.assign(state, {sources:saved.sources,entries:saved.entries,draftPath:saved.draftPath});
    $('draft').value = saved.draft;$('knowledgePosition').value=saved.knowledgePosition||'';$('knowledgeFocus').value=saved.knowledgeFocus||''; $('bookConfirmed').checked = false; $('ocrConsent').checked = false;
    state.sourceParties={};
    state.timelineSides={};
    state.timelinePartySubjects={};
    state.timelineLocations={};
    state.locationsJob=null;
    state.caseTitle = ApexCasePicker.caseName(item);
    titleCause = String(item.case_type || '').trim();
    const titleSuffix = state.caseTitle.endsWith('案件') ? '中台' : '案件中台';
    $('caseTitleName').textContent = state.caseTitle;
    $('caseTitleSuffix').textContent = titleSuffix;
    $('caseTitleSwitch').title = `${state.caseTitle}${titleSuffix} · 切换案件`;
    $('caseTitleSwitch').setAttribute('aria-label', `${state.caseTitle}${titleSuffix}，切换案件`);
    scheduleCaseTitle();
    closeCasePicker();
    closeTimelinePopovers();
    history.replaceState(null, '', `?case_id=${state.caseId}${state.kind==='material_analysis'?'&mode=tasks':''}`);
    $('empty').hidden = true; $('work').hidden = false; $('detailPanel').hidden = true;document.body.classList.remove('reviewing-result');
    $('filePicker').classList.add('picker-loading');$('filePicker').src = `/case-files?case_id=${state.caseId}&workflow_picker=1&title=${encodeURIComponent(ApexCasePicker.caseName(item))}`;
    closePreview(); window.StellaAgentTasks.setCase(state.caseId);renderInputs();if(saved.plan){state.plan=saved.plan;state.pageCounts=saved.pageCounts||{};$('planPanel').hidden=state.kind!=='evidence_book';$('inputStage').open=state.kind!=='evidence_book';renderPlan();}if(state.kind==='timeline')activateTimeline();else refresh(); busy(false);
    if (parent !== window) parent.postMessage({type:'apex:case-workflow-case-selected',version:1,caseId:state.caseId,caseTitle:item.title || ''}, location.origin);
  }
  function setMode(kind) {
    if (kind !== 'timeline') {
      stopTimelineGlow();
      document.body.classList.remove('timeline-progress-active');
    }
    captureEntries(); state.kind = kind;state.sequence++;
    const materialMode=kind==='material_analysis';
    const consent=$('ocrConsent').closest('label');consent.hidden=kind==='timeline';if(kind==='timeline')updateTimelineVision();
    document.body.classList.toggle('timeline-mode',kind==='timeline');
    document.body.classList.toggle('fact-mode',kind==='fact_check');
    closeTimelinePopovers();
    closePreview();
    requestAnimationFrame(updateContextOffset);
    $('timelineDiscovery').hidden=true;
    if(state.job && state.job.kind!==kind) $('detailPanel').hidden=true;
    document.body.classList.toggle('material-mode',materialMode);
    document.querySelector('.history-panel').hidden=materialMode;
    $('draftOptions').open=!materialMode;
    $('draftOptions').querySelector('summary').textContent=materialMode?'粘贴补充文字（选填）':['timeline','knowledge_match'].includes(kind)?'参考文书文字（可选）':'文书内容';
    $('empty').textContent=materialMode?'先选择案件，再添加需要分析的材料。':'先选择案件，再选择起诉状、仲裁申请书、答辩状等法律文书与相关材料。';
    if(materialMode)$('sourceSection').appendChild($('draftOptions'));
    else document.querySelector('.form').insertBefore($('draftOptions'),$('sourceSection'));
    $('sourceCount').hidden=!materialMode;
    if(!materialMode)$('draft').placeholder='粘贴起诉状、仲裁申请书或答辩状的相关内容。保留分段，便于回到原文。';
    $('materialsTitle').textContent=materialMode?'案件文件':'1 · 选择文书与材料';
    $('materialsHint').textContent=materialMode?'选中文件，点击“添加到本次任务”。支持多选。':'选中文件后，点击“添加到本次任务”，选择文书或材料。支持多选材料。';
    $('formIntro').textContent=materialMode?'确认材料，写下想解决的问题，即可开始。':'左侧添加文件，或在下方粘贴文书；确认材料后开始办理。';
    $('inputStageTitle').textContent=materialMode?'选择材料与分析目标':'文书与候选材料';
    clearTimeout(state.timer);
    const params=new URLSearchParams(location.search);
    if(kind==='material_analysis')params.set('mode','tasks');else params.delete('mode');
    history.replaceState(null,'',`?${params}`);
    window.StellaAgentTasks.setActive(kind==='material_analysis');
    $('agentMode').setAttribute('aria-pressed',String(kind==='material_analysis'));
    if(kind==='material_analysis')$('detailPanel').hidden=true;
    $('timelineMode').setAttribute('aria-pressed',String(kind==='timeline'));$('knowledgeMode').setAttribute('aria-pressed',String(kind==='knowledge_match'));$('knowledgeOptions').hidden=kind!=='knowledge_match';$('analysisDisclosure').textContent=kind==='knowledge_match'?'所选案件材料及候选知识库文章片段会发送至当前配置的AI模型。仅检索现有知识库，不联网核验法条。推荐供专业复核。':'分析会将所选文书与材料内容发送至当前配置的AI模型。摘要与关联均为建议，须回看原文确认。';
    $('factMode').setAttribute('aria-pressed', String(kind === 'fact_check')); $('bookMode').setAttribute('aria-pressed', String(kind === 'evidence_book'));
    $('factForm').hidden = kind === 'evidence_book'; $('bookForm').hidden = kind !== 'evidence_book';
    $('formTitle').textContent = kind === 'fact_check' ? '待核对的法律文书' : '编排依据：定稿法律文书';
    $('submit').textContent = kind === 'fact_check' ? '开始对照核对' : '按定稿文书拟定目录';
    $('guideTitle').textContent=kind==='fact_check'?'这份文书的事实，有没有材料支持？':'定稿文书中的事实，应当用哪些证据证明？';
    $('guideText').textContent=kind==='fact_check'?'逐项对照文书与材料，列出支持、矛盾和依据缺口，供你回看原文并修改。':'先选定稿文书和候选材料，系统拟定证据摘要及对应关系；你审阅分组、证明内容和选页，再生成目录与证据册。';
    $('steps').innerHTML=(kind==='fact_check'?['选文书与材料','对照事实及原文','复核并导出／转入编排']:['选定稿文书与材料','审阅目录及文书对应','生成证据册与目录']).map(step=>`<li>${step}</li>`).join('');
    $('planPanel').hidden=kind==='fact_check'||!state.plan;
    $('inputStage').open=kind==='fact_check'||!state.plan;document.body.classList.toggle('reviewing-plan',kind==='evidence_book'&&!!state.plan);
    if(kind==='timeline'){$('inputStage').open=true;$('planPanel').hidden=true;document.body.classList.remove('reviewing-plan');$('materialsTitle').textContent='选择材料';$('materialsHint').textContent='选中文件后添加，可确认或调整来源方。';$('formTitle').textContent='确认材料来源';$('submit').textContent='启动 AI 识别并生成时间轴';$('guideTitle').textContent='发生了什么，什么时候发生，材料依据在哪里？';$('guideText').textContent='从材料提取日期、主体与事件，保留日期精度和逐字出处；同一事项的日期差异与疑似重复会并列提示。参考文书可选，不填写也能生成时间轴。';$('steps').innerHTML='<li>选择事件材料</li><li>核对日期与出处</li><li>保存、补录及导出</li>';}
    $('factForm').querySelector('p').textContent=kind==='timeline'?'输出：事件日期、主体、经过、逐字出处，以及可编辑的事实经过表和时间轴。日期不明确时保留原文。':'输出：文书事项 → 支持／矛盾／缺口 → 材料原文及位置。法律观点和请求单独标识，不显示为已证明事实。';
    $('sourceTitle').textContent=kind==='timeline'?'从中提取事件的材料':kind==='evidence_book'?'候选证据材料':'用于核对文书的依据材料';
    $('draftLabel').textContent=kind==='timeline'?'参考法律文书（可选，用于对照）':'文书内容（或在左侧选择文书文件）';
    if(kind==='knowledge_match'){$('factForm').hidden=false;$('bookForm').hidden=true;$('planPanel').hidden=true;$('inputStage').open=true;document.body.classList.remove('reviewing-plan');$('formTitle').textContent='案件文书或证据';$('draftLabel').textContent='粘贴文书（可选，也可直接添加文件）';$('sourceTitle').textContent='用于分析的案件材料';$('submit').textContent='分析关联文章';$('guideTitle').textContent='哪些知识库文章能用于这个案件？';$('guideText').textContent='分析案件事实与问题，筛选支持、不利和程序参考文章，逐篇说明用途及两侧原文依据。';$('steps').innerHTML='<li>添加文书或证据</li><li>分析问题与相关文章</li><li>核对依据并归案</li>';$('factForm').querySelector('p').textContent='输出：相关文章 → 具体用途 → 文章与案件原文 → 适用边界。只提供证据也能分析。';}else $('sourceTitle').textContent=kind==='timeline'?'用于提取事件的材料':kind==='evidence_book'?'候选证据':'用于核对文书的依据材料';
    if(kind==='material_analysis'){
      $('factForm').hidden=true;$('bookForm').hidden=true;$('planPanel').hidden=true;$('inputStage').open=true;
      document.body.classList.remove('reviewing-plan');$('formTitle').textContent='确认本次分析';
      $('formIntro').textContent='确认分析范围，再填写目标与模型。';
      $('sourceTitle').textContent='分析范围';$('draftLabel').textContent='文字内容';
      $('draft').placeholder='有需要一并分析的文字，可粘贴在这里。';
      $('submit').textContent='开始分析';$('guideTitle').textContent='从材料中找出重点与待核问题';
      $('guideText').textContent='选材料 → 开始分析 → 看重点与时间线。上方“分析记录”可找回结果。';
      $('steps').innerHTML='<li>选择材料</li><li>开始分析</li><li>核对结果</li>';
      $('analysisDisclosure').textContent='所选材料和补充文字将发送至所选模型。结果为待复核草稿，不自动写入案件事实。';
    }
    renderInputs(); sendPickerRoles(); syncTimelineToolbar();
  }
  function switchMode(kind) {
    if (state.kind === 'timeline' && state.reviewDirty) {
      if (state.kind !== kind) toast('请先保存或撤销当前事件修改');
      return;
    }
    setMode(kind);
    if (kind === 'timeline') activateTimeline();
    else refresh();
  }
  $('agentMode').onclick = () => switchMode('material_analysis');
  document.addEventListener('stella-agent-copy',event=>{
    if(event.detail.caseId!==state.caseId||state.busy)return;
    state.sources=event.detail.paths;state.draftPath='';$('draft').value=event.detail.draft;
    renderInputs();$('inputStage').open=true;$('agentGoal').focus();
  });
  $('knowledgeMode').onclick = () => switchMode('knowledge_match');
  $('timelineMode').onclick = () => switchMode('timeline');
  $('factMode').onclick = () => switchMode('fact_check');
  $('bookMode').onclick = () => switchMode('evidence_book');
  function syncFileTheme() {
    const dark = document.documentElement.classList.contains('dark-mode') || document.documentElement.dataset.theme === 'dark';
    for (const id of ['inlinePreview', 'filePicker', 'sourcePreview']) $(id).contentWindow?.postMessage({type:'theme',dark},location.origin);
  }
  $('inlinePreview').addEventListener('load',syncFileTheme);
  $('filePicker').addEventListener('load',()=>{syncFileTheme();sendPickerRoles();});
  new MutationObserver(syncFileTheme).observe(document.documentElement,{attributes:true,attributeFilter:['class','data-theme']});
  function sendPickerRoles() {
    const roles = state.kind==='material_analysis' ? [{code:'source',name:'分析这些材料',description:'固定本次分析范围 · 可多选'}] : state.kind === 'knowledge_match' ? [{code:'source',name:'分析这些材料的关联知识',description:'法律文书或证据 · 可多选，不要求另选文书'}] : state.kind === 'timeline'
      ? [{code:'source',name:'添加材料',description:'选择后可确认来源方'}]
      : state.kind === 'fact_check'
      ? [{code:'draft',name:'核对这份文书的事实',description:'起诉状、申请书、答辩状等 · 选一份'}, {code:'source',name:'用这些材料核对文书',description:'合同、付款凭证、往来记录等 · 可多选'}]
      : [{code:'draft',name:'按这份定稿文书编排',description:'定稿起诉状、申请书、答辩状等 · 选一份'}, {code:'source',name:'把这些材料列为候选证据',description:'审阅后决定编册内容与选页 · 可多选'}];
    $('filePicker').contentWindow?.postMessage({type:'apex:workflow-status',version:1,caseId:state.caseId,statuses:{},categories:roles,allowFolders:state.kind==='timeline',analyzedPaths:state.kind==='timeline'&&state.job?.kind==='timeline'&&state.job.status==='completed'?state.job.sources.map(row=>row.path):[]}, location.origin);
  }
  addEventListener('message', event => {
    if (event.origin !== location.origin || event.source !== $('filePicker').contentWindow || event.data?.version !== 1 || Number(event.data.caseId) !== state.caseId) return;
    if (event.data.type === 'apex:workflow-picker-ready') {$('filePicker').classList.remove('picker-loading');return sendPickerRoles();}
    if(event.data.type==='apex:workflow-selection'&&Array.isArray(event.data.paths)){const notice=$('timelineDuplicateNotice');const selected=event.data.paths.filter(path=>typeof path==='string');const previous=state.kind==='timeline'&&state.job?.kind==='timeline'&&state.job.status==='completed'?state.job.sources.map(row=>row.path):[];const repeated=previous.filter(path=>selected.some(item=>path===item||path.startsWith(item.replace(/\/$/,'')+'/')));notice.hidden=!repeated.length;notice.textContent=repeated.length?`已分析过 ${repeated.length} 份所选材料：${repeated.slice(0,3).map(path=>path.split('/').pop()).join('、')}${repeated.length>3?' 等':''}。再次添加时会自动跳过。`:'';return;}
    if (event.data.type !== 'apex:workflow-assign' || state.busy || !Array.isArray(event.data.paths)) return;
    const paths = [...new Set(event.data.paths.filter(path => typeof path === 'string' && !path.startsWith('Stella办案成果/')))];
    if(paths.length!==new Set(event.data.paths).size)return toast('请选择原始材料；办案成果需另存到材料目录后使用');
    captureEntries();
    if (event.data.itemCode === 'draft') {
      if (paths.length !== 1) return toast('请选择一份法律文书');
      if ($('draft').value.trim()) return toast('已有粘贴文书，请先清空后再选择文件');
      state.draftPath = paths[0];
    } else if (event.data.itemCode === 'source') {if(state.kind==='timeline'){classifyTimelineSources(paths);}else{const selected=[...new Set([...state.sources,...paths])];if(selected.length>40)return toast('一次最多40份材料，本次未加入');state.sources=selected;}}
    else return;
    $('filePicker').contentWindow.postMessage({type:'apex:workflow-clear-selection',version:1,caseId:state.caseId}, location.origin);
    renderInputs();

  });
  async function updateTimelineVision(){const consent=$('ocrConsent').closest('label');consent.hidden=true;try{const result=await api('/api/case-workflows/timeline-model-capability');if(state.kind==='timeline')consent.hidden=!!result.vision;}catch(error){if(state.kind==='timeline')consent.hidden=false;}}
  async function classifyTimelineSources(paths){const id=state.caseId;state.classifying=true;$('submit').disabled=true;try{const result=await send(`/api/case-workflows/cases/${id}/timeline-classify`,'POST',{paths});if(state.caseId!==id)return;const existing=new Set(state.job?.kind==='timeline'?state.job.sources.map(row=>row.path):[]);const duplicates=result.items.filter(row=>existing.has(row.path)||state.sources.includes(row.path));const fresh=result.items.filter(row=>!existing.has(row.path)&&!state.sources.includes(row.path));if(state.sources.length+fresh.length>40){toast('本次最多添加40份材料，请缩小范围');return;}state.sourceParties=state.sourceParties||{};for(const row of fresh){state.sources.push(row.path);state.sourceParties[row.path]=row.party;}if(duplicates.length)toast(`已跳过 ${duplicates.length} 份已添加材料`);else if(!fresh.length)toast('所选文件夹没有可识别材料');renderInputs();}catch(error){toast(error.message);}finally{if(state.caseId===id){state.classifying=false;$('submit').disabled=state.busy||!state.caseId;}}}
  function renderInputs() {
    $('sources').innerHTML = state.sources.map((path,index) => `<div class="source-row"><span title="${esc(path)}">${esc(state.kind==='material_analysis'?path.split('/').pop():path)}</span><button class="button small" type="button" data-remove-source="${index}">移出</button></div>`).join('') || `<p class="note">${state.kind==='material_analysis'?'还没有添加材料，请从文件区选择。':state.kind==='knowledge_match'?'尚未添加文件；也可在上方粘贴文书':state.kind==='timeline'?'尚未添加事件材料':state.kind==='evidence_book'?'尚未添加候选证据':'尚未添加核对依据'}</p>`;
    if(state.kind==='timeline' && state.job?.kind==='timeline' && state.job.status==='completed'){const choices=['待确认','原告方','被告方','申请人','被申请人','上诉人','被上诉人'];$('sources').innerHTML=state.sources.filter(path=>!state.job.sources.some(row=>row.path===path)).map(path=>`<div class="timeline-source-choice"><span>${esc(path.split('/').pop())}</span><details><summary class="button small">来源：${esc(state.sourceParties?.[path]||'识别中')}</summary><div class="timeline-source-menu">${choices.map(choice=>`<button type="button" class="button small" data-source-party="${esc(choice)}" data-source-path="${esc(path)}">${esc(choice)}</button>`).join('')}</div></details><button class="button small" type="button" data-remove-path="${esc(path)}">移出</button></div>`).join(''); }
    $('draftFile').textContent = state.draftPath ? `法律文书：${state.draftPath}（提交时粘贴文字优先）` : '';
    $('clearDraftFile').hidden = !state.draftPath;
    if(state.kind==='material_analysis'&&!state.sources.length)$('sources').innerHTML='<div class="analysis-empty"><div><strong>还未选择文件</strong><p>从文件区添加，或在下方粘贴补充文字。</p></div><button class="button small" type="button" data-focus-materials>选择文件</button></div>';
    updateSourceCount();
    if(state.plan)updateLayout();
  }
  function updateSourceCount(){const count=state.sources.length+(state.draftPath&&!state.sources.includes(state.draftPath)?1:0);$('sourceCount').textContent=`${count} 份文件${$('draft').value.trim()?' + 补充文字':''}`;}
  $('draft').addEventListener('input',()=>{updateSourceCount();if(state.plan)updateLayout();});
  $('sources').onclick=event=>{const party=event.target.closest('[data-source-party]');if(party){state.sourceParties=state.sourceParties||{};state.sourceParties[party.dataset.sourcePath]=party.dataset.sourceParty;renderInputs();return;}const removed=event.target.closest('[data-remove-path]');if(removed){state.sources=state.sources.filter(path=>path!==removed.dataset.removePath);renderInputs();return;}if(event.target.closest('[data-focus-materials]')){$('filePicker').scrollIntoView({block:'center'});$('filePicker').focus();return;}const button=event.target.closest('[data-remove-source]');if(button&&!state.busy){captureEntries();state.sources.splice(Number(button.dataset.removeSource),1);renderInputs();}};
  $('clearDraftFile').onclick=()=>{state.draftPath='';renderInputs();};
  function closeTimelineFilter() {
    $('timelineTopFilters').hidden = true;
    if ($('refresh').hasAttribute('aria-expanded')) $('refresh').setAttribute('aria-expanded', 'false');
  }
  $('inputStage').addEventListener('toggle',()=>{if($('inputStage').open)closeTimelineFilter();});
  addEventListener('blur',()=>{if(document.activeElement===$('filePicker'))closeTimelineFilter();});
  $('entries').addEventListener('input',()=>{markPlanDirty();updateLayout();});
  $('entries').onclick=event=>{
    const preview=event.target.closest('[data-preview-material]');if(preview){showMaterial(state.entries[Number(preview.dataset.entryIndex)].materials[Number(preview.dataset.previewMaterial)]);return;}
    const button=event.target.closest('[data-entry-action]');if(!button||state.busy)return;captureEntries();
    const index=Number(button.dataset.index),action=button.dataset.entryAction,entry=state.entries[index];
    if(action==='remove')state.entries.splice(index,1);
    else if(action==='merge'){
      const next=state.entries[index+1];if(!next)return;
      if(entry.materials.some(material=>next.materials.some(row=>row.path===material.path)))return toast('两项包含同一材料，请先调整选页，避免重复');
      const combinedSummary=[entry.summary,next.summary].filter(Boolean).join('；'),combinedPurpose=[entry.purpose,next.purpose].filter(Boolean).join('；'),combinedOrigin=next.origin&&next.origin!==entry.origin?[entry.origin,next.origin].filter(Boolean).join('；'):entry.origin;
      if(combinedSummary.length>3000||combinedPurpose.length>2000||combinedOrigin.length>600)return toast('合并后文字超过目录字段上限，请精简摘要、证明内容或来源后再合并');
      entry.materials.push(...next.materials);entry.claim_ids=[...new Set([...entry.claim_ids,...next.claim_ids])];entry.summary=[entry.summary,next.summary].filter(Boolean).join('；');entry.purpose=[entry.purpose,next.purpose].filter(Boolean).join('；');entry.summary_refs=[...(entry.summary_refs||[]),...(next.summary_refs||[])];if(next.origin&&next.origin!==entry.origin)entry.origin=[entry.origin,next.origin].filter(Boolean).join('；');state.entries.splice(index+1,1);
    }else if(action==='duplicate'){if(state.entries.length>=80)return toast('目录最多80项');const copy=structuredClone(entry);copy.title=entry.title;copy.purpose='';copy.summary='';copy.claim_ids=[];copy.warning='请调整选页，填写分项摘要和证明内容，并重新关联文书事项。';state.entries.splice(index+1,0,copy);}
    else if(action==='split'){
      if(state.entries.length+entry.materials.length-1>80)return toast('目录最多80项，请分册整理');
      const materials=entry.materials.splice(1),refs=entry.summary_refs||[];entry.summary='';entry.purpose='';entry.claim_ids=[];entry.origin='';entry.summary_refs=refs.filter(ref=>ref.path===entry.materials[0].path);entry.warning='组成材料已拆分，请重新填写摘要、证明内容并确认关联。';state.entries.splice(index+1,0,...materials.map(material=>({...structuredClone(entry),title:material.path.split('/').pop().replace(/\.[^.]+$/,''),materials:[material],summary_refs:refs.filter(ref=>ref.path===material.path)})));
    }else{const target=index+(action==='up'?-1:1);if(target>=0&&target<state.entries.length){[state.entries[index],state.entries[target]]=[state.entries[target],state.entries[index]];state.activeEntry=target;}}
    state.activeEntry=Math.min(state.activeEntry,Math.max(0,state.entries.length-1));markPlanDirty();renderEntries();updateLayout();showMaterial(state.entries[state.activeEntry]?.materials[0]);
  };
  $('submit').onclick = async () => {
    if (state.busy || !state.caseId) return;
    if(state.reviewDirty||state.planDirty)return toast('请先保存复核意见或编排草稿，再交办新任务');
    if(state.kind==='material_analysis'){
      if(!state.sources.length&&!state.draftPath&&!$('draft').value.trim())return toast('请先添加材料，或展开“粘贴补充文字”输入内容');
      const calls=Number($('agentMaxCalls').value);
      if(!Number.isInteger(calls)||calls<1||calls>120){$('agentAdvanced').open=true;$('agentMaxCalls').focus();return toast('请求上限请填写1至120之间的整数');}
      busy(true);
      try{await window.StellaAgentTasks.submit({paths:state.sources,draftPath:state.draftPath,draft:$('draft').value,ocr:$('ocrConsent').checked});}
      finally{busy(false);}
      return;
    }
    captureEntries(); const id = state.caseId;
    const reference=state.factReference;
    const referenceId=reference&&reference.draft.trim()===$('draft').value.trim()&&JSON.stringify([...reference.sources.map(row=>row.path)].sort())===JSON.stringify([...state.sources].sort())?reference.id:'';
    const payload = {reference_task_id:referenceId,knowledge_position:$('knowledgePosition').value,knowledge_focus:$('knowledgeFocus').value,kind:state.kind==='knowledge_match'?'knowledge_match':state.kind==='timeline'?'timeline':state.kind==='fact_check'?'fact_check':'evidence_plan',paths:state.sources,draft:$('draft').value,draft_path:state.draftPath,allow_cloud_ocr:$('ocrConsent').checked,entries:state.entries,confirmed:$('bookConfirmed').checked};
    if(state.kind==='timeline'){if(state.classifying)return toast('正在检查所选材料');payload.draft='';payload.draft_path='';}
    if(state.kind==='timeline' && state.job?.kind==='timeline' && state.job.status==='completed') { payload.parent_timeline_id=state.job.id; payload.parent_revision=state.job.revision;payload.paths=state.sources.filter(path=>!state.job.sources.some(row=>row.path===path));payload.source_parties=Object.fromEntries(payload.paths.filter(path=>state.sourceParties?.[path]).map(path=>[path,state.sourceParties[path]])); }
    busy(true);
    try { const job = await send(base(id),'POST',payload); if(state.caseId!==id)return; state.job=job;state.reviewDirty=false;if(job.kind==='timeline'){$('timelineDiscovery').hidden=true;$('inputStage').open=false;}renderDetail();await refresh();schedule(); }
    catch(error){toast(error.message);}finally{busy(false);}
  };
  async function activateTimeline(){
    timelineAnimationPending=true;
    if(!state.caseId || state.kind!=='timeline') return;
    const id=state.caseId, sequence=++state.timelineSequence;
    $('timelineDiscovery').hidden=false;
    $('timelineDiscovery').innerHTML='<p class="note">正在查找本案诉讼文书与时间轴…</p>';
    $('inputStage').open=false;
    try {
      const result=await send(`/api/case-workflows/cases/${id}/timeline-auto`,'POST',{});
      if(id!==state.caseId||sequence!==state.timelineSequence||state.kind!=='timeline')return;
      applyTimelineContext(result, result.job);
      if (result.job?.status === 'completed') state.locationsJob = result.job.id;
      if(result.job){
        state.job=result.job;
        const scan=result.scan||{}, count=Number(scan.unadded_count||0);
        const notice=scan.scan_incomplete?'文件数量较多，自动扫描未完成；请手动选择其他诉讼文书或证据。':count&&!result.created?`还有 ${count} 份诉讼文书未加入；时间轴一次最多包含 40 份材料。`:'';
        $('timelineDiscovery').hidden=!notice;
        if(notice){$('timelineDiscovery').innerHTML=`<p class="note">${esc(notice)}</p>`;}
        renderDetail();await refresh();
      }
      else {
        const scan=result.scan||{}, count=(scan.candidates||[]).length;
        const message=scan.scan_incomplete?'文件数量较多，自动扫描未完成。请手动选择诉讼文书或证据材料。':count>40?'找到的诉讼文书超过40份，请手动选择需要分析的文件。':'未发现可识别的诉讼文书。可以选择证据材料，按需要生成时间轴。';
        $('timelineDiscovery').innerHTML=`<h2>选择本案材料</h2><p>${esc(message)}</p><button class="button" type="button" id="chooseTimelineEvidence">选择材料</button>`;
        $('chooseTimelineEvidence').onclick=()=>{$('inputStage').open=true;$('inputStage').scrollIntoView({block:'start',behavior:'smooth'});};
      }
    } catch(error){
      if(id!==state.caseId||sequence!==state.timelineSequence)return;
      $('timelineDiscovery').innerHTML=`<h2>暂时无法生成时间轴</h2><p>${esc(error.message)}</p><button class="button" type="button" id="retryTimelineDiscovery">重试</button>`;
      $('retryTimelineDiscovery').onclick=activateTimeline;
    }
  }
  function applyTimelineContext(result, job) {
    const sides = result.party_sides || {};
    const subjects = result.party_subjects || {};
    const locations = result.job?.id === job?.id ? result.word_locations || {} : {};
    const changed = JSON.stringify([sides,subjects,locations]) !== JSON.stringify([state.timelineSides,state.timelinePartySubjects,state.timelineLocations]);
    Object.assign(state, {timelineSides:sides,timelinePartySubjects:subjects,timelineLocations:locations});
    return changed;
  }
  async function refresh() {
    if(state.kind==='material_analysis'){clearTimeout(state.timer);return window.StellaAgentTasks.refresh();}
    if (!state.caseId) return;
    const id=state.caseId,sequence=++state.sequence;
    try { const data=await api(base(id));if(sequence!==state.sequence||id!==state.caseId)return;state.tasks=data.items;renderTasks();
      if(state.job&&!state.reviewDirty){const latest=data.items.find(row=>row.id===state.job.id);if(latest){const changed=latest.kind!=='timeline'||latest.status!=='completed'||latest.status!==state.job.status||latest.revision!==state.job.revision;state.job=latest;if(changed&&(latest.kind!=='timeline'||state.kind==='timeline'))renderDetail();if(latest.kind==='evidence_plan'&&latest.status==='completed'&&state.plan?.id!==latest.id)loadPlan(latest);
        if (state.kind === 'timeline' && latest.kind === 'timeline' && latest.status === 'completed' && state.locationsJob !== latest.id) {
          state.locationsJob=latest.id;
          send(`/api/case-workflows/cases/${id}/timeline-auto`,'POST',{}).then(result => {
            if (state.caseId !== id || state.job?.id !== latest.id || state.kind !== 'timeline') return;
            if (applyTimelineContext(result,latest) && !state.reviewDirty) renderDetail();
          }).catch(() => {});
        }
      }} }
    catch(error){if(id===state.caseId)toast(error.message);}
    schedule();
  }
  function completedTimeline() {
    return state.kind === 'timeline' && state.job?.kind === 'timeline' && state.job.status === 'completed';
  }
  function closeTimelinePopovers() {
    $('timelineTopMenu').hidden = true;
    $('timelineMore').setAttribute('aria-expanded', 'false');
    $('timelineTopFilters').hidden = true;
    if ($('refresh').hasAttribute('aria-expanded')) $('refresh').setAttribute('aria-expanded', 'false');
  }
  function syncTimelineToolbar() {
    const active = state.kind === 'timeline';
    const complete = completedTimeline();
    const count = complete ? Number(timelineFilter !== 'all') + Number(!!timelineParty) + Number(!!timelineCategory) : 0;
    const refresh = $('refresh');
    $('refreshGlyph').querySelector('use').setAttribute('href', complete ? '#wf-filter' : '#wf-refresh');
    $('refreshLabel').textContent = complete ? '筛选' : '刷新记录';
    $('timelineFilterCount').textContent = count;
    $('timelineFilterCount').hidden = !count;
    if (complete) {
      refresh.setAttribute('aria-controls', 'timelineTopFilters');
      refresh.setAttribute('aria-expanded', String(!$('timelineTopFilters').hidden));
      refresh.setAttribute('aria-label', count ? `筛选，已启用 ${count} 项` : '筛选');
    } else {
      refresh.removeAttribute('aria-controls');
      refresh.removeAttribute('aria-expanded');
      refresh.removeAttribute('aria-label');
    }
    $('topTimelineExport').hidden = $('timelineMore').hidden = !active;
    $('topTimelineExport').disabled = $('timelineMore').disabled = !complete || state.busy;
    refresh.disabled = !state.caseId || state.busy;
    if (!complete) closeTimelinePopovers();
  }
  $('refresh').onclick = event => {
    if (completedTimeline()) {
      const panel = $('timelineTopFilters');
      const opening = panel.hidden;
      closeTimelinePopovers();
      panel.hidden = !opening;
      $('refresh').setAttribute('aria-expanded', String(opening));
      if (opening && event.detail === 0) panel.querySelector('[data-time-filter][aria-pressed=true]')?.focus();
      return;
    }
    window.StellaCaseKnowledge.invalidate();
    refresh();
  };
  $('timelineMore').onclick = event => {
    const menu = $('timelineTopMenu');
    const opening = menu.hidden;
    closeTimelinePopovers();
    menu.hidden = !opening;
    $('timelineMore').setAttribute('aria-expanded', String(opening));
    if (opening && event.detail === 0) $('topTimelineAdd').focus();
  };
  $('timelineTopMenu').addEventListener('keydown', event => {
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
    const buttons = [...$('timelineTopMenu').querySelectorAll('button:not(:disabled)')];
    const current = buttons.indexOf(document.activeElement);
    const step = event.key === 'ArrowDown' ? 1 : -1;
    const index = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (current + step + buttons.length) % buttons.length;
    event.preventDefault();
    buttons[index]?.focus();
  });
  for (const type of ['pointerdown','focusin']) {
    document.addEventListener(type, event => {
      if (!event.target.closest('.case-actions')) closeTimelinePopovers();
    });
  }
  $('topTimelineExport').onclick = () => {
    closeTimelinePopovers();
    const panel = $('timelineDelivery');
    if (!panel) return;
    panel.open = true;
    loadExportPreview();
    panel.querySelector('summary').focus({preventScroll:true});
    panel.scrollIntoView({behavior:scrollBehavior(),block:'start'});
  };
  $('topTimelineAdd').onclick = () => {
    closeTimelinePopovers();
    $('ocrConsent').checked = false;
    updateTimelineVision();
    state.sources = [];
    state.sourceParties = {};
    renderInputs();
    $('inputStage').open = true;
    sendPickerRoles();
    $('submit').textContent = '启动 AI 分析并添加到时间轴';
    $('inputStage').scrollIntoView({block:'start',behavior:scrollBehavior()});
  };
  $('topTimelineManual').onclick = () => {
    closeTimelinePopovers();
    if (state.reviewDirty) return toast('请先保存当前时间轴修改');
    $('manualEventForm').reset();
    $('manualEventPartyLabel').textContent = '待确认';
    $('manualEventPartyLabel').closest('details').open = false;
    $('manualEventQuoteOptions').open = false;
    setManualEventSource(null);
    $('manualEventPicker').src = `/case-files?case_id=${state.caseId}&workflow_picker=1&title=${encodeURIComponent('选择关联文件')}`;
    $('manualEventDialog').showModal();
  };
  $('topTimelineRefresh').onclick = () => {
    closeTimelinePopovers();
    $('timelineMore').focus();
    window.StellaCaseKnowledge.invalidate();
    refresh();
  };
  $('timelineTopFilters').addEventListener('click', event => handleTimeline(event));
  function schedule(){clearTimeout(state.timer);if(state.kind!=='material_analysis'&&window.ApexLifecycle?.active!==false&&document.visibilityState==='visible'&&state.tasks.some(row=>['running','queued'].includes(row.status)))state.timer=setTimeout(refresh,1500);}
  window.ApexLifecycle?.onChange(active=>{
    $('filePicker').contentWindow?.postMessage({type:'apex:workflow-visibility',version:1,caseId:state.caseId,active},location.origin);
    if (active) {
      syncTimelineGlow();
      const timeline = state.kind === 'timeline' && $('detail').querySelector('.timeline-workbench');
      if (timeline && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
        timeline.classList.remove('timeline-animate');
        void timeline.offsetWidth;
        timeline.classList.add('timeline-animate');
        timelineAnimationPending = false;
      }
      refresh();
    } else { clearTimeout(state.timer); stopTimelineGlow(); }
  });
  addEventListener('beforeunload',()=>{clearTimeout(state.timer);stopTimelineGlow();});
  function jobName(row){return {fact_check:'文书事实核对',evidence_plan:'证据编排草案',evidence_book:'证据册',timeline:'案件事实时间轴',knowledge_match:'案件关联知识'}[row.kind]||row.kind;}
  function renderTasks(){ $('tasks').innerHTML=state.tasks.map(row=>`<div class="task-row"><span>${jobName(row)} · ${esc(statusNames[row.status])}<small class="note"> ${esc(displayTime(row.created_at))} · ${row.sources.length}份材料</small></span><button class="button" type="button" data-job="${row.id}">查看</button></div>`).join('')||'<p class="note">尚未交办任务。</p>'; }
  $('tasks').onclick=event=>{const button=event.target.closest('[data-job]');if(!button||state.busy)return;if(state.reviewDirty||state.planDirty)return toast('请先保存复核意见或编排草稿，再切换任务');state.job=state.tasks.find(row=>row.id===button.dataset.job);if(state.job.kind==='knowledge_match')setMode('knowledge_match');else if(state.job.kind==='timeline')setMode('timeline');else if(state.job.kind==='fact_check')setMode('fact_check');else if(state.job.kind==='evidence_book'){$('planPanel').hidden=true;$('inputStage').open=false;}renderDetail();if(state.job.kind==='evidence_plan'&&state.job.status==='completed')loadPlan(state.job);};
  function artifactLinks(job, revision, artifacts){return artifacts.map((row,index)=>`<a href="${base()}/${job.id}/artifacts/${index}?revision=${revision}" download>${esc(row.name)}</a>`).join('');}
  function sourceLocation(ref){if(/^第\s*\d+\s*段$/.test(ref.locator))return '未取得原件页码或段落位置，请按引句查找';if(/\.docx?$/i.test(ref.path)&&/^第\s*\d+\s*页$/.test(ref.locator))return '页码依据尚未确认，请按引句查找';return ref.locator;}
  function timelineSourceLocation(ref, eventId) {
    return state.timelineLocations?.[eventId] || sourceLocation(ref);
  }
  const timelineExportStyles = {
    axis: ['纵向时间轴', '按日期顺序阅读'],
    table: ['精简对照表', '逐项比较和打印'],
    cards: ['纪事卡片', '逐条呈现事件']
  };
  function renderTimelineExport(job, visibleCount) {
    const settings = state.timelineExportDraft || job.export_options || {style:'axis',include_evidence:true};
    const preview = `${base()}/${job.id}/timeline-preview?revision=${job.revision}&style=${settings.style}&include_evidence=${settings.include_evidence}`;
    const delivered = state.timelineExportRecord?.jobId === job.id ? `<div class="timeline-export-done" role="status">${icon('check')}<span>已导出：${esc(state.timelineExportRecord.name)}</span><button id="timelineExportFolder" class="button small" type="button">查看所在文件夹</button><button id="timelineDownloadCenter" class="button small" type="button">下载中心</button></div>` : '';
    const sketch = style => `<span class="style-sketch sketch-${style}" aria-hidden="true"><span class="sketch-paper"><i></i><i></i><i></i></span></span>`;
    return `
      <div class="timeline-pdf-export">
        <span class="workflow-icon-tile">${icon('download')}</span>
        <div><h3>双侧时间轴 PDF</h3><p class="note">${visibleCount ? `当前筛选 · ${visibleCount} 项事件 · 随文保留出处与引句` : '当前筛选没有可导出的事件'}</p></div>
        <button id="exportTimelinePDF" class="button workflow-tool" type="button" ${visibleCount?'':'disabled'}>${icon('download')}导出 PDF</button>
      </div>
      ${delivered}
      <section class="timeline-export">
        <div class="timeline-export-settings">
          <h3>选择文件样式</h3>
          <div class="export-styles" role="group" aria-label="时间轴导出样式">
            ${Object.entries(timelineExportStyles).map(([key,[label,description]])=>`
              <button class="export-style" type="button" data-export-style="${key}" aria-pressed="${settings.style===key}">
                ${sketch(key)}<span class="export-style-label"><strong>${label}</strong><span class="export-style-check">${icon('check')}</span></span><small>${description}</small>
              </button>`).join('')}
          </div>
          <label class="timeline-export-option"><input id="timelineEvidence" type="checkbox" ${settings.include_evidence?'checked':''}><span><strong>附上原文依据</strong><small>随文件保留出处与引句，Word 使用尾注。</small></span></label>
          <div class="timeline-export-submit"><p class="note">PDF、SVG、Word 应用所选样式。Excel 和 Markdown 保留各自格式。<br>生成文件涵盖已保存且纳入时间轴的全部事件。</p><button id="saveTimeline" class="button primary" type="button">生成文件</button></div>
        </div>
        <details class="export-preview" ${state.exportPreviewOpen?'open':''}>
          <summary><span>${icon('document')}实际预览</span><span class="note">最多 8 项 ${icon('chevron')}</span></summary>
          <div class="export-paper" tabindex="0" aria-label="滚动查看样式预览"><img data-preview-src="${esc(preview)}" alt="已保存事件的导出排版预览"><p class="note preview-error" hidden>当前预览不可用，请确认材料和版本后重试。</p></div>
        </details>
      </section>`;
  }
  function loadExportPreview() {
    const panel = $('timelineDelivery');
    const preview = panel?.querySelector('.export-preview');
    if (!panel?.open || !preview?.open) return;
    const image = preview.querySelector('img');
    if (image.hasAttribute('src')) return;
    image.addEventListener('error', () => { image.hidden = true; image.nextElementSibling.hidden = false; }, {once:true});
    image.src = image.dataset.previewSrc;
  }
  function renderTimelineDelivery(job, visibleCount) {
    const links = (items, revision) => items.map((row,index)=>({row,index})).filter(({row})=>!row.name.endsWith('.json')).map(({row,index})=>`
      <a href="${base()}/${job.id}/artifacts/${index}?revision=${revision}" download="${esc(row.name)}" title="${esc(row.name)}" data-download-category="case" data-download-source="案件时间轴">
        <span class="file-format" data-format="${esc(row.name.split('.').pop().toUpperCase())}" aria-hidden="true"></span><span>${esc(row.name)}</span>${icon('download')}
      </a>`).join('');
    const history = (job.versions || []).filter(version => version.revision !== job.revision);
    return `<details id="timelineDelivery" class="timeline-delivery" ${state.timelineDeliveryOpen?'open':''}>
      <summary>${icon('download')}<span>导出时间轴</span>${icon('chevron')}</summary>
      ${renderTimelineExport(job, visibleCount)}
      <div class="timeline-delivery-heading"><h3>已生成文件</h3><span class="note">当前成果版本：${job.revision} · ${timelineExportStyles[job.export_options?.style || 'axis'][0]}</span></div>
      <div class="downloads">${links(job.artifacts,job.revision)}</div>
      ${history.length?`<details class="timeline-versions" ${state.timelineVersionsOpen?'open':''}><summary>${icon('chevron')}历史成果版本</summary>${history.map(version=>`<p class="note">第 ${version.revision} 版</p><div class="downloads">${links(version.artifacts,version.revision)}</div>`).join('')}</details>`: ''}
    </details>`;
  }
  function stopTimelineGlow() {
    timelineGlowGeneration++;
    if (timelineGlow) {
      const glow = timelineGlow;
      timelineGlow = null;
      timelineGlowHost = null;
      timelineGlowStopped = Promise.resolve(glow.finish()).catch(() => {});
    }
    return timelineGlowStopped;
  }
  function syncTimelineGlow() {
    const host = $('timelineProgressGlow');
    const job = state.job;
    const working = state.kind === 'timeline' && job?.kind === 'timeline'
      && ['running','queued'].includes(job.status) && !$('detailPanel').hidden
      && window.ApexLifecycle?.active !== false && document.visibilityState === 'visible';
    if (!working || !host || typeof startSummaryGenerationGlow !== 'function') {
      if (timelineGlow) stopTimelineGlow();
      return;
    }
    const label = job.status === 'queued' ? '等待任务开始…' : '正在提炼时间轴…';
    if (timelineGlow && timelineGlowHost === host) {
      timelineGlow.setStatus(label);
      return;
    }
    if (timelineGlow) stopTimelineGlow();
    const generation = ++timelineGlowGeneration;
    timelineGlowStopped.then(() => {
      if (generation !== timelineGlowGeneration || !host.isConnected || $('timelineProgressGlow') !== host
          || $('detailPanel').hidden || state.kind !== 'timeline' || state.job?.id !== job.id
          || !['running','queued'].includes(state.job?.status) || window.ApexLifecycle?.active === false
          || document.visibilityState !== 'visible') return;
      timelineGlow = startSummaryGenerationGlow(host, state.job.status === 'queued' ? '等待任务开始…' : '正在提炼时间轴…', null);
      timelineGlowHost = host;
    });
  }
  function renderTimelineProgress(job) {
    let card = $('detail').querySelector('.timeline-progress-card');
    if (!card || card.dataset.jobId !== String(job.id)) {
      stopTimelineGlow();
      $('detail').innerHTML = `<section class="timeline-progress-card" data-job-id="${esc(job.id)}" aria-labelledby="timelineProgressTitle">
        <header class="timeline-progress-header">
          <div class="timeline-progress-identity"><span class="workflow-icon-tile">${icon('document')}</span><div><p class="timeline-progress-eyebrow">案件时间轴</p><h2 id="timelineProgressTitle">案件事实时间轴</h2></div></div>
          <div class="timeline-progress-actions"><span id="timelineProgressStatus" class="timeline-progress-status"></span><button id="cancelJob" class="button" type="button">停止任务</button><button id="resumeJob" class="button" type="button">继续办理</button></div>
        </header>
        <div class="timeline-progress-main">
          <div class="timeline-progress-content">
            <div class="timeline-progress-heading"><span>当前进度</span><strong id="timelineProgressPercent"></strong></div>
            <progress id="timelineProgressBar" max="100" aria-label="时间轴提取进度"></progress>
            <div class="timeline-progress-current" role="status" aria-live="polite"><span class="timeline-progress-current-icon">${icon('document')}</span><div><span class="timeline-progress-current-label">当前办理</span><p id="timelineProgressMessage"></p><p id="timelineProgressFile" hidden></p></div></div>
          </div>
          <div id="timelineProgressGlow" class="timeline-progress-glow" aria-hidden="true"></div>
        </div>
        <div class="timeline-progress-meta"><div><strong id="timelineProgressSources"></strong><span>材料</span></div><div><strong id="timelineProgressEvents"></strong><span>已保留事件检查点</span></div><div><strong id="timelineProgressRevision"></strong><span>成果版本</span></div></div>
        <p class="timeline-progress-note">材料版本已固定；原件变化时不会继续办理或打开旧引用。</p>
        <div id="timelineProgressDownloads" class="timeline-progress-downloads" hidden></div>
        <details class="timeline-progress-steps"><summary>${icon('chevron')}<span>办理步骤</span><span id="timelineProgressStepCount"></span></summary><ol id="timelineProgressSteps"></ol></details>
      </section>`;
      card = $('detail').querySelector('.timeline-progress-card');
    }
    updateTimelineProgress(job);
    syncTimelineGlow();
  }
  function updateTimelineProgress(job, keepGlow = false) {
    const card = $('detail').querySelector('.timeline-progress-card');
    if (!card || card.dataset.jobId !== String(job.id)) return;
    const working = ['running','queued'].includes(job.status);
    card.dataset.status = job.status;
    $('timelineProgressStatus').textContent = statusNames[job.status] || job.status;
    $('cancelJob').hidden = !working;
    $('resumeJob').hidden = !['failed','cancelled','interrupted'].includes(job.status);
    $('timelineProgressGlow').hidden = !working && !keepGlow;
    const rawProgress = job.progress;
    const progress = rawProgress === null || rawProgress === undefined || rawProgress === '' ? NaN : Number(rawProgress);
    const value = Number.isFinite(progress) ? Math.max(0, Math.min(100, progress)) : null;
    $('timelineProgressPercent').textContent = value === null ? '—' : `${value}%`;
    if (value === null) $('timelineProgressBar').removeAttribute('value');
    else $('timelineProgressBar').value = value;
    const message = String(job.message || (working ? '等待任务状态更新' : '暂无办理说明'));
    const reading = message.match(/^(读取材料\s+\d+\s*\/\s*\d+)[：:]\s*([\s\S]+)$/);
    const updateText = (node, text) => { if (node.textContent !== text) node.textContent = text; };
    updateText($('timelineProgressMessage'), reading ? reading[1] : message);
    const file = $('timelineProgressFile');
    file.hidden = !reading;
    updateText(file, reading ? reading[2] : '');
    file.title = reading ? reading[2] : '';
    $('timelineProgressSources').textContent = String((job.sources || []).length);
    $('timelineProgressEvents').textContent = String((job.timeline_events || []).length);
    $('timelineProgressRevision').textContent = String(job.revision ?? '—');
    const steps = job.steps || [];
    $('timelineProgressStepCount').textContent = steps.length ? `${steps.length} 条` : '';
    const stepHtml = steps.map(step => `<li><time>${esc(displayTime(step.at))}</time><span>${esc(step.message)}</span></li>`).join('') || '<li class="note">暂无办理步骤</li>';
    if ($('timelineProgressSteps').innerHTML !== stepHtml) $('timelineProgressSteps').innerHTML = stepHtml;
    const links = artifactLinks(job, job.revision, job.artifacts || []);
    const versions = job.versions?.length > 1 ? `<details><summary>历史成果版本</summary>${job.versions.slice(0,-1).map(version=>`<p>第 ${esc(version.revision)} 版</p><div class="downloads">${artifactLinks(job,version.revision,version.artifacts || [])}</div>`).join('')}</details>` : '';
    const downloads = $('timelineProgressDownloads');
    const downloadHtml = links ? `<div class="downloads">${links}</div>${versions}` : versions;
    if (downloads.innerHTML !== downloadHtml) downloads.innerHTML = downloadHtml;
    downloads.hidden = !downloadHtml;
  }
  function renderDetail(){
    const previousDelivery = $('timelineDelivery');
    const job = state.job;
    if (!job) return;
    const existingReview = $('detail').querySelector('.timeline-editor:not([hidden])');
    const previousReviewScroll = existingReview?.querySelector('.timeline-review-body').scrollTop || 0;
    const completed = job.kind === 'timeline' && job.status === 'completed';
    if (completed && timelineCompletionTransition?.caseId === state.caseId && timelineCompletionTransition.jobId === job.id) return;
    const progressCard = $('detail').querySelector('.timeline-progress-card');
    if (completed && progressCard?.dataset.jobId === String(job.id) && timelineGlow && window.ApexLifecycle?.active !== false) {
      updateTimelineProgress(job, true);
      const transition = {caseId:state.caseId, jobId:job.id};
      timelineCompletionTransition = transition;
      stopTimelineGlow().then(() => {
        if (timelineCompletionTransition !== transition) return;
        timelineCompletionTransition = null;
        if (state.caseId === transition.caseId && state.job?.id === transition.jobId && state.job.status === 'completed' && state.kind === 'timeline') renderDetail();
      });
      return;
    }
    if (completed && timelineJob !== job.id) {
      state.timelineDeliveryOpen = false;
      state.exportPreviewOpen = true;
      state.timelineVersionsOpen = false;
      state.timelineExportDraft = null;
      closeTimelinePopovers();
    } else if (previousDelivery) {
      state.timelineDeliveryOpen = previousDelivery.open;
      state.exportPreviewOpen = previousDelivery.querySelector('.export-preview').open;
      state.timelineVersionsOpen = previousDelivery.querySelector('.timeline-versions')?.open;
    }
    $('detailPanel').hidden=false;$('detailPanel').classList.toggle('is-delivered',job.status==='completed');document.body.classList.toggle('reviewing-result',job.status==='completed');document.body.classList.toggle('timeline-progress-active',job.kind==='timeline'&&!completed&&state.kind==='timeline');if(job.status==='completed'&&$('detailPanel').dataset.deliveredJob!==job.id){$('inputStage').open=false;$('detailPanel').dataset.deliveredJob=job.id;}
    if (completed) {
      stopTimelineGlow();
      const visible = visibleTimelineEvents(job.timeline_events || []);
      $('detail').innerHTML = renderTimeline(job, visible) + renderTimelineDelivery(job, timelineFilter === 'excluded' ? 0 : visible.length);
      if (visible.length && window.ApexLifecycle?.active !== false) timelineAnimationPending = false;
      const editor = $('detail').querySelector('.timeline-editor:not([hidden])');
      if (editor && editor.dataset.reviewId === existingReview?.dataset.reviewId) editor.querySelector('.timeline-review-body').scrollTop = previousReviewScroll;
      loadExportPreview();
      syncTimelinePosition();
      requestAnimationFrame(() => window.dispatchEvent(new Event('scroll')));
    } else if (job.kind === 'timeline') renderTimelineProgress(job);
    else { stopTimelineGlow(); renderOtherJob(job); }
    syncTimelineToolbar();
    if(state.busy)$('detail').querySelectorAll('input,textarea,button').forEach(el=>{if(el.dataset.busyDisabled===undefined)el.dataset.busyDisabled=String(el.disabled);el.disabled=true;});
  }
  function renderOtherJob(job) {
    $('timelineTopFilters').replaceChildren();
    closeTimelinePopovers();
    const results=(job.results||[]).map(row=>`<tr data-result="${row.id}"><td>${row.id}</td><td class="claim"><span class="note">${esc(row.document_locator||'')} · ${esc({fact:'事实',legal:'法律观点',request:'请求',opinion:'推测'}[row.statement_type]||'事实')}</span><p>${esc(row.claim)}</p></td><td class="reason"><strong>${esc(resultNames[row.status])}</strong><p>${esc(row.reason)}</p>${row.evidence.map(ref=>`<button class="button small source-button" type="button" data-source="${esc(ref.id)}" data-result-source="${row.id}">${esc(ref.path)} · ${esc(sourceLocation(ref))}</button><div class="quote">${esc(ref.quote)}</div>`).join('')}</td><td class="review"><div class="review-actions">${Object.entries(reviewNames).map(([value,label])=>`<button class="button small" type="button" data-review="${value}" ${job.status!=='completed'||job.kind!=='fact_check'?'disabled':''} aria-pressed="${row.review_status===value}">${label}</button>`).join('')}</div><label>人工意见<textarea rows="2" maxlength="2000" data-note ${job.status!=='completed'||job.kind!=='fact_check'?'disabled':''}>${esc(row.review_note)}</textarea></label></td></tr>`).join('');
    $('detail').innerHTML=`<h2>${jobName(job)} · ${esc(statusNames[job.status])}</h2><p ${job.status==='failed'?'class="warning"':''}>${esc(job.message)}</p><progress value="${job.progress}" max="100" aria-label="办理进度"></progress><div class="downloads">${artifactLinks(job,job.revision,job.artifacts)}</div>${job.versions?.length>1?`<details><summary>历史成果版本</summary>${job.versions.slice(0,-1).map(version=>`<p>第${version.revision}版</p><div class="downloads">${artifactLinks(job,version.revision,version.artifacts)}</div>`).join('')}</details>`:''}<p class="note">材料版本已固定；原件变化时不会继续办理或打开旧引用。当前成果版本：${job.revision}</p>${['running','queued'].includes(job.status)?'<button id="cancelJob" class="button" type="button">停止任务</button>':''}${['failed','cancelled','interrupted'].includes(job.status)?'<button id="resumeJob" class="button" type="button">继续办理</button>':''}${job.kind==='fact_check'&&results?`<div class="table-wrap"><table><thead><tr><th>编号</th><th>文书事项及位置</th><th>AI初核及出处</th><th>人工复核</th></tr></thead><tbody>${results}</tbody></table></div>`:''}${job.kind==='fact_check'&&job.status==='completed'?'<div class="entry-controls"><button id="saveReview" class="button primary" type="button">保存复核并生成新版本</button><button id="useForBook" class="button" type="button">以此文书与材料编排证据</button></div>':''}<details><summary>办理步骤</summary>${job.steps.map(step=>`<p class="note">${esc(displayTime(step.at))} · ${esc(step.message)}</p>`).join('')}</details>`;
    if(job.kind==='timeline')$('detail').innerHTML+=renderTimeline(job,[]);
    if(job.kind==='knowledge_match'){
      $('detail').innerHTML+=window.StellaCaseKnowledge.render(job);
      if(job.status==='completed')window.StellaCaseKnowledge.hydrate(knowledgeContext());
    }
  }
  let timelineReviewOpen=false,timelineAnimationPending=false;
  let timelineSelection='',timelineFilter='all',timelineParty='',timelineCategory='',timelineJob='',timelineSelected=new Set();
  const timelineFilters = {all:'全部事件',unknown:'日期不确定',pending:'待复核',excluded:'已删除'};
  function visibleTimelineEvents(events) {
    if (timelineJob !== state.job.id) return events.filter(row => row.review_status !== 'excluded');
    return events.filter(row => {
      const active = row.review_status !== 'excluded';
      const status = timelineFilter === 'all' ? active : timelineFilter === 'unknown' ? active && row.date_precision === 'unknown' : row.review_status === timelineFilter;
      return status && (!timelineParty || (row.party || row.evidence?.[0]?.party || '待确认') === timelineParty)
        && (!timelineCategory || (row.category || '其他') === timelineCategory);
    });
  }
  function renderTimeline(job, visible) {
    if (timelineJob !== job.id) {
      timelineJob = job.id;
      timelineReviewOpen = false;
      timelineSelection = '';
      timelineFilter = 'all';
      timelineParty = '';
      timelineCategory = '';
      timelineSelected.clear();
      state.timelineExportDraft = null;
    }
    if (job.status !== 'completed') return `<p class="note">已保留${(job.timeline_events||[]).length}项事件检查点；提取完成后可复核和导出。</p>`;
    const events = job.timeline_events || [];
    if (!visible.some(row => row.id === timelineSelection)) {
      timelineSelection = visible[0]?.id || '';
      timelineReviewOpen = false;
    }
    const selected = visible.find(row => row.id === timelineSelection);
    const numberTokens=value=>new Set((String(value||'').replace(/(?<=\d)[,，](?=\d{3}(?:\D|$))/g,'').match(/\d+(?:\.\d+)?/g)||[]));
    const unsupportedNumbers=row=>{if(row.manual_unverified&&!row.evidence?.[0]?.quote)return false;const origin=numberTokens(row.evidence?.[0]?.quote);return [...numberTokens(row.description)].some(value=>!origin.has(value));};
    const reliableIds=new Set(events.filter(row=>row.review_status!=='excluded'&&!unsupportedNumbers(row)).map(row=>row.id));
    const safeIssues=(job.timeline_issues||[]).filter(issue=>issue.type!=='date_difference').map(issue=>({...issue,event_ids:(issue.event_ids||[]).filter(id=>reliableIds.has(id))})).filter(issue=>issue.event_ids.length>=2);
    const visibleIds = new Set(visible.map(row => row.id));
    for (const id of timelineSelected) if (!visibleIds.has(id)) timelineSelected.delete(id);
    const activeCount=events.filter(row=>row.review_status!=='excluded').length;
    const parties=[...new Set(events.map(row=>row.party||row.evidence?.[0]?.party||'待确认'))];
    const categories=[...new Set(events.map(row=>row.category||'其他'))];
    const sides=state.timelineSides||{};
    const eventSide=row=>sides[row.party||row.evidence?.[0]?.party]||'unknown';
    const duplicateGroups=safeIssues.filter(issue=>issue.type==='possible_duplicate');
    const duplicateControls=duplicateGroups.length?`<details class="timeline-duplicates"><summary>查看可能重复的记录 · ${duplicateGroups.length}组</summary><p class="note">系统按事项、主体及可用日期初步分组，可能是同一件事的不同材料，也可能是独立事件；不会自动合并。查看时显示全部来源。</p>${duplicateGroups.map((issue,index)=>`<section><strong>第 ${index+1} 组</strong>${issue.event_ids.map(id=>events.find(row=>row.id===id)).filter(Boolean).map(row=>`<button class="timeline-duplicate-item" type="button" data-duplicate-event="${esc(row.id)}"><b>${esc(row.date_text||'日期不明')}</b><span>${esc(row.description)}</span><small>${esc(row.evidence?.[0]?.path||'来源待确认')}</small><em>查看事件 ›</em></button>`).join('')}</section>`).join('')}</details>`:'';
    $('timelineTopFilters').innerHTML=`<div class="filter-heading"><strong id="timelineFiltersTitle">筛选事件</strong><button id="resetTimelineFilters" class="button small text-button" type="button" ${timelineFilter==='all'&&!timelineParty&&!timelineCategory?'disabled':''}>重置</button></div><div class="segmented timeline-filters" role="group" aria-label="事件状态">${Object.entries(timelineFilters).map(([key,label])=>`<button class="button small" type="button" data-time-filter="${key}" aria-pressed="${timelineFilter===key}">${label}</button>`).join('')}</div>
      <div class="timeline-facet" role="group" aria-label="按材料方筛选"><span>来源方</span><button class="button small" type="button" data-time-party="*" aria-pressed="${!timelineParty}">全部</button>${parties.map(party=>`<button class="button small" type="button" data-time-party="${esc(party)}" aria-pressed="${timelineParty===party}">${esc(party)}</button>`).join('')}</div>
      <div class="timeline-facet" role="group" aria-label="按事件类型筛选"><span>事件类型</span><button class="button small" type="button" data-time-category="*" aria-pressed="${!timelineCategory}">全部</button>${categories.map(category=>`<button class="button small" type="button" data-time-category="${esc(category)}" aria-pressed="${timelineCategory===category}">${esc(category)}</button>`).join('')}</div>
      ${duplicateControls}`;
    const conflicts=new Set(safeIssues.filter(issue=>issue.type==='possible_conflict').flatMap(issue=>issue.event_ids));
    const conflictIssues=row=>safeIssues.filter(issue=>issue.type==='possible_conflict'&&issue.event_ids.includes(row.id));
    const conflictDetail=row=>{const items=conflictIssues(row);if(!items.length)return '';return `<details class="timeline-comparison"><summary>查看需要对照的记录</summary>${items.map(issue=>{const peers=(issue.event_ids||[]).filter(id=>id!==row.id).map(id=>events.find(event=>event.id===id)).filter(event=>event&&event.review_status!=='excluded');const explanation=issue.type==='date_difference'?'系统将下列记录归为相同事项和主体，但日期不同；也可能是不同时间发生的独立事件，请结合内容与原文判断。':(issue.label||'不同材料的记载可能不一致，请对照原文判断。');return `<div class="timeline-comparison-group"><p>${esc(explanation)}</p>${peers.map(peer=>`<div class="timeline-comparison-peer"><strong>${esc(peer.date_text||'日期不明')} · ${esc(peer.party||peer.evidence?.[0]?.party||'来源待确认')}</strong><span>${esc(peer.description)}</span><small>${esc(peer.evidence?.[0]?.path||'来源待确认')} · ${esc(state.timelineLocations?.[peer.id]||sourceLocation(peer.evidence?.[0]||{}))}</small>${peer.evidence?.length?`<button type="button" class="button small" data-time-source="${esc(peer.id)}">查看这条记录的原文</button>`:''}</div>`).join('')||'<p>关联记录当前不可用，请刷新记录后重试。</p>'}</div>`;}).join('')}<p class="timeline-comparison-note">这只是待核对的线索，不能单凭日期不同认定事实冲突。单条事件“已确认”与关联记录是否存在差异是两项独立状态。</p></details>`;};
    const eventBadges=row=>{const parts=[];const precision={month:'精确到月',year:'精确到年',range:'时间范围'}[row.date_precision];if(precision)parts.push(`<span class="timeline-badge precision">${precision}</span>`);const status=row.review_status==='pending'?(row.requires_review===true||conflicts.has(row.id)||unsupportedNumbers(row)||row.date_precision==='unknown'?'待复核':''):({confirmed:'已确认',amended:'人工修改',excluded:'已删除'}[row.review_status]||'');if(status)parts.push(`<span class="timeline-badge status-${esc(row.review_status)}">${status}</span>`);return parts.join('');};
    const eventAlert=row=>unsupportedNumbers(row)?'数值与引文不一致':conflicts.has(row.id)?'有关联记录需对照':'';
    const grouped=[];const used=new Set();
    for(const row of visible){if(used.has(row.id))continue;used.add(row.id);const side=eventSide(row);const peer=row.sort_start&&row.sort_start===row.sort_end&&row.topic&&side!=='unknown'?visible.find(other=>!used.has(other.id)&&other.sort_start===row.sort_start&&other.sort_end===row.sort_end&&other.topic===row.topic&&eventSide(other)!=='unknown'&&eventSide(other)!==side):null;if(peer)used.add(peer.id);grouped.push(peer?[row,peer]:[row]);}
    const filterLabel = [timelineFilters[timelineFilter], timelineParty, timelineCategory].filter(Boolean).join(' · ');
    const filtered = timelineFilter !== 'all' || timelineParty || timelineCategory;
    const count = timelineFilter === 'excluded' ? `${visible.length} 项已删除` : `显示 ${visible.length} / ${activeCount} 项事件`;
    const empty = filtered ? '当前筛选没有事件' : '暂无时间轴事件';
    return `<section class="timeline-workbench ${timelineAnimationPending && window.ApexLifecycle?.active !== false && visible.length?'timeline-animate':''}" aria-label="案件事实时间轴">
      ${filtered?`<p class="timeline-filter-note note">${count} · ${esc(filterLabel)}</p>`:''}
      ${job.timeline_coverage?.conflict_warning?`<p class="timeline-coverage note">${icon('warning')}${esc(job.timeline_coverage.conflict_warning)}</p>`:''}
      <aside class="timeline-rail" aria-label="时间轴索引" ${visible.length?'':'hidden'}>
        <nav class="timeline-mini" aria-label="按日期跳转">${visible.map((row,index)=>`<button type="button" data-mini-target="${esc(row.id)}" ${index===0?'aria-current="true"':''} aria-label="跳转至 ${esc(row.date_text||'日期不明')}"><i aria-hidden="true"></i><span>${esc(row.date_text||'日期不明')}</span></button>`).join('')}</nav>
      </aside>
      <div id="timelineSelectionBar" class="timeline-selection-bar" role="toolbar" aria-label="批量操作" ${timelineSelected.size?'':'hidden'}>
        <strong id="timelineSelectionCount">已选择 ${timelineSelected.size} 项</strong><button id="clearTimelineSelection" class="button small" type="button">取消选择</button>
        <button id="restoreTimelineSelected" class="button small" type="button" ${timelineFilter==='excluded'?'':'hidden'}>恢复所选</button>
        <button id="removeTimelineSelected" class="button small" type="button" ${timelineFilter==='excluded'?'hidden':''}>移至已删除</button>
        <button id="purgeTimelineSelected" class="button small danger" type="button" ${timelineFilter==='excluded'?'':'hidden'}>彻底删除所选</button>
      </div>
      <div class="timeline-reading">
        <div class="timeline-legend" ${visible.length?'':'hidden'}>${timelineLaneLabels}</div>
        <div class="timeline-list ${visible.length?'':'is-empty'}">${grouped.map((group,index)=>`
          <div class="timeline-pair" style="--entry-index:${Math.min(index,8)}">
            ${group.map(row=>renderTimelineCard(row,eventSide(row),eventBadges(row),eventAlert(row),conflictDetail(row))).join('')}
          </div>`).join('')||`<div class="timeline-empty"><span class="workflow-icon-tile">${icon(filtered?'filter':'document')}</span><p>${empty}</p><button class="button small" id="emptyTimelineAction" type="button">${filtered?'清除筛选':'添加事件'}</button></div>`}</div>
        ${selected ? renderTimelineReview(selected,eventSide(selected),eventBadges(selected)) : ''}
        ${job.results?.length?`<details class="timeline-reference-review"><summary>${icon('chevron')}与参考法律文书对照 <span class="note">${job.results.length} 项</span></summary>${job.results.map(row=>`<article class="basis-item"><strong>${esc(row.document_locator)} · ${esc(resultNames[row.status])}</strong><p>${esc(row.claim)}</p><p>${esc(row.reason)}</p>${row.evidence.map(ref=>`<blockquote class="quote">${esc(ref.path)} · ${esc(sourceLocation(ref))}<br>${esc(ref.quote)}</blockquote>`).join('')}</article>`).join('')}</details>`:''}
      </div>
    </section>`;
  }
  function renderTimelineCard(row, side, badges, alert, comparison) {
    const ref = row.evidence?.[0];
    const id = esc(row.id);
    const path = ref?.path || '';
    const locator = ref ? timelineSourceLocation(ref, row.id) : '';
    const lane = side === 'client' ? '我方材料' : side === 'other' ? '对方材料' : '来源待确认';
    const reviewing = timelineReviewOpen && row.id === timelineSelection;
    return `<article class="timeline-entry side-${side} ${alert?'has-conflict':''}">
      <label class="timeline-select" title="选择此事件进行批量操作"><input type="checkbox" data-time-select="${id}" aria-label="选择此事件进行批量操作" ${timelineSelected.has(row.id)?'checked':''}></label>
      <button class="timeline-event" type="button" data-time-event="${id}" aria-expanded="${reviewing}" aria-controls="timelineEventReview">
        <span class="timeline-date-line"><span class="timeline-date">${esc(row.date_text||'日期不明')}</span>${badges}<span class="timeline-card-lane">${lane}</span></span>
        ${alert?`<span class="timeline-card-alert">${icon('warning')}${esc(alert)}</span>`:''}
        ${row.actors?`<strong class="timeline-actor">${esc(row.actors)}</strong>`:''}
        <span class="timeline-event-description">${esc(row.description)}</span>
        ${ref?`<span class="timeline-event-file" title="${esc(path+' · '+locator)}"><span>${esc(path.split(/[\\/]/).pop())}</span><span class="note">${esc(locator)}</span></span><span class="timeline-event-quote" hidden>${esc(ref.quote)}</span>`:''}
      </button>
      <div class="timeline-card-actions">
        ${ref?`<button class="button small text-button timeline-source-link" type="button" data-time-source="${id}">${icon(ref.source_kind==='case_folder'?'folder':'document')}${ref.source_kind==='case_folder'?'打开关联文件夹':'核对关联原文'}${icon('chevron')}</button>`:''}
        <div class="timeline-card-management">${row.review_status==='excluded'
          ? `<button class="button small text-button" type="button" data-restore-event="${id}">恢复</button><button class="button small text-button danger" type="button" data-purge-event="${id}">彻底删除</button>`
          : `<button class="button small icon-button text-button timeline-delete" type="button" data-delete-event="${id}" aria-label="移至已删除" title="移至已删除">${icon('trash')}</button>`}</div>
      </div>
      ${comparison}
    </article>`;
  }
  function renderTimelineReview(row, side, badges) {
    const ref = row.evidence?.[0];
    const path = ref?.path || '';
    const locator = ref ? timelineSourceLocation(ref, row.id) : '';
    const states = {pending:'待复核',confirmed:'确认',amended:'人工修改',excluded:'不纳入时间轴'};
    const original = row.original || row;
    const party = ref?.party || row.party;
    const subjects = state.timelinePartySubjects || {};
    const actorDefault = ref && ref.source_kind !== 'case_folder' && !row.actors && !original.actors && !row.actors_default && !row.actors_edited
      && Object.hasOwn(subjects,party) ? subjects[party] : '';
    return `<section id="timelineEventReview" class="timeline-editor ${side==='client'?'editor-opposite-right':'editor-opposite-left'}" aria-labelledby="timelineReviewTitle" data-review-id="${esc(row.id)}" ${timelineReviewOpen?'':'hidden'}>
      <header class="timeline-review-header">
        <span class="workflow-icon-tile">${icon('document')}</span>
        <div><h3 id="timelineReviewTitle">复核事件</h3><p class="note">${esc(row.date_text||'日期不明')} ${badges}</p></div>
        <button id="closeTimelineReview" class="button icon-button" type="button" aria-label="关闭复核" title="关闭">${icon('close')}</button>
      </header>
      <div class="timeline-review-body">
        <div class="timeline-review-fields">
          <div class="timeline-review-row"><label class="timeline-field-label" for="timelineReviewDate">日期原文</label><div class="timeline-field-control"><input id="timelineReviewDate" type="text" maxlength="100" data-time-field="date_text" value="${esc(row.date_text)}" placeholder="日期不明可留空" ${row.date_warning?'aria-describedby="timelineDateHint"':''}>${row.date_warning?`<small id="timelineDateHint" class="note">${esc(row.date_warning)}</small>`:''}</div></div>
          <div class="timeline-review-row"><label class="timeline-field-label" for="timelineReviewActors">主体</label><div class="timeline-field-control"><input id="timelineReviewActors" type="text" maxlength="300" data-time-field="actors" value="${esc(actorDefault || row.actors)}" placeholder="选填" ${actorDefault?'data-source-default aria-describedby="timelineActorHint"':''}>${actorDefault?'<small id="timelineActorHint" class="note">按来源方带入</small>':''}</div></div>
          <div class="timeline-review-row"><label class="timeline-field-label" for="timelineReviewDescription">事件内容</label><textarea id="timelineReviewDescription" rows="3" maxlength="1200" data-time-field="description">${esc(row.description)}</textarea></div>
          <div class="timeline-review-row"><span class="timeline-field-label" id="timelineReviewStatusLabel">复核状态</span><div class="review-actions" role="group" aria-labelledby="timelineReviewStatusLabel">${Object.entries(states).map(([key,label])=>`<button class="button small" type="button" data-time-status="${key}" aria-pressed="${row.review_status===key}">${label}</button>`).join('')}</div></div>
          <div class="timeline-review-row"><label class="timeline-field-label" for="timelineReviewNote">复核意见</label><textarea id="timelineReviewNote" rows="2" maxlength="2000" data-time-field="review_note" placeholder="修改或排除时必填">${esc(row.review_note)}</textarea></div>
        </div>
        <section class="timeline-review-row timeline-review-reference">
          <h4 class="timeline-field-label">材料与原文</h4>
          <div class="timeline-field-control">
            ${ref?`<button class="button review-document" type="button" data-time-source="${esc(row.id)}" title="${esc(path)}">${icon(ref.source_kind==='case_folder'?'folder':'document')}<span><strong>${esc(path.split(/[\\/]/).pop())}</strong><small>${esc(locator)}</small></span>${icon(ref.source_kind==='case_folder'?'external':'chevron')}</button>
            ${ref.quote?`<blockquote class="quote">${esc(ref.quote)}</blockquote>`:`<p class="note">${ref.source_kind==='case_folder'?'已关联文件夹，可打开核对。':'尚未附上原文引句。'}</p>`}`:'<p class="note">尚未关联材料。</p>'}
          </div>
        </section>
        <details class="timeline-review-original"><summary>${icon('chevron')}${row.origin==='manual'?'添加时填写':'原始提取'}</summary><p>${esc(original.date_text||'日期不明')} · ${esc(original.description)}</p></details>
      </div>
      <footer class="timeline-review-footer">
        <span id="timelineUnsaved" role="status" class="note" ${state.reviewDirty?'':'hidden'}>有未保存的修改</span>
        <button id="restoreTimeline" class="button small text-button" type="button" ${state.reviewDirty?'':'hidden'}>撤销修改</button>
        <button id="saveTimelineReview" class="button primary" type="button">保存</button>
      </footer>
    </section>`;
  }
  function timelineCard(id) {
    return [...$('detail').querySelectorAll('[data-time-event]')].find(node => node.dataset.timeEvent === id);
  }
  function highlightTimelineDate(rail, id) {
    for (const marker of rail.querySelectorAll('[data-mini-target]')) {
      if (marker.dataset.miniTarget !== id) {
        marker.removeAttribute('aria-current');
        continue;
      }
      marker.setAttribute('aria-current', 'true');
      const top = marker.offsetTop, bottom = top + marker.offsetHeight;
      if (top < rail.scrollTop) rail.scrollTop = top;
      else if (bottom > rail.scrollTop + rail.clientHeight) rail.scrollTop = bottom - rail.clientHeight;
      const left = marker.offsetLeft, right = left + marker.offsetWidth;
      if (left < rail.scrollLeft) rail.scrollLeft = left;
      else if (right > rail.scrollLeft + rail.clientWidth) rail.scrollLeft = right - rail.clientWidth;
    }
  }
  let miniScrollFrame = 0;
  addEventListener('scroll', () => {
    if (state.kind !== 'timeline' || miniScrollFrame) return;
    miniScrollFrame = requestAnimationFrame(() => {
      miniScrollFrame = 0;
      const cards = $('detail').querySelectorAll('[data-time-event]');
      if (!cards.length) return;
      const rail = $('detail').querySelector('.timeline-mini');
      const current = rail.querySelector('[aria-current=true]')?.dataset.miniTarget;
      const anchor = Math.max(contextBar.getBoundingClientRect().bottom + 60, innerHeight * .36);
      let nearest, distance = Infinity;
      for (const card of cards) {
        const next = Math.abs(card.getBoundingClientRect().top - anchor);
        if (next < distance || (next === distance && card.dataset.timeEvent === current)) {
          nearest = card;
          distance = next;
        }
      }
      highlightTimelineDate(rail, nearest.dataset.timeEvent);
    });
  }, {passive:true});
  function captureTimeline(){
    const job = state.job;
    if (job?.kind !== 'timeline') return;
    const row = job.timeline_events.find(row => row.id === timelineSelection);
    if (!row) return;
    for (const input of $('detail').querySelectorAll('[data-time-field]:not([data-source-default])')) {
      row[input.dataset.timeField] = input.value;
    }
  }
  function dismissTimelineReview(restoreFocus = false) {
    if (!timelineReviewOpen) return;
    captureTimeline();
    timelineReviewOpen = false;
    const editor = $('timelineEventReview');
    if (editor) editor.hidden = true;
    const card = timelineCard(timelineSelection);
    card?.setAttribute('aria-expanded','false');
    if (restoreFocus) card?.focus({preventScroll:true});
  }
  document.addEventListener('pointerdown', event => {
    if (!$('preview').open && !event.target.closest('.timeline-editor,.case-actions,dialog')) dismissTimelineReview();
  }, {capture:true});
  function timelineUpdates(saveSourceActor = false) {
    captureTimeline();
    const suggested = saveSourceActor && $('timelineEventReview')?.querySelector('[data-source-default]');
    return state.job.timeline_events.map(row => {
      const update = {id:row.id,date_text:row.date_text,actors:row.actors,description:row.description,status:row.review_status,note:row.review_note};
      if (row.actors_edited) update.actors_edited = true;
      if (suggested && row.id === timelineSelection) {
        update.actors = suggested.value;
        update.use_source_actor = true;
      }
      return update;
    });
  }
  function syncTimelineSelection() {
    const bar = $('timelineSelectionBar');
    if (!bar) return;
    bar.hidden = !timelineSelected.size;
    $('timelineSelectionCount').textContent = `已选择 ${timelineSelected.size} 项`;
  }
  function showTimelineDraftState(){const label=$('timelineUnsaved'),button=$('restoreTimeline');if(label)label.hidden=!state.reviewDirty;if(button)button.hidden=!state.reviewDirty;}
  let pendingTimelinePurge=null;
  function openTimelinePurge(ids){pendingTimelinePurge={caseId:state.caseId,jobId:state.job.id,revision:state.job.revision,ids};$('timelinePurgeMessage').textContent=`确定彻底删除所选 ${ids.length} 项事件吗？`;$('timelinePurgeDialog').showModal();}
  $('timelinePurgeCancel').onclick=()=>{$('timelinePurgeDialog').close();pendingTimelinePurge=null;};
  $('timelinePurgeDialog').addEventListener('close',()=>{pendingTimelinePurge=null;});
  $('timelinePurgeConfirm').onclick=async()=>{const pending=pendingTimelinePurge;if(!pending||state.busy)return;const button=$('timelinePurgeConfirm');button.disabled=true;busy(true);try{const updated=await send(`${base(pending.caseId)}/${pending.jobId}/timeline-purge`,'POST',{revision:pending.revision,event_ids:pending.ids});if(state.caseId!==pending.caseId||state.job?.id!==pending.jobId)return;state.job=updated;state.timelineExportRecord=null;state.reviewDirty=false;timelineSelected.clear();$('timelinePurgeDialog').close();renderDetail();await refresh();toast('已彻底删除所选事件');}catch(error){toast(error.message);}finally{button.disabled=false;busy(false);}};
  async function handleTimeline(event){
    if(state.job?.kind!=='timeline'||state.busy)return false;
    if(event.target.matches('[data-time-select]')){if(event.target.checked)timelineSelected.add(event.target.dataset.timeSelect);else timelineSelected.delete(event.target.dataset.timeSelect);syncTimelineSelection();return true;}
    const button = event.target.closest('[data-duplicate-event],[data-mini-target],[data-time-event],[data-time-filter],[data-time-party],[data-time-category],[data-time-status],[data-time-source],[data-delete-event],[data-restore-event],[data-purge-event],#exportTimelinePDF,#timelineExportFolder,#timelineDownloadCenter,#closeTimelineReview,#emptyTimelineAction,#resetTimelineFilters,#removeTimelineSelected,#clearTimelineSelection,#restoreTimelineSelected,#purgeTimelineSelected,#saveTimeline,#saveTimelineReview,#restoreTimeline,[data-export-style]');
    if (!button) return false;
    if (button.dataset.duplicateEvent) {
      captureTimeline();
      timelineSelected.clear();
      timelineFilter = 'all';
      timelineParty = timelineCategory = '';
      timelineSelection = button.dataset.duplicateEvent;
      timelineReviewOpen = true;
      closeTimelineFilter();
      renderDetail();
      timelineCard(timelineSelection)?.scrollIntoView({behavior:scrollBehavior(),block:'center'});
      $('closeTimelineReview')?.focus({preventScroll:true});
      return true;
    }
    if (button.dataset.miniTarget) {
      highlightTimelineDate(button.closest('.timeline-mini'), button.dataset.miniTarget);
      timelineCard(button.dataset.miniTarget)?.scrollIntoView({behavior:scrollBehavior(),block:'center'});
      return true;
    }
    if(button.id==='timelineDownloadCenter'){window.ApexDownloads?.openCenter();return true;}
    if(button.id==='timelineExportFolder'){const record=state.timelineExportRecord;if(record)try{await send(`/api/download-center/records/${encodeURIComponent(record.id)}/open`,'POST',{});}catch(error){toast(error.message);}return true;}
    if(button.id==='exportTimelinePDF'){if(state.reviewDirty){toast('请先保存时间轴修改后再导出');return true;}const job=state.job;busy(true);try{const record=await send(`${base()}/${job.id}/timeline-export-pdf`,'POST',{revision:job.revision,filter:timelineFilter,party:timelineParty,category:timelineCategory});if(state.job?.id!==job.id)return true;state.timelineExportRecord={...record,jobId:job.id};renderDetail();try{await send(`/api/download-center/records/${encodeURIComponent(record.id)}/open`,'POST',{});toast('已导出 PDF，已打开所在文件夹');}catch(error){toast('PDF 已导出，可在下载中心查看所在文件夹');}}catch(error){toast(error.message);}finally{busy(false);}return true;}
    if (button.id === 'closeTimelineReview') { dismissTimelineReview(true); return true; }
    if (button.id === 'emptyTimelineAction' && timelineFilter === 'all' && !timelineParty && !timelineCategory) {
      $('topTimelineManual').click();
      return true;
    }
    const filter = ['timeFilter','timeParty','timeCategory'].find(key => button.dataset[key]);
    if (filter || ['resetTimelineFilters','emptyTimelineAction'].includes(button.id)) {
      captureTimeline();
      timelineSelected.clear();
      if (!filter) { timelineFilter = 'all'; timelineParty = timelineCategory = ''; }
      if (filter === 'timeFilter') timelineFilter = button.dataset.timeFilter;
      if (filter === 'timeParty') timelineParty = button.dataset.timeParty === '*' ? '' : button.dataset.timeParty;
      if (filter === 'timeCategory') timelineCategory = button.dataset.timeCategory === '*' ? '' : button.dataset.timeCategory;
      const wasKeyboard = event.detail === 0;
      renderDetail();
      if (wasKeyboard) {
        const replacement = [...$('timelineTopFilters').querySelectorAll('button')].find(node => filter && node.dataset[filter] === button.dataset[filter]);
        (replacement || $('refresh')).focus({preventScroll:true});
      }
      return true;
    }
    if (button.dataset.exportStyle) {
      state.timelineExportDraft = {...(state.timelineExportDraft || state.job.export_options || {include_evidence:true}), style:button.dataset.exportStyle};
      renderDetail();
      $('detail').querySelector(`[data-export-style="${button.dataset.exportStyle}"]`)?.focus({preventScroll:true});
      return true;
    }
    if (button.dataset.timeEvent) {
      captureTimeline();
      timelineSelection = button.dataset.timeEvent;
      timelineReviewOpen = true;
      renderDetail();
      $('closeTimelineReview')?.focus({preventScroll:true});
      return true;
    }
    if (button.dataset.timeStatus) {
      captureTimeline();
      const row = state.job.timeline_events.find(row => row.id === timelineSelection);
      row.review_status = button.dataset.timeStatus;
      state.reviewDirty = true;
      renderDetail();
      $('detail').querySelector(`[data-time-status="${button.dataset.timeStatus}"]`)?.focus({preventScroll:true});
      return true;
    }
    if (button.dataset.timeSource) {
      const row = state.job.timeline_events.find(row => row.id === button.dataset.timeSource);
      if (!row?.evidence?.length) return true;
      if (row.evidence[0].source_kind === 'case_folder') {
        try { await send(`${base()}/${state.job.id}/timeline-open`, 'POST', {event_id:row.id}); }
        catch (error) { toast(error.message); }
      } else openSource(row.evidence[0], row, button);
      return true;
    }
    if(button.id==='clearTimelineSelection'){timelineSelected.clear();$('detail').querySelectorAll('[data-time-select]').forEach(input=>input.checked=false);syncTimelineSelection();return true;}
    if(button.dataset.purgeEvent||button.id==='purgeTimelineSelected'){
      if(state.reviewDirty){toast('请先保存或撤销未保存的修改');return true;}
      const ids=button.dataset.purgeEvent?[button.dataset.purgeEvent]:[...timelineSelected];
      if(ids.length)openTimelinePurge(ids);return true;
    }
    if(button.dataset.deleteEvent||button.id==='removeTimelineSelected'||button.dataset.restoreEvent||button.id==='restoreTimelineSelected'){
      if(state.reviewDirty){toast('请先保存或撤销未保存的修改');return true;}
      const restoring=!!button.dataset.restoreEvent||button.id==='restoreTimelineSelected';
      const ids=new Set(button.dataset.deleteEvent?[button.dataset.deleteEvent]:button.dataset.restoreEvent?[button.dataset.restoreEvent]:timelineSelected);
      if(!ids.size)return true;
      busy(true);
      try {
        const rows = new Map(state.job.timeline_events.map(row => [row.id,row]));
        const updates = timelineUpdates().map(update => {
          if (!ids.has(update.id)) return update;
          if (!restoring) return {...update, status:'excluded', note:update.note || '用户从时间轴移出'};
          const row = rows.get(update.id);
          const original = row.original || {};
          const changed = (update.date_text || '') !== (original.date_text || '') ||
            (update.description || '') !== (original.description || '') ||
            (update.actors || '') !== (row.actors_default || original.actors || '');
          let status = row.before_delete_status || (changed ? 'amended' : 'pending');
          if (status === 'excluded' || (changed && status !== 'amended')) status = changed ? 'amended' : 'pending';
          return {...update, status, note:row.before_delete_note || (status === 'amended' ? '恢复已修改事件' : '')};
        });
        state.job=await send(`${base()}/${state.job.id}/timeline`,'PUT',{revision:state.job.revision,events:updates,export_options:state.job.export_options});
        timelineSelected.clear();state.timelineExportRecord=null;state.reviewDirty=false;renderDetail();await refresh();toast(restoring?'已恢复所选事件':'已移至“已删除”，可恢复或彻底删除');
      }catch(error){toast(error.message);}finally{busy(false);}
      return true;
    }
    const generating = button.id === 'saveTimeline';
    if (generating && state.reviewDirty) {
      toast('请先保存或撤销事件修改，再生成文件');
      return true;
    }
    busy(true);
    try {
      if (button.id === 'restoreTimeline') {
        state.job = await api(`${base()}/${state.job.id}`);
        state.reviewDirty = false;
        renderDetail();
        toast('已撤销未保存的修改');
      } else {
        const options = generating ? state.timelineExportDraft || state.job.export_options : state.job.export_options;
        state.job = await send(`${base()}/${state.job.id}/timeline`, 'PUT', {revision:state.job.revision,events:timelineUpdates(!generating),export_options:options});
        if (generating) state.timelineExportDraft = null;
        state.timelineExportRecord = null;
        state.reviewDirty = false;
        renderDetail();
        toast(generating ? '导出文件已生成' : '时间轴已保存，导出文件已更新');
        await refresh();
      }
    } catch(error) { toast(error.message); }
    finally {
      busy(false);
      ($(button.id) || $('saveTimelineReview'))?.focus({preventScroll:true});
    }
    return true;
  }


  function setManualEventSource(source){
    const field=$('manualEventFile');delete field.dataset.path;delete field.dataset.token;
    if(source?.token)field.dataset.token=source.token;else if(source?.path)field.dataset.path=source.path;
    field.textContent=source?`已关联${source.isFolder?'文件夹':'文件'}：${source.display||source.path}`:'尚未选择关联材料';
    $('manualEventQuote').disabled=!!source?.isFolder;
    $('manualEventQuoteOptions').classList.toggle('source-folder',!!source?.isFolder);
  }
  $('manualEventClose').onclick=()=>$('manualEventDialog').close();
  $('manualEventDialog').addEventListener('click',event=>{const choice=event.target.closest('[data-manual-party]');if(!choice)return;$('manualEventParty').value=choice.dataset.manualParty;$('manualEventPartyLabel').textContent=choice.dataset.manualParty;choice.closest('details').open=false;});
  $('manualEventNative').onclick=async()=>{const job=state.job,caseId=state.caseId;if(!job||state.busy)return;const button=$('manualEventNative');button.disabled=true;try{const result=await send(`${base(caseId)}/${job.id}/timeline-select-file`,'POST',{});if(state.caseId!==caseId||state.job?.id!==job.id||!$('manualEventDialog').open)return;if(!result.cancelled)setManualEventSource({token:result.token,display:result.path||result.name});}catch(error){toast(error.message);}finally{button.disabled=false;}};
  addEventListener('message',event=>{if(event.origin!==location.origin||event.source!==$('manualEventPicker').contentWindow||event.data?.version!==1||Number(event.data.caseId)!==state.caseId)return;if(event.data.type==='apex:workflow-picker-ready'){$('manualEventPicker').contentWindow.postMessage({type:'apex:workflow-status',version:1,caseId:state.caseId,statuses:{},categories:[{code:'source',name:'关联所选材料'}],allowFolders:true,eventSource:true},location.origin);}else if(event.data.type==='apex:workflow-assign'&&Array.isArray(event.data.paths)){if(event.data.paths.length!==1)return toast('请选择一个文件或文件夹');const path=event.data.paths[0],item=event.data.items?.find(row=>row.path===path);setManualEventSource({path,isFolder:!!item?.is_directory});}});
  $('manualEventForm').onsubmit=async event=>{event.preventDefault();const file=$('manualEventFile'),path=file.dataset.path,token=file.dataset.token;if(!path&&!token)return toast('请选择一个关联文件或文件夹');if(!state.job||state.busy)return;const job=state.job,caseId=state.caseId,save=$('manualEventSave');save.disabled=true;busy(true);try{const updated=await send(`${base(caseId)}/${job.id}/timeline`,'PUT',{revision:job.revision,events:timelineUpdates(),manual_events:[{...(token?{native_token:token}:{path}),date_text:$('manualEventDate').value,actors:$('manualEventActors').value,description:$('manualEventDescription').value,party:$('manualEventParty').value,quote:$('manualEventQuote').disabled?'':$('manualEventQuote').value}],export_options:job.export_options});if(state.caseId!==caseId||state.job?.id!==job.id)return;state.job=updated;state.reviewDirty=false;$('manualEventDialog').close();renderDetail();await refresh();toast('事件已添加到时间轴');}catch(error){toast(error.message);}finally{save.disabled=false;busy(false);}};

  function captureReviews(){if(!state.job)return;document.querySelectorAll('[data-result]').forEach(el=>{const row=state.job.results.find(item=>item.id===el.dataset.result);if(row)row.review_note=el.querySelector('[data-note]').value;});}
  $('detail').addEventListener('input', event => {
    if (event.target.id === 'timelineEvidence') {
      state.timelineExportDraft = {...(state.timelineExportDraft || state.job.export_options || {style:'axis'}), include_evidence:event.target.checked};
      renderDetail();
      $('timelineEvidence')?.focus({preventScroll:true});
      return;
    }
    if (event.target.matches('[data-time-field]')) {
      const row = state.job.timeline_events.find(row => row.id === timelineSelection);
      if (event.target.dataset.timeField === 'actors') {
        delete event.target.dataset.sourceDefault;
        event.target.removeAttribute('aria-describedby');
        $('timelineActorHint')?.remove();
        row.actors_edited = true;
      }
      captureTimeline();
      if (event.target.dataset.timeField !== 'review_note') {
        row.review_status = 'amended';
        $('detail').querySelectorAll('[data-time-status]').forEach(button => button.setAttribute('aria-pressed',String(button.dataset.timeStatus==='amended')));
      }
      state.reviewDirty = true;
      showTimelineDraftState();
    }
    if (event.target.matches('[data-note]')) { state.reviewDirty = true; captureReviews(); }
  });
  function knowledgeContext(){const job=state.job,id=state.caseId;return {job,busy:state.busy,base:base(id),api,toast,openSource,render:renderDetail,current:()=>state.caseId===id&&state.job?.id===job.id,rerun:async questions=>{busy(true);try{const next=await send(base(id),'POST',{kind:'knowledge_match',paths:job.sources.map(row=>row.path),draft:job.draft,allow_cloud_ocr:job.allow_cloud_ocr,model:job.model,knowledge_position:job.knowledge_position,knowledge_focus:job.knowledge_focus,knowledge_topic_override:questions});if(state.caseId===id){state.job=next;renderDetail();await refresh();schedule();}}catch(error){if(state.caseId===id)toast(error.message);}finally{busy(false);}}};}
  $('detail').addEventListener('toggle',event=>{if(event.target.matches('.timeline-delivery,.export-preview'))loadExportPreview();if(event.target.matches('[data-knowledge-details]')&&state.job?.kind==='knowledge_match')window.StellaCaseKnowledge.showContext(event.target,knowledgeContext());},true);
  $('detail').onclick=async event=>{
    if(await window.StellaCaseKnowledge.handle(event,knowledgeContext()))return;
    if(await handleTimeline(event))return;
    const review=event.target.closest('[data-review]');if(review){if(state.job?.status!=='completed'||state.job.kind!=='fact_check')return;const tr=review.closest('[data-result]');const row=state.job.results.find(item=>item.id===tr.dataset.result);row.review_status=review.dataset.review;tr.querySelectorAll('[data-review]').forEach(button=>button.setAttribute('aria-pressed',String(button===review)));state.reviewDirty=true;return;}
    const source=event.target.closest('[data-source]');if(source){const ref=state.job.results.find(row=>row.id===source.dataset.resultSource)?.evidence.find(row=>row.id===source.dataset.source);if(ref)openSource(ref);return;}
    if(event.target.closest('#useForBook')){if(state.reviewDirty||state.planDirty)return toast('请先保存复核意见或编排草稿');state.factReference=state.job;state.sources=state.job.sources.map(row=>row.path);state.draftPath='';$('draft').value=state.job.draft;setMode('evidence_book');$('formTitle').scrollIntoView({block:'center'});return toast('已带入文书和材料；请确认这是定稿内容，再拟定目录');}
    const action=event.target.closest('#cancelJob,#resumeJob,#saveReview');if(!action||state.busy)return;
    const id=state.caseId,job=state.job;busy(true);action.disabled=true;
    try{let updated;
      if(action.id==='saveReview'){captureReviews();updated=await send(`${base(id)}/${job.id}/review`,'PUT',{revision:job.revision,reviews:job.results.map(row=>({id:row.id,status:row.review_status,note:row.review_note}))});}
      else updated=await send(`${base(id)}/${job.id}/${action.id==='cancelJob'?'cancel':'resume'}`,'POST');
      if(state.caseId===id&&state.job?.id===job.id){state.job=updated;state.reviewDirty=false;renderDetail();await refresh();}
    }catch(error){toast(error.message);}finally{busy(false);action.disabled=false;}
  };
  function loadPlan(job) {
    state.sources=job.sources.map(row=>row.path);state.draftPath='';$('draft').value=job.draft;setMode('evidence_book');
    // Clear the previous editor before layout captures inputs for the new plan.
    $('entries').textContent='';$('evidenceRail').textContent='';
    state.activeEntry=0;state.plan=job;state.planDirty=false;state.entries=structuredClone(job.plan_entries||[]);state.pageCounts={};
    renderInputs();$('planPanel').hidden=false;$('inputStage').open=false;document.body.classList.add('reviewing-plan');$('inlinePreview').removeAttribute('src');renderPlan();
    const caseId=state.caseId;
    Promise.all(job.sources.map(async row=>{try{const info=await api(`${base(caseId)}/${job.id}/material-info?path=${encodeURIComponent(row.path)}`);if(state.plan?.id===job.id&&state.caseId===caseId)state.pageCounts[row.path]=info;}catch(error){if(state.plan?.id===job.id&&state.caseId===caseId)state.pageCounts[row.path]={error:error.message};}})).then(()=>{if(state.plan?.id===job.id&&state.caseId===caseId)updateLayout();});
  }
  function showMaterial(material,page=1){if(!material||!state.plan){$('inlinePreview').removeAttribute('src');return;}$('inlinePreviewTitle').textContent=material.path;$('inlinePreview').src=`${base()}/${state.plan.id}/material-preview?path=${encodeURIComponent(material.path)}&page=${page}`;}
  $('evidenceRail').onclick=event=>{const button=event.target.closest('[data-entry-select]');if(!button||state.busy)return;captureEntries();state.activeEntry=Number(button.dataset.entrySelect);renderEntries();updateLayout();showMaterial(state.entries[state.activeEntry]?.materials[0]);};
  function pageCount(selection,total) {
    if(!selection.trim()||selection.trim()==='全部')return total;
    const pages=[];
    for(const part of selection.replaceAll('，',',').split(',')){
      const match=part.match(/^\s*(\d+)(?:\s*-\s*(\d+))?\s*$/);if(!match)throw Error('选页格式应为1-3,5');
      const first=Number(match[1]),last=Number(match[2]||match[1]);if(first<1||last<first||last>total)throw Error(`选页超出原件范围（共${total}页）`);
      for(let page=first;page<=last;page++)pages.push(page);
    }
    if(pages.some((page,index)=>index&&page<=pages[index-1]))throw Error('选页不能重复且须升序');
    return pages.length;
  }
  function markPlanDirty(){state.planDirty=true;$('bookConfirmed').checked=false;$('gapsAcknowledged').checked=false;}
  function renderPlan(){
    if(!state.plan)return;
    $('basisItems').innerHTML=state.plan.results.map(row=>`<article class="basis-item"><strong>${esc(row.document_locator||`事项${row.id}`)} · ${esc({fact:'待证事实',legal:'法律观点',request:'请求',opinion:'推测'}[row.statement_type]||'待证事实')}</strong><p>${esc(row.claim)}</p><span class="note">${esc(resultNames[row.status])} · 事项${row.id}</span></article>`).join('');
    renderEntries();updateLayout();showMaterial(state.entries[state.activeEntry]?.materials[0]);
  }
  function renderEntries(){
    $('evidenceRail').innerHTML=state.entries.map((row,index)=>`<button class="evidence-tab" type="button" data-entry-select="${index}" aria-pressed="${index===state.activeEntry}"><span class="evidence-number">${index+1}</span><span><strong data-rail-title>${esc(row.title||'未命名证据')}</strong><small data-rail-range>${row.materials.length}份材料</small></span></button>`).join('');
    $('entries').innerHTML=state.entries.map((row,index)=>index!==state.activeEntry?'':`<article class="entry" data-entry="${index}"><header><h3>证据${index+1}</h3><span class="note" data-page-range></span></header>
      <label>证据名称<input data-field="title" type="text" maxlength="200" value="${esc(row.title)}"></label>
      <label>证据摘要 · 材料写了什么<textarea data-field="summary" rows="3" maxlength="3000">${esc(row.summary)}</textarea></label>
      <label>证明内容 · 用它证明什么<textarea data-field="purpose" rows="3" maxlength="2000">${esc(row.purpose)}</textarea></label>
      <div class="entry-meta"><label>证据来源（选填）<input data-field="origin" type="text" maxlength="600" value="${esc(row.origin)}" placeholder="如：当事人提供、银行调取"></label><label>分组（选填）<input data-field="group" type="text" maxlength="200" value="${esc(row.group)}" placeholder="如：借贷关系、履行情况"></label></div>
      <fieldset class="claim-links"><legend>对应文书事项（可多选）</legend>${state.plan.results.map(claim=>`<label class="claim-link"><input type="checkbox" data-claim="${claim.id}" ${(row.claim_ids||[]).includes(claim.id)?'checked':''}><span>${claim.id} · ${esc(claim.claim)}</span></label>`).join('')}</fieldset>
      <h3>组成材料与原件选页</h3>${row.materials.map((material,mi)=>`<div class="material-part" data-material="${mi}"><button class="button small" type="button" data-preview-material="${mi}" data-entry-index="${index}">${esc(material.path)}</button><label>选页<input data-pages type="text" maxlength="2000" value="${esc(material.pages)}" placeholder="全部，或1-3,5"><small class="note">${esc(state.pageCounts[material.path]?.page_basis||'按原件物理页码；Word按转换后PDF页码')}</small></label></div>`).join('')}
      ${row.coverage_note?`<p class="note">${esc(row.coverage_note)}</p>`:''}${row.warning?`<p class="warning">${esc(row.warning)}</p>`:''}
      ${(row.summary_refs||[]).map(ref=>`<p class="quote">原始建议的参考引句：${esc(ref.path)} · ${esc(sourceLocation(ref))}<br>${esc(ref.quote)}</p>`).join('')}
      <div class="entry-controls"><button class="button small" type="button" data-entry-action="up" data-index="${index}" ${index===0?'disabled':''}>上移</button><button class="button small" type="button" data-entry-action="down" data-index="${index}" ${index===state.entries.length-1?'disabled':''}>下移</button><button class="button small" type="button" data-entry-action="merge" data-index="${index}" ${index===state.entries.length-1?'disabled':''}>合并下一项</button><button class="button small" type="button" data-entry-action="duplicate" data-index="${index}">复制为分项／选页拆分</button><button class="button small" type="button" data-entry-action="split" data-index="${index}" ${row.materials.length<2?'disabled':''}>拆分材料</button><button class="button small" type="button" data-entry-action="remove" data-index="${index}">移出目录</button></div></article>`).join('')||'<p class="note">目录为空，重新载入草稿可恢复已保存的条目。</p>';
    if(state.busy)$('entries').querySelectorAll('input,textarea,button').forEach(el=>{el.dataset.busyDisabled=String(el.disabled);el.disabled=true;});
  }
  function updateLayout(){
    if(!state.plan)return;
    captureEntries();let next=1,valid=true;
    state.entries.forEach((entry,index)=>{let count=0,message='';
      try{entry.materials.forEach(material=>{const info=state.pageCounts[material.path];if(!info)throw Error('读取原件页数中…');if(info.error)throw Error(info.error);count+=pageCount(material.pages,info.pages);});message=`第${next}—${next+count-1}页 · ${count}页`;next+=count;}
      catch(error){valid=false;message=error.message;}
      const rail=$('evidenceRail').querySelector(`[data-entry-select="${index}"]`);if(rail){rail.querySelector('[data-rail-range]').textContent=message;rail.querySelector('[data-rail-title]').textContent=entry.title||'未命名证据';}
      const active=$('entries').querySelector(`[data-entry="${index}"] [data-page-range]`);if(active)active.textContent=message;
    });
    const linked=new Set(state.entries.flatMap(row=>row.claim_ids));
    const gaps=state.plan.results.filter(row=>{if(['legal','request'].includes(row.statement_type))return false;if(!linked.has(row.id)||row.status!=='supported'||['rejected','amended'].includes(row.review_status))return true;return !row.evidence.length||!row.evidence.every(ref=>state.entries.some(entry=>entry.claim_ids.includes(row.id)&&entry.materials.some(material=>{if(material.path!==ref.path)return false;if(!material.pages.trim()||material.pages.trim()==='全部')return true;const match=ref.locator.match(/第\s*(\d+)\s*页/);if(!match)return false;return material.pages.replaceAll('，',',').split(',').some(part=>{const range=part.match(/^\s*(\d+)(?:\s*-\s*(\d+))?\s*$/);return range&&Number(match[1])>=Number(range[1])&&Number(match[1])<=Number(range[2]||range[1]);});})));});
    $('planGaps').innerHTML=gaps.map(row=>`<article class="basis-item warning"><strong>事项${row.id} · ${esc(resultNames[row.status])}</strong><p>${esc(row.claim)}</p><p class="note">${linked.has(row.id)?'请核查矛盾、证明范围及选页是否包含引用原文：'+esc(row.reason):'尚未关联编册证据'}</p></article>`).join('')||'<p class="note">当前未见未关联事项；仍须核对证明范围和选页是否覆盖引用原文。</p>';
    $('gapConsent').hidden=!gaps.length;
    if(state.draftPath||$('draft').value.trim()!==state.plan.draft.trim()||JSON.stringify([...state.sources].sort())!==JSON.stringify(state.plan.sources.map(row=>row.path).sort())){valid=false;$('pageTotal').textContent='文书或候选材料已变化，请重新拟定目录。当前草稿仍对应左侧所列原文书事项。';$('compileBook').disabled=true;return;}
    $('pageTotal').textContent=valid?`预计编册${next-1}页 · 目录独立，不计入页码；增删、重排、选页后自动同步。`:'请先处理选页或材料读取问题，页码未确认。';
    $('compileBook').disabled=state.busy||!valid||!state.entries.length;
  }
  $('restorePlan').onclick=async()=>{if(state.busy||!state.plan)return;busy(true);try{const job=await api(`${base()}/${state.plan.id}`);loadPlan(job);toast('已载入最后保存的编排草稿');}catch(error){toast(error.message);}finally{busy(false);updateLayout();}};
  $('savePlan').onclick=async()=>{
    if(state.busy||!state.plan)return;captureEntries();busy(true);
    try{const job=await send(`${base()}/${state.plan.id}/plan`,'PUT',{revision:state.plan.revision,entries:state.entries});state.plan=job;state.entries=structuredClone(job.plan_entries);state.planDirty=false;renderEntries();toast('编排草稿已保存，可从办理记录继续编辑');await refresh();}catch(error){toast(error.message);}finally{busy(false);updateLayout();}
  };
  $('compileBook').onclick=async()=>{
    if(state.busy||!state.plan)return;captureEntries();
    if(!$('bookConfirmed').checked)return toast('请先确认已审阅编排内容');
    if(!$('gapConsent').hidden&&!$('gapsAcknowledged').checked)return toast('请审阅依据缺口及矛盾后确认');
    busy(true);
    try{if(state.planDirty){const saved=await send(`${base()}/${state.plan.id}/plan`,'PUT',{revision:state.plan.revision,entries:state.entries});state.plan=saved;state.planDirty=false;}const job=await send(base(),'POST',{kind:'evidence_book',plan_id:state.plan.id,plan_revision:state.plan.revision,paths:state.plan.sources.map(row=>row.path),entries:state.entries,confirmed:true,gaps_acknowledged:$('gapsAcknowledged').checked});state.job=job;state.planDirty=false;renderDetail();await refresh();schedule();}catch(error){toast(error.message);}finally{busy(false);updateLayout();}
  };
  let previewFocus = null;
  function openSource(ref, timelineEvent = null, trigger = document.activeElement) {
    const preview = $('preview'), frame = $('sourcePreview');
    previewFocus = trigger;
    const path = ref.path || '';
    const locationLabel = timelineEvent ? timelineSourceLocation(ref, timelineEvent.id) : sourceLocation(ref);
    $('previewPath').textContent = path;
    $('previewPath').title = path;
    $('previewLocator').textContent = locationLabel || '尚未定位原文';
    $('previewQuote').textContent = ref.quote || '尚未附上原文引句。';
    $('previewEvent').hidden = !timelineEvent;
    $('previewEventDate').textContent = timelineEvent?.date_text || '日期不明';
    $('previewEventText').textContent = timelineEvent?.description || '';
    const page = ref.locator?.match(/第\s*(\d+)\s*页/)?.[1];
    const endpoint = `${base()}/${state.job.id}`;
    const link = $('sourceLink');
    if (timelineEvent) {
      link.dataset.timelineEvent = timelineEvent.id;
      link.href = '#';
      $('sourceLinkLabel').textContent = '用默认应用打开原件';
    } else {
      delete link.dataset.timelineEvent;
      link.href = `${endpoint}/source?source_id=${encodeURIComponent(ref.id)}${page?'#page='+page:''}`;
      $('sourceLinkLabel').textContent = '在新窗口打开原件';
    }
    const supported = /\.(pdf|docx?|png|jpe?g)$/i.test(path);
    frame.hidden = !supported;
    $('sourcePreviewEmpty').hidden = supported;
    $('sourcePreviewEmpty').querySelector('p').textContent = '此格式可在原件中查看';
    preview.classList.toggle('source-dialog-text', !supported);
    if (supported) {
      const event = timelineEvent ? `&event_id=${encodeURIComponent(timelineEvent.id)}` : '';
      frame.src = `${endpoint}/material-preview?path=${encodeURIComponent(path)}&page=${page||1}${event}`;
    } else frame.removeAttribute('src');
    if (!preview.open) preview.showModal();
  }
  function closePreview() { if ($('preview').open) $('preview').close(); }
  $('closePreview').onclick = closePreview;
  $('preview').addEventListener('click', event => { if (event.target === $('preview')) closePreview(); });
  $('preview').addEventListener('close', () => {
    $('sourcePreview').removeAttribute('src');
    if (previewFocus?.isConnected) previewFocus.focus({preventScroll:true});
    previewFocus = null;
  });
  $('sourcePreview').addEventListener('load', () => {
    const frame = $('sourcePreview');
    const doc = frame.contentDocument;
    syncFileTheme();
    if ($('preview').open && !frame.hidden && doc?.URL !== 'about:blank' && !doc?.querySelector('#pageViewer,#textViewer')) {
      frame.hidden = true;
      $('sourcePreviewEmpty').hidden = false;
      $('sourcePreviewEmpty').querySelector('p').textContent = '预览读取失败，请检查材料后重试';
    }
    const wordLocation = doc?.getElementById('textSummary')?.dataset.location;
    if ($('preview').open && wordLocation && $('sourceLink').dataset.timelineEvent) {
      $('previewLocator').textContent = wordLocation;
    }
    doc?.addEventListener('keydown', event => {
      if (event.key === 'Escape' && $('preview').open) {
        event.preventDefault();
        closePreview();
      }
    });
  });
  $('sourceLink').onclick = async event => {
    const eventId = $('sourceLink').dataset.timelineEvent;
    if (!eventId) return;
    event.preventDefault();
    try { await send(`${base()}/${state.job.id}/timeline-open`,'POST',{event_id:eventId}); }
    catch(error) { toast(error.message); }
  };
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || event.defaultPrevented || document.querySelector('dialog[open]')) return;
    if (!$('timelineTopFilters').hidden || !$('timelineTopMenu').hidden) {
      const trigger = $('timelineTopFilters').hidden ? $('timelineMore') : $('refresh');
      closeTimelinePopovers();
      trigger.focus();
      event.preventDefault();
    } else if (timelineReviewOpen) {
      dismissTimelineReview(true);
      event.preventDefault();
    }
  });
  setMode(new URLSearchParams(location.search).get('mode')==='tasks'?'material_analysis':'timeline');
  busy(false);
  if(state.caseId){api(`/api/case-workflows/cases/${state.caseId}`).then(item=>selectCase(item)).catch(error=>{toast(error.message);busy(false);});}
})();
