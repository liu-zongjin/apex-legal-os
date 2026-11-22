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
    const state = { y: 0, width: 0, opacity: 0 };
    const centers = [], widths = [];
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const scope = { reduced: () => motion.matches || !gsap };
    let hint = -1, tween = null, hideTimer = 0;

    function fit() {
      const origin = sidebar.getBoundingClientRect().top + sidebar.clientTop;
      buttons.forEach((button, index) => {
        const rect = button.getBoundingClientRect();
        centers[index] = rect.top + rect.height / 2 - origin;
        rows[index].style.top = centers[index] - height / 2 + "px";
        widths[index] = Math.ceil(rows[index].offsetWidth);
      });
    }
    function paint() {
      tip.style.transform = `translateY(${state.y}px)`;
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
      fit();
      cancelHide();
      hint = index;
      tip.setAttribute("aria-hidden", "false");
      tip.setAttribute("aria-label", rows[index].querySelector(".ft-label").textContent);
      buttons.forEach((button, i) => {
        if (i === index) button.setAttribute("aria-describedby", tip.id);
        else button.removeAttribute("aria-describedby");
      });
      tween?.kill();
      const next = { y: centers[index] - height / 2, width: widths[index], opacity: 1 };
      if (immediate || scope.reduced()) {
        Object.assign(state, next);
        paint();
        return;
      }
      const first = state.opacity < 0.01;
      if (first) {
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
    motion.addEventListener("change", () => {
      if (hint >= 0) show(hint, true);
    });
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) hide(true);
    });
    return { hide, visible: () => hint >= 0 };
  }

  const sidebar = document.getElementById("sidebar");
  const nav = document.getElementById("sidebar-nav");
  const mobileToggle = document.getElementById("work-sidebar-mobile-toggle");
  const desktop = window.matchMedia("(min-width: 769px)");
  const rail = document.createElement("nav");
  rail.className = "work-sidebar-rail";
  rail.setAttribute("aria-label", "工作区导航");

  const isWorkTab = () => !document.body.classList.contains("main-tab-active");
  const entries = [
    { id: "home", label: "返回首页", icon: "#tab-bar-home-btn svg" },
    { id: "all", label: "全部知识", source: '[data-view="all"]', home: true },
    { id: "notes", label: "我的笔记", source: '[data-view="notes"]', home: true },
    { id: "knowledge", label: "知识中心", source: ".nav-item-legal-knowledge" },
    { id: "trash", label: "回收站", source: ".nav-item[onclick*='openArticleTrash']" },
    { id: "domain", label: "专业领域", directory: true, icon: "M2 4h12v9H2zM5.5 4V2.5h5V4M2 7.5h12M7 7.5h2" },
    { id: "customLib", label: "自定义库", directory: true, icon: "M2.5 4h4l1.4 1.6h5.6v7.5h-11zM8 7.6v3.4m-1.7-1.7h3.4" },
    { id: "author", label: "作者", directory: true, icon: "M10.5 5a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0ZM3 13.5a5 5 0 0 1 10 0" },
    { id: "add", label: "添加知识", source: ".btn-add" },
    { id: "stats", label: "可视化统计", source: ".btn-stats[onclick='openKbStatsTab()']" },
    { id: "settings", label: "设置", source: "#sidebar-settings-btn" }
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
    if (restoreFocus && desktop.matches && isWorkTab()) button.focus({ preventScroll: true });
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
    const icon = entry.id === "home" ? document.querySelector(entry.icon) : source?.querySelector("svg");
    const button = document.createElement("button");
    button.className = "work-sidebar-button";
    button.type = "button";
    button.dataset.workAction = entry.id;
    button.setAttribute("aria-label", entry.label);
    if (entry.directory) {
      button.setAttribute("aria-controls", nav.id);
      button.setAttribute("aria-expanded", "false");
    }
    if (icon) {
      button.append(icon.cloneNode(true));
    } else {
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("viewBox", "0 0 16 16");
      const path = document.createElementNS(svg.namespaceURI, "path");
      path.setAttribute("d", entry.icon);
      path.setAttribute("fill", "none");
      path.setAttribute("stroke", "currentColor");
      path.setAttribute("stroke-width", "1.4");
      path.setAttribute("stroke-linecap", "round");
      path.setAttribute("stroke-linejoin", "round");
      svg.append(path);
      button.append(svg);
    }
    button.firstElementChild.setAttribute("aria-hidden", "true");
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

  mobileToggle.addEventListener("click", () => {
    toggleSidebar();
    if (mobileToggle.matches(":focus-visible")) sidebar.querySelector(".sidebar-mobile-close").focus();
  });
  new MutationObserver(() => {
    const wasOpen = mobileToggle.getAttribute("aria-expanded") === "true";
    const isOpen = sidebar.classList.contains("mobile-open");
    mobileToggle.setAttribute("aria-expanded", String(isOpen));
    if (wasOpen && !isOpen && !desktop.matches && isWorkTab() && sidebar.contains(document.activeElement)) {
      mobileToggle.focus({ preventScroll: true });
    }
  }).observe(sidebar, { attributes: true, attributeFilter: ["class"] });

  nav.addEventListener("click", (event) => {
    if (!isWorkTab()) return;
    const view = event.target.closest(".nav-item[data-view]");
    const filter = event.target.closest(".directory-label");
    if (view || filter) {
      const keyboard = event.detail === 0;
      goToMainView();
      if (keyboard) focusHome(view);
    } else if (directoryTrigger && event.target.closest(".directory-tools button")) {
      closeDirectory();
    }
  });

  document.addEventListener("pointerdown", (event) => {
    if (!rail.contains(event.target) && !nav.contains(event.target)) closeDirectory();
    if (!rail.contains(event.target)) tooltip.hide(true);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !isWorkTab()) return;
    if (directoryTrigger && sidebar.contains(event.target)) {
      closeDirectory(true);
      tooltip.hide(true);
    } else if (tooltip.visible()) {
      tooltip.hide(true);
    } else if (!desktop.matches && sidebar.classList.contains("mobile-open")) {
      closeMobileSidebar();
      mobileToggle.focus();
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
    if (event.relatedTarget && !sidebar.contains(event.relatedTarget)) closeDirectory();
  });
  desktop.addEventListener("change", () => {
    closeDirectory();
    closeMobileSidebar();
    tooltip.hide(true);
  });

  window.StellaWorkSidebar = {
    sync(tabType) {
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
