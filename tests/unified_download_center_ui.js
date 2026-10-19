const fs=require('fs'),path=require('path'),http=require('http'),assert=require('assert');
const {chromium,webkit}=require('playwright');
(async()=>{
  const frontend=path.resolve('frontend');let next=10,saved=0,uploaded=0,lastQuery=null,cleaned=0,trashed=0;
  const rows=[
    {id:'1'.repeat(32),name:'匿名案件证据.pdf',source:'网易企业邮箱',category:'mail',purpose:'case',status:'completed',case_id:1,case_title:'匿名合同纠纷案件',destination:'/匿名目录/案件材料',path:'/匿名目录/案件材料/a.pdf',file_available:true,created_at:'2026-10-13T10:00:00'},
    {id:'2'.repeat(32),name:'匿名发票.pdf',source:'QQ邮箱',category:'invoice',purpose:'invoice',status:'completed',case_id:0,destination:'/匿名目录/发票归集',file_available:true,created_at:'2026-10-13T09:00:00'},
    {id:'3'.repeat(32),name:'司法送达材料.pdf',source:'司法短信',category:'judicial',purpose:'case',case_title:'匿名合同纠纷案件',status:'downloading',phase:'正在下载送达文书',received_bytes:50*1048576,total_bytes:100*1048576,total_files:2,completed_files:1,destination:'应用暂存区',created_at:'2026-10-13T08:00:00'},
    {id:'4'.repeat(32),name:'法院卷宗',source:'一张网',category:'court',purpose:'case',status:'partial',error:'一个附件连接中断',destination:'/匿名目录/法院卷宗',created_at:'2026-10-13T07:00:00'},
    {id:'5'.repeat(32),name:'授权委托书.docx',source:'文书生成',category:'document',purpose:'case',status:'completed',case_title:'匿名合同纠纷案件',destination:'/匿名目录/案件',created_at:'2026-10-13T06:00:00'},
    {id:'6'.repeat(32),name:'法律研究.docx',source:'AI增强',category:'ai',purpose:'other',status:'completed',destination:'应用暂存区',created_at:'2026-10-13T05:00:00'},
    {id:'7'.repeat(32),name:'<img src=x onerror=alert(1)>',source:'历史下载',category:'export',purpose:'other',status:'completed',destination:'历史浏览器记录：保存位置未确认',created_at:'2026-10-13T04:00:00'},
  ];
  rows.forEach((row,index)=>{row.size_bytes=(7-index)*1048576;row.file_revision='fixture-'+row.id;});
  const json=(res,value,status=200)=>{res.writeHead(status,{'content-type':'application/json'});res.end(JSON.stringify(value));};
  const server=http.createServer(async(req,res)=>{
    const url=new URL(req.url,'http://localhost');
    if(url.pathname.startsWith('/static/')){const target=path.join(frontend,path.basename(url.pathname));if(fs.existsSync(target)){res.writeHead(200,{'content-type':target.endsWith('.js')?'text/javascript':'text/css'});res.end(fs.readFileSync(target));}else{res.writeHead(404);res.end();}return;}
    if(url.pathname==='/download-center'){res.writeHead(200,{'content-type':'text/html'});res.end(fs.readFileSync(path.join(frontend,'download-center.html')));return;}
    if(url.pathname==='/api/ai-ask/messages/md/export'){const data=Buffer.from('匿名测试 Markdown','utf8');res.writeHead(200,{'content-type':'text/markdown','content-length':String(data.length),'content-disposition':"attachment; filename*=UTF-8''question.md"});res.end(data);return;}
    if(url.pathname==='/api/suohan/generate'){
      const block=Buffer.alloc(1048576,'0');res.writeHead(200,{'content-type':'application/pdf','content-length':String(6*block.length),'content-disposition':"attachment; filename*=UTF-8''anonymous.pdf"});
      for(let i=0;i<6;i++){res.write(block);await new Promise(resolve=>setTimeout(resolve,180));}res.end();return;
    }
    const chunks=[];for await(const chunk of req)chunks.push(chunk);let body={};const text=Buffer.concat(chunks).toString();if((req.headers['content-type']||'').includes('application/json'))body=JSON.parse(text||'{}');
    if(url.pathname==='/api/case-manager/case-lookup'){json(res,{items:[{id:1,title:'匿名合同纠纷案件',source_status:'active'}],has_more:false});return;}
    if(url.pathname.endsWith('/folder-binding')){json(res,{available:true,real_path:'/匿名目录/已绑定案件'});return;}
    if(url.pathname==='/api/download-center/import-legacy'){json(res,{imported:0});return;}
    if(url.pathname==='/api/download-center/analyze'){json(res,{items:[{id:'missing-fixture',name:'missing.pdf'}],total:1});return;}
    if(url.pathname==='/api/download-center/clean-missing'){assert.equal(body.confirmed,true);assert.deepEqual(body.ids,['missing-fixture']);cleaned++;json(res,{removed:1,skipped:0});return;}
    if(url.pathname==='/api/download-center/trash'){assert.equal(body.confirmed,true);assert(body.items.length>=2);trashed++;json(res,{moved:body.items.map(item=>item.id),errors:[]});return;}
    if(url.pathname==='/api/download-center/records'&&req.method==='POST'){const item={id:(next++).toString(16).padStart(32,'0'),...body,status:'preparing',created_at:new Date().toISOString(),total_files:1};rows.unshift(item);json(res,item);return;}
    if(url.pathname==='/api/download-center/records'){lastQuery=url.searchParams;let result=rows.filter(r=>(!url.searchParams.get('category')||r.category===url.searchParams.get('category'))&&(!url.searchParams.get('q')||JSON.stringify(r).includes(url.searchParams.get('q'))));if(lastQuery.get('sort')==='largest')result.sort((a,b)=>(b.size_bytes||0)-(a.size_bytes||0));if(lastQuery.get('sort')==='smallest')result.sort((a,b)=>(a.size_bytes||0)-(b.size_bytes||0));json(res,{items:result,total:result.length,summary:{total:rows.length,active:rows.filter(r=>['preparing','downloading','saving'].includes(r.status)).length,failed:1,unassigned:1}});return;}
    const match=url.pathname.match(/^\/api\/download-center\/records\/([^/]+)(?:\/(.+))?$/);
    if(match){const item=rows.find(r=>r.id===match[1]);if(!item){json(res,{detail:'missing'},404);return;}
      if(req.method==='PATCH'){Object.assign(item,body);json(res,item);return;}
      if(match[2]==='file'&&req.method==='POST'){uploaded++;Object.assign(item,{status:'completed',received_bytes:6*1048576,total_bytes:6*1048576,file_available:true,path:'/匿名目录/暂存',destination:'应用暂存区'});json(res,item);return;}
      if(match[2]==='native-saved'){Object.assign(item,{status:'completed',destination:body.path,path:body.path});json(res,item);return;}
      if(match[2]==='save-case'){assert.equal(body.confirmed,true);assert.equal(body.case_id,1);saved++;Object.assign(item,{case_id:1,case_title:'匿名合同纠纷案件',destination:'/匿名目录/已绑定案件/#下载材料'});json(res,item);return;}
      json(res,item);return;
    }
    json(res,{detail:'unsupported '+url.pathname},404);
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const origin='http://127.0.0.1:'+server.address().port;
  const browser=process.env.STELLA_UI_ENGINE==='webkit'?await webkit.launch({headless:true}):await chromium.launch({headless:true,channel:process.env.STELLA_UI_BROWSER||'chrome'});
  const page=await browser.newPage({viewport:{width:1440,height:900}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(origin+'/download-center');await page.waitForFunction(()=>document.querySelectorAll('.dc-record').length>=7);
  assert((await page.textContent('#dc-records')).includes('匿名合同纠纷案件'));
  assert.equal(await page.locator('#dc-records img').count(),0);
  assert.equal(await page.locator('.dc-record').filter({hasText:'匿名发票.pdf'}).locator('[data-case]').count(),0);
  await page.click('[data-category="mail"]');await page.waitForFunction(()=>document.querySelectorAll('.dc-record').length===1);
  await page.click('[data-category=""]');await page.waitForFunction(()=>document.querySelectorAll('.dc-record').length>=7);
  await page.locator('[data-case]').first().click();
  await page.click('[data-confirm]');assert.equal(saved,0);
  assert((await page.textContent('#ad-error')).includes('请选择'));
  await page.fill('#ad-case-input','匿名');await page.waitForSelector('[data-case-index]');await page.click('[data-case-index]');
  await page.waitForFunction(()=>document.getElementById('ad-binding').textContent.includes('已绑定案件'));
  fs.mkdirSync('outputs/unified-download-center',{recursive:true});
  await page.screenshot({path:'outputs/unified-download-center/confirmation.png',animations:'disabled'});
  await page.click('[data-confirm]');await page.waitForFunction(()=>document.querySelector('.ad-modal')===null);await page.waitForTimeout(150);
  assert.equal(saved,1);
  for(const width of [1440,1024]){await page.setViewportSize({width,height:width===1440?900:768});for(const dark of [false,true]){await page.evaluate(d=>document.body.classList.toggle('dark-mode',d),dark);await page.screenshot({path:`outputs/unified-download-center/${width}-${dark?'dark':'light'}.png`,animations:'disabled'});assert(await page.locator('main').evaluate(el=>el.scrollWidth<=el.clientWidth+1));}}
  // Test real streaming transfer rather than a timer-based fabricated percentage.
  await page.evaluate(()=>{window.downloadPromise=ApexDownloads.fetch('/api/suohan/generate',{method:'POST'}).then(r=>r.blob());});
  await page.waitForFunction(()=>{const bars=[...document.querySelectorAll('#apex-download-progress [role="progressbar"]')];return bars.some(b=>Number(b.getAttribute('aria-valuenow'))>0&&Number(b.getAttribute('aria-valuenow'))<99);});
  await page.evaluate(()=>window.downloadPromise.then(blob=>{window.exportedBlob=blob;window.exportedUrl=ApexDownloads.objectURL(blob);}));assert.equal(uploaded,1);
  await page.waitForFunction(()=>document.querySelector('#apex-download-progress').textContent.includes('已完成'));
  const recordId=await page.evaluate(()=>ApexDownloads.nativeRecord({id:'native-fixture',name:'anonymous.pdf',url:exportedUrl}));
  assert(recordId);
  await page.evaluate(()=>ApexDownloads.nativeEvent({id:'native-fixture',name:'anonymous.pdf',url:exportedUrl,status:'preparing'}));
  await page.waitForFunction(()=>document.querySelector('#apex-download-progress').textContent.includes('等待选择系统保存位置'));
  await page.evaluate(()=>ApexDownloads.nativeEvent({id:'native-fixture',name:'anonymous.pdf',url:exportedUrl,status:'downloading',received_bytes:3*1048576,total_bytes:6*1048576}));
  assert((await page.textContent('#apex-download-progress')).includes('50%'));
  await page.evaluate(()=>ApexDownloads.nativeEvent({id:'native-fixture',name:'anonymous.pdf',url:exportedUrl,status:'completed',path:'/匿名目录/用户所选位置/anonymous.pdf'}));
  await page.waitForFunction(()=>document.querySelector('#apex-download-progress').textContent.includes('已完成'));
  await page.evaluate(async()=>{const response=await ApexDownloads.fetch('/api/ai-ask/messages/md/export?format=md');window.markdownBytes=[...new Uint8Array(await response.arrayBuffer())];});
  assert.deepEqual(await page.evaluate(()=>markdownBytes.slice(0,3)),[239,187,191]);
  await page.evaluate(()=>document.querySelectorAll('[data-dismiss]').forEach(b=>b.click()));
  // Keyboard cancellation and no accidental case write for invoices/other attachments.
  await page.evaluate(()=>{window.destinationPromise=ApexDownloads.mail({uid:'10',account:'qq_mail'});});
  await page.waitForSelector('.ad-modal');await page.keyboard.press('Escape');assert.equal(await page.evaluate(()=>window.destinationPromise),null);
  await page.setViewportSize({width:390,height:844});assert(await page.locator('main').evaluate(el=>el.scrollWidth<=el.clientWidth+1));
  await page.setViewportSize({width:1440,height:1000});
  await page.click('[data-sort="smallest"]');await page.waitForResponse(r=>r.url().includes('sort=smallest'));
  await page.fill('#dc-min','2');await page.fill('#dc-max','10');await page.fill('#dc-from','2026-10-01');await page.fill('#dc-to','2026-10-19');
  await page.click('#dc-apply');await page.waitForResponse(r=>r.url().includes('min_bytes=2097152'));
  assert.equal(lastQuery.get('max_bytes'),'10485760');assert.equal(lastQuery.get('date_from'),'2026-10-01');assert.equal(lastQuery.get('date_to'),'2026-10-19');
  await page.click('#dc-reset');await page.waitForResponse(r=>r.url().includes('min_bytes=0'));
  await page.click('#dc-select-page');assert(await page.locator('[data-select]:checked').count()>=2);
  await page.click('#dc-trash');await page.click('[data-no]');assert.equal(trashed,0);
  await page.click('#dc-trash');await page.click('[data-yes]');await page.waitForFunction(()=>document.getElementById('dc-notice').textContent.includes('已移到废纸篓'));assert.equal(trashed,1);
  await page.click('#dc-analyze');await page.waitForSelector('#dc-analysis:not([hidden])');assert((await page.textContent('#dc-analysis-text')).includes('1 条'));
  await page.click('#dc-clean-missing');await page.click('[data-yes]');await page.waitForFunction(()=>document.getElementById('dc-notice').textContent.includes('已清理 1'));assert.equal(cleaned,1);
  const previousUploaded=uploaded;
  await page.evaluate(()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob(['fixture CSV']));a.download='fixture.csv';a.dataset.downloadCategory='calculator';a.click();URL.revokeObjectURL(a.href);});
  await page.waitForFunction(()=>document.querySelector('#apex-download-progress').textContent.includes('fixture.csv'));
  for(let attempt=0;attempt<30&&uploaded===previousUploaded;attempt++)await page.waitForTimeout(50);
  assert.equal(uploaded,previousUploaded+1);assert.equal(rows.find(r=>r.name==='fixture.csv').category,'calculator');
  await page.screenshot({path:'outputs/unified-download-center/enhanced.png',animations:'disabled'});
  assert.equal(errors.length,0,errors.join('\n'));
  await browser.close();server.close();
  console.log('Unified downloads UI: sources, size/date query controls, page selection, trash confirmation, missing cleanup, detached exports, real streaming, native save, responsive light/dark layouts passed');
})().catch(error=>{console.error(error);process.exit(1);});
