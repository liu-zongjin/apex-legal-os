/* App notifications remain an enhancement; the app always retains an update indicator. */
(() => {
  'use strict';
  if(window.top!==window)return;
  let initialized=false,busy=false,lastCheck=0,button,availableVersion='',availableRevision='',sourceUpdate=false;
  function init(){
    if(initialized||!window.StellaWindows)return;initialized=true;
    const host=document.querySelector('.tab-bar-actions');if(!host)return;
    button=document.createElement('button');button.type='button';button.className='tab-bar-action-btn';
    button.textContent='检查更新';button.title='检查 Windows 版本更新';host.prepend(button);
    async function check(manual=false){
      if(busy||document.hidden||(!manual&&Date.now()-lastCheck<60000))return;
      busy=true;button.disabled=true;
      try{
        const result=await window.StellaWindows.invoke('check_stella_update');lastCheck=Date.now();
        availableVersion=result.available?result.version:'';availableRevision=result.available?String(result.build||''):'';sourceUpdate=!!result.source;
        button.textContent=result.available?`更新至 ${result.version}`:'已是最新版本';
        button.title=result.available?(sourceUpdate?'请保存工作后按提示更新源码版。':'请保存工作后退出 Stella，重新打开并选择“检查更新与修复”完成更新。'):'当前已是可用的最新 Windows 版本';
        if(result.available){
          const noticeKey='stella.windows.update-notified.v1';let notified='';
          try{notified=localStorage.getItem(noticeKey)||'';}catch{}
          const revision=String(result.build);
          if(notified!==revision)try{
            await window.StellaWindows.invoke('notify_stella',{title:'Stella 有新版本',body:`${result.version} 已可用。保存工作并退出后，可在启动界面完成更新。`});
            try{localStorage.setItem(noticeKey,revision);}catch{}
          }catch{}
        }
      }catch{button.textContent='重试检查更新';button.title='暂时无法检查更新，联网后会自动重试';}
      finally{busy=false;button.disabled=false;}
    }
    button.onclick=()=>{
      if(!availableVersion)return check(true);
      const mask=document.createElement('div');mask.className='stella-messages-mask';
      const panel=document.createElement('section');panel.className='stella-messages';panel.setAttribute('role','dialog');panel.setAttribute('aria-modal','true');panel.setAttribute('aria-label','Stella 更新');panel.tabIndex=-1;
      const head=document.createElement('header');head.className='stella-messages-head';
      const title=document.createElement('h2');title.textContent=`Stella ${availableVersion} 已可用`;head.append(title);
      const content=document.createElement('p');content.style.padding='20px';content.textContent=sourceUpdate?'请先保存正在编辑的内容。继续后将关闭 Stella 并打开更新窗口，在独立目录下载、编译和检查新版本；旧版本和用户资料会保留。':'请先保存正在编辑的内容。继续后将安全关闭本地服务，进入组件更新界面；下载并校验完成后可重新打开工作空间。';
      const actions=document.createElement('div');actions.className='stella-messages-tools';
      const cancel=document.createElement('button'),proceed=document.createElement('button');cancel.textContent='稍后';proceed.textContent='已保存，前往更新';
      const close=()=>{mask.remove();button.focus();};cancel.onclick=close;
      proceed.onclick=async()=>{proceed.disabled=true;try{await window.StellaWindows.invoke(sourceUpdate?'update_source':'return_to_installer',sourceUpdate?{expectedRevision:availableRevision}:{});}catch{content.textContent='暂时无法结束后台任务或启动更新，请重启 Stella 后重试。';proceed.disabled=false;}};
      panel.addEventListener('keydown',event=>{if(event.key==='Escape')close();if(event.key==='Tab'){event.preventDefault();(document.activeElement===cancel?proceed:cancel).focus();}});
      actions.append(cancel,proceed);panel.append(head,content,actions);mask.append(panel);document.body.append(mask);cancel.focus();
    };
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)check();});
    window.addEventListener('online',()=>check(true));
    window.addEventListener('focus',()=>check());
    setInterval(()=>check(),30*60*1000);check();
    window.addEventListener('stella:system-messages',event=>{
      const messages=event.detail?.messages||[];if(!messages.length)return;
      let seen=[];
      try{seen=JSON.parse(localStorage.getItem('stella.windows.notified.v1')||'[]');}catch{}
      const fresh=messages.filter(m=>!seen.includes(m.id));if(!fresh.length)return;
      const latest=fresh[0];
      window.StellaWindows.invoke('notify_stella',{title:fresh.length>1?`Stella · ${fresh.length} 条系统消息`:latest.title,body:latest.body.slice(0,200)}).catch(()=>{});
      try{localStorage.setItem('stella.windows.notified.v1',JSON.stringify(messages.map(m=>m.id)));}catch{}
    });
  }
  window.addEventListener('stella:windows-ready',init);init();
})();
