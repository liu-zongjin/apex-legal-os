const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(process.argv[2] || 'frontend/case-manager.js', 'utf8');
const spans = [
  ['async function openDetail(', '\nfunction openCaseDetailDrawer('],
  ['function openNewCaseDetail(', '\nfunction resetCaseResearchWorkspace('],
  ['async function editCaseSection(', '\nfunction readInlineParties('],
  ['async function saveCaseSection(', '\n// 所有案件详情视图'],
  ['function closeEditor(', '\nfunction clearContractWorkspaceChrome('],
  ['async function saveEditor(', '\nasync function deleteItem('],
];
const code = spans.map(([start, end]) => {
  const a = source.indexOf(start), b = source.indexOf(end, a);
  assert(a >= 0 && b > a, `Missing function span: ${start}`);
  return source.slice(a, b);
}).join('\n');
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}
function setup(tab = 'todos') {
  const requests = [], opened = [], messages = [], nodes = new Map();
  const noop = () => {};
  const state = {editing: {tab, item: {id: 1, title: '匿名案件'}, mode: 'detail'}, items: {cases: []}};
  const context = vm.createContext({
    state, console, URLSearchParams, activeTab: tab, tabMeta: {todos: {endpoint: '/api/case-manager/todos'}},
    api: (url, options) => { const call = {url, options, ...deferred()}; requests.push(call); return call.promise; },
    $: id => {
      if (!nodes.has(id)) nodes.set(id, {innerHTML: '', classList: {add: noop, remove: noop, toggle: noop}});
      return nodes.get(id);
    },
    clearContractWorkspaceChrome: noop, setSeriesChildDetailOverlay: noop,
    offlineCaseById: () => null, isOfflineReadonly: () => false,
    openCaseDetailDrawer: item => opened.push(item),
    ApexCasePicker: {closeAll: noop}, closeSeriesSide: noop, closeOptionManager: noop,
    resetCaseResearchWorkspace: noop, renderCaseResearchFloatHost: noop,
    forgetOpenCaseDetail: noop, rememberOpenCaseDetail: noop, renderOpenCaseDetail: noop,
    notifyCaseManagerContext: noop, currentCaseManagerPageLabel: () => '案件管理',
    toast: text => messages.push(text),
    collectForm: () => ({todo_title: '匿名待办', remind_at: '2026-11-20T09:00'}),
    refreshAll: async () => {}, requireOnlineAction: () => true,
    updatedCaseFromSection: () => ({...state.editing.item, memo: '修改内容'}),
    caseSavePayload: item => item, caseDetailSaveUrl: id => `/api/case-manager/cases/${id}`,
    readMasterClients: () => [{id: 1, name: '匿名客户'}],
    loadCaseAutomationPanel: noop, hasCaseClient: () => true,
    prepareCaseSection: async () => {}, bindIntakeFolder: async () => {},
    scheduleCaseOfflineSnapshot: noop,
  });
  vm.runInContext(`let caseDetailLoadSequence = 0;\n${code}`, context);
  return {context, state, requests, opened, messages};
}

const tests = {
  async 'only the latest requested case can open'() {
    const fx = setup('cases');
    const first = fx.context.openDetail('cases', 1);
    const second = fx.context.openDetail('cases', 2);
    fx.requests[1].resolve({id: 2}); await second;
    fx.requests[0].resolve({id: 1}); await first;
    assert.deepEqual(fx.opened.map(x => x.id), [2]);
  },
  async 'closing or creating cancels an older detail response'() {
    for (const action of ['closeEditor', 'openNewCaseDetail']) {
      const fx = setup('cases');
      const pending = fx.context.openDetail('cases', 1);
      fx.context[action]();
      const editor = fx.state.editing;
      fx.requests[0].resolve({id: 1}); await pending;
      assert.deepEqual(fx.opened, []);
      assert.equal(fx.state.editing, editor);
    }
  },
  async 'reminder save submits once while pending'() {
    const fx = setup();
    const first = fx.context.saveEditor();
    const second = fx.context.saveEditor();
    assert.equal(fx.requests.length, 1);
    fx.requests[0].resolve({id: 1}); await Promise.all([first, second]);
  },
  async 'reminder completion leaves a newer editor open'() {
    const fx = setup();
    const pending = fx.context.saveEditor();
    const newer = fx.state.editing = {tab: 'todos', item: {id: 2, title: '另一事项'}};
    fx.requests[0].resolve({id: 1}); await pending;
    assert.equal(fx.state.editing, newer);
  },
  async 'failed saves retain input and allow retry'() {
    const fx = setup();
    const editor = fx.state.editing;
    const first = fx.context.saveEditor();
    fx.requests[0].reject(new Error('模拟保存失败')); await first;
    assert.equal(fx.state.editing, editor);
    assert.equal(Boolean(editor.saving), false);
    assert(fx.messages.includes('模拟保存失败'));
    const retry = fx.context.saveEditor();
    assert.equal(fx.requests.length, 2);
    fx.requests[1].resolve({id: 1}); await retry;
  },
  async 'case section submits once and preserves a newer case'() {
    const fx = setup('cases');
    const pending = fx.context.saveCaseSection('contacts');
    const duplicate = fx.context.saveCaseSection('contacts');
    assert.equal(fx.requests.length, 1);
    const newer = fx.state.editing = {tab: 'cases', item: {id: 2, title: '另一案件'}};
    fx.requests[0].resolve({id: 1, title: '已保存案件'}); await Promise.all([pending, duplicate]);
    assert.equal(fx.state.editing, newer);
    assert.equal(newer.item.id, 2);
  },
  async 'client save finishes for the original case without changing a new editor'() {
    const fx = setup('cases');
    const pending = fx.context.saveCaseSection('clients');
    const newer = fx.state.editing = {tab: 'cases', item: {id: 2, title: '另一案件'}};
    fx.context.api = async (url, options) => { fx.requests.push({url, options}); return {id: 1}; };
    fx.requests[0].resolve({id: 1, name: '匿名客户'}); await pending;
    assert.equal(fx.requests.length, 2);
    assert.equal(fx.requests[1].url, '/api/case-manager/cases/1');
    assert.equal(fx.state.editing, newer);
    assert.equal(newer.item.id, 2);
  },
  async 'a new case retains its chosen folder after switching editors'() {
    const fx = setup('cases'), bindings = [];
    fx.state.editing = {tab: 'cases', item: {title: '匿名新案件'}, isNew: true, intake: {folderPath: '/anonymous/original'}};
    fx.context.bindIntakeFolder = async (id, path) => bindings.push({id, path});
    const pending = fx.context.saveCaseSection('basic');
    const newer = fx.state.editing = {tab: 'cases', item: {id: 2}, intake: {folderPath: '/anonymous/other'}};
    fx.requests[0].resolve({id: 3}); await pending;
    assert.deepEqual(bindings, [{id: 3, path: '/anonymous/original'}]);
    assert.equal(fx.state.editing, newer);
  },
  async 'delayed section loading cannot change a new case or canceled section'() {
    for (const action of ['replace', 'cancel']) {
      const fx = setup('cases'), preparation = deferred();
      fx.context.prepareCaseSection = () => preparation.promise;
      const pending = fx.context.editCaseSection('contacts');
      if (action === 'replace') fx.state.editing = {tab: 'cases', item: {id: 2}};
      else fx.context.cancelCaseSectionEdit();
      const editor = fx.state.editing;
      preparation.resolve(); await pending;
      assert(!editor.inlineSection);
    }
  },
};

(async () => {
  let failed = 0;
  for (const [name, test] of Object.entries(tests)) {
    try { await test(); console.log(`PASS ${name}`); }
    catch (error) { failed++; console.error(`FAIL ${name}: ${error.message}`); }
  }
  if (failed) process.exitCode = 1;
})().catch(error => { console.error(error); process.exitCode = 1; });
