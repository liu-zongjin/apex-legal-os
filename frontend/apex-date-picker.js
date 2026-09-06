(() => {
  'use strict';

  const state = { input: null, year: 0, month: 0, time: '' };
  const pad = value => String(value).padStart(2, '0');
  const today = () => {
    const value = new Date();
    return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}`;
  };
  const parseDate = value => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return null;
    const [year, month, day] = value.split('-').map(Number);
    const date = new Date(year, month - 1, day);
    return date.getFullYear() === year && date.getMonth() === month - 1 && date.getDate() === day ? date : null;
  };
  const formatDate = date => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;

  function injectStyles() {
    const style = document.createElement('style');
    style.textContent = `
      .apex-date-input { cursor:pointer!important; padding-right:32px!important; background-image:linear-gradient(45deg,transparent 50%,#8b1a1a 50%),linear-gradient(135deg,#8b1a1a 50%,transparent 50%)!important; background-position:calc(100% - 16px) 50%,calc(100% - 11px) 50%!important; background-size:5px 5px,5px 5px!important; background-repeat:no-repeat!important; }
      /* 案件台账等编辑浮窗的遮罩层为 10020；日期面板挂在 body 下，必须高于
         遮罩层才能在当前浮窗内正常操作。 */
      #apexDatePicker { position:fixed; z-index:10050; display:none; width:304px; padding:12px; border:1px solid #dbe1ea; border-radius:14px; background:#fff; color:#172033; box-shadow:0 18px 46px rgba(20,29,46,.22); font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif; }
      #apexDatePicker.show { display:block; } #apexDatePicker * { box-sizing:border-box; }
      .adp-head { display:flex; align-items:center; justify-content:space-between; gap:8px; padding:0 2px 10px; }.adp-selects,.adp-nav,.adp-foot { display:flex; align-items:center; gap:5px; }
      .adp-selects select { height:29px; border:1px solid #dbe1ea; border-radius:8px; padding:0 6px; background:#f8fafc; color:#172033; font-size:12.5px; font-weight:700; outline:0; }.adp-selects select:focus { border-color:#8b1a1a; box-shadow:0 0 0 3px rgba(139,26,26,.14); }
      .adp-nav button,.adp-foot button { border:0; border-radius:8px; background:#f6f7f9; color:#172033; font-weight:680; cursor:pointer; }.adp-nav button { width:28px; height:28px; font-size:18px; line-height:1; }.adp-nav button:hover,.adp-foot button:hover { background:rgba(139,26,26,.09); color:#8b1a1a; }
      .adp-week,.adp-grid { display:grid; grid-template-columns:repeat(7,1fr); text-align:center; }.adp-week { padding-bottom:5px; color:#667085; font-size:11px; font-weight:700; }.adp-day { width:100%; aspect-ratio:1; padding:0; border:0; border-radius:9px; background:transparent; color:#172033; font-size:12.5px; cursor:pointer; }.adp-day:hover { background:rgba(139,26,26,.09); color:#8b1a1a; }.adp-day.muted { color:#667085; opacity:.56; }.adp-day.today { box-shadow:inset 0 0 0 1px rgba(139,26,26,.42); color:#8b1a1a; font-weight:760; }.adp-day.selected { background:#8b1a1a; color:#fff; box-shadow:0 4px 10px rgba(139,26,26,.24); }
      .adp-foot { justify-content:space-between; margin-top:10px; padding-top:10px; border-top:1px solid #e3e7ef; }.adp-foot button { min-height:30px; padding:0 10px; font-size:12px; }.adp-today { margin-left:auto; color:#8b1a1a!important; }.adp-confirm { background:#8b1a1a!important; color:#fff!important; }.adp-time { display:flex; align-items:center; gap:6px; margin:0 0 9px; color:#667085; font-size:12px; }.adp-time select { height:28px; min-width:52px; border:1px solid #dbe1ea; border-radius:8px; padding:0 5px; color:#172033; background:#f8fafc; font:inherit; outline:0; }.adp-time select:focus { border-color:#8b1a1a; box-shadow:0 0 0 3px rgba(139,26,26,.14); }
      html.dark-mode #apexDatePicker,body.dark-mode #apexDatePicker { background:#151c27; color:#e5e7eb; border-color:#2d3748; box-shadow:0 18px 46px rgba(0,0,0,.42); } html.dark-mode .adp-selects select,body.dark-mode .adp-selects select,html.dark-mode .adp-nav button,body.dark-mode .adp-nav button,html.dark-mode .adp-foot button,body.dark-mode .adp-foot button,html.dark-mode .adp-time select,body.dark-mode .adp-time select { background:#111827; color:#e5e7eb; border-color:#2d3748; } html.dark-mode .adp-week,body.dark-mode .adp-week,html.dark-mode .adp-day.muted,body.dark-mode .adp-day.muted,html.dark-mode .adp-time,body.dark-mode .adp-time { color:#94a3b8; } html.dark-mode .adp-day,body.dark-mode .adp-day { color:#e5e7eb; }
      @media (prefers-color-scheme: dark) { #apexDatePicker { background:#151c27; color:#e5e7eb; border-color:#2d3748; box-shadow:0 18px 46px rgba(0,0,0,.42); }.adp-selects select,.adp-nav button,.adp-foot button,.adp-time select { background:#111827; color:#e5e7eb; border-color:#2d3748; }.adp-week,.adp-day.muted,.adp-time { color:#94a3b8; }.adp-day { color:#e5e7eb; } }
    `;
    document.head.append(style);
  }

  function picker() { return document.getElementById('apexDatePicker'); }
  function close() { picker()?.classList.remove('show'); state.input = null; state.time = ''; }
  function apply(value) {
    const input = state.input;
    if (!input) return close();
    const kind = input.dataset.apexDateKind;
    if (kind === 'datetime-local' && value) {
      const hour = document.getElementById('adpHour')?.value;
      const minute = document.getElementById('adpMinute')?.value;
      const time = /^\d{2}$/.test(hour || '') && /^\d{2}$/.test(minute || '')
        ? `${hour}:${minute}`
        : String(input.value || '').slice(11, 16) || '00:00';
      value = `${value}T${time}`;
    } else if (kind === 'month' && value) value = value.slice(0, 7);
    input.value = value;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    close();
  }
  function render() {
    const host = picker();
    if (!host || !state.input) return;
    const selected = String(state.input.value || '').slice(0, 10);
    const first = new Date(state.year, state.month, 1);
    const start = new Date(state.year, state.month, 1 - first.getDay());
    const currentYear = new Date().getFullYear();
    const years = Array.from({ length: currentYear + 21 - 1900 }, (_, i) => 1900 + i);
    const yearOptions = years.map(year => `<option value="${year}" ${year === state.year ? 'selected' : ''}>${year} 年</option>`).join('');
    const monthOptions = Array.from({ length: 12 }, (_, i) => `<option value="${i}" ${i === state.month ? 'selected' : ''}>${i + 1} 月</option>`).join('');
    const days = Array.from({ length: 42 }, (_, i) => {
      const date = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
      const value = formatDate(date);
      const classes = ['adp-day'];
      if (date.getMonth() !== state.month) classes.push('muted');
      if (value === today()) classes.push('today');
      if (value === selected) classes.push('selected');
      return `<button type="button" class="${classes.join(' ')}" data-value="${value}">${date.getDate()}</button>`;
    }).join('');
    const initialTime = state.time || String(state.input.value || '').slice(11,16);
    const [selectedHour = '00', selectedMinute = '00'] = /^\d{2}:\d{2}$/.test(initialTime) ? initialTime.split(':') : [];
    const hourOptions = Array.from({length:24}, (_, hour) => String(hour).padStart(2, '0')).map(hour => `<option value="${hour}" ${hour === selectedHour ? 'selected' : ''}>${hour} 时</option>`).join('');
    const minuteOptions = Array.from({length:60}, (_, minute) => String(minute).padStart(2, '0')).map(minute => `<option value="${minute}" ${minute === selectedMinute ? 'selected' : ''}>${minute} 分</option>`).join('');
    const time = state.input.dataset.apexDateKind === 'datetime-local' ? `<div class="adp-time"><span>时间</span><select id="adpHour" aria-label="选择小时">${hourOptions}</select><span>:</span><select id="adpMinute" aria-label="选择分钟">${minuteOptions}</select></div>` : '';
    const confirm = state.input.dataset.apexDateKind === 'datetime-local' ? '<button type="button" class="adp-confirm" data-confirm>确定</button>' : '';
    host.innerHTML = `<div class="adp-head"><div class="adp-selects"><select id="adpYear" aria-label="选择年份">${yearOptions}</select><select id="adpMonth" aria-label="选择月份">${monthOptions}</select></div><div class="adp-nav"><button type="button" data-move="-1" aria-label="上个月">‹</button><button type="button" data-move="1" aria-label="下个月">›</button></div></div>${time}<div class="adp-week"><span>日</span><span>一</span><span>二</span><span>三</span><span>四</span><span>五</span><span>六</span></div><div class="adp-grid">${days}</div><div class="adp-foot"><button type="button" data-clear>清空</button><button type="button" class="adp-today" data-today>今天</button>${confirm}</div>`;
    host.querySelector('#adpYear').onchange = event => { state.year = Number(event.target.value); render(); };
    host.querySelector('#adpMonth').onchange = event => { state.month = Number(event.target.value); render(); };
    host.querySelector('#adpHour')?.addEventListener('change', event => { state.time = `${event.target.value}:${host.querySelector('#adpMinute')?.value || '00'}`; });
    host.querySelector('#adpMinute')?.addEventListener('change', event => { state.time = `${host.querySelector('#adpHour')?.value || '00'}:${event.target.value}`; });
    host.querySelectorAll('[data-move]').forEach(button => button.onclick = () => { const date = new Date(state.year, state.month + Number(button.dataset.move), 1); state.year = date.getFullYear(); state.month = date.getMonth(); render(); });
    host.querySelectorAll('.adp-day').forEach(button => button.onclick = () => apply(button.dataset.value));
    host.querySelector('[data-clear]').onclick = () => apply('');
    host.querySelector('[data-today]').onclick = () => apply(today());
    host.querySelector('[data-confirm]')?.addEventListener('click', () => apply(selected || today()));
  }
  function open(input) {
    if (input.disabled) return;
    state.input = input;
    state.time = String(input.value || '').slice(11,16) || '00:00';
    const selected = parseDate(String(input.value || '').slice(0, 10)) || parseDate(today());
    state.year = selected.getFullYear(); state.month = selected.getMonth();
    render();
    const host = picker(); const rect = input.getBoundingClientRect(); const width = 304;
    host.style.left = `${Math.max(12, Math.min(rect.left, window.innerWidth - width - 12))}px`;
    host.classList.add('show');
    host.style.top = `${rect.bottom + 8 + host.offsetHeight <= window.innerHeight - 12 ? rect.bottom + 8 : Math.max(12, rect.top - host.offsetHeight - 8)}px`;
  }
  function bind(input) {
    if (input.dataset.apexDatePicker) return;
    const kind = input.getAttribute('type');
    input.dataset.apexDatePicker = 'true'; input.dataset.apexDateKind = kind;
    input.readOnly = true; input.classList.add('apex-date-input');
    input.addEventListener('mousedown', event => { event.preventDefault(); open(input); });
    input.addEventListener('click', event => event.preventDefault());
    input.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); open(input); } });
  }
  function scan(root = document) {
    if (root.matches?.('input[type="date"],input[type="datetime-local"],input[type="month"]')) bind(root);
    root.querySelectorAll?.('input[type="date"],input[type="datetime-local"],input[type="month"]').forEach(bind);
  }
  function start() {
    injectStyles();
    const host = document.createElement('div'); host.id = 'apexDatePicker'; host.setAttribute('role', 'dialog'); host.setAttribute('aria-label', '选择日期'); document.body.append(host);
    scan();
    new MutationObserver(mutations => mutations.forEach(mutation => mutation.addedNodes.forEach(node => { if (node.nodeType === 1) scan(node); }))).observe(document.body, { childList: true, subtree: true });
    document.addEventListener('mousedown', event => { const host = picker(); if (host?.classList.contains('show') && !host.contains(event.target) && event.target !== state.input) close(); });
    document.addEventListener('keydown', event => { if (event.key === 'Escape') close(); });
  }
  document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', start, { once: true }) : start();
})();
