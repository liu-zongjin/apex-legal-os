const fs=require('fs'),path=require('path'),http=require('http'),assert=require('assert');
const {chromium}=require('playwright');
(async()=>{
 const root=path.resolve('frontend');let next=1,scanCount=0,held=[],hold=false,notify=null,downloadHolds={},downloadNotifies={},partialRounds=0;
 const base={uid:'42',mailbox:'INBOX',ext:'.pdf',parsed:true,issue_time:'2026年09月01日',amount:'100.00'};
 const accountRows={
  qq_mail:[{...base,filename:'old.pdf',path:'/anonymous/old.pdf',issuer:'OLD ACCOUNT',export_key:'old'}],
  qq_exmail:[{...base,filename:'new.pdf',path:'/anonymous/new.pdf',issuer:'CURRENT ACCOUNT',export_key:'new'}]
 };
 const json=(res,body)=>{res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify(body));};
 const server=http.createServer(async(req,res)=>{
  const url=new URL(req.url,'http://localhost');let body='';for await(const chunk of req)body+=chunk;
  if(url.pathname==='/invoice-center'){res.writeHead(200,{'content-type':'text/html'});res.end(fs.readFileSync(path.join(root,'invoice-center.html')));return;}
  if(url.pathname.startsWith('/static/')){const target=path.join(root,path.basename(url.pathname));if(fs.existsSync(target)){res.writeHead(200,{'content-type':target.endsWith('.js')?'text/javascript':'text/css'});res.end(fs.readFileSync(target));return;}}
  if(url.pathname==='/api/download-center/records'&&req.method==='POST'){json(res,{id:String(next++).padStart(32,'0'),...JSON.parse(body)});return;}
  if(url.pathname==='/api/download-center/invoice-results'){json(res,{id:JSON.parse(body).identity,status:'completed'});return;}
  if(url.pathname==='/api/qq-mail/invoices'){
   scanCount++;const payload=JSON.parse(body);const rows=accountRows[payload.account]||[];
   const partial=partialRounds-->0;
   const reply=()=>json(res,{invoices:rows,total:rows.length,parsed_count:rows.length,scanned_mails:partial?3:5,scanned_folders:partial?3:5,total_folders:5,folder:'/anonymous',warnings:[],timed_out:partial});
   if(hold&&payload.account==='qq_mail'){held.push(reply);if(notify)notify();}else reply();return;
  }
  if(url.pathname==='/api/qq-mail/invoices/download'){
   const account=JSON.parse(body).account;const reply=()=>{res.writeHead(200,{'content-type':'application/zip','content-length':'3'});res.end('zip');};
   downloadHolds[account]=reply;if(downloadNotifies[account])downloadNotifies[account]();return;
  }
  if(/\/api\/download-center\/records\/[^/]+\/file$/.test(url.pathname)){json(res,{id:url.pathname.split('/').at(-2),status:'completed',name:'匿名.zip'});return;}
  if(url.pathname==='/api/qq-mail/invoices/history'){
   const account=url.searchParams.get('account');const reply=()=>json(res,{records:[],export_keys:[account==='qq_exmail'?'new':'old']});
   if(hold&&account==='qq_mail')held.push(reply);else reply();return;
  }
  if(url.pathname==='/api/qq-mail/invoice-automation'){
   const account=url.searchParams.get('account');const reply=()=>json(res,{tasks:account==='qq_mail'?[{id:'old-task',name:'OLD TASK',day:1,hour:9,minute:0}]:[],collections:[]});
   if(hold&&account==='qq_mail')held.push(reply);else reply();return;
  }
  json(res,{ok:true});
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const browser=await chromium.launch({headless:true,channel:process.env.STELLA_UI_BROWSER||'chrome'});
 const page=await browser.newPage({viewport:{width:1440,height:900}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const change=async account=>page.evaluate(account=>{const select=document.querySelector('#account-select');select.value=account;select.dispatchEvent(new Event('change'));},account);
 const scan=async()=>{await page.locator('#scan-btn').click();await page.waitForFunction(()=>!document.querySelector('#scan-btn').disabled&&!document.querySelector('#summary').hidden);};
 try{
  await page.goto('http://127.0.0.1:'+server.address().port+'/invoice-center?account=qq_exmail');await scan();
  hold=true;const started=new Promise(resolve=>notify=resolve);await change('qq_mail');
  await page.locator('#scan-btn').click();await started;
  await change('qq_exmail');assert(await page.locator('#invoice-table').isHidden());assert(await page.locator('#download-btn').isDisabled());
  await scan();await page.waitForFunction(()=>document.querySelector('#invoice-tbody').textContent.includes('CURRENT ACCOUNT'));
  held.splice(0).forEach(reply=>reply());hold=false;await page.waitForTimeout(150);
  assert((await page.locator('#invoice-tbody').innerText()).includes('CURRENT ACCOUNT'));
  assert(!(await page.locator('#invoice-tbody').innerText()).includes('OLD ACCOUNT'));
  assert(!(await page.locator('#automation-task-list').innerText()).includes('OLD TASK'));
  await page.locator('#exclude-exported-btn').click();assert.equal(await page.locator('#invoice-tbody [data-select]').count(),0);
  // A completed old-account ZIP must not re-enable a newer account's pending export.
  await page.evaluate(()=>{HTMLAnchorElement.prototype.click=function(){};});
  await change('qq_mail');await scan();
  let qqStarted=new Promise(resolve=>downloadNotifies.qq_mail=resolve);
  await page.locator('#download-btn').click();await qqStarted;
  await change('qq_exmail');await scan();
  let exStarted=new Promise(resolve=>downloadNotifies.qq_exmail=resolve);
  await page.locator('#download-btn').click();await exStarted;
  downloadHolds.qq_mail();await page.waitForTimeout(150);
  assert(await page.locator('#download-btn').isDisabled());
  await page.locator('#invoice-tbody [data-select]').first().click();await page.locator('#invoice-tbody [data-select]').first().click();
  assert(await page.locator('#download-btn').isDisabled());
  downloadHolds.qq_exmail();await page.waitForFunction(()=>!document.querySelector('#download-btn').disabled);
  // Same local UID in different folders, and separate files within one message, remain distinct.
  accountRows.qq_exmail=[
   {...base,filename:'a.pdf',path:'/anonymous/a.pdf'},
   {...base,mailbox:'Archive',filename:'a.pdf',path:'/anonymous/archive/a.pdf',amount:'200.00'},
   {...base,filename:'b.pdf',path:'/anonymous/b.pdf',amount:'-25.00'},
  ];await scan();assert((await page.locator('#summary').innerText()).includes('275.00'));
  assert.equal(await page.locator('#invoice-tbody [data-select]:checked').count(),3);
  // Underscore-delimited invoice numbers group format variants and forwarded copies once.
  const number='26442000010000000001';accountRows.qq_exmail=[
   {...base,filename:'dzfp_'+number+'_seller.pdf',path:'/anonymous/main.pdf'},
   {...base,filename:'dzfp_'+number+'_seller.xml',path:'/anonymous/main.xml',ext:'.xml'},
   {...base,mailbox:'Archive',filename:'dzfp_'+number+'_copy.pdf',path:'/anonymous/copy.pdf'},
  ];await scan();assert((await page.locator('#summary').innerText()).includes('100.00'));
  assert.equal(await page.locator('#invoice-tbody [data-select]:checked').count(),1);
  accountRows.qq_exmail=[{...base,filename:'credit.pdf',path:'/anonymous/credit.pdf',amount:'-100.00'}];
  await scan();assert((await page.locator('#summary').innerText()).includes('-100.00'));
  accountRows.qq_exmail=[{...base,filename:'zero.pdf',path:'/anonymous/zero.pdf',amount:'0.00'}];
  await scan();assert((await page.locator('#summary').innerText()).includes('0.00'));
  accountRows.qq_exmail=[
   {...base,invoice_number:number,filename:'unreadable.pdf',path:'/anonymous/unreadable.pdf',amount:'',parsed:false},
   {...base,invoice_number:number,filename:'readable.xml',path:'/anonymous/readable.xml',ext:'.xml',amount:'100.00'},
  ];await scan();assert((await page.locator('#summary').innerText()).includes('100.00'));
  const batchStart=scanCount;partialRounds=1;await scan();assert.equal(scanCount,batchStart+2);
  accountRows.qq_exmail=[{...base,filename:'invoice.pdf',path:'/anonymous/invoice.pdf'},
   {...base,filename:'行程单.pdf',path:'/anonymous/trip.pdf',document_role:'supporting',parsed:false}];
  await scan();assert((await page.locator('#invoice-tbody').innerText()).includes('配套行程单'));
  assert(!(await page.locator('#invoice-tbody').innerText()).includes('需人工查看'));
  assert.equal(await page.locator('#invoice-tbody [data-select]:checked').count(),1);
  assert((await page.locator('#summary').innerText()).includes('100.00'));
  const before=scanCount;await page.evaluate(()=>document.querySelectorAll('.ext-chip').forEach(el=>el.classList.remove('on')));
  await page.locator('#scan-btn').click();assert.equal(scanCount,before);assert((await page.locator('#toast').innerText()).includes('文件类型'));
  for(const theme of ['light','dark'])for(const width of [1440,1024]){
   await page.emulateMedia({colorScheme:theme});await page.setViewportSize({width,height:900});
   assert(await page.locator('#scan-btn').isVisible());assert(await page.locator('#summary').isVisible());
   await page.screenshot({path:'/tmp/invoice-audit-'+theme+'-'+width+'.png'});
  }
  assert.deepEqual(errors,[]);console.log('Invoice audit UI: delayed mailbox responses/history isolated, no old selection after switching, signed totals and format/forward dedup correct, empty formats rejected; light/dark desktop screenshots captured.');
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);process.exit(1);});
