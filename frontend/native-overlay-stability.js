/* Mac WebKit can show color blocks when a live backdrop samples composited content.
   The marked masks use one small, blurred image for the duration of each opening. */
(() => {
  'use strict';
  if (!/LegalKB-NativeShell/.test(navigator.userAgent || '')) return;
  const attached = new WeakMap();
  const masks = ':is(.open-pages-overview, .modal-overlay, .overlay, .mask, [class*="-overlay"], ' +
    '[class*="-mask"], [class*="-backdrop"], .confirm-layer, .gate, .ask-word-export-modal, ' +
    '.finchina-candidate-modal, .court-link-modal)';
  const pending = '[data-stella-overlay-pending]';
  const css = `
    :where(${masks}) { --stella-overlay-blur: 0px; }
    ${masks} { -webkit-backdrop-filter: none !important; backdrop-filter: none !important; }
    ${pending}, .drawer-mask${pending} + .drawer, .ask-panel-overlay${pending} + .ask-panel,
    .inspector-backdrop${pending} + .inspector {
      opacity: 0 !important;
      transition-property: none !important;
    }
    [data-stella-overlay-snapshot] {
      background-image: var(--stella-overlay-image) !important;
      background-position: center !important;
      background-size: cover !important;
      background-repeat: no-repeat !important;
    }
    .gate:not([hidden]) { background-color: var(--bg, #202835); }
  `;

  function captureRegion(view, rect, radius) {
    let {left, top, right, bottom} = rect;
    while (true) {
      left = Math.max(0, left);
      top = Math.max(0, top);
      right = Math.min(view.innerWidth, right);
      bottom = Math.min(view.innerHeight, bottom);
      if (right - left < 32 || bottom - top < 32) return null;
      if (view === window) return {
        x: left / view.innerWidth, y: top / view.innerHeight,
        width: (right - left) / view.innerWidth, height: (bottom - top) / view.innerHeight,
        blur: Math.min(0.5, radius / (right - left))
      };
      const frame = view.frameElement;
      if (!frame) return null;
      const box = frame.getBoundingClientRect();
      if (!box.width || !box.height || frame.ownerDocument.defaultView.getComputedStyle(frame).visibility !== 'visible') return null;
      const scaleX = box.width / frame.offsetWidth, scaleY = box.height / frame.offsetHeight;
      left = box.left + (frame.clientLeft + left) * scaleX;
      right = box.left + (frame.clientLeft + right) * scaleX;
      top = box.top + (frame.clientTop + top) * scaleY;
      bottom = box.top + (frame.clientTop + bottom) * scaleY;
      radius *= scaleX;
      view = view.parent;
    }
  }

  // An external document can also be presented through the same-origin reader proxy.
  function hasVisibleExternalFrame(doc) {
    for (const frame of doc.querySelectorAll('iframe')) {
      const rect = frame.getBoundingClientRect();
      const view = doc.defaultView;
      if (!rect.width || !rect.height || rect.bottom <= 0 || rect.right <= 0 ||
          rect.top >= view.innerHeight || rect.left >= view.innerWidth ||
          view.getComputedStyle(frame).visibility !== 'visible') continue;
      const embedded = frame.contentDocument;
      if (!embedded || embedded.location?.pathname === '/api/proxy' || hasVisibleExternalFrame(embedded)) return true;
    }
    return false;
  }

  function install(doc) {
    if (!doc || attached.has(doc) || !doc.documentElement) return;
    const view = doc.defaultView;
    if (!view) return;
    const style = doc.createElement('style');
    style.id = 'stella-native-overlay-stability';
    style.textContent = css;
    (doc.head || doc.documentElement).appendChild(style);
    const bridge = view.webkit?.messageHandlers?.overlayBackdrop;
    const preference = view.matchMedia('(prefers-reduced-transparency: reduce)');
    const candidates = new Set();
    const shown = new Map();
    const embeddedFrames = new Set();

    function release(el) {
      window.clearTimeout(shown.get(el)?.deadline);
      shown.delete(el);
      el.removeAttribute('data-stella-overlay-pending');
      el.removeAttribute('data-stella-overlay-snapshot');
      el.style.removeProperty('--stella-overlay-image');
    }

    function refresh(el) {
      const previous = shown.get(el);
      const style = view.getComputedStyle(el);
      const visible = el.isConnected && !el.hidden && el.getAttribute('aria-hidden') !== 'true' &&
        style.visibility === 'visible' && style.display !== 'none' &&
        (previous?.deadline || style.opacity !== '0' || style.pointerEvents !== 'none');
      const radius = parseFloat(style.getPropertyValue('--stella-overlay-blur'));
      const region = visible && !preference.matches && radius > 0 &&
        captureRegion(view, el.getBoundingClientRect(), radius);
      if (!region) {
        if (previous) release(el);
        return;
      }
      if (previous) return;
      const state = {};
      shown.set(el, state);
      if (hasVisibleExternalFrame(document)) return;

      const tint = style.backgroundColor;
      const layers = style.backgroundImage === 'none' ? [] : [style.backgroundImage];
      layers.push(`linear-gradient(${tint}, ${tint})`);
      // The overview has an opaque fallback below its two tint gradients.
      if (el.classList.contains('open-pages-overview')) layers.pop();
      const finish = image => {
        if (shown.get(el) !== state || !state.deadline) return;
        window.clearTimeout(state.deadline);
        state.deadline = null;
        el.removeAttribute('data-stella-overlay-pending');
        if (typeof image === 'string' && /^data:image\/jpeg;base64,[A-Za-z0-9+/]+=*$/.test(image)) {
          el.style.setProperty('--stella-overlay-image', [...layers, `url("${image}")`].join(', '));
          el.setAttribute('data-stella-overlay-snapshot', '');
        }
      };
      el.setAttribute('data-stella-overlay-pending', '');
      state.deadline = window.setTimeout(finish, 220);
      try {
        Promise.resolve(bridge.postMessage(region)).then(finish, () => finish());
      } catch (_) {
        finish();
      }
    }

    function installFrame(frame) {
      embeddedFrames.add(frame);
      if (frame.contentDocument) install(frame.contentDocument);
    }

    function refreshTree() {
      candidates.forEach(refresh);
      embeddedFrames.forEach(frame => attached.get(frame.contentDocument)?.());
    }
    attached.set(doc, bridge ? refreshTree : null);
    doc.addEventListener('load', event => {
      if (event.target?.tagName === 'IFRAME') installFrame(event.target);
      if (bridge && event.target?.rel === 'stylesheet') refreshTree();
    }, true);
    doc.querySelectorAll('iframe').forEach(installFrame);
    if (!bridge) return;

    const register = el => {
      candidates.add(el);
      return el;
    };
    doc.querySelectorAll(masks).forEach(el => refresh(register(el)));
    new MutationObserver(records => {
      const dirty = new Set(), frames = new Set();
      let removed = false;
      for (const record of records) {
        if (record.type === 'attributes') {
          const el = record.target;
          if (el.matches(masks)) register(el);
          candidates.forEach(candidate => { if (el.contains(candidate)) dirty.add(candidate); });
          embeddedFrames.forEach(frame => { if (el.contains(frame)) frames.add(frame); });
          continue;
        }
        for (const node of record.addedNodes) {
          if (node.nodeType !== 1) continue;
          if (node.matches(masks)) dirty.add(register(node));
          if (node.childElementCount) node.querySelectorAll(masks).forEach(el => dirty.add(register(el)));
        }
        removed ||= record.removedNodes.length > 0;
      }
      if (removed) {
        candidates.forEach(el => {
          if (el.isConnected) return;
          if (shown.has(el)) release(el);
          candidates.delete(el);
        });
        embeddedFrames.forEach(frame => { if (!frame.isConnected) embeddedFrames.delete(frame); });
      }
      dirty.forEach(refresh);
      frames.forEach(frame => attached.get(frame.contentDocument)?.());
    }).observe(doc.documentElement, {subtree: true, childList: true, attributes: true,
      attributeFilter: ['class', 'style', 'hidden', 'aria-hidden']});
    doc.addEventListener('transitionend', event => {
      if (event.propertyName === 'visibility' && candidates.has(event.target)) refresh(event.target);
    });
    preference.addEventListener('change', refreshTree);
    view.addEventListener('pageshow', refreshTree);
    view.addEventListener('pagehide', () => shown.forEach((_, el) => release(el)));
  }
  install(document);
})();
