const fs=require('fs'),assert=require('assert'),{chromium}=require('playwright');
const src=fs.readFileSync('frontend/app.js','utf8');
assert(/oninput="autoResizeAskInput\(this\); saveAskDraft\(this\)"/.test(fs.readFileSync('frontend/index.html','utf8')));
function extract(name){
  const match=new RegExp('^(?:async )?function '+name+'\\(','m').exec(src);assert(match,name);
  const rest=src.slice(match.index), next=/\n(?:async )?function [\w]+\(/g;next.lastIndex=1;
  const end=next.exec(rest),decl=/\n(?:const|let|var|class) \w/.exec(rest);const stop=Math.min(end?end.index:rest.length,decl?decl.index:rest.length);return rest.slice(0,stop);
}
(async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.STELLA_UI_BROWSER||'chrome'});
 const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 let rejectCancel=false, saveFault='', releaseSave;
 const pending=new Map(),cancelled=[],saved=new Map(),progress=new Map(),versions=new Map();
 await page.route('http://parallel.test/**',async route=>{
  const request=route.request(),url=new URL(request.url());
  if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:'<meta charset="utf-8"><div id="ask-panel"><div id="ask-chat-area"></div><textarea id="ask-input"></textarea><select id="ask-model-select"><option value="fixture">fixture</option></select><button id="ask-send-btn" onclick="sendAskQuestion()">发送</button><button id="new-chat" onclick="createNewAskConversation()">新建</button></div>'});
  if(['/api/ask','/api/ask-stream'].includes(url.pathname)){const body=request.postData();const key=/name="history_key"\r\n\r\n([^\r]+)/.exec(body)[1];const id=/name="request_id"\r\n\r\n([^\r]+)/.exec(body)[1];pending.set(key,{route,id,streamed:url.pathname.endsWith("-stream")});return;}
  if(url.pathname.startsWith('/api/ask-cancel/')){if(rejectCancel){const missing=rejectCancel==='missing';rejectCancel=false;return route.fulfill(missing ? {json:{success:false,reason:'任务不存在或已结束'}} : {status:503,json:{detail:'fixture interruption'}});}cancelled.push(url.pathname.split('/').pop());return route.fulfill({json:{success:true}});}
  if(url.pathname.startsWith('/api/ask-progress/'))return route.fulfill({json:progress.get(url.pathname.split('/').pop()) || {status:'running',events:[]}});
  if(url.pathname==='/api/skills')return route.fulfill({json:{skills:[{id:'fixture-skill',source:'personal',display_name:'匿名 Skill'}]}});
  if(url.pathname==='/api/ai-ask/local-files/prepare')return route.fulfill({json:{session_id:'anonymous',files:[{id:'1',name:'匿名.txt'}]}});
  if(url.pathname==='/api/case-manager/cases/1/local-files/ai/prepare')return route.fulfill({json:{files:[{path:'anonymous.txt',name:'匿名.txt'}]}});
  if(url.pathname==='/api/ai-ask/history')return route.fulfill({json:{conversations:[...saved].map(([history_key,records])=>({history_key,records,version:versions.get(history_key)||0}))}});
  if(url.pathname==='/api/ai-ask/history/save'){const data=request.postDataJSON();if(saveFault==='hold'){saveFault='';await new Promise(resolve=>{releaseSave=resolve;});}if(saveFault==='unavailable'){saveFault='';return route.fulfill({status:503,json:{detail:'重启中'}});}if(saveFault==='conflict')return route.fulfill({status:409,json:{detail:'对话已在其他窗口更新'}});if(data.version!==undefined)assert.equal(data.version,versions.get(data.history_key)||0);const version=(versions.get(data.history_key)||0)+1;versions.set(data.history_key,version);saved.set(data.history_key,data.records);if(saveFault==='lost'){saveFault='';return route.abort();}return route.fulfill({json:{version}});}
  return route.fulfill({json:{}});
 });
 async function fulfillAnswer(entry,data){return entry.route.fulfill(entry.streamed ? {contentType:'text/event-stream',body:'event: delta\ndata: '+JSON.stringify({text:data.answer})+'\n\nevent: result\ndata: '+JSON.stringify(data)+'\n\n'} : {json:data});}
 await page.goto('http://parallel.test/');
 const names=['loadAskSkillList','updateAskSkillUI','selectAskSkill','setAskSourceMode','handleAskLocalFiles','confirmAskCaseFiles','cloneAskContext','saveAskDraft','restoreAskDraft','getAskBaseHistoryKey','getAskHistoryKey','activateAskHistoryKey','loadPendingAskTasks','loadPendingAskTask','savePendingAskTask','clearPendingAskTask','syncAskConversationView','finishAskConversationTask','startFreshAskConversation','createNewAskConversation','openAskHistoryEntry','genAskId','saveAskHistory','pushAskRecord','appendAskMessage','showAskLoading','removeAskLoading','startAskProgressPolling','stopAskTask','appendRecoveredAskAnswer','recoverPendingAskTask','readAskStream','deleteAskRecord','regenerateAskAnswer','sendAskQuestion'];
 let bootstrap=`var askConversationTasks=new Map(),askDraftInitialized=false,askDraftStorageWarningShown=false,ASK_DRAFT_STORAGE_KEY='stella-ai-ask-draft-v1',ASK_DRAFT_MAX_AGE_MS=30*24*60*60*1000,askIsLoading=false,askActiveRequestId=null,askActiveRequestContext=null,askActiveRequestHistoryKey='',askAbortController=null,askContext=null,askActiveHistoryKey='ask_history_a',askActiveHistoryBaseKey='ask_history_global',askHistoryCache=new Map([['ask_history_a',[]],['ask_history_b',[]]]),askHistoryVersions=new Map(),askHistorySaveQueues=new Map(),askEmptyConversationCreatedAt=new Map(),askHistorySaveWarningAt=0,askSourceMode='direct_ai',askSkillId='',askSkillList=null,askSkillListLoaded=false,ASK_SKILL_EXCLUDED_IDS=new Set(),ASK_PENDING_TASK_KEY='parallel_pending',askResearchProgressTimer=null,askResearchProgressPollTimer=null,DEFAULT_AI_ASK_MODEL='fixture',ASK_MODEL_LABELS={},ASK_SLOW_MODELS=new Set(),ASK_MCP_SOURCE_LABELS={};
 function ensureAskHistoryLoaded(){return Promise.resolve();} function loadAskHistory(ctx=askContext,key=getAskHistoryKey(ctx)){return askHistoryCache.get(key)||[];}
 async function apiFetch(url,init){const r=await fetch(url,init);if(!r.ok){const e=new Error('fixture save failed');e.status=r.status;throw e;}return r.json();}
 function showToast(){} function escapeHtml(s){return String(s);} function getSelectedAskMcpSources(){return [];} function updateCaseAiShortcutToolbar(){} function renderAskHistoryIndex(){} function renderAskProgressEvents(){} function autoResizeAskInput(){} function syncAskAccountBalance(){} function refreshAskYuandianBalance(){} function sourceModeForAskContext(){return 'direct_ai';} function updateAskSourceModeUI(){} function syncAskContextToActiveTab(){} function _updateAskContextBar(){} function toggleAskHistorySidebar(){}
 var ASK_SKILL_QUARK_DRIVE_ID='quark',tabState={tabs:[]},TAB_TYPES={AI_ASK:'ai'},askPendingLocalFiles=[],askCaseFilePickerState={caseItem:{id:1,title:'匿名'},selected:new Map([['anonymous.txt',{}]])};
 function setSelectedAskMcpSources(){} function closeAskMcpMenu(){} function applyAskSkillMcpLinkage(){} function renderAskSkillMenu(){} function closeAskSkillMenu(){} function renderAskSelectedFiles(){} function closeAskCaseFilePicker(){} function updateAskCaseFilePickerCount(){}
 function _renderOneMessage(host,record){const p=document.createElement('p');p.textContent=record.content;p.dataset.msgId=record.id;host.append(p);}
 function renderAskHistory(){document.getElementById('ask-chat-area').replaceChildren();for(const r of loadAskHistory())_renderOneMessage(document.getElementById('ask-chat-area'),r);syncAskConversationView();}
 `;
 await page.addScriptTag({content:bootstrap+names.map(extract).join('\n')});
 // The current composer follows scope changes and survives refresh byte-for-byte.
 const draft='  未完成的匿名问题\n第二行  ';
 await page.fill('#ask-input',draft);await page.evaluate(()=>saveAskDraft(document.getElementById('ask-input')));
 await page.evaluate(()=>selectAskSkill('fixture-skill'));assert.equal(await page.inputValue('#ask-input'),draft);
 await page.evaluate(()=>setAskSourceMode('direct_ai_web'));assert.equal(await page.inputValue('#ask-input'),draft);
 await page.evaluate(()=>handleAskLocalFiles([new File(['匿名'],'匿名.txt',{type:'text/plain'})]));assert.equal(await page.inputValue('#ask-input'),draft);
 await page.evaluate(()=>{const button=document.createElement('button');button.id='ask-case-file-picker-confirm';document.body.append(button);});
 await page.evaluate(()=>confirmAskCaseFiles());assert.equal(await page.inputValue('#ask-input'),draft);
 await page.click('#new-chat');assert.equal(await page.inputValue('#ask-input'),draft);
 await page.reload();await page.addScriptTag({content:bootstrap+names.map(extract).join('\n')});await page.evaluate(()=>restoreAskDraft());
 assert.equal(await page.inputValue('#ask-input'),draft);
 await page.fill('#ask-input','');await page.evaluate(()=>saveAskDraft(document.getElementById('ask-input')));
 await page.reload();await page.addScriptTag({content:bootstrap+names.map(extract).join('\n')});await page.evaluate(()=>restoreAskDraft());
 assert.equal(await page.inputValue('#ask-input'),'');
 await page.evaluate(()=>{askDraftInitialized=false;sessionStorage.setItem(ASK_DRAFT_STORAGE_KEY,JSON.stringify({text:'过期草稿',updatedAt:Date.now()-ASK_DRAFT_MAX_AGE_MS-1}));restoreAskDraft();});
 assert.equal(await page.inputValue('#ask-input'),'');assert.equal(await page.evaluate(()=>sessionStorage.getItem(ASK_DRAFT_STORAGE_KEY)),null);
 // Editing while the previous send is saving must not erase the newer input.
 await page.click('#new-chat');const editingKey=await page.evaluate(()=>getAskHistoryKey(askContext));saveFault='hold';
 await page.fill('#ask-input','已提交的匿名问题');await page.click('#ask-send-btn');
 while(!releaseSave) await new Promise(resolve=>setTimeout(resolve,10));
 await page.fill('#ask-input','保存期间继续编辑的草稿');await page.evaluate(()=>saveAskDraft(document.getElementById('ask-input')));releaseSave();
 await page.waitForFunction(k=>askConversationTasks.get(k)?.questionId,editingKey);assert.equal(await page.inputValue('#ask-input'),'保存期间继续编辑的草稿');
 await page.waitForTimeout(50);await fulfillAnswer(pending.get(editingKey),{answer:'完成'});await page.waitForFunction(()=>askConversationTasks.size===0);
 await page.fill('#ask-input','');await page.evaluate(()=>saveAskDraft(document.getElementById('ask-input')));
 // A restart can briefly reject the save, or commit it before the connection drops.
 for (const fault of ['unavailable','lost']) {
  await page.click('#new-chat');const key=await page.evaluate(()=>getAskHistoryKey(askContext));saveFault=fault;
  await page.fill('#ask-input','重启后的匿名问题');await page.click('#ask-send-btn');await page.waitForFunction(k=>askConversationTasks.get(k)?.questionId,key);
  assert.equal(saved.get(key).length,1);await page.waitForTimeout(50);await fulfillAnswer(pending.get(key),{answer:'恢复成功'});await page.waitForFunction(()=>askConversationTasks.size===0);
 }
 // A conflicting version must never dispatch or overwrite the other window.
 await page.click('#new-chat');const conflictKey=await page.evaluate(()=>getAskHistoryKey(askContext));saveFault='conflict';
 await page.fill('#ask-input','  保留的匿名草稿\n ');await page.click('#ask-send-btn');await page.waitForFunction(()=>askConversationTasks.size===0);
 assert.equal(await page.inputValue('#ask-input'),'  保留的匿名草稿\n ');assert.equal(await page.locator('#ask-chat-area [data-msg-id]').count(),0);assert(!saved.has(conflictKey));assert(!pending.has(conflictKey));saveFault='';
 await page.evaluate(()=>{askActiveHistoryKey='ask_history_a';renderAskHistory();});
 await page.fill('#ask-input','甲对话问题');await page.click('#ask-send-btn');await page.waitForFunction(()=>askConversationTasks.get('ask_history_a')?.questionId);
 await page.waitForTimeout(50);assert(pending.has('ask_history_a'));
 await page.fill('#ask-input','甲未发送草稿');
 await page.click('#new-chat');const b=await page.evaluate(()=>getAskHistoryKey(askContext));assert.notEqual(b,'ask_history_a');assert(!(await page.isDisabled('#ask-send-btn')));
 assert.equal(await page.inputValue('#ask-input'),'甲未发送草稿');
 await page.fill('#ask-input','乙对话问题');await page.click('#ask-send-btn');await page.waitForFunction(key=>askConversationTasks.get(key)?.questionId,b);
 await page.waitForTimeout(50);assert(pending.has(b));
 await page.evaluate(()=>openAskHistoryEntry(encodeURIComponent('ask_history_a')));
 assert.equal(await page.inputValue('#ask-input'),'');assert(await page.isDisabled('#ask-send-btn'));assert.equal(await page.locator('#ask-loading-msg').count(),1);
 // Complete B first while A remains selected: A's progress and draft must survive.
 await fulfillAnswer(pending.get(b),{answer:'乙独立答案',model_used:'fixture'});
 await page.waitForFunction(key=>!askConversationTasks.has(key),b);
 assert(!(await page.textContent('#ask-chat-area')).includes('乙独立答案'));assert(await page.isDisabled('#ask-send-btn'));assert.equal(await page.locator('#ask-loading-msg').count(),1);
 await fulfillAnswer(pending.get('ask_history_a'),{answer:'甲独立答案',model_used:'fixture'});await page.waitForFunction(()=>askConversationTasks.size===0);
 assert((await page.textContent('#ask-chat-area')).includes('甲独立答案'));assert.equal(await page.inputValue('#ask-input'),'');
 assert.equal(saved.get('ask_history_a').filter(r=>r.role==='ai').length,1);assert.equal(saved.get(b).filter(r=>r.role==='ai').length,1);
 // Two new requests; stop only C while D stays live.
 await page.click('#new-chat');const c=await page.evaluate(()=>getAskHistoryKey(askContext));await page.fill('#ask-input','丙问题');await page.click('#ask-send-btn');await page.waitForFunction(k=>askConversationTasks.get(k)?.questionId,c);
 await page.click('#new-chat');const d=await page.evaluate(()=>getAskHistoryKey(askContext));await page.fill('#ask-input','丁问题');await page.click('#ask-send-btn');await page.waitForFunction(k=>askConversationTasks.get(k)?.questionId,d);
 await page.evaluate(k=>openAskHistoryEntry(encodeURIComponent(k)),c);await page.locator('.ask-stop-btn').click();await page.waitForFunction(k=>!askConversationTasks.has(k),c);
 assert.equal(cancelled.length,1);assert.equal(await page.evaluate(k=>askConversationTasks.has(k),d),true);
 // Release the aborted C route and complete D to avoid leaking browser fixture jobs.
 try{await fulfillAnswer(pending.get(c),{answer:'不应写入的丙答案'});}catch(_){}
 await fulfillAnswer(pending.get(d),{answer:'丁答案',model_used:'fixture'});await page.waitForFunction(()=>askConversationTasks.size===0);
 assert.equal(saved.get(c).filter(r=>r.role==='ai').length,1);assert(saved.get(c).some(r=>r.content.includes('停止')));
 assert(saved.get(d).some(r=>r.content==='丁答案'));assert.equal(await page.evaluate(()=>loadPendingAskTasks().length),0);
 // Refresh with two in-flight requests, recover both without forcing the visible conversation.
 await page.click('#new-chat');const e=await page.evaluate(()=>getAskHistoryKey(askContext));await page.fill('#ask-input','刷新恢复甲');await page.click('#ask-send-btn');await page.waitForFunction(k=>askConversationTasks.get(k)?.questionId,e);
 await page.click('#new-chat');const f=await page.evaluate(()=>getAskHistoryKey(askContext));await page.fill('#ask-input','刷新恢复乙');await page.click('#ask-send-btn');await page.waitForFunction(k=>askConversationTasks.get(k)?.questionId,f);
 await page.waitForTimeout(50);
 const markers=await page.evaluate(()=>loadPendingAskTasks());assert.equal(markers.length,2);
 await page.reload();
 await page.addScriptTag({content:bootstrap+names.map(extract).join('\n')});
 await page.evaluate(({records,revisions,key})=>{askHistoryCache=new Map(records);askHistoryVersions=new Map(revisions);askActiveHistoryKey=key;renderAskHistory();},{records:[...saved.entries()],revisions:[...versions.entries()],key:f});
 progress.set(pending.get(e).id,{status:'complete',result:{answer:'恢复甲答案',model_used:'fixture'},events:[]});
 progress.set(pending.get(f).id,{status:'complete',result:{answer:'恢复乙答案',model_used:'fixture'},events:[]});
 await page.evaluate(()=>recoverPendingAskTask());await page.waitForFunction(()=>askConversationTasks.size===0);
 assert.equal(await page.evaluate(()=>getAskHistoryKey(askContext)),f);
 assert(saved.get(e).some(r=>r.content==='恢复甲答案'));assert(saved.get(f).some(r=>r.content==='恢复乙答案'));
 assert.equal(await page.evaluate(()=>loadPendingAskTasks().length),0);
 // A failed cancellation acknowledgement must not falsely claim that work stopped.
 await page.click('#new-chat');const g=await page.evaluate(()=>getAskHistoryKey(askContext));await page.fill('#ask-input','停止确认测试');await page.click('#ask-send-btn');await page.waitForFunction(k=>askConversationTasks.get(k)?.questionId,g);
 await page.waitForTimeout(50);rejectCancel=true;await page.locator('.ask-stop-btn').click();await page.waitForFunction(k=>askConversationTasks.get(k)?.recovered,g);
 assert.equal(saved.get(g).filter(r=>r.role==='ai').length,0);
 progress.set(pending.get(g).id,{status:'complete',result:{answer:'原任务仍完成，应正确恢复',model_used:'fixture'},events:[]});
 await page.waitForFunction(()=>askConversationTasks.size===0);assert(saved.get(g).some(r=>r.content==='原任务仍完成，应正确恢复'));
 // HTTP 200 with success:false is not a successful cancellation.
 await page.click('#new-chat');const missingKey=await page.evaluate(()=>getAskHistoryKey(askContext));await page.fill('#ask-input','取消未确认');await page.click('#ask-send-btn');await page.waitForFunction(k=>askConversationTasks.get(k)?.questionId,missingKey);await page.waitForTimeout(50);
 rejectCancel='missing';await page.locator('.ask-stop-btn').click();await page.waitForFunction(k=>askConversationTasks.get(k)?.recovered,missingKey);assert.equal(saved.get(missingKey).filter(r=>r.role==='ai').length,0);
 progress.set(pending.get(missingKey).id,{status:'error',events:[{status:'error',message:'保留原始错误原因'}]});await page.waitForFunction(()=>askConversationTasks.size===0);assert(saved.get(missingKey).some(r=>r.content.includes('保留原始错误原因')));
 // Mutation/retry controls cannot remove a running question or overwrite a draft.
 await page.click('#new-chat');const mutationKey=await page.evaluate(()=>getAskHistoryKey(askContext));await page.fill('#ask-input','进行中的问题');await page.click('#ask-send-btn');await page.waitForFunction(k=>askConversationTasks.get(k)?.questionId,mutationKey);await page.waitForTimeout(50);
 await page.fill('#ask-input','保留草稿');const blocked=await page.evaluate(k=>deleteAskRecord(askHistoryCache.get(k)[0].id),mutationKey);assert.equal(blocked,false);
 await page.evaluate(()=>regenerateAskAnswer('fixture'));assert.equal(await page.inputValue('#ask-input'),'保留草稿');assert.equal(saved.get(mutationKey).length,1);
 await fulfillAnswer(pending.get(mutationKey),{answer:'原问题答案'});await page.waitForFunction(()=>askConversationTasks.size===0);
 // A terminal SSE error must retain its real cause and release this conversation.
 await page.click('#new-chat');const h=await page.evaluate(()=>getAskHistoryKey(askContext));
 await page.fill('#ask-input','短问题');await page.click('#ask-send-btn');await page.waitForFunction(k=>askConversationTasks.get(k)?.questionId,h);
 await page.waitForTimeout(50);assert(pending.get(h).streamed);
 await pending.get(h).route.fulfill({contentType:'text/event-stream',body:'event: error\ndata: '+JSON.stringify({message:'所选 Skill 超过输入预算',status:413})+'\n\n'});
 await page.waitForFunction(()=>askConversationTasks.size===0);
 assert.equal(saved.get(h).filter(r=>r.role==='ai').length,1);assert(saved.get(h).some(r=>r.content.includes('所选 Skill 超过输入预算') && r.contextEligible===false));
 assert.equal(await page.evaluate(()=>loadPendingAskTasks().length),0);
 // CRLF boundaries split across packets and terminal records without a trailing
 // blank line must still return the complete answer immediately.
 const parsed=await page.evaluate(async()=>{
  const encoder=new TextEncoder();
  const chunks=['event: delta\r','\ndata: {"text":"预览"}\r\n\r','\nevent: result\r\ndata: {"answer":"完整终稿"}'];
  const response=new Response(new ReadableStream({start(controller){for(const value of chunks)controller.enqueue(encoder.encode(value));controller.close();}}));
  return readAskStream(response,{historyKey:getAskHistoryKey(askContext),cancelled:false});
 });assert.equal(parsed.answer,'完整终稿');
 // Browsers without response streams use the existing whole-answer endpoint.
 await page.evaluate(()=>{window.ReadableStream=undefined;});await page.click('#new-chat');const j=await page.evaluate(()=>getAskHistoryKey(askContext));
 await page.fill('#ask-input','兼容浏览器');await page.click('#ask-send-btn');await page.waitForFunction(k=>askConversationTasks.get(k)?.questionId,j);await page.waitForTimeout(50);
 assert.equal(pending.get(j).streamed,false);await fulfillAnswer(pending.get(j),{answer:'兼容回答'});await page.waitForFunction(()=>askConversationTasks.size===0);
 assert(saved.get(j).some(r=>r.content==='兼容回答'));
 await page.evaluate(()=>{askHistoryLoadPromise=null;localStorage.setItem('ask_history_imported',JSON.stringify([{id:'legacy-user',role:'user',content:'旧浏览器记录',ts:1}]));});
 await page.addScriptTag({content:extract('ensureAskHistoryLoaded')});
 await page.evaluate(()=>ensureAskHistoryLoaded());
 assert.equal(await page.evaluate(()=>askHistoryVersions.get('ask_history_imported')),1);
 assert.equal(await page.evaluate(()=>localStorage.getItem('ask_history_imported')),null);
 // A persisted selection remains visible and obsolete IDs cannot be sent invisibly.
 await page.evaluate(()=>{const button=document.createElement('button');button.id='ask-skill-btn';const label=document.createElement('span');label.id='ask-skill-btn-label';button.append(label);document.body.append(button);askSkillId='fixture-skill';askSkillList=null;askSkillListLoaded=false;updateAskSkillUI();});
 assert.equal(await page.textContent('#ask-skill-btn-label'),'已选 Skill');await page.evaluate(()=>loadAskSkillList());assert.equal(await page.textContent('#ask-skill-btn-label'),'匿名 Skill');
 await page.evaluate(()=>{askSkillId='removed-skill';localStorage.setItem('ask-skill-id',askSkillId);});await page.evaluate(()=>loadAskSkillList(true));assert.equal(await page.evaluate(()=>askSkillId),'');assert.equal(await page.evaluate(()=>localStorage.getItem('ask-skill-id')),null);
 assert.equal(errors.length,0,errors.join('\n'));
 await browser.close();console.log('Parallel chats: switch/new during generation, reversed completion, isolated progress, drafts, cancellation and multi-request persistence passed.');
})().catch(e=>{console.error(e);process.exit(1);});
