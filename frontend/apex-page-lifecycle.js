(function () {
  'use strict';
  let active = document.visibilityState === 'visible';
  const listeners = new Set();

  function update(next) {
    const value = Boolean(next) && document.visibilityState === 'visible';
    if (value === active) return;
    active = value;
    listeners.forEach(listener => {
      try { listener(active); } catch (_) { /* Keep other consumers running. */ }
    });
    window.dispatchEvent(new CustomEvent('apex:page-visibility', { detail: { active } }));
  }

  window.addEventListener('message', event => {
    if (event.data?.type === 'apex:page-visibility' && event.data.version === 1) update(event.data.active);
  });
  document.addEventListener('visibilitychange', () => update(active));

  window.ApexLifecycle = {
    get active() { return active; },
    onChange(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    interval(callback, milliseconds) {
      return window.setInterval(() => { if (active) callback(); }, milliseconds);
    },
  };
  try { window.parent.postMessage({ type: 'apex:page-ready', version: 1 }, '*'); } catch (_) {}
})();
