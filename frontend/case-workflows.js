(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const state = {caseId: Number(new URLSearchParams(location.search).get('case_id') || 0), kind: 'fact_check', caseTitle:'', sources: [], entries: [], draftPath: '', tasks: [], job: null, busy: false, sequence: 0, timer: null, drafts: new Map(), reviewDirty: false, plan:null, planDirty:false, pageCounts:{}, factReference:null, activeEntry:0};
  const displayTime=value=>{const date=new Date(value);return Number.isNaN(date.getTime())?String(value||''):date.toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});};
  const statusNames = {queued:'排队中',running:'办理中',completed:'已交付',failed:'失败',cancelled:'已停止',interrupted:'已中断'};
  const resultNames = {supported:'AI初核支持',contradicted:'AI初核矛盾',not_found:'未找到出处',inference:'推断／待核'};
  const reviewNames = {pending:'待复核',confirmed:'确认初核',rejected:'否定初核',amended:'需修改'};
  async function api(url, options = {}) {
    const response = await fetch(url, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `操作失败（${response.status}）`);
    return data;
  }
  const send = (url, method, body) => api(url, {method, headers:{'Content-Type':'application/json'},body:JSON.stringify(body || {})});
  const base = (id = state.caseId) => `/api/case-workflows/cases/${id}/tasks`;
  function toast(text) { $('toast').textContent = text; $('toast').classList.add('visible'); clearTimeout(toast.timer); toast.timer = setTimeout(() => $('toast').classList.remove('visible'), 4000); }
  function busy(value) { $('agentMode').disabled=value; state.busy = value; $('submit').disabled = value || !state.caseId; $('caseSearch').disabled = value; $('factMode').disabled = value; $('bookMode').disabled = value;$('timelineMode').disabled=value;$('knowledgeMode').disabled=value;$('knowledgePosition').disabled=value;$('knowledgeFocus').disabled=value; $('draft').disabled=value;$('ocrConsent').disabled=value;$('savePlan').disabled=value;$('restorePlan').disabled=value;$('bookConfirmed').disabled=value;$('gapsAcknowledged').disabled=value;document.querySelectorAll('#entries input,#entries textarea,#entries button,#detail input,#detail textarea,#detail button').forEach(el=>{if(value){el.dataset.busyDisabled=String(el.disabled);el.disabled=true;}else if(el.dataset.busyDisabled!==undefined){el.disabled=el.dataset.busyDisabled==='true';delete el.dataset.busyDisabled;}});if(value)$('compileBook').disabled=true;else if(state.plan)updateLayout(); }
  const picker = ApexCasePicker.attach({input:$('caseSearch'),menu:$('caseResults'),value:state.caseId,onSelect:item => selectCase(item)});
  function captureEntries() {
    $('entries').querySelectorAll('[data-entry]').forEach(el=>{const entry=state.entries[Number(el.dataset.entry)];if(!entry)return;
      el.querySelectorAll('[data-field]').forEach(input=>entry[input.dataset.field]=input.value);
      entry.claim_ids=[...el.querySelectorAll('[data-claim]:checked')].map(input=>input.dataset.claim);
      el.querySelectorAll('[data-material]').forEach(part=>{entry.materials[Number(part.dataset.material)].pages=part.querySelector('[data-pages]').value;});
    });
  }
  function selectCase(item) {
    if(state.reviewDirty||state.planDirty){$('caseSearch').value=state.caseTitle;picker.setValue(state.caseId);return toast('请先保存复核意见或编排草稿，再切换案件');}
    captureEntries();
    if (state.caseId) state.drafts.set(state.caseId, {sources:state.sources,entries:state.entries,draftPath:state.draftPath,draft:$('draft').value,knowledgePosition:$('knowledgePosition').value,knowledgeFocus:$('knowledgeFocus').value,plan:state.plan,pageCounts:state.pageCounts});
    state.factReference=null;state.activeEntry=0;state.pageCounts={};document.body.classList.remove('reviewing-plan');state.caseId = Number(item.id); state.plan=null;state.planDirty=false;$('planPanel').hidden=true;state.sequence++; state.job = null; state.reviewDirty = false;
    const saved = state.drafts.get(state.caseId) || {sources:[],entries:[],draftPath:'',draft:''};
    Object.assign(state, {sources:saved.sources,entries:saved.entries,draftPath:saved.draftPath});
    $('draft').value = saved.draft;$('knowledgePosition').value=saved.knowledgePosition||'';$('knowledgeFocus').value=saved.knowledgeFocus||''; $('bookConfirmed').checked = false; $('ocrConsent').checked = false;
    state.caseTitle=ApexCasePicker.caseName(item); $('caseSearch').value = state.caseTitle; picker.setValue(state.caseId);
    history.replaceState(null, '', `?case_id=${state.caseId}${state.kind==='material_analysis'?'&mode=tasks':''}`);
    $('empty').hidden = true; $('work').hidden = false; $('detailPanel').hidden = true;document.body.classList.remove('reviewing-result');
    $('filePicker').src = `/case-files?case_id=${state.caseId}&workflow_picker=1&title=${encodeURIComponent(ApexCasePicker.caseName(item))}`;
    closePreview(); window.StellaAgentTasks.setCase(state.caseId);renderInputs();if(saved.plan){state.plan=saved.plan;state.pageCounts=saved.pageCounts||{};$('planPanel').hidden=state.kind!=='evidence_book';$('inputStage').open=state.kind!=='evidence_book';renderPlan();}refresh(); busy(false);
    if (parent !== window) parent.postMessage({type:'apex:case-workflow-case-selected',version:1,caseId:state.caseId,caseTitle:item.title || ''}, location.origin);
  }
  function setMode(kind) {
    captureEntries(); state.kind = kind;
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
    if(kind==='timeline'){$('inputStage').open=true;$('planPanel').hidden=true;document.body.classList.remove('reviewing-plan');$('formTitle').textContent='事件材料与参考文书';$('submit').textContent='提取事件并生成时间轴';$('guideTitle').textContent='发生了什么，什么时候发生，材料依据在哪里？';$('guideText').textContent='从材料提取日期、主体与事件，保留日期精度和逐字出处；同一事项的日期差异与疑似重复会并列提示。参考文书可选，不填写也能生成时间轴。';$('steps').innerHTML='<li>选择事件材料</li><li>核对日期与出处</li><li>保存、补录及导出</li>';}
    $('factForm').querySelector('p').textContent=kind==='timeline'?'输出：事件日期、主体、经过、逐字出处，以及可编辑的事实经过表和时间轴。日期不明确时保留原文。':'输出：文书事项 → 支持／矛盾／缺口 → 材料原文及位置。法律观点和请求单独标识，不显示为已证明事实。';
    $('sourceTitle').textContent=kind==='timeline'?'从中提取事件的材料':kind==='evidence_book'?'候选证据材料':'用于核对文书的依据材料';
    $('draftLabel').textContent=kind==='timeline'?'参考法律文书（可选，用于对照）':'文书内容（或在左侧选择文书文件）';
    if(kind==='knowledge_match'){$('factForm').hidden=false;$('bookForm').hidden=true;$('planPanel').hidden=true;$('inputStage').open=true;document.body.classList.remove('reviewing-plan');$('formTitle').textContent='案件文书或证据';$('draftLabel').textContent='粘贴文书（可选，也可直接添加文件）';$('sourceTitle').textContent='用于分析的案件材料';$('submit').textContent='分析关联文章';$('guideTitle').textContent='哪些知识库文章能用于这个案件？';$('guideText').textContent='分析案件事实与问题，筛选支持、不利和程序参考文章，逐篇说明用途及两侧原文依据。';$('steps').innerHTML='<li>添加文书或证据</li><li>分析问题与相关文章</li><li>核对依据并归案</li>';$('factForm').querySelector('p').textContent='输出：相关文章 → 具体用途 → 文章与案件原文 → 适用边界。只提供证据也能分析。';}else $('sourceTitle').textContent=kind==='timeline'?'用于提取事件的材料':kind==='evidence_book'?'候选证据':'用于核对文书的依据材料';
    if(kind==='material_analysis'){
      $('factForm').hidden=true;$('bookForm').hidden=true;$('planPanel').hidden=true;$('inputStage').open=true;
      document.body.classList.remove('reviewing-plan');$('formTitle').textContent='材料分析任务';
      $('sourceTitle').textContent='本次授权分析的材料';$('draftLabel').textContent='参考文书文字（可选，用于逐项初核）';
      $('submit').textContent='交办材料分析任务';$('guideTitle').textContent='把材料整理成可追溯、可继续的分析草稿';
      $('guideText').textContent='依次清点材料、提取时间线、分析事项与缺口，并保存进度。离开页面仍可办理；服务重启后请核对并继续。';
      $('steps').innerHTML='<li>固定材料与目标</li><li>时间线与来源分析</li><li>复核草稿及缺口</li>';
      $('analysisDisclosure').textContent='所选材料及参考文字将发送至下方选择的模型；请求上限包含重试。引句存在不等于事实已证明，成果均待专业复核。';
    }
    renderInputs(); sendPickerRoles();
  }
  $('agentMode').onclick=()=>setMode('material_analysis');
  document.addEventListener('stella-agent-copy',event=>{
    if(event.detail.caseId!==state.caseId||state.busy)return;
    state.sources=event.detail.paths;state.draftPath='';$('draft').value=event.detail.draft;
    renderInputs();$('inputStage').open=true;$('agentGoal').focus();
  });
  $('knowledgeMode').onclick=()=>setMode('knowledge_match');
  $('timelineMode').onclick=()=>setMode('timeline');
  $('factMode').onclick = () => setMode('fact_check'); $('bookMode').onclick = () => setMode('evidence_book');
  function syncFileTheme(){ $('inlinePreview').contentWindow?.postMessage({type:'theme',dark:document.documentElement.classList.contains('dark-mode')||document.documentElement.dataset.theme==='dark'},location.origin);$('filePicker').contentWindow?.postMessage({type:'theme',dark:document.documentElement.classList.contains('dark-mode')||document.documentElement.dataset.theme==='dark'},location.origin); }
  $('inlinePreview').addEventListener('load',syncFileTheme);
  $('filePicker').addEventListener('load',()=>{syncFileTheme();sendPickerRoles();});
  new MutationObserver(syncFileTheme).observe(document.documentElement,{attributes:true,attributeFilter:['class','data-theme']});
  function sendPickerRoles() {
    const roles = state.kind==='material_analysis' ? [{code:'source',name:'分析这些材料',description:'固定本次分析范围 · 可多选'}] : state.kind === 'knowledge_match' ? [{code:'source',name:'分析这些材料的关联知识',description:'法律文书或证据 · 可多选，不要求另选文书'}] : state.kind === 'timeline'
      ? [{code:'source',name:'从这些材料提取事件',description:'合同、往来记录、裁判文书等 · 可多选'}, {code:'draft',name:'用这份文书作对照',description:'起诉状、答辩状等 · 选一份，可不添加'}]
      : state.kind === 'fact_check'
      ? [{code:'draft',name:'核对这份文书的事实',description:'起诉状、申请书、答辩状等 · 选一份'}, {code:'source',name:'用这些材料核对文书',description:'合同、付款凭证、往来记录等 · 可多选'}]
      : [{code:'draft',name:'按这份定稿文书编排',description:'定稿起诉状、申请书、答辩状等 · 选一份'}, {code:'source',name:'把这些材料列为候选证据',description:'审阅后决定编册内容与选页 · 可多选'}];
    $('filePicker').contentWindow?.postMessage({type:'apex:workflow-status',version:1,caseId:state.caseId,statuses:{},categories:roles}, location.origin);
  }
  addEventListener('message', event => {
    if (event.origin !== location.origin || event.source !== $('filePicker').contentWindow || event.data?.version !== 1 || Number(event.data.caseId) !== state.caseId) return;
    if (event.data.type === 'apex:workflow-picker-ready') return sendPickerRoles();
    if (event.data.type !== 'apex:workflow-assign' || state.busy || !Array.isArray(event.data.paths)) return;
    const paths = [...new Set(event.data.paths.filter(path => typeof path === 'string' && !path.startsWith('Stella办案成果/')))];
    if(paths.length!==new Set(event.data.paths).size)return toast('请选择原始材料；办案成果需另存到材料目录后使用');
    captureEntries();
    if (event.data.itemCode === 'draft') {
      if (paths.length !== 1) return toast('请选择一份法律文书');
      if ($('draft').value.trim()) return toast('已有粘贴文书，请先清空后再选择文件');
      state.draftPath = paths[0];
    } else if (event.data.itemCode === 'source') {const selected=[...new Set([...state.sources,...paths])];if(selected.length>40)return toast('一次最多40份材料，本次未加入');state.sources=selected;}
    else return;
    $('filePicker').contentWindow.postMessage({type:'apex:workflow-clear-selection',version:1,caseId:state.caseId}, location.origin);
    renderInputs();
  });
  function renderInputs() {
    $('sources').innerHTML = state.sources.map((path,index) => `<div class="source-row"><span>${esc(path)}</span><button class="button small" type="button" data-remove-source="${index}">移出</button></div>`).join('') || `<p class="note">${state.kind==='knowledge_match'?'尚未添加文件；也可在上方粘贴文书':state.kind==='timeline'?'尚未添加事件材料':state.kind==='evidence_book'?'尚未添加候选证据':'尚未添加核对依据'}</p>`;
    $('draftFile').textContent = state.draftPath ? `法律文书：${state.draftPath}（提交时粘贴文字优先）` : '';
    $('clearDraftFile').hidden = !state.draftPath;
    if(state.plan)updateLayout();
  }
  $('draft').addEventListener('input',()=>{if(state.plan)updateLayout();});
  $('sources').onclick=event=>{const button=event.target.closest('[data-remove-source]');if(button&&!state.busy){captureEntries();state.sources.splice(Number(button.dataset.removeSource),1);renderInputs();}};
  $('clearDraftFile').onclick=()=>{state.draftPath='';renderInputs();};
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
      busy(true);
      try{await window.StellaAgentTasks.submit({paths:state.sources,draftPath:state.draftPath,draft:$('draft').value,ocr:$('ocrConsent').checked});}
      finally{busy(false);}
      return;
    }
    captureEntries(); const id = state.caseId;
    const reference=state.factReference;
    const referenceId=reference&&reference.draft.trim()===$('draft').value.trim()&&JSON.stringify([...reference.sources.map(row=>row.path)].sort())===JSON.stringify([...state.sources].sort())?reference.id:'';
    const payload = {reference_task_id:referenceId,knowledge_position:$('knowledgePosition').value,knowledge_focus:$('knowledgeFocus').value,kind:state.kind==='knowledge_match'?'knowledge_match':state.kind==='timeline'?'timeline':state.kind==='fact_check'?'fact_check':'evidence_plan',paths:state.sources,draft:$('draft').value,draft_path:state.draftPath,allow_cloud_ocr:$('ocrConsent').checked,entries:state.entries,confirmed:$('bookConfirmed').checked};
    busy(true);
    try { const job = await send(base(id),'POST',payload); if(state.caseId!==id)return; state.job=job;state.reviewDirty=false;renderDetail();await refresh();schedule(); }
    catch(error){toast(error.message);}finally{busy(false);}
  };
  async function refresh() {
    if(state.kind==='material_analysis')window.StellaAgentTasks.refresh();
    if (!state.caseId) return;
    const id=state.caseId,sequence=++state.sequence;
    try { const data=await api(base(id));if(sequence!==state.sequence||id!==state.caseId)return;state.tasks=data.items;renderTasks();
      if(state.job&&!state.reviewDirty){const latest=data.items.find(row=>row.id===state.job.id);if(latest){state.job=latest;renderDetail();if(latest.kind==='evidence_plan'&&latest.status==='completed'&&state.plan?.id!==latest.id)loadPlan(latest);}} }
    catch(error){if(id===state.caseId)toast(error.message);}
    schedule();
  }
  $('refresh').onclick=()=>{window.StellaCaseKnowledge.invalidate();refresh();};
  function schedule(){clearTimeout(state.timer);if(window.ApexLifecycle?.active!==false&&document.visibilityState==='visible'&&state.tasks.some(row=>['running','queued'].includes(row.status)))state.timer=setTimeout(refresh,1500);}
  window.ApexLifecycle?.onChange(active=>{ $('filePicker').contentWindow?.postMessage({type:'apex:workflow-visibility',version:1,caseId:state.caseId,active},location.origin); if(active)refresh();else clearTimeout(state.timer);});
  addEventListener('beforeunload',()=>clearTimeout(state.timer));
  function jobName(row){return {fact_check:'文书事实核对',evidence_plan:'证据编排草案',evidence_book:'证据册',timeline:'案件事实时间轴',knowledge_match:'案件关联知识'}[row.kind]||row.kind;}
  function renderTasks(){ $('tasks').innerHTML=state.tasks.map(row=>`<div class="task-row"><span>${jobName(row)} · ${esc(statusNames[row.status])}<small class="note"> ${esc(displayTime(row.created_at))} · ${row.sources.length}份材料</small></span><button class="button" type="button" data-job="${row.id}">查看</button></div>`).join('')||'<p class="note">尚未交办任务。</p>'; }
  $('tasks').onclick=event=>{const button=event.target.closest('[data-job]');if(!button||state.busy)return;if(state.reviewDirty||state.planDirty)return toast('请先保存复核意见或编排草稿，再切换任务');state.job=state.tasks.find(row=>row.id===button.dataset.job);if(state.job.kind==='knowledge_match')setMode('knowledge_match');else if(state.job.kind==='timeline')setMode('timeline');else if(state.job.kind==='fact_check')setMode('fact_check');else if(state.job.kind==='evidence_book'){$('planPanel').hidden=true;$('inputStage').open=false;}renderDetail();if(state.job.kind==='evidence_plan'&&state.job.status==='completed')loadPlan(state.job);};
  function artifactLinks(job, revision, artifacts){return artifacts.map((row,index)=>`<a href="${base()}/${job.id}/artifacts/${index}?revision=${revision}" download>${esc(row.name)}</a>`).join('');}
  function sourceLocation(ref){if(/^第\s*\d+\s*段$/.test(ref.locator))return '未取得原件页码或段落位置，请按引句查找';if(/\.docx?$/i.test(ref.path)&&/^第\s*\d+\s*页$/.test(ref.locator))return '页码依据尚未确认，请按引句查找';return ref.locator;}
  function renderTimelineExport(job){
    if(job.kind!=='timeline'||job.status!=='completed')return '';
    const settings=job.export_options||{style:'axis',include_evidence:true};
    const styles={axis:['纵向时间轴','沿时间线阅读事实经过'],table:['精简对照表','适合逐项比较与打印'],cards:['纪事卡片','突出每个事件的日期与内容']};
    const preview=`${base()}/${job.id}/timeline-preview?revision=${job.revision}&style=${settings.style}&include_evidence=${settings.include_evidence}`;
    return `<section class="timeline-export"><header><div><h3>导出样式</h3><p class="note">布局应用于 Word、PDF、SVG；Excel 保持事实表。复核状态保留在工作台。</p></div><button id="saveTimeline" class="button primary" type="button">按此样式生成导出</button></header><div class="export-styles" role="group" aria-label="时间轴导出样式">${Object.entries(styles).map(([key,value])=>`<button class="export-style" type="button" data-export-style="${key}" aria-pressed="${settings.style===key}"><span class="style-sketch sketch-${key}" aria-hidden="true"><i></i><i></i><i></i></span><strong>${value[0]}</strong><small>${value[1]}</small></button>`).join('')}</div><label class="consent"><input id="timelineEvidence" type="checkbox" ${settings.include_evidence?'checked':''}>显示原文依据（正文上标引用，Word文末尾注）</label><p class="note">隐藏时不显示引用编号及原文依据；核验底稿仍保留完整记录。预览基于当前已保存事件，复核修改保存后同步。</p><details class="export-preview" ${state.exportPreviewOpen?'open':''}><summary>查看所选样式的实际预览 · 前8项</summary><div class="export-paper"><img src="${preview}" alt="所选时间轴样式的已保存事件预览" loading="lazy"><p class="note preview-error" hidden>预览暂不可用，请检查材料与版本后重新载入。</p></div></details></section><p class="note">下载当前已保存版本 · 样式调整后请先生成新版</p>`;
  }
  function renderDetail(){
    state.exportPreviewOpen=$('detail').querySelector('.export-preview')?.open||false;
    const job=state.job;if(!job)return;$('detailPanel').hidden=false;$('detailPanel').classList.toggle('is-delivered',job.status==='completed');document.body.classList.toggle('reviewing-result',job.status==='completed');if(job.status==='completed'&&$('detailPanel').dataset.deliveredJob!==job.id){$('inputStage').open=false;$('detailPanel').dataset.deliveredJob=job.id;}
    const results=(job.results||[]).map(row=>`<tr data-result="${row.id}"><td>${row.id}</td><td class="claim"><span class="note">${esc(row.document_locator||'')} · ${esc({fact:'事实',legal:'法律观点',request:'请求',opinion:'推测'}[row.statement_type]||'事实')}</span><p>${esc(row.claim)}</p></td><td class="reason"><strong>${esc(resultNames[row.status])}</strong><p>${esc(row.reason)}</p>${row.evidence.map(ref=>`<button class="button small source-button" type="button" data-source="${esc(ref.id)}" data-result-source="${row.id}">${esc(ref.path)} · ${esc(sourceLocation(ref))}</button><div class="quote">${esc(ref.quote)}</div>`).join('')}</td><td class="review"><div class="review-actions">${Object.entries(reviewNames).map(([value,label])=>`<button class="button small" type="button" data-review="${value}" ${job.status!=='completed'||job.kind!=='fact_check'?'disabled':''} aria-pressed="${row.review_status===value}">${label}</button>`).join('')}</div><label>人工意见<textarea rows="2" maxlength="2000" data-note ${job.status!=='completed'||job.kind!=='fact_check'?'disabled':''}>${esc(row.review_note)}</textarea></label></td></tr>`).join('');
    $('detail').innerHTML=`<h2>${jobName(job)} · ${esc(statusNames[job.status])}</h2><p ${job.status==='failed'?'class="warning"':''}>${esc(job.message)}</p><progress value="${job.progress}" max="100" aria-label="办理进度"></progress>${renderTimelineExport(job)}<div class="downloads">${artifactLinks(job,job.revision,job.artifacts)}</div>${job.versions?.length>1?`<details><summary>历史成果版本</summary>${job.versions.slice(0,-1).map(version=>`<p>第${version.revision}版</p><div class="downloads">${artifactLinks(job,version.revision,version.artifacts)}</div>`).join('')}</details>`:''}<p class="note">材料版本已固定；原件变化时不会继续办理或打开旧引用。当前成果版本：${job.revision}</p>${['running','queued'].includes(job.status)?'<button id="cancelJob" class="button" type="button">停止任务</button>':''}${['failed','cancelled','interrupted'].includes(job.status)?'<button id="resumeJob" class="button" type="button">继续办理</button>':''}${job.kind==='fact_check'&&results?`<div class="table-wrap"><table><thead><tr><th>编号</th><th>文书事项及位置</th><th>AI初核及出处</th><th>人工复核</th></tr></thead><tbody>${results}</tbody></table></div>`:''}${job.kind==='fact_check'&&job.status==='completed'?'<div class="entry-controls"><button id="saveReview" class="button primary" type="button">保存复核并生成新版本</button><button id="useForBook" class="button" type="button">以此文书与材料编排证据</button></div>':''}<details><summary>办理步骤</summary>${job.steps.map(step=>`<p class="note">${esc(displayTime(step.at))} · ${esc(step.message)}</p>`).join('')}</details>`;
    if(job.kind==='timeline')$('detail').innerHTML+=renderTimeline(job);
    if(job.kind==='knowledge_match'){
      $('detail').innerHTML+=window.StellaCaseKnowledge.render(job);
      if(job.status==='completed')window.StellaCaseKnowledge.hydrate(knowledgeContext());
    }
    const image=$('detail').querySelector('.export-paper img');if(image)image.onerror=()=>{image.hidden=true;image.nextElementSibling.hidden=false;};
    if(state.busy)$('detail').querySelectorAll('input,textarea,button').forEach(el=>{el.dataset.busyDisabled=String(el.disabled);el.disabled=true;});
  }
  let timelineSelection='',timelineFilter='all',timelineJob='',manualFragments=[],manualDirty=false;
  function renderTimeline(job){
    if(timelineJob!==job.id){timelineJob=job.id;timelineSelection='';timelineFilter='all';manualFragments=[];manualDirty=false;}
    if(job.status!=='completed')return `<p class="note">已保留${(job.timeline_events||[]).length}项事件检查点；提取完成后可复核和导出。</p>`;
    const events=job.timeline_events||[];if(!events.some(row=>row.id===timelineSelection))timelineSelection=events[0]?.id||'';
    let selected=events.find(row=>row.id===timelineSelection);
    const filters={all:'全部事件',unknown:'日期不确定',pending:'待复核',excluded:'已排除'};
    const visible=events.filter(row=>timelineFilter==='all'||(timelineFilter==='unknown'?row.date_precision==='unknown':row.review_status===timelineFilter));
    if(!visible.some(row=>row.id===timelineSelection)){timelineSelection=visible[0]?.id||'';selected=visible[0];}
    return `<section class="timeline-workbench"><header><div><h2>案件事实时间轴</h2><p class="note">逐片段处理${job.timeline_coverage?.processed_chunks||0}个片段，${events.length}项事件；${job.timeline_coverage?.rejected_unverifiable||0}项无有效引句未采用。事件间距不表示时长，年月及相对日期不补成确定日期。</p></div><div class="entry-controls"><button id="restoreTimeline" class="button" type="button">放弃修改，载入保存版本</button></div></header>
      <div class="segmented timeline-filters">${Object.entries(filters).map(([key,label])=>`<button class="button" type="button" data-time-filter="${key}" aria-pressed="${timelineFilter===key}">${label}</button>`).join('')}</div>
      ${(job.timeline_issues||[]).map(issue=>`<p class="timeline-warning">${esc(issue.label)} · ${issue.event_ids.length}条记录（仅为待核对候选）</p>`).join('')}
      <div class="timeline-grid"><div class="timeline-list">${visible.map(row=>`<button class="timeline-event" type="button" data-time-event="${row.id}" aria-pressed="${row.id===timelineSelection}"><span class="timeline-date">${esc(row.date_text||'日期不明')}<small>${esc({day:'到日',month:'到月',year:'到年',range:'期间',unknown:'不参与先后排序'}[row.date_precision])} · ${esc({pending:'待复核',confirmed:'已确认',amended:'人工修改',excluded:'已排除'}[row.review_status])}</small></span><strong>${esc(row.actors)}</strong><p>${esc(row.description)}</p><small>${esc(row.evidence[0].path)} · ${esc(sourceLocation(row.evidence[0]))}</small></button>`).join('')||'<p class="note">当前筛选没有事件。提取遗漏可以在下方按原文补录。</p>'}</div>
      <div class="timeline-editor">${selected?`<h3>复核当前事件</h3><label>日期原文／人工修订<input type="text" maxlength="100" data-time-field="date_text" value="${esc(selected.date_text)}" placeholder="日期不明可以留空；保存后重新排序"></label><p class="note">${esc(selected.date_warning)}</p><label>主体<input type="text" maxlength="300" data-time-field="actors" value="${esc(selected.actors)}"></label><label>事件内容<textarea rows="4" maxlength="1200" data-time-field="description">${esc(selected.description)}</textarea></label><div class="review-actions">${Object.entries({pending:'待复核',confirmed:'确认',amended:'人工修改',excluded:'不纳入时间轴'}).map(([key,label])=>`<button class="button small" type="button" data-time-status="${key}" aria-pressed="${selected.review_status===key}">${label}</button>`).join('')}</div><label>复核意见<textarea rows="2" maxlength="2000" data-time-field="review_note" placeholder="修改或排除时必填；确认不代表系统已经证明事实。">${esc(selected.review_note)}</textarea></label>${selected.evidence.map(ref=>`<button class="button small" type="button" data-time-source="${selected.id}">打开原件 · ${esc(ref.path)} · ${esc(sourceLocation(ref))}</button><blockquote class="quote">${esc(ref.quote)}</blockquote>`).join('')}<p class="note">原始提取：${esc(selected.original.date_text||'日期不明')} · ${esc(selected.original.description)}</p>`:'<p class="note">未取得可验证事件。可以按材料原文手工补录。</p>'}</div></div>
      <details id="manualTimeline"><summary>按原文手工补录遗漏事件</summary><button id="loadTimeFragments" class="button" type="button">读取本次材料片段</button><div id="timeFragments"></div><p id="manualSourceText" class="quote"></p><label>逐字引句<textarea id="manualTimeQuote" rows="3" maxlength="1200"></textarea></label><label>日期原文<input id="manualTimeDate" type="text" maxlength="100" placeholder="必须原样出现在引句中；不明可以留空"></label><label>主体<input id="manualTimeActors" type="text" maxlength="300"></label><label>事件内容<textarea id="manualTimeDescription" rows="2" maxlength="1200"></textarea></label><label>事项类型（用于发现日期差异）<input id="manualTimeTopic" type="text" maxlength="200"></label><button id="addTimeEvent" class="button" type="button">保存补录事件</button></details>
      ${job.results?.length?`<details><summary>与参考法律文书对照 · ${job.results.length}项</summary>${job.results.map(row=>`<article class="basis-item"><strong>${esc(row.document_locator)} · ${esc(resultNames[row.status])}</strong><p>${esc(row.claim)}</p><p>${esc(row.reason)}</p>${row.evidence.map(ref=>`<blockquote class="quote">${esc(ref.path)} · ${esc(sourceLocation(ref))}<br>${esc(ref.quote)}</blockquote>`).join('')}</article>`).join('')}</details>`:''}</section>`;
  }
  function captureTimeline(){const job=state.job;if(job?.kind!=='timeline')return;const row=job.timeline_events.find(row=>row.id===timelineSelection);if(!row)return;$('detail').querySelectorAll('[data-time-field]').forEach(input=>row[input.dataset.timeField]=input.value);}
  function timelineUpdates(){captureTimeline();return state.job.timeline_events.map(row=>({id:row.id,date_text:row.date_text,actors:row.actors,description:row.description,status:row.review_status,note:row.review_note}));}
  async function handleTimeline(event){
    if(state.job?.kind!=='timeline'||state.busy)return false;
    const button=event.target.closest('[data-time-event],[data-time-filter],[data-time-status],[data-time-source],#saveTimeline,#restoreTimeline,#loadTimeFragments,[data-time-fragment],#addTimeEvent,[data-export-style]');if(!button)return false;
    if(button.dataset.exportStyle){if(manualDirty){toast('请先保存补录事件');return true;}captureTimeline();state.job.export_options={...(state.job.export_options||{style:'axis',include_evidence:true}),style:button.dataset.exportStyle};state.reviewDirty=true;renderDetail();$('detail').querySelector(`[data-export-style="${button.dataset.exportStyle}"]`)?.focus({preventScroll:true});return true;}
    if(button.dataset.timeEvent||button.dataset.timeFilter){if(manualDirty){toast('请先保存补录事件，或放弃修改载入保存版本');return true;}captureTimeline();if(button.dataset.timeEvent)timelineSelection=button.dataset.timeEvent;else timelineFilter=button.dataset.timeFilter;renderDetail();return true;}
    if(button.dataset.timeStatus){if(manualDirty){toast('请先保存补录事件');return true;}captureTimeline();const row=state.job.timeline_events.find(row=>row.id===timelineSelection);row.review_status=button.dataset.timeStatus;state.reviewDirty=true;renderDetail();return true;}
    if(button.dataset.timeSource){const row=state.job.timeline_events.find(row=>row.id===button.dataset.timeSource),ref=row.evidence[0];previewFocus=document.activeElement;$('previewTitle').textContent=ref.path+' · '+sourceLocation(ref);$('previewQuote').textContent=ref.quote;const page=ref.locator.match(/第\s*(\d+)\s*页/);const original=`${base()}/${state.job.id}/timeline-source?event_id=${row.id}`;$('sourceLink').href=original;if(/\.(pdf|docx?|png|jpe?g)$/i.test(ref.path))$('sourcePreview').src=`${base()}/${state.job.id}/material-preview?path=${encodeURIComponent(ref.path)}&page=${page?.[1]||1}`;else $('sourcePreview').removeAttribute('src');$('preview').hidden=false;$('closePreview').focus();return true;}
    if(button.dataset.timeFragment){const source=manualFragments[Number(button.dataset.timeFragment)];$('manualSourceText').textContent=source.text;$('manualSourceText').dataset.sourceId=source.id;return true;}
    if(button.id==='saveTimeline'&&manualDirty){toast('请先添加补录事件，或放弃修改载入保存版本');return true;}
    busy(true);
    try{
      if(button.id==='loadTimeFragments'){const data=await api(`${base()}/${state.job.id}/timeline-fragments`);manualFragments=data.items;$('timeFragments').innerHTML=manualFragments.map((row,index)=>`<button class="button small" type="button" data-time-fragment="${index}">${esc(row.path)} · ${esc(sourceLocation(row))}</button>`).join('');}
      else if(button.id==='restoreTimeline'){state.job=await api(`${base()}/${state.job.id}`);state.reviewDirty=false;manualDirty=false;renderDetail();toast('已恢复保存的时间轴');}
      else{let manual=[];if(button.id==='addTimeEvent'){manual=[{source_id:$('manualSourceText').dataset.sourceId||'',quote:$('manualTimeQuote').value,date_text:$('manualTimeDate').value,actors:$('manualTimeActors').value,description:$('manualTimeDescription').value,topic:$('manualTimeTopic').value}];}
        const updated=await send(`${base()}/${state.job.id}/timeline`,'PUT',{revision:state.job.revision,events:timelineUpdates(),manual_events:manual,export_options:state.job.export_options});state.job=updated;state.reviewDirty=false;manualDirty=false;renderDetail();toast('时间轴已保存，导出已更新');await refresh();}
    }catch(error){toast(error.message);}finally{busy(false);}
    return true;
  }

  function captureReviews(){if(!state.job)return;document.querySelectorAll('[data-result]').forEach(el=>{const row=state.job.results.find(item=>item.id===el.dataset.result);if(row)row.review_note=el.querySelector('[data-note]').value;});}
  $('detail').addEventListener('input',event=>{if(event.target.id==='timelineEvidence'){captureTimeline();state.job.export_options={...(state.job.export_options||{style:'axis',include_evidence:true}),include_evidence:event.target.checked};state.reviewDirty=true;renderDetail();$('timelineEvidence')?.focus({preventScroll:true});return;}if(event.target.matches('[data-time-field]')){captureTimeline();const row=state.job.timeline_events.find(row=>row.id===timelineSelection);if(event.target.dataset.timeField!=='review_note'){row.review_status='amended';$('detail').querySelectorAll('[data-time-status]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.timeStatus==='amended')));}state.reviewDirty=true;}if(event.target.id?.startsWith('manualTime')){state.reviewDirty=true;manualDirty=true;}if(event.target.matches('[data-note]')){state.reviewDirty=true;captureReviews();}});
  function knowledgeContext(){const job=state.job,id=state.caseId;return {job,busy:state.busy,base:base(id),api,toast,openSource,render:renderDetail,current:()=>state.caseId===id&&state.job?.id===job.id,rerun:async questions=>{busy(true);try{const next=await send(base(id),'POST',{kind:'knowledge_match',paths:job.sources.map(row=>row.path),draft:job.draft,allow_cloud_ocr:job.allow_cloud_ocr,model:job.model,knowledge_position:job.knowledge_position,knowledge_focus:job.knowledge_focus,knowledge_topic_override:questions});if(state.caseId===id){state.job=next;renderDetail();await refresh();schedule();}}catch(error){if(state.caseId===id)toast(error.message);}finally{busy(false);}}};}
  $('detail').addEventListener('toggle',event=>{if(event.target.matches('[data-knowledge-details]')&&state.job?.kind==='knowledge_match')window.StellaCaseKnowledge.showContext(event.target,knowledgeContext());},true);
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
  let previewFocus=null;
  function openSource(ref){previewFocus=document.activeElement;const page=ref.locator.match(/第\s*(\d+)\s*页/);const url=`${base()}/${state.job.id}/source?source_id=${encodeURIComponent(ref.id)}`+(page?`#page=${page[1]}`:'');$('previewTitle').textContent=ref.path+' · '+sourceLocation(ref);$('previewQuote').textContent=ref.quote;if(/\.(pdf|docx?|png|jpe?g)$/i.test(ref.path))$('sourcePreview').src=`${base()}/${state.job.id}/material-preview?path=${encodeURIComponent(ref.path)}&page=${page?.[1]||1}`;else $('sourcePreview').removeAttribute('src');$('sourceLink').href=url;$('preview').hidden=false;$('closePreview').focus();}
  function closePreview(){$('preview').hidden=true;$('sourcePreview').removeAttribute('src');previewFocus?.focus();previewFocus=null;}
  $('closePreview').onclick=closePreview;$('preview').onclick=event=>{if(event.target===$('preview'))closePreview();};
  document.addEventListener('keydown',event=>{if($('preview').hidden)return;if(event.key==='Escape'){event.preventDefault();closePreview();}if(event.key==='Tab'){const controls=[$('closePreview'),$('sourcePreview'),$('sourceLink')];const index=controls.indexOf(document.activeElement);if(event.shiftKey&&index===0){event.preventDefault();controls.at(-1).focus();}else if(!event.shiftKey&&index===controls.length-1){event.preventDefault();controls[0].focus();}}});
  renderInputs();busy(false);
  if(new URLSearchParams(location.search).get('mode')==='tasks')setMode('material_analysis');
  if(state.caseId){api(`/api/case-workflows/cases/${state.caseId}`).then(item=>selectCase(item)).catch(error=>{toast(error.message);busy(false);});}
})();
