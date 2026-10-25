const SHELL_VERSION = '283';
const CACHE_PREFIX = 'legal-kb-app-shell-v';
const CACHE_NAME = `${CACHE_PREFIX}${SHELL_VERSION}`;
const STAGING_CACHE = `legal-kb-app-shell-staging-v${SHELL_VERSION}`;
const ARTICLE_IMAGE_CACHE = 'legal-kb-article-images-v1';
const SHELL_URL = '/case-manager';
const CACHE_READY_URL = `/__apex_shell_ready__/${SHELL_VERSION}`;
const SHELL_URLS = [
  SHELL_URL,
  '/static/apex-case-record-editor.js?v=2026102108',
  '/static/apex-case-record-editor.css?v=2026102108',
  '/static/apex-record-typography.css?v=2026102108',
  '/static/apex-platform.js?v=2026102001',
  '/static/mobile-brand.js?v=2',
  '/static/brand-logo.js?v=2026100401',
  '/brand-logo.png?v=stella-20261007',
  '/static/case-manager.css?v=283',
  '/static/case-manager.js?v=283',
  '/static/apex-downloads.js?v=2026101903',
  '/static/apex-downloads.css?v=1',
  '/static/color-theme.css?v=11',
  '/static/apex-design-tokens.css?v=2026102503',
  '/static/apex-components.css?v=3',
  '/static/color-theme.js?v=7',
  '/static/apex-api.js?v=1',
  '/static/apex-client-picker.js?v=4',
  '/static/apex-case-picker.js?v=1',
  '/static/apex-case-picker.css?v=1',
  '/static/apex-page-lifecycle.js?v=2026101601',
  '/static/apex-date-picker.js?v=3',
  '/static/search-shortcut.js?v=1',
  '/manifest.webmanifest?v=stella-20261007'
];

// Public UI markup contains no business data; business APIs remain authenticated.
const HOME_URL = '/';
const HOME_SHELL_URL = '/app-shell';
const HOME_READY_URL = `/__stella_home_ready__/${SHELL_VERSION}`;
const HOME_RESOURCES = [
  '/static/apex-case-record-editor.js?v=2026102108',
  '/static/apex-case-record-editor.css?v=2026102108',
  '/static/apex-record-typography.css?v=2026102108',
  '/static/apex-platform.js?v=2026102001',
  '/static/apex-windows-updates.js?v=2026102002',
  '/static/apex-windows-statistics.js?v=2026102301',
  '/static/apex-system-messages.js?v=2026102003',
  '/static/apex-system-messages.css?v=2026102003',
  '/static/apex-appearance.js?v=2026102003',
  '/static/apex-appearance.css?v=2026102003',
  '/static/apex-design-tokens.css?v=2026102503',
  '/static/apex-feature-loader.js?v=2026102003',
  '/static/app-bootstrap.js?v=2026102503',
  '/static/app-ai-lazy.js?v=2026102003',
  '/static/style.min.css?v=2026102503',
  '/static/user-memory.js?v=3',
  '/static/user-memory.css?v=3',
  '/static/sidebar-directory.js?v=2026100802',
  '/static/apex-performance.js?v=2026101601',
  '/static/stella-brand.png?v=2026100701',

  '/static/apex-page-lifecycle.js?v=2026101601',];

self.addEventListener('install', event => event.waitUntil(installVerifiedShell()));
self.addEventListener('activate', event => event.waitUntil(activateVerifiedShell()));
self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== location.origin) return;
  if ((request.mode === 'navigate' || request.destination === 'document') && url.pathname === HOME_URL) {
    event.respondWith(homeNavigation(event));
    return;
  }
  if ((request.mode === 'navigate' || request.destination === 'document') && isCaseManagerNavigation(url)) {
    event.respondWith(caseManagerNavigation(event));
    return;
  }
  if (/^\/(brand-logo|app-icon-\d+|apple-touch-icon(?:-[\w-]+)?)\.png$/.test(url.pathname)) {
    event.respondWith(brandResource(request));
    return;
  }
  if (url.pathname === '/proxy/image' || request.destination === 'image') {
    event.respondWith(imageFirst(request));
    return;
  }
  if (url.pathname.includes('manifest')) {
    event.respondWith(fetch(request, {cache:'no-store'}).catch(() => shellResource(request)));
    return;
  }
  if (isShellResource(url)) event.respondWith(shellResource(request));
});

async function installVerifiedShell() {
  await caches.delete(STAGING_CACHE);
  const staging = await caches.open(STAGING_CACHE);
  for (const path of SHELL_URLS) {
    const request = new Request(path, { cache: 'reload', credentials: 'same-origin' });
    const response = await fetch(request);
    assertValidShellResponse(path, response);
    await staging.put(path, response.clone());
  }
  // Never replace the active cache until every core response has passed validation.
  await caches.delete(CACHE_NAME);
  const current = await caches.open(CACHE_NAME);
  // Copy the document last, then write a completion marker. Readers ignore a
  // cache without that marker, so an interrupted copy falls back to v211.
  for (const path of [...SHELL_URLS.filter(item => item !== SHELL_URL), SHELL_URL]) {
    const response = await staging.match(path);
    if (!response) throw new Error(`missing staged shell resource: ${path}`);
    assertValidShellResponse(path, response);
    await current.put(path, response);
  }
  await current.put(CACHE_READY_URL, new Response(SHELL_VERSION, {
    headers: { 'Content-Type': 'text/plain', 'X-APEX-Shell-Version': SHELL_VERSION },
  }));
  await caches.delete(STAGING_CACHE);
  // Fresh standalone storage must receive the main tab host even before login.
  await prepareHome();
  await self.skipWaiting();
}

async function activateVerifiedShell() {
  const keys = await caches.keys();
  const versions = keys
    .filter(key => key.startsWith(CACHE_PREFIX) && !key.includes('-staging-'))
    .map(key => ({ key, version: Number(key.slice(CACHE_PREFIX.length)) || 0 }))
    .sort((a, b) => b.version - a.version);
  const keep = new Set([CACHE_NAME, ARTICLE_IMAGE_CACHE, ...versions.slice(0, 2).map(item => item.key)]);
  await Promise.all(keys
    .filter(key => (key.startsWith(CACHE_PREFIX) || key.startsWith('legal-kb-app-shell-staging-')) && !keep.has(key))
    .map(key => caches.delete(key)));
  await self.clients.claim();
}

function isCaseManagerNavigation(url) {
  return url.pathname === '/case-manager' || url.pathname === '/case-manager/';
}

function isShellResource(url) {
  return [...SHELL_URLS, ...HOME_RESOURCES].some(path => {
    const expected = new URL(path, location.origin);
    return expected.pathname === url.pathname && expected.search === url.search;
  });
}

async function prepareHome(response) {
  response = response || await fetchWithTimeout(new Request(HOME_SHELL_URL, {
    cache: 'no-store', credentials: 'same-origin', headers: { Accept: 'text/html' },
  }), 10000);
  if (!isValidShellDocument(response)) throw new Error('unverified home shell');
  const cache = await caches.open(CACHE_NAME);
  // Publish the home document only once its resources are usable offline.
  for (const path of HOME_RESOURCES) {
    const asset = await fetchWithTimeout(new Request(path, {cache:'reload', credentials:'same-origin'}), 5000);
    assertValidShellResponse(path, asset);
    await cache.put(path, asset);
  }
  await cache.put(HOME_URL, response.clone());
  await cache.put(HOME_READY_URL, new Response(SHELL_VERSION));
  return response;
}

async function homeNavigation(event) {
  try {
    const response = await fetchWithTimeout(new Request(event.request.url, {
      cache:'no-store', credentials:'same-origin', headers:{Accept:'text/html'},
    }), 1500);
    // Online authentication remains authoritative, including the login page.
    if (isValidShellDocument(response)) event.waitUntil(prepareHome(response.clone()).catch(() => undefined));
    if (response.ok || response.status === 401 || response.status === 403) return response;
    throw new Error('home unavailable');
  } catch (_) {
    const home = await findVerifiedHome();
    if (home) return home;
    return offlineFallback();
  }
}

async function findVerifiedHome() {
  const keys = (await caches.keys()).filter(key => key.startsWith(CACHE_PREFIX) && !key.includes('-staging-'))
    .sort((a,b) => Number(b.slice(CACHE_PREFIX.length))-Number(a.slice(CACHE_PREFIX.length)));
  for (const key of keys) {
    const cache = await caches.open(key);
    const version = key.slice(CACHE_PREFIX.length);
    const ready = await cache.match(`/__stella_home_ready__/${version}`);
    const response = await cache.match(HOME_URL);
    if (ready && response && isValidShellDocument(response, version)) return response;
  }
  return null;
}

async function caseManagerNavigation(event) {
  // Top-level legacy Home Screen launches enter the shared tab host. Iframes
  // keep the case shell, so the redirect cannot recurse inside a case tab.
  if (event.request.destination === 'document' && await findVerifiedHome()) {
    return Response.redirect(new URL('/?workspace=cases', location.origin).href, 302);
  }
  const cached = await findVerifiedShell();
  if (cached) {
    event.waitUntil(refreshCurrentShell().catch(() => undefined));
    return cached;
  }
  try {
    const response = await fetchWithTimeout(new Request(SHELL_URL, {
      cache: 'no-store', credentials: 'same-origin', headers: { Accept: 'text/html' },
    }), 1500);
    assertValidShellResponse(SHELL_URL, response);
    const cache = await caches.open(CACHE_NAME);
    await cache.put(SHELL_URL, response.clone());
    return response;
  } catch (_) {
    return offlineFallback();
  }
}

async function findVerifiedShell() {
  const keys = await caches.keys();
  const candidates = [CACHE_NAME, ...keys
    .filter(key => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME && !key.includes('-staging-'))
    .sort((a, b) => Number(b.slice(CACHE_PREFIX.length)) - Number(a.slice(CACHE_PREFIX.length)))];
  for (const key of candidates) {
    const cache = await caches.open(key);
    const ready = await cache.match(`/__apex_shell_ready__/${key.slice(CACHE_PREFIX.length)}`);
    if (!ready) continue;
    const response = await cache.match(SHELL_URL);
    if (response && isValidShellDocument(response, key.slice(CACHE_PREFIX.length))) return response;
  }
  return null;
}

async function refreshCurrentShell() {
  const response = await fetchWithTimeout(new Request(SHELL_URL, {
    cache: 'no-store', credentials: 'same-origin', headers: { Accept: 'text/html' },
  }), 1500);
  assertValidShellResponse(SHELL_URL, response);
  const cache = await caches.open(CACHE_NAME);
  await cache.put(SHELL_URL, response.clone());
}

async function shellResource(request) {
  const keys = await caches.keys();
  const candidates = [CACHE_NAME, ...keys
    .filter(key => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME && !key.includes('-staging-'))
    .sort((a, b) => Number(b.slice(CACHE_PREFIX.length)) - Number(a.slice(CACHE_PREFIX.length)))];
  for (const key of candidates) {
    const cache = await caches.open(key);
    const ready = await cache.match(`/__apex_shell_ready__/${key.slice(CACHE_PREFIX.length)}`);
    if (!ready) continue;
    const cached = await cache.match(request);
    if (cached) return cached;
  }
  const response = await fetch(request);
  assertValidShellResponse(request.url, response);
  const cache = await caches.open(CACHE_NAME);
  await cache.put(request, response.clone());
  return response;
}

function assertValidShellResponse(path, response) {
  if (!response || !response.ok) throw new Error(`invalid shell status: ${path}`);
  const contentType = (response.headers.get('content-type') || '').toLowerCase();
  const url = new URL(path, location.origin);
  if (url.pathname === SHELL_URL) {
    if (!contentType.includes('text/html') || response.headers.get('x-apex-shell-version') !== SHELL_VERSION) {
      throw new Error('unverified application shell');
    }
    return;
  }
  if (url.pathname.endsWith('.css') && !contentType.includes('text/css')) throw new Error(`invalid CSS: ${path}`);
  if (url.pathname.endsWith('.js') && !/(javascript|ecmascript)/.test(contentType)) throw new Error(`invalid JavaScript: ${path}`);
  if (url.pathname.includes('manifest') && !/(json|manifest)/.test(contentType)) throw new Error(`invalid manifest: ${path}`);
}

function isValidShellDocument(response, expectedVersion = SHELL_VERSION) {
  return response.ok
    && (response.headers.get('content-type') || '').toLowerCase().includes('text/html')
    && response.headers.get('x-apex-shell-version') === expectedVersion;
}

function offlineFallback() {
  return new Response(
    '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>案件管理</title><body style="margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;box-sizing:border-box;background:#f6f7f9;color:#172033;font-family:-apple-system,BlinkMacSystemFont,sans-serif"><main style="max-width:420px;padding:24px;border:1px solid #d8dde7;border-radius:18px;background:#fff;text-align:center"><h1 style="font-size:19px">离线应用尚未准备完成</h1><p style="color:#667085;line-height:1.65">请连接 Tailscale 并启动桌面端服务器，联网登录并打开一次 Stella 后即可离线使用主页与案件管理。</p><button onclick="location.reload()" style="min-height:42px;padding:0 18px;border:0;border-radius:10px;background:#8b1a1a;color:#fff;font-weight:650">重试连接</button></main></body></html>',
    { status: 200, headers: { 'Content-Type': 'text/html; charset=utf-8', 'X-APEX-Offline-Fallback': '1' } }
  );
}

async function imageFirst(request) {
  const cache = await caches.open(ARTICLE_IMAGE_CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetchWithTimeout(request, 2500);
  if (response && response.ok) await cache.put(request, response.clone());
  return response;
}

async function brandResource(request) {
  const cache = await caches.open(ARTICLE_IMAGE_CACHE);
  try {
    const response = await fetchWithTimeout(new Request(request, {cache:'no-store'}), 2500);
    if (!response.ok || !(response.headers.get('content-type') || '').includes('image/')) throw new Error('invalid brand image');
    await cache.put(request, response.clone());
    return response;
  } catch (error) {
    const cached = await cache.match(request);
    if (cached) return cached;
    return shellResource(request);
  }
}

function fetchWithTimeout(request, timeoutMs) {
  if (!timeoutMs || typeof AbortController === 'undefined') return fetch(request);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  return fetch(request, { signal: controller.signal }).finally(() => clearTimeout(timer));
}
