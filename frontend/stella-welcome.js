/* Local, optional orientation. No account data is read or sent. */
(() => {
  const key = 'stella.welcome.dismissed.v1';
  const steps = [
    { icon: '✦', title: '让 Stella 成为你的办案空间', text: '用几步找到 AI、快捷键和常用同步设置。你可以现在了解，也可以以后从设置重新打开。', action: '' },
    { icon: '✧', title: '接入 AI，辅助办案与知识管理', text: '推荐从 DeepSeek 开始：注册并开通 API、创建密钥，在 AI API 管理中填写密钥并检测，最后选择默认模型。准备好账号后通常几分钟即可完成。按用量计费，轻度使用费用较低，实际金额取决于模型和使用量。', action: '打开 AI API 管理', run: () => openAiApiManagerFromSettings(), link: 'https://api-docs.deepseek.com/zh-cn/quick_start/pricing' },
    { icon: '⌘', title: '设置顺手的快捷键', text: '在设置的“效率与快捷操作”中选择快捷键，可快速打开效率中心、案件管理、添加知识、总览、设置或返回首页。', action: '打开快捷键设置', run: () => openSettingsModal('productivity') },
    { icon: '⚖', title: '连接法院一张网', text: '打开一张网，在“登录、同步与下载设置”中填写法院账号和密码，保存后按页面提示登录官网。', action: '打开一张网', run: () => { closeSettingsModal(); openCourtOnlineService(); } },
    { icon: '✉', title: '连接电子邮箱', text: '在设置中的邮箱配置选择邮箱服务，填写账号和服务商提供的授权信息。连接成功后可在工作空间处理邮件与附件。', action: '打开邮箱配置', run: () => openMailConfigFromSettings() },
    { icon: '☏', title: '同步短信和通讯录', text: '在案件管理的“司法短信”中打开设置和权限诊断。联系人可在案件的联系与备忘中按需同步到 iCloud 通讯录，需授予系统权限；Windows 的可用功能可能不同。', action: '打开案件管理', run: () => { closeSettingsModal(); openCaseManagerTab(); } },
  ];
  let index = 0, previousFocus = null;
  function close() {
    const overlay = document.getElementById('stella-welcome');
    if (!overlay) return;
    if (overlay.querySelector('#welcome-dismiss').checked) {
      try { localStorage.setItem(key, '1'); } catch (_) {}
    }
    overlay.remove();
    previousFocus?.focus();
  }
  function render() {
    const overlay = document.getElementById('stella-welcome');
    const step = steps[index];
    overlay.querySelector('.welcome-icon').textContent = step.icon;
    overlay.querySelector('h2').textContent = step.title;
    overlay.querySelector('.welcome-copy').textContent = step.text;
    overlay.querySelector('.welcome-count').textContent = `${index + 1} / ${steps.length}`;
    const link = overlay.querySelector('.welcome-price');
    link.hidden = !step.link;
    if (step.link) link.href = step.link;
    const action = overlay.querySelector('.welcome-action');
    action.hidden = !step.action;
    action.textContent = step.action;
    action.onclick = () => { close(); step.run(); };
    overlay.querySelector('.welcome-back').disabled = index === 0;
    overlay.querySelector('.welcome-next').textContent = index === steps.length - 1 ? '完成' : '下一步';
  }
  function open() {
    if (document.getElementById('stella-welcome')) return;
    previousFocus = document.activeElement;
    index = 0;
    const overlay = document.createElement('div');
    overlay.id = 'stella-welcome';
    overlay.className = 'welcome-overlay';
    overlay.innerHTML = `<section class="welcome-dialog" role="dialog" aria-modal="true" aria-labelledby="welcome-title"><button class="welcome-close" aria-label="关闭引导">×</button><div class="welcome-art" aria-hidden="true"><div class="welcome-orbit"></div><span class="welcome-icon"></span></div><div class="welcome-content"><span class="welcome-count"></span><h2 id="welcome-title"></h2><p class="welcome-copy"></p><a class="welcome-price" target="_blank" rel="noopener">查看官方计费 ↗</a><button class="welcome-action" type="button"></button></div><div class="welcome-footer"><label><input id="welcome-dismiss" type="checkbox"> 下次不再提示</label><div><button class="welcome-back" type="button">上一步</button><button class="welcome-next" type="button">下一步</button></div></div></section>`;
    document.body.appendChild(overlay);
    overlay.querySelector('.welcome-close').onclick = close;
    overlay.querySelector('.welcome-back').onclick = () => { index--; render(); };
    overlay.querySelector('.welcome-next').onclick = () => { if (index === steps.length - 1) close(); else { index++; render(); } };
    overlay.addEventListener('keydown', event => {
      if (event.key === 'Escape') { close(); return; }
      if (event.key !== 'Tab') return;
      const controls = [...overlay.querySelectorAll('button:not([disabled]):not([hidden]),a:not([hidden]),input')];
      if (event.shiftKey && document.activeElement === controls[0]) { event.preventDefault(); controls[controls.length - 1].focus(); }
      else if (!event.shiftKey && document.activeElement === controls[controls.length - 1]) { event.preventDefault(); controls[0].focus(); }
    });
    render();
    overlay.querySelector('.welcome-close').focus();
  }
  window.StellaWelcome = { open };
  window.addEventListener('load', () => {
    try { if (!localStorage.getItem(key)) setTimeout(open, 800); } catch (_) {}
  });
})();
