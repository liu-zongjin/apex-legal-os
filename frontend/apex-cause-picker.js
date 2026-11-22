/* Shared cause catalog and text-field adapter. Existing forms own record persistence. */
(function (root) {
  'use strict';
  const labels = { all: '全部', civil: '民事', administrative: '行政', criminal: '刑事罪名' };
  const historyKey = 'stella:cause-picker:usage:v1';
  const pageSize = 60;
  const normalize = value => String(value || '').normalize('NFKC').toLowerCase();
  const terms = value => normalize(value).trim().split(/\s+/).filter(Boolean);
  const compact = value => normalize(value).replace(/[\p{P}\p{Z}]/gu, '');
  const selectable = node => node.category !== 'criminal' || node.entry;
  const pathText = node => [labels[node.category], ...node.path.map(parent => parent.label)].join(' › ');

  function createIndex(data) {
    const byId = new Map();
    const byLabel = new Map();
    const roots = [];
    const nodes = data.nodes.map(item => {
      const parent = byId.get(item.parent);
      const node = { ...item, path: parent ? [...parent.path, parent] : [], children: [] };
      byId.set(node.id, node);
      if (parent) parent.children.push(node);
      else roots.push(node);
      if (selectable(node)) {
        const matches = byLabel.get(node.label) || [];
        matches.push(node);
        byLabel.set(node.label, matches);
      }
      return node;
    });
    return { roots, nodes, byId, byLabel };
  }

  function search(index, query, category = 'all') {
    const keywords = terms(query).map(compact).filter(Boolean);
    if (!keywords.length) return [];
    const phrase = keywords.join('');
    return index.nodes.filter(node => {
      if (category !== 'all' && node.category !== category) return false;
      const haystack = compact(pathText(node) + node.label);
      return keywords.every(keyword => haystack.includes(keyword));
    }).map(node => {
      const name = compact(node.label);
      return { node, rank: name === phrase ? 0 : name.startsWith(phrase) ? 1 :
        keywords.every(keyword => name.includes(keyword)) ? 2 : 3 };
    }).sort((a, b) => a.rank - b.rank).map(result => result.node);
  }

  function history() {
    try {
      const saved = JSON.parse(root.localStorage.getItem(historyKey));
      if (saved && !Array.isArray(saved) && typeof saved === 'object') return saved;
    } catch (_) {}
    return {};
  }

  function remember(id) {
    const saved = history();
    saved[id] = { at: Date.now(), count: (Number(saved[id]?.count) || 0) + 1 };
    const entries = Object.entries(saved).filter(([, value]) => value?.at)
      .sort((a, b) => b[1].at - a[1].at).slice(0, 100);
    try { root.localStorage.setItem(historyKey, JSON.stringify(Object.fromEntries(entries))); } catch (_) {}
  }

  let catalog;
  let pending;
  function load() {
    if (catalog) return Promise.resolve(catalog);
    if (!pending) pending = fetch('/static/apex-cause-catalog.json?v=1')
      .then(response => {
        if (!response.ok) throw new Error('Cause catalog unavailable');
        return response.json();
      }).then(data => (catalog = createIndex(data)))
      .finally(() => { pending = null; });
    return pending;
  }

  function documentLabel(value) {
    const name = String(value || '').trim();
    if (!name || catalog?.byLabel.has(name) || /(?:纠纷|争议|罪)$/.test(name)) return name;
    return name + '纠纷';
  }

  const api = { createIndex, search, documentLabel, load };
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (!root.document) return;

  const doc = root.document;
  const selector = 'input[data-apex-cause],textarea[data-apex-cause]';
  const configs = new WeakMap();
  const chosenIds = new WeakMap();
  let current = null;
  let popup;
  let panelSearch;
  let controls;
  let crumbs;
  let list;
  let footer;
  let writing = false;

  function button(text, handler, className = '') {
    const element = doc.createElement('button');
    element.type = 'button';
    element.className = className;
    element.textContent = text;
    element.onclick = handler;
    return element;
  }

  function initPanel() {
    if (popup) return;
    popup = doc.createElement('section');
    popup.id = 'apex-cause-picker';
    popup.className = 'apex-cause-picker';
    popup.setAttribute('role', 'dialog');
    popup.setAttribute('aria-label', '选择案由或罪名');
    popup.hidden = true;
    panelSearch = doc.createElement('input');
    panelSearch.type = 'search';
    panelSearch.placeholder = '搜索案由、罪名或所属路径';
    panelSearch.setAttribute('aria-label', panelSearch.placeholder);
    panelSearch.autocomplete = 'off';
    panelSearch.addEventListener('input', event => {
      if (!event.isComposing) query(panelSearch.value);
    });
    panelSearch.addEventListener('compositionend', () => query(panelSearch.value));
    controls = doc.createElement('div');
    controls.className = 'apex-cause-controls';
    crumbs = doc.createElement('nav');
    crumbs.className = 'apex-cause-crumbs';
    crumbs.setAttribute('aria-label', '案由路径');
    list = doc.createElement('div');
    list.className = 'apex-cause-list';
    list.setAttribute('aria-label', '案由列表');
    footer = doc.createElement('div');
    footer.className = 'apex-cause-footer';
    popup.append(panelSearch, controls, crumbs, list, footer);
    doc.body.append(popup);
  }

  function close(restore = false) {
    if (!current) return;
    const { anchor } = current;
    current.observer?.disconnect();
    root.clearTimeout(current.extraTimer);
    if (restore && anchor.isConnected) anchor.focus();
    anchor.setAttribute('aria-expanded', 'false');
    popup.hidden = true;
    current = null;
  }

  function place() {
    if (!current) return;
    const { anchor } = current;
    const rect = anchor.getBoundingClientRect();
    const viewportTop = root.visualViewport?.offsetTop || 0;
    const viewportHeight = root.visualViewport?.height || root.innerHeight;
    const viewportBottom = viewportTop + viewportHeight;
    const width = Math.min(root.innerWidth - 16, Math.max(380, rect.width));
    const below = viewportBottom - rect.bottom - 12;
    const above = rect.top - viewportTop - 12;
    if (!anchor.isConnected || !rect.width || rect.bottom < viewportTop || rect.top >= viewportBottom) {
      close();
      return;
    }
    // At constrained heights use a viewport overlay instead of clipping the controls.
    const overlay = Math.max(above, below) < 245;
    const upwards = !overlay && below < 350 && above > below;
    const max = Math.min(520, overlay ? viewportHeight - 16 : upwards ? above : below);
    Object.assign(popup.style, {
      left: Math.max(8, Math.min(rect.left, root.innerWidth - width - 8)) + 'px',
      width: width + 'px', maxHeight: max + 'px',
      top: upwards ? 'auto' : (overlay ? viewportTop + 8 : rect.bottom + 5) + 'px',
      bottom: upwards ? (root.innerHeight - rect.top + 5) + 'px' : 'auto'
    });
  }

  function hydrate(session) {
    const saved = chosenIds.get(session.input);
    const exact = catalog.byLabel.get(session.input.value.trim()) || [];
    const selected = exact.find(node => node.id === saved) || (exact.length === 1 ? exact[0] : null);
    session.selected = selected?.id;
    if (selected && session.config.categories.includes(selected.category) && !session.query) {
      session.category = selected.category;
      selected.path.forEach(ancestor => session.expanded.add(ancestor.id));
      session.path = selected.path.at(-1) || null;
    }
  }

  function open(input, filter = '', anchor = input) {
    if (current?.input === input) return;
    close();
    initPanel();
    const config = configs.get(input) || defaultConfig();
    const session = current = {
      input, anchor, config, query: filter, category: config.categories.length === 1 ? config.categories[0] : 'all',
      expanded: new Set(), path: null, limit: pageSize, mode: 'frequent', extras: []
    };
    if (anchor === input && !input.labels?.length && !input.hasAttribute('aria-labelledby') &&
        !input.hasAttribute('aria-label')) input.setAttribute('aria-label', '案由或罪名');
    anchor.setAttribute('aria-haspopup', 'dialog');
    anchor.setAttribute('aria-controls', popup.id);
    anchor.setAttribute('aria-expanded', 'true');
    panelSearch.value = filter;
    popup.hidden = false;
    if (catalog) hydrate(session);
    const loading = catalog ? null : load();
    render();
    place();
    revealSelection();
    if (root.MutationObserver && current === session) {
      session.observer = new MutationObserver(() => {
        if (!anchor.isConnected || !anchor.getClientRects().length) close();
      });
      session.observer.observe(anchor.closest('[role=dialog],#drawer,#seriesSide,.form-card,#seriesChildTableHost') || anchor.parentElement,
        { attributes: true, childList: true, subtree: true });
    }
    loading?.then(() => {
      if (current !== session) return;
      if (!session.query && !session.interacted) hydrate(session);
      render();
      if (!session.query) revealSelection();
    }).catch(() => { if (current === session) render(); });
    refreshExtras(session);
  }

  function revealSelection() {
    list.querySelector('.apex-cause-row.is-selected')?.scrollIntoView({ block: 'nearest' });
  }

  function choose(anchor, config) {
    const input = doc.createElement('input');
    input.value = config.value || '';
    attach(input, config);
    open(input, '', anchor);
    if (current) panelSearch.focus();
  }

  function defaultConfig() {
    return { categories: ['civil', 'administrative', 'criminal'], custom: true };
  }

  function attach(input, config) {
    if (!input) return;
    input.dataset.apexCause = '';
    configs.set(input, { ...defaultConfig(), ...config });
    if (config?.onReady) load().then(config.onReady).catch(() => {});
  }

  function refreshExtras(session) {
    if (!session.config.items) return;
    const request = session.extraRequest = (session.extraRequest || 0) + 1;
    root.clearTimeout(session.extraTimer);
    const lookup = () => Promise.resolve().then(() => session.config.items(session.query)).then(items => {
      if (current !== session || request !== session.extraRequest) return;
      const distinct = new Map();
      for (const item of items || []) {
        const label = String(typeof item === 'string' ? item : item?.label || item?.name || item?.value || '').trim();
        if (!label) continue;
        const note = session.config.itemNote?.(item) || '';
        if (!distinct.has(label) || note) distinct.set(label, { label, note });
      }
      session.extras = [...distinct.values()];
      render();
    }).catch(() => {});
    if (session.query) session.extraTimer = root.setTimeout(lookup, 150);
    else lookup();
  }

  function query(value) {
    if (!current) return;
    current.query = value;
    current.path = null;
    current.interacted = true;
    current.limit = pageSize;
    panelSearch.value = value;
    render(true);
    refreshExtras(current);
  }

  function commit(value, node, custom = false) {
    const { input, config } = current;
    if (node) {
      chosenIds.set(input, node.id);
      remember(node.id);
    } else chosenIds.delete(input);
    input.value = value;
    close(true);
    writing = true;
    try {
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
    } finally { writing = false; }
    const placeholder = value.indexOf('××');
    if (input.isConnected && placeholder >= 0) input.setSelectionRange(placeholder, placeholder + 2);
    config.onChange?.(value, node?.id);
    if (value && custom) config.onCustom?.(value);
  }

  function branch(node, expand) {
    if (expand) {
      current.expanded.add(node.id);
      current.path = node;
    } else {
      current.expanded.delete(node.id);
      if (current.path === node || current.path?.path.includes(node)) current.path = node.path.at(-1);
    }
    render();
    list.querySelector(`[data-key="toggle-${node.id}"]`)?.focus({ preventScroll: true });
  }

  function group(text) {
    const title = doc.createElement('div');
    title.className = 'apex-cause-group';
    title.textContent = text;
    list.append(title);
  }

  function row(node, options = {}) {
    const { depth = 0, showPath = false, key = node.id || node.label } = options;
    const wrapper = doc.createElement('div');
    wrapper.className = 'apex-cause-row';
    wrapper.style.setProperty('--cause-depth', depth);
    const hasChildren = !!node.children?.length;
    const expanded = current.expanded.has(node.id);
    const selected = node.id ? current.selected === node.id : current.input.value.trim() === node.label;
    wrapper.classList.toggle('is-selected', selected);
    if (hasChildren && !showPath) {
      const toggle = button(expanded ? '▾' : '▸', () => branch(node, !expanded), 'apex-cause-toggle');
      toggle.dataset.key = 'toggle-' + key;
      toggle.setAttribute('aria-label', (expanded ? '收起' : '展开') + node.label);
      toggle.setAttribute('aria-expanded', String(expanded));
      wrapper.append(toggle);
    }
    const canSelect = !node.id || selectable(node);
    const pick = button(node.label, () => {
      if (canSelect) commit(node.label, node.id ? node : null);
      else if (showPath) locate(node);
      else branch(node, !expanded);
    }, 'apex-cause-option');
    pick.dataset.key = 'pick-' + key;
    if (selected) pick.setAttribute('aria-current', 'true');
    const hint = node.note || (showPath && node.id ? pathText(node) : (node.label.includes('××') ? '按实际情况补全 ××' : ''));
    if (hint) {
      const sub = doc.createElement('small');
      sub.textContent = hint;
      pick.append(sub);
    }
    wrapper.append(pick);
    list.append(wrapper);
  }

  function locate(node) {
    const { expanded } = current;
    current.category = node.category;
    current.query = '';
    panelSearch.value = '';
    node.path.forEach(parent => expanded.add(parent.id));
    if (node.children.length) expanded.add(node.id);
    current.path = node.children.length ? node : node.path.at(-1);
    render(true);
    const target = list.querySelector(`[data-key="pick-${node.id}"]`);
    target?.focus({ preventScroll: true });
    target?.scrollIntoView({ block: 'nearest' });
  }

  function render(resetScroll = false) {
    const { category, config, expanded, mode, path, query: value, limit } = current;
    const focusedKey = popup.contains(doc.activeElement) ? doc.activeElement.dataset.key : null;
    const oldScroll = list.scrollTop;
    const categories = config.categories.length > 1 ? ['all', ...config.categories] : config.categories;
    const tab = name => {
      const item = button(labels[name], () => {
        Object.assign(current, { category: name, path: null, limit: pageSize, interacted: true });
        render(true);
      });
      item.dataset.key = 'tab-' + name;
      item.setAttribute('aria-pressed', String(name === category));
      return item;
    };
    controls.replaceChildren(...categories.map(tab));
    const filtered = !!value.trim();
    if (!filtered) {
      const order = button(mode === 'frequent' ? '常用优先' : '目录顺序', () => {
        current.mode = mode === 'frequent' ? 'directory' : 'frequent';
        render(true);
      }, 'apex-cause-order');
      order.dataset.key = 'order';
      order.setAttribute('aria-pressed', String(mode === 'frequent'));
      controls.append(order);
    }

    crumbs.replaceChildren();
    crumbs.hidden = filtered || !path;
    if (!crumbs.hidden) {
      const trail = [null, ...path.path, path];
      for (const node of trail) {
        const crumb = button(node ? node.label : labels[category], () => {
          if (node) locate(node);
          else {
            current.path = null;
            current.expanded.clear();
            render(true);
            controls.querySelector('[aria-pressed=true]')?.focus();
          }
        });
        crumb.dataset.key = 'crumb-' + (node?.id || 'root');
        crumbs.append(crumb);
      }
    }

    list.replaceChildren();
    const allowed = node => config.categories.includes(node.category) && (category === 'all' || node.category === category);
    const catalogResults = filtered && catalog ? search(catalog, value, category).filter(allowed) : [];
    const prefixes = terms(value).map(compact).filter(Boolean);
    const items = current.extras.filter(item =>
      prefixes.every(word => compact(item.label).includes(word)) &&
      (item.note || !catalog?.byLabel.has(item.label)));
    if (items.length) {
      group(config.itemGroup || '本地备选');
      items.slice(0, limit).forEach(item => row(item, { key: 'extra-' + item.label }));
    }
    if (!catalog) group(pending ? '正在读取案由汇编…' : '案由汇编暂不可用');
    if (catalog && filtered) {
      if (catalogResults.length) {
        group('汇编检索结果');
        catalogResults.slice(0, limit).forEach(node => row(node, { showPath: true }));
      } else if (!items.length) group('未找到匹配案由');
    }
    if (catalog && !filtered) {
      if (mode === 'frequent') {
        const historyRows = Object.entries(history()).map(([id, usage]) => ({ node: catalog.byId.get(id), usage }))
          .filter(({ node, usage }) => node && usage && allowed(node));
        const recent = historyRows.slice().sort((a, b) => b.usage.at - a.usage.at).slice(0, 4);
        const frequent = historyRows.filter(({ node, usage }) => usage.count > 1 &&
          !recent.some(item => item.node === node)).sort((a, b) => b.usage.count - a.usage.count || b.usage.at - a.usage.at).slice(0, 4);
        for (const [title, entries] of [['最近使用', recent], ['常用案由', frequent]]) {
          if (!entries.length) continue;
          group(title);
          entries.forEach(({ node }) => row(node, { showPath: true, key: title + node.id }));
        }
      }
      const renderBranch = (node, depth) => {
        row(node, { depth });
        if (expanded.has(node.id)) node.children.forEach(child => renderBranch(child, depth + 1));
      };
      for (const key of config.categories) {
        if (category !== 'all' && key !== category) continue;
        group(labels[key] + (key === 'criminal' ? '分类' : '案由目录'));
        catalog.roots.filter(node => node.category === key).forEach(node => renderBranch(node, 0));
      }
    }
    const total = Math.max(items.length, catalogResults.length);
    if (total > limit) {
      const more = button(`显示更多（${limit} / ${total}）`, () => {
        current.limit += pageSize;
        render();
        (list.querySelector('[data-key="more"]') || list.lastElementChild?.querySelector('button'))?.focus();
      }, 'apex-cause-option');
      more.dataset.key = 'more';
      list.append(more);
    }
    footer.replaceChildren();
    const custom = value.trim();
    if (config.custom && custom && !catalog?.byLabel.has(custom) && !items.some(item => item.label === custom)) {
      const use = button('使用当前输入：' + custom, () => commit(custom, null, true), 'apex-cause-use');
      use.title = custom;
      use.dataset.key = 'custom';
      footer.append(use);
    }
    if (current.input.value) {
      const clear = button('清除案由', () => commit(''));
      clear.dataset.key = 'clear';
      footer.append(clear);
    }
    footer.hidden = !footer.childElementCount;
    list.scrollTop = resetScroll ? 0 : oldScroll;
    if (focusedKey) {
      [...popup.querySelectorAll('[data-key]')].find(element => element.dataset.key === focusedKey)?.focus({ preventScroll: true });
    }
  }

  doc.addEventListener('focusin', event => {
    if (event.target.matches(selector)) {
      if (!event.target.readOnly && !event.target.disabled && !writing) open(event.target);
    } else if (current && event.target !== current.anchor && !popup.contains(event.target)) close();
  });
  doc.addEventListener('pointerdown', event => {
    if (current && event.target !== current.anchor && !popup.contains(event.target)) close();
  });
  doc.addEventListener('click', event => {
    if (event.target.matches(selector) && !event.target.readOnly && !event.target.disabled) open(event.target);
  });
  doc.addEventListener('input', event => {
    if (writing || event.isComposing || !event.target.matches(selector)) return;
    chosenIds.delete(event.target);
    open(event.target, event.target.value);
    query(event.target.value);
  });
  doc.addEventListener('compositionend', event => {
    if (event.target.matches(selector) && current?.input === event.target) query(event.target.value);
  });
  doc.addEventListener('keydown', event => {
    const { target, key } = event;
    if (event.isComposing || event.keyCode === 229) return;
    if (!current && target.matches(selector) && !target.readOnly && key === 'ArrowDown') open(target);
    if (!current || (target !== current.anchor && !popup.contains(target))) return;
    if (key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      close(true);
      return;
    }
    if (key === 'Tab' && target === current.anchor && !event.shiftKey) {
      event.preventDefault();
      panelSearch.focus();
      return;
    }
    if (key === 'Tab' && ((event.shiftKey && target === panelSearch) ||
        (!event.shiftKey && target === [...popup.querySelectorAll('input,button')].filter(el => el.getClientRects().length).at(-1)))) {
      close(true);
      if (event.shiftKey) event.preventDefault();
      return;
    }
    if (key === 'Enter' && (target === panelSearch || target === current.anchor)) {
      const first = list.querySelector('.apex-cause-option') || footer.querySelector('.apex-cause-use');
      if (target === panelSearch || (current.query && first)) {
        event.preventDefault();
        first?.click();
      }
      return;
    }
    if (['ArrowDown', 'ArrowUp'].includes(key)) {
      const options = [...list.querySelectorAll('.apex-cause-option')];
      if (!options.length) return;
      event.preventDefault();
      const index = options.indexOf(target);
      const next = index < 0 ? (key === 'ArrowDown' ? 0 : options.length - 1) :
        Math.max(0, Math.min(options.length - 1, index + (key === 'ArrowDown' ? 1 : -1)));
      options[next].focus();
    }
    if (['ArrowLeft', 'ArrowRight'].includes(key) && list.contains(target)) {
      const toggle = target.closest('.apex-cause-row')?.querySelector('.apex-cause-toggle');
      if (toggle && (toggle.getAttribute('aria-expanded') === 'true') === (key === 'ArrowLeft')) {
        event.preventDefault();
        toggle.click();
      }
    }
  }, true);
  root.addEventListener('resize', place);
  root.visualViewport?.addEventListener('resize', place);
  doc.addEventListener('scroll', event => { if (!popup?.contains(event.target)) place(); }, true);
  api.attach = attach;
  api.close = close;
  api.choose = choose;
  root.ApexCausePicker = api;
})(typeof window === 'object' ? window : globalThis);
