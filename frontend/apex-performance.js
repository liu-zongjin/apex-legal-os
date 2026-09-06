(function () {
  'use strict';

  let longTaskCount = 0;
  let longTaskMaxMs = 0;
  if ('PerformanceObserver' in window) {
    try {
      const observer = new PerformanceObserver(list => {
        list.getEntries().forEach(entry => {
          longTaskCount += 1;
          longTaskMaxMs = Math.max(longTaskMaxMs, entry.duration || 0);
        });
      });
      observer.observe({ entryTypes: ['longtask'] });
    } catch (_) { /* Older WebKit does not expose longtask entries. */ }
  }

  function frameIsActive(frame, activeTabId) {
    const page = frame.closest('.tab-page');
    if (!page) return document.visibilityState === 'visible';
    const pageId = page.id === 'tab-page-main' ? 'main' : page.id;
    return document.visibilityState === 'visible' && pageId === activeTabId;
  }

  function publishPageActivity(activeTabId) {
    document.querySelectorAll('iframe').forEach(frame => {
      try {
        frame.contentWindow.postMessage({
          type: 'apex:page-visibility',
          version: 1,
          active: frameIsActive(frame, activeTabId),
        }, '*');
      } catch (_) { /* Cross-origin pages receive the same postMessage when allowed. */ }
    });
  }

  function sample() {
    const tabs = typeof tabState === 'object' && Array.isArray(tabState.tabs) ? tabState.tabs.length : 0;
    return {
      openTabs: tabs,
      mountedPages: document.querySelectorAll('.tab-page').length,
      iframes: document.querySelectorAll('iframe').length,
      domNodes: document.getElementsByTagName('*').length,
      longTasks: longTaskCount,
      longTaskMaxMs: Math.round(longTaskMaxMs * 10) / 10,
      visible: document.visibilityState === 'visible',
    };
  }

  async function report() {
    if (document.visibilityState !== 'visible') return;
    try {
      await fetch('/api/diagnostics/frontend', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(sample()),
        keepalive: true,
      });
    } catch (_) { /* Diagnostics must never interrupt legal work. */ }
  }

  window.ApexPerformance = { sample, report, publishPageActivity };
  document.addEventListener('visibilitychange', () => {
    const activeId = typeof tabState === 'object' ? tabState.activeTabId : 'main';
    publishPageActivity(activeId);
    if (document.visibilityState === 'visible') report();
  });
  window.addEventListener('message', event => {
    if (event.data?.type === 'apex:page-ready') {
      const activeId = typeof tabState === 'object' ? tabState.activeTabId : 'main';
      publishPageActivity(activeId);
    }
  });
  setTimeout(report, 5000);
  setInterval(report, 60000);
})();
