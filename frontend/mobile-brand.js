/* Branding is shared across origins/devices; business caches stay untouched. */
(function () {
  const key = 'legal_kb_brand_logo';
  const native = document.documentElement.classList.contains('native-shell');
  let bootPromise;
  let appearanceVersion = 0;
  function stored() {
    try {
      return localStorage.getItem(key) || '';
    } catch (_) {
      return '';
    }
  }
  function remember(logo) {
    try {
      if (logo) localStorage.setItem(key, logo);
      else localStorage.removeItem(key);
    } catch (_) {}
  }
  function apply(logo) {
    const version = ++appearanceVersion;
    const dark =
      document.documentElement.classList.contains('dark-mode') ||
      document.body?.classList.contains('dark-mode') ||
      document.documentElement.dataset.launchTheme === 'dark';
    const source = logo || '/brand-logo.png?v=stella-20261007';
    const images = document.querySelectorAll('[data-mobile-brand]');
    images.forEach((image) => {
      image.src = source;
    });
    if (dark && window.StellaBrandLogo)
      window.StellaBrandLogo.forDark(source, { glow: true })
        .then((value) => {
          if (version === appearanceVersion)
            images.forEach((image) => {
              image.src = value;
            });
        })
        .catch(() => {});
    if (typeof renderBrandLogo === 'function') renderBrandLogo(logo);
  }
  async function read() {
    const response = await fetch('/api/brand', { cache: 'no-store' });
    if (!response.ok) throw new Error('品牌同步暂不可用');
    const value = await response.json();
    let logo = '';
    if (value.custom) {
      const image = await fetch(value.logo_url, { cache: 'no-store' });
      if (!image.ok) throw new Error('品牌图片未能载入');
      const blob = await image.blob();
      logo = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(blob);
      });
    }
    remember(logo);
    document
      .querySelectorAll('link[rel="apple-touch-icon"],link[rel="apple-touch-icon-precomposed"]')
      .forEach((link) => {
        const url = new URL(link.href);
        url.searchParams.set('v', value.revision);
        link.href = url.href;
      });
    const manifest = document.querySelector('link[rel="manifest"]');
    if (manifest) manifest.href = '/manifest.webmanifest?v=' + value.revision;
    apply(logo);
  }
  async function publish(logo) {
    const options = {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ logo })
    };
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    let response;
    try {
      response = await fetch('/api/brand', { ...options, signal: controller.signal });
    } finally {
      clearTimeout(timer);
    }
    if (!response.ok) throw new Error('手机品牌同步失败');
  }
  function bootstrap(logo = stored()) {
    if (bootPromise) return bootPromise;
    apply(logo);
    bootPromise = (native ? publish(logo) : read())
      .catch(() => {})
      .finally(() => {
        bootPromise = null;
      });
    return bootPromise;
  }
  window.StellaMobileBrand = { publish, bootstrap };
  document.addEventListener(
    'DOMContentLoaded',
    () => {
      if (window.parent === window) document.body.classList.add('mobile-brand-standalone');
      bootstrap();
      if (!native) {
        const observer = new MutationObserver(() => apply(stored()));
        observer.observe(document.documentElement, {
          attributes: true,
          attributeFilter: ['class']
        });
        observer.observe(document.body, { attributes: true, attributeFilter: ['class'] });
      }
    },
    { once: true }
  );
  window.addEventListener('online', () => bootstrap());
  document.addEventListener('visibilitychange', () => {
    if (!native && !document.hidden) bootstrap();
  });
})();
