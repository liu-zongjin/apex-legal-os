/* Anonymous browser regressions; never connects to the live service. */
const fs = require('fs'), path = require('path'), assert = require('node:assert/strict'), acorn = require('acorn');
const { chromium, webkit } = require(process.env.STELLA_PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'frontend/case-manager.js'), 'utf8');
const names = new Set(['seriesNumberRowHtml', 'seriesNumberEditorHtml', 'collectSeriesNumberEditor',
  'openSeriesChildEditor', 'openSeriesChildDetail', 'saveSeriesChild', 'addSeriesInlineRow',
  'persistSeriesColumns', 'persistSeriesPublicUpdate', 'showSeriesSide', 'closeSeriesSide',
  'beginSeriesSideRequest', 'isCurrentSeriesSideRequest', 'runSeriesBatch']);
const code = acorn.parse(source, { ecmaVersion: 'latest' }).body
  .filter(n => n.type === 'FunctionDeclaration' && names.has(n.id.name))
  .map(n => source.slice(n.start, n.end)).join('\n');
(async () => {
  for (const engine of [chromium, webkit]) {
    const browser = await engine.launch(engine === chromium
      ? { headless: true, executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' }
      : { headless: true, ...(process.env.STELLA_WEBKIT_EXECUTABLE ? { executablePath: process.env.STELLA_WEBKIT_EXECUTABLE } : {}) });
    try {
      const page = await browser.newPage(), errors = [], failures = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.setContent('<div id="seriesSide"><div id="seriesSideTitle"></div><div id="seriesSideSubtitle"></div><div id="seriesSideBody"></div><div id="seriesSideFoot"></div></div><div id="numbers"></div><select id="seriesBatchOperation"><option value="archive">archive</option></select>');
      await page.addScriptTag({ content: `
        const $=id=>document.getElementById(id), state={}; let seriesEditorRowSeed=0;
        const workspace=id=>({id,case_type:'示例案由',children:[],stats:{total:0,active:0},profile:{}});
        let calls=[],reloads=[],drawers=[],pending=[],deferred=false;
        function reset(){Object.keys(state).forEach(k=>delete state[k]);state.seriesWorkspace=workspace(1);state.seriesSelectedChildIds=new Set([101]);calls=[];reloads=[];drawers=[];pending=[];deferred=false;}
        async function api(url,opts={}){calls.push({url,opts});if(deferred)return new Promise(resolve=>pending.push(resolve));return {};}
        function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
        function toast(){} function activateSeriesLookups(){} function requireOnlineAction(){return true}
        function isOfflineReadonly(){return false}function applySeriesDetailMappings(item){return item}function decorateSeriesWorkspaceChildren(item){return item}
        function seriesEditorTableFieldsHtml(){return ''}function seriesEditorColumnLabel(k,v){return v}function seriesEditorGroupLabel(k,v){return v}
        function seriesLookupInput(id,value,kind){return '<input id="'+id+'" data-series-lookup="'+kind+'" value="'+esc(value)+'">'}
        function seriesModeField(){return ''}function seriesPartyEditorHtml(){return ''}function childClaimEditorHtml(){return ''}function childMilestoneEditorHtml(){return ''}
        function collectChildForm(){return {display_name:'匿名子案'}} function currentSeriesSettings(){return {}}
        function renderSeriesWorkspace(){} function currentSeriesColumns(){return []} function scheduleCaseOfflineSnapshot(){}
        async function reloadSeriesWorkspace(){reloads.push(state.seriesWorkspace.id)} async function refreshAll(){}
        function openCaseDetailDrawer(item,id){drawers.push({item,id})}function confirm(){return true}
        ${code}
        reset();
      ` });
      const check = async (name, action) => { try { await page.evaluate(() => reset()); await action(); } catch (e) { failures.push(name + ': ' + e.message); } };
      await check('case-number dates survive editing and reordering', async () => {
        const result = await page.evaluate(() => {
          const dates = { first_filing_at: '2026-01-02', first_judgment_served_at: '2026-03-04', second_filing_at: '2026-05-06', second_judgment_effective_at: '2026-07-08' };
          $('numbers').innerHTML = seriesNumberEditorHtml([{ ...dates, case_no: '示例案号甲', court: '示例机构甲', handler_contact: '匿名经办人' }, { case_no: '示例案号乙', first_filing_at: '2026-09-01' }], 'numberList');
          const rows = $('numberList').querySelectorAll('[data-series-number-row]');
          rows[0].querySelector('[data-number-case-no]').value = '修改后的案号甲';
          $('numberList').prepend(rows[1]);
          return { dates, values: collectSeriesNumberEditor('numberList') };
        });
        assert.equal(result.values[0].first_filing_at, '2026-09-01');
        for (const [key, value] of Object.entries(result.dates)) assert.equal(result.values[1][key], value);
        assert.equal(result.values[1].case_no, '修改后的案号甲');
        assert.equal(result.values[1].handler_contact, '匿名经办人');
      });
      await check('late editor result cannot overwrite a newer child', async () => {
        const name = await page.evaluate(async () => {
          deferred = true; const a = openSeriesChildEditor(11), b = openSeriesChildEditor(12);
          pending[1]({ display_name: '子案乙' }); await b;
          pending[0]({ display_name: '子案甲' }); await a;
          return $('childFormName').value;
        });
        assert.equal(name, '子案乙');
      });
      await check('cancel invalidates loading editor', async () => {
        assert.equal(await page.evaluate(async () => {
          deferred = true; const load = openSeriesChildEditor(11); closeSeriesSide();
          pending[0]({ display_name: '已取消的子案' }); await load;
          return $('seriesSide').classList.contains('show');
        }), false);
      });
      await check('late detail cannot open in another series', async () => {
        const count = await page.evaluate(async () => {
          deferred = true; const load = openSeriesChildDetail(11);
          state.seriesWorkspace = workspace(2); pending[0]({ id: 11 }); await load; return drawers.length;
        });
        assert.equal(count, 0);
      });
      await check('repeated save creates one child and leaves a newer panel intact', async () => {
        const result = await page.evaluate(async () => {
          await openSeriesChildEditor(); deferred = true;
          const a = saveSeriesChild(0), b = saveSeriesChild(0);
          const count = calls.length;
          state.seriesWorkspace = workspace(2); showSeriesSide('新面板', '', '新内容');
          pending.forEach(resolve => resolve({ id: 101 })); await Promise.all([a, b]);
          return { count, title: $('seriesSideTitle').textContent, shown: $('seriesSide').classList.contains('show'), reloads };
        });
        assert.equal(result.count, 1); assert.equal(result.title, '新面板'); assert(result.shown); assert.deepEqual(result.reloads, []);
      });
      await check('ordinary child save still closes and refreshes its original series', async () => {
        const result = await page.evaluate(async () => {
          deferred = true; const load = openSeriesChildEditor(11); pending[0]({ display_name: '示例子案' }); await load;
          deferred = false; calls = []; await saveSeriesChild(11);
          return { calls, reloads, shown: $('seriesSide').classList.contains('show') };
        });
        assert.equal(result.calls[0].url, '/api/case-manager/series/1/children/11');
        assert.equal(result.calls[0].opts.method, 'PUT'); assert.deepEqual(result.reloads, [1]); assert.equal(result.shown, false);
      });
      await check('late inline add does not append to another series', async () => {
        const count = await page.evaluate(async () => {
          deferred = true; const add = addSeriesInlineRow(); state.seriesWorkspace = workspace(2);
          pending[0]({ id: 101 }); await add; return state.seriesWorkspace.children.length;
        });
        assert.equal(count, 0);
      });
      await check('late column save does not alter another table', async () => {
        const result = await page.evaluate(async () => {
          deferred = true; const save = persistSeriesColumns([{ key: 'memo' }]); state.seriesWorkspace = workspace(2);
          pending[0]({ items: [{ key: 'memo' }] }); const accepted = await save;
          return { accepted, columns: state.seriesWorkspace.profile.table_columns || [] };
        });
        assert.equal(result.accepted, false); assert.deepEqual(result.columns, []);
      });
      await check('late common-field save does not replace another series', async () => {
        const id = await page.evaluate(async () => {
          deferred = true; const save = persistSeriesPublicUpdate({ title: '旧系列' }, '已保存');
          state.seriesWorkspace = workspace(2); pending[0](workspace(1)); await save; return state.seriesWorkspace.id;
        });
        assert.equal(id, 2);
      });
      await check('current column and common-field saves still render their results', async () => {
        const result = await page.evaluate(async () => {
          deferred = true; const columns = persistSeriesColumns([{ key: 'memo' }]); pending[0]({ items: [{ key: 'memo' }] });
          const accepted = await columns, savedColumns = state.seriesWorkspace.profile.table_columns;
          const common = persistSeriesPublicUpdate({ title: '更新的公共信息' }, '已保存'); pending[1]({ ...workspace(1), title: '更新的公共信息' });
          await common; return { accepted, savedColumns, title: state.seriesWorkspace.title };
        });
        assert(result.accepted); assert.deepEqual(result.savedColumns, [{ key: 'memo' }]); assert.equal(result.title, '更新的公共信息');
      });
      await check('batch archive uses one atomic series request', async () => {
        const urls = await page.evaluate(async () => { showSeriesSide('批量操作', '', ''); await runSeriesBatch(); return calls.map(call => call.url); });
        assert.deepEqual(urls, ['/api/case-manager/series/1/children/bulk']);
      });
      assert.deepEqual(errors, []);
      assert.deepEqual(failures, []);
      console.log(engine.name() + ': dates, stale child/editor/columns/common saves, cancel, duplicate save and atomic batch passed');
    } finally { await browser.close(); }
  }
})().catch(error => { console.error(error); process.exit(1); });
