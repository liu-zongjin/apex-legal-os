import { SignJWT, jwtVerify } from 'jose';
import {publicMessages, adminMessages} from './messages.js';
import {websiteIngest,websiteSummary} from './website.js';

const TELEMETRY_SAVE_INTERVAL_SECONDS = 6 * 60 * 60;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

const headers = {
  'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY',
  'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
};
export function json(value, status = 200) {
  return Response.json(value, { status, headers });
}
export function validateEvent(body) {
  if (!body || typeof body !== 'object' || Array.isArray(body) ||
      Object.keys(body).sort().join(',') !== 'install_id,os,version' ||
      !UUID.test(body.install_id) || !/^[1-9][0-9]{0,17}$/.test(body.version) ||
      !/^(?:[0-9]{1,2}\.[0-9]{1,2}\.[0-9]{1,3}|Windows 10\.0\.[0-9]{4,6})$/.test(body.os)) {
    throw new Error('invalid_event');
  }
  return body;
}
const SESSION_COOKIE = '__Host-stella_admin';
const sessionKey = env => new TextEncoder().encode(env.ADMIN_SESSION_SECRET || '');
export async function authorized(request, env) {
  if (!env.ADMIN_SESSION_SECRET || env.ADMIN_SESSION_SECRET.length < 40) return false;
  const token = request.headers.get('Cookie')?.split(';').map(v=>v.trim())
    .find(v=>v.startsWith(SESSION_COOKIE+'='))?.slice(SESSION_COOKIE.length+1);
  if (!token) return false;
  try {
    const {payload} = await jwtVerify(token, sessionKey(env), {
      issuer:'stella-admin', audience:'stella-admin', algorithms:['HS256'], maxTokenAge:'8h'
    });
    return payload.sub === 'administrator';
  } catch { return false; }
}
export async function login(request, env) {
  if (request.method !== 'POST') return json({error:'method_not_allowed'},405);
  if (request.headers.get('Origin') !== new URL(request.url).origin) return json({error:'invalid_origin'},403);
  if (!env.ADMIN_PASSWORD_SHA256 || !/^[a-f0-9]{64}$/.test(env.ADMIN_PASSWORD_SHA256) ||
      !env.ADMIN_SESSION_SECRET || env.ADMIN_SESSION_SECRET.length < 40) return json({error:'后台尚未完成登录配置'},503);
  if (!env.LOGIN_LIMITER || !(await env.LOGIN_LIMITER.limit({key:request.headers.get('CF-Connecting-IP') || 'unknown'})).success) {
    return json({error:'尝试过于频繁，请一分钟后重试'},429);
  }
  if (request.headers.get('Content-Type') !== 'application/json' || Number(request.headers.get('Content-Length')) > 512) {
    return json({error:'invalid_request'},400);
  }
  // Generated 256-bit administrator password: a fast hash is safe for this random
  // high-entropy credential. Never accept a weak user-chosen password here.
  const reader=request.body?.getReader(); let size=0, bytes=[];
  if (!reader) return json({error:'invalid_request'},400);
  while (true) {
    const {done,value}=await reader.read(); if(done)break;
    size+=value.length;
    if(size>512){await reader.cancel();return json({error:'too_large'},413);}
    bytes.push(...value);
  }
  let password;
  try { password=JSON.parse(new TextDecoder().decode(new Uint8Array(bytes))).password; }
  catch { return json({error:'invalid_request'},400); }
  if(typeof password!=='string' || password.length>128) return json({error:'密码不正确'},401);
  const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(password))),
    b=>b.toString(16).padStart(2,'0')).join('');
  let difference=0;
  for(let i=0;i<64;i++) difference |= digest.charCodeAt(i)^env.ADMIN_PASSWORD_SHA256.charCodeAt(i);
  if(difference!==0)return json({error:'密码不正确'},401);
  const token=await new SignJWT({}).setProtectedHeader({alg:'HS256'}).setSubject('administrator')
    .setIssuer('stella-admin').setAudience('stella-admin').setIssuedAt().setExpirationTime('8h').sign(sessionKey(env));
  const response=json({ok:true});
  response.headers.set('Set-Cookie',`${SESSION_COOKIE}=${token}; Secure; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800`);
  return response;
}

async function ingest(request, env) {
  if (request.method !== 'POST') return json({error: 'method_not_allowed'}, 405);
  if (!request.headers.get('Content-Type')?.startsWith('application/json')) return json({error:'json_required'}, 415);
  if (Number(request.headers.get('Content-Length')) > 512) return json({error:'too_large'}, 413);
  // Cloudflare's rate limit uses an ephemeral IP key; no IP is written to D1/logs.
  if (!env.INGEST_LIMITER || !(await env.INGEST_LIMITER.limit({key: request.headers.get('CF-Connecting-IP') || 'unknown'})).success) {
    return json({error:'rate_limited'}, 429);
  }
  const reader = request.body?.getReader();
  let length = 0; const chunks = [];
  if (!reader) return json({error:'invalid_event'}, 400);
  while (true) {
    const {done, value} = await reader.read();
    if (done) break;
    length += value.byteLength;
    if (length > 512) { await reader.cancel(); return json({error:'too_large'}, 413); }
    chunks.push(value);
  }
  let event;
  try {
    const bytes = new Uint8Array(length); let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
    event = validateEvent(JSON.parse(new TextDecoder().decode(bytes)));
  } catch { return json({error:'invalid_event'}, 400); }
  const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode('stella-public:' + event.install_id));
  const id = Array.from(new Uint8Array(hash), b => b.toString(16).padStart(2,'0')).join('');
  const now = Math.floor(Date.now()/1000), day = new Date(now*1000).toISOString().slice(0,10);
  await env.DB.batch([
    env.DB.prepare(`INSERT INTO installations(id,first_seen,last_seen,version,os) VALUES(?,?,?,?,?)
      ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen,version=excluded.version,os=excluded.os
      WHERE installations.last_seen <= excluded.last_seen - ?`)
      .bind(id,now,now,event.version,event.os,TELEMETRY_SAVE_INTERVAL_SECONDS),
    // Atomic with the conditional upsert; duplicate reports write zero rows.
    env.DB.prepare(`INSERT OR IGNORE INTO daily_activity(day,installation_id)
      SELECT ?,id FROM installations WHERE id=? AND last_seen=?`).bind(day,id,now)
  ]);
  return new Response(null, {status:204, headers});
}
export async function syncDownloads(env) {
  if (env.GITHUB_REPOSITORY !== 'liu-zongjin/stella-downloads') throw new Error('repository_not_allowed');
  const assets = [];
  for (let page=1; page<=5; page++) {
    const result = await fetch(`https://api.github.com/repos/${env.GITHUB_REPOSITORY}/releases?per_page=100&page=${page}`, {
      headers: {'User-Agent':'Stella-public-metrics', 'Accept':'application/vnd.github+json'}
    });
    if (!result.ok) throw new Error('github_unavailable');
    const releases = await result.json();
    if (!Array.isArray(releases)) throw new Error('invalid_github_response');
    for (const release of releases) {
      if (release.draft) continue;
      for (const asset of release.assets || []) {
        // Delta transfers and helper files are updates, not full package downloads.
        if (!/^Stella.*\.(zip|dmg)$/i.test(asset.name) && !/^Stella-Windows.*-setup\.exe$/i.test(asset.name)) continue;
        if (!Number.isSafeInteger(asset.download_count) || asset.download_count < 0) throw new Error('invalid_count');
        assets.push({name:asset.name, count:asset.download_count, release:release.tag_name});
      }
    }
    if (releases.length < 100) break;
    if (page === 5) throw new Error('release_limit_exceeded');
  }
  const total = assets.reduce((sum, asset) => sum + asset.count, 0);
  await env.DB.prepare(`INSERT INTO download_snapshots(id,total,checked_at,assets_json) VALUES(1,?,?,?)
    ON CONFLICT(id) DO UPDATE SET total=excluded.total,checked_at=excluded.checked_at,assets_json=excluded.assets_json`)
    .bind(total,Math.floor(Date.now()/1000),JSON.stringify(assets)).run();
}
async function summary(env) {
  const now = Math.floor(Date.now()/1000);
  const [counts, versions, days, downloads] = await env.DB.batch([
    env.DB.prepare(`SELECT count(*) AS installations,
      coalesce(sum(last_seen >= ?),0) AS online,
      coalesce(sum(last_seen >= ?),0) AS active_day,
      coalesce(sum(last_seen >= ?),0) AS active_month FROM installations`)
      .bind(now-TELEMETRY_SAVE_INTERVAL_SECONDS,now-86400,now-30*86400),
    env.DB.prepare('SELECT version,count(*) AS count FROM installations GROUP BY version ORDER BY count DESC LIMIT 50'),
    env.DB.prepare("SELECT day,count(*) AS count FROM daily_activity WHERE day >= date('now','-29 days') GROUP BY day ORDER BY day"),
    env.DB.prepare('SELECT total,checked_at,assets_json FROM download_snapshots WHERE id=1')
  ]);
  const download = downloads.results[0];
  return json({as_of:now, ...counts.results[0], versions:versions.results, days:days.results,
    downloads:download ? {...download, assets:JSON.parse(download.assets_json), assets_json:undefined,
      stale:now-download.checked_at>1800} : null});
}
export default {
  async fetch(request, env) {
    try {
      const path = new URL(request.url).pathname;
      if (path === '/v1/website-events') return await websiteIngest(request,env);
      if (path === '/v1/messages') return await publicMessages(request, env);
      if (path === '/v1/events') return await ingest(request, env);
      if (path === '/api/login') return await login(request,env);
      if (path === '/api/logout') {
        if(request.method!=='POST' || request.headers.get('Origin')!==new URL(request.url).origin) return json({error:'invalid_origin'},403);
        const response=json({ok:true});
        response.headers.set('Set-Cookie',`${SESSION_COOKIE}=; Secure; HttpOnly; SameSite=Strict; Path=/; Max-Age=0`);
        return response;
      }
      if (['/login', '/login.js', '/admin.css', '/apex-design-tokens.css'].includes(path)) {
        if(request.method!=='GET' && request.method!=='HEAD')return json({error:'method_not_allowed'},405);
        const url=new URL(request.url);if(path==='/login')url.pathname='/login.html';
        const asset=await env.ASSETS.fetch(new Request(url,request));
        const response=new Response(asset.body,asset);
        for (const [name,value] of Object.entries(headers)) response.headers.set(name,value);
        response.headers.set('Content-Type',path.endsWith('.js')?'text/javascript':path.endsWith('.css')?'text/css':'text/html; charset=utf-8');
        return response;
      }
      // Every dashboard route/API is protected, including workers.dev and preview URLs.
      if (!(await authorized(request, env))) {
        if(path.startsWith('/api/'))return json({error:'请登录管理后台'},401);
        return new Response(null,{status:303,headers:{...headers,Location:'/login'}});
      }
      if (path === '/api/messages' || path.startsWith('/api/messages/')) return await adminMessages(request, env);
      if (request.method !== 'GET' && request.method !== 'HEAD') return json({error:'method_not_allowed'},405);
      if (path === '/api/website') return await websiteSummary(request,env);
      if (path === '/api/summary') return await summary(env);
      const assetURL = new URL(request.url);
      if (path === '/') assetURL.pathname = '/index.html';
      const response = await env.ASSETS.fetch(new Request(assetURL, request));
      const protectedResponse = new Response(response.body, response);
      for (const [name,value] of Object.entries(headers)) protectedResponse.headers.set(name,value);
      return protectedResponse;
    } catch { return json({error:'服务暂不可用，请稍后重试'},503); }
  },
  async scheduled(_event, env) {
    // Keep only 90 days of per-day activity; lifetime counts retain a hash and timestamps.
    await env.DB.prepare("DELETE FROM daily_activity WHERE day < date('now','-90 days')").run();
    await env.DB.prepare("DELETE FROM website_events WHERE at < ?").bind(Math.floor((Date.now()/1000+28800)/86400)*86400-28800-89*86400).run();
    await syncDownloads(env);
  }
};
