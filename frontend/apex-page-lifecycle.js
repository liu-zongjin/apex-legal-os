(function () {
  'use strict';
  let active = document.visibilityState === 'visible';
  const listeners = new Set();

  // iframe 标签页被隐藏时，浏览器不会自动暂停 CSS 动画。对于包含长列表、
  // 毛玻璃和状态提示的页面，这些后台合成会直接挤占当前页面的帧时间。
  // 统一标记页面活跃状态，让样式在不可见页暂停非必要运动。
  function syncMotionState() {
    const inactive = !active;
    document.documentElement.classList.toggle('apex-page-inactive', inactive);
    if (document.body) document.body.classList.toggle('apex-page-inactive', inactive);
  }

  function update(next) {
    const value = Boolean(next) && document.visibilityState === 'visible';
    if (value === active) return;
    active = value;
    syncMotionState();
    listeners.forEach(listener => {
      try { listener(active); } catch (_) { /* Keep other consumers running. */ }
    });
    window.dispatchEvent(new CustomEvent('apex:page-visibility', { detail: { active } }));
  }

  window.addEventListener('message', event => {
    if (event.data?.type === 'apex:page-visibility' && event.data.version === 1) update(event.data.active);
  });
  document.addEventListener('visibilitychange', () => update(active));
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', syncMotionState, { once: true });
  } else {
    syncMotionState();
  }

  window.ApexLifecycle = {
    get active() { return active; },
    onChange(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    interval(callback, milliseconds) {
      return window.setInterval(() => { if (active) callback(); }, milliseconds);
    },
  };
  try { window.parent.postMessage({ type: 'apex:page-ready', version: 1 }, '*'); } catch (_) {}
})();
