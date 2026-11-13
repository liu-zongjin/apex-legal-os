'use strict';
// The server stores only an authenticated encrypted envelope. The key never leaves this page.
const vault = { key: null, salt: null, items: [], revision: 0, payload: null, revealed: new Set(), filters: { all: '', account: '', password: '', site: '' } };
const vaultEncode = bytes => btoa(Array.from(bytes, b => String.fromCharCode(b)).join(''));
const vaultDecode = value => Uint8Array.from(atob(value), c => c.charCodeAt(0));
async function vaultKey(encoded) {
  const raw = vaultDecode(encoded.replace(/-/g, '+').replace(/_/g, '/') + '=');
  return crypto.subtle.importKey('raw', raw, { name: 'AES-GCM' }, false, ['encrypt', 'decrypt']);
}
async function vaultSeal(items, key, salt) {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const bytes = new TextEncoder().encode(JSON.stringify(items));
  const encrypted = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, bytes);
  return { version: 1, salt: vaultEncode(salt), iv: vaultEncode(iv), ciphertext: vaultEncode(new Uint8Array(encrypted)) };
}
async function vaultSave(items, key = vault.key, salt = vault.salt) {
  const payload = await vaultSeal(items, key, salt);
  const result = await api('/api/personal-center/password-vault', { method: 'PUT', body: { payload, revision: vault.revision } });
  vault.revision = result.revision; vault.payload = payload;
  if (vault.key === key) vault.items = items;
}
function vaultLock() {
  vault.key = null; vault.salt = null; vault.items = []; vault.revealed.clear(); vault.filters = { all: '', account: '', password: '', site: '' }; vaultCloseEditor();
  if ($('drawer')?.classList.contains('show')) { closeEditor(); $('drawerBody').textContent = ''; }
  if (activeTab === 'vault') $('content').textContent = '';
}
async function loadVault() {
  if (vault.key) { renderVault(); return; }
  try {
    const data = await api('/api/personal-center/password-vault', { cache: 'no-store' });
    const keyData = await api('/api/personal-center/password-vault/key', { method: 'POST', cache: 'no-store' });
    const key = await vaultKey(keyData.key);
    let items = [];
    if (data.payload) {
      const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: vaultDecode(data.payload.iv) }, key, vaultDecode(data.payload.ciphertext));
      items = JSON.parse(new TextDecoder().decode(plain));
      if (!Array.isArray(items) || !items.every(x => x && /^[0-9a-f-]{36}$/.test(x.id) && ['site', 'account', 'password'].every(k => typeof x[k] === 'string'))) throw new Error('密码库内容格式不正确');
    }
    vault.payload = data.payload; vault.revision = data.revision;
    vault.key = key; vault.salt = data.payload ? vaultDecode(data.payload.salt) : crypto.getRandomValues(new Uint8Array(16)); vault.items = items;
    if (activeTab === 'vault') renderVault();
  } catch (e) { if (activeTab === 'vault') $('content').innerHTML = `<div class="empty">${esc(e.message || '无法解密密码库，请检查本机密钥')}</div>`; }
}
function renderVault() {
  renderTopActions();
  if (!vault.key) { $('content').innerHTML = '<div class="empty">正在打开密码库…</div>'; return; }
  $('content').innerHTML = `<div class="vault-page">

    <section class="vault-workspace" aria-label="账号列表"><div class="vault-section-heading"><div><p class="vault-kicker">YOUR ACCOUNTS</p><h2>已保存的账号 <span id="vaultCount"></span></h2></div><button type="button" class="vault-text-button" onclick="vaultClearFilters()">清除筛选</button></div>
      <div class="vault-filters"><div class="field vault-filter-all"><label for="vaultSearch">全部搜索</label><input class="input" id="vaultSearch" type="search" autocomplete="off" placeholder="搜索账号、密码或网址 / APP"></div><div class="field"><label for="vaultSearchAccount">账号</label><input class="input" id="vaultSearchAccount" type="search" autocomplete="off" placeholder="筛选账号"></div><div class="field"><label for="vaultSearchPassword">密码</label><input class="input" id="vaultSearchPassword" type="password" autocomplete="off" placeholder="筛选密码"></div><div class="field"><label for="vaultSearchSite">网址 / APP 名称</label><input class="input" id="vaultSearchSite" type="search" autocomplete="off" placeholder="筛选网址或名称"></div></div>
      <div id="vaultList" class="vault-list" aria-live="polite"></div></section></div>`;
  for (const [field, id] of Object.entries({ all: 'vaultSearch', account: 'vaultSearchAccount', password: 'vaultSearchPassword', site: 'vaultSearchSite' })) {
    $(id).value = vault.filters[field];
    $(id).addEventListener('input', e => { vault.filters[field] = e.target.value; vaultRows(); });
  }
  vaultRows();
}
function vaultClearFilters() {
  vault.filters = { all: '', account: '', password: '', site: '' };
  for (const id of ['vaultSearch', 'vaultSearchAccount', 'vaultSearchPassword', 'vaultSearchSite']) $(id).value = '';
  vaultRows(); $('vaultSearch').focus();
}
function vaultSafeUrl(value) {
  const raw = String(value || '').trim();
  if (!raw || /[\s\u0000-\u001f]/.test(raw)) return '';
  try {
    const url = new URL(raw);
    if (!['http:', 'https:'].includes(url.protocol) || !url.hostname || url.username || url.password) return '';
    return url.href;
  } catch (_) { return ''; }
}
function vaultOpenUrl(id) {
  const item = vault.items.find(entry => entry.id === id);
  const url = vaultSafeUrl(item?.url || item?.site);
  if (!url) { toast('网址链接无效，请编辑后重试'); return; }
  if (isNativeShell()) window.location.href = `legalkb-external://open?url=${encodeURIComponent(url)}`;
  else window.open(url, '_blank', 'noopener,noreferrer');
}
function vaultRows() {
  const filters = Object.fromEntries(Object.entries(vault.filters).map(([key, value]) => [key, value.trim().toLocaleLowerCase()]));
  const matches = (value, query) => String(value || '').toLocaleLowerCase().includes(query);
  const items = vault.items.filter(item => {
    const fields = [item.account, item.password, item.site, item.url];
    const combined = !filters.all || fields.some(value => matches(value, filters.all)) || filters.all.split(/\s+/).every(term => fields.some(value => matches(value, term)));
    return combined && ['account', 'password'].every(key => matches(item[key], filters[key])) && [item.site, item.url].some(value => matches(value, filters.site));
  });
  $('vaultCount').textContent = `${items.length} / ${vault.items.length}`;
  if (!items.length) {
    const filtered = Object.values(filters).some(Boolean);
    $('vaultList').innerHTML = `<div class="vault-empty"><div class="vault-empty-icon" aria-hidden="true">✳</div><strong>${filtered ? '没有找到匹配的账号' : '从这里，收好第一个账号'}</strong><p>${filtered ? '试试调整搜索条件。' : '添加常用网站或 APP 的登录信息，随用随找。'}</p>${filtered ? '' : '<button class="btn primary" type="button" onclick="vaultEdit()">添加账号</button>'}</div>`;
    return;
  }
  $('vaultList').innerHTML = items.map(item => `<article class="vault-entry"><div class="vault-entry-heading"><span class="vault-entry-icon" aria-hidden="true">${esc(Array.from(item.site.trim())[0]?.toUpperCase() || '✦')}</span><div class="vault-entry-site"><span>网址 / APP</span><strong>${esc(item.site)}</strong></div><div class="vault-entry-actions">${vaultSafeUrl(item.url || item.site) ? `<button class="vault-text-button" type="button" onclick="vaultOpenUrl('${item.id}')" aria-label="打开 ${esc(item.site)} 的网址">打开网址 ↗</button>` : ''}<button class="vault-text-button" type="button" onclick="vaultEdit('${item.id}')">编辑</button><button class="vault-text-button vault-delete" type="button" onclick="vaultDelete('${item.id}')">删除</button></div></div><div class="vault-entry-details"><div class="vault-entry-field"><span>账号</span><div><strong>${esc(item.account)}</strong><button class="vault-mini-button" type="button" onclick="vaultCopy('${item.id}','account')" aria-label="复制 ${esc(item.site)} 的账号">复制</button></div></div><div class="vault-entry-field"><span>密码</span><div><strong class="vault-secret">${vault.revealed.has(item.id) ? esc(item.password) : '••••••••'}</strong><button class="vault-mini-button" type="button" onclick="vaultToggle('${item.id}')" aria-label="${vault.revealed.has(item.id) ? '隐藏' : '显示'} ${esc(item.site)} 的密码">${vault.revealed.has(item.id) ? '隐藏' : '显示'}</button><button class="vault-mini-button" type="button" onclick="vaultCopy('${item.id}','password')" aria-label="复制 ${esc(item.site)} 的密码">复制</button></div></div></div></article>`).join('');
}
function vaultToggle(id) { if (vault.revealed.has(id)) vault.revealed.delete(id); else vault.revealed.add(id); vaultRows(); }
async function vaultCopy(id, field) {
  const item = vault.items.find(x => x.id === id); if (!item) return;
  try { await navigator.clipboard.writeText(item[field]); toast(field === 'password' ? '密码已复制' : '账号已复制'); } catch (_) { toast('复制失败，请检查系统剪贴板权限'); }
}
// Parse pasted text locally; preserve exact candidate values and flag conflicts.
function vaultRecognize(text) {
  const aliases = {
    account: /^(?:登录账号|登陆账号|登录账户|登录帐号|登录名|用户名|用户名称|使用者名称|账户名|账号|帐号|账户|工号|手机号码|手机号|手机|邮箱地址|电子邮件|邮箱|username|user[ _-]?name|login[ _-]?(?:id|name|account)?|account|e-?mail|phone)$/i,
    password: /^(?:登录密码|登陆密码|初始密码|账号密码|账户密码|口令|密碼|密码|pass[ _-]?word|passcode|pass|pwd)$/i,
    site: /^(?:网站名称|平台名称|应用名称|软件名称|app名称|系统名称|网站|平台|应用|软件|系统|app|service)$/i,
    url: /^(?:登录网址|登陆网址|登录地址|登录链接|网站地址|网址链接|网站链接|访问地址|访问链接|官方网址|链接地址|网址|链接|地址|website|url|link)$/i
  };
  const labelPattern = '登录账号|登陆账号|登录账户|登录帐号|登录名|用户名|用户名称|使用者名称|账户名|账号密码|账户密码|账号|帐号|账户|工号|手机号码|手机号|手机|邮箱地址|电子邮件|邮箱|user[ _-]?name|login[ _-]?(?:id|name|account)?|account|e-?mail|phone|登录密码|登陆密码|初始密码|口令|密碼|密码|pass[ _-]?word|passcode|pass|pwd|登录网址|登陆网址|登录地址|登录链接|网站地址|网址链接|网站链接|访问地址|访问链接|官方网址|链接地址|网站名称|平台名称|应用名称|软件名称|系统名称|app名称|网址|链接|地址|website|url|link|网站|平台|应用|软件|系统|app|service';
  const marker = new RegExp('(?:^|[\\n\\r，,；;。\\t \\u4e00-\\u9fff]|\\*\\*|__|【|\\[|（|\\()(' + labelPattern + ')(?:\\*\\*|__)?[】\\]）)]?[ \\t]*(?:[:：=]|是|为|->|→|[ \\t]+)[ \\t]*(?:\\*\\*|__)?', 'gim');
  const found = { account: [], password: [], site: [], url: [] };
  const markers = Array.from(String(text).matchAll(marker));
  const standalone = new RegExp('^[ \\t]*(?:[-*•][ \\t]*)?(' + labelPattern + ')[ \\t]*$', 'gim');
  for (const match of String(text).matchAll(standalone)) {
    if (!markers.some(existing => match.index < existing.index + existing[0].length && existing.index < match.index + match[0].length)) markers.push(match);
  }
  markers.sort((a, b) => a.index - b.index);
  for (let i = 0; i < markers.length; i++) {
    const match = markers[i];
    const key = Object.keys(aliases).find(k => aliases[k].test(match[1]));
    const end = i + 1 < markers.length ? markers[i + 1].index : text.length;
    const segment = text.slice(match.index + match[0].length, end);
    const lines = segment.split(/\r?\n/);
    let value = (lines[0].trim() || (lines.length > 1 ? lines[1].trim() : ''));
    if (value.startsWith('**') && value.endsWith('**') && value.length > 4) value = value.slice(2, -2).trim();
    if ((value.startsWith('“') && value.endsWith('”')) || (value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) value = value.slice(1, -1);
    if (key && value) found[key].push(value);
  }
  let inferred = false;
  if (!markers.length) {
    const lines = text.split(/\r?\n/).map(line => line.trim()).filter(Boolean)
      .filter(line => !/^https?:\/\/\S+$/i.test(line));
    if (lines.length === 2) {
      found.account.push(lines[0]);
      found.password.push(lines[1]);
      inferred = true;
    }
  }
  if (!found.url.length) {
    const urls = text.match(/https?:\/\/[^\s，,；;<>'"）)】\]]+/gi) || [];
    if (urls.length) found.url.push(...urls);
  }
  if (!found.account.length) {
    const emails = text.match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi) || [];
    if (emails.length) found.account.push(...emails);
    else { const phones = text.match(/(?<!\d)1[3-9]\d{9}(?!\d)/g) || []; if (phones.length) found.account.push(...phones); }
  }
  const values = {}, ambiguous = [];
  for (const key of Object.keys(found)) {
    const unique = [...new Set(found[key])];
    values[key] = unique.length === 1 ? unique[0] : '';
    if (unique.length > 1) ambiguous.push(key);
  }
  // A lone URL also supplies a useful display name without hiding the link field.
  if (!values.site && !ambiguous.includes('site') && values.url) values.site = values.url;
  return { values, ambiguous, inferred };
}
let vaultEditorReturnFocus = null;
function vaultCloseEditor() {
  const modal = $('vaultEditorMask'); if (!modal) return;
  modal.remove();
  if (vaultEditorReturnFocus?.isConnected) vaultEditorReturnFocus.focus();
  vaultEditorReturnFocus = null;
}
function vaultEdit(id = '') {
  if (!vault.key) return;
  vaultCloseEditor(); vaultEditorReturnFocus = document.activeElement;
  const item = vault.items.find(x => x.id === id) || { site: '', account: '', password: '', url: '' };
  const mask = document.createElement('div'); mask.id = 'vaultEditorMask'; mask.className = 'vault-editor-mask';
  mask.innerHTML = `<section class="vault-modal" role="dialog" aria-modal="true" aria-labelledby="vaultEditorTitle"><div class="vault-modal-head"><div><p class="vault-kicker">STELLA / ACCOUNT</p><h2 id="vaultEditorTitle">${id ? '编辑账号' : '添加账号'}</h2><p>把登录信息收好，随时可以找到。</p></div><button class="vault-close" type="button" aria-label="关闭" onclick="vaultCloseEditor()">×</button></div><div class="vault-modal-body"><div class="vault-import"><div class="vault-import-heading"><div><strong>粘贴文本，快速识别</strong><p>在本机识别账号、密码和网址，确认后填入下方。</p></div><span>SMART FILL</span></div><label class="vault-sr-only" for="vaultPaste">粘贴包含账号信息的文本</label><textarea id="vaultPaste" spellcheck="false" autocapitalize="off" autocomplete="off" maxlength="20000" placeholder="例如：网址：https://example.com&#10;账号：yourname&#10;密码：••••••••"></textarea><div class="vault-import-actions"><p>识别结果需要你确认，不会自动保存。</p><button class="btn" id="vaultRecognizeButton" type="button">识别信息</button></div><div id="vaultPreview" class="vault-preview" aria-live="polite" hidden></div></div><div class="vault-form-heading"><div><p class="vault-kicker">ACCOUNT DETAILS</p><h3>账号信息</h3></div><span>网址链接为选填</span></div><div class="vault-form"><div class="field vault-full"><label for="vaultSite">网站或 APP 名称</label><input class="input" id="vaultSite" autocomplete="off" maxlength="1000" placeholder="例如：网站或 APP 名称"></div><div class="field vault-full"><label for="vaultUrl">网址链接（选填）</label><input class="input" id="vaultUrl" type="url" autocomplete="off" maxlength="2000" placeholder="https://example.com"></div><div class="field"><label for="vaultAccount">账号</label><input class="input" id="vaultAccount" spellcheck="false" autocapitalize="off" autocomplete="off" maxlength="1000" placeholder="输入账号"></div><div class="field"><label for="vaultPassword">密码</label><input class="input" id="vaultPassword" type="password" spellcheck="false" autocapitalize="off" autocomplete="new-password" maxlength="2000" placeholder="输入密码"></div></div></div><div class="vault-modal-foot"><span>加密保存在本机</span><div><button class="btn" type="button" onclick="vaultCloseEditor()">取消</button><button class="btn primary" type="button" id="vaultSaveButton">保存账号</button></div></div></section>`;
  document.body.appendChild(mask);
  mask.addEventListener('click', e => { if (e.target === mask) vaultCloseEditor(); });
  mask.addEventListener('keydown', e => {
    if (e.key === 'Escape') { e.stopPropagation(); vaultCloseEditor(); }
    if (e.key !== 'Tab') return;
    const focusable = Array.from(mask.querySelectorAll('button:not([disabled]), input:not([disabled]), textarea:not([disabled])')).filter(el => el.getClientRects().length);
    if (!focusable.length) return;
    if (e.shiftKey && document.activeElement === focusable[0]) { e.preventDefault(); focusable[focusable.length - 1].focus(); }
    else if (!e.shiftKey && document.activeElement === focusable[focusable.length - 1]) { e.preventDefault(); focusable[0].focus(); }
  });
  $('vaultSite').value = item.site; $('vaultUrl').value = item.url || ''; $('vaultAccount').value = item.account; $('vaultPassword').value = item.password;
  $('vaultPaste').addEventListener('input', () => { $('vaultPreview').hidden = true; $('vaultPreview').replaceChildren(); });
  $('vaultRecognizeButton').onclick = () => {
    const { values, ambiguous, inferred } = vaultRecognize($('vaultPaste').value);
    const names = { site: '网站 / APP 名称', url: '网址链接', account: '账号', password: '密码' };
    const available = Object.keys(names).filter(k => values[k]);
    const preview = $('vaultPreview'); preview.hidden = false;
    const renderPreview = () => {
      preview.innerHTML = `<div class="vault-preview-head"><strong>识别结果</strong><span>请确认后填入</span></div>${inferred ? '<p>未标注账号和密码，已按两行的先后顺序推测，请核对或调换。</p>' : ''}${available.length ? available.map(k => `<div class="vault-preview-row"><span>${names[k]}</span>${k === 'password' ? '<div><strong id="vaultPreviewPassword">••••••••</strong> <button class="vault-mini-button" type="button" id="vaultPreviewToggle">显示</button></div>' : `<strong>${esc(values[k])}</strong>`}</div>`).join('') : '<p>未找到明确的字段，请补充“账号：”“密码：”等标签后重试，或直接填写。</p>'}${ambiguous.length ? `<p>发现多个${ambiguous.map(k => names[k]).join('、')}，请手动填写这些字段。</p>` : ''}<div class="vault-preview-actions">${values.account && values.password ? '<button class="btn" type="button" id="vaultSwapRecognition">调换账号和密码</button>' : ''}${available.length ? '<button class="btn primary" type="button" id="vaultApplyRecognition">确认并填入</button>' : ''}</div>`;
      if (values.password) $('vaultPreviewToggle').onclick = event => {
        const showing = event.currentTarget.dataset.showing === 'true';
        $('vaultPreviewPassword').textContent = showing ? '••••••••' : values.password;
        event.currentTarget.dataset.showing = String(!showing);
        event.currentTarget.textContent = showing ? '显示' : '隐藏';
      };
      if ($('vaultSwapRecognition')) $('vaultSwapRecognition').onclick = () => {
        [values.account, values.password] = [values.password, values.account];
        renderPreview();
        $('vaultSwapRecognition').focus();
      };
      if (available.length) $('vaultApplyRecognition').onclick = () => {
        for (const key of available) $(key === 'site' ? 'vaultSite' : key === 'url' ? 'vaultUrl' : key === 'account' ? 'vaultAccount' : 'vaultPassword').value = values[key];
        $('vaultPaste').value = ''; preview.hidden = true; preview.replaceChildren(); $('vaultAccount').focus(); toast('已填入，请核对后保存');
      };
    };
    renderPreview();
  };
  $('vaultSaveButton').onclick = async () => {
    const site = $('vaultSite').value.trim(), account = $('vaultAccount').value.trim(), password = $('vaultPassword').value, rawUrl = $('vaultUrl').value.trim();
    const url = rawUrl ? vaultSafeUrl(rawUrl) : '';
    if (rawUrl && !url) { toast('请输入以 http:// 或 https:// 开头的有效网址'); $('vaultUrl').focus(); return; }
    if (!site || !account || !password) { toast('请填写网址或 APP 名称、账号和密码'); return; }
    const next = vault.items.filter(x => x.id !== id); next.unshift({ ...item, id: id || crypto.randomUUID(), site, account, password, url });
    const saveButton = $('vaultSaveButton'); saveButton.disabled = true;
    try { await vaultSave(next); if (mask.isConnected) vaultCloseEditor(); if (activeTab === 'vault' && vault.key) renderVault(); toast('已保存'); } catch (e) { toast(e.message || '保存失败'); if (saveButton.isConnected) saveButton.disabled = false; }
  };
  $('vaultPaste').focus();
}
function vaultDelete(id) {
  const item = vault.items.find(x => x.id === id); if (!item) return;
  openConfirm('删除账号', `确定删除 ${item.site} 的账号记录吗？`, async () => {
    try { await vaultSave(vault.items.filter(x => x.id !== id)); vault.revealed.delete(id); renderVault(); toast('已删除'); } catch (e) { toast(e.message || '删除失败'); }
  });
}
