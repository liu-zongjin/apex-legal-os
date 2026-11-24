/* Local walkthrough. Screenshots use anonymous example data. */
(() => {
  const key = 'stella.welcome.dismissed.v1';
  // Coordinates are measured against the full 1440 × 850 screenshots.
  const shotTargets = {
  "start-knowledge": [
    94.61,
    7.94
  ],
  "start-cases": [
    21.64,
    16.44
  ],
  "menu-settings": [
    85.97,
    5.08
  ],
  "menu-court": [
    21.64,
    31.03
  ],
  "settings-productivity": [
    18.42,
    36.12
  ],
  "settings-ai": [
    57.22,
    33.26
  ],
  "settings-mail": [
    57.22,
    54.43
  ],
  "settings-guide": [
    80.07,
    9.29
  ],
  "shortcut-keys": [
    47.15,
    55.01
  ],
  "shortcut-edit": [
    57.22,
    55.01
  ],
  "ai-configure": [
    15.21,
    40.32
  ],
  "deepseek-test": [
    81.32,
    75.43
  ],
  "deepseek-default": [
    60.43,
    49.98
  ],
  "deepseek-create": [
    72.89,
    18.41
  ],
  "deepseek-key": [
    83.68,
    50.24
  ],
  "deepseek-save": [
    95.07,
    95.53
  ],
  "mail-authorize": [
    18.21,
    50.01
  ],
  "mail-account": [
    50,
    50.04
  ],
  "mail-save": [
    85.97,
    77.34
  ],
  "mail-test": [
    17.36,
    49.96
  ],
  "court-entry": [
    89.51,
    11.24
  ],
  "court-login": [
    16.81,
    11.24
  ],
  "court-account": [
    37.12,
    45.16
  ],
  "sms-entry": [
    86.35,
    13.41
  ],
  "sms-settings": [
    65.05,
    14.83
  ],
  "sms-permissions": [
    79.86,
    13.41
  ]
};
  Object.assign(shotTargets, {"sms-tab": [45.43, 3.53], "contact-sync": [74.78, 49.93]});
  const demonstrations = {
    'home-court': ['context-home', 'context-menu', 87.15, 2.29, 'context-court', 21.64, 31.03],
    'home-mail': ['context-home', 'context-menu', 87.15, 2.29, 'after-menu-settings', 85.97, 5.08, 'context-mail-form', 57.22, 54.43],
    'home-cases': ['context-home', 'context-menu', 87.15, 2.29, 'context-cases', 21.64, 16.44],
    'home-settings': ['context-home', 'context-menu', 87.15, 2.29, 'after-menu-settings', 85.97, 5.08],
    'menu-mail': ['full-menu-settings', 'after-menu-settings', 85.97, 5.08, 'context-mail-form', 57.22, 54.43],
    'start-efficiency': ['context-home', 'context-menu', 87.15, 2.29],
    'menu-settings': ['full-menu-settings', 'after-menu-settings', 85.97, 5.08],
    'start-cases': ['full-start-cases', 'context-cases', 21.64, 16.44],
    'menu-court': ['full-menu-court', 'context-court', 21.64, 31.03],
    'case-contact-entry': ['full-case-contact-entry', 'after-case-contact-entry', 50, 36.71],
    'shortcut-keys': ['full-shortcut-keys', 'after-shortcut-keys', 47.16, 54.65],
    'sms-permissions': ['full-sms-permissions', 'after-sms-permissions', 79.86, 13.41],
    'sms-tab': ['full-sms-tab', 'after-sms-tab', 45.43, 3.53],
    'settings-ai': ['full-settings-ai', 'context-ai', 57.22, 33.26],
    'settings-mail': ['full-settings-mail', 'context-mail-form', 57.22, 54.43],
    'settings-productivity': ['full-settings-productivity', 'context-shortcuts', 18.42, 36.12],
    'ai-configure': ['full-ai-configure', 'context-ai-form', 15.21, 40.32],
    'court-entry': ['full-court-entry', 'context-court-form', 89.51, 11.24],
    'sms-entry': ['full-sms-entry', 'context-sms-form', 86.35, 13.41],
  };
  const steps = [
    { label: '开始使用', title: '从案件和知识开始', copy: '案件管理和知识库可直接使用。需要 AI 辅助整理材料或检索知识时，再接入模型。',
      panels: [
        ['home-cases', '打开案件管理', '点击右上角「效率中心」，再选择「案件管理」。'],
        ['start-knowledge', '收录第一篇知识', '打开「添加知识」，按资料类型选择网页链接、上传文档或国家法规库。'],
      ], actions: [['打开案件管理', () => { closeSettingsModal(); openCaseManagerTab(); }], ['打开添加知识', () => { closeSettingsModal(); openSubmitModal(); }, {host: '#submit-modal.open'}]] },
    { label: '配置 AI API', title: '配置 AI API', copy: '推荐先接入 DeepSeek，配置简单、费用较低，拿到密钥后通常几分钟即可完成。具体费用按模型和实际用量计费。',
      panels: [
        ['home-settings', '进入设置', '点击右上角「效率中心」，再点击菜单中的设置图标。'],
        ['settings-ai', '进入 AI API 管理', '在「AI 与扩展功能」中选择「AI API 管理」。'],
        ['ai-configure', '选择 DeepSeek', '在 AI API 管理页点击「配置 DeepSeek」。'],
        ['deepseek-create', '创建并复制密钥', '从 Stella 的「如何配置？」进入 DeepSeek 开放平台，在 API keys 页面创建并复制密钥。'],
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
        ['home-settings', '进入设置', '点击右上角「效率中心」，再点击菜单中的设置图标。'],
        ['settings-productivity', '选择工作效率', '在设置左侧点击「工作效率」，找到快捷键。'],
        ['shortcut-keys', '点选一个键帽', '在「设置 → 工作效率 → 快捷键」的键盘上，点你要设置的键位。'],
        ['shortcut-edit', '选择功能和组合键', '在「执行动作」里选功能，勾选组合键，再点击「保存」。'],
      ], actions: [['打开快捷键设置', () => {
        openSettingsModal('shortcuts');
        requestAnimationFrame(() => document.getElementById('settings-shortcuts-title')?.scrollIntoView({block:'start'}));
      }, {host: '#settings-modal-overlay.open'}]] },
    { label: '一张网', title: '填写法院一张网账号', copy: '保存后，在一张网页面按提示登录官网。',
      panels: [
        ['home-court', '打开一张网', '点击右上角「效率中心」，再选择「一张网」。'],
        ['court-entry', '打开登录设置', '在一张网页面右侧点击「设置」。'],
        ['court-account', '填写法院账号和密码', '在「登录、同步与下载设置」中填写账号和密码，点击「保存设置」。'],
        ['court-login', '回到一张网登录', '点击「打开法院诉讼服务网」或「登录官网」，按法院官网提示完成核验。'],
      ], actions: [['打开一张网登录设置', () => {
        closeSettingsModal();
        openCourtOnlineService();
        return atWorkspaceFrame('/case-manager', frame => frame.openCourtLoginSetup());
      }, {frame: '#courtSettingsModal'}]] },
    { label: '电子邮箱', title: '连接你的电子邮箱', copy: '选择你使用的邮箱，直接进入该账号的配置表单。',
      panels: [
        ['home-mail', '进入邮箱配置', '依次打开「效率中心」「设置」和「邮箱配置」。'],
        ['mail-authorize', '获取客户端授权', '通过表单顶部的指引进入邮箱网页版，按该服务商的说明取得授权码或客户端专用密码。截图以 QQ 邮箱为例。'],
        ['mail-account', '填写邮箱账号和授权码', '填入完整邮箱地址和客户端授权码或专用密码。'],
        ['mail-save', '保存邮箱配置', '点击表单底部的「保存配置」。'],
        ['mail-test', '检测连接', '在邮箱卡片点击「检测连接」，通过后即可从效率中心打开该邮箱。'],
      ], actions: [['腾讯企业邮箱', () => openMailConfigFromSettings('qq_exmail'), {frame: '#drawerBackdrop.open'}], ['网易企业邮箱', () => openMailConfigFromSettings('netease_exmail'), {frame: '#drawerBackdrop.open'}], ['QQ 邮箱', () => openMailConfigFromSettings('qq_mail'), {frame: '#drawerBackdrop.open'}]] },
    { label: '短信与通讯录', title: '同步司法短信和案件联系人', copy: 'macOS 可读取已同步到「信息」的司法短信，并将案件联系人按需同步到 iCloud 通讯录。Windows 可在司法短信中导入文本或截图。',
      panels: [
        ['home-cases', '打开案件管理', '点击右上角「效率中心」，再选择「案件管理」。'],
        ['sms-tab', '进入司法短信', '在案件管理顶部点击「司法短信」。'],
        ['sms-entry', '打开司法短信设置', '在案件管理顶部选择「司法短信」，再点击右侧「设置」。'],
        ['sms-settings', '设置司法短信读取', '在「司法短信设置」里设置定时读取和扫描间隔，再保存。'],
        ['sms-permissions', '检查短信同步权限', '打开「同步与权限诊断」，在 Mac 上按页面指引检查信息同步及读取权限。'],
        ['case-contact-entry', '选择一个案件', '回到案件信息列表，点击要同步联系人的案件。'],
        ['contact-sync', '同步一位案件联系人', '选择案件进入「联系与备忘」，点联系人行尾的「同步通讯录」。首次使用按 macOS 提示授权。'],
      ], actions: [
        ['打开司法短信设置', () => openCaseGuide(frame => { frame.switchTab('judicialMessages'); return frame.openJudicialSettings(); }), {frame: '#drawer.show'}],
        ['打开权限诊断', () => openCaseGuide(frame => frame.openJudicialSyncGuide()), {frame: '#drawer.show'}],
        ['选择案件，同步联系人', () => openCaseGuide(frame => frame.openContactSyncGuide()), {frame: '#drawer.show'}],
      ] },
    { label: '完成', title: '准备好了', copy: '可以随时回到这里，继续了解 Stella。',
      panels: [
        ['settings-guide', '以后在哪里打开新手引导', '打开「设置」，点击右上角的「新手引导」。即使勾选了「下次不再提示」，也可以从这里重新打开。'],
      ], actions: [] },
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
      const demonstration = demonstrations[shot];
      const target = shotTargets[shot];
      const origin = target && target.map(v => v > 80 ? 100 : v < 20 ? 0 : v);
      return `<figure class="welcome-slide" role="group" aria-label="第 ${i + 1} 步，共 ${step.panels.length} 步">
        <button class="welcome-shot" type="button" aria-label="放大查看截图：${title}">
          <span class="welcome-shot-frame ${demonstration || target ? 'welcome-full-frame' : ''} ${demonstration ? (demonstration[7] ? 'welcome-demo-sequence welcome-demo-four' : demonstration[4] ? 'welcome-demo-sequence welcome-demo-three' : 'welcome-demo-sequence') : target ? 'welcome-context-sequence' : ''}" ${demonstration ? `style="--target-x:${demonstration[2]}%;--target-y:${demonstration[3]}%;--target2-x:${demonstration[5] || 0}%;--target2-y:${demonstration[6] || 0}%;--target3-x:${demonstration[8] || 0}%;--target3-y:${demonstration[9] || 0}%"` : target ? `style="--target-x:${target[0]}%;--target-y:${target[1]}%;--origin-x:${origin[0]}%;--origin-y:${origin[1]}%"` : ''}>${demonstration
            ? `<img src="/static/welcome-shots/${demonstration[0]}.webp?v=4" alt="${title}的 Stella 实际操作截图" draggable="false">
               <img class="welcome-demo-after" src="/static/welcome-shots/${demonstration[1]}.webp?v=4" alt="" aria-hidden="true" draggable="false">
               ${demonstration[4] ? `<img class="welcome-demo-third" src="/static/welcome-shots/${demonstration[4]}.webp?v=4" alt="" aria-hidden="true" draggable="false">` : ""}
               ${demonstration[7] ? `<img class="welcome-demo-fourth" src="/static/welcome-shots/${demonstration[7]}.webp?v=4" alt="" aria-hidden="true" draggable="false">` : ""}
               <span class="welcome-demo-pointer" aria-hidden="true"></span>`
            : target ? `<img src="/static/welcome-shots/full-${shot}.webp?v=4" alt="${title}的 Stella 完整页面截图，红框标出操作位置" draggable="false">`
            : `<img src="/static/welcome-shots/${shot}.jpg?v=4" alt="${title}的 Stella 操作截图，红框标出操作位置" draggable="false" ${i > 0 ? 'loading="lazy"' : ''}>`}
          </span>
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
      `<button type="button" aria-label="第 ${i + 1} 步：${title}"></button>`).join('');
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
    // Slide area has a stable height across topics.
    if (slide) carousel.style.removeProperty('height');
  }

  function renderSlideControls(overlay) {

    const total = steps[index].panels.length;
    const [, title, caption] = steps[index].panels[slideIndex];
    overlay.querySelector('.welcome-current-title').textContent = title;
    overlay.querySelector('.welcome-current-caption').textContent = caption;
    const isLast = index === steps.length - 1;
    overlay.querySelector('.welcome-actions').hidden = isLast;
    overlay.querySelector('.welcome-slide-count').textContent = `${slideIndex + 1} / ${total}`;
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
      <div class="welcome-slide-meta"><div class="welcome-current-copy"><strong class="welcome-current-title"></strong><span class="welcome-current-caption"></span></div>
      <div class="welcome-slide-nav" aria-label="子步骤导航"><div class="welcome-slide-dots"></div>
      <span class="welcome-slide-count" aria-live="polite"></span><span class="welcome-swipe-hint">左右滑动 · 点击截图放大</span>
      <div class="welcome-slide-arrows"><button class="welcome-slide-prev" type="button" aria-label="上一张截图">‹</button>
      <button class="welcome-slide-next" type="button" aria-label="下一张截图">›</button></div></div></div>
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
