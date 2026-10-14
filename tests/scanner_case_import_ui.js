const fs = require('fs'), path = require('path'), http = require('http'), assert = require('assert');
const { chromium } = require('playwright');
(async () => {
  let requests = [], fail = false;
  const frontend = path.resolve('frontend');
  const json = (res, data, status = 200) => { res.writeHead(status, {'Content-Type':'application/json'}); res.end(JSON.stringify(data)); };
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://fixture');
    if (url.pathname === '/scanner-inbox') { res.writeHead(200, {'Content-Type':'text/html'}); res.end(fs.readFileSync(path.join(frontend, 'scanner-inbox.html'))); return; }
    if (url.pathname.startsWith('/static/')) { const filename = path.join(frontend, path.basename(url.pathname)); if (fs.existsSync(filename)) { res.writeHead(200, {'Content-Type':filename.endsWith('.js')?'application/javascript':'text/css'}); res.end(fs.readFileSync(filename)); return; } }
    if (url.pathname === '/api/scanner-inbox/status') return json(res, {configured:true});
    if (url.pathname === '/api/scanner-inbox/documents') return json(res, {items:[{source_id:'9554',name:'匿名扫描件',pages:3,compression:'JPEG'}]});
    if (url.pathname === '/api/case-manager/case-lookup') return json(res, {items:[{id:1,title:'匿名案件',folder_bound:true}],has_more:false});
    if (url.pathname.endsWith('/folder-binding')) return json(res, {bound:true,available:true,real_path:'/匿名目录/案件'});
    if (url.pathname === '/api/scanner-inbox/import') {
      let body = ''; for await (const chunk of req) body += chunk;
      requests.push(JSON.parse(body));
      await new Promise(resolve => setTimeout(resolve, 250));
      return fail ? json(res, {detail:'案件文件夹当前不可用'}, 409) : json(res, {ok:true,items:[{source_id:'9554',path:'/匿名目录/案件/#下载材料/扫描.pdf'}]});
    }
    json(res, {}, 404);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({headless:true,channel:process.env.STELLA_UI_BROWSER || 'chrome'});
    const page = await browser.newPage({viewport:{width:1440,height:900}}), errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('http://127.0.0.1:'+server.address().port+'/scanner-inbox');
    await page.locator('input[data-source="9554"]').check();
    await page.click('#import-case');
    assert((await page.textContent('#case-status')).includes('请先搜索并选择案件'));
    assert.equal(requests.length, 0);
    await page.fill('#case-search', '匿名案件');
    await page.locator('#case-results button').filter({hasText:'匿名案件'}).first().click();
    await page.waitForFunction(() => document.querySelector('#case-status').textContent.includes('#下载材料'));
    await page.click('#import-case');
    assert(await page.locator('#import-case').isDisabled());
    await page.evaluate(() => importCase());
    await page.waitForFunction(() => document.querySelector('#case-status').textContent.includes('已将 1 个 PDF 保存到'));
    assert.equal(requests.length, 1);
    assert.deepEqual(requests[0].source_ids, ['9554']);
    assert.equal(requests[0].case_id, 1);
    assert.equal(requests[0].destination, 'case');
    fail = true;
    await page.locator('input[data-source="9554"]').check();
    await page.click('#import-case');
    await page.waitForFunction(() => document.querySelector('#case-status').textContent.includes('案件文件夹当前不可用'));
    assert(!(await page.locator('#import-case').isDisabled()));
    assert.deepEqual(errors, []);
    await page.setViewportSize({width:1024,height:768});
    await page.evaluate(() => document.documentElement.classList.add('dark-mode'));
    assert(await page.locator('#case-search').isVisible());
    console.log('Scanner case import UI: passed');
  } finally { if (browser) await browser.close(); await new Promise(resolve => server.close(resolve)); }
})().catch(error => { console.error(error); process.exitCode = 1; });
