const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('frontend/app.js', 'utf8');
const nodes = {'domain-reclass-preview': {}, 'domain-reclass-apply': {}};
const requests = [];
const unchanged = {id: 1, has_changes: false, subcategories: [7], suggestions: [{name: '已有主题'}], needs_ai: true};
const changed = {id: 51, title: '<测试文章>', has_changes: true, add: [], remove: [], subcategory_add: ['新子分类'], subcategory_remove: ['旧子分类'], needs_ai: false};
const responses = [{items: [unchanged], next_after_id: 50}, {items: [changed], next_after_id: 100}, {items: [], next_after_id: null}];
const context = vm.createContext({
  $: id => nodes[id],
  apiFetch: async path => {requests.push(path); return responses.shift();},
  escapeHtml: text => String(text).replaceAll('<', '&lt;').replaceAll('>', '&gt;'),
  showToast: () => {throw new Error('Unexpected preview error');},
});
const start = source.indexOf('async function previewDomainReclassification(');
const end = source.indexOf('async function applyDomainReclassification()', start);
vm.runInContext('let domainReclassAfterId = 0; let domainReclassPreview = null; let domainReclassLoading = false;\n' + source.slice(start, end), context);
(async () => {
  await context.previewDomainReclassification();
  assert(nodes['domain-reclass-apply'].disabled);
  assert(nodes['domain-reclass-preview'].innerHTML.includes('0 篇分类有变化'));
  assert(!nodes['domain-reclass-preview'].innerHTML.includes('已有主题'));
  await context.previewDomainReclassification(true);
  assert(requests[1].includes('after_id=50'));
  assert(!nodes['domain-reclass-apply'].disabled);
  assert(nodes['domain-reclass-preview'].innerHTML.includes('新增子分类：新子分类'));
  assert(nodes['domain-reclass-preview'].innerHTML.includes('移除子分类：旧子分类'));
  assert(nodes['domain-reclass-preview'].innerHTML.includes('&lt;测试文章&gt;'));
  await context.previewDomainReclassification(true);
  assert(requests[2].includes('after_id=100'));
  assert(nodes['domain-reclass-apply'].disabled);
  assert(nodes['domain-reclass-preview'].innerHTML.includes('没有更多文章'));
  console.log('Reclassification UI: unchanged, differences, pagination and escaping passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
