(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const categoryNames = { litigation: '诉讼 / 仲裁', non_litigation: '非诉', criminal: '刑事' };
  const stateNames = { confirmed: '已入卷', excluded: '不入卷', review: '待确认', suggested: '建议分类', learned: '已学习建议', ambiguous: '分类有歧义', unmatched: '待分类', template: '疑似空白模板', changed: '文件已变化', missing: '文件缺失' };
  const state = { caseId: Number(new URLSearchParams(location.search).get('case_id') || 0), data: null, busy: false, searchTimer: 0, modalAction: null, folder:'', fileQuery:'', selected:new Set(), visibleLimit:80, expanded:new Set() };
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const caseName = item => item.series_code && (!item.display_name || item.display_name===item.series_code || item.display_name.startsWith('新子案')) ? item.title.split('·').at(-1) : (item.display_name || item.title);
  const api = async (url, options = {}) => { const response = await fetch(url, {credentials:'same-origin', ...options}); const raw = await response.text(); let data; try { data = JSON.parse(raw); } catch (_) { data = {}; } if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `请求失败 (${response.status})`); return data; };
  const send = (url, method, body) => api(url, {method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(body || {})});
  function toast(message) { const element = $('toast'); element.textContent = message; element.classList.add('show'); clearTimeout(toast.timer); toast.timer = setTimeout(() => element.classList.remove('show'), 4200); }
  function modal(title, body, confirmLabel, action) { $('modalTitle').textContent = title; $('modalBody').innerHTML = body; $('modalConfirm').textContent = confirmLabel; state.modalAction = action; $('modal').hidden = false; $('modalCancel').focus(); }
  function closeModal() { $('modal').hidden = true; state.modalAction = null; }
  $('modalCancel').addEventListener('click', closeModal);
  $('modal').addEventListener('click', event => { if (event.target === $('modal')) closeModal(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') { closeModal(); document.querySelectorAll('.material-options').forEach(el => el.remove()); } });
  $('modalConfirm').addEventListener('click', async () => { if (!state.modalAction) return; const action = state.modalAction; $('modalConfirm').disabled = true; try { await action(); closeModal(); } catch(error) { toast(error.message); } finally { $('modalConfirm').disabled = false; } });

  async function lookup(query) {
    try {
      const result = await api(`/api/case-manager/case-lookup?q=${encodeURIComponent(query)}&limit=30`);
      const rows = (result.items || []).flatMap(item => [item, ...(item.children || [])]);
      $('caseResults').innerHTML = rows.length ? rows.map(item => `<button type="button" role="option" data-case-id="${Number(item.id)}" data-title="${esc(caseName(item))}"><strong>${esc(item.series_code ? `${item.series_code} ${caseName(item)}` : item.title)}</strong><small>${esc(item.case_type || '未标注类型')}${item.case_numbers?.[0]?.case_no ? ' · ' + esc(item.case_numbers[0].case_no) : ''}</small></button>`).join('') : '<div class="no-results">没有找到案件</div>';
      $('caseResults').hidden = false; $('caseSearch').setAttribute('aria-expanded', 'true');
    } catch(error) { toast(error.message); }
  }
  $('caseSearch').addEventListener('input', event => { clearTimeout(state.searchTimer); state.searchTimer = setTimeout(() => lookup(event.target.value.trim()), 230); });
  $('caseSearch').addEventListener('focus', () => lookup($('caseSearch').value.trim()));
  $('caseResults').addEventListener('click', event => { const button = event.target.closest('[data-case-id]'); if (!button) return; state.caseId = Number(button.dataset.caseId); state.folder=''; state.selected.clear(); $('caseSearch').value = button.dataset.title; $('caseResults').hidden = true; $('caseSearch').setAttribute('aria-expanded','false'); history.replaceState(null, '', `?case_id=${state.caseId}`); parent.postMessage({type:'apex:case-archive-case-selected',version:1,caseId:state.caseId,caseTitle:button.dataset.title},location.origin); refresh(true); });
  document.addEventListener('click', event => { if (!event.target.closest('.picker')) { $('caseResults').hidden = true; $('caseSearch').setAttribute('aria-expanded','false'); } });

  function setBusy(busy) { state.busy = busy; $('scanButton').disabled = busy || !state.caseId; $('exportButton').disabled = busy || !state.data?.bound; }
  async function refresh(scan = false) {
    if (!state.caseId) return;
    setBusy(true);
    try {
      state.data = scan ? await send(`/api/case-archive/cases/${state.caseId}/scan`, 'POST') : await api(`/api/case-archive/cases/${state.caseId}`);
      $('caseSearch').value = state.data.case.display_name;
      if (parent !== window) parent.postMessage({type:'apex:case-archive-case-selected',version:1,
        caseId:state.caseId,caseTitle:state.data.case.display_name},location.origin);
      render();
    } catch(error) { toast(error.message); }
    finally { setBusy(false); }
  }
  $('scanButton').addEventListener('click', () => refresh(true));

  function render() {
    const data = state.data;
    $('caseLabel').textContent = `${data.case.display_name} · ${data.case.case_type || '未标注案件类型'}`;
    $('categoryChoices').innerHTML = Object.entries(categoryNames).map(([code,name]) => `<button type="button" data-category="${code}" class="${data.category === code ? 'active' : ''}" aria-pressed="${data.category === code}">${name}</button>`).join('');
    if (!data.bound) {
      $('summary').textContent = '尚未连接案件文件夹';
      $('workspace').innerHTML = `<div class="empty-state"><strong>${esc(data.message || '请先绑定案件文件夹')}</strong><p>工作台直接读取案件管理中绑定的本地文件夹。</p><button class="button primary" id="goBind" type="button">前往案件管理绑定</button></div>`;
      $('goBind').onclick = () => parent.postMessage({type:'apex:open-case-manager',version:1},location.origin);
      return;
    }
    const confirmed = data.materials.filter(m => m.state === 'confirmed').length;
    const unresolved = data.materials.filter(m => !['confirmed','excluded'].includes(m.state)).length;
    $('summary').textContent = `${confirmed} 份入卷 · ${unresolved} 份待核对`;
    $('workspace').innerHTML = `${renderChecklist(data)}<div class="right-column">${renderMaterials(data)}${renderExports(data)}</div>`;
    const query = $('fileSearch'); if(query) query.value = state.fileQuery;
  }

  function renderChecklist(data) {
    const rows = data.checklist.map((item,index) => {
      const count = data.counts?.[item.code] || 0;
      const na = item.applicability === 'na';
      const generated = (data.category==='litigation' && index===14) || (data.category==='non_litigation' && index===6);
      const files = data.materials.filter(m=>m.state==='confirmed' && m.item_code===item.code).sort((a,b)=>(a.position||9999)-(b.position||9999)||a.path.localeCompare(b.path,'zh-CN'));
      const expanded = state.expanded.has(item.code);
      return `<div class="check-row ${na?'na':''}" data-code="${esc(item.code)}"><span class="number">${index+1}</span><div><button class="check-title" data-action="expand" aria-expanded="${expanded}" type="button">${files.length ? (expanded?'▾':'▸') : '·'} ${esc(item.name)}</button><small>${generated ? '生成案卷时自动编写' : na ? '不适用' : count ? `${count} 份已确认材料` : '待补或待核对'}</small>${expanded ? `<div class="check-files">${files.map(m=>`<button type="button" data-action="preview" data-path="${esc(m.path)}" title="预览 ${esc(m.name)}">${esc(m.name)}</button>`).join('') || '<small>此类暂无已入卷文件</small>'}</div>` : ''}</div><div class="check-actions"><span class="pill ${count||generated?'good':na?'':'alert'}">${generated?'自动生成':na?'不适用':count?'已齐':'待补'}</span>${generated?'':`<button class="button small" data-action="toggle-na" title="切换适用状态" type="button" aria-pressed="${na}">${na?'恢复':'不适用'}</button>`}</div></div>`;
    }).join('');
    return `<section class="panel"><div class="panel-head"><div><h2>归档清单</h2><p class="note">按律所样本排列；材料可逐案调整。</p></div><button class="button small" data-action="edit-checklist" type="button">编辑清单</button></div><div class="panel-body">${rows}</div></section>`;
  }
  function materialStatus(m) {
    const label = stateNames[m.state] || m.state;
    const details = [m.duplicate_of ? `与 ${m.duplicate_of} 内容重复` : '', m.aggregate ? '疑似已合并卷，需确认版本' : ''].filter(Boolean).join(' · ');
    return `<span class="pill ${m.state==='confirmed'?'good':['changed','missing','ambiguous'].includes(m.state)?'alert':''}">${esc(label)}</span>${details ? `<small>${esc(details)}</small>` : ''}`;
  }
  function renderMaterials(data) {
    const all = data.materials.filter(m=>m.state!=='confirmed');
    const folders = new Map();
    all.forEach(m=>{const prefix=state.folder ? state.folder+'/' : '';if(!m.path.startsWith(prefix))return;const rest=m.path.slice(prefix.length);const slash=rest.indexOf('/');if(slash>0){const path=prefix+rest.slice(0,slash);folders.set(path,(folders.get(path)||0)+1);}});
    let items = all.filter(m=>{
      if(state.fileQuery) return m.path.toLocaleLowerCase().includes(state.fileQuery.toLocaleLowerCase());
      return state.folder ? m.path.startsWith(state.folder+'/') && m.path.slice(state.folder.length+1).indexOf('/')<0 : !m.path.includes('/');
    }).sort((a,b) => {
      const rank = m => m.state==='confirmed' ? 0 : m.state==='excluded' ? 2 : 1;
      return rank(a)-rank(b) || (a.position||9999)-(b.position||9999) || a.path.localeCompare(b.path,'zh-CN');
    });
    const total = items.length; items=items.slice(0,state.visibleLimit);
    const names = Object.fromEntries(data.checklist.map(item => [item.code,item.name]));
    const rows = items.map(m => `<div class="material-row" data-path="${esc(m.path)}"><label class="select-file"><input type="checkbox" data-select="${esc(m.path)}" ${state.selected.has(m.path)?'checked':''} aria-label="选择 ${esc(m.name)}"></label><div><div class="material-name">${esc(m.name)}</div><div class="material-path">${esc(m.path)}</div><div class="material-path">${materialStatus(m)}${m.item_code ? ` · ${esc(names[m.item_code] || '原分类已删除')}` : ''}</div></div><div class="material-actions"><button class="button small" data-action="preview" type="button">预览</button><button class="button small" data-action="assign" type="button">分类入卷</button><button class="button small ${m.state==='excluded'?'':'warning'}" data-action="exclude" type="button">${m.state==='excluded'?'重新核对':'不入卷'}</button></div></div>`).join('');
    const folderRows = !state.fileQuery ? (state.folder ? `<button type="button" class="folder-row" data-action="folder-up">← 返回上级</button>` : '') + [...folders].sort((a,b)=>a[0].localeCompare(b[0],'zh-CN')).map(([name,count])=>`<button type="button" class="folder-row" data-action="folder" data-folder="${esc(name)}">📁 ${esc(name.split('/').at(-1))} <small>${count} 份</small></button>`).join('') : '';
    return `<section class="panel"><div class="panel-head"><div><h2>案件材料</h2><p class="note">按文件夹浏览或搜索，勾选后批量归档。</p></div><span class="pill">${all.length} 份待选</span></div><div class="material-toolbar"><input id="fileSearch" class="row-input" type="search" placeholder="搜索文件名或路径" aria-label="搜索案件文件"><span class="pill">已选 ${state.selected.size} 份</span><button class="button small primary" data-action="batch-assign" type="button" ${state.selected.size?'':'disabled'}>归档所选文件</button></div><div class="panel-body material-list">${folderRows}${rows || '<p class="note">当前文件夹没有待选文件。</p>'}${total>items.length?`<button class="button load-more" data-action="more" type="button">继续显示（${items.length}/${total}）</button>`:''}</div></section>`;
  }
  function renderExports(data) {
    const rows = (data.exports || []).map(entry => `<div class="export-row"><span>${esc(entry.created_at)}<small class="material-path">${esc(entry.relative_directory)}</small></span><span><a href="/api/case-archive/cases/${state.caseId}/exports/${entry.id}/pdf" download>PDF</a><a href="/api/case-archive/cases/${state.caseId}/exports/${entry.id}/catalog" download>卷内目录</a>${entry.summary_available?`<a href="/api/case-archive/cases/${state.caseId}/exports/${entry.id}/summary" download>办案小结</a>`:''}<a href="/api/case-archive/cases/${state.caseId}/exports/${entry.id}/manifest" download>清单</a></span></div>`).join('');
    return `<section class="panel"><div class="panel-head"><div><h2>导出历史</h2><p class="note">每次生成新版本；可在案件文件夹中查看。</p></div></div><div class="exports">${rows || '<p class="note">尚未生成电子案卷。</p>'}</div></section>`;
  }

  $('categoryChoices').addEventListener('click', event => {
    const code = event.target.closest('[data-category]')?.dataset.category;
    if (!code || !state.data || code === state.data.category) return;
    modal('切换案卷类型', '<p>将改用对应的默认清单。已有材料分类将回到待核对状态；原文件和既有导出版本不受影响。</p>', '切换', async () => {
      const template = await api(`/api/case-archive/templates/${code}`);
      state.data = await send(`/api/case-archive/cases/${state.caseId}/checklist`, 'PUT', {category:code,items:template.items}); render();
    });
  });
  $('workspace').addEventListener('click', async event => {
    const button = event.target.closest('[data-action]'); if (!button || state.busy) return;
    const action = button.dataset.action;
    try {
      if (action === 'edit-checklist') return editChecklist();
      if (action === 'expand') { const code=button.closest('[data-code]').dataset.code; state.expanded.has(code)?state.expanded.delete(code):state.expanded.add(code); return render(); }
      if (action === 'folder') { state.folder=button.dataset.folder; state.visibleLimit=80; return render(); }
      if (action === 'folder-up') { state.folder=state.folder.split('/').slice(0,-1).join('/'); state.visibleLimit=80; return render(); }
      if (action === 'more') { state.visibleLimit+=80; return render(); }
      if (action === 'batch-assign') return showBatchAssignment();
      if (action === 'toggle-na') { const code = button.closest('[data-code]').dataset.code; const items = state.data.checklist.map(i => i.code===code ? {...i,applicability:i.applicability==='na'?'review':'na'} : i); state.data = await send(`/api/case-archive/cases/${state.caseId}/checklist`,'PUT',{category:state.data.category,items}); return render(); }
      const path = button.closest('[data-path]')?.dataset.path;
      const material = state.data.materials.find(m => m.path === path);
      if (!material) return;
      if (action === 'preview') return preview(material);
      if (action === 'assign') return showAssignment(button,material);
      if (action === 'exclude') { state.data = await send(`/api/case-archive/cases/${state.caseId}/materials`,'PUT',{path,state:material.state==='excluded'?'review':'excluded'}); return render(); }
      if (action === 'up' || action === 'down') return reorder(material,action==='up'?-1:1);
    } catch(error) { toast(error.message); }
  });
  $('workspace').addEventListener('input', event=>{if(event.target.id==='fileSearch'){state.fileQuery=event.target.value.trim();state.visibleLimit=80;const caret=event.target.selectionStart;render();$('fileSearch').focus();$('fileSearch').setSelectionRange(caret,caret);}});
  $('workspace').addEventListener('change', event=>{const box=event.target.closest('[data-select]');if(!box)return;box.checked?state.selected.add(box.dataset.select):state.selected.delete(box.dataset.select);const counter=$('workspace').querySelector('.material-toolbar .pill');if(counter)counter.textContent=`已选 ${state.selected.size} 份`;const batch=$('workspace').querySelector('[data-action="batch-assign"]');if(batch)batch.disabled=!state.selected.size;});
  async function preview(material) {
    const info=await send(`/api/case-manager/cases/${state.caseId}/local-files/preview`,'POST',{path:material.path});
    const content=info.preview_kind==='pdf' ? `<iframe class="preview-frame" src="${esc(info.url)}" title="${esc(material.name)}"></iframe>` : info.preview_kind==='image'||info.preview_kind==='html_url' ? `<img class="preview-image" src="${esc(info.url)}" alt="${esc(material.name)}">` : info.preview_kind==='thumbnail' ? `<img class="preview-image" src="${esc(info.data_url)}" alt="${esc(material.name)}">` : info.preview_kind==='html' ? `<div class="preview-text">${info.content || ''}</div>` : info.preview_kind==='text' ? `<pre class="preview-text">${esc(info.content)}</pre>` : '<p>此格式暂不支持内嵌预览，请在案件文件中打开。</p>';
    modal(material.name,content,'关闭',async()=>{});
  }
  function showBatchAssignment() {
    const paths=[...state.selected].filter(path=>state.data.materials.some(m=>m.path===path&&m.state!=='confirmed'));
    if(!paths.length)return;
    const choices=state.data.checklist.filter(item=>item.applicability!=='na'&&!['办案小结','工作小结'].includes(item.name));
    modal(`归档 ${paths.length} 份文件`,`<p>将所选文件归档至：</p><div class="batch-categories">${choices.map((item,index)=>`<label><input type="radio" name="batchCategory" value="${esc(item.code)}" ${index===0?'checked':''}>${esc(item.name)}</label>`).join('')}</div>`,'确认归档',async()=>{const code=$('modalBody').querySelector('input[name="batchCategory"]:checked')?.value;if(!code)throw new Error('请选择归档类别');state.data=await send(`/api/case-archive/cases/${state.caseId}/materials/batch`,'PUT',{paths,item_code:code});paths.forEach(path=>state.selected.delete(path));render();});
  }
  function showAssignment(anchor, material) {
    document.querySelectorAll('.material-options').forEach(el => el.remove());
    const popup = document.createElement('div'); popup.className = 'material-options';
    popup.innerHTML = state.data.checklist.filter(item=>item.applicability!=='na'&&!['办案小结','工作小结'].includes(item.name)).map(item => `<button type="button" data-code="${esc(item.code)}">${esc(item.name)}</button>`).join('');
    document.body.appendChild(popup);
    const rect = anchor.getBoundingClientRect(); popup.style.left = `${Math.min(rect.left,window.innerWidth-popup.offsetWidth-12)}px`; popup.style.top = `${Math.min(rect.bottom+4,window.innerHeight-popup.offsetHeight-12)}px`;
    popup.addEventListener('click', async event => { const code = event.target.closest('[data-code]')?.dataset.code; if (!code) return; popup.remove(); try { state.data = await send(`/api/case-archive/cases/${state.caseId}/materials`,'PUT',{path:material.path,item_code:code,state:'confirmed',position:material.position}); render(); } catch(error){toast(error.message);} });
    const dismiss = event => { if (!popup.contains(event.target) && event.target !== anchor) { popup.remove(); document.removeEventListener('pointerdown',dismiss); } }; setTimeout(()=>document.addEventListener('pointerdown',dismiss),0);
  }
  async function reorder(material,direction) {
    const selected = state.data.materials.filter(m => m.state==='confirmed' && m.item_code===material.item_code).sort((a,b)=>(a.position||9999)-(b.position||9999)||a.path.localeCompare(b.path,'zh-CN'));
    const index = selected.findIndex(m=>m.path===material.path); const target=index+direction; if (target<0||target>=selected.length) return;
    [selected[index],selected[target]]=[selected[target],selected[index]];
    const all = state.data.materials.filter(m=>m.state==='confirmed'&&m.item_code!==material.item_code).sort((a,b)=>(a.position||9999)-(b.position||9999));
    state.data=await send(`/api/case-archive/cases/${state.caseId}/order`,'PUT',{paths:[...all,...selected].map(m=>m.path)}); render();
  }
  function editChecklist() {
    const items = state.data.checklist.map(item=>({...item}));
    function draw() { $('modalBody').innerHTML = `<p>可调整名称与顺序，新增清单项。移除已分类项目后，相关材料须重新分类。</p><div id="editRows">${items.map((item,index)=>`<div class="edit-item" data-index="${index}"><input class="row-input" value="${esc(item.name)}" aria-label="第 ${index+1} 项名称" ${['办案小结','工作小结'].includes(item.name)?'disabled':''}><button class="button small" data-edit="up" type="button" aria-label="上移">↑</button><button class="button small" data-edit="down" type="button" aria-label="下移">↓</button>${['办案小结','工作小结'].includes(item.name)?'':`<button class="button small warning" data-edit="remove" type="button" aria-label="移除">×</button>`}</div>`).join('')}</div><button class="button small" id="addItem" type="button">添加项目</button>`; $('addItem').onclick=()=>{capture();items.push({code:'custom_'+crypto.randomUUID().replace(/-/g,'').slice(0,14),name:'新项目',applicability:'review'});draw();}; $('editRows').onclick=event=>{const control=event.target.closest('[data-edit]');if(!control)return;capture();const i=Number(control.closest('[data-index]').dataset.index);const kind=control.dataset.edit;if(kind==='remove')items.splice(i,1);if(kind==='up'&&i>0)[items[i-1],items[i]]=[items[i],items[i-1]];if(kind==='down'&&i<items.length-1)[items[i+1],items[i]]=[items[i],items[i+1]];draw();}; }
    function capture(){ document.querySelectorAll('#editRows .edit-item').forEach(row=>{items[Number(row.dataset.index)].name=row.querySelector('input').value.trim();}); }
    modal('编辑归档清单','', '保存清单',async()=>{capture();state.data=await send(`/api/case-archive/cases/${state.caseId}/checklist`,'PUT',{category:state.data.category,items});render();}); draw();
  }
  $('exportButton').addEventListener('click', () => {
    if (!state.data?.bound) return;
    const confirmed = state.data.materials.filter(m=>m.state==='confirmed');
    const unresolved = state.data.materials.filter(m=>!['confirmed','excluded'].includes(m.state));
    const missing = state.data.checklist.filter(item=>item.applicability!=='na' && !['办案小结','工作小结'].includes(item.name) && !state.data.counts?.[item.code]);
    const warning = unresolved.length || missing.length ? `<p>仍有 ${unresolved.length} 份材料待核对、${missing.length} 个适用项目尚无已确认材料。它们不会自动入卷。</p>` : '';
    modal('生成电子案卷', `<p>本次将按已确认顺序合并 ${confirmed.length} 份材料，自动生成卷内目录${state.data.category==='criminal'?'':'和办案小结'}并连续编页。原文件不会更改。</p>${warning}`, '生成新版本', async()=>{setBusy(true);try{const result=await send(`/api/case-archive/cases/${state.caseId}/exports`,'POST');toast(`已生成 ${result.pages} 页电子案卷`);await refresh();}finally{setBusy(false);}});
  });
  window.addEventListener('message', event => { if(event.origin===location.origin && event.data?.type==='apex:page-visibility' && event.data.visible===false) { $('caseResults').hidden=true; document.querySelectorAll('.material-options').forEach(el=>el.remove()); } });
  if (state.caseId) refresh(true);
})();
