/* Local walkthrough. Screenshots use anonymous example data. */
(() => {
  const key = 'stella.welcome.dismissed.v1';
  // Target rectangles as percentages of the annotated screenshots.
  const shotTargets = {
    'start-efficiency': [33, 2.4, 34, 41.3],
    'start-cases': [8.1, 61.2, 87.2, 33],
    'start-knowledge': [3.6, 27.4, 15, 9.4],
    'shortcut-keys': [9, 6.8, 6, 19.8],
    'shortcut-edit': [11.1, 51.7, 29.1, 29.3],
    'settings-guide': [85.2, 26.7, 7, 46.7],
    'deepseek-create': [2.8, 33.4, 96.5, 15.3],
    'deepseek-key': [1.9, 51.8, 96.3, 28],
    'deepseek-save': [75.7, 28.4, 18.3, 49.4],
    'deepseek-test': [84, 45.3, 6.3, 23.4],
    'deepseek-default': [38.3, 63.4, 47.8, 20.9],
    'mail-authorize': [7.2, 27, 88.5, 15.3],
    'mail-account': [1.2, 12.9, 97.6, 15.8],
    'mail-save': [84.1, 28.8, 12, 48.8],
    'mail-test': [12.4, 73.8, 10.1, 14],
    'court-account': [3.2, 41, 45.7, 6.6],
    'court-login': [38.5, 26.2, 38, 54],
    'sms-settings': [0.3, 27.5, 48.8, 47.6],
    'sms-permissions': [0.9, 17.7, 98.1, 77.1],
    'contact-sync': [91.3, 60.6, 4.7, 20.7],
  };
  const steps = [
    { label: '开始使用', title: '从案件和知识开始', copy: '案件管理和知识库可直接使用。需要 AI 辅助整理材料或检索知识时，再接入模型。',
      panels: [
        ['start-efficiency', '找到效率中心入口', '在 Stella 主窗口的右上角，点击「效率中心」展开菜单。'],
        ['start-cases', '打开案件管理', '在效率中心点击标注的「案件管理」，即可查看案件和提醒。'],
        ['start-knowledge', '收录第一篇知识', '打开「添加知识」，按资料类型选择网页链接、上传文档或国家法规库。'],
      ], actions: [['打开案件管理', () => { closeSettingsModal(); openCaseManagerTab(); }], ['打开添加知识', () => { closeSettingsModal(); openSubmitModal(); }, {host: '#submit-modal.open'}]] },
    { label: '配置 AI API', title: '配置 AI API', copy: '推荐先接入 DeepSeek，费用低、配置简单，拿到密钥后通常几分钟即可完成。作为费用参考，开发者日常每天使用，月支出不到 10 元。实际费用随模型和用量变化。',
      panels: [
        ['deepseek-create', '创建并复制密钥', '从 Stella 的「查看配置指引」进入 DeepSeek 开放平台，在 API keys 页面创建并复制密钥。'],
        ['deepseek-key', '填入密钥', '保留预填的接口地址，在「API 密钥」粘贴刚复制的密钥。'],
        ['deepseek-save', '保存配置', '点击 DeepSeek 表单底部的「保存配置」。'],
        ['deepseek-test', '检测连接', '在 DeepSeek 服务卡片点击「检测」，确认连接成功。'],
        ['deepseek-default', '设为全局默认模型', '选择默认 API 服务及模型，点击「保存默认设置」。'],
      ], actions: [['打开 DeepSeek 配置', () => {
        openAiApiManagerFromSettings();
        return atWorkspaceFrame('/ai-api-manager', frame => frame.openDeepSeekSetup());
      }, {frame: '#drawerBackdrop.open'}], ['查看其他 AI 服务', () => openAiApiManagerFromSettings()]], links: [['DeepSeek 开放平台', 'https://platform.deepseek.com/'], ['官方计费', 'https://api-docs.deepseek.com/zh-cn/quick_start/pricing']] },
    { label: '快捷键', title: '给常用操作设置快捷键', copy: '可为效率中心、案件管理、添加知识、页面总览、打开设置和返回首页分配键位。',
      panels: [
        ['shortcut-keys', '点选一个键帽', '在「设置 → 工作效率 → 快捷键」的键盘上，点你要设置的键位。'],
        ['shortcut-edit', '选择功能和组合键', '在「执行动作」里选功能，勾选组合键，再点击「保存」。'],
      ], actions: [['打开快捷键设置', () => {
        openSettingsModal('shortcuts');
        requestAnimationFrame(() => document.getElementById('settings-shortcuts-title')?.scrollIntoView({block:'start'}));
      }, {host: '#settings-modal-overlay.open'}]] },
    { label: '一张网', title: '填写法院一张网账号', copy: '保存后，在一张网页面按提示登录官网。',
      panels: [
        ['court-account', '填写法院账号和密码', '在「登录、同步与下载设置」中填写账号和密码，点击「保存设置」。'],
        ['court-login', '回到一张网登录', '点击「打开法院诉讼服务网」或「登录官网」，按法院官网提示完成核验。'],
      ], actions: [['打开一张网登录设置', () => {
        closeSettingsModal();
        openCourtOnlineService();
        return atWorkspaceFrame('/case-manager', frame => frame.openCourtLoginSetup());
      }, {frame: '#courtSettingsModal'}]] },
    { label: '电子邮箱', title: '连接你的电子邮箱', copy: '选择你使用的邮箱，直接进入该账号的配置表单。',
      panels: [
        ['mail-authorize', '获取客户端授权', '通过表单顶部的指引进入邮箱网页版，按该服务商的说明取得授权码或客户端专用密码。截图以 QQ 邮箱为例。'],
        ['mail-account', '填写邮箱账号和授权码', '填入完整邮箱地址和客户端授权码或专用密码。'],
        ['mail-save', '保存邮箱配置', '点击表单底部的「保存配置」。'],
        ['mail-test', '检测连接', '在邮箱卡片点击「检测连接」，通过后即可从效率中心打开该邮箱。'],
      ], actions: [['腾讯企业邮箱', () => openMailConfigFromSettings('qq_exmail'), {frame: '#drawerBackdrop.open'}], ['网易企业邮箱', () => openMailConfigFromSettings('netease_exmail'), {frame: '#drawerBackdrop.open'}], ['QQ 邮箱', () => openMailConfigFromSettings('qq_mail'), {frame: '#drawerBackdrop.open'}]] },
    { label: '短信与通讯录', title: '同步司法短信和案件联系人', copy: 'macOS 可读取已同步到「信息」的司法短信，并将案件联系人按需同步到 iCloud 通讯录。Windows 可在司法短信中导入文本或截图。',
      panels: [
        ['sms-settings', '设置司法短信读取', '在「司法短信设置」里设置定时读取和扫描间隔，再保存。'],
        ['sms-permissions', '检查短信同步权限', '打开「同步与权限诊断」，在 Mac 上按页面指引检查信息同步及读取权限。'],
        ['contact-sync', '同步一位案件联系人', '选择案件进入「联系与备忘」，点联系人行尾的「同步通讯录」。首次使用按 macOS 提示授权。'],
        ['settings-guide', '以后在哪里打开新手引导', '打开 Stella 的「设置」，点击窗口右上方的「新手引导」。即使勾选了「下次不再提示」，也可以从这里重新打开。'],
      ], actions: [
        ['打开司法短信设置', () => openCaseGuide(frame => { frame.switchTab('judicialMessages'); return frame.openJudicialSettings(); }), {frame: '#drawer.show'}],
        ['打开权限诊断', () => openCaseGuide(frame => frame.openJudicialSyncGuide()), {frame: '#drawer.show'}],
        ['选择案件，同步联系人', () => openCaseGuide(frame => frame.openContactSyncGuide()), {frame: '#drawer.show'}],
      ] },
  ];
  let index = 0;
  let previousFocus;
  let slideIndex = 0;
  let resumeVisit;
  let slideObserver;

  function showOverlay(overlay) {
    const savedSlide = slideIndex;
    overlay.hidden = false;
    overlay.showPopover?.();
    const carousel = overlay.querySelector('.welcome-carousel');
    carousel.scrollLeft = savedSlide * carousel.clientWidth;
    fitSlide(overlay);
    overlay.querySelector('h2').focus({preventScroll:true});
  }

  function startVisit(overlay, run, {host, frame: frameSelector} = {}) {
    const origin = tabState.activeTabId;
    overlay.hidePopover?.();
    overlay.hidden = true;
    try { run(); }
    catch (error) {
      showOverlay(overlay);
      throw error;
    }
    const destination = tabState.activeTabId;
    const screen = document.getElementById(destination);
    const frame = frameSelector && screen?.querySelector('iframe');
    let dialogWasOpen = Boolean(host && document.querySelector(host));
    const observers = [];
    let frameObserver;
    const resume = () => {
      observers.forEach(observer => observer.disconnect());
      frameObserver?.disconnect();
      frame?.removeEventListener('load', observeFrame);
      resumeVisit = null;
      showOverlay(overlay);
    };
    function check() {
      const current = tabState.activeTabId;
      const hasTab = !host && destination !== 'main';
      if (hasTab && (!tabState.tabs.some(tab => tab.id === destination) || current === 'main')) {
        resume();
        return;
      }
      const doc = host ? document : frame?.contentDocument;
      const selector = host || frameSelector;
      const open = Boolean(selector && doc?.querySelector(selector));
      if (open) dialogWasOpen = true;
      else if (dialogWasOpen && (host || current === destination)) resume();
    }
    function observe(element, config) {
      if (!element) return;
      const observer = new MutationObserver(check);
      observer.observe(element, config);
      observers.push(observer);
    }
    function observeFrame() {
      if (!resumeVisit) return;
      frameObserver?.disconnect();
      const body = frame.contentDocument?.body;
      if (body) {
        frameObserver = new MutationObserver(check);
        frameObserver.observe(body, {subtree: true, childList: true, attributes: true, attributeFilter: ['class']});
      }
      check();
    }
    resumeVisit = resume;
    observe(document.body, {attributes:true, attributeFilter:['class']});
    observe(document.getElementById('tab-content-area'), {childList:true});
    if (host) observe(document.getElementById(host.split('.')[0].slice(1)), {attributes:true,attributeFilter:['class']});
    if (frame) {
      frame.addEventListener('load', observeFrame);
      observeFrame();
    }
    if (!host && destination === origin && !screen) resume();
  }

  // A workspace can already exist or can be loading in an iframe.
  function atWorkspaceFrame(path, openTarget) {
    const page = document.getElementById(tabState.activeTabId);
    const frame = page?.querySelector('iframe');
    if (!frame) { showToast('设置页面未能打开，请重试。', 'warning'); return; }
    const open = async () => {
      if (!frame.isConnected || tabState.activeTabId !== page.id) return;
      try {
        if (frame.contentWindow.location.pathname !== path ||
            await openTarget(frame.contentWindow) === false) throw new Error();
      } catch (_) { showToast('暂时无法打开配置，请在当前页面重试。', 'warning'); }
    };
    if (frame.contentDocument?.readyState === 'complete' &&
        frame.contentDocument.location.pathname === path) return open();
    frame.addEventListener('load', open, {once: true});
  }

  function openCaseGuide(openTarget) {
    closeSettingsModal();
    openCaseManagerTab();
    return atWorkspaceFrame('/case-manager', openTarget);
  }

  function close() {
    const overlay = document.getElementById('stella-welcome');
    if (!overlay) return;
    if (overlay.querySelector('#welcome-dismiss').checked) {
      try { localStorage.setItem(key, '1'); } catch (_) {}
    }
    slideObserver?.disconnect();
    overlay.remove();
    previousFocus?.focus();
  }

  function render(overlay) {
    const step = steps[index];
    overlay.querySelectorAll('.welcome-topic').forEach((button, i) => {
      if (i === index) button.setAttribute('aria-current', 'step');
      else button.removeAttribute('aria-current');
    });
    const heading = overlay.querySelector('h2');
    heading.textContent = step.title;
    overlay.querySelector('.welcome-copy').textContent = step.copy;
    const carousel = overlay.querySelector('.welcome-carousel');
    carousel.innerHTML = step.panels.map(([shot, title, caption], i) => {
      const [x, y, width, height] = shotTargets[shot];
      return `<figure class="welcome-slide" role="group" aria-label="第 ${i + 1} 步，共 ${step.panels.length} 步">
        <button class="welcome-shot" type="button" aria-label="放大查看截图：${title}">
          <span class="welcome-shot-frame"><img src="/static/welcome-shots/${shot}.jpg?v=3" alt="${title}的 Stella 操作截图，红框和文字标出要操作的位置" draggable="false" ${i > 0 ? 'loading="lazy"' : ''}>
          <span class="welcome-shot-focus" aria-hidden="true" style="--focus-x:${x}%;--focus-y:${y}%;--focus-w:${width}%;--focus-h:${height}%"></span></span>
        </button>
        <figcaption><strong>${title}</strong><span>${caption}</span></figcaption>
      </figure>`;
    }).join('');
    carousel.scrollLeft = 0;
    carousel.querySelectorAll('.welcome-shot').forEach(button => button.onclick = () => {
      const viewer = overlay.querySelector('.welcome-zoom');
      const source = button.querySelector('img');
      const image = viewer.querySelector('img');
      image.src = source.src;
      image.alt = source.alt;
      viewer.hidden = false;
      viewer.querySelector('.welcome-zoom-body').scrollTo(0, 0);
      viewer.querySelector('button').focus();
    });
    slideIndex = 0;
    const dots = overlay.querySelector('.welcome-slide-dots');
    dots.innerHTML = step.panels.map(([, title], i) =>
      `<button type="button" aria-label="第 ${i + 1} 步：${title}">${i + 1}</button>`).join('');
    [...dots.children].forEach((dot, i) => dot.onclick = () => moveSlide(overlay, i));
    renderSlideControls(overlay);
    const actions = overlay.querySelector('.welcome-actions');
    actions.replaceChildren();
    for (const [label, run, target] of step.actions) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'welcome-action';
      button.textContent = label;
      button.onclick = () => startVisit(overlay, run, target);
      actions.append(button);
    }
    for (const [label, href] of step.links || []) {
      const link = document.createElement('a');
      link.href = href;
      link.target = '_blank';
      link.rel = 'noopener';
      link.textContent = label + ' ↗';
      actions.append(link);
    }
    overlay.querySelector('.welcome-back').disabled = index === 0;
    overlay.querySelector('.welcome-next').textContent = index === steps.length - 1 ? '完成' : '下一步';
    overlay.querySelector('.welcome-content').scrollTop = 0;
  }

  function fitSlide(overlay) {
    const carousel = overlay.querySelector('.welcome-carousel');
    const slide = carousel.children[slideIndex];
    if (slide?.offsetHeight) carousel.style.height = (slide.offsetHeight + 2) + 'px';
  }

  function renderSlideControls(overlay) {
    const slide = overlay.querySelector('.welcome-carousel').children[slideIndex];
    slideObserver?.disconnect();
    if (slide && window.ResizeObserver) {
      slideObserver = new ResizeObserver(() => fitSlide(overlay));
      slideObserver.observe(slide);
    }
    fitSlide(overlay);
    const total = steps[index].panels.length;
    const isLast = index === steps.length - 1 && slideIndex === total - 1;
    overlay.querySelector('.welcome-actions').hidden = isLast;
    overlay.querySelector('.welcome-slide-count').textContent = `步骤 ${slideIndex + 1} / ${total}`;
    overlay.querySelector('.welcome-slide-prev').disabled = slideIndex === 0;
    overlay.querySelector('.welcome-slide-next').disabled = slideIndex === total - 1;
    overlay.querySelectorAll('.welcome-slide-dots button').forEach((button, i) => {
      if (i === slideIndex) button.setAttribute('aria-current', 'step');
      else button.removeAttribute('aria-current');
    });
    overlay.querySelectorAll('.welcome-shot').forEach((button, i) => {
      button.tabIndex = i === slideIndex ? 0 : -1;
      button.closest('figure').setAttribute('aria-hidden', String(i !== slideIndex));
    });
  }

  function moveSlide(overlay, next) {
    const carousel = overlay.querySelector('.welcome-carousel');
    const slide = carousel.children[next];
    if (!slide) return;
    const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
    carousel.scrollTo({left: next * carousel.clientWidth, behavior: reducedMotion ? 'instant' : 'smooth'});
  }

  function open() {
    if (resumeVisit) { resumeVisit(); return; }
    if (document.getElementById('stella-welcome')) return;
    previousFocus = document.activeElement;
    index = 0;
    const overlay = document.createElement('div');
    overlay.id = 'stella-welcome';
    overlay.className = 'welcome-overlay';
    overlay.innerHTML = `<section class="welcome-dialog" role="dialog" aria-modal="true" aria-labelledby="welcome-title">
      <header class="welcome-header"><span>新手引导</span><button class="welcome-close" type="button" aria-label="关闭引导">×</button></header>
      <nav class="welcome-nav" aria-label="引导主题">${steps.map((step, i) =>
        `<button type="button" class="welcome-topic"><span>${i + 1}</span>${step.label}</button>`).join('')}</nav>
      <div class="welcome-content"><h2 id="welcome-title" tabindex="-1"></h2><p class="welcome-copy"></p>
      <div class="welcome-carousel" tabindex="0" aria-label="分步截图，可左右滑动"></div>
      <div class="welcome-slide-nav" aria-label="子步骤导航"><div class="welcome-slide-dots"></div>
      <span class="welcome-slide-count" aria-live="polite"></span><span class="welcome-swipe-hint">左右滑动 · 点击截图放大</span>
      <div class="welcome-slide-arrows"><button class="welcome-slide-prev" type="button" aria-label="上一张截图">‹</button>
      <button class="welcome-slide-next" type="button" aria-label="下一张截图">›</button></div></div>
      <div class="welcome-actions"></div></div>
      <footer class="welcome-footer"><label><input id="welcome-dismiss" type="checkbox"> 下次不再提示</label>
      <div><button class="welcome-back" type="button">上一步</button><button class="welcome-next" type="button">下一步</button></div></footer>
      <div class="welcome-zoom" hidden><header><strong>截图原图</strong><button type="button" aria-label="关闭原图">×</button></header>
      <div class="welcome-zoom-body" tabindex="0"><img alt=""></div></div></section>`;
    if (typeof overlay.showPopover === 'function') overlay.setAttribute('popover', 'manual');
    document.body.appendChild(overlay);
    const go = (next, focusHeading = false) => {
      index = next;
      render(overlay);
      if (focusHeading) overlay.querySelector('h2').focus({preventScroll: true});
    };
    overlay.querySelectorAll('.welcome-topic').forEach((button, i) => button.onclick = () => go(i));
    overlay.querySelector('.welcome-close').onclick = close;
    const carousel = overlay.querySelector('.welcome-carousel');
    carousel.addEventListener('load', () => fitSlide(overlay), true);
    carousel.addEventListener('scroll', () => {
      if (!carousel.clientWidth) return;
      const next = Math.max(0, Math.min(carousel.children.length - 1, Math.round(carousel.scrollLeft / carousel.clientWidth)));
      if (next === slideIndex) return;
      slideIndex = next;
      renderSlideControls(overlay);
    }, {passive: true});
    carousel.addEventListener('keydown', event => {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      event.preventDefault();
      moveSlide(overlay, slideIndex + (event.key === 'ArrowRight' ? 1 : -1));
    });
    overlay.querySelector('.welcome-slide-prev').onclick = () => moveSlide(overlay, slideIndex - 1);
    overlay.querySelector('.welcome-slide-next').onclick = () => moveSlide(overlay, slideIndex + 1);
    const viewer = overlay.querySelector('.welcome-zoom');
    const closeViewer = () => {
      viewer.hidden = true;
      carousel.children[slideIndex]?.querySelector('button')?.focus({preventScroll:true});
    };
    viewer.querySelector('button').onclick = closeViewer;
    overlay.querySelector('.welcome-back').onclick = () => go(index - 1, true);
    overlay.querySelector('.welcome-next').onclick = () => {
      if (index === steps.length - 1) close();
      else go(index + 1, true);
    };
    overlay.addEventListener('keydown', event => {
      event.stopPropagation();
      if (event.key === 'Escape') { if (viewer.hidden) close(); else closeViewer(); return; }
      if (event.key !== 'Tab') return;
      const controls = viewer.hidden
        ? [...overlay.querySelectorAll('button:enabled,a[href],input,.welcome-carousel')].filter(control => control.tabIndex >= 0 && !viewer.contains(control) && !control.closest('[hidden]'))
        : [...viewer.querySelectorAll('button,[tabindex="0"]')];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === controls[0]) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); controls[0].focus(); }
    });
    go(0);
    showOverlay(overlay);
  }

  window.StellaWelcome = { open };
  window.addEventListener('load', () => {
    try { if (!localStorage.getItem(key)) setTimeout(open, 800); } catch (_) {}
  });
})();
