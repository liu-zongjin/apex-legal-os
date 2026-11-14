(() => {
  const key = 'stella.homeWorkbench.v1';
  const isNew = localStorage.getItem(key) === null;
  let config = { mode: 'knowledge', interval: 0, image: '', tone: 'dark', imageScope: 'both' };
  try { config = { ...config, ...JSON.parse(localStorage.getItem(key) || '{}') }; } catch (_) {}
  const defaults = {knowledge: ['add','ask','explore'], case: ['newCase','caseManager','calendar']};
  config.actions = {...defaults, ...(config.actions || {})};
  config.overlay = {knowledge:25, case:25, ...(config.overlay || {})};
  const overlayValue = kind => { const n = Number(config.overlay[kind]); return Number.isFinite(n) ? Math.max(0, Math.min(80, n)) : 25; };
  let imageTarget = 'knowledge';
  const imageUrls = {knowledge: '', case: ''};
  let bundledImages = [];
  let imageGeneration = 0;
  config.order = config.order === 'case' ? 'case' : 'knowledge';
  let current = config.mode === 'case' ? 'case' : config.order, timer, lastWheel = 0;
  const hero = document.querySelector('.kb-home-hero');
  const side = document.querySelector('.kb-home-side');
  const grid = document.querySelector('.kb-home-grid');
  const knowledge = hero.querySelector('.kb-home-hero-copy');
  const overview = side.querySelector('.kb-home-overview');
  const caseCopy = document.createElement('div');
  caseCopy.className = 'kb-home-hero-copy home-case-copy';
  caseCopy.innerHTML = '<div class="kb-home-kicker">案件管理工作台</div><h2>案件统筹与推进</h2><p>掌握案件进展，让每一步工作清晰有序。</p><div class="kb-home-actions"></div>';
  hero.append(caseCopy);
  const caseOverview = document.createElement('section');
  caseOverview.className = 'kb-home-card kb-home-overview home-case-overview';
  caseOverview.innerHTML = '<div class="kb-home-section-title"><div><h3>案件概览</h3><span>今日工作状态</span></div><div class="kb-overview-actions"><button type="button" class="kb-home-link-btn" data-case-stats>可视化统计</button></div></div><div class="kb-home-overview-grid"><div><strong data-stat="all_count">—</strong><span>全部案件</span></div><div><strong data-stat="active_count">—</strong><span>在办</span></div><div><strong data-stat="archived_count">—</strong><span>已结</span></div><div><strong data-stat="pending_reminder_count">—</strong><span>待处理提醒</span></div></div>';
  side.append(caseOverview);
  const switcher = document.createElement('div');
  switcher.className = 'home-workbench-switch';
  switcher.innerHTML = '<button type="button" data-page="knowledge" aria-label="法律知识工作台">1</button><button type="button" data-page="case" aria-label="案件管理工作台">2</button>';
  hero.append(switcher);
  let loadedAt = 0;
  async function loadCases() {
    if (Date.now() - loadedAt < 60000) return;
    try { const response = await fetch('/api/case-stats?status=all', {cache:'no-store'}); if (!response.ok) throw Error(); const data = await response.json(); caseOverview.querySelectorAll('[data-stat]').forEach(el => { el.textContent = Number(data.overview[el.dataset.stat] ?? 0).toLocaleString(); }); loadedAt = Date.now(); } catch (_) { caseOverview.querySelectorAll('[data-stat]').forEach(el => el.textContent = '—'); }
  }
  function openStats() { openCaseStatsTab(); }
  document.querySelectorAll('[data-case-stats]').forEach(b => b.onclick = openStats);
  function caseView(view, create = false) {
    openCaseManagerTab();
    const tab = tabState.tabs.find(t => t.id === tabState.activeTabId);
    const frame = tab && document.getElementById(tab.id)?.querySelector('iframe');
    if (!frame || (!view && !create)) return;
    const navigate = () => { try { const w = frame.contentWindow; w.switchTab(view || 'cases'); if (create) w.openNewCaseDetail(); } catch (_) { if (typeof showToast === 'function') showToast('打开案件页面失败，请重试', 'warning'); } };
    if (frame.contentDocument?.readyState === 'complete' && typeof frame.contentWindow.switchTab === 'function') navigate();
    else frame.addEventListener('load', navigate, {once:true});
  }
  const actions = {
    knowledge: {
      add: ['添加知识', () => openSubmitModal()], ask: ['基于当前结果问答', () => openCurrentResultsAskPanel()], explore: ['探索', () => openKnowledgeExpandTab()],
      center: ['知识中心', () => openLegalKnowledgeTab()], stats: ['可视化统计', () => openKbStatsTab()], recommendations: ['今日推荐', () => openRecommendationsTab()],
      recent: ['最近阅读', () => showRecentWorkspace()], research: ['研究项目', () => openResearchProjectsTab()], ai: ['AI 增强', () => openAskPanel()],
      category: ['新建分类', () => openCreateCategoryModal()]
    },
    case: {
      newCase: ['新建案件', () => caseView('cases', true)], caseManager: ['进入案件管理', () => caseView()], calendar: ['案件日历', () => caseView('caseCalendar')],
      todos: ['待办事项', () => caseView('todos')], hearings: ['开庭安排', () => caseView('hearings')], preservation: ['财产保全', () => caseView('preservations')],
      appeals: ['上诉与异议', () => caseView('appeals')], messages: ['司法短信', () => caseView('judicialMessages')], stats: ['案件可视化', openStats],
      workflow: ['办案工作台', () => openCaseWorkflowsTab()], archive: ['案卷归档', () => openCaseArchiveTab()], court: ['一张网', () => openCourtOnlineService()],
      directory: ['法院通讯录', () => openCourtDirectoryTab()], documents: ['文书合集', () => openDocumentBundleTab()]
    }
  };
  function renderActions() {
    for (const kind of ['knowledge','case']) {
      const list = Array.isArray(config.actions[kind]) && config.actions[kind].length === 3 ? config.actions[kind] : defaults[kind];
      config.actions[kind] = list.map((id, i) => actions[kind][id] ? id : defaults[kind][i]);
      const container = (kind === 'knowledge' ? knowledge : caseCopy).querySelector('.kb-home-actions');
      container.replaceChildren();
      config.actions[kind].forEach((id, i) => { const button = document.createElement('button'); button.type = 'button'; button.className = i ? 'kb-home-btn' : 'btn-primary'; button.textContent = actions[kind][id][0]; button.onclick = actions[kind][id][1]; container.append(button); });
    }
    const editor = document.getElementById('home-action-editors'); editor.replaceChildren();
    for (const kind of ['knowledge','case']) {
      const group = document.createElement('div'); group.className = 'home-action-group';
      const title = document.createElement('strong'); title.textContent = kind === 'knowledge' ? '法律知识工作台' : '案件管理工作台'; group.append(title);
      const slots = document.createElement('div'); slots.className = 'home-action-slots';
      config.actions[kind].forEach((id, i) => {
        const details = document.createElement('details'); details.className = 'home-action-picker';
        const summary = document.createElement('summary'); summary.setAttribute('aria-label', `${title.textContent}，按钮 ${i+1}：${actions[kind][id][0]}`); summary.innerHTML = `<span>按钮 ${i+1}</span><b></b><i>⌄</i>`; summary.querySelector('b').textContent = actions[kind][id][0]; details.append(summary);
        const menu = document.createElement('div'); menu.className = 'home-action-menu';
        Object.entries(actions[kind]).forEach(([value, [label]]) => { const option = document.createElement('button'); option.type = 'button'; option.textContent = label; option.setAttribute('aria-pressed', String(value === id)); option.onclick = () => { config.actions[kind][i] = value; save(); renderActions(); }; menu.append(option); });
        details.append(menu); slots.append(details);
      }); group.append(slots); editor.append(group);
    }
  }
  function save() { try { const settings = {...config}; delete settings.image; localStorage.setItem(key, JSON.stringify(settings)); return true; } catch (_) { document.getElementById('home-settings-status').textContent = '设置保存失败，请检查本机存储空间。'; return false; } }
  function imageStore(mode, value, itemKey = 'background') { return new Promise((resolve, reject) => { const request = indexedDB.open('stella-home-workbench', 1); request.onupgradeneeded = () => request.result.createObjectStore('images'); request.onerror = () => reject(request.error); request.onsuccess = () => { const db = request.result; const tx = db.transaction('images', mode === 'get' ? 'readonly' : 'readwrite'); const store = tx.objectStore('images'); const op = mode === 'get' ? store.get(itemKey) : mode === 'delete' ? store.delete(itemKey) : store.put(value, itemKey); let result; op.onsuccess = () => { result = op.result; }; tx.oncomplete = () => { db.close(); resolve(result); }; tx.onerror = () => { db.close(); reject(tx.error); }; }; }); }
  function replaceImageUrl(kind, url) { if (imageUrls[kind].startsWith('blob:')) URL.revokeObjectURL(imageUrls[kind]); imageUrls[kind] = url; }
  function bundledUrl(item) { return '/static/home-backgrounds/' + encodeURIComponent(item.name) + '?v=' + encodeURIComponent(item.version); }
  function toneFor(url) { return new Promise((resolve, reject) => { const img = new Image(); img.onload = () => { try { const c = document.createElement('canvas'); c.width = c.height = 32; const ctx = c.getContext('2d'); ctx.drawImage(img, 0, 0, 32, 32); const pixels = ctx.getImageData(0, 0, 32, 32).data; let sum = 0; for (let i=0; i<pixels.length; i+=4) sum += .2126*pixels[i]+.7152*pixels[i+1]+.0722*pixels[i+2]; resolve(sum / (pixels.length/4) > 155 ? 'light' : 'dark'); } catch (err) { reject(err); } }; img.onerror = reject; img.src = url; }); }
  const preview = document.createElement('div');
  preview.className = 'home-background-preview'; preview.hidden = true;
  preview.setAttribute('aria-hidden', 'true');
  preview.innerHTML = '<div class="home-preview-card"><div class="home-preview-copy"><div class="home-preview-kicker"></div><strong></strong><div class="home-preview-actions"></div></div><div class="home-preview-overview"><div class="home-preview-overview-heading"><div><b></b><small></small></div><span></span></div><div class="home-preview-stats"></div></div><div class="home-preview-switch"><i></i><i></i></div></div><div class="home-preview-name"></div>';
  document.body.append(preview);
  let previewSequence = 0, previewAnchor = null, previewItem = null;
  function hidePreview() { preview.hidden = true; previewAnchor = previewItem = null; previewSequence++; }
  function showPreview(button, item) {
    previewAnchor = button; previewItem = item;
    const sequence = ++previewSequence, kind = imageTarget, url = bundledUrl(item);
    const copy = kind === 'case' ? caseCopy : knowledge;
    const stats = kind === 'case' ? caseOverview : overview;
    preview.querySelector('.home-preview-kicker').textContent = copy.querySelector('.kb-home-kicker').textContent;
    preview.querySelector('.home-preview-copy > strong').textContent = copy.querySelector('h2').textContent;
    const actionArea = preview.querySelector('.home-preview-actions'); actionArea.replaceChildren();
    copy.querySelectorAll('.kb-home-actions button').forEach(button => { const label = document.createElement('span'); label.textContent = button.textContent.trim(); actionArea.append(label); });
    preview.querySelector('.home-preview-overview-heading b').textContent = stats.querySelector('h3').textContent;
    preview.querySelector('.home-preview-overview-heading small').textContent = stats.querySelector('.kb-home-section-title span')?.textContent || '今日工作状态';
    preview.querySelector('.home-preview-overview-heading > span').textContent = stats.querySelector('.kb-home-link-btn')?.textContent || '可视化统计';
    const statArea = preview.querySelector('.home-preview-stats'); statArea.replaceChildren();
    stats.querySelectorAll('.kb-home-overview-grid > div').forEach(stat => { const cell = document.createElement('div'); const value = document.createElement('strong'); const label = document.createElement('span'); value.textContent = stat.querySelector('strong')?.textContent || '—'; label.textContent = stat.querySelector('span')?.textContent || ''; cell.append(value, label); statArea.append(cell); });
    const previewSwitch = preview.querySelector('.home-preview-switch');
    previewSwitch.hidden = config.mode !== 'both';
    previewSwitch.querySelectorAll('i').forEach((dot, index) => dot.classList.toggle('is-active', index === (kind === config.order ? 0 : 1)));
    preview.querySelector('.home-preview-name').textContent = item.name.replace(/\.[^.]+$/, '');
    const card = preview.querySelector('.home-preview-card');
    card.style.backgroundImage = `linear-gradient(rgba(0,0,0,${overlayValue(kind) / 100}),rgba(0,0,0,${overlayValue(kind) / 100})), url("${url}")`;
    card.classList.remove('is-light');
    toneFor(url).then(tone => { if (sequence === previewSequence) card.classList.toggle('is-light', tone === 'light' && overlayValue(kind) < 35); }).catch(() => {});
    preview.hidden = false;
    const rect = button.getBoundingClientRect(), width = preview.offsetWidth, height = preview.offsetHeight, gap = 10;
    const top = rect.top >= height + gap ? rect.top - height - gap : rect.bottom + gap;
    preview.style.left = Math.max(8, Math.min(rect.left + rect.width / 2 - width / 2, innerWidth - width - 8)) + 'px';
    preview.style.top = Math.max(8, Math.min(top, innerHeight - height - 8)) + 'px';
  }
  document.addEventListener('scroll', hidePreview, true);
  window.addEventListener('resize', hidePreview);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') hidePreview(); });
  function renderGallery() {
    hidePreview();
    document.querySelectorAll('[data-home-image-target]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.homeImageTarget === imageTarget)));
    document.getElementById('home-overlay-opacity').value = overlayValue(imageTarget);
    document.getElementById('home-overlay-value').textContent = overlayValue(imageTarget) + '%';
    const gallery = document.getElementById('home-background-gallery'); gallery.replaceChildren();
    if (!bundledImages.length) { gallery.textContent = '暂无内置背景图片。'; return; }
    for (const item of bundledImages) { const button = document.createElement('button'); button.type = 'button'; button.className = 'home-background-option'; button.setAttribute('aria-label', item.name.replace(/\.[^.]+$/, '')); button.setAttribute('aria-pressed', String(config.images?.[imageTarget]?.name === item.name && config.images[imageTarget].type === 'bundled')); const image = document.createElement('img'); image.src = bundledUrl(item); image.alt = ''; image.loading = 'lazy'; button.append(image); button.addEventListener('mouseenter', () => showPreview(button, item)); button.addEventListener('mouseleave', hidePreview); button.addEventListener('focus', () => showPreview(button, item)); button.addEventListener('blur', hidePreview); button.onclick = () => selectBundled(item); gallery.append(button); }
  }
  async function selectBundled(item) {
    if (!config.images) return;
    const kind = imageTarget, url = bundledUrl(item), generation = ++imageGeneration;
    try { const tone = await toneFor(url); if (generation !== imageGeneration) return; config.images[kind] = {type:'bundled', name:item.name, tone}; replaceImageUrl(kind, url); save(); renderGallery(); apply(); status.textContent = '已更新' + (kind === 'case' ? '案件管理' : '法律知识') + '工作台背景。'; } catch (_) { status.textContent = '无法读取内置背景图片。'; }
  }
  function show(page) {
    if (current !== page && !matchMedia('(prefers-reduced-motion: reduce)').matches) { [hero, side].forEach(el => el.animate([{opacity:.55, transform:'translateX(' + (page === 'case' ? '12px' : '-12px') + ')'},{opacity:1,transform:'translateX(0)'}], {duration:240,easing:'ease-out'})); }
    current = page; const activeUrl = imageUrls[page]; grid.classList.toggle('home-has-image', !!activeUrl); grid.classList.toggle('home-image-light', config.images?.[page]?.tone === 'light' && overlayValue(page) < 35); grid.style.setProperty('--home-overlay-opacity', overlayValue(page) / 100); grid.style.setProperty('--home-image', activeUrl ? `url("${activeUrl}")` : 'none'); knowledge.hidden = page !== 'knowledge'; overview.hidden = page !== 'knowledge'; caseCopy.hidden = page !== 'case'; caseOverview.hidden = page !== 'case';
    switcher.hidden = config.mode !== 'both'; switcher.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.page === page)));
    if (page === 'case') loadCases();
  }
  function apply() {
    switcher.append(...Array.from(switcher.children).sort((a, b) => (a.dataset.page === config.order ? -1 : 1)));
    switcher.querySelectorAll('button').forEach((b, i) => b.textContent = String(i + 1));
    document.querySelectorAll('[data-home-order]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.homeOrder === config.order)));
    document.querySelectorAll('[data-home-mode]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.homeMode === config.mode)));
    document.querySelectorAll('[data-home-interval]').forEach(b => b.setAttribute('aria-pressed', String(Number(b.dataset.homeInterval) === Number(config.interval))));
    show(config.mode === 'both' ? current : config.mode); clearInterval(timer);
    if (config.mode === 'both' && config.interval) timer = setInterval(() => { if (!document.hidden && document.getElementById('tab-page-main')?.offsetParent && !hero.matches(':hover') && !hero.contains(document.activeElement)) show(current === 'case' ? 'knowledge' : 'case'); }, config.interval * 1000);
  }
  document.querySelectorAll('[data-home-mode]').forEach(b => b.onclick = () => { config.mode = b.dataset.homeMode; if (config.mode === 'both') current = config.order; save(); apply(); });
  document.querySelectorAll('[data-home-order]').forEach(b => b.onclick = () => { config.order = b.dataset.homeOrder; if (config.mode === 'both') current = config.order; save(); apply(); });
  document.querySelectorAll('[data-home-image-target]').forEach(b => b.onclick = () => { imageTarget = b.dataset.homeImageTarget; renderGallery(); if (imageTarget === 'case') loadCases().then(() => { if (imageTarget === 'case' && previewAnchor && previewItem) showPreview(previewAnchor, previewItem); }); });
  document.getElementById('home-overlay-opacity').addEventListener('input', e => { config.overlay[imageTarget] = Number(e.target.value); document.getElementById('home-overlay-value').textContent = overlayValue(imageTarget) + '%'; save(); show(config.mode === 'both' ? current : config.mode); });
  document.querySelectorAll('[data-home-interval]').forEach(b => b.onclick = () => { config.interval = Number(b.dataset.homeInterval); save(); apply(); });
  switcher.onclick = e => { if (e.target.dataset.page) show(e.target.dataset.page); };
  [hero, side].forEach(el => el.addEventListener('wheel', e => { if (config.mode !== 'both' || Math.abs(e.deltaX) < 18 || Math.abs(e.deltaX) <= Math.abs(e.deltaY)) return; e.preventDefault(); if (Date.now() - lastWheel > 700) { show(e.deltaX > 0 ? (config.order === 'knowledge' ? 'case' : 'knowledge') : config.order); lastWheel = Date.now(); } }, {passive:false}));
  let startX = 0; hero.addEventListener('touchstart', e => { startX = e.touches[0].clientX; }, {passive:true}); hero.addEventListener('touchend', e => { const dx = e.changedTouches[0].clientX - startX; if (config.mode === 'both' && Math.abs(dx) > 60) show(dx < 0 ? (config.order === 'knowledge' ? 'case' : 'knowledge') : config.order); }, {passive:true});
  document.getElementById('home-actions-reset').onclick = () => { config.actions = {knowledge:[...defaults.knowledge], case:[...defaults.case]}; save(); renderActions(); };
  const status = document.getElementById('home-settings-status');
  document.getElementById('home-image-clear').onclick = () => { if (!config.images) return; ++imageGeneration; config.images[imageTarget] = {type:'none'}; replaceImageUrl(imageTarget, ''); save(); renderGallery(); apply(); status.textContent = '已移除当前工作台背景。'; };
  document.getElementById('home-image-input').onchange = async e => {
    if (!config.images) return;
    const file = e.target.files[0], kind = imageTarget, generation = ++imageGeneration; e.target.value = ''; if (!file) return;
    if (file.size > 5 * 1024 * 1024) { status.textContent = '图片不能超过 5 MB，请选择其他图片。'; return; }
    if (!file.type.startsWith('image/')) { status.textContent = '请选择图片文件。'; return; }
    const url = URL.createObjectURL(file);
    try { const tone = await toneFor(url); if (generation !== imageGeneration) { URL.revokeObjectURL(url); return; } await imageStore('put', file, 'background-' + kind); if (generation !== imageGeneration) { URL.revokeObjectURL(url); return; } config.images[kind] = {type:'custom', tone}; replaceImageUrl(kind, url); save(); renderGallery(); apply(); status.textContent = '背景图片已保存。'; }
    catch (_) { URL.revokeObjectURL(url); status.textContent = '图片读取或保存失败，请检查图片及本机存储空间。'; }
  };
  async function loadImages() {
    const generation = imageGeneration;
    try {
      const response = await fetch('/api/home-backgrounds', {cache:'no-store'}); if (response.ok) bundledImages = (await response.json()).items || [];
    } catch (_) {}
    let legacy = await imageStore('get');
    if (!legacy && config.image) legacy = await (await fetch(config.image)).blob();
    if (!config.images) {
      config.images = {};
      for (const kind of ['knowledge','case']) {
        const active = legacy && (config.imageScope === 'both' || config.imageScope === kind);
        if (active) { await imageStore('put', legacy, 'background-' + kind); config.images[kind] = {type:'custom', tone:config.tone || 'dark'}; }
        else if (isNew) config.images[kind] = {type:'bundled', name:kind === 'knowledge' ? '15_金色夕照与海岸悬崖.jpg' : '13_日出星芒与云海雪峰.jpg', tone:'dark'};
        else config.images[kind] = {type:'none'};
      }
      if (isNew) config.overlay = {knowledge:0, case:20};
      save();
    }
    for (const kind of ['knowledge','case']) {
      const selection = config.images[kind] || {type:'none'};
      if (selection.type === 'custom') { const blob = await imageStore('get', null, 'background-' + kind); if (blob && generation === imageGeneration) replaceImageUrl(kind, URL.createObjectURL(blob)); }
      if (selection.type === 'bundled') { const item = bundledImages.find(entry => entry.name === selection.name); if (item && generation === imageGeneration) replaceImageUrl(kind, bundledUrl(item)); }
    }
    renderGallery(); apply();
  }
  config.images = config.images || null;
  renderActions(); apply();
  loadImages().catch(() => { status.textContent = '无法读取本机背景图片。'; if (!config.images) config.images = {knowledge:{type:'none'},case:{type:'none'}}; renderGallery(); });
})();
