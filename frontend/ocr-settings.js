(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let config = null, mode = 'shared', busy = false;
  const media = matchMedia('(prefers-color-scheme: dark)');
  function theme() {
    let dark = localStorage.getItem('theme') === 'dark' || (localStorage.getItem('theme') !== 'light' && media.matches);
    try { if (parent !== window) dark = parent.document.body.classList.contains('dark-mode'); } catch (_) {}
    document.body.classList.toggle('dark-mode', dark);
  }
  theme();
  window.addEventListener('storage', theme);
  media.addEventListener?.('change', theme);
  try { if (parent !== window) new MutationObserver(theme).observe(parent.document.body, {attributes:true, attributeFilter:['class']}); } catch (_) {}
  const dirty = () => config && (mode !== config.key_mode || $('api-key').value.trim() !== '');
  function controls() {
    document.querySelectorAll('[data-mode]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.mode === mode));
      button.disabled = busy || !config || config.managed_mode;
    });
    $('dedicated-fields').hidden = mode !== 'dedicated';
    $('api-key').disabled = busy || !config || config.managed_key;
    $('save-button').disabled = busy || !config || !dirty();
    $('test-button').disabled = busy || !config?.configured || !!dirty();
    $('ai-settings').disabled = busy;
    $('mode-note').textContent = mode === 'shared'
      ? '使用 AI API 管理中 SCNet 的密钥。更换共用密钥请打开 AI API 管理；返回本页时会更新状态。'
      : '只用于共用云端 OCR，不修改大模型密钥。首次填写后保存，再运行测试。';
    if (config?.managed_mode) $('mode-note').textContent += ' 密钥方式由系统环境变量管理。';
    $('key-note').textContent = config?.managed_key ? '专用密钥由系统环境变量管理，需在部署配置中修改并重启。' : '保存后只显示掩码，完整密钥不会返回页面。';
    if (dirty()) $('test-state').textContent = '有未保存的配置';
  }
  function showTest(result) {
    $('test-state').textContent = result ? (result.ok ? '本次测试通过' : '本次测试失败') : (config?.configured ? '已配置，尚未测试' : '尚未配置');
    $('test-result').hidden = !result;
    if (!result) return;
    $('test-message').textContent = result.message;
    $('test-message').classList.toggle('error', !result.ok);
    const date = result.tested_at ? new Date(result.tested_at).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai', hour12:false}) : '';
    $('test-meta').textContent = `测试时间（北京时间）：${date} · 耗时 ${result.latency_ms ?? 0} 毫秒`;
    $('test-text').textContent = result.text || '';
    $('test-text').hidden = !result.text;
  }
  function render(value) {
    config = value; mode = value.key_mode;
    $('masked-key').textContent = value.key_masked;
    $('api-key').value = '';
    showTest(value.test); controls();
  }
  async function api(path, options = {}) {
    const response = await fetch(path, {cache:'no-store', ...options, headers:{'Content-Type':'application/json', ...options.headers}});
    if (response.status === 401 || response.redirected) throw new Error('登录已过期，请重新登录 Stella 后再操作');
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '操作失败，请稍后重试');
    return data;
  }
  function feedback(message, error = false) { $('save-status').textContent = message; $('save-status').classList.toggle('error', error); }
  document.querySelectorAll('[data-mode]').forEach(button => button.addEventListener('click', () => {
    mode = button.dataset.mode;
    if (mode === 'shared') $('api-key').value = '';
    showTest(config.test); controls(); feedback(dirty() ? '请保存配置后再测试。' : '');
  }));
  $('api-key').addEventListener('input', () => { showTest(config.test); controls(); });
  $('config-form').addEventListener('submit', async event => {
    event.preventDefault(); if (busy || !config || !dirty()) return;
    busy = true; controls(); feedback('正在保存…');
    try {
      render(await api('/api/ocr-settings', {method:'PUT', body:JSON.stringify({key_mode:mode, api_key:$('api-key').value.trim()})}));
      feedback('配置已保存，新的 OCR 请求立即生效。');
    } catch (error) { feedback(error.message, true); }
    finally { busy = false; controls(); }
  });
  $('test-button').addEventListener('click', async () => {
    if (busy || !config?.configured || dirty()) return;
    busy = true; controls(); $('test-state').textContent = '正在识别…'; $('test-result').hidden = true;
    try {
      const result = await api('/api/ocr-settings/test', {method:'POST'});
      // Refresh configuration as it may have changed in another settings tab during the request.
      const latest = await api('/api/ocr-settings');
      render(latest);
      if (!latest.test) { showTest(null); feedback('配置已变化，请使用当前配置重新测试。'); }
      else showTest(result);
    } catch (error) { $('test-state').textContent = '测试未完成'; feedback(error.message, true); }
    finally { busy = false; controls(); }
  });
  $('ai-settings').addEventListener('click', () => {
    try { if (parent !== window && typeof parent.openAiApiManagerTab === 'function') { parent.openAiApiManagerTab(); return; } } catch (_) {}
    location.href = '/ai-api-manager';
  });
  let loadSequence = 0;
  async function load() {
    const sequence = ++loadSequence;
    try {
      const value = await api('/api/ocr-settings');
      if (sequence === loadSequence && !busy && !dirty()) render(value);
    } catch (error) { if (sequence === loadSequence) feedback(error.message, true); }
  }
  document.addEventListener('visibilitychange', () => { if (!document.hidden && !busy && !dirty()) load(); });
  window.addEventListener('focus', () => { if (!busy && !dirty()) load(); });
  window.ApexLifecycle?.onChange(active => { if (active && !busy && !dirty()) load(); });
  load();
})();
