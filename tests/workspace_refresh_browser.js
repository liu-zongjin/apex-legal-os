const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium, webkit } = require(process.env.STELLA_PLAYWRIGHT_MODULE || 'playwright');

const root = path.resolve(__dirname, '..', 'frontend');
const origin = 'http://workspace-refresh.test';
const caseContext = { type: 'case_database' };
const makeConversation = (history_key, askContext) => ({
  history_key,
  version: 1,
  records: [{ id: history_key, role: 'user', content: '匿名测试问题', askContext, ts: Date.now() }],
});
const history = [
  makeConversation('ask_history_global__chat_fixture', null),
  makeConversation('ask_history_case_database__chat_fixture', caseContext),
];

async function serve(route) {
  const url = new URL(route.request().url());
  const name = url.pathname;
  if (name.startsWith('/api/')) {
    let json = { items: [], total: 0 };
    if (name === '/api/ai-ask/history') json = { conversations: history };
    if (name === '/api/ai-ask-models') json = { groups: [], default_model: '' };
    if (name === '/api/articles') json.articles = [];
    if (name === '/api/case-manager/cases' && url.searchParams.get('case_id') === '901') {
      json = { id: 901, title: '匿名示例案件', case_kind: 'ordinary', source_status: 'active' };
    }
    if (name === '/api/server-status') json = { status: 'running' };
    if (name.endsWith('/session-status')) json = { server_reachable: true, authenticated: true };
    return route.fulfill({ json });
  }
  const relative = name === '/' ? 'index.html' : name === '/case-manager' ? 'case-manager.html' :
    name.startsWith('/static/') ? name.slice('/static/'.length) : '';
  const file = path.resolve(root, relative);
  if (!relative || !file.startsWith(root + path.sep) || !fs.existsSync(file)) return route.fulfill({ status: 404 });
  return route.fulfill({ path: file });
}

async function checkWorkspace(page, type, id, collapsed = true) {
  await page.waitForFunction(({ type, id }) => typeof appStartupComplete !== 'undefined' && appStartupComplete &&
    tabState.tabs.some(tab => tab.id === id && tab.type === type) &&
    tabState.activeTabId === id && document.getElementById(id)?.classList.contains('active'), { type, id });
  assert.equal(await page.locator('body').evaluate(el => el.classList.contains('sidebar-collapsed')), collapsed);
  assert.equal(await page.locator('#sidebar').evaluate(el => el.classList.contains('collapsed')), collapsed);
}

async function checkAiPosition(page, type, id, key) {
  await checkWorkspace(page, type, id);
  await page.waitForFunction(key => getAskHistoryKey(askContext) === key
    && document.querySelector('#ask-chat-area')?.textContent.includes('匿名测试问题'), key);
  assert.equal(await page.locator('#ask-history-btn').getAttribute('aria-expanded'), 'false');
  assert.equal(await page.locator('#ask-history-tab-cases').getAttribute('aria-selected'), 'true');
}

(async () => {
  const browsers = [
    ['Chromium', chromium, { channel: process.env.STELLA_UI_BROWSER || 'chrome' }],
    ['WebKit', webkit, {}],
  ];
  for (const [name, engine, options] of browsers) {
    const browser = await engine.launch(options);
    try {
      const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, serviceWorkers: 'block', reducedMotion: 'reduce' });
      await context.route(origin + '/**', serve);
      const page = await context.newPage();
      await page.goto(origin + '/?native-shell=1');
      await page.waitForFunction(() => typeof appStartupComplete !== 'undefined' && appStartupComplete);

      await page.evaluate(() => openCaseManagerTab());
      const caseId = await page.evaluate(() => tabState.activeTabId);
      const frame = page.frameLocator('iframe[src^="/case-manager"]');
      await frame.locator('[data-tab="todos"]').first().click();
      await page.waitForFunction(() => tabState.tabs.find(t => t.id === tabState.activeTabId)?.data?.pageLabel === '待办事项');
      await page.reload();
      await checkWorkspace(page, 'case_manager', caseId);
      await frame.locator('[data-tab="todos"].active').first().waitFor();

      // A different window writing the persistent fallback must not switch
      // this window's page on reload.
      const other = await context.newPage();
      await other.goto(origin + '/');
      await other.waitForFunction(() => typeof appStartupComplete !== 'undefined' && appStartupComplete);
      await other.evaluate(() => goToMainView());
      await other.close();
      await page.goto(origin + '/?native-shell=1&reload=100');
      await checkWorkspace(page, 'case_manager', caseId);
      await frame.locator('[data-tab="todos"].active').first().waitFor();

      const casePage = page.frames().find(item => new URL(item.url()).pathname === '/case-manager');
      await casePage.evaluate(async () => {
        switchTab('cases');
        await openDetail('cases', 901);
      });
      await frame.locator('#drawer').getByText('匿名示例案件', { exact: true }).first().waitFor();
      await page.reload();
      await checkWorkspace(page, 'case_manager', caseId);
      await frame.locator('#drawer').getByText('匿名示例案件', { exact: true }).first().waitFor();

      for (const [type, key] of [
        ['ai_ask', 'ask_history_global__chat_fixture'],
        ['case_ai', 'ask_history_case_database__chat_fixture'],
      ]) {
        await page.evaluate(type => {
          if (type === 'case_ai') openCaseAiPanel();
          else { askContext = null; openAskPanel(); }
        }, type);
        await page.waitForFunction(key => askHistoryCache.has(key), key);
        await page.locator('#ask-history-list .ask-history-entry').filter({ hasText: '匿名测试问题' }).click();
        await page.evaluate(() => { selectAskHistoryTab('cases'); toggleAskHistorySidebar(false); });
        const id = await page.evaluate(() => tabState.activeTabId);
        const openTabs = await page.evaluate(() => tabState.tabs.map(tab => tab.id));
        await page.waitForFunction(() => Math.abs(document.querySelector('#tab-content-area').getBoundingClientRect().left) < 2);
        await page.locator('#ask-input').fill('未发送的匿名草稿');
        await page.reload();
        await checkAiPosition(page, type, id, key);
        await page.waitForFunction(() => Math.abs(document.querySelector('#tab-content-area').getBoundingClientRect().left) < 2);
        assert.deepEqual(await page.evaluate(() => tabState.tabs.map(tab => tab.id)), openTabs);
        assert.equal(await page.locator('#ask-input').inputValue(), '未发送的匿名草稿');
        await Promise.all([
          page.waitForURL(url => url.searchParams.get('reload') !== '100'),
          page.keyboard.press('Alt+Meta+r'),
        ]);
        await checkAiPosition(page, type, id, key);
        assert.equal(new URL(page.url()).searchParams.get('native-shell'), '1');

        await page.evaluate(() => createNewAskConversation());
        const emptyKey = await page.evaluate(() => getAskHistoryKey(askContext));
        assert.notEqual(emptyKey, key);
        await page.reload();
        await checkWorkspace(page, type, id);
        await page.waitForFunction(emptyKey => getAskHistoryKey(askContext) === emptyKey
          && askHistoryCache.has(emptyKey) && askHistoryCache.get(emptyKey).length === 0, emptyKey);

        await page.evaluate(() => closeTab(tabState.activeTabId));
        await page.reload();
        await page.waitForFunction(id => typeof appStartupComplete !== 'undefined' && appStartupComplete && !tabState.tabs.some(tab => tab.id === id), id);
      }

      await page.evaluate(() => goToMainView());
      await page.evaluate(() => toggleSidebar());
      await page.reload();
      await page.waitForFunction(() => typeof appStartupComplete !== 'undefined' && appStartupComplete && tabState.activeTabId === 'main');
      assert.equal(await page.locator('body').evaluate(el => el.classList.contains('sidebar-collapsed')), true);
      await page.evaluate(() => toggleSidebar());
      await page.reload();
      await page.waitForFunction(() => typeof appStartupComplete !== 'undefined' && appStartupComplete);
      assert.equal(await page.locator('body').evaluate(el => el.classList.contains('sidebar-collapsed')), false);

      await page.evaluate(() => openToolsMenu());
      const gear = page.locator('#tools-popup').getByRole('button', { name: '打开设置' });
      const pencil = page.locator('#tools-popup').getByRole('button', { name: '编辑效率中心入口' });
      await pencil.waitFor();
      assert.ok((await gear.boundingBox()).x < (await pencil.boundingBox()).x);
      await gear.press('Enter');
      await page.locator('#settings-modal-overlay.open').waitFor();
      assert.equal(await page.locator('#tools-popup').getAttribute('aria-hidden'), 'true');

      const mobile = await context.newPage();
      await mobile.setViewportSize({ width: 390, height: 844 });
      await mobile.goto(origin + '/');
      await mobile.waitForFunction(() => typeof appStartupComplete !== 'undefined' && appStartupComplete);
      await mobile.evaluate(() => toggleSidebar());
      await mobile.reload();
      await mobile.waitForFunction(() => typeof appStartupComplete !== 'undefined' && appStartupComplete && document.body.classList.contains('mobile-sidebar-open'));
      await mobile.evaluate(() => closeMobileSidebar());
      await mobile.reload();
      await mobile.waitForFunction(() => typeof appStartupComplete !== 'undefined' && appStartupComplete);
      assert.equal(await mobile.locator('body').evaluate(el => el.classList.contains('mobile-sidebar-open')), false);

      console.log(name + ': workspace, case details, AI history, navigation layout and reload passed');
      await context.close();
    } finally {
      await browser.close();
    }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
