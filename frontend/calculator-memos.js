(() => {
  const dialog = document.getElementById('calculator-case-dialog');
  const form = dialog.querySelector('form');
  const search = form.querySelector('input');
  const status = form.querySelector('[role="status"]');
  const confirm = form.querySelector('[type="submit"]');
  const snapshots = new Map();
  const tools = {
    interest: {tab: 'interest', pane: 'interest-tool-pane', result: 'result-section'},
    litigation_arbitration: {tab: 'fee', pane: 'fee-tool-pane', result: 'fee-results'},
    risk_agency: {tab: 'risk', pane: 'risk-fee-tool-pane', result: 'risk-fee-results'},
  };
  let active, selectedCase, trigger, saving = false;
  const picker = ApexCasePicker.attach({
    input: search,
    menu: '#calculator-case-options',
    inline: true,
    onInput() { selectedCase = null; confirm.disabled = true; },
    onSelect(item) {
      selectedCase = item;
      search.value = ApexCasePicker.caseName(item);
      picker.close();
      confirm.disabled = false;
    },
  });

  window.setCalculatorMemoSnapshot = (type, parameters, details) => {
    snapshots.set(type, {type, parameters, details, requestId: crypto.randomUUID()});
    document.getElementById(tools[type].pane).querySelector('.calculator-saved-result')?.remove();
    document.querySelector(`[data-calculator-status="${type}"]`).textContent = '';
  };
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-calculator-link]');
    if (!button) return;
    active = snapshots.get(button.dataset.calculatorLink);
    if (!active) return;
    trigger = button;
    selectedCase = null;
    search.value = status.textContent = '';
    picker.setValue(null);
    confirm.disabled = true;
    dialog.showModal();
    search.focus();
  });
  form.querySelector('[data-close]').addEventListener('click', () => dialog.close());
  dialog.addEventListener('cancel', event => { if (saving) event.preventDefault(); });
  dialog.addEventListener('close', () => { picker.close(); trigger?.focus(); });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!selectedCase || saving || !active) return;
    const caseId = Number(selectedCase.id);
    const name = ApexCasePicker.caseName(selectedCase);
    const close = form.querySelector('[data-close]');
    saving = confirm.disabled = search.disabled = close.disabled = true;
    status.textContent = '正在保存到案件备忘录…';
    try {
      const response = await fetch(`/api/case-research/cases/${caseId}/calculator-memos`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(active),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : '保存失败，请重试');
      document.querySelector(`[data-calculator-status="${active.type}"]`).textContent =
        `${result.existing ? '已关联' : '已保存'} · ${name} / 案件备忘录`;
      if (parent !== window) parent.postMessage({type: 'apex:calculator-memo-saved', version: 1, caseId}, location.origin);
      dialog.close();
    } catch (error) {
      status.textContent = error.message || '保存失败，请重试';
    } finally {
      saving = confirm.disabled = search.disabled = close.disabled = false;
    }
  });

  async function openSavedCalculation() {
    const memo = new URLSearchParams(location.search).get('memo');
    if (!/^\d+$/.test(memo || '')) return;
    const launchStatus = document.getElementById('calculator-launch-status');
    launchStatus.hidden = false;
    launchStatus.textContent = '正在读取已关联的计算结果…';
    try {
      const response = await fetch(`/api/calculator-memos/${memo}`, {cache: 'no-store'});
      const record = await response.json();
      const tool = tools[record.type];
      if (!response.ok || !tool) throw new Error(record.detail || '计算记录无法读取');
      switchToolTab(tool.tab);
      if (record.type === 'interest') restoreInterestInputs(record.parameters);
      else restoreFeeInputs(record.type, record.parameters);
      const card = document.createElement('section');
      card.className = 'card calculator-saved-result';
      const heading = document.createElement('h2');
      heading.className = 'card-title';
      heading.textContent = '案件备忘录中的计算结果';
      const details = document.createElement('pre');
      details.textContent = record.details;
      card.append(heading, details);
      document.getElementById(tool.result).before(card);
      launchStatus.hidden = true;
      card.scrollIntoView({block: 'start'});
    } catch (error) {
      launchStatus.textContent = error.message || '无法读取计算结果，请重试';
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', openSavedCalculation, {once: true});
  else openSavedCalculation();
})();
