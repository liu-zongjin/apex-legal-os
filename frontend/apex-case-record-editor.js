/* Same-origin adapter: reuses the knowledge editor and its sanitized renderer. */
(() => {
 let hostPromise;
 const controllers=new WeakMap();
 function host() {
  if(window.ApexRecordEditor)return Promise.resolve({api:window.ApexRecordEditor});
  try{if(parent!==window&&parent.ApexRecordEditor)return Promise.resolve({api:parent.ApexRecordEditor});}catch(_){}
  if(hostPromise)return hostPromise;
  hostPromise=new Promise((resolve,reject)=>{
   const frame=document.createElement('iframe');frame.className='case-record-editor-host';frame.title='案件记录格式编辑器';frame.src='/?case-record-editor=1';
   const timer=setTimeout(()=>{frame.remove();hostPromise=null;reject(Error('格式编辑器加载失败，请联网后重试'));},15000);
   frame.onload=()=>{
    const api=frame.contentWindow.ApexRecordEditor;if(!api)return;
    clearTimeout(timer);const style=frame.contentDocument.createElement('style');
    style.textContent='body > :not(#edit-body-modal):not(.toast-container):not(#toast-container){visibility:hidden!important} #edit-body-modal{visibility:visible!important}';frame.contentDocument.head.appendChild(style);frame.contentWindow.postMessage({type:'apex:page-visibility',version:1,active:false},location.origin);resolve({api,frame});
   };document.body.appendChild(frame);
  });return hostPromise;
 }
 function mount(input,{editing=true,titleInput,key='record',position=null}={}) {
  if(!input||input.dataset.recordEditor)return;input.dataset.recordEditor='true';
  const panel=document.createElement('div');panel.className='case-record-content';
  const tools=document.createElement('div');tools.className='case-record-tools';
  const preview=document.createElement('article');preview.className='case-record-preview';preview.tabIndex=0;preview.setAttribute('aria-label','记录内容预览');
  const format=document.createElement('button');format.type='button';format.className='btn';format.textContent='高级格式设置';format.classList.add('case-record-format-button');
  const source=document.createElement('button');source.type='button';source.className='btn case-record-source-button';
  const caption=document.createElement('span');caption.className='case-record-tools-label';caption.textContent='正文';
  tools.append(caption,source,format);input.before(panel);panel.append(tools,input,preview);format.hidden=source.hidden=!editing;
  let showingPreview=!editing||position?.showingPreview!==false,revision=0,syncing=false,apiReady=null;
  preview.setAttribute('role','textbox');preview.setAttribute('aria-multiline','true');preview.setAttribute('aria-readonly',String(!editing));
  preview.dataset.placeholder=editing?'开始记录事实进展、沟通结论或下一步安排…':'尚未填写内容';
  preview.setAttribute('aria-placeholder',preview.dataset.placeholder);
  preview.setAttribute('placeholder',preview.dataset.placeholder);
  const markEmpty=()=>{preview.dataset.empty=String(!preview.textContent.trim()&&!preview.querySelector('img,table'));};
  const restore=snapshot=>{
   if(!snapshot)return;
   requestAnimationFrame(()=>requestAnimationFrame(()=>{
    if(!input.isConnected)return;
    if(!showingPreview){input.scrollTop=snapshot.sourceTop||0;return;}
    if(snapshot.anchor&&apiReady?.restoreScroll)apiReady.restoreScroll(preview,preview,snapshot.anchor);
    else preview.scrollTop=snapshot.top||0;
   }));
  };
  controllers.set(input,{restore,capture:()=>({anchor:showingPreview?apiReady?.captureScroll?.(preview,preview):null,top:preview.scrollTop,sourceTop:input.scrollTop,showingPreview})});
  const report=message=>{if(typeof toast==='function')toast(message);else if(typeof showToast==='function')showToast(message);};
  async function refresh(){
   const current=++revision;input.hidden=showingPreview;preview.hidden=!showingPreview;
   source.textContent=showingPreview?'编辑源文':'预览 Markdown';source.setAttribute('aria-pressed',String(showingPreview));preview.textContent=input.value||'';markEmpty();
   if(!showingPreview){restore(position);position=null;return;}
   try{const {api}=await host();if(input.isConnected&&current===revision){apiReady=api;for(const [key,value] of Object.entries(api.theme?.()||{}))preview.style.setProperty(key,value);preview.innerHTML=input.value.trim()?api.render(input.value):'';markEmpty();preview.contentEditable=String(editing);restore(position);position=null;}}catch(error){if(input.isConnected)report(error.message);}
  }
  source.onclick=()=>{showingPreview=!showingPreview;refresh();};
  format.onclick=async()=>{
   if(input.matches(':disabled'))return;format.disabled=true;
   try{
    const {api,frame}=await host();if(!input.isConnected||input.matches(':disabled'))return;
    const anchor=showingPreview ? api.captureScroll?.(preview,preview) : null;
    const sourceTop=input.scrollTop;
    const opened=api.open({key,anchor,title:titleInput?.value||'',content:input.value,
     apply(value){if(!input.isConnected||input.matches(':disabled'))return false;input.value=value.content;if(titleInput)titleInput.value=value.title;input.dispatchEvent(new Event('input',{bubbles:true}));showingPreview=true;refresh();return true;},
     close(returnAnchor){
      frame?.classList.remove('open');frame?.contentWindow.postMessage({type:'apex:page-visibility',version:1,active:false},location.origin);
      if(format.isConnected)format.focus({preventScroll:true});
      requestAnimationFrame(()=>requestAnimationFrame(()=>{
       if(!input.isConnected)return;
       if(showingPreview)api.restoreScroll?.(preview,preview,returnAnchor||anchor);
       else input.scrollTop=sourceTop;
      }));
     }});
    if(opened){frame?.classList.add('open');frame?.contentWindow.postMessage({type:'apex:page-visibility',version:1,active:true},location.origin);}
   }catch(error){report(error.message);}finally{format.disabled=false;}
  };
  preview.addEventListener('beforeinput',event=>{if(input.matches(':disabled'))event.preventDefault();});
  preview.addEventListener('input',()=>{
   if(!editing||!apiReady)return;
   markEmpty();syncing=true;input.value=preview.dataset.empty==='true'?'':apiReady.clean ? apiReady.clean(preview.innerHTML) : preview.innerHTML;
   input.dispatchEvent(new Event('input',{bubbles:true}));syncing=false;
  });
  input.addEventListener('input',()=>{if(showingPreview&&!syncing)refresh();});refresh();
 }
 window.ApexCaseRecordEditor={mount,capture:input=>controllers.get(input)?.capture(),restore:(input,position)=>controllers.get(input)?.restore(position), text(value){const doc=new DOMParser().parseFromString(String(value||'').replace(/<\/(p|div|li|h[1-6]|tr)>/gi,'</$1>\n'),'text/html');return doc.body.textContent||'';}};
})();
