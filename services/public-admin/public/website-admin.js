(() => {
'use strict';
const $=id=>document.getElementById(id),number=n=>new Intl.NumberFormat('zh-CN').format(n);
const labels={home:'首页',cases:'案件管理',knowledge:'知识与阅读',office:'邮箱与工具',updates:'更新日志',install:'下载指引',questions:'常见问题',download:'下载区', 'platform-downloads':'版本选择',arm:'macOS · Apple 芯片',intel:'macOS · Intel',windows:'Windows',desktop:'电脑',mobile:'手机',tablet:'平板'};
const dimensions=['sources','countries','regions','devices','systems','browsers','sections','landings','downloads'];
const downloadTargets=['arm','intel','windows'];
let days=30,device='all',loading=false,pending=false,current=null;
function node(tag,text,cls=''){const el=document.createElement(tag);el.textContent=text;el.className=cls;return el;}
function label(value){if(/^[A-Z]{2}$/.test(value)){try{return new Intl.DisplayNames(['zh-CN'],{type:'region'}).of(value);}catch{}}return labels[value]||value;}
function renderRows(key,rows) {
  const total=rows.reduce((n,r)=>n+r.count,0),maximum=Math.max(1,...rows.map(r=>r.count));
  $('web-'+key).replaceChildren(...rows.map(row=>{
    const item=node('div','','metric-row'),head=node('div','');
    head.append(node('span',label(row.label),'metric-label'),node('span',`${number(row.count)} 次${row.visitors===undefined?'':` · ${number(row.visitors)} 位访客`}`,'metric-count'));
    const meter=node('span','','metric-meter');meter.style.width=(row.count/maximum*100)+'%';
    item.append(head,meter);return item;
  }));
  if(!total)$('web-'+key).append(node('p','所选范围内暂无数据。'));
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
    for(const key of ['pageviews','visitors','sessions','clicks'])$('web-'+key).textContent=number(data[key]);
    $('web-conversion').textContent=`${number(data.download_visitors)} 位访客点击下载 · 不代表完成下载`;
    $('web-recent').textContent=`最近 5 分钟有访问行为：${number(data.recent_visitors)} 位访客`;
    if(document.body.dataset.view==='website')$('status').textContent='更新于 '+new Date(data.as_of*1000).toLocaleTimeString('zh-CN');
    const date=value=>new Date(value*1000).toLocaleDateString('zh-CN',{timeZone:'Asia/Shanghai'});
    $('website-period').textContent=`${date(data.start)} — ${date(data.as_of)} · 北京时间 · ${data.started_at?'开始采集：'+new Date(data.started_at*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}):'尚未收到官网访问数据，历史访问无法补采'} · 设备：${label(device==='all'?'全部':device)}`;
    $('website-empty').hidden=data.pageviews>0 || data.clicks>0;
    const map=new Map(data.trend.map(r=>[r.day,r])),maximum=Math.max(1,...data.trend.map(r=>r.pageviews));
    $('web-trend').replaceChildren(...Array.from({length:days},(_,i)=>{
      const day=new Date((data.start+28800+i*86400)*1000).toISOString().slice(0,10),row=map.get(day)||{pageviews:0,visitors:0,clicks:0};
      const uncollected=!data.started_at || day<new Date((data.started_at+28800)*1000).toISOString().slice(0,10);
      const tr=node('tr',''),pv=node('td',''),meter=node('span','','trend-meter');meter.style.width=(row.pageviews/maximum*120)+'px';
      pv.append(meter,node('span',uncollected?'未采集':number(row.pageviews)));tr.append(node('td',day),pv,node('td',uncollected?'—':number(row.visitors)),node('td',uncollected?'—':number(row.clicks)));return tr;
    }).reverse());
    const hours=new Map(data.hours.map(r=>[Number(r.label),r.count])),maxHour=Math.max(1,...data.hours.map(r=>r.count));
    $('web-hours').replaceChildren(...Array.from({length:24},(_,i)=>{
      const count=hours.get(i)||0,bar=node('div','','bar');bar.style.height=(count/maxHour*100)+'%';bar.title=`${i}:00 · ${number(count)} 次浏览`;bar.setAttribute('aria-label',bar.title);return bar;
    }));
    for(const key of dimensions)if(key==='downloads')renderDownloads(data[key]);else renderRows(key,data[key]);
    $('website-export').disabled=false;
  }catch(error){if(document.body.dataset.view==='website')$('status').textContent=error.name==='TimeoutError'?'读取超时，请刷新':error.message;$('website-period').textContent='读取失败；保留的上次数据可能已过期。';}
  finally{loading=false;$('refresh').disabled=false;if(pending){pending=false;refresh();}}
}
for(const attr of ['days','device']) document.querySelectorAll('[data-'+attr+']').forEach(button=>button.addEventListener('click',()=>{
  if(attr==='days')days=Number(button.dataset.days);else device=button.dataset.device;
  current=null;$('website-export').disabled=true;
  document.querySelectorAll('[data-'+attr+']').forEach(el=>el.setAttribute('aria-pressed',String(el===button)));
  for(const key of ['pageviews','visitors','sessions','clicks'])$('web-'+key).textContent='—';
  const row=node('tr',''),cell=node('td','正在读取所选范围…');cell.colSpan=4;row.append(cell);
  $('web-downloads').replaceChildren(row);
  $('website-period').textContent='正在读取所选范围…';refresh();
}));
$('website-export').addEventListener('click',()=>{
  if(!current)return;
  const quote=v=>'"'+String(v).replace(/"/g,'""')+'"';
  const rows=[['统计范围（北京时间）',new Date(current.start*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}),new Date(current.as_of*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})],['设备',label(device)],['日期','浏览量','独立访客','下载点击'],...current.trend.map(r=>[r.day,r.pageviews,r.visitors,r.clicks])];
  for(const key of dimensions){rows.push([], [key,'类别','次数','访客']);for(const row of key==='downloads'?downloadRows(current[key]):current[key])rows.push([key,label(row.label),row.count,row.visitors]);}
  const blob=new Blob(['\ufeff'+rows.map(row=>row.map(v=>quote(v??'')).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'}),url=URL.createObjectURL(blob),a=node('a','');
  a.href=url;a.download=`Stella-官网统计-${days}天-${device}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
$('refresh').addEventListener('click',refresh);
document.addEventListener('apex:admin-view',refresh);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
setInterval(refresh,30000);refresh();
})();
