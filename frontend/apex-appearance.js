(() => {
  'use strict';
  const defaults={user_name:'新用户',firm_name:'',firm_logo:'',firm_code:'',firm_address:'',firm_phone:''};
  let profile={...defaults},pendingLogo=null,dirty=false,loadGeneration=0;
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function apply(value) {
    profile={...defaults,...value};window.ApexAppearance.profile=profile;
    try{localStorage.setItem('greeting_username',profile.user_name);}catch{}
    const greeting=document.getElementById('greetingUsername');if(greeting)greeting.textContent=profile.user_name;
    for(const key of Object.keys(defaults)){
      const input=document.getElementById('appearance-'+key);
      if(input && !dirty && document.activeElement!==input)input.value=profile[key];
    }
    const preview=document.getElementById('appearance-logo-preview');
    if(preview && !dirty){preview.hidden=!profile.firm_logo;if(profile.firm_logo)preview.src=profile.firm_logo;else preview.removeAttribute('src');}
    const note=document.getElementById('appearance-document-note');if(note)note.hidden=Boolean(profile.firm_name && profile.firm_logo);
    // The same preview functions and document CSS are used in local/public builds.
    if(document.querySelector('.preview-document')){
      try{window.updatePreview?.();}catch{}
    }
    if(document.getElementById('previewDocument')){try{window.renderPreview?.();}catch{}}
    window.dispatchEvent(new CustomEvent('apex:appearance-changed',{detail:{user_name:profile.user_name}}));
  }
  async function load() {
    const generation=++loadGeneration;
    try{const response=await fetch('/api/appearance',{cache:'no-store'});if(!response.ok)throw new Error();const value=await response.json();if(generation===loadGeneration)apply(value);}
    catch{const status=document.getElementById('appearance-status');if(status)status.textContent='暂时无法读取外观设置，请稍后重试';}
  }
  async function save(changes) {
    ++loadGeneration;
    const response=await fetch('/api/appearance',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(changes)});
    const data=await response.json();if(!response.ok)throw new Error(data.detail || '保存失败');
    ++loadGeneration;apply(data);try{localStorage.setItem('stella.appearance.changed',String(Date.now()));}catch{}return data;
  }
  window.ApexAppearance={profile,escape:esc,save,load};
  for(const input of document.querySelectorAll('.appearance-fields input'))input.addEventListener('input',()=>{dirty=true;});
  const saveButton=document.getElementById('appearance-save');
  saveButton?.addEventListener('click',async()=>{
    saveButton.disabled=true;const status=document.getElementById('appearance-status');
    try{
      const changes={};for(const key of Object.keys(defaults)){const input=document.getElementById('appearance-'+key);if(input)changes[key]=input.value;}
      if(pendingLogo!==null)changes.firm_logo=pendingLogo;
      const saved=await save(changes);pendingLogo=null;dirty=false;apply(saved);status.textContent='已保存，姓名与律所资料已同步至相关页面';
    }catch(error){status.textContent=error.message;}finally{saveButton.disabled=false;}
  });
  document.getElementById('appearance-logo-upload')?.addEventListener('change',async event=>{
    const file=event.target.files?.[0],status=document.getElementById('appearance-status');if(!file)return;
    if(!['image/png','image/webp'].includes(file.type) || file.size>1572864){status.textContent='请上传不超过 1.5 MB 的 PNG 或 WebP';event.target.value='';return;}
    const reader=new FileReader();reader.onload=()=>{pendingLogo=reader.result;dirty=true;const preview=document.getElementById('appearance-logo-preview');preview.src=pendingLogo;preview.hidden=false;status.textContent='Logo 已选中，点击保存后生效';};reader.readAsDataURL(file);
  });
  document.getElementById('appearance-logo-clear')?.addEventListener('click',()=>{pendingLogo='';dirty=true;document.getElementById('appearance-logo-preview').hidden=true;document.getElementById('appearance-status').textContent='点击保存后清空律所 Logo';});
  window.addEventListener('storage',event=>{if(event.key==='stella.appearance.changed')load();});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)load();});
  window.addEventListener('message',event=>{
    if(event.origin!==location.origin || event.data?.type!=='apex:open-appearance-settings')return;
    const frames=[...document.querySelectorAll('iframe')];if(!frames.some(frame=>frame.contentWindow===event.source))return;
    window.openSettingsModal?.('appearance');
  });
  if(new URLSearchParams(location.search).get('settings')==='appearance')window.openSettingsModal?.('appearance');
  load();
})();
