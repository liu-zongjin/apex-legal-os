(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const names = {queued:'排队中',running:'分析中',succeeded:'已交付 · 待复核',failed:'未完成',paused:'已暂停',cancelled:'已停止',interrupted:'已中断'};
  const kinds = {statement:'材料陈述',issue:'待研究争点',conflict:'矛盾候选',gap:'补证建议'};
  const state = {caseId:0,active:false,visible:true,sequence:0,job:null,models:[],model:'',projects:[],project:null,timer:null,busy:false,limit:6,offset:0,view:'focus',delivered:null};
  const drafts = new Map();
  const base = () => `/api/agent-tasks/cases/${state.caseId}/tasks`;
  const time = value => new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});
  async function api(url, options={}) {
    const response = await fetch(url, options);
    const data = await response.json().catch(()=>({}));
    if (!response.ok) {const error=new Error(typeof data.detail==='string'?data.detail:`操作失败（${response.status}）`);error.status=response.status;throw error;}
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
      $('agentHistory').innerHTML=data.items.map(item=>`<div class="task-row"><div><strong>${esc(item.config?.goal||'材料分析')}</strong><small>${esc(time(item.created_at))} · ${esc(names[item.status]||item.status)}</small></div><button class="button" type="button" data-agent-task="${item.id}">查看结果</button></div>`).join('')||'<p class="note">还没有分析记录。选择材料后即可开始。</p>';
      $('agentHistoryCount').textContent=data.items.length?` · ${state.offset+1}—${state.offset+data.items.length}`:'';
      $('agentHistory').innerHTML+=`<div class="entry-controls">${state.offset?'<button class="button" type="button" data-agent-page="previous">较新记录</button>':''}${data.has_more?'<button class="button" type="button" data-agent-page="next">更早记录</button>':''}</div>`;
      const selected=state.job?.id||recalled()||data.items[0]?.id;
      if(selected) {
        let job;
        try {job=await api(`${base()}/${selected}`);}
        catch(error){
          if(error.status!==404)throw error;
          const fallback=data.items[0]?.id;
          job=fallback&&fallback!==selected?await api(`${base()}/${fallback}`):null;
        }
        if(id!==state.caseId||sequence!==state.sequence)return;
        state.job=job;if(job)remember(job.id);render();
      }
      await loadProjects(id,sequence);
      schedule([...data.items,...(state.job?[state.job]:[])]);
    } catch(error) { if(id===state.caseId&&sequence===state.sequence)notice(error.message); }
  }
  const filename = path => String(path||'').split('/').pop();
  function refLink(ref,job) {
    const prefix=`/api/case-workflows/cases/${state.caseId}/tasks/${job.child_id}`;
    const page=String(ref.locator||'').match(/第\s*(\d+)\s*页/);
    const url=`${prefix}/source?source_id=${encodeURIComponent(ref.id)}${page?'#page='+page[1]:''}`;
    return `<div class="agent-reference"><a href="${url}" title="${esc(ref.path)}" target="_blank" rel="noopener">${esc(filename(ref.path))} · ${esc(ref.locator)} · 打开原件</a><blockquote class="quote">${esc(ref.quote)}</blockquote></div>`;
  }
  function evidence(refs,job) {
    const unique=[...new Map(refs.map(ref=>[JSON.stringify([ref.path,ref.locator,ref.quote]),ref])).values()];
    return unique.length?`<details class="agent-evidence"><summary>查看依据 · ${esc(filename(unique[0].path))} · ${esc(unique[0].locator)}${unique.length>1?` 等 ${unique.length} 处`:''}</summary>${unique.map(ref=>refLink(ref,job)).join('')}</details>`:'';
  }
  function render() {
    const job=state.job;if(!job){$('agentDetail').innerHTML='<h2>从材料中找出需要关注的问题</h2><p class="note">先添加材料，再点击“开始分析”。完成后在这里查看重点、时间线和可下载的报告。</p>';return;}
    const child=job.child,active=['running','queued'].includes(job.status);
    const newlyDelivered=job.status==='succeeded'&&state.delivered!==job.id;
    if(newlyDelivered){$('inputStage').open=false;state.delivered=job.id;notice('');}
    document.body.classList.toggle('reviewing-result',job.status==='succeeded');
    const artifacts=!job.source_warning&&job.status==='succeeded'?(child?.artifacts||[]):[];
    const primary=new Set(['材料分析草稿.docx','事实时间轴.pdf','事实经过表.xlsx']);
    const link=(item,index)=>`<a href="/api/case-workflows/cases/${state.caseId}/tasks/${job.child_id}/artifacts/${index}">${esc(item.name)}</a>`;
    const mainLinks=[...primary].map(name=>{const index=artifacts.findIndex(item=>item.name===name);return index<0?'':link(artifacts[index],index);}).join('');
    const otherLinks=artifacts.map((item,index)=>!primary.has(item.name)?link(item,index):'').join('');
    const all=child?.analysis_items||[],events=child?.timeline_events||[];
    const focus=all.filter(item=>item.type!=='statement'),statements=all.filter(item=>item.type==='statement');
    if(newlyDelivered&&state.view==='focus'&&!focus.length)state.view=statements.length?'statement':events.length?'timeline':'focus';
    const selected=state.view==='timeline'?events:state.view==='statement'?statements:focus;
    const items=selected.slice(0,state.limit);
    const views=[['focus','待关注',focus.length],['statement','材料要点',statements.length],['timeline','时间线',events.length]];
    $('agentDetail').innerHTML=`<header><div><p class="eyebrow">${esc(time(job.created_at))} · ${job.sources.length} 份材料</p><h2>${job.status==='succeeded'?'分析结果 · ':''}${esc(names[job.status]||job.status)}</h2></div><button class="button" type="button" data-agent-copy>沿用材料再分析</button></header>
      <p class="agent-goal">${esc(job.config.goal)}</p>
      ${job.source_warning?`<p class="warning">${esc(job.source_warning)}</p>`:''}${job.error?`<p class="warning">${esc(job.error)}</p>`:''}
      ${active?`<div class="agent-progress" role="status"><strong>${esc(job.message)}</strong><p class="note">可以离开此页，稍后从上方“分析记录”找回。服务重启后可继续。</p><div class="entry-controls"><button class="button" type="button" data-agent-action="pause">暂停</button><button class="button" type="button" data-agent-action="cancel">停止</button></div></div>`:''}
      ${['failed','paused','interrupted','cancelled'].includes(job.status)?'<button class="button primary" type="button" data-agent-action="resume">继续分析</button><p class="note">已完成的步骤会保留。</p>':''}
      ${mainLinks?`<div class="downloads agent-downloads" aria-label="下载分析成果">${mainLinks}</div>`:''}
      ${all.length||events.length?`<nav class="agent-views" aria-label="分析结果分类">${views.map(([value,label,count])=>`<button class="button" type="button" data-agent-view="${value}" aria-pressed="${state.view===value}">${label}<span>${count}</span></button>`).join('')}</nav><section class="agent-findings"><h3>${state.view==='focus'?'关键事项与缺口（待复核）':state.view==='timeline'?'事实时间线（待复核）':'材料要点（材料陈述，待复核）'}</h3>${items.map((item,index)=>`<article class="agent-item"><div class="agent-item-heading"><span class="agent-number">${index+1}</span><strong>${esc(state.view==='timeline'?(item.date_text||'日期不明'):item.title)}</strong>${item.type?`<span class="agent-badge">${esc(kinds[item.type])}</span>`:''}</div><p>${esc(state.view==='timeline'?item.description:item.analysis)}</p>${item.follow_up?`<p class="agent-next"><strong>下一步</strong> ${esc(item.follow_up)}</p>`:''}${evidence(item.evidence,job)}</article>`).join('')||'<p class="note">本次未返回此类事项。可切换查看材料要点或时间线；未发现不代表不存在。</p>'}</section>${selected.length>state.limit?`<button class="button" type="button" data-agent-more>继续查看 · 还有 ${selected.length-state.limit} 项</button>`:''}`:job.status==='succeeded'?'<p class="note">本次未返回通过校验的分析事项。请回看材料，或缩小范围重新分析；这不代表没有问题。</p>':''}
      <p class="note agent-review-note">以上为基于本次材料的待复核草稿。点击“查看依据”核对原文；不自动写入案件事实。</p>
      <details class="agent-audit"><summary>分析详情与其他格式</summary><p class="note">任务固定模型：${esc(state.models.find(item=>item.value===job.config.model)?.label||job.config.model)} · 请求 ${job.calls_used}/${job.config.max_calls} 次（含重试，不等于最终账单）</p>
      <ol class="agent-steps">${job.steps.map(step=>`<li data-step-status="${esc(step.status)}">${esc(step.label)} · ${step.status==='completed'?'已完成':step.status==='running'?'办理中':'待办理'}</li>`).join('')}</ol>
      ${child?.analysis_diagnostics?.length?'<p class="note">格式或引用曾不一致，纠正记录已保留；未通过校验的内容不进入草稿。</p>':''}
      <h3>本次材料</h3>${job.sources.map(source=>`<p class="note">${esc(source.path)}</p>`).join('')}<p class="note">${child?.coverage?`已解析 ${child.coverage.chunks} 个片段。${child.coverage.layout_exclusions===undefined?'旧任务保留原解析底稿；需要重新识别时请沿用材料再分析。':`排除 ${child.coverage.layout_exclusions} 行可识别的页眉页脚。`}`:'尚未完成解析。'}未找到不代表事实不存在。原件与固定版本的引用保留。</p>${otherLinks?`<div class="downloads">${otherLinks}</div>`:''}</details>`;
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
      clearPending();state.job=job;state.limit=6;state.view='focus';state.offset=0;remember(job.id);$('inputStage').open=false;render();$('agentPanel').scrollIntoView({block:'start'});notice('分析已开始，进度和结果会自动更新。');
    } catch(error) { if(id===state.caseId)notice(error.message); }
    finally { state.busy=false;if(id===state.caseId)await refresh(); }
  }
  $('agentModels').onclick=event=>{const button=event.target.closest('[data-agent-model]');if(button){state.model=button.dataset.agentModel;menus();$('agentModelMenu').open=false;$('agentModelMenu').querySelector('summary').focus();}};
  $('agentProjects').onclick=event=>{const button=event.target.closest('[data-agent-project]');if(button){state.project=Number(button.dataset.agentProject)||null;menus();$('agentProjectMenu').open=false;$('agentProjectMenu').querySelector('summary').focus();}};
  document.querySelectorAll('.agent-menu').forEach(menu=>menu.addEventListener('keydown',event=>{const buttons=[...menu.querySelectorAll('button')];if(event.key==='Escape'){menu.open=false;menu.querySelector('summary').focus();}else if(['ArrowDown','ArrowUp'].includes(event.key)&&buttons.length){event.preventDefault();const i=buttons.indexOf(document.activeElement);buttons[(i+(event.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length].focus();}}));
  $('agentHistory').onclick=async event=>{if(state.busy)return;const page=event.target.closest('[data-agent-page]');if(page){state.offset=Math.max(0,state.offset+(page.dataset.agentPage==='next'?60:-60));await refresh();return;}const button=event.target.closest('[data-agent-task]');if(!button)return;state.job={id:button.dataset.agentTask};state.limit=6;state.view='focus';await refresh();$('agentRecords').open=false;$('agentPanel').scrollIntoView({block:'start'});};
  $('agentNew').onclick=()=>{$('inputStage').open=true;$('inputStage').scrollIntoView({block:'start'});$('agentGoal').focus({preventScroll:true});notice('选择要分析的材料，已有选择可移出或补充。');};
  $('agentDetail').onclick=async event=>{
    const view=event.target.closest('[data-agent-view]');if(view){state.view=view.dataset.agentView;state.limit=6;render();$('agentDetail').querySelector(`[data-agent-view="${state.view}"]`).focus({preventScroll:true});return;}
    if(event.target.closest('[data-agent-more]')){state.limit+=6;render();return;}
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
      const saved=drafts.get(id)||{};state.sequence++;clearTimeout(state.timer);state.caseId=id;state.job=null;state.delivered=null;state.projects=[];state.project=saved.project||null;state.limit=6;state.view='focus';state.offset=0;
      $('agentGoal').value=saved.goal||'';$('agentMaxCalls').value=saved.calls||40;notice('');menus();render();refresh();
    },
    setActive(active){state.sequence++;state.active=active;$('agentOptions').hidden=!active;$('agentPanel').hidden=!active;$('agentToolbar').hidden=!active;clearTimeout(state.timer);if(active)refresh();}
  };
  state.visible=window.ApexLifecycle?.active!==false;
  window.ApexLifecycle?.onChange(active=>{state.visible=active;clearTimeout(state.timer);if(active)refresh();});
  window.addEventListener('online',refresh);
})();
