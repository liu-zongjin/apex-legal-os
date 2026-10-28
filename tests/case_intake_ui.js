const fs = require('fs'), path = require('path'), assert = require('assert');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
(async () => {
 const browser = await chromium.launch({headless:true, executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const page = await browser.newPage({viewport:{width:1000,height:800}});
 const errors=[]; page.on('pageerror', error => errors.push(error.message));
 await page.setContent(`<style>${fs.readFileSync(path.join(root,'frontend/case-manager.css'),'utf8')}</style><div class="drawer show" style="position:static;transform:none;width:100%;height:auto;overflow:visible"><div class="drawer-body"><main class="case-detail-main" id="mount"></main></div></div>`);
 await page.addScriptTag({content:`
 const state={editing:{isNew:true,item:{parties:[],case_numbers:[],client_profiles:[],case_type:'之前的案由',current_stage:''},inlineSection:''}};
 let notices=[], requests=[], created=[], existingMode=false, updated=null, slowRecognize=false, resolveRecognize=null;
 function $(id){return document.getElementById(id)}
 function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
 function toast(v){notices.push(v)}
 function hasCaseClient(item){return !!item.parties.find(p=>p.party_group==='client')}
 function renderCaseFolderUnboundPanel(){document.getElementById('mount').innerHTML='<section class="detail-section" id="caseAutomationPanel"><h3>案件文件夹与文书</h3><div class="case-folder-summary"><button class="btn" onclick="selectIntakeFolder()">绑定案件文件夹</button><button class="btn primary" id="caseIntakeStartBtn" onclick="beginIntakeRecognition()">AI 智能识别</button></div>'+caseIntakeHtml()+'</section>'};
 function renderOpenCaseDetail(){renderCaseFolderUnboundPanel()}
 async function api(url,opts={}){requests.push({url,body:opts.body?JSON.parse(opts.body):null});
  if(url.endsWith('/intake/folder'))return {session:'session',folder_path:'/tmp/案例',files:['合同.txt','材料/通知.txt']};
  if(url.endsWith('/intake/recognize') && slowRecognize) return new Promise(resolve=>{resolveRecognize=resolve});
  if(url.endsWith('/intake/recognize'))return {parties:[{name:'甲公司',role:'原告',type:'单位',source:'合同：甲公司'}],questions:[{field:'case_type',question:'是否为买卖合同纠纷？',value:'买卖合同纠纷',source:'合同：买卖'}]};
  if(url.includes('/ai-lookup'))return JSON.parse(opts.body).action==='profile'?{name:'甲公司',identity_code:'TEST01',data_source:'测试',address:'工商地址',registration_status:'存续'}:{candidates:[{name:'甲公司'}]};
  if(url.includes('/clients?'))return {items:existingMode?[{id:12,name:'甲公司',identity_code:'TEST01'}]:[]};
  if(url.endsWith('/clients/12') && opts.method==='PUT'){updated=JSON.parse(opts.body);return updated;}
  if(url.endsWith('/clients/12'))return {id:12,name:'甲公司',client_type:'单位',identity_code:'TEST01',address:'原有地址',contacts:[{name:'联系人',phone:'10000'}]};
  if(url.endsWith('/clients')){let v=JSON.parse(opts.body);created.push(v);return {...v,id:10};}
  if(url==='/api/case-manager/cases' && opts.method==='POST')return {...JSON.parse(opts.body),id:99};
  if(url==='/api/case-manager/cases/99/folder-binding')return {bound:true};
  throw Error(url);
 }`});
 await page.addScriptTag({path:path.join(root,'frontend/case-intake.js')});
 await page.evaluate(()=>renderOpenCaseDetail());
 for (const [width,height] of [[1000,800],[600,850]]) {
   await page.setViewportSize({width,height});
   for (const dark of [false,true]) {
     await page.evaluate(dark=>document.documentElement.classList.toggle('dark-mode',dark),dark);
     const bounds=await page.evaluate(()=>{const card=document.querySelector('.case-intake').getBoundingClientRect(),text=document.querySelector('.case-intake-help').getBoundingClientRect(),button=document.querySelector('#caseIntakeStartBtn').getBoundingClientRect();return {left:text.left-card.left,right:card.right-text.right,button:button.left-card.left,overflow:document.documentElement.scrollWidth-innerWidth};});
     assert(bounds.left>=12 && bounds.button>=12 && bounds.right>=12 && bounds.overflow<=1,JSON.stringify(bounds));
   }
 }
 await page.setViewportSize({width:1000,height:800});
 await page.evaluate(()=>document.documentElement.classList.remove('dark-mode'));
 if (process.env.CASE_INTAKE_SCREENSHOT) await page.screenshot({path:process.env.CASE_INTAKE_SCREENSHOT});
 await page.getByRole('button',{name:'绑定案件文件夹'}).click();
 await page.getByRole('button',{name:'选择识别材料'}).click();
 await page.getByRole('button',{name:'选择全部'}).click();
 await page.getByRole('button',{name:'AI 智能识别'}).click();
 assert.deepEqual(await page.evaluate(()=>requests.find(r=>r.url.endsWith('/intake/recognize')).body.paths),['合同.txt','材料/通知.txt']);
 assert.equal(await page.evaluate(()=>created.length),0);
 await page.getByRole('button',{name:'工商查询'}).click();
 await page.locator('.case-intake-candidates button').click();
 await page.getByLabel('当事人名称').fill('修改后的公司');
 assert.equal(await page.evaluate(()=>state.editing.intake.parties[0].profile),null);
 await page.getByLabel('当事人名称').fill('甲公司');
 await page.getByRole('button',{name:'工商查询'}).click();
 await page.locator('.case-intake-candidates button').click();
 await page.getByLabel('诉讼地位').fill('上诉人');
 await page.getByLabel('识别内容（可修改）').fill('合同纠纷');
 await page.getByRole('button',{name:'委托人',exact:true}).click();
 await page.getByRole('button',{name:'确认填入'}).click();
 await page.getByRole('button',{name:'应用已确认的信息'}).click();
 assert.equal(await page.evaluate(()=>created[0].identity_code),'TEST01');
 assert.equal(await page.evaluate(()=>state.editing.item.parties[0].name),'甲公司');
 assert.equal(await page.evaluate(()=>state.editing.item.parties[0].role),'上诉人');
 assert.equal(await page.evaluate(()=>state.editing.item.case_type),'合同纠纷');
 assert.equal(await page.evaluate(()=>state.editing.intake.folderPath),'/tmp/案例');
 await page.evaluate(()=>{existingMode=true;state.editing.item={parties:[],case_numbers:[],client_profiles:[]};state.editing.intake={folderPath:'/tmp/案例',files:[],selected:[],result:{},parties:[{name:'甲公司',role:'原告',type:'单位',group:'client',source:'合同：甲公司',profile:{name:'甲公司',identity_code:'TEST01',address:'工商地址',registration_status:'存续'}}],questions:[]};renderOpenCaseDetail();});
 await page.getByRole('button',{name:'应用已确认的信息'}).click();
 assert.equal(await page.evaluate(()=>updated.address),'原有地址');
 assert.equal(await page.evaluate(()=>updated.registration_status),'存续');
 assert.equal(await page.evaluate(()=>updated.contacts[0].phone),'10000');
 await page.evaluate(()=>{slowRecognize=true;state.editing.item={parties:[],case_numbers:[],client_profiles:[]};state.editing.intake={session:'session',folderPath:'/tmp/案例',files:['a.txt','b.txt'],selected:['a.txt'],parties:[],questions:[],pickerOpen:true};renderOpenCaseDetail();});
 await page.getByRole('button',{name:'AI 智能识别'}).click();
 assert.equal(await page.getByRole('button',{name:'选择全部'}).isDisabled(),true);
 await page.evaluate(()=>setIntakeSelection(true));
 assert.deepEqual(await page.evaluate(()=>state.editing.intake.selected),['a.txt']);
 await page.evaluate(()=>resolveRecognize({parties:[],questions:[]}));
 await page.waitForFunction(()=>!state.editing.intake.busy);
 assert.equal(await page.getByRole('button',{name:'选择识别材料'}).isDisabled(),false);
 const managerSource=fs.readFileSync(path.join(root,'frontend/case-manager.js'),'utf8');
 const saveSource=managerSource.slice(managerSource.indexOf('async function saveCaseSection(section) {'),managerSource.indexOf('// 所有案件详情视图共用这一套字段标记'));
 await page.addScriptTag({content:`function updatedCaseFromSection(){return {...state.editing.item}}; function readMasterClients(){return [{id:12,name:'甲公司',identity_code:'TEST01'}]}; ${saveSource}`});
 await page.evaluate(async()=>{state.editing.item={client_profiles:[{id:12,name:'甲公司',identity_code:'TEST01',contacts:[{name:'第一联系人',phone:'10000'},{name:'第二联系人',phone:'20000'}]}],parties:[{party_group:'client',name:'甲公司',role:'原告'}],case_numbers:[]};state.editing.isNew=true;state.editing.inlineSection='clients';await saveCaseSection('clients');});
 assert.deepEqual(await page.evaluate(()=>updated.contacts.map(c=>c.phone)),['10000','20000']);
 await page.addScriptTag({content:`function isOfflineReadonly(){return false}; function caseSavePayload(item){return {...item}}; function caseDetailSaveUrl(id){return '/api/case-manager/cases/'+id}; function rememberOpenCaseDetail(){}; async function refreshAll(){}`});
 await page.evaluate(async()=>{state.editing={tab:'cases',isNew:true,item:{title:'匿名案件',parties:[],case_numbers:[]},inlineSection:'',intake:{folderPath:'/tmp/案例',files:[],selected:[],parties:[],questions:[]}};await saveCaseSection('basic');});
 assert.equal(await page.evaluate(()=>requests.find(r=>r.url==='/api/case-manager/cases/99/folder-binding').body.folder_path),'/tmp/案例');
 assert.equal(await page.evaluate(()=>state.editing.isNew),false);
 assert.deepEqual(errors,[]);
 await browser.close(); console.log('case intake UI scenarios passed');
})().catch(e=>{console.error(e);process.exit(1)});
