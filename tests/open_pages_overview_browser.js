// Isolated UI regression: real overview markup/rendering/CSS; anonymous tabs only.
const fs = require('fs'), path = require('path'), assert = require('assert');
const { chromium, webkit } = require(process.env.STELLA_PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'frontend/index.html'), 'utf8');
const markup = html.slice(html.indexOf('  <div class="open-pages-overview"'), html.indexOf('  <!-- 设置 Modal -->'));
const source = fs.readFileSync(path.join(root, 'frontend/app.js'), 'utf8');
const overview = source.slice(source.indexOf('function getOpenPageTypeLabel('), source.indexOf('function chooseOpenPageFromOverview('));
const bootstrap = `
  const TAB_TYPES = new Proxy({}, {get: (_, key) => key});
  const TAB_ICONS = new Proxy({}, {get: () => '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="7"/></svg>'});
  const TOOLS_GROUP_ICON = '', COURT_ONLINE_TAB_TYPES = new Set(),
    KNOWLEDGE_CENTER_TAB_TYPES = new Set(), SETTINGS_TAB_TYPES = new Set();
  const tabState = { activeTabId: 'tool-0', tabs: [
    ...Array.from({length: 7}, (_, i) => ({id: 'tool-'+i, type: 'SCANNER_INBOX', title: '测试工具 '+i})),
    {id: 'case-1', type: 'CASE_MANAGER', data: {caseTitle: '测试案件甲'}},
    {id: 'case-2', type: 'CASE_MANAGER', data: {caseTitle: '测试案件乙'}}
  ]};
  function escapeHtml(value) { return String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
  function sortTabsByRecentView(tabs) { return tabs; }
  function hideAllTabGroupMenus() {}
  ${overview}
  document.getElementById('open-pages-overview-categories').addEventListener('click', event => {
    const button = event.target.closest('[data-overview-category]');
    if (button) renderOpenPagesOverview(button.dataset.overviewCategory);
  });
`;

(async () => {
  const engine = process.env.STELLA_TEST_WEBKIT ? webkit : chromium;
  const browser = await engine.launch(process.env.STELLA_TEST_WEBKIT ? {headless: true} : {headless:true, channel:'chrome'});
  try {
    const page = await browser.newPage();
    await page.route('http://overview.test/**', async route => {
      const url = new URL(route.request().url());
      if (url.pathname === '/') return route.fulfill({contentType:'text/html', body:
        `<html><head><meta charset="utf-8"><link rel="stylesheet" href="/static/style.css"><script src="/static/apex-page-lifecycle.js"></script></head><body>${markup}<script>${bootstrap}</script></body></html>`});
      const file = path.join(root, 'frontend', url.pathname.replace('/static/', ''));
      if (!fs.existsSync(file)) return route.fulfill({status:404, body:''});
      return route.fulfill({body:fs.readFileSync(file), contentType:file.endsWith('.css')?'text/css':file.endsWith('.js')?'text/javascript':'image/png'});
    });
    for (const size of [{width:1440,height:900}, {width:1024,height:768}]) {
      await page.setViewportSize(size);
      for (const reducedMotion of ['no-preference', 'reduce']) {
        await page.emulateMedia({reducedMotion});
        await page.goto('http://overview.test/');
        // Freeze animation before rendering: reproduces the original blank cards.
        await page.evaluate(() => { document.documentElement.classList.add('apex-page-inactive'); openPagesOverview(); });
        for (const dark of [false, true]) {
          await page.evaluate(value => document.body.classList.toggle('dark-mode', value), dark);
          for (const [category, count] of [['case-manager',2], ['tools',7]]) {
            await page.locator(`[data-overview-category="${category}"]`).click();
            const cards = await page.locator('.open-page-card').evaluateAll(nodes => nodes.map(node => {
              const style = getComputedStyle(node), rect = node.getBoundingClientRect();
              return {opacity:style.opacity, width:rect.width, height:rect.height};
            }));
            assert.equal(cards.length, count);
            assert(cards.every(card => Number(card.opacity) === 1 && card.width > 100 && card.height > 100), JSON.stringify(cards));
            const viewport = await page.locator('#open-pages-overview-grid').evaluate(node => {
              const r = node.getBoundingClientRect(); return {height:r.height, bottom:r.bottom};
            });
            assert(viewport.height > 200 && viewport.bottom <= size.height, JSON.stringify(viewport));
          }
        }
        await page.addStyleTag({content:'.open-page-card {animation:none!important}'});
        for (let i = 0; i < 20; i++) {
          await page.evaluate(() => {closeOpenPagesOverview(); openPagesOverview();});
        }
        // Delayed close cleanup must not erase a newly opened overview.
        await page.waitForTimeout(260);
        assert.equal(await page.locator('.open-page-card').count(), 7);
        assert.equal(await page.locator('.open-page-card').first().evaluate(node => getComputedStyle(node).opacity), '1');
        if (process.env.STELLA_OVERVIEW_QA_OUTPUT) {
          fs.mkdirSync(process.env.STELLA_OVERVIEW_QA_OUTPUT, {recursive:true});
          await page.screenshot({path:path.join(process.env.STELLA_OVERVIEW_QA_OUTPUT, `overview-${size.width}-${reducedMotion}.png`)});
        }
      }
    }
    console.log('Overview UI: paused/disabled animation, categories, repeated reopen, light/dark, reduced motion and 2 window sizes passed');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exit(1);});
