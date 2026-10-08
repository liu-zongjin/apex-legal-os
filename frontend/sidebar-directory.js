/* One directory state model for browsing, search and management. Legacy entries
 * below are adapters so existing article and settings consumers keep working. */
const directoryState = (() => {
  const saved = readJsonStore('legal_kb_directory_state_v1', {});
  return {
    mode: saved?.mode === 'click' ? 'click' : 'hover',
    expanded: new Set(
      Array.isArray(saved?.expanded)
        ? saved.expanded.filter((x) => typeof x === 'string' &&
            !(saved?.mode !== 'click' && /^(domain|customLib):/.test(x)))
        : []
    ),
    hoverOpen: new Set(),
    query: '',
    searchCollapsed: new Set(),
    timers: new Map(),
    managerTab: 'domain',
    busy: false,
    editor: null,
    drag: null
  };
})();
function persistDirectoryState() {
  writeJsonStore('legal_kb_directory_state_v1', {
    mode: directoryState.mode,
    expanded: [...directoryState.expanded]
  });
}
function clearDirectoryTimers() {
  directoryState.timers.forEach(clearTimeout);
  directoryState.timers.clear();
}
function directoryPathOpen(key, hit = false) {
  return directoryState.query
    ? hit && !directoryState.searchCollapsed.has(key)
    : directoryState.expanded.has(key) || directoryState.hoverOpen.has(key);
}
function setDirectoryExpansionMode(mode) {
  clearDirectoryTimers();
  directoryState.hoverOpen.clear();
  directoryState.mode = mode === 'click' ? 'click' : 'hover';
  if (directoryState.mode === 'click') {
    const roots = ['domain', 'customLib', 'author'].filter((key) =>
      directoryState.expanded.has(key)
    );
    roots.slice(1).forEach((key) => directoryState.expanded.delete(key));
  }
  persistDirectoryState();
  refreshKnowledgeDirectory();
}
function toggleDirectoryPath(key, force) {
  clearDirectoryTimers();
  const wasOpen = directoryPathOpen(key);
  directoryState.hoverOpen.delete(key);
  if (directoryState.query) {
    if (directoryState.searchCollapsed.has(key)) directoryState.searchCollapsed.delete(key);
    else directoryState.searchCollapsed.add(key);
    refreshKnowledgeDirectory();
    return;
  }
  const open = force === undefined ? !wasOpen : force;
  if (open && directoryState.mode === 'click' && ['domain', 'customLib', 'author'].includes(key))
    ['domain', 'customLib', 'author']
      .filter((x) => x !== key)
      .forEach((x) => directoryState.expanded.delete(x));
  if (open) directoryState.expanded.add(key);
  else directoryState.expanded.delete(key);
  persistDirectoryState();
  refreshKnowledgeDirectory();
}
function bindDirectoryHover(element, key) {
  element.addEventListener('pointerenter', (event) => {
    if (directoryState.mode !== 'hover' || event.pointerType !== 'mouse' || directoryState.query)
      return;
    clearTimeout(directoryState.timers.get(key));
    directoryState.timers.set(
      key,
      setTimeout(() => {
        directoryState.timers.delete(key);
        directoryState.expanded.add(key);
        persistDirectoryState();
        refreshKnowledgeDirectory();
      }, 240)
    );
  });
  element.addEventListener('pointerleave', (event) => {
    if (directoryState.mode !== 'hover' || event.pointerType !== 'mouse' || directoryState.query)
      return;
    clearTimeout(directoryState.timers.get(key));
    directoryState.timers.set(
      key,
      setTimeout(() => {
        directoryState.timers.delete(key);
        if (directoryState.keyboardFocus && element.contains(document.activeElement)) return;
        directoryState.expanded.delete(key);
        [...directoryState.hoverOpen]
          .filter((childKey) => childKey.startsWith(`${key}:`))
          .forEach((childKey) => directoryState.hoverOpen.delete(childKey));
        persistDirectoryState();
        refreshKnowledgeDirectory();
      }, 280)
    );
  });
}
function bindDirectoryChildHover(group, row, content, arrow, key) {
  let openTimer = null;
  let closeTimer = null;
  let latestPoint = null;
  const eligible = (event) => directoryState.mode === 'hover' &&
    !directoryState.query && event.pointerType === 'mouse';
  const show = (open) => {
    directoryState.hoverOpen[open ? 'add' : 'delete'](key);
    content.hidden = !directoryPathOpen(key);
    arrow.setAttribute('aria-expanded', String(!content.hidden));
    arrow.setAttribute('aria-label', `${content.hidden ? '展开' : '收起'}${row.querySelector('.directory-label span')?.textContent || ''}`);
  };
  row.addEventListener('pointerenter', (event) => {
    if (!eligible(event)) return;
    clearTimeout(closeTimer);
    if (!content.hidden) return;
    latestPoint = { x: event.clientX, y: event.clientY };
    const sample = () => {
      const previous = latestPoint;
      openTimer = setTimeout(() => {
        const distance = Math.hypot(latestPoint.x - previous.x, latestPoint.y - previous.y);
        if (distance > 6) return sample();
        // Only one sibling submenu follows the pointer at a time.
        group.parentElement.querySelectorAll(':scope > .directory-node').forEach((sibling) => {
          if (sibling === group) return;
          const siblingKey = sibling.dataset.directoryKey;
          if (!siblingKey || !directoryState.hoverOpen.has(siblingKey)) return;
          directoryState.hoverOpen.delete(siblingKey);
          sibling.querySelector(':scope > .directory-children').hidden = true;
          sibling.querySelector(':scope > .directory-row .directory-arrow').setAttribute('aria-expanded', 'false');
        });
        show(true);
        openTimer = null;
      }, 90);
    };
    sample();
  });
  row.addEventListener('pointermove', (event) => {
    if (eligible(event)) latestPoint = { x: event.clientX, y: event.clientY };
  });
  row.addEventListener('pointerleave', () => {
    clearTimeout(openTimer);
    openTimer = null;
  });
  group.addEventListener('pointerenter', () => clearTimeout(closeTimer));
  group.addEventListener('pointerleave', (event) => {
    if (!eligible(event)) return;
    clearTimeout(openTimer);
    closeTimer = setTimeout(() => show(false), 180);
  });
}
function initKnowledgeDirectory() {
  const nav = $('sidebar-nav');
  if (!nav || nav.dataset.directoryReady) return;
  nav.dataset.directoryReady = 'true';
  nav.classList.add('knowledge-directory');
  ['domain', 'customLib', 'author'].forEach((key) => bindDirectoryHover($(`nav-sec-${key}`), key));
  $('directory-search').addEventListener('input', (event) => {
    clearDirectoryTimers();
    directoryState.query = event.target.value.trim().toLocaleLowerCase();
    directoryState.searchCollapsed.clear();
    refreshKnowledgeDirectory();
  });
  nav.addEventListener('keydown', () => {
    directoryState.keyboardFocus = true;
  });
  nav.addEventListener('pointerdown', () => {
    directoryState.keyboardFocus = false;
  });
  const empty = document.createElement('p');
  empty.id = 'directory-no-results';
  empty.className = 'directory-empty';
  empty.setAttribute('role', 'status');
  empty.textContent = '未找到匹配目录';
  empty.hidden = true;
  nav.querySelector('.directory-tools').after(empty);
  initDirectoryManager();
  refreshKnowledgeDirectory();
}
function directoryNode(
  name,
  count,
  active,
  select,
  children = [],
  key = '',
  path = '',
  dropId = null
) {
  const query = directoryState.query;
  const selfHit = !query || name.toLocaleLowerCase().includes(query);
  const matchedChildren = children.filter(
    (child) => !query || selfHit || child.name.toLocaleLowerCase().includes(query)
  );
  if (!selfHit && !matchedChildren.length) return null;
  const group = document.createElement('div');
  group.className = 'directory-node';
  if (key) group.dataset.directoryKey = key;
  const row = document.createElement('div');
  row.className = 'directory-row';
  const arrow = document.createElement('button');
  arrow.type = 'button';
  arrow.className = 'directory-arrow';
  arrow.dataset.directoryFocus = `arrow:${path}/${name}`;
  arrow.textContent = children.length ? '›' : '·';
  arrow.disabled = !children.length;
  const open = directoryPathOpen(key, !!query && matchedChildren.length > 0);
  arrow.setAttribute('aria-expanded', String(open));
  arrow.setAttribute('aria-label', `${open ? '收起' : '展开'}${name}`);
  arrow.onclick = () => toggleDirectoryPath(key);
  row.append(arrow);
  const label = document.createElement('button');
  label.type = 'button';
  label.className = 'directory-label';
  label.classList.toggle('active', active);
  label.setAttribute('aria-current', active ? 'true' : 'false');
  label.dataset.directoryFocus = `label:${path}/${name}`;
  label.title = path ? `${path} / ${name}` : name;
  const text = document.createElement('span');
  text.textContent = name;
  label.append(text);
  const badge = document.createElement('small');
  badge.textContent = Number(count) || 0;
  label.append(badge);
  label.onclick = select;
  row.append(label);
  group.append(row);
  if (dropId) {
    label.ondragover = (event) => {
      onTagItemDragOver(event, dropId, null);
      if (window._articleDragId) label.classList.add('drop-target');
    };
    label.ondragleave = () => label.classList.remove('drop-target');
    label.ondrop = (event) => {
      label.classList.remove('drop-target');
      onTagItemDrop(event, dropId);
    };
  }
  if (children.length) {
    const content = document.createElement('div');
    content.className = 'directory-children';
    content.hidden = !open;
    matchedChildren.forEach((child) => {
      const node = directoryNode(
        child.name,
        child.count,
        child.active,
        child.select,
        [],
        '',
        name,
        child.dropId
      );
      // A parent name hit includes all descendants.
      if (node) content.append(node);
      else if (selfHit) {
        const previous = directoryState.query;
        directoryState.query = '';
        const all = directoryNode(
          child.name,
          child.count,
          child.active,
          child.select,
          [],
          '',
          name,
          child.dropId
        );
        directoryState.query = previous;
        content.append(all);
      }
    });
    group.append(content);
    if (key) bindDirectoryChildHover(group, row, content, arrow, key);
  }
  return group;
}
function paintDirectory(host, nodes) {
  if (!host) return;
  const focus = document.activeElement;
  const focusedLabel = host.contains(focus) ? focus?.dataset.directoryFocus : null;
  host.replaceChildren(...nodes.filter(Boolean));
  if (!host.children.length) {
    const empty = document.createElement('p');
    empty.className = 'directory-empty';
    empty.textContent = directoryState.query ? '无匹配目录' : '暂无目录';
    host.append(empty);
  }
  if (focusedLabel)
    [...host.querySelectorAll('button')]
      .find((button) => button.dataset.directoryFocus === focusedLabel)
      ?.focus({ preventScroll: true });
}
renderDomains = function (domains) {
  const nodes = _sortedFacetItems(domains || [], 'domain', 'domainOrder').map((root) =>
    directoryNode(
      root.domain,
      root.count,
      state.domain === root.domain && !state.subcategoryId,
      () => selectDomain(root.domain),
      (root.children || []).map((child) => ({
        name: child.name,
        count: child.count,
        active: Number(state.subcategoryId) === child.id,
        select: () => selectSubcategory(child.id, root.domain, child.name)
      })),
      `domain:${root.id}`
    )
  );
  if (_domainPendingCount)
    nodes.unshift(
      directoryNode(
        '待分类',
        _domainPendingCount,
        state.view === 'pending-domains',
        selectPendingDomains
      )
    );
  paintDirectory($('domain-list'), nodes);
  applyDirectorySections();
};
renderAuthors = function (authors) {
  paintDirectory(
    $('author-list'),
    _sortedFacetItems(authors || [], 'author', 'authorOrder').map((author) =>
      directoryNode(author.author, author.count, state.author === author.author, () =>
        selectAuthor(author.author)
      )
    )
  );
  applyDirectorySections();
};
renderTagGroups = function (categories) {
  paintDirectory(
    $('tag-groups-container'),
    (categories || []).map((cat) =>
      directoryNode(
        cat.name,
        cat.count ?? (cat.tags || []).reduce((sum, tag) => sum + (Number(tag.count) || 0), 0),
        state.customCategory === cat.id,
        () => selectCustomCategory(cat.id, cat.name),
        (cat.tags || []).map((tag) => ({
          name: tag.name,
          count: tag.count,
          active: state.currentTagGroupId === tag.id,
          select: () => selectCustomTag(tag.name, tag.id),
          dropId: tag.id
        })),
        `customLib:${cat.id}`
      )
    )
  );
  applyDirectorySections();
};
function applyDirectorySections() {
  for (const key of ['domain', 'customLib', 'author']) {
    const host = $(`section-${key}`),
      heading = $(`nav-sec-${key}`)?.querySelector('.directory-section-heading');
    if (!host || !heading) continue;
    const hits = !!host.querySelector('.directory-node');
    const open = directoryPathOpen(key, hits);
    host.classList.toggle('collapsed', !open);
    host.hidden = !open;
    heading.setAttribute('aria-expanded', String(open));
    $(`nav-sec-${key}`).hidden = !!directoryState.query && !hits;
  }
  const empty = $('directory-no-results');
  if (empty)
    empty.hidden =
      !directoryState.query ||
      ['domain', 'customLib', 'author'].some((key) => !$(`nav-sec-${key}`).hidden);
  document
    .querySelectorAll('[data-directory-mode]')
    .forEach((button) =>
      button.setAttribute(
        'aria-pressed',
        String(button.dataset.directoryMode === directoryState.mode)
      )
    );
}
function refreshKnowledgeDirectory() {
  renderDomains(_domainsEditorCache || []);
  renderAuthors(_authorsEditorCache || []);
  renderTagGroups(_tagCategoriesCache || []);
  const active = !!(
    state.domain ||
    state.author ||
    state.customTag ||
    state.customCategory ||
    state.view === 'pending-domains'
  );
  document
    .querySelectorAll('#sidebar-nav .nav-item[data-view]')
    .forEach((el) => el.classList.toggle('active', !active && el.dataset.view === state.view));
}
function directoryFilterTitle() {
  const child = (_domainsEditorCache || [])
    .flatMap((root) => root.children || [])
    .find((row) => row.id === state.subcategoryId);
  return state.domain
    ? child
      ? `${state.domain} · ${child.name}`
      : state.domain
    : state.author ||
        state.customTag ||
        _tagCategoriesCache.find((cat) => cat.id === state.customCategory)?.name ||
        {
          all: '全部知识',
          notes: '我的笔记',
          url: '网页来源',
          file: '本地文档',
          'pending-domains': '待分类'
        }[state.view] ||
        '全部知识';
}
function chooseDirectoryFilter(fields, title) {
  clearActiveSavedView();
  Object.assign(
    state,
    {
      domain: null,
      subcategoryId: null,
      author: null,
      customTag: null,
      currentTagGroupId: null,
      customCategory: null,
      customCategoryTags: null,
      view: 'all',
      page: 1
    },
    fields
  );
  $('page-title').textContent = title;
  state.sortMode = loadSortModePreference();
  refreshKnowledgeDirectory();
  loadArticles();
}
selectDomain = (domain) => chooseDirectoryFilter({ domain }, domain);
selectAuthor = (author) => chooseDirectoryFilter({ author }, author);
selectSubcategory = (id, domain, name) =>
  chooseDirectoryFilter({ domain, subcategoryId: Number(id) }, `${domain} · ${name}`);
selectCustomTag = (customTag, id) =>
  chooseDirectoryFilter({ customTag, currentTagGroupId: Number(id) || null }, customTag);
selectCustomCategory = (id, name) => {
  const cat = _tagCategoriesCache.find((x) => x.id === Number(id));
  if (!cat) return;
  chooseDirectoryFilter(
    { customCategory: cat.id, customCategoryTags: (cat.tags || []).map((x) => x.name) },
    name
  );
};
selectPendingDomains = () => chooseDirectoryFilter({ view: 'pending-domains' }, '待分类');
switchView = (view, el) => {
  chooseDirectoryFilter(
    { view: ['all', 'url', 'file', 'notes'].includes(view) ? view : 'all' },
    { all: '全部知识', url: '网页来源', file: '本地文档', notes: '我的笔记' }[view] || '全部知识'
  );
};

// The existing intelligent classification panels remain the shared implementation.
function initDirectoryManager() {
  const overlay = $('domain-classification-modal'),
    modal = overlay.querySelector('.modal');
  // The sidebar stays visible on other workspace tabs, whose hidden main page
  // must not hide this shared manager.
  if (overlay.parentElement !== document.body) document.body.append(overlay);
  if (modal.dataset.directoryReady) return;
  modal.dataset.directoryReady = 'true';
  modal.classList.add('directory-manager');
  $('domain-classification-title').textContent = '目录管理';
  const chrome = modal.querySelector('.domain-modal-chrome');
  const tabs = document.createElement('div');
  tabs.className = 'directory-manager-tabs';
  tabs.setAttribute('role', 'tablist');
  tabs.setAttribute('aria-label', '目录分组');
  [
    ['domain', '专业领域'],
    ['customLib', '自定义库'],
    ['author', '作者']
  ].forEach(([key, title]) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = title;
    button.dataset.managerTab = key;
    button.id = `directory-manager-tab-${key}`;
    button.setAttribute(
      'aria-controls',
      key === 'domain' ? 'domain-pane-catalog' : 'directory-manager-extra'
    );
    button.setAttribute('role', 'tab');
    button.onclick = () => setDirectoryManagerTab(key);
    tabs.append(button);
  });
  chrome.querySelector('.modal-header').after(tabs);
  tabs.addEventListener('keydown', (event) => {
    const buttons = [...tabs.querySelectorAll('button')],
      index = buttons.indexOf(document.activeElement);
    if (index < 0 || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next =
      event.key === 'Home'
        ? 0
        : event.key === 'End'
          ? 2
          : (index + (event.key === 'ArrowRight' ? 1 : -1) + 3) % 3;
    buttons[next].click();
    buttons[next].focus();
  });
  overlay.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      if (directoryState.drag) { clearDirectoryDrag(); event.preventDefault(); return; }
      event.preventDefault();
      event.stopPropagation();
      closeDomainClassificationModal();
      return;
    }
    if (event.key !== 'Tab') return;
    const focusable = [
      ...modal.querySelectorAll('button:not(:disabled),input:not(:disabled),summary,[tabindex="0"]')
    ].filter((el) => el.getClientRects().length);
    const first = focusable[0],
      last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  });
  const extra = document.createElement('div');
  extra.id = 'directory-manager-extra';
  extra.className = 'domain-modal-content';
  extra.hidden = true;
  modal.append(extra);
  modal.querySelector('.domain-text-action')?.remove();
  const rename = document.createElement('div');
  rename.className = 'modal-overlay';
  rename.id = 'directory-action-modal';
  rename.innerHTML =
    '<div class="modal directory-action-dialog" role="dialog" aria-modal="true" aria-labelledby="directory-action-title"><div class="modal-header"><h2 id="directory-action-title"></h2><button type="button" class="btn-icon" aria-label="关闭" onclick="closeDirectoryAction()">×</button></div><div class="modal-body"><p id="directory-action-impact"></p><input id="directory-action-name" class="form-input" maxlength="80" aria-label="目录名称"><label id="directory-preserve-option" hidden><input id="directory-preserve-tags" type="checkbox">仅移除目录，保留文章标签</label><p id="directory-action-error" role="alert"></p></div><div class="modal-footer"><button class="btn-secondary" type="button" onclick="closeDirectoryAction()">取消</button><button class="btn-primary" id="directory-action-submit" type="button" onclick="submitDirectoryAction()">确认</button></div></div>';
  rename.addEventListener('keydown', (event) => {
    if (event.key !== 'Tab') return;
    const buttons = [
      ...rename.querySelectorAll('button:not(:disabled),input:not(:disabled)')
    ].filter((el) => el.getClientRects().length);
    const first = buttons[0],
      last = buttons[buttons.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
  rename.onclick = (event) => {
    if (event.target === rename) closeDirectoryAction();
  };
  document.body.append(rename);
  $('directory-action-name').onkeydown = (event) => {
    if (event.key === 'Enter') submitDirectoryAction();
  };
  document.addEventListener(
    'keydown',
    (event) => {
      if (event.key === 'Escape' && rename.classList.contains('open')) {
        event.stopImmediatePropagation();
        closeDirectoryAction();
      }
    },
    true
  );
}
function setDirectoryManagerTab(tab) {
  directoryState.managerTab = tab;
  const modal = $('domain-classification-modal');
  modal.querySelectorAll('[data-manager-tab]').forEach((button) => {
    const selected = button.dataset.managerTab === tab;
    button.setAttribute('aria-selected', String(selected));
    button.tabIndex = selected ? 0 : -1;
  });
  for (const el of modal.querySelectorAll(
    '.domain-modal-chrome > :not(.directory-manager-tabs), .domain-modal-content:not(#directory-manager-extra)'
  ))
    el.hidden = tab !== 'domain';
  // Keep the common title and close button visible on every tab.
  modal.querySelector('.modal-header').hidden = false;
  $('directory-manager-extra').hidden = tab === 'domain';
  $('directory-manager-extra').setAttribute('role', 'tabpanel');
  $('directory-manager-extra').setAttribute('aria-labelledby', `directory-manager-tab-${tab}`);
  if (tab !== 'domain') {
    clearTimeout(domainDiscoveryTimer);
    domainDiscoveryTimer = null;
    renderDirectoryManagerExtra();
  } else {
    renderDomainChildOrder();
    loadDomainDiscoveryStatus();
  }
}
async function openKnowledgeDirectoryManager(tab = 'domain') {
  initDirectoryManager();
  directoryState.returnFocus = document.activeElement;
  $('domain-classification-modal').classList.add('open');
  setDirectoryManagerTab(tab);
  setDomainModalTab('catalog');
  await Promise.allSettled([loadDomains(), loadAuthors(), loadTagGroups()]);
  renderDomainModalParents();
  renderDomainChildOrder();
  renderDirectoryManagerExtra();
  if (tab === 'domain')
    await Promise.allSettled([loadDomainSuggestions(), loadDomainDiscoveryStatus()]);
  $('domain-classification-modal')
    .querySelector('[data-manager-tab][aria-selected="true"]')
    ?.focus();
}
openDomainClassificationModal = () => openKnowledgeDirectoryManager('domain');
openTagListEditorModal = () => openKnowledgeDirectoryManager('customLib');
const directoryOriginalClose = closeDomainClassificationModal;
closeDomainClassificationModal = () => {
  clearDirectoryDrag();
  directoryOriginalClose();
  directoryState.returnFocus?.focus?.();
};
function directoryCollection(kind, parent) {
  if (kind === 'child')
    return ((_domainsEditorCache || []).find((root) => root.id === parent)?.children || []).map(
      (x) => ({ ...x, name: x.name })
    );
  if (kind === 'domain')
    return _sortedFacetItems(_domainsEditorCache, 'domain', 'domainOrder').map((x) => ({
      ...x,
      name: x.domain
    }));
  if (kind === 'author')
    return _sortedFacetItems(_authorsEditorCache, 'author', 'authorOrder').map((x) => ({
      ...x,
      name: x.author
    }));
  if (kind === 'category') return _tagCategoriesCache;
  return _tagCategoriesCache.find((x) => x.id === parent)?.tags || [];
}
// A drop describes an insertion boundary, not a swap with the hovered row.
function directoryDropIndex(from, target, after) {
  const boundary = target + (after ? 1 : 0);
  return boundary > from ? boundary - 1 : boundary;
}
function clearDirectoryDropIndicators() {
  document.querySelectorAll('.directory-drop-before,.directory-drop-after,.directory-drop-inside')
    .forEach((row) => row.classList.remove('directory-drop-before', 'directory-drop-after', 'directory-drop-inside'));
}
function directoryPointerTarget(clientX, clientY) {
  const row = document.elementFromPoint(clientX, clientY)?.closest('.directory-manager-row');
  const source = directoryState.drag;
  if (!row || !source) return null;
  const kind = row.dataset.sortKind, parent = row.dataset.sortParent;
  if (kind === source.kind && parent === String(source.parent))
    return {row, index: Number(row.dataset.sortIndex), sameGroup: true};
  if (kind === 'category' && source.kind === 'tag' && Number(row.dataset.sortId) !== source.parent)
    return {row, categoryId: Number(row.dataset.sortId), sameGroup: false};
  return null;
}
function paintDirectoryPointerTarget(clientX, clientY) {
  clearDirectoryDropIndicators();
  const target = directoryPointerTarget(clientX, clientY);
  if (!target) return;
  if (!target.sameGroup) target.row.classList.add('directory-drop-inside');
  else if (target.index !== directoryState.drag.index) {
    const after = clientY >= target.row.getBoundingClientRect().top + target.row.offsetHeight / 2;
    target.row.classList.add(after ? 'directory-drop-after' : 'directory-drop-before');
  }
}
let directoryDragFrame = null;
function clearDirectoryDrag() {
  const source = directoryState.drag;
  directoryState.drag = null;
  source?.cancel?.();
  cancelAnimationFrame(directoryDragFrame);
  directoryDragFrame = null;
  clearDirectoryDropIndicators();
  document.querySelectorAll('.directory-dragging').forEach((row) => row.classList.remove('directory-dragging'));
}
function scrollDirectoryDrag(host, clientX, clientY) {
  cancelAnimationFrame(directoryDragFrame);
  directoryDragFrame = null;
  if (!host) return;
  const bounds = host.getBoundingClientRect();
  const speed = clientY < bounds.top + 48 ? -8 : clientY > bounds.bottom - 48 ? 8 : 0;
  if (!speed) return;
  const tick = () => {
    if (!directoryState.drag) return;
    const previous = host.scrollTop;
    host.scrollTop += speed;
    if (host.scrollTop === previous) { directoryDragFrame = null; return; }
    paintDirectoryPointerTarget(clientX, clientY);
    directoryDragFrame = requestAnimationFrame(tick);
  };
  directoryDragFrame = requestAnimationFrame(tick);
}
function directoryManagerRows(kind, parent = null) {
  const host = document.createElement('div');
  host.className = 'directory-manager-rows';
  const rows = directoryCollection(kind, parent);
  rows.forEach((item, index) => {
    const row = document.createElement('div');
    row.className = 'directory-manager-row';
    row.dataset.directoryRowKey = `${kind}:${item.id ?? item.name}`;
    row.dataset.sortKind = kind;
    row.dataset.sortParent = String(parent);
    row.dataset.sortIndex = index;
    row.dataset.sortId = item.id;
    const handle = document.createElement('button');
    handle.type = 'button';
    handle.className = 'directory-drag-handle';
    handle.textContent = '⠿';
    handle.draggable = false;
    handle.disabled = directoryState.busy || rows.length < 2;
    handle.setAttribute('aria-label', `调整${item.name}顺序`);
    handle.title = '拖动调整顺序；按住 Option / Alt，方向键移动，Home / End 移到首尾';
    handle.onkeydown = (event) => {
      if (!event.altKey || !['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const to = event.key === 'Home' ? 0 : event.key === 'End' ? rows.length - 1
        : index + (event.key === 'ArrowUp' ? -1 : 1);
      reorderDirectory(kind, parent, index, to);
    };
    // Pointer capture works consistently in WKWebView, including touch input.
    let pointer = null;
    handle.onpointerdown = (event) => {
      if (directoryState.busy || handle.disabled || event.button !== 0) return;
      event.preventDefault();
      clearDirectoryDrag();
      handle.focus({ preventScroll: true });
      pointer = {id: event.pointerId, x: event.clientX, y: event.clientY};
      handle.setPointerCapture(event.pointerId);
    };
    handle.onpointermove = (event) => {
      if (!pointer || pointer.id !== event.pointerId) return;
      if (!directoryState.drag && Math.hypot(event.clientX - pointer.x, event.clientY - pointer.y) < 4) return;
      directoryState.drag = {kind, parent, index, cancel: () => {
        const active = pointer;
        pointer = null;
        if (active && handle.hasPointerCapture(active.id)) handle.releasePointerCapture(active.id);
      }};
      row.classList.add('directory-dragging');
      paintDirectoryPointerTarget(event.clientX, event.clientY);
      scrollDirectoryDrag(row.closest('.domain-modal-content'), event.clientX, event.clientY);
    };
    handle.onpointerup = (event) => {
      if (!pointer || pointer.id !== event.pointerId) return;
      const target = directoryPointerTarget(event.clientX, event.clientY);
      pointer = null;
      clearDirectoryDrag();
      handle.releasePointerCapture(event.pointerId);
      if (!target) return;
      if (target.sameGroup) {
        const after = event.clientY >= target.row.getBoundingClientRect().top + target.row.offsetHeight / 2;
        reorderDirectory(kind, parent, index, directoryDropIndex(index, target.index, after));
      } else moveDirectoryTag(parent, index, target.categoryId);
    };
    handle.onpointercancel = handle.onlostpointercapture = () => {
      pointer = null;
      clearDirectoryDrag();
    };
    row.append(handle);
    const label = document.createElement('span');
    label.textContent = item.name;
    label.title = item.name;
    row.append(label);
    const count = document.createElement('small');
    count.textContent = `${Number(item.count) || 0} 篇`;
    row.append(count);
    const actions = document.createElement('div');
    actions.className = 'directory-row-actions';
    [
      ['改名', '改名', () => openDirectoryAction('rename', kind, item, parent), false],
      ['删除', '删除', () => openDirectoryAction('delete', kind, item, parent), false]
    ].forEach(([text, label, action, disabled]) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = text;
      button.setAttribute('aria-label', `${item.name}${label}`);
      button.disabled = disabled || directoryState.busy;
      button.onclick = action;
      actions.append(button);
    });
    if (kind === 'category') {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = '＋标签';
      button.onclick = () => openDirectoryAction('create', 'tag', {}, item.id);
      actions.append(button);
    }
    row.append(actions);
    host.append(row);
    if (kind === 'domain') host.append(directoryManagerRows('child', item.id));
    if (kind === 'category') host.append(directoryManagerRows('tag', item.id));
  });
  return host;
}
function preserveDirectoryManagerFocus(host, paint) {
  const focused = document.activeElement,
    row = host.contains(focused) ? focused.closest('[data-directory-row-key]') : null;
  const key = row?.dataset.directoryRowKey,
    text = focused?.textContent;
  paint();
  if (key) {
    const replacement = [...host.querySelectorAll('[data-directory-row-key]')].find(
      (item) => item.dataset.directoryRowKey === key
    );
    const actions = [...(replacement?.querySelectorAll('button:not(:disabled)') || [])];
    (
      actions.find((button) => button.textContent === text) ||
      actions.find((button) => button.textContent === '改名') ||
      actions[0]
    )?.focus({ preventScroll: true });
  }
}
renderDomainChildOrder = function () {
  if (!$('domain-child-order')) return;
  const roots = _domainsEditorCache || [];
  $('domain-approved-count').textContent =
    `${roots.length} 个领域 · ${roots.reduce((sum, root) => sum + (root.children || []).length, 0)} 个子分类`;
  preserveDirectoryManagerFocus($('domain-child-order'), () => {
    $('domain-child-order').replaceChildren(directoryManagerRows('domain'));
  });
};
function renderDirectoryManagerExtra() {
  const host = $('directory-manager-extra');
  if (!host) return;
  preserveDirectoryManagerFocus(host, () => {
    const custom = directoryState.managerTab === 'customLib';
    host.replaceChildren();
    const intro = document.createElement('p');
    intro.className = 'domain-classification-help';
    intro.textContent = '拖动左侧手柄调整顺序，松开后自动保存。键盘：Option / Alt ＋ ↑ ↓ 移动，Home / End 移到首尾。删除目录保留文章。';
    host.append(intro);
    if (custom) {
      const add = document.createElement('button');
      add.type = 'button';
      add.className = 'btn-secondary';
      add.textContent = '＋ 新建自定义库';
      add.onclick = () => openDirectoryAction('create', 'category', {});
      host.append(add);
    }
    host.append(directoryManagerRows(custom ? 'category' : 'author'));
  });
}
function closeDirectoryAction() {
  if (directoryState.busy) return;
  $('directory-action-modal').classList.remove('open');
  directoryState.actionFocus?.focus?.();
}
function openDirectoryAction(mode, kind, item, parent = null) {
  if (directoryState.busy) return;
  directoryState.editor = { mode, kind, item: { ...item }, parent };
  directoryState.actionFocus = document.activeElement;
  $('directory-action-title').textContent = {
    rename: '修改名称',
    delete: '删除目录',
    create: '新增目录'
  }[mode];
  $('directory-action-impact').textContent =
    mode === 'delete'
      ? `确定删除「${item.name}」？涉及 ${Number(item.count) || 0} 篇文章。文章保留，分类或标签关联将移除。${kind === 'child' ? '此名称不会被再次自动建议。' : ''}`
      : '确认后即时保存，原有文章关联保留。';
  const input = $('directory-action-name');
  input.hidden = mode === 'delete';
  input.value = mode === 'rename' ? item.name : '';
  $('directory-preserve-option').hidden = mode !== 'delete' || kind !== 'tag';
  $('directory-preserve-tags').checked = false;
  $('directory-action-error').textContent = '';
  $('directory-action-modal').classList.add('open');
  (mode === 'delete' ? $('directory-action-submit') : input).focus();
  if (mode !== 'delete') input.select();
}
async function submitDirectoryAction() {
  if (directoryState.busy || !directoryState.editor) return;
  const { mode, kind, item, parent } = directoryState.editor,
    name = $('directory-action-name').value.trim();
  if (mode !== 'delete' && !name) {
    $('directory-action-error').textContent = '请输入名称';
    return;
  }
  if (!navigator.onLine) {
    $('directory-action-error').textContent = '联网后才能管理目录';
    return;
  }
  const base =
    kind === 'child'
      ? '/api/domains/categories'
      : kind === 'domain'
        ? '/api/domains'
        : kind === 'author'
          ? '/api/authors'
          : kind === 'category'
            ? '/api/tag-categories'
            : '/api/tag-groups';
  let url = base,
    method = 'POST',
    body = { name };
  if (mode === 'rename') {
    method = 'PUT';
    url = kind === 'domain' || kind === 'author' ? `${base}/rename` : `${base}/${item.id}/rename`;
    body = kind === 'domain' || kind === 'author' ? { old: item.name, new: name } : { name };
  }
  if (mode === 'delete') {
    method = 'DELETE';
    url = `${base}/${kind === 'domain' || kind === 'author' ? encodeURIComponent(item.name) : item.id}`;
    body = undefined;
    if (kind === 'tag' && $('directory-preserve-tags').checked) url += '/purge';
  }
  if (mode === 'create' && kind === 'tag') body.category_id = parent;
  directoryState.busy = true;
  $('directory-action-submit').disabled = true;
  try {
    const result = await apiFetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      ...(body ? { body: JSON.stringify(body) } : {})
    });
    applyDirectoryMutation(mode, kind, item, parent, name, result);
    $('directory-action-modal').classList.remove('open');
    renderDomainChildOrder();
    renderDirectoryManagerExtra();
    await Promise.allSettled([loadDomains(), loadAuthors(), loadTagGroups()]);
    renderDomainChildOrder();
    renderDirectoryManagerExtra();
    refreshKnowledgeDirectory();
    loadArticles();
    showToast('目录已保存');
  } catch (error) {
    $('directory-action-error').textContent = error.message || '保存失败，请重试';
  } finally {
    directoryState.busy = false;
    $('directory-action-submit').disabled = false;
    renderDomainChildOrder();
    renderDirectoryManagerExtra();
    if (!$('directory-action-modal').classList.contains('open'))
      $('domain-classification-modal')
        .querySelector('[data-manager-tab][aria-selected="true"]')
        ?.focus({ preventScroll: true });
  }
}
function applyDirectoryMutation(mode, kind, item, parent, name, result = {}) {
  ++domainDirectoryRequestVersion;
  ++authorsDirectoryRequestVersion;
  ++tagGroupsDirectoryRequestVersion;
  if (articleOfflineSnapshot && mode !== 'create') {
    articleOfflineSnapshot = {
      ...articleOfflineSnapshot,
      articles: articleOfflineSnapshot.articles.map((article) => {
        const next = { ...article };
        if (kind === 'child' && mode === 'delete')
          next.subcategory_ids = (next.subcategory_ids || []).filter((id) => id !== item.id);
        if (kind === 'domain') {
          next.domains = (next.domains || []).flatMap((value) =>
            value === item.name ? (mode === 'delete' ? [] : [name]) : [value]
          );
          if (mode === 'delete')
            next.subcategory_ids = (next.subcategory_ids || []).filter(
              (id) => !(item.children || []).some((child) => child.id === id)
            );
        }
        if (kind === 'author' || kind === 'tag' || kind === 'category') {
          const names =
            kind === 'category'
              ? (item.tags || []).map((tag) => tag.name)
              : [kind === 'author' ? `作者:${item.name}` : item.name];
          if (!(kind === 'tag' && mode === 'delete' && $('directory-preserve-tags').checked))
            next.tags = (next.tags || []).flatMap((value) =>
              names.includes(value)
                ? mode === 'delete'
                  ? []
                  : [kind === 'author' ? `作者:${name}` : name]
                : [value]
            );
        }
        return next;
      })
    };
    writeArticleOfflineSnapshot(articleOfflineSnapshot).catch(() => {});
  }
  if (mode === 'create') {
    if (kind === 'category') _tagCategoriesCache.push({ id: result.id, name, count: 0, tags: [] });
    if (kind === 'tag')
      _tagCategoriesCache
        .find((cat) => cat.id === parent)
        ?.tags.push({ id: result.id, name, count: 0 });
  }
  const change = (list) =>
    mode === 'delete'
      ? list.filter((row) => row.id !== item.id)
      : list.map((row) => (row.id === item.id ? { ...row, name } : row));
  if (kind === 'child')
    _domainsEditorCache = _domainsEditorCache.map((root) => ({
      ...root,
      children: root.id === parent ? change(root.children || []) : root.children
    }));
  if (kind === 'domain')
    _domainsEditorCache =
      mode === 'delete'
        ? _domainsEditorCache.filter((row) => row.domain !== item.name)
        : _domainsEditorCache.map((row) =>
            row.domain === item.name ? { ...row, domain: name } : row
          );
  if (kind === 'author')
    _authorsEditorCache =
      mode === 'delete'
        ? _authorsEditorCache.filter((row) => row.author !== item.name)
        : _authorsEditorCache.map((row) =>
            row.author === item.name ? { ...row, author: name } : row
          );
  if (kind === 'category' && mode !== 'create') _tagCategoriesCache = change(_tagCategoriesCache);
  if (kind === 'tag' && mode !== 'create')
    _tagCategoriesCache = _tagCategoriesCache.map((cat) => ({
      ...cat,
      tags: cat.id === parent ? change(cat.tags || []) : cat.tags
    }));
  _tagGroupsCache = _tagCategoriesCache.flatMap((cat) => cat.tags || []);
  writeNavDirectoryCache(DOMAINS_OFFLINE_CACHE_KEY, _domainsEditorCache);
  writeNavDirectoryCache(AUTHORS_OFFLINE_CACHE_KEY, _authorsEditorCache);
  writeJsonStore(TAG_CATEGORIES_OFFLINE_CACHE_KEY, _tagCategoriesCache);
  if (kind === 'child' && state.subcategoryId === item.id) {
    if (mode === 'delete') state.subcategoryId = null;
  }
  if (kind === 'domain' && state.domain === item.name) {
    state.domain = mode === 'delete' ? null : name;
    state.subcategoryId = null;
  }
  if (kind === 'author' && state.author === item.name)
    state.author = mode === 'delete' ? null : name;
  if (kind === 'category' && state.customCategory === item.id) {
    state.customCategory = mode === 'delete' ? null : item.id;
    state.customCategoryTags = mode === 'delete' ? null : state.customCategoryTags;
  }
  if (kind === 'tag' && state.currentTagGroupId === item.id) {
    state.customTag = mode === 'delete' ? null : name;
    state.currentTagGroupId = mode === 'delete' ? null : item.id;
  }
  if (state.customCategory)
    state.customCategoryTags = (
      _tagCategoriesCache.find((cat) => cat.id === state.customCategory)?.tags || []
    ).map((tag) => tag.name);
  if (kind === 'domain' || kind === 'author') {
    const key = kind === 'domain' ? 'domainOrder' : 'authorOrder';
    writeJsonStore(
      key,
      _readFacetOrder(key).flatMap((value) =>
        value === item.name ? (mode === 'delete' ? [] : [name]) : [value]
      )
    );
  }
  $('page-title').textContent = directoryFilterTitle();
  refreshKnowledgeDirectory();
}
async function reorderDirectory(kind, parent, from, to) {
  if (directoryState.busy) return;
  if (!navigator.onLine) {
    showToast('联网后才能调整目录顺序', 'error');
    return;
  }
  const rows = directoryCollection(kind, parent);
  if (to < 0 || to >= rows.length || from === to) return;
  const next = [...rows];
  next.splice(to, 0, next.splice(from, 1)[0]);
  directoryState.busy = true;
  try {
    if (kind === 'domain' || kind === 'author') {
      const key = kind === 'domain' ? 'domainOrder' : 'authorOrder';
      writeJsonStore(
        key,
        next.map((x) => x.name)
      );
      if (JSON.stringify(_readFacetOrder(key)) !== JSON.stringify(next.map((x) => x.name)))
        throw new Error('无法保存本机排序偏好');
    } else {
      const url =
        kind === 'child'
          ? '/api/domains/categories/reorder'
          : kind === 'category'
            ? '/api/tag-categories/reorder'
            : '/api/tag-groups/reorder';
      await apiFetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ids: next.map((x) => x.id),
          ...(kind === 'child'
            ? { parent_id: parent }
            : kind === 'tag'
              ? { category_id: parent }
              : {})
        })
      });
      if (kind === 'child') _domainsEditorCache.find((root) => root.id === parent).children = next;
      if (kind === 'category') _tagCategoriesCache = next;
      if (kind === 'tag') _tagCategoriesCache.find((cat) => cat.id === parent).tags = next;
    }
    _tagGroupsCache = _tagCategoriesCache.flatMap((cat) => cat.tags || []);
    writeNavDirectoryCache(DOMAINS_OFFLINE_CACHE_KEY, _domainsEditorCache);
    writeJsonStore(TAG_CATEGORIES_OFFLINE_CACHE_KEY, _tagCategoriesCache);
    showToast('顺序已保存');
  } catch (error) {
    showToast(`排序未保存：${error.message || '请重试'}`, 'error');
  } finally {
    directoryState.busy = false;
    renderDomainChildOrder();
    renderDirectoryManagerExtra();
    refreshKnowledgeDirectory();
  }
}

// Specialized analysis actions share the same pending/offline gate as the editor.
function directoryManagedAction(action) {
  return async (...args) => {
    if (directoryState.busy) return;
    if (!navigator.onLine) {
      showToast('联网后才能管理目录', 'error');
      return;
    }
    directoryState.busy = true;
    const buttons = [
      ...$('domain-classification-modal').querySelectorAll('.domain-modal-content button')
    ];
    const disabled = buttons.map((button) => button.disabled);
    buttons.forEach((button) => (button.disabled = true));
    try {
      await action(...args);
    } finally {
      directoryState.busy = false;
      buttons.forEach((button, index) => (button.disabled = disabled[index]));
      $('domain-reclass-apply').disabled = !domainReclassPreview?.items?.length;
      renderDomainChildOrder();
      renderDirectoryManagerExtra();
      refreshKnowledgeDirectory();
    }
  };
}
createDomainCategoryFromModal = directoryManagedAction(createDomainCategoryFromModal);
reviewDomainSuggestion = directoryManagedAction(reviewDomainSuggestion);
restartDomainDiscovery = directoryManagedAction(restartDomainDiscovery);
applyDomainReclassification = directoryManagedAction(applyDomainReclassification);

function cacheCreatedDomainNode(node) {
  ++domainDirectoryRequestVersion;
  _domainsEditorCache = _domainsEditorCache || [];
  if (node.parent_id !== null && node.parent_id !== undefined) {
    const root = _domainsEditorCache.find((item) => item.id === node.parent_id);
    if (root && !(root.children || []).some((child) => child.id === node.id))
      root.children = [...(root.children || []), { ...node, count: 0 }];
  } else if (!_domainsEditorCache.some((root) => root.id === node.id))
    _domainsEditorCache.push({ id: node.id, domain: node.name, count: 0, children: [] });
  writeNavDirectoryCache(DOMAINS_OFFLINE_CACHE_KEY, _domainsEditorCache);
  refreshKnowledgeDirectory();
}

async function moveDirectoryTag(parent, index, target) {
  if (directoryState.busy || parent === target) return;
  if (!navigator.onLine) {
    showToast('联网后才能移动标签', 'error');
    return;
  }
  const source = _tagCategoriesCache.find((cat) => cat.id === parent),
    destination = _tagCategoriesCache.find((cat) => cat.id === target),
    tag = source?.tags[index];
  if (!tag || !destination) return;
  directoryState.busy = true;
  try {
    await apiFetch(`/api/tag-groups/${tag.id}/move`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ category_id: target })
    });
    ++tagGroupsDirectoryRequestVersion;
    source.tags = source.tags.filter((item) => item.id !== tag.id);
    destination.tags.push(tag);
    if (state.customCategory)
      state.customCategoryTags = (
        _tagCategoriesCache.find((cat) => cat.id === state.customCategory)?.tags || []
      ).map((item) => item.name);
    _tagGroupsCache = _tagCategoriesCache.flatMap((cat) => cat.tags || []);
    writeJsonStore(TAG_CATEGORIES_OFFLINE_CACHE_KEY, _tagCategoriesCache);
    showToast('标签已移动');
    loadArticles();
  } catch (error) {
    showToast(error.message || '移动失败', 'error');
  } finally {
    directoryState.busy = false;
    renderDirectoryManagerExtra();
    refreshKnowledgeDirectory();
  }
}

// Article badges and statistics reuse the same filter transitions.
function clearDirectoryArticleSearch() {
  state.q = '';
  if ($('search-input')) $('search-input').value = '';
}
filterByDomain = (domain) => {
  clearDirectoryArticleSearch();
  selectDomain(domain);
};
filterByAuthor = (author) => {
  clearDirectoryArticleSearch();
  selectAuthor(author || null);
};
filterBySource = (view) => {
  clearDirectoryArticleSearch();
  switchView(view === 'url' || view === 'file' ? view : 'all');
};

function normalizeDirectoryFilterState() {
  if (state.domain) {
    state.author = null;
    state.customTag = null;
    state.currentTagGroupId = null;
    state.customCategory = null;
    state.customCategoryTags = null;
    return;
  }
  state.subcategoryId = null;
  if (state.author) {
    state.customTag = null;
    state.currentTagGroupId = null;
    state.customCategory = null;
    state.customCategoryTags = null;
    return;
  }
  if (state.currentTagGroupId) {
    const tag = _tagCategoriesCache
      .flatMap((cat) => cat.tags || [])
      .find((item) => item.id === Number(state.currentTagGroupId));
    state.customTag = tag?.name || null;
    state.currentTagGroupId = tag?.id || null;
    state.customCategory = null;
    state.customCategoryTags = null;
  } else if (state.customCategory) {
    const cat = _tagCategoriesCache.find((item) => item.id === Number(state.customCategory));
    state.customCategory = cat?.id || null;
    state.customCategoryTags = cat ? (cat.tags || []).map((tag) => tag.name) : null;
    state.customTag = null;
  }
}
