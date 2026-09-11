const CACHE_NAME = 'legal-kb-case-manager-v202';
const ARTICLE_IMAGE_CACHE = 'legal-kb-article-images-v1';
const SHELL_URLS = [
  '/',
  '/case-manager',
  '/static/style.css?v=2026090705',
  '/static/app.js?v=496',
  '/static/launch-logo.png?v=2026090705',
  '/static/mingsi_logo.png',
  '/apple-touch-icon.png?v=2026090702',
  '/app-icon-192.png?v=2026090702',
  '/manifest.webmanifest?v=2026090704'
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
  try {
    const cache = await caches.open(CACHE_NAME);
    const url = new URL(request.url);
    // 带版本号的前端资源必须精确匹配，避免新 HTML 仍配到旧 CSS/JS。
    // 无网络时才退回同路径旧缓存，兼顾离线可用性。
    const exact = await cache.match(request);
    if (exact) return exact;
    const response = await fetch(request);
    if (response && response.ok) await cache.put(request, response.clone());
    return response;
  } catch (error) {
    try {
      const cache = await caches.open(CACHE_NAME);
      const url = new URL(request.url);
      const fallback = await cache.match(request)
        || await cache.match(url.pathname, { ignoreSearch: true })
        || await caches.match(request, { ignoreSearch: true });
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
