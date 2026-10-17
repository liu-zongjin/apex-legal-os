(function () {
  'use strict';
  let pending = null;
  window.StellaFeatures = {
    loadAI() {
      if (pending) return pending;
      pending = new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = '/static/app-ai-lazy.js?v=2026101703';
        script.onload = resolve;
        script.onerror = () => {
          pending = null;
          script.remove();
          reject(new Error('AI 功能未能加载，请检查连接后重试；原对话已保留。'));
        };
        document.head.appendChild(script);
      });
      return pending;
    },
  };
})();
