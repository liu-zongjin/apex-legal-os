(() => {
  const observers = new WeakMap();

  window.updateApexGlassTabs = nav => {
    if (!nav) return;
    const selected = nav.querySelector('.apex-glass-tab.active');
    if (!selected?.offsetWidth) {
      nav.classList.remove('glass-ready');
      return;
    }
    nav.style.setProperty('--glass-x', `${selected.offsetLeft}px`);
    nav.style.setProperty('--glass-width', `${selected.offsetWidth}px`);
    nav.style.setProperty('--glass-top', `${selected.offsetTop}px`);
    nav.style.setProperty('--glass-height', `${selected.offsetHeight}px`);
    nav.classList.add('glass-ready');
    if (!observers.has(nav) && window.ResizeObserver) {
      const observer = new ResizeObserver(() => updateApexGlassTabs(nav));
      observers.set(nav, observer);
      observer.observe(nav);
      nav.querySelectorAll('.apex-glass-tab').forEach(button => observer.observe(button));
    }
  };
})();
