const assert = require('assert/strict');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('frontend/case-manager.js', 'utf8');
const content = {innerHTML: ''};
const ctx = vm.createContext({
  URLSearchParams, console, document: {activeElement: null},
  state: {courtOnline: {kind:'', page:1, pageSize:50, q:'', items:[], total:0}},
  activeTab:'courtOnline', $: id => id === 'content' ? content : null,
  esc: value => String(value || ''),
  courtUpdateStatusButton() {}, courtObserveSync() {},
  courtCaseAjlbTabHtml: () => '', courtLayyAjlbTabHtml: () => '',
  courtSyncBannerHtml: () => '', bindCourtKindHoverMenus() {}, courtUpdateSyncBanner() {},
});
vm.runInContext(source.slice(source.indexOf('const CO_API ='), source.indexOf('let courtCaseDetailId =')), ctx);
vm.runInContext(source.slice(source.indexOf('function renderCourtOnline()'), source.indexOf('function courtSelectKind(')), ctx);
vm.runInContext(source.slice(source.indexOf('function renderCourtReadings('), source.indexOf('function courtReadingFilter(')), ctx);
const requests = [];
const status = {record_count:98, todo_count:17, message_count:41, delivery_count:40};
ctx.api = async url => {
  requests.push(url);
  if (url.endsWith('/status')) return status;
  if (url.includes('/readings?')) {
    const params = new URL(url, 'https://fixture.test').searchParams;
    return {items:[], total:params.has('q') || params.has('status') ? 2 : 9};
  }
  return {items:[], total:98, kind_counts:{total:98, todo:17}};
};
function badge(expected) {
  assert.match(content.innerHTML, new RegExp('data-kind="readings"[^>]*>在线阅卷<span class="tab-count">' + expected + '</span>'));
}
(async () => {
  await ctx.loadCourtOnline();
  badge(9);
  assert.equal(ctx.state.courtOnline.kind, '', 'Initial count needs no tab click');
  assert(requests.some(url => url.endsWith('/readings?page_size=1')));
  ctx.state.courtOnline.kind = 'readings';
  requests.length = 0;
  await ctx.loadCourtOnline();
  badge(9);
  assert.equal(requests.filter(url => url.includes('/readings?')).length, 1, 'Reuse unfiltered reading list');
  ctx.state.courtOnline.q = '匿名法院';
  ctx.state.courtOnline.readingStatus = '11800006-3';
  await ctx.loadCourtOnline();
  badge(9);
  assert.equal(ctx.state.courtOnline.total, 2, 'Filtered list retains its own total');
  assert.match(content.innerHTML, /共 2 条/);
  ctx.state.courtOnline.kind = '';
  const normalApi = ctx.api;
  ctx.api = url => url.includes('/readings?') ? Promise.reject(new Error('unavailable')) : normalApi(url);
  await ctx.loadCourtOnline();
  badge(9);
  assert.equal(ctx.state.courtOnline.total, 98, 'Count failure does not break ordinary records');
  // An older response must not overwrite a newer navigation or account load.
  let resolveOld;
  ctx.api = url => url.includes('/readings?') ? new Promise(resolve => {resolveOld=resolve;}) : normalApi(url);
  const oldLoad = ctx.loadCourtOnline();
  ctx.api = async url => url.includes('/readings?') ? {total:4, items:[]} : normalApi(url);
  await ctx.loadCourtOnline();
  resolveOld({total:99, items:[]});
  await oldLoad;
  badge(4);
  console.log('Court reading counts: initial entry, filtering, request reuse, failures and stale responses passed');
})().catch(error => {console.error(error); process.exitCode=1;});
