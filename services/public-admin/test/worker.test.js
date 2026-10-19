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
 const schema=fs.readFileSync(new URL('../migrations/0001_metrics.sql',import.meta.url),'utf8').replace(/^--.*$/gm,'');
 for(const statement of schema.split(';').filter(s=>s.trim()))await DB.prepare(statement).run();
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
 assert.equal(rows.results.length,1);assert.notEqual(rows.results[0].id,event.install_id);assert.equal(rows.results[0].version,'2026101902');
 assert.equal((await env.DB.prepare('SELECT count(*) AS count FROM daily_activity').first()).count,1);
 const logged=await login(request('/api/login',{password}),env);
 const response=await worker.fetch(new Request(origin+'/api/summary',{headers:{Cookie:logged.headers.get('Set-Cookie').split(';')[0]}}),env);
 const summary=await response.json();assert.equal(summary.installations,1);assert.equal(summary.online,1);
 assert.equal(summary.downloads,null);assert.equal(summary.days.length,1);
});
test('download counts exclude deltas; failed refresh preserves snapshot',async()=>{
 const original=globalThis.fetch;
 try{
 globalThis.fetch=async()=>Response.json([{tag_name:'v1',assets:[{name:'Stella-v1.zip',download_count:12},{name:'Stella.delta',download_count:20},{name:'notes.txt',download_count:3}]}]);
 await syncDownloads(env);assert.equal((await env.DB.prepare('SELECT total FROM download_snapshots').first()).total,12);
 globalThis.fetch=async()=>new Response('limited',{status:403});await assert.rejects(syncDownloads(env));
 assert.equal((await env.DB.prepare('SELECT total FROM download_snapshots').first()).total,12);
 }finally{globalThis.fetch=original;}
});
