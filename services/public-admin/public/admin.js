const $ = id => document.getElementById(id);
let loading = false;
const number = value => new Intl.NumberFormat('zh-CN').format(value);
function cell(text, tag='td') { const node=document.createElement(tag); node.textContent=text; return node; }
async function refresh() {
  if (loading || document.hidden) return;
  loading=true; $('refresh').disabled=true;
  try {
    const result=await fetch('/api/summary', {cache:'no-store'});
    if (result.status===401) { location.replace('/login'); return; }
    if (!result.ok) throw new Error('暂时无法读取，请稍后刷新');
    const data=await result.json();
    for (const key of ['installations','online','active_month']) $(key).textContent=number(data[key]);
    $('downloads').textContent=data.downloads?number(data.downloads.total):'—';
    $('status').textContent='更新于 '+new Date(data.as_of*1000).toLocaleTimeString('zh-CN');
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
  } catch(error) { $('status').textContent=error.message; }
  finally { loading=false; $('refresh').disabled=false; }
}
$('refresh').addEventListener('click',refresh);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
setInterval(refresh,30000);
refresh();

$('logout').addEventListener('click',async()=>{ const result=await fetch('/api/logout',{method:'POST'}); if(result.ok)location.replace('/login'); });
