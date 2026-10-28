/* Saved memories: a pinned scope, bounded requests, and explicit editing views. */
(() => {
  let state = null, busy = false, stale = false, view = 'list', filter = 'personal';
  let scope = {caseId:0}, offset = 0, editing = null, original = '', returnFocus;
  let epoch = 0, loadId = 0, searchTimer, confirmation = null, confirmFocus;
  const controllers = new Set(), expanded = new Set();
  const panel = document.createElement('div');
  panel.className = 'modal-overlay user-memory-overlay'; panel.id = 'user-memory-panel';
  panel.innerHTML = `<section class="modal user-memory-modal" role="dialog" aria-modal="true" aria-labelledby="user-memory-title">
    <header class="modal-header memory-sheet-header"><div><p class="memory-eyebrow">STELLA · AI</p><h2 id="user-memory-title">长期记忆</h2><p class="memory-sheet-subtitle">管理希望 AI 记住的偏好与背景。</p></div><button class="btn-icon" type="button" data-action="close" aria-label="关闭长期记忆">×</button></header>
    <div class="memory-workspace"><nav class="memory-nav" aria-label="记忆分类">
      <div class="memory-nav-items"><button type="button" data-action="filter" data-filter="personal"><span>个人记忆<small>跨对话使用</small></span><b data-count="personal">0</b></button><button type="button" data-action="filter" data-filter="case"><span>案件背景<small>仅当前关联案件</small></span><b data-count="case">0</b></button><button type="button" data-action="filter" data-filter="pending"><span>待确认<small>确认后才会使用</small></span><b data-count="pending">0</b></button></div>
      <button class="memory-nav-settings" type="button" data-action="settings">使用设置</button><p id="memory-nav-note">按相关性选用，不会每次全部带入。</p>
    </nav><main class="memory-main">
      <section id="memory-list-view"><div class="memory-view-heading"><div><h3 id="memory-category-title">个人记忆</h3><p id="memory-scope"></p></div><button class="btn btn-primary" type="button" data-action="add">＋ 添加记忆</button></div>
        <div class="memory-search-row"><label class="user-memory-search"><span class="memory-sr-only">搜索记忆</span><input id="memory-search" type="search" placeholder="搜索这一分类的记忆" maxlength="4000"></label><button type="button" data-action="refresh" aria-label="刷新记忆列表">刷新</button></div>
        <div id="memory-list"></div><div class="memory-pagination"><span id="memory-total"></span><button type="button" data-action="prev">上一页</button><button type="button" data-action="next">下一页</button></div>
      </section>
      <section id="memory-edit-view" hidden><button class="memory-back" type="button" data-action="back">‹ 返回列表</button><h3 id="memory-editor-title">添加记忆</h3><p id="memory-editor-scope" class="user-memory-description"></p><form id="memory-editor"><label for="memory-content">记忆内容</label><textarea id="memory-content" rows="12" maxlength="4000" placeholder="例如：回答时先给结论，再列出依据。" required></textarea><p class="user-memory-description">建议每条记录一个主题，方便以后修改和停用。已保存的内容会完整保留。</p><div class="user-memory-actions"><span id="memory-counter">0/4000</span><button type="button" data-action="cancel-edit">取消</button><button type="submit" class="btn btn-primary">保存记忆</button></div></form></section>
      <section id="memory-settings-view" hidden><h3>使用设置</h3><p class="user-memory-description">关闭使用不会删除已保存的内容。</p><div class="memory-setting-row"><label for="memory-enabled"><strong>使用长期记忆</strong><span>回答时选用相关记忆，也允许保存新的记忆。</span></label><input type="checkbox" id="memory-enabled"></div><div class="memory-setting-row"><label for="memory-auto"><strong>自动提炼记忆</strong><span>从新的对话中提炼稳定偏好与案件背景；有冲突时先放入待确认。</span></label><input type="checkbox" id="memory-auto"></div><p class="user-memory-description" id="memory-auto-note"></p><div class="memory-how"><h4>保存与使用范围</h4><p>个人记忆跨对话使用；案件背景只在明确关联该案件时使用。待确认和已停用的条目不会带入回答。</p><p>记忆保存在本机，使用时会随问题发送给所选 AI 服务。删除聊天不会删除单独保存的记忆。自动提炼与摘要整理会使用本轮模型并产生相应用量。</p></div><div class="memory-danger-zone"><div><h4>清空所有记忆</h4><p>包括个人记忆、所有案件背景和待确认内容。聊天记录仍会保留。</p></div><button class="user-memory-danger" type="button" data-action="clear">清空所有记忆</button></div></section>
      <section id="memory-versions-view" hidden><button class="memory-back" type="button" data-action="back">‹ 返回列表</button><h3>变更记录</h3><p class="user-memory-description">按保存顺序展示。状态变化也会产生版本；相同内容不会在回答中重复使用。</p><div id="memory-versions"></div></section>
    </main></div><footer class="memory-sheet-footer"><span id="memory-usage-state"></span><p id="memory-status" role="status" aria-live="polite"></p><button type="button" data-action="refresh" id="memory-retry" hidden>刷新列表</button></footer>
    <div id="memory-confirm" hidden><div role="alertdialog" aria-modal="true" aria-labelledby="memory-confirm-title" aria-describedby="memory-confirm-text"><h3 id="memory-confirm-title">确认操作</h3><p id="memory-confirm-text"></p><div class="user-memory-actions"><button type="button" data-action="cancel-delete">取消</button><button type="button" class="btn-primary" data-action="confirm-delete">确认</button></div></div></div>
  </section>`;
  document.body.appendChild(panel);
  const el = id => panel.querySelector('#'+id);
  const status = message => { el('memory-status').textContent = message; };
  const isOpen = () => panel.classList.contains('open');
  const dirty = () => view === 'edit' && el('memory-content').value !== original;
  const limit = () => state?.content_limit || 4000;
  function button(label, action, id) {
    const b = document.createElement('button'); b.type='button'; b.textContent=label; b.dataset.action=action;
    if (id != null) b.dataset.id=id; return b;
  }
  async function request(path='', method='GET', body) {
    const controller = new AbortController(); controllers.add(controller);
    const timer = setTimeout(()=>controller.abort(),12000);
    try {
      const response = await fetch('/api/user-memory'+path,{method,signal:controller.signal,headers:{'Content-Type':'application/json'},...(body!==undefined ? {body:JSON.stringify(body)} : {})});
      const data = await response.json();
      if (!response.ok) { const error = new Error(typeof data.detail==='string' ? data.detail : '记忆操作失败，请重试'); error.code=response.status; throw error; }
      return data;
    } catch (error) {
      if (error.name==='AbortError') { const failure=new Error(method==='GET' ? '加载超时，请刷新重试。' : '操作超时，保存结果尚未确认；请先刷新列表再操作。'); failure.uncertain=method!=='GET'; throw failure; }
      throw error;
    } finally {clearTimeout(timer);controllers.delete(controller);}
  }
  function controls() {
    panel.querySelectorAll('button,input,textarea').forEach(n=>{n.disabled=busy;});
    // A read failure must not allow edits against an unverified list.
    panel.querySelectorAll('[data-action=add],[data-action=edit],[data-action=status],[data-action=delete],[data-action=clear],#memory-editor button[type=submit],#memory-enabled,#memory-auto').forEach(n=>{n.disabled=busy || stale || !state;});
    el('memory-auto').disabled=busy || stale || !state?.enabled;
    el('memory-retry').hidden=!stale;
    panel.querySelector('[data-action=add]').disabled=busy || stale || !state || filter==='pending' || filter==='case' && !state.scope?.case_available;
    panel.querySelector('[data-action=prev]').disabled=busy || offset===0;
    panel.querySelector('[data-action=next]').disabled=busy || !state?.has_more;
  }
  function render() {
    for (const name of ['list','edit','settings','versions']) el('memory-'+name+'-view').hidden=view!==name;
    panel.querySelectorAll('[data-action=filter]').forEach(b=>b.setAttribute('aria-current',view!=='settings' && b.dataset.filter===filter ? 'page' : 'false'));
    panel.querySelector('[data-action=settings]').setAttribute('aria-current',view==='settings' ? 'page' : 'false');
    panel.querySelectorAll('[data-count]').forEach(n=>n.textContent=state?.counts?.[n.dataset.count] ?? '—');
    el('memory-usage-state').textContent=state ? state.enabled ? '长期记忆已开启' : '长期记忆已暂停' : '长期记忆';
    el('memory-nav-note').textContent=state?.enabled===false ? '已暂停使用与提炼。已保存内容仍保留。' : '按相关性选用，不会每次全部带入。';
    el('memory-enabled').checked=!!state?.enabled; el('memory-auto').checked=!!state?.auto_save;
    el('memory-auto-note').textContent=state?.enabled===false ? '长期记忆已暂停，自动提炼也暂停；重新开启后沿用此设置。' : '';
    el('memory-category-title').textContent=({personal:'个人记忆',case:'案件背景',pending:'待确认'})[filter];
    const caseTitle=state?.scope?.case_title;
    el('memory-scope').textContent=filter==='case' ? caseTitle || '请先在对话中聚焦或关联一个案件，再打开此页。' : filter==='pending' ? '个人记忆与当前案件中需要确认的内容。确认前不会使用。' : '称呼、写作习惯和工作偏好，在不同对话中使用。';
    el('memory-total').textContent=state ? `${state.total || 0} 条${state.total ? ' · '+(offset+1)+'–'+(offset+state.items.length) : ''}` : '';
    el('memory-list').replaceChildren();
    for (const item of state?.items || []) {
      const row=document.createElement('article'); row.className='user-memory-item';
      const heading=document.createElement('div'); heading.className='memory-item-heading';
      const title=document.createElement('strong'); title.textContent=item.subject || (item.kind==='case' ? '案件背景' : '个人记忆');
      const badge=document.createElement('span'); badge.className='memory-badge memory-badge-'+item.status;
      badge.textContent=({active:'使用中',inactive:'已停用',pending:'待确认',conflict:'存在冲突'})[item.status] || '待确认';heading.append(title,badge);
      const content=document.createElement('p');content.className='memory-item-content';content.textContent=item.content;
      const long=item.content.length>150 || item.content.split('\n').length>3;
      if (long && !expanded.has(item.id)) content.classList.add('memory-collapsed');
      row.append(heading,content);
      if (long) { const expand=button(expanded.has(item.id) ? '收起全文' : '展开全文','expand',item.id); expand.className='memory-expand';expand.setAttribute('aria-expanded',String(expanded.has(item.id)));row.append(expand); }
      const meta=document.createElement('small');
      meta.textContent=(({manual:'手动保存',chat:'从对话保存',auto:'自动提炼'})[item.source] || '已保存')+' · '+(item.updated_at || '').slice(0,16)+(item.source_deleted ? ' · 原对话已删除' : '')+(item.kind==='case' && filter==='pending' ? ' · 当前案件' : '');
      const actions=document.createElement('div');actions.className='user-memory-actions';
      actions.append(button('编辑','edit',item.id),button(item.status==='active' ? '停用' : item.status==='inactive' ? '启用' : '确认使用','status',item.id));
      if (item.source_key && item.source_message_id && !item.source_deleted) actions.append(button('查看来源','source',item.id));
      actions.append(button('变更记录','versions',item.id),button('删除','delete',item.id));
      actions.lastChild.className='user-memory-danger'; row.append(meta,actions);el('memory-list').append(row);
    }
    if (state && !state.items.length) {
      const empty=document.createElement('div');empty.className='memory-empty';
      const heading=document.createElement('h4'),description=document.createElement('p');
      heading.textContent=el('memory-search').value.trim() ? '没有匹配的记忆' : filter==='case' && !state.scope?.case_available ? '尚未关联案件' : filter==='pending' ? '没有待确认内容' : '还没有保存记忆';
      description.textContent=filter==='case' && !state.scope?.case_available ? '回到对话，选择一个案件后即可管理它的专属背景。' : filter==='pending' ? '需要你确认的新内容或冲突内容会出现在这里。' : '可以添加常用偏好，也可以在对话中说“记住：……”来保存。';
      if (el('memory-search').value.trim()) description.textContent='试试其他关键词，或清空搜索查看全部内容。';
      empty.append(heading,description);el('memory-list').append(empty);
    }
    controls();
  }
  async function load(message='') {
    const run=++loadId, opened=epoch;
    const query=new URLSearchParams({kind:filter,case_id:String(scope.caseId || 0),q:el('memory-search').value,limit:'40',offset:String(offset)});
    status('正在加载…');
    try {
      const data=await request('?'+query);
      if (!isOpen() || opened!==epoch || run!==loadId) return false;
      state=data;stale=false;render();status(message);return true;
    } catch(error) {
      if (opened===epoch && run===loadId && isOpen()) {stale=true;render();status(error.message);}
      return false;
    }
  }
  async function mutate(operation,message,onSuccess) {
    if(busy || stale || !state) return;
    busy=true;controls();status('正在保存…');
    let saved=false;
    try { await operation(); saved=true;onSuccess?.(); await load(message); if(stale) status(message+' 列表未能刷新，请点击刷新后继续。'); }
    catch(error) { if(error.code===409 || error.uncertain) stale=true;status(error.message); }
    finally {busy=false;render();}
    return saved;
  }
  function ask(text,action,label='确认删除') {
    confirmation=action;confirmFocus=document.activeElement;el('memory-confirm-text').textContent=text;
    el('memory-confirm-title').textContent=label==='放弃修改' ? '有尚未保存的修改' : '确认删除';
    panel.querySelector('[data-action=confirm-delete]').textContent=label;el('memory-confirm').hidden=false;
    panel.querySelector('[data-action=cancel-delete]').focus();
  }
  function cancelConfirm() {confirmation=null;el('memory-confirm').hidden=true;confirmFocus?.focus();}
  function leave(action) {if(dirty()) ask('修改尚未保存。放弃修改并离开？',action,'放弃修改');else action();}
  function close() {
    if(busy) return;
    leave(()=>{++epoch;++loadId;clearTimeout(searchTimer);controllers.forEach(c=>c.abort());panel.classList.remove('open');confirmation=null;el('memory-confirm').hidden=true;returnFocus?.focus();});
  }
  function edit(item) {
    editing=item || null;original=item?.content || '';el('memory-content').value=original;view='edit';
    el('memory-content').maxLength=limit();el('memory-counter').textContent=Array.from(original).length+'/'+limit();
    el('memory-editor-title').textContent=item ? '编辑记忆' : '添加记忆';
    el('memory-editor-scope').textContent=(item?.kind || filter)==='case' ? '仅用于：'+(state.scope?.case_title || '当前案件') : '保存到个人记忆，在不同对话中使用。';
    render();el('memory-content').focus();
  }
  window.openUserMemory=async()=>{
    if(busy || isOpen())return;
    returnFocus=document.activeElement;scope={...(window.getAiContextLocation?.() || {caseId:0})};
    ++epoch;state=null;stale=true;view='list';filter='personal';offset=0;editing=null;expanded.clear();
    el('memory-search').value='';panel.classList.add('open');render();panel.querySelector('[data-action=close]').focus();await load();
  };
  panel.addEventListener('click',event=>{
    if(event.target===panel) return close();
    const b=event.target.closest('[data-action]');if(!b || busy)return;
    const a=b.dataset.action,item=state?.items.find(i=>i.id===Number(b.dataset.id));
    if(a==='cancel-delete')return cancelConfirm();
    if(a==='confirm-delete'){const next=confirmation;cancelConfirm();return next?.();}
    if(confirmation)return;
    if(a==='close')return close();
    if(a==='filter')return leave(()=>{filter=b.dataset.filter;view='list';offset=0;el('memory-search').value='';render();load();});
    if(a==='settings')return leave(()=>{view='settings';render();});
    if(a==='back' || a==='cancel-edit')return leave(()=>{view='list';render();});
    if(a==='refresh')return load('已刷新。');
    if(a==='add')return edit();
    if(a==='edit' && item)return edit(item);
    if(a==='expand' && item){if(expanded.has(item.id))expanded.delete(item.id);else expanded.add(item.id);render();panel.querySelector(`[data-action=expand][data-id="${item.id}"]`)?.focus();}
    if(a==='status' && item)mutate(()=>request('/'+item.id+'/status','PUT',{status:item.status==='active' ? 'inactive' : 'active',version:item.version}),'记忆状态已更新。');
    if(a==='source' && item){close();window.openAiContextSource?.(item.source_key,item.source_message_id);}
    if(a==='delete' && item)ask('删除这条记忆及其变更记录？此操作无法撤销，聊天记录仍会保留。',()=>mutate(()=>request('/'+item.id+'?version='+item.version,'DELETE'),'已删除记忆。',()=>{if(state.items.length===1 && offset)offset=Math.max(0,offset-40);}));
    if(a==='clear')ask('清空个人记忆、所有案件背景和待确认内容及其变更记录？此操作无法撤销，聊天记录仍会保留。',()=>mutate(()=>request('?revision='+state.revision,'DELETE'),'已删除记忆。',()=>{offset=0;}));
    if(a==='prev' || a==='next'){offset=Math.max(0,offset+(a==='next' ? 40 : -40));load();}
    if(a==='versions' && item) {
      const opened=epoch,ticket=++loadId;view='versions';render();el('memory-versions').replaceChildren();status('正在加载变更记录…');
      request('/'+item.id+'/versions').then(data=>{
        if(opened!==epoch || ticket!==loadId || view!=='versions')return;
        for(const v of [{...item,current:true},...data.items]){const row=document.createElement('article');row.className='user-memory-item';const h=document.createElement('strong');h.textContent=(v.current ? '当前版本' : '历史版本')+' · '+v.version;const p=document.createElement('p');p.textContent=v.content;row.append(h,p);el('memory-versions').append(row);}status('');
      }).catch(e=>{if(opened===epoch && ticket===loadId && view==='versions')status(e.message);});
    }
  });
  panel.addEventListener('keydown',event=>{
    if(event.key==='Escape'){event.preventDefault();event.stopPropagation();if(confirmation)cancelConfirm();else close();}
    if(event.key!=='Tab')return;
    const root=confirmation ? el('memory-confirm') : panel;
    const nodes=[...root.querySelectorAll('button,input,textarea,[tabindex="0"]')].filter(n=>!n.disabled && n.getClientRects().length);
    if(!nodes.length){event.preventDefault();return;}
    const first=nodes[0],last=nodes[nodes.length-1];
    if(event.shiftKey && (document.activeElement===first || !root.contains(document.activeElement))){event.preventDefault();last.focus();}
    if(!event.shiftKey && (document.activeElement===last || !root.contains(document.activeElement))){event.preventDefault();first.focus();}
  });
  el('memory-search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{offset=0;load();},200);});
  el('memory-content').addEventListener('input',()=>{el('memory-counter').textContent=Array.from(el('memory-content').value).length+'/'+limit();});
  el('memory-editor').addEventListener('submit',async event=>{
    event.preventDefault();if(busy)return;
    const content=el('memory-content').value.trim();if(!content)return status('请输入记忆内容。');
    const kind=editing?.kind || (filter==='case' ? 'case' : 'personal'),case_id=kind==='case' ? editing?.case_id || scope.caseId || 0 : 0;
    if(kind==='case' && !case_id)return status('请先关联一个明确案件。');
    await mutate(()=>request(editing ? '/'+editing.id : '',editing ? 'PUT' : 'POST',{content,kind,case_id,version:editing?.version}),'记忆已保存。',()=>{original=content;view='list';offset=0;el('memory-search').value='';});
  });
  for(const id of ['memory-enabled','memory-auto'])el(id).addEventListener('change',()=>{
    const body={enabled:el('memory-enabled').checked,auto_save:el('memory-auto').checked,revision:state?.revision};
    mutate(()=>request('/settings','PUT',body),'设置已保存。');
  });
})();

// A small, on-demand inspector; no background polling while hidden.
(() => {
  let state, usage, location, returnFocus, busy = false;
  const panel = document.createElement('div');
  panel.className = 'modal-overlay user-memory-overlay';
  panel.id = 'ai-context-panel';
  panel.innerHTML = `<section class="modal user-memory-modal" role="dialog" aria-modal="true" aria-labelledby="ai-context-title">
    <div class="modal-header memory-sheet-header"><div><p class="memory-eyebrow">STELLA · AI</p><h2 id="ai-context-title">上下文</h2><p class="memory-sheet-subtitle">看清这次回答，带入了哪些背景。</p></div><button type="button" class="btn-icon" data-context-action="close" aria-label="关闭上下文">×</button></div>
    <div class="memory-sheet-content"><p class="user-memory-description">历史和摘要用于延续工作，不能代替案件证据或法律依据。只处理升级后的新消息。</p>
    <label class="user-memory-request-toggle"><input type="checkbox" id="context-recall">在此对话召回相关历史</label>
    <p id="context-scope" class="user-memory-description"></p>
    <div id="context-items"></div>
    <label class="user-memory-search">当前对话摘要<textarea id="context-summary" rows="7" maxlength="1800" placeholder="对话较长时自动生成；也可手动补充任务与约定。"></textarea></label>
    <div id="context-summary-sources"></div>
    <p id="context-status" role="status" aria-live="polite"></p>
    </div><div class="user-memory-actions memory-sheet-footer"><button type="button" data-context-action="refresh">刷新状态</button><button type="button" data-context-action="rebuild">重建摘要／重试整理</button><button type="button" class="btn-primary" data-context-action="save">保存更改</button></div>
  </section>`;
  document.body.appendChild(panel);
  const el = id => panel.querySelector('#'+id);
  const status = text => { el('context-status').textContent = text; };
  async function request(method='GET', suffix='', body) {
    const response = await fetch('/api/ai-context'+suffix+'?history_key='+encodeURIComponent(location.historyKey), {method,headers:{'Content-Type':'application/json'},...(body ? {body:JSON.stringify(body)} : {})});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '上下文操作失败');
    return data;
  }
  function close() { if (!busy) { panel.classList.remove('open'); returnFocus?.focus(); } }
  function sourceLink(key,mid,label) {
    const button = document.createElement('button'); button.type = 'button'; button.textContent = label;
    button.onclick = () => { close(); window.openAiContextSource?.(key,mid); }; return button;
  }
  async function refresh() {
    state = await request();
    panel.querySelectorAll('input,textarea,[data-context-action=save],[data-context-action=rebuild]').forEach(n => {n.disabled=false;});
    el('context-recall').checked = !!state.recall_enabled;
    el('context-summary').value = state.summary;
    el('context-scope').textContent = `当前范围：${state.case_id > 0 ? '案件 '+state.case_id : state.case_id < 0 ? '多案件对话（不参与跨对话召回）' : '非案件对话'} · 摘要 v${state.summary_version}${state.summary_manual ? ' · 已固定，重建后恢复自动更新' : ''}${usage?.enabled === false ? ' · 该回答未使用长期记忆或跨对话召回' : ''}${usage?.omitted_recent ? ' · 部分较早消息未直接带入' : ''}`;
    const excluded = new Set(JSON.parse(state.excluded_json));
    el('context-items').replaceChildren();
    for (const item of usage?.items || []) {
      const row = document.createElement('article'); row.className = 'user-memory-item';
      const title = document.createElement('strong');
      title.textContent = ({memory:'长期记忆',summary:'对话摘要',recall:'相关历史',recent:'本对话原文'})[item.type];
      const details = document.createElement('details'); details.className='context-source-detail';
      const summary = document.createElement('summary');
      const preview = document.createElement('span'); preview.textContent = item.content.slice(0,72)+(item.content.length>72 ? '…' : '');
      summary.append(title,preview);
      const text = document.createElement('p'); text.textContent = item.content;
      details.append(summary,text); row.append(details);
      const actions = document.createElement('div'); actions.className = 'user-memory-actions';
      {
        const label = document.createElement('label'), checkbox = document.createElement('input'); checkbox.type='checkbox';
        checkbox.dataset.exclude = item.type === 'summary' ? 'summary' : item.type === 'memory' ? `memory:${item.id}` : `message:${item.id}`;
        checkbox.checked = excluded.has(checkbox.dataset.exclude); label.append(checkbox,'后续提问排除此项'); actions.append(label);
      }
      const sourceKey = item.history_key || item.source_key || location.historyKey;
      const sourceId = item.source_message_id || (item.type !== 'memory' ? item.id : '');
      if (sourceId) actions.append(sourceLink(sourceKey,sourceId,'查看来源'));
      details.append(actions); el('context-items').append(row);
    }
    el('context-summary-sources').replaceChildren();
    for (const item of state.summary_sources || []) el('context-summary-sources').append(sourceLink(location.historyKey,item.id,`来源：${item.content.slice(0,40)}`));
    status((state.jobs || []).length ? state.jobs.map(j => ({pending:'等待整理',running:'正在整理',complete:'整理完成',failed:'整理失败，可重试',cancelled:'内容已变化，整理已取消'})[j.state]+(j.error ? '：'+j.error : '')).filter((x,i,a) => a.indexOf(x)===i).join('；') : '暂无后台整理任务。');
  }
  window.openAiContext = async (selectedUsage) => {
    if (panel.classList.contains('open')) return;
    location = window.getAiContextLocation?.();
    if (!location) return;
    usage = selectedUsage || location.usage;
    if (selectedUsage?.history_key) location.historyKey = selectedUsage.history_key;
    returnFocus = document.activeElement;
    state = null;
    panel.querySelectorAll('input,textarea,[data-context-action=save],[data-context-action=rebuild]').forEach(n => {n.disabled=true;});
    panel.classList.add('open'); el('context-items').replaceChildren(); el('context-summary').value=''; status('正在加载…');
    panel.querySelector('button').focus();
    try { await refresh(); } catch(e) { status(e.message); }
  };
  panel.addEventListener('click',async event => {
    if (event.target === panel) return close();
    const action = event.target.closest('[data-context-action]')?.dataset.contextAction;
    if (!action || busy) return;
    if (action === 'close') return close();
    busy=true;
    panel.querySelectorAll('button').forEach(b => {b.disabled=true;});
    try {
      if (action === 'save' && state) {
        const excluded = new Set(JSON.parse(state.excluded_json));
        panel.querySelectorAll('[data-exclude]').forEach(node => node.checked ? excluded.add(node.dataset.exclude) : excluded.delete(node.dataset.exclude));
        const summary = el('context-summary').value;
        const result = await request('PUT','',{version:state.version,recall_enabled:el('context-recall').checked,excluded:[...excluded],...(summary !== state.summary ? {summary} : {})});
      }
      if (action === 'rebuild') {
        if (el('context-summary').value !== state.summary) throw new Error('请先保存摘要修改，再重建。');
        await request('POST','/rebuild');
      }
      if (action === 'refresh' && state && el('context-summary').value !== state.summary) throw new Error('请先保存摘要修改，再刷新。');
      await refresh();
    } catch(e) { status(e.message); }
    finally { busy=false; panel.querySelectorAll('button').forEach(b => {b.disabled=false;}); if (!state) panel.querySelectorAll('[data-context-action=save],[data-context-action=rebuild]').forEach(b => {b.disabled=true;}); }
  });
  panel.addEventListener('keydown',event => {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); }
    if (event.key !== 'Tab') return;
    const nodes = [...panel.querySelectorAll('button,input,textarea')].filter(n => !n.disabled && n.getClientRects().length);
    if (!nodes.length) return;
    if (event.shiftKey && document.activeElement === nodes[0]) {event.preventDefault();nodes.at(-1).focus();}
    else if (!event.shiftKey && document.activeElement === nodes.at(-1)) {event.preventDefault();nodes[0].focus();}
  });
})();

(() => {
  const watching = new Map();
  window.watchAiContextJob = (key,mid) => {
    const id=key+':'+mid;
    if (watching.has(id)) return;
    let count=0;
    const poll=async () => {
      if (document.hidden || window.getAiContextLocation?.().historyKey !== key || !document.getElementById('ask-panel')?.getClientRects().length || count++ >= 30) { watching.delete(id); return; }
      try {
        const response=await fetch('/api/ai-context?history_key='+encodeURIComponent(key));
        if (!response.ok) { watching.delete(id); return; }
        const data=await response.json();
        const job=data.jobs?.find(j => j.message_id === mid);
        if (!job || ['complete','failed','cancelled'].includes(job.state)) {
          const updates=data.memory_updates?.filter(m => m.source_message_id === mid) || [];
          if (job?.state === 'failed') window.showToast?.('背景整理失败，可在“上下文”中重试','warning');
          else if (updates.some(m => ['pending','conflict'].includes(m.status))) window.showToast?.('发现记忆冲突，请在“长期记忆”中确认','warning');
          else if (updates.length) window.showToast?.('长期记忆已更新，可查看来源和变更记录','success');
          watching.delete(id); return;
        }
      } catch (_) { watching.delete(id); return; }
      watching.set(id,setTimeout(poll,3000));
    };
    watching.set(id,setTimeout(poll,2000));
  };
})();
