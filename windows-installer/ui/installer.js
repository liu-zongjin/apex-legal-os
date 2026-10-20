'use strict';
(() => {
  const $=id=>document.getElementById(id),invoke=(name)=>window.__TAURI__.core.invoke(name);
  const names={server:'Stella 工作空间',browser:'法院与网页组件',ocr:'文字识别组件',converter:'文档转换组件',node:'本地工具组件'};
  let action='plan',busy=false;
  const mb=n=>(n/1000000).toFixed(1)+' MB';
  function message(text){$('status').textContent=String(text);}
  async function run(){
    if(busy)return;busy=true;$('primary').disabled=true;$('repair').disabled=true;
    try{
      if(action==='launch'){message('正在安全启动工作空间…');await invoke('start_stella');return;}
      if(action==='install'){
        message('正在准备组件，请保持联网…');$('progress').removeAttribute('value');
        await invoke('install_components');action='launch';$('primary').textContent='打开 Stella';
        $('progress').value=100;message('准备完成，欢迎使用 Stella');
      }else{
        const plan=await invoke('installation_plan');
        $('components').replaceChildren(...plan.components.map(c=>{const row=document.createElement('li'),name=document.createElement('span'),status=document.createElement('span');name.textContent=names[c.id]||c.id;status.textContent=c.reuse?'已准备':mb(c.bytes);row.append(name,status);return row;}));
        $('size').textContent=`需下载 ${mb(plan.download_bytes)} · 建议可用空间 ${mb(plan.required_free_bytes)}`;
        message(`即将准备 Stella ${plan.version}`);action='install';$('primary').textContent='安装并准备组件';
      }
    }catch(e){message(e);$('primary').textContent=action==='launch'?'重试启动':'重试';}
    finally{busy=false;$('primary').disabled=false;$('repair').disabled=false;}
  }
  $('primary').addEventListener('click',run);
  $('repair').addEventListener('click',()=>{action='plan';run();});
  async function init(){
    try{
      await window.__TAURI__.event.listen('stella:installer',({payload:p})=>{
        if(p.event==='progress'){$('progress').value=p.received/p.total*100;message(`正在下载${names[p.component]||'组件'} · ${mb(p.received)} / ${mb(p.total)}`);}
        if(p.event==='phase'){message((p.phase==='download'?'正在获取':'正在校验并安装')+(names[p.component]||'组件'));$('progress').removeAttribute('value');}
      });
      const p=await invoke('inspect_installation');
      if(!p.supported){message('首版支持 Windows 11 的 Intel / AMD 64 位电脑。当前系统尚未纳入支持范围。');$('primary').textContent='暂不支持此设备';return;}
      if(p.installed){action='launch';$('title').textContent='欢迎回到 Stella';message('你的工作空间已安装，可直接打开或检查更新与修复。');$('primary').textContent='打开 Stella';$('repair').hidden=false;$('primary').disabled=false;}
      else await run();
    }catch(e){message('无法完成环境检测：'+String(e));$('primary').textContent='重新检测';$('primary').disabled=false;$('primary').onclick=init;}
  }
  init();
})();
