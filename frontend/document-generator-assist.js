/* Shared assistance for document generators. */
(() => {
  const client = document.getElementById('clientInput');
  const number = document.getElementById('caseNumber') || document.getElementById('caseNoInput');
  const party = document.getElementById('partyInput');
  let names = [], request = 0, items = [], timer;
  const recentKey = 'apex:document-case-number-recent';
  const recent = () => { try { return JSON.parse(localStorage.getItem(recentKey) || '[]'); } catch (_) { return []; } };
  if (client && number) {
    const menu = document.createElement('div');
    menu.className = 'document-case-number-menu';
    menu.hidden = true;
    number.insertAdjacentElement('afterend', menu);
    const style = document.createElement('style');
    style.textContent = '.document-case-number-menu{max-height:220px;overflow:auto;margin-top:4px;background:var(--surface,#fff);border:1px solid #ddd;border-radius:10px;box-shadow:0 8px 24px #0002}.document-case-number-menu[hidden]{display:none}.document-case-number-menu button{display:block;width:100%;text-align:left;padding:9px 12px;border:0;background:transparent;color:inherit;cursor:pointer}.document-case-number-menu button:hover,.document-case-number-menu button:focus{background:#8882}';
    document.head.appendChild(style);
    function render() {
      const q = number.value.trim().toLowerCase();
      const matches = items.filter(x => !q || x.case_no.toLowerCase().includes(q));
      menu.replaceChildren();
      for (const item of matches) {
        const button = document.createElement('button'); button.type = 'button';
        button.textContent = [item.case_no, item.number_type, item.court].filter(Boolean).join(' · ');
        button.addEventListener('click', () => {
          number.value = item.case_no;
          const list = [item.case_no, ...recent().filter(x => x !== item.case_no)].slice(0, 100);
          try { localStorage.setItem(recentKey, JSON.stringify(list)); } catch (_) {}
          number.dispatchEvent(new Event('input', {bubbles:true}));
          number.dispatchEvent(new Event('change', {bubbles:true})); menu.hidden = true;
        });
        menu.appendChild(button);
      }
      menu.hidden = !matches.length;
    }
    async function load(values) {
      const current = ++request;
      const unique = [...new Set(values.filter(Boolean))];
      try {
        const responses = await Promise.all(unique.map(n => fetch('/api/case-manager/client-case-numbers?name=' + encodeURIComponent(n))));
        if (responses.some(r => !r.ok)) throw Error('案号加载失败');
        const data = await Promise.all(responses.map(r => r.json()));
        if (current !== request) return;
        const seen = new Set(); items = data.flatMap(x => x.items || []).filter(x => !seen.has(x.case_no) && seen.add(x.case_no));
        const order = recent(); items.sort((a,b) => (order.indexOf(a.case_no) < 0 ? 9999 : order.indexOf(a.case_no)) - (order.indexOf(b.case_no) < 0 ? 9999 : order.indexOf(b.case_no)));
        if (document.activeElement === number) render();
      } catch (e) { if (current === request) { items = []; menu.hidden = true; console.error(e); } }
    }
    client.addEventListener('apex:client-change', e => { clearTimeout(timer); names = Array.isArray(e.detail.value) ? e.detail.value : [e.detail.value]; load(names); });
    client.addEventListener('input', () => { names = [client.value.trim()]; ++request; clearTimeout(timer); timer = setTimeout(() => load(names), 300); });
    number.addEventListener('focus', () => { if (!names.length && client.value.trim()) { names = [client.value.trim()]; load(names); } else render(); });
    number.addEventListener('input', render);
    document.addEventListener('click', e => { if (e.target !== number && !menu.contains(e.target)) menu.hidden = true; });
  }
  if (party) party.addEventListener('keydown', e => {
    if (e.key !== 'Enter' || e.isComposing || e.keyCode === 229) return;
    const values = [...new Set(party.value.split(/[、,，]/).map(x => x.trim()).filter(Boolean))];
    for (const name of values) fetch('/api/case-manager/opponents', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name})}).then(r => {
      if (!r.ok && r.status !== 409) throw Error('保存对方当事人失败');
    }).catch(() => { const notice = document.createElement('div'); notice.textContent = '对方当事人“' + name + '”未能保存，请检查网络后重试'; notice.style.color = '#b33'; party.insertAdjacentElement('afterend', notice); });
  }, true);
})();
