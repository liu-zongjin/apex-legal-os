/* Shared progress, staged exports and explicit mailbox destination confirmation. */
(function () {
  'use strict';
  const BASE = '/api/download-center', KEY = 'apex_download_center_records';
  const tasks = new Map();
  let lastTask = null;
  const blobTasks=new WeakMap(),responseTasks=new WeakMap(),urlRecords=new Map();
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const active = () => !document.hidden && window.ApexLifecycle?.active !== false;
  const running = item => ['preparing','downloading','saving','queued','packing'].includes(item.status);
  const size = bytes => Number(bytes||0)<1048576 ? `${(Number(bytes||0)/1024).toFixed(1)} KB` : `${(Number(bytes||0)/1048576).toFixed(1)} MB`;
  const css = document.createElement('link'); css.rel='stylesheet'; css.href='/static/apex-downloads.css?v=1'; document.head.append(css);
  if(!document.querySelector('link[href*="apex-design-tokens"]')){const tokens=document.createElement('link');tokens.rel='stylesheet';tokens.href='/static/apex-design-tokens.css?v=2';document.head.append(tokens);}
  async function api(path, options={}) {
    const response = await fetch(BASE+path, options);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '下载操作失败');
    return data;
  }
  function publish(task) {
    try {
      const prior = JSON.parse(localStorage.getItem(KEY)||'[]').filter(r=>String(r.id)!==String(task.id));
      const row = {...task,name:task.name,createdAt:task.created_at,format:task.name?.split('.').pop()?.toUpperCase()};
      delete row.timer; delete row.queue; delete row.polling; delete row.watching;
      localStorage.setItem(KEY,JSON.stringify([row,...prior].slice(0,200)));
    } catch (_) {}
    render();
  }
  function progressHtml(item) {
    const known = Number(item.total_bytes)>0;
    const success = item.status==='completed';
    const percent = success?100:Math.min(99,Math.floor(100*Number(item.received_bytes||0)/(Number(item.total_bytes)||1)));
    return `<div class="ad-progress ${!known&&running(item)?'ad-indeterminate':''}"><div class="ad-progress-head"><strong>${escape(item.phase||item.name||'正在下载')}</strong><span>${success?'已完成':known?percent+'%':running(item)?'进行中':escape({partial:'部分完成',failed:'失败',interrupted:'已中断',needs_action:'需验证'}[item.status]||item.status)}</span></div>
      <div class="ad-track" role="progressbar" aria-label="文件下载进度" aria-valuemin="0" aria-valuemax="100" ${known||success?`aria-valuenow="${percent}"`:''}><i style="width:${known||success?percent:30}%"></i></div>
      <div class="ad-progress-meta">${escape(item.name||'')}<br>${size(item.received_bytes)}${known?' / '+size(item.total_bytes):' · 总大小待确认'}${item.total_files>1?` · 已完成 ${Number(item.completed_files)||0}/${item.total_files} 份`:''}</div>${item.error?`<p class="ad-error">${escape(item.error)}</p>`:''}</div>`;
  }
  function render() {
    let host=document.getElementById('apex-download-progress');
    if(!host) { host=document.createElement('section');host.id='apex-download-progress';host.className='ad-floating';document.body.append(host); }
    const shown=[...tasks.values()].slice(-3);
    host.hidden=!shown.length;
    host.innerHTML=shown.map(item=>`<article data-download-id="${escape(item.id)}"><div class="ad-float-title"><button class="ad-link" data-center>下载中心 · ${escape(item.source)}</button><button class="ad-dismiss" data-dismiss="${escape(item.id)}" aria-label="收起进度提示">×</button></div>${progressHtml(item)}</article>`).join('');
    host.querySelectorAll('[data-dismiss]').forEach(button=>button.onclick=()=>{const item=tasks.get(button.dataset.dismiss); if(item){clearTimeout(item.timer);tasks.delete(item.id);}render();});
    host.querySelectorAll('[data-center]').forEach(button=>button.onclick=openCenter);
  }
  function openCenter() { if(window.parent!==window)window.parent.postMessage({type:'apex:open-download-center',version:1},location.origin);else if(window.openDownloadCenterTab)window.openDownloadCenterTab();else location.href='/download-center'; }
  function update(task, values, persist=true) {
    Object.assign(task,values);publish(task);
    if(persist) {
      task.queue=(task.queue||Promise.resolve()).catch(()=>{}).then(()=>api('/records/'+task.id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(values)})).catch(error=>{task.connectionError=error.message;return null;});
    }
  }
  function context(url) {
    const path=String(url);
    const caseId=Number(new URLSearchParams(location.search).get('case_id')||0);
    if(/invoices|invoice-automation/.test(path))return {source:'发票中心',category:'invoice',purpose:'invoice',case_id:0,name:/\/invoices$/.test(path)?'发票检索与归集':'发票下载.zip'};
    if(/ai-ask|research/.test(path))return {source:'AI增强',category:'ai',purpose:caseId?'case':'other',case_id:caseId,name:'AI导出.docx'};
    if(/court-online/.test(path))return {source:'一张网',category:'court',purpose:'case',case_id:caseId,name:'法院材料'};
    const names={'suohan':'所函','power-attorney':'授权委托书','rep-identity-cert':'法定代表人身份证明','business-approval':'业务审批表','document-bundle':'文书合集'};
    const key=Object.keys(names).find(key=>path.includes('/'+key+'/')||path.endsWith('/'+key));
    return {source:key?'文书生成 · '+names[key]:'其他导出',category:key?'document':'export',purpose:caseId?'case':'other',case_id:caseId,name:key?names[key]+(key==='document-bundle'?'.zip':'.docx'):'导出文件'};
  }
  function retain(){while(tasks.size>=64){const old=[...tasks].find(([,task])=>!running(task));if(!old)break;clearTimeout(old[1].timer);tasks.delete(old[0]);}}
  async function begin(metadata) {
    retain();
    if([...tasks.values()].filter(running).length>=6)throw new Error('正在下载的文件较多，请稍后重试');
    const task=await api('/records',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(metadata)});
    tasks.set(task.id,task);lastTask=task;publish(task);return task;
  }
  async function read(response,task) {
    try {
      const length=response.headers.get('content-encoding')?0:Number(response.headers.get('content-length')||0);
      const disposition=response.headers.get('content-disposition')||'';
      const match=disposition.match(/filename\*=UTF-8''([^;]+)/i)||disposition.match(/filename="?([^";]+)/i);
      const name=match?decodeURIComponent(match[1]):task.name;
      update(task,{name,status:'downloading',phase:'正在下载文件',total_bytes:length});
      const reader=response.body?.getReader();let chunks=[],received=0,last=0;
      if(reader) {
        while(true) {const next=await reader.read();if(next.done)break;received+=next.value.byteLength;
          if(received>500*1048576){await reader.cancel();throw new Error('文件超过 500MB');}
          chunks.push(next.value);
          if(Date.now()-last>400){update(task,{received_bytes:received});last=Date.now();}
        }
      } else { chunks=[await task.nativeArrayBuffer()];received=chunks[0].byteLength; }
      let blob=new Blob(chunks,{type:response.headers.get('content-type')||'application/octet-stream'});
      if(task.category==='ai'&&name.toLowerCase().endsWith('.md')){const text=new TextDecoder('utf-8').decode(await blob.arrayBuffer()).replace(/^\uFEFF/,'');blob=new Blob(['\uFEFF',text],{type:'application/octet-stream'});}
      update(task,{received_bytes:received,total_bytes:received,status:'saving',phase:'正在保存下载记录和文件'});
      await task.queue;
      const form=new FormData();form.append('file',blob,name);
      const saved=await api('/records/'+task.id+'/file',{method:'POST',body:form});
      update(task,saved,false);lastTask=task;blobTasks.set(blob,task.id);
      return blob;
    } catch(error) {update(task,{status:'failed',phase:'下载失败',error:error.message});throw error;}
  }
  async function monitoredFetch(url, options={}, metadata={}) {
    const descriptor={...context(url),...metadata};
    try{const account=JSON.parse(typeof options.body==='string'?options.body:'{}').account;if(descriptor.category==='invoice'&&account){const label={qq_mail:'QQ邮箱',qq_exmail:'腾讯企业邮箱',netease_exmail:'网易企业邮箱'}[account];if(label)descriptor.source='发票中心 · '+label;}}catch(_){}
    const task=await begin(descriptor);
    try {
      const response=await fetch(url,options);
      if(!response.ok){update(task,{status:'failed',error:'请求失败（HTTP '+response.status+'）',phase:'下载失败'});return response;}
      responseTasks.set(response,task);
      const nativeArrayBuffer=response.arrayBuffer.bind(response);
      task.nativeArrayBuffer=nativeArrayBuffer;
      // Only the explicitly opted-in export response is instrumented.
      if(!response.body)response.arrayBuffer=nativeArrayBuffer;
      Object.defineProperty(response,'blob',{value:()=>read(response,task)});
      Object.defineProperty(response,'arrayBuffer',{value:async()=>{const blob=await read(response,task);return blob.arrayBuffer();}});
      if((response.headers.get('content-type')||'').includes('application/json')) {
        const nativeJson=response.json.bind(response);
        Object.defineProperty(response,'json',{value:async()=>{const result=await nativeJson();
          if(result.id&&result.absolute_path){const saved=await api('/case-files/'+result.id+'/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({identity:task.id})});update(task,{...saved,phase:'已保存到案件文件夹'},false);}
          else if(Array.isArray(result.invoices)){const saved=await api('/invoice-results',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({identity:task.id,invoices:result.invoices})});update(task,saved,false);}
          else if(Array.isArray(result.files)){for(const file of result.files)if(file.id)await api('/case-files/'+file.id+'/register',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});update(task,{status:'completed',phase:'文书合集已存入案件',completed_files:result.files.length,total_files:result.files.length});}
          else update(task,{status:'completed',phase:'操作已完成'});
          return result;}});
      }
      return response;
    }catch(error){update(task,{status:'failed',phase:'下载失败',error:error.message});throw error;}
  }
  function record(name,category,source) {
    if(lastTask&&lastTask.status==='completed'&&!lastTask.recorded&&lastTask.category===category) {lastTask.recorded=true;update(lastTask,{name});return;}
    begin({name,category,source,purpose:category==='invoice'?'invoice':'other'}).then(task=>update(task,{status:'completed',phase:'已交给系统下载',destination:'系统下载位置（历史记录未定位）'})).catch(()=>{});
  }
  async function poll(task) {
    if(task.polling||!task.watching||!active())return;
    task.polling=true;
    try{const next=await api('/records/'+task.id);update(task,next,false);if(!running(next))task.watching=false;}
    catch(error){task.error='进度连接暂时中断，正在重连…';render();}
    finally{task.polling=false;if(task.watching&&active())task.timer=setTimeout(()=>{task.timer=null;poll(task);},650);}
  }
  function watch(item) {retain();const task={...item,watching:true};tasks.set(task.id,task);publish(task);poll(task);return task;}
  function resume(){tasks.forEach(task=>{if(!active()){clearTimeout(task.timer);task.timer=null;}else if(task.watching&&!task.timer)poll(task);});}
  window.addEventListener('pagehide',()=>tasks.forEach(task=>{if(running(task)&&!task.watching&&!task.nativeId)navigator.sendBeacon?.(BASE+'/records/'+task.id+'/interrupt',new Blob(['{}'],{type:'application/json'}));}));
  document.addEventListener('visibilitychange',resume);window.addEventListener('apex:page-visibility',resume);
  async function chooseDestination(options={}) {
    return new Promise(resolve=>{
      const prior=document.activeElement;
      const mask=document.createElement('div');mask.className='ad-modal-mask';
      mask.innerHTML=`<section class="ad-modal" role="dialog" aria-modal="true" aria-labelledby="ad-title"><h2 id="ad-title">${escape(options.title||'选择附件用途与保存位置')}</h2><p>发票与案件材料分开归集。案件材料保存前，请确认案件及绑定的本地文件夹。</p>
        ${options.caseOnly?'':`<div class="ad-purpose" role="group" aria-label="附件用途"><button data-purpose="case" class="ad-selected">案件材料</button><button data-purpose="invoice">发票归集</button><button data-purpose="other">其他附件</button></div>`}
        <div id="ad-case-section"><label for="ad-case-input">目标案件</label><div class="ad-case-picker"><input id="ad-case-input" placeholder="搜索案件名称、案号、当事人" autocomplete="off"><div id="ad-case-menu" class="apex-case-menu" hidden></div></div><p id="ad-binding">请选择案件，确认已绑定文件夹。</p></div><p id="ad-error" class="ad-error" role="status"></p>
        <footer><button data-cancel>取消</button><button data-confirm class="ad-primary">${options.caseOnly?'确认并保存':'确认并下载'}</button></footer></section>`;
      document.body.append(mask);let purpose='case',caseId=0,binding=null;
      const finish=value=>{window.ApexCasePicker?.closeAll();mask.remove();prior?.focus();resolve(value);};
      mask.querySelector('[data-cancel]').onclick=()=>finish(null);
      mask.addEventListener('keydown',event=>{if(event.key==='Escape')finish(null);if(event.key==='Tab'){const focus=[...mask.querySelectorAll('button,input')].filter(e=>!e.disabled&&e.offsetParent!==null);if(event.shiftKey&&document.activeElement===focus[0]){event.preventDefault();focus.at(-1).focus();}else if(!event.shiftKey&&document.activeElement===focus.at(-1)){event.preventDefault();focus[0].focus();}}});
      mask.querySelectorAll('[data-purpose]').forEach(button=>button.onclick=()=>{purpose=button.dataset.purpose;mask.querySelectorAll('[data-purpose]').forEach(b=>b.classList.toggle('ad-selected',b===button));mask.querySelector('#ad-case-section').hidden=purpose!=='case';mask.querySelector('#ad-error').textContent='';});
      const request=async url=>{const r=await fetch(url);const data=await r.json();if(!r.ok)throw new Error(data.detail||'案件加载失败');return data;};
      if(window.ApexCasePicker)window.ApexCasePicker.attach({input:mask.querySelector('#ad-case-input'),menu:mask.querySelector('#ad-case-menu'),request,
        onInput:()=>{caseId=0;binding=null;mask.querySelector('#ad-binding').textContent='请选择案件';},
        onSelect:async selected=>{caseId=Number(selected.id);binding=null;mask.querySelector('#ad-error').textContent='';const id=caseId;mask.querySelector('#ad-case-input').value=selected.title;mask.querySelector('#ad-binding').textContent='正在核对绑定文件夹…';try{const value=await request('/api/case-manager/cases/'+id+'/folder-binding');if(caseId!==id)return;binding=value;mask.querySelector('#ad-binding').textContent=value.available?'保存到：'+value.real_path:'该案件未绑定可用文件夹，请先在案件管理中绑定';}catch(error){mask.querySelector('#ad-binding').textContent=error.message;}}});
      else mask.querySelector('#ad-error').textContent='案件选择器未加载，请刷新页面';
      mask.querySelector('[data-confirm]').onclick=()=>{if(purpose==='case'&&(!caseId||!binding?.available)){mask.querySelector('#ad-error').textContent='请选择已绑定可用本地文件夹的案件';return;}finish({purpose,case_id:purpose==='case'?caseId:0,confirmed:true});};
      mask.querySelector('[data-cancel]').focus();
    });
  }
  async function mail(options) {const destination=await chooseDestination();if(!destination)return null;const item=await api('/mail-jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...options,...destination})});return watch(item);}
  async function court(options){const item=await api('/court-jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(options)});return watch(item);}
  async function saveCase(identity){const destination=await chooseDestination({title:'确认保存到案件文件夹',caseOnly:true});if(!destination)return null;return api('/records/'+identity+'/save-case',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(destination)});}
  // Direct ZIP download links also receive actual transfer progress.
  document.addEventListener('click',event=>{const link=event.target.closest?.('a[href]');if(!link||link.target==='_blank')return;const url=link.getAttribute('href');if(!/^\/api\/qq-mail\/invoice-automation\/collections\/[^/]+\/download$/.test(url||''))return;event.preventDefault();monitoredFetch(url).then(r=>r.blob()).then(blob=>{const a=document.createElement('a');a.href=objectURL(blob);a.download=lastTask.name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}).catch(()=>{});});
  function confirmAction(title,detail){return new Promise(resolve=>{const prior=document.activeElement,mask=document.createElement('div');mask.className='ad-modal-mask';mask.innerHTML=`<section class="ad-modal" role="dialog" aria-modal="true"><h2>${escape(title)}</h2><p>${escape(detail)}</p><footer><button data-no>取消</button><button data-yes class="ad-primary">确认清理</button></footer></section>`;document.body.append(mask);const finish=value=>{mask.remove();prior?.focus();resolve(value);};mask.querySelector('[data-no]').onclick=()=>finish(false);mask.querySelector('[data-yes]').onclick=()=>finish(true);mask.onkeydown=e=>{if(e.key==='Escape')finish(false);if(e.key==='Tab'){e.preventDefault();(document.activeElement===mask.querySelector('[data-no]')?mask.querySelector('[data-yes]'):mask.querySelector('[data-no]')).focus();}};mask.querySelector('[data-no]').focus();});}
  function rememberBlob(response,blob){const task=responseTasks.get(response);if(task)blobTasks.set(blob,task.id);return blob;}
  function objectURL(blob){const id=blobTasks.get(blob);const url=id?new URL(BASE+'/records/'+id+'/file',location.origin).href:URL.createObjectURL(blob);if(id){urlRecords.set(url,id);while(urlRecords.size>128)urlRecords.delete(urlRecords.keys().next().value);}return url;}
  const nativeTransfers=new Map(),nativeIds=new Map();
  function nativeCandidates(){return [...new Set([...tasks.values(),lastTask].filter(Boolean))];}
  function nativeRecord(event){return urlRecords.get(event.url)||nativeIds.get(event.id)||event.record_id||(!event.url||event.url.startsWith('blob:')?nativeCandidates().find(task=>task.name===event.name&&task.path&&(!task.nativeId||task.nativeId===event.id))?.id:'')||'';}
  function nativeMatches(event){return urlRecords.has(event.url)||((!event.url||event.url.startsWith('blob:'))&&nativeCandidates().some(task=>task.name===event.name&&task.path&&(!task.nativeId||task.nativeId===event.id)));}
  async function nativeEvent(event){
    let transfer=nativeTransfers.get(event.id);
    if(!transfer){
      const mapped=urlRecords.get(event.url);
      const task=nativeCandidates().reverse().find(task=>task.path&&(mapped?task.id===mapped:(!event.url||event.url.startsWith('blob:'))&&task.name===event.name)&&(!task.nativeId||task.nativeId===event.id));
      if(task){task.nativeId=event.id;transfer=Promise.resolve(task);}
      else if(event.record_id){transfer=api('/records/'+event.record_id).then(task=>{tasks.set(task.id,task);return task;});}
      else if(event.url?.includes('/court-online/downloads/')){transfer=api('/native-ticket',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:event.url,native_id:event.id})}).then(task=>{tasks.set(task.id,task);publish(task);return task;});}
      else return;
      nativeTransfers.set(event.id,transfer);
    }
    let task;
    try{task=await transfer;task.nativeId=event.id;nativeIds.set(event.id,task.id);while(nativeIds.size>128)nativeIds.delete(nativeIds.keys().next().value);
      if(event.status==='completed'){
        update(task,{status:'saving',phase:'正在核对最终保存位置'});await task.queue;
        const saved=await api('/records/'+task.id+'/native-saved',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:event.path})});update(task,saved,false);nativeTransfers.delete(event.id);nativeIds.delete(event.id);
      }else if(event.status==='failed'){update(task,{status:'failed',phase:'系统保存未完成',error:event.error||'下载未完成'});nativeTransfers.delete(event.id);nativeIds.delete(event.id);}
      else{update(task,{status:event.status==='preparing'?'preparing':'downloading',phase:event.status==='preparing'?'等待选择系统保存位置':'正在保存到所选位置',received_bytes:event.received_bytes||0,total_bytes:event.total_bytes||task.total_bytes||0});}
    }catch(error){if(task)update(task,{status:'partial',phase:'系统保存位置尚未确认',error:error.message});nativeTransfers.delete(event.id);console.warn('Native download tracking:',error.message);}
  }
  window.ApexDownloads={fetch:monitoredFetch,record,watch,mail,court,saveCase,progressHtml,size,escape,api,openCenter,confirmAction,objectURL,rememberBlob,nativeMatches,nativeRecord,nativeEvent};
})();
