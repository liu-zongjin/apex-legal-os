const fs=require('fs'), assert=require('assert'), acorn=require('acorn'), {chromium}=require('playwright');
const source=fs.readFileSync('frontend/app.js','utf8'), tree=acorn.parse(source,{ecmaVersion:'latest'});
const names=['renderCaseHubQuestions','selectCaseHubQuestion','setCaseHubSide','setCaseHubOcrConsent','askSourcesToContext','askEffectiveSources','askChipSources','toggleAskPublicWebSource','toggleAskCombinedSource','setAskCombinedSources','getSelectedAskMcpSources','setSelectedAskMcpSources','askSourceModeFromSources','syncAskSourceModeFromSources','askCombinedSummary'];
const declarations=names.map(name=>{const n=tree.body.find(n=>n.type==='FunctionDeclaration'&&n.id.name===name);assert(n,name);return source.slice(n.start,n.end)}).join('\n');
const questions=tree.body.find(n=>n.type==='VariableDeclaration'&&n.declarations.some(d=>d.id.name==='CASE_HUB_QUESTIONS'));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});const page=await browser.newPage({viewport:{width:1100,height:800}});
 await page.setContent('<div id="ask-case-hub-prompts"></div><textarea id="ask-input"></textarea>');
 await page.addScriptTag({content:`let askContext={type:'combined',caseHub:true,kinds:['knowledge','files'],mcpSources:[],files:{type:'case_files',caseId:4,wholeCase:true,paths:['__CASE_ROOT__'],files:[]}},askSourceMode='local_only',askIsLoading=false;const ASK_COMBINED_LABELS={knowledge:'知识库',fada:'法答网',files:'文件',publicweb:'公开案例'},ASK_KB_SCOPE_LABELS={},ASK_MCP_SOURCE_LABELS={aluris:'法随',yuandian_case:'元典',qcc_company:'企业信息'};function escapeHtml(s){let x=document.createElement('span');x.textContent=s;return x.innerHTML}function syncAskContextToActiveTab(){} function _updateAskContextBar(){} function updateAskSourceModeUI(){} function renderAskSelectedFiles(){} function renderAskHistory(){} function renderAskHistoryIndex(){} function refreshAskSourceScope(){} function autoResizeAskInput(){} function saveAskDraft(){} function showToast(x){window.lastToast=x} function leaveAskAutoMcp(){return false} function stashAskLocalScope(){} function restoreAskLocalScope(){}\n`+source.slice(questions.start,questions.end)+'\n'+declarations});
 await page.evaluate(()=>renderCaseHubQuestions());assert.equal(await page.locator('#ask-case-hub-prompts > button').count(),6);
 for(const [i,expected] of [[0,['knowledge','files']],[1,['fada','files']],[2,['knowledge','fada','files']],[3,['knowledge','fada','files','publicweb']],[4,['knowledge','fada','files','publicweb']],[5,['knowledge','fada','files']]]){
  await page.locator('#ask-case-hub-prompts > button').nth(i).click();
  const state=await page.evaluate(()=>({kinds:askContext.kinds,paths:askContext.files.paths,pack:askContext.exportKnowledgePack,mcps:askContext.mcpSources}));
  assert.deepEqual(state.kinds,expected);assert.deepEqual(state.paths,['__CASE_ROOT__']);assert.equal(state.pack,i===5);assert.deepEqual(state.mcps,[]);
 }
 await page.locator('#ask-case-hub-prompts > button').nth(3).click();await page.getByRole('button',{name:'被告',exact:true}).click();assert((await page.inputValue('#ask-input')).includes('支持被告观点'));
 await page.evaluate(()=>setSelectedAskMcpSources(['aluris']));assert.deepEqual(await page.evaluate(()=>askContext.mcpSources),['aluris']);assert((await page.evaluate(()=>askChipSources().has('publicweb'))));
 await page.evaluate(()=>setSelectedAskMcpSources(['aluris','qcc_company']));assert.deepEqual(await page.evaluate(()=>askContext.mcpSources),['aluris']);
 await page.evaluate(()=>toggleAskPublicWebSource());assert(!(await page.evaluate(()=>askContext.kinds.includes('publicweb'))));assert.deepEqual(await page.evaluate(()=>askContext.mcpSources),['aluris']);
 await browser.close();console.log('case hub source presets passed');
})().catch(e=>{console.error(e);process.exit(1)});
