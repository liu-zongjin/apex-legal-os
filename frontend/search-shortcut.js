/* 页面内搜索快捷键：在当前页面优先聚焦可见的搜索框。 */
(function installPageSearchShortcut() {
  function isVisible(el) {
    if (!el || el.disabled || el.type === 'hidden') return false;
    const style = window.getComputedStyle(el);
    return style.display !== 'none' && style.visibility !== 'hidden' && el.getClientRects().length > 0;
  }

  function focusPageSearch(event) {
    if (event.key.toLowerCase() !== 'f' || !(event.metaKey || event.ctrlKey) || event.shiftKey || event.altKey) return;

    const selectors = [
      '#search-input', '#detail-search-input',
      '.research-case-search', '.case-list-search input', '.toolbar input.search',
      'input[type="search"]',
      'input[placeholder*="搜索"], textarea[placeholder*="搜索"]',
      'input[id*="search" i], textarea[id*="search" i]',
      'input[class*="search" i], textarea[class*="search" i]'
    ];
    const input = selectors.flatMap(selector => Array.from(document.querySelectorAll(selector)))
      .find(isVisible);
    if (!input) return;

    event.preventDefault();
    input.focus({ preventScroll: true });
    if (typeof input.select === 'function') input.select();
  }

  document.addEventListener('keydown', focusPageSearch, true);
})();
