// Anonymous fixture; never contacts the live service or deletes real files.
const fs = require('fs');
const assert = require('assert/strict');
const { chromium } = require(process.env.STELLA_PLAYWRIGHT_MODULE || 'playwright');
const source = fs.readFileSync('frontend/app.js', 'utf8');
(async () => {
 const browser = await chromium.launch({headless:true,channel:'chrome'});
 const page = await browser.newPage({viewport:{width:1440,height:900}});
 const errors=[]; page.on('pageerror',e=>errors.push(e.message));
 await page.setContent('<button id="opener">明细</button><div id="storage-modal-body"></div>');
 for (const path of ['frontend/apex-design-tokens.css','frontend/style.css']) await page.addStyleTag({content:fs.readFileSync(path,'utf8')});
 await page.evaluate(()=>{
  window.escapeHtml = value => String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  window.storageDataCache={items:[{raw:'review_artifacts',name:'界面验收截图',size_fmt:'2.8 MB',desc:'开发验收生成的页面截图，不参与应用运行',files:[{name:'data/dossier-ui-review/completed-1440-light.png',size_fmt:'1.4 MB',cleanable:true},{name:'data/dossier-ui-review/completed-1440-dark.png',size_fmt:'1.4 MB',cleanable:true}]},{raw:'ai_runtime',name:'AI 接口运行程序',desc:'本地接口调用所需，请保留',size_fmt:'457.2 MB',files:[{name:'data/cc2api-runtime/bin/claude',size_fmt:'228.6 MB',cleanable:false}]}]};
  window.requests=[];window.fetchStorageJson=async(url,options)=>{requests.push(JSON.parse(options.body));return {ok:true,message:'已清理'};};
  window.refreshStorageAfterCleanup=msg=>window.refreshed=msg;
 });
 await page.addScriptTag({content:source.slice(source.indexOf('function showStorageFileDetails('),source.indexOf('function showHistoryBackupsModal('))});
 await page.locator('#opener').focus();await page.evaluate(()=>showStorageFileDetails('review_artifacts'));
 for(const width of [1440,1024,390])for(const dark of [false,true]){
  await page.setViewportSize({width,height:900});await page.evaluate(d=>document.body.classList.toggle('dark-mode',d),dark);
  const box=await page.getByRole('dialog').boundingBox();assert(box.x>=0 && box.x+box.width<=width);
  assert(await page.getByRole('dialog').evaluate(el=>el.scrollWidth<=el.clientWidth));
  if(width===1440)await page.screenshot({path:`/tmp/storage-breakdown-${dark?'dark':'light'}.png`});
 }
 await page.locator('input').first().check();await page.locator('#storage-detail-delete').click();
 assert.equal(await page.evaluate(()=>requests.length),0);
 await page.locator('input').last().check();await page.locator('#storage-detail-delete').click();
 assert.equal(await page.evaluate(()=>requests.length),0);
 await page.locator('#storage-detail-delete').click();
 assert.deepEqual(await page.evaluate(()=>requests),[{type:'review_artifact_files',paths:['data/dossier-ui-review/completed-1440-light.png','data/dossier-ui-review/completed-1440-dark.png']}]);
 assert.equal(await page.locator('#storage-file-details').count(),0);
 await page.evaluate(()=>showStorageFileDetails('ai_runtime'));
 assert.equal(await page.locator('input').count(),0);assert.equal(await page.locator('#storage-detail-delete').count(),0);
 await page.keyboard.press('Escape');assert.equal(await page.locator('#storage-file-details').count(),0);
 assert.deepEqual(errors,[]);await browser.close();console.log('Storage details: light/dark, 3 widths, selection, confirmation reset, protected files and Escape passed');
})().catch(error=>{console.error(error);process.exit(1);});
