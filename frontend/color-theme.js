(function () {
  'use strict';

  var KEY = 'legal_kb_color_theme';
  var THEMES = ['red', 'blue', 'green', 'indigo', 'amber', 'gray'];
  var SYSTEM_THEME_QUERY = '(prefers-color-scheme: dark)';

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
    var toggle = document.getElementById('theme-toggle');
    if (toggle) {
      toggle.textContent = enabled ? '☾' : '☼';
      toggle.setAttribute('aria-label', enabled ? '切换到白天模式' : '切换到黑夜模式');
    }
  }

  function systemPrefersDark() {
    try {
      return !!(window.matchMedia && window.matchMedia(SYSTEM_THEME_QUERY).matches);
    } catch (e) {
      return false;
    }
  }

  function savedMode() {
    try {
      var value = localStorage.getItem('theme');
      return value === 'dark' || value === 'light' ? value : null;
    } catch (e) {
      return null;
    }
  }

  function currentDarkMode() {
    var mode = savedMode();
    return mode ? mode === 'dark' : systemPrefersDark();
  }

  function read() {
    try {
      return normalize(localStorage.getItem(KEY));
    } catch (e) {
      return 'red';
    }
  }

  apply(read());
  applyMode(currentDarkMode());
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      apply(read());
      applyMode(currentDarkMode());
    });
  }

  window.addEventListener('message', function (event) {
    if (event.data && event.data.type === 'colorTheme') apply(event.data.theme);
    if (event.data && event.data.type === 'theme') applyMode(event.data.dark);
  });

  window.addEventListener('storage', function (event) {
    if (event.key === KEY) apply(event.newValue);
    if (event.key === 'theme') applyMode(currentDarkMode());
  });

  try {
    var channel = new BroadcastChannel('legal-kb-color-theme');
    channel.addEventListener('message', function (event) { apply(event.data); });
    var modeChannel = new BroadcastChannel('legal-kb-theme');
    modeChannel.addEventListener('message', function (event) { applyMode(event.data === 'dark'); });
  } catch (e) { /* ignore */ }

  try {
    var systemThemeMedia = window.matchMedia && window.matchMedia(SYSTEM_THEME_QUERY);
    var onSystemThemeChange = function (event) {
      if (!savedMode()) applyMode(!!event.matches);
    };
    if (systemThemeMedia && systemThemeMedia.addEventListener) {
      systemThemeMedia.addEventListener('change', onSystemThemeChange);
    } else if (systemThemeMedia && systemThemeMedia.addListener) {
      systemThemeMedia.addListener(onSystemThemeChange);
    }
  } catch (e) { /* ignore */ }

  window.applyKnowledgeColorTheme = apply;
  window.apexSystemPrefersDark = systemPrefersDark;
  window.apexCurrentDarkMode = currentDarkMode;
})();
