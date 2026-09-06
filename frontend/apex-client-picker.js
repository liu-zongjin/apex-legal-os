(function (global) {
  'use strict';

  const instances = new WeakMap();
  const escapeHTML = value => String(value || '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[char]);

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
      this.selected = names(options.value, this.mode);
      this.activeIndex = -1;
      this.requestVersion = 0;
      this.destroyed = false;
      this.input.placeholder = options.placeholder || this.input.placeholder || '输入或选择委托人';
      this.input.disabled = Boolean(options.disabled);
      this.menu.classList.add('apex-client-picker-menu');
      this.menu.setAttribute('role', 'listbox');
      this.menu.setAttribute('aria-multiselectable', String(this.mode === 'multiple'));
      this.input.setAttribute('role', 'combobox');
      this.input.setAttribute('aria-autocomplete', 'list');
      this.input.setAttribute('aria-expanded', 'false');
      this.onFocus = () => this.open();
      this.onInput = () => { this.options.onInput?.(this.input.value.trim()); this.open(true); };
      this.onKeyDown = event => this.keyDown(event);
      this.onDocumentPointer = event => {
        if (!this.input.contains(event.target) && !this.menu.contains(event.target)) this.close();
      };
      this.input.addEventListener('focus', this.onFocus);
      this.input.addEventListener('click', this.onFocus);
      this.input.addEventListener('input', this.onInput);
      this.input.addEventListener('keydown', this.onKeyDown);
      document.addEventListener('pointerdown', this.onDocumentPointer);
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
        const needle = String(query || '').toLocaleLowerCase();
        this.items = needle ? all.filter(item => `${item.name} ${item.identity_code || ''}`.toLocaleLowerCase().includes(needle)) : all;
        this.activeIndex = this.items.length ? 0 : -1;
        this.render();
      } catch (error) {
        if (requestVersion !== this.requestVersion || this.destroyed) return;
        this.menu.innerHTML = `<div class="apex-client-picker-error">${escapeHTML(error.message || '委托人加载失败')}</div>`;
        this.dispatch('apex:client-error', { error });
        this.options.onError?.(error);
      }
    }

    async open(useQuery = false) {
      if (this.input.disabled || this.destroyed) return;
      this.menu.classList.add('active', 'is-open');
      this.input.setAttribute('aria-expanded', 'true');
      this.dispatch('apex:client-open', { mode: this.mode });
      await this.load(useQuery ? this.input.value.trim() : '');
    }

    close() {
      this.menu.classList.remove('active', 'is-open');
      this.input.setAttribute('aria-expanded', 'false');
      this.activeIndex = -1;
    }

    render() {
      if (!this.items.length) {
        this.menu.innerHTML = '<div class="apex-client-picker-empty">没有找到委托人</div>';
        return;
      }
      this.menu.innerHTML = this.items.slice(0, this.options.maxVisible || 50).map((item, index) => {
        const selected = this.selected.includes(item.name);
        const meta = [item.client_type, item.identity_code].filter(Boolean).join(' · ');
        const check = this.mode === 'multiple' ? `<input type="checkbox" tabindex="-1" ${selected ? 'checked' : ''}>` : '';
        return `<button type="button" class="apex-client-picker-option ${this.mode === 'single' ? 'is-single' : ''} ${index === this.activeIndex ? 'is-active' : ''}" data-index="${index}" role="option" aria-selected="${selected}">${check}<span class="apex-client-picker-option-text"><span class="apex-client-picker-option-name">${escapeHTML(item.name)}</span>${meta ? `<span class="apex-client-picker-option-meta">${escapeHTML(meta)}</span>` : ''}</span></button>`;
      }).join('');
      this.menu.querySelectorAll('[data-index]').forEach(button => button.addEventListener('click', () => this.choose(Number(button.dataset.index))));
    }

    choose(index) {
      const item = this.items[index];
      if (!item) return;
      if (this.mode === 'multiple') {
        this.selected = this.selected.includes(item.name)
          ? this.selected.filter(name => name !== item.name)
          : [...this.selected, item.name];
        this.input.value = '';
        this.render();
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

    keyDown(event) {
      if (event.key === 'Escape') { this.close(); return; }
      if (!this.menu.classList.contains('is-open')) {
        if (event.key === 'ArrowDown') { event.preventDefault(); this.open(true); }
        return;
      }
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        const delta = event.key === 'ArrowDown' ? 1 : -1;
        this.activeIndex = Math.max(0, Math.min(this.items.length - 1, this.activeIndex + delta));
        this.render();
        this.menu.querySelector('.is-active')?.scrollIntoView({ block: 'nearest' });
      } else if (event.key === 'Enter' && this.activeIndex >= 0) {
        event.preventDefault(); this.choose(this.activeIndex);
      }
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
      this.input.removeEventListener('focus', this.onFocus);
      this.input.removeEventListener('click', this.onFocus);
      this.input.removeEventListener('input', this.onInput);
      this.input.removeEventListener('keydown', this.onKeyDown);
      document.removeEventListener('pointerdown', this.onDocumentPointer);
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

