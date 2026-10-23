'use strict';
(() => {
  const $=id=>document.getElementById(id),invoke=(name)=>window.__TAURI__.core.invoke(name);
  const names={server:'Stella 工作空间',browser:'法院与网页组件',ocr:'文字识别组件',converter:'文档转换组件',node:'本地工具组件'};
  let action='probe',busy=false,listening=false;
  let downloadPlan=[],downloaded=new Map();
  const mb=n=>(n/1000000).toFixed(1)+' MB';
  function message(text){const value=String(text);if($('status').textContent!==value)$('status').textContent=value;}
  function note(id,text){$(id).textContent=text||'';$(id).hidden=!text;}
  function stage(value){
    for(const id of ['download','verify','launch']){
      const item=$('stage-'+id);item.removeAttribute('aria-current');
      if(id===value)item.setAttribute('aria-current','step');
    }
    note('transfer','');note('detail','');note('step-label','');$('progress').value=0;$('progress').hidden=true;
  }
  function progress(value,label){$('progress').hidden=false;$('progress').value=value;note('step-label',label);}
  function totalDownload(){
    const total=downloadPlan.reduce((n,c)=>n+c.bytes,0);
    const received=downloadPlan.reduce((n,c)=>n+Math.min(c.bytes,downloaded.get(c.id)||0),0);
    $('overall').hidden=total===0;
    $('overall-progress').value=total>0?received/total*100:0;
    $('overall-label').textContent=received===total?'组件下载已完成 · '+mb(total):'总下载 '+mb(received)+' / '+mb(total)+' · '+Math.floor(received/total*100)+'%';
    return Math.max(0,total-received);
  }
  function setPlan(plan){downloadPlan=plan.components.filter(c=>!c.reuse);downloaded=new Map();totalDownload();}
  function component(id,text){
    for(const row of $('components').children){
      row.dataset.state=row.dataset.component===id?'active':'';
      if(row.dataset.component===id)row.lastElementChild.textContent=text;
    }
  }
  function duration(seconds){
    if(seconds<60)return Math.max(1,Math.ceil(seconds))+' 秒';
    return Math.ceil(seconds/60)+' 分钟';
  }
  function onEvent(p){
    const name=names[p.component]||'组件';
    if(p.event==='plan')setPlan(p);
    if(p.event==='download_reset'){downloaded.set(p.component,0);totalDownload();}
    if(p.event==='download_complete'){downloaded.set(p.component,p.total);totalDownload();component(p.component,p.cached?'已从本机复用':'下载完成');}
    if(p.event==='component_extracted')component(p.component,'解压校验完成');
    if(p.event==='progress'){
      $('stage-download').setAttribute('aria-current','step');
      $('stage-verify').removeAttribute('aria-current');$('stage-launch').removeAttribute('aria-current');
      downloaded.set(p.component,p.received);const remaining=totalDownload();
      progress(p.total>0?p.received/p.total*100:0,'当前组件下载 · '+Math.floor(p.received/p.total*100)+'%');
      message('正在下载'+name);component(p.component,mb(p.received)+' / '+mb(p.total));
      const rate=Number(p.speed_bytes_per_second)||0;
      const speed=rate>=1000000?mb(rate)+'/s':(rate/1000).toFixed(0)+' KB/s';
      const estimate=rate>0&&p.elapsed_seconds>=3&&remaining>0?' · 全部下载预计剩余 '+duration(remaining/rate):'';
      note('transfer',rate>0?'本次连接平均速度 '+speed+estimate:'正在测量下载速度…');
      if(rate>0&&!estimate&&remaining>0)note('transfer','本次连接平均速度 '+speed+' · 正在估算下载时间…');
      note('detail',p.source?'下载通道：'+p.source:'');
    }
    if(p.event==='phase'){
      const labels={plan_verify:'正在检查已有组件',download:'正在连接下载通道',verify_archive:'正在校验组件下载文件',verify_resume:'正在检查续传文件',verify_extract:'正在解压并校验',self_test:'正在测试组件能否正常运行',final_verify:'正在进行安装后的完整校验',launch_verify:'正在校验启动文件',launch_service:'正在启动本机工作空间'};
      stage(p.phase==='download'?'download':p.phase==='launch_service'?'launch':'verify');
      message((labels[p.phase]||'正在校验组件')+(p.component?' · '+name:''));
      if(p.component)component(p.component,p.phase==='download'?'等待下载':'校验中');
      if(p.source)note('detail','下载通道：'+p.source);
      if(p.phase==='download')progress(0,'正在连接，等待下载数据');
      if(p.phase==='self_test')progress(0,'组件运行自检 · 0 / 4 项');
    }
    if(p.event==='verification'){
      stage('verify');
      const label=p.phase==='launch_verify'?'正在校验启动文件':p.phase==='verify_extract'?'正在解压并校验':p.phase==='plan_verify'?'正在检查已有组件':'正在进行安装后的完整校验';
      message(label+' · '+name);
      const ratio=p.expanded_bytes>0?p.received/p.expanded_bytes:p.total>0?p.checked/p.total:0;
      progress(ratio*100,p.phase==='verify_extract'?'当前组件解压校验 · '+mb(p.received||0)+' / '+mb(p.expanded_bytes||0):'当前组件文件检查 · '+Math.floor(ratio*100)+'%');
      note('detail','已检查 '+p.checked+' / '+p.total+' 个文件');component(p.component,p.checked===p.total?'校验完成':'校验中');
      if(p.elapsed_seconds>=3&&Number.isFinite(p.eta_seconds)&&p.eta_seconds>0)note('transfer','此组件当前检查预计剩余 '+duration(p.eta_seconds));
    }
    if(p.event==='self_test_progress'){stage('verify');message('正在测试组件能否正常运行');progress(p.checked/p.total*100,'组件运行自检 · '+p.checked+' / '+p.total+' 项');}
    if(p.event==='retry'){
      stage('download');
      const reason=p.reason==='slow'?'下载持续偏慢':p.reason==='checksum'?'文件校验未通过':'下载连接中断';
      message(reason+'，'+(p.switching_source?'正在切换下载通道':'正在重新连接'));
      note('detail','第 '+p.attempt+' 次尝试 · 自动检查并续传有效进度');
    }
    if(p.event==='ready'){stage('launch');progress(100,'本机服务已就绪');message('工作空间已启动，正在打开…');}
    if(p.event==='startup_wait'){
      stage('launch');message('正在启动本机工作空间');
      note('step-label','已等待 '+Math.max(0,Number(p.elapsed_seconds)||0)+' 秒');
      note('detail','首次启动需要初始化本机资料；超过两分钟会显示诊断提示。');
    }
    if(p.event==='launch_failed'){
      stage('launch');message(p.message);
      note('detail',p.cleanup_pending?'正在等待后台安全结束，请先保留此窗口。':'后台已退出，可重试启动。');
    }
    if(p.event==='shutdown_wait')note('detail',p.message+'；请勿重复打开或重新安装。');
  }
  async function run(){
    if(action==='probe'){await init();return;}
    if(busy)return;busy=true;$('primary').disabled=true;$('repair').disabled=true;
    try{
      if(action==='launch'){stage('verify');$('overall').hidden=true;$('size').textContent='组件已安装，无需重新下载';message('正在校验启动文件…');await invoke('start_stella');window.location.replace('http://127.0.0.1:18865/');return;}
      if(action==='install'){
        stage('verify');message('正在检查组件，请稍候…');$('primary').textContent='正在准备组件';$('size').textContent='已下载的有效组件将自动复用';
        await invoke('install_components');action='launch';$('primary').textContent='打开 Stella';
        for(const c of downloadPlan)downloaded.set(c.id,c.bytes);totalDownload();
        progress(100,'组件安装与校验已完成');note('transfer','');note('detail','');
        for(const row of $('components').children){row.dataset.state='';row.lastElementChild.textContent='已准备';}
        $('size').textContent='组件已安装，打开后将在本机校验并启动';message('准备完成，欢迎使用 Stella');
      }else{
        stage('verify');message('正在检查已有组件…');const plan=await invoke('installation_plan');
        setPlan(plan);
        $('components').replaceChildren(...plan.components.map(c=>{const row=document.createElement('li'),name=document.createElement('span'),status=document.createElement('span');row.dataset.component=c.id;name.textContent=names[c.id]||c.id;status.textContent=c.reuse?'已准备':mb(c.bytes);row.append(name,status);return row;}));
        $('size').textContent=`需下载 ${mb(plan.download_bytes)} · 建议可用空间 ${mb(plan.required_free_bytes)}`;
        stage('');message(`即将准备 Stella ${plan.version}`);action='install';$('primary').textContent='安装并准备组件';
      }
    }catch(e){note('transfer','');message(e);$('primary').textContent=action==='launch'?'重试启动':'重试';}
    finally{busy=false;$('primary').disabled=false;$('repair').disabled=false;}
  }
  $('primary').addEventListener('click',run);
  $('repair').addEventListener('click',()=>{action='plan';run();});
  async function init(){
    if(busy)return;busy=true;$('primary').disabled=true;$('repair').disabled=true;
    let plan=false;
    try{
      if(!listening){await window.__TAURI__.event.listen('stella:installer',({payload:p})=>onEvent(p));listening=true;}
      const p=await invoke('inspect_installation');
      if(!p.supported){message('支持 Windows 10 1809（17763）及更新版本、Windows 11 的 Intel / AMD 64 位电脑。不支持 Windows Server 或 ARM 设备。');$('progress').value=0;$('primary').textContent='暂不支持此设备';return;}
      if(p.installed){action='launch';$('title').textContent='欢迎回到 Stella';message('你的工作空间已安装，可直接打开或检查更新与修复。');$('primary').textContent='打开 Stella';$('repair').hidden=false;$('repair').disabled=false;$('primary').disabled=false;}
      else {action='plan';plan=true;}
    }catch(e){action='probe';message('无法完成环境检测：'+String(e));$('primary').textContent='重新检测';$('primary').disabled=false;}
    finally{busy=false;}
    if(plan)await run();
  }
  init();
})();
