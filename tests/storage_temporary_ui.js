// Anonymous fixture, mocked cleanup only. Never deletes local application data.
const fs = require('fs');
const assert = require('assert/strict');
const {chromium} = require(process.env.STELLA_PLAYWRIGHT_MODULE || 'playwright');
const source = fs.readFileSync('frontend/app.js','utf8');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 const page=await browser.newPage({viewport:{width:1440,height:900}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.setContent('<button id="opener">明细</button>');
 for(const name of ['frontend/apex-design-tokens.css','frontend/style.css'])await page.addStyleTag({content:fs.readFileSync(name,'utf8')});
 await page.evaluate(()=>{
  window.escapeHtml=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  window.formatStorageBytes=n=>(n/1024/1024).toFixed(1)+' MB';
  const row=(name,level,size,revision)=>({name,title:level==='keep'?'回滚、数据或敏感文件':'应用打包副本',group:'build',recommendation:level==='keep'?'建议保留：需要单独核对用途。':level==='priority'?'优先清理：旧轮次打包副本。':'建议暂留：当前目录中最新候选包。',impact:'删除本地副本；需要时重新打包。',level,cleanable:level!=='keep',size,disk_size:size,count:1200,modified_at:1792486800,size_fmt:(size/1024/1024).toFixed(1)+' MB',disk_size_fmt:(size/1024/1024).toFixed(1)+' MB',revision});
  window.storageDataCache={items:[{raw:'temp_files',temporary_items:[row('.tmp/public-update-package-20261020-final','optional',967494253,'final'),row('.tmp/public-update-package-20261020-r2','priority',967475868,'r2'),row('.tmp/system-messages-before.sql','keep',200,'sql'),...Array.from({length:45},(_,i)=>row('.tmp/unknown-'+i+'-long-directory-name-for-test','keep',100,'keep'+i))]}]};
  window.requests=[];window.fetchStorageJson=async(url,options)=>{requests.push(JSON.parse(options.body));return{ok:true,message:'已清理所选项目'};};
  window.refreshStorageAfterCleanup=msg=>window.refreshed=msg;
 });
 await page.addScriptTag({content:source.slice(source.indexOf('function showTemporaryFilesModal('),source.indexOf('function showStorageFileDetails('))});
 await page.locator('#opener').focus();await page.evaluate(()=>showTemporaryFilesModal());
 assert.equal(await page.locator('input:checked').count(),0);
 assert.equal(await page.locator('input[type="checkbox"]').count(),2);
 assert.equal(await page.locator('.storage-temporary-row').count(),40);
 for(const width of [1440,1024,390])for(const dark of [false,true]){
  await page.setViewportSize({width,height:900});await page.evaluate(d=>document.body.classList.toggle('dark-mode',d),dark);
  const box=await page.getByRole('dialog').boundingBox();assert(box.x>=0&&box.x+box.width<=width);
  assert(await page.getByRole('dialog').evaluate(e=>e.scrollWidth<=e.clientWidth));
  if(width===1440)await page.screenshot({path:`/tmp/storage-temporary-${dark?'dark':'light'}.png`});
 }
 await page.getByRole('button',{name:'下一页'}).click();assert.equal(await page.locator('.storage-temporary-row').count(),8);
 await page.getByRole('button',{name:'上一页'}).click();
 await page.getByRole('button',{name:'选择优先清理项'}).click();
 assert.equal(await page.locator('input:checked').count(),1);
 assert(await page.locator('input:checked').getAttribute('aria-label').then(s=>s.endsWith('-r2')));
 await page.locator('[data-action="delete"]').click();assert.equal(await page.evaluate(()=>requests.length),0);
 await page.locator('input[type="checkbox"]').first().check();
 assert.equal(await page.locator('[data-action="delete"]').textContent(),'清理所选项目');
 await page.locator('input[type="checkbox"]').first().uncheck();
 await page.getByRole('searchbox').fill('r2');assert.equal(await page.locator('.storage-temporary-row').count(),1);
 await page.locator('[data-action="delete"]').click();assert.equal(await page.evaluate(()=>requests.length),0);
 await page.locator('[data-action="delete"]').click();
 assert.deepEqual(await page.evaluate(()=>requests),[{type:'temp_files',items:[{name:'.tmp/public-update-package-20261020-r2',revision:'r2'}]}]);
 assert.equal(await page.locator('#storage-temporary-details').count(),0);
 await page.evaluate(()=>showTemporaryFilesModal());await page.keyboard.press('Escape');
 assert.equal(await page.locator('#opener').evaluate(e=>e===document.activeElement),true);
 assert.deepEqual(errors,[]);await browser.close();console.log('Temporary details: responsive light/dark, default protection, recommendations, pagination, search, selection and revision confirmation passed');
})().catch(e=>{console.error(e);process.exit(1)});
