const fs = require('fs'), path = require('path'), assert = require('assert');
const {chromium} = require(process.env.STELLA_PLAYWRIGHT_MODULE || 'playwright');
const acorn = require('acorn');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'frontend/index.html'), 'utf8');
const app = fs.readFileSync(path.join(root, 'frontend/app.js'), 'utf8');
const css = fs.readFileSync(path.join(root, 'frontend/style.min.css'), 'utf8') + fs.readFileSync(path.join(root, 'frontend/settings-accordion.css'), 'utf8');
const accordion = fs.readFileSync(path.join(root, 'frontend/settings-accordion.js'), 'utf8');
const tree = acorn.parse(app, {ecmaVersion:'latest'});
const get = name => { const n = tree.body.find(n => n.type === 'FunctionDeclaration' && n.id.name === name); assert(n, name); return app.slice(n.start, n.end); };
const fragment = html.slice(html.indexOf('  <div class="modal-overlay" id="settings-modal-overlay"'), html.indexOf('  <!-- 最近阅读 Modal -->'));
const funcs = ['selectSettingsSection','storageIsInline','openStorageModal','openOfflineCacheManager','selectBulkShortcutModifier','replaceShortcutModifiers','isReservedShortcut'];
(async () => {
 const browser = await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
 try {
 const page = await browser.newPage({viewport:{width:1440,height:900}, reducedMotion:'reduce'});
 await page.route('http://settings.test/', route => route.fulfill({status:200, contentType:'text/html', body:'<html></html>'}));
 await page.goto('http://settings.test/');
 await page.setContent(`<style>${css}</style>${fragment}<script>
 let storageRequestGeneration=0, storageDataCache=null, articleOfflineBrowserCacheBytes=0, shortcutBulkFrom='alt', shortcutBulkTo='meta'; const SHORTCUT_BINDINGS_KEY='test-settings-shortcuts';
 function renderShortcutKeyboard(){} function renderShortcutEditor(){} function renderCauseDictSettings(){} function loadPerformanceDiagnostics(){} function loadBackupManagement(){} function renderAccessUserSettings(){} function searchSettings(){} function renderOfflineCacheManager(){document.getElementById('offline-cache-modal-body').textContent='离线功能内容'} function fetchStorageJson(){return Promise.resolve({})} function renderStorageInfo(){document.getElementById('storage-modal-body').textContent='储存功能内容'} function measureArticleOfflineBrowserCacheBytes(){return Promise.resolve(0)} function escapeHtml(x){return x} function loadShortcutBindings(){return JSON.parse(localStorage.getItem(SHORTCUT_BINDINGS_KEY))}
 ${funcs.map(get).join('\n')}
 document.getElementById('settings-section-storage').addEventListener('settings:opened',()=>openStorageModal(true));document.getElementById('settings-section-offline-cache').addEventListener('settings:opened',()=>openOfflineCacheManager(true));
 </script><script>${accordion}</script>`);
 await page.locator('#settings-modal-overlay').evaluate(el=>el.classList.add('open'));
 await page.evaluate(()=>selectSettingsSection('ai-extensions',false));
 assert.equal(await page.locator('#settings-section-manage .settings-section-head').count(),0);
 assert(await page.getByRole('button',{name:/AI API 管理/}).isVisible());
 await page.evaluate(()=>selectSettingsSection('workspace',false));
 await page.locator('#settings-section-storage .settings-section-head').click();
 await page.getByText('储存功能内容').waitFor();
 assert.equal(await page.locator('#storage-settings-host #storage-modal-body').count(),1);
 assert.equal(await page.locator('#storage-modal-overlay').evaluate(el=>el.style.display),'none');
 await page.evaluate(()=>{document.getElementById('settings-modal-overlay').classList.remove('open'); openStorageModal();});
 assert.equal(await page.locator('#storage-modal-overlay #storage-modal-body').count(),1);
 await page.evaluate(()=>{document.getElementById('storage-modal-overlay').style.display='none'; document.getElementById('settings-modal-overlay').classList.add('open');});
 await page.locator('#settings-section-offline-cache .settings-section-head').click();
 assert.equal(await page.locator('#offline-cache-settings-host #offline-cache-modal-body').innerText(),'离线功能内容');
 await page.emulateMedia({reducedMotion:'no-preference'});
 await page.locator('#settings-section-automated-filing .settings-section-head').click();
 assert(await page.locator('#settings-section-automated-filing').evaluate(el=>el.getAnimations().some(a=>a.playState==='running')));
 await page.evaluate(()=>selectSettingsSection('productivity',false));
 assert.equal(await page.locator('.settings-section.active').first().getAttribute('id'),'settings-section-shortcuts');
 await page.locator('#settings-section-shortcuts .settings-section-head').click();
 await page.waitForTimeout(350);
 const bulk = page.locator('.shortcut-bulk');
 const fromBox=await bulk.locator('.shortcut-bulk-field').first().boundingBox();
 const toBox=await bulk.locator('.shortcut-bulk-field').last().boundingBox();
 assert(Math.abs(fromBox.y-toBox.y)<2 && toBox.x>fromBox.x);
 await page.screenshot({path:'/tmp/stella-shortcuts-layout-desktop.png'});
 await page.setViewportSize({width:600,height:900});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
 await page.screenshot({path:'/tmp/stella-shortcuts-layout-narrow.png'});
 await page.setViewportSize({width:1440,height:900});
 await page.evaluate(()=>localStorage.setItem(SHORTCUT_BINDINGS_KEY, JSON.stringify({w:{actionId:'x',modifiers:['alt']},r:{actionId:'y',modifiers:['alt']},t:{actionId:'z',modifiers:['alt','shift']}})));
 await page.getByRole('button',{name:'应用替换',exact:true}).click();
 const result = await page.evaluate(()=>JSON.parse(localStorage.getItem(SHORTCUT_BINDINGS_KEY)));
 assert.deepEqual(result.w.modifiers,['meta']); assert.deepEqual(result.t.modifiers,['meta','shift']); assert.deepEqual(result.r.modifiers,['meta']);
 assert.match(await page.locator('#shortcut-bulk-status').innerText(),/已替换 3/);
 console.log('settings sections and bulk shortcuts passed');
 } finally {await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
