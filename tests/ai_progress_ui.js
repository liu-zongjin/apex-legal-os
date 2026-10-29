const fs = require('fs'), assert = require('assert'), {chromium} = require('playwright');
const src = fs.readFileSync('frontend/app.js','utf8');
function extract(name) {
  const match = new RegExp('^(?:async )?function '+name+'\\(', 'm').exec(src); assert(match, name);
  const rest = src.slice(match.index), next = /\n(?:async )?function [\w]+\(/g; next.lastIndex = 1;
  const end = next.exec(rest), decl = /\n(?:const|let|var|class) \w/.exec(rest);
  return rest.slice(0, Math.min(end ? end.index : rest.length, decl ? decl.index : rest.length));
}
(async () => {
  const browser = await chromium.launch({headless:true, channel:process.env.STELLA_UI_BROWSER || 'chrome'});
  const page = await browser.newPage({viewport:{width:390,height:844}});
  await page.setContent('<div id="ask-panel"><div id="ask-chat-area"></div></div>');
  for (const f of ['frontend/apex-design-tokens.css','frontend/style.css']) await page.addStyleTag({content:fs.readFileSync(f,'utf8').replace(/@import[^;]+;/g,'')});
  await page.addScriptTag({content:`var askContext=null, askResearchProgressTimer=null; var askConversationTasks=new Map([['a',{startedAt:Date.now()}]]); function getAskHistoryKey(){return 'a'} function escapeHtml(s){const e=document.createElement('span');e.textContent=String(s);return e.innerHTML} function stopAskTask(){}\n`+['showAskLoading','renderAskProgressEvents','formatAskProgressData'].map(extract).join('\n')});
  await page.evaluate(()=>{showAskLoading('');renderAskProgressEvents([{stage:'intent_start',message:'正在分析用户原话',status:'running'},{stage:'intent_plan',message:'已提取原话中的任务要点',status:'running',data:{tasks:['比较甲乙'] }},{stage:'coverage_start',message:'正在检查回答',status:'running'}])});
  assert.equal(await page.locator('.ask-research-step').count(), 3);
  assert.equal(await page.locator('.ask-research-step.active').count(), 1);
  assert((await page.locator('.ask-research-steps').innerText()).includes('比较甲乙'));
  const dims = await page.locator('.ask-research-progress').boundingBox();assert(dims.width <= 390);
  await page.evaluate(()=>document.body.classList.add('dark-mode'));
  assert.equal(await page.locator('.ask-research-progress').count(),1);
  await browser.close();console.log('Live progress events, state and narrow theme passed.');
})().catch(e=>{console.error(e);process.exit(1)});
