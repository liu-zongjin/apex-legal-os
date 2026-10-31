/* ─────────────────────────────────────────────
   会议录音 · 实时转写工作台（独立标签页）
   配合 backend/recording_routes.py 使用
────────────────────────────────────────────── */

(function () {
  'use strict';

  const FRAME_SAMPLES = 640;          // 40ms @ 16k（1280 字节/帧）
  const TARGET_RATE = 16000;

  const recState = {
    mode: 'history',
    recordingId: null,
    ws: null,
    audioCtx: null,
    processor: null,
    micStream: null,
    recording: false,
    elapsedMs: 0,
    timerHandle: null,
    pollHandle: null,
    segments: [],          // [{start, end, text}]
    partialSegment: null,  // 火山引擎当前尚未定稿的一句话
    segmentEls: [],
    currentRecording: null,
    playerLoadedId: null,
    playing: false,
    autoFollow: true,
    inited: false,
  };

  const $ = (id) => document.getElementById(id);

  /* ── 基础工具（独立页面不依赖 app.js） ────── */

  function fmtTime(ms) {
    const total = Math.max(0, Math.floor((ms || 0) / 1000));
    const m = String(Math.floor(total / 60)).padStart(2, '0');
    const s = String(total % 60).padStart(2, '0');
    return `${m}:${s}`;
  }

  function escapeHtml(str) {
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  async function apiFetch(path, options = {}) {
    const res = await fetch(path, options);
    if (!res.ok) {
      let message = res.statusText;
      try {
        const err = await res.json();
        if (typeof err.detail === 'string') message = err.detail;
        else if (err.detail) message = JSON.stringify(err.detail);
        else if (err.message) message = err.message;
      } catch (e) { /* 保留默认消息 */ }
      throw new Error(message);
    }
    return res.json();
  }

  let toastTimer = null;
  function showToast(message, type = 'success') {
    const toast = $('recording-toast');
    if (!toast) return;
    toast.textContent = message;
    toast.className = `recording-toast ${type === 'error' ? 'error' : ''}`;
    toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('show'), 3600);
  }

  /* ── 模式切换 ─────────────────────────────── */

  window.recordingSetMode = function (mode) {
    recState.mode = mode;
    document.querySelectorAll('.recording-mode-btn').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.mode === mode);
    });
    document.querySelectorAll('.recording-mode-pane').forEach((pane) => {
      pane.classList.toggle('active', pane.id === `recording-pane-${mode}`);
    });
    if (mode === 'history') recordingLoadHistory();
  };

  /* ── 语音识别凭据（火山引擎 / 讯飞备用） ────── */

  async function recordingLoadConfigStatus() {
    try {
      const data = await apiFetch('/api/recordings/asr-config');
      const status = $('recording-config-status');
      if (status) {
        if (data.configured) {
          status.textContent = `已配置：${data.backend}`;
          status.style.color = 'var(--success)';
        } else {
          status.textContent = '尚未配置语音识别凭据：请在火山引擎语音技术控制台开通「语音识别大模型」并填写 APP Key';
          status.style.color = 'var(--danger)';
        }
      }
      const keyInput = $('recording-volc-apikey');
      if (keyInput && !keyInput.value && data.volcengine) {
        if (data.volcengine.api_key_masked) {
          keyInput.placeholder = `已保存：${data.volcengine.api_key_masked}（留空不改）`;
        } else if (data.volcengine.app_id_masked) {
          keyInput.placeholder = `旧版凭据已保存：APP ID ${data.volcengine.app_id_masked}`;
        }
      }
      const resourceInput = $('recording-volc-resource');
      if (resourceInput && !resourceInput.value && data.volcengine) {
        resourceInput.placeholder = `默认 ${data.volcengine.resource_id || 'volc.bigasr.sauc.duration'}`;
      }
    } catch (e) { /* 静默 */ }
  }

  function recordingToggleConfig() {
    const panel = $('recording-config-panel');
    panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
    if (panel.style.display === 'block') recordingLoadConfigStatus();
  }
  window.recordingToggleConfig = recordingToggleConfig;

  window.recordingSaveAsrConfig = async function () {
    const apikey = $('recording-volc-apikey').value.trim();
    const resource = $('recording-volc-resource').value.trim();
    const appid = $('recording-volc-appid').value.trim();
    const token = $('recording-volc-token').value.trim();
    const iflyAppid = $('recording-iflytek-appid').value.trim();
    const iflyKey = $('recording-iflytek-apikey').value.trim();
    const iflySecret = $('recording-iflytek-apisecret').value.trim();
    if (!apikey && !(appid && token) && !iflyAppid) {
      showToast('请填写火山引擎 APP Key（或旧版 APP ID + Access Token）', 'error');
      return;
    }
    try {
      const result = await apiFetch('/api/recordings/asr-config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          VOLCENGINE_ASR_API_KEY: apikey,
          VOLCENGINE_ASR_RESOURCE_ID: resource,
          VOLCENGINE_ASR_APP_ID: appid,
          VOLCENGINE_ASR_ACCESS_TOKEN: token,
          IFLYTEK_APP_ID: iflyAppid,
          IFLYTEK_API_KEY: iflyKey,
          IFLYTEK_API_SECRET: iflySecret,
        }),
      });
      if (result.ok && result.configured) {
        showToast(`凭据已保存，当前使用：${result.backend}`);
        ['recording-volc-apikey', 'recording-volc-resource', 'recording-volc-appid',
         'recording-volc-token', 'recording-iflytek-appid', 'recording-iflytek-apikey',
         'recording-iflytek-apisecret'].forEach((id) => { $(id).value = ''; });
        recordingLoadConfigStatus();
      } else {
        showToast('保存失败，请检查凭据是否正确', 'error');
      }
    } catch (e) {
      showToast(`保存失败：${e.message}`, 'error');
    }
  };

  /* ── 实时录音 ─────────────────────────────── */

  window.recordingToggle = function () {
    if (recState.recording) recordingStop();
    else recordingStart();
  };

  async function recordingStart() {
    const title = ($('recording-title-input').value || '').trim();
    try {
      const res = await apiFetch('/api/recordings/live/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: title || '未命名会议录音' }),
      });
      recState.recordingId = res.id;
    } catch (e) {
      if (/语音识别|火山|讯飞|凭据/.test(e.message)) {
        showToast(e.message, 'error');
        recordingToggleConfig();
        const panel = $('recording-config-panel');
        if (panel) panel.style.display = 'block';
        return;
      }
      showToast(`无法开始录音：${e.message}`, 'error');
      return;
    }

    if (!window.isSecureContext) {
      showToast('当前为非安全连接（需 HTTPS 或本机 localhost），浏览器已禁用麦克风。请在本机浏览器打开 http://localhost:8000 使用录音，或改用「上传音频」', 'error');
      return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      const isNativeShell = /LegalKB-NativeShell/.test(navigator.userAgent || '');
      if (isNativeShell) {
        showToast('当前 Stella 应用壳不支持麦克风。请退出并重新打开最新版 Stella（或改用「上传音频」）', 'error');
      } else {
        showToast('当前浏览器不支持麦克风录音，请使用最新版 Chrome、Edge 或 Safari，或改用「上传音频」', 'error');
      }
      return;
    }
    try {
      recState.micStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch (e) {
      if (e && (e.name === 'NotAllowedError' || e.name === 'SecurityError')) {
        const isNativeShell = /LegalKB-NativeShell/.test(navigator.userAgent || '');
        if (isNativeShell) {
          showToast('麦克风未授权：请完全退出 Stella 后重新打开（首次录音时在系统弹窗中点击“允许”），或改用「上传音频」', 'error');
        } else {
          showToast('麦克风权限被拒绝：请在浏览器地址栏左侧点击“网站设置”，允许麦克风访问后重试', 'error');
        }
      } else if (e && e.name === 'NotFoundError') {
        showToast('未检测到麦克风设备，请检查输入设备连接后重试', 'error');
      } else {
        showToast(`无法访问麦克风（${(e && e.name) || '未知错误'}），可改用「上传音频」`, 'error');
      }
      return;
    }

    // 建立实时转写连接
    const proto = location.protocol === 'https:' ? 'wss://' : 'ws://';
    recState.ws = new WebSocket(`${proto}${location.host}/ws/recordings/live/${recState.recordingId}`);
    recState.ws.binaryType = 'arraybuffer';
    recState.ws.onmessage = onLiveMessage;
    recState.ws.onerror = () => showToast('实时转写连接异常', 'error');
    recState.ws.onclose = () => {
      if (recState.recording) showToast('实时转写连接已断开（录音仍在继续，转写将中止）', 'error');
    };

    // 音频处理管线
    recState.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    recState.processor = recState.audioCtx.createScriptProcessor(4096, 1, 1);
    const source = recState.audioCtx.createMediaStreamSource(recState.micStream);
    source.connect(recState.processor);
    recState.processor.connect(recState.audioCtx.destination);
    recState.pending = new Int16Array(0);
    recState.elapsedMs = 0;

    const inputRate = recState.audioCtx.sampleRate;
    recState.processor.onaudioprocess = (event) => {
      if (!recState.recording) return;
      const buffer = event.inputBuffer.getChannelData(0);
      const down = downsample(buffer, inputRate, TARGET_RATE);
      recState.pending = concatInt16(recState.pending, down);
      const frames = Math.floor(recState.pending.length / FRAME_SAMPLES);
      if (frames > 0) {
        const usable = frames * FRAME_SAMPLES;
        const sendBuf = recState.pending.slice(0, usable);
        recState.pending = recState.pending.slice(usable);
        recState.elapsedMs += (usable / TARGET_RATE) * 1000;
        if (recState.ws && recState.ws.readyState === WebSocket.OPEN) {
          recState.ws.send(sendBuf.buffer);
        }
      }
    };

    recState.recording = true;
    resetResultView();
    $('recording-segments').innerHTML = '';
    $('recording-segments-empty').style.display = 'block';
    $('recording-result').style.display = 'block';
    $('recording-result').classList.add('is-live');
    setRecordButton(true);
    recState.timerHandle = (window.ApexLifecycle?.interval || window.setInterval)(() => {
      $('recording-timer').textContent = fmtTime(recState.elapsedMs);
    }, 500);
  }

  function onLiveMessage(event) {
    let msg;
    try { msg = JSON.parse(event.data); } catch (e) { return; }
    if (msg.type === 'segment') {
      const segment = { start: msg.start, end: msg.end, text: msg.text, definite: !!msg.definite };
      if (segment.definite) {
        const existing = recState.segments.findIndex((item) => Math.abs(Number(item.start) - Number(segment.start)) < 0.35);
        if (existing >= 0) recState.segments[existing] = segment;
        else recState.segments.push(segment);
        recState.segments.sort((a, b) => Number(a.start) - Number(b.start));
        recState.partialSegment = null;
      } else {
        // 临时结果始终只占一个预览行；后续修订直接替换，不进入正式分段。
        recState.partialSegment = segment;
      }
      renderSegments(recState.partialSegment ? [...recState.segments, recState.partialSegment] : recState.segments);
      $('recording-live-badge').hidden = false;
    } else if (msg.type === 'error') {
      showToast(msg.message || '转写服务错误', 'error');
    } else if (msg.type === 'status' && msg.message) {
      showToast(msg.message, /错误|失败|中断/.test(msg.message) ? 'error' : 'success');
    }
  }

  async function recordingStop() {
    if (!recState.recording) return;
    recState.recording = false;
    setRecordButton(false);
    $('recording-result').classList.remove('is-live');
    clearInterval(recState.timerHandle);

    // 停止音频管线
    try {
      recState.processor && recState.processor.disconnect();
      recState.audioCtx && recState.audioCtx.close();
      recState.micStream && recState.micStream.getTracks().forEach((t) => t.stop());
    } catch (e) { /* 忽略 */ }
    recState.processor = null;
    recState.audioCtx = null;
    recState.micStream = null;

    // 通知服务端结束
    if (recState.ws) {
      try {
        if (recState.ws.readyState === WebSocket.OPEN) recState.ws.send('end');
      } catch (e) { /* 忽略 */ }
    }

    showToast('录音已结束，正在生成 AI 规整与纪要…');
    const id = recState.recordingId;
    showResultView(recState.segments);
    recState.segments = [];
    recState.partialSegment = null;
    startPolling(id);
  }

  function setRecordButton(active) {
    const btn = $('recording-btn');
    const label = $('recording-btn-label');
    const badge = $('recording-live-badge');
    const stage = $('recording-live-stage');
    btn.classList.toggle('recording', active);
    stage.classList.toggle('live', active);
    label.textContent = active ? '录音中，点击结束' : '点击开始录音';
    btn.innerHTML = active
      ? '<svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true"><rect x="4" y="4" width="12" height="12" rx="2.5" fill="currentColor"/></svg>'
      : '<svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true"><circle cx="13" cy="13" r="7.5" fill="currentColor"/></svg>';
    $('recording-timer').textContent = '00:00';
    if (!active) {
      badge.hidden = true;
      $('recording-title-input').disabled = false;
      $('recording-mode-switch').style.pointerEvents = '';
    } else {
      $('recording-title-input').disabled = true;
      $('recording-mode-switch').style.pointerEvents = 'none';
    }
  }

  function downsample(buffer, inputRate, targetRate) {
    const ratio = inputRate / targetRate;
    const outLen = Math.max(1, Math.round(buffer.length / ratio));
    const out = new Int16Array(outLen);
    for (let i = 0; i < outLen; i++) {
      const pos = i * ratio;
      const i0 = Math.min(Math.floor(pos), buffer.length - 1);
      const i1 = Math.min(i0 + 1, buffer.length - 1);
      const frac = pos - i0;
      const v = buffer[i0] * (1 - frac) + buffer[i1] * frac;
      out[i] = Math.max(-32768, Math.min(32767, Math.round(v * 32767)));
    }
    return out;
  }

  function concatInt16(a, b) {
    if (!a || a.length === 0) return b;
    const merged = new Int16Array(a.length + b.length);
    merged.set(a, 0);
    merged.set(b, a.length);
    return merged;
  }

  /* ── 上传音频 ─────────────────────────────── */

  window.recordingDragOver = function (e) {
    e.preventDefault();
    $('recording-upload-drop').classList.add('drag-over');
  };
  window.recordingDragLeave = function (e) {
    e.preventDefault();
    $('recording-upload-drop').classList.remove('drag-over');
  };
  window.recordingDrop = function (e) {
    e.preventDefault();
    $('recording-upload-drop').classList.remove('drag-over');
    if (e.dataTransfer && e.dataTransfer.files.length) recordingFileSelected(e.dataTransfer.files);
  };

  window.recordingFileSelected = async function (files) {
    if (!files || !files.length) return;
    const file = files[0];
    const selected = $('recording-file-selected');
    selected.style.display = 'inline-block';
    selected.textContent = `已选择：${file.name}（${(file.size / 1024 / 1024).toFixed(1)} MB）`;
    $('recording-upload-progress').style.display = 'block';
    $('recording-upload-status-text').textContent = '正在上传…';
    $('recording-upload-percent').textContent = '0%';
    $('recording-upload-progress-fill').style.width = '2%';
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await apiFetch('/api/recordings', { method: 'POST', body: form });
      showToast('音频已上传，后台开始转写（耗时约等于音频时长）');
      resetResultView();
      recState.currentRecording = { id: res.id };
      startPolling(res.id);
    } catch (e) {
      showToast(`上传失败：${e.message}`, 'error');
    }
  };

  /* ── 历史列表 ─────────────────────────────── */

  async function recordingLoadHistory() {
    const list = $('recording-history-list');
    if (!list) return;
    try {
      const data = await apiFetch('/api/recordings');
      const recordings = data.recordings || [];
      if (!recordings.length) {
        list.innerHTML = `<div class="recording-history-empty">还没有录音，开始第一条会议记录吧</div>`;
        return;
      }
      list.innerHTML = recordings.map((r) => {
        const statusMap = {
          completed: { label: '已完成', cls: 'ok' },
          recording: { label: '实时录音中', cls: 'live' },
          transcribing: { label: '转写中', cls: 'busy' },
          converting: { label: '格式转换中', cls: 'busy' },
          ai_processing: { label: 'AI 整理中', cls: 'busy' },
          failed: { label: '转写失败', cls: 'err' },
          uploading: { label: '上传中', cls: 'busy' },
          cancelled: { label: '已取消', cls: '' },
        };
        const st = statusMap[r.status] || { label: r.status, cls: '' };
        const hasResult = r.status === 'completed' && (r.segments || []).length;
        return `
          <div class="recording-history-item" onclick="recordingOpenHistory(${r.id})">
            <div class="recording-history-icon">
              <svg width="16" height="16" viewBox="0 0 15 15"><rect x="5.5" y="2" width="4" height="8" rx="2" stroke="currentColor" stroke-width="1.4" fill="none"/><path d="M2.5 9.5a5.5 5.5 0 0011 0" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" fill="none"/></svg>
            </div>
            <div class="recording-history-copy">
              <strong>${escapeHtml(r.title)}</strong>
              <span>${fmtTime(r.duration * 1000)} · ${(r.created_at || '').slice(0, 16).replace('T', ' ')}</span>
            </div>
            <span class="recording-history-status ${st.cls}">${st.label}</span>
            ${hasResult ? '<span class="recording-history-open">查看 ›</span>' : ''}
            <button type="button" class="recording-history-delete" onclick="recordingDeleteHistory(event, ${r.id})" aria-label="删除${escapeHtml(r.title)}" title="删除录音">
              <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 4h10M6 4V2.7h4V4M4.5 4l.6 9h5.8l.6-9M6.5 6.5v4M9.5 6.5v4" stroke="currentColor" stroke-width="1.35" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </button>
          </div>`;
      }).join('');
    } catch (e) {
      list.innerHTML = `<div class="recording-history-empty">历史列表加载失败：${escapeHtml(e.message)}</div>`;
    }
  }

  window.recordingDeleteHistory = async function (event, id) {
    event.preventDefault();
    event.stopPropagation();
    const displayTitle = event.currentTarget.closest('.recording-history-item')
      ?.querySelector('.recording-history-copy strong')?.textContent?.trim() || '这条录音';
    if (!window.confirm(`确定删除“${displayTitle}”吗？\n\n录音文件、转写稿和会议纪要将一并删除，且无法恢复。`)) return;
    try {
      await apiFetch(`/api/recordings/${id}`, { method: 'DELETE' });
      if (recState.currentRecording && recState.currentRecording.id === id) {
        clearInterval(recState.pollHandle);
        resetResultView();
        $('recording-result').style.display = 'none';
        recState.currentRecording = null;
      }
      showToast('录音已删除');
      recordingLoadHistory();
    } catch (e) {
      showToast(`删除失败：${e.message}`, 'error');
    }
  };

  window.recordingOpenHistory = async function (id) {
    const data = await apiFetch(`/api/recordings/${id}`);
    const rec = data.recording;
    recState.currentRecording = rec;
    if (rec.status === 'completed' || (rec.segments || []).length) {
      renderResult(rec);
    } else {
      if (rec.status === 'failed') {
        showToast(`转写失败：${rec.error || '未知错误'}`, 'error');
        startPolling(id);
      } else {
        showToast('该录音仍在处理中，稍后刷新历史查看');
        startPolling(id);
      }
    }
  };

  /* ── 结果渲染 ─────────────────────────────── */

  function resetResultView() {
    recState.segments = [];
    recState.partialSegment = null;
    recState.segmentEls = [];
    $('recording-segments').innerHTML = '';
    $('recording-polished').innerHTML = '';
    $('recording-summary-content').innerHTML = '';
    $('recording-summary-content').style.display = 'none';
    $('recording-summary-placeholder').style.display = 'block';
    $('recording-summary-status').textContent = '录音结束后自动生成';
    $('recording-player-time').textContent = '00:00 / 00:00';
    $('recording-player-fill').style.width = '0%';
    $('recording-player-knob').style.left = '0%';
    const audio = $('recording-audio');
    audio.pause();
    audio.removeAttribute('src');
    recState.playerLoadedId = null;
  }

  function showResultView(segments) {
    $('recording-result').style.display = 'block';
    renderSegments(segments);
  }

  function renderSegments(segments) {
    const container = $('recording-segments');
    container.innerHTML = '';
    recState.segmentEls = [];
    $('recording-segments-empty').style.display = segments.length ? 'none' : 'block';
    segments.forEach((seg) => appendSegmentEl(seg));
  }

  function appendSegmentEl(seg) {
    const container = $('recording-segments');
    $('recording-segments-empty').style.display = 'none';
    // 同一起始时间的分句后到覆盖先到（服务端会回传更新后的分句）
    const existing = container.querySelector(`[data-start="${seg.start}"]`);
    if (existing) {
      existing.querySelector('.recording-segment-text').textContent = seg.text;
      existing.dataset.end = seg.end;
      return;
    }
    const el = document.createElement('div');
    el.className = `recording-segment${seg.definite === false ? ' partial' : ''}`;
    el.dataset.start = seg.start;
    el.dataset.end = seg.end;
    el.innerHTML = `
      <span class="recording-segment-time">${fmtTime(seg.start * 1000)}</span>
      <span class="recording-segment-text">${escapeHtml(seg.text)}</span>
      ${seg.definite === false ? '<span class="recording-segment-state">识别中</span>' : ''}`;
    el.addEventListener('click', () => seekToSegment(seg));
    container.appendChild(el);
    recState.segmentEls.push(el);
    if (recState.autoFollow) {
      container.scrollTop = container.scrollHeight;
    }
  }

  function seekToSegment(seg) {
    const audio = $('recording-audio');
    if (!audio.src) return;
    audio.currentTime = Math.max(0, seg.start);
    highlightSegment(seg.start);
    audio.play().catch(() => {});
  }

  function renderResult(rec) {
    recState.currentRecording = rec;
    const segments = rec.segments || [];
    showResultView(segments);
    $('recording-player-title').textContent = rec.title || '未命名会议录音';

    // 播放器
    const audio = $('recording-audio');
    if (rec.audio_path) {
      if (recState.playerLoadedId !== rec.id) {
        audio.src = `/api/recordings/${rec.id}/audio`;
        recState.playerLoadedId = rec.id;
        audio.load();
      }
      $('recording-player-time').textContent = `${fmtTime(0)} / ${fmtTime(rec.duration * 1000)}`;
    }

    // AI 规整稿
    if (rec.polished_text) {
      $('recording-polished').innerHTML = `<div class="recording-polished-text">${markdownToHtml(rec.polished_text)}</div>`;
      $('recording-polished-empty').style.display = 'none';
    } else {
      $('recording-polished').innerHTML = '';
      $('recording-polished-empty').style.display = 'block';
      $('recording-polished-empty').textContent = rec.status === 'completed' ? '暂无规整稿' : 'AI 规整中，完成后自动显示…';
    }

    // AI 纪要
    if (rec.summary) {
      $('recording-summary-content').innerHTML = markdownToHtml(rec.summary);
      $('recording-summary-content').style.display = 'block';
      $('recording-summary-placeholder').style.display = 'none';
      $('recording-summary-status').textContent = '已生成';
    } else {
      $('recording-summary-content').style.display = 'none';
      $('recording-summary-placeholder').style.display = 'block';
      $('recording-summary-status').textContent = rec.status === 'completed' ? '未生成' : 'AI 整理中…';
    }

    const saveBtn = $('recording-save-kb-btn');
    if (saveBtn) {
      if (rec.article_id) {
        saveBtn.textContent = '已在知识库';
        saveBtn.classList.add('saved');
      } else {
        saveBtn.innerHTML = '<svg width="13" height="13" viewBox="0 0 14 14"><path d="M7 1v12M1 7h12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>存入知识库';
        saveBtn.classList.remove('saved');
      }
    }
  }

  function markdownToHtml(text) {
    let html = escapeHtml(text);
    html = html.replace(/^#{1,4} (.+)$/gm, (m, t) => `<h4>${t}</h4>`);
    html = html.replace(/^[-•] (.+)$/gm, (m, t) => `<div class="recording-md-li">• ${t}</div>`);
    html = html.replace(/^(\d+)[.、] (.+)$/gm, (m, num, t) => `<div class="recording-md-li">${num}. ${t}</div>`);
    return html.split(/\n{2,}/).map((block) => {
      if (!block.trim()) return '';
      if (/^(<h4>|<div class="recording-md-li">)/.test(block)) return block;
      return `<p>${block.replace(/\n/g, '<br>')}</p>`;
    }).join('');
  }

  /* ── 轮询转写进度 ─────────────────────────── */

  function startPolling(id) {
    clearInterval(recState.pollHandle);
    let done = false;
    const tick = async () => {
      if (done) return;
      try {
        const data = await apiFetch(`/api/recordings/${id}`);
        const rec = data.recording;
        recState.currentRecording = rec;
        updateUploadProgress(rec);
        if (rec.status === 'completed' || rec.status === 'failed') {
          done = true;
          clearInterval(recState.pollHandle);
          renderResult(rec);
          if (rec.status === 'failed') {
            showToast(`转写失败：${rec.error || '未知错误'}`, 'error');
          } else {
            showToast('转写与 AI 整理完成');
          }
          recordingLoadHistory();
        }
      } catch (e) { /* 网络抖动，继续轮询 */ }
    };
    tick();
    recState.pollHandle = (window.ApexLifecycle?.interval || window.setInterval)(tick, 3000);
  }

  function updateUploadProgress(rec) {
    const box = $('recording-upload-progress');
    if (!box || box.style.display === 'none') return;
    let percent = 0;
    let statusText = '';
    if (rec.status === 'converting') {
      percent = 5; statusText = '正在转换音频格式…';
    } else if (rec.status === 'transcribing') {
      const dur = Math.max(rec.duration || 0, 0.001);
      percent = Math.min(99, Math.round((rec.processed_ms / (dur * 1000)) * 100));
      statusText = `正在转写… 已处理 ${fmtTime(rec.processed_ms)} / ${fmtTime(rec.duration * 1000)}`;
    } else if (rec.status === 'ai_processing') {
      percent = 99; statusText = 'AI 正在规整语篇、生成纪要…';
    } else if (rec.status === 'completed') {
      percent = 100; statusText = '转写完成';
    } else if (rec.status === 'failed') {
      percent = 0; statusText = `转写失败：${rec.error || '未知错误'}`;
    }
    $('recording-upload-status-text').textContent = statusText;
    $('recording-upload-percent').textContent = `${percent}%`;
    $('recording-upload-progress-fill').style.width = `${percent}%`;
  }

  /* ── 播放器 ───────────────────────────────── */

  function bindPlayerEvents() {
    const audio = $('recording-audio');
    if (!audio || audio.dataset.bound) return;
    audio.dataset.bound = '1';

    // 进度条拖拽
    const progress = $('recording-player-progress');
    let dragging = false;
    progress.addEventListener('pointerdown', (e) => {
      dragging = true;
      progress.setPointerCapture && progress.setPointerCapture(e.pointerId);
      seekPlayerTo(e.clientX);
    });
    progress.addEventListener('pointermove', (e) => {
      if (dragging) seekPlayerTo(e.clientX);
    });
    progress.addEventListener('pointerup', () => { dragging = false; });
    progress.addEventListener('pointercancel', () => { dragging = false; });

    audio.addEventListener('timeupdate', () => {
      const t = audio.currentTime;
      updatePlayerUI(t);
      highlightSegment(t);
    });
    audio.addEventListener('play', () => setPlayIcon(true));
    audio.addEventListener('pause', () => setPlayIcon(false));
    audio.addEventListener('loadedmetadata', () => {
      const rec = recState.currentRecording;
      if (rec) $('recording-player-time').textContent = `${fmtTime(0)} / ${fmtTime((rec.duration || audio.duration) * 1000)}`;
    });
    audio.addEventListener('ended', () => {
      setPlayIcon(false);
      $('recording-player-fill').style.width = '100%';
      $('recording-player-knob').style.left = '100%';
    });
  }

  function updatePlayerUI(t) {
    const rec = recState.currentRecording;
    const duration = rec && rec.duration ? rec.duration : ($('recording-audio').duration || 0);
    $('recording-player-time').textContent = `${fmtTime(t * 1000)} / ${fmtTime(duration * 1000)}`;
    if (duration > 0) {
      const pct = Math.min(100, (t / duration) * 100);
      $('recording-player-fill').style.width = `${pct}%`;
      $('recording-player-knob').style.left = `${pct}%`;
    }
  }

  function setPlayIcon(playing) {
    recState.playing = playing;
    const playBtn = $('recording-play-btn');
    if (!playBtn) return;
    playBtn.querySelector('.icon-play').style.display = playing ? 'none' : '';
    playBtn.querySelector('.icon-pause').style.display = playing ? '' : 'none';
  }

  window.recordingTogglePlay = function () {
    const audio = $('recording-audio');
    if (!audio.src) { showToast('暂无可播放的录音', 'error'); return; }
    if (audio.paused) audio.play().catch(() => {});
    else audio.pause();
  };

  function highlightSegment(t) {
    let active = null;
    const els = recState.segmentEls;
    for (let i = 0; i < els.length; i++) {
      const start = parseFloat(els[i].dataset.start || '0');
      const end = parseFloat(els[i].dataset.end || '0');
      if (t >= start && t < end) { active = els[i]; break; }
    }
    const container = $('recording-segments');
    let changed = false;
    els.forEach((el) => {
      const isActive = el === active;
      if (el.classList.contains('active') !== isActive) {
        el.classList.toggle('active', isActive);
        changed = true;
      }
    });
    if (active && changed && recState.playing && container) {
      const containerRect = container.getBoundingClientRect();
      const elRect = active.getBoundingClientRect();
      if (elRect.top < containerRect.top + 60 || elRect.bottom > containerRect.bottom - 40) {
        active.scrollIntoView({ block: 'center', behavior: 'smooth' });
      }
    }
  }

  window.recordingSeek = function (event) {
    seekPlayerTo(event.clientX);
  };

  function seekPlayerTo(clientX) {
    const track = $('recording-player-progress');
    const rect = track.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    const rec = recState.currentRecording;
    const duration = rec && rec.duration ? rec.duration : ($('recording-audio').duration || 0);
    if (duration > 0) {
      $('recording-audio').currentTime = ratio * duration;
      updatePlayerUI(ratio * duration);
      highlightSegment(ratio * duration);
    }
  }

  window.recordingSwitchTranscriptView = function (view) {
    document.querySelectorAll('.recording-transcript-tab').forEach((tab) => {
      tab.classList.toggle('active', tab.dataset.view === view);
    });
    $('recording-view-transcript').classList.toggle('active', view === 'transcript');
    $('recording-view-polished').classList.toggle('active', view === 'polished');
  };

  /* ── 入库与 AI 重生成 ──────────────────────── */

  window.recordingSaveToKb = async function () {
    const rec = recState.currentRecording;
    if (!rec) { showToast('请先完成一次转写', 'error'); return; }
    if (rec.article_id) {
      showToast('该录音已存入知识库');
      return;
    }
    const btn = $('recording-save-kb-btn');
    btn.disabled = true;
    try {
      const res = await apiFetch(`/api/recordings/${rec.id}/save-to-kb`, { method: 'POST' });
      recState.currentRecording.article_id = res.article_id;
      showToast('已存入知识库');
      btn.textContent = '已在知识库';
      btn.classList.add('saved');
      try { window.parent.loadArticles && window.parent.loadArticles(); } catch (e) { /* 跨域或未定义，忽略 */ }
      recordingLoadHistory();
    } catch (e) {
      showToast(`入库失败：${e.message}`, 'error');
    } finally {
      btn.disabled = false;
    }
  };

  window.recordingRegenerateAI = async function () {
    const rec = recState.currentRecording;
    if (!rec) { showToast('请先完成一次转写', 'error'); return; }
    showToast('已开始重新生成规整与纪要');
    try {
      await apiFetch(`/api/recordings/${rec.id}/ai-process`, { method: 'POST' });
      startPolling(rec.id);
    } catch (e) {
      showToast(`操作失败：${e.message}`, 'error');
    }
  };

  /* ── 页面离开时兜底停止录音 ────────────────── */

  window.addEventListener('beforeunload', () => {
    if (recState.recording) {
      try {
        recState.ws && recState.ws.send('end');
        recState.micStream && recState.micStream.getTracks().forEach((t) => t.stop());
      } catch (e) { /* 忽略 */ }
    }
  });

  /* ── 初始化 ────────────────────────────────── */

  window.addEventListener('DOMContentLoaded', () => {
    if (recState.inited) return;
    recState.inited = true;
    bindPlayerEvents();
    recordingLoadConfigStatus();
    recordingLoadHistory();
  });
})();
