/* Public distribution only: packaging supplies the public feed meta tag. */
(() => {
  'use strict';
  const meta=document.querySelector('meta[name="stella-system-messages"]');
  if(!meta || window.top!==window)return;
  let endpoint;
  try {
    endpoint=new URL(meta.content);
    if(endpoint.protocol!=='https:' || endpoint.pathname!=='/v1/messages' || endpoint.username || endpoint.password || endpoint.search || endpoint.hash)return;
  }catch{return;}
  const CACHE='stella.system-messages.v1', READ='stella.system-messages.read.v1';
  let messages=[], read=new Set(), controller=null, timer=null, lastFocus=null;
  function store(key,value){try{localStorage.setItem(key,JSON.stringify(value));}catch{}}
  function validate(data) {
    if(!Array.isArray(data?.messages) || data.messages.length>100)throw new Error('invalid_feed');
    const ids=new Set();
    return data.messages.map(item=>{
      if(!item || !/^[0-9a-f-]{36}$/.test(item.id) || ids.has(item.id) ||
        typeof item.title!=='string' || !item.title.trim() || item.title.length>80 ||
        typeof item.body!=='string' || !item.body.trim() || item.body.length>6000 ||
        !Number.isSafeInteger(item.published_at) || item.published_at<=0)throw new Error('invalid_feed');
      ids.add(item.id);return {id:item.id,title:item.title,body:item.body,published_at:item.published_at};
    });
  }
  try {messages=validate(JSON.parse(localStorage.getItem(CACHE)));}catch{}
  try {const saved=JSON.parse(localStorage.getItem(READ));if(Array.isArray(saved))read=new Set(saved.filter(id=>typeof id==='string').slice(-200));}catch{}
  const anchor=document.querySelector('.tab-bar-actions');if(!anchor)return;
  const button=document.createElement('button');
  button.id='system-messages-btn';button.type='button';button.className='tab-bar-action-btn stella-messages-trigger';
  button.title='系统消息';button.setAttribute('aria-label','系统消息');button.setAttribute('aria-haspopup','dialog');
  button.innerHTML='<svg width="17" height="17" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M15 7a5 5 0 0 0-10 0c0 5-2 5-2 6.5h14C17 12 15 12 15 7ZM8 16a2.2 2.2 0 0 0 4 0" stroke="currentColor" stroke-width="1.45" stroke-linecap="round" stroke-linejoin="round"/></svg><span class="stella-messages-dot" hidden></span>';
  anchor.insertBefore(button,document.getElementById('download-center-btn'));
  // Custom modal also supports WebKit shipped with macOS 12.0 (before <dialog>).
  const mask=document.createElement('div');mask.className='stella-messages-mask';mask.hidden=true;
  const dialog=document.createElement('section');dialog.className='stella-messages';dialog.id='system-messages-dialog';
  dialog.setAttribute('role','dialog');dialog.setAttribute('aria-modal','true');dialog.tabIndex=-1;
  dialog.setAttribute('aria-labelledby','system-messages-title');
  dialog.innerHTML='<header class="stella-messages-head"><div><p>STELLA</p><h2 id="system-messages-title">系统消息</h2></div><button type="button" class="stella-messages-close" aria-label="关闭系统消息">✕</button></header><div class="stella-messages-tools"><span role="status" id="system-messages-status">正在检查新消息…</span><button type="button" id="system-messages-read">全部已读</button></div><div class="stella-messages-list"></div>';
  mask.append(dialog);document.body.append(mask);
  const list=dialog.querySelector('.stella-messages-list'),status=dialog.querySelector('[role="status"]'),markAll=dialog.querySelector('#system-messages-read');
  function updateUnread() {
    const unread=messages.filter(item=>!read.has(item.id)).length;
    button.querySelector('span').hidden=unread===0;
    button.setAttribute('aria-label',unread?`系统消息，${unread} 条未读`:'系统消息');
    button.title=unread?`系统消息 · ${unread} 条未读`:'系统消息';
    markAll.disabled=unread===0;
  }
  function saveRead() {read=new Set(messages.filter(item=>read.has(item.id)).map(item=>item.id));store(READ,[...read]);updateUnread();}
  function render() {
    list.replaceChildren(...messages.map(item=>{
      const details=document.createElement('details');details.className='stella-message';
      details.classList.toggle('unread',!read.has(item.id));
      const summary=document.createElement('summary'),title=document.createElement('strong'),date=document.createElement('time'),body=document.createElement('div');
      title.textContent=item.title;date.dateTime=new Date(item.published_at*1000).toISOString();
      date.textContent=new Date(item.published_at*1000).toLocaleString('zh-CN');body.textContent=item.body;body.className='stella-message-body';
      summary.append(title,date);details.append(summary,body);
      details.addEventListener('toggle',()=>{if(details.open){read.add(item.id);details.classList.remove('unread');saveRead();}});
      return details;
    }));
    if(!messages.length){const empty=document.createElement('p');empty.className='stella-messages-empty';empty.textContent='暂无系统消息';list.append(empty);}
    updateUnread();
  }
  async function refresh() {
    if(document.hidden || controller)return;
    const active=new AbortController();controller=active;
    const timeout=setTimeout(()=>active.abort(),10000);
    try {
      const response=await fetch(endpoint.href,{credentials:'omit',cache:'no-store',signal:active.signal,referrerPolicy:'no-referrer'});
      if(!response.ok)throw new Error('feed_unavailable');
      // Bound even a malformed or compromised endpoint before parsing or caching.
      const reader=response.body.getReader(),chunks=[];let length=0;
      while(true){const {done,value}=await reader.read();if(done)break;length+=value.byteLength;if(length>2600000){await reader.cancel();throw new Error('feed_too_large');}chunks.push(value);}
      const bytes=new Uint8Array(length);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
      const next=validate(JSON.parse(new TextDecoder().decode(bytes)));
      const changed=JSON.stringify(messages)!==JSON.stringify(next);messages=next;if(!mask.hidden)messages.forEach(item=>read.add(item.id));
      store(CACHE,{messages});saveRead();if(changed)render();
      status.textContent='已同步 · '+new Date().toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'});
    }catch {
      if(controller===active)status.textContent=messages.length?'暂时无法同步，显示上次获取的消息':'暂时无法连接，联网后将自动重试';
    }finally{clearTimeout(timeout);if(controller===active)controller=null;}
  }
  let background=[],previousOverflow='';
  function close() {
    mask.hidden=true;document.body.style.overflow=previousOverflow;
    for(const [node,value,inert] of background){if(value===null)node.removeAttribute('aria-hidden');else node.setAttribute('aria-hidden',value);node.inert=inert;}
    background=[];lastFocus?.focus();
  }
  button.addEventListener('click',()=>{
    lastFocus=document.activeElement;previousOverflow=document.body.style.overflow;
    background=[...document.body.children].filter(node=>node!==mask).map(node=>[node,node.getAttribute('aria-hidden'),node.inert]);
    for(const [node] of background){node.setAttribute('aria-hidden','true');node.inert=true;}
    document.body.style.overflow='hidden';mask.hidden=false;messages.forEach(item=>read.add(item.id));saveRead();render();dialog.querySelector('button').focus();refresh();
  });
  dialog.querySelector('.stella-messages-close').addEventListener('click',close);
  mask.addEventListener('click',event=>{if(event.target===mask)close();});
  document.addEventListener('keydown',event=>{
    if(mask.hidden)return;
    if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close();}
    if(event.key==='Tab'){
      const targets=[...dialog.querySelectorAll('button:not(:disabled),summary')];
      const index=targets.indexOf(document.activeElement);
      if(event.shiftKey && index<=0){event.preventDefault();targets[targets.length-1]?.focus();}
      else if(!event.shiftKey && (index<0 || index===targets.length-1)){event.preventDefault();targets[0]?.focus();}
    }
  },true);
  markAll.addEventListener('click',()=>{messages.forEach(item=>read.add(item.id));saveRead();list.querySelectorAll('.unread').forEach(el=>el.classList.remove('unread'));});
  function schedule() {clearInterval(timer);timer=null;if(document.hidden){controller?.abort();controller=null;return;}refresh();timer=setInterval(refresh,300000);}
  document.addEventListener('visibilitychange',schedule);
  window.addEventListener('online',()=>{controller?.abort();controller=null;refresh();});
  window.addEventListener('pagehide',()=>{clearInterval(timer);controller?.abort();});
  window.addEventListener('pageshow',event=>{if(event.persisted)schedule();});
  render();schedule();
})();
