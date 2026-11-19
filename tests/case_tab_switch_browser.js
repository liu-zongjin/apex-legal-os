const assert = require('node:assert/strict');
const fs = require('node:fs');
const acorn = require('acorn');
const { chromium, webkit } = require(process.env.STELLA_PLAYWRIGHT_MODULE || 'playwright');

const source = fs.readFileSync('frontend/case-manager.js', 'utf8');
const functions = new Set([
  'switchTab', 'afterCaseTabPaint', 'syncActiveTabNav', 'closeMobileTabs',
  'updateMobileTabLabel', 'render', 'loadList',
]);
const behavior = acorn.parse(source, { ecmaVersion: 'latest' }).body
  .filter(node => node.type === 'FunctionDeclaration' && functions.has(node.id.name))
  .map(node => source.slice(node.start, node.end))
  .join('\n');
const html = fs.readFileSync('frontend/case-manager.html', 'utf8');
const nav = html.match(/<nav class="tabs" id="tabs">[\s\S]*?<\/nav>/)[0];
const css = fs.readFileSync('frontend/case-manager.css', 'utf8');

async function check(engine) {
  const browser = await engine.launch(engine === chromium && process.env.STELLA_CASE_TAB_CHROME
    ? { executablePath: process.env.STELLA_CASE_TAB_CHROME } : {});
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await page.setContent(`
      <style>${css}</style>
      <header class="topbar">
        <button id="mobileTabToggle" aria-expanded="true"><span id="mobileTabLabel"></span></button>
        ${nav}
      </header>
      <main id="content"></main>
    `);
    await page.addScriptTag({ content: `
      const $ = id => document.getElementById(id);
      const tabMeta = Object.fromEntries(['cases', 'todos', 'hearings', 'preservations', 'appeals']
        .map(tab => [tab, {endpoint: tab}]));
      const state = {
        items: {cases: [{id: 1}], todos: [{id: 2}], hearings: [{id: 3}]},
        selectedCaseIds: new Set(),
      };
      let activeTab = 'cases', caseDetailLoadSequence = 0, caseListLoadSequence = 0;
      const renders = [], pending = [], notices = [];
      let filters = 0, immediate = false;
      function rememberActiveTab() {}
      function renderMobileFilters() { filters += 1; }
      function updateTopAdd() {}
      function notifyCaseManagerContext() {}
      function currentCaseManagerPageLabel() { return activeTab; }
      function listHeroHtml(tab) { return '<h2>' + tab + '</h2>'; }
      function renderTable() {
        renders.push([activeTab, state.items[activeTab].map(item => item.id)]);
        document.querySelector('.table-wrap').textContent = state.items[activeTab].map(item => item.id).join(',');
      }
      function api(url) {
        if (immediate) return Promise.resolve({items: [{id: 99}]});
        return new Promise((resolve, reject) => pending.push({url, resolve, reject}));
      }
      function sortCasesForList(items) { return items; }
      function applyLocalCasePins(items) { return items; }
      async function loadCaseCollections() {}
      function groupSeriesReminderItems(items) { return items; }
      function toast(message) { notices.push(message); }
      ${behavior}
    ` });
    for (const width of [1440, 1024, 901, 900, 390]) {
      await page.setViewportSize({ width, height: 900 });
      for (const dark of [false, true]) {
        const result = await page.evaluate(({ width, dark }) => {
          document.body.classList.toggle('dark-mode', dark);
          $('tabs').classList.toggle('mobile-open', width <= 900);
          document.querySelector('[data-tab="todos"]').click();
          const active = $('tabs').querySelector('.tab.active');
          const trackStyle = getComputedStyle($('tabs'));
          const itemStyle = getComputedStyle(active);
          return {
            current: active.dataset.tab,
            announced: active.getAttribute('aria-current'),
            activeCount: $('tabs').querySelectorAll('[aria-current="true"]').length,
            overlay: getComputedStyle($('tabs'), '::after').content,
            trackRadius: parseFloat(trackStyle.borderTopLeftRadius),
            itemRadius: parseFloat(itemStyle.borderTopLeftRadius),
            status: document.querySelector('#content [role="status"]')?.textContent,
            filters,
          };
        }, { width, dark });
        assert.equal(result.current, 'todos');
        assert.equal(result.announced, 'true');
        assert.equal(result.activeCount, 1);
        assert.equal(result.overlay, 'none');
        assert.equal(result.status, '加载中...');
        assert.equal(result.filters, 1);
        if (width > 900) {
          assert(result.trackRadius >= 50 && result.itemRadius >= 50, JSON.stringify(result));
        }
        await page.evaluate(() => pending.shift().resolve({ items: [{ id: 20 }] }));
        await page.waitForFunction(() => renders.length === 1);
        assert.deepEqual(await page.evaluate(() => renders.splice(0)), [['todos', [20]]]);
        await page.evaluate(() => { filters = 0; });
      }
    }

    const beforePaint = await page.evaluate(async () => {
      immediate = true;
      switchTab('hearings');
      await new Promise(resolve => requestAnimationFrame(() => resolve(renders.length)));
      return {
        selected: $('tabs').querySelector('[aria-current="true"]').dataset.tab,
        rendered: renders.length,
      };
    });
    assert.deepEqual(beforePaint, { selected: 'hearings', rendered: 0 });
    await page.waitForFunction(() => renders.length === 1);
    assert.deepEqual(await page.evaluate(() => renders.splice(0)), [['hearings', [99]]]);

    await page.evaluate(() => {
      immediate = false;
      switchTab('todos');
      switchTab('cases');
      pending.shift().resolve({ items: [{ id: 200 }] });
      pending.shift().reject(new Error('示例请求失败'));
    });
    await page.waitForFunction(() => notices.length === 1);
    assert.deepEqual(await page.evaluate(() => renders), [['cases', [1]]]);
    assert.deepEqual(await page.evaluate(() => notices), ['示例请求失败']);
  } finally {
    await browser.close();
  }
}

(async () => {
  for (const engine of [chromium, webkit]) await check(engine);
  console.log('Case tab pills, first-paint feedback, single list rendering and stale-request checks passed');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
