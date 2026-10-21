// Website telemetry is independent of application installation telemetry.
const SITE = 'https://liu-zongjin.github.io';
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
export const sections = ['home','cases','knowledge','office','updates','install','questions','download','platform-downloads'];
function response(body, status=200, cors=false) {
  const headers = {'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'};
  if (cors) Object.assign(headers, {'Access-Control-Allow-Origin':SITE,'Access-Control-Allow-Methods':'POST, OPTIONS','Access-Control-Allow-Headers':'Content-Type','Vary':'Origin'});
  return body===null ? new Response(null,{status,headers}) : Response.json(body,{status,headers});
}
export function validateWebsiteEvent(value) {
  const keys='event_id,kind,referrer,section,session_id,target,visitor_id';
  if (!value || Array.isArray(value) || Object.keys(value).sort().join(',')!==keys ||
    ![value.event_id,value.session_id,value.visitor_id].every(v=>typeof v==='string' && UUID.test(v)) ||
    !['pageview','section','download'].includes(value.kind) || !sections.includes(value.section) ||
    typeof value.referrer!=='string' || value.referrer.length>253 ||
    (value.referrer!=='' && !/^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/.test(value.referrer)) ||
    (value.kind==='download' ? !['arm','intel','windows'].includes(value.target) : value.target!=='')) throw new Error('invalid_event');
  return value;
}
export function classifyAgent(ua='') {
  const device=/iPad|Tablet|Android(?!.*Mobile)/i.test(ua)?'tablet':/Mobile|iPhone|iPod/i.test(ua)?'mobile':'desktop';
  const os=/Windows/i.test(ua)?'Windows':/iPhone|iPad|iPod/i.test(ua)?'iOS':/Android/i.test(ua)?'Android':/Mac/i.test(ua)?'macOS':/Linux/i.test(ua)?'Linux':'其他';
  const browser=/Edg(?:e|A|iOS)?\//i.test(ua)?'Edge':/Firefox|FxiOS/i.test(ua)?'Firefox':/Chrome|CriOS/i.test(ua)?'Chrome':/Safari/i.test(ua)?'Safari':'其他';
  return {device,os,browser};
}
async function hash(value) {
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode('stella-website:'+value))),b=>b.toString(16).padStart(2,'0')).join('');
}
export async function websiteIngest(request,env) {
  if (request.headers.get('Origin')!==SITE) return response({error:'invalid_origin'},403);
  if (request.method==='OPTIONS') return response(null,204,true);
  if (request.method!=='POST') return response({error:'method_not_allowed'},405,true);
  if (request.headers.get('DNT')==='1' || request.headers.get('Sec-GPC')==='1') return response(null,204,true);
  if (!request.headers.get('Content-Type')?.startsWith('application/json')) return response({error:'json_required'},415,true);
  if (Number(request.headers.get('Content-Length'))>2048) return response({error:'too_large'},413,true);
  if (!env.WEBSITE_LIMITER || !(await env.WEBSITE_LIMITER.limit({key:request.headers.get('CF-Connecting-IP')||'unknown'})).success) return response({error:'rate_limited'},429,true);
  const reader=request.body?.getReader();
  if (!reader) return response({error:'invalid_event'},400,true);
  let size=0; const chunks=[];
  while (true) {
    const {done,value}=await reader.read(); if(done)break;
    size+=value.byteLength;
    if(size>2048){await reader.cancel();return response({error:'too_large'},413,true);}
    chunks.push(value);
  }
  let event;
  try {
    const bytes=new Uint8Array(size);let offset=0;
    for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
    event=validateWebsiteEvent(JSON.parse(new TextDecoder().decode(bytes)));
  } catch {return response({error:'invalid_event'},400,true);}
  // Ignore known crawlers. Classification never persists the raw User-Agent or IP.
  const ua=request.headers.get('User-Agent')||'';
  if (/bot\b|crawler|spider|headless|preview/i.test(ua)) return response(null,204,true);
  const {device,os,browser}=classifyAgent(ua);
  const country=/^[A-Z]{2}$/.test(request.cf?.country||'')?request.cf.country:'未知';
  const region=/^[A-Z0-9-]{1,8}$/.test(request.cf?.regionCode||'')?request.cf.regionCode:'未知';
  const now=Math.floor(Date.now()/1000);
  await env.DB.batch([
    env.DB.prepare(`INSERT OR IGNORE INTO website_events
      (id,visitor,session,at,kind,section,target,referrer,country,region,device,os,browser)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)`).bind(event.event_id,await hash(event.visitor_id),await hash(event.session_id),now,event.kind,event.section,event.target,event.referrer||'直接访问 / 未知',country,region,device,os,browser),
    env.DB.prepare("INSERT OR IGNORE INTO website_meta(id,started_at) VALUES(1,?)").bind(now)
  ]);
  return response(null,204,true);
}
export async function websiteSummary(request,env) {
  const params=new URL(request.url).searchParams;
  const days=Number(params.get('days')||30), device=params.get('device')||'all';
  if (![1,7,30,90].includes(days) || !['all','desktop','mobile','tablet'].includes(device)) return response({error:'invalid_filter'},400);
  const now=Math.floor(Date.now()/1000);
  // Calendar days in Asia/Shanghai; explicit timestamps make tests and UTC hosts deterministic.
  const start=Math.floor((now+28800)/86400)*86400-28800-(days-1)*86400;
  const where='at >= ? AND at <= ?'+(device==='all'?'':' AND device = ?');
  const bindings=device==='all'?[start,now]:[start,now,device];
  const query=sql=>env.DB.prepare(sql).bind(...bindings);
  const grouped=(field,kind='pageview')=>query(`SELECT ${field} AS label,count(*) AS count,count(DISTINCT visitor) AS visitors FROM website_events WHERE ${where} AND kind='${kind}' GROUP BY ${field} ORDER BY count DESC,label LIMIT 20`);
  const results=await env.DB.batch([
    query(`SELECT count(CASE WHEN kind='pageview' THEN 1 END) AS pageviews,
      count(DISTINCT visitor) AS visitors,
      count(DISTINCT session) AS sessions,
      count(CASE WHEN kind='download' THEN 1 END) AS clicks,
      count(DISTINCT CASE WHEN kind='download' THEN visitor END) AS download_visitors,
      count(DISTINCT CASE WHEN at>=${now-300} THEN visitor END) AS recent_visitors
      FROM website_events WHERE ${where}`),
    query(`SELECT date(at,'unixepoch','+8 hours') AS day,
      count(CASE WHEN kind='pageview' THEN 1 END) AS pageviews,
      count(DISTINCT visitor) AS visitors,
      count(CASE WHEN kind='download' THEN 1 END) AS clicks FROM website_events WHERE ${where} GROUP BY day ORDER BY day`),
    query(`SELECT strftime('%H',at,'unixepoch','+8 hours') AS label,count(*) AS count FROM website_events WHERE ${where} AND kind='pageview' GROUP BY label ORDER BY label`),
    grouped('referrer'),grouped('country'),grouped("country || ' / ' || region"),grouped('device'),grouped('os'),grouped('browser'),grouped('section','section'),grouped('target','download'),grouped('section'),
    env.DB.prepare('SELECT started_at FROM website_meta WHERE id=1')
  ]);
  const [totals,trend,hours,sources,countries,regions,devices,systems,browsers,sections,downloads,landings,meta]=results.map(r=>r.results);
  return response({as_of:now,started_at:meta[0]?.started_at||null,days,device,start,...totals[0],trend,hours,sources,countries,regions,devices,systems,browsers,sections,downloads,landings});
}
