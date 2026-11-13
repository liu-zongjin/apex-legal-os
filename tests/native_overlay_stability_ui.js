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
   await context.close();
  }
  console.log(`${name} native overlays and browser control passed`);
 } finally {await browser.close();}
}
(async()=>{await check(chromium,'chromium');await check(webkit,'webkit')})().catch(e=>{console.error(e);process.exitCode=1});
