const views={website:['官网访问','了解访客从哪里来、关注什么，以及如何选择下载。'],application:['应用统计','了解安装包下载、首次启动与使用情况。'],messages:['系统消息','管理向公开版用户展示的系统消息。']};
function selectView() {
  const view=Object.hasOwn(views,location.hash.slice(1))?location.hash.slice(1):'website';
  document.body.dataset.view=view;
  for(const key of Object.keys(views)) $('view-'+key).hidden=key!==view;
  document.querySelectorAll('[data-view]').forEach(link=>{if(link.dataset.view===view)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');});
  $('page-title').textContent=views[view][0];$('page-description').textContent=views[view][1];
  $('status').textContent='正在读取';
  document.dispatchEvent(new CustomEvent('apex:admin-view',{detail:view}));
  if(view==='application')refresh();
}
window.addEventListener('hashchange',selectView);
const $ = id => document.getElementById(id);
let loading = false;
const number = value => new Intl.NumberFormat('zh-CN').format(value);
function cell(text, tag='td') { const node=document.createElement(tag); node.textContent=text; return node; }
async function refresh() {
  if (loading || document.hidden || document.body.dataset.view!=='application') return;
  loading=true; $('refresh').disabled=true;
  try {
    const result=await fetch('/api/summary', {cache:'no-store'});
    if (result.status===401) { location.replace('/login'); return; }
    if (!result.ok) throw new Error('暂时无法读取，请稍后刷新');
    const data=await result.json();
    for (const key of ['installations','online','active_month']) $(key).textContent=number(data[key]);
    $('downloads').textContent=data.downloads?number(data.downloads.total):'—';
    if(document.body.dataset.view==='application')$('status').textContent='更新于 '+new Date(data.as_of*1000).toLocaleTimeString('zh-CN');
    $('download-status').textContent=data.downloads?
      `${data.downloads.stale?'同步延迟 · ':''}GitHub 数据更新于 ${new Date(data.downloads.checked_at*1000).toLocaleString('zh-CN')}`:
      '尚未取得 GitHub 数据；使用统计仍正常显示。';
    $('versions').replaceChildren(...data.versions.map(item=>{
      const row=document.createElement('div');row.className='version';row.append(cell('构建 '+item.version,'span'),cell(number(item.count)+' 台','span'));return row;
    }));
    if (!data.versions.length) $('versions').append(cell('还没有版本数据。', 'p'));
    $('assets').replaceChildren(...(data.downloads?.assets||[]).map(item=>{
      const row=document.createElement('tr');row.append(cell(item.name),cell(item.release),cell(number(item.count)));return row;
    }));
    const days=Array.from({length:30},(_,i)=>new Date((data.as_of-(29-i)*86400)*1000).toISOString().slice(0,10));
    const counts=new Map(data.days.map(item=>[item.day,item.count]));
    const maximum=Math.max(1,...data.days.map(item=>item.count));
    $('activity').replaceChildren(...days.map(day=>{
      const bar=document.createElement('div'), count=counts.get(day)||0;
      bar.className='bar';bar.style.height=Math.max(1,count/maximum*100)+'%';
      bar.title=`${day} · ${number(count)} 台`;bar.setAttribute('aria-label',bar.title);return bar;
    }));
    $('activity').hidden=data.days.length===0;
    $('empty').hidden=data.days.length>0;
  } catch(error) { if(document.body.dataset.view==='application')$('status').textContent=error.message; }
  finally { loading=false; $('refresh').disabled=false; }
}
$('refresh').addEventListener('click',refresh);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
setInterval(refresh,30000);
refresh();

$('logout').addEventListener('click',async()=>{ const result=await fetch('/api/logout',{method:'POST'}); if(result.ok)location.replace('/login'); });

selectView();
