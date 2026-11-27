/* App notifications remain an enhancement; the app always retains an update indicator. */
(() => {
  'use strict';
  if(window.top!==window)return;
  const sourcePrompt='请根据 https://github.com/liu-zongjin/apex-legal-os 中 docs/WINDOWS_SOURCE_DEPLOYMENT.md 的源码更新步骤，将此 Windows 电脑上的 Stella 源码版更新到 GitHub main。先检查 Git、现有源码目录和 GitHub 连通性，保留旧版本、案件、附件、数据库和设置。验证新版能正常打开、读取原有资料并退出，失败时保留旧入口并说明具体原因。';
  let initialized=false,busy=false,lastCheck=0,button,availableVersion='',availableRevision='',sourceUpdate=false;
  function init(){
    if(initialized||!window.StellaWindows)return;
    const host=document.querySelector('.tab-bar-actions');if(!host)return;
    initialized=true;
    button=document.createElement('button');button.type='button';button.className='tab-bar-action-btn';
    button.id='stella-windows-update-btn';
    button.innerHTML='<svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M13.5 6A5.8 5.8 0 1 0 14 10M13.5 2.5V6H10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    const setStatus=(label, title=label)=>{button.setAttribute('aria-label',label);button.title=title;};
    setStatus('检查更新');host.prepend(button);
    async function check(manual=false){
      if(busy||document.hidden||(!manual&&Date.now()-lastCheck<30*60*1000))return;
      busy=true;lastCheck=Date.now();button.disabled=true;
      setStatus('正在检查更新');
      try{
        const result=await window.StellaWindows.invoke('check_stella_update');
        availableVersion=result.available?result.version:'';availableRevision=result.available?String(result.build||''):'';sourceUpdate=!!result.source;
        button.classList.toggle('active',!!result.available);
        setStatus(result.available?`更新至 ${result.version}`:'检查更新',
          result.available?`Stella ${result.version} 已可用，点击查看`:'已是最新版本，点击重新检查');
        if(result.available){
          const noticeKey='stella.windows.update-notified.v1';let notified='';
          try{notified=localStorage.getItem(noticeKey)||'';}catch{}
          const revision=String(result.build);
          if(notified!==revision)try{
            await window.StellaWindows.invoke('notify_stella',{title:'Stella 有新版本',body:sourceUpdate?`${result.version} 已可用。保存工作后可从检查更新入口进行更新。`:`${result.version} 已可用。保存工作后可从更新入口进入维护界面。`});
            try{localStorage.setItem(noticeKey,revision);}catch{}
          }catch{}
        }
        if(manual&&result.available&&sourceUpdate)showAvailable();
      }catch(error){
        availableVersion='';availableRevision='';
        button.classList.remove('active');
        setStatus('重试检查更新','暂时无法检查更新，点击重试');
        button.disabled=false;
        if(manual&&(window.StellaWindows.source||sourceUpdate)){
          const detail=typeof error==='string'?error:error?.message;
          showDialog('暂时无法检查源码更新',detail||'更新检查未完成，请让 AI 检查本机源码安装。',true);
        }
      }
      finally{busy=false;button.disabled=false;}
    }
    function showAvailable(){
      const description=sourceUpdate?'请先保存正在编辑的内容。继续后将关闭 Stella 并打开更新窗口，在独立目录下载、编译和检查新版本。':'请先保存正在编辑的内容。继续后将安全关闭本地服务并进入组件更新界面。';
      const isSource=sourceUpdate,revision=availableRevision;
      showDialog(`Stella ${availableVersion} 已可用`,description,isSource,async()=>{
        await window.StellaWindows.invoke(isSource?'update_source':'return_to_installer',isSource?{expectedRevision:revision}:{});
      });
    }
    function showDialog(heading,description,offerCopy,update){
      if(document.getElementById('stella-windows-update-dialog'))return;
      const mask=document.createElement('div');mask.className='stella-messages-mask';
      const panel=document.createElement('section');panel.id='stella-windows-update-dialog';panel.className='stella-messages';panel.setAttribute('role','dialog');panel.setAttribute('aria-modal','true');panel.setAttribute('aria-label',heading);
      const head=document.createElement('header');head.className='stella-messages-head';
      const title=document.createElement('h2');title.textContent=heading;head.append(title);
      const content=document.createElement('p');content.style.padding='20px';content.textContent=description;
      const actions=document.createElement('div');actions.className='stella-messages-tools';
      const cancel=document.createElement('button');cancel.textContent=update?'稍后':'关闭';
      const close=()=>{mask.remove();button.focus();};cancel.onclick=close;
      actions.append(cancel);
      let manualCopy;
      if(offerCopy){
        const copy=document.createElement('button');copy.textContent='复制更新指令';
        copy.onclick=async()=>{
          try{
            await navigator.clipboard.writeText(sourcePrompt);
            copy.textContent='已复制更新指令';
          }catch{
            if(!manualCopy){
              manualCopy=document.createElement('textarea');manualCopy.readOnly=true;manualCopy.rows=5;
              manualCopy.setAttribute('aria-label','AI 更新指令');manualCopy.value=sourcePrompt;
              panel.insertBefore(manualCopy,actions);
            }
            copy.textContent='请手动复制已选指令';
            manualCopy.focus();manualCopy.select();
          }
        };
        actions.append(copy);
      }
      if(update){
        const proceed=document.createElement('button');proceed.textContent='已保存，前往更新';
        proceed.onclick=async()=>{proceed.disabled=true;try{await update();}catch{content.textContent='暂时无法结束后台任务或启动更新，请重启 Stella 后重试。';proceed.disabled=false;}};
        actions.append(proceed);
      }
      panel.addEventListener('keydown',event=>{
        if(event.key==='Escape')close();
        if(event.key==='Tab'){
          const controls=[...panel.querySelectorAll('button:not(:disabled),textarea')];
          const index=controls.indexOf(document.activeElement);
          event.preventDefault();
          controls[(index+(event.shiftKey?-1:1)+controls.length)%controls.length].focus();
        }
      });
      panel.append(head,content,actions);mask.append(panel);document.body.append(mask);cancel.focus();
    }
    button.onclick=()=>availableVersion?showAvailable():check(true);
    // Let the local workspace render first and count failed attempts for throttling.
    const startupCheck=setTimeout(()=>check(),3000);
    const scheduledCheck=()=>{if(!document.hidden && lastCheck)check();};
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)check();});
    window.addEventListener('online',()=>check(true));
    window.addEventListener('focus',scheduledCheck);
    const updateTimer=setInterval(()=>check(),30*60*1000);
    window.addEventListener('pagehide',event=>{
      if(!event.persisted){clearTimeout(startupCheck);clearInterval(updateTimer);}
    });
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
