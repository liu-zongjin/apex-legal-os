const fs=require('fs'),assert=require('assert'),acorn=require('acorn'),{chromium}=require('playwright');
const source=fs.readFileSync('frontend/app.js','utf8'),tree=acorn.parse(source,{ecmaVersion:'latest'});
const names=['ensureAskCaseFilePicker','selectAskCaseForFiles','loadAskTreeChildren','renderAskCaseFileTree','askTreeRow','toggleAskCaseWholeFolder','updateAskCaseFilePickerCount','confirmAskCaseFiles','toggleAskCaseFile','findAskTreeItem'];
const declarations=names.map(name=>{const n=tree.body.find(n=>n.type==='FunctionDeclaration'&&n.id.name===name);assert(n,name);return source.slice(n.start,n.end)}).join('\n');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'}),page=await browser.newPage();let request;
 await page.route('http://fixture.test/**',async route=>{const url=new URL(route.request().url());
  if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:'<select id="ask-model-select"><option value="deepseek-flash">vision</option></select>'});
  if(url.pathname.endsWith('/list'))return route.fulfill({json:{items:[{name:'匿名.txt',path:'匿名.txt',ai_supported:true,is_directory:false}]}});
  if(url.pathname.endsWith('/ai/prepare')){request=route.request().postDataJSON();return route.fulfill({json:{files:[{path:'匿名.txt',name:'匿名.txt'}],consent_required:[]}})}
  return route.fulfill({json:{}});
 });
 await page.goto('http://fixture.test/');
 await page.addScriptTag({content:`let askContext=null,askCaseFilePickerState={cases:[{id:7,title:'匿名案件'}],caseItem:null,items:[],selected:new Map(),wholeCase:false,searchResults:[],treeChildren:new Map(),treeExpanded:new Set(),treeLoading:new Set(),folderTags:new Map()};const DEFAULT_AI_ASK_MODEL='deepseek-flash',TAB_TYPES={AI_ASK:'ai'},tabState={tabs:[]};let ApexCasePicker={get:()=>null};function escapeHtml(v){let e=document.createElement('span');e.textContent=String(v||'');return e.innerHTML}function renderFinderTagDots(){return ''}function renderFinderFolderIcon(){return ''}function showToast(){}function applyAskFilesContext(x){window.lastFiles=x;return true}function syncAskSourceModeFromSources(){}function startFreshAskConversation(){}function closeAskCaseFilePicker(){}function _updateAskContextBar(){}function updateAskSourceModeUI(){}function renderAskSelectedFiles(){}function renderAskHistory(){} function askCurrentFilesContext(){return window.lastFiles}function confirmArticleTrashAction(){throw Error('视觉模型不应请求OCR授权')}\n`+declarations});
 await page.evaluate(()=>{ensureAskCaseFilePicker();document.getElementById('ask-case-file-picker').classList.add('open')});
 await page.evaluate(()=>selectAskCaseForFiles(7));
 await page.locator('#ask-case-file-whole').check();assert.equal(await page.locator('#ask-case-file-picker-count').innerText(),'已选择整个案件文件夹');
 await page.locator('#ask-case-file-picker-confirm').click();await page.waitForFunction(()=>window.lastFiles);
 assert.deepEqual(request.paths,['__CASE_ROOT__']);assert.equal(request.model,'deepseek-flash');assert.equal(request.allow_cloud_ocr,false);
 assert.deepEqual(await page.evaluate(()=>window.lastFiles.paths),['__CASE_ROOT__']);assert.equal(await page.evaluate(()=>window.lastFiles.wholeCase),true);
 await browser.close();console.log('whole case folder picker passed');
})().catch(error=>{console.error(error);process.exit(1)});
