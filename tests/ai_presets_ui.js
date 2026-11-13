const fs=require('fs'),assert=require('assert'),{chromium}=require('playwright');
const source=fs.readFileSync('frontend/app.js','utf8'), html=fs.readFileSync('frontend/index.html','utf8');
function extract(name){const match=new RegExp('^(?:async )?function '+name+'\\(','m').exec(source);assert(match,name);const rest=source.slice(match.index),next=/\n(?:async )?function [\w]+\(|\n(?:const|let|var|class) \w/g;next.lastIndex=1;const end=next.exec(rest);return rest.slice(0,end?end.index:rest.length);}
(async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.STELLA_UI_BROWSER||'chrome'}),page=await browser.newPage();
 let presets=[],caseDefault='both';
 await page.route('http://presets.test/**',async route=>{
  const req=route.request(),url=new URL(req.url());
  if(url.pathname==='/') {const start=html.indexOf('    <div class="ask-preset-menu"'),end=html.indexOf('    <div class="ask-skill-menu"',start); return route.fulfill({contentType:'text/html',body:'<div id="ask-panel"><button id="ask-preset-btn" onclick="toggleAskPresetMenu(event)">固定搭配</button>'+html.slice(start,end)+'<select id="ask-model-select"><option value="deepseek-flash">Flash</option><option value="other">Other</option></select></div>'});}
  if(url.pathname==='/api/preferences/case-search-source'){if(req.method()==='PUT')caseDefault=req.postDataJSON().value;return route.fulfill({json:{value:caseDefault}});}
  if(url.pathname==='/api/ai-ask/presets' && req.method()==='POST'){const item={...req.postDataJSON(),id:String(presets.length+1).padStart(32,'0')};presets.push(item);return route.fulfill({json:{preset:item}});}
  if(url.pathname==='/api/ai-ask/presets')return route.fulfill({json:{presets}});
  if(url.pathname.startsWith('/api/ai-ask/presets/')){presets=presets.filter(p=>p.id!==url.pathname.split('/').pop());return route.fulfill({json:{success:true}});}
  return route.fulfill({status:404});
 });
 await page.goto('http://presets.test/');
 const names=['closeAskPresetMenu','renderAskPresets','toggleAskPresetMenu','saveAskPreset','applyAskPreset','deleteAskPreset'];
 await page.addScriptTag({content:`let askPresetItems=[],askContext=null,askIsLoading=false,askSourceMode='mcp:aluris',askSkillId='personal---demo',askSkillListLoaded=true,askSkillList=[{id:'personal---demo'}];const ASK_MODEL_LABELS={},ASK_REASONING_LABELS={fast:'快速',low:'轻度',high:'深度',max:'最深'},ASK_MCP_SOURCE_LABELS={aluris:'法随'},CASE_SEARCH_SOURCE_DEFAULTS={mcp:'mcp',both:'both',public_web:'public_web'};function escapeHtml(s){const x=document.createElement('span');x.textContent=String(s);return x.innerHTML}function closeAskModelMenu(){}function closeAskReasoningMenu(){}function closeAskMcpMenu(){}function closeAskSkillMenu(){}function positionAskPopupMenu(){}function showToast(x){window.lastToast=x}function askReasoningForModel(m){return m==='deepseek-flash'?(localStorage.getItem('ask-reasoning-'+m)||'fast'):''}function applyCaseSearchSourceDefault(x){window.caseSelected=x}function selectAskModel(x){document.getElementById('ask-model-select').value=x}function setAskSourceMode(x){askSourceMode=x}function updateAskSkillUI(){}function updateAskSourceModeUI(){}function syncAskContextToActiveTab(){}async function loadAskSkillList(){}\n`+names.map(extract).join('\n')});
 await page.evaluate(()=>localStorage.setItem('ask-reasoning-deepseek-flash','max'));
 await page.click('#ask-preset-btn');await page.waitForSelector('.ask-preset-empty');await page.fill('#ask-preset-name','我的研究');await page.locator('.ask-preset-form button').click();await page.waitForSelector('.ask-preset-apply');
 assert.deepEqual(Object.fromEntries(Object.entries(presets[0]).filter(([k])=>k!=='id')),{name:'我的研究',model:'deepseek-flash',source_mode:'mcp:aluris',skill_id:'personal---demo',reasoning_effort:'max',case_source:'both'});
 await page.evaluate(()=>{askSourceMode='local_only';askSkillId='';localStorage.setItem('ask-reasoning-deepseek-flash','fast')});caseDefault='mcp';
 await page.click('.ask-preset-apply');await page.waitForFunction(()=>window.lastToast?.startsWith('已应用固定搭配'));
 assert.deepEqual(await page.evaluate(()=>({mode:askSourceMode,skill:askSkillId,effort:localStorage.getItem('ask-reasoning-deepseek-flash'),caseSource:window.caseSelected})),{mode:'mcp:aluris',skill:'personal---demo',effort:'max',caseSource:'both'});
 await page.click('#ask-preset-btn');await page.waitForSelector('.ask-preset-apply');await page.click('.ask-preset-delete');assert.equal(presets.length,1);await page.click('.ask-preset-delete');await page.waitForSelector('.ask-preset-empty');assert.equal(presets.length,0);
 await browser.close();console.log('preset UI passed');
})().catch(e=>{console.error(e);process.exit(1)});
