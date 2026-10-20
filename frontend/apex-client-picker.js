(function (global) {
  'use strict';

  const instances = new WeakMap();
  const SORT_STORAGE_KEY = 'apex.clientPicker.sort';
  const RECENT_STORAGE_KEY = 'apex.clientPicker.recent';
  const RECENT_LIMIT = 5;
  const SORTS = ['default', 'name', 'updated'];
  const SORT_LABELS = { default: '常用优先', name: '名称', updated: '最近更新' };
  let uidCounter = 0;

  const escapeHTML = value => String(value || '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[char]);

  const collator = (typeof Intl !== 'undefined' && Intl.Collator)
    ? new Intl.Collator(['zh-Hans-CN', 'zh'], { numeric: true })
    : null;
  const compareName = (a, b) => collator
    ? collator.compare(String(a.name || ''), String(b.name || ''))
    : String(a.name || '').localeCompare(String(b.name || ''), 'zh-Hans-CN');

  const SORTERS = {
    default: null,
    name: list => [...list].sort(compareName),
    updated: list => [...list].sort((a, b) =>
      String(b.updated_at || '').localeCompare(String(a.updated_at || '')) || compareName(a, b)),
  };

  const firstChar = value => {
    const text = String(value || '').trim();
    return text ? [...text][0] : '';
  };

  function highlight(text, needle) {
    const raw = String(text || '');
    const target = String(needle || '').trim().toLocaleLowerCase();
    if (!target) return escapeHTML(raw);
    const lower = raw.toLocaleLowerCase();
    const parts = [];
    let cursor = 0;
    while (cursor <= raw.length) {
      const hit = lower.indexOf(target, cursor);
      if (hit < 0) { parts.push(escapeHTML(raw.slice(cursor))); break; }
      if (hit > cursor) parts.push(escapeHTML(raw.slice(cursor, hit)));
      parts.push(`<mark class="apex-client-picker-mark">${escapeHTML(raw.slice(hit, hit + target.length))}</mark>`);
      cursor = hit + target.length;
    }
    return parts.join('');
  }

  function readStore(key, fallback) {
    try {
      const value = JSON.parse(global.localStorage.getItem(key));
      return value === null || value === undefined ? fallback : value;
    } catch (_) { return fallback; }
  }

  function writeStore(key, value) {
    try { global.localStorage.setItem(key, JSON.stringify(value)); } catch (_) { /* 存储不可用时静默降级 */ }
  }

  function storedSort() {
    const value = readStore(SORT_STORAGE_KEY, 'default');
    return SORTS.includes(value) ? value : 'default';
  }

  function recentNames() {
    const stored = readStore(RECENT_STORAGE_KEY, []);
    return Array.isArray(stored)
      ? stored.filter(name => typeof name === 'string' && name.trim()).slice(0, RECENT_LIMIT)
      : [];
  }

  function rememberRecent(name) {
    writeStore(RECENT_STORAGE_KEY, [name, ...recentNames().filter(item => item !== name)].slice(0, RECENT_LIMIT));
  }

  function names(value, mode) {
    const list = Array.isArray(value) ? value : (value ? [value] : []);
    const cleaned = list.map(item => typeof item === 'string' ? item : item?.name).map(item => String(item || '').trim()).filter(Boolean);
    return mode === 'multiple' ? [...new Set(cleaned)] : cleaned.slice(0, 1);
  }

  class ClientPicker {
    constructor(options) {
      this.input = typeof options.input === 'string' ? document.querySelector(options.input) : options.input;
      this.menu = typeof options.menu === 'string' ? document.querySelector(options.menu) : options.menu;
      if (!this.input || !this.menu) throw new Error('委托人选择器缺少输入框或候选容器');
      this.options = options;
      this.mode = options.mode === 'multiple' ? 'multiple' : 'single';
      this.items = [];
      this.sourceItems = [];
      this.displayItems = [];
      this.recent = [];
      this.selected = names(options.value, this.mode);
      this.activeIndex = -1;
      this.requestVersion = 0;
      this.destroyed = false;
      this.sortBy = options.sortBy || storedSort();
      this.pageSize = Math.max(10, Number(options.pageSize || options.maxVisible) || 60);
      this.visibleCount = this.pageSize;
      this.totalCount = 0;
      this.query = '';
      this.listEl = null;
      this.uid = ++uidCounter;
      this.input.placeholder = options.placeholder || this.input.placeholder || '输入或选择客户';
      this.input.disabled = Boolean(options.disabled);
      this.menu.classList.add('apex-client-picker-menu');
      this.menuHome = this.menu.parentNode;
      document.body.appendChild(this.menu);
      this.onListScroll = event => this.extendOnScroll(event.target);
      this.onListClick = event => {
        const target = event.target.closest('[data-index]');
        if (target && this.menu.contains(target)) this.choose(Number(target.dataset.index));
      };
      this.onReposition = event => {
        if (event?.target?.nodeType && this.menu.contains(event.target)) return;
        if (this.repositionRaf || !this.menu.classList.contains('is-open')) return;
        this.repositionRaf = requestAnimationFrame(() => {
          this.repositionRaf = 0;
          if (!this.destroyed && this.menu.classList.contains('is-open')) this.place();
        });
      };
      this.onFocus = () => this.open();
      this.onInput = () => {
        this.options.onInput?.(this.input.value.trim());
        clearTimeout(this.debounceTimer);
        this.debounceTimer = setTimeout(() => { if (!this.destroyed) this.open(true); }, 180);
      };
      this.onKeyDown = event => this.keyDown(event);
      this.onDocumentPointer = event => {
        if (!this.input.contains(event.target) && !this.menu.contains(event.target)) this.close();
      };
      this.input.addEventListener('focus', this.onFocus);
      this.input.addEventListener('click', this.onFocus);
      this.input.addEventListener('input', this.onInput);
      this.input.addEventListener('keydown', this.onKeyDown);
      document.addEventListener('pointerdown', this.onDocumentPointer);
      document.addEventListener('scroll', this.onReposition, true);
      global.addEventListener('resize', this.onReposition);
      instances.set(this.input, this);
    }

    async load(query) {
      const requestVersion = ++this.requestVersion;
      try {
        const source = this.options.items
          ? (typeof this.options.items === 'function' ? await this.options.items(query) : this.options.items)
          : await global.ApexAPI.searchClients(query, this.options.limit || 2000);
        if (requestVersion !== this.requestVersion || this.destroyed) return;
        const all = global.ApexAPI.uniqueClients(source);
        this.totalCount = all.length;
        const needle = String(query || '').trim().toLocaleLowerCase();
        this.query = needle;
        const pool = needle
          ? all.filter(item => `${item.name} ${item.identity_code || ''}`.toLocaleLowerCase().includes(needle))
          : all;
        this.sourceItems = pool;
        const sorter = SORTERS[this.sortBy];
        this.items = sorter ? sorter(pool) : pool;
        this.recent = needle || this.sortBy !== 'default'
          ? []
          : recentNames().map(name => this.items.find(item => item.name === name)).filter(Boolean);
        this.buildDisplay();
        this.visibleCount = this.pageSize;
        this.activeIndex = this.displayItems.length ? 0 : -1;
        this.render();
      } catch (error) {
        if (requestVersion !== this.requestVersion || this.destroyed) return;
        this.menu.innerHTML = `<div class="apex-client-picker-error">${escapeHTML(error.message || '客户列表加载失败')}</div>`;
        this.dispatch('apex:client-error', { error });
        this.options.onError?.(error);
      }
    }

    buildDisplay() {
      if (!this.recent.length) { this.displayItems = this.items; return; }
      const recentSet = new Set(this.recent.map(item => item.name));
      this.displayItems = [...this.recent, ...this.items.filter(item => !recentSet.has(item.name))];
    }

    async open(useQuery = false) {
      if (this.input.disabled || this.destroyed) return;
      this.menu.classList.add('active', 'is-open');
      this.input.setAttribute('aria-expanded', 'true');
      this.dispatch('apex:client-open', { mode: this.mode });
      this.place();
      if (!this.displayItems.length && !this.query) {
        this.menu.innerHTML = '<div class="apex-client-picker-loading">正在加载客户…</div>';
      }
      await this.load(useQuery ? this.input.value.trim() : '');
    }

    close() {
      this.menu.classList.remove('active', 'is-open');
      this.input.setAttribute('aria-expanded', 'false');
      this.input.removeAttribute('aria-activedescendant');
      this.activeIndex = -1;
    }

    place() {
      if (this.destroyed) return;
      const rect = this.input.getBoundingClientRect();
      const margin = 8;
      const width = Math.max(rect.width, 200);
      const spaceBelow = global.innerHeight - rect.bottom - margin;
      const spaceAbove = rect.top - margin;
      const desired = Math.min(480, Math.max(240, Math.round(global.innerHeight * 0.6)));
      const flip = spaceBelow < Math.min(desired, 280) && spaceAbove > spaceBelow;
      const height = Math.max(200, Math.min(desired, flip ? spaceAbove : spaceBelow));
      this.menu.style.width = `${width}px`;
      this.menu.style.maxHeight = `${height}px`;
      this.menu.style.left = `${Math.max(margin, Math.min(rect.left, global.innerWidth - width - margin))}px`;
      const measured = this.menu.offsetHeight || height;
      this.menu.style.top = `${flip ? Math.max(margin, rect.top - measured - 4) : rect.bottom + 4}px`;
    }

    optionId(index) { return `apex-client-option-${this.uid}-${index}`; }

    render() {
      const buttons = SORTS.map(sort =>
        `<button type="button" class="apex-client-picker-sort${sort === this.sortBy ? ' is-on' : ''}" data-sort="${sort}" aria-pressed="${sort === this.sortBy}">${SORT_LABELS[sort]}</button>`
      ).join('');
      this.menu.innerHTML = `
        <div class="apex-client-picker-head">
          <div class="apex-client-picker-sort-group" role="group" aria-label="排序方式">${buttons}</div>
          <span class="apex-client-picker-total">共 ${this.totalCount} 位客户</span>
        </div>
        <div class="apex-client-picker-list" role="listbox" aria-multiselectable="${this.mode === 'multiple'}" aria-label="客户候选列表">${this.listHTML()}</div>
        ${this.footHTML()}`;
      this.listEl = this.menu.querySelector('.apex-client-picker-list');
      this.listEl.addEventListener('scroll', this.onListScroll);
      this.listEl.addEventListener('click', this.onListClick);
      this.menu.querySelectorAll('[data-sort]').forEach(button => {
        button.addEventListener('click', () => this.setSort(button.dataset.sort));
      });
      this.syncActiveDescendant();
      this.place();
    }

    listHTML() {
      if (!this.displayItems.length) {
        return `<div class="apex-client-picker-empty">${this.query ? '没有找到匹配的客户，可更换关键词或排序方式' : '还没有可选客户'}</div>`;
      }
      return this.sliceHTML(0, Math.min(this.visibleCount, this.displayItems.length));
    }

    sliceHTML(start, end) {
      const groupMode = !this.query && this.sortBy === 'name';
      const recentMode = this.recent.length > 0;
      let lastChar = groupMode && start > 0 ? (firstChar(this.displayItems[start - 1].name) || '#') : null;
      let html = '';
      for (let index = start; index < end; index++) {
        if (recentMode && index === 0) html += '<div class="apex-client-picker-group-label is-recent">最近使用</div>';
        if (recentMode && index === this.recent.length) html += '<div class="apex-client-picker-group-label">全部客户</div>';
        if (groupMode) {
          const char = firstChar(this.displayItems[index].name) || '#';
          if (char !== lastChar) {
            html += `<div class="apex-client-picker-group-label">${escapeHTML(char)}</div>`;
            lastChar = char;
          }
        }
        html += this.optionHTML(index);
      }
      return html;
    }

    optionHTML(index) {
      const item = this.displayItems[index];
      const selected = this.selected.includes(item.name);
      const meta = [item.client_type, item.identity_code].filter(Boolean).join(' · ');
      const check = this.mode === 'multiple'
        ? `<span class="apex-client-picker-check${selected ? ' is-checked' : ''}" aria-hidden="true"></span>`
        : '';
      const tick = this.mode === 'single' && selected ? '<span class="apex-client-picker-tick" aria-hidden="true"></span>' : '';
      const classes = ['apex-client-picker-option'];
      if (this.mode === 'single') classes.push('is-single');
      if (selected) classes.push('is-selected');
      if (index === this.activeIndex) classes.push('is-active');
      return `<div class="${classes.join(' ')}" id="${this.optionId(index)}" data-index="${index}" role="option" aria-selected="${selected}">${check}<span class="apex-client-picker-badge" aria-hidden="true">${escapeHTML(firstChar(item.name) || '客')}</span><span class="apex-client-picker-option-text"><span class="apex-client-picker-option-name">${highlight(item.name, this.query)}</span>${meta ? `<span class="apex-client-picker-option-meta">${highlight(meta, this.query)}</span>` : ''}</span>${tick}</div>`;
    }

    footHTML() {
      if (!this.displayItems.length) return '';
      const shown = Math.min(this.visibleCount, this.displayItems.length);
      const cap = Math.min(Number(this.options.limit) || 2000, 2000);
      const capped = !this.query && this.totalCount >= cap;
      return `<div class="apex-client-picker-foot"><span>已显示 <b>${shown}</b> / ${this.displayItems.length}</span>${capped ? '<span class="apex-client-picker-foot-hint">已达单次加载上限，可输入关键词缩小范围</span>' : ''}</div>`;
    }

    updateFoot() {
      const foot = this.menu.querySelector('.apex-client-picker-foot');
      if (foot) foot.outerHTML = this.footHTML();
    }

    refreshList() {
      if (!this.listEl) { this.render(); return; }
      const scrollTop = this.listEl.scrollTop;
      this.listEl.innerHTML = this.listHTML();
      this.updateFoot();
      this.listEl.scrollTop = scrollTop;
      this.syncActiveDescendant();
    }

    syncActiveDescendant() {
      if (this.activeIndex >= 0) this.input.setAttribute('aria-activedescendant', this.optionId(this.activeIndex));
      else this.input.removeAttribute('aria-activedescendant');
    }

    extendOnScroll(list) {
      if (!list || this.visibleCount >= this.displayItems.length) return;
      if (list.scrollTop + list.clientHeight < list.scrollHeight - 48) return;
      const start = this.visibleCount;
      this.visibleCount = Math.min(this.displayItems.length, start + this.pageSize);
      list.insertAdjacentHTML('beforeend', this.sliceHTML(start, this.visibleCount));
      this.updateFoot();
    }

    extendTo(index) {
      if (index < this.visibleCount) return;
      const start = this.visibleCount;
      this.visibleCount = Math.min(this.displayItems.length, index + 1);
      this.listEl?.insertAdjacentHTML('beforeend', this.sliceHTML(start, this.visibleCount));
      this.updateFoot();
    }

    choose(index) {
      const item = this.displayItems[index];
      if (!item) return;
      rememberRecent(item.name);
      if (this.mode === 'multiple') {
        this.selected = this.selected.includes(item.name)
          ? this.selected.filter(name => name !== item.name)
          : [...this.selected, item.name];
        this.input.value = '';
        this.refreshList();
      } else {
        this.selected = [item.name];
        this.input.value = item.name;
        this.close();
      }
      const value = this.mode === 'multiple' ? this.selected.slice() : (this.selected[0] || '');
      this.options.onChange?.(value, item);
      this.options.onSelect?.(item, value);
      this.dispatch('apex:client-change', { value, item, mode: this.mode });
    }

    setSort(sortBy) {
      if (!SORTS.includes(sortBy) || sortBy === this.sortBy) return;
      this.sortBy = sortBy;
      writeStore(SORT_STORAGE_KEY, sortBy);
      const sorter = SORTERS[sortBy];
      this.items = sorter ? sorter(this.sourceItems) : this.sourceItems.slice();
      this.recent = sortBy === 'default' && !this.query
        ? recentNames().map(name => this.items.find(item => item.name === name)).filter(Boolean)
        : [];
      this.buildDisplay();
      this.visibleCount = this.pageSize;
      this.activeIndex = this.displayItems.length ? 0 : -1;
      this.render();
      this.dispatch('apex:client-sort', { sortBy });
    }

    move(delta) {
      if (!this.displayItems.length) return;
      const next = Math.max(0, Math.min(this.displayItems.length - 1, this.activeIndex + delta));
      if (next === this.activeIndex) return;
      this.activeIndex = next;
      this.extendTo(next);
      this.refreshActive();
    }

    jump(index) {
      if (!this.displayItems.length) return;
      this.activeIndex = Math.max(0, Math.min(this.displayItems.length - 1, index));
      this.extendTo(this.activeIndex);
      this.refreshActive();
    }

    refreshActive() {
      this.listEl?.querySelector('.is-active')?.classList.remove('is-active');
      const active = this.listEl?.querySelector(`[data-index="${this.activeIndex}"]`);
      if (active) {
        active.classList.add('is-active');
        active.scrollIntoView({ block: 'nearest' });
      }
      this.syncActiveDescendant();
    }

    keyDown(event) {
      if (event.key === 'Escape') { this.close(); return; }
      if (!this.menu.classList.contains('is-open')) {
        if (event.key === 'ArrowDown') { event.preventDefault(); this.open(true); }
        return;
      }
      if (event.key === 'ArrowDown') { event.preventDefault(); this.move(1); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); this.move(-1); }
      else if (event.key === 'PageDown') { event.preventDefault(); this.move(10); }
      else if (event.key === 'PageUp') { event.preventDefault(); this.move(-10); }
      else if (event.key === 'Home') { event.preventDefault(); this.jump(0); }
      else if (event.key === 'End') { event.preventDefault(); this.jump(this.displayItems.length - 1); }
      else if (event.key === 'Enter' && this.activeIndex >= 0) { event.preventDefault(); this.choose(this.activeIndex); }
    }

    setValue(value) {
      this.selected = names(value, this.mode);
      if (this.mode === 'single') this.input.value = this.selected[0] || '';
      this.render();
    }

    setDisabled(disabled) { this.input.disabled = Boolean(disabled); if (disabled) this.close(); }

    dispatch(type, detail) {
      this.input.dispatchEvent(new CustomEvent(type, { bubbles: true, detail }));
    }

    destroy() {
      this.destroyed = true;
      this.requestVersion += 1;
      clearTimeout(this.debounceTimer);
      if (this.repositionRaf) { cancelAnimationFrame(this.repositionRaf); this.repositionRaf = 0; }
      this.input.removeEventListener('focus', this.onFocus);
      this.input.removeEventListener('click', this.onFocus);
      this.input.removeEventListener('input', this.onInput);
      this.input.removeEventListener('keydown', this.onKeyDown);
      document.removeEventListener('pointerdown', this.onDocumentPointer);
      document.removeEventListener('scroll', this.onReposition, true);
      global.removeEventListener('resize', this.onReposition);
      this.menu.remove();
      if (this.menuHome && this.menuHome.isConnected) this.menuHome.appendChild(this.menu);
      instances.delete(this.input);
    }
  }

  global.ApexClientPicker = Object.freeze({
    attach(options) {
      const input = typeof options.input === 'string' ? document.querySelector(options.input) : options.input;
      instances.get(input)?.destroy();
      return new ClientPicker(options);
    },
    forInput(input) { return instances.get(typeof input === 'string' ? document.querySelector(input) : input) || null; },
  });
})(window);
