/* Shared pages keep their business code; capabilities govern platform-only affordances. */
(() => {
  'use strict';
  const ready=fetch('/api/platform-capabilities',{credentials:'same-origin'}).then(r=>{if(!r.ok)throw Error('capabilities');return r.json();});
  window.StellaPlatformReady=ready;
  ready.then(cap=>{
    window.StellaPlatform=cap;
    if(cap.platform!=='windows')return;
    document.documentElement.classList.add('stella-windows');
    const css=document.createElement('style');
    css.textContent=`.stella-windows #tab-recording,.stella-windows #panel-recording,.stella-windows [id*="quark"],.stella-windows [data-mcp-source="quark_drive"],.stella-windows [id*="feishu"],.stella-windows .contact-sync-btn,.stella-windows .contact-detail-sync,.stella-windows .calendar-sync-entry,.stella-windows [data-tab="calendar"],.stella-windows [onclick*="syncContactToICloud"],.stella-windows [onclick*="openJudicialPermissionGuide"],.stella-windows [onclick*="biometric"]{display:none!important}`;
    document.head.append(css);
    const filter=()=>{
      for(const button of document.querySelectorAll('[onclick*="scanJudicialMessages"]')){
        button.setAttribute('onclick','openManualJudicialImport()');
        const label=button.querySelector('.jm-scan-label');if(label)label.textContent='导入短信';
      }
      for(const id of ['jmEnabled','jmInterval','jmBackfill'])document.getElementById(id)?.parentElement?.setAttribute('hidden','');
    };
    new MutationObserver(filter).observe(document.body,{childList:true,subtree:true});filter();
    window.dispatchEvent(new CustomEvent('stella:platform-ready',{detail:cap}));
  }).catch(()=>{});
})();
