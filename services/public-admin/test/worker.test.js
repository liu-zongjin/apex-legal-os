import {test,before,after} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {Miniflare,convertV4MiniflareOptions} from 'miniflare';
import {SignJWT} from 'jose';
import worker,{authorized,login,validateEvent,syncDownloads} from '../src/worker.js';
let mf,env;
const origin='https://admin.example.test';
const event={install_id:'b5307a71-6eb1-4484-b0a8-381a8733ff86',version:'2026101901',os:'12.7.6'};
const password='test-only-256-bit-credential-not-a-real-password';
const request=(path,body,headers={})=>new Request(origin+path,{method:'POST',headers:{Origin:origin,'Content-Type':'application/json',...headers},body:JSON.stringify(body)});
before(async()=>{
 mf=new Miniflare(convertV4MiniflareOptions({modules:true,script:'export default {fetch(){return new Response("ok")}}',d1Databases:['DB'],compatibilityDate:'2026-10-19'}));
 const DB=await mf.getD1Database('DB');
 for(const name of ['0001_metrics.sql','0002_messages.sql']) {
  const schema=fs.readFileSync(new URL('../migrations/'+name,import.meta.url),'utf8').replace(/^--.*$/gm,'');
  for(const statement of schema.split(';').filter(s=>s.trim()))await DB.prepare(statement).run();
 }
 const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(password));
 env={DB,INGEST_LIMITER:{limit:async()=>({success:true})},LOGIN_LIMITER:{limit:async()=>({success:true})},
 ADMIN_PASSWORD_SHA256:Buffer.from(digest).toString('hex'),ADMIN_SESSION_SECRET:'test-only-session-secret-with-over-forty-characters',
 GITHUB_REPOSITORY:'liu-zongjin/stella-downloads',ASSETS:{fetch:async()=>new Response('protected assets')}};
});
after(async()=>{await mf?.dispose();});
test('admin fails closed without config, unsigned and forged sessions',async()=>{
 assert.equal(await authorized(new Request(origin),{}),false);
 assert.equal(await authorized(new Request(origin,{headers:{Cookie:'__Host-stella_admin=forged'}}),env),false);
 assert.equal((await worker.fetch(new Request(origin+'/api/summary'),env)).status,401);
 const response=await worker.fetch(new Request(origin+'/admin.js'),env);
 assert.equal(response.status,303);assert.equal(response.headers.get('Location'),'/login');
});
test('login validates origin, rate limit, password, secure cookie and expiry',async()=>{
 assert.equal((await login(request('/api/login',{password:'wrong'}),env)).status,401);
 assert.equal((await login(request('/api/login',{password},{Origin:'https://attacker.test'}),env)).status,403);
 assert.equal((await login(request('/api/login',{password}),{...env,LOGIN_LIMITER:{limit:async()=>({success:false})}})).status,429);
 const response=await login(request('/api/login',{password}),env);assert.equal(response.status,200);
 const cookie=response.headers.get('Set-Cookie');
 for(const flag of ['Secure','HttpOnly','SameSite=Strict','Path=/','Max-Age=28800'])assert.ok(cookie.includes(flag));
 assert.equal(await authorized(new Request(origin,{headers:{Cookie:cookie.split(';')[0]}}),env),true);
 const expired=await new SignJWT({}).setProtectedHeader({alg:'HS256'}).setSubject('administrator')
 .setIssuer('stella-admin').setAudience('stella-admin').setIssuedAt(1).setExpirationTime(2)
 .sign(new TextEncoder().encode(env.ADMIN_SESSION_SECRET));
 assert.equal(await authorized(new Request(origin,{headers:{Cookie:'__Host-stella_admin='+expired}}),env),false);
});
test('bounded allowlisted telemetry and rate limiting',async()=>{
 for(const body of [{...event,file:'case.docx'},{...event,install_id:'real-person'},{...event,version:'<script>'},null]){
 assert.throws(()=>validateEvent(body));assert.equal((await worker.fetch(request('/v1/events',body),env)).status,400);
 }
 assert.equal((await worker.fetch(request('/v1/events',{extra:'x'.repeat(600)}),env)).status,413);
 assert.equal((await worker.fetch(request('/v1/events',event),{...env,INGEST_LIMITER:{limit:async()=>({success:false})}})).status,429);
});
test('heartbeats deduplicate installations and daily active in real D1',async()=>{
 for(let i=0;i<3;i++)assert.equal((await worker.fetch(request('/v1/events',event),env)).status,204);
 assert.equal((await worker.fetch(request('/v1/events',{...event,version:'2026101902'}),env)).status,204);
 const rows=await env.DB.prepare('SELECT * FROM installations').all();
 assert.equal(rows.results.length,1);assert.notEqual(rows.results[0].id,event.install_id);assert.equal(rows.results[0].version,event.version);
 assert.equal((await env.DB.prepare('SELECT count(*) AS count FROM daily_activity').first()).count,1);
 const logged=await login(request('/api/login',{password}),env);
 const response=await worker.fetch(new Request(origin+'/api/summary',{headers:{Cookie:logged.headers.get('Set-Cookie').split(';')[0]}}),env);
 const summary=await response.json();assert.equal(summary.installations,1);assert.equal(summary.online,1);
 assert.equal(summary.downloads,null);assert.equal(summary.days.length,1);
});
test('six-hour persistence skips writes across restarts, concurrent requests and midnight',async()=>{
 const originalNow=Date.now;
 const fixture={...event,install_id:'459b19c4-411b-4c5d-801c-4f72475b63d4'};
 const start=Date.UTC(2027,0,1,23,0,0)/1000;
 let now=start,writes=0,saves=0;
 const freshEnv=()=>({...env,DB:{prepare:sql=>env.DB.prepare(sql),batch:async statements=>{
  const results=await env.DB.batch(statements);
  writes+=results.reduce((n,r)=>n+r.meta.rows_written,0);saves+=results[0].meta.changes;return results;
 }}});
 const send=()=>worker.fetch(request('/v1/events',{...fixture,version:now===start?event.version:'2026101902'}),freshEnv());
 try {
  Date.now=()=>now*1000;
  assert.equal((await send()).status,204);assert.ok(writes>0);
  const row0=await env.DB.prepare('SELECT * FROM installations WHERE first_seen=?').bind(start).first();
  const id=row0.id;
  writes=0;saves=0;
  for(const elapsed of [0,60,3600,21599]){now=start+elapsed;assert.equal((await send()).status,204);}
  assert.equal(writes,0);
  let row=await env.DB.prepare('SELECT * FROM installations WHERE id=?').bind(id).first();
  assert.equal(row.last_seen,start);assert.equal(row.version,event.version);
  assert.equal((await env.DB.prepare('SELECT count(*) AS n FROM daily_activity WHERE installation_id=?').bind(id).first()).n,1);
  now=start+21600;
  const responses=await Promise.all([send(),send(),send()]);
  assert.ok(responses.every(r=>r.status===204));assert.ok(writes>0);assert.equal(saves,1);
  row=await env.DB.prepare('SELECT * FROM installations WHERE id=?').bind(id).first();
  assert.equal(row.first_seen,start);assert.equal(row.last_seen,now);assert.equal(row.version,'2026101902');
  assert.equal((await env.DB.prepare('SELECT count(*) AS n FROM daily_activity WHERE installation_id=?').bind(id).first()).n,2);
  writes=0;now++;
  assert.equal((await send()).status,204);assert.equal(writes,0);
  const logged=await login(request('/api/login',{password}),env);
  const Cookie=logged.headers.get('Set-Cookie').split(';')[0];
  const summary=async()=> (await worker.fetch(new Request(origin+'/api/summary',{headers:{Cookie}}),env)).json();
  now=start+21600+3600;assert.equal((await summary()).online,1);
  now=start+21600+21600;assert.equal((await summary()).online,1);
  now++;assert.equal((await summary()).online,0);
 } finally {Date.now=originalNow;}
});

test('download counts exclude deltas; failed refresh preserves snapshot',async()=>{
 const original=globalThis.fetch;
 try{
 globalThis.fetch=async()=>Response.json([{tag_name:'v1',assets:[{name:'Stella-v1.zip',download_count:12},{name:'Stella.delta',download_count:20},{name:'notes.txt',download_count:3},{name:'Stella-Windows-1.1.6-setup.exe',download_count:7},{name:'browser-component.zip',download_count:99},{name:'other.exe',download_count:99}]}]);
 await syncDownloads(env);assert.equal((await env.DB.prepare('SELECT total FROM download_snapshots').first()).total,19);
 globalThis.fetch=async()=>new Response('limited',{status:403});await assert.rejects(syncDownloads(env));
 assert.equal((await env.DB.prepare('SELECT total FROM download_snapshots').first()).total,19);
 }finally{globalThis.fetch=original;}
});

test('login HTML errors and redirects retain their real status',async()=>{
 for(const status of [404,503,308]){
  const response=await worker.fetch(new Request(origin+'/login'),{...env,ASSETS:{fetch:async()=>new Response(null,{status,headers:{Location:'/login'}})}});
  assert.equal(response.status,status);
  assert.equal(response.headers.get('Cache-Control'),'no-store');
 }
 const response=await worker.fetch(new Request(origin+'/login'),{...env,ASSETS:{fetch:async r=>{
  assert.equal(new URL(r.url).pathname,'/login.html');
  return new Response('<h1>fixture login</h1>');
 }}});
 assert.equal(response.status,200);assert.ok((await response.text()).includes('fixture login'));
});

test('authenticated dashboard root resolves explicit HTML without exposing it before login',async()=>{
 assert.equal((await worker.fetch(new Request(origin+'/'),env)).status,303);
 const logged=await login(request('/api/login',{password}),env);
 const response=await worker.fetch(new Request(origin+'/',{headers:{Cookie:logged.headers.get('Set-Cookie').split(';')[0]}}),
  {...env,ASSETS:{fetch:async request=>{
   assert.equal(new URL(request.url).pathname,'/index.html');
   return new Response('<h1>fixture dashboard</h1>');
  }}});
 assert.equal(response.status,200);assert.ok((await response.text()).includes('fixture dashboard'));
});

test('announcements require admin and same origin; public feed exposes active text only',async()=>{
 assert.equal((await worker.fetch(request('/api/messages',{title:'test',body:'test'}),env)).status,401);
 assert.equal((await worker.fetch(new Request(origin+'/messages-admin.js'),env)).status,303);
 const logged=await login(request('/api/login',{password}),env),Cookie=logged.headers.get('Set-Cookie').split(';')[0];
 const post=(path,body,headers={})=>request(path,body,{Cookie,...headers});
 assert.equal((await worker.fetch(post('/api/messages',{title:'a',body:'b'},{Origin:'https://evil.test'}),env)).status,403);
 for(const payload of [{title:' ',body:'a'},{title:'a',body:'b',url:'https://evil.test'},{title:'x'.repeat(81),body:'b'},{title:'a',body:'b'.repeat(6001)}])
  assert.equal((await worker.fetch(post('/api/messages',payload),env)).status,400);
 assert.equal((await worker.fetch(post('/api/messages',{title:'a',body:'b'.repeat(27000)}),env)).status,413);
 const content={title:'服务通知 <script>',body:'第一段\n<img src=x onerror=alert(1)>\n第二段'};
 const published=await worker.fetch(post('/api/messages',content),env);assert.equal(published.status,201);
 const item=await published.json();
 const response=await worker.fetch(new Request(origin+'/v1/messages'),env);
 assert.equal(response.headers.get('Access-Control-Allow-Origin'),'*');assert.equal(response.headers.get('Cache-Control'),'no-store');
 const feed=await response.json();assert.equal(feed.messages.length,1);assert.equal(feed.messages[0].body,content.body);
 assert.deepEqual(Object.keys(feed.messages[0]).sort(),['body','id','published_at','title']);
 assert.equal((await worker.fetch(request('/v1/messages',content),env)).status,405);
 assert.equal((await worker.fetch(new Request(origin+'/v1/messages',{method:'OPTIONS'}),env)).status,204);
 assert.equal((await worker.fetch(new Request(origin+'/api/messages?offset=-1',{headers:{Cookie}}),env)).status,400);
 assert.equal((await worker.fetch(new Request(origin+'/api/messages',{headers:{Cookie}}),env)).status,200);
 assert.equal((await worker.fetch(post('/api/messages/'+item.id+'/withdraw',{}),env)).status,200);
 assert.equal((await worker.fetch(post('/api/messages/'+item.id+'/withdraw',{}),env)).status,200);
 assert.equal((await (await worker.fetch(new Request(origin+'/v1/messages'),env)).json()).messages.length,0);
 const history=await (await worker.fetch(new Request(origin+'/api/messages',{headers:{Cookie}}),env)).json();
 assert.ok(history.messages[0].withdrawn_at);assert.equal(history.has_more,false);
});

test('message feed bound is enforced atomically and history paginates',async()=>{
 await env.DB.prepare('DELETE FROM system_messages').run();
 const statements=Array.from({length:100},(_,i)=>env.DB.prepare('INSERT INTO system_messages(id,title,body,published_at) VALUES(?,?,?,?)').bind(crypto.randomUUID(),'通知 '+i,'内容',100+i));
 await env.DB.batch(statements);
 const logged=await login(request('/api/login',{password}),env),Cookie=logged.headers.get('Set-Cookie').split(';')[0];
 const result=await worker.fetch(request('/api/messages',{title:'第101条',body:'内容'},{Cookie}),env);
 assert.equal(result.status,409);
 const page=await (await worker.fetch(new Request(origin+'/api/messages?offset=50',{headers:{Cookie}}),env)).json();
 assert.equal(page.messages.length,50);assert.equal(page.has_more,false);
 const first=await (await worker.fetch(new Request(origin+'/api/messages',{headers:{Cookie}}),env)).json();
 assert.equal(first.messages.length,50);assert.equal(first.has_more,true);
 assert.equal((await (await worker.fetch(new Request(origin+'/v1/messages'),env)).json()).messages.length,100);
 await env.DB.prepare('DELETE FROM system_messages').run();
});

test('Windows anonymous metrics retain exact payload allowlist and six-hour deduplication',async()=>{
 const windows={install_id:'a811d260-145e-4a93-8a4f-bb6fa405f2fb',version:'2026102301',os:'Windows 10.0.26100'};
 assert.deepEqual(validateEvent(windows),windows);
 for(const os of ['Windows 10.0.19045','Windows 10.0.22631'])assert.equal(validateEvent({...windows,os}).os,os);
 for(const os of ['Windows user-name','Windows 10.0.26100 account','Windows 10.0.1'])assert.throws(()=>validateEvent({...windows,os}));
 const start=1900000000000,originalNow=Date.now;let writes=0;
 const target={...env,DB:{prepare:sql=>env.DB.prepare(sql),batch:async statements=>{
  const results=await env.DB.batch(statements);writes+=results.reduce((n,r)=>n+r.meta.rows_written,0);return results;
 }}};
 try{
  Date.now=()=>start;assert.equal((await worker.fetch(request('/v1/events',windows),target)).status,204);assert.ok(writes>0);
  writes=0;Date.now=()=>start+21599000;assert.equal((await worker.fetch(request('/v1/events',windows),target)).status,204);assert.equal(writes,0);
  Date.now=()=>start+21600000;assert.equal((await worker.fetch(request('/v1/events',windows),target)).status,204);assert.ok(writes>0);
 }finally{Date.now=originalNow;}
});
