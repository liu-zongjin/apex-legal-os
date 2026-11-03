(() => {
'use strict';
const $=id=>document.getElementById(id),number=n=>new Intl.NumberFormat('zh-CN').format(n);
const labels={home:'首页 / 历史未区分页面',cases:'案件管理',knowledge:'知识与阅读',office:'邮箱与发票',updates:'更新日志',install:'首页安装介绍','download-guide':'下载与安装指引',questions:'常见问题',download:'下载区 / 历史下载页','platform-downloads':'版本选择',watch:'功能介绍视频',film:'视频播放区',chapters:'按功能观看','agent-install':'AI 辅助源码安装',arm:'macOS · Apple 芯片',intel:'macOS · Intel',windows:'Windows',mac:'Mac 安装指令',quark:'夸克网盘',github:'GitHub',unknown:'历史 / 未区分渠道',desktop:'电脑',mobile:'手机',tablet:'平板',workbuddy:'WorkBuddy（腾讯）',doubao:'豆包（桌面版）',qwen:'千问办公',lingma:'通义灵码',trae:'TRAE'};
const chapterTitles={'00':'全局总览','01':'案件管理系统','02':'自动化立案','03':'文书合集','04':'知识库与笔记','05':'法答网精选答问','06':'本地工作空间','07':'自由扩展'};
const fixedTargets={copy_targets:['mac','windows'],tab_targets:['arm','intel','windows'],chapter_targets:Object.keys(chapterTitles),assistant_targets:['workbuddy','doubao','qwen','lingma','trae']};
const dimensions=['sources','countries','regions','devices','systems','browsers','sections','landings','downloads','channels','copy_targets','tab_targets','chapter_targets','assistant_targets'];
const downloadTargets=['arm','intel','windows'];
const element=key=>'web-'+key.replace(/_/g,'-');
let days=30,device='all',loading=false,pending=false,current=null;
function node(tag,text,cls=''){const el=document.createElement(tag);el.textContent=text;el.className=cls;return el;}
function label(value){if(/^[A-Z]{2}$/.test(value)){try{return new Intl.DisplayNames(['zh-CN'],{type:'region'}).of(value);}catch{}}return labels[value]||value;}
function valueLabel(key,value){
  if(key==='chapter_targets')return chapterTitles[value]?`${value} · ${chapterTitles[value]}`:`章节 ${value}`;
  if(key==='copy_targets')return value==='mac'?'Mac 安装指令':value==='windows'?'Windows 安装指令':label(value);
  return label(value);
}
function renderRows(key,rows) {
  const values=fixedTargets[key]?fixedTargets[key].map(value=>rows.find(row=>row.label===value)||{label:value,count:0,visitors:0}):rows;
  const total=values.reduce((sum,row)=>sum+row.count,0),maximum=Math.max(1,...values.map(row=>row.count));
  $(element(key)).replaceChildren(...values.map(row=>{
    const item=node('div','','metric-row'),head=node('div','');
    head.append(node('span',valueLabel(key,row.label),'metric-label'),node('span',`${number(row.count)} 次${row.visitors===undefined?'':` · ${number(row.visitors)} 位访客`}`,'metric-count'));
    const meter=node('span','','metric-meter');meter.style.width=(row.count/maximum*100)+'%';
    item.append(head,meter);return item;
  }));
  if(!total && !fixedTargets[key])$(element(key)).append(node('p','所选范围内暂无数据。'));
}
function downloadRows(rows) {
  const map=new Map(rows.map(row=>[row.label,row]));
  return downloadTargets.map(target=>map.get(target)||{label:target,count:0,visitors:0});
}
function renderDownloads(rows) {
  const total=rows.reduce((sum,row)=>sum+row.count,0);
  $('web-downloads').replaceChildren(...downloadRows(rows).map(row=>{
    const tr=node('tr',''),heading=node('th',label(row.label));heading.scope='row';
    tr.append(heading,node('td',number(row.count)),node('td',number(row.visitors)),node('td',total?(row.count/total*100).toFixed(1)+'%':'—'));
    return tr;
  }));
}
async function refresh() {
  if(document.hidden || document.body.dataset.view!=='website')return;
  if(loading){pending=true;return;}
  const selectedDays=days,selectedDevice=device;
  loading=true;$('refresh').disabled=true;
  try {
    const response=await fetch(`/api/website?days=${days}&device=${device}`,{cache:'no-store',signal:AbortSignal.timeout(15000)});
    if(response.status===401){location.replace('/login');return;}
    if(!response.ok)throw new Error('官网统计暂时无法读取，请稍后刷新');
    const data=await response.json();
    if(selectedDays!==days || selectedDevice!==device)return;
    current=data;
    for(const key of ['pageviews','visitors','sessions','clicks','copies','video_plays','chapter_seeks','assistant_clicks'])$(element(key)).textContent=number(data[key]??0);
    $('web-conversion').textContent=`${number(data.download_visitors)} 位访客点击下载 · 含夸克与 GitHub`;
    $('web-recent').textContent=`最近 5 分钟有访问行为：${number(data.recent_visitors)} 位访客`;
    if(document.body.dataset.view==='website')$('status').textContent='更新于 '+new Date(data.as_of*1000).toLocaleTimeString('zh-CN');
    const date=value=>new Date(value*1000).toLocaleDateString('zh-CN',{timeZone:'Asia/Shanghai'});
    $('website-period').textContent=`${date(data.start)} — ${date(data.as_of)} · 北京时间 · ${data.started_at?'开始采集：'+new Date(data.started_at*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}):'尚未收到官网访问数据，历史访问无法补采'} · 设备：${label(device==='all'?'全部':device)}`;
    $('website-empty').hidden=data.pageviews>0 || data.clicks>0 || data.copies>0 || data.tabs>0 || data.video_plays>0 || data.chapter_seeks>0 || data.assistant_clicks>0;
    const map=new Map(data.trend.map(r=>[r.day,r])),interactionDays=new Map((data.interaction_trend||[]).map(r=>[r.day,r.count])),maximum=Math.max(1,...data.trend.map(r=>r.pageviews));
    $('web-trend').replaceChildren(...Array.from({length:days},(_,i)=>{
      const day=new Date((data.start+28800+i*86400)*1000).toISOString().slice(0,10),row=map.get(day)||{pageviews:0,visitors:0,clicks:0};
      const uncollected=!data.started_at || day<new Date((data.started_at+28800)*1000).toISOString().slice(0,10);
      const tr=node('tr',''),pv=node('td',''),meter=node('span','','trend-meter');meter.style.width=(row.pageviews/maximum*120)+'px';
      pv.append(meter,node('span',uncollected?'未采集':number(row.pageviews)));tr.append(node('td',day),pv,node('td',uncollected?'—':number(row.visitors)),node('td',uncollected?'—':number(row.clicks)),node('td',uncollected?'—':number(interactionDays.get(day)||0)));return tr;
    }).reverse());
    const hours=new Map(data.hours.map(r=>[Number(r.label),r.count])),maxHour=Math.max(1,...data.hours.map(r=>r.count));
    $('web-hours').replaceChildren(...Array.from({length:24},(_,i)=>{
      const count=hours.get(i)||0,bar=node('div','','bar');bar.style.height=(count/maxHour*100)+'%';bar.title=`${i}:00 · ${number(count)} 次浏览`;bar.setAttribute('aria-label',bar.title);return bar;
    }));
    for(const key of dimensions)if(key==='downloads')renderDownloads(data[key]||[]);else renderRows(key,data[key]||[]);
    $('website-export').disabled=false;
  }catch(error){if(document.body.dataset.view==='website')$('status').textContent=error.name==='TimeoutError'?'读取超时，请刷新':error.message;$('website-period').textContent='读取失败；保留的上次数据可能已过期。';}
  finally{loading=false;$('refresh').disabled=false;if(pending){pending=false;refresh();}}
}
for(const attr of ['days','device']) document.querySelectorAll('[data-'+attr+']').forEach(button=>button.addEventListener('click',()=>{
  if(attr==='days')days=Number(button.dataset.days);else device=button.dataset.device;
  current=null;$('website-export').disabled=true;
  document.querySelectorAll('[data-'+attr+']').forEach(el=>el.setAttribute('aria-pressed',String(el===button)));
  for(const key of ['pageviews','visitors','sessions','clicks','copies','video_plays','chapter_seeks','assistant_clicks'])$(element(key)).textContent='—';
  const row=node('tr',''),cell=node('td','正在读取所选范围…');cell.colSpan=5;row.append(cell);
  $('web-downloads').replaceChildren(row);
  $('website-period').textContent='正在读取所选范围…';refresh();
}));
$('website-export').addEventListener('click',()=>{
  if(!current)return;
  const quote=v=>'"'+String(v).replace(/"/g,'""')+'"';
  const rows=[['统计范围（北京时间）',new Date(current.start*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}),new Date(current.as_of*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})],['设备',label(device)],['日期','浏览量','独立访客','下载点击','互动'],...current.trend.map(r=>[r.day,r.pageviews,r.visitors,r.clicks,(current.interaction_trend||[]).find(item=>item.day===r.day)?.count||0])];
  rows.push([],['互动汇总','次数'],['复制 AI 安装指令',current.copies??0],['安装系统切换',current.tabs??0],['介绍视频播放',current.video_plays??0],['视频章节点击',current.chapter_seeks??0],['AI 助手入口点击',current.assistant_clicks??0]);
  for(const key of dimensions){rows.push([], [key,'类别','次数','访客']);for(const row of key==='downloads'?downloadRows(current[key]):(fixedTargets[key]?fixedTargets[key].map(value=>(current[key]||[]).find(item=>item.label===value)||{label:value,count:0,visitors:0}):(current[key]||[])))rows.push([key,valueLabel(key,row.label),row.count,row.visitors]);}
  const blob=new Blob(['\ufeff'+rows.map(row=>row.map(v=>quote(v??'')).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'}),url=URL.createObjectURL(blob),a=node('a','');
  a.href=url;a.download=`Stella-官网统计-${days}天-${device}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
$('refresh').addEventListener('click',refresh);
document.addEventListener('apex:admin-view',refresh);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
setInterval(refresh,30000);refresh();
})();
