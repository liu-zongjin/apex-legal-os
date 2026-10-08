(() => {
  'use strict';
  const API = '/api/case-manager/court-online/downloads';
  const labels = { queued: '排队中', downloading: '下载中', packing: '正在打包', paused: '已暂停', completed: '已完成', partial: '部分完成', failed: '失败', cancelled: '已取消' };
  let selected = new URLSearchParams(location.search).get('job') || '';
  let page = 1, filePage = 0, busy = false, pending = false, reloadRequested = false, items = [], detail = null;
  const $ = id => document.getElementById(id);
  const esc = value => { const el = document.createElement('span'); el.textContent = String(value ?? ''); return el.innerHTML; };
  const paths = {
    folder: 'M3 7h6l2 2h10v10H3V7ZM3 7V5h6l2 2',
    download: 'M12 3v12M7 10l5 5 5-5M4 16v5h16v-5',
    archive: 'M4 4h16v4H4zM5 8v12h14V8M10 12h4',
    check: 'm5 12 4 4L19 6',
    pause: 'M8 5v14M16 5v14',
    play: 'm8 5 11 7-11 7V5Z',
    retry: 'M20 7v5h-5M19 12a7 7 0 1 1-2-5l3 3',
    stop: 'M6 6h12v12H6z',
    info: 'M12 11v6M12 7h.01M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0',
  };
  const icon = name => `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name] || paths.info}"/></svg>`;
  function size(value) {
    if (value === null || value === undefined) return '待确认';
    if (value < 1024) return value + ' B';
    const units = ['KB', 'MB', 'GB', 'TB']; let n = value / 1024, i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return n.toFixed(n >= 10 ? 1 : 2) + ' ' + units[i];
  }
  function eta(value) {
    if (value === null || value === undefined) return '待估算';
    if (value < 60) return Math.ceil(value) + ' 秒';
    if (value < 3600) return Math.ceil(value / 60) + ' 分钟';
    return (value / 3600).toFixed(1) + ' 小时';
  }
  function taskInfo(item) {
    const source = item.source === 'application-test' ? '申请材料打包测试' : '开放卷宗';
    let title = String(item.title || '未命名任务').replace(/-\d{8}-\d{6}$/, '');
    if (title.endsWith('—' + source)) title = title.slice(0, -source.length - 1);
    const suffix = String(item.title || '').match(/-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})$/);
    const created = item.created_at || (suffix ? `${suffix[1]}-${suffix[2]}-${suffix[3]}T${suffix[4]}:${suffix[5]}:${suffix[6]}+08:00` : '');
    const date = new Date(created);
    const time = Number.isNaN(date.getTime()) ? '' : date.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
    return { title, source, time };
  }
  function feedback(message = '') { $('feedback').textContent = message; $('feedback').hidden = !message; }
  async function request(path, options) {
    const response = await fetch(path, options); const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '无法读取下载任务');
    return data;
  }
  async function load() {
    if (!window.ApexLifecycle.active) return;
    if (busy) { reloadRequested = true; return; }
    busy = true;
    try {
      const data = await request(API + '?page=' + page); items = data.items;
      if (!selected && items.length) selected = items[0].id;
      const requestedId = selected;
      const current = requestedId ? await request(API + '/' + encodeURIComponent(requestedId)) : null;
      if (requestedId !== selected) { reloadRequested = true; return; }
      detail = current; feedback(); render();
    } catch (error) { feedback(error.message); }
    finally {
      busy = false;
      if (reloadRequested) { reloadRequested = false; load(); }
    }
  }
  function action(name, text, glyph, primary = false) {
    return `<button type="button" class="${primary ? 'primary' : name === 'cancel' ? 'destructive' : ''}" data-action="${name}" data-focus="${name}">${icon(glyph)}${text}</button>`;
  }
  function render() {
    const focus = document.activeElement?.dataset.focus;
    const fileScroll = $('detail').querySelector('.files-wrap')?.scrollTop || 0;
    const jobScroll = $('jobs').scrollTop;
    $('task-count').textContent = items.length;
    $('jobs').innerHTML = items.length ? items.map(item => {
      const info = taskInfo(item);
      return `<button type="button" class="job ${item.id === selected ? 'active' : ''}" aria-pressed="${item.id === selected}" data-job="${esc(item.id)}" data-focus="job-${esc(item.id)}" title="${esc(item.title)}"><strong class="job-title">${esc(info.title)}</strong><span class="job-source">${esc(info.source)}</span><span class="job-meta"><span>${esc(labels[item.state] || item.state)}</span><span>${item.completed_count} / ${item.file_count} 个文件</span></span>${info.time ? `<time class="job-time">${esc(info.time)}</time>` : ''}</button>`;
    }).join('') : '<p class="empty-list">本页暂无下载任务。</p>';
    $('jobs').scrollTop = jobScroll;
    $('previous').disabled = page === 1;
    $('next').disabled = items.length < 50;
    $('task-pagination').hidden = page === 1 && items.length < 50;
    $('task-page').textContent = '第 ' + page + ' 页';
    if (!detail) {
      $('detail').innerHTML = '<div class="empty"><strong>暂无下载任务</strong><p>在“一张网—在线阅卷”中选择卷宗，点击打包下载。</p></div>'; return;
    }
    const d = detail, info = taskInfo(d), done = d.state === 'completed', hasArchive = Boolean(d.zip_path);
    const percent = d.download_percent, running = ['queued', 'downloading', 'packing'].includes(d.state);
    let actions = '';
    if (running) actions = action('pause', '暂停', 'pause', true) + action('cancel', '取消任务', 'stop');
    else if (d.state === 'paused') actions = action('resume', '继续下载', 'play', true) + action('cancel', '取消任务', 'stop');
    else if (['failed', 'partial', 'cancelled'].includes(d.state)) actions = action('retry', '重试未完成文件', 'retry', true);
    if (hasArchive) actions += `<a class="download-link ${done ? 'primary' : ''}" data-focus="archive" href="${API}/${encodeURIComponent(d.id)}/archive" download>${icon('download')}下载 ZIP</a>` + action('open-zip', '打开 ZIP', 'archive');
    actions += action('open-folder', '打开文件夹', 'folder');
    let speed = size(d.speed_bytes) + ' <small>/s</small>', speedLabel = '当前下载速度';
    let remaining = eta(d.eta_seconds), remainingLabel = '预计剩余时间';
    if (done || d.state === 'partial') { speed = size(d.zip_size_bytes); speedLabel = 'ZIP 大小'; remaining = done ? '已就绪' : '待重试'; remainingLabel = done ? '下载与打包完成' : `${d.failed_count} 份文件未完成`; }
    else if (d.state === 'packing') { speed = '—'; speedLabel = '文件传输已结束'; remaining = '打包中'; remainingLabel = '正在生成 ZIP'; }
    else if (d.state !== 'downloading') { speed = '—'; remaining = labels[d.state] || '—'; remainingLabel = d.state === 'paused' ? '继续后重新估算' : '任务状态'; }
    const progressTitle = done ? '文件下载与 ZIP 打包已完成' : d.state === 'packing' ? '文件下载完成，正在打包' : '文件下载进度';
    filePage = Math.min(filePage, Math.max(0, Math.ceil(d.file_count / 50) - 1));
    const files = d.files.slice(filePage * 50, filePage * 50 + 50);
    const badgeIcon = done ? icon('check') : d.state === 'paused' ? icon('pause') : '';
    $('detail').innerHTML = `<div class="task-summary ${done ? 'is-complete' : ''}">
      <div class="task-top"><div class="task-identity"><h2 class="task-title" title="${esc(d.title)}">${esc(info.title)}</h2><div class="task-meta"><span>${esc(info.source)}</span>${info.time ? `<time>创建于 ${esc(info.time)}</time>` : ''}</div></div><span class="badge" data-state="${esc(d.state)}">${badgeIcon}${esc(labels[d.state] || d.state)}</span></div>
      ${d.source === 'application-test' ? `<div class="test-note">${icon('info')}<span><strong>申请材料打包测试</strong>介绍信、执业证等申请材料，用于验证下载与打包。</span></div>` : ''}
      <div class="metrics"><div class="metric"><b>${size(d.total_bytes)}</b><span>文件总大小</span></div><div class="metric"><b>${d.completed_count}<small> / ${d.file_count}</small></b><span>已完成文件${d.failed_count ? ' · 失败 ' + d.failed_count : ''}</span></div><div class="metric"><b>${speed}</b><span>${speedLabel}</span></div><div class="metric"><b>${remaining}</b><span>${remainingLabel}</span></div></div>
      <div class="progress-caption"><span>${progressTitle}</span><strong>${percent === null ? '大小待确认' : percent.toFixed(1) + '%'}</strong></div><div class="progress" role="progressbar" aria-label="文件下载" ${percent !== null ? `aria-valuenow="${percent.toFixed(1)}" aria-valuemin="0" aria-valuemax="100"` : ''}><span style="width:${percent === null ? d.file_percent : percent}%"></span></div>
      <div class="progress-meta"><span>已下载 ${size(d.downloaded_bytes)}${d.total_bytes !== null ? ' / ' + size(d.total_bytes) : ' · 总大小待确认'}</span><span>${d.completed_count} / ${d.file_count} 个文件</span></div>
      ${d.error ? `<p class="error" role="status">${esc(d.error)}</p>` : ''}${d.state === 'partial' ? '<p class="error">ZIP 包含成功文件及失败清单，可重试未完成文件。</p>' : ''}
      <div class="actions">${actions}</div><div class="save-location"><span>保存位置</span><code>${esc(d.directory)}</code></div>
      </div><section class="file-section" aria-label="文件明细"><div class="file-heading"><h3>文件明细</h3><span>${d.file_count} 个文件</span></div><div class="files-wrap"><table><colgroup><col class="file-name-column"><col class="file-size-column"><col class="file-downloaded-column"><col class="file-percent-column"><col class="file-status-column"></colgroup><thead><tr><th>名称 / 目录</th><th>大小</th><th>已下载</th><th>进度</th><th>状态</th></tr></thead><tbody>${files.map(f => `<tr><td><div class="file-identity"><span class="file-icon" aria-hidden="true">${esc(f.name.split('.').pop().toUpperCase().slice(0, 4))}</span><div class="file-text"><span class="file-name">${esc(f.name)}</span><div class="path">${esc(f.relative_path)}</div>${f.error ? `<div class="error">${esc(f.error)}</div>` : ''}</div></div></td><td>${size(f.size_bytes)}</td><td>${size(f.downloaded_bytes)}</td><td>${f.size_bytes ? Math.min(100, 100 * f.downloaded_bytes / f.size_bytes).toFixed(1) + '%' : f.state === 'completed' ? '100%' : '待确认'}</td><td><span class="file-status" data-state="${esc(f.state)}"><span class="status-dot" aria-hidden="true"></span>${esc(labels[f.state] || f.state)}</span></td></tr>`).join('')}</tbody></table></div>
      ${d.file_count > 50 ? `<nav class="pagination file-pagination" aria-label="文件分页"><button type="button" data-files="previous" data-focus="files-previous" ${filePage === 0 ? 'disabled' : ''}>上一页文件</button><span>第 ${filePage + 1} / ${Math.ceil(d.file_count / 50)} 页</span><button type="button" data-files="next" data-focus="files-next" ${(filePage + 1) * 50 >= d.file_count ? 'disabled' : ''}>下一页文件</button></nav>` : ''}</section>`;
    if (pending) $('detail').querySelectorAll('button[data-action]').forEach(button => button.disabled = true);
    const scroller = $('detail').querySelector('.files-wrap'); if (scroller) scroller.scrollTop = fileScroll;
    if (focus) document.querySelector(`[data-focus="${CSS.escape(focus)}"]`)?.focus({ preventScroll: true });
  }
  $('jobs').addEventListener('click', event => {
    const button = event.target.closest('[data-job]');
    if (!button) return;
    selected = button.dataset.job; filePage = 0;
    history.replaceState(null, '', '?job=' + encodeURIComponent(selected)); load();
  });
  $('detail').addEventListener('click', async event => {
    const files = event.target.closest('[data-files]');
    if (files) { filePage += files.dataset.files === 'next' ? 1 : -1; render(); return; }
    const button = event.target.closest('[data-action]');
    if (!button || pending) return;
    pending = true; button.disabled = true;
    const requestedId = selected;
    try {
      const current = await request(API + '/' + encodeURIComponent(requestedId) + '/' + button.dataset.action, { method: 'POST' });
      if (selected === requestedId) detail = current;
      feedback(); render();
    } catch (error) { feedback(error.message); }
    finally { pending = false; render(); }
  });
  $('refresh').onclick = load;
  $('previous').onclick = () => { page--; load(); };
  $('next').onclick = () => { page++; load(); };
  document.addEventListener('visibilitychange', () => {
    if (window.parent === window) window.postMessage({ type: 'apex:page-visibility', version: 1, active: document.visibilityState === 'visible' }, location.origin);
  });
  ApexLifecycle.onChange(active => { if (active) load(); });
  ApexLifecycle.interval(load, 1000); load();
})();
