const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium, webkit } = require(process.env.STELLA_PLAYWRIGHT_MODULE || 'playwright');

const root = path.resolve(__dirname, '..', 'frontend');
const origin = 'http://stella-search.test';
const article = {
  id: 42, title: '示例合同', content: '<p>审查合同条款和付款期限。</p>',
  summary: '合同内容', created_at: '2026-11-22T09:00:00+08:00', notes: [],
};
const fixtures = {
  '/api/articles': { articles: [article], total: 1, page: 1, page_size: 10 },
  '/api/articles/42': article,
  '/api/ai-ask/history': { conversations: [] },
  '/api/domains': [],
  '/api/authors': [],
  '/api/tag-categories': [],
  '/api/case-manager/cases/901/folder-binding': { bound: true, folder_path: '/示例目录' },
  '/api/case-manager/cases/901/local-files/list': { path: '', items: [] },
  '/api/case-manager/court-online/status': { record_count: 1 },
  '/api/case-manager/court-online/records': { items: [], total: 0 },
  '/api/case-manager/court-online/readings': { items: [], total: 0 },
  '/api/server-status': { status: 'running' },
};

async function serve(route) {
  const { pathname } = new URL(route.request().url());
  if (pathname.startsWith('/api/')) {
    return route.fulfill({ json: pathname.endsWith('/session-status')
      ? { server_reachable: true, authenticated: true }
      : fixtures[pathname] ?? { items: [], total: 0 } });
  }
  const relative = pathname === '/' ? 'index.html' : pathname.startsWith('/static/')
    ? pathname.slice('/static/'.length) : pathname.slice(1) + '.html';
  const file = path.resolve(root, relative);
  if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
    return route.fulfill({ status: 404 });
  }
  return route.fulfill({ path: file });
}

async function assertFocused(locator, focused) {
  await locator.evaluate((input, expected) => {
    if ((input.ownerDocument.activeElement === input) !== expected) {
      throw new Error('Unexpected focus for ' + (input.id || input.className));
    }
  }, focused);
}

async function toggle(page, field, key = 'Meta+f') {
  await page.keyboard.press(key);
  await assertFocused(field, true);
  const value = await field.inputValue();
  await page.keyboard.press(key);
  await assertFocused(field, false);
  assert.equal(await field.inputValue(), value);
}

async function run(browser) {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce', serviceWorkers: 'block',
  });
  try {
    await context.route(origin + '/**', serve);
    const page = await context.newPage();
    page.setDefaultTimeout(8000);
    await page.goto(origin + '/?native-shell=1');
    await page.waitForFunction(() => typeof appStartupComplete !== 'undefined' && appStartupComplete);

    await toggle(page, page.locator('#search-input'));
    await page.locator('#directory-search').fill('待保留');
    await page.keyboard.press('Meta+f');
    await assertFocused(page.locator('#directory-search'), false);
    assert.equal(await page.locator('#directory-search').inputValue(), '待保留');

    await page.evaluate(() => {
      localStorage.setItem('legal_kb_shortcut_bindings_v1',
        JSON.stringify({ j: { actionId: 'focus_search', modifiers: ['alt'] } }));
      openSettingsModal('workspace');
    });
    const settings = page.locator('#settings-search');
    await toggle(page, settings);
    await toggle(page, settings, 'Alt+j');
    assert.equal(await page.locator('#settings-modal-overlay').evaluate(el => el.classList.contains('open')), true);
    await page.evaluate(() => closeSettingsModal());

    await page.evaluate(() => openArticleInTab(42, '示例合同'));
    const articleSearch = page.locator('.tab-page.active .detail-search-input');
    await articleSearch.waitFor();
    await page.keyboard.press('Meta+f');
    await assertFocused(articleSearch, true);
    await articleSearch.fill('合同');
    await page.locator('.tab-page.active .detail-search-dropdown').waitFor();
    await page.keyboard.press('Meta+f');
    await assertFocused(articleSearch, false);
    await page.locator('.tab-page.active .detail-search-dropdown').waitFor({ state: 'hidden' });
    assert.equal(await articleSearch.inputValue(), '合同');

    // The first press can originate in the host. The second originates in the iframe.
    const workspaces = [
      [() => openCaseManagerTab(), '.jm-search-field input'],
      [() => openCourtOnlineService(0, { kind: 'delivery' }), '#courtSearch'],
      [() => openCaseFilesTab(901, '示例案件'), '#fileSearch'],
      [() => openLegalKnowledgeTab(), '#hero-search'],
      [() => openSkillManagerTab(), '#searchInput'],
      [() => openDownloadCenterTab(), '#dc-search'],
    ];
    const frame = page.frameLocator('.tab-page.active iframe.tab-iframe');
    for (const [open, field] of workspaces) {
      await page.evaluate(open);
      const input = frame.locator(field);
      await input.waitFor();
      await page.locator('#tab-bar-home-btn').focus();
      await toggle(page, input);
      await toggle(page, input, 'Alt+j');
    }

    for (const open of [() => openAskPanel(), () => openCaseAiPanel()]) {
      await page.evaluate(open);
      await page.evaluate(() => toggleAskHistorySidebar(false));
      const history = page.locator('#ask-history-search-input');
      await toggle(page, history);
      await toggle(page, history, 'Alt+j');
    }

    // An unbound case folder has no visible file search. Do not take the
    // user to the home search or consume the browser's remaining shortcut.
    await page.evaluate(() => openCaseFilesTab(902, '未绑定目录的示例案件'));
    await frame.getByText('尚未绑定本地案件文件夹', { exact: true }).first().waitFor();
    await page.locator('#tab-bar-home-btn').focus();
    assert.equal(await page.evaluate(() => document.dispatchEvent(new KeyboardEvent('keydown', {
      code: 'KeyF', key: 'f', metaKey: true, bubbles: true, cancelable: true,
    }))), true);
    await assertFocused(page.locator('#search-input'), false);

    // Standalone pages still use the same Command/Ctrl+F implementation.
    await page.goto(origin + '/legal-knowledge');
    await toggle(page, page.locator('#hero-search'), 'Control+f');
    await toggle(page, page.locator('#hero-search'), 'Alt+j');
    await page.goto(origin + '/case-files?case_id=901');
    await toggle(page, page.locator('#fileSearch'));
  } finally {
    await context.close();
  }
}

(async () => {
  for (const [name, engine, options] of [
    ['Chromium', chromium, { channel: 'chrome' }],
    ['WebKit', webkit, {}],
  ]) {
    const browser = await engine.launch(options);
    try {
      await run(browser);
      console.log(name + ': foreground search, iframe and standalone toggle passed');
    } finally {
      await browser.close();
    }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
