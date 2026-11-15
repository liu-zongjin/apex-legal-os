const fs = require('fs'), http = require('http'), assert = require('assert');
const { chromium } = require('playwright');
(async () => {
  const many = Array.from({length: 80}, (_, i) => `Person ${i} <person${i}@example.test>`).join(', ');
  const mails = [
    {uid:'1', subject:'长名单', from:'sender@example.test', to:many, cc:many, date:'2026-01-01', read:true},
    {uid:'2', subject:'短名单', from:'sender@example.test', to:'one@example.test', date:'2026-01-01', read:true}
  ];
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://localhost');
    if (url.pathname === '/qq-mail') { res.writeHead(200, {'content-type':'text/html'}); return res.end(fs.readFileSync('frontend/qq-mail.html')); }
    if (url.pathname.startsWith('/static/')) { const file = 'frontend/' + url.pathname.slice(8); if (fs.existsSync(file)) return res.end(fs.readFileSync(file)); res.writeHead(404); return res.end(); }
    let data = {};
    if (url.pathname === '/api/qq-mail/status') data = {connected:true};
    else if (url.pathname === '/api/qq-mail/mails') data = {mails};
    else if (url.pathname === '/api/qq-mail/team-labels') data = {members:[], assignments:{}};
    else if (/\/api\/qq-mail\/mails\/\d+$/.test(url.pathname)) data = {...mails.find(m => m.uid === url.pathname.split('/').pop()), body_text:'邮件正文测试', attachments:[], body_render_version:2};
    res.writeHead(200, {'content-type':'application/json'}); res.end(JSON.stringify(data));
  });
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const browser = await chromium.launch({headless:true, executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const page = await browser.newPage({viewport:{width:1440,height:900}}), errors = [];
  page.on('pageerror', e => errors.push(e.message));
  try {
    await page.goto(`http://127.0.0.1:${server.address().port}/qq-mail?account=netease_exmail`);
    await page.locator('[data-uid="1"] .mail-open').click();
    for (const field of ['to', 'cc']) {
      const value = page.locator(`#detail-${field}`), toggle = page.locator(`#detail-${field}-toggle`);
      await toggle.waitFor({state:'visible'});
      assert.equal(await value.textContent(), many);
      assert.equal(await toggle.getAttribute('aria-expanded'), 'false');
      assert(await value.evaluate(el => el.scrollHeight > el.clientHeight));
      await toggle.click();
      assert.equal(await toggle.getAttribute('aria-expanded'), 'true');
      assert(await value.evaluate(el => el.scrollHeight > el.clientHeight));
      await toggle.click();
    }
    assert(await page.locator('#detail-body-text').isVisible());
    assert(await page.locator('#detail-body-text').evaluate(el => el.getBoundingClientRect().bottom <= innerHeight));
    await page.locator('#detail-to-toggle').click();
    await page.locator('[data-uid="2"] .mail-open').click();
    await page.locator('#detail-to').filter({hasText:'one@example.test'}).waitFor();
    assert.equal(await page.locator('#detail-to-toggle').isVisible(), false);
    assert.equal(await page.locator('#detail-cc-row').isVisible(), false);
    await page.locator('[data-uid="1"] .mail-open').click();
    await page.locator('#detail-to-toggle').waitFor({state:'visible'});
    assert.equal(await page.locator('#detail-to-toggle').getAttribute('aria-expanded'), 'false');
    await page.setViewportSize({width:900,height:700});
    assert.equal(await page.locator('#detail-cc-toggle').isVisible(), true);
    assert.deepEqual(errors, []);
    console.log('Mail recipient and cc collapse, expansion, message switch, and layout passed');
  } finally { await browser.close(); server.close(); }
})().catch(e => {console.error(e); process.exit(1);});
