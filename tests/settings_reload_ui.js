const fs = require('fs'), path = require('path'), assert = require('assert');
const acorn = require('acorn');
const {chromium} = require(process.env.STELLA_PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'frontend/index.html'), 'utf8');
const app = fs.readFileSync(path.join(root, 'frontend/app.js'), 'utf8');
const accordion = fs.readFileSync(path.join(root, 'frontend/settings-accordion.js'), 'utf8');
const css = fs.readFileSync(path.join(root, 'frontend/style.min.css'), 'utf8') + fs.readFileSync(path.join(root, 'frontend/settings-accordion.css'), 'utf8');
const tree = acorn.parse(app, {ecmaVersion:'latest'});
const get = name => { const node = tree.body.find(n => n.type === 'FunctionDeclaration' && n.id.name === name); assert(node, name); return app.slice(node.start, node.end); };
const fragment = html.slice(html.indexOf('  <div class="modal-overlay" id="settings-modal-overlay"'), html.indexOf('  <!-- 最近阅读 Modal -->'));
const functions = ['searchSettings','selectSettingsSection','openSettingsModal','closeSettingsModal','settingsReloadStores','saveSettingsReloadState','restoreSettingsReloadState'];
const stubs = ['closeBrandLogoHistory','renderKnowledgeThemeOptions','renderBrandLogo','applySidebarGreetingVisibility','renderLaunchDurationSetting','renderToolsHoverDelaySetting','renderToolsMenuMotionSettings','renderOpenPagesHoldDurationSetting','renderOpenPagesCommandSideSetting','renderSearchScopeSetting','syncSmartHibernationSetting','renderShortcutKeyboard','renderPersonalCenterSecurity','renderAccessUserSettings','renderCauseDictSettings','loadPerformanceDiagnostics','loadBackupManagement','openStorageModal','openOfflineCacheManager'].map(name => `function ${name}(){}`).join('\n');
const documentBody = `<!doctype html><html><head><meta charset="utf-8"><style>${css}</style></head><body>${fragment}<script>${stubs}\nconst SETTINGS_RELOAD_STATE_KEY='stella.settings.reload.v1';\n${functions.map(get).join('\n')}</script><script>${accordion}</script><script>restoreSettingsReloadState();const overlay=document.getElementById('settings-modal-overlay');overlay.addEventListener('click',saveSettingsReloadState);overlay.addEventListener('input',saveSettingsReloadState);overlay.querySelector('.settings-modal-body').addEventListener('scroll',saveSettingsReloadState);</script></body></html>`;
(async () => {
 const browser = await chromium.launch({headless:true, channel:'chrome'});
 try {
  const page = await browser.newPage({viewport:{width:1100,height:750}, reducedMotion:'reduce'});
  await page.route('http://settings.test/**', route => route.fulfill({contentType:'text/html; charset=utf-8', body:documentBody}));
  await page.goto('http://settings.test/?native-shell=1');
  await page.evaluate(() => openSettingsModal('appearance'));
  await page.locator('#settings-home-workbench .settings-section-head').click();
  const scrollBefore = await page.locator('.settings-modal-body').evaluate(el => { el.scrollTop = 100; return el.scrollTop; });
  assert(scrollBefore > 0);
  await page.reload();
  assert(await page.locator('#settings-modal-overlay').evaluate(e => e.classList.contains('open')));
  assert.equal(await page.locator('.settings-nav-item.active').getAttribute('data-settings-section'),'appearance');
  assert(await page.locator('#settings-home-workbench').evaluate(e => e.classList.contains('settings-accordion-open')));
  await page.waitForFunction(expected => Math.abs(document.querySelector('.settings-modal-body').scrollTop - expected) < 2, scrollBefore);
  await page.locator('#settings-search').fill('邮箱');
  // Simulate a native navigation that loses session storage and never dispatches beforeunload.
  await page.evaluate(() => sessionStorage.removeItem('stella.settings.reload.v1'));
  await page.evaluate(() => {location.href = '/?native-shell=1&reload=123';});
  await page.waitForURL('**/\u003fnative-shell=1&reload=123');
  assert(await page.locator('#settings-modal-overlay').evaluate(e => e.classList.contains('open')));
  assert.equal(await page.locator('#settings-search').inputValue(),'邮箱');
  assert(await page.locator('#settings-search-results').isVisible());
  await page.evaluate(() => closeSettingsModal());
  await page.reload();
  assert(!(await page.locator('#settings-modal-overlay').evaluate(e => e.classList.contains('open'))));
  await page.evaluate(() => openSettingsModal('workspace'));
  await page.goto('http://settings.test/?native-shell=1&other=1');
  assert(!(await page.locator('#settings-modal-overlay').evaluate(e => e.classList.contains('open'))));
  console.log('Settings refresh restores category, expanded section and search; ordinary navigation and closed settings stay closed');
 } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode=1});
