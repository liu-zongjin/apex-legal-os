const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync('frontend/app.js', 'utf8');
let pendingCatalog, rendered = [], requests = [];
const root = {domain: '测试领域', count: 10, children: [{id: 7, count: 3}]};
const ctx = {
  console, URLSearchParams, articleOfflineMode: false,
  state: {domain: '测试领域', subcategoryId: 7, view: 'all', page: 1, pageSize: 50, fuzzy: true},
  _domainsEditorCache: [root], DOMAINS_OFFLINE_CACHE_KEY: 'domains',
  $: () => ({innerHTML: ''}), requestAnimationFrame: fn => fn(),
  generateArticleListPinScope: () => '', applyArticleOrder: x => x,
  renderArticles: articles => rendered.push(articles), renderPagination: () => {},
  renderDomains: () => {}, writeNavDirectoryCache: () => {},
  apiFetch: async url => { requests.push(url); return {articles: [{id: 1}], total: 1, page: 1, page_size: 50}; },
  loadDomains: () => new Promise(resolve => pendingCatalog = resolve)
};
vm.createContext(ctx);
vm.runInContext(source.slice(source.indexOf('let articleListRequestVersion ='), source.indexOf('\nfunction renderArticles')), ctx);
const tick = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  ctx.loadArticles(); await tick();
  assert.equal(new URLSearchParams(requests[0].split('?')[1]).get('subcategory_id'), '7');
  assert.equal(rendered[0].length, 1);
  pendingCatalog(); await tick();
  assert.equal(root.children[0].count, 1); // Classification changed after initial catalog load.
  assert.equal(root.count, 10); // Parent count represents the full parent scope.
  ctx.loadArticles(); await tick(); const obsolete = pendingCatalog;
  ctx.state.subcategoryId = null; ctx.loadArticles(); await tick();
  root.children[0].count = 9;
  obsolete(); await tick();
  assert.equal(root.children[0].count, 9); // Old scope refresh cannot overwrite new selection.
  pendingCatalog(); await tick();
  assert.equal(root.count, 1);
  ctx.state.q = '搜索'; ctx.loadArticles(); await tick();
  assert.equal(root.count, 1); // Search-result count never replaces the full category count.
  console.log('Domain list filters, count refresh, and stale-response checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
