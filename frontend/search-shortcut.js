/* Shared search shortcut for the workspace and its standalone pages. */
(() => {
  const searchSelectors = [
    '[data-apex-page-search]',
    '#search-input, .detail-search-input, .research-case-search, .mobile-filter-search, .jm-search-field input, .toolbar input.search',
    'input[type="search"]',
    ...['搜索', '筛选', '查找', '检索'].map(label =>
      ['input', 'textarea'].map(field => field + '[placeholder*="' + label + '"], ' + field + '[aria-label*="' + label + '"]').join(', ')
    ),
    'input:is([id*="search" i], [class*="search" i]), textarea:is([id*="search" i], [class*="search" i])'
  ];
  const searchSelector = searchSelectors.join(', ');
  const layers = [
    '[aria-modal="true"]', 'dialog[open]', '.modal-overlay:is(.open, .show)',
    '.drawer:is(.open, .show)', '.ask-panel.open:not(.ask-tabbed)', '#open-pages-overview.open'
  ].join(', ');

  function visible(element) {
    if (!element?.getClientRects().length || element.closest('[hidden], [inert], [aria-hidden="true"]')) return false;
    const style = element.ownerDocument.defaultView.getComputedStyle(element);
    return style.visibility === 'visible';
  }

  function foreground(doc) {
    let highest = -Infinity;
    let layer = null;
    for (const candidate of doc.querySelectorAll(layers)) {
      if (!visible(candidate)) continue;
      const rect = candidate.getBoundingClientRect();
      if (rect.bottom <= 0 || rect.right <= 0 ||
          rect.top >= doc.defaultView.innerHeight || rect.left >= doc.defaultView.innerWidth) continue;
      let z = 0;
      for (let node = candidate; node && node !== doc.body; node = node.parentElement) {
        const value = Number(doc.defaultView.getComputedStyle(node).zIndex);
        if (Number.isFinite(value)) z = Math.max(z, value);
      }
      if (z >= highest) {
        highest = z;
        layer = candidate;
      }
    }
    return layer;
  }

  function isSearchInput(element) {
    return element?.matches(searchSelector) &&
      (element.localName === 'textarea' || ['text', 'search'].includes(element.type)) &&
      !element.matches(':disabled, [readonly]') && visible(element);
  }

  function toggle(scope) {
    const doc = scope.ownerDocument || scope;
    const current = doc.activeElement;
    if (scope.contains(current) && isSearchInput(current)) {
      current.dispatchEvent(new doc.defaultView.CustomEvent('apex:search-dismiss', { bubbles: true }));
      current.blur();
      return true;
    }

    for (const selector of searchSelectors) {
      const input = Array.from(scope.querySelectorAll(selector)).find(isSearchInput);
      if (!input) continue;
      input.focus();
      if (doc.activeElement !== input) continue;
      input.select();
      return true;
    }
    return false;
  }

  function frameDocument(frame) {
    try { return frame?.contentDocument?.body ? frame.contentDocument : null; }
    catch (_) { return null; }
  }

  function toggleDocument(doc) {
    const layer = foreground(doc);
    if (layer) return toggle(layer);
    const activeFrame = doc.activeElement?.matches('iframe') ? doc.activeElement : null;
    if (activeFrame) {
      const child = frameDocument(activeFrame);
      return child ? toggleDocument(child) : false;
    }
    return toggle(doc);
  }

  const bindingKey = 'legal_kb_shortcut_bindings_v1';

  function keyFromEvent(event) {
    const code = event.code || '';
    if (/^Key[A-Z]$/.test(code)) return code.slice(3).toLowerCase();
    if (/^Digit[0-9]$/.test(code)) return code.slice(5);
    return { Minus: '-', Equal: '=' }[code] || '';
  }

  function isConfiguredSearch(event) {
    let bindings;
    try { bindings = JSON.parse(localStorage.getItem(bindingKey) || 'null'); }
    catch (_) { /* Use the default search binding. */ }
    if (!bindings || typeof bindings !== 'object' || Array.isArray(bindings)) {
      return keyFromEvent(event) === 'q' && event.altKey && !event.metaKey && !event.ctrlKey && !event.shiftKey;
    }
    const binding = bindings[keyFromEvent(event)];
    return binding?.actionId === 'focus_search' && Array.isArray(binding.modifiers) &&
      ['meta', 'ctrl', 'alt', 'shift'].every(key => event[key + 'Key'] === binding.modifiers.includes(key));
  }

  function isFindKey(event) {
    return (event.code === 'KeyF' || event.key?.toLowerCase() === 'f') &&
      event.metaKey !== event.ctrlKey && !event.shiftKey && !event.altKey;
  }

  function handle(event, run = () => toggleDocument(document), match = isFindKey) {
    if (event.defaultPrevented || event.isComposing || !match(event)) return false;
    if (!event.repeat && !run()) return false;
    event.preventDefault();
    event.stopPropagation();
    return true;
  }

  window.ApexSearchShortcut = { foreground, toggle, frameDocument, toggleDocument, handle, bindingKey, keyFromEvent };
  if (!document.currentScript?.hasAttribute('data-workspace-host')) {
    document.addEventListener('keydown', (event) =>
      handle(event, undefined, key => isFindKey(key) || isConfiguredSearch(key)), true);
  }
})();
