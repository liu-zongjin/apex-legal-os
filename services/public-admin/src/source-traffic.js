const base='https://api.github.com/repos/liu-zongjin/apex-legal-os/traffic/';
export async function syncSourceTraffic(env) {
  if (!env.SOURCE_TRAFFIC_TOKEN) throw new Error('source_traffic_token_missing');
  const data={};
  for (const [key,path] of Object.entries({views:'views',clones:'clones',referrers:'popular/referrers',paths:'popular/paths'})) {
    const response=await fetch(base+path,{headers:{'User-Agent':'Stella-public-metrics','Accept':'application/vnd.github+json','Authorization':'Bearer '+env.SOURCE_TRAFFIC_TOKEN}});
    if(!response.ok) throw new Error('source_traffic_github_'+response.status);
    data[key]=await response.json();
  }
  const valid=n=>Number.isSafeInteger(n)&&n>=0;
  for (const key of ['views','clones']) if(!valid(data[key].count)||!valid(data[key].uniques)||!Array.isArray(data[key][key])||data[key][key].some(r=>!/^\d{4}-\d{2}-\d{2}T00:00:00Z$/.test(r.timestamp)||!valid(r.count)||!valid(r.uniques))) throw new Error('invalid_traffic');
  if(!Array.isArray(data.referrers)||!Array.isArray(data.paths)) throw new Error('invalid_traffic');
  const now=Math.floor(Date.now()/1000), views=new Map(data.views.views.map(r=>[r.timestamp.slice(0,10),r])), clones=new Map(data.clones.clones.map(r=>[r.timestamp.slice(0,10),r]));
  const days=[...new Set([...views.keys(),...clones.keys()])];
  if(!days.length||days.some(d=>!views.has(d)||!clones.has(d))) throw new Error('incomplete_traffic');
  const commands=days.map(day=>env.DB.prepare('INSERT INTO source_traffic_days VALUES(?,?,?,?,?,?) ON CONFLICT(day) DO UPDATE SET views=excluded.views,view_uniques=excluded.view_uniques,clones=excluded.clones,clone_uniques=excluded.clone_uniques,updated_at=excluded.updated_at').bind(day,views.get(day).count,views.get(day).uniques,clones.get(day).count,clones.get(day).uniques,now));
  commands.push(env.DB.prepare('INSERT INTO source_traffic_latest VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at').bind(JSON.stringify(data),now));
  await env.DB.batch(commands);
}
export async function sourceTraffic(env) {
  const [latest,days]=await env.DB.batch([env.DB.prepare('SELECT payload,updated_at FROM source_traffic_latest WHERE id=1'),env.DB.prepare('SELECT * FROM source_traffic_days ORDER BY day DESC LIMIT 3650')]);
  const row=latest.results[0];
  return row?{...JSON.parse(row.payload),updated_at:row.updated_at,days:days.results}:null;
}
