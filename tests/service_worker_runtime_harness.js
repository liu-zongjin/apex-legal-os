const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(process.argv[2], 'utf8');
const origin = 'https://apex.test';

function cacheKey(value) {
  const raw = typeof value === 'string' ? value : value.url;
  const url = new URL(raw, origin);
  return `${url.pathname}${url.search}`;
}

function makeCaches(initial = {}) {
  const stores = new Map();
  for (const [name, entries] of Object.entries(initial)) {
    stores.set(name, new Map(Object.entries(entries)));
  }
  return {
    stores,
    async open(name) {
      if (!stores.has(name)) stores.set(name, new Map());
      const store = stores.get(name);
      return {
        async match(request) {
          const response = store.get(cacheKey(request));
          return response ? response.clone() : undefined;
        },
        async put(request, response) { store.set(cacheKey(request), response.clone()); },
      };
    },
    async delete(name) { return stores.delete(name); },
    async keys() { return [...stores.keys()]; },
  };
}

function shellResponse(version, body = 'shell') {
  return new Response(body, {
    status: 200,
    headers: { 'Content-Type': 'text/html; charset=utf-8', 'X-APEX-Shell-Version': version },
  });
}

function runWorker(caches, fetchImpl) {
  const listeners = {};
  let skipped = false;
  const self = {
    addEventListener(type, callback) { listeners[type] = callback; },
    async skipWaiting() { skipped = true; },
    clients: { async claim() {} },
  };
  class WorkerRequest extends Request {
    constructor(input, init) {
      super(typeof input === 'string' ? new URL(input, origin) : input, init);
    }
  }
  const context = vm.createContext({
    self, caches, fetch: fetchImpl, location: new URL(`${origin}/case-manager-sw.js`),
    URL, Request: WorkerRequest, Response, Headers, AbortController, setTimeout, clearTimeout, console,
  });
  vm.runInContext(source, context, { filename: 'case-manager-sw.js' });
  return { listeners, context, skipped: () => skipped };
}

async function installPromise(listener) {
  let promise;
  listener({ waitUntil(value) { promise = value; } });
  return promise;
}

async function testLoginPageCannotInstall() {
  const oldShell = shellResponse('211', 'old');
  const caches = makeCaches({
    'legal-kb-app-shell-v211': {
      '/case-manager': oldShell,
      '/__apex_shell_ready__/211': new Response('211'),
    },
  });
  const worker = runWorker(caches, async () => new Response('<title>登录法律操作系统</title>', {
    status: 200, headers: { 'Content-Type': 'text/html' },
  }));
  await assert.rejects(installPromise(worker.listeners.install), /unverified application shell/);
  assert.equal(worker.skipped(), false);
  assert.equal(await (await caches.open('legal-kb-app-shell-v211')).match('/case-manager').then(r => r.text()), 'old');
}

async function testCachedNavigationDoesNotWaitForNetwork() {
  const caches = makeCaches({
    'legal-kb-app-shell-v212': {
      '/case-manager': shellResponse('212', 'cached-shell'),
      '/__apex_shell_ready__/212': new Response('212'),
    },
  });
  const worker = runWorker(caches, () => new Promise(() => {}));
  let responsePromise;
  worker.listeners.fetch({
    request: { method: 'GET', url: `${origin}/case-manager`, mode: 'navigate', destination: 'document' },
    respondWith(value) { responsePromise = value; },
    waitUntil() {},
  });
  const response = await Promise.race([
    responsePromise,
    new Promise((_, reject) => setTimeout(() => reject(new Error('cached navigation waited for network')), 100)),
  ]);
  assert.equal(await response.text(), 'cached-shell');
}

async function testPreviousVerifiedVersionIsFallback() {
  const caches = makeCaches({
    'legal-kb-app-shell-v211': {
      '/case-manager': shellResponse('211', 'previous-shell'),
      '/__apex_shell_ready__/211': new Response('211'),
    },
    'legal-kb-app-shell-v212': {
      '/case-manager': shellResponse('212', 'incomplete-shell'),
    },
  });
  const worker = runWorker(caches, () => Promise.reject(new Error('offline')));
  const response = await worker.context.findVerifiedShell();
  assert.equal(await response.text(), 'previous-shell');
}

async function testOfflineHomeAndOnlineLogin() {
  const version = /SHELL_VERSION = '(\d+)'/.exec(source)[1];
  const caches = makeCaches();
  const worker = runWorker(caches, async request => {
    const path = cacheKey(request);
    if (path === '/') return shellResponse(version, 'main-home');
    const type = path.includes('.css') ? 'text/css' : path.includes('.png') ? 'image/png' : 'text/javascript';
    return new Response('asset', {headers:{'Content-Type':type}});
  });
  await worker.context.prepareHome();
  const legacy = await worker.context.caseManagerNavigation({request:{destination:'document'},waitUntil(){}});
  assert.equal(legacy.headers.get('location'), origin+'/?workspace=cases');
  const caseCache = await caches.open('legal-kb-app-shell-v'+version);
  await caseCache.put('/case-manager', shellResponse(version,'case-iframe'));
  await caseCache.put('/__apex_shell_ready__/'+version, new Response(version));
  worker.context.fetch = async () => { throw new Error('offline'); };
  const iframe = await worker.context.caseManagerNavigation({request:{destination:'iframe'},waitUntil(){}});
  assert.equal(await iframe.text(),'case-iframe');
  const event = {request:{url:origin+'/?v=fresh'},waitUntil(){}};
  assert.equal(await (await worker.context.homeNavigation(event)).text(), 'main-home');
  worker.context.fetch = async () => new Response('<title>登录</title>', {headers:{'Content-Type':'text/html'}});
  assert.equal(await (await worker.context.homeNavigation(event)).text(), '<title>登录</title>');
  await assert.rejects(worker.context.prepareHome(), /unverified home shell/);
  assert.equal(await (await (await caches.open('legal-kb-app-shell-v'+version)).match('/')).text(), 'main-home');
}

async function testIncompleteHomeNeverOpens() {
  const version = /SHELL_VERSION = '(\d+)'/.exec(source)[1];
  const caches = makeCaches();
  let count=0;
  const worker = runWorker(caches, async request => {
    if (cacheKey(request) === '/') return shellResponse(version, 'incomplete-home');
    if (++count===2) throw new Error('asset unavailable');
    return new Response('css', {headers:{'Content-Type':'text/css'}});
  });
  await assert.rejects(worker.context.prepareHome(), /asset unavailable/);
  worker.context.fetch = async () => {throw new Error('offline');};
  const response = await worker.context.homeNavigation({request:{url:origin+'/'},waitUntil(){}});
  assert.equal(response.headers.get('X-APEX-Offline-Fallback'), '1');
}

(async () => {
  await testOfflineHomeAndOnlineLogin();
  await testIncompleteHomeNeverOpens();
  await testLoginPageCannotInstall();
  await testCachedNavigationDoesNotWaitForNetwork();
  await testPreviousVerifiedVersionIsFallback();
  process.stdout.write('service worker runtime scenarios passed\n');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
