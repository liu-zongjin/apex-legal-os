/* Material-first case intake. Suggestions remain a draft until the user applies them. */
function intakeState() {
  if (!state.editing?.isNew) return null;
  return state.editing.intake || (state.editing.intake = { files: [], selected: [], parties: [], questions: [] });
}
function caseIntakeHtml() {
  const intake = intakeState();
  if (!intake) return '';
  const files = intake.files || [];
  const results = intake.result;
  return `<div class="case-intake" id="caseIntakePanel">
    <fieldset class="case-intake-body" ${intake.busy ? 'disabled' : ''}>
    ${intake.folderPath ? `<div class="case-intake-actions"><button class="btn" type="button" onclick="toggleIntakePicker()" aria-expanded="${!!intake.pickerOpen}">${intake.pickerOpen ? '收起材料' : '选择识别材料'}</button><span>已选 ${intake.selected.length} / ${files.length} 个文件（每次最多 100 个）</span></div>
      ${intake.pickerOpen ? `<p class="case-intake-help">展开文件夹，选择其中的文件或整个文件夹。仅所选材料会发送给当前 AI 服务。</p>
      <div class="case-intake-actions"><button class="btn" type="button" onclick="setIntakeSelection(true)">选择全部</button><button class="btn" type="button" onclick="setIntakeSelection(false)">清空选择</button></div>
      <div class="case-intake-files">${files.length ? intakeFileTreeHtml(intake) : '<p>文件夹中没有支持的材料。</p>'}</div>` : ''}` : '<p class="case-intake-help">绑定文件夹后，可选择其中的材料进行 AI 智能识别。</p>'}
    ${intake.ocr?.length ? `<div class="case-intake-notice">以下文件需要云端文字识别：${esc(intake.ocr.join('、'))}。同意后会将相关页面发送至已配置的 OCR 服务。<br><button class="btn" type="button" onclick="recognizeIntake(true)" ${intake.busy ? 'disabled' : ''}>同意并继续识别</button></div>` : ''}
    ${results ? `<div class="case-intake-results"><h4>请核对识别结果</h4><p class="case-intake-help">可直接修改识别内容，再逐项确认；依据保留原识别内容，视觉识别请对照原件核对。同名已有档案保留原有内容，工商查询结果仅补充空白字段。</p>
      ${intake.parties.length ? `<p><strong>您代理哪一方？哪些是对方？</strong> 可分别选择多名当事人。</p>${intake.parties.map((p, i) => `<div class="case-intake-question"><div class="case-intake-edit-grid"><label>当事人名称<input class="input" value="${esc(p.name)}" maxlength="500" oninput="updateIntakeParty(${i},'name',this.value,this)"></label><label>诉讼地位<input class="input" value="${esc(p.role || '')}" maxlength="200" placeholder="可补充或修改" oninput="updateIntakeParty(${i},'role',this.value,this)"></label></div><small>原识别依据：${esc(p.source)}</small><div class="case-intake-actions">${[['client','委托人'],['other','对方'],['','暂不录入']].map(([v,label]) => `<button class="btn ${p.group === v ? 'primary' : ''}" type="button" onclick="setIntakeParty(${i}, '${v}')">${label}</button>`).join('')}<button class="btn" type="button" onclick="setIntakePartyType(${i}, '${p.type === '个人' ? '单位' : '个人'}')">${p.type === '个人' ? '个人' : '单位'} · 切换</button>${p.type !== '个人' ? `<button class="btn" type="button" onclick="lookupIntakeParty(${i})">工商查询</button>` : ''}</div>${p.candidates?.length ? `<div class="case-intake-candidates">${p.candidates.map((c,j) => `<button class="btn" type="button" onclick="selectIntakeCompany(${i},${j})">${esc(c.name)}</button>`).join('')}</div>` : ''}${p.profile ? `<small class="case-intake-profile">已查询：${esc(p.profile.name || p.name)} · ${esc(p.profile.identity_code || '未返回统一社会信用代码')} · ${esc(p.profile.data_source || '工商信息')}。请核对后应用。</small>` : ''}</div>`).join('')}` : ''}
      ${intake.questions.map((q, i) => `<div class="case-intake-question"><strong>${esc(q.question)}</strong><label class="case-intake-value-label">识别内容（可修改）${['court_contact','party_contact','memo'].includes(q.field) ? `<textarea class="input case-intake-value" maxlength="2000" oninput="updateIntakeQuestion(${i},this.value)">${esc(q.value)}</textarea>` : `<input class="input case-intake-value" maxlength="2000" value="${esc(q.value)}" oninput="updateIntakeQuestion(${i},this.value)">`}</label><small>原识别依据：${esc(q.source)}</small><div class="case-intake-actions"><button class="btn ${q.accepted ? 'primary' : ''}" type="button" onclick="setIntakeQuestion(${i},true)">确认填入</button><button class="btn ${!q.accepted ? 'primary' : ''}" type="button" onclick="setIntakeQuestion(${i},false)">暂不填入</button></div></div>`).join('')}
      ${!intake.parties.length && !intake.questions.length ? '<p>没有识别到可确认的信息，请在下方手动填写。</p>' : `<button class="btn primary" type="button" onclick="applyIntake()" ${intake.busy ? 'disabled' : ''}>应用已确认的信息</button>`}</div>` : ''}
    </fieldset>
  </div>`;
}
function intakePathToken(path) { return encodeURIComponent(path).replace(/'/g, '%27'); }
function intakeFileTreeHtml(intake) {
  const root={dirs:new Map(), files:[]}, selected=new Set(intake.selected || []), expanded=new Set(intake.expanded || []);
  (intake.files || []).forEach((path,index) => {
    const parts=path.split('/'), name=parts.pop(); let node=root, prefix='';
    for(const part of parts) { prefix=prefix ? `${prefix}/${part}` : part; if(!node.dirs.has(part)) node.dirs.set(part,{path:prefix,dirs:new Map(),files:[]}); node=node.dirs.get(part); }
    node.files.push({name,path,index});
  });
  function rows(node,depth) {
    const folders=[...node.dirs.entries()].sort((a,b)=>a[0].localeCompare(b[0], 'zh-CN')).map(([name,dir])=>{
      const token=intakePathToken(dir.path), descendants=intake.files.filter(p=>p.startsWith(`${dir.path}/`));
      const count=descendants.filter(p=>selected.has(p)).length, checked=count===descendants.length && count>0, open=expanded.has(dir.path);
      return `<div class="case-intake-tree-row" style="--intake-depth:${Math.min(depth,8)}"><button class="case-intake-tree-expand" type="button" aria-label="${open?'收起':'展开'}文件夹 ${esc(name)}" aria-expanded="${open}" data-intake-expand="${esc(dir.path)}" onclick="toggleIntakeDirectory('${token}')">${open?'▾':'▸'}</button><label class="case-intake-tree-label"><input type="checkbox" data-intake-dir="${esc(dir.path)}" ${checked?'checked':''} onchange="toggleIntakeDirectorySelection('${token}',this.checked)"><span class="case-intake-folder-icon" aria-hidden="true"><svg viewBox="0 0 20 20" fill="none"><path d="M2.5 5.2c0-.9.7-1.6 1.6-1.6h4l1.5 1.7h6.3c.9 0 1.6.7 1.6 1.6v7.8c0 .9-.7 1.6-1.6 1.6H4.1c-.9 0-1.6-.7-1.6-1.6z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg></span><span>${esc(name)}</span></label><small>${count ? `已选 ${count} / ` : ''}${descendants.length} 个文件</small></div>${open ? rows(dir,depth+1) : ''}`;
    }).join('');
    const files=node.files.sort((a,b)=>a.name.localeCompare(b.name, 'zh-CN')).map(item=>`<div class="case-intake-tree-row case-intake-tree-file" style="--intake-depth:${Math.min(depth,8)}"><label class="case-intake-tree-label"><input type="checkbox" data-intake-file-index="${item.index}" ${selected.has(item.path)?'checked':''} onchange="toggleIntakeFile(${item.index},this.checked)"><span>${esc(item.name)}</span></label></div>`).join('');
    return folders+files;
  }
  return rows(root,0);
}
function refreshIntake() {
  const panel=$('caseIntakePanel'); if (panel) panel.outerHTML=caseIntakeHtml();
  const d=intakeState(), start=$('caseIntakeStartBtn');
  if(start && d){start.disabled=!!d.busy; start.textContent=d.busyLabel || 'AI 智能识别';}
  document.querySelectorAll('[data-intake-dir]').forEach(input=>{const prefix=input.dataset.intakeDir+'/';const items=(d?.files||[]).filter(p=>p.startsWith(prefix)), count=items.filter(p=>d.selected.includes(p)).length;input.indeterminate=count>0 && count<items.length;});
}
async function selectIntakeFolder(openPicker=false) {
  const editing=state.editing, d=intakeState(); if (!d || d.busy) return;
  d.busy=true; refreshIntake();
  try {
    const selected = await api('/api/case-manager/intake/folder', {method:'POST'});
    if (selected.cancelled || state.editing !== editing || editing.intake !== d) return;
    editing.intake = {session:selected.session, folderPath:selected.folder_path, files:selected.files || [], selected:[], parties:[], questions:[],pickerOpen:!!openPicker,expanded:[]};
    renderCaseFolderUnboundPanel();
    refreshIntake();
  } catch (e) { if (state.editing === editing) toast(e.message || '选择文件夹失败'); }
  finally { d.busy=false; if (state.editing === editing && editing.intake === d) refreshIntake(); }
}
async function beginIntakeRecognition() {
  const d=intakeState(); if(!d || d.busy) return;
  if(!d.folderPath) return selectIntakeFolder(true);
  if(!d.selected.length) { d.pickerOpen=true; refreshIntake(); return toast('请选择要识别的文件或文件夹'); }
  return recognizeIntake(false);
}
function toggleIntakePicker() { const d=intakeState(); if(!d || d.busy) return; d.pickerOpen=!d.pickerOpen; refreshIntake(); }
function toggleIntakeDirectory(encoded) { const d=intakeState(); if(!d || d.busy) return; const path=decodeURIComponent(encoded), expanded=new Set(d.expanded||[]); expanded.has(path)?expanded.delete(path):expanded.add(path); d.expanded=[...expanded]; refreshIntake(); [...document.querySelectorAll('[data-intake-expand]')].find(el=>el.dataset.intakeExpand===path)?.focus(); }
function toggleIntakeDirectorySelection(encoded, checked) { const d=intakeState(); if(!d || d.busy) return; const prefix=decodeURIComponent(encoded)+'/', paths=d.files.filter(path=>path.startsWith(prefix)), selected=new Set(d.selected); paths.forEach(path=>checked?selected.add(path):selected.delete(path)); d.selected=[...selected]; d.result=null; d.ocr=[]; refreshIntake(); [...document.querySelectorAll('[data-intake-dir]')].find(el=>el.dataset.intakeDir===prefix.slice(0,-1))?.focus(); }
function setIntakeSelection(all) { const d=intakeState(); if (!d || d.busy) return; d.selected=all ? d.files.slice() : []; d.result=null; d.ocr=[]; refreshIntake(); }
function toggleIntakeFile(index, checked) { const d=intakeState(), path=d?.files[index]; if (!path || d.busy) return; d.selected=checked ? [...new Set([...d.selected,path])] : d.selected.filter(p=>p!==path); d.result=null; d.ocr=[]; refreshIntake(); $('caseIntakePanel')?.querySelector(`[data-intake-file-index="${index}"]`)?.focus(); }
async function recognizeIntake(allowCloudOcr) {
  const d=intakeState(); if (d?.busy) return; if (!d?.selected.length) return toast('请先选择材料');
  if (d.selected.length > 100) return toast('一次最多识别 100 个文件，请缩小选择范围');
  d.busy=true; d.busyLabel='正在识别…'; refreshIntake();
  try {
    const result=await api('/api/case-manager/intake/recognize',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session:d.session,paths:d.selected,allow_cloud_ocr:allowCloudOcr})});
    if (state.editing?.intake !== d) return;
    if (result.consent_required?.length) { d.ocr=result.consent_required; d.result=null; }
    else { d.ocr=[]; d.pickerOpen=false; d.result=result; d.parties=(result.parties||[]).map(p=>({...p,group:''})); d.questions=(result.questions||[]).map(q=>({...q,accepted:false})); }
  } catch(e) { if(state.editing?.intake === d) toast(e.message || '识别失败，请重试或手动填写'); }
  finally { d.busy=false; d.busyLabel=''; if (state.editing?.intake === d) refreshIntake(); }
}
function updateIntakeParty(index, field, value, input) {
  const d=intakeState(), p=d?.parties[index]; if(!p || d.busy || !['name','role'].includes(field)) return;
  p[field]=value;
  if(field==='name') { p.profile=null; p.candidates=[]; const row=input?.closest('.case-intake-question'); row?.querySelector('.case-intake-profile')?.remove(); row?.querySelector('.case-intake-candidates')?.remove(); }
}
function updateIntakeQuestion(index, value) { const d=intakeState(), q=d?.questions[index]; if(q && !d.busy) q.value=value; }
function setIntakePartyType(index, type) { const d=intakeState(), p=d?.parties[index]; if(p && !d.busy){p.type=type;p.profile=null;p.candidates=[];refreshIntake();} }
function setIntakeParty(index, group) { const d=intakeState(), p=d?.parties[index]; if(p && !d.busy){p.group=group;refreshIntake();} }
function setIntakeQuestion(index, accepted) { const d=intakeState(), q=d?.questions[index]; if(q && !d.busy){q.accepted=accepted;refreshIntake();} }
async function lookupIntakeParty(index) {
  const d=intakeState(), p=d?.parties[index]; if(!p || d.busy) return;
  d.busy=true; refreshIntake();
  try { const data=await api('/api/case-manager/clients/ai-lookup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'search',name:p.name})});
    if (state.editing?.intake !== d) return;
    p.candidates=(data.candidates||[]).filter(x=>x.name); if(!p.candidates.length) toast('未找到匹配企业');
  } catch(e){if(state.editing?.intake === d) toast(e.message || '工商查询失败');}
  finally { d.busy=false; if(state.editing?.intake === d) refreshIntake(); }
}
async function selectIntakeCompany(index, candidate) {
  const d=intakeState(), p=d?.parties[index], name=p?.candidates?.[candidate]?.name; if(!name || d.busy) return;
  d.busy=true; refreshIntake();
  try { const profile=await api('/api/case-manager/clients/ai-lookup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'profile',name})});
    if(state.editing?.intake !== d) return;
    p.profile=profile; p.name=profile.name || name; p.candidates=[];
  } catch(e){if(state.editing?.intake === d) toast(e.message || '工商信息获取失败');}
  finally { d.busy=false; if(state.editing?.intake === d) refreshIntake(); }
}
async function applyIntake() {
  const d=intakeState(), item=state.editing?.item; if(!d || !item || d.busy) return;
  if (state.editing.inlineSection) return toast('请先保存或取消正在编辑的内容，再应用识别结果');
  const selected=d.parties.filter(p=>p.group);
  if (selected.some(p=>!String(p.name || '').trim())) return toast('请填写已选择当事人的名称');
  if (d.questions.some(q=>q.accepted && !String(q.value || '').trim())) return toast('已确认的信息不能为空，请修改后确认或选择暂不填入');
  selected.forEach(p=>{p.name=String(p.name || '').trim(); p.role=String(p.role || '').trim();});
  d.busy=true; refreshIntake();
  try {
    const profiles=[]; const parties=[];
    for (const p of selected) {
      const kind=p.group==='client'?'clients':'opponents';
      const matches=await api(`/api/case-manager/${kind}?q=${encodeURIComponent(p.name)}&limit=100`);
      if (state.editing?.intake !== d || state.editing?.item !== item) return;
      let existing=(matches.items||[]).find(x=>x.name===p.name);
      if (existing && p.profile) {
        existing=await api(`/api/case-manager/${kind}/${existing.id}`);
        if (state.editing?.intake !== d || state.editing?.item !== item) return;
        if ((existing.client_type || existing.opponent_type) === '个人') throw new Error(`“${p.name}”已有个人档案，请先核对主体类别`);
        if (p.profile.identity_code && existing.identity_code && p.profile.identity_code !== existing.identity_code) throw new Error(`“${p.name}”与已有档案的证件号码不一致，请先核对档案`);
        const merged={...existing}; let changed=false;
        for (const field of ['identity_code','address','legal_representative','registered_capital','establishment_date','registration_status','business_scope','enterprise_nature','industry','region','data_source','source_checked_at']) {
          if (!String(merged[field]||'').trim() && String(p.profile[field]||'').trim()) { merged[field]=p.profile[field]; changed=true; }
        }
        if (changed) existing=await api(`/api/case-manager/${kind}/${existing.id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(merged)});
      }
      if (!existing) {
        const profile={...(p.profile||{}),name:p.name,[p.group==='client'?'client_type':'opponent_type']:p.type==='个人'?'个人':'单位'};
        existing=await api(`/api/case-manager/${kind}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(profile)});
      }
      if (state.editing?.intake !== d || state.editing?.item !== item) return;
      if(p.group==='client') profiles.push(existing);
      parties.push({party_group:p.group,role:p.role || (p.group==='client'?'委托人':'对方当事人'),name:p.name,credit_code:existing.identity_code||''});
    }
    item.client_profiles=[...(item.client_profiles||[]),...profiles.filter(p=>!(item.client_profiles||[]).some(x=>x.name===p.name))];
    for(const party of parties) if(!(item.parties||[]).some(p=>p.party_group===party.party_group&&p.name===party.name)) item.parties.push(party);
    const number={};
    for(const q of d.questions.filter(q=>q.accepted)) {
      if(q.field==='case_no' || q.field==='court') number[q.field]=q.value.trim();
      else item[q.field]=q.value.trim();
    }
    if(Object.keys(number).length) item.case_numbers.push({...number,number_type:item.current_stage||''});
    d.result=null; d.parties=[]; d.questions=[]; state.editing.inlineSection=''; renderOpenCaseDetail();
    toast('已应用确认的信息；请在下方核对并保存案件');
  } catch(e){if(state.editing?.intake === d) toast((e.message || '应用失败') + '；已创建的当事人档案会保留，可重试');}
  finally { d.busy=false; if(state.editing?.intake === d) refreshIntake(); }
}
async function bindIntakeFolder(caseId) {
  const path=state.editing?.intake?.folderPath; if(!path) return;
  await api(`/api/case-manager/cases/${caseId}/folder-binding`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({folder_path:path})});
}
