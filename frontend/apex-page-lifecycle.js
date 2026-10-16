(function () {
  'use strict';
  // Host selection and document visibility are independent inputs. Never feed
  // the derived state back into itself: one background event would latch false.
  let hostActive = true;
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

  function update() {
    const value = hostActive && document.visibilityState === 'visible';
    if (value === active) return;
    active = value;
    syncMotionState();
    listeners.forEach(listener => {
      try { listener(active); } catch (_) { /* Keep other consumers running. */ }
    });
    window.dispatchEvent(new CustomEvent('apex:page-visibility', { detail: { active } }));
  }

  window.addEventListener('message', event => {
    if (event.source === window.parent && event.origin === location.origin && event.data?.type === 'apex:page-visibility' && event.data.version === 1) {
      hostActive = Boolean(event.data.active);
      update();
    }
  });
  document.addEventListener('visibilitychange', update);
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', syncMotionState, { once: true });
  } else {
    syncMotionState();
  }

  window.ApexLifecycle = {
    get active() { return active; },
    onChange(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    interval(callback, milliseconds) {
      let running = false;
      return window.setInterval(() => {
        if (!active || running) return;
        running = true;
        try {
          const result = callback();
          if(result && typeof result.then === 'function') result.catch(()=>{}).finally(()=>{running=false;});
          else running = false;
        } catch (_) { running=false; }
      }, milliseconds);
    },
  };
  try { window.parent.postMessage({ type: 'apex:page-ready', version: 1 }, '*'); } catch (_) {}
})();
