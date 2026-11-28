const fs=require('fs'),assert=require('assert'),acorn=require('acorn'),{chromium}=require('playwright');
const source=fs.readFileSync('frontend/app.js','utf8'),tree=acorn.parse(source,{ecmaVersion:'latest'});
const names=['openAskWordExportModal','exportAskAnswer'];
const code=names.map(name=>{const node=tree.body.find(n=>n.type==='FunctionDeclaration'&&n.id.name===name);assert(node);return source.slice(node.start,node.end)}).join('\n');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'}),page=await browser.newPage();
 await page.setContent(`<div id="modal"><fieldset class="ask-word-destination" hidden><label><input type="radio" name="ask-word-destination" value="case"><span data-case-label></span></label><label><input type="radio" name="ask-word-destination" value="other"></label></fieldset><section class="ask-word-layout-editor"></section><button data-layout></button></div>`);
 await page.addScriptTag({content:`let askWordExportState,askContext=null;const record={id:'msg',role:'ai',content:'正文',askContext:{type:'combined',files:{caseId:7,caseTitle:'匿名案件'}}};function loadAskHistory(){return [record]}async function saveAskHistory(){}function ensureAskWordExportModal(){return document.querySelector('#modal')}async function loadAskWordCustomLayouts(){}function renderAskWordLayoutGrid(){}function showToast(x){window.notice=x}async function readExportBlob(){return new Blob(['doc'])}const ApexDownloads={fetch:async()=>({ok:true,headers:new Headers()}),saveBlobToCase:async(blob,id)=>{window.savedCase=id;return {destination:'匿名文件夹'}},objectURL:()=>{window.savedElsewhere=true;return 'data:text/plain,doc'}};\n`+code});
 await page.evaluate(()=>openAskWordExportModal('msg',null));
 assert.equal(await page.locator('[value=case]').isChecked(),true);assert((await page.locator('[data-case-label]').innerText()).includes('匿名案件'));
 await page.evaluate(()=>exportAskAnswer('msg','docx',null,'legal_standard',null,'case'));
 assert.equal(await page.evaluate(()=>window.savedCase),7);assert(!(await page.evaluate(()=>window.savedElsewhere)));
 await browser.close();console.log('word case export default passed');
})().catch(error=>{console.error(error);process.exit(1)});
