/* Exercise real loaders/save logic with deliberately reordered anonymous responses. */
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const acorn = require('acorn');
function functions(file, names) {
  const source = fs.readFileSync(file, 'utf8');
  return acorn.parse(source, {ecmaVersion: 'latest'}).body
    .filter(n => n.type === 'FunctionDeclaration' && names.includes(n.id.name))
    .map(n => source.slice(n.start, n.end)).join('\n');
}
function deferred() {
  let resolve;
  const promise = new Promise(r => { resolve = r; });
  return {promise, resolve};
}
async function listRaces() {
  const requests = [], rendered = [];
  const context = vm.createContext({URLSearchParams, activeTab: 'cases',
    state: {items: {}, q: '', selectedCaseIds: new Set()},
    tabMeta: {cases: {endpoint: '/cases'}, todos: {endpoint: '/todos'}},
    api: url => { const task = deferred(); requests.push({url, ...task}); return task.promise; },
    sortCasesForList: rows => rows, applyLocalCasePins: rows => rows,
    groupSeriesReminderItems: rows => rows, loadCaseCollections: async () => {},
    renderTable: () => rendered.push(context.activeTab),
  });
  vm.runInContext('let caseListLoadSequence = 0;\n' + functions('frontend/case-manager.js', ['loadList']), context);
  const older = context.loadList();
  context.state.q = 'new';
  const newer = context.loadList();
  requests[1].resolve({items: [{id: 2}]}); await newer;
  requests[0].resolve({items: [{id: 1}]}); await older;
  assert.equal(context.state.items.cases[0].id, 2, 'Older searches must not overwrite newer results');
  const oldCases = context.loadList();
  context.activeTab = 'todos';
  const todos = context.loadList();
  requests[3].resolve({items: [{id: 4}]}); await todos;
  requests[2].resolve({items: [{id: 3}]}); await oldCases;
  assert.equal(context.state.items.todos[0].id, 4, 'A case response must never become a todo');
  const collections = deferred();
  context.activeTab = 'cases';
  context.loadCaseCollections = () => collections.promise;
  const cases = context.loadList();
  requests[4].resolve({items: [{id: 5}]});
  await Promise.resolve(); await Promise.resolve();
  context.activeTab = 'calendar';
  const count = rendered.length;
  collections.resolve(); await cases;
  assert.equal(rendered.length, count, 'Leaving during collection loading must not render the old list');
}
async function editorSave({typing = false, modal = false} = {}) {
  const originalTitle = '标题'.repeat(110);
  const title = {value: originalTitle};
  const reader = {innerHTML: 'old'};
  // The production detail container has class "modal", not "modal-content".
  const detail = {innerHTML: 'unrelated', closest: () => null};
  const editor = {innerText: '正文'};
  const requests = [];
  const article = {id: 1, title: originalTitle};
  const context = vm.createContext({
    _bodyEditorSaving: false, _bodyEditorRecordSession: null, _bodyEditorArticleId: 1,
    _bodyEditorLayoutPromise: Promise.resolve(), _bodyEditorImageUploads: new Set(),
    _bodyEditorEditRevision: 0, _bodyEditorMargins: {}, _bodyEditorServerContent: 'old',
    _bodyEditorInitialTitle: originalTitle, _bodyEditorInitialHtml: 'old',
    _bodyEditorReturnContext: {type: modal ? 'detail' : 'tab', tabId: 'article-1', articleId: 1},
    _bodyEditorSessions: new Map(), _bodyEditorContentHtml: () => '<p>正文</p>',
    _bodyEditorHasChanges: () => title.value !== context._bodyEditorInitialTitle,
    _finalizeBodyEditorMultiSelections() {}, sanitizeBodyHtml: html => html,
    state: {currentArticle: article, bodyCache: new Map()},
    tabState: {tabs: [{type: 'article', id: 'article-1', data: {articleId: 1, article}}]},
    TAB_TYPES: {ARTICLE: 'article'}, CSS: {escape: text => text}, currentArticleId: modal ? 1 : 2,
    $: id => ({'body-editor': editor, 'body-editor-document-title': title, 'detail-body': detail})[id],
    document: {querySelector: selector => selector.includes('.tab-article-body-text') ? reader : null},
    apiFetch: async (url, options) => {
      const body = JSON.parse(options.body); requests.push(body);
      if (requests.length > 1) assert.equal(body.base_title, originalTitle.slice(0, 200), 'Next save must use the acknowledged server title');
      if (typing) { title.value = '保存期间的新标题'; context._bodyEditorEditRevision++; }
      return {title: body.title.slice(0, 200), content: body.content};
    },
    localStorage: {removeItem() {}, setItem() {}}, _getBodyEditorDraftKey: () => 'draft',
    _updateBodyEditorSaveState() {}, showToast() {}, alert: message => { throw Error(message); },
    renderBodyContentWithToc: html => ({html, toc: []}), refreshModalSidebarToc() {},
    refreshTabSidebarToc() {}, enhancePdfPageGalleries() {}, setupTextSelection() {},
    loadNotes: async () => {}, setupTabTextSelection() {}, loadNotesForTab: async () => {},
    renderTabs() {}, saveTabsState() {},
  });
  vm.runInContext(functions('frontend/app.js', ['saveBody']), context);
  assert.equal(await context.saveBody({closeAfter: false}), true);
  if (modal) assert.equal(detail.innerHTML, '<p>正文</p>', 'The detail reader must refresh after saving');
  else {
    assert.equal(reader.innerHTML, '<p>正文</p>', 'The article tab must refresh even when the detail modal exists');
    assert.equal(detail.innerHTML, 'unrelated', 'An unrelated detail modal must remain intact');
  }
  assert.equal(article.title, originalTitle.slice(0, 200), 'Reader metadata must match persisted title');
  assert.equal(title.value, typing ? '保存期间的新标题' : originalTitle.slice(0, 200));
  assert.equal(context._bodyEditorDirty, typing);
  assert.equal(await context.saveBody({closeAfter: false}), true);
}
(async () => {
  const failures = [];
  for (const [name, run] of [['list races', listRaces], ['editor save', editorSave], ['detail save', () => editorSave({modal: true})], ['typing during save', () => editorSave({typing: true})]]) {
    try { await run(); console.log(name + ': passed'); }
    catch (error) { failures.push(name + ': ' + error.message); }
  }
  assert.deepEqual(failures, []);
})().catch(error => { console.error(error); process.exitCode = 1; });
