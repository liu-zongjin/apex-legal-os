// Anonymous, isolated browser regression for retained mailbox tabs.
const fs = require('fs'), path = require('path'), http = require('http'), assert = require('assert');
const { chromium } = require('playwright');

(async () => {
  const frontend = path.resolve('frontend');
  const row = (uid, date) => ({ uid, date, from: 'sender@example.test', subject: '测试邮件 ' + uid, read: true });
  let mails = Array.from({ length: 30 }, (_, i) => row(String(100 - i), '2026-10-19 09:00'));
  let requests = 0, failure = false, release = null, hold = false;
  let detailRelease = null, holdDetail = false;
  const detail = row('103', '2026-10-20 16:00');
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    const json = (body, status = 200) => { res.writeHead(status, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(body)); };
    if (url.pathname === '/qq-mail') {
      res.writeHead(200, { 'Content-Type': 'text/html' });
      return res.end(fs.readFileSync(process.env.MAIL_SYNC_HTML || path.join(frontend, 'qq-mail.html')));
    }
    if (url.pathname.startsWith('/static/')) {
      const file = path.join(frontend, path.basename(url.pathname));
      if (!fs.existsSync(file)) { res.writeHead(404); return res.end(); }
      res.writeHead(200, { 'Content-Type': file.endsWith('.js') ? 'text/javascript' : 'text/css' });
      return res.end(fs.readFileSync(file));
    }
    if (url.pathname === '/api/qq-mail/mails') {
      requests++;
      if (hold) await new Promise(resolve => { release = resolve; });
      return failure ? json({ detail: '测试连接中断' }, 502) : json({ mails });
    }
    if (url.pathname === '/api/qq-mail/team-labels') return json({ members: [], assignments: {} });
    if (url.pathname === '/api/qq-mail/mails/103') {
      if (holdDetail) await new Promise(resolve => { detailRelease = resolve; });
      return json({ ...detail, body_text: '匿名正文', body_render_version: 2, attachments: [] });
    }
    if (url.pathname === '/api/qq-mail/status') return json({ ok: true, total: mails.length, latency_ms: 10 });
    return json({});
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const visible = active => page.evaluate(active => window.postMessage({ type: 'apex:page-visibility', version: 1, active }, location.origin), active);
  const synced = () => page.waitForFunction(() => document.getElementById('cache-hint').textContent.startsWith('已同步'));
  try {
    await page.clock.install();
    await page.addInitScript(() => {
      // Reminder-opened detail plus an older complete orphan: neither was indexed.
      localStorage.setItem('qqmail_cache_v2_netease_exmail_inbox', JSON.stringify({
        mails: { '100': { _detail: { subject: '先读正文' } }, '99': { uid: '99', subject: '已缓存摘要', date: '2026-10-19 09:00' } }, order: []
      }));
    });
    await page.goto(`http://127.0.0.1:${server.address().port}/qq-mail?account=netease_exmail`);
    // Check recovery before any lifecycle sync: manual refresh used to leave both hidden.
    await page.waitForFunction(() => !document.getElementById('cache-hint').textContent.includes('正在'));
    assert.equal(await page.locator('.mail-item').count(), 30, 'existing cached mails must regain missing list entries');
    await synced();
    assert.equal(requests, 1);
    mails.unshift(row('101', '2026-10-20 12:40'));
    await page.clock.fastForward(60000);
    await page.locator('[data-uid="101"]').waitFor();
    assert.equal(await page.locator('.mail-item').first().getAttribute('data-uid'), '101');

    await visible(false);
    const beforeHidden = requests;
    mails.unshift(row('102', '2026-10-20 15:53'));
    await page.clock.fastForward(180000);
    assert.equal(requests, beforeHidden, 'inactive tabs must not poll');
    await visible(true);
    await page.locator('[data-uid="102"]').waitFor();
    assert.equal(await page.locator('.mail-item').first().getAttribute('data-uid'), '102');

    await page.locator('#mail-list').evaluate(list => { list.scrollTop = 140; });
    await page.clock.fastForward(60000);
    await synced();
    assert.equal(await page.locator('#mail-list').evaluate(list => list.scrollTop), 140);

    failure = true;
    await page.locator('#refresh-btn').click();
    await page.locator('#cache-hint').filter({ hasText: '同步失败' }).waitFor();
    assert.equal(await page.locator('.mail-item').count(), 32, 'failed sync must preserve cached mail');
    failure = false;
    hold = true;
    await page.clock.fastForward(60000);
    await page.waitForFunction(() => document.getElementById('cache-hint').textContent.includes('正在检查'));
    const beforeHeld = requests;
    await page.clock.fastForward(120000);
    assert.equal(requests, beforeHeld, 'automatic sync must not overlap');
    hold = false;
    release();
    await synced();

    // A reminder can open mail outside the loaded summary window. Its delayed
    // detail must merge with, rather than overwrite, a more recent list sync.
    holdDetail = true;
    await page.evaluate(() => window.postMessage({ type: 'openHomeReminderMail', uid: '103' }, location.origin));
    await page.waitForRequest(request => request.url().includes('/api/qq-mail/mails/103'));
    mails.unshift(row('104', '2026-10-20 16:30'));
    await page.locator('#refresh-btn').click();
    await page.locator('[data-uid="104"]').waitFor();
    holdDetail = false;
    detailRelease();
    await page.locator('#detail-subject').filter({ hasText: '测试邮件 103' }).waitFor();
    await page.locator('#refresh-btn').click();
    await synced();
    await page.locator('[data-uid="103"]').waitFor();
    assert.equal(await page.locator('.mail-item').first().getAttribute('data-uid'), '104');
    assert.equal(await page.locator('.mail-item').count(), 34);
    assert.deepEqual(errors, []);
    console.log('Mailbox sync: orphan recovery, detail/list race, initial, periodic, resume, inactive pause, scroll, failure cache, no overlap passed');
  } finally {
    if (release) release();
    if (detailRelease) detailRelease();
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
