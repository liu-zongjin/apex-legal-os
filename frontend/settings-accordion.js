(() => {
  const sections = Array.from(document.querySelectorAll('.settings-modal .settings-section[data-settings-group]'));
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  function setOpen(section, opened, animate = false) {
    if (section.hasAttribute('data-settings-static')) return;
    const wasOpen = section.classList.contains('settings-accordion-open');
    if (wasOpen === opened) return;
    const head = section.querySelector(':scope > .settings-section-head');
    const canAnimate = animate && section.classList.contains('active') && !reducedMotion.matches;
    const startHeight = canAnimate ? section.getBoundingClientRect().height : 0;
    section.getAnimations().forEach(animation => animation.cancel());
    section.classList.toggle('settings-accordion-open', opened);
    head?.setAttribute('aria-expanded', String(opened));
    if (opened) section.dispatchEvent(new CustomEvent('settings:opened'));
    if (canAnimate) {
      const endHeight = section.getBoundingClientRect().height;
      section.animate([{height: `${startHeight}px`, overflow: 'hidden'}, {height: `${endHeight}px`, overflow: 'hidden'}], {duration: 260, easing: 'cubic-bezier(.22, 1, .36, 1)'});
      if (opened) Array.from(section.children).filter(node => node !== head).forEach(node => node.animate([{opacity: 0, transform: 'translateY(-5px)'}, {opacity: 1, transform: 'translateY(0)'}], {duration: 220, easing: 'ease-out'}));
    }
  }
  function open(section, animate = false) {
    if (!sections.includes(section) || section.hasAttribute('data-settings-static')) return;
    sections.forEach(item => setOpen(item, item === section, animate));
  }
  function select(group, sectionId) {
    sections.forEach(section => setOpen(section, false));
    if (sectionId !== group) {
      const target = document.getElementById('settings-section-' + sectionId);
      if (target?.dataset.settingsGroup === group) open(target);
    }
  }
  sections.forEach(section => {
    const head = section.querySelector(':scope > .settings-section-head');
    if (!head || section.hasAttribute('data-settings-static')) return;
    head.setAttribute('role', 'button'); head.tabIndex = 0;
    head.setAttribute('aria-expanded', 'false');
    head.addEventListener('click', () => {
      if (section.classList.contains('settings-accordion-open')) setOpen(section, false, true);
      else open(section, true);
    });
    head.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); head.click(); }
    });
  });
  window.SettingsAccordion = {open, select};
})();
