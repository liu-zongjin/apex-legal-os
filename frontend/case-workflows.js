(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const state = {caseId: Number(new URLSearchParams(location.search).get('case_id') || 0), kind: 'fact_check', caseTitle:'', sources: [], entries: [], draftPath: '', tasks: [], job: null, busy: false, sequence: 0, timer: null, drafts: new Map(), reviewDirty: false, plan:null, planDirty:false, pageCounts:{}, factReference:null};
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
  function busy(value) { state.busy = value; $('submit').disabled = value || !state.caseId; $('caseSearch').disabled = value; $('factMode').disabled = value; $('bookMode').disabled = value; $('draft').disabled=value;$('ocrConsent').disabled=value;$('savePlan').disabled=value;$('restorePlan').disabled=value;$('bookConfirmed').disabled=value;$('gapsAcknowledged').disabled=value;$('entries').querySelectorAll('input,textarea,button').forEach(el=>{if(value){el.dataset.busyDisabled=String(el.disabled);el.disabled=true;}else if(el.dataset.busyDisabled!==undefined){el.disabled=el.dataset.busyDisabled==='true';delete el.dataset.busyDisabled;}}); }
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
    if (state.caseId) state.drafts.set(state.caseId, {sources:state.sources,entries:state.entries,draftPath:state.draftPath,draft:$('draft').value,plan:state.plan,pageCounts:state.pageCounts});
    state.factReference=null;state.caseId = Number(item.id); state.plan=null;state.planDirty=false;$('planPanel').hidden=true;state.sequence++; state.job = null; state.reviewDirty = false;
    const saved = state.drafts.get(state.caseId) || {sources:[],entries:[],draftPath:'',draft:''};
    Object.assign(state, {sources:saved.sources,entries:saved.entries,draftPath:saved.draftPath});
    $('draft').value = saved.draft; $('bookConfirmed').checked = false; $('ocrConsent').checked = false;
    state.caseTitle=ApexCasePicker.caseName(item); $('caseSearch').value = state.caseTitle; picker.setValue(state.caseId);
    history.replaceState(null, '', `?case_id=${state.caseId}`);
    $('empty').hidden = true; $('work').hidden = false; $('detailPanel').hidden = true;
    $('filePicker').src = `/case-files?case_id=${state.caseId}&workflow_picker=1&title=${encodeURIComponent(ApexCasePicker.caseName(item))}`;
    closePreview(); renderInputs();if(saved.plan){state.plan=saved.plan;state.pageCounts=saved.pageCounts||{};$('planPanel').hidden=false;renderPlan();}refresh(); busy(false);
    if (parent !== window) parent.postMessage({type:'apex:case-workflow-case-selected',version:1,caseId:state.caseId,caseTitle:item.title || ''}, location.origin);
  }
  function setMode(kind) {
    captureEntries(); state.kind = kind;
    $('factMode').setAttribute('aria-pressed', String(kind === 'fact_check')); $('bookMode').setAttribute('aria-pressed', String(kind === 'evidence_book'));
    $('factForm').hidden = kind !== 'fact_check'; $('bookForm').hidden = kind !== 'evidence_book';
    $('formTitle').textContent = kind === 'fact_check' ? '待核对的法律文书' : '编排依据：定稿法律文书';
    $('submit').textContent = kind === 'fact_check' ? '开始对照核对' : '按定稿文书拟定目录';
    $('guideTitle').textContent=kind==='fact_check'?'这份文书的事实，有没有材料支持？':'定稿文书中的事实，应当用哪些证据证明？';
    $('guideText').textContent=kind==='fact_check'?'逐项对照文书与材料，列出支持、矛盾和依据缺口，供你回看原文并修改。':'先选定稿文书和候选材料，系统拟定证据摘要及对应关系；你审阅分组、证明内容和选页，再生成目录与证据册。';
    $('steps').innerHTML=(kind==='fact_check'?['选文书与材料','对照事实及原文','复核并导出／转入编排']:['选定稿文书与材料','审阅目录及文书对应','生成证据册与目录']).map(step=>`<li>${step}</li>`).join('');
    $('planPanel').hidden=kind==='fact_check'||!state.plan;
    renderInputs(); sendPickerRoles();
  }
  $('factMode').onclick = () => setMode('fact_check'); $('bookMode').onclick = () => setMode('evidence_book');
  function syncFileTheme(){ $('inlinePreview').contentWindow?.postMessage({type:'theme',dark:document.documentElement.classList.contains('dark-mode')||document.documentElement.dataset.theme==='dark'},location.origin);$('filePicker').contentWindow?.postMessage({type:'theme',dark:document.documentElement.classList.contains('dark-mode')||document.documentElement.dataset.theme==='dark'},location.origin); }
  $('inlinePreview').addEventListener('load',syncFileTheme);
  $('filePicker').addEventListener('load',()=>{syncFileTheme();sendPickerRoles();});
  new MutationObserver(syncFileTheme).observe(document.documentElement,{attributes:true,attributeFilter:['class','data-theme']});
  function sendPickerRoles() {
    $('filePicker').contentWindow?.postMessage({type:'apex:workflow-status',version:1,caseId:state.caseId,statuses:{},categories:[{code:'source',name:state.kind==='fact_check'?'加入核对材料':'加入候选证据材料'},{code:'draft',name:state.kind==='fact_check'?'选作法律文书（单份）':'选作定稿文书（单份）'}]}, location.origin);
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
    $('sources').innerHTML = state.sources.map((path,index) => `<div class="source-row"><span>${esc(path)}</span><button class="button small" type="button" data-remove-source="${index}">移出</button></div>`).join('') || '<p class="note">尚未选择核对材料</p>';
    $('draftFile').textContent = state.draftPath ? `法律文书：${state.draftPath}（提交时粘贴文字优先）` : '';
    $('clearDraftFile').hidden = !state.draftPath;
    if(state.plan)updateLayout();
  }
  $('draft').addEventListener('input',()=>{if(state.plan)updateLayout();});
  $('sources').onclick=event=>{const button=event.target.closest('[data-remove-source]');if(button&&!state.busy){captureEntries();state.sources.splice(Number(button.dataset.removeSource),1);renderInputs();}};
  $('clearDraftFile').onclick=()=>{state.draftPath='';renderInputs();};
  $('entries').addEventListener('input',()=>{markPlanDirty();updateLayout();});
  $('entries').onclick=event=>{
    const preview=event.target.closest('[data-preview-material]');if(preview){const material=state.entries[Number(preview.dataset.entryIndex)].materials[Number(preview.dataset.previewMaterial)];$('inlinePreviewTitle').textContent=material.path;$('inlinePreview').src=`${base()}/${state.plan.id}/material-preview?path=${encodeURIComponent(material.path)}`;return;}
    const button=event.target.closest('[data-entry-action]');if(!button||state.busy)return;captureEntries();
    const index=Number(button.dataset.index),action=button.dataset.entryAction,entry=state.entries[index];
    if(action==='remove')state.entries.splice(index,1);
    else if(action==='merge'){
      const next=state.entries[index+1];if(!next)return;
      if(entry.materials.some(material=>next.materials.some(row=>row.path===material.path)))return toast('两项包含同一材料，请先调整选页，避免重复');
      entry.materials.push(...next.materials);entry.claim_ids=[...new Set([...entry.claim_ids,...next.claim_ids])];entry.summary=[entry.summary,next.summary].filter(Boolean).join('；');entry.purpose=[entry.purpose,next.purpose].filter(Boolean).join('；');entry.summary_refs=[...(entry.summary_refs||[]),...(next.summary_refs||[])];if(next.origin&&next.origin!==entry.origin)entry.origin=[entry.origin,next.origin].filter(Boolean).join('；');state.entries.splice(index+1,1);
    }else if(action==='duplicate'){if(state.entries.length>=80)return toast('目录最多80项');const copy=structuredClone(entry);copy.title+='（分项）';copy.purpose='';copy.summary='';copy.claim_ids=[];copy.warning='请调整选页，填写分项摘要和证明内容，并重新关联文书事项。';state.entries.splice(index+1,0,copy);}
    else if(action==='split'){
      if(state.entries.length+entry.materials.length-1>80)return toast('目录最多80项，请分册整理');
      const materials=entry.materials.splice(1);state.entries.splice(index+1,0,...materials.map(material=>({...structuredClone(entry),title:material.path.split('/').pop().replace(/\.[^.]+$/,''),summary:'',purpose:'',claim_ids:[],materials:[material],summary_refs:[],warning:'拆分后请重新填写摘要、证明内容并确认文书关联。'})));
    }else{const target=index+(action==='up'?-1:1);if(target>=0&&target<state.entries.length)[state.entries[index],state.entries[target]]=[state.entries[target],state.entries[index]];}
    markPlanDirty();renderEntries();updateLayout();
  };
  $('submit').onclick = async () => {
    if (state.busy || !state.caseId) return;
    if(state.reviewDirty||state.planDirty)return toast('请先保存复核意见或编排草稿，再交办新任务');
    captureEntries(); const id = state.caseId;
    const reference=state.factReference;
    const referenceId=reference&&reference.draft.trim()===$('draft').value.trim()&&JSON.stringify([...reference.sources.map(row=>row.path)].sort())===JSON.stringify([...state.sources].sort())?reference.id:'';
    const payload = {reference_task_id:referenceId,kind:state.kind==='fact_check'?'fact_check':'evidence_plan',paths:state.sources,draft:$('draft').value,draft_path:state.draftPath,allow_cloud_ocr:$('ocrConsent').checked,entries:state.entries,confirmed:$('bookConfirmed').checked};
    busy(true);
    try { const job = await send(base(id),'POST',payload); if(state.caseId!==id)return; state.job=job;state.reviewDirty=false;renderDetail();await refresh();schedule(); }
    catch(error){toast(error.message);}finally{busy(false);}
  };
  async function refresh() {
    if (!state.caseId) return;
    const id=state.caseId,sequence=++state.sequence;
    try { const data=await api(base(id));if(sequence!==state.sequence||id!==state.caseId)return;state.tasks=data.items;renderTasks();
      if(state.job&&!state.reviewDirty){const latest=data.items.find(row=>row.id===state.job.id);if(latest){state.job=latest;renderDetail();if(latest.kind==='evidence_plan'&&latest.status==='completed'&&state.plan?.id!==latest.id)loadPlan(latest);}} }
    catch(error){if(id===state.caseId)toast(error.message);}
    schedule();
  }
  $('refresh').onclick=refresh;
  function schedule(){clearTimeout(state.timer);if(window.ApexLifecycle?.active!==false&&document.visibilityState==='visible'&&state.tasks.some(row=>['running','queued'].includes(row.status)))state.timer=setTimeout(refresh,1500);}
  window.ApexLifecycle?.onChange(active=>{ $('filePicker').contentWindow?.postMessage({type:'apex:workflow-visibility',version:1,caseId:state.caseId,active},location.origin); if(active)refresh();else clearTimeout(state.timer);});
  addEventListener('beforeunload',()=>clearTimeout(state.timer));
  function jobName(row){return {fact_check:'文书事实核对',evidence_plan:'证据编排草案',evidence_book:'证据册'}[row.kind]||row.kind;}
  function renderTasks(){ $('tasks').innerHTML=state.tasks.map(row=>`<div class="task-row"><span>${jobName(row)} · ${esc(statusNames[row.status])}<small class="note"> ${esc(displayTime(row.created_at))} · ${row.sources.length}份材料</small></span><button class="button" type="button" data-job="${row.id}">查看</button></div>`).join('')||'<p class="note">尚未交办任务。</p>'; }
  $('tasks').onclick=event=>{const button=event.target.closest('[data-job]');if(!button||state.busy)return;if(state.reviewDirty||state.planDirty)return toast('请先保存复核意见或编排草稿，再切换任务');state.job=state.tasks.find(row=>row.id===button.dataset.job);renderDetail();if(state.job.kind==='evidence_plan'&&state.job.status==='completed')loadPlan(state.job);};
  function artifactLinks(job, revision, artifacts){return artifacts.map((row,index)=>`<a href="${base()}/${job.id}/artifacts/${index}?revision=${revision}" download>${esc(row.name)}</a>`).join('');}
  function renderDetail(){
    const job=state.job;if(!job)return;$('detailPanel').hidden=false;
    const results=(job.results||[]).map(row=>`<tr data-result="${row.id}"><td>${row.id}</td><td class="claim"><span class="note">${esc(row.document_locator||'')} · ${esc({fact:'事实',legal:'法律观点',request:'请求',opinion:'推测'}[row.statement_type]||'事实')}</span><p>${esc(row.claim)}</p></td><td class="reason"><strong>${esc(resultNames[row.status])}</strong><p>${esc(row.reason)}</p>${row.evidence.map(ref=>`<button class="button small source-button" type="button" data-source="${esc(ref.id)}" data-result-source="${row.id}">${esc(ref.path)} · ${esc(ref.locator)}</button><div class="quote">${esc(ref.quote)}</div>`).join('')}</td><td class="review"><div class="review-actions">${Object.entries(reviewNames).map(([value,label])=>`<button class="button small" type="button" data-review="${value}" ${job.status!=='completed'||job.kind!=='fact_check'?'disabled':''} aria-pressed="${row.review_status===value}">${label}</button>`).join('')}</div><label>人工意见<textarea rows="2" maxlength="2000" data-note ${job.status!=='completed'||job.kind!=='fact_check'?'disabled':''}>${esc(row.review_note)}</textarea></label></td></tr>`).join('');
    $('detail').innerHTML=`<h2>${jobName(job)} · ${esc(statusNames[job.status])}</h2><p ${job.status==='failed'?'class="warning"':''}>${esc(job.message)}</p><progress value="${job.progress}" max="100" aria-label="办理进度"></progress><div class="downloads">${artifactLinks(job,job.revision,job.artifacts)}</div>${job.versions?.length>1?`<details><summary>历史成果版本</summary>${job.versions.slice(0,-1).map(version=>`<p>第${version.revision}版</p><div class="downloads">${artifactLinks(job,version.revision,version.artifacts)}</div>`).join('')}</details>`:''}<p class="note">材料版本已固定；原件变化时不会继续办理或打开旧引用。当前成果版本：${job.revision}</p>${['running','queued'].includes(job.status)?'<button id="cancelJob" class="button" type="button">停止任务</button>':''}${['failed','cancelled','interrupted'].includes(job.status)?'<button id="resumeJob" class="button" type="button">继续办理</button>':''}${job.kind!=='evidence_book'&&results?`<div class="table-wrap"><table><thead><tr><th>编号</th><th>文书事项及位置</th><th>AI初核及出处</th><th>人工复核</th></tr></thead><tbody>${results}</tbody></table></div>`:''}${job.kind==='fact_check'&&job.status==='completed'?'<div class="entry-controls"><button id="saveReview" class="button primary" type="button">保存复核并生成新版本</button><button id="useForBook" class="button" type="button">以此文书与材料编排证据</button></div>':''}<details><summary>办理步骤</summary>${job.steps.map(step=>`<p class="note">${esc(displayTime(step.at))} · ${esc(step.message)}</p>`).join('')}</details>`;
  }
  function captureReviews(){if(!state.job)return;document.querySelectorAll('[data-result]').forEach(el=>{const row=state.job.results.find(item=>item.id===el.dataset.result);if(row)row.review_note=el.querySelector('[data-note]').value;});}
  $('detail').addEventListener('input',event=>{if(event.target.matches('[data-note]')){state.reviewDirty=true;captureReviews();}});
  $('detail').onclick=async event=>{
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
    state.plan=job;state.planDirty=false;state.entries=structuredClone(job.plan_entries||[]);state.pageCounts={};
    renderInputs();$('planPanel').hidden=false;$('inlinePreview').removeAttribute('src');renderPlan();
    const caseId=state.caseId;
    Promise.all(job.sources.map(async row=>{try{const info=await api(`${base(caseId)}/${job.id}/material-info?path=${encodeURIComponent(row.path)}`);if(state.plan?.id===job.id&&state.caseId===caseId)state.pageCounts[row.path]=info;}catch(error){if(state.plan?.id===job.id&&state.caseId===caseId)state.pageCounts[row.path]={error:error.message};}})).then(()=>{if(state.plan?.id===job.id&&state.caseId===caseId)updateLayout();});
  }
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
    renderEntries();updateLayout();
  }
  function renderEntries(){
    $('entries').innerHTML=state.entries.map((row,index)=>`<article class="entry" data-entry="${index}"><header><h3>证据${index+1}</h3><span class="note" data-page-range></span></header>
      <label>证据名称<input data-field="title" type="text" maxlength="200" value="${esc(row.title)}"></label>
      <label>证据摘要 · 材料写了什么<textarea data-field="summary" rows="3" maxlength="3000">${esc(row.summary)}</textarea></label>
      <label>证明内容 · 用它证明什么<textarea data-field="purpose" rows="3" maxlength="2000">${esc(row.purpose)}</textarea></label>
      <div class="entry-meta"><label>证据来源（选填）<input data-field="origin" type="text" maxlength="600" value="${esc(row.origin)}" placeholder="如：当事人提供、银行调取"></label><label>分组（选填）<input data-field="group" type="text" maxlength="200" value="${esc(row.group)}" placeholder="如：借贷关系、履行情况"></label></div>
      <fieldset class="claim-links"><legend>对应文书事项（可多选）</legend>${state.plan.results.map(claim=>`<label class="claim-link"><input type="checkbox" data-claim="${claim.id}" ${(row.claim_ids||[]).includes(claim.id)?'checked':''}><span>${claim.id} · ${esc(claim.claim)}</span></label>`).join('')}</fieldset>
      <h3>组成材料与原件选页</h3>${row.materials.map((material,mi)=>`<div class="material-part" data-material="${mi}"><button class="button small" type="button" data-preview-material="${mi}" data-entry-index="${index}">${esc(material.path)}</button><label>选页<input data-pages type="text" maxlength="2000" value="${esc(material.pages)}" placeholder="全部，或1-3,5"><small class="note">${esc(state.pageCounts[material.path]?.page_basis||'按原件物理页码；Word按转换后PDF页码')}</small></label></div>`).join('')}
      ${row.coverage_note?`<p class="note">${esc(row.coverage_note)}</p>`:''}${row.warning?`<p class="warning">${esc(row.warning)}</p>`:''}
      ${(row.summary_refs||[]).map(ref=>`<p class="quote">原始建议的参考引句：${esc(ref.path)} · ${esc(ref.locator)}<br>${esc(ref.quote)}</p>`).join('')}
      <div class="entry-controls"><button class="button small" type="button" data-entry-action="up" data-index="${index}" ${index===0?'disabled':''}>上移</button><button class="button small" type="button" data-entry-action="down" data-index="${index}" ${index===state.entries.length-1?'disabled':''}>下移</button><button class="button small" type="button" data-entry-action="merge" data-index="${index}" ${index===state.entries.length-1?'disabled':''}>合并下一项</button><button class="button small" type="button" data-entry-action="duplicate" data-index="${index}">复制为分项／选页拆分</button><button class="button small" type="button" data-entry-action="split" data-index="${index}" ${row.materials.length<2?'disabled':''}>拆分材料</button><button class="button small" type="button" data-entry-action="remove" data-index="${index}">移出目录</button></div></article>`).join('')||'<p class="note">目录为空，重新载入草稿可恢复已保存的条目。</p>';
    if(state.busy)$('entries').querySelectorAll('input,textarea,button').forEach(el=>{el.dataset.busyDisabled=String(el.disabled);el.disabled=true;});
  }
  function updateLayout(){
    if(!state.plan)return;
    captureEntries();let next=1,valid=true;
    $('entries').querySelectorAll('[data-entry]').forEach(el=>{const entry=state.entries[Number(el.dataset.entry)];let count=0;
      try{entry.materials.forEach(material=>{const info=state.pageCounts[material.path];if(!info)throw Error('读取原件页数中…');if(info.error)throw Error(info.error);count+=pageCount(material.pages,info.pages);});el.querySelector('[data-page-range]').textContent=`编册第${next}—${next+count-1}页 · ${count}页`;next+=count;}
      catch(error){valid=false;el.querySelector('[data-page-range]').textContent=error.message;}
    });
    const linked=new Set(state.entries.flatMap(row=>row.claim_ids));
    const gaps=state.plan.results.filter(row=>{if(['legal','request'].includes(row.statement_type))return false;if(!linked.has(row.id)||row.status!=='supported'||['rejected','amended'].includes(row.review_status))return true;return !row.evidence.some(ref=>state.entries.some(entry=>entry.claim_ids.includes(row.id)&&entry.materials.some(material=>{if(material.path!==ref.path)return false;if(!material.pages.trim()||material.pages.trim()==='全部')return true;const match=ref.locator.match(/第\s*(\d+)\s*页/);if(!match)return false;return material.pages.replaceAll('，',',').split(',').some(part=>{const range=part.match(/^\s*(\d+)(?:\s*-\s*(\d+))?\s*$/);return range&&Number(match[1])>=Number(range[1])&&Number(match[1])<=Number(range[2]||range[1]);});})));});
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
  function openSource(ref){previewFocus=document.activeElement;const page=ref.locator.match(/第\s*(\d+)\s*页/);const url=`${base()}/${state.job.id}/source?source_id=${encodeURIComponent(ref.id)}`+(page?`#page=${page[1]}`:'');$('previewTitle').textContent=ref.path+' · '+ref.locator;$('previewQuote').textContent=ref.quote;$('sourcePreview').src=url;$('sourceLink').href=url;$('preview').hidden=false;$('closePreview').focus();}
  function closePreview(){$('preview').hidden=true;$('sourcePreview').removeAttribute('src');previewFocus?.focus();previewFocus=null;}
  $('closePreview').onclick=closePreview;$('preview').onclick=event=>{if(event.target===$('preview'))closePreview();};
  document.addEventListener('keydown',event=>{if($('preview').hidden)return;if(event.key==='Escape'){event.preventDefault();closePreview();}if(event.key==='Tab'){const controls=[$('closePreview'),$('sourcePreview'),$('sourceLink')];const index=controls.indexOf(document.activeElement);if(event.shiftKey&&index===0){event.preventDefault();controls.at(-1).focus();}else if(!event.shiftKey&&index===controls.length-1){event.preventDefault();controls[0].focus();}}});
  renderInputs();busy(false);
  if(state.caseId){api(`/api/case-workflows/cases/${state.caseId}`).then(item=>selectCase(item)).catch(error=>{toast(error.message);busy(false);});}
})();
