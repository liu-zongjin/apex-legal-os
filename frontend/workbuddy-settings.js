(() => {
  const card = document.getElementById('workbuddy-card');
  const panel = document.getElementById('settings-workbuddy-panel');
  if (!card || !panel) return;
  if (!['localhost', '127.0.0.1', '[::1]'].includes(location.hostname)) {
    card.remove();
    panel.remove();
    return;
  }
  card.hidden = false;
  const connect = document.getElementById('workbuddy-connect');
  const openApp = document.getElementById('workbuddy-open-app');
  const revoke = document.getElementById('workbuddy-revoke');
  const message = document.getElementById('workbuddy-status');
  const accessState = document.getElementById('workbuddy-access-state');
  const grantAll = document.getElementById('workbuddy-grant-all');
  const extraCount = document.getElementById('workbuddy-extra-scope-count');
  const manual = document.getElementById('workbuddy-manual');
  const configuration = document.getElementById('workbuddy-config');
  const switches = Array.from(panel.querySelectorAll('[data-workbuddy-scope]'));
  let enabled = false;
  let loaded = false;
  let busy = false;

  async function request(method, url = '/api/workbuddy/settings', permissions) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    const options = { method, cache: 'no-store', signal: controller.signal };
    if (permissions) {
      options.headers = { 'Content-Type': 'application/json' };
      options.body = JSON.stringify(permissions);
    }
    try {
      const response = await fetch(url, options);
      const data = await response.json().catch(() => null);
      if (response.status === 401) throw new Error('请重新登录本机 Stella，再重试。');
      if (!response.ok || !data) throw new Error(data?.detail || 'Stella 暂时无法完成操作，请重试。');
      return data;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('Stella 响应超时，请重试。');
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }

  const extraScopes = Array.from(panel.querySelectorAll('.workbuddy-extra-scopes [data-workbuddy-scope]'));

  function updateExtraCount() {
    const number = extraScopes.filter(element => element.getAttribute('aria-checked') === 'true').length;
    extraCount.textContent = `${number}/${extraScopes.length} 项已选`;
  }

  function render(data) {
    enabled = data.enabled;
    accessState.dataset.enabled = String(enabled);
    accessState.textContent = enabled ? 'Stella 已授权' : '尚未授权';
    openApp.hidden = revoke.hidden = !enabled;
    connect.textContent = enabled ? '保存权限' : '连接 WorkBuddy';
    for (const element of switches) {
      if (data.permissions) element.setAttribute('aria-checked', String(data.permissions[element.dataset.workbuddyScope]));
    }
    updateExtraCount();
    manual.hidden = !data.configuration;
    configuration.value = data.configuration ? JSON.stringify(data.configuration, null, 2) : '';
    message.textContent = data.message || (data.registered
      ? '已写入连接配置。首次使用请查看下方引导。'
      : enabled ? '可打开 WorkBuddy 开始查询。' : '尚未授权。');
  }

  async function run(pending, operation) {
    if (busy) return;
    busy = true;
    message.textContent = pending;
    connect.disabled = openApp.disabled = revoke.disabled = grantAll.disabled = true;
    for (const element of switches) element.disabled = true;
    try {
      await operation();
    } catch (error) {
      message.textContent = error.message || '暂时无法完成操作，请重试。';
      if (!loaded) {
        accessState.textContent = '读取失败';
        connect.textContent = '重试读取权限';
      }
    } finally {
      busy = false;
      connect.disabled = openApp.disabled = revoke.disabled = false;
      grantAll.disabled = !loaded;
      for (const element of switches) element.disabled = !loaded;
    }
  }

  function load() {
    return run('正在读取连接状态…', async () => {
      render(await request('GET'));
      loaded = true;
    });
  }

  async function launch() {
    await request('POST', '/api/workbuddy/open');
    message.textContent = manual.hidden
      ? '已请求打开 WorkBuddy。首次使用请查看下方引导。'
      : '已请求打开 WorkBuddy。配置仍需按下方提示完成。';
  }

  card.addEventListener('click', () => {
    panel.hidden = !panel.hidden;
    card.setAttribute('aria-expanded', String(!panel.hidden));
    if (!panel.hidden) {
      panel.scrollIntoView({ block: 'nearest' });
      if (!loaded) void load();
    }
  });
  for (const element of switches) {
    element.addEventListener('click', () => {
      element.setAttribute('aria-checked', String(element.getAttribute('aria-checked') !== 'true'));
      updateExtraCount();
    });
  }
  function savePermissions(permissions, all = false) {
    const firstConnection = !enabled;
    const pending = firstConnection ? '正在连接 WorkBuddy…' : '正在保存权限…';
    return run(all ? '正在保存全部授权…' : pending, async () => {
      const data = await request('PUT', '/api/workbuddy/settings', permissions);
      render(data);
      if (firstConnection && data.registered) await launch();
      if (data.registered) {
        const restartNote = '如果 WorkBuddy 中还看不到新工具，请重新打开 WorkBuddy。';
        message.textContent = all ? '已全部授权。' + restartNote : message.textContent + restartNote;
      }
    });
  }

  connect.addEventListener('click', () => {
    if (!loaded) return load();
    return savePermissions(Object.fromEntries(switches.map(element => [
      element.dataset.workbuddyScope, element.getAttribute('aria-checked') === 'true'
    ])));
  });
  grantAll.addEventListener('click', () => {
    if (loaded) return savePermissions(Object.fromEntries(switches.map(element => [element.dataset.workbuddyScope, true])), true);
  });
  openApp.addEventListener('click', () => run('正在打开 WorkBuddy…', launch));
  revoke.addEventListener('click', () => run('正在撤销授权…', async () => {
    const data = await request('DELETE');
    render({ ...data, permissions: Object.fromEntries(switches.map(element => [element.dataset.workbuddyScope, element.dataset.workbuddyScope === 'knowledge'])) });
  }));
  document.getElementById('workbuddy-copy').addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(configuration.value);
      message.textContent = '已复制 Stella 配置。';
    } catch {
      configuration.select();
      message.textContent = '请使用复制快捷键复制已选中的配置。';
    }
  });

  const exampleStatus = document.getElementById('workbuddy-guide-copy-status');
  panel.querySelectorAll('[data-workbuddy-copy]').forEach(button => {
    button.addEventListener('click', async () => {
      const example = document.getElementById(button.dataset.workbuddyCopy);
      try {
        await navigator.clipboard.writeText(example.textContent.trim());
        exampleStatus.textContent = '已复制。请在 WorkBuddy 新建任务中粘贴并发送。';
      } catch {
        const selection = window.getSelection();
        if (selection) {
          const range = document.createRange();
          range.selectNodeContents(example);
          selection.removeAllRanges();
          selection.addRange(range);
        }
        exampleStatus.textContent = '请按复制快捷键复制选中的示例。';
      }
    });
  });

  function openLinkedArticle() {
    const url = new URL(location.href);
    const articleId = Number(url.searchParams.get('open_article'));
    if (!Number.isSafeInteger(articleId) || articleId < 1) return;
    url.searchParams.delete('open_article');
    history.replaceState(null, '', url);
    openArticleInTab(articleId, '文章详情');
  }
  if (typeof appStartupComplete !== 'undefined' && appStartupComplete) openLinkedArticle();
  else window.addEventListener('apex:app-ready', openLinkedArticle, { once: true });
})();
