// Behavioral regressions run in a VM with anonymous fixtures and deferred I/O.
const fs = require('fs'),
  vm = require('vm'),
  assert = require('assert');
const app = fs.readFileSync('frontend/app.js', 'utf8');
const directory = fs.readFileSync('frontend/sidebar-directory.js', 'utf8');
const store = new Map();
const grid = { innerHTML: '' };
const title = { textContent: '' };
const elements = { 'article-grid': grid, 'page-title': title };
const ctx = {
  console,
  URLSearchParams,
  URL,
  Set,
  Map,
  JSON,
  Number,
  String,
  Date,
  Array,
  Promise,
  setTimeout,
  clearTimeout,
  localStorage: {
    getItem: (key) => store.get(key) || null,
    setItem: (key, value) => store.set(key, value)
  },
  document: { querySelectorAll: () => [], activeElement: null },
  navigator: { onLine: true },
  location: { origin: 'http://test' },
  state: { view: 'all', page: 1, pageSize: 10, fuzzy: true, q: '', sortMode: 'time' },
  $: (id) => elements[id] || null,
  requestAnimationFrame: (fn) => fn(),
  escapeHtml: String,
  readJsonStore: (key, fallback) => {
    try {
      return JSON.parse(store.get(key)) || fallback;
    } catch {
      return fallback;
    }
  },
  writeJsonStore: (key, value) => store.set(key, JSON.stringify(value)),
  generateArticleListPinScope: () => '',
  applyArticleOrder: (x) => x,
  renderPagination: () => {},
  loadAllNotes: () => {},
  searchNotes: () => {},
  renderNotesList: (notes) => {
    grid.innerHTML = notes.map((x) => x.title).join(',');
  },
  renderNoteSearchResults: (notes) => {
    grid.innerHTML = notes.map((x) => x.title).join(',');
  },
  refreshNavCounts: () => {},
  renderArticles: (articles) => {
    grid.innerHTML = articles.map((x) => x.title).join(',');
  },
  clearActiveSavedView: () => {},
  loadSortModePreference: () => 'time',
  renderDomains: () => {},
  renderAuthors: () => {},
  renderTagGroups: () => {},
  selectDomain: () => {},
  selectAuthor: () => {},
  selectSubcategory: () => {},
  selectCustomTag: () => {},
  selectCustomCategory: () => {},
  selectPendingDomains: () => {},
  switchView: () => {},
  createDomainCategoryFromModal: () => {},
  reviewDomainSuggestion: () => {},
  restartDomainDiscovery: () => {},
  applyDomainReclassification: () => {},
  openDomainClassificationModal: () => {},
  closeDomainClassificationModal: () => {},
  openTagListEditorModal: () => {},
  renderDomainChildOrder: () => {},
  _domainsEditorCache: [],
  _authorsEditorCache: [],
  _tagCategoriesCache: [],
  _domainPendingCount: 0,
  domainDirectoryRequestVersion: 0,
  authorsDirectoryRequestVersion: 0,
  tagGroupsDirectoryRequestVersion: 0,
  DOMAINS_OFFLINE_CACHE_KEY: 'domains',
  AUTHORS_OFFLINE_CACHE_KEY: 'authors',
  TAG_CATEGORIES_OFFLINE_CACHE_KEY: 'cats',
  writeNavDirectoryCache: (key, value) => store.set(key, JSON.stringify(value)),
  _readFacetOrder: (key) => JSON.parse(store.get(key) || '[]'),
  _sortedFacetItems: (items) => items || [],
  showToast: () => {},
  articleSearchText: (article) => article.title || '',
  articleOfflineSnapshot: null,
  closeSavedViewsDropdown: () => {},
  readSavedViewsStore: () => ctx.savedViews,
  applyArticleDensity: () => {},
  renderSortModeToggle: () => {},
  renderSavedViews: () => {}
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(
  app.slice(app.indexOf('function readJsonStore('), app.indexOf('function readSavedViewsStore(')),
  ctx
);
vm.runInContext(
  app.slice(
    app.indexOf('let articleListRequestVersion ='),
    app.indexOf('\nfunction renderArticles')
  ),
  ctx
);
vm.runInContext(
  app.slice(
    app.indexOf('function articleMatchesOffline('),
    app.indexOf('\nfunction offlineContentSnippets')
  ),
  ctx
);
vm.runInContext(
  app.slice(
    app.indexOf('function getCurrentViewPayload('),
    app.indexOf('\nfunction deleteSavedView')
  ),
  ctx
);
vm.runInContext(
  app.slice(app.indexOf('async function loadAllNotes('), app.indexOf('function renderNotesList(')),
  ctx
);
vm.runInContext(
  app.slice(app.indexOf('async function searchNotes('), app.indexOf('function highlightText(')),
  ctx
);
vm.runInContext(
  app.slice(
    app.indexOf('function offlineArticleList('),
    app.indexOf('function offlineArticleDetail(')
  ),
  ctx
);
vm.runInContext(directory, ctx);
vm.runInContext(
  'renderDomainChildOrder=()=>{};renderDirectoryManagerExtra=()=>{};refreshKnowledgeDirectory=()=>{};renderDomains=()=>{};',
  ctx
);
const tick = () => new Promise((resolve) => setImmediate(resolve));
(async () => {
  const requests = [];
  ctx.apiFetch = (url) => new Promise((resolve, reject) => requests.push({ url, resolve, reject }));
  ctx.state.domain = '旧领域';
  ctx.loadArticles();
  ctx.state.domain = '新领域';
  ctx.loadArticles();
  requests[1].resolve({ articles: [{ title: '新结果' }], total: 1, page: 1, page_size: 10 });
  await tick();
  requests[0].resolve({ articles: [{ title: '旧结果' }], total: 9, page: 1, page_size: 10 });
  await tick();
  assert.equal(grid.innerHTML, '新结果');
  assert.equal(ctx.state.total, 1);
  assert(requests[0].url.includes(encodeURIComponent('旧领域')));
  ctx.loadArticles();
  ctx.loadArticles();
  requests[3].resolve({ articles: [{ title: '仍是新结果' }], total: 1, page: 1, page_size: 10 });
  await tick();
  requests[2].reject(new Error('旧请求失败'));
  await tick();
  assert.equal(grid.innerHTML, '仍是新结果');
  ctx.state.view = 'notes';
  ctx.state.q = '';
  ctx.loadArticles();
  ctx.state.view = 'all';
  ctx.loadArticles();
  requests[5].resolve({ articles: [{ title: '文章结果' }], total: 1, page: 1, page_size: 10 });
  await tick();
  requests[4].resolve({ notes: [{ title: '旧笔记' }] });
  await tick();
  assert.equal(grid.innerHTML, '文章结果');
  ctx._domainsEditorCache = [
    {
      id: 1,
      domain: '行政法',
      children: [
        { id: 10, name: '行政处罚' },
        { id: 11, name: '行政诉讼' }
      ]
    }
  ];
  ctx.state.domain = '行政法';
  ctx.state.subcategoryId = 10;
  assert.equal(ctx.getCurrentViewPayload().subcategoryId, 10);
  ctx.savedViews = [{ id: 'saved', domain: '行政法', subcategoryId: 11 }];
  ctx.restoreSavedView('saved');
  assert.equal(ctx.state.subcategoryId, 11);
  ctx.savedViews = [{ id: 'legacy', domain: '行政法' }];
  ctx.restoreSavedView('legacy');
  assert.equal(ctx.state.subcategoryId, null);
  ctx.savedViews = [{ id: 'deleted', domain: '行政法', subcategoryId: 99 }];
  ctx.restoreSavedView('deleted');
  assert.equal(ctx.state.domain, '行政法');
  assert.equal(ctx.state.subcategoryId, null);
  ctx.articleOfflineSnapshot = { version: 2, articles: [] };
  assert.throws(() => ctx.offlineArticleList('/api/articles?subcategory_id=10'), /暂不可离线/);
  ctx.articleOfflineSnapshot = { version: 3, articles: [{ id: 1 }] };
  assert.throws(() => ctx.offlineArticleList('/api/articles?subcategory_id=10'), /暂不可离线/);
  ctx.articleOfflineSnapshot = null;
  const params = new URLSearchParams({ domain: '行政法', subcategory_id: '10' });
  assert(!ctx.articleMatchesOffline({ domains: ['行政法'], subcategory_ids: [11] }, params));
  assert(ctx.articleMatchesOffline({ domains: ['行政法'], subcategory_ids: [10] }, params));
  assert(
    !ctx.articleMatchesOffline(
      { classification_status: 'classified' },
      new URLSearchParams({ classification_status: 'needs_review' })
    )
  );
  ctx._tagCategoriesCache = [
    {
      id: 2,
      name: '测试库',
      tags: [
        { id: 20, name: '甲' },
        { id: 21, name: '乙' }
      ]
    }
  ];
  ctx.apiFetch = async () => {
    throw new Error('保存失败');
  };
  await ctx.reorderDirectory('tag', 2, 0, 1);
  assert.equal(ctx._tagCategoriesCache[0].tags[0].id, 20);
  ctx.applyDirectoryMutation('delete', 'child', { id: 10, name: '行政处罚' }, 1, '');
  assert.equal(ctx._domainsEditorCache[0].children.length, 1);
  assert(!JSON.parse(store.get('domains'))[0].children.some((x) => x.id === 10));
  // A subsequent offline fallback reads the new cache, so the deleted node stays gone.
  ctx.readNavDirectoryCache = (key) => JSON.parse(store.get(key) || '[]');
  vm.runInContext(
    app.slice(app.indexOf('async function loadDomains('), app.indexOf('let _domainPendingCount')),
    ctx
  );
  await ctx.loadDomains();
  assert.equal(ctx._domainsEditorCache[0].children[0].id, 11);
  vm.runInContext(
    "directoryState.expanded.add('domain');directoryState.query='命中';toggleDirectoryPath('domain');directoryState.query='';",
    ctx
  );
  assert(vm.runInContext("directoryState.expanded.has('domain')", ctx));
  const getter = ctx.localStorage.getItem;
  ctx.localStorage.getItem = () => {
    throw new Error('storage unavailable');
  };
  assert.equal(Object.keys(ctx.readJsonStore('unavailable', {})).length, 0);
  ctx.localStorage.getItem = getter;
  store.set('legal_kb_cat_collapsed', '{corrupt');
  vm.runInContext(
    app.slice(
      app.indexOf('let _catCollapsed ='),
      app.indexOf('// 当前弹窗操作上下文', app.indexOf('let _catCollapsed ='))
    ),
    ctx
  );
  assert.equal(vm.runInContext('Object.keys(_catCollapsed).length', ctx), 0);
  console.log(
    'directory regressions: reverse responses, stale errors, saved/legacy/deleted views, offline filters, sort failure, delete cache, corrupt storage passed'
  );
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
