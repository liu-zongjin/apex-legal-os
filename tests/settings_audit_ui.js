// Run against the isolated loopback fixture created for the settings audit.
const assert = require('node:assert/strict');
const path = require('node:path');
const {chromium, webkit} = require(process.env.STELLA_PLAYWRIGHT_MODULE || 'playwright');

const base = process.env.STELLA_SETTINGS_PREVIEW;
assert.match(base || '', /^http:\/\/127\.0\.0\.1:\d+$/);
const overlay = '#settings-modal-overlay';
const scrollArea = '.settings-modal-body';
const storageHead = '#settings-section-storage > .settings-section-head';
const homeHead = '#settings-home-workbench > .settings-section-head';

async function pinHeader(page, selector) {
  const head = page.locator(selector);
  const offset = await head.evaluate(el => {
    const area = el.closest('.settings-modal-body');
    const natural = el.getBoundingClientRect().top - area.getBoundingClientRect().top + area.scrollTop;
    area.scrollTop = natural + 90;
    return area.scrollTop;
  });
  assert(offset > 90);
  await page.waitForFunction(({selector, scrollArea}) => {
    const head = document.querySelector(selector);
    const container = document.querySelector(scrollArea);
    return Math.abs(head.getBoundingClientRect().top - container.getBoundingClientRect().top) < 2;
  }, {selector, scrollArea});
  assert(await head.evaluate(el => {
    const rect = el.getBoundingClientRect();
    const hit = document.elementFromPoint(rect.right - 20, rect.top + rect.height / 2);
    return el.contains(hit);
  }));
}

async function run(browserType, options, label) {
  const browser = await browserType.launch(options);
  try {
    const page = await browser.newPage({viewport:{width:1280,height:760}, reducedMotion:'reduce',
      serviceWorkers:'block'});
    // Use actual settings code and inventory. Prevent third-party network calls.
    await page.route('**/*', route => route.request().url().startsWith(base + '/')
      ? route.continue() : route.abort());
    await page.goto(base + '/?native-shell=1');
    await page.waitForFunction(() => window.SettingsAccordion && typeof openSettingsModal === 'function');
    const headers = [
      ['ai-extensions', /AI API 管理/], ['workspace', /储存管理/], ['productivity', /快捷键/],
      ['appearance', /首页工作台/], ['security', /个人中心保护/], ['system', /性能诊断/],
      ['backup', /自动备份计划/],
    ];
    await page.evaluate(() => openSettingsModal());
    for (const [group, header] of headers) {
      await page.locator(`[data-settings-section="${group}"]`).click();
      assert(await page.locator(overlay).getByRole('button', {name:header}).first().isVisible(), group);
    }
    let storageCalls = 0;
    page.on('request', request => { if (new URL(request.url()).pathname === '/api/storage-info') storageCalls++; });
    await page.evaluate(async () => {
      const images = await caches.open('legal-kb-article-images-v1');
      await images.put('/fixture-offline-image', new Response(new Uint8Array(2048)));
      openSettingsModal('storage');
    });
    await page.locator('.storage-hero').waitFor();
    await page.locator('.storage-offline-item').getByText('约 2.0 KiB', {exact:true}).waitFor();
    assert.equal(storageCalls, 1, 'direct opening fetches one inventory');
    await pinHeader(page, storageHead);
    const scrollBefore = await page.locator(scrollArea).evaluate(el => el.scrollTop);
    await page.waitForFunction(expected => {
      const saved = JSON.parse(sessionStorage.getItem('stella.settings.reload.v1') || 'null');
      return Math.abs((saved?.scrollTop || 0) - expected) < 2;
    }, scrollBefore);
    if (process.env.STELLA_SETTINGS_SCREENSHOTS && label === 'Chromium') {
      await page.screenshot({path:path.join(process.env.STELLA_SETTINGS_SCREENSHOTS,'stella-settings-sticky.png'), animations:'disabled'});
    }
    await page.route('**/api/storage-info', async route => {
      const response = await route.fetch();
      await new Promise(resolve => setTimeout(resolve, 200));
      await route.fulfill({response});
    });
    // A delayed inventory must not leave the restored accordion at the top.
    await page.reload();
    await page.locator('.storage-hero').waitFor();
    await page.waitForFunction(({scrollArea, scrollBefore}) =>
      Math.abs(document.querySelector(scrollArea).scrollTop - scrollBefore) < 2, {scrollArea, scrollBefore});
    await page.locator(storageHead).press('Enter');
    assert.equal(await page.locator(storageHead).getAttribute('aria-expanded'), 'false');

    await page.setViewportSize({width:1024,height:600});
    await page.evaluate(() => { document.body.classList.add('dark-mode'); selectSettingsSection('appearance'); });
    await page.locator(homeHead).click();
    await pinHeader(page, homeHead);
    await page.locator(homeHead).click();
    assert.equal(await page.locator(homeHead).getAttribute('aria-expanded'), 'false');

    await page.evaluate(() => openSettingsModal('storage'));
    await page.locator('.storage-hero').waitFor();
    await page.locator('.storage-tab').filter({hasText:'需确认'}).click();
    const count = await page.locator('#storage-modal-body .storage-item').count();
    assert.equal(Number(await page.locator('.storage-section-count').innerText().then(value => value.split(' ')[0])), count);
    await page.getByRole('searchbox', {name:'搜索储存项目'}).fill('没有这个储存项目');
    assert.match(await page.locator('.storage-section-count').innerText(), /^0 /);
    assert(await page.getByText('没有匹配的储存项目').isVisible());

    await page.evaluate(() => { document.body.classList.remove('dark-mode'); openSettingsModal('backup-files'); });
    const list = page.locator('#backup-files-list');
    await list.getByText('应用更新前备份', {exact:true}).waitFor();
    assert(await list.getByText('定时数据库备份', {exact:true}).isVisible());
    assert(await list.getByText(/2026-11-22 08:45:30/).first().isVisible());
    assert(await list.getByText(/建议保留/).first().isVisible());
    assert(await list.getByText(/原始文件名 before-source-start-/).isVisible());
    if (process.env.STELLA_SETTINGS_SCREENSHOTS && label === 'Chromium') {
      await page.setViewportSize({width:1280,height:880});
      await page.screenshot({path:path.join(process.env.STELLA_SETTINGS_SCREENSHOTS,'stella-settings-backups.png')});
    }
    const writes = [];
    await page.route('**/api/storage/cleanup', route => {
      writes.push(route.request().postDataJSON());
      return route.fulfill({json:{ok:true,count:1}});
    });
    await list.getByRole('button',{name:/删除 应用更新前备份/}).click();
    await page.getByRole('alertdialog').waitFor();
    assert.equal(writes.length, 0);
    await page.keyboard.press('Escape');
    assert.equal(writes.length, 0);
    await list.getByRole('button',{name:/删除 应用更新前备份/}).click();
    await page.getByRole('button',{name:'确认删除',exact:true}).click();
    await page.getByRole('alertdialog').waitFor({state:'detached'});
    assert.equal(writes.length, 1);
    assert.equal(writes[0].type, 'history_backup_files');
    assert.equal(Object.keys(writes[0].revisions).length, 1);
    console.log(`${label}: seven categories, storage reload, sticky headers, totals, backup labels and cancellation passed`);
  } finally {
    await browser.close();
  }
}
(async () => {
  await run(chromium, {channel:'chrome'}, 'Chromium');
  await run(webkit, {}, 'WebKit');
})().catch(error => { console.error(error); process.exitCode = 1; });
