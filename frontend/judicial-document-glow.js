// Judicial document adaptation of Stella summary generation glow.
function startJudicialDocumentGlow(pane) {
  if (!pane) return { finish: async () => {} };
  const overlay = document.createElement('div');
  overlay.className = 'summary-generation-glow';
  overlay.innerHTML = '<div class="summary-glow-veil"></div><canvas class="summary-glow-canvas" aria-hidden="true"></canvas><div class="summary-glow-status" role="status"><span class="summary-glow-spinner" aria-hidden="true"></span><span class="summary-glow-copy"><span class="summary-glow-old" aria-hidden="true"></span><span class="summary-glow-text">正在读取文书清单…</span></span></div>';
  pane.appendChild(overlay);
  pane.classList.add('summary-generating');
  pane.setAttribute('aria-busy', 'true');
  const canvas = overlay.querySelector('canvas'), ctx = canvas.getContext('2d');
  const haze = document.createElement('canvas'), c = haze.getContext('2d');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const hash = n => { const q = Math.sin(n * 127.1 + 311.7) * 43758.5453; return q - Math.floor(q); };
  const motes = Array.from({length: 240}, (_, i) => ({x: hash(i + 2), phase: hash(i + 20), speed: .16 + hash(i + 600) * .13, size: .25 + Math.pow(hash(i + 100), 3) * 1.5, light: .35 + hash(i + 80) * .6, twinkle: 2 + hash(i + 700) * 4}));
  let frame = 0, start = performance.now(), visible = true, stopped = false;
  function paint(now) {
    frame = 0;
    if (stopped) return;
    if (!document.hidden && visible && ctx && c) {
      const width = pane.clientWidth, height = pane.clientHeight;
      const w = Math.max(1, Math.round(Math.min(650, width * (devicePixelRatio || 1))));
      const h = Math.max(1, Math.round(w * height / Math.max(width, 1)));
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; haze.width = Math.min(320, w); haze.height = Math.max(1, Math.round(haze.width * h / w)); }
      const t = (now - start) / 1000, breath = 1 + .2 * Math.sin(t * 2.2 - .6), base = .99 + .04 * Math.sin(t * 1.55 + 1.7);
      const fw = haze.width, fh = haze.height;
      c.clearRect(0, 0, fw, fh);
      function wash(x, y, rx, ry, color, alpha) {
        c.save(); c.translate(x * fw, y * fh); c.scale(rx * fw, ry * fh * breath);
        const g = c.createRadialGradient(0, 0, 0, 0, 0, 1.6);
        g.addColorStop(0, `rgba(${color},${alpha})`); g.addColorStop(.38, `rgba(${color},${alpha * .7})`); g.addColorStop(1, `rgba(${color},0)`);
        c.fillStyle = g; c.fillRect(-1.6, -1.6, 3.2, 3.2); c.restore();
      }
      wash(.42 + .04 * Math.sin(t * .8), base + .025, .72, .16, [246,104,235], .72);
      wash(.34 + .06 * Math.sin(t * 1.1), base - .035, .39, .21, [255,162,150], .4);
      wash(.13 + .035 * Math.cos(t * 1.5), base + .07, .29, .14, [244,98,235], .62);
      wash(.84 + .035 * Math.sin(t * 1.1), base - .1, .38, .23, [244,112,236], .48);
      wash(.88 + .035 * Math.sin(t * 1.2), base + .025, .2, .075, [199,60,236], .83);
      wash(.51 + .055 * Math.sin(t * .95), base + .09, .35, .16, [248,207,68], .98);
      const colors = [[255,116,217],[255,170,153],[255,214,119],[232,123,241]];
      for (let i=0; i<12; i++) { const life = (t * (.17 + hash(i+70)*.1) + hash(i+30)) % 1; wash(hash(i+12)+Math.sin(life*4+i)*.07, base+.16-life*.36, .1+hash(i+22)*.11, .065+hash(i+52)*.07, colors[i%4], Math.sin(life*Math.PI)*.19); }
      ctx.clearRect(0,0,w,h); ctx.save(); ctx.imageSmoothingQuality = 'high'; ctx.filter = 'blur(1.2px)'; ctx.drawImage(haze,0,0,w,h); ctx.restore();
      for (let i=0; i<motes.length; i++) { const m=motes[i], life=(t*m.speed+m.phase)%1, x=(m.x+Math.sin(t*.9+i)*.012)*w, y=(base+.22-life*.34)*h; ctx.fillStyle=`rgba(255,255,255,${Math.sin(life*Math.PI)*m.light*(.72+.28*Math.sin(t*m.twinkle+i))})`; ctx.beginPath(); ctx.arc(x,y,m.size*w/530,0,Math.PI*2); ctx.fill(); }
    }
    wake();
  }
  function wake() {
    if (!reduced && !stopped && visible && !document.hidden && !frame) frame = requestAnimationFrame(paint);
  }
  const observer = new IntersectionObserver(entries => {
    visible = entries[0].isIntersecting;
    if (!visible && frame) { cancelAnimationFrame(frame); frame = 0; }
    wake();
  });
  const onVisibility = () => {
    if (document.hidden && frame) { cancelAnimationFrame(frame); frame = 0; }
    wake();
  };
  document.addEventListener('visibilitychange', onVisibility);
  observer.observe(pane);
  requestAnimationFrame(() => { if (!stopped) overlay.classList.add('is-visible'); });
  wake();
  function update(label) {
    const old = overlay.querySelector('.summary-glow-old'), current = overlay.querySelector('.summary-glow-text');
    if (!label || current.textContent === label) return;
    old.textContent = current.textContent; old.classList.remove('is-retiring'); current.classList.remove('is-changing');
    current.textContent = label;
    requestAnimationFrame(() => { if (!stopped) { old.classList.add('is-retiring'); current.classList.add('is-changing'); } });
  }
  return { update, async finish() {
    overlay.classList.remove('is-visible'); overlay.classList.add('is-finishing');
    pane.classList.remove('summary-generating');
    if (!reduced && pane.isConnected && !document.hidden) await new Promise(resolve => setTimeout(resolve, 650));
    stopped = true; cancelAnimationFrame(frame); observer.disconnect(); document.removeEventListener('visibilitychange', onVisibility); overlay.remove(); pane.removeAttribute('aria-busy');
  }};
}
