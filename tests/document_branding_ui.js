/* Full generator pages against anonymous local API fixtures, never the live database. */
const {chromium}=require('playwright');const fs=require('fs'),path=require('path'),http=require('http'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),out=path.join(root,'.tmp/document-branding-ui');fs.mkdirSync(out,{recursive:true});
const defaults={user_name:'新用户',firm_name:'',firm_logo:'',firm_code:'',firm_address:'',firm_phone:''};let profile={...defaults};
const pages=['suohan-generator','document-bundle-generator','business-approval-generator','power-attorney-generator'];
const server=http.createServer((req,res)=>{
 const url=new URL(req.url,'http://fixture');
 if(url.pathname==='/api/appearance'){res.setHeader('Content-Type','application/json');res.end(JSON.stringify(profile));return;}
 if(url.pathname.startsWith('/api/')){res.setHeader('Content-Type','application/json');res.end(JSON.stringify({court:[],client:[],lawyer:[],party:[],caseType:[],stage:[],items:[],templates:{},types:[],history:[]}));return;}
 let file=pages.includes(url.pathname.slice(1))?url.pathname.slice(1)+'.html':url.pathname.replace(/^\/static\//,'');
 if(file.includes('..')){res.writeHead(404);res.end();return;}
 const absolute=path.join(root,'frontend',file);
 if(fs.existsSync(absolute)&&fs.statSync(absolute).isFile()){
  res.setHeader('Content-Type',file.endsWith('.html')?'text/html; charset=utf-8':file.endsWith('.css')?'text/css':file.endsWith('.js')?'text/javascript':'image/png');res.end(fs.readFileSync(absolute));return;
 }res.writeHead(404);res.end();
});
(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const origin='http://127.0.0.1:'+server.address().port;
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try{
  for(const name of pages){
   profile={...defaults};const page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[];
   page.on('pageerror',error=>errors.push(error.message));
   await page.goto(origin+'/'+name);
   const preview=page.locator(name==='document-bundle-generator'?'#previewSuohan':'#previewDocument');
   await page.waitForFunction(selector=>document.querySelector(selector)?.textContent.trim().length>50,name==='document-bundle-generator'?'#previewSuohan':'#previewDocument');
   assert.ok(!(await preview.innerText()).includes('明思'));if(name!=='power-attorney-generator')await page.locator('#appearance-document-note').waitFor();
   profile={...defaults,firm_name:'示例律师事务所 <测试>',firm_code:'测试',firm_address:'示例地址',firm_phone:'12345'};
   await page.evaluate(()=>window.ApexAppearance.load());
   await page.waitForFunction(selector=>document.querySelector(selector).textContent.includes('示例律师事务所'),name==='document-bundle-generator'?'#previewSuohan':'#previewDocument');
   assert.ok((await preview.innerText()).includes('示例律师事务所 <测试>'));
   if(name==='suohan-generator'){
    await page.locator('#courtInput').fill('示例法院 <img src=x onerror="window.injected=true">');
    await page.waitForFunction(()=>document.getElementById('preview-court').textContent.includes('<img'));
    assert.equal(await preview.locator('#preview-court img').count(),0);assert.equal(await page.evaluate(()=>window.injected),undefined);
    await page.locator('#clientInput').fill('示例委托人');await page.waitForFunction(()=>document.getElementById('preview-client').textContent.includes('示例委托人'));
    await page.evaluate(()=>renderHistory([{id:1,clients:['示例 &quot;});window.historyInjected=true;//'],lawyers:[],caseType:'合同纠纷'}]));
    await page.locator('.history-item').first().click();assert.equal(await page.evaluate(()=>window.historyInjected),undefined);

   }
   for(const width of [1440,1024])for(const dark of [false,true]){
    await page.setViewportSize({width,height:900});await page.evaluate(d=>{document.body.classList.toggle('dark-mode',d);document.body.classList.toggle('dark',d);},dark);
    await page.screenshot({path:path.join(out,`${name}-${width}-${dark?'dark':'light'}.png`)});
   }
   if(name==='suohan-generator'){await page.setViewportSize({width:1440,height:900});const box=await page.locator('.page-wrapper').boundingBox();assert.ok(box.width>1300,'configuration guidance must not become a sidebar or shrink the document workspace');}
   assert.deepEqual(errors,[],name+' must render without script errors');await page.close();
  }
  console.log('DOCUMENT_BRANDING_UI_OK: all four actual generator pages, blank/custom firm, suohan live editing and safe text, light/dark 1440/1024');
 }finally{await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
