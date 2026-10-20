import {json} from './worker.js';

export function validateMessage(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value) ||
      Object.keys(value).sort().join(',') !== 'body,title' ||
      typeof value.title !== 'string' || typeof value.body !== 'string') throw new Error('消息格式不正确');
  const title = value.title.trim(), body = value.body.trim();
  if (!title || title.length > 80 || /[\r\n\x00-\x1f]/.test(title) ||
      !body || body.length > 6000 || /[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(body)) {
    throw new Error('请填写标题（最多 80 字）和正文（最多 6000 字）');
  }
  return {title, body};
}

export async function publicMessages(request, env) {
  const cors = {'Access-Control-Allow-Origin':'*', 'Access-Control-Allow-Methods':'GET, HEAD, OPTIONS'};
  let response;
  if (request.method === 'OPTIONS') response = new Response(null, {status:204});
  else if (!['GET','HEAD'].includes(request.method)) response = json({error:'method_not_allowed'},405);
  else {
    const {results} = await env.DB.prepare(`SELECT id,title,body,published_at FROM system_messages
      WHERE withdrawn_at IS NULL ORDER BY published_at DESC,id DESC LIMIT 100`).all();
    response = request.method === 'HEAD' ? new Response(null) : json({messages:results});
  }
  for (const [key,value] of Object.entries(cors)) response.headers.set(key,value);
  response.headers.set('Cache-Control','no-store');
  return response;
}

export async function adminMessages(request, env) {
  const url = new URL(request.url), path = url.pathname;
  if (path === '/api/messages' && request.method === 'GET') {
    const offset = Number(url.searchParams.get('offset') || 0);
    if (!Number.isSafeInteger(offset) || offset < 0 || offset > 100000) return json({error:'invalid_offset'},400);
    const {results} = await env.DB.prepare(`SELECT id,title,body,published_at,withdrawn_at FROM system_messages
      ORDER BY published_at DESC,id DESC LIMIT 51 OFFSET ?`).bind(offset).all();
    return json({messages:results.slice(0,50), has_more:results.length>50});
  }
  if (request.method !== 'POST') return json({error:'method_not_allowed'},405);
  if (request.headers.get('Origin') !== url.origin) return json({error:'invalid_origin'},403);
  if (path === '/api/messages') {
    if (!request.headers.get('Content-Type')?.startsWith('application/json')) return json({error:'json_required'},415);
    const reader = request.body?.getReader();
    if (!reader) return json({error:'请填写消息内容'},400);
    let size=0; const chunks=[];
    while (true) {
      const {done,value}=await reader.read(); if(done)break;
      size+=value.byteLength;
      if(size>26000){await reader.cancel();return json({error:'消息过长'},413);}
      chunks.push(value);
    }
    let message;
    try {
      const bytes = new Uint8Array(size); let offset=0;
      for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
      message=validateMessage(JSON.parse(new TextDecoder().decode(bytes)));
    } catch(error) { return json({error:error.message === '消息格式不正确' || error.message?.startsWith('请填写') ? error.message : '消息格式不正确'},400); }
    const id=crypto.randomUUID(), now=Math.floor(Date.now()/1000);
    // One atomic statement prevents concurrent publishers exceeding the feed bound.
    const result=await env.DB.prepare(`INSERT INTO system_messages(id,title,body,published_at)
      SELECT ?,?,?,? WHERE (SELECT count(*) FROM system_messages WHERE withdrawn_at IS NULL)<100`)
      .bind(id,message.title,message.body,now).run();
    if (!result.meta.changes) return json({error:'最多同时展示 100 条消息，请先撤回较早消息'},409);
    return json({id, ...message, published_at:now, withdrawn_at:null},201);
  }
  const match=path.match(/^\/api\/messages\/([0-9a-f-]{36})\/withdraw$/);
  if (!match) return json({error:'not_found'},404);
  await env.DB.prepare('UPDATE system_messages SET withdrawn_at=coalesce(withdrawn_at,?) WHERE id=?')
    .bind(Math.floor(Date.now()/1000),match[1]).run();
  return json({ok:true});
}
