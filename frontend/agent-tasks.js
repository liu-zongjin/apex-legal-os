(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const names = {queued:'排队中',running:'分析中',succeeded:'已交付 · 待复核',failed:'未完成',paused:'已暂停',cancelled:'已停止',interrupted:'已中断'};
  const kinds = {statement:'材料陈述',issue:'待研究争点',conflict:'矛盾候选',gap:'补证建议'};
  const state = {caseId:0,active:false,visible:true,sequence:0,job:null,models:[],model:'',projects:[],project:null,timer:null,busy:false,limit:20,offset:0};
  const drafts = new Map();
  const base = () => `/api/agent-tasks/cases/${state.caseId}/tasks`;
  const time = value => new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});
  async function api(url, options={}) {
    const response = await fetch(url, options);
    const data = await response.json().catch(()=>({}));
    if (!response.ok) throw new Error(typeof data.detail==='string'?data.detail:`操作失败（${response.status}）`);
    return data;
  }
  const send = (url, body) => api(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  function notice(message) { $('agentMessage').textContent=message; }
  function remember(id) { try { localStorage.setItem(`stella-agent-selected-${state.caseId}`,id); } catch (_) {} }
  function recalled() { try { return localStorage.getItem(`stella-agent-selected-${state.caseId}`); } catch (_) { return null; } }
  function pending(config) {
    const key=`stella-agent-request-${state.caseId}`,signature=JSON.stringify(config);
    try { const saved=JSON.parse(sessionStorage.getItem(key)||'null'); if(saved?.signature===signature)return saved.id; } catch (_) {}
    const id=crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    try { sessionStorage.setItem(key,JSON.stringify({signature,id})); } catch (_) {}
    return id;
  }
  function clearPending() { try { sessionStorage.removeItem(`stella-agent-request-${state.caseId}`); } catch (_) {} }
  function menus() {
    $('agentModelLabel').textContent=state.models.find(item=>item.value===state.model)?.label || '暂无已配置模型';
    $('agentModels').innerHTML=state.models.map(item=>`<button class="button" role="menuitemradio" aria-checked="${item.value===state.model}" type="button" data-agent-model="${esc(item.value)}">${esc(item.label)}</button>`).join('');
    $('agentProjectLabel').textContent=state.projects.find(item=>item.id===state.project)?.name || '本案材料分析';
    $('agentProjects').innerHTML=[{id:0,name:'本案材料分析'},...state.projects].map(item=>`<button class="button" role="menuitemradio" aria-checked="${(state.project||0)===item.id}" type="button" data-agent-project="${item.id}">${esc(item.name)}</button>`).join('');
  }
  async function models() {
    if(state.models.length)return;
    const data=await api('/api/agent-tasks/models');
    state.models=data.items; state.model=state.model||data.default_model; menus();
  }
  async function loadProjects(id,sequence) {
    const data=await api(`/api/agent-tasks/cases/${id}/projects`);
    if(id!==state.caseId||sequence!==state.sequence)return;
    state.projects=data.items;
    if(!state.projects.some(item=>item.id===state.project))state.project=null;
    menus();
  }
  function schedule(items=[]) {
    clearTimeout(state.timer);state.timer=null;
    if(state.active&&state.visible&&!state.busy&&items.some(item=>['queued','running'].includes(item.status)))
      state.timer=setTimeout(refresh,3000);
  }
  async function refresh() {
    if(!state.caseId||!state.active||!state.visible)return;
    const id=state.caseId,sequence=++state.sequence;
    try {
      await models();
      if(id!==state.caseId||sequence!==state.sequence)return;
      const data=await api(`${base()}?offset=${state.offset}`);
      if(id!==state.caseId||sequence!==state.sequence)return;
      $('agentHistory').innerHTML=data.items.map(item=>`<div class="task-row"><div><strong>${esc(names[item.status]||item.status)}</strong><small>${esc(time(item.created_at))} · ${esc(item.message)}</small></div><button class="button" type="button" data-agent-task="${item.id}">查看任务</button></div>`).join('')||'<p class="note">尚无材料分析任务。</p>';
      $('agentHistory').innerHTML+=`<div class="entry-controls">${state.offset?'<button class="button" type="button" data-agent-page="previous">较新记录</button>':''}${data.has_more?'<button class="button" type="button" data-agent-page="next">更早记录</button>':''}</div>`;
      const selected=state.job?.id||recalled()||data.items[0]?.id;
      if(selected) {
        const job=await api(`${base()}/${selected}`);
        if(id!==state.caseId||sequence!==state.sequence)return;
        state.job=job;remember(job.id);render();
      }
      await loadProjects(id,sequence);
      schedule([...data.items,...(state.job?[state.job]:[])]);
    } catch(error) { if(id===state.caseId&&sequence===state.sequence)notice(error.message); }
  }
  function refLink(ref,job) {
    const prefix=`/api/case-workflows/cases/${state.caseId}/tasks/${job.child_id}`;
    const url=`${prefix}/source?source_id=${encodeURIComponent(ref.id)}`;
    return `<div class="agent-reference"><a href="${url}" target="_blank" rel="noopener">${esc(ref.path)} · ${esc(ref.locator)}</a><p class="quote">${esc(ref.quote)}</p></div>`;
  }
  function render() {
    const job=state.job;if(!job){$('agentDetail').textContent='选择材料并交办后，可在这里查看任务和成果。';return;}
    const child=job.child,active=['running','queued'].includes(job.status);
    const links=!job.source_warning&&job.status==='succeeded'?(child?.artifacts||[]).map((item,index)=>`<a href="/api/case-workflows/cases/${state.caseId}/tasks/${job.child_id}/artifacts/${index}">${esc(item.name)}</a>`).join(''):'';
    const items=(child?.analysis_items||[]).slice(0,state.limit),events=(child?.timeline_events||[]).slice(0,state.limit);
    $('agentDetail').innerHTML=`<header><div><h2>${esc(names[job.status]||job.status)}</h2><p class="note">${esc(job.message)}</p></div><span class="agent-badge">待专业复核</span></header><p>${esc(job.config.goal)}</p>
      <ol class="agent-steps">${job.steps.map(step=>`<li data-step-status="${esc(step.status)}">${esc(step.label)} · ${step.status==='completed'?'已完成':step.status==='running'?'办理中':'待办理'}</li>`).join('')}</ol>
      <p class="note">任务固定模型：${esc(state.models.find(item=>item.value===job.config.model)?.label||job.config.model)}</p>
      <p class="note">所选材料 ${job.sources.length} 份 · 模型请求 ${job.calls_used}/${job.config.max_calls} 次（含重试，不等于最终账单）</p>
      ${child?.analysis_diagnostics?.length?'<p class="note">分析结果曾出现格式或引用不一致，纠正记录已保留；未通过校验的内容不会进入草稿，纠正请求计入原上限。</p>':''}
      ${job.source_warning?`<p class="warning">${esc(job.source_warning)}</p>`:''}${job.error?`<p class="warning">${esc(job.error)}</p>`:''}
      <div class="entry-controls">${active?'<button class="button" type="button" data-agent-action="pause">暂停任务</button><button class="button" type="button" data-agent-action="cancel">停止任务</button>':''}${['failed','paused','interrupted','cancelled'].includes(job.status)?'<button class="button" type="button" data-agent-action="resume">继续任务</button>':''}<button class="button" type="button" data-agent-copy>以当前设置交办后继任务</button></div>
      <div class="downloads">${links}</div>
      <details open><summary>材料处理范围</summary>${job.sources.map(source=>`<p class="note">${esc(source.path)}</p>`).join('')}<p class="note">${child?.coverage?`已解析 ${child.coverage.chunks} 个片段。`:'尚未完成解析。'}逐片段处理不保证重要事项全部发现；未找到不代表事实不存在。</p></details>
      ${events.length?`<details><summary>事实时间线（待复核）</summary>${events.map(row=>`<article class="agent-item"><strong>${esc(row.date_text||'日期不明')}</strong><p>${esc(row.description)}</p>${row.evidence.map(ref=>refLink(ref,job)).join('')}</article>`).join('')}</details>`:''}
      ${items.length?`<section><h3>关键事项与缺口（待复核）</h3>${items.map(item=>`<article class="agent-item"><strong>${esc(item.title)} · ${esc(kinds[item.type])}</strong><p>${esc(item.analysis)}</p>${item.evidence.map(ref=>refLink(ref,job)).join('')}<p class="note">后续建议：${esc(item.follow_up||'回看原文并复核')}</p></article>`).join('')}</section>`:''}
      ${Math.max(child?.analysis_items?.length||0,child?.timeline_events?.length||0)>state.limit?'<button class="button" type="button" data-agent-more>再显示20项</button>':''}
      <p class="note">草稿仅展示通过原文校验的引句；真实性、证明力、语义和法律适用仍需复核。成果依据任务固定的材料版本。</p>`;
    $('agentDetail').querySelectorAll('button').forEach(button=>button.disabled=state.busy);
  }
  async function submit(input) {
    if(state.busy)return;
    const id=state.caseId;
    state.busy=true;clearTimeout(state.timer);notice('正在交办材料分析任务…');
    try {
      const paths=[...new Set([...input.paths,...(input.draftPath?[input.draftPath]:[])])];
      const config={paths,goal:$('agentGoal').value,model:state.model,max_calls:Number($('agentMaxCalls').value),allow_cloud_ocr:input.ocr,draft:input.draft,project_id:state.project};
      const job=await send(base(),{...config,request_key:pending(config)});
      if(id!==state.caseId)return;
      clearPending();state.job=job;state.limit=20;state.offset=0;remember(job.id);render();notice('任务已保存。离开页面可继续；服务重启后请核对并继续。');
    } catch(error) { if(id===state.caseId)notice(error.message); }
    finally { state.busy=false;if(id===state.caseId)await refresh(); }
  }
  $('agentModels').onclick=event=>{const button=event.target.closest('[data-agent-model]');if(button){state.model=button.dataset.agentModel;menus();$('agentModelMenu').open=false;$('agentModelMenu').querySelector('summary').focus();}};
  $('agentProjects').onclick=event=>{const button=event.target.closest('[data-agent-project]');if(button){state.project=Number(button.dataset.agentProject)||null;menus();$('agentProjectMenu').open=false;$('agentProjectMenu').querySelector('summary').focus();}};
  document.querySelectorAll('.agent-menu').forEach(menu=>menu.addEventListener('keydown',event=>{const buttons=[...menu.querySelectorAll('button')];if(event.key==='Escape'){menu.open=false;menu.querySelector('summary').focus();}else if(['ArrowDown','ArrowUp'].includes(event.key)&&buttons.length){event.preventDefault();const i=buttons.indexOf(document.activeElement);buttons[(i+(event.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length].focus();}}));
  $('agentHistory').onclick=async event=>{if(state.busy)return;const page=event.target.closest('[data-agent-page]');if(page){state.offset=Math.max(0,state.offset+(page.dataset.agentPage==='next'?60:-60));await refresh();return;}const button=event.target.closest('[data-agent-task]');if(!button)return;state.job={id:button.dataset.agentTask};state.limit=20;await refresh();};
  $('agentDetail').onclick=async event=>{
    if(event.target.closest('[data-agent-more]')){state.limit+=20;render();return;}
    if(event.target.closest('[data-agent-copy]')){const job=state.job;state.project=job.project_id;state.model=job.config.model;$('agentGoal').value=job.config.goal;$('agentMaxCalls').value=job.config.max_calls;clearPending();menus();document.dispatchEvent(new CustomEvent('stella-agent-copy',{detail:{caseId:state.caseId,paths:job.sources.map(row=>row.path),draft:job.config.draft}}));notice('已带入原设置；请核对当前材料和上限，再交办新任务。');return;}
    const button=event.target.closest('[data-agent-action]');if(!button||state.busy||!state.job)return;
    const id=state.caseId;state.busy=true;render();
    try { const job=await send(`${base()}/${state.job.id}/${button.dataset.agentAction}`,{generation:state.job.generation});if(id===state.caseId){state.job=job;notice(job.message);} }
    catch(error){if(id===state.caseId)notice(error.message);}
    finally{state.busy=false;if(id===state.caseId){render();await refresh();}}
  };
  window.StellaAgentTasks={submit,refresh,
    setCase(id){
      if(id===state.caseId)return;
      if(state.caseId)drafts.set(state.caseId,{goal:$('agentGoal').value,project:state.project,calls:$('agentMaxCalls').value});
      const saved=drafts.get(id)||{};state.sequence++;clearTimeout(state.timer);state.caseId=id;state.job=null;state.projects=[];state.project=saved.project||null;state.limit=20;state.offset=0;
      $('agentGoal').value=saved.goal||'';$('agentMaxCalls').value=saved.calls||40;notice('');menus();render();refresh();
    },
    setActive(active){state.active=active;$('agentOptions').hidden=!active;$('agentPanel').hidden=!active;clearTimeout(state.timer);if(active)refresh();}
  };
  state.visible=window.ApexLifecycle?.active!==false;
  window.ApexLifecycle?.onChange(active=>{state.visible=active;clearTimeout(state.timer);if(active)refresh();});
  window.addEventListener('online',refresh);
})();
