// The app shell needs its own version.  Article snapshots live in IndexedDB,
// but without these matching HTML/CSS/JS files an offline launch can silently
// fall back to an earlier interface.
const CACHE_NAME = 'legal-kb-app-shell-v211';
const ARTICLE_IMAGE_CACHE = 'legal-kb-article-images-v1';
const SHELL_URLS = [
  '/',
  '/case-manager',
  '/static/style.css?v=2026091401',
  '/static/app.js?v=504',
  '/static/apex-performance.js?v=1',
  '/static/apex-date-picker.js?v=3',
  '/static/sidebar-logo.png?v=2026070401',
  '/static/launch-logo.png?v=2026081301',
  '/static/mingsi_logo.png',
  '/static/color-theme.css?v=11',
  '/static/apex-design-tokens.css?v=1',
  '/static/apex-components.css?v=3',
  '/static/color-theme.js?v=6',
  '/static/apex-api.js?v=1',
  '/static/apex-client-picker.js?v=3',
  '/static/apex-page-lifecycle.js?v=1',
  '/static/search-shortcut.js?v=1',
  '/apple-touch-icon.png?v=20260908',
  '/app-icon-192.png?v=20260908',
  '/manifest.webmanifest?v=20260908'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(SHELL_URLS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => {
        const keep = new Set([CACHE_NAME, ARTICLE_IMAGE_CACHE]);
        return Promise.all(keys.filter(key => !keep.has(key)).map(key => caches.delete(key)));
      })
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== location.origin) return;

  if (request.mode === 'navigate' || request.destination === 'document') {
    event.respondWith(navigationSafe(request));
    return;
  }

  if (url.pathname === '/proxy/image' || request.destination === 'image') {
    event.respondWith(imageFirst(request));
    return;
  }

  if (url.pathname === '/api/tag-categories' || url.pathname === '/api/domains' || url.pathname === '/api/authors') {
    event.respondWith(networkFirst(request, 5000));
    return;
  }

  if (url.pathname === '/static/style.css' || url.pathname === '/static/app.js') {
    // 布局与脚本每次在线加载都优先取新版本，离线时回退缓存，
    // 避免样式/逻辑改动因预缓存版本号未变而迟迟不生效。
    event.respondWith(networkFirst(request));
    return;
  }

  if (url.pathname === '/' || url.pathname === '/case-manager' || url.pathname.startsWith('/static/')) {
    event.respondWith(shellCacheFirst(request));
  }
});

async function navigationSafe(request) {
  let cache = null;
  try {
    cache = await caches.open(CACHE_NAME);
  } catch (error) {
    cache = null;
  }

  try {
    const response = await fetchWithTimeout(request, 5000);
    if (response && response.ok && cache) await cache.put(request, response.clone());
    return response;
  } catch (error) {
    try {
      const fallbackCache = cache || await caches.open(CACHE_NAME);
      const url = new URL(request.url);
      const preferredPath = url.pathname === '/case-manager' ? '/case-manager' : '/';
      const fallback = await fallbackCache.match(preferredPath)
        || await fallbackCache.match('/')
        || await fallbackCache.match('/case-manager');
      if (fallback) return fallback;
    } catch (cacheError) {
      // Fall through to a valid offline response instead of rejecting respondWith.
    }
    return new Response(
      '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>法律操作系统</title><body style="font-family:-apple-system,sans-serif;padding:32px;color:#555">离线缓存尚未准备完成，请连接 Tailscale 后重新打开。</body></html>',
      { status: 200, headers: { 'Content-Type': 'text/html; charset=utf-8' } }
    );
  }
}

async function shellCacheFirst(request) {
  const url = new URL(request.url);
  try {
    const cache = await caches.open(CACHE_NAME);
    // 带版本号的前端资源必须精确匹配。不同版本绝不能互相回退，
    // 否则新版页面会被旧 CSS/JS 覆盖，离线时看起来像“退回旧版”。
    const exact = await cache.match(request);
    if (exact) return exact;
    const response = await fetch(request);
    if (response && response.ok) await cache.put(request, response.clone());
    return response;
  } catch (error) {
    try {
      const cache = await caches.open(CACHE_NAME);
      let fallback = await cache.match(request);
      // Query-free resources may safely reuse a same-path entry.  Versioned
      // resources must either have an exact cache entry or fail explicitly.
      if (!fallback && !url.search) {
        fallback = await cache.match(url.pathname)
          || await caches.match(request);
      }
      if (fallback) return fallback;
    } catch (cacheError) {
      // Let the resource request fail without breaking top-level navigation.
    }
    throw error;
  }
}

function eventlessRefresh(cache, request) {
  fetchWithTimeout(request, 5000)
    .then(response => {
      if (response && response.ok) return cache.put(request, response.clone());
      return undefined;
    })
    .catch(() => undefined);
}

async function networkFirst(request, timeoutMs = 0) {
  const cache = await caches.open(CACHE_NAME);
  try {
    const response = await fetchWithTimeout(request, timeoutMs);
    if (response && response.ok) await cache.put(request, response.clone());
    return response;
  } catch (error) {
    const cached = await cache.match(request);
    if (cached) return cached;
    const url = new URL(request.url);
    const cachedPath = await cache.match(url.pathname);
    if (cachedPath) return cachedPath;
    throw error;
  }
}

async function imageFirst(request) {
  const cache = await caches.open(ARTICLE_IMAGE_CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;
  try {
    const response = await fetchWithTimeout(request, 2500);
    if (response && response.ok) await cache.put(request, response.clone());
    return response;
  } catch (error) {
    const cachedAgain = await cache.match(request);
    if (cachedAgain) return cachedAgain;
    throw error;
  }
}

function fetchWithTimeout(request, timeoutMs = 0) {
  if (!timeoutMs || typeof AbortController === 'undefined') return fetch(request);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  return fetch(request, { signal: controller.signal })
    .finally(() => clearTimeout(timer));
}
