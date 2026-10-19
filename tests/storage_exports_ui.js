const fs=require('fs'),assert=require('assert/strict');
const {chromium}=require(process.env.STELLA_PLAYWRIGHT_MODULE || 'playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 const page=await browser.newPage({viewport:{width:1440,height:900}});
 await page.setContent('<button id="open">打开</button>');
 await page.addStyleTag({content:fs.readFileSync('frontend/style.css','utf8')});
 await page.evaluate(()=>{
  window.escapeHtml=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  window.requests=[];window.refreshStorageAfterCleanup=()=>{};
  window.fetchStorageJson=async(url,options)=>{
   if(options){requests.push(JSON.parse(options.body));return{ok:true,message:'已清理所选文件'};}
   return{files:Array.from({length:123},(_,i)=>({name:`public-preview/app/file-${i}.txt`,size:1024,size_fmt:'1 KB',purpose:'公开版打包、发布与验证产物',modified:'2026-10-19 12:00:00',revision:`rev${i}`}))};
  };
 });
 const source=fs.readFileSync('frontend/app.js','utf8');
 await page.addScriptTag({content:source.slice(source.indexOf('async function showExportFilesModal('),source.indexOf('function showStorageFileDetails('))});
 await page.evaluate(()=>showExportFilesModal());
 assert.equal(await page.locator('.storage-export-row').count(),50);
 await page.locator('[data-action="next"]').click();await page.locator('[data-action="next"]').click();
 assert.equal(await page.locator('.storage-export-row').count(),23);
 await page.locator('input[type="search"]').fill('file-122.txt');assert.equal(await page.locator('.storage-export-row').count(),1);
 await page.locator('input[type="checkbox"]').check();await page.locator('[data-action="delete"]').click();
 assert.equal(await page.evaluate(()=>requests.length),0);
 await page.locator('input[type="search"]').fill('file-121.txt');await page.locator('input[type="checkbox"]').check();
 await page.locator('[data-action="delete"]').click();assert.equal(await page.evaluate(()=>requests.length),0);
 await page.locator('[data-action="delete"]').click();
 assert.deepEqual((await page.evaluate(()=>requests))[0].files.map(f=>f.name),['public-preview/app/file-121.txt','public-preview/app/file-122.txt']);
 for(const width of [1440,1024,390])for(const dark of [false,true]){
  await page.setViewportSize({width,height:900});await page.evaluate(d=>document.body.classList.toggle('dark-mode',d),dark);
  await page.locator('input[type="search"]').fill('');
  const dialog=page.getByRole('dialog');const box=await dialog.boundingBox();assert(box.x>=0&&box.x+box.width<=width);
  assert(await dialog.evaluate(e=>e.scrollWidth<=e.clientWidth));
  await page.screenshot({path:`/tmp/stella-exports-${width}-${dark?'dark':'light'}.png`});
 }
 const download=page.waitForEvent('download');await page.locator('[data-action="csv"]').click();
 const item=await download;assert.equal(item.suggestedFilename(),'Stella导出文件完整清单.csv');
 const content=fs.readFileSync(await item.path(),'utf8');assert(content.includes('file-122.txt'));assert.equal(content.split('\r\n').length,124);
 await page.keyboard.press('Escape');assert.equal(await page.getByRole('dialog').count(),0);
 await browser.close();console.log('Export inventory pagination, full search/CSV, selection, confirmation reset, cleanup and 6 visual states passed');
})().catch(e=>{console.error(e);process.exit(1)});
