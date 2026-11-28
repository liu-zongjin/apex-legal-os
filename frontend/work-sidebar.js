/* Fluid Tooltip — Vanilla, supplied with the sidebar design.
 * Reuses the GSAP position, width, opacity, counter-translated label track,
 * and delayed hide. Stella supplies the live triggers and theme. */
(() => {
  function mountFluidTooltip(sidebar, rail, buttons) {
    const gsap = window.gsap;
    const tip = document.createElement("div");
    tip.className = "work-fluid-tooltip";
    tip.id = "work-sidebar-tooltip";
    tip.setAttribute("role", "tooltip");
    tip.setAttribute("aria-hidden", "true");

    const track = document.createElement("div");
    track.className = "work-fluid-track";
    const rows = buttons.map((button) => {
      const row = document.createElement("div");
      row.className = "work-fluid-row";
      const label = document.createElement("span");
      label.className = "ft-label";
      label.textContent = button.getAttribute("aria-label");
      row.append(label);
      track.append(row);
      return row;
    });
    tip.append(track);
    sidebar.append(tip);

    const height = 34;
    const tabBar = document.getElementById("tab-bar");
    const state = { x: 0, y: 0, width: 0, opacity: 0 };
    const tops = [], widths = [];
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const scope = { reduced: () => motion.matches || !gsap };
    let hint = -1, tween = null, hideTimer = 0;

    function fit(index) {
      const bounds = sidebar.getBoundingClientRect();
      const origin = bounds.top + sidebar.clientTop;
      const clip = rail.getBoundingClientRect();
      const centers = buttons.map((button) => {
        const rect = button.getBoundingClientRect();
        return rect.top + rect.height / 2;
      });
      const isInRail = (center) => center >= clip.top && center <= clip.bottom;
      if (!isInRail(centers[index])) return false;
      // The tooltip lives beside the rail, below the fixed tab bar.
      const topLimit = Math.max(0, tabBar.getBoundingClientRect().bottom + 4 - origin);
      const bottomLimit = bounds.bottom - origin - height;
      if (topLimit > bottomLimit) return false;

      rows.forEach((row, i) => { widths[i] = Math.ceil(row.offsetWidth); });
      rows.forEach((row, i) => {
        const top = centers[i] - origin - height / 2;
        tops[i] = isInRail(centers[i]) ? Math.max(topLimit, Math.min(top, bottomLimit)) : top;
        row.style.top = tops[i] + "px";
      });
      return true;
    }
    function horizontalOffset(index) {
      if (buttons[index].dataset.workAction !== "home") return 0;
      const header = document.querySelector(".tab-page.active .ask-panel-head-left");
      if (!header) return 0;
      const left = sidebar.getBoundingClientRect().left + sidebar.clientLeft + tip.offsetLeft;
      const bounds = header.getBoundingClientRect();
      // Keep the home hint clear of the inline AI title and history button.
      if (bounds.left >= left + widths[index] || bounds.right <= left) return 0;
      const offset = bounds.right + 8 - left;
      return left + offset + widths[index] <= window.innerWidth - 8 ? offset : 0;
    }
    function paint() {
      tip.style.transform = `translate(${state.x}px, ${state.y}px)`;
      tip.style.width = state.width + "px";
      tip.style.opacity = String(state.opacity);
      track.style.transform = `translateY(${-state.y}px)`;
    }
    function cancelHide() {
      if (hideTimer) {
        window.clearTimeout(hideTimer);
        hideTimer = 0;
      }
    }
    function show(index, immediate = false) {
      if (!rail.offsetWidth || index < 0 || index >= buttons.length) return;
      if (!fit(index)) {
        hide(true);
        return;
      }
      cancelHide();
      hint = index;
      tip.setAttribute("aria-hidden", "false");
      tip.setAttribute("aria-label", rows[index].querySelector(".ft-label").textContent);
      buttons.forEach((button, i) => {
        if (i === index) button.setAttribute("aria-describedby", tip.id);
        else button.removeAttribute("aria-describedby");
      });
      tween?.kill();
      const next = { x: horizontalOffset(index), y: tops[index], width: widths[index], opacity: 1 };
      if (immediate || scope.reduced()) {
        Object.assign(state, next);
        paint();
        return;
      }
      const first = state.opacity < 0.01;
      if (first) {
        state.x = next.x;
        state.y = next.y;
        state.width = next.width;
        paint();
      }
      tween = gsap.to(state, { ...next, duration: first ? 0.15 : 0.43, ease: first ? "power2.out" : "expo.out", overwrite: true, onUpdate: paint });
    }
    function hide(immediate = false) {
      cancelHide();
      hint = -1;
      tip.setAttribute("aria-hidden", "true");
      buttons.forEach((button) => button.removeAttribute("aria-describedby"));
      tween?.kill();
      if (immediate || scope.reduced()) {
        state.opacity = 0;
        paint();
      } else tween = gsap.to(state, { opacity: 0, duration: 0.15, ease: "power2.out", onUpdate: paint });
    }
    function leave() {
      cancelHide();
      hideTimer = window.setTimeout(() => {
        hideTimer = 0;
        const focused = buttons.indexOf(document.activeElement);
        if (focused >= 0 && buttons[focused].matches(":focus-visible")) show(focused);
        else hide();
      }, 75);
    }
    buttons.forEach((button, index) => {
      button.addEventListener("pointerenter", (event) => {
        if (event.pointerType !== "touch") show(index);
      });
      button.addEventListener("pointerleave", (event) => {
        if (event.pointerType !== "touch") leave();
      });
      button.addEventListener("focus", () => {
        if (button.matches(":focus-visible")) show(index);
      });
      button.addEventListener("blur", leave);
    });
    tip.addEventListener("pointerenter", cancelHide);
    tip.addEventListener("pointerleave", leave);
    rail.addEventListener("scroll", () => {
      if (hint < 0) return;
      const focused = buttons[hint];
      if (focused === document.activeElement && focused.matches(":focus-visible")) show(hint, true);
      else hide(true);
    }, { passive: true });
    const reposition = () => {
      if (hint >= 0) show(hint, true);
    };
    window.addEventListener("resize", reposition, { passive: true });
    motion.addEventListener("change", reposition);
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) hide(true);
    });
    return { hide, visible: () => hint >= 0 };
  }

  const sidebar = document.getElementById("sidebar");
  const nav = document.getElementById("sidebar-nav");
  const mobileToggle = document.getElementById("work-sidebar-mobile-toggle");
  const homeToggle = document.querySelector("#tab-page-main .sidebar-toggle");
  const mobile = window.matchMedia("(max-width: 768px)");
  const rail = document.createElement("nav");
  rail.className = "work-sidebar-rail";
  rail.setAttribute("aria-label", "工作区导航");

  const isWorkTab = () => !document.body.classList.contains("main-tab-active");
  const preferenceKey = "legal_kb_work_sidebar_enabled";
  const preferenceSwitch = document.getElementById("work-sidebar-switch");
  const isCompact = () => !mobile.matches && document.body.classList.contains("work-sidebar-enabled") &&
    (isWorkTab() || sidebar.classList.contains("collapsed"));

  function readPreference() {
    try { return localStorage.getItem(preferenceKey) !== "false"; }
    catch (_) { return true; }
  }

  function applyPreference(enabled) {
    document.body.classList.toggle("work-sidebar-enabled", enabled);
    preferenceSwitch.setAttribute("aria-checked", String(enabled));
    if (!enabled) {
      closeDirectory();
      tooltip.hide(true);
    }
  }

  const entries = [
    { id: "home", label: "返回首页",
      icon: "M4 10.4 10.8 4.6a1.8 1.8 0 0 1 2.4 0l6.8 5.8v7.8a1.8 1.8 0 0 1-1.8 1.8H5.8A1.8 1.8 0 0 1 4 18.2z M9.4 20v-5.5a1 1 0 0 1 1-1h3.2a1 1 0 0 1 1 1V20" },
    { id: "all", label: "全部知识", source: '[data-view="all"]', home: true,
      icon: "M5.5 3.5h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2h-3a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2z M15.5 3.5h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2h-3a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2z M5.5 13.5h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2h-3a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2z M15.5 13.5h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2h-3a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2z" },
    { id: "notes", label: "我的笔记", source: '[data-view="notes"]', home: true,
      icon: "M7 3h7l5 5v11a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z M14 3v4a1 1 0 0 0 1 1h4 M8.5 12h7m-7 4h4.5" },
    { id: "knowledge", label: "知识中心", source: ".nav-item-legal-knowledge",
      icon: "M12 6.8C9.7 5.1 6.6 4.8 3.5 5.5v13.2c3.1-.7 6.2-.4 8.5 1.3 2.3-1.7 5.4-2 8.5-1.3V5.5c-3.1-.7-6.2-.4-8.5 1.3V20" },
    { id: "trash", label: "回收站", source: ".nav-item[onclick*='openArticleTrash']",
      icon: "M4.5 7h15 M9 7V5.3A1.3 1.3 0 0 1 10.3 4h3.4A1.3 1.3 0 0 1 15 5.3V7 M6.3 7l.9 11.2A2 2 0 0 0 9.2 20h5.6a2 2 0 0 0 2-1.8L17.7 7 M10.2 10.8l.3 5.5m3.3-5.5-.3 5.5" },
    { id: "domain", label: "专业领域", directory: true,
      icon: "M5 7h14a2 2 0 0 1 2 2v8.5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2z M8.5 7V5.5A1.5 1.5 0 0 1 10 4h4a1.5 1.5 0 0 1 1.5 1.5V7 M3 11.5c2.5 1.2 5.1 1.8 7 1.8m4 0c1.9 0 4.5-.6 7-1.8 M10 13.3h4" },
    { id: "customLib", label: "自定义库", directory: true,
      icon: "M3 6.5a2 2 0 0 1 2-2h4.3L12 7h7a2 2 0 0 1 2 2v8.5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z M12 10.5v5.5m-2.75-2.75h5.5" },
    { id: "author", label: "作者", directory: true,
      icon: "M16 7.5a4 4 0 1 1-8 0 4 4 0 0 1 8 0z M4.5 20.5v-1a7.5 6 0 0 1 15 0v1" },
    { id: "add", label: "添加知识", source: ".btn-add",
      icon: "M12 4.5v15m-7.5-7.5h15" },
    { id: "stats", label: "可视化统计", source: ".btn-stats[onclick='openKbStatsTab()']",
      icon: "M4 20v-6a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v6z M10 20V9.5a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1V20z M16 20V5a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v15z" },
    { id: "settings", label: "设置", source: "#sidebar-settings-btn",
      icon: "M9.7 3.2h4.6l.45 2.45 1.48.85 2.34-.83 2.3 4-1.9 1.6v1.46l1.9 1.6-2.3 4-2.34-.83-1.48.85-.45 2.45H9.7l-.45-2.45-1.48-.85-2.34.83-2.3-4 1.9-1.6v-1.46l-1.9-1.6 2.3-4 2.34.83 1.48-.85z M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0z" }
  ];

  function focusHome(source) {
    const target = source?.getClientRects().length ? source : document.getElementById("search-input");
    target.focus({ preventScroll: true });
  }

  let directoryTrigger = null;
  function closeDirectory(restoreFocus = false) {
    if (!directoryTrigger) return;
    const button = directoryTrigger;
    directoryTrigger = null;
    sidebar.removeAttribute("data-work-directory");
    button.setAttribute("aria-expanded", "false");
    if (restoreFocus && isCompact()) button.focus({ preventScroll: true });
  }

  function toggleDirectory(entry, button) {
    if (directoryTrigger === button) {
      closeDirectory();
      return;
    }
    closeDirectory();
    directoryTrigger = button;
    sidebar.dataset.workDirectory = entry.id;
    button.setAttribute("aria-expanded", "true");
    const heading = document.querySelector("#nav-sec-" + entry.id + " .directory-section-heading");
    if (!directoryState.query) toggleDirectoryPath(entry.id, true);
    heading.focus({ preventScroll: true });
    heading.scrollIntoView({ block: "nearest" });
  }

  const actions = document.createElement("div");
  actions.className = "work-sidebar-actions";
  const buttons = entries.map((entry) => {
    const source = entry.source && sidebar.querySelector(entry.source);
    const button = document.createElement("button");
    button.className = "work-sidebar-button";
    button.type = "button";
    button.dataset.workAction = entry.id;
    button.setAttribute("aria-label", entry.label);
    if (entry.directory) {
      button.setAttribute("aria-controls", nav.id);
      button.setAttribute("aria-expanded", "false");
    }
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("width", "20");
    svg.setAttribute("height", "20");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "1.65");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    const path = document.createElementNS(svg.namespaceURI, "path");
    path.setAttribute("d", entry.icon);
    svg.append(path);
    button.append(svg);
    button.addEventListener("click", () => {
      const keyboard = button.matches(":focus-visible");
      tooltip.hide(true);
      if (entry.directory) {
        toggleDirectory(entry, button);
        return;
      }
      closeDirectory();
      const returnsHome = entry.home || entry.id === "home";
      if (returnsHome) goToMainView();
      source?.click();
      if (keyboard && returnsHome) focusHome(source || nav.querySelector('[data-view="all"]'));
    });
    (["add", "stats", "settings"].includes(entry.id) ? actions : rail).append(button);
    return button;
  });
  rail.append(actions);
  sidebar.append(rail);
  const tooltip = mountFluidTooltip(sidebar, rail, buttons);

  preferenceSwitch.addEventListener("click", () => {
    const enabled = preferenceSwitch.getAttribute("aria-checked") !== "true";
    try { localStorage.setItem(preferenceKey, String(enabled)); } catch (_) {}
    applyPreference(enabled);
  });
  window.addEventListener("storage", (event) => {
    if (event.key === preferenceKey || event.key === null) applyPreference(readPreference());
  });
  applyPreference(readPreference());

  function drawerOpener() {
    return isWorkTab() ? mobileToggle : homeToggle;
  }

  function updateDrawer() {
    const wasOpen = mobileToggle.getAttribute("aria-expanded") === "true";
    const isOpen = mobile.matches && sidebar.classList.contains("mobile-open");
    const active = document.activeElement;
    if (!mobile.matches && !isCompact()) {
      closeDirectory();
      tooltip.hide(true);
    }
    const opener = drawerOpener();
    mobileToggle.setAttribute("aria-expanded", String(isOpen));
    homeToggle.setAttribute("aria-expanded", String(mobile.matches ? isOpen : !sidebar.classList.contains("collapsed")));

    if (wasOpen && !isOpen && mobile.matches && sidebar.contains(active)) {
      opener.focus({ preventScroll: true });
    }
    sidebar.inert = mobile.matches && !isOpen;

    if (!wasOpen && isOpen && active === opener && opener.matches(":focus-visible")) {
      sidebar.querySelector(".sidebar-mobile-close").focus({ preventScroll: true });
    }
  }

  mobileToggle.addEventListener("click", toggleSidebar);
  new MutationObserver(updateDrawer).observe(sidebar, { attributes: true, attributeFilter: ["class"] });
  updateDrawer();

  nav.addEventListener("click", (event) => {
    if (event.target.closest(".directory-tools button")) {
      // The manager outlives its menu or drawer. Restore focus to their opener.
      if (directoryTrigger) {
        directoryState.returnFocus = directoryTrigger;
        closeDirectory();
      } else if (mobile.matches) {
        directoryState.returnFocus = drawerOpener();
      }
      return;
    }

    const view = event.target.closest(".nav-item[data-view]");
    const filter = event.target.closest(".directory-label");
    if (!view && !filter) return;
    if (isWorkTab()) {
      goToMainView();
      if (event.detail === 0) focusHome(mobile.matches ? null : view);
    } else if (directoryTrigger) {
      closeDirectory(event.detail === 0);
    }
  });

  document.addEventListener("pointerdown", (event) => {
    if (!rail.contains(event.target) && !nav.contains(event.target)) closeDirectory();
    if (!rail.contains(event.target)) tooltip.hide(true);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (directoryTrigger && sidebar.contains(event.target)) {
      closeDirectory(true);
      tooltip.hide(true);
    } else if (tooltip.visible()) {
      tooltip.hide(true);
    } else if (mobile.matches && sidebar.classList.contains("mobile-open") && sidebar.contains(event.target)) {
      closeMobileSidebar();
      drawerOpener().focus({ preventScroll: true });
    } else {
      return;
    }
    event.preventDefault();
    event.stopImmediatePropagation();
  }, true);
  window.addEventListener("blur", () => {
    closeDirectory();
    tooltip.hide(true);
  });
  sidebar.addEventListener("focusout", (event) => {
    if (!directoryTrigger || !event.relatedTarget || sidebar.contains(event.relatedTarget)) return;
    if (event.relatedTarget.closest("#domain-classification-modal")) {
      directoryState.returnFocus = directoryTrigger;
    }
    closeDirectory();
  });
  mobile.addEventListener("change", () => {
    closeDirectory();
    closeMobileSidebar();
    updateDrawer();
    tooltip.hide(true);
  });

  const tabBar = document.getElementById("tab-bar");
  const tabStrip = document.getElementById("tab-bar-tabs");
  function revealActiveTab() {
    if (mobile.matches) return;
    const active = tabStrip.querySelector(":scope > .tab-item.active");
    const strip = tabStrip.getBoundingClientRect();
    const tab = active?.getBoundingClientRect();
    if (!tab?.width) return;
    if (tab.left < strip.left) tabStrip.scrollLeft += tab.left - strip.left;
    else if (tab.right > strip.right) tabStrip.scrollLeft += tab.right - strip.right;
  }
  window.addEventListener("resize", revealActiveTab, { passive: true });
  tabBar.addEventListener("transitionend", (event) => {
    if (event.target === tabBar && event.propertyName === "left") revealActiveTab();
  });

  window.StellaWorkSidebar = {
    sync(tabType) {
      requestAnimationFrame(revealActiveTab);
      closeDirectory();
      tooltip.hide(true);
      let activeId = { legal_knowledge: "knowledge", kb_stats: "stats" }[tabType];
      if (tabType === "article") {
        if (state.domain || state.view === "pending-domains") activeId = "domain";
        else if (state.author) activeId = "author";
        else if (state.customTag || state.customCategory) activeId = "customLib";
        else activeId = state.view;
      }
      buttons.forEach((button) => {
        if (button.dataset.workAction === activeId) button.setAttribute("aria-current", "true");
        else button.removeAttribute("aria-current");
      });
    }
  };
})();
