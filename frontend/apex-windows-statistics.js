/* Windows-only opt-in preference. Scheduling and the persistent gate live in the worker. */
(() => {
  'use strict';
  if (window.top !== window) return;
  let initialized = false, button, mask, allowed = null;
  const invoke = value => window.StellaWindows.invoke('windows_statistics', {allowed: value});
  function show() {
    if (mask) return;
    mask = document.createElement('div'); mask.className = 'stella-messages-mask';
    const panel = document.createElement('section'); panel.className = 'stella-messages';
    panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-modal', 'true');
    panel.setAttribute('aria-labelledby', 'windows-statistics-title');
    const head = document.createElement('header'); head.className = 'stella-messages-head';
    const title = document.createElement('h2'); title.id = 'windows-statistics-title'; title.textContent = '匿名使用统计'; head.append(title);
    const content = document.createElement('p'); content.style.padding = '20px';
    content.textContent = '是否允许 Stella 发送匿名使用统计？仅包含随机生成的安装标识、应用版本和 Windows 系统版本，用于了解使用情况。同意后立即发送一次，此后每六小时最多一次；不会发送案件、文件、账号或业务内容。你可以随时通过工具栏“匿名统计”关闭。';
    const status = document.createElement('p'); status.style.padding = '0 20px'; status.setAttribute('role', 'status');
    status.textContent = allowed === true ? '当前：已开启' : allowed === false ? '当前：已关闭' : '尚未授权，当前不会发送统计。';
    const actions = document.createElement('div'); actions.className = 'stella-messages-tools';
    const deny = document.createElement('button'), agree = document.createElement('button');
    deny.type = agree.type = 'button'; deny.textContent = '不允许'; agree.textContent = '允许匿名统计';
    const close = () => { mask.remove(); mask = null; button.focus(); };
    async function save(value) {
      deny.disabled = agree.disabled = true;
      try { const result = await invoke(value); allowed = result.allowed; close(); }
      catch { status.textContent = '设置未能保存，请重试。'; deny.disabled = agree.disabled = false; deny.focus(); }
    }
    deny.onclick = () => save(false); agree.onclick = () => save(true);
    panel.addEventListener('keydown', event => {
      if (event.key === 'Escape' && !deny.disabled) { event.preventDefault(); close(); }
      if (event.key === 'Tab') { event.preventDefault(); (document.activeElement === deny ? agree : deny).focus(); }
    });
    actions.append(deny, agree); panel.append(head, content, status, actions); mask.append(panel); document.body.append(mask); deny.focus();
  }
  async function init() {
    if (initialized || !window.StellaWindows) return;
    const host = document.querySelector('.tab-bar-actions'); if (!host) return;
    initialized = true;
    button = document.createElement('button'); button.type = 'button'; button.className = 'tab-bar-action-btn';
    button.textContent = '匿名统计'; button.title = '设置匿名使用统计授权'; host.append(button);
    async function read(manual) {
      button.disabled = true;
      try { const result = await invoke(null); allowed = result.allowed; if (manual || allowed === null) show(); }
      catch { button.title = '暂时无法读取统计设置，请点击重试；未授权时不会发送'; }
      finally { button.disabled = false; }
    }
    button.onclick = () => read(true); await read(false);
  }
  window.addEventListener('stella:windows-ready', init); init();
})();
