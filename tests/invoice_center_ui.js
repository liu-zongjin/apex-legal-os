const fs=require('fs'),path=require('path'),http=require('http'),assert=require('assert');
const {chromium}=require('playwright');
(async()=>{
 const root=path.resolve('frontend');let scans=[],registrations=[];
 const json=(res,data)=>{res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify(data));};
 const server=http.createServer(async(req,res)=>{
  const url=new URL(req.url,'http://localhost');let body='';for await(const chunk of req)body+=chunk;
  if(url.pathname==='/invoice-center'){res.writeHead(200,{'content-type':'text/html'});res.end(fs.readFileSync(path.join(root,'invoice-center.html')));return;}
  if(url.pathname.startsWith('/static/')){const file=path.join(root,path.basename(url.pathname));if(fs.existsSync(file)){res.writeHead(200,{'content-type':file.endsWith('.js')?'text/javascript':'text/css'});res.end(fs.readFileSync(file));return;}}
  if(url.pathname==='/api/qq-mail/invoices'){const payload=JSON.parse(body);scans.push(payload);json(res,{total:1,parsed_count:1,scanned_mails:25,scanned_folders:2,total_folders:5,timed_out:true,warnings:['扫描达到时间上限，剩余邮件将在下次扫描时继续'],folder:'/匿名目录',invoices:[{uid:'42',filename:'匿名发票.pdf',path:'/匿名目录/发票.pdf',ext:'.pdf',parsed:true,amount:'100.00',issuer:'匿名销售方',issue_time:'2026年09月01日'}]});return;}
  if(url.pathname==='/api/download-center/records'&&req.method==='POST'){json(res,{id:'1'.repeat(32),...JSON.parse(body)});return;}
  if(url.pathname==='/api/download-center/invoice-results'){registrations.push(JSON.parse(body));json(res,{id:'1'.repeat(32),status:'partial',phase:'发票归集部分完成',error:'扫描达到时间上限'});return;}
  if(url.pathname==='/api/qq-mail/invoice-automation'){json(res,{tasks:[],collections:[{id:'anonymous',period:'2026-09',status:'partial',error:'扫描未完成',invoice_count:1,invoices:[]}]});return;}
  json(res,{records:[],history:[],items:[],ok:true});
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const browser=await chromium.launch({headless:true,channel:process.env.STELLA_UI_BROWSER||"chrome"});const page=await browser.newPage({viewport:{width:1440,height:900}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
  for(const account of ['qq_mail','qq_exmail','netease_exmail']){
   await page.goto('http://127.0.0.1:'+server.address().port+'/invoice-center?account='+account);
   await page.locator('#scan-btn').click();await page.waitForFunction(()=>document.querySelector('#summary').textContent.includes('2/5'));
   assert((await page.locator('#summary').innerText()).includes('扫描达到时间上限'));
   await page.waitForFunction(()=>document.querySelector('#apex-download-progress').textContent.includes('发票归集部分完成'));
   assert.equal(scans.at(-1).account,account);assert.equal(registrations.at(-1).timed_out,true);assert.equal(registrations.at(-1).warnings.length,1);
  }
  for(const scheme of ['light','dark'])for(const width of [1440,1024]){
   await page.emulateMedia({colorScheme:scheme});await page.setViewportSize({width,height:900});
   assert(await page.locator('#scan-btn').isVisible());assert(await page.locator('#summary').isVisible());
  }
  await page.locator('#automation-tab').click();
  assert((await page.locator('#automation-collection-list').innerText()).includes('部分完成'));
  assert(await page.locator('#automation-collection-list a').isVisible());
  assert.deepEqual(errors,[]);
  console.log('Invoice UI: three accounts preserve warning/timeout registration, show folder coverage, and keep partial ZIP download in light/dark desktop layouts.');
 }finally{await browser.close();server.close();}
})().catch(err=>{console.error(err);process.exit(1);});
