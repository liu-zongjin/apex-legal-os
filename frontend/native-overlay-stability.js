/* Keep WebKit's full-window overlays from sampling moving composited content.
   Narrow glass surfaces retain their existing blur. Runs only in the Mac shell. */
(() => {
  'use strict';
  if (!/LegalKB-NativeShell/.test(navigator.userAgent || '')) return;
  const attached = new WeakSet();
  const css = `
    :is(.open-pages-overview, .modal-overlay, .overlay, .mask,
        [class*="-overlay"], [class*="-mask"], [class*="-backdrop"],
        .confirm-layer, .gate, .ask-word-export-modal, .finchina-candidate-modal, .court-link-modal) {
      -webkit-backdrop-filter: none !important;
      backdrop-filter: none !important;
    }
  `;
  function install(doc) {
    try {
      if (!doc || attached.has(doc) || !doc.documentElement) return;
      attached.add(doc);
      const style = doc.createElement('style');
      style.id = 'stella-native-overlay-stability';
      style.textContent = css;
      (doc.head || doc.documentElement).appendChild(style);
      const installFrame = frame => {
        try { if (frame.contentDocument) install(frame.contentDocument); } catch (_) { /* cross-origin frame */ }
      };
      doc.addEventListener('load', event => {
        if (event.target?.tagName === 'IFRAME') installFrame(event.target);
      }, true);
      doc.querySelectorAll('iframe').forEach(installFrame);
    } catch (_) { /* Cross-origin pages keep their own rendering. */ }
  }
  install(document);
})();
