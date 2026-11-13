const fs = require('fs'), assert = require('assert'), {chromium} = require('playwright');
const source = fs.readFileSync('frontend/app.js','utf8');
function extract(name) {
  const match = new RegExp('^function '+name+'\\(', 'm').exec(source); assert(match,name);
  const rest = source.slice(match.index), next = /\n(?:async )?function [\w]+\(|\n(?:const|let|var|class) \w/g;
  next.lastIndex = 1; const end = next.exec(rest); return rest.slice(0,end ? end.index : rest.length);
}
(async()=>{
  const browser = await chromium.launch({headless:true,channel:process.env.STELLA_UI_BROWSER||'chrome'});
  const page = await browser.newPage({viewport:{width:1400,height:800}});
  await page.setContent('<style>body{margin:0}#ask-panel{position:relative;margin-left:200px;width:900px;height:700px}#ask-skill-btn{position:absolute;left:430px;top:640px;width:80px;height:30px}#ask-skill-menu{position:absolute;width:380px;height:200px;box-sizing:border-box}#ask-model-picker-btn{position:absolute;right:30px;top:10px;width:80px}#ask-model-menu{position:absolute;width:300px;height:100px}</style><div id="ask-panel"><button id="ask-skill-btn">Skill</button><div id="ask-skill-menu"></div><button id="ask-model-picker-btn">模型</button><div id="ask-model-menu"></div></div>');
  await page.addScriptTag({content:['positionAskPopupMenu','positionAskSkillMenu','repositionAskPopupMenus'].map(extract).join('\n')});
  const measure = ()=>page.evaluate(()=>{const b=document.querySelector('#ask-skill-btn').getBoundingClientRect(),m=document.querySelector('#ask-skill-menu').getBoundingClientRect(),p=document.querySelector('#ask-panel').getBoundingClientRect(),mb=document.querySelector('#ask-model-picker-btn').getBoundingClientRect(),mm=document.querySelector('#ask-model-menu').getBoundingClientRect();return {button:b.x,menu:m.x,right:m.right,edge:p.right,modelRight:mb.right,modelMenuRight:mm.right,top:m.top,buttonTop:b.top}});
  await page.evaluate(()=>{positionAskSkillMenu(document.querySelector('#ask-skill-btn'),document.querySelector('#ask-skill-menu'));positionAskPopupMenu(document.querySelector('#ask-model-picker-btn'),document.querySelector('#ask-model-menu'))});
  let value=await measure(); assert(Math.abs(value.menu-value.button)<1,JSON.stringify(value)); assert(value.top<value.buttonTop); assert(Math.abs(value.modelRight-value.modelMenuRight)<1);
  await page.evaluate(()=>{document.querySelector('#ask-skill-btn').style.left='820px';repositionAskPopupMenus()});
  value=await measure(); assert(value.right<=value.edge-11,JSON.stringify(value)); assert(value.menu<value.button);
  await page.setViewportSize({width:380,height:800});
  await page.evaluate(()=>{const p=document.querySelector('#ask-panel');p.style.marginLeft='0';p.style.width='380px';document.querySelector('#ask-skill-btn').style.left='50px';repositionAskPopupMenus()});
  value=await measure();assert(value.menu>=11 && value.right<=380-11,JSON.stringify(value));
  await browser.close();console.log('skill popup positioning passed');
})().catch(error=>{console.error(error);process.exit(1)});
