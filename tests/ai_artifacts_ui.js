const fs = require('fs'), http = require('http'), assert = require('assert');
const {chromium} = require('playwright');
const source = fs.readFileSync('frontend/app.js', 'utf8');
const extract = name => {
  const start = source.indexOf(`function ${name}(`);
  const end = source.indexOf('\n}\n', start) + 3;
  return source.slice(start, end);
};
(async () => {
  const records = new Map(); let saved = 0;
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    const json = data => {res.writeHead(200, {'Content-Type':'application/json'}); res.end(JSON.stringify(data));};
    if (url.pathname.startsWith('/static/')) {
      const path = 'frontend/' + url.pathname.split('/').pop();
      res.writeHead(200, {'Content-Type': path.endsWith('.js') ? 'text/javascript' : 'text/css'});
      res.end(fs.readFileSync(path)); return;
    }
    if (url.pathname.includes('/messages/')) {
      assert.equal(url.searchParams.get('artifact_index'), '0');
      assert.equal(url.searchParams.get('format'), 'html');
      res.writeHead(200, {'Content-Type':'text/html', 'Content-Disposition':"attachment; filename*=UTF-8''square.html"});
      res.end('<!doctype html><html><body>蓝色正方形</body></html>'); return;
    }
    if (url.pathname === '/api/download-center/records' && req.method === 'POST') {
      const row = {id:'1'.repeat(32), name:'生成文件', status:'preparing', category:'ai'};
      records.set(row.id, row); json(row); return;
    }
    const match = url.pathname.match(/\/records\/([^/]+)(\/file)?$/);
    if (match) {
      const row = records.get(match[1]);
      if (req.method === 'PATCH') {
        let text = ''; for await (const data of req) text += data;
        Object.assign(row, JSON.parse(text)); json(row); return;
      }
      if (req.method === 'POST') {
        const chunks=[]; for await (const data of req) chunks.push(data);
        assert(Buffer.concat(chunks).toString().includes('蓝色正方形'));
        saved++; row.status = 'completed'; json(row); return;
      }
      res.writeHead(200, {'Content-Type':'text/html', 'Content-Disposition':'attachment; filename="square.html"'});
      res.end('<!doctype html><html><body>蓝色正方形</body></html>'); return;
    }
    res.writeHead(200, {'Content-Type':'text/html'});
    res.end('<!doctype html><html><meta charset="UTF-8"><body><div class="ask-msg ask-msg-ai"><div class="ask-msg-content" id="cards"></div></div></body></html>');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({headless:true, channel:process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:900}});
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.addStyleTag({path:'frontend/apex-design-tokens.css'});
    await page.addStyleTag({path:'frontend/style.css'});
    await page.addScriptTag({url:'/static/apex-downloads.js'});
    await page.addScriptTag({content:extract('getAskArtifactPresentation')});
    const presentation = await page.evaluate(() => ({
      empty:getAskArtifactPresentation('', []),
      unsupported:getAskArtifactPresentation('原始回答', [{format:'docx', filename:'x.docx', content:'内容', source:'原始回答'}]),
      valid:getAskArtifactPresentation('```md\n正文\n```', [{format:'md',filename:'报告.md',content:'正文',source:'```md\n正文\n```'}])
    }));
    assert(presentation.empty.display.includes('未收到有效回答'));
    assert.equal(presentation.unsupported.display, '原始回答');
    assert.equal(presentation.valid.artifacts.length, 1);
    assert(presentation.valid.display.includes('可下载文件'));
    await page.addScriptTag({content:extract('renderAskArtifacts')+'\nasync '+extract('exportAskAnswer')+'\nasync '+extract('readExportBlob')});
    await page.evaluate(() => {
      window.savedHistory = 0;
      const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200"><rect width="200" height="200" fill="#1E6FD9"/></svg>';
      window.fixture = {id:'anonymous', role:'ai', content:'fixture', artifacts:[
        {index:0,format:'html',filename:'蓝色正方形.html',content:'<!doctype html><html><head><style>body{margin:0;display:grid;place-items:center;height:100vh}.square{width:200px;height:200px;background:#1E6FD9}</style><meta http-equiv="refresh" content="0;url=https://example.invalid/leak"></head><body><div class="square"></div><script>parent.compromised=true</script></body></html>'},
        {index:1,format:'svg',filename:'蓝色正方形.svg',content:svg},
      ]};
      window.loadAskHistory = () => [fixture];
      window.saveAskHistory = async () => {savedHistory++;};
      window.askContext = null;
      window.showToast = text => {window.toast = text;};
      window.renderAskArtifacts(document.getElementById('cards'), fixture);
    });
    assert.equal(await page.locator('.ask-artifact-card').count(), 2);
    assert.equal(await page.locator('iframe').first().getAttribute('sandbox'), '');
    await page.waitForFunction(() => document.querySelector('iframe').contentDocument === null);
    const htmlFrame = page.frames()[1];
    assert.equal(await htmlFrame.locator('script,meta[http-equiv="refresh"]').count(), 0);
    assert.equal(await htmlFrame.locator('.square').evaluate(el => getComputedStyle(el).backgroundColor), 'rgb(30, 111, 217)');
    assert.equal(await page.evaluate(() => window.compromised), undefined);
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', {name:'下载 HTML', exact:true}).click();
    const download = await downloadPromise;
    assert.equal(download.suggestedFilename(), 'square.html');
    assert.equal(fs.readFileSync(await download.path(), 'utf8'), '<!doctype html><html><body>蓝色正方形</body></html>');
    assert.equal(saved, 1);
    assert.equal(await page.evaluate(() => savedHistory), 1);
    fs.mkdirSync('outputs', {recursive:true});
    for (const dark of [false,true]) for (const size of [{width:1440,height:900},{width:1024,height:768}]) {
      await page.setViewportSize(size);
      await page.evaluate(dark => document.body.classList.toggle('dark-mode', dark), dark);
      await page.screenshot({path:`outputs/ai-artifacts-${size.width}-${dark?'dark':'light'}.png`});
    }
    console.log('Artifact preview, isolation, exact HTML download and unified staging passed.');
  } finally {await browser.close();server.close();}
})().catch(error => {console.error(error);process.exit(1);});
