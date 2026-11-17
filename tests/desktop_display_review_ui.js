/* Native desktop host, real panel transitions and anonymous configured models. */
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
module.exports=async function desktopReview(page,engine){
 const output=process.env.STELLA_DESKTOP_QA_OUTPUT||'.tmp/desktop-display-review-20261117';fs.mkdirSync(output,{recursive:true});
 const failures=[],measurements=[];
 const sizes=[[761,720],[800,720],[960,720],[1000,760],[1001,760],[1024,768],[1100,800],[1101,800],[1280,800],[1440,900],[1920,1080],[2560,1440]];
 const modes=[{name:'tab-history',drawer:false,history:true},{name:'tab-wide',drawer:false,history:false},{name:'drawer-history',drawer:true,history:true},{name:'drawer',drawer:true,history:false}];
 assert(await page.evaluate(()=>document.documentElement.classList.contains('native-shell')),'fixture must use desktop-shell styles');
 await page.addStyleTag({content:'*,*::before,*::after{transition:none!important;animation:none!important}'});
 for(const [width,height] of sizes)for(const dark of [false,true]){
  await page.setViewportSize({width,height});await page.evaluate(d=>document.body.classList.toggle('dark-mode',d),dark);
  for(const mode of modes){
   await page.evaluate(()=>{closeAskPanel();openAskPanel();});
   await page.waitForFunction(()=>[...document.querySelector('#ask-model-select').options].some(o=>o.value==='deepseek-flash'));
   await page.evaluate(()=>selectAskModel('deepseek-flash'));
   if(mode.drawer)await page.evaluate(()=>toggleAskFullscreen());
   await page.evaluate(on=>toggleAskHistorySidebar(on),mode.history);
   for(const attached of [false,true]){
    await page.evaluate(on=>{askPendingLocalFiles=on?[{name:'示例案件材料_20261117.pdf',pending:false}]:[];renderAskSelectedFiles();const input=document.querySelector('#ask-input');input.value='请核对这份示例材料的重点。\n第二行用于检查桌面输入文字。\n第三行应与附件和按钮保持间隔。';autoResizeAskInput(input);},attached);
    await page.evaluate(()=>new Promise(requestAnimationFrame));
    const result=await page.evaluate(()=>{
     const rect=el=>{const r=el.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};};
     const el=s=>document.querySelector(s),visible=n=>n&&getComputedStyle(n).display!=='none'&&n.getBoundingClientRect().width>0;
     const panel=el('#ask-panel'),input=el('#ask-input'),history=el('.ask-history-sidebar'),chat=el('#ask-chat-area'),style=getComputedStyle(input),r=rect(input);
     const nodes={actions:el('.ask-file-actions'),reason:el('#ask-reasoning-picker'),send:el('#ask-send-btn'),files:el('#ask-selected-files')};
     const regions=Object.fromEntries(Object.entries(nodes).filter(([k,n])=>visible(n)&&!n.hidden).map(([k,n])=>[k,rect(n)]));
     const buttons=[...el('.ask-file-actions').querySelectorAll('.ask-file-action')].map(n=>({text:n.textContent.trim(),...rect(n)}));
     const text={left:r.left+parseFloat(style.paddingLeft),right:r.right-parseFloat(style.paddingRight),top:r.top+parseFloat(style.paddingTop),bottom:r.bottom-parseFloat(style.paddingBottom)};
     const hit=n=>{const r=n.getBoundingClientRect(),top=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);return n===top||n.contains(top);};
     const send=nodes.send;send.disabled=false;const sendHit=hit(send);
     const hint=el('#ask-panel-hint'),hintControls=[...hint.querySelectorAll(':scope > button,:scope > label,:scope > .ask-mcp-source-picker')].map(n=>({text:n.textContent.trim(),...rect(n)}));
     return{panel:rect(panel),input:r,text,regions,buttons,hint:rect(hint),hintControls,fileActionsHit:[...el('.ask-file-actions').querySelectorAll('.ask-file-action')].every(hit),history:visible(history)?rect(history):null,chat:rect(chat),sendHit,inputAreaHeight:el('.ask-input-area').getBoundingClientRect().height,ariaHidden:panel.getAttribute('aria-hidden')};
    });
    const data={engine,width,height,dark,mode:mode.name,attached,...result};measurements.push(data);
    const record=(ok,message)=>{if(!ok)failures.push({...data,message});};
    const disjoint=(a,b)=>!a||!b||a.right<=b.left+1||b.right<=a.left+1||a.bottom<=b.top+1||b.bottom<=a.top+1;
    const inside=(a,b)=>a.left>=b.left-1&&a.right<=b.right+1&&a.top>=b.top-1&&a.bottom<=b.bottom+1;
    record(result.panel.left>=-1&&result.panel.right<=width+1&&result.panel.top>=-1&&result.panel.bottom<=height+1,'panel outside desktop window');
    record(result.buttons.every(b=>inside(b,result.regions.actions)),'file action clipped by its own action strip');
    record(result.fileActionsHit,'file action obscured by another desktop region');
    record(result.hintControls.every(b=>inside(b,result.hint)&&b.height<=40),'hint controls wrap vertically or leave toolbar');
    if(mode.history)record(result.input.left>=result.history.right-1,'history covers desktop composer');
    record(result.text.bottom-result.text.top>=40,'less than two visible text lines');
    for(const [a,b] of [['actions','reason'],['actions','send'],['reason','send'],['files','actions'],['files','reason'],['files','send']])record(disjoint(result.regions[a],result.regions[b]),a+' overlaps '+b);
    for(const [key,rect] of Object.entries(result.regions))record(disjoint(rect,result.text),key+' overlaps editable text');
    record(result.sendHit,'Send is obscured');record(result.ariaHidden!=='true','visible desktop panel hidden from accessibility');
    if(width>=1280)record(result.inputAreaHeight<(attached?260:220),'desktop composer consumes excessive height');
    if(!dark&&attached&&[960,1440,1920].includes(width))await page.screenshot({path:path.join(output,`${engine}-${mode.name}-${width}.png`)});
    if(!dark&&attached&&[960,1440].includes(width))for(const [button,menu,close] of [
     ['#ask-preset-btn','#ask-preset-menu','closeAskPresetMenu'],
     ['#ask-skill-btn','#ask-skill-menu','closeAskSkillMenu'],
     ['#ask-reasoning-btn','#ask-reasoning-menu','closeAskReasoningMenu'],
     ['#ask-mcp-source-btn','#ask-mcp-source-menu','closeAskMcpMenu']
    ]){
     await page.locator(button).click();await page.locator(menu).waitFor({state:'visible'});
     const bounds=await page.locator(menu).evaluate(n=>{const r=n.getBoundingClientRect();return{left:r.left,right:r.right,top:r.top,bottom:r.bottom};});
     record(bounds.left>=-1&&bounds.right<=width+1&&bounds.top>=-1&&bounds.bottom<=height+1,menu+' outside desktop window');
     await page.evaluate(name=>window[name](),close);
    }
   }
  }
 }
 await page.evaluate(()=>{askPendingLocalFiles=[];renderAskSelectedFiles();closeAskPanel();});
 fs.writeFileSync(path.join(output,engine+'-results.json'),JSON.stringify({failures,measurements},null,2));
 assert.deepEqual(failures.map(f=>({width:f.width,mode:f.mode,attached:f.attached,dark:f.dark,message:f.message})),[],'desktop display failures');
 console.log(`${engine}: desktop ${sizes.length} sizes × 4 modes × light/dark × attachment states passed`);
};
