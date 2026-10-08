(() => {
  'use strict';
  const API='/api/case-manager/court-online/downloads';
  const labels={queued:'排队中',downloading:'下载中',packing:'正在打包',paused:'已暂停',completed:'已完成',partial:'部分完成',failed:'失败',cancelled:'已取消'};
  let selected=new URLSearchParams(location.search).get('job')||'', page=1, filePage=0, busy=false, pending=false, items=[], detail=null;
  const $=id=>document.getElementById(id);
  const esc=value=>{const el=document.createElement('span');el.textContent=String(value??'');return el.innerHTML};
  function size(value){if(value===null||value===undefined)return '待确认';if(value<1024)return value+' B';const units=['KB','MB','GB','TB'];let n=value/1024,i=0;while(n>=1024&&i<units.length-1){n/=1024;i++}return n.toFixed(n>=10?1:2)+' '+units[i]}
  function eta(value){if(value===null)return '待估算';if(value<60)return Math.ceil(value)+' 秒';if(value<3600)return Math.ceil(value/60)+' 分钟';return (value/3600).toFixed(1)+' 小时'}
  async function request(path,options){const r=await fetch(path,options);const d=await r.json();if(!r.ok)throw new Error(d.detail||'无法读取下载任务');return d}
  async function load(){
    if(busy||!window.ApexLifecycle.active)return;busy=true;
    try{
      const data=await request(API+'?page='+page);items=data.items;
      if(!selected&&items.length)selected=items[0].id;
      detail=selected?await request(API+'/'+encodeURIComponent(selected)):null;
      $('feedback').textContent='';render();
    }catch(e){$('feedback').textContent=e.message}
    finally{busy=false}
  }
  function render(){
    const focus=document.activeElement?.dataset.focus;
    const scroll=$('detail').querySelector('.files-wrap')?.scrollTop||0;
    $('jobs').innerHTML=items.length?items.map(item=>`<button class="job ${item.id===selected?'active':''}" data-job="${esc(item.id)}" data-focus="job-${esc(item.id)}"><strong>${esc(item.title)}</strong><small>${labels[item.state]||item.state} · ${item.completed_count}/${item.file_count} 个文件</small></button>`).join(''):'<p class="muted">本页暂无下载任务。</p>';
    $('previous').disabled=page===1;$('next').disabled=items.length<50;
    if(!detail){$('detail').innerHTML='<div class="empty">暂无下载任务。<br>在“一张网—在线阅卷”中选择卷宗，点击打包下载。</div>';return}
    const d=detail, running=['queued','downloading','packing'].includes(d.state), percent=d.download_percent, done=d.state==='completed';
    let actions=running?'<button data-action="pause" data-focus="pause">暂停</button><button data-action="cancel" data-focus="cancel">取消任务</button>':d.state==='paused'?'<button class="primary" data-action="resume" data-focus="resume">继续下载</button><button data-action="cancel" data-focus="cancel">取消任务</button>':['failed','partial','cancelled'].includes(d.state)?'<button data-action="retry" data-focus="retry">重试未完成文件</button>':'';
    actions+='<button data-action="open-folder" data-focus="open-folder">打开文件夹</button>';
    if(d.zip_path)actions+=`<button data-action="open-zip" data-focus="open-zip">打开 ZIP</button><a class="download-link" href="${API}/${encodeURIComponent(d.id)}/archive" download>下载 ZIP</a>`;
    const files=d.files.slice(filePage*50,filePage*50+50);
    $('detail').innerHTML=`<div class="task-top"><div><h2 class="task-title">${esc(d.title)}</h2><p class="path">保存位置：${esc(d.directory)}</p></div><span class="badge">${labels[d.state]||esc(d.state)}</span></div>
      ${d.source==='application-test'?'<p class="test-note">申请材料打包测试：本任务下载介绍信、执业证等申请材料，供验证下载与打包功能。</p>':''}
      <div class="metrics"><div class="metric"><b>${size(d.total_bytes)}</b><span>文件总大小</span></div><div class="metric"><b>${d.completed_count} / ${d.file_count}</b><span>成功 / 总文件数 · 失败 ${d.failed_count}</span></div><div class="metric"><b>${size(d.speed_bytes)} /s</b><span>当前下载速度</span></div><div class="metric"><b>${eta(d.eta_seconds)}</b><span>下载预计剩余时间</span></div></div>
      <div class="progress-caption"><span>${d.state==='packing'?'文件传输已结束，正在生成 ZIP':done?'文件下载与 ZIP 打包已完成':'文件下载进度'}</span><strong>${percent===null?'字节百分比待确认':percent.toFixed(1)+'%'}</strong></div>
      <div class="progress" role="progressbar" aria-label="文件下载" ${percent!==null?`aria-valuenow="${percent.toFixed(1)}" aria-valuemin="0" aria-valuemax="100"`:''}><span style="width:${percent===null?d.file_percent:percent}%"></span></div>
      <div class="progress-caption muted"><span>已下载 ${size(d.downloaded_bytes)}${d.total_bytes!==null?' / '+size(d.total_bytes):' · 总大小待确认'}</span><span>文件完成 ${d.file_percent.toFixed(1)}%</span></div>
      ${d.error?`<p class="error" role="status">${esc(d.error)}</p>`:''}${d.state==='partial'?'<p class="error">部分文件未下载成功，ZIP 内附完整文件清单与失败原因。</p>':''}
      <div class="actions">${actions}</div><div class="files-wrap"><h3>文件明细 · ${d.file_count} 个</h3><table><thead><tr><th>名称 / 目录</th><th>大小</th><th>已下载</th><th>百分比</th><th>状态</th></tr></thead><tbody>${files.map(f=>`<tr><td>${esc(f.name)}<div class="path">${esc(f.relative_path)}</div>${f.error?`<div class="error">${esc(f.error)}</div>`:''}</td><td>${size(f.size_bytes)}</td><td>${size(f.downloaded_bytes)}</td><td>${f.size_bytes?Math.min(100,100*f.downloaded_bytes/f.size_bytes).toFixed(1)+'%':f.state==='completed'?'100%':'待确认'}</td><td>${labels[f.state]||esc(f.state)}</td></tr>`).join('')}</tbody></table></div>
      <div class="actions"><button data-files="previous" data-focus="files-previous" ${filePage===0?'disabled':''}>上一页文件</button><span>第 ${filePage+1} / ${Math.max(1,Math.ceil(d.file_count/50))} 页</span><button data-files="next" data-focus="files-next" ${(filePage+1)*50>=d.file_count?'disabled':''}>下一页文件</button></div>`;
    if(pending)$('detail').querySelectorAll('button[data-action]').forEach(b=>b.disabled=true);
    const fileScroll=$('detail').querySelector('.files-wrap');if(fileScroll)fileScroll.scrollTop=scroll;
    if(focus)document.querySelector(`[data-focus="${CSS.escape(focus)}"]`)?.focus({preventScroll:true});
  }
  $('jobs').addEventListener('click',e=>{const b=e.target.closest('[data-job]');if(b){selected=b.dataset.job;filePage=0;history.replaceState(null,'','?job='+encodeURIComponent(selected));load()}});
  $('detail').addEventListener('click',async e=>{
    const files=e.target.closest('[data-files]');if(files){filePage+=files.dataset.files==='next'?1:-1;render();return}
    const button=e.target.closest('[data-action]');if(!button||pending)return;pending=true;button.disabled=true;
    try{detail=await request(API+'/'+encodeURIComponent(selected)+'/'+button.dataset.action,{method:'POST'});$('feedback').textContent='';render()}
    catch(error){$('feedback').textContent=error.message}finally{pending=false;render()}
  });
  $('refresh').onclick=load;$('previous').onclick=()=>{page--;load()};$('next').onclick=()=>{page++;load()};
  document.addEventListener('visibilitychange',()=>{if(window.parent===window)window.postMessage({type:'apex:page-visibility',version:1,active:document.visibilityState==='visible'},location.origin)});
  ApexLifecycle.onChange(active=>{if(active)load()});ApexLifecycle.interval(load,1000);load();
})();
