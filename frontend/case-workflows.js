(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const state = {caseId: Number(new URLSearchParams(location.search).get('case_id') || 0), kind: 'fact_check', caseTitle:'', sources: [], entries: [], draftPath: '', tasks: [], job: null, busy: false, sequence: 0, timer: null, drafts: new Map(), reviewDirty: false};
  const displayTime=value=>{const date=new Date(value);return Number.isNaN(date.getTime())?String(value||''):date.toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});};
  const statusNames = {queued:'排队中',running:'办理中',completed:'已交付',failed:'失败',cancelled:'已停止',interrupted:'已中断'};
  const resultNames = {supported:'AI初核支持',contradicted:'AI初核矛盾',not_found:'未找到出处',inference:'推断／待核'};
  const reviewNames = {pending:'待复核',confirmed:'确认初核',rejected:'否定初核',amended:'已修改'};
  async function api(url, options = {}) {
    const response = await fetch(url, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `操作失败（${response.status}）`);
    return data;
  }
  const send = (url, method, body) => api(url, {method, headers:{'Content-Type':'application/json'},body:JSON.stringify(body || {})});
  const base = (id = state.caseId) => `/api/case-workflows/cases/${id}/tasks`;
  function toast(text) { $('toast').textContent = text; $('toast').classList.add('visible'); clearTimeout(toast.timer); toast.timer = setTimeout(() => $('toast').classList.remove('visible'), 4000); }
  function busy(value) { state.busy = value; $('submit').disabled = value || !state.caseId; $('caseSearch').disabled = value; $('factMode').disabled = value; $('bookMode').disabled = value; }
  const picker = ApexCasePicker.attach({input:$('caseSearch'),menu:$('caseResults'),value:state.caseId,onSelect:item => selectCase(item)});
  function captureEntries() {
    $('entries').querySelectorAll('[data-entry]').forEach(el => { const entry = state.entries[Number(el.dataset.entry)]; if (entry) { entry.title = el.querySelector('input').value; entry.purpose = el.querySelector('textarea').value; } });
  }
  function selectCase(item) {
    if(state.reviewDirty){$('caseSearch').value=state.caseTitle;picker.setValue(state.caseId);return toast('请先保存当前复核意见，再切换案件');}
    captureEntries();
    if (state.caseId) state.drafts.set(state.caseId, {sources:state.sources,entries:state.entries,draftPath:state.draftPath,draft:$('draft').value});
    state.caseId = Number(item.id); state.sequence++; state.job = null; state.reviewDirty = false;
    const saved = state.drafts.get(state.caseId) || {sources:[],entries:[],draftPath:'',draft:''};
    Object.assign(state, {sources:saved.sources,entries:saved.entries,draftPath:saved.draftPath});
    $('draft').value = saved.draft; $('bookConfirmed').checked = false; $('ocrConsent').checked = false;
    state.caseTitle=ApexCasePicker.caseName(item); $('caseSearch').value = state.caseTitle; picker.setValue(state.caseId);
    history.replaceState(null, '', `?case_id=${state.caseId}`);
    $('empty').hidden = true; $('work').hidden = false; $('detailPanel').hidden = true;
    $('filePicker').src = `/case-files?case_id=${state.caseId}&workflow_picker=1&title=${encodeURIComponent(ApexCasePicker.caseName(item))}`;
    closePreview(); renderInputs(); refresh(); busy(false);
    if (parent !== window) parent.postMessage({type:'apex:case-workflow-case-selected',version:1,caseId:state.caseId,caseTitle:item.title || ''}, location.origin);
  }
  function setMode(kind) {
    captureEntries(); state.kind = kind;
    $('factMode').setAttribute('aria-pressed', String(kind === 'fact_check')); $('bookMode').setAttribute('aria-pressed', String(kind === 'evidence_book'));
    $('factForm').hidden = kind !== 'fact_check'; $('bookForm').hidden = kind !== 'evidence_book';
    $('formTitle').textContent = kind === 'fact_check' ? '交办事实核对' : '生成证据册';
    $('submit').textContent = kind === 'fact_check' ? '交办事实核对' : '生成证据册';
    renderInputs(); sendPickerRoles();
  }
  $('factMode').onclick = () => setMode('fact_check'); $('bookMode').onclick = () => setMode('evidence_book');
  function syncFileTheme(){ $('filePicker').contentWindow?.postMessage({type:'theme',dark:document.documentElement.classList.contains('dark-mode')||document.documentElement.dataset.theme==='dark'},location.origin); }
  $('filePicker').addEventListener('load',()=>{syncFileTheme();sendPickerRoles();});
  new MutationObserver(syncFileTheme).observe(document.documentElement,{attributes:true,attributeFilter:['class','data-theme']});
  function sendPickerRoles() {
    $('filePicker').contentWindow?.postMessage({type:'apex:workflow-status',version:1,caseId:state.caseId,statuses:{},categories:state.kind === 'fact_check' ? [{code:'source',name:'加入核对材料'},{code:'draft',name:'选作草稿（单份）'}] : [{code:'evidence',name:'加入证据清单'}]}, location.origin);
  }
  addEventListener('message', event => {
    if (event.origin !== location.origin || event.source !== $('filePicker').contentWindow || event.data?.version !== 1 || Number(event.data.caseId) !== state.caseId) return;
    if (event.data.type === 'apex:workflow-picker-ready') return sendPickerRoles();
    if (event.data.type !== 'apex:workflow-assign' || state.busy || !Array.isArray(event.data.paths)) return;
    const paths = [...new Set(event.data.paths.filter(path => typeof path === 'string' && !path.startsWith('Stella办案成果/')))];
    if(paths.length!==new Set(event.data.paths).size)return toast('请选择原始材料；办案成果需另存到材料目录后使用');
    captureEntries();
    if (event.data.itemCode === 'draft' && state.kind === 'fact_check') {
      if (paths.length !== 1) return toast('请选择一份草稿文件');
      if ($('draft').value.trim()) return toast('已有粘贴草稿，请先清空后再选择草稿文件');
      state.draftPath = paths[0];
    } else if (event.data.itemCode === 'source' && state.kind === 'fact_check') {const selected=[...new Set([...state.sources,...paths])];if(selected.length>40)return toast('一次最多40份材料，本次未加入');state.sources=selected;}
    else if (event.data.itemCode === 'evidence' && state.kind === 'evidence_book') {
      if(state.entries.length+paths.filter(path=>!state.entries.some(row=>row.path===path)).length>40)return toast('一次最多40份证据，本次未加入');
      paths.forEach(path => { if (!state.entries.some(row => row.path === path) && state.entries.length < 40) state.entries.push({path,title:path.split('/').pop().replace(/\.[^.]+$/, ''),purpose:''}); });
      $('bookConfirmed').checked = false;
    } else return;
    $('filePicker').contentWindow.postMessage({type:'apex:workflow-clear-selection',version:1,caseId:state.caseId}, location.origin);
    renderInputs();
  });
  function renderInputs() {
    $('sources').innerHTML = state.sources.map((path,index) => `<div class="source-row"><span>${esc(path)}</span><button class="button small" type="button" data-remove-source="${index}">移出</button></div>`).join('') || '<p class="note">尚未选择核对材料</p>';
    $('draftFile').textContent = state.draftPath ? `草稿文件：${state.draftPath}（提交时粘贴文字优先）` : '';
    $('clearDraftFile').hidden = !state.draftPath;
    $('entries').innerHTML = state.entries.map((row,index) => `<div class="entry" data-entry="${index}"><p class="note">证据${index+1} · ${esc(row.path)}</p><label>证据名称<input type="text" maxlength="200" value="${esc(row.title)}"></label><label>证明目的<textarea rows="2" maxlength="2000">${esc(row.purpose)}</textarea></label><div class="entry-controls"><button class="button small" type="button" data-entry-action="up" data-index="${index}" ${index===0?'disabled':''}>上移</button><button class="button small" type="button" data-entry-action="down" data-index="${index}" ${index===state.entries.length-1?'disabled':''}>下移</button><button class="button small" type="button" data-entry-action="remove" data-index="${index}">移出</button></div></div>`).join('') || '<p class="note">尚未加入证据，选择案件文件后加入清单。</p>';
  }
  $('sources').onclick = event => { const button = event.target.closest('[data-remove-source]'); if (button && !state.busy) {captureEntries();state.sources.splice(Number(button.dataset.removeSource),1); renderInputs();} };
  $('clearDraftFile').onclick = () => {captureEntries();state.draftPath='';renderInputs();};
  $('entries').addEventListener('input', () => { $('bookConfirmed').checked=false; });
  $('entries').onclick = event => {
    const button = event.target.closest('[data-entry-action]'); if (!button || state.busy) return;
    captureEntries(); const index = Number(button.dataset.index), action = button.dataset.entryAction;
    if (action === 'remove') state.entries.splice(index,1);
    else { const target = index + (action==='up'?-1:1); if(target>=0 && target<state.entries.length) [state.entries[index],state.entries[target]]=[state.entries[target],state.entries[index]]; }
    $('bookConfirmed').checked=false;renderInputs();
  };
  $('submit').onclick = async () => {
    if (state.busy || !state.caseId) return;
    if(state.reviewDirty)return toast('请先保存当前复核意见，再交办新任务');
    captureEntries(); const id = state.caseId;
    const payload = {kind:state.kind,paths:state.kind==='fact_check'?state.sources:state.entries.map(row=>row.path),draft:$('draft').value,draft_path:state.draftPath,allow_cloud_ocr:$('ocrConsent').checked,entries:state.entries,confirmed:$('bookConfirmed').checked};
    busy(true);
    try { const job = await send(base(id),'POST',payload); if(state.caseId!==id)return; state.job=job;state.reviewDirty=false;renderDetail();await refresh();schedule(); }
    catch(error){toast(error.message);}finally{busy(false);}
  };
  async function refresh() {
    if (!state.caseId) return;
    const id=state.caseId,sequence=++state.sequence;
    try { const data=await api(base(id));if(sequence!==state.sequence||id!==state.caseId)return;state.tasks=data.items;renderTasks();
      if(state.job&&!state.reviewDirty){const latest=data.items.find(row=>row.id===state.job.id);if(latest){state.job=latest;renderDetail();}} }
    catch(error){if(id===state.caseId)toast(error.message);}
    schedule();
  }
  $('refresh').onclick=refresh;
  function schedule(){clearTimeout(state.timer);if(window.ApexLifecycle?.active!==false&&document.visibilityState==='visible'&&state.tasks.some(row=>['running','queued'].includes(row.status)))state.timer=setTimeout(refresh,1500);}
  window.ApexLifecycle?.onChange(active=>{ $('filePicker').contentWindow?.postMessage({type:'apex:workflow-visibility',version:1,caseId:state.caseId,active},location.origin); if(active)refresh();else clearTimeout(state.timer);});
  addEventListener('beforeunload',()=>clearTimeout(state.timer));
  function renderTasks(){ $('tasks').innerHTML=state.tasks.map(row=>`<div class="task-row"><span>${row.kind==='fact_check'?'事实核对':'证据册'} · ${esc(statusNames[row.status])}<small class="note"> ${esc(displayTime(row.created_at))} · ${row.sources.length}份材料</small></span><button class="button" type="button" data-job="${row.id}">查看</button></div>`).join('')||'<p class="note">尚未交办任务。</p>'; }
  $('tasks').onclick=event=>{const button=event.target.closest('[data-job]');if(!button)return;if(state.reviewDirty)return toast('请先保存当前复核意见，再切换任务');state.job=state.tasks.find(row=>row.id===button.dataset.job);renderDetail();};
  function artifactLinks(job, revision, artifacts){return artifacts.map((row,index)=>`<a href="${base()}/${job.id}/artifacts/${index}?revision=${revision}" download>${esc(row.name)}</a>`).join('');}
  function renderDetail(){
    const job=state.job;if(!job)return;$('detailPanel').hidden=false;
    const results=(job.results||[]).map(row=>`<tr data-result="${row.id}"><td>${row.id}</td><td class="claim">${esc(row.claim)}</td><td class="reason"><strong>${esc(resultNames[row.status])}</strong><p>${esc(row.reason)}</p>${row.evidence.map(ref=>`<button class="button small source-button" type="button" data-source="${esc(ref.id)}" data-result-source="${row.id}">${esc(ref.path)} · ${esc(ref.locator)}</button><div class="quote">${esc(ref.quote)}</div>`).join('')}</td><td class="review"><div class="review-actions">${Object.entries(reviewNames).map(([value,label])=>`<button class="button small" type="button" data-review="${value}" ${job.status!=='completed'?'disabled':''} aria-pressed="${row.review_status===value}">${label}</button>`).join('')}</div><label>人工意见<textarea rows="2" maxlength="2000" data-note ${job.status!=='completed'?'disabled':''}>${esc(row.review_note)}</textarea></label></td></tr>`).join('');
    $('detail').innerHTML=`<h2>${job.kind==='fact_check'?'事实核对':'证据册'} · ${esc(statusNames[job.status])}</h2><p ${job.status==='failed'?'class="warning"':''}>${esc(job.message)}</p><progress value="${job.progress}" max="100" aria-label="办理进度"></progress><div class="downloads">${artifactLinks(job,job.revision,job.artifacts)}</div>${job.versions?.length>1?`<details><summary>历史成果版本</summary>${job.versions.slice(0,-1).map(version=>`<p>第${version.revision}版</p><div class="downloads">${artifactLinks(job,version.revision,version.artifacts)}</div>`).join('')}</details>`:''}<p class="note">材料版本已固定；原件变化时不会继续办理或打开旧引用。当前成果版本：${job.revision}</p>${['running','queued'].includes(job.status)?'<button id="cancelJob" class="button" type="button">停止任务</button>':''}${['failed','cancelled','interrupted'].includes(job.status)?'<button id="resumeJob" class="button" type="button">继续办理</button>':''}${results?`<div class="table-wrap"><table><thead><tr><th>编号</th><th>草稿主张</th><th>AI初核及出处</th><th>人工复核</th></tr></thead><tbody>${results}</tbody></table></div>`:''}${job.kind==='fact_check'&&job.status==='completed'?'<button id="saveReview" class="button primary" type="button">保存复核并生成新版本</button>':''}<details><summary>办理步骤</summary>${job.steps.map(step=>`<p class="note">${esc(displayTime(step.at))} · ${esc(step.message)}</p>`).join('')}</details>`;
  }
  function captureReviews(){if(!state.job)return;document.querySelectorAll('[data-result]').forEach(el=>{const row=state.job.results.find(item=>item.id===el.dataset.result);if(row)row.review_note=el.querySelector('[data-note]').value;});}
  $('detail').addEventListener('input',event=>{if(event.target.matches('[data-note]')){state.reviewDirty=true;captureReviews();}});
  $('detail').onclick=async event=>{
    const review=event.target.closest('[data-review]');if(review){if(state.job?.status!=='completed')return;const tr=review.closest('[data-result]');const row=state.job.results.find(item=>item.id===tr.dataset.result);row.review_status=review.dataset.review;tr.querySelectorAll('[data-review]').forEach(button=>button.setAttribute('aria-pressed',String(button===review)));state.reviewDirty=true;return;}
    const source=event.target.closest('[data-source]');if(source){const ref=state.job.results.find(row=>row.id===source.dataset.resultSource)?.evidence.find(row=>row.id===source.dataset.source);if(ref)openSource(ref);return;}
    const action=event.target.closest('#cancelJob,#resumeJob,#saveReview');if(!action||state.busy)return;
    const id=state.caseId,job=state.job;busy(true);action.disabled=true;
    try{let updated;
      if(action.id==='saveReview'){captureReviews();updated=await send(`${base(id)}/${job.id}/review`,'PUT',{revision:job.revision,reviews:job.results.map(row=>({id:row.id,status:row.review_status,note:row.review_note}))});}
      else updated=await send(`${base(id)}/${job.id}/${action.id==='cancelJob'?'cancel':'resume'}`,'POST');
      if(state.caseId===id&&state.job?.id===job.id){state.job=updated;state.reviewDirty=false;renderDetail();await refresh();}
    }catch(error){toast(error.message);}finally{busy(false);action.disabled=false;}
  };
  let previewFocus=null;
  function openSource(ref){previewFocus=document.activeElement;const page=ref.locator.match(/第\s*(\d+)\s*页/);const url=`${base()}/${state.job.id}/source?source_id=${encodeURIComponent(ref.id)}`+(page?`#page=${page[1]}`:'');$('previewTitle').textContent=ref.path+' · '+ref.locator;$('previewQuote').textContent=ref.quote;$('sourcePreview').src=url;$('sourceLink').href=url;$('preview').hidden=false;$('closePreview').focus();}
  function closePreview(){$('preview').hidden=true;$('sourcePreview').removeAttribute('src');previewFocus?.focus();previewFocus=null;}
  $('closePreview').onclick=closePreview;$('preview').onclick=event=>{if(event.target===$('preview'))closePreview();};
  document.addEventListener('keydown',event=>{if($('preview').hidden)return;if(event.key==='Escape'){event.preventDefault();closePreview();}if(event.key==='Tab'){const controls=[$('closePreview'),$('sourcePreview'),$('sourceLink')];const index=controls.indexOf(document.activeElement);if(event.shiftKey&&index===0){event.preventDefault();controls.at(-1).focus();}else if(!event.shiftKey&&index===controls.length-1){event.preventDefault();controls[0].focus();}}});
  renderInputs();busy(false);
  if(state.caseId){api(`/api/case-workflows/cases/${state.caseId}`).then(item=>selectCase(item)).catch(error=>{toast(error.message);busy(false);});}
})();
