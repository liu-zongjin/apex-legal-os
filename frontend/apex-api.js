(function (global) {
  'use strict';

  const clientCache = new Map();
  const CACHE_MS = 60 * 1000;

  async function requestJSON(url, options) {
    const response = await fetch(url, { cache: 'no-store', ...(options || {}) });
    let payload = null;
    try { payload = await response.json(); } catch (_) { /* handled below */ }
    if (!response.ok) {
      const error = new Error(payload?.detail || payload?.message || `请求失败（${response.status}）`);
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function normalizeClient(item) {
    if (typeof item === 'string') return { id: null, name: item.trim(), client_type: '', identity_code: '' };
    return {
      ...item,
      id: Number.isFinite(Number(item?.id)) ? Number(item.id) : null,
      name: String(item?.name || item?.label || item?.value || '').trim(),
      client_type: String(item?.client_type || '').trim(),
      identity_code: String(item?.identity_code || '').trim(),
    };
  }

  function uniqueClients(items) {
    const byIdentity = new Map();
    (items || []).map(normalizeClient).filter(item => item.name).forEach(item => {
      const key = item.id ? `id:${item.id}` : `name:${item.name}`;
      if (!byIdentity.has(key)) byIdentity.set(key, item);
    });
    return [...byIdentity.values()];
  }

  async function searchClients(query = '', limit = 2000, options = {}) {
    const q = String(query || '').trim();
    const boundedLimit = Math.max(1, Math.min(Number(limit) || 500, 2000));
    const key = `${q}\u0000${boundedLimit}`;
    const cached = clientCache.get(key);
    if (!options.fresh && cached && Date.now() - cached.at < CACHE_MS) return cached.items.slice();
    const payload = await requestJSON(`/api/case-manager/clients?q=${encodeURIComponent(q)}&limit=${boundedLimit}`);
    const items = uniqueClients(payload?.items || []);
    clientCache.set(key, { at: Date.now(), items });
    return items.slice();
  }

  async function clientProfile(client) {
    const item = normalizeClient(client);
    if (item.id) {
      try { return await requestJSON(`/api/case-manager/clients/${item.id}`); } catch (_) { /* name fallback */ }
    }
    if (!item.name) throw new Error('缺少委托人名称');
    return requestJSON(`/api/document-generators/client-profile?name=${encodeURIComponent(item.name)}`);
  }

  function clearClientCache() { clientCache.clear(); }

  global.ApexAPI = Object.freeze({
    requestJSON,
    normalizeClient,
    uniqueClients,
    searchClients,
    clientProfile,
    clearClientCache,
  });
})(window);

