const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('frontend/case-manager.js', 'utf8');
const start = source.indexOf('async function parseApiResponse(');
const end = source.indexOf('\nlet loginRedirectScheduled', start);
const context = vm.createContext({});
vm.runInContext(source.slice(start, end), context);
function response(status, body, contentType = 'application/json') {
  return {status, ok:status < 400, text:async () => body, headers:{get:() => contentType}};
}
(async () => {
  await assert.rejects(context.parseApiResponse(response(403, JSON.stringify({detail:'请在本机 Stella 中管理和打开本地文件'}))), e => e.kind === 'server' && e.status === 403 && e.message.includes('本机 Stella'));
  await assert.rejects(context.parseApiResponse(response(401, 'Authentication required', 'text/plain')), e => e.kind === 'unauthenticated');
  await assert.rejects(context.parseApiResponse(response(200, '<title>登录法律操作系统</title>', 'text/html')), e => e.kind === 'unauthenticated');
  const data = await context.parseApiResponse(response(200, '{"items":[]}'));
  assert.equal(data.items.length, 0);
  console.log('Case API error handling: passed');
})().catch(e => { console.error(e); process.exitCode = 1; });
