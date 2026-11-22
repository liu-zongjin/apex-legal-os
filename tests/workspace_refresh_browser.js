const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium, webkit } = require(process.env.STELLA_PLAYWRIGHT_MODULE || 'playwright');

const root = path.resolve(__dirname, '..', 'frontend');
const origin = 'http://workspace-refresh.test';
const caseContext = { type: 'case_database' };
const article = {
  id: 42, title: '合同审查要点', author: '示例作者', domains: ['合同法'],
  content: '<p>合同审查应先确认签约主体、履行期限与违约责任。</p><p>逐条核对付款节点、通知方式及争议解决条款。</p>',
  summary: '一份用于预览文章阅读界面的示例知识。', created_at: '2026-11-22T09:00:00+08:00', notes: [],
};
const sampleCase = {
  id: 901, title: '匿名示例案件', case_kind: 'ordinary', source_status: 'active', current_stage: '一审',
  updated_at: '2026-11-17T16:01:00+08:00', hearing_count: 1, pinned: true,
};
const courtApi = '/api/case-manager/court-online';
const delivery = {
  id: 101, kind: 'delivery', unread: true, title: '示例电子送达通知书',
  published_at: '2026-11-20T15:21:00+08:00', court_name: '示例人民法院',
  attachments: [{ id: 1, filename: '示例通知书.pdf' }],
};
const rail = (page, id) => page.locator('[data-work-action="' + id + '"]');
const expectRailWidth = page => page.waitForFunction(() => {
  const sidebar = document.querySelector('#sidebar').getBoundingClientRect();
  const content = document.querySelector('#tab-content-area').getBoundingClientRect();
  return Math.abs(sidebar.width - 60) < 1 && Math.abs(content.left - sidebar.right) < 1;
});
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
    if (name === '/api/articles') json.articles = [article];
    if (name === '/api/articles/42') json = article;
    if (name === '/api/domains') json = [{ id: 1, domain: '合同法', count: 1, children: [] }];
    if (name === '/api/authors') json = [{ author: '示例作者', count: 1 }];
    if (name === '/api/tag-categories') json = [{ id: 2, name: '示例库', count: 1, tags: [] }];
    if (name === '/api/case-manager/cases') {
      json = url.searchParams.get('case_id') === '901' ? sampleCase : { items: [sampleCase], total: 1 };
    }
    if (name === courtApi + '/status') {
      json = { record_count: 259, todo_count: 29, message_count: 160, delivery_count: 70, case_count: 168,
        layy_count: 37, hearing_count: 83, credentials_configured: true };
    }
    if (name === courtApi + '/records') json = { items: [delivery], total: 70 };
    if (name === courtApi + '/readings') json = { items: [], total: 3 };
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
  if (type !== 'main') await expectRailWidth(page);
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

      const previews = name === 'Chromium' && process.env.STELLA_SIDEBAR_PREVIEWS;
      const capture = async filename => {
        if (previews) await page.screenshot({ path: path.join(previews, filename) });
      };
      await page.waitForFunction(() => document.querySelector('#sidebar').getBoundingClientRect().width >= 239);
      await capture('stella-home.png');
      await page.emulateMedia({ reducedMotion: 'no-preference' });
      await page.evaluate(() => openArticleInTab(42, '合同审查要点'));
      await expectRailWidth(page);
      await page.locator('.tab-article-body').waitFor();
      assert.equal(await rail(page, 'all').getAttribute('aria-current'), 'true');
      assert.equal(await page.locator('.work-sidebar-button').count(), 11);
      const element = rail(page, 'stats');
      const box = await element.boundingBox();
      assert.equal(box.width, box.height);
      await rail(page, 'home').hover();
      await page.getByRole('tooltip', { name: '返回首页' }).waitFor();
      await page.waitForFunction(() => {
        const tip = document.querySelector('#work-sidebar-tooltip');
        const tabs = document.querySelector('#tab-bar').getBoundingClientRect();
        const box = tip.getBoundingClientRect();
        return box.top >= tabs.bottom && tip.contains(document.elementFromPoint(box.x + 4, box.top + 5));
      });
      await element.hover();
      await page.waitForFunction(() => {
        const tooltip = document.querySelector('#work-sidebar-tooltip');
        const box = document.querySelector('[data-work-action="stats"]').getBoundingClientRect();
        const tip = tooltip.getBoundingClientRect();
        return Math.abs(tip.top + tip.height / 2 - box.top - box.height / 2) < 1;
      });
      const tip = page.getByRole('tooltip', { name: '可视化统计' });
      await tip.waitFor();
      assert.ok((await tip.boundingBox()).x > box.x + box.width);
      await capture('stella-article-tooltip.png');
      await page.setViewportSize({ width: 1440, height: 710 });
      await page.waitForFunction(() => {
        const tip = document.querySelector('#work-sidebar-tooltip');
        const box = document.querySelector('[data-work-action="stats"]').getBoundingClientRect();
        const panel = tip.getBoundingClientRect();
        return tip.getAttribute('aria-hidden') === 'true' ||
          Math.abs(panel.top + panel.height / 2 - box.top - box.height / 2) < 1;
      });
      await page.setViewportSize({ width: 1440, height: 900 });
      await rail(page, 'settings').focus();
      await page.getByRole('tooltip', { name: '设置' }).waitFor();
      await page.keyboard.press('Escape');
      assert.equal(await page.getByRole('tooltip').count(), 0);
      await page.keyboard.press('Enter');
      await page.locator('#settings-modal-overlay.open').waitFor();
      await page.evaluate(() => closeSettingsModal());
      await rail(page, 'trash').click();
      await page.getByRole('dialog', { name: '知识库回收站' }).waitFor();
      await page.evaluate(() => closeArticleTrash());
      await rail(page, 'add').click();
      await page.locator('#submit-modal.open').waitFor();
      await page.evaluate(() => closeSubmitModal());
      await rail(page, 'knowledge').click();
      await page.waitForFunction(() => tabState.tabs.find(tab => tab.id === tabState.activeTabId)?.type === 'legal_knowledge');
      assert.equal(await rail(page, 'knowledge').getAttribute('aria-current'), 'true');
      await rail(page, 'stats').click();
      await page.waitForFunction(() => tabState.tabs.find(tab => tab.id === tabState.activeTabId)?.type === 'kb_stats');
      assert.equal(await rail(page, 'stats').getAttribute('aria-current'), 'true');
      await page.evaluate(() => openArticleInTab(42, '合同审查要点'));
      for (const key of ['domain', 'customLib', 'author']) {
        const directory = rail(page, key);
        await directory.click();
        assert.equal(await directory.getAttribute('aria-expanded'), 'true');
        await page.locator('#section-' + key).waitFor();
        await page.keyboard.press('Escape');
        assert.equal(await directory.getAttribute('aria-expanded'), 'false');
      }
      await rail(page, 'domain').click();
      await page.getByRole('button', { name: '管理目录' }).click();
      await page.getByRole('dialog', { name: '目录管理' }).waitFor();
      await page.keyboard.press('Escape');
      await page.getByRole('dialog', { name: '目录管理' }).waitFor({ state: 'hidden' });
      assert.equal(await rail(page, 'domain').evaluate(el => el === document.activeElement), true);

      await rail(page, 'domain').click();
      await capture('stella-article-directory.png');
      await page.locator('#domain-list .directory-label').getByText('合同法').click();
      await page.waitForFunction(() => tabState.activeTabId === 'main' && state.domain === '合同法');
      assert.equal(await rail(page, 'domain').isVisible(), false);
      await page.waitForFunction(() => document.querySelector('#sidebar').getBoundingClientRect().width >= 239);
      await page.emulateMedia({ reducedMotion: 'reduce' });
      await page.evaluate(() => openArticleInTab(42, '合同审查要点'));
      await rail(page, 'notes').click();
      await page.waitForFunction(() => tabState.activeTabId === 'main' && state.view === 'notes');

      await page.evaluate(() => openCaseManagerTab());
      const caseId = await page.evaluate(() => tabState.activeTabId);
      const cases = page.frameLocator('.tab-page.active iframe');
      for (const width of [1470, 1160, 1024, 961]) {
        await page.setViewportSize({ width, height: 900 });
        await cases.locator('.table-cases .date-main').first().waitFor();
        const cells = await cases.locator('.table-cases tbody tr').first().evaluate(row => {
          const date = document.createRange();
          date.selectNodeContents(row.querySelector('.date-main'));
          const action = row.querySelector('.action-cell .actions');
          const scroll = row.closest('.table-x-scroll');
          return [date.getClientRects().length, action.scrollWidth <= action.clientWidth + 1,
            scroll.scrollWidth <= scroll.clientWidth + 2];
        });
        assert.deepEqual(cells, [1, true, true], 'case fields at width ' + width);
      }
      await page.setViewportSize({ width: 1440, height: 900 });
      const frame = page.frameLocator('iframe[src^="/case-manager"]');
      await frame.locator('[data-tab="todos"]').first().click();
      await page.waitForFunction(() => tabState.tabs.find(t => t.id === tabState.activeTabId)?.data?.pageLabel === '待办事项');
      await page.reload();
      await checkWorkspace(page, 'case_manager', caseId);
      await frame.locator('[data-tab="todos"].active').first().waitFor();
      await capture('stella-case-manager.png');

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
        await expectRailWidth(page);
        await capture(type === 'case_ai' ? 'stella-case-ai.png' : 'stella-ai-enhance.png');
        await rail(page, 'home').hover();
        await page.getByRole('tooltip', { name: '返回首页' }).waitFor();
        assert.ok(await page.evaluate(() => {
          const tip = document.querySelector('#work-sidebar-tooltip').getBoundingClientRect();
          const heading = document.querySelector('.tab-page.active .ask-panel-head-left').getBoundingClientRect();
          return tip.left >= heading.right;
        }), 'the home tooltip must clear the AI header controls');
        if (type === 'case_ai') {
          await page.setViewportSize({ width: 1024, height: 540 });
          await page.evaluate(() => setThemeMode('dark'));
          await rail(page, 'stats').focus();
          await page.keyboard.press('Tab');
          await page.getByRole('tooltip', { name: '设置' }).waitFor();
          await capture('stella-case-ai-dark.png');
          await page.keyboard.press('Escape');
          assert.equal(await page.evaluate(() => tabState.activeTabId), id);
          await page.evaluate(() => setThemeMode('light'));
          await page.setViewportSize({ width: 1440, height: 900 });
        }
        await page.locator('#ask-input').fill('未发送的匿名草稿');
        await page.reload();
        await checkAiPosition(page, type, id, key);
        await expectRailWidth(page);
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

      await page.evaluate(() => openCourtOnlineService(0, { kind: 'delivery' }));
      await expectRailWidth(page);
      const court = page.frameLocator('.tab-page.active iframe');
      await court.getByText('示例电子送达通知书', { exact: true }).waitFor();
      for (const width of [1470, 1024, 769, 390]) {
        await page.setViewportSize({ width, height: 900 });
        const layout = await court.locator('.court-filter-toolbar').evaluate(toolbar => {
          const total = toolbar.querySelector('.court-result-count');
          const range = document.createRange();
          range.selectNodeContents(total);
          const bounds = toolbar.getBoundingClientRect();
          const controls = [...toolbar.querySelectorAll('.court-search-controls > :not([hidden])')];
          return [range.getClientRects().length,
            controls.every(el => el.getBoundingClientRect().right <= bounds.right + 1),
            bounds.width > 0];
        });
        assert.deepEqual(layout, [1, true, true], 'court toolbar at width ' + width);
        const category = court.locator('#courtKindTabs [data-kind="cases"]').first();
        await category.focus();
        const submenu = court.locator('#courtCaseAjlbMenu');
        await submenu.waitFor();
        assert.ok(await submenu.evaluate(el => {
          const bounds = el.getBoundingClientRect();
          return bounds.left >= 0 && bounds.right <= innerWidth;
        }), 'court category submenu at width ' + width);
        await court.locator('#courtSearch').focus();
        if (width === 1470) await capture('stella-court-online.png');
      }
      await page.setViewportSize({ width: 1440, height: 900 });

      await page.setViewportSize({ width: 769, height: 844 });
      await page.evaluate(() => {
        openCaseFilesTab(901, '匿名示例案件');
        openCaseArchiveTab(901, '匿名示例案件');
        openAiApiManagerTab();
      });
      await page.waitForFunction(() => {
        const strip = document.querySelector('#tab-bar-tabs');
        const active = strip.querySelector(':scope > .tab-item.active');
        const tab = active?.getBoundingClientRect();
        const bar = strip.getBoundingClientRect();
        const actions = document.querySelector('.tab-bar-actions').getBoundingClientRect();
        return tab?.width && strip.scrollWidth > strip.clientWidth &&
          getComputedStyle(strip).overflowX === 'auto' &&
          tab.left >= bar.left - 1 && tab.right <= actions.left + 1;
      });
      await page.setViewportSize({ width: 1440, height: 900 });

      await page.evaluate(() => goToMainView());
      const homeToggle = page.getByRole('button', { name: '切换侧边栏' });
      await homeToggle.click();
      await expectRailWidth(page);
      await page.reload();
      await page.waitForFunction(() => typeof appStartupComplete !== 'undefined' && appStartupComplete && tabState.activeTabId === 'main');
      assert.equal(await page.locator('body').evaluate(el => el.classList.contains('sidebar-collapsed')), true);
      await page.evaluate(() => toggleSidebar());
      await page.reload();
      await page.waitForFunction(() => typeof appStartupComplete !== 'undefined' && appStartupComplete);
      assert.equal(await page.locator('body').evaluate(el => el.classList.contains('sidebar-collapsed')), false);

      await page.evaluate(() => openSettingsModal('work-sidebar'));
      const switcher = page.getByRole('switch', { name: '收起时显示窄边栏' });
      if (!(await switcher.isVisible())) await page.getByRole('button', { name: '侧边栏', exact: true }).click();
      assert.equal(await switcher.getAttribute('aria-checked'), 'true');
      await capture('stella-sidebar-setting.png');
      await switcher.click();
      assert.equal(await switcher.getAttribute('aria-checked'), 'false');
      await page.evaluate(() => closeSettingsModal());
      await page.evaluate(() => openCaseManagerTab());
      await page.waitForFunction(() => document.querySelector('#sidebar').getBoundingClientRect().width === 0 &&
        document.querySelector('#tab-content-area').getBoundingClientRect().left === 0);
      await page.reload();
      await page.waitForFunction(() => appStartupComplete && tabState.activeTabId !== 'main');
      assert.equal(await rail(page, 'home').isVisible(), false);
      await page.evaluate(() => goToMainView());
      await homeToggle.click();
      await page.waitForFunction(() => document.querySelector('#sidebar').getBoundingClientRect().width === 0);
      await homeToggle.click();
      await page.waitForFunction(() => document.querySelector('#sidebar').getBoundingClientRect().width >= 239);
      await page.evaluate(() => openSettingsModal('work-sidebar'));
      if (!(await switcher.isVisible())) await page.getByRole('button', { name: '侧边栏', exact: true }).click();
      await switcher.click();
      await page.evaluate(() => closeSettingsModal());

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

      await mobile.evaluate(() => openArticleInTab(42, '合同审查要点'));
      assert.equal(await rail(mobile, 'settings').isVisible(), false);
      const drawer = mobile.getByRole('button', { name: '打开工作区导航' });
      assert.equal(await mobile.locator('#sidebar').evaluate(el => el.inert), true);
      await drawer.click();
      assert.equal(await drawer.getAttribute('aria-expanded'), 'true');
      await mobile.getByRole('button', { name: '管理目录' }).click();
      await mobile.getByRole('dialog', { name: '目录管理' }).waitFor();
      assert.equal(await mobile.locator('#sidebar').evaluate(el => el.inert), true);
      await mobile.keyboard.press('Escape');
      await mobile.getByRole('dialog', { name: '目录管理' }).waitFor({ state: 'hidden' });
      assert.equal(await drawer.evaluate(el => el === document.activeElement), true);
      await drawer.click();
      assert.equal(await drawer.getAttribute('aria-expanded'), 'true');
      if (previews) await mobile.screenshot({ path: path.join(previews, 'stella-mobile-drawer.png') });
      await mobile.locator('#sidebar-nav [data-view="notes"]').click();
      await mobile.waitForFunction(() => tabState.activeTabId === 'main' && state.view === 'notes');
      assert.equal(await mobile.locator('#sidebar').evaluate(el => el.classList.contains('mobile-open')), false);

      await mobile.evaluate(() => openArticleInTab(42, '合同审查要点'));
      await mobile.setViewportSize({ width: 768, height: 844 });
      assert.equal(await drawer.isVisible(), true);
      await mobile.setViewportSize({ width: 769, height: 844 });
      await expectRailWidth(mobile);
      assert.equal(await drawer.isVisible(), false);

      console.log(name + ': workspace, case details, AI history, navigation layout and reload passed');
      await context.close();
    } finally {
      await browser.close();
    }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
