/* Saved user memories share the main AI workspace, including case AI. */
(() => {
  let state = null, busy = false, editing = null, returnFocus = null;
  const panel = document.createElement('div');
  panel.className = 'modal-overlay user-memory-overlay';
  panel.id = 'user-memory-panel';
  panel.innerHTML = `<section class="modal user-memory-modal" role="dialog" aria-modal="true" aria-labelledby="user-memory-title">
    <div class="modal-header"><h2 id="user-memory-title">长期记忆</h2><button class="btn-icon" type="button" data-action="close" aria-label="关闭长期记忆">×</button></div>
    <p class="user-memory-description">跨对话记住您的称呼与回答偏好。记忆保存在本机，使用时会随提问发送给所选 AI 服务。删除聊天不会删除已保存的记忆。</p>
    <div class="user-memory-settings">
      <label><input type="checkbox" id="memory-enabled"> 使用长期记忆</label>
      <label><input type="checkbox" id="memory-auto"> 自动保存明确的称呼与回答偏好</label>
    </div>
    <p class="user-memory-description">自动保存仅识别简短、明确的自我陈述，如“我叫小林”“我希望你用中文回答”。其他信息可用“记住：……”保存；不自动读取旧聊天、案件文件或网页。</p>
    <form id="memory-editor"><label for="memory-content">添加记忆</label><textarea id="memory-content" maxlength="500" rows="3" placeholder="例如：称呼我为刘律师；回答时先给结论，再列依据。" required></textarea><div class="user-memory-actions"><span id="memory-counter">0/500</span><button type="button" data-action="cancel-edit" hidden>取消编辑</button><button type="submit" class="btn btn-primary">保存记忆</button></div></form>
    <label class="user-memory-search">搜索记忆<input id="memory-search" type="search" placeholder="搜索已保存的内容"></label>
    <p id="memory-status" role="status" aria-live="polite"></p>
    <div id="memory-list"></div>
    <div class="user-memory-actions"><span id="memory-total"></span><button type="button" class="user-memory-danger" data-action="clear">清空所有记忆</button></div>
    <div id="memory-confirm" hidden><p id="memory-confirm-text"></p><div class="user-memory-actions"><button type="button" data-action="cancel-delete">取消</button><button type="button" class="user-memory-danger" data-action="confirm-delete">确认删除</button></div></div>
  </section>`;
  document.body.appendChild(panel);
  const el = id => panel.querySelector(`#${id}`);
  let pendingDelete = null;
  function status(message) { el('memory-status').textContent = message; }
  async function request(path = '', method = 'GET', body) {
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
    el('memory-total').textContent = `${state.items.length}/100 条记忆`;
    const search = el('memory-search').value.trim().toLocaleLowerCase();
    const items = state.items.filter(item => item.content.toLocaleLowerCase().includes(search));
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
      meta.textContent = `${({manual:'手动保存',chat:'对话保存',auto:'自动保存'})[item.source] || '已保存'} · ${item.updated_at}`;
      const actions = document.createElement('div'); actions.className = 'user-memory-actions';
      for (const [label, action] of [['编辑', 'edit'], ['删除', 'delete']]) {
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
    await mutate(() => request(id === null ? '' : '/' + id, id === null ? 'POST' : 'PUT', {content}), '记忆已保存。');
    if (el('memory-status').textContent === '记忆已保存。') edit();
  });
  for (const id of ['memory-enabled','memory-auto']) el(id).addEventListener('change', () => {
    mutate(() => request('/settings', 'PUT', {enabled: el('memory-enabled').checked, auto_save: el('memory-auto').checked}), '设置已保存。');
  });
})();
