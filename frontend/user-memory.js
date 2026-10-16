/* Saved user memories share the main AI workspace, including case AI. */
(() => {
  let state = null, busy = false, editing = null, returnFocus = null, filter = 'personal';
  const panel = document.createElement('div');
  panel.className = 'modal-overlay user-memory-overlay';
  panel.id = 'user-memory-panel';
  panel.innerHTML = `<section class="modal user-memory-modal" role="dialog" aria-modal="true" aria-labelledby="user-memory-title">
    <div class="modal-header memory-sheet-header"><div><p class="memory-eyebrow">STELLA · AI</p><h2 id="user-memory-title">长期记忆</h2><p class="memory-sheet-subtitle">个人偏好与案件背景，各归其位。</p></div><button class="btn-icon" type="button" data-action="close" aria-label="关闭长期记忆">×</button></div>
    <div class="memory-sheet-content"><details class="memory-privacy"><summary>记忆如何使用</summary><p class="user-memory-description">个人偏好跨对话使用，案件记忆仅在明确关联的案件内使用。记忆保存在本机，使用时会随问题发送给所选 AI 服务。删除聊天不删除单独保存的记忆。</p>    <p class="user-memory-description memory-footnote">仅从升级后的新消息提炼，案件信息标为“用户提供”。冲突内容暂停使用，等待确认；不处理升级前的旧聊天。摘要与提炼会使用本轮模型并产生相应用量。</p></details>
    <div class="user-memory-settings">
      <label><input type="checkbox" id="memory-enabled"> 使用长期记忆</label>
      <label><input type="checkbox" id="memory-auto"> 自动提炼记忆</label>
    </div>

    <div class="user-memory-actions memory-filters" role="group" aria-label="记忆分类"><button type="button" data-action="filter" data-filter="personal">个人偏好</button><button type="button" data-action="filter" data-filter="case">当前案件</button><button type="button" data-action="filter" data-filter="pending">待确认</button></div>
    <details class="memory-compose"><summary>添加记忆<span aria-hidden="true">＋</span></summary><form id="memory-editor"><label for="memory-content">添加记忆</label><textarea id="memory-content" maxlength="500" rows="3" placeholder="例如：称呼我为刘律师；回答时先给结论，再列依据。" required></textarea><div class="user-memory-actions"><span id="memory-counter">0/500</span><button type="button" data-action="cancel-edit" hidden>取消编辑</button><button type="submit" class="btn btn-primary">保存记忆</button></div></form></details>
    <label class="user-memory-search">搜索记忆<input id="memory-search" type="search" placeholder="搜索已保存的内容"></label>
    <p id="memory-status" role="status" aria-live="polite"></p>
    <div id="memory-list"></div>
    </div><div class="user-memory-actions memory-sheet-footer"><span id="memory-total"></span><button type="button" class="user-memory-danger" data-action="clear">清空所有记忆</button></div>
    <div id="memory-confirm" hidden><p id="memory-confirm-text"></p><div class="user-memory-actions"><button type="button" data-action="cancel-delete">取消</button><button type="button" class="user-memory-danger" data-action="confirm-delete">确认删除</button></div></div>
  </section>`;
  document.body.appendChild(panel);
  const el = id => panel.querySelector(`#${id}`);
  let pendingDelete = null;
  function status(message) { el('memory-status').textContent = message; }
  async function request(path = '', method = 'GET', body) {
    if (!path && method === 'GET') path = '?kind='+encodeURIComponent(filter)+'&case_id='+(window.getAiContextLocation?.().caseId || 0);
    const response = await fetch('/api/user-memory' + path, {
      method, headers: { 'Content-Type': 'application/json' },
      ...(body !== undefined ? {body: JSON.stringify(body)} : {})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '记忆操作失败，请重试');
    return data;
  }
  function edit(item = null) {
    editing = item?.id ?? null;
    panel.querySelector('.memory-compose').open = !!item;
    el('memory-content').value = item?.content || '';
    panel.querySelector('label[for="memory-content"]').textContent = item ? '编辑记忆' : '添加记忆';
    panel.querySelector('[data-action="cancel-edit"]').hidden = !item;
    el('memory-counter').textContent = `${el('memory-content').value.length}/500`;
  }
  function render() {
    if (!state) return;
    el('memory-enabled').checked = state.enabled;
    el('memory-auto').checked = state.auto_save;
    el('memory-auto').disabled = !state.enabled || busy;
    const cid = window.getAiContextLocation?.().caseId || 0;
    const visible = state.items.filter(item => filter === 'pending' ? ['pending','conflict'].includes(item.status) && (item.kind === 'personal' || item.case_id === cid && cid > 0) : item.kind === filter && (filter !== 'case' || cid > 0 && item.case_id === cid));
    el('memory-total').textContent = `${visible.length} 条记忆${filter === 'case' && !cid ? ' · 请先关联一个明确案件' : ''}`;
    panel.querySelectorAll('[data-action=filter]').forEach(button => { button.setAttribute('aria-pressed', String(button.dataset.filter === filter)); });
    const search = el('memory-search').value.trim().toLocaleLowerCase();
    const items = visible.filter(item => item.content.toLocaleLowerCase().includes(search));
    el('memory-list').replaceChildren();
    if (!items.length) {
      const empty = document.createElement('p');
      empty.className = 'user-memory-description';
      empty.textContent = search ? '没有匹配的记忆。' : '暂无长期记忆。添加后，新对话也会记得。';
      el('memory-list').appendChild(empty);
    }
    for (const item of items) {
      const row = document.createElement('article'); row.className = 'user-memory-item';
      const content = document.createElement('p'); content.textContent = item.content;
      const meta = document.createElement('small');
      meta.textContent = `${({manual:'手动保存',chat:'对话保存',auto:'自动提炼'})[item.source] || '已保存'} · ${item.attribution || '用户提供'} · ${({active:'使用中',inactive:'已停用',pending:'待确认',conflict:'存在冲突'})[item.status] || ''} · v${item.version} · ${item.updated_at}${item.source_deleted ? ' · 原对话已删除' : ''}`;
      const actions = document.createElement('div'); actions.className = 'user-memory-actions';
      for (const [label, action] of [['编辑', 'edit'], [item.status === 'active' ? '停用' : '确认使用', 'status'], ['变更记录','versions'], ...(item.source_key && !item.source_deleted ? [['查看来源','source']] : []), ['删除', 'delete']]) {
        const button = document.createElement('button'); button.type = 'button'; button.textContent = label;
        button.dataset.action = action; button.dataset.id = item.id; button.disabled = busy;
        actions.appendChild(button);
      }
      row.append(content, meta, actions); el('memory-list').appendChild(row);
    }
  }
  async function mutate(operation, message) {
    if (busy) return;
    busy = true;
    panel.querySelectorAll('button,input,textarea').forEach(node => { node.disabled = true; });
    status('正在保存…');
    try { await operation(); state = await request(); status(message); }
    catch (error) { status(error.message); }
    finally {
      busy = false;
      panel.querySelectorAll('button,input,textarea').forEach(node => { node.disabled = false; });
      render();
    }
  }
  function close() {
    if (busy) return;
    panel.classList.remove('open'); pendingDelete = null; el('memory-confirm').hidden = true;
    returnFocus?.focus();
  }
  window.openUserMemory = async () => {
    if (busy || panel.classList.contains('open')) return;
    returnFocus = document.activeElement;
    panel.classList.add('open'); edit(); el('memory-search').value = ''; status('正在加载…');
    panel.querySelector('[data-action="close"]').focus();
    state = null; el('memory-list').replaceChildren();
    await mutate(async () => {}, '');
  };
  panel.addEventListener('click', event => {
    if (event.target === panel) return close();
    const button = event.target.closest('[data-action]'); if (!button || busy) return;
    const action = button.dataset.action;
    if (action === 'close') close();
    if (action === 'filter') { filter = button.dataset.filter; edit(); mutate(async () => {}, ''); }
    const item = state?.items.find(i => i.id === Number(button.dataset.id));
    if (action === 'source' && item) { close(); window.openAiContextSource?.(item.source_key,item.source_message_id); }
    if (action === 'versions' && item) { request(`/${item.id}/versions`).then(data => status(data.items.length ? data.items.map(v => `v${v.version}：${v.content}`).join('；') : '暂无历史版本。')).catch(e => status(e.message)); }
    if (action === 'status' && item) mutate(() => request(`/${item.id}/status`, 'PUT', {status:item.status === 'active' ? 'inactive' : 'active',version:item.version}), '记忆状态已更新。');
    if (action === 'cancel-edit') edit();
    if (action === 'edit') { edit(state.items.find(item => item.id === Number(button.dataset.id))); el('memory-content').focus(); }
    if (action === 'delete' || action === 'clear') {
      pendingDelete = action === 'clear' ? '' : '/' + button.dataset.id;
      el('memory-confirm-text').textContent = action === 'clear' ? '删除所有已保存记忆？此操作无法撤销，聊天记录仍会保留。' : '删除这条已保存记忆？此操作无法撤销。';
      el('memory-confirm').hidden = false;
      panel.querySelector('[data-action="cancel-delete"]').focus();
    }
    if (action === 'cancel-delete') { pendingDelete = null; el('memory-confirm').hidden = true; }
    if (action === 'confirm-delete' && pendingDelete !== null) {
      const path = pendingDelete; pendingDelete = null; el('memory-confirm').hidden = true;
      mutate(() => request(path, 'DELETE'), '已删除记忆。'); edit();
    }
  });
  panel.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); }
    if (event.key !== 'Tab') return;
    const nodes = [...panel.querySelectorAll('button,input,textarea')].filter(node => !node.disabled && node.getClientRects().length);
    if (!nodes.length) { event.preventDefault(); return; }
    const first = nodes[0], last = nodes[nodes.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });
  el('memory-content').addEventListener('input', () => { el('memory-counter').textContent = `${el('memory-content').value.length}/500`; });
  el('memory-search').addEventListener('input', render);
  el('memory-editor').addEventListener('submit', async event => {
    event.preventDefault(); if (busy) return;
    const content = el('memory-content').value.trim(); if (!content) return status('请输入记忆内容。');
    const id = editing;
    const item = state.items.find(i => i.id === id);
    const kind = item?.kind || (filter === 'case' ? 'case' : 'personal');
    const case_id = kind === 'case' ? item?.case_id || window.getAiContextLocation?.().caseId || 0 : 0;
    if (kind === 'case' && !case_id) return status('请先关联一个明确案件。');
    await mutate(() => request(id === null ? '' : '/' + id, id === null ? 'POST' : 'PUT', {content,kind,case_id,version:item?.version}), '记忆已保存。');
    if (el('memory-status').textContent === '记忆已保存。') edit();
  });
  for (const id of ['memory-enabled','memory-auto']) el(id).addEventListener('change', () => {
    mutate(() => request('/settings', 'PUT', {enabled: el('memory-enabled').checked, auto_save: el('memory-auto').checked}), '设置已保存。');
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
      if (item.type !== 'recent') {
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
