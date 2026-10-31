const fs=require('fs'), path=require('path'), assert=require('assert');
const {chromium,webkit}=require('playwright');
const root=path.resolve(__dirname,'..'), engine=process.env.CASE_INTAKE_ENGINE==='webkit'?webkit:chromium;
(async()=>{
 const browser=await engine.launch({headless:true,...(engine===chromium?{executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'}:{})});
 const context=await browser.newContext({viewport:{width:1440,height:900},userAgent:'LegalKB-NativeShell Fixture',serviceWorkers:'block',reducedMotion:'reduce'});
 await context.route('**/*',async route=>{
  const url=new URL(route.request().url()), pathname=url.pathname;
  if(pathname==='/case-manager')return route.fulfill({status:200,contentType:'text/html; charset=utf-8',body:fs.readFileSync(path.join(root,'frontend/case-manager.html'))});
  if(pathname.startsWith('/static/')){const file=path.join(root,'frontend',pathname.slice(8));if(fs.existsSync(file)){const ext=path.extname(file), mime=ext==='.css'?'text/css':ext==='.js'?'text/javascript':'application/octet-stream';return route.fulfill({status:200,contentType:mime,body:fs.readFileSync(file)});}return route.fulfill({status:404,body:''});}
  if(pathname==='/api/case-manager/cases/42/folder-binding')return route.fulfill({json:{bound:true,available:true,real_path:'/匿名目录/案件'}});
  if(pathname==='/api/case-manager/intake/folder')return route.fulfill({json:{session:'fixture',folder_path:'/匿名目录/案例材料',files:['合同.pdf','材料/通知书.pdf','材料/证据/附件.pdf','材料/另一份.pdf','材料-其他/文件.pdf']}});
  if(pathname==='/api/case-manager/intake/recognize')return route.fulfill({json:{parties:[{name:'甲公司',role:'原告',type:'单位',source:'合同.pdf（第 2 页，模型视觉识别，请核对原件）：原告甲公司'}],questions:[{field:'case_type',question:'本案是否为买卖合同纠纷？',value:'买卖合同纠纷',source:'合同.pdf（文字层核对）：买卖合同'}]}});
  if(pathname==='/api/pwa/session-status')return route.fulfill({json:{server_reachable:true,authenticated:true,shell_version:'297'}});
  if(pathname.startsWith('/api/'))return route.fulfill({json:pathname.endsWith('/offline-snapshot')?{version:1,cases:[],todos:[],hearings:[],preservations:[],appeals:[],options:{}}:{ok:true,items:[],counts:{}}});
  return route.fulfill({status:404,body:''});
 });
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://stella.test/case-manager', {waitUntil:'domcontentloaded'});
 await page.waitForFunction(()=>typeof openNewCaseDetail==='function');
 await page.evaluate(()=>openNewCaseDetail());
 await page.locator('#caseIntakePanel').waitFor();
 await page.waitForTimeout(500);
 for(const [w,h] of [[1440,900],[1024,768],[600,850]]){
  await page.setViewportSize({width:w,height:h});
  for(const dark of [false,true]){
   await page.evaluate(dark=>{document.documentElement.classList.toggle('dark-mode',dark);document.body.classList.toggle('dark-mode',dark)},dark);
   const geometry=await page.evaluate(()=>{const card=document.querySelector('#caseAutomationPanel').getBoundingClientRect(), text=document.querySelector('.case-intake-help').getBoundingClientRect(), button=document.querySelector('#caseIntakeStartBtn').getBoundingClientRect();return {left:text.left-card.left,button:button.left-card.left,right:card.right-text.right,cardOverflow:document.querySelector('#caseIntakePanel').scrollWidth-document.querySelector('#caseIntakePanel').clientWidth};});
   assert(geometry.left>=12 && geometry.button>=12 && geometry.right>=12 && geometry.cardOverflow<=1,JSON.stringify(geometry));
  }
 }
 await page.setViewportSize({width:1440,height:900});
 await page.evaluate(()=>{document.documentElement.classList.remove('dark-mode');document.body.classList.remove('dark-mode')});
 if(process.env.CASE_INTAKE_FULL_SCREENSHOT) await page.screenshot({path:process.env.CASE_INTAKE_FULL_SCREENSHOT});
 assert.equal(await page.locator('#caseAutomationPanel h3').count(),1);
 assert.equal(await page.getByText('AI 智能立案',{exact:true}).count(),0);
 await page.getByRole('button',{name:'绑定案件文件夹',exact:true}).click();
 await page.getByRole('button',{name:'选择识别材料',exact:true}).click();
 if(process.env.CASE_INTAKE_PICKER_SCREENSHOT) await page.screenshot({path:process.env.CASE_INTAKE_PICKER_SCREENSHOT});
 await page.getByLabel('材料',{exact:true}).check();
 assert.deepEqual((await page.evaluate(()=>state.editing.intake.selected)).sort(),['材料/通知书.pdf','材料/证据/附件.pdf','材料/另一份.pdf'].sort());
 await page.getByRole('button',{name:'展开文件夹 材料',exact:true}).click();
 await page.getByText('通知书.pdf',{exact:true}).click();
 assert.equal(await page.locator('input[data-intake-dir="材料"]').evaluate(el=>el.indeterminate),true);
 assert.equal((await page.evaluate(()=>state.editing.intake.selected)).length,2);
 await page.getByRole('button',{name:'选择全部',exact:true}).click();
 await page.getByRole('button',{name:'识别并填写案件信息',exact:true}).click();
 await page.getByText('模型视觉识别，请核对原件',{exact:false}).first().waitFor({state:'visible'});
 for(const [w,h] of [[1440,900],[600,850]]) {
  await page.setViewportSize({width:w,height:h});
  for(const dark of [false,true]) {
   await page.evaluate(dark=>{document.documentElement.classList.toggle('dark-mode',dark);document.body.classList.toggle('dark-mode',dark)},dark);
   const bounds=await page.locator('#caseIntakePanel').evaluate(el=>({overflow:el.scrollWidth-el.clientWidth,left:el.getBoundingClientRect().left,right:el.getBoundingClientRect().right}));
   assert(bounds.overflow<=1 && bounds.right<=w+1, JSON.stringify(bounds));
  }
 }
 await page.setViewportSize({width:1440,height:900});
 await page.evaluate(()=>{document.documentElement.classList.remove('dark-mode');document.body.classList.remove('dark-mode')});
 if(process.env.CASE_INTAKE_RESULT_SCREENSHOT) await page.screenshot({path:process.env.CASE_INTAKE_RESULT_SCREENSHOT});
 for (const selector of ['.case-intake-question']) {
  const overflow=await page.locator(selector).first().evaluate(el=>el.scrollWidth<=el.clientWidth+1);
  assert(overflow,selector+' overflows');
 }
 await page.getByLabel('当事人名称').fill('甲公司修正');
 await page.getByLabel('诉讼地位').fill('上诉人');
 await page.getByLabel('识别内容（可修改）').fill('合同纠纷');
 assert.equal(await page.evaluate(()=>state.editing.intake.parties[0].name),'甲公司修正');
 assert.equal(await page.evaluate(()=>state.editing.intake.parties[0].role),'上诉人');
 assert.equal(await page.evaluate(()=>state.editing.intake.questions[0].value),'合同纠纷');
 await page.evaluate(()=>{state.editing.item.client_profiles=[{id:1,name:'甲公司'}];state.editing.intake.parties=[];state.editing.intake.questions=[];});
 await page.getByRole('button',{name:'填入并继续创建案件'}).click();
 await page.locator('[data-case-inline-section="basic"] .case-section-tools').waitFor();
 await page.waitForFunction(()=>{const section=document.querySelector('[data-case-inline-section="basic"]'), body=document.querySelector('#drawerBody');return section.getBoundingClientRect().top>=body.getBoundingClientRect().top-5 && section.getBoundingClientRect().top<body.getBoundingClientRect().bottom;});
 await page.locator('#drawerCloseButton').click();
 await page.getByRole('alertdialog').getByText('案件尚未创建').waitFor();
 await page.getByRole('button',{name:'继续填写'}).click();
 assert.equal(await page.getByRole('alertdialog').count(),0);
 await page.evaluate(()=>openNewCaseDetail());
 await page.getByRole('button',{name:'识别并填写案件信息',exact:true}).click();
 await page.getByRole('button',{name:'选择全部',exact:true}).waitFor();
 assert.equal(await page.evaluate(()=>state.editing.intake.folderPath),'/匿名目录/案例材料');
 assert.equal(await page.locator('#caseAutomationPanel h3').innerText(),'案件文件夹与文书');
 await page.evaluate(()=>{state.editing={tab:'cases',mode:'detail',isNew:false,item:{id:42,title:'匿名案件',parties:[],case_numbers:[],todos:[],hearings:[],preservations:[],appeals:[],audit_logs:[]}};renderOpenCaseDetail();});
 await page.locator('#caseAutomationPanel').getByText('案件文件夹与文书').waitFor();
 assert.equal(await page.locator('#caseIntakeStartBtn').count(),0);
 const menuButton=page.locator('#caseAutomationPanel').getByRole('button',{name:'文书与管理'});
 await menuButton.click();
 const menu=page.getByRole('menu',{name:'文书与文件夹管理'});
 for(const name of ['合同','文书合集','文书核对 · 证据册 · 时间轴','案卷归档','重新绑定文件夹','解绑文件夹']) assert.equal(await menu.getByRole('menuitem',{name,exact:false}).count(),1);
 assert.equal(await menuButton.getAttribute('aria-expanded'),'true');
 await page.keyboard.press('Escape');
 assert.equal(await menuButton.getAttribute('aria-expanded'),'false');
 assert.equal(await menuButton.evaluate(el=>document.activeElement===el),true);
 assert.deepEqual(errors,[]);
 await browser.close();console.log('full case intake drawer browser review passed');
})().catch(error=>{console.error(error);process.exit(1)});
