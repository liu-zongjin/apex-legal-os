const fs = require('fs'), path = require('path'), http = require('http'), assert = require('assert');
const { chromium, webkit } = require('playwright');
(async () => {
  let requests = [], downloads = [], fail = false;
  const records = new Map(), delay = ms => new Promise(resolve => setTimeout(resolve, ms));
  const progress = (res, stage, details = {}) => res.write(`data: ${JSON.stringify({stage, ...details})}\n\n`);
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
      assert.equal(req.headers.accept, 'text/event-stream');
      res.writeHead(200, {'Content-Type':'text/event-stream'});
      progress(res, 'check_case');
      await delay(250);
      if (fail) progress(res, 'error', {detail:'案件文件夹当前不可用'});
      else progress(res, 'result', {result:{ok:true,items:[{source_id:'9554',path:'/匿名目录/案件/#下载材料/扫描.pdf'}]}});
      return res.end();
    }
    if (url.pathname === '/api/scanner-inbox/download') {
      let body = ''; for await (const chunk of req) body += chunk;
      const data = JSON.parse(body); downloads.push(data);
      assert.equal(req.headers.accept, 'text/event-stream');
      res.writeHead(200, {'Content-Type':'text/event-stream'});
      const file = {source_id:'9554',completed:0,total:1};
      progress(res, 'convert', file);
      await delay(350);
      if (fail) { progress(res, 'error', {detail:'扫描盘连接中断'}); return res.end(); }
      progress(res, 'read', file);
      await delay(200);
      progress(res, 'retrieved', {...file,completed:1});
      if (data.mode === 'zip') {
        progress(res, 'pack', file);
        await delay(300);
      }
      const name = data.mode==='zip'?'Stella扫描件.zip':'匿名扫描.pdf';
      progress(res, 'result', {result:{files:[{name,url:'/api/scanner-inbox/download-file/fixture'}]}});
      return res.end();
    }
    if (url.pathname === '/api/scanner-inbox/download-file/fixture') {
      res.writeHead(200, {'Content-Type':'application/octet-stream','Content-Length':'16384'});
      res.write(Buffer.alloc(4096)); await delay(550); return res.end(Buffer.alloc(12288));
    }
    if (url.pathname.startsWith('/api/download-center/records')) {
      let body = ''; for await (const chunk of req) body += chunk;
      const values = (req.headers['content-type']||'').includes('application/json')?JSON.parse(body):{};
      const [,id,action] = url.pathname.match(/records(?:\/([^/]+)(?:\/(.+))?)?$/);
      if (!id) {
        const task={id:String(records.size+1),...values,status:'preparing'};
        records.set(task.id,task);return json(res,task);
      }
      const task=records.get(id);
      if(req.method==='PATCH')return json(res,Object.assign(task,values));
      if(action==='file'&&req.method==='GET'){
        res.writeHead(200,{'Content-Type':'application/octet-stream','Content-Length':'16384'});
        return res.end(Buffer.alloc(16384));
      }
      if(action==='file'){
        const native=url.searchParams.has('await_native');
        return json(res,Object.assign(task,{status:native?'saving':'completed',path:'/fixture',
          phase:native?'正在打开系统保存窗口':'文件已就绪',received_bytes:native?0:16384,total_bytes:16384}));
      }
      if(action==='native-saved'){
        return json(res,Object.assign(task,{status:'completed',phase:'已保存到所选位置',path:values.path}));
      }
    }
    json(res, {}, 404);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = process.env.STELLA_UI_BROWSER==='webkit'?await webkit.launch():
      await chromium.launch({headless:true,channel:process.env.STELLA_UI_BROWSER || 'chrome'});
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
    assert(await page.locator('#transfer-progress').isVisible());
    assert.equal(await page.getAttribute('#transfer-track','aria-valuenow'), null);
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
    assert.equal(await page.getAttribute('#transfer-progress','data-state'), 'error');
    fail = false;
    await page.click('#download');
    assert(await page.locator('#transfer-progress').isVisible());
    assert.equal(await page.getAttribute('#transfer-progress','aria-busy'), 'true');
    for (const id of ['download','send-ai','import-case']) assert(await page.locator('#'+id).isDisabled());
    await page.evaluate(() => downloadSelected());
    await page.screenshot({path:'/tmp/scanner-progress-light.png'});
    await page.waitForFunction(() => document.querySelector('#transfer-label').textContent.includes('请求打印机生成 PDF'));
    assert.equal(await page.getAttribute('#transfer-track','aria-valuenow'), '0');
    await page.waitForFunction(() => document.querySelector('#transfer-label').textContent.includes('生成压缩包'));
    await page.waitForFunction(() => document.querySelector('#transfer-track').getAttribute('aria-valuenow')==='25');
    await page.waitForFunction(() => document.querySelector('#transfer-progress').dataset.state === 'handed-off');
    assert.equal(downloads.length, 1);
    assert((await page.textContent('#transfer-label')).includes('已交给浏览器保存'));
    assert.equal(await page.getAttribute('#transfer-track','aria-valuenow'), null);
    await page.locator('input[data-source="9554"]').check();
    await page.selectOption('#download-mode','files');
    await page.click('#download');
    await page.waitForFunction(() => document.querySelector('#transfer-progress').dataset.state === 'handed-off');
    assert.equal(downloads.length, 2);
    assert.equal(downloads[1].mode, 'files');
    await page.locator('input[data-source="9554"]').check();
    fail = true;
    await page.setViewportSize({width:1024,height:768});
    await page.evaluate(() => { document.documentElement.classList.add('dark-mode'); document.body.classList.add('dark-mode'); });
    await page.click('#download');
    await page.screenshot({path:'/tmp/scanner-progress-dark.png'});
    await page.waitForFunction(() => document.querySelector('#transfer-progress').dataset.state === 'error');
    assert((await page.textContent('#transfer-label')).includes('扫描盘连接中断'));
    assert((await page.textContent('#transfer-detail')).includes('正在请求打印机生成 PDF'));
    assert.equal(await page.getAttribute('#transfer-track','aria-valuenow'), '0');
    assert(!(await page.locator('#download').isDisabled()));
    assert.equal(await page.getAttribute('#transfer-progress','aria-busy'), 'false');
    await page.emulateMedia({reducedMotion:'reduce'});
    assert.equal(await page.locator('#transfer-track').evaluate(el => getComputedStyle(el,'::after').animationName), 'none');
    await page.evaluate(() => window.postMessage({type:'apex:page-visibility',version:1,active:false},location.origin));
    await page.waitForFunction(() => document.documentElement.classList.contains('apex-page-inactive'));
    assert.deepEqual(errors, []);
    await page.setViewportSize({width:1024,height:768});
    await page.evaluate(() => { document.documentElement.classList.add('dark-mode'); document.body.classList.add('dark-mode'); });
    assert(await page.locator('#case-search').isVisible());
    fail = false;
    const nativePage = await browser.newPage({userAgent:'LegalKB-NativeShell'});
    await nativePage.goto('http://127.0.0.1:'+server.address().port+'/scanner-inbox');
    await nativePage.evaluate(() => {
      const click=HTMLAnchorElement.prototype.click;
      HTMLAnchorElement.prototype.click=function(){
        if(this.href.includes('/api/download-center/records/')){
          window.nativeSave={id:this.href.split('/').at(-2),url:this.href,name:this.download};
          return;
        }
        return click.call(this);
      };
      window.nativeStage=(status,values={})=>ApexDownloads.nativeEvent({...window.nativeSave,status,...values});
    });
    await nativePage.locator('input[data-source="9554"]').check();
    await nativePage.click('#download');
    await nativePage.waitForFunction(() => window.nativeSave);
    await nativePage.evaluate(() => nativeStage('preparing'));
    assert((await nativePage.textContent('#transfer-label')).includes('等待选择系统保存位置'));
    assert.equal(await nativePage.getAttribute('#transfer-track','aria-valuenow'), null);
    assert.equal(await nativePage.getAttribute('#apex-download-progress .ad-track','aria-valuenow'), null);
    assert(await nativePage.locator('#download').isDisabled());
    await nativePage.evaluate(() => nativeStage('downloading',{received_bytes:8192,total_bytes:16384}));
    assert.equal(await nativePage.getAttribute('#transfer-track','aria-valuenow'), '50');
    assert.equal(await nativePage.getAttribute('#apex-download-progress .ad-track','aria-valuenow'), '50');
    await nativePage.evaluate(() => nativeStage('completed',{path:'/fixture/zip'}));
    await nativePage.waitForFunction(() => document.querySelector('#transfer-progress').dataset.state==='done');
    assert.equal(await nativePage.getAttribute('#transfer-track','aria-valuenow'), '100');
    await nativePage.waitForFunction(() => !document.querySelector('#select-all').checked && !document.querySelector('input[data-source]').checked);
    await nativePage.locator('input[data-source="9554"]').check();
    await nativePage.selectOption('#download-mode','files');
    await nativePage.evaluate(() => { window.nativeSave=null; });
    await nativePage.click('#download');
    await nativePage.waitForFunction(() => window.nativeSave);
    await nativePage.evaluate(async () => { await nativeStage('preparing'); await nativeStage('failed',{error:'已取消'}); });
    await nativePage.waitForFunction(() => document.querySelector('#transfer-progress').dataset.state==='cancelled');
    assert.equal(await nativePage.getAttribute('#transfer-track','aria-valuenow'), null);
    console.log('Scanner case import UI: passed');
  } finally { if (browser) await browser.close(); await new Promise(resolve => server.close(resolve)); }
})().catch(error => { console.error(error); process.exitCode = 1; });
