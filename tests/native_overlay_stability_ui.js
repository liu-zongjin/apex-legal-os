const fs=require('fs'), path=require('path'), assert=require('assert');
const {chromium,webkit}=require(process.env.STELLA_PLAYWRIGHT_MODULE||'playwright');
const script=fs.readFileSync(path.join(__dirname,'../frontend/native-overlay-stability.js'),'utf8');
async function check(engine,name){
 let browser;
 try { browser=await engine.launch(name==='chromium'?{executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true}:{headless:true}); }
 catch(e){if(name==='webkit' && /Executable doesn't exist/.test(e.message)){console.log('WebKit runtime unavailable');return;} throw e;}
 try {
  for (const native of [true,false]) {
   const context=await browser.newContext({userAgent:'Mozilla/5.0 AppleWebKit/605.1.15'+(native?' LegalKB-NativeShell':''),viewport:{width:1280,height:800}});
   const page=await context.newPage();
   await page.setContent(`<style>.modal-overlay,.open-pages-overview,.drawer-mask,.drawer-backdrop,.court-link-modal,.panel{backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px)}</style><div class="modal-overlay"></div><div class="open-pages-overview"></div><div class="panel"></div><div class="drawer-backdrop"></div><div class="court-link-modal"></div><script>${script}</script><iframe srcdoc="<style>.drawer-mask {backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px)}</style><div class='drawer-mask'></div>"></iframe>`);
   const iframe=page.frameLocator('iframe'); await iframe.locator('.drawer-mask').waitFor({state:'attached'});
   if(native) await iframe.locator('#stella-native-overlay-stability').waitFor({state:'attached'});
   const read=sel=>page.locator(sel).evaluate(el=>getComputedStyle(el).backdropFilter);
   const main=await read('.modal-overlay'), overview=await read('.open-pages-overview'), panel=await read('.panel');
   const framed=await iframe.locator('.drawer-mask').evaluate(el=>getComputedStyle(el).backdropFilter);
   assert.equal(main,native?'none':'blur(6px)'); assert.equal(overview,native?'none':'blur(6px)'); assert.equal(framed,native?'none':'blur(6px)'); assert.equal(panel,'blur(6px)'); assert.equal(await read('.drawer-backdrop'),native?'none':'blur(6px)'); assert.equal(await read('.court-link-modal'),native?'none':'blur(6px)');
   if (native) {
    const fixture = `
      <style>
        .modal-overlay, .drawer-mask { position: fixed; inset: 0; background-color: rgba(24, 30, 40, .5); --stella-overlay-blur: 8px }
        [hidden] { display: none !important }
        iframe { position: absolute; top: 100px; left: 200px; width: 600px; height: 400px; border: 0 }
      </style>
      <div class="modal-overlay" hidden></div>
      <iframe srcdoc="<style>.drawer-mask{position:fixed;inset:0;--stella-overlay-blur:8px}[hidden]{display:none}</style><div class='drawer-mask' hidden></div>"></iframe>
    `;
    await page.addInitScript(() => {
     if (window === window.top) {
      window.snapshots = [];
      window.snapshotReplies = [];
     }
     window.webkit = {messageHandlers:{overlayBackdrop:{postMessage: region => {
      const mask = document.querySelector('[data-stella-overlay-pending]');
      window.top.snapshots.push({...region, maskOpacity: getComputedStyle(mask).opacity});
      return new Promise(resolve => window.top.snapshotReplies.push(resolve));
     }}}};
    });
    await page.route('http://overlays.test/', route => route.fulfill({
     contentType: 'text/html', body: fixture + `<script>${script}</script>`
    }));
    await page.goto('http://overlays.test/');
    const mask = page.locator('.modal-overlay');
    const image = 'data:image/jpeg;base64,/9j/2Q==';
    const open = el => { el.hidden = false; };
    const close = el => { el.hidden = true; };
    await mask.evaluate(open);
    await mask.evaluate(el => el.classList.add('unrelated'));
    assert.deepEqual(await page.evaluate(() => snapshots), [
     {x:0, y:0, width:1, height:1, blur:8/1280, maskOpacity:'0'}
    ]);
    await page.evaluate(value => snapshotReplies.shift()(value), image);
    await mask.locator('xpath=self::*[@data-stella-overlay-snapshot]').waitFor({state:'attached'});
    assert((await mask.evaluate(el => getComputedStyle(el).backgroundImage)).includes(image));
    await mask.evaluate(close);
    assert.equal(await mask.getAttribute('data-stella-overlay-snapshot'), null);

    await mask.evaluate(open);
    await mask.evaluate(close);
    await page.evaluate(value => snapshotReplies.shift()(value), image);
    assert.equal(await mask.getAttribute('data-stella-overlay-snapshot'), null);
    await mask.evaluate(open);
    await mask.waitFor({state:'visible'});
    await page.waitForFunction(() => !document.querySelector('[data-stella-overlay-pending]'));
    await page.evaluate(value => snapshotReplies.shift()(value), image);
    assert.equal(await mask.getAttribute('data-stella-overlay-snapshot'), null);
    await mask.evaluate(close);

    const inner = page.frameLocator('iframe').locator('.drawer-mask');
    await inner.evaluate(open);
    const crop = await page.evaluate(() => snapshots.at(-1));
    assert.deepEqual(crop, {x:200/1280, y:100/800, width:600/1280, height:400/800, blur:8/600, maskOpacity:'0'});
    await page.evaluate(value => snapshotReplies.shift()(value), image);
    await inner.locator('xpath=self::*[@data-stella-overlay-snapshot]').waitFor({state:'attached'});
    await page.locator('iframe').evaluate(close);
    assert.equal(await inner.getAttribute('data-stella-overlay-snapshot'), null);
   }
   await context.close();
  }
  console.log(`${name} native overlays and browser control passed`);
 } finally {await browser.close();}
}
(async()=>{await check(chromium,'chromium');await check(webkit,'webkit')})().catch(e=>{console.error(e);process.exitCode=1});
