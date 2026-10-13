const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('frontend/case-manager.js', 'utf8');
const start = source.indexOf('async function parseApiResponse(');
const end = source.indexOf('\nasync function applyCaseServerConnection', start);
let currentResponse, redirects = [], fallback = 0;
const context = vm.createContext({
  state: {offlineMode:false, offlineReady:true},
  window: {location:{assign:url=>redirects.push(url)}},
  location:{origin:'http://localhost:8000'},
  fetchWithTimeout:async()=>currentResponse,
  caseManagerApiTimeout:()=>100,
  requireOnlineAction:()=>true,
  offlineApi:()=>{fallback++;return {cached:true};},
  updateOfflineStatus:()=>{}, toast:()=>{},
});
vm.runInContext(source.slice(start, end), context);
function response(status, body, contentType = 'application/json', marker = '') {
  return {status, ok:status < 400, text:async () => body,
    headers:{get:name=>name==='content-type'?contentType:name==='x-apex-auth-required'?marker:null}};
}
(async () => {
  for (const status of [400,401,403,404,409,422]) {
    currentResponse=response(status, JSON.stringify({detail:'法院官网会话已过期，请重新登录'}));
    await assert.rejects(context.api('/api/case-manager/court-online/readings/1/detail'),
      e=>e.kind==='server'&&e.status===status&&e.message.includes('法院官网'));
    assert.equal(redirects.length,0);
    assert.equal(fallback,0);
    assert.equal(context.state.serverOnline,true);
  }
  currentResponse=response(401, JSON.stringify({detail:'请先登录官网'}));
  await assert.rejects(context.api('/api/case-manager/court-online/login',{method:'POST'}),e=>e.kind==='server');
  assert.equal(redirects.length,0);
  await assert.rejects(context.parseApiResponse(response(401,'Authentication required','text/plain')),e=>e.kind==='unauthenticated');
  await assert.rejects(context.parseApiResponse(response(401,'{}','application/json','local')),e=>e.kind==='unauthenticated');
  await assert.rejects(context.parseApiResponse(response(200,'<title>登录法律操作系统</title>','text/html')),e=>e.kind==='unauthenticated');
  assert.equal((await context.parseApiResponse(response(200,'{"items":[]}'))).items.length,0);
  // Actual network failure keeps the existing offline fallback.
  context.fetchWithTimeout=async()=>{throw new TypeError('Failed to fetch');};
  assert.equal((await context.api('/api/case-manager/cases')).cached,true);
  assert.equal(fallback,1);
  context.fetchWithTimeout=async()=>response(401,'Authentication required','text/plain','local');
  await assert.rejects(context.api('/api/case-manager/cases'),e=>e.kind==='unauthenticated');
  assert.equal(redirects.length,1);
  assert(redirects[0].startsWith('/login?next='));
  assert.equal(fallback,1);
  console.log('Case API error handling: passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
