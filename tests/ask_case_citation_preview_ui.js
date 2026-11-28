const fs=require('fs'),assert=require('assert'),acorn=require('acorn'),{chromium}=require('playwright');
const source=fs.readFileSync('frontend/app.js','utf8'),tree=acorn.parse(source,{ecmaVersion:'latest'});
const names=['openAskCaseCitationPreview','syncAskConversationView'];
const code=names.map(name=>{const node=tree.body.find(n=>n.type==='FunctionDeclaration'&&n.id.name===name);assert(node);return source.slice(node.start,node.end)}).join('\n');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'}),page=await browser.newPage();
 await page.setContent('<div id="ask-case-hub-prompts"><details open><summary>预置问题</summary></details></div><button id="ask-send-btn"></button>');
 await page.addScriptTag({content:`let askContext={},askConversationTasks=new Map([['key',{requestId:'r'}]]),askIsLoading=false,askActiveRequestId,askActiveRequestContext,askActiveRequestHistoryKey,askAbortController;function getAskHistoryKey(){return 'key'}function restoreAskDraft(){}function removeAskLoading(){}function showAskLoading(){}function renderAskProgressEvents(){}function showToast(){}window.fetch=async()=>({ok:true,json:async()=>({kind:'docx',paragraphs:[{number:1,text:'无关段落'},{number:2,text:'合同双方约定的付款时间为二零二六年十二月三十一日，具体条款见合同。'}]})});\n`+code});
 await page.evaluate(()=>syncAskConversationView(false));assert.equal(await page.locator('details').evaluate(el=>el.open),false);
 await page.evaluate(()=>openAskCaseCitationPreview(1,{source:'材料.docx',quote:'合同双方约定的付款时间为二零二六年十二月三十一日，具体条款见合同。'}));
 await page.waitForSelector('dialog .match');assert((await page.locator('dialog .match').innerText()).includes('第2段'));
 await page.locator('dialog [data-close]').click();await page.locator('dialog').waitFor({state:'detached'});
 await browser.close();console.log('case citation preview and preset collapse passed');
})().catch(error=>{console.error(error);process.exit(1)});
