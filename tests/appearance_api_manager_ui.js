/* Isolated settings/provider/notice UI: fake keys and no external AI requests. */
const {chromium}=require('playwright'),acorn=require('acorn'),fs=require('fs'),path=require('path'),http=require('http'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),out=path.join(root,'.tmp/unified-settings-ui');fs.mkdirSync(out,{recursive:true});
const source=fs.readFileSync(path.join(root,'frontend/app.js'),'utf8'),tree=acorn.parse(source,{ecmaVersion:'latest'});
const functions=['escapeHtml','_getTimeGreeting','currentAskWelcomeText'].map(name=>{const node=tree.body.find(n=>n.type==='FunctionDeclaration'&&n.id.name===name);assert(node,name);return source.slice(node.start,node.end);}).join('\n');
const listener=source.slice(source.indexOf("window.addEventListener('apex:appearance-changed'"),source.indexOf('function renderAskHistory()'));
const index=fs.readFileSync(path.join(root,'frontend/index.html'),'utf8');const settings=index.slice(index.indexOf('<div id="settings-brand-main">'),index.indexOf('<div class="brand-history-page"'));
let profile={user_name:'新用户',firm_name:'',firm_logo:'',firm_code:'',firm_address:'',firm_phone:''};let custom=null,purpose={},lastPayload=null;
const builtin={id:'deepseek',name:'DeepSeek',caption:'fixture',models:[{model:'deepseek-flash',label:'测试模型',hidden:false}],configured:false,api_url:'https://example.test/chat/completions',color:'#64748b'};
function publicCustom(){return custom?{...custom,api_key:undefined,key_masked:'••••••••',custom:true,caption:'自定义 API',models:custom.models.map(m=>({model:custom.id+':'+m,label:m,hidden:false})),color:'#64748b',configured:true,managed_key:false,managed_url:false}:null;}
function json(res,value){res.setHeader('Content-Type','application/json');res.end(JSON.stringify(value));}
const server=http.createServer(async(req,res)=>{
 const url=new URL(req.url,'http://fixture');
 if(url.pathname==='/settings'){res.setHeader('Content-Type','text/html; charset=utf-8');res.end(`<meta charset="utf-8"><link rel="stylesheet" href="/static/apex-design-tokens.css"><link rel="stylesheet" href="/static/apex-appearance.css"><style>body{padding:32px;max-width:900px;font:14px var(--apex-font-sans)}button{padding:10px;border-radius:10px}#settings-brand-main{padding:24px;background:var(--apex-surface-muted)}</style><script>let askContext=null;${functions}\n${listener}</script><script src="/static/apex-appearance.js" defer></script><div id="greetingUsername"></div><div id="ask-chat-area"><div class="ask-welcome"><p></p></div></div>${settings}`);return;}
 if(url.pathname==='/ai-api-manager'){res.setHeader('Content-Type','text/html; charset=utf-8');res.end(fs.readFileSync(path.join(root,'frontend/ai-api-manager.html')));return;}
 if(url.pathname==='/mingsi-meeting' || url.pathname==='/quick-approval'){
  if(url.searchParams.get('experience')==='1'){res.setHeader('Content-Type','text/html; charset=utf-8');res.end('<p id="experience">已进入体验页面</p>');return;}
  res.setHeader('Content-Type','text/html; charset=utf-8');res.end(`<meta name="stella-experience-route" content="${url.pathname}"><script src="/static/apex-customization.js" defer></script><label><input type="checkbox" id="customization-remember">知悉以上情况，不再提示</label><button id="customization-continue">打开明思律所版本体验</button>`);return;
 }
 if(url.pathname.startsWith('/api/')){
  let body='';for await(const chunk of req)body+=chunk;const payload=body?JSON.parse(body):{};
  if(url.pathname==='/api/appearance'){if(req.method==='PUT')profile={...profile,...payload};json(res,profile);return;}
  if(url.pathname==='/api/ai-providers'){json(res,{providers:[builtin,...(custom?[publicCustom()]:[])],default_provider:'deepseek',default_model:'deepseek-flash',configured_count:custom?1:0,total_count:custom?2:1});return;}
  if(url.pathname==='/api/ai-providers/purposes'){
   if(req.method==='PUT')purpose=payload.purpose_models;
   json(res,{purposes:['judicial_messages','hearing_notice','case_intake'].map((key,i)=>({key,label:['司法短信分析','传票与开庭通知分析','新建案件智能识别'][i],overridden:!!purpose[key],selected_model:purpose[key]||'',model:purpose[key]||'deepseek-flash'}))});return;
  }
  if(url.pathname==='/api/ai-providers/custom'&&req.method==='POST'){lastPayload=payload;custom={...payload,id:'custom_1234567890abcdef'};json(res,{provider:publicCustom()});return;}
  if(url.pathname.startsWith('/api/ai-providers/custom/')&&req.method==='DELETE'){custom=null;purpose={};json(res,{success:true});return;}
  if(url.pathname==='/api/ai-providers/custom_1234567890abcdef'&&req.method==='PUT'){custom={...custom,...payload};json(res,{provider:publicCustom()});return;}
  if(url.pathname.endsWith('/balance')){json(res,{unsupported:true,message:'未提供余额接口'});return;}
  json(res,{});return;
 }
 const name=path.basename(url.pathname),candidate=path.join(root,'frontend',name);
 if(fs.existsSync(candidate)&&fs.statSync(candidate).isFile()){res.setHeader('Content-Type',name.endsWith('.css')?'text/css':'text/javascript');res.end(fs.readFileSync(candidate));return;}
 res.writeHead(404);res.end();
});
(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const origin='http://127.0.0.1:'+server.address().port;
 const browser=await chromium.launch({headless:true,channel:'chrome'});const page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[];page.on('pageerror',error=>errors.push(error.message));
 try{
  await page.goto(origin+'/settings');await page.getByText(/新用户，我可以/).waitFor();
  await page.locator('#appearance-user_name').fill('示例律师 <测试>');await page.locator('#appearance-firm_name').fill('示例律所');
  await page.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));assert.equal(await page.locator('#appearance-user_name').inputValue(),'示例律师 <测试>');
  await page.locator('#appearance-save').click();await page.getByText('已保存，姓名与律所资料已同步至相关页面').waitFor();
  assert.equal(await page.locator('#greetingUsername').innerText(),'示例律师 <测试>');assert.ok((await page.locator('.ask-welcome p').innerText()).includes('示例律师 <测试>'));
  await page.evaluate(()=>{askContext={type:'case_database',caseId:1,caseTitle:'虚构示例案'};window.dispatchEvent(new CustomEvent('apex:appearance-changed'));});
  assert.ok((await page.locator('.ask-welcome p').innerText()).includes('虚构示例案'));
  await page.locator('#appearance-user_name').fill('另一名称');await page.locator('#appearance-save').click();await page.waitForFunction(()=>document.querySelector('.ask-welcome p').textContent.includes('另一名称'));
  assert.ok((await page.locator('.ask-welcome p').innerText()).includes('虚构示例案'));await page.screenshot({path:path.join(out,'appearance.png')});
  await page.goto(origin+'/ai-api-manager');await page.getByRole('button',{name:'接入 ChatGPT / OpenAI API',exact:true}).click();
  assert.equal(await page.locator('#apiUrl').inputValue(),'https://api.openai.com/v1/responses');assert.equal(await page.locator('#protocolResponses').getAttribute('aria-pressed'),'true');
  await page.locator('#customModels').fill('wire-model\nsecond-model');await page.locator('#apiKey').fill('fixture-key-never-real');await page.locator('#saveBtn').click();
  await page.getByText('配置已保存并立即生效',{exact:true}).waitFor();assert.equal(lastPayload.protocol,'responses');assert.deepEqual(lastPayload.models,['wire-model','second-model']);
  const model=custom.id+':wire-model';
  for(const key of ['judicial_messages','hearing_notice','case_intake']){await page.locator(`[data-purpose-provider="${key}"]`).selectOption(custom.id);await page.locator(`[data-purpose="${key}"]`).selectOption(model);}
  await page.locator('#savePurposeBtn').click();await page.getByText('各功能默认模型已保存并生效',{exact:true}).waitFor();assert.equal(purpose.judicial_messages,model);assert.equal(purpose.hearing_notice,model);assert.equal(purpose.case_intake,model);
  await page.locator('[data-purpose-provider="case_intake"]').selectOption('');await page.locator('#savePurposeBtn').click();await page.waitForFunction(()=>document.querySelector('[data-purpose-provider="case_intake"]').value==='');assert.equal(purpose.case_intake,'');
  await page.getByRole('button',{name:'接入 Kimi API',exact:true}).click();assert.equal(await page.locator('#apiUrl').inputValue(),'https://api.moonshot.cn/v1/chat/completions');assert.equal(await page.locator('#protocolChat').getAttribute('aria-pressed'),'true');await page.locator('#cancelDrawer').click();
  for(const width of [1440,1024])for(const dark of [false,true]){await page.setViewportSize({width,height:900});await page.evaluate(d=>document.body.classList.toggle('dark',d),dark);await page.screenshot({path:path.join(out,`api-${width}-${dark?'dark':'light'}.png`)});}
  await page.locator(`[data-edit="${custom.id}"]`).click();await page.locator('#deleteCustom').click();assert(custom);await page.locator('#deleteCustom').click();await page.getByText('已移除自定义 API',{exact:true}).waitFor();assert.equal(custom,null);
  await page.goto(origin+'/mingsi-meeting');await page.locator('#customization-continue').click();await page.locator('#experience').waitFor();
  await page.goto(origin+'/mingsi-meeting');await page.locator('#customization-remember').check();await page.locator('#customization-continue').click();await page.locator('#experience').waitFor();
  await page.goto(origin+'/quick-approval');await page.locator('#experience').waitFor();
  assert.deepEqual(errors,[]);console.log('APPEARANCE_API_NOTICE_UI_OK: profile and context greetings, unsaved drafts, OpenAI/Kimi presets, custom model purpose controls, removal, notice opt-out');
 }finally{await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
