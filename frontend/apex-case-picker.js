(function (global) {
  'use strict';
  const instances = new WeakMap(), live = new Set();
  const SORT_KEY = 'apex.casePicker.sort', RECENT_KEY = 'apex.casePicker.recent';
  const labels = { recent: '常用优先', updated: '最近更新', name: '案件名称', client: '按客户' };
  const collator = new Intl.Collator('zh-CN', { numeric: true });
  let uid = 0;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
  const read = (key, fallback) => { try { return JSON.parse(global.localStorage.getItem(key)) ?? fallback; } catch (_) { return fallback; } };
  const write = (key, value) => { try { global.localStorage.setItem(key, JSON.stringify(value)); } catch (_) {} };
  const recentIds = () => { const value = read(RECENT_KEY, []); return Array.isArray(value) ? value.map(Number).filter(id => Number.isFinite(id) && id > 0).slice(0, 8) : []; };
  const storedSort = () => { const value = read(SORT_KEY, 'recent'); return Object.prototype.hasOwnProperty.call(labels, value) ? value : 'recent'; };
  const clients = item => [...new Set((item.clients || []).map(client => client.name).filter(Boolean))];
  // A series display name can be just its code; the saved case title is the full name.
  const caseName = item => {
    const title = String(item.title || item.case_name || '').trim();
    if (title && title !== String(item.series_code || '').trim()) return title;
    const display = String(item.display_name || item.series_display_name || '').trim();
    const code = String(item.series_code || '').trim();
    return display && display !== code ? [code, display].filter(Boolean).join(' · ') : title || display || code || '未命名案件';
  };
  function flatten(items) {
    const seen = new Set(), rows = [];
    (items || []).forEach(root => {
      [root, ...(root.children || root.series_children || []).map(child => ({ ...child, parentTitle: root.title, parentId: root.id, case_kind: 'series_child', clients: child.clients?.length ? child.clients : root.clients }))].forEach(item => {
        if (!item.id || seen.has(Number(item.id))) return;
        seen.add(Number(item.id)); rows.push(item);
      });
    });
    return rows;
  }
  function sortRows(rows, sort, recent = []) {
    const nameCompare = (a, b) => collator.compare(caseName(a), caseName(b)) || Number(a.id) - Number(b.id);
    const updatedCompare = (a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')) || Number(b.id) - Number(a.id);
    const rank = id => { const index = recent.indexOf(Number(id)); return index < 0 ? Infinity : index; };
    return [...rows].sort((a, b) => {
      if (sort === 'recent') return (rank(a.id) - rank(b.id)) || updatedCompare(a, b);
      if (sort === 'updated') return updatedCompare(a, b);
      return nameCompare(a, b);
    });
  }
  function displayRows(rows, sort, recent = []) {
    const sorted = sortRows(rows, sort, recent);
    if (sort === 'client') {
      const groups = new Map();
      sorted.forEach(item => (clients(item).length ? clients(item) : ['未关联客户']).forEach(name => {
        if (!groups.has(name)) groups.set(name, []);
        groups.get(name).push(item);
      }));
      return [...groups.keys()].sort((a, b) => a === '未关联客户' ? 1 : b === '未关联客户' ? -1 : collator.compare(a, b))
        .flatMap(group => groups.get(group).map(item => ({ item, group })));
    }
    return sorted.map(item => ({ item, group: sort === 'recent' ? (recent.includes(Number(item.id)) ? '最近使用' : '全部在办案件') : '' }));
  }
  function highlight(value, query) {
    const raw = String(value || ''), needle = String(query || '').trim().toLocaleLowerCase();
    if (!needle) return esc(raw);
    const hit = raw.toLocaleLowerCase().indexOf(needle);
    return hit < 0 ? esc(raw) : `${esc(raw.slice(0, hit))}<mark>${esc(raw.slice(hit, hit + needle.length))}</mark>${esc(raw.slice(hit + needle.length))}`;
  }
  async function request(url, { signal } = {}) {
    const response = await global.fetch(url, { credentials: 'same-origin', signal });
    if (!response.ok) throw new Error('案件列表读取失败，请重试');
    return response.json();
  }
  async function load(query = '', options = {}) {
    const result = [], send = options.request || request;
    let offset = 0;
    do {
      if (options.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      const page = await send(`/api/case-manager/case-lookup?q=${encodeURIComponent(query)}&limit=200&offset=${offset}`, { signal: options.signal });
      result.push(...(page.items || []));
      if (!page.has_more) break;
      const next = Number(page.next_offset);
      if (next <= offset || !Number.isFinite(next)) throw new Error('案件列表分页异常，请重试');
      offset = next;
    } while (true);
    return result;
  }
  class CasePicker {
    constructor(options) {
      this.options = options;
      this.input = typeof options.input === 'string' ? document.querySelector(options.input) : options.input;
      this.menu = typeof options.menu === 'string' ? document.querySelector(options.menu) : options.menu;
      if (!this.input || !this.menu) throw new Error('案件选择器缺少输入框或候选容器');
      this.uid = ++uid; this.sequence = 0; this.rows = []; this.visible = 60; this.active = -1;
      this.selected = new Set((Array.isArray(options.value) ? options.value : [options.value]).filter(Boolean).map(Number));
      this.sort = storedSort(); this.recent = recentIds(); this.opened = false;
      this.menu.classList.add('apex-case-picker-menu');
      this.menu.classList.toggle('apex-case-picker-inline', !!options.inline);
      if (!this.menu.id) this.menu.id = `apex-case-picker-${this.uid}`;
      // Old containers retain their IDs, but all presentation is owned here.
      this.menu.removeAttribute('role'); this.menu.hidden = true;
      if (!options.inline) { this.home = this.menu.parentNode; document.body.appendChild(this.menu); }
      this.input.setAttribute('role', 'combobox');
      this.input.setAttribute('aria-autocomplete', 'list');
      this.input.setAttribute('aria-expanded', 'false');
      this.input.setAttribute('aria-controls', `${this.menu.id}-list`);
      this.onFocus = () => this.open(false);
      this.onInput = () => {
        this.cancelRequest(); this.opened = false;
        if (!this.options.inline && this.options.mode !== 'multiple') this.selected.clear();
        this.input.removeAttribute('aria-activedescendant');
        this.display = [];
        if (!this.menu.hidden) this.menu.innerHTML = '<div class="apex-case-picker-state" role="status">正在搜索在办案件…</div>';
        this.options.onInput?.(this.input.value);
        clearTimeout(this.timer); this.timer = setTimeout(() => this.open(true), 180);
      };
      this.onKey = event => this.keyDown(event);
      this.onClick = event => this.click(event);
      this.onPointer = event => { if (event.target.closest('[data-case-index]')) event.preventDefault(); };
      this.input.addEventListener('focus', this.onFocus);
      this.input.addEventListener('click', this.onFocus);
      this.input.addEventListener('input', this.onInput);
      this.input.addEventListener('keydown', this.onKey);
      this.menu.addEventListener('click', this.onClick);
      this.menu.addEventListener('pointerdown', this.onPointer);
      instances.set(this.input, this); live.add(this);
    }
    cancelRequest() { ++this.sequence; this.controller?.abort(); }
    async open(useQuery = false) {
      if (this.destroyed || this.input.disabled) return;
      const query = useQuery || this.options.inline ? this.input.value.trim() : (this.selected.size ? '' : this.input.value.trim());
      if (this.opened && this.query === query) return;
      this.cancelRequest();
      const sequence = this.sequence;
      this.controller = new AbortController(); this.query = query; this.opened = true;
      this.sort = storedSort(); this.recent = recentIds();
      this.menu.hidden = false; this.menu.classList.add('is-open');
      this.input.setAttribute('aria-expanded', 'true');
      this.menu.innerHTML = '<div class="apex-case-picker-state" role="status">正在加载在办案件…</div>';
      this.place();
      try {
        const source = this.options.items
          ? (typeof this.options.items === 'function' ? await this.options.items(query) : this.options.items)
          : await load(query, { request: this.options.request, signal: this.controller.signal });
        if (sequence !== this.sequence || this.destroyed) return;
        this.rows = flatten(Array.isArray(source) ? source : source.items);
        if (this.options.filter) this.rows = this.rows.filter(this.options.filter);
        this.visible = 60; this.active = -1; this.render();
        this.input.dispatchEvent(new CustomEvent('apex:case-open', { bubbles: true, detail: { count: this.rows.length } }));
      } catch (error) {
        if (sequence !== this.sequence || this.destroyed || error.name === 'AbortError') return;
        this.menu.innerHTML = `<div class="apex-case-picker-state" role="status">${esc(error.message)}</div><button type="button" class="apex-case-picker-more" data-case-retry>重新加载</button>`;
        this.place(); this.options.onError?.(error);
      }
    }
    render() {
      this.display = displayRows(this.rows, this.sort, this.recent);
      const selected = this.options.selected ? new Set(this.options.selected()) : this.selected;
      const end = Math.min(this.visible, this.display.length);
      let previousGroup = '';
      const html = this.display.slice(0, end).map(({ item, group }, index) => {
        const heading = group && group !== previousGroup ? `<div class="apex-case-picker-group">${esc(group)}</div>` : '';
        previousGroup = group;
        const title = caseName(item), checked = selected.has(Number(item.id));
        const meta = [item.case_kind === 'series' ? `系列案件 · ${(item.children || item.series_children || []).length} 个子案` : '', item.case_type, item.current_stage,
          (item.case_numbers || []).map(number => number.case_no).filter(Boolean).join('、'), clients(item).join('、')].filter(Boolean).join(' · ');
        return `${heading}<button type="button" id="apex-case-option-${this.uid}-${index}" role="option" aria-selected="${checked}" class="apex-case-picker-option${checked ? ' is-selected' : ''}${index === this.active ? ' is-active' : ''}" data-case-index="${index}"><span class="apex-case-picker-check" aria-hidden="true">${checked ? '✓' : ''}</span><span class="apex-case-picker-content">${item.parentTitle ? `<em>${highlight(item.parentTitle, this.query)} · 系列子案</em>` : ''}<strong>${highlight(title, this.query)}</strong><small>${highlight(meta, this.query) || '暂无补充信息'}</small></span></button>`;
      }).join('');
      this.menu.innerHTML = `<div class="apex-case-picker-head"><div role="group" aria-label="案件浏览方式">${Object.entries(labels).map(([key, label]) => `<button type="button" data-case-sort="${key}" aria-pressed="${key === this.sort}" class="${key === this.sort ? 'is-on' : ''}">${label}</button>`).join('')}</div><span>共 ${this.rows.length} 个在办案件</span></div><div id="${this.menu.id}-list" class="apex-case-picker-list" role="listbox" aria-label="在办案件" aria-multiselectable="${this.options.mode === 'multiple'}">${html || '<div class="apex-case-picker-state" role="status">没有找到匹配的在办案件</div>'}</div><div class="apex-case-picker-foot">已显示 ${end} / ${this.display.length}${this.sort === 'client' ? ' 项（多客户案件分别归类）' : ''}${this.options.allowClear ? `<button type="button" data-case-clear>${esc(this.options.clearLabel || '清除案件')}</button>` : ''}${end < this.display.length ? '<button type="button" data-case-more>显示更多</button>' : ''}</div>`;
      this.syncActive(); this.place();
    }
    click(event) {
      if (event.target.closest('[data-case-clear]')) {
        this.setValue(null); this.options.onClear?.();
        this.input.dispatchEvent(new CustomEvent('apex:case-change', { bubbles: true, detail: { item: null, ids: [] } }));
        return;
      }
      const sort = event.target.closest('[data-case-sort]');
      if (sort) { this.sort = sort.dataset.caseSort; write(SORT_KEY, this.sort); this.visible = 60; this.active = -1; this.render(); return; }
      if (event.target.closest('[data-case-more]')) { this.visible += 60; this.render(); return; }
      if (event.target.closest('[data-case-retry]')) { this.opened = false; this.open(true); return; }
      const button = event.target.closest('[data-case-index]');
      if (!button) return;
      const item = this.display[Number(button.dataset.caseIndex)]?.item;
      if (!item) return;
      const selected = this.options.selected ? new Set(this.options.selected()) : this.selected;
      const id = Number(item.id), checked = !selected.has(id);
      this.selected = selected;
      this.selected = this.options.mode === 'multiple' ? new Set(this.selected) : new Set([id]);
      if (this.options.mode === 'multiple') { if (checked) this.selected.add(id); else this.selected.delete(id); }
      this.recent = [id, ...recentIds().filter(value => value !== id)].slice(0, 8); write(RECENT_KEY, this.recent);
      if (!this.options.inline && this.options.mode !== 'multiple') this.close();
      this.options.onSelect?.(item, checked);
      this.input.dispatchEvent(new CustomEvent('apex:case-change', { bubbles: true, detail: { item, ids: [...this.selected] } }));
      if (this.opened) this.render();
    }
    keyDown(event) {
      if (event.key === 'Escape') { if (this.opened && !this.options.inline) { event.stopPropagation(); this.close(); } return; }
      if (event.key === 'ArrowDown' && !this.opened) { event.preventDefault(); this.open(false); return; }
      if (!this.opened || !this.display?.length) return;
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault(); const count = Math.min(this.visible, this.display.length);
        this.active = this.active < 0 ? (event.key === 'ArrowDown' ? 0 : count - 1) : (this.active + (event.key === 'ArrowDown' ? 1 : -1) + count) % count;
        this.syncActive();
      } else if (event.key === 'Enter' && this.active >= 0) { event.preventDefault(); this.menu.querySelector(`[data-case-index="${this.active}"]`)?.click(); }
    }
    syncActive() {
      this.menu.querySelectorAll('[data-case-index]').forEach(button => button.classList.toggle('is-active', Number(button.dataset.caseIndex) === this.active));
      const active = this.menu.querySelector(`[data-case-index="${this.active}"]`);
      if (active) { this.input.setAttribute('aria-activedescendant', active.id); active.scrollIntoView({ block: 'nearest' }); }
      else this.input.removeAttribute('aria-activedescendant');
    }
    place() {
      if (!this.opened || this.options.inline) return;
      const rect = this.input.getBoundingClientRect(), margin = 8;
      if (!this.input.isConnected || !rect.width || !rect.height) { this.close(); return; }
      const width = Math.min(Math.max(rect.width, 420), global.innerWidth - margin * 2);
      const below = global.innerHeight - rect.bottom - margin, above = rect.top - margin;
      const flip = below < 240 && above > below;
      const height = Math.max(100, Math.min(520, flip ? above : below));
      Object.assign(this.menu.style, { width: `${width}px`, maxHeight: `${height}px`, left: `${Math.max(margin, Math.min(rect.left, global.innerWidth - width - margin))}px` });
      this.menu.style.top = `${flip ? Math.max(margin, rect.top - this.menu.offsetHeight - 4) : rect.bottom + 4}px`;
    }
    setValue(value) { this.selected = new Set((Array.isArray(value) ? value : [value]).filter(Boolean).map(Number)); if (this.opened) this.render(); }
    close() { clearTimeout(this.timer); this.cancelRequest(); this.opened = false; this.menu.hidden = true; this.menu.classList.remove('is-open'); this.input.setAttribute('aria-expanded', 'false'); this.input.removeAttribute('aria-activedescendant'); }
    destroy() {
      if (this.destroyed) return;
      this.close(); this.destroyed = true;
      this.input.removeEventListener('focus', this.onFocus); this.input.removeEventListener('click', this.onFocus); this.input.removeEventListener('input', this.onInput); this.input.removeEventListener('keydown', this.onKey);
      this.menu.removeEventListener('click', this.onClick); this.menu.removeEventListener('pointerdown', this.onPointer);
      if (this.home) this.menu.remove();
      instances.delete(this.input); live.delete(this);
    }
  }
  document.addEventListener('pointerdown', event => live.forEach(picker => { if (!picker.options.inline && !picker.input.contains(event.target) && !picker.menu.contains(event.target)) picker.close(); }));
  document.addEventListener('scroll', event => live.forEach(picker => { if (!picker.menu.contains(event.target)) picker.place(); }), true);
  global.addEventListener('resize', () => live.forEach(picker => picker.place()));
  document.addEventListener('transitionend', () => live.forEach(picker => picker.place()), true);
  global.addEventListener('message', event => { if (event.origin === location.origin && event.data?.type === 'apex:page-visibility' && event.data.visible === false) live.forEach(picker => picker.close()); });
  new MutationObserver(() => live.forEach(picker => { if (!picker.input.isConnected) picker.destroy(); })).observe(document.documentElement, { childList: true, subtree: true });
  global.ApexCasePicker = { attach: options => { const input = typeof options.input === 'string' ? document.querySelector(options.input) : options.input; return instances.get(input) || new CasePicker(options); }, get: input => instances.get(input), closeAll: () => live.forEach(picker => picker.close()), load, flatten, sortRows, displayRows, caseName };
})(window);
