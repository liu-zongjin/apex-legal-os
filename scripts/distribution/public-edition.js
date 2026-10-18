/* Public edition UI. Injected only into the isolated distribution snapshot. */
(() => {
  'use strict';
  const NAME_KEY='greeting_username', VISIBLE_KEY='stella_public_username_visible';
  const CONTACT='https://github.com/liu-zongjin/stella-downloads/issues/new';
  const storage={get(k){try{return localStorage.getItem(k)}catch(_){return null}},set(k,v){try{localStorage.setItem(k,v)}catch(_){}}};
  let firm={firm_name:'律师事务所',logo:''},cropVersion=0;
  const name=()=>String(storage.get(NAME_KEY)||'使用者').slice(0,40);
  function applyIdentity(){
    const visible=storage.get(VISIBLE_KEY)!=='false';
    document.documentElement.classList.toggle('hide-public-username',!visible);
    const user=document.getElementById('greetingUsername');if(user&&user.textContent!==name())user.textContent=name();
    const time=document.getElementById('greetingTimeText');if(time){const text=time.textContent.replace(/[，,\s]+$/,'');time.textContent=text+(visible?'，':'');}
    const toggle=document.getElementById('public-username-visible');if(toggle)toggle.setAttribute('aria-checked',String(visible));
    const input=document.getElementById('public-username');if(input&&document.activeElement!==input)input.value=name();
  }
  function status(text){const el=document.getElementById('public-profile-status');if(el)el.textContent=text;}
  function showCustomization(title='此功能'){
    if(document.getElementById('public-custom-overlay'))return;
    const previous=document.activeElement,overlay=document.createElement('div');overlay.id='public-custom-overlay';overlay.className='public-custom-overlay';
    overlay.innerHTML='<section class="public-custom-dialog" role="dialog" aria-modal="true" aria-labelledby="public-custom-title"><small>STELLA · 定制服务</small><h2 id="public-custom-title">此功能需定制化开发</h2><p class="public-custom-feature"></p><p>请结合您的律所系统与设备环境进行定制。详情请联系作者。</p><div class="actions"><a target="_blank" rel="noopener noreferrer">联系作者 ↗</a><button type="button">知道了</button></div></section>';
    overlay.querySelector('.public-custom-feature').textContent=title;overlay.querySelector('a').href=CONTACT;
    const close=()=>{overlay.remove();previous?.focus()};overlay.querySelector('button').onclick=close;
    overlay.onclick=e=>{if(e.target===overlay)close()};overlay.onkeydown=e=>{if(e.key==='Escape')close();if(e.key==='Tab'){const first=overlay.querySelector('a'),last=overlay.querySelector('button');if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}}};
    document.body.append(overlay);overlay.querySelector('a').focus();
  }
  async function sidebarLogo(){
    const version=++cropVersion,host=document.querySelector('.sidebar-header .logo');if(!host)return;
    let el=document.getElementById('publicSidebarLogo');if(!el){el=new Image();el.id='publicSidebarLogo';el.alt='Stella';host.prepend(el)}
    const raw=storage.get('legal_kb_brand_logo')||'/static/distribution-brand.png';
    const source=(document.body.classList.contains('dark-mode')&&window.StellaBrandLogo)?await window.StellaBrandLogo.forDark(raw,{crop:true,glow:false}):raw;
    const image=new Image();image.src=source;await image.decode().catch(()=>{});if(!image.naturalWidth||version!==cropVersion)return;
    const canvas=document.createElement('canvas');canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;const ctx=canvas.getContext('2d');ctx.drawImage(image,0,0);
    try{const rgba=ctx.getImageData(0,0,canvas.width,canvas.height).data;let l=canvas.width,t=canvas.height,r=-1,b=-1;for(let y=0;y<canvas.height;y++)for(let x=0;x<canvas.width;x++){if(rgba[(y*canvas.width+x)*4+3]>16){l=Math.min(l,x);r=Math.max(r,x);t=Math.min(t,y);b=Math.max(b,y)}}if(r>=l&&b>=t){const out=document.createElement('canvas');out.width=r-l+1;out.height=b-t+1;out.getContext('2d').drawImage(canvas,l,t,out.width,out.height,0,0,out.width,out.height);el.src=out.toDataURL('image/png')}else el.src=source}catch(_){el.src=source}
  }
  function applyFirm(){
    document.querySelectorAll('.preview-document').forEach(preview=>{
      let logo=preview.querySelector('.doc-logo');
      if(!logo&&firm.logo){logo=document.createElement('div');logo.className='doc-logo public-firm-logo-block';logo.append(new Image());preview.prepend(logo)}
      if(logo){logo.hidden=!firm.logo;const image=logo.querySelector('img');if(image&&firm.logo&&image.getAttribute('src')!==firm.logo){image.src=firm.logo;image.alt='律所 Logo';image.style.removeProperty('display')}}
      preview.querySelectorAll('.doc-firm').forEach(el=>{if(el.textContent!==firm.firm_name)el.textContent=firm.firm_name});
      preview.querySelectorAll('.doc-title').forEach(el=>{if(el.dataset.publicFirmTitle==='true'||el.textContent.trim()==='律师事务所函'){el.dataset.publicFirmTitle='true';if(el.textContent!==firm.firm_name+'函')el.textContent=firm.firm_name+'函'}});
    });
    const image=document.getElementById('public-firm-logo-preview');if(image){image.hidden=!firm.logo;if(firm.logo)image.src=firm.logo}
    const input=document.getElementById('public-firm-name');if(input&&document.activeElement!==input)input.value=firm.firm_name;
  }
  async function saveFirm(next){
    status('正在保存…');try{const response=await fetch('/api/public-edition/document-brand',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(next)});const value=await response.json();if(!response.ok)throw Error(value.detail||'保存失败');firm=value;applyFirm();status('已保存；所有文书预览和导出共用此设置。')}catch(e){status(e.message)}
  }
  function firmControls(){
    const card=document.createElement('div');card.className='public-doc-brand';card.id='public-document-brand';
    card.innerHTML='<div class="public-setting"><div><strong>律所名称与文书 Logo</strong><small>仅用于法律文书，与 Stella 的应用品牌分开保存。</small></div><div class="public-setting-actions"><input id="public-firm-name" type="text" maxlength="80" aria-label="律所名称"><button id="public-firm-save" type="button">保存名称</button></div></div><div class="public-setting"><div><strong>律所 Logo</strong><small>PNG、JPG 或 WebP，最大 2 MB；上传即保存。</small></div><div class="public-setting-actions"><img id="public-firm-logo-preview" class="public-logo-preview" alt="当前律所 Logo" hidden><label class="public-upload" tabindex="0">上传律所 Logo<input id="public-firm-logo" type="file" accept="image/png,image/jpeg,image/webp"></label><button id="public-firm-clear" type="button">移除 Logo</button></div></div><p id="public-profile-status" class="public-status" role="status" aria-live="polite"></p>';
    card.querySelector('#public-firm-save').onclick=()=>saveFirm({...firm,firm_name:card.querySelector('#public-firm-name').value});
    card.querySelector('#public-firm-clear').onclick=()=>saveFirm({...firm,logo:''});
    card.querySelector('.public-upload').onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();card.querySelector('input[type=file]').click()}};
    card.querySelector('#public-firm-logo').onchange=async e=>{const file=e.target.files?.[0];e.target.value='';if(!file)return;if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>2*1024*1024){status('请选择不超过 2 MB 的 PNG、JPG 或 WebP 图片');return}const reader=new FileReader();reader.onload=()=>saveFirm({...firm,firm_name:card.querySelector('#public-firm-name').value,logo:reader.result});reader.readAsDataURL(file)};
    return card;
  }
  async function init(){
    document.documentElement.classList.add('public-edition');
    const switchEl=document.getElementById('sidebar-greeting-switch');
    if(switchEl){const row=switchEl.closest('.settings-brand-preference');row.querySelector('small').textContent='默认隐藏；显示时与品牌左对齐，不改变品牌位置。';
      const controls=document.createElement('div');controls.className='public-setting';controls.innerHTML='<div><strong>首页用户名</strong><small>可单独显示或隐藏，也可自行编辑。</small></div><div class="public-setting-actions"><input id="public-username" type="text" maxlength="40" aria-label="用户名"><button id="public-username-save" type="button">保存</button><button id="public-username-visible" class="settings-switch" type="button" role="switch" aria-label="显示用户名"><span class="settings-switch-thumb" aria-hidden="true"></span></button></div>';
      controls.querySelector('#public-username-save').onclick=()=>{storage.set(NAME_KEY,controls.querySelector('input').value.trim()||'使用者');applyIdentity();window.showToast?.('用户名已保存')};
      controls.querySelector('#public-username-visible').onclick=()=>{storage.set(VISIBLE_KEY,String(storage.get(VISIBLE_KEY)==='false'));applyIdentity()};
      controls.querySelector('input').onkeydown=e=>{if(e.key==='Enter')controls.querySelector('#public-username-save').click()};row.after(controls,firmControls());
      document.getElementById('greetingUsername')?.addEventListener('blur',()=>{storage.set(NAME_KEY,name());applyIdentity()});
      const old=window.renderBrandLogo;if(old)window.renderBrandLogo=function(...args){const value=old.apply(this,args);sidebarLogo();return value};
      new MutationObserver(()=>sidebarLogo()).observe(document.body,{attributes:true,attributeFilter:['class']});
      applyIdentity();sidebarLogo();
    }else if(/(?:suohan|power-attorney|rep-identity-cert|business-approval|document-bundle)-generator/.test(location.pathname)){
      const header=document.querySelector('.header');if(header)header.after(firmControls());else document.body.prepend(firmControls());
    }
    document.addEventListener('click',e=>{if(e.target.closest('#chapterUploadButton')){e.preventDefault();e.stopImmediatePropagation();showCustomization('所函一键上传和自动审批')}},true);
    try{const response=await fetch('/api/public-edition/document-brand');if(response.ok){firm=await response.json();applyFirm()}}catch(_){status('律所设置暂时无法读取，请稍后重试。')}
    const preview=document.querySelector('.preview-document');if(preview)new MutationObserver(()=>applyFirm()).observe(preview,{childList:true,subtree:true});
    window.addEventListener('storage',e=>{if([NAME_KEY,VISIBLE_KEY].includes(e.key))applyIdentity()});
  }
  window.StellaPublicEdition={showCustomization};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
