import {test,before,after} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {Miniflare,convertV4MiniflareOptions} from 'miniflare';
import {websiteIngest,websiteSummary,classifyAgent} from '../src/website.js';
import worker from '../src/worker.js';
let mf,env;
const origin='https://liu-zongjin.github.io';
const event=(extra={})=>({event_id:crypto.randomUUID(),visitor_id:crypto.randomUUID(),session_id:crypto.randomUUID(),kind:'pageview',section:'updates',target:'',referrer:'www.google.com',...extra});
function request(body,headers={}){return new Request('https://admin.test/v1/website-events',{method:'POST',headers:{Origin:origin,'Content-Type':'application/json','User-Agent':'Mozilla/5.0 (Macintosh) Safari/605.1',...headers},body:JSON.stringify(body)});}
const summary=query=>websiteSummary(new Request('https://admin.test/api/website'+query),env);
before(async()=>{
 mf=new Miniflare(convertV4MiniflareOptions({modules:true,script:'export default {fetch(){return new Response("ok")}}',d1Databases:['DB'],compatibilityDate:'2026-10-19'}));
 const DB=await mf.getD1Database('DB');
 const schema=fs.readFileSync(new URL('../migrations/0003_website.sql',import.meta.url),'utf8').replace(/^--.*$/gm,'');
 for(const statement of schema.split(';').filter(s=>s.trim()))await DB.prepare(statement).run();
 env={DB,WEBSITE_LIMITER:{limit:async()=>({success:true})}};
});
after(async()=>{await mf?.dispose();});
test('website ingest restricts origin, method, fields, size, rate limits and privacy preferences',async()=>{
 assert.equal((await worker.fetch(new Request('https://admin.test/api/website'),env)).status,401);
 assert.equal((await websiteIngest(request(event(),{Origin:'https://evil.test'}),env)).status,403);
 const preflight=await websiteIngest(new Request('https://admin.test/v1/website-events',{method:'OPTIONS',headers:{Origin:origin}}),env);
 assert.equal(preflight.status,204);assert.equal(preflight.headers.get('Access-Control-Allow-Origin'),origin);
 assert.equal((await websiteIngest(new Request('https://admin.test/v1/website-events',{headers:{Origin:origin}}),env)).status,405);
 for(const extra of [{url:'private'},{referrer:'https://example.com/?secret=x'},{target:'private'},{visitor_id:'user@example.com'},{section:'case-123'}])
  assert.equal((await websiteIngest(request(event(extra)),env)).status,400);
 assert.equal((await websiteIngest(request({extra:'x'.repeat(2200)}),env)).status,413);
 assert.equal((await websiteIngest(request(event()),{...env,WEBSITE_LIMITER:{limit:async()=>({success:false})}})).status,429);
 for(const headers of [{DNT:'1'},{'Sec-GPC':'1'},{'User-Agent':'Googlebot/1.0'}])assert.equal((await websiteIngest(request(event(),headers),env)).status,204);
 assert.equal((await env.DB.prepare('SELECT count(*) AS n FROM website_events').first()).n,0);
});
test('real D1 deduplicates event retries and visitors; dimensions, filters and retention windows are accurate',async()=>{
 const visitor=crypto.randomUUID(),session=crypto.randomUUID(),pv=event({visitor_id:visitor,session_id:session});
 async function send(body){const req=request(body);Object.defineProperty(req,'cf',{value:{country:'CN',regionCode:'SH'}});return websiteIngest(req,env);}
 for(let i=0;i<3;i++)assert.equal((await send(pv)).status,204);
 await send(event({visitor_id:visitor,session_id:session,kind:'download',target:'arm'}));
 await send(event({visitor_id:visitor,session_id:session,kind:'section'}));
 await websiteIngest(request(event({referrer:''}),{'User-Agent':'Mozilla/5.0 (iPhone) Mobile Safari/605.1'}),env);
 const rows=(await env.DB.prepare('SELECT * FROM website_events').all()).results;
 assert.equal(rows.length,4);assert.notEqual(rows[0].visitor,visitor);assert.notEqual(rows[0].session,session);
 assert.ok(!JSON.stringify(rows).includes('Mozilla'));
 const all=await (await summary('?days=7')).json();
 assert.equal(all.pageviews,2);assert.equal(all.visitors,2);assert.equal(all.sessions,2);assert.equal(all.clicks,1);assert.equal(all.download_visitors,1);
 assert.equal(all.downloads[0].label,'arm');assert.equal(all.sections[0].label,'updates');assert.equal(all.countries[0].label,'CN');assert.ok(all.started_at);assert.equal(all.trend.length,1);
 const desktop=await (await summary('?days=1&device=desktop')).json();assert.equal(desktop.pageviews,1);assert.equal(desktop.clicks,1);
 const mobile=await (await summary('?days=30&device=mobile')).json();assert.equal(mobile.pageviews,1);assert.equal(mobile.clicks,0);
 for(const query of ['?days=0','?days=91','?device=unknown',"?device=' OR 1=1"])assert.equal((await summary(query)).status,400);
 await env.DB.prepare('UPDATE website_events SET at=? WHERE id=?').bind(Math.floor(Date.now()/1000)-91*86400,pv.event_id).run();
 assert.equal((await (await summary('?days=90&device=desktop')).json()).pageviews,0);
});
test('browser classification uses coarse categories',()=>{
 assert.deepEqual(classifyAgent('Mozilla/5.0 (iPad) Safari/605.1'),{device:'tablet',os:'iOS',browser:'Safari'});
 assert.deepEqual(classifyAgent('Mozilla/5.0 (Windows NT 10.0) Chrome/130 Edg/130'),{device:'desktop',os:'Windows',browser:'Edge'});
 assert.equal(classifyAgent('Mozilla/5.0 Android Mobile Chrome/130').device,'mobile');
});
test('today uses Shanghai midnight and rolling windows include earlier calendar days',async()=>{
 await env.DB.prepare('DELETE FROM website_events').run();
 const original=Date.now;
 try {
  Date.now=()=>Date.parse('2026-10-20T15:59:59Z');await websiteIngest(request(event()),env);
  Date.now=()=>Date.parse('2026-10-20T16:00:01Z');await websiteIngest(request(event()),env);
  const today=await (await summary('?days=1')).json();assert.equal(today.pageviews,1);assert.equal(today.trend[0].day,'2026-10-21');
  assert.equal(today.start,Date.parse('2026-10-20T16:00:00Z')/1000);
  const week=await (await summary('?days=7')).json();assert.equal(week.pageviews,2);assert.equal(week.trend.length,2);
 }finally{Date.now=original;}
});
