const fs = require('fs'), path = require('path'), assert = require('assert');
const {chromium} = require(process.env.STELLA_PLAYWRIGHT_MODULE || 'playwright');
const acorn = require('acorn');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root,'frontend/index.html'),'utf8');
const css = fs.readFileSync(path.join(root,'frontend/style.min.css'),'utf8');
const app = fs.readFileSync(path.join(root,'frontend/app.js'),'utf8');
const worker = fs.readFileSync(path.join(root,'frontend/case-manager-sw.js'),'utf8');
for (const file of ['style.min.css','app-bootstrap.js']) { const asset = html.match(new RegExp('/static/' + file.replace('.', '\\.') + '\\?v=[a-zA-Z0-9]+'))?.[0]; assert(asset && worker.includes(asset), `${file} must use the same version in page and offline cache`); }
assert(css.includes('.settings-quick-actions')); 
const tree = acorn.parse(app,{ecmaVersion:'latest'});
const get = name => { const n=tree.body.find(n=>n.type==='FunctionDeclaration' && n.id.name===name); assert(n); return app.slice(n.start,n.end); };
const fragment=html.slice(html.indexOf('  <div class="modal-overlay" id="settings-modal-overlay"'),html.indexOf('  <!-- 储存管理 Modal -->'));
(async()=>{
 const browser=await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
 try { for (const [width, dark] of [[1440,false],[1024,false],[1440,true],[390,false]]) { const page=await browser.newPage({viewport:{width,height:900}}); const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.setContent(`<style>${css}</style>${fragment}<script>function renderShortcutKeyboard(){} function renderCauseDictSettings(){} function loadPerformanceDiagnostics(){} function loadBackupManagement(){} function renderAccessUserSettings(){} function openUserManualFromSettings(){window.manualOpened=true} ${get('selectSettingsSection')} ${get('searchSettings')}</script>`);
 await page.locator('#settings-modal-overlay').evaluate(e=>e.classList.add('open')); if (dark) await page.evaluate(()=>document.body.classList.add('dark-mode')); await page.waitForTimeout(300); await page.screenshot({path:`/tmp/stella-settings-review-${width}-${dark}.png`});
 await page.locator('#settings-search').fill('邮箱');
 assert(await page.locator('#settings-search-results button').filter({hasText:'邮箱配置'}).count()); assert.equal(await page.locator('#settings-section-manage').isVisible(),false); assert((await page.locator('#settings-search').boundingBox()).height >= 40);
 await page.locator('#settings-search-results button').filter({hasText:'邮箱配置'}).first().click();
 assert.equal(await page.locator('[data-settings-section="workspace"]').getAttribute('aria-current'),'page');
 assert.equal(await page.locator('#settings-search').inputValue(),'');
 await page.locator('#settings-search').fill('页面休眠'); assert(await page.locator('#settings-search-results button').filter({hasText:'智能页面休眠'}).count());
 await page.locator('#settings-search').fill('备计');
 assert(await page.locator('#settings-search-results button').filter({hasText:'自动备份计划'}).count());
 await page.locator('#settings-search-results button').filter({hasText:'自动备份计划'}).first().click();
 assert.equal(await page.locator('[data-settings-section="backup"]').getAttribute('aria-current'),'page');
 await page.locator('#settings-search').fill('无匹配关键词xyz'); assert.match(await page.locator('#settings-search-results').innerText(),/没有找到/);
 await page.locator('#settings-search').fill(''); assert.equal(await page.locator('#settings-search-results').isVisible(),false);
 await page.locator('.settings-manual-shortcut').click();assert(await page.evaluate(()=>window.manualOpened));
 await page.locator('[data-settings-section="workspace"]').click(); assert.equal(await page.locator('.cause-dict-details').getAttribute('open'),null);
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth+1),true);
 assert.deepEqual(errors,[]); await page.close(); }
 console.log('settings search: desktop and narrow viewport passed');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
