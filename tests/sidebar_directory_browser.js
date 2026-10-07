// Optional browser QA: STELLA_PLAYWRIGHT_MODULE=/path/to/playwright node tests/sidebar_directory_browser.js
const { chromium } = require(process.env.STELLA_PLAYWRIGHT_MODULE || 'playwright');
const fs = require('fs');
const path = require('path');
const assert = require('assert');
(async () => {
  const output =
    process.env.STELLA_DIRECTORY_QA_OUTPUT ||
    path.join(require('os').tmpdir(), 'stella-directory-test');
  fs.mkdirSync(output, { recursive: true });
  const root = process.cwd(),
    browser = await chromium.launch({
      headless: true,
      executablePath:
        process.env.STELLA_CHROME_EXECUTABLE ||
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
    });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    reducedMotion: 'reduce'
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const domains = [
    {
      id: 1,
      domain: '行政法',
      count: 17,
      children: [
        { id: 101, name: '行政处罚', count: 3 },
        { id: 102, name: '党政领导干部依法履职与政绩观', count: 0 }
      ]
    },
    { id: 2, domain: '行政法相关', count: 4, children: [] }
  ];
  const authors = [
    { author: '测试作者', count: 2 },
    { author: '测试作者甲', count: 3 }
  ];
  const cats = [
    {
      id: 11,
      name: '常用资料',
      count: 4,
      tags: [
        { id: 201, name: '案例分析', count: 2 },
        { id: 202, name: '法律实务长名称用于检查目录省略与弹窗换行效果', count: 2 }
      ]
    }
  ];
  let failDirectoryRefresh = false;
  const fixtures = {
    '/api/domains': domains,
    '/api/authors': authors,
    '/api/tag-categories': cats,
    '/api/domains/pending-count': { count: 2 },
    '/api/domains/discovery-status': { queued: 0, total: 0, pending_suggestions: 0 },
    '/api/domains/suggestions': [],
    '/api/domains/suggestions/review': { items: [], total: 0 },
    '/api/articles': { articles: [], total: 0, page: 1, page_size: 10 }
  };
  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.startsWith('/api/')) {
      const method = route.request().method();
      if (method === 'DELETE' && url.pathname === '/api/domains/categories/102') {
        domains[0].children = domains[0].children.filter((x) => x.id !== 102);
        failDirectoryRefresh = true;
        return route.fulfill({ json: { ok: true } });
      }
      if (failDirectoryRefresh && url.pathname === '/api/domains')
        return route.fulfill({ status: 503, json: { detail: '模拟刷新失败' } });
      return route.fulfill({ json: fixtures[url.pathname] || {} });
    }
    let file = url.pathname === '/' ? 'index.html' : url.pathname.replace(/^\/static\//, '');
    let target = path.join(root, 'frontend', file);
    if (!fs.existsSync(target) || fs.statSync(target).isDirectory())
      return route.fulfill({ status: 404, body: '' });
    let content = fs.readFileSync(target);
    if (file === 'app.js')
      content = content
        .toString()
        .replace(
          "document.addEventListener('DOMContentLoaded', initApp);",
          '/* isolated fixture boot */'
        )
        .replace('  initApp();\n}', '  /* isolated fixture boot */\n}');
    const ext = path.extname(file);
    return route.fulfill({
      body: content,
      contentType:
        {
          '.html': 'text/html',
          '.js': 'application/javascript',
          '.css': 'text/css',
          '.svg': 'image/svg+xml',
          '.png': 'image/png'
        }[ext] || 'application/octet-stream'
    });
  });
  await page.goto('http://stella.test/');
  await page.waitForTimeout(1700);
  await page.evaluate(
    ({ domains, authors, cats }) => {
      _domainsEditorCache = domains;
      _authorsEditorCache = authors;
      _tagCategoriesCache = cats;
      _domainPendingCount = 2;
      initKnowledgeDirectory();
      showToast = () => {};
    },
    { domains, authors, cats }
  );
  assert.deepEqual(errors, []);
  await page.evaluate(() => {
    window._testApiFetch = apiFetch;
  });
  await page.evaluate(() => setDirectoryExpansionMode('click'));
  await page.locator('#nav-sec-domain .directory-section-heading').click();
  assert(await page.locator('#section-domain').isVisible());
  await page.locator('#domain-list .directory-arrow').nth(1).click();
  await page.getByRole('button', { name: '党政领导干部依法履职与政绩观 0', exact: true }).click();
  assert.equal(await page.evaluate(() => state.subcategoryId), 102);
  await page.getByRole('button', { name: '行政法 17', exact: true }).click();
  assert.equal(await page.evaluate(() => state.domain), '行政法');
  assert.equal(await page.evaluate(() => state.subcategoryId), null);
  await page.getByRole('button', { name: '行政法 17', exact: true }).click();
  assert.equal(await page.evaluate(() => state.domain), '行政法');
  await page.locator('#directory-search').fill('党政');
  assert(
    await page
      .getByRole('button', { name: '党政领导干部依法履职与政绩观 0', exact: true })
      .isVisible()
  );
  await page.locator('#directory-search').fill('');
  assert.equal(await page.evaluate(() => state.domain), '行政法');
  await page.locator('#nav-sec-author .directory-section-heading').click();
  assert(!(await page.locator('#section-domain').isVisible()));
  await page.getByRole('button', { name: '测试作者 2', exact: true }).click();
  assert.equal(await page.evaluate(() => state.domain), null);
  assert.equal(await page.evaluate(() => state.author), '测试作者');
  await page.getByRole('button', { name: '管理目录', exact: true }).click();
  await page.waitForTimeout(100);
  assert(await page.getByRole('tab', { name: '专业领域', exact: true }).isVisible());
  await page.evaluate(() => {
    document.getElementById('tab-page-main').style.display = 'none';
  });
  assert(await page.locator('#domain-classification-modal').isVisible());
  await page.evaluate(() => {
    document.getElementById('tab-page-main').style.display = '';
  });
  await page.getByRole('tab', { name: '自定义库', exact: true }).click();
  assert(await page.getByRole('button', { name: '常用资料改名', exact: true }).isVisible());
  await page.getByRole('button', { name: '常用资料改名', exact: true }).click();
  await page.locator('#directory-action-name').fill('新的资料库');
  await page.evaluate(() => {
    apiFetch = async () => {
      throw new Error('模拟保存失败');
    };
  });
  await page.locator('#directory-action-submit').click();
  await page.waitForTimeout(80);
  assert.equal(await page.locator('#directory-action-name').inputValue(), '新的资料库');
  assert.equal(await page.evaluate(() => _tagCategoriesCache[0].name), '常用资料');
  assert(await page.locator('#directory-action-error').textContent());
  await page.locator('#directory-action-modal .btn-secondary').click();
  await page.evaluate(() => {
    apiFetch = window._testApiFetch;
  });
  await page.getByRole('tab', { name: '专业领域', exact: true }).click();
  await page.getByRole('button', { name: '党政领导干部依法履职与政绩观删除', exact: true }).click();
  await page.locator('#directory-action-submit').click();
  await page.waitForTimeout(120);
  assert.equal(
    await page.evaluate(() => _domainsEditorCache[0].children.some((x) => x.id === 102)),
    false
  );
  assert.equal(
    await page.evaluate(() =>
      JSON.parse(localStorage.getItem(DOMAINS_OFFLINE_CACHE_KEY))[0].children.some(
        (x) => x.id === 102
      )
    ),
    false
  );
  await page.getByRole('tab', { name: '自定义库', exact: true }).click();
  await page.screenshot({ path: path.join(output, 'manager-light-1440.png') });
  await page.evaluate(() => {
    document.documentElement.classList.add('dark-mode');
    document.body.classList.add('dark-mode');
  });
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(output, 'manager-dark-1024.png') });
  await page.evaluate(() => closeDomainClassificationModal());
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.evaluate(() => {
    document.documentElement.classList.remove('dark-mode');
    document.body.classList.remove('dark-mode');
    setDirectoryExpansionMode('hover');
    directoryState.expanded.clear();
    refreshKnowledgeDirectory();
  });
  await page.mouse.move(700, 500);
  await page.locator('#nav-sec-domain .directory-section-heading').hover();
  await page.waitForTimeout(280);
  assert(await page.locator('#section-domain').isVisible());
  assert(await page.getByRole('button', { name: '行政处罚 3', exact: true }).isVisible());
  await page.getByRole('button', { name: '行政法 17', exact: true }).hover();
  await page.waitForTimeout(300);
  assert(await page.locator('#section-domain').isVisible());
  await page.mouse.move(700, 500);
  await page.waitForTimeout(100);
  assert(await page.locator('#section-domain').isVisible());
  await page.waitForTimeout(220);
  assert(!(await page.locator('#section-domain').isVisible()));
  await page.locator('#nav-sec-customLib .directory-section-heading').hover();
  await page.waitForTimeout(280);
  assert(await page.getByRole('button', { name: '案例分析 2', exact: true }).isVisible());
  await page.mouse.move(700, 500);
  await page.waitForTimeout(300);
  assert(!(await page.getByRole('button', { name: '案例分析 2', exact: true }).isVisible()));
  await page.locator('#nav-sec-domain .directory-section-heading').hover();
  await page.waitForTimeout(80);
  await page.mouse.move(700, 500);
  await page.waitForTimeout(300);
  assert(!(await page.locator('#section-domain').isVisible()));
  await page.locator('#nav-sec-domain .directory-section-heading').hover();
  await page.waitForTimeout(60);
  await page.evaluate(() => setDirectoryExpansionMode('click'));
  await page.waitForTimeout(300);
  assert(!(await page.locator('#section-domain').isVisible()));
  await page.locator('#nav-sec-domain .directory-section-heading').click();
  await page.locator('#domain-list .directory-arrow').nth(1).click();
  const before = await page.evaluate(() => [...directoryState.expanded]);
  await page.locator('#directory-search').fill('行政处罚');
  await page.locator('#domain-list .directory-arrow').nth(0).click();
  await page.locator('#directory-search').fill('');
  assert.deepEqual(await page.evaluate(() => [...directoryState.expanded]), before);
  await page.evaluate(() => refreshKnowledgeDirectory());
  assert(await page.getByRole('button', { name: '行政处罚 3', exact: true }).isVisible());
  await page.screenshot({ path: path.join(output, 'sidebar-light-1440.png') });
  await page.reload();
  await page.waitForTimeout(1600);
  await page.evaluate(
    ({ domains, authors, cats }) => {
      _domainsEditorCache = domains;
      _authorsEditorCache = authors;
      _tagCategoriesCache = cats;
      initKnowledgeDirectory();
    },
    { domains, authors, cats }
  );
  assert.equal(await page.evaluate(() => directoryState.mode), 'click');
  assert(await page.locator('#section-domain').isVisible());
  await page.evaluate(() => {
    document.documentElement.style.setProperty('--apex-accent', '#456a57');
    document.body.style.setProperty('--sb-ink', '#31473a');
  });
  await page.screenshot({ path: path.join(output, 'sidebar-theme-1440.png') });
  await page.getByRole('button', { name: '管理目录', exact: true }).click();
  await page.getByRole('tab', { name: '专业领域', exact: true }).focus();
  await page.keyboard.press('ArrowRight');
  assert(
    (await page
      .getByRole('tab', { name: '自定义库', exact: true })
      .getAttribute('aria-selected')) === 'true'
  );
  await page.keyboard.press('Escape');
  assert(!(await page.locator('#domain-classification-modal').isVisible()));
  // Touch is verified on the same production DOM using dispatch of a touch pointer.
  await page
    .locator('#nav-sec-author .directory-section-heading')
    .dispatchEvent('pointerenter', { pointerType: 'touch' });
  await page.waitForTimeout(300);
  assert(!(await page.locator('#section-author').isVisible()));
  await page.locator('#nav-sec-author .directory-section-heading').click();
  assert(await page.locator('#section-author').isVisible());
  assert.deepEqual(errors, []);
  await page.evaluate(() => {
    document.body.classList.add('dark-mode');
    document.documentElement.classList.add('dark-mode');
  });
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.getByRole('button', { name: '管理目录', exact: true }).click();
  await page.getByRole('tab', { name: '专业领域', exact: true }).click();
  await page.evaluate(() => {
    window._qaDirs = _domainsEditorCache;
    _domainsEditorCache = [
      {
        id: 1,
        domain: '行政法',
        count: 80,
        children: Array.from({ length: 80 }, (_, i) => ({
          id: 1000 + i,
          name: `较长的行政法律主题分类名称用于检查滚动与换行 ${i}`,
          count: i
        }))
      }
    ];
    renderDomainChildOrder();
    refreshKnowledgeDirectory();
  });
  assert(
    await page
      .locator('#domain-classification-modal .domain-modal-content')
      .first()
      .evaluate((el) => el.scrollHeight > el.clientHeight)
  );
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  const cdp = await context.newCDPSession(page);
  await cdp.send('Emulation.setEmulatedMedia', {
    features: [{ name: 'prefers-reduced-transparency', value: 'reduce' }]
  });
  assert.equal(
    await page.locator('.directory-manager').evaluate((el) => getComputedStyle(el).backdropFilter),
    'none'
  );
  await page.screenshot({ path: path.join(output, 'manager-long-1024.png') });
  await page.evaluate(() => {
    _domainsEditorCache = window._qaDirs;
    closeDomainClassificationModal();
  });
  assert(
    await page
      .locator('.sidebar-footer')
      .evaluate((el) => el.getBoundingClientRect().bottom <= innerHeight)
  );
  assert.deepEqual(errors, []);
  console.log('browser directory workflows passed; light/dark/theme screenshots saved');
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
