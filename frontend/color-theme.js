(function () {
  'use strict';

  var KEY = 'legal_kb_color_theme';
  var THEMES = ['red', 'blue', 'green', 'indigo', 'amber', 'gray'];

  function normalize(theme) {
    return THEMES.indexOf(theme) !== -1 ? theme : 'red';
  }

  function apply(theme) {
    theme = normalize(theme);
    document.documentElement.dataset.colorTheme = theme;
    if (document.body) {
      document.body.dataset.colorTheme = theme;
      if (/fada[-_]wang|fada_wang_search/i.test(location.pathname)) {
        document.body.dataset.themeSurface = 'brand';
      }
    }
    return theme;
  }

  function applyMode(dark) {
    var enabled = !!dark;
    document.documentElement.classList.toggle('dark-mode', enabled);
    if (document.body) document.body.classList.toggle('dark-mode', enabled);
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', enabled ? '#0f1724' : '#f5f5f7');
  }

  function read() {
    try {
      return normalize(localStorage.getItem(KEY));
    } catch (e) {
      return 'red';
    }
  }

  apply(read());
  try { applyMode(localStorage.getItem('theme') === 'dark'); } catch (e) { /* ignore */ }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      apply(read());
      try { applyMode(localStorage.getItem('theme') === 'dark'); } catch (e) { /* ignore */ }
    });
  }

  window.addEventListener('message', function (event) {
    if (event.data && event.data.type === 'colorTheme') apply(event.data.theme);
    if (event.data && event.data.type === 'theme') applyMode(event.data.dark);
  });

  window.addEventListener('storage', function (event) {
    if (event.key === KEY) apply(event.newValue);
    if (event.key === 'theme') applyMode(event.newValue === 'dark');
  });

  try {
    var channel = new BroadcastChannel('legal-kb-color-theme');
    channel.addEventListener('message', function (event) { apply(event.data); });
    var modeChannel = new BroadcastChannel('legal-kb-theme');
    modeChannel.addEventListener('message', function (event) { applyMode(event.data === 'dark'); });
  } catch (e) { /* ignore */ }

  window.applyKnowledgeColorTheme = apply;
})();
