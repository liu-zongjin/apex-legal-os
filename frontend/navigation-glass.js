/* Sliding selection for the main workspace, court, knowledge and settings navigation. */
(() => {
  const specs = [
    ['#tab-bar-tabs', ':scope > .tab-item.active'],
    ['.settings-sidebar', ':scope > .settings-nav-item.active'],
    ['#section-view', ':scope > .nav-item.active'],
    ['.court-kind-tabs', ':scope > .tab.active, :scope > .court-kind-tab-wrap > .tab.active'],
    ['.mode-nav', ':scope > button.active']
  ];
  const groups = new Map();
  const previous = new Map();
  let frame = 0;
  function position(group, selector) {
    const selected = group.querySelector(selector);
    if (!selected || !group.isConnected || !selected.getClientRects().length) {
      if (group.classList.contains('nav-glass-ready')) group.classList.remove('nav-glass-ready');
      return;
    }
    const g = group.getBoundingClientRect(), s = selected.getBoundingClientRect();
    const sx = group.offsetWidth / g.width || 1, sy = group.offsetHeight / g.height || 1;
    group.style.setProperty('--nav-glass-x', `${(s.left-g.left)*sx + group.scrollLeft - group.clientLeft}px`);
    group.style.setProperty('--nav-glass-y', `${(s.top-g.top)*sy + group.scrollTop - group.clientTop}px`);
    group.style.setProperty('--nav-glass-w', `${s.width*sx}px`);
    group.style.setProperty('--nav-glass-h', `${s.height*sy}px`);
    if (!group.classList.contains('nav-glass-ready')) group.classList.add('nav-glass-ready');
  }
  const schedule = () => { if (!frame) frame = requestAnimationFrame(() => { frame = 0; groups.forEach((selector, group) => position(group, selector)); }); };
  const resize = window.ResizeObserver ? new ResizeObserver(schedule) : null;
  function scan() {
    for (const [group, selector] of groups) if (!group.isConnected) {
      if (group.classList.contains('nav-glass-ready')) previous.set(selector, {time:Date.now(), values:['x','y','w','h'].map(key => group.style.getPropertyValue(`--nav-glass-${key}`))});
      resize?.unobserve(group); groups.delete(group);
    }
    for (const [container, selected] of specs) document.querySelectorAll(container).forEach(group => {
      if (groups.has(group)) return;
      groups.set(group, selected);
      const old = previous.get(selected);
      if (old && Date.now() - old.time < 1500) {
        ['x','y','w','h'].forEach((key, i) => group.style.setProperty(`--nav-glass-${key}`, old.values[i]));
        group.classList.add('nav-glass-ready');
        void group.offsetWidth;
        previous.delete(selected);
      }
      resize?.observe(group);
    });
    schedule();
  }
  new MutationObserver(records => {
    const containers = specs.map(spec => spec[0]).join(',');
    if (records.some(r => r.type === 'childList' && [...r.addedNodes, ...r.removedNodes].some(node => node.nodeType === 1 && (node.matches(containers) || node.querySelector(containers))))) scan();
    else if (records.some(r => r.type === 'childList' && [...groups.keys()].some(group => group.contains(r.target)))) schedule();
    else if (records.some(r => r.type === 'attributes' && [...groups.keys()].some(group => group.contains(r.target)))) schedule();
  }).observe(document.documentElement, {subtree:true, childList:true, attributes:true, attributeFilter:['class']});
  window.addEventListener('resize', schedule);
  scan();
})();
