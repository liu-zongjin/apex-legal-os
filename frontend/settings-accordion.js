(() => {
  const sections = Array.from(document.querySelectorAll('.settings-modal .settings-section[data-settings-group]'));
  function setOpen(section, opened) {
    section.classList.toggle('settings-accordion-open', opened);
    section.querySelector(':scope > .settings-section-head')?.setAttribute('aria-expanded', String(opened));
  }
  function open(section) {
    if (!sections.includes(section)) return;
    sections.forEach(item => setOpen(item, item === section));
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
    if (!head) return;
    head.setAttribute('role', 'button'); head.tabIndex = 0;
    head.setAttribute('aria-expanded', 'false');
    head.addEventListener('click', () => {
      if (section.classList.contains('settings-accordion-open')) setOpen(section, false);
      else open(section);
    });
    head.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); head.click(); }
    });
  });
  window.SettingsAccordion = {open, select};
})();
