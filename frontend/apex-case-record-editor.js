/* Same-origin adapter: reuses the knowledge editor and its sanitized renderer. */
(() => {
 let hostPromise;
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
 function mount(input,{editing=true,titleInput,key='record'}={}) {
  if(!input||input.dataset.recordEditor)return;input.dataset.recordEditor='true';
  const panel=document.createElement('div');panel.className='case-record-content';
  const tools=document.createElement('div');tools.className='case-record-tools';
  const preview=document.createElement('article');preview.className='case-record-preview';preview.tabIndex=0;preview.setAttribute('aria-label','记录内容预览');
  const format=document.createElement('button');format.type='button';format.className='btn';format.textContent='设置格式';
  const source=document.createElement('button');source.type='button';source.className='btn';
  tools.append(format,source);input.before(panel);panel.append(tools,input,preview);format.hidden=source.hidden=!editing;
  let showingPreview=true,revision=0,syncing=false,apiReady=null;
  preview.setAttribute('role','textbox');preview.setAttribute('aria-multiline','true');preview.setAttribute('aria-readonly',String(!editing));
  const report=message=>{if(typeof toast==='function')toast(message);else if(typeof showToast==='function')showToast(message);};
  async function refresh(){
   const current=++revision;input.hidden=showingPreview;preview.hidden=!showingPreview;
   source.textContent=showingPreview?'编辑源文':'预览 Markdown';source.setAttribute('aria-pressed',String(showingPreview));preview.textContent=input.value||'暂无内容';
   if(!showingPreview)return;
   try{const {api}=await host();if(input.isConnected&&current===revision){apiReady=api;for(const [key,value] of Object.entries(api.theme?.()||{}))preview.style.setProperty(key,value);preview.innerHTML=api.render(input.value);preview.contentEditable=String(editing);}}catch(error){if(input.isConnected)report(error.message);}
  }
  source.onclick=()=>{showingPreview=!showingPreview;refresh();};
  format.onclick=async()=>{
   if(input.matches(':disabled'))return;format.disabled=true;
   try{
    const {api,frame}=await host();if(!input.isConnected||input.matches(':disabled'))return;
    const opened=api.open({key,title:titleInput?.value||'',content:input.value,
     apply(value){if(!input.isConnected||input.matches(':disabled'))return false;input.value=value.content;if(titleInput)titleInput.value=value.title;input.dispatchEvent(new Event('input',{bubbles:true}));showingPreview=true;refresh();return true;},
     close(){frame?.classList.remove('open');frame?.contentWindow.postMessage({type:'apex:page-visibility',version:1,active:false},location.origin);if(format.isConnected)format.focus();}});
    if(opened){frame?.classList.add('open');frame?.contentWindow.postMessage({type:'apex:page-visibility',version:1,active:true},location.origin);}
   }catch(error){report(error.message);}finally{format.disabled=false;}
  };
  preview.addEventListener('beforeinput',event=>{if(input.matches(':disabled'))event.preventDefault();});
  preview.addEventListener('input',()=>{
   if(!editing||!apiReady)return;
   syncing=true;input.value=apiReady.clean ? apiReady.clean(preview.innerHTML) : preview.innerHTML;
   input.dispatchEvent(new Event('input',{bubbles:true}));syncing=false;
  });
  input.addEventListener('input',()=>{if(showingPreview&&!syncing)refresh();});refresh();
 }
 window.ApexCaseRecordEditor={mount, text(value){const doc=new DOMParser().parseFromString(String(value||'').replace(/<\/(p|div|li|h[1-6]|tr)>/gi,'</$1>\n'),'text/html');return doc.body.textContent||'';}};
})();
