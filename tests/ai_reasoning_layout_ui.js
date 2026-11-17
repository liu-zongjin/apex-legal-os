/* Production composer markup: files, reasoning and Send must remain independent. */
const fs=require('fs'),assert=require('assert'),{chromium}=require(process.env.STELLA_PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const h=fs.readFileSync('frontend/index.html','utf8'),css=fs.readFileSync('frontend/apex-design-tokens.css','utf8')+'\n'+fs.readFileSync('frontend/style.css','utf8');
 const a=h.indexOf('    <div class="ask-input-area">'),b=h.indexOf('    <div class="ask-preset-menu"',a);
 const content=h.slice(a,b).replace('id="ask-reasoning-picker" hidden','id="ask-reasoning-picker"');
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try{for(const width of [320,375,600,601,760,761,800,1024,1400])for(const attached of [false,true]){
  const page=await browser.newPage({viewport:{width,height:800}});
  await page.setContent('<style>'+css+'</style><div id="ask-panel" class="ask-panel open ask-tabbed fullscreen"><div class="ask-chat-area"></div>'+content+'</div>');
  if(attached)await page.evaluate(()=>{document.querySelector('#ask-panel').classList.add('has-selected-files');const files=document.querySelector('#ask-selected-files');files.hidden=false;files.innerHTML='<span class="ask-selected-file"><span>示例长文件名称_20261117.pdf</span><button type="button" aria-label="移除文件">×</button></span>';});
  const x=await page.evaluate(()=>{
   const rect=selector=>{const r=document.querySelector(selector).getBoundingClientRect();return{x:r.x,right:r.right,y:r.y,bottom:r.bottom};};
   return {area:rect('.ask-input-area'),reason:rect('#ask-reasoning-picker'),send:rect('#ask-send-btn'),actions:rect('.ask-file-actions'),files:rect('#ask-selected-files'),buttons:[...document.querySelectorAll('.ask-file-actions .ask-file-action')].map(n=>({right:n.getBoundingClientRect().right,left:n.getBoundingClientRect().left}))};
  });
  const disjoint=(a,b)=>a.right<=b.x+1||b.right<=a.x+1||a.bottom<=b.y+1||b.bottom<=a.y+1;
  assert(disjoint(x.reason,x.send)&&disjoint(x.actions,x.reason)&&disjoint(x.actions,x.send),'controls overlap at '+width+': '+JSON.stringify(x));
  assert(x.buttons.every(r=>r.left>=0&&r.right<=width+1),'composer action clipped at '+width);
  assert(x.send.right>=x.area.right-65,'Send must stay at the right edge at '+width);
  if(attached)assert(disjoint(x.files,x.actions)&&disjoint(x.files,x.send)&&disjoint(x.files,x.reason),'attachment overlap at '+width+': '+JSON.stringify(x));
  await page.close();
 }}finally{await browser.close();}
 console.log('Composer: 9 widths, with/without attachments, visible file controls and independent reasoning/Send passed');
})().catch(e=>{console.error(e);process.exit(1)});
