try {
  if (window.parent !== window) {
    document.documentElement.classList.add('embedded-host');
    document.body.classList.add('embedded-host');
  }
} catch (e) {}

function applyCaseManagerTheme(dark) {
  document.documentElement.classList.toggle('dark-mode', !!dark);
  if (document.body) document.body.classList.toggle('dark-mode', !!dark);
}
try {
  applyCaseManagerTheme(window.apexCurrentDarkMode?.() === true);
  window.addEventListener('storage', function(event) {
    if (event.key === 'theme') applyCaseManagerTheme(event.newValue === 'dark');
  });
  window.addEventListener('message', function(event) {
    if (event.data && event.data.type === 'theme') applyCaseManagerTheme(!!event.data.dark);
  });
  if (typeof BroadcastChannel !== 'undefined') {
    const themeChannel = new BroadcastChannel('legal-kb-theme');
    themeChannel.onmessage = function(event) {
      applyCaseManagerTheme(event.data === 'dark');
    };
  }
} catch (e) {}

const state = {
  dashboard: null, items: {}, q: '', searchField: 'all', due: '', editing: null,
  selectedFiles: null, calendarsLoaded: false,
  calendarOptions: [], calendarSettings: null, calendarDetails: [], calendarLastResult: null, calendarWarning: '', calendarIcloudVerified: false,
  caseTypes: [], caseTypeQuery: '', caseStages: [], partyRoles: [],
  caseNumberTypes: [], preservationTypes: [], courts: [], courtQuery: '',
  selectedCaseIds: new Set(), archivedCases: [], trashCases: [], caseListEditing: false, archivedQ: '',
  clients: [], selectedClient: null, clientEditing: false, clientQ: '',
  opponents: [], selectedOpponent: null, opponentEditing: false, opponentQ: '',
  offlineSnapshot: null, offlineMode: false, offlineReady: false, offlineToastShown: false, offlineReadyToastShown: false,
  lastOnlineProbeAt: 0, serverOnline: null, lastServerSuccessAt: 0, failedServerProbes: 0,
  caseCalendarDate: new Date(), caseCalendarTypes: { todo: true, hearing: true, preservation: true, appeal: true }, caseCalendarEvents: [],
  hideOverdue: (() => { try { return localStorage.getItem('cm_hide_overdue') === '1'; } catch (e) { return false; } })(),
  completingTodo: null,
  caseResearch: { caseId: 0, section: '', projectId: 0, data: null, loading: false, query: '', sideExpanded: true },
  judicialMessages: { items: [], total: 0, page: 1, pageSize: 50, q: '', status: '', category: '', dateFrom: '', dateTo: '', newOnly: false, statusData: null, settings: null, selected: null, selectedIds: [], cases: [] },
  courtOnline: { items: [], total: 0, page: 1, pageSize: 50, kind: '', caseAjlb: 'sp', layyAjlb: 'sp', q: '', unread: false, status: null, sync: { phase: 'idle', message: '' }, focusRecordId: 0, linkingRecordId: 0, linkCaseQuery: '', advSearch: { case_no: '', court: '', party: '' } },
  filing: { items: [], current: null, validation: null, loading: false },
  managedOptionKind: '', managedOptions: [], managedOptionQuery: '',
  seriesWorkspace: null, seriesSelectedChildIds: new Set(), seriesChildQuery: '', seriesImportPreview: null, seriesImportHistory: null, seriesHistoryPendingId: 0, seriesMobileCardLayout: null, seriesShowHiddenRows: false,
  seriesCreateImportPreview: null, seriesColumnFilters: {}, seriesSortKey: '', seriesSortDirection: 'asc', seriesFilterDraft: null, seriesFilterComposing: false,
  seriesDraggingColumnKey: '', seriesDeletedColumnKeys: [], seriesTableEditMode: false, seriesTableFocusMode: false,
  seriesWorkspaceTab: 'children', seriesPublicEditMode: false, seriesPublicInlineEditKey: '', seriesPublicFieldOrderDraft: [], seriesCellSelection: null, seriesSelectionDragging: false, seriesTableContext: null, seriesCellMultiSelection: new Set(),
  seriesDetailMappingDraft: { sourceKey: '', targetKey: '' },
  seriesPendingDeleteIds: [], pendingCaseDelete: null, seriesUndoStack: [], seriesRedoStack: [], seriesHistoryBusy: false,
  seriesDraggingRowId: 0,
  prepaidExpenses: {
    items: [], summary: { balance: 0, advance: 0, expense: 0, record_count: 0 },
    categories: ['交通出行','快递邮寄/跑腿','打印复印/装订','餐饮/业务招待','差旅住宿','培训/书刊资料','调查取证/查档','诉讼仲裁/公证/保全','办公用品/耗材','其他'],
    presets: { expense: [], advance: [] }, presetDraft: { expense: [], advance: [] },
    sync: {}, filters: { dateFrom: '', dateTo: '', entryType: '', project: '', category: '', q: '' },
    editing: null, caseSuggestions: [], categoryDraft: [], syncing: false, settings: null
  }
};
const apexReorderAnimationCleanups = new WeakMap();
const apexReorderCommitTimers = new WeakMap();
function captureApexReorderRects(container, selector = ':scope > *') {
  if (!container) return new Map();
  return new Map(Array.from(container.querySelectorAll(selector)).map(element => [element, element.getBoundingClientRect()]));
}
function animateApexReorder(container, beforeRects, { skip = null, duration = 180 } = {}) {
  if (!container || !beforeRects?.size) return;
  apexReorderAnimationCleanups.get(container)?.();
  const moved = [];
  beforeRects.forEach((before, element) => {
    if (element === skip || !element.isConnected || !container.contains(element)) return;
    const after = element.getBoundingClientRect();
    const dx = before.left - after.left;
    const dy = before.top - after.top;
    if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5) return;
    element.style.setProperty('--apex-reorder-dx', `${dx}px`);
    element.style.setProperty('--apex-reorder-dy', `${dy}px`);
    element.classList.add('apex-reorder-flip');
    moved.push(element);
  });
  if (!moved.length) return;
  let frameId = 0;
  let cleanupTimer = 0;
  const cleanup = () => {
    if (frameId) cancelAnimationFrame(frameId);
    if (cleanupTimer) clearTimeout(cleanupTimer);
    moved.forEach(element => {
      element.classList.remove('apex-reorder-flip');
      element.style.removeProperty('--apex-reorder-dx');
      element.style.removeProperty('--apex-reorder-dy');
    });
    if (apexReorderAnimationCleanups.get(container) === cleanup) apexReorderAnimationCleanups.delete(container);
  };
  apexReorderAnimationCleanups.set(container, cleanup);
  frameId = requestAnimationFrame(() => {
    moved.forEach(element => {
      element.style.setProperty('--apex-reorder-dx', '0px');
      element.style.setProperty('--apex-reorder-dy', '0px');
    });
    cleanupTimer = window.setTimeout(cleanup, duration + 40);
  });
}
function markApexReorderCommitted(element) {
  if (!element) return;
  const previousTimer = apexReorderCommitTimers.get(element);
  if (previousTimer) clearTimeout(previousTimer);
  element.classList.add('apex-reorder-committed');
  const timer = window.setTimeout(() => {
    element.classList.remove('apex-reorder-committed');
    apexReorderCommitTimers.delete(element);
  }, 260);
  apexReorderCommitTimers.set(element, timer);
}
const initialPageParams = new URLSearchParams(location.search);
state.courtOnline.focusRecordId = Number(initialPageParams.get('court_record') || 0);
const courtLocateKind = String(initialPageParams.get('court_kind') || '');
if (courtLocateKind) {
  state.courtOnline.kind = courtLocateKind;
  state.courtOnline.q = String(initialPageParams.get('court_q') || '');
}
const isTeamExpensesMode = initialPageParams.get('mode') === 'team-expenses';
const isCourtOnlineMode = initialPageParams.get('mode') === 'court-online';
// 案件管理、一张网和团队费用共用同一页面文件；每个外层标签都传入独立
// workspace_id，避免同源 iframe 共享 sessionStorage 时互相恢复抽屉或子页面。
const PAGE_WORKSPACE_ID = String(initialPageParams.get('workspace_id') || 'standalone')
  .replace(/[^A-Za-z0-9_-]/g, '').slice(0, 80) || 'standalone';
const workspaceSessionKey = name => `case-manager:${PAGE_WORKSPACE_ID}:${name}`;
const ACTIVE_TAB_SESSION_KEY = workspaceSessionKey(isCourtOnlineMode
  ? 'active-tab-court-online-v2'
  : (isTeamExpensesMode ? 'active-tab-team-expenses-v2' : 'active-tab-manager-v2'));
const RESTORABLE_TABS = new Set(['cases', 'todos', 'hearings', 'preservations', 'appeals', 'judicialMessages', 'import', 'caseCalendar', 'calendar', 'courtOnline', 'prepaidExpenses']);
function rememberedActiveTab() {
  try {
    const tab = String(sessionStorage.getItem(ACTIVE_TAB_SESSION_KEY) || '');
    // 普通案件管理页不应因历史状态恢复成嵌套的一张网页面。
    if (!isCourtOnlineMode && tab === 'courtOnline') return '';
    return RESTORABLE_TABS.has(tab) ? tab : '';
  } catch (_) { return ''; }
}
function rememberActiveTab(tab) {
  if (!RESTORABLE_TABS.has(tab)) return;
  // 一张网在普通案件管理页中可以临时查看，但不把它作为普通入口的恢复页。
  if (!isCourtOnlineMode && tab === 'courtOnline') return;
  try { sessionStorage.setItem(ACTIVE_TAB_SESSION_KEY, tab); } catch (_) {}
}
const explicitTab = String(initialPageParams.get('tab') || '');
let activeTab = isTeamExpensesMode && explicitTab === 'prepaidExpenses'
  ? 'prepaidExpenses'
  : (isCourtOnlineMode ? 'courtOnline' : (rememberedActiveTab() || 'cases'));
if (explicitTab === 'judicialMessages' && !isCourtOnlineMode && !isTeamExpensesMode) activeTab = 'judicialMessages';
if (isTeamExpensesMode) {
  document.body.classList.add('team-expenses-mode');
  document.title = '团队费用管理';
}
if (isCourtOnlineMode) {
  document.body.classList.add('court-online-mode');
  document.title = '一张网';
}
const OPEN_CASE_DETAIL_SESSION_KEY = workspaceSessionKey('open-case-detail');
const OPEN_CASE_DETAIL_STATE_SESSION_KEY = workspaceSessionKey('open-case-detail-state-v2');

function rememberOpenCaseDetail(itemOrId, seriesId = 0) {
  const item = itemOrId && typeof itemOrId === 'object' ? itemOrId : null;
  const id = Number(item?.id || itemOrId || 0);
  if (!id) return;
  try {
    sessionStorage.setItem(OPEN_CASE_DETAIL_SESSION_KEY, String(id));
    // 只在当前浏览器会话内保存已打开的详情数据。刷新时先用该快照绘制
    // 原页面，随后再请求最新数据，避免总览/列表加载挡住详情数秒。
    if (item) {
      sessionStorage.setItem(OPEN_CASE_DETAIL_STATE_SESSION_KEY, JSON.stringify({
        id,
        seriesId: Number(seriesId || 0),
        item,
      }));
    }
  } catch (_) {}
}

function rememberedOpenCaseDetailId() {
  try { return Number(sessionStorage.getItem(OPEN_CASE_DETAIL_SESSION_KEY) || 0); } catch (_) { return 0; }
}

function rememberedOpenCaseDetailState() {
  try {
    const data = JSON.parse(sessionStorage.getItem(OPEN_CASE_DETAIL_STATE_SESSION_KEY) || 'null');
    if (!data || !Number(data.id) || !data.item || typeof data.item !== 'object') return null;
    return { id: Number(data.id), seriesId: Number(data.seriesId || 0), item: data.item };
  } catch (_) { return null; }
}

function forgetOpenCaseDetail() {
  try {
    sessionStorage.removeItem(OPEN_CASE_DETAIL_SESSION_KEY);
    sessionStorage.removeItem(OPEN_CASE_DETAIL_STATE_SESSION_KEY);
  } catch (_) {}
}

const OPEN_MANAGER_SESSION_KEY = workspaceSessionKey('open-manager');

function rememberOpenManager(kind, patch = {}) {
  const kindKey = kind === 'opponent' ? 'opponent' : 'client';
  const prev = rememberedOpenManager();
  const base = prev && prev.kind === kindKey
    ? prev
    : { kind: kindKey, selectedId: 0, listScrollTop: 0, detailScrollTop: 0, bodyScrollTop: 0 };
  const next = Object.assign({}, base, patch);
  try { sessionStorage.setItem(OPEN_MANAGER_SESSION_KEY, JSON.stringify(next)); } catch (_) {}
}

function rememberedOpenManager() {
  try {
    const raw = sessionStorage.getItem(OPEN_MANAGER_SESSION_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (data.kind !== 'client' && data.kind !== 'opponent') return null;
    return {
      kind: data.kind,
      selectedId: Number(data.selectedId || 0),
      listScrollTop: Number(data.listScrollTop || 0),
      detailScrollTop: Number(data.detailScrollTop || 0),
      bodyScrollTop: Number(data.bodyScrollTop || 0),
    };
  } catch (_) { return null; }
}

function forgetOpenManager() {
  try { sessionStorage.removeItem(OPEN_MANAGER_SESSION_KEY); } catch (_) {}
}

function managerElementsFor(kind) {
  const isOpponent = kind === 'opponent';
  return {
    list: document.getElementById(isOpponent ? 'opponentList' : 'clientList'),
    detail: document.getElementById(isOpponent ? 'opponentDetail' : 'clientDetail'),
  };
}

function bindManagerScrollRemember(kind) {
  const { list, detail } = managerElementsFor(kind);
  if (list && !list.dataset.scrollRememberBound) {
    list.dataset.scrollRememberBound = '1';
    list.addEventListener('scroll', () => rememberOpenManager(kind, { listScrollTop: list.scrollTop }));
  }
  if (detail && !detail.dataset.scrollRememberBound) {
    detail.dataset.scrollRememberBound = '1';
    detail.addEventListener('scroll', () => rememberOpenManager(kind, { detailScrollTop: detail.scrollTop }));
  }
  const body = document.querySelector(`#${kind === 'opponent' ? 'opponentManager' : 'clientManager'} .client-manager-body`);
  if (body && !body.dataset.scrollRememberBound) {
    body.dataset.scrollRememberBound = '1';
    body.addEventListener('scroll', () => rememberOpenManager(kind, { bodyScrollTop: body.scrollTop }));
  }
}

function restoreManagerScroll(kind, remembered) {
  if (!remembered) return;
  requestAnimationFrame(() => {
    const { list, detail } = managerElementsFor(kind);
    if (list && remembered.listScrollTop) list.scrollTop = remembered.listScrollTop;
    if (detail && remembered.detailScrollTop) detail.scrollTop = remembered.detailScrollTop;
    const body = document.querySelector(`#${kind === 'opponent' ? 'opponentManager' : 'clientManager'} .client-manager-body`);
    if (body && remembered.bodyScrollTop) body.scrollTop = remembered.bodyScrollTop;
  });
}

const tabMeta = {
  cases: { label: '案件', endpoint: '/api/case-manager/cases' },
  todos: { label: '待办', endpoint: '/api/case-manager/todos' },
  hearings: { label: '开庭', endpoint: '/api/case-manager/hearings' },
  preservations: { label: '财产保全', endpoint: '/api/case-manager/preservations' },
  appeals: { label: '上诉/异议期', endpoint: '/api/case-manager/appeals' },
};
const TODO_RECURRENCE_LABELS = {
  weekly: '每星期', semimonthly: '每半个月', monthly: '每月',
  bimonthly: '每两个月', quarterly: '每三个月', semiannual: '每半年',
};
const CASE_MANAGER_PAGE_LABELS = {
  cases: '案件列表',
  todos: '待办事项',
  hearings: '开庭提醒',
  preservations: '财产保全',
  appeals: '上诉/异议期',
  judicialMessages: '司法短信',
  courtOnline: '一张网',
  filing: '智能立案',
  import: '导入中心',
  caseCalendar: '案件日历',
  prepaidExpenses: '团队费用管理',
  calendar: '日历同步'
};

function currentCaseManagerPageLabel() {
  return CASE_MANAGER_PAGE_LABELS[activeTab] || tabMeta[activeTab]?.label || '案件管理';
}

function notifyCaseManagerContext(contextLabel = '', detailLabel = '', caseContext = null) {
  if (!window.parent || window.parent === window) return;
  const caseId = Number(caseContext?.id || 0);
  const caseTitle = String(caseContext?.title || '').trim();
  window.parent.postMessage({
    type: 'caseManagerContext',
    contextLabel: contextLabel || currentCaseManagerPageLabel(),
    pageLabel: currentCaseManagerPageLabel(),
    detailLabel: detailLabel || '',
    caseId: caseId > 0 ? caseId : 0,
    caseTitle: caseId > 0 ? caseTitle : ''
  }, location.origin);
}

function forwardOpenPagesCommandKey(eventType, repeat = false, code = '', location = 0) {
  if (!window.parent || window.parent === window) return;
  window.parent.postMessage({
    type: 'openPagesCommandKey',
    eventType,
    repeat: !!repeat,
    code,
    location
  }, location.origin);
}

window.addEventListener('keydown', event => {
  if (event.key === 'Meta') {
    forwardOpenPagesCommandKey('down', event.repeat, event.code, event.location);
  } else if (event.metaKey) {
    forwardOpenPagesCommandKey('cancel');
  }
}, true);
window.addEventListener('keyup', event => {
  if (event.key === 'Meta') forwardOpenPagesCommandKey('up', false, event.code, event.location);
}, true);
window.addEventListener('blur', () => forwardOpenPagesCommandKey('blur'));

function currentSeriesWorkspaceDetailLabel() {
  if (state.seriesWorkspace?.creating) return '新增系列案件';
  return state.seriesWorkspaceTab === 'public' ? '系列案公共信息' : '系列案子案主表';
}

function notifySeriesWorkspaceContext() {
  const title = state.seriesWorkspace?.creating
    ? '新增系列案件'
    : (state.seriesWorkspace?.title || '系列案件');
  notifyCaseManagerContext(title, currentSeriesWorkspaceDetailLabel());
}
const HEARING_TYPE_OPTIONS = ['一审开庭', '二审庭询', '二审开庭', '再审审查开庭', '再审开庭', '执行异议听证', '开庭', '听证', '询问', '谈话'];

const OFFLINE_DB_NAME = 'legal-kb-case-manager';
const OFFLINE_DB_VERSION = 1;
const OFFLINE_STORE = 'snapshots';
const OFFLINE_KEY = 'latest';
const LOCAL_PIN_KEY = 'case-manager-local-pinned-case-ids';
const PENDING_CASE_OPS_KEY = 'case-manager-pending-case-ops';
const OFFLINE_SYNCED_AT_KEY = 'case-manager-offline-synced-at';
const OFFLINE_REFRESH_AGE = 60 * 60 * 1000;
const OFFLINE_DB_STARTUP_TIMEOUT_MS = 800;
const PWA_SESSION_STATUS_URL = '/api/pwa/session-status';
let offlineRefreshTimer = null;
let offlineRefreshForced = false;
let lastOfflineCacheUserActivityAt = Date.now();

['pointerdown', 'touchstart', 'keydown', 'scroll'].forEach(eventName => {
  document.addEventListener(eventName, () => { lastOfflineCacheUserActivityAt = Date.now(); }, { passive: true, capture: true });
});

function scheduleCaseOfflineSnapshot(force = false, delay = 10000) {
  offlineRefreshForced ||= force;
  const lastSync = Number(localStorage.getItem(OFFLINE_SYNCED_AT_KEY) || 0);
  if (!force && lastSync && Date.now() - lastSync < OFFLINE_REFRESH_AGE) return;
  if (force && offlineRefreshTimer) {
    clearTimeout(offlineRefreshTimer);
    offlineRefreshTimer = null;
  }
  if (offlineRefreshTimer) return;
  offlineRefreshTimer = window.setTimeout(async () => {
    offlineRefreshTimer = null;
    const userIsActive = Date.now() - lastOfflineCacheUserActivityAt < 15000;
    if (document.hidden || state.serverOnline !== true || userIsActive) {
      scheduleCaseOfflineSnapshot(offlineRefreshForced, 15000);
      return;
    }
    const shouldForce = offlineRefreshForced;
    offlineRefreshForced = false;
    await syncOfflineSnapshot(true);
    if (shouldForce && offlineRefreshForced) scheduleCaseOfflineSnapshot(true, 5000);
  }, Math.max(0, delay));
}

function openOfflineDb(timeoutMs = OFFLINE_DB_STARTUP_TIMEOUT_MS) {
  return new Promise((resolve, reject) => {
    if (!('indexedDB' in window)) return reject(new Error('当前浏览器不支持离线数据存储'));
    const req = indexedDB.open(OFFLINE_DB_NAME, OFFLINE_DB_VERSION);
    let settled = false;
    const finish = (callback, value) => {
      if (settled) {
        if (callback === resolve) {
          try { value?.close?.(); } catch (_) {}
        }
        return;
      }
      settled = true;
      clearTimeout(timer);
      callback(value);
    };
    const timer = window.setTimeout(() => {
      finish(reject, Object.assign(new Error('读取本机案件缓存超时'), { kind: 'timeout' }));
    }, Math.max(100, Number(timeoutMs) || OFFLINE_DB_STARTUP_TIMEOUT_MS));
    req.onupgradeneeded = () => req.result.createObjectStore(OFFLINE_STORE);
    req.onsuccess = () => finish(resolve, req.result);
    req.onerror = () => finish(reject, req.error || new Error('本机案件缓存无法打开'));
    req.onblocked = () => finish(reject, Object.assign(new Error('本机案件缓存正被其他页面占用'), { kind: 'blocked' }));
  });
}
async function readOfflineSnapshot() {
  const db = await openOfflineDb(OFFLINE_DB_STARTUP_TIMEOUT_MS);
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (callback, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      try { db.close(); } catch (_) {}
      callback(value);
    };
    const timer = window.setTimeout(() => {
      finish(reject, Object.assign(new Error('读取本机案件快照超时'), { kind: 'timeout' }));
    }, OFFLINE_DB_STARTUP_TIMEOUT_MS);
    const tx = db.transaction(OFFLINE_STORE, 'readonly');
    const req = tx.objectStore(OFFLINE_STORE).get(OFFLINE_KEY);
    req.onsuccess = () => finish(resolve, req.result || null);
    req.onerror = () => finish(reject, req.error || new Error('本机案件快照读取失败'));
    tx.onabort = () => finish(reject, tx.error || new Error('本机案件快照读取中断'));
  });
}
async function writeOfflineSnapshot(snapshot) {
  const db = await openOfflineDb(3000);
  return new Promise((resolve, reject) => {
    const tx = db.transaction(OFFLINE_STORE, 'readwrite');
    tx.objectStore(OFFLINE_STORE).put(snapshot, OFFLINE_KEY);
    tx.oncomplete = () => { db.close(); resolve(); };
    tx.onerror = () => { db.close(); reject(tx.error); };
  });
}
function pendingCaseOps() {
  try {
    return JSON.parse(localStorage.getItem(PENDING_CASE_OPS_KEY) || '[]');
  } catch (e) {
    return [];
  }
}
function savePendingCaseOps(ops) {
  localStorage.setItem(PENDING_CASE_OPS_KEY, JSON.stringify(ops || []));
}
function makeTempCaseId() {
  return -Math.floor(Date.now() + Math.random() * 1000000);
}
function caseBodyToOfflineItem(body, id, existing = {}) {
  const now = new Date().toISOString();
  const item = {
    ...existing,
    ...body,
    id,
    parties: body.parties || existing.parties || [],
    case_numbers: body.case_numbers || existing.case_numbers || [],
    todos: body.todos || existing.todos || [],
    hearings: body.hearings || existing.hearings || [],
    preservations: body.preservations || existing.preservations || [],
    appeals: body.appeals || existing.appeals || [],
    todo_count: (body.todos || existing.todos || []).length,
    hearing_count: (body.hearings || existing.hearings || []).length,
    preservation_count: (body.preservations || existing.preservations || []).length,
    appeal_count: (body.appeals || existing.appeals || []).length,
    created_at: existing.created_at || now,
    updated_at: now,
    offline_pending: true,
  };
  return item;
}
function applyOfflineCaseMutation(op) {
  if (!state.offlineSnapshot) return;
  const cases = state.offlineSnapshot.cases || (state.offlineSnapshot.cases = {});
  cases.active = cases.active || [];
  cases.trash = cases.trash || [];
  const id = Number(op.id);
  if (op.action === 'delete') {
    const idx = cases.active.findIndex(item => Number(item.id) === id);
    if (idx >= 0) {
      const [removed] = cases.active.splice(idx, 1);
      cases.trash.unshift({ ...removed, deleted_at: new Date().toISOString(), offline_pending: true });
    }
  } else if (op.action === 'upsert') {
    const existing = allOfflineCases().find(item => Number(item.id) === id) || {};
    const item = caseBodyToOfflineItem(op.payload, id, existing);
    const idx = cases.active.findIndex(x => Number(x.id) === id);
    if (idx >= 0) cases.active[idx] = item;
    else cases.active.unshift(item);
  }
  state.offlineSnapshot.dashboard = state.offlineSnapshot.dashboard || { counts: {} };
  state.offlineSnapshot.dashboard.counts = state.offlineSnapshot.dashboard.counts || {};
  state.offlineSnapshot.dashboard.counts.cases = (cases.active || []).length;
  writeOfflineSnapshot(state.offlineSnapshot).catch(() => {});
}
function enqueueCaseOp(op) {
  const ops = pendingCaseOps();
  ops.push({ ...op, queued_at: new Date().toISOString() });
  savePendingCaseOps(ops);
  applyOfflineCaseMutation(op);
}
async function submitPendingCaseOp(op, idMap) {
  const originalId = Number(op.id || 0);
  const mappedId = idMap.get(originalId) || originalId;
  if (op.action === 'delete') {
    if (mappedId < 0) return null;
    const res = await fetchWithTimeout(`/api/case-manager/cases/${mappedId}`, { method: 'DELETE' }, 30000);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.message || '离线删除同步失败');
    return data;
  }
  const isExisting = mappedId > 0;
  const res = await fetchWithTimeout(
    isExisting ? `/api/case-manager/cases/${mappedId}` : '/api/case-manager/cases',
    {
      method: isExisting ? 'PUT' : 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(op.payload || {}),
    },
    30000
  );
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || data.message || '离线保存同步失败');
  if (originalId < 0 && data && data.id) idMap.set(originalId, Number(data.id));
  return data;
}
async function syncPendingCaseOps() {
  const ops = pendingCaseOps();
  if (!ops.length) return false;
  if (!(await localServerReachable(3000))) return false;
  const remaining = [];
  const idMap = new Map();
  let failed = false;
  for (const op of ops) {
    if (failed) {
      const mappedId = idMap.get(Number(op.id || 0));
      remaining.push(mappedId ? { ...op, id: mappedId } : op);
      continue;
    }
    try {
      await submitPendingCaseOp(op, idMap);
    } catch (e) {
      const mappedId = idMap.get(Number(op.id || 0));
      remaining.push(mappedId ? { ...op, id: mappedId } : op);
      failed = true;
    }
  }
  savePendingCaseOps(remaining);
  scheduleCaseOfflineSnapshot(true, 3000);
  if (!remaining.length) {
    toast('案件离线修改已同步');
    await refreshAll(false);
    return true;
  }
  updateOfflineStatus();
  toast('部分离线修改暂未同步，稍后会继续尝试');
  return false;
}
function canOfflineEditCase() {
  return state.offlineMode && state.offlineReady;
}
async function initOfflineSupport() {
  if ('serviceWorker' in navigator && window.isSecureContext &&
      !/LegalKB-NativeShell/.test(navigator.userAgent || '')) {
    navigator.serviceWorker.register('/case-manager-sw.js?v=242', { updateViaCache: 'none' })
      .then(reg => { if (reg && reg.update) reg.update(); })
      .catch(() => {});
  }
  try {
    const snapshot = await readOfflineSnapshot();
    if (snapshot) {
      state.offlineSnapshot = snapshot;
      state.offlineReady = true;
      if (!localStorage.getItem(OFFLINE_SYNCED_AT_KEY)) {
        const generatedAt = Date.parse(snapshot.generated_at || '');
        if (Number.isFinite(generatedAt)) localStorage.setItem(OFFLINE_SYNCED_AT_KEY, String(generatedAt));
      }
      }
      window.apexRecordStartup?.('indexeddb-ready', snapshot ? 'snapshot' : 'empty');
    } catch (e) {
      console.warn('读取离线缓存失败', e);
      window.apexRecordStartup?.('indexeddb-failed', e?.kind || e?.name || 'error');
    }
  updateOfflineStatus();
}
function snapshotTime(snapshot = state.offlineSnapshot) {
  return snapshot?.generated_at ? fmt(snapshot.generated_at) : '';
}
function offlineStatusText() {
  if (state.offlineMode) {
    return state.offlineReady ? `离线缓存 ${snapshotTime()}` : '离线无缓存';
  }
  return state.offlineReady ? `已缓存 ${snapshotTime()}` : '准备离线缓存';
}
function showOfflineStatusDetail() {
  toast(offlineStatusText());
}
function updateOfflineStatus() {
  const el = $('offlineStatus');
  if (!el) return;
  const text = offlineStatusText();
  el.classList.toggle('offline', state.offlineMode);
  el.classList.toggle('ready', state.offlineReady);
  el.title = text;
  el.setAttribute('aria-label', text);
  const sr = el.querySelector('.sr-only');
  if (sr) sr.textContent = text;
  updateListHeroMeta();
  updateTopAdd();
}
async function syncOfflineSnapshot(silent = true) {
  try {
    const res = await fetchWithTimeout(
      '/api/case-manager/offline-snapshot',
      { cache: 'no-store' },
      state.offlineReady ? 15000 : 30000
    );
    if (!res.ok) throw new Error('离线快照更新失败');
    const snapshot = await res.json();
    await writeOfflineSnapshot(snapshot);
    state.offlineSnapshot = snapshot;
    state.offlineReady = true;
    state.offlineMode = false;
    localStorage.setItem(OFFLINE_SYNCED_AT_KEY, String(Date.now()));
    updateOfflineStatus();
    if (!silent) {
      toast('离线缓存已更新');
    } else if (!state.offlineReadyToastShown) {
      toast(`案件离线缓存已更新 ${snapshotTime(snapshot)}`);
      state.offlineReadyToastShown = true;
    }
    return true;
  } catch (e) {
    updateOfflineStatus();
    if (!silent && state.offlineReady) toast('当前使用上次离线缓存');
    return false;
  }
}
function requireOnlineAction() {
  if (isOfflineReadonly()) {
    toast('离线模式下仅支持检索和查看，联网后可新增、编辑或删除');
    return false;
  }
  return true;
}
function isOfflineReadonly() {
  return state.offlineMode;
}
function canWriteCurrentTabOffline(tab = activeTab) {
  return tab === 'cases' && canOfflineEditCase();
}
function offlineText(value) {
  return String(value ?? '').toLowerCase();
}
function caseSearchText(item, field = 'all') {
  const parties = item.parties || [];
  const nums = item.case_numbers || [];
  const clients = parties.filter(p => p.party_group === 'client');
  const opponents = parties.filter(p => p.party_group !== 'client');
  const groups = {
    client: clients.flatMap(p => [p.role, p.name, p.credit_code]),
    opponent: opponents.flatMap(p => [p.role, p.name, p.credit_code]),
    title: [item.title],
    case_type: [item.case_type],
    current_stage: [item.current_stage],
    all: [
      item.title, item.case_type, item.current_stage, item.court_contact, item.party_contact, item.memo,
      ...parties.flatMap(p => [p.role, p.name, p.credit_code]),
      ...nums.flatMap(n => [n.number_type, n.case_no, n.court, n.handler_contact]),
      ...(item.hearings || []).flatMap(h => Object.values(h)),
      ...(item.preservations || []).flatMap(p => Object.values(p)),
      ...(item.appeals || []).flatMap(a => Object.values(a)),
    ],
  };
  return offlineText((groups[field] || groups.all).join(' '));
}
function itemSearchText(item, field = 'all') {
  if (field === 'title' || field === 'client' || field === 'opponent') return offlineText(item.title);
  if (field === 'case_type') return offlineText(item.case_type);
  if (field === 'current_stage') return offlineText(item.current_stage);
  return offlineText(Object.values(item || {}).join(' '));
}
function filterItems(items, q, field, searcher) {
  const query = offlineText(q).trim();
  if (!query) return [...items];
  return items.filter(item => searcher(item, field).includes(query));
}
function caseUpdatedValue(item) {
  const time = Date.parse(String(item?.updated_at || '').replace(' ', 'T'));
  return Number.isFinite(time) ? time : 0;
}
function sortCasesForList(items) {
  return [...items].sort((a, b) => {
    const pinDiff = Number(!!b.pinned) - Number(!!a.pinned);
    if (pinDiff) return pinDiff;
    const updatedDiff = caseUpdatedValue(b) - caseUpdatedValue(a);
    if (updatedDiff) return updatedDiff;
    return Number(b.id || 0) - Number(a.id || 0);
  });
}
function localPinnedCaseIds() {
  try {
    return new Set(JSON.parse(localStorage.getItem(LOCAL_PIN_KEY) || '[]').map(String));
  } catch (e) {
    return new Set();
  }
}
function setLocalCasePinned(id, pinned) {
  const ids = localPinnedCaseIds();
  const key = String(id);
  if (pinned) ids.add(key);
  else ids.delete(key);
  localStorage.setItem(LOCAL_PIN_KEY, JSON.stringify([...ids]));
}
function applyLocalCasePins(items) {
  const ids = localPinnedCaseIds();
  if (!ids.size) return [...items];
  return items.map(item => ids.has(String(item.id)) ? { ...item, pinned: true } : item);
}
function filterDue(items, due) {
  if (!due) return items;
  const today = new Date(); today.setHours(0,0,0,0);
  const max = due === '7d' ? 7 : due === '30d' ? 30 : null;
  return items.filter(item => {
    const date = parseDateLoose(item.hearing_at || item.deadline_at);
    if (!date) return false;
    date.setHours(0,0,0,0);
    const days = Math.round((date - today) / 86400000);
    if (due === 'overdue') return days < 0;
    return days >= 0 && days <= max;
  });
}
function offlineCasesByStatus(status) {
  const key = status === 'trash' ? 'trash' : status === 'archived' ? 'archived' : 'active';
  return state.offlineSnapshot?.cases?.[key] || [];
}
function allOfflineCases() {
  const cases = state.offlineSnapshot?.cases || {};
  return [...(cases.active || []), ...(cases.archived || []), ...(cases.trash || [])];
}
function offlineCaseById(id) {
  return allOfflineCases().find(item => Number(item.id) === Number(id));
}
function offlineOption(items, url) {
  const parsed = new URL(url, location.origin);
  const q = offlineText(parsed.searchParams.get('q') || '').trim();
  const limit = Number(parsed.searchParams.get('limit') || 200);
  const filtered = q ? items.filter(item => offlineText(item).includes(q)) : items;
  return { items: filtered.slice(0, limit) };
}
function offlineEvents(url) {
  const parsed = new URL(url, location.origin);
  const types = new Set((parsed.searchParams.get('types') || 'todo,hearing,preservation,appeal').split(',').filter(Boolean));
  const start = parseDateLoose(parsed.searchParams.get('start') || '1970-01-01');
  const end = parseDateLoose(parsed.searchParams.get('end') || '2100-12-31');
  const limit = Number(parsed.searchParams.get('limit') || 1000);
  const items = (state.offlineSnapshot?.events || []).filter(item => {
    if (!types.has(item.item_type || item.event_type)) return false;
    const due = parseDateLoose(item.due_at);
    return due && (!start || due >= start) && (!end || due <= end);
  });
  return { items: items.slice(0, limit) };
}
function offlineApi(url) {
  if (!state.offlineSnapshot) throw new Error('没有可用的离线缓存，请在联网时打开案件管理并完成缓存');
  const parsed = new URL(url, location.origin);
  const path = parsed.pathname;
  if (path === '/api/case-manager/dashboard') return state.offlineSnapshot.dashboard || { counts: {} };
  if (path === '/api/case-manager/cases') {
    const caseId = Number(parsed.searchParams.get('case_id') || 0);
    if (caseId) {
      const item = offlineCaseById(caseId);
      if (!item) throw new Error('离线缓存中未找到该案件');
      return item;
    }
    const status = parsed.searchParams.get('status') || 'active';
    const limit = Number(parsed.searchParams.get('limit') || 300);
    const items = sortCasesForList(applyLocalCasePins(filterItems(
      offlineCasesByStatus(status),
      parsed.searchParams.get('q') || '',
      parsed.searchParams.get('search_field') || 'all',
      caseSearchText
    )));
    return { items: items.slice(0, limit) };
  }
  if (path === '/api/case-manager/todos' || path === '/api/case-manager/hearings' || path === '/api/case-manager/preservations' || path === '/api/case-manager/appeals') {
    const key = path.split('/').pop();
    const limit = Number(parsed.searchParams.get('limit') || 300);
    const items = filterDue(filterItems(
      state.offlineSnapshot[key] || [],
      parsed.searchParams.get('q') || '',
      parsed.searchParams.get('search_field') || 'all',
      itemSearchText
    ), parsed.searchParams.get('due') || '');
    return { items: items.slice(0, limit) };
  }
  if (path === '/api/case-manager/prepaid-expenses') {
    const source = state.offlineSnapshot.prepaid_expenses || { items: [], summary: {}, categories: [], sync: {} };
    const dateFrom = parsed.searchParams.get('date_from') || '';
    const dateTo = parsed.searchParams.get('date_to') || '';
    const entryType = parsed.searchParams.get('entry_type') || '';
    const project = offlineText(parsed.searchParams.get('project') || '').trim();
    const category = parsed.searchParams.get('category') || '';
    const q = offlineText(parsed.searchParams.get('q') || '').trim();
    const items = (source.items || []).filter(item => {
      if (dateFrom && String(item.occurred_on || '') < dateFrom) return false;
      if (dateTo && String(item.occurred_on || '') > dateTo) return false;
      if (entryType && item.entry_type !== entryType) return false;
      if (project && !offlineText(item.project_name).includes(project)) return false;
      if (category && item.category !== category) return false;
      if (q && !offlineText([item.project_name,item.category,item.description].join(' ')).includes(q)) return false;
      return true;
    });
    return { ...source, items };
  }
  if (path === '/api/case-manager/events') return offlineEvents(url);
  if (path === '/api/case-manager/court-online/status') {
    const st = state.offlineSnapshot.court_online?.status || {};
    const layy = state.offlineSnapshot.court_online?.layy || [];
    const counts = { sp: 0, zx: 0, pc: 0 };
    layy.forEach(l => { const c = l.category === 'zx' ? 'zx' : l.category === 'pc' ? 'pc' : 'sp'; counts[c] += 1; });
    const num = v => Number(v) || 0;
    return {
      unread_count: num(st.unread_count),
      record_count: num(st.record_count) || (co.records || []).length,
      todo_count: num(st.todo_count) || (co.records || []).filter(r => r.kind === 'todo').length,
      message_count: num(st.message_count) || (co.records || []).filter(r => r.kind === 'message').length,
      delivery_count: num(st.delivery_count) || (co.records || []).filter(r => r.kind === 'delivery').length,
      case_count: num(st.case_count),
      case_trial_count: num(st.case_trial_count), execute_case_count: num(st.execute_case_count),
      bankruptcy_case_count: num(st.bankruptcy_case_count),
      layy_count: num(st.layy_count) || layy.length,
      layy_trial_count: num(st.layy_trial_count) || counts.sp,
      layy_execute_count: num(st.layy_execute_count) || counts.zx,
      layy_bankruptcy_count: num(st.layy_bankruptcy_count) || counts.pc,
      hearing_count: num(st.hearing_count),
    };
  }
  if (path === '/api/case-manager/court-online/records'
      || path === '/api/case-manager/court-online/cases'
      || path === '/api/case-manager/court-online/layy'
      || path === '/api/case-manager/court-online/hearings') {
    const kind = path.split('/').pop();
    const co = state.offlineSnapshot.court_online || {};
    const source = kind === 'records' ? (co.records || []) : (co[kind] || []);
    const q = offlineText(parsed.searchParams.get('q') || '').trim();
    const kindFilter = parsed.searchParams.get('kind') || '';
    const unreadOnly = parsed.searchParams.get('unread') === 'true';
    const ajlbFilter = parsed.searchParams.get('ajlb') || '';
    const items = source.filter(item => {
      if (kind === 'records' && kindFilter && item.kind !== kindFilter) return false;
      if (kind === 'records' && unreadOnly && !item.unread) return false;
      if (kind === 'cases' && ajlbFilter && item.ajlb !== ajlbFilter) return false;
      if (!q) return true;
      const hay = offlineText(Object.values(item).filter(v => typeof v === 'string' && v).join(' '));
      return hay.includes(q);
    });
    const page = Number(parsed.searchParams.get('page') || 1);
    const pageSize = Number(parsed.searchParams.get('page_size') || 50);
    const kindCounts = {};
    if (kind === 'records') {
      (co.records || []).forEach(item => { kindCounts[item.kind] = (kindCounts[item.kind] || 0) + 1; });
      kindCounts.total = (co.records || []).length;
    }
    return {
      items: items.slice((page - 1) * pageSize, page * pageSize),
      total: items.length,
      page, page_size: pageSize,
      kind_counts: kindCounts,
    };
  }
  if (path === '/api/case-manager/case-types') return offlineOption(state.offlineSnapshot.options?.case_types || [], url);
  if (path === '/api/case-manager/case-stages') return offlineOption(state.offlineSnapshot.options?.case_stages || [], url);
  if (path === '/api/case-manager/party-roles') return offlineOption(state.offlineSnapshot.options?.party_roles || [], url);
  if (path === '/api/case-manager/case-number-types') return offlineOption(state.offlineSnapshot.options?.case_number_types || [], url);
  if (path === '/api/case-manager/preservation-types') return offlineOption(state.offlineSnapshot.options?.preservation_types || [], url);
  if (path === '/api/case-manager/court-options') return offlineOption(state.offlineSnapshot.options?.courts || [], url);
  if (path === '/api/case-manager/series-options') {
    const kind = parsed.searchParams.get('kind') || '';
    const q = offlineText(parsed.searchParams.get('q') || '').trim();
    const limit = Math.max(10, Number(parsed.searchParams.get('limit') || 80));
    let items = [];
    if (kind === 'clients' || kind === 'opponents' || kind === 'parties') {
      const group = kind === 'clients' ? 'client' : kind === 'opponents' ? 'other' : '';
      const seen = new Map();
      allOfflineCases().forEach(c => (c.parties || []).forEach(p => {
        if (!p || !p.name) return;
        if (group && p.party_group !== group) return;
        if (!seen.has(p.name)) seen.set(p.name, { id: p.id ?? seen.size, value: p.name, label: p.name, identity_code: p.credit_code || '', meta: p.credit_code || '' });
      }));
      items = [...seen.values()];
    } else {
      const map = { case_types:'case_types', stages:'case_stages', party_roles:'party_roles', courts:'courts', number_types:'case_number_types' };
      items = (state.offlineSnapshot.options?.[map[kind]] || []).filter(Boolean).map(v => ({ value: v, label: v, meta: '' }));
    }
    if (q) items = items.filter(i => offlineText(i.value || i.label).includes(q) || offlineText(i.meta || '').includes(q));
    return { items: items.slice(0, limit) };
  }
  if (path === '/api/case-manager/case-lookup') {
    const q = parsed.searchParams.get('q') || '';
    const limit = Math.max(1, Math.min(200, Number(parsed.searchParams.get('limit') || 20)));
    const offset = Math.max(0, Number(parsed.searchParams.get('offset') || 0));
    const adapt = item => ({ ...item,
      clients: (item.parties || []).filter(party => party.party_group === 'client'),
      opponents: (item.parties || []).filter(party => party.party_group !== 'client'),
      children: (item.series_children || []).filter(child => child.source_status === 'active').map(child => adapt(child)) });
    const pool = offlineCasesByStatus('active').filter(item => !q ||
      caseSearchText(item).includes(offlineText(q)) || (item.series_children || []).some(child => child.source_status === 'active' && caseSearchText(child).includes(offlineText(q))))
      .sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')) || Number(b.id) - Number(a.id));
    return { items: pool.slice(offset, offset + limit).map(adapt), has_more: offset + limit < pool.length, next_offset: offset + Math.min(limit, Math.max(0, pool.length - offset)) };
  }
  throw new Error('离线模式下暂不支持该功能');
}

function $(id) { return document.getElementById(id); }
function esc(v) {
  return String(v ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}
function fmt(v) {
  if (!v) return '';
  return String(v).replace('T', ' ').slice(0, 16);
}
function dateOnly(v) {
  if (!v) return '';
  return String(v).slice(0, 10);
}
function parseDateLoose(v) {
  if (!v) return null;
  const text = String(v).trim().replace(/\//g, '-').replace(' ', 'T');
  const date = new Date(text.length === 10 ? `${text}T00:00:00` : text);
  return Number.isNaN(date.getTime()) ? null : date;
}
async function fetchWithTimeout(url, options = {}, timeoutMs = 0) {
  if (!timeoutMs || typeof AbortController === 'undefined') return fetch(url, options);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } catch (error) {
    if (error?.name === 'AbortError' || /aborted/i.test(String(error?.message || ''))) {
      throw Object.assign(new Error('请求等待超时'), { kind: 'timeout', cause: error });
    }
    throw Object.assign(new Error(error?.message || '当前无法连接服务器'), { kind: 'offline', cause: error });
  } finally {
    clearTimeout(timer);
  }
}
function caseManagerApiTimeout(method, isCaseManagerRead, url = '') {
  const path = String(url);
  if (path.includes('/api/case-manager/court-online/browser/reveal')) return 120000;
  if (/\/matters\/[^/]+\/\d+\/local-links\/select/.test(path)) return 125000;
  if (path.includes('/api/case-manager/calendar/sync')) return 10 * 60 * 1000;
  if (path.includes('/api/case-manager/calendar/')) return 120000;
  if (path.includes('/api/case-manager/hearings/recognize') || path.includes('/api/case-manager/preservations/recognize')) return 3 * 60 * 1000;
  if (path.includes('/api/case-manager/opponents/recognize')) return 3 * 60 * 1000;
  if (path.includes('/api/case-manager/import/')) return 5 * 60 * 1000;
  if (path.includes('/documents/') && path.includes('/browser-download')) return 6 * 60 * 1000;
  // These requests are monitored by live byte progress; large bundles can exceed 30 seconds.
  if (method === 'POST' && /\/judicial-messages\/\d+\/documents\/\d+\/download$/.test(path)) return 0;
  if (method !== 'GET') return 30000;
  if (!isCaseManagerRead) return 15000;
  if (state.offlineMode && state.offlineReady) return 0;
  return state.offlineReady ? 6000 : 10000;
}
async function parseApiResponse(res) {
  const text = await res.text().catch(() => '');
  let data = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch (e) {
      data = {};
    }
  }
  const contentType = String(res.headers.get('content-type') || '').toLowerCase();
  const looksLikeLoginPage = contentType.includes('text/html')
    && /<title>\s*登录法律操作系统\s*<\/title>|<form[^>]+action=["']\/login["']/i.test(text);
  // Only the local access gate can expire the Stella session. Court and other
  // integrations also return 401, which must remain a visible feature error.
  const localAuthRequired = res.status === 401 && (
    res.headers.get('x-apex-auth-required') === 'local'
    || (!contentType.includes('json') && text.trim() === 'Authentication required')
  );
  if (localAuthRequired || looksLikeLoginPage) {
    throw Object.assign(new Error('登录状态已失效'), { kind: 'unauthenticated', status: res.status });
  }
  if (!res.ok) {
    const message = data.detail || data.message || (text ? text.slice(0, 500) : '') || `请求失败（HTTP ${res.status}）`;
    throw Object.assign(new Error(message), { kind: 'server', status: res.status });
  }
  if (text && !contentType.includes('json')) {
    throw Object.assign(new Error('服务器返回了无法识别的内容'), { kind: 'server', status: res.status });
  }
  return data;
}

let loginRedirectScheduled = false;
function redirectToCaseManagerLogin() {
  if (loginRedirectScheduled) return;
  loginRedirectScheduled = true;
  window.apexRecordStartup?.('authentication-required');
  const target = '/login?next=' + encodeURIComponent('/?workspace=cases');
  // A login inside the case iframe cannot renew the main app's startup path.
  try {
    if (window.parent !== window && window.parent.location.origin === location.origin) {
      window.parent.location.assign(target);
      return;
    }
  } catch (_) {}
  window.location.assign(target);
}
async function api(url, options = {}) {
  const method = String(options.method || 'GET').toUpperCase();
  const urlText = String(url);
  const bypassOffline = !!options.bypassOffline;
  const isCaseManagerRead = method === 'GET'
    && urlText.startsWith('/api/case-manager/')
    && !urlText.includes('/offline-snapshot');
  if (method !== 'GET' && !requireOnlineAction()) throw new Error('离线模式下仅支持检索和查看，联网后可新增、编辑或删除');
  if (isCaseManagerRead && state.offlineMode && state.offlineReady && !bypassOffline) {
    return offlineApi(url);
  }
  try {
    const timeoutMs = caseManagerApiTimeout(method, isCaseManagerRead, urlText);
    const res = await fetchWithTimeout(url, options, timeoutMs);
    const data = await parseApiResponse(res);
    noteCaseServerSuccess();
    if (isCaseManagerRead) {
      state.offlineMode = false;
      state.offlineToastShown = false;
      updateOfflineStatus();
    }
    return data;
  } catch (e) {
    if (e?.kind === 'unauthenticated') {
      redirectToCaseManagerLogin();
      throw e;
    }
    // A rejected request is an online response, not a connectivity failure.
    if (e?.kind === 'server' && e.status >= 400 && e.status < 500) {
      noteCaseServerSuccess();
      throw e;
    }
    if (isCaseManagerRead && !bypassOffline) {
      const data = offlineApi(url);
      const confirmedOffline = noteCaseServerFailure();
      if (confirmedOffline) {
        state.offlineMode = true;
        updateOfflineStatus();
      }
      if (confirmedOffline && !state.offlineToastShown) {
        toast('已切换到离线缓存，可继续检索和查看案件');
        state.offlineToastShown = true;
      }
      return data;
    }
    if (e?.kind === 'timeout' || e?.name === 'AbortError' || /aborted/i.test(String(e?.message || ''))) {
      if (urlText.includes('/api/case-manager/calendar/sync')) {
        throw new Error('请求等待超时：日历同步耗时较长，请稍后查看结果或减少本次同步数量后重试。');
      }
      throw new Error('请求等待超时，请稍后重试。');
    }
    throw e;
  }
}
let recoveringOnline = false;
function noteCaseServerSuccess() {
  state.serverOnline = true;
  state.lastServerSuccessAt = Date.now();
  state.failedServerProbes = 0;
  state.offlineMode = false;
  state.offlineToastShown = false;
  updateOfflineStatus();
}
function noteCaseServerFailure(force = false) {
  state.failedServerProbes += 1;
  const recentlySucceeded = state.lastServerSuccessAt && Date.now() - state.lastServerSuccessAt < 15000;
  if (!force && (recentlySucceeded || (state.serverOnline === true && state.failedServerProbes < 2))) return false;
  state.serverOnline = false;
  return true;
}
async function applyCaseServerConnection(online) {
  const wasOnline = state.serverOnline;
  if (!online) {
    if (noteCaseServerFailure()) enterOfflineMode();
    return state.serverOnline === true;
  }
  noteCaseServerSuccess();
  if (wasOnline === true && !state.offlineMode) return true;
  await syncPendingCaseOps();
  await refreshAll(false);
  // 网络恢复时立即写入完整快照，避免手机下次离线仍只看到旧记录。
  await syncOfflineSnapshot(true);
  return true;
}
async function recoverOnlineIfPossible() {
  if (recoveringOnline) return;
  recoveringOnline = true;
  state.lastOnlineProbeAt = 0;
  try {
    const timeout = state.serverOnline === false ? 10000 : 5000;
    await applyCaseServerConnection(await localServerReachable(timeout));
  } catch (e) {
    updateOfflineStatus();
  } finally {
    recoveringOnline = false;
  }
}
async function localServerReachable(timeoutMs = 5000) {
  try {
    const status = await readPwaSessionStatus(timeoutMs);
    if (status.server_reachable && !status.authenticated) redirectToCaseManagerLogin();
    return !!status.authenticated;
  } catch (e) {
    return false;
  }
}

async function readPwaSessionStatus(timeoutMs = 1500) {
  const response = await fetchWithTimeout(`${PWA_SESSION_STATUS_URL}?_=${Date.now()}`, { cache: 'no-store' }, timeoutMs);
  const contentType = String(response.headers.get('content-type') || '').toLowerCase();
  if (!response.ok || !contentType.includes('json')) {
    throw Object.assign(new Error('服务器状态不可用'), { kind: response.status === 401 ? 'unauthenticated' : 'server' });
  }
  const status = await response.json();
  return {
    server_reachable: status?.server_reachable === true,
    authenticated: status?.authenticated === true,
    shell_version: String(status?.shell_version || ''),
  };
}
function enterOfflineMode() {
  if (!state.offlineReady) return;
  const alreadyOffline = state.offlineMode;
  state.offlineMode = true;
  updateOfflineStatus();
  if (alreadyOffline) return;
  render();
  if (['cases','todos','hearings','preservations','appeals'].includes(activeTab)) loadList();
  if (activeTab === 'caseCalendar') loadCaseCalendar();
}
function toast(message) {
  const el = $('toast');
  el.textContent = message;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 2200);
}

async function refreshAll(updateOfflineCache = true) {
  await loadDashboard();
  render();
  if (['cases','todos','hearings','preservations','appeals'].includes(activeTab)) await loadList();
  if (activeTab === 'caseCalendar') await loadCaseCalendar();
  if (activeTab === 'calendar') await loadCalendar();
  if (activeTab === 'judicialMessages') await loadJudicialMessages();
  if (activeTab === 'courtOnline') await loadCourtOnline();
  if (activeTab === 'prepaidExpenses') await loadPrepaidExpenses();
  if (updateOfflineCache && !state.offlineMode) scheduleCaseOfflineSnapshot(true, 5000);
}
async function loadDashboard() {
  state.dashboard = await api('/api/case-manager/dashboard');
  renderStats();
}
function renderStats() {
  const c = state.dashboard?.counts || {};
  const badges = {
    caseCountBadge: c.cases || 0,
    todoCountBadge: c.todos || 0,
    hearingCountBadge: c.hearings || 0,
    preservationCountBadge: c.preservations || 0,
    appealCountBadge: c.appeals || 0,
    judicialMessageBadge: c.judicial_messages_pending || 0,
  };
  Object.entries(badges).forEach(([id, value]) => {
    const badge = $(id);
    if (badge) badge.textContent = value;
  });
  updateMobileTabLabel();
}

function updateMobileTabLabel() {
  const visibleTab = activeTab === 'calendar' ? 'caseCalendar' : activeTab;
  const active = document.querySelector(`.tab[data-tab="${visibleTab}"]`);
  const label = $('mobileTabLabel');
  if (!active || !label) return;
  const text = [...active.childNodes].find(node => node.nodeType === Node.TEXT_NODE)?.textContent?.trim();
  label.textContent = text || tabMeta[activeTab]?.label || '案件管理';
}
function toggleMobileTabs(event) {
  event?.stopPropagation();
  const tabs = $('tabs');
  const toggle = $('mobileTabToggle');
  const open = !tabs?.classList.contains('mobile-open');
  tabs?.classList.toggle('mobile-open', open);
  toggle?.setAttribute('aria-expanded', open ? 'true' : 'false');
}
function closeMobileTabs() {
  $('tabs')?.classList.remove('mobile-open');
  $('mobileTabToggle')?.setAttribute('aria-expanded', 'false');
}
function renderMobileFilters() {
  const host = $('mobileFilters');
  if (!host) return;
  if (!['cases','todos','hearings','preservations','appeals'].includes(activeTab)) {
    host.innerHTML = '';
    host.style.display = 'none';
    return;
  }
  host.style.display = '';
  const mobileFieldLabels = {
    all: '全部字段', client: '委托人名称', title: '案件名称', opponent: '对方当事人',
    case_type: '案件类型（案由）', current_stage: '当前阶段'
  };
  const mobileFieldLabel = mobileFieldLabels[state.searchField] || '全部字段';
  host.innerHTML = `
    <label class="mobile-filter-field-shell ${state.searchField !== 'all' ? 'active' : ''}" title="筛选字段：${esc(mobileFieldLabel)}">
      <svg viewBox="0 0 18 18" fill="none" aria-hidden="true"><path d="M3 4h12l-4.7 5.2v3.6l-2.6 1.3V9.2L3 4z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>
      <select class="mobile-filter-field" aria-label="筛选字段：${esc(mobileFieldLabel)}" onchange="state.searchField=this.value; renderMobileFilters(); loadList()">
        ${option('all', '全部字段', state.searchField)}
        ${option('client', '委托人名称', state.searchField)}
        ${option('title', '案件名称', state.searchField)}
        ${option('opponent', '对方当事人', state.searchField)}
        ${option('case_type', '案件类型（案由）', state.searchField)}
        ${option('current_stage', '当前阶段', state.searchField)}
      </select>
    </label>
    <input class="input mobile-filter-search" aria-label="搜索" placeholder="搜索" value="${esc(state.q)}" oninput="state.q=this.value; debounceLoad()">
    ${activeTab === 'cases' ? '' : `<select class="mobile-filter-due" aria-label="期限筛选" onchange="state.due=this.value; loadList()">
      ${option('', '期限', state.due)}
      ${option('overdue', '逾期', state.due)}
      ${option('7d', '7日', state.due)}
      ${option('30d', '30日', state.due)}
    </select>`}
    ${activeTab === 'cases' ? '' : hideOverdueToggle('mobile')}
    ${activeTab === 'cases' && !isOfflineReadonly() ? `
      <button class="btn mobile-filter-edit mobile-client-btn" onclick="openClientManager()" type="button" aria-label="委托人管理">委托</button>
      <button class="btn mobile-filter-edit mobile-client-btn" onclick="openOpponentManager()" type="button" aria-label="对方管理">对方</button>
      <button class="btn mobile-filter-edit mobile-edit-btn ${state.caseListEditing ? 'active' : ''}" onclick="toggleCaseListEditing()" type="button">${state.caseListEditing ? '完成' : '编辑'}</button>
    ` : ''}
  `;
}
function switchTab(tab) {
  activeTab = tab;
  rememberActiveTab(tab);
  state.q = '';
  state.searchField = 'all';
  state.due = '';
  state.caseListEditing = false;
  state.selectedCaseIds.clear();
  syncActiveTabNav();
  closeMobileTabs();
  updateMobileTabLabel();
  renderMobileFilters();
  updateTopAdd();
  render();
  if (['cases','todos','hearings','preservations','appeals'].includes(tab)) loadList();
  if (tab === 'caseCalendar') loadCaseCalendar();
  if (tab === 'calendar') loadCalendar();
  if (tab === 'judicialMessages') loadJudicialMessages();
  if (tab === 'courtOnline') loadCourtOnline();
  if (tab === 'prepaidExpenses') {
    loadPrepaidExpenses();
    if (!isOfflineReadonly()) syncPrepaidExpenses(false);
  }
  notifyCaseManagerContext(currentCaseManagerPageLabel());
}

function syncActiveTabNav() {
  const selectedTab = activeTab === 'calendar' ? 'caseCalendar' : activeTab;
  document.querySelectorAll('.tab').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === selectedTab);
  });
}

async function openHomeReminderItem(view, itemId) {
  if (view === 'judicialMessages') {
    switchTab('judicialMessages');
    if (itemId) window.setTimeout(() => openJudicialMessage(itemId), 80);
    return;
  }
  if (!tabMeta[view]) return;
  switchTab(view);
  if (!itemId) return;
  try {
    const data = await api(tabMeta[view].endpoint);
    const item = (data.items || []).find(entry => Number(entry.id) === Number(itemId));
    if (!item) return;
    state.items[view] = groupSeriesReminderItems(data.items || [], view);
    openDetail(view, itemId, encodeURIComponent(JSON.stringify(item)));
  } catch (e) {
    toast(e.message || '提醒详情加载失败');
  }
}

window.addEventListener('message', event => {
  if (event.origin !== location.origin) return;
  if (event.data?.type === 'openCourtRecord') {
    state.courtOnline.focusRecordId = Number(event.data.recordId || 0);
    switchTab('courtOnline');
    return;
  }
  if (event.data?.type === 'courtOnlineLocate') {
    const kind = String(event.data.kind || '');
    if (kind) {
      state.courtOnline.kind = kind;
      state.courtOnline.q = String(event.data.query || '').trim();
      state.courtOnline.page = 1;
      state.courtOnline.unread = false;
    }
    if (activeTab !== 'courtOnline') switchTab('courtOnline');
    loadCourtOnline();
    return;
  }
  if (event.data?.type === 'openCaseResearchWorkspace') {
    const caseId = Number(event.data.caseId || 0);
    const section = event.data.section === 'memo' ? 'memo' : 'ledger';
    if (!caseId) return;
    openDetail('cases', caseId).then(() => openCaseResearchWorkspace(caseId, section)).catch(e => toast(e.message || '案件详情加载失败'));
    return;
  }
  if (event.data?.type === 'openHomeReminderItem') openHomeReminderItem(String(event.data.view || ''), Number(event.data.itemId || 0));
});

function updateTopAdd() {
  const btn = $('topAddBtn');
  if (!btn) return;
  const menu = $('topAddMenu');
  const visible = !!tabMeta[activeTab] || activeTab === 'prepaidExpenses';
  if (menu) menu.style.display = visible ? 'inline-flex' : 'none';
  menu?.classList.toggle('single-action', activeTab === 'prepaidExpenses');
  btn.style.display = 'inline-flex';
  btn.disabled = isOfflineReadonly() && !canWriteCurrentTabOffline();
  if (activeTab === 'prepaidExpenses') {
    if (window.matchMedia('(max-width: 900px)').matches) {
      btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 2v12M2 8h12" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>`;
    } else {
      btn.textContent = '新增收支';
    }
    btn.setAttribute('aria-label', '新增团队费用收支记录');
  } else if (tabMeta[activeTab]) {
    if (window.matchMedia('(max-width: 900px)').matches) {
      btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 2v12M2 8h12" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>`;
      btn.setAttribute('aria-label', `新增${tabMeta[activeTab].label}`);
    } else {
      btn.textContent = `新增${tabMeta[activeTab].label}`;
      btn.setAttribute('aria-label', `新增${tabMeta[activeTab].label}`);
    }
  }
}

function runTopAddAction() {
  if (activeTab === 'prepaidExpenses') return openPrepaidEditor();
  if (activeTab === 'cases') return openNewCaseDetail();
  if (tabMeta[activeTab]) openEditor(activeTab);
}

async function loadList() {
  const meta = tabMeta[activeTab];
  const params = new URLSearchParams();
  if (state.q) params.set('q', state.q);
  if (state.searchField && state.searchField !== 'all') params.set('search_field', state.searchField);
  if (state.due) params.set('due', state.due);
  const data = await api(`${meta.endpoint}?${params}`);
  state.items[activeTab] = activeTab === 'cases'
    ? sortCasesForList(applyLocalCasePins(data.items || []))
    : groupSeriesReminderItems(data.items || [], activeTab);
  if (activeTab === 'cases') {
    state.selectedCaseIds.clear();
    await loadCaseCollections();
  }
  renderTable();
}

function groupSeriesReminderItems(items, tab) {
  const rows = [...items];
  return rows.sort((a, b) => compareReminderItems(a, b, tab));
}
function getReminderSortValue(item, tab) { return tab === 'todos' ? item.remind_at : tab === 'hearings' ? item.hearing_at : item.deadline_at; }
function compareReminderItems(a, b, tab) {
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const oldCutoff = new Date(today); oldCutoff.setDate(oldCutoff.getDate() - 15);
  const sortInfo = item => {
    const value = String(getReminderSortValue(item, tab) || '');
    const date = new Date(value.replace(' ', 'T'));
    if (!value || Number.isNaN(date.getTime())) return { bucket: 3, time: 0 };
    date.setHours(0, 0, 0, 0);
    return {
      bucket: date < oldCutoff ? 2 : date < today ? 0 : 1,
      time: new Date(value.replace(' ', 'T')).getTime(),
    };
  };
  const left = sortInfo(a);
  const right = sortInfo(b);
  if (left.bucket !== right.bucket) return left.bucket - right.bucket;
  if (left.bucket === 0 || left.bucket === 2) return right.time - left.time;
  if (left.bucket === 1) return left.time - right.time;
  return String(b.id).localeCompare(String(a.id), undefined, { numeric: true });
}
function openSeriesReminderGroup(item) {
  const items = item.group_items || [];
  state.editing = { tab: activeTab, item, mode:'detail' };
  $('drawerTitle').textContent = `${item.series_title || item.title} · ${item.group_date} · ${items.length}项`;
  $('drawerBody').innerHTML = `<section class="detail-section"><h3>涉及子案</h3><div class="record-list">${items.map((entry,index)=>`<article class="record-card"><div class="record-card-head"><span>${index+1}. ${esc(entry.series_code||'')} ${esc(entry.child_display_name||entry.title||'')}</span></div><dl class="record-fields"><dt>事项</dt><dd>${esc(entry.todo_title||entry.reminder_type||entry.preservation_type||entry.appeal_type||'')}</dd><dt>时间</dt><dd>${esc(fmt(getReminderSortValue(entry,activeTab)))}</dd><dt class="full-label">详情</dt><dd class="full-value">${esc(entry.notes||entry.location||entry.asset_content||entry.case_no||'')}</dd></dl></article>`).join('')}</div></section>`;
  $('drawerFoot').innerHTML = `<button class="btn" onclick="closeEditor()">关闭</button><button class="btn primary" onclick="closeEditor(); openSeriesWorkspace(${Number(item.series_id)})">打开系列案件</button>`;
  $('drawerMask').classList.add('show'); $('drawer').classList.add('show','detail-mode');
}

const LIST_FIELD_OPTIONS = [
  ['all', '全部字段'],
  ['client', '客户名称'],
  ['title', '案件名称'],
  ['opponent', '对方当事人名称'],
  ['case_type', '案件类型'],
  ['current_stage', '当前阶段'],
];
const LIST_DUE_OPTIONS = [['', '全部期限'], ['overdue', '逾期'], ['7d', '7日内'], ['30d', '30日内']];
const listHeroIcons = {
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="6.4"/><path d="m20.3 20.3-3.9-3.9"/></svg>',
  users: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="8" r="3.2"/><path d="M3.5 19c.6-3 2.8-4.6 5.5-4.6s4.9 1.6 5.5 4.6"/><circle cx="16.5" cy="9" r="2.6"/><path d="M16.8 14.6c2.2.2 3.5 1.6 3.9 3.9"/></svg>',
  opponent: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h16"/><path d="M6 20V6.8L12 4l6 2.8V20"/><path d="M9.5 20v-4.4h5V20"/></svg>',
  edit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h4.2L19.4 8.8a2.1 2.1 0 0 0-3-3L5.2 17 4 20z"/><path d="M13.5 6.5l3 3"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m4.5 12.5 5 5 10-11"/></svg>',
  trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M9.5 7V4.8h5V7M6.5 7l1 13h9l1-13"/><path d="M10 11v5.5M14 11v5.5"/></svg>',
  archive: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="4.5" width="17" height="4.6" rx="1.2"/><path d="M5.4 9.1V19a1 1 0 0 0 1 1h11.2a1 1 0 0 0 1-1V9.1"/><path d="M10 13h4"/></svg>',
};
function listStatusLabel(tab) {
  return { cases: '案件信息', todos: '待办事项', hearings: '开庭提醒', preservations: '财产保全', appeals: '上诉/异议期' }[tab] || '案件管理';
}
function listSearchPlaceholder(tab) {
  return tab === 'cases' ? '搜索案件名称、客户、对方当事人或案号' : '搜索案件名称、案号或事项内容';
}
function listStatusItem(label, value, tone = '', title = '') {
  return `<div class="jm-status-item ${tone}"${title ? ` title="${esc(title)}"` : ''}><i class="jm-dot"></i><span class="jm-status-label">${esc(label)}</span><strong>${esc(value)}</strong></div>`;
}
function listHeroStatusItems(tab, items) {
  const parts = [listStatusItem('离线缓存', offlineStatusText() || '准备离线缓存', state.offlineMode ? 'warn' : state.offlineReady ? 'ok' : '', '点击顶栏左侧图标可查看离线缓存详情')];
  if (tab === 'cases') {
    const pinned = items.filter(item => item.pinned).length;
    const series = items.filter(item => item.case_kind === 'series').length;
    parts.push(listStatusItem('置顶案件', pinned ? `${pinned} 个` : '未置顶', pinned ? 'ok' : '', '在列表中置顶显示的案件'));
    parts.push(listStatusItem('系列案件', `${series} 组`, 'ok'));
  } else {
    const overdue = items.filter(item => isItemOverdue(item)).length;
    parts.push(listStatusItem('逾期事项', overdue ? `${overdue} 条待处理` : '暂无逾期', overdue ? 'warn' : 'ok'));
  }
  return parts.join('<i class="jm-status-sep"></i>');
}
function listHeroActionsHtml(tab) {
  if (tab !== 'cases' || isOfflineReadonly()) return '';
  const editing = state.caseListEditing;
  return `<div class="jm-hero-actions">
    ${editing ? `
      <button class="jm-ghost-btn danger" title="删除所选案件（进入垃圾站）" onclick="bulkDeleteCases()">${listHeroIcons.trash}批量删除</button>
      <button class="jm-ghost-btn" title="确认所选案件已结案并归档" onclick="bulkArchiveCases()">${listHeroIcons.archive}确认已结案</button>` : `
      <button class="jm-ghost-btn" title="维护委托人档案" onclick="openClientManager()">${listHeroIcons.users}委托人管理</button>
      <button class="jm-ghost-btn" title="维护对方当事人档案" onclick="openOpponentManager()">${listHeroIcons.opponent}对方管理</button>`}
    <button class="jm-scan-btn" title="${editing ? '退出批量编辑模式' : '进入批量编辑模式'}" onclick="toggleCaseListEditing()">${editing ? listHeroIcons.check : listHeroIcons.edit}<span class="jm-scan-label">${editing ? '完成编辑' : '编辑列表'}</span></button>
  </div>`;
}
function listHeroHtml(tab) {
  const items = state.items[tab] || [];
  const isCases = tab === 'cases';
  const dueSegs = isCases ? '' : `<div class="jm-seg" role="tablist" aria-label="期限筛选">${LIST_DUE_OPTIONS.map(([value, label]) => `<button class="jm-seg-item ${state.due === value ? 'active' : ''}" role="tab" aria-selected="${state.due === value}" onclick="setListDue('${value}')">${label}</button>`).join('')}</div>`;
  const fieldLabel = (LIST_FIELD_OPTIONS.find(([value]) => value === state.searchField) || LIST_FIELD_OPTIONS[0])[1];
  const fieldDd = `<div class="jm-dd" id="listFieldDd"><button type="button" class="jm-field jm-dd-trigger" onclick="toggleListFieldDropdown(event)" aria-haspopup="listbox" aria-expanded="false"><span class="jm-dd-label">${esc(fieldLabel)}</span><i class="jm-dd-caret"></i></button><div class="jm-dd-menu" role="listbox" aria-label="筛选字段">${LIST_FIELD_OPTIONS.map(([value, label]) => `<button type="button" class="jm-dd-option${state.searchField === value ? ' active' : ''}" data-value="${value}">${esc(label)}</button>`).join('')}</div></div>`;
  const searchField = `<label class="jm-search-field">${listHeroIcons.search}<input placeholder="${esc(listSearchPlaceholder(tab))}" value="${esc(state.q)}" oninput="state.q=this.value; debounceLoad()"></label>`;
  const overdueToggle = isCases ? '' : hideOverdueToggle();
  return `<div class="jm-hero-wrap list-hero-wrap">
      <div class="jm-aurora" aria-hidden="true"><i></i><i></i><i></i></div>
      <header class="jm-hero list-hero">
        <div class="jm-hero-top">
          <div class="jm-hero-title"><h2>${esc(listStatusLabel(tab))}</h2><span class="jm-hero-total" id="listHeroTotal">共 ${items.length} 条</span></div>
          <div class="jm-status-strip" id="listHeroStatus">${listHeroStatusItems(tab, items)}</div>
          ${listHeroActionsHtml(tab)}
        </div>
        <div class="jm-filter-row">${dueSegs}${fieldDd}${searchField}${overdueToggle}</div>
      </header>
    </div>`;
}
function updateListHeroMeta() {
  if (!['cases', 'todos', 'hearings', 'preservations', 'appeals'].includes(activeTab)) return;
  const items = state.items[activeTab] || [];
  const total = $('listHeroTotal');
  if (total) total.textContent = `共 ${items.length} 条`;
  const strip = $('listHeroStatus');
  if (strip) strip.innerHTML = listHeroStatusItems(activeTab, items);
}
function render() {
  renderMobileFilters();
  if (activeTab === 'import') return renderImport();
  if (activeTab === 'caseCalendar') return renderCaseCalendar();
  if (activeTab === 'calendar') return renderCalendar();
  if (activeTab === 'judicialMessages') return renderJudicialMessages();
  if (activeTab === 'courtOnline') return renderCourtOnline();
  if (activeTab === 'prepaidExpenses') return renderPrepaidExpenses();
  $('content').innerHTML = `${listHeroHtml(activeTab)}
    <div class="table-wrap"><div class="empty">加载中...</div></div>`;
  renderTable();
}

function prepaidMoney(value) {
  const number = Number(value || 0);
  return new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY', minimumFractionDigits: 2 }).format(number);
}

function prepaidFilterParams() {
  const f = state.prepaidExpenses.filters;
  const params = new URLSearchParams();
  if (f.dateFrom) params.set('date_from', f.dateFrom);
  if (f.dateTo) params.set('date_to', f.dateTo);
  if (f.entryType) params.set('entry_type', f.entryType);
  if (f.project) params.set('project', f.project);
  if (f.category) params.set('category', f.category);
  if (f.q) params.set('q', f.q);
  return params;
}

async function loadPrepaidExpenses() {
  try {
    const data = await api(`/api/case-manager/prepaid-expenses?${prepaidFilterParams()}`);
    state.prepaidExpenses.items = data.items || [];
    state.prepaidExpenses.summary = data.summary || { balance: 0, advance: 0, expense: 0, record_count: 0 };
    state.prepaidExpenses.categories = data.categories || state.prepaidExpenses.categories;
    state.prepaidExpenses.presets = data.presets || state.prepaidExpenses.presets;
    state.prepaidExpenses.sync = data.sync || {};
    if (activeTab === 'prepaidExpenses') renderPrepaidExpenses();
  } catch (error) {
    if (activeTab === 'prepaidExpenses') {
      $('content').innerHTML = `<div class="empty">${esc(error.message || '团队费用管理加载失败')}</div>`;
    }
  }
}

function prepaidSyncDescription(sync) {
  if (!sync?.configured) return '尚未配置飞书表单同步，本地记账功能可正常使用';
  if (sync.last_error) return `最近同步异常：${sync.last_error}`;
  if (sync.project_options_error) return `案件选项同步异常：${sync.project_options_error}`;
  if (sync.last_success_at) {
    const result = sync.last_result || {};
    return `最近同步 ${fmt(sync.last_success_at)} · 新增 ${Number(result.imported || 0)} 条 · 待修正 ${Number(sync.issue_count || 0)} 条`;
  }
  return '飞书已配置，等待首次同步';
}

function prepaidTableRows(items) {
  if (!items.length) return `<tr><td colspan="8"><div class="empty">当前筛选条件下暂无收支记录</div></td></tr>`;
  return items.map(item => {
    const amountClass = item.entry_type === 'advance' ? 'advance' : 'expense';
    const signed = item.entry_type === 'advance' ? `+${prepaidMoney(item.amount)}` : `−${prepaidMoney(item.amount)}`;
    const running = Number(item.running_balance || 0);
    return `<tr>
      <td>${esc(dateOnly(item.occurred_on))}</td>
      <td><span class="tag">${esc(item.entry_type_label || '')}</span>${item.source_type === 'feishu' ? '<span class="prepaid-source-badge">来自飞书</span>' : ''}</td>
      <td><div class="truncate" title="${esc(item.project_name || '')}">${esc(item.project_name || '—')}</div></td>
      <td>${item.category ? `<span class="tag">${esc(item.category)}</span>` : '—'}</td>
      <td><div class="prepaid-content-main">${esc(item.description || (item.entry_type === 'advance' ? '团队备用金' : '—'))}</div></td>
      <td class="prepaid-amount ${amountClass}">${signed}</td>
      <td class="prepaid-running-balance ${running < 0 ? 'negative' : ''}">${prepaidMoney(running)}</td>
      <td class="action-cell"><div class="actions">
        <button class="btn" type="button" onclick="openPrepaidEditorById(${Number(item.id)})">编辑</button>
        <button class="btn danger" type="button" onclick="deletePrepaidExpense(${Number(item.id)})">删除</button>
      </div></td>
    </tr>`;
  }).join('');
}

function prepaidMobileCards(items) {
  if (!items.length) return '<div class="empty">当前筛选条件下暂无收支记录</div>';
  return items.map(item => {
    const amountClass = item.entry_type === 'advance' ? 'advance' : 'expense';
    const signed = item.entry_type === 'advance' ? `+${prepaidMoney(item.amount)}` : `−${prepaidMoney(item.amount)}`;
    return `<article class="prepaid-mobile-card">
      <div class="prepaid-mobile-head"><strong>${esc(item.description || item.entry_type_label || '收支记录')}</strong><span class="prepaid-amount ${amountClass}">${signed}</span></div>
      <p>${esc(item.project_name || '未关联项目')}${item.category ? ` · ${esc(item.category)}` : ''}${item.source_type === 'feishu' ? '<span class="prepaid-source-badge">来自飞书</span>' : ''}</p>
      <div class="prepaid-mobile-foot"><span>${esc(dateOnly(item.occurred_on))} · 余额 ${esc(prepaidMoney(item.running_balance))}</span><span class="prepaid-mobile-actions"><button class="btn" type="button" onclick="openPrepaidEditorById(${Number(item.id)})">编辑</button><button class="btn danger" type="button" onclick="deletePrepaidExpense(${Number(item.id)})">删除</button></span></div>
    </article>`;
  }).join('');
}

function renderPrepaidExpenses() {
  const data = state.prepaidExpenses;
  const summary = data.summary || {};
  const filters = data.filters;
  const sync = data.sync || {};
  const syncClass = sync.last_error ? 'error' : sync.configured && sync.last_success_at ? 'ready' : '';
  $('content').innerHTML = `<section class="prepaid-page">
    <div class="prepaid-summary">
      <article class="prepaid-summary-card balance"><span>团队备用金剩余金额</span><strong class="${Number(summary.balance || 0) < 0 ? 'negative' : ''}">${prepaidMoney(summary.balance)}</strong></article>
      <article class="prepaid-summary-card advance"><span>累计团队备用金</span><strong>${prepaidMoney(summary.advance)}</strong></article>
      <article class="prepaid-summary-card expense"><span>累计团队支出</span><strong>${prepaidMoney(summary.expense)}</strong></article>
    </div>
    <div class="prepaid-sync-strip">
      <div class="prepaid-sync-copy"><span class="prepaid-sync-dot ${syncClass}"></span><strong>飞书表单同步</strong><span>${esc(prepaidSyncDescription(sync))}</span></div>
      <div class="prepaid-sync-actions">
        ${state.prepaidExpenses.settings?.form_url || state.prepaidExpenses.settings?.base_url ? `<button class="btn" type="button" onclick="openPrepaidFeishuForm()">打开表单</button>` : ''}
        <button class="btn" type="button" onclick="openPrepaidFeishuSettings()"><span>同步设置</span>⚙</button>
        <button class="btn" type="button" onclick="syncPrepaidExpenses(true)" ${state.prepaidExpenses.syncing || isOfflineReadonly() ? 'disabled' : ''}><span>${state.prepaidExpenses.syncing ? '同步中' : '立即同步'}</span>↻</button>
      </div>
    </div>
    <div class="prepaid-toolbar">
      <div class="prepaid-filters">
        <input class="input prepaid-date" type="date" aria-label="开始日期" value="${esc(filters.dateFrom)}" onchange="state.prepaidExpenses.filters.dateFrom=this.value;loadPrepaidExpenses()">
        <input class="input prepaid-date" type="date" aria-label="结束日期" value="${esc(filters.dateTo)}" onchange="state.prepaidExpenses.filters.dateTo=this.value;loadPrepaidExpenses()">
        <select aria-label="流水类型" onchange="state.prepaidExpenses.filters.entryType=this.value;loadPrepaidExpenses()">
          ${option('', '全部类型', filters.entryType)}${option('expense', '团队支出', filters.entryType)}${option('advance', '团队备用金', filters.entryType)}
        </select>
        <select aria-label="支出分类" onchange="state.prepaidExpenses.filters.category=this.value;loadPrepaidExpenses()">
          ${option('', '全部分类', filters.category)}${data.categories.map(value => option(value, value, filters.category)).join('')}
        </select>
        <input class="input prepaid-search" placeholder="筛选对应项目" value="${esc(filters.project)}" oninput="state.prepaidExpenses.filters.project=this.value;debouncePrepaidLoad()">
        <input class="input prepaid-search" placeholder="搜索支出内容" value="${esc(filters.q)}" oninput="state.prepaidExpenses.filters.q=this.value;debouncePrepaidLoad()">
        <button class="btn" type="button" onclick="resetPrepaidFilters()">重置</button>
      </div>
      <button class="btn" type="button" onclick="exportPrepaidExpenses()" ${isOfflineReadonly() ? 'disabled' : ''}>导出 Excel</button>
    </div>
    <div class="prepaid-list">
      <div class="table-x-scroll"><table class="data-table prepaid-table"><colgroup><col style="width:11%"><col style="width:14%"><col style="width:17%"><col style="width:14%"><col style="width:20%"><col style="width:10%"><col style="width:10%"><col style="width:12%"></colgroup>
        <thead><tr><th>收支时间</th><th>收支类型</th><th>对应项目</th><th>支出分类</th><th>支出内容</th><th style="text-align:right">金额</th><th style="text-align:right">当时余额</th><th>操作</th></tr></thead>
        <tbody>${prepaidTableRows(data.items || [])}</tbody></table></div>
      <div class="prepaid-mobile-list">${prepaidMobileCards(data.items || [])}</div>
    </div>
  </section>`;
  if (!data.settings && !isOfflineReadonly()) loadPrepaidSettings(true);
}

let prepaidLoadTimer = null;
function debouncePrepaidLoad() {
  clearTimeout(prepaidLoadTimer);
  prepaidLoadTimer = setTimeout(loadPrepaidExpenses, 240);
}

function resetPrepaidFilters() {
  state.prepaidExpenses.filters = { dateFrom: '', dateTo: '', entryType: '', project: '', category: '', q: '' };
  loadPrepaidExpenses();
}

function localTodayValue() {
  const now = new Date();
  const adjusted = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
  return adjusted.toISOString().slice(0, 10);
}

function openPrepaidEditorById(id) {
  const item = (state.prepaidExpenses.items || []).find(entry => Number(entry.id) === Number(id));
  if (item) openPrepaidEditor(item);
}

function openPrepaidEditor(item = null) {
  if (!requireOnlineAction()) return;
  state.prepaidExpenses.editing = item ? { ...item } : null;
  state.prepaidExpenses.categoryDraft = [...state.prepaidExpenses.categories];
  state.prepaidExpenses.presetDraft = {
    expense: [...(state.prepaidExpenses.presets.expense || [])],
    advance: [...(state.prepaidExpenses.presets.advance || [])]
  };
  const entryType = item?.entry_type || 'expense';
  const categoryValues = [...state.prepaidExpenses.categories];
  if (item?.category && !categoryValues.includes(item.category)) categoryValues.unshift(item.category);
  $('drawerTitle').textContent = item ? '编辑收支记录' : '新增收支记录';
  $('drawerHeadActions').innerHTML = '';
  $('drawerBody').innerHTML = `<div class="prepaid-editor">
    <div class="prepaid-type-switch">
      <label class="prepaid-type-option"><input type="radio" name="prepaid_entry_type" value="expense" ${entryType === 'expense' ? 'checked' : ''} onchange="prepaidEditorTypeChanged()"><span>团队支出</span></label>
      <label class="prepaid-type-option"><input type="radio" name="prepaid_entry_type" value="advance" ${entryType === 'advance' ? 'checked' : ''} onchange="prepaidEditorTypeChanged()"><span>团队备用金</span></label>
    </div>
    <div class="prepaid-form-grid">
      <div class="field"><label>收支时间</label><input class="input" id="prepaidOccurredOn" type="date" value="${esc(item?.occurred_on || localTodayValue())}" oninput="updatePrepaidBalancePreview()"></div>
      <div class="field" id="prepaidCategoryField"><label class="prepaid-category-label"><span>支出分类（可选）</span><button type="button" class="prepaid-category-manage-link" onclick="togglePrepaidCategoryManager()">管理分类</button></label><select id="prepaidCategory">${option('', '不分类', item?.category || '')}${categoryValues.map(value => option(value, value, item?.category || '')).join('')}</select><div class="prepaid-category-manager" id="prepaidCategoryManager"></div></div>
      <div class="field full prepaid-project-field" id="prepaidProjectField"><label>对应项目（可选）</label><input class="input" id="prepaidProjectName" value="${esc(item?.project_name || '')}" placeholder="可搜索案件，也可直接填写项目名称" autocomplete="off" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="prepaidProjectSuggestions"><div class="prepaid-project-suggestions" id="prepaidProjectSuggestions" role="listbox"></div></div>
      <div class="field full"><label class="prepaid-category-label"><span id="prepaidDescriptionLabel">支出内容</span><span><button type="button" class="prepaid-category-manage-link" onclick="saveCurrentPrepaidDescriptionPreset()">保存为常用项</button><button type="button" class="prepaid-category-manage-link" onclick="togglePrepaidDescriptionPresetManager()">管理常用项</button></span></label><select id="prepaidDescriptionPreset" onchange="applyPrepaidDescriptionPreset(this.value)"></select><textarea id="prepaidDescription" placeholder="例如：文件快递费（顺丰、EMS）">${esc(item?.description || '')}</textarea><div class="prepaid-category-manager" id="prepaidDescriptionPresetManager"></div></div>
      <div class="field full"><label>具体金额</label><input class="input" id="prepaidAmount" type="number" min="0.01" step="0.01" inputmode="decimal" value="${item?.amount != null ? esc(Number(item.amount).toFixed(2)) : ''}" placeholder="0.00" oninput="updatePrepaidBalancePreview()"></div>
    </div>
    <div class="prepaid-balance-preview"><span>保存后预计剩余金额</span><strong id="prepaidBalancePreview">${prepaidMoney(state.prepaidExpenses.summary.balance)}</strong></div>
  </div>`;
  $('drawerFoot').innerHTML = `<button class="btn" onclick="closeEditor();state.prepaidExpenses.editing=null">取消</button><button class="btn primary" id="savePrepaidExpenseButton" onclick="savePrepaidExpense()">保存</button>`;
  $('drawerMask').classList.add('show');
  $('drawer').classList.add('show');
  $('drawer').classList.remove('detail-mode');
  prepaidEditorTypeChanged();
  ApexCasePicker.attach({ input: $('prepaidProjectName'), menu: $('prepaidProjectSuggestions'), request: api,
    onSelect: item => { $('prepaidProjectName').value = item.title || ''; } });
  setTimeout(() => (item ? $('prepaidDescription') : $('prepaidAmount'))?.focus(), 0);
}

function prepaidEditorType() {
  return document.querySelector('[name="prepaid_entry_type"]:checked')?.value || 'expense';
}

function prepaidEditorTypeChanged() {
  const expense = prepaidEditorType() === 'expense';
  if ($('prepaidCategoryField')) $('prepaidCategoryField').style.display = expense ? '' : 'none';
  if ($('prepaidProjectField')) $('prepaidProjectField').style.display = expense ? '' : 'none';
  if ($('prepaidDescriptionLabel')) $('prepaidDescriptionLabel').textContent = expense ? '支出内容' : '备用金说明（可选）';
  if ($('prepaidDescription')) $('prepaidDescription').placeholder = expense ? '例如：文件快递费（顺丰、EMS）' : '例如：团队转入备用金';
  renderPrepaidDescriptionPresetSelect();
  if ($('prepaidDescriptionPresetManager')?.classList.contains('show')) renderPrepaidDescriptionPresetManager();
  updatePrepaidBalancePreview();
}

function togglePrepaidCategoryManager() {
  const host = $('prepaidCategoryManager');
  if (!host) return;
  const show = !host.classList.contains('show');
  host.classList.toggle('show', show);
  if (show) renderPrepaidCategoryManager();
}

function renderPrepaidCategoryManager() {
  const host = $('prepaidCategoryManager');
  if (!host) return;
  host.innerHTML = `${state.prepaidExpenses.categoryDraft.map((value, index) => `<div class="prepaid-category-row"><input class="input" value="${esc(value)}" maxlength="60" aria-label="支出分类 ${index + 1}" oninput="state.prepaidExpenses.categoryDraft[${index}]=this.value"><button type="button" class="btn danger" onclick="removePrepaidCategory(${index})">删除</button></div>`).join('')}<div class="prepaid-category-add"><input class="input" id="newPrepaidCategory" maxlength="60" placeholder="新增分类名称" onkeydown="if(event.key==='Enter'){event.preventDefault();addPrepaidCategory()}"><button type="button" class="btn" onclick="addPrepaidCategory()">增加</button></div><div class="prepaid-category-actions"><button type="button" class="btn primary" id="savePrepaidCategoriesButton" onclick="savePrepaidCategories()">保存分类</button></div>`;
}

function removePrepaidCategory(index) {
  state.prepaidExpenses.categoryDraft.splice(index, 1);
  renderPrepaidCategoryManager();
}

function addPrepaidCategory() {
  const input = $('newPrepaidCategory');
  const value = (input?.value || '').trim();
  if (!value) return;
  if (state.prepaidExpenses.categoryDraft.some(item => item.trim() === value)) {
    toast('该分类已存在');
    return;
  }
  state.prepaidExpenses.categoryDraft.push(value);
  renderPrepaidCategoryManager();
}

async function savePrepaidCategories() {
  const categories = state.prepaidExpenses.categoryDraft.map(value => value.trim()).filter((value, index, all) => value && all.indexOf(value) === index);
  const button = $('savePrepaidCategoriesButton');
  if (button) { button.disabled = true; button.textContent = '保存中…'; }
  try {
    const data = await api('/api/case-manager/prepaid-expenses/categories', {
      method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ categories })
    });
    state.prepaidExpenses.categories = data.categories || categories;
    state.prepaidExpenses.categoryDraft = [...state.prepaidExpenses.categories];
    const select = $('prepaidCategory');
    if (select) {
      const selected = select.value;
      select.innerHTML = `${option('', '不分类', selected)}${state.prepaidExpenses.categories.map(value => option(value, value, selected)).join('')}`;
    }
    renderPrepaidCategoryManager();
    toast('支出分类已保存');
    await loadPrepaidExpenses();
    scheduleCaseOfflineSnapshot(true, 3000);
  } catch (error) {
    toast(error.message || '分类保存失败');
    if (button) { button.disabled = false; button.textContent = '保存分类'; }
  }
}

function prepaidPresetKind() {
  return prepaidEditorType() === 'advance' ? 'advance' : 'expense';
}

function renderPrepaidDescriptionPresetSelect() {
  const select = $('prepaidDescriptionPreset');
  if (!select) return;
  const values = state.prepaidExpenses.presets[prepaidPresetKind()] || [];
  select.innerHTML = `${option('', '选择常用内容', '')}${values.map(value => option(value, value, '')).join('')}`;
}

function applyPrepaidDescriptionPreset(value) {
  if (!value || !$('prepaidDescription')) return;
  $('prepaidDescription').value = value;
  $('prepaidDescription').focus();
}

function togglePrepaidDescriptionPresetManager() {
  const host = $('prepaidDescriptionPresetManager');
  if (!host) return;
  const show = !host.classList.contains('show');
  host.classList.toggle('show', show);
  if (show) renderPrepaidDescriptionPresetManager();
}

function renderPrepaidDescriptionPresetManager() {
  const host = $('prepaidDescriptionPresetManager');
  if (!host) return;
  const kind = prepaidPresetKind();
  const values = state.prepaidExpenses.presetDraft[kind] || [];
  host.innerHTML = `${values.map((value, index) => `<div class="prepaid-category-row"><input class="input" value="${esc(value)}" maxlength="200" aria-label="常用内容 ${index + 1}" oninput="state.prepaidExpenses.presetDraft['${kind}'][${index}]=this.value"><button type="button" class="btn danger" onclick="removePrepaidDescriptionPreset(${index})">删除</button></div>`).join('')}<div class="prepaid-category-add"><input class="input" id="newPrepaidDescriptionPreset" maxlength="200" placeholder="新增常用内容" onkeydown="if(event.key==='Enter'){event.preventDefault();addPrepaidDescriptionPreset()}"><button type="button" class="btn" onclick="addPrepaidDescriptionPreset()">增加</button></div><div class="prepaid-category-actions"><button type="button" class="btn primary" id="savePrepaidDescriptionPresetsButton" onclick="savePrepaidDescriptionPresets()">保存常用项</button></div>`;
}

function removePrepaidDescriptionPreset(index) {
  state.prepaidExpenses.presetDraft[prepaidPresetKind()].splice(index, 1);
  renderPrepaidDescriptionPresetManager();
}

function addPrepaidDescriptionPreset(value = '') {
  const input = $('newPrepaidDescriptionPreset');
  const content = (value || input?.value || '').trim();
  if (!content) return false;
  const values = state.prepaidExpenses.presetDraft[prepaidPresetKind()];
  if (values.some(item => item.trim() === content)) {
    toast('该常用内容已存在');
    return false;
  }
  values.push(content);
  renderPrepaidDescriptionPresetManager();
  return true;
}

async function persistPrepaidDescriptionPresets(showSuccess = true) {
  const payload = {};
  for (const kind of ['expense', 'advance']) {
    payload[kind] = (state.prepaidExpenses.presetDraft[kind] || [])
      .map(value => value.trim())
      .filter((value, index, all) => value && all.indexOf(value) === index);
  }
  const data = await api('/api/case-manager/prepaid-expenses/presets', {
    method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload)
  });
  state.prepaidExpenses.presets = data.presets || payload;
  state.prepaidExpenses.presetDraft = {
    expense: [...(state.prepaidExpenses.presets.expense || [])],
    advance: [...(state.prepaidExpenses.presets.advance || [])]
  };
  renderPrepaidDescriptionPresetSelect();
  renderPrepaidDescriptionPresetManager();
  if (showSuccess) toast('常用内容已保存');
  scheduleCaseOfflineSnapshot(true, 3000);
}

async function savePrepaidDescriptionPresets() {
  const button = $('savePrepaidDescriptionPresetsButton');
  if (button) { button.disabled = true; button.textContent = '保存中…'; }
  try {
    await persistPrepaidDescriptionPresets(true);
  } catch (error) {
    toast(error.message || '常用内容保存失败');
    if (button) { button.disabled = false; button.textContent = '保存常用项'; }
  }
}

async function saveCurrentPrepaidDescriptionPreset() {
  const value = ($('prepaidDescription')?.value || '').trim();
  if (!value) return toast('请先填写内容');
  if (!addPrepaidDescriptionPreset(value)) return;
  try {
    await persistPrepaidDescriptionPresets(false);
    toast('已保存为常用项');
  } catch (error) {
    toast(error.message || '常用内容保存失败');
  }
}

function updatePrepaidBalancePreview() {
  const current = Number(state.prepaidExpenses.summary.balance || 0);
  const old = state.prepaidExpenses.editing;
  const oldImpact = old ? (old.entry_type === 'advance' ? Number(old.amount || 0) : -Number(old.amount || 0)) : 0;
  const amount = Math.max(0, Number($('prepaidAmount')?.value || 0));
  const newImpact = prepaidEditorType() === 'advance' ? amount : -amount;
  const expected = current - oldImpact + newImpact;
  const host = $('prepaidBalancePreview');
  if (host) {
    host.textContent = prepaidMoney(expected);
    host.classList.toggle('negative', expected < 0);
  }
}

async function savePrepaidExpense() {
  const editing = state.prepaidExpenses.editing;
  const body = {
    occurred_on: $('prepaidOccurredOn')?.value || '',
    entry_type: prepaidEditorType(),
    project_name: prepaidEditorType() === 'expense' ? ($('prepaidProjectName')?.value || '') : '',
    category: prepaidEditorType() === 'expense' ? ($('prepaidCategory')?.value || '') : '',
    description: $('prepaidDescription')?.value || '',
    amount: $('prepaidAmount')?.value || '',
  };
  const button = $('savePrepaidExpenseButton');
  if (button) { button.disabled = true; button.textContent = '保存中…'; }
  try {
    await api(editing?.id ? `/api/case-manager/prepaid-expenses/${editing.id}` : '/api/case-manager/prepaid-expenses', {
      method: editing?.id ? 'PUT' : 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body)
    });
    state.prepaidExpenses.editing = null;
    closeEditor();
    toast(editing?.id ? '收支记录已更新' : '收支记录已保存');
    await loadPrepaidExpenses();
    scheduleCaseOfflineSnapshot(true, 3000);
  } catch (error) {
    toast(error.message || '保存失败');
    if (button) { button.disabled = false; button.textContent = '保存'; }
  }
}

async function deletePrepaidExpense(id) {
  if (!requireOnlineAction()) return;
  if (!confirm('确定删除这条收支记录吗？删除后团队备用金余额会立即重新计算。')) return;
  try {
    await api(`/api/case-manager/prepaid-expenses/${id}`, { method: 'DELETE' });
    toast('收支记录已删除');
    await loadPrepaidExpenses();
    scheduleCaseOfflineSnapshot(true, 3000);
  } catch (error) { toast(error.message || '删除失败'); }
}

function exportPrepaidExpenses() {
  if (!requireOnlineAction()) return;
  window.location.href = `/api/case-manager/prepaid-expenses/export?${prepaidFilterParams()}`;
}

async function syncPrepaidExpenses(showToast = true) {
  if (state.prepaidExpenses.syncing || isOfflineReadonly()) return;
  state.prepaidExpenses.syncing = true;
  if (activeTab === 'prepaidExpenses') renderPrepaidExpenses();
  try {
    const result = await api('/api/case-manager/prepaid-expenses/feishu-sync', { method: 'POST' });
    if (showToast) toast(result.ok ? `飞书同步完成：新增 ${Number(result.imported || 0)} 条` : (result.message || '飞书同步未完成'));
  } catch (error) {
    if (showToast) toast(error.message || '飞书同步失败');
  } finally {
    state.prepaidExpenses.syncing = false;
    await loadPrepaidExpenses();
    scheduleCaseOfflineSnapshot(true, 3000);
  }
}

async function loadPrepaidSettings(rerender = true) {
  try {
    state.prepaidExpenses.settings = await api('/api/case-manager/prepaid-expenses/feishu-settings');
    if (rerender && activeTab === 'prepaidExpenses') renderPrepaidExpenses();
  } catch (e) {}
}

function openPrepaidFeishuForm() {
  const settings = state.prepaidExpenses.settings || {};
  const url = settings.form_url || settings.base_url;
  if (!url) return openPrepaidFeishuSettings();
  window.open(url, '_blank', 'noopener,noreferrer');
}

async function openPrepaidFeishuSettings() {
  if (!requireOnlineAction()) return;
  await loadPrepaidSettings(false);
  const settings = state.prepaidExpenses.settings || {};
  $('drawerTitle').textContent = '飞书团队费用同步设置';
  $('drawerHeadActions').innerHTML = '';
  $('drawerBody').innerHTML = `<div class="prepaid-editor">
    <div class="feishu-settings-guide"><strong>一次配置，手机可长期使用</strong>电脑关闭时，飞书表单仍会保存提交内容；案件管理系统下次启动后自动同步。App Secret 只保存在当前电脑。</div>
    <div class="feishu-setup-steps">
      <div class="feishu-setup-step"><strong>① 创建企业自建应用并取得密钥</strong>打开 <a href="https://open.feishu.cn/app" target="_blank" rel="noopener">飞书开发者后台</a>，选择“创建企业自建应用”。进入“凭证与基础信息”，复制 App ID 与 App Secret 到下方。</div>
      <div class="feishu-setup-step"><strong>② 开通并发布权限</strong>在“权限管理”搜索并开通“查看、评论、编辑和管理多维表格（bitable:app）”；如页面提供更细权限，还应开通“根据条件搜索记录”和“更新记录”。创建版本并发布；企业开启审核时需管理员通过。</div>
      <div class="feishu-setup-step"><strong>③ 创建多维表格和数据表字段</strong>新建多维表格“预支费用快捷提交”，将第一张数据表改为“费用流水”，按下表创建字段。团队备用金时“对应项目”和“支出分类”留空即可。
        <div class="feishu-field-table"><span class="head">字段</span><span class="head">类型</span><span class="head">设置</span><span>支出内容/说明</span><span>文本</span><span>主字段；团队支出时必填</span><span>流水类型</span><span>单选</span><span>团队支出、团队备用金</span><span>发生日期</span><span>日期</span><span>可选</span><span>对应项目</span><span>单选</span><span>由案件管理系统自动更新</span><span>支出分类</span><span>单选</span><span>选项与本地分类一致</span><span>金额</span><span>数字</span><span>必填、大于 0</span><span>同步状态</span><span>单选</span><span>已同步、需修正</span><span>本地记录编号</span><span>文本</span><span>管理字段</span><span>同步时间</span><span>日期</span><span>管理字段</span><span>同步说明</span><span>文本</span><span>管理字段</span></div>
      </div>
      <div class="feishu-setup-step"><strong>④ 授予文档权限并创建手机表单</strong>在多维表格右上角“…”→“更多”→“添加文档应用”，加入刚创建的应用并授予可管理权限。新增“表单”视图，只展示前六个业务字段，把流水类型和金额设为必填，并仅分享给本人。</div>
      <div class="feishu-setup-step"><strong>⑤ 粘贴链接并验证</strong>打开“费用流水”数据表，复制浏览器地址栏中同时包含 <code>/base/</code> 和 <code>table=tbl…</code> 的完整链接；再复制表单分享链接。填写下方内容并点击“保存并验证”。</div>
    </div>
    <div class="field"><label>飞书自建应用 App ID</label><input class="input" id="prepaidFeishuAppId" value="${esc(settings.app_id || '')}" placeholder="cli_xxxxxxxxxxxxxxxx"></div>
    <div class="field"><label>App Secret</label><input class="input" id="prepaidFeishuAppSecret" type="password" value="" placeholder="${esc(settings.app_secret_masked || '请输入 App Secret')}"><div class="muted" style="margin-top:5px;font-size:11px">密钥仅保存在本机私有文件中；留空表示保留现有密钥。</div></div>
    <div class="field"><label>多维表格编辑页面链接（不能填分享链接）</label><input class="input" id="prepaidFeishuBaseUrl" value="${esc(settings.base_url || '')}" placeholder="必须同时包含 /base/ 和 table=tbl…"><div class="muted" style="margin-top:5px;font-size:11px">正确示例：https://xxx.feishu.cn/base/appToken?table=tblTableId&amp;view=vew…</div></div>
    <div class="field"><label>手机表单分享链接（可选）</label><input class="input" id="prepaidFeishuFormUrl" value="${esc(settings.form_url || '')}" placeholder="从“表单”视图复制分享表单链接"></div>
    <div id="prepaidFeishuVerifyResult" class="muted">${settings.configured ? '已有配置；保存时会重新检查连接与字段。' : '尚未配置。'}</div>
  </div>`;
  $('drawerFoot').innerHTML = `<button class="btn" onclick="closeEditor()">取消</button><button class="btn primary" id="savePrepaidFeishuButton" onclick="savePrepaidFeishuSettings()">保存并验证</button>`;
  $('drawerMask').classList.add('show'); $('drawer').classList.add('show'); $('drawer').classList.remove('detail-mode');
}

async function savePrepaidFeishuSettings() {
  const button = $('savePrepaidFeishuButton');
  const resultHost = $('prepaidFeishuVerifyResult');
  if (button) { button.disabled = true; button.textContent = '正在验证…'; }
  if (resultHost) resultHost.textContent = '正在连接飞书并检查字段，请稍候…';
  try {
    const settings = await api('/api/case-manager/prepaid-expenses/feishu-settings', {
      method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify({
        app_id: $('prepaidFeishuAppId')?.value || '',
        app_secret: $('prepaidFeishuAppSecret')?.value || '',
        base_url: $('prepaidFeishuBaseUrl')?.value || '',
        form_url: $('prepaidFeishuFormUrl')?.value || '',
        verify: true,
      })
    });
    state.prepaidExpenses.settings = settings;
    if (resultHost) resultHost.textContent = settings.verification?.message || '连接验证通过';
    toast('飞书同步设置已保存');
    if (button) { button.disabled = false; button.textContent = '验证通过'; }
    await loadPrepaidExpenses();
  } catch (error) {
    if (resultHost) resultHost.textContent = error.message || '验证失败';
    if (button) { button.disabled = false; button.textContent = '保存并验证'; }
  }
}

async function openClientManager(preferredId = null) {
  if (!requireOnlineAction()) return;
  const manager = $('clientManager');
  manager.classList.add('show');
  manager.setAttribute('aria-hidden', 'false');
  state.clientEditing = false;
  notifyCaseManagerContext('委托人管理', '委托人管理');
  rememberOpenManager('client');
  bindManagerScrollRemember('client');
  await loadClients(preferredId || state.selectedClient?.id || null);
}
function closeClientManager() {
  const manager = $('clientManager');
  manager.classList.remove('show');
  manager.setAttribute('aria-hidden', 'true');
  state.clientEditing = false;
  notifyCaseManagerContext(currentCaseManagerPageLabel());
  forgetOpenManager();
}
let clientSearchTimer = null;
function debounceClientSearch(value) {
  state.clientQ = value || '';
  clearTimeout(clientSearchTimer);
  clientSearchTimer = setTimeout(() => loadClients(), 240);
}
async function loadClients(preferredId = null) {
  const params = new URLSearchParams();
  if (state.clientQ) params.set('q', state.clientQ);
  const data = await api(`/api/case-manager/clients?${params}`);
  state.clients = data.items || [];
  renderClientList();
  const targetId = preferredId || state.selectedClient?.id || state.clients[0]?.id;
  if (targetId && state.clients.some(client => Number(client.id) === Number(targetId))) {
    await selectClient(targetId);
  } else {
    state.selectedClient = null;
    state.clientEditing = false;
    renderClientDetail();
  }
}
function renderClientList() {
  const host = $('clientList');
  if (!host) return;
  if (!state.clients.length) {
    host.innerHTML = '<div class="empty">暂无委托人</div>';
    return;
  }
  host.innerHTML = state.clients.map(client => `
    <button class="client-list-item ${Number(state.selectedClient?.id) === Number(client.id) ? 'active' : ''}"
            type="button" onclick="selectClient(${client.id})">
      <span class="client-list-item-head">
        <strong>${esc(client.name || '未命名委托人')}</strong>
        <span class="client-case-count">在办${client.active_case_count || 0}</span>
      </span>
      <span class="client-list-item-meta">${esc(client.client_type || '未分类')} · 共${client.case_count || 0}案 · ${esc(client.contact_person || client.phone || '暂无联系人')}</span>
    </button>
  `).join('');
}
async function selectClient(clientId) {
  state.selectedClient = await api(`/api/case-manager/clients/${clientId}`);
  state.clientEditing = false;
  rememberOpenManager('client', { selectedId: Number(clientId) });
  renderClientList();
  renderClientDetail();
}
function clientIdentityLabel(clientType) {
  if (clientType === '单位') return '统一社会信用代码';
  if (clientType === '个人') return '公民身份号码';
  if (clientType === '境外主体') return '海外居民身份代码';
  return '证件号码';
}
function updateClientIdentityCodeLabel(clientType) {
  const label = $('clientIdentityCodeLabel');
  if (label) label.textContent = clientIdentityLabel(clientType);
  const representativeField = $('clientLegalRepresentativeField');
  if (representativeField) representativeField.style.display = clientType === '单位' ? '' : 'none';
  const representativeTitleField = $('clientLegalRepresentativeTitleField');
  if (representativeTitleField) representativeTitleField.style.display = clientType === '单位' ? '' : 'none';
  const companyProfileFields = $('clientCompanyProfileFields');
  if (companyProfileFields) companyProfileFields.style.display = clientType === '单位' ? 'contents' : 'none';
}
function clientInfoRows(client) {
  const contacts = (client.contacts || []).map((item, index) => {
    const name = item.name || `联系人 ${index + 1}`;
    return `${name}${item.phone ? `：${item.phone}` : ''}`;
  }).join('\n');
  const rows = [
    ['委托人类别', client.client_type],
    ['名称 / 姓名', client.name],
    [clientIdentityLabel(client.client_type), client.identity_code],
  ];
  if (client.client_type === '单位') rows.push(
    ['法定代表人', client.legal_representative],
    ['法定代表人职务', client.legal_representative_title],
    ['注册资本', client.registered_capital],
    ['成立日期', client.establishment_date],
    ['登记状态', client.registration_status],
    ['企业性质', client.enterprise_nature],
    ['所属行业', client.industry],
    ['所属地区', client.region],
    ['经营范围', client.business_scope],
    ['工商数据来源', client.data_source ? `${client.data_source}${client.source_checked_at ? `（查询时间：${client.source_checked_at.replace('T', ' ')}）` : ''}` : ''],
  );
  rows.push(
    ['联系地址', client.address],
    ['联系人及联系方式', contacts],
    ['开票信息', client.invoice_info],
  );
  return rows;
}
function clientCasesHtml(client) {
  const cases = client.cases || [];
  if (!cases.length) return '<div class="empty">暂无关联案件</div>';
  const activeCases = cases.filter(item => (item.source_status || 'active') !== 'archived');
  const archivedCases = cases.filter(item => item.source_status === 'archived');
  const groupHtml = (title, items) => `<section class="client-case-group">
    <div class="client-case-group-head"><span>${esc(title)}</span><span>${items.length} 件</span></div>
    ${items.length ? `<div class="client-case-list">${items.map(item => `
    <button class="client-case-card" type="button" onclick="openClientCase(${item.id})">
      <strong>${esc(item.title || '未命名案件')}</strong>
      <span class="client-case-summary">${esc(item.summary || '暂无案件综述')}</span>
    </button>
    `).join('')}</div>` : '<div class="empty compact">暂无案件</div>'}
  </section>`;
  return `${groupHtml('在办案件', activeCases)}${groupHtml('已归档案件', archivedCases)}`;
}
function clientFormHtml(client) {
  const contacts = client.contacts?.length ? client.contacts : [{ name: '', phone: '' }];
  return `<form class="client-form" id="clientInfoForm" onsubmit="event.preventDefault(); saveClient()">
    <div class="field"><label>委托人类别</label><select name="client_type" onchange="updateClientIdentityCodeLabel(this.value)">
      ${option('单位', '单位', client.client_type || '单位')}
      ${option('个人', '个人', client.client_type || '单位')}
      ${option('境外主体', '境外主体', client.client_type || '单位')}
      ${option('其他', '其他', client.client_type || '单位')}
    </select></div>
    <div class="field">
      <label>名称 / 姓名</label>
      <div class="client-ai-lookup-row">
        <input class="input" name="name" value="${esc(client.name || '')}" required>
        <div class="client-ai-lookup-actions">
          <button class="btn primary" type="button" onclick="importClientFromFinchina(this)">导入企业信息</button>
          <button class="btn" type="button" onclick="openOfficialClientLookup()">官方复核</button>
        </div>
      </div>
      <div class="client-ai-hint">财汇将按企业名称匹配并填入工商信息；保存前请核对匹配企业。重要信息可点击“官方复核”再次确认。</div>
    </div>
    <div class="field"><label>证件类型</label><input class="input" name="document_type" value="${esc(client.document_type || '')}" placeholder="居民身份证 / 统一社会信用代码"></div>
    <div class="field"><label id="clientIdentityCodeLabel">${esc(clientIdentityLabel(client.client_type || '单位'))}</label><input class="input" name="identity_code" value="${esc(client.identity_code || '')}"></div>
    <div class="field"><label>国别或地区</label><input class="input" name="nationality" value="${esc(client.nationality || '中国')}"></div>
    <div class="field"><label>性别</label><input class="input" name="gender" value="${esc(client.gender || '')}" placeholder="自然人填写"></div>
    <div class="field" id="clientLegalRepresentativeField" style="${(client.client_type || '单位') === '单位' ? '' : 'display:none'}"><label>法定代表人</label><input class="input" name="legal_representative" value="${esc(client.legal_representative || '')}"></div>
    <div class="field" id="clientLegalRepresentativeTitleField" style="${(client.client_type || '单位') === '单位' ? '' : 'display:none'}"><label>法定代表人职务（如有）</label><input class="input" name="legal_representative_title" value="${esc(client.legal_representative_title || '')}"></div>
    <div class="field" id="clientLegalRepresentativeField" style="${(client.client_type || '单位') === '单位' ? '' : 'display:none'}"><label>法定代表人证件类型</label><input class="input" name="legal_representative_document_type" value="${esc(client.legal_representative_document_type || '')}"></div>
    <div class="field" id="clientLegalRepresentativeField" style="${(client.client_type || '单位') === '单位' ? '' : 'display:none'}"><label>法定代表人证件号码</label><input class="input" name="legal_representative_document_number" value="${esc(client.legal_representative_document_number || '')}"></div>
    <div class="field" id="clientLegalRepresentativeField" style="${(client.client_type || '单位') === '单位' ? '' : 'display:none'}"><label>法定代表人联系电话</label><input class="input" name="legal_representative_mobile" value="${esc(client.legal_representative_mobile || '')}"></div>
    <div id="clientCompanyProfileFields" style="${(client.client_type || '单位') === '单位' ? 'display:contents' : 'display:none'}">
      <div class="field"><label>注册资本</label><input class="input" name="registered_capital" value="${esc(client.registered_capital || '')}"></div>
      <div class="field"><label>成立日期</label><input class="input" type="date" name="establishment_date" value="${esc(client.establishment_date || '')}"></div>
      <div class="field"><label>登记状态</label><input class="input" name="registration_status" value="${esc(client.registration_status || '')}"></div>
      <div class="field"><label>企业性质</label><input class="input" name="enterprise_nature" value="${esc(client.enterprise_nature || '')}"></div>
      <div class="field"><label>所属行业</label><input class="input" name="industry" value="${esc(client.industry || '')}"></div>
      <div class="field"><label>所属地区</label><input class="input" name="region" value="${esc(client.region || '')}"></div>
      <div class="field"><label>经营范围</label><textarea name="business_scope">${esc(client.business_scope || '')}</textarea></div>
      <input type="hidden" name="data_source" value="${esc(client.data_source || '')}">
      <input type="hidden" name="source_checked_at" value="${esc(client.source_checked_at || '')}">
    </div>
    <div class="field"><label>联系地址</label><textarea name="address">${esc(client.address || '')}</textarea></div>
    <div class="field">
      <label>联系人及联系方式</label>
      <div class="client-contact-rows" id="clientContactRows">${contacts.map(clientContactRowHtml).join('')}</div>
      <button class="btn" type="button" onclick="addClientContactRow()">新增一组联系人</button>
    </div>
    <div class="field"><label>开票信息</label><textarea name="invoice_info">${esc(client.invoice_info || '')}</textarea></div>
    <div class="client-detail-actions">
      <button class="btn primary" type="submit">保存</button>
      <button class="btn" type="button" onclick="cancelClientEdit()">取消</button>
    </div>
  </form>`;
}
function clientContactRowHtml(contact = {}) {
  return `<div class="client-contact-row">
    <input class="input" name="contact_name" value="${esc(contact.name || '')}" placeholder="联系人">
    <input class="input" name="contact_phone" value="${esc(contact.phone || '')}" placeholder="联系电话 / 邮箱 / 其他联系方式">
    <button class="btn" type="button" onclick="removeClientContactRow(this)" title="删除该联系人">×</button>
  </div>`;
}
function addClientContactRow() {
  $('clientContactRows')?.insertAdjacentHTML('beforeend', clientContactRowHtml());
}
function removeClientContactRow(button) {
  const rows = $('clientContactRows');
  button.closest('.client-contact-row')?.remove();
  if (rows && !rows.querySelector('.client-contact-row')) {
    rows.insertAdjacentHTML('beforeend', clientContactRowHtml());
  }
}
function openOfficialClientLookup() {
  const form = $('clientInfoForm');
  const name = form?.querySelector('[name="name"]')?.value.trim() || '';
  if (!name) return toast('请先填写委托人名称');
  navigator.clipboard?.writeText(name).catch(() => {});
  window.open('https://aiqicha.baidu.com/', '_blank', 'noopener,noreferrer');
  toast('委托人名称已复制，正在使用默认浏览器打开爱企查');
}
let finchinaCompanyCandidates = [];
let finchinaProfileTarget = 'client';
function closeFinchinaCandidateModal() {
  $('finchinaCandidateModal')?.remove();
  finchinaCompanyCandidates = [];
}
function renderFinchinaCandidateList(filterText = '') {
  const host = $('finchinaCandidateList');
  if (!host) return;
  const keyword = String(filterText || '').trim().toLowerCase();
  const visible = finchinaCompanyCandidates
    .map((item, index) => ({ ...item, index }))
    .filter(item => !keyword || String(item.name || '').toLowerCase().includes(keyword));
  host.innerHTML = visible.length ? visible.map(item => `
    <button class="finchina-candidate-item" type="button" onclick="selectFinchinaCandidate(${item.index}, this)">
      <strong>${esc(item.name || '')}</strong><span>选择</span>
    </button>`).join('') : '<div class="finchina-candidate-empty">没有符合当前筛选的企业</div>';
}
function openFinchinaCandidateModal(data, target = 'client') {
  closeFinchinaCandidateModal();
  finchinaProfileTarget = target;
  finchinaCompanyCandidates = Array.isArray(data.candidates) ? data.candidates : [];
  const returned = Number(data.returned || finchinaCompanyCandidates.length);
  const total = Number(data.total || returned);
  document.body.insertAdjacentHTML('beforeend', `
    <div class="finchina-candidate-modal" id="finchinaCandidateModal" role="dialog" aria-modal="true" aria-label="选择匹配企业">
      <section class="finchina-candidate-dialog">
        <div class="finchina-candidate-head">
          <div><strong>选择匹配企业</strong><span>“${esc(data.query || '')}”共匹配 ${total} 家企业${data.truncated ? `，当前显示前 ${returned} 家` : ''}</span></div>
          <button class="btn" type="button" onclick="closeFinchinaCandidateModal()">关闭</button>
        </div>
        <div class="finchina-candidate-toolbar">
          <input class="input" id="finchinaCandidateFilter" placeholder="在候选结果中继续筛选" oninput="renderFinchinaCandidateList(this.value)">
        </div>
        <div class="finchina-candidate-list" id="finchinaCandidateList"></div>
        <div class="finchina-candidate-foot">请选择准确的企业全称；点选后才会查询并填充工商档案，不会自动保存。</div>
      </section>
    </div>`);
  renderFinchinaCandidateList();
  setTimeout(() => $('finchinaCandidateFilter')?.focus(), 0);
}
function applyFinchinaCompanyProfile(data) {
  const form = $(finchinaProfileTarget === 'opponent' ? 'opponentInfoForm' : 'clientInfoForm');
  if (!form) return;
  const fields = [
    'name', 'identity_code', 'legal_representative', 'registered_capital',
    'establishment_date', 'registration_status', 'enterprise_nature', 'industry',
    'region', 'address', 'business_scope', 'data_source', 'source_checked_at',
  ];
  fields.forEach(field => {
    const input = form.querySelector(`[name="${field}"]`);
    if (input && data[field] !== undefined && data[field] !== null) input.value = data[field];
  });
}
async function selectFinchinaCandidate(index, button) {
  const candidate = finchinaCompanyCandidates[index];
  if (!candidate?.name) return;
  const originalText = button?.innerHTML || '';
  if (button) {
    button.disabled = true;
    button.innerHTML = `<strong>${esc(candidate.name)}</strong><span>正在导入…</span>`;
  }
  try {
    const profile = await api(`/api/case-manager/${finchinaProfileTarget === 'opponent' ? 'opponents' : 'clients'}/ai-lookup`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ action: 'profile', name: candidate.name }),
    });
    applyFinchinaCompanyProfile(profile);
    closeFinchinaCandidateModal();
    toast(`已导入“${profile.name || candidate.name}”的企业信息，请核对后保存`);
  } catch (error) {
    toast(error?.message || '财汇企业信息导入失败');
    if (button) {
      button.disabled = false;
      button.innerHTML = originalText;
    }
  }
}
async function importClientFromFinchina(button) {
  finchinaProfileTarget = 'client';
  const form = $('clientInfoForm');
  const clientType = form?.querySelector('[name="client_type"]')?.value || '';
  const nameInput = form?.querySelector('[name="name"]');
  const companyName = nameInput?.value.trim() || '';
  if (clientType !== '单位') return toast('财汇企业信息导入仅适用于单位客户');
  if (!companyName) return toast('请先输入法人客户名称');
  const originalText = button?.textContent || '导入企业信息';
  if (button) {
    button.disabled = true;
    button.textContent = '正在查询…';
  }
  try {
    const data = await api('/api/case-manager/clients/ai-lookup', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ action: 'search', name: companyName }),
    });
    if (!data.candidates?.length) return toast('财汇未找到匹配企业，请尝试更完整的名称');
    if (data.candidates.length === 1) {
      finchinaCompanyCandidates = data.candidates;
      await selectFinchinaCandidate(0, null);
      return;
    }
    openFinchinaCandidateModal(data, 'client');
  } catch (error) {
    toast(error?.message || '财汇企业信息导入失败');
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = originalText;
    }
  }
}
function renderClientDetail() {
  const host = $('clientDetail');
  if (!host) return;
  const client = state.selectedClient;
  if (!client) {
    host.innerHTML = '<div class="empty">请选择委托人，或点击“新增委托人”建立档案</div>';
    return;
  }
  const isNew = !client.id;
  host.innerHTML = `
    <div class="client-detail-head">
      <h2>${esc(isNew ? '新增委托人' : (client.name || '委托人详情'))}</h2>
      ${state.clientEditing ? '' : `<div class="client-detail-actions">
        <button class="btn" type="button" onclick="editClient(state.selectedClient)">修改</button>
        <button class="btn danger" type="button" onclick="deleteClient()">删除</button>
      </div>`}
    </div>
    <div class="client-detail-grid">
      <section class="client-info-card">
        <div class="client-card-title">委托人信息</div>
        ${state.clientEditing
          ? clientFormHtml(client)
          : `<dl class="client-info-list">${clientInfoRows(client).map(([label, value]) => `<dt>${esc(label)}</dt><dd>${esc(value || '-')}</dd>`).join('')}</dl>`}
      </section>
      <section class="client-cases-card">
        <div class="client-card-title">关联案件（${client.case_count || 0}）</div>
        ${clientCasesHtml(client)}
      </section>
    </div>`;
}
function editClient(client = null) {
  state.selectedClient = client
    ? { ...client }
    : { client_type: '单位', name: '', identity_code: '', address: '', legal_representative: '', registered_capital: '', establishment_date: '', registration_status: '', business_scope: '', enterprise_nature: '', industry: '', region: '', data_source: '', source_checked_at: '', contacts: [{ name: '', phone: '' }], invoice_info: '', cases: [], case_count: 0 };
  state.clientEditing = true;
  renderClientList();
  renderClientDetail();
  setTimeout(() => $('clientInfoForm')?.querySelector('[name="name"]')?.focus(), 0);
}
function cancelClientEdit() {
  const clientId = state.selectedClient?.id;
  if (clientId) selectClient(clientId);
  else loadClients();
}
async function saveClient() {
  const form = $('clientInfoForm');
  if (!form) return;
  const body = {};
  form.querySelectorAll('input,textarea,select').forEach(el => {
    if (!el.closest('.client-contact-row')) body[el.name] = el.value;
  });
  body.contacts = [...form.querySelectorAll('.client-contact-row')].map(row => ({
    name: row.querySelector('[name="contact_name"]')?.value || '',
    phone: row.querySelector('[name="contact_phone"]')?.value || '',
  })).filter(item => item.name.trim() || item.phone.trim());
  if (!String(body.name || '').trim()) return toast('请填写委托人名称或姓名');
  const existingId = state.selectedClient?.id;
  const saved = await api(
    existingId ? `/api/case-manager/clients/${existingId}` : '/api/case-manager/clients',
    { method: existingId ? 'PUT' : 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) }
  );
  state.selectedClient = saved;
  state.clientEditing = false;
  toast('委托人已保存');
  await loadClients(saved.id);
  loadList();
}
async function deleteClient() {
  const client = state.selectedClient;
  if (!client?.id) return;
  if (!confirm(`确定删除委托人“${client.name}”吗？\n\n不会删除案件，但会从 ${client.case_count || 0} 个关联案件中移除该委托人。`)) return;
  if (!confirm('请再次确认：删除委托人档案及案件关联后无法撤销。')) return;
  await api(`/api/case-manager/clients/${client.id}`, { method: 'DELETE' });
  toast('委托人已删除');
  state.selectedClient = null;
  await loadClients();
  loadList();
}
function openClientCase(caseId) {
  closeClientManager();
  openDetail('cases', caseId);
}

async function openOpponentManager(preferredId = null) {
  if (!requireOnlineAction()) return;
  const manager = $('opponentManager');
  manager.classList.add('show');
  manager.setAttribute('aria-hidden', 'false');
  state.opponentEditing = false;
  notifyCaseManagerContext('对方管理', '对方管理');
  rememberOpenManager('opponent');
  bindManagerScrollRemember('opponent');
  await loadOpponents(preferredId || state.selectedOpponent?.id || null);
}
function closeOpponentManager() {
  const manager = $('opponentManager');
  manager.classList.remove('show');
  manager.setAttribute('aria-hidden', 'true');
  state.opponentEditing = false;
  notifyCaseManagerContext(currentCaseManagerPageLabel());
  forgetOpenManager();
}
let opponentSearchTimer = null;
function debounceOpponentSearch(value) {
  state.opponentQ = value || '';
  clearTimeout(opponentSearchTimer);
  opponentSearchTimer = setTimeout(() => loadOpponents(), 240);
}
async function loadOpponents(preferredId = null) {
  const params = new URLSearchParams();
  if (state.opponentQ) params.set('q', state.opponentQ);
  const data = await api(`/api/case-manager/opponents?${params}`);
  state.opponents = data.items || [];
  renderOpponentList();
  const targetId = preferredId || state.selectedOpponent?.id || state.opponents[0]?.id;
  if (targetId && state.opponents.some(item => Number(item.id) === Number(targetId))) {
    await selectOpponent(targetId);
  } else {
    state.selectedOpponent = null;
    state.opponentEditing = false;
    renderOpponentDetail();
  }
}
function renderOpponentList() {
  const host = $('opponentList');
  if (!host) return;
  if (!state.opponents.length) {
    host.innerHTML = '<div class="empty">暂无对方</div>';
    return;
  }
  host.innerHTML = state.opponents.map(item => `
    <button class="client-list-item ${Number(state.selectedOpponent?.id) === Number(item.id) ? 'active' : ''}"
            type="button" onclick="selectOpponent(${item.id})">
      <span class="client-list-item-head">
        <strong>${esc(item.name || '未命名对方')}</strong>
        <span class="client-case-count">在办${item.active_case_count || 0}</span>
      </span>
      <span class="client-list-item-meta">${esc(item.opponent_type || '未分类')} · 共${item.case_count || 0}案 · ${esc(item.contact_person || item.phone || '暂无联系人')}</span>
    </button>
  `).join('');
}
async function selectOpponent(opponentId) {
  state.selectedOpponent = await api(`/api/case-manager/opponents/${opponentId}`);
  state.opponentEditing = false;
  rememberOpenManager('opponent', { selectedId: Number(opponentId) });
  renderOpponentList();
  renderOpponentDetail();
}
function updateOpponentIdentityCodeLabel(opponentType) {
  const label = $('opponentIdentityCodeLabel');
  if (label) label.textContent = clientIdentityLabel(opponentType);
  const representativeField = $('opponentLegalRepresentativeField');
  if (representativeField) representativeField.style.display = opponentType === '单位' ? '' : 'none';
  const companyProfileFields = $('opponentCompanyProfileFields');
  if (companyProfileFields) companyProfileFields.style.display = opponentType === '单位' ? 'contents' : 'none';
}
function opponentInfoRows(item) {
  const contacts = (item.contacts || []).map((contact, index) => {
    const name = contact.name || `联系人 ${index + 1}`;
    return `${name}${contact.phone ? `：${contact.phone}` : ''}`;
  }).join('\n');
  const rows = [
    ['对方类别', item.opponent_type],
    ['名称 / 姓名', item.name],
    [clientIdentityLabel(item.opponent_type), item.identity_code],
  ];
  if (item.opponent_type === '单位') rows.push(
    ['法定代表人', item.legal_representative],
    ['注册资本', item.registered_capital],
    ['成立日期', item.establishment_date],
    ['登记状态', item.registration_status],
    ['企业性质', item.enterprise_nature],
    ['所属行业', item.industry],
    ['所属地区', item.region],
    ['经营范围', item.business_scope],
    ['工商数据来源', item.data_source ? `${item.data_source}${item.source_checked_at ? `（查询时间：${item.source_checked_at.replace('T', ' ')}）` : ''}` : ''],
  );
  rows.push(
    ['联系地址', item.address],
    ['联系人及联系方式', contacts],
    ['备注', item.notes],
  );
  return rows;
}
function opponentCasesHtml(item) {
  const cases = item.cases || [];
  if (!cases.length) return '<div class="empty">暂无关联案件</div>';
  const activeCases = cases.filter(entry => (entry.source_status || 'active') !== 'archived');
  const archivedCases = cases.filter(entry => entry.source_status === 'archived');
  const groupHtml = (title, items) => `<section class="client-case-group">
    <div class="client-case-group-head"><span>${esc(title)}</span><span>${items.length} 件</span></div>
    ${items.length ? `<div class="client-case-list">${items.map(entry => `
      <button class="client-case-card" type="button" onclick="openOpponentCase(${entry.id})">
        <strong>${esc(entry.title || '未命名案件')}</strong>
        <span class="client-case-summary">${esc(entry.summary || '暂无案件综述')}</span>
      </button>`).join('')}</div>` : '<div class="empty compact">暂无案件</div>'}
  </section>`;
  return `${groupHtml('在办案件', activeCases)}${groupHtml('已归档案件', archivedCases)}`;
}
function opponentContactRowHtml(contact = {}) {
  return `<div class="client-contact-row">
    <input class="input" name="opponent_contact_name" value="${esc(contact.name || '')}" placeholder="联系人">
    <input class="input" name="opponent_contact_phone" value="${esc(contact.phone || '')}" placeholder="联系电话 / 邮箱 / 其他联系方式">
    <button class="btn" type="button" onclick="removeOpponentContactRow(this)" title="删除该联系人">×</button>
  </div>`;
}
function opponentFormHtml(item) {
  opponentProfilePastedFiles = [];
  const contacts = item.contacts?.length ? item.contacts : [{ name: '', phone: '' }];
  const type = item.opponent_type || '单位';
  return `<form class="client-form" id="opponentInfoForm" onsubmit="event.preventDefault(); saveOpponent()" onpaste="pasteOpponentProfileScreenshot(event)">
    <div class="opponent-ai-recognizer">
      <div class="opponent-ai-copy">
        <strong>截图智能填充</strong>
        <span>粘贴用户信息截图，自动识别单位或自然人并填入下方字段</span>
      </div>
      <div class="notice-ai-actions">
        <button class="btn primary" type="button" id="recognizeOpponentBtn" onclick="recognizeOpponentProfile()">粘贴截图识别</button>
        <label class="btn opponent-file-button">选择图片<input id="opponentProfileFiles" type="file" accept=".pdf,image/*,.txt" multiple onchange="updateOpponentProfilePasteStatus()"></label>
        <button class="btn" type="button" onclick="clearOpponentProfileRecognition()">清空</button>
      </div>
      <div class="notice-paste-status" id="opponentProfilePasteStatus">可在表单任意位置按 ⌘V 粘贴截图</div>
      <div class="notice-ai-result" id="opponentProfileResult"></div>
    </div>
    <div class="field"><label>对方类别</label><select name="opponent_type" onchange="updateOpponentIdentityCodeLabel(this.value)">
      ${option('单位', '单位', type)}${option('个人', '个人', type)}${option('境外主体', '境外主体', type)}${option('其他', '其他', type)}
    </select></div>
    <div class="field">
      <label>名称 / 姓名</label>
      <div class="client-ai-lookup-row">
        <input class="input" name="name" value="${esc(item.name || '')}" required>
        <div class="client-ai-lookup-actions">
          <button class="btn primary" type="button" onclick="importOpponentFromFinchina(this)">导入企业信息</button>
          <button class="btn" type="button" onclick="openOfficialOpponentLookup()">官方复核</button>
        </div>
      </div>
      <div class="client-ai-hint">财汇将按企业名称匹配并填入工商信息；保存前请核对匹配企业。重要信息可点击“官方复核”再次确认。</div>
    </div>
    <div class="field"><label>证件类型</label><input class="input" name="document_type" value="${esc(item.document_type || '')}" placeholder="居民身份证 / 统一社会信用代码"></div>
    <div class="field"><label id="opponentIdentityCodeLabel">${esc(clientIdentityLabel(type))}</label><input class="input" name="identity_code" value="${esc(item.identity_code || '')}"></div>
    <div class="field"><label>国别或地区</label><input class="input" name="nationality" value="${esc(item.nationality || '中国')}"></div>
    <div class="field"><label>性别</label><input class="input" name="gender" value="${esc(item.gender || '')}" placeholder="自然人填写"></div>
    <div class="field" id="opponentLegalRepresentativeField" style="${type === '单位' ? '' : 'display:none'}"><label>法定代表人</label><input class="input" name="legal_representative" value="${esc(item.legal_representative || '')}"></div>
    <div class="field" id="opponentLegalRepresentativeField" style="${type === '单位' ? '' : 'display:none'}"><label>法定代表人证件类型</label><input class="input" name="legal_representative_document_type" value="${esc(item.legal_representative_document_type || '')}"></div>
    <div class="field" id="opponentLegalRepresentativeField" style="${type === '单位' ? '' : 'display:none'}"><label>法定代表人证件号码</label><input class="input" name="legal_representative_document_number" value="${esc(item.legal_representative_document_number || '')}"></div>
    <div class="field" id="opponentLegalRepresentativeField" style="${type === '单位' ? '' : 'display:none'}"><label>法定代表人联系电话</label><input class="input" name="legal_representative_mobile" value="${esc(item.legal_representative_mobile || '')}"></div>
    <div id="opponentCompanyProfileFields" style="${type === '单位' ? 'display:contents' : 'display:none'}">
      <div class="field"><label>注册资本</label><input class="input" name="registered_capital" value="${esc(item.registered_capital || '')}"></div>
      <div class="field"><label>成立日期</label><input class="input" type="date" name="establishment_date" value="${esc(item.establishment_date || '')}"></div>
      <div class="field"><label>登记状态</label><input class="input" name="registration_status" value="${esc(item.registration_status || '')}"></div>
      <div class="field"><label>企业性质</label><input class="input" name="enterprise_nature" value="${esc(item.enterprise_nature || '')}"></div>
      <div class="field"><label>所属行业</label><input class="input" name="industry" value="${esc(item.industry || '')}"></div>
      <div class="field"><label>所属地区</label><input class="input" name="region" value="${esc(item.region || '')}"></div>
      <div class="field"><label>经营范围</label><textarea name="business_scope">${esc(item.business_scope || '')}</textarea></div>
      <input type="hidden" name="data_source" value="${esc(item.data_source || '')}">
      <input type="hidden" name="source_checked_at" value="${esc(item.source_checked_at || '')}">
    </div>
    <div class="field"><label>联系地址</label><textarea name="address">${esc(item.address || '')}</textarea></div>
    <div class="field">
      <label>联系人及联系方式</label>
      <div class="client-contact-rows" id="opponentContactRows">${contacts.map(opponentContactRowHtml).join('')}</div>
      <button class="btn" type="button" onclick="addOpponentContactRow()">新增一组联系人</button>
    </div>
    <div class="field"><label>备注</label><textarea name="notes">${esc(item.notes || '')}</textarea></div>
    <div class="client-detail-actions">
      <button class="btn primary" type="submit">保存</button>
      <button class="btn" type="button" onclick="cancelOpponentEdit()">取消</button>
    </div>
  </form>`;
}
let opponentProfilePastedFiles = [];
function pasteOpponentProfileScreenshot(event) {
  const imageFiles = [...(event.clipboardData?.items || [])]
    .filter(item => item.kind === 'file' && (item.type || '').startsWith('image/'))
    .map(item => item.getAsFile())
    .filter(Boolean);
  if (!imageFiles.length) return;
  event.preventDefault();
  const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
  const renamed = imageFiles.map((file, index) => {
    const extension = (file.type || '').split('/')[1]?.replace('jpeg', 'jpg') || 'png';
    return new File([file], `对方资料-${stamp}${imageFiles.length > 1 ? `-${index + 1}` : ''}.${extension}`, {
      type: file.type || 'image/png',
      lastModified: Date.now(),
    });
  });
  opponentProfilePastedFiles.push(...renamed);
  updateOpponentProfilePasteStatus();
  toast(`已粘贴 ${renamed.length} 张用户信息截图`);
  recognizeOpponentProfile();
}
function opponentProfileFiles() {
  return [...($('opponentProfileFiles')?.files || []), ...opponentProfilePastedFiles];
}
function updateOpponentProfilePasteStatus() {
  const status = $('opponentProfilePasteStatus');
  if (!status) return;
  const files = opponentProfileFiles();
  status.classList.toggle('has-files', files.length > 0);
  status.textContent = files.length
    ? `已添加 ${files.length} 个文件：${files.map(file => file.name).join('、')}`
    : '可在表单任意位置按 ⌘V 粘贴截图';
}
function clearOpponentProfileRecognition() {
  opponentProfilePastedFiles = [];
  if ($('opponentProfileFiles')) $('opponentProfileFiles').value = '';
  updateOpponentProfilePasteStatus();
  const result = $('opponentProfileResult');
  if (result) {
    result.classList.remove('show');
    result.innerHTML = '';
  }
}
function applyOpponentRecognition(data) {
  const form = $('opponentInfoForm');
  const item = data.item || {};
  if (!form) return;
  const type = ['单位', '个人', '境外主体', '其他'].includes(item.opponent_type) ? item.opponent_type : '';
  if (type) {
    const typeSelect = form.querySelector('[name="opponent_type"]');
    if (typeSelect) typeSelect.value = type;
    updateOpponentIdentityCodeLabel(type);
  }
  [
    'name', 'identity_code', 'address', 'legal_representative', 'registered_capital',
    'establishment_date', 'registration_status', 'business_scope', 'enterprise_nature',
    'industry', 'region', 'notes',
  ].forEach(name => {
    const input = form.querySelector(`[name="${name}"]`);
    if (input && item[name]) input.value = item[name];
  });
  if (Array.isArray(item.contacts) && item.contacts.length) {
    const rows = $('opponentContactRows');
    if (rows) rows.innerHTML = item.contacts.map(opponentContactRowHtml).join('');
  }
}
function opponentRecognitionSummary(data) {
  const item = data.item || {};
  const ai = data.ai || {};
  const typeLabel = item.opponent_type === '个人' ? '自然人' : (item.opponent_type || '未确定');
  const aiStatus = ai.used
    ? `AI 增强：${esc(['deepseek-flash', 'deepseek-v4-flash'].includes(ai.model) ? 'DeepSeek V4.1 Flash' : ai.model || '已启用')}`
    : `AI 增强：<span style="color:#9a3412">暂不可用，已使用本机规则识别${ai.error ? `（${esc(ai.error)}）` : ''}</span>`;
  return `<strong>识别完成，请核对后保存</strong>
    <br>主体类型：${esc(typeLabel)}　置信度：${esc(data.confidence || 0)}%
    <br>名称 / 姓名：${esc(item.name || '-')}
    <br>证件号码：${esc(item.identity_code || '-')}
    <br>${aiStatus}`;
}
async function recognizeOpponentProfile() {
  if (!requireOnlineAction()) return;
  const files = opponentProfileFiles();
  if (!files.length) return toast('请先在表单中按 ⌘V 粘贴用户信息截图，或选择图片');
  if (files.length > 8) return toast('单次最多识别 8 张截图或文件');
  const button = $('recognizeOpponentBtn');
  const result = $('opponentProfileResult');
  const form = new FormData();
  files.forEach(file => form.append('files', file));
  if (button) {
    button.disabled = true;
    button.textContent = '正在识别…';
  }
  if (result) {
    result.classList.add('show');
    result.textContent = '正在使用本机 OCR 与 DeepSeek V4.1 Flash 识别对方资料…';
  }
  try {
    const data = await api('/api/case-manager/opponents/recognize', { method: 'POST', body: form });
    applyOpponentRecognition(data);
    if (result) result.innerHTML = opponentRecognitionSummary(data);
    toast('已自动区分主体并填入对方信息，请核对后保存');
  } catch (error) {
    if (result) result.innerHTML = `<strong>识别失败</strong><br>${esc(error?.message || '请稍后重试')}`;
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = '重新识别';
    }
  }
}
function addOpponentContactRow() {
  $('opponentContactRows')?.insertAdjacentHTML('beforeend', opponentContactRowHtml());
}
function removeOpponentContactRow(button) {
  const rows = $('opponentContactRows');
  button.closest('.client-contact-row')?.remove();
  if (rows && !rows.querySelector('.client-contact-row')) rows.insertAdjacentHTML('beforeend', opponentContactRowHtml());
}
function openOfficialOpponentLookup() {
  const form = $('opponentInfoForm');
  const name = form?.querySelector('[name="name"]')?.value.trim() || '';
  if (!name) return toast('请先填写对方名称');
  navigator.clipboard?.writeText(name).catch(() => {});
  window.open('https://aiqicha.baidu.com/', '_blank', 'noopener,noreferrer');
  toast('对方名称已复制，正在使用默认浏览器打开爱企查');
}
async function importOpponentFromFinchina(button) {
  finchinaProfileTarget = 'opponent';
  const form = $('opponentInfoForm');
  const opponentType = form?.querySelector('[name="opponent_type"]')?.value || '';
  const companyName = form?.querySelector('[name="name"]')?.value.trim() || '';
  if (opponentType !== '单位') return toast('财汇企业信息导入仅适用于单位对方');
  if (!companyName) return toast('请先输入对方单位名称');
  const originalText = button?.textContent || '导入企业信息';
  if (button) {
    button.disabled = true;
    button.textContent = '正在查询…';
  }
  try {
    const data = await api('/api/case-manager/opponents/ai-lookup', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ action: 'search', name: companyName }),
    });
    if (!data.candidates?.length) return toast('财汇未找到匹配企业，请尝试更完整的名称');
    if (data.candidates.length === 1) {
      finchinaCompanyCandidates = data.candidates;
      await selectFinchinaCandidate(0, null);
      return;
    }
    openFinchinaCandidateModal(data, 'opponent');
  } catch (error) {
    toast(error?.message || '财汇企业信息导入失败');
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = originalText;
    }
  }
}
function renderOpponentDetail() {
  const host = $('opponentDetail');
  if (!host) return;
  const item = state.selectedOpponent;
  if (!item) {
    host.innerHTML = '<div class="empty">请选择对方，或点击“新增对方”建立档案</div>';
    return;
  }
  const isNew = !item.id;
  host.innerHTML = `
    <div class="client-detail-head">
      <h2>${esc(isNew ? '新增对方' : (item.name || '对方详情'))}</h2>
      ${state.opponentEditing ? '' : `<div class="client-detail-actions">
        <button class="btn" type="button" onclick="editOpponent(state.selectedOpponent)">修改</button>
        <button class="btn danger" type="button" onclick="deleteOpponent()">删除</button>
      </div>`}
    </div>
    <div class="client-detail-grid">
      <section class="client-info-card">
        <div class="client-card-title">对方信息</div>
        ${state.opponentEditing ? opponentFormHtml(item) : `<dl class="client-info-list">${opponentInfoRows(item).map(([label, value]) => `<dt>${esc(label)}</dt><dd>${esc(value || '-')}</dd>`).join('')}</dl>`}
      </section>
      <section class="client-cases-card">
        <div class="client-card-title">关联案件（${item.case_count || 0}）</div>
        ${opponentCasesHtml(item)}
      </section>
    </div>`;
}
function editOpponent(item = null) {
  state.selectedOpponent = item ? { ...item } : {
    opponent_type: '单位', name: '', identity_code: '', address: '', legal_representative: '',
    registered_capital: '', establishment_date: '', registration_status: '', business_scope: '',
    enterprise_nature: '', industry: '', region: '', data_source: '', source_checked_at: '',
    contacts: [{ name: '', phone: '' }], notes: '', cases: [], case_count: 0,
  };
  state.opponentEditing = true;
  renderOpponentList();
  renderOpponentDetail();
  setTimeout(() => $('opponentInfoForm')?.querySelector('[name="name"]')?.focus(), 0);
}
function cancelOpponentEdit() {
  const opponentId = state.selectedOpponent?.id;
  if (opponentId) selectOpponent(opponentId);
  else loadOpponents();
}
async function saveOpponent() {
  const form = $('opponentInfoForm');
  if (!form) return;
  const body = {};
  form.querySelectorAll('input,textarea,select').forEach(el => {
    if (!el.closest('.client-contact-row')) body[el.name] = el.value;
  });
  body.contacts = [...form.querySelectorAll('.client-contact-row')].map(row => ({
    name: row.querySelector('[name="opponent_contact_name"]')?.value || '',
    phone: row.querySelector('[name="opponent_contact_phone"]')?.value || '',
  })).filter(contact => contact.name.trim() || contact.phone.trim());
  if (!String(body.name || '').trim()) return toast('请填写对方名称或姓名');
  const existingId = state.selectedOpponent?.id;
  const saved = await api(
    existingId ? `/api/case-manager/opponents/${existingId}` : '/api/case-manager/opponents',
    { method: existingId ? 'PUT' : 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) }
  );
  state.selectedOpponent = saved;
  state.opponentEditing = false;
  toast('对方已保存');
  await loadOpponents(saved.id);
  loadList();
}
async function deleteOpponent() {
  const item = state.selectedOpponent;
  if (!item?.id) return;
  if (!confirm(`确定删除对方“${item.name}”吗？\n\n不会删除案件，但会从 ${item.case_count || 0} 个关联案件中移除该对方。`)) return;
  if (!confirm('请再次确认：删除对方档案及案件关联后无法撤销。')) return;
  await api(`/api/case-manager/opponents/${item.id}`, { method: 'DELETE' });
  toast('对方已删除');
  state.selectedOpponent = null;
  await loadOpponents();
  loadList();
}
function openOpponentCase(caseId) {
  closeOpponentManager();
  openDetail('cases', caseId);
}

function option(value, label, selected, menuLabel = '') {
  return `<option value="${esc(value)}" ${menuLabel ? `label="${esc(menuLabel)}"` : ''} ${value === selected ? 'selected' : ''}>${esc(label)}</option>`;
}
let loadTimer = null;
function debounceLoad() {
  clearTimeout(loadTimer);
  loadTimer = setTimeout(loadList, 260);
}
function installAxisLockScroller(el) {
  if (!el || el.dataset.axisLockReady === '1') return;
  el.dataset.axisLockReady = '1';
  let startX = 0;
  let startY = 0;
  let startLeft = 0;
  let axis = '';
  let raf = 0;
  const threshold = 8;
  const reset = () => {
    axis = '';
    el.style.overflowX = '';
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
  };
  el.addEventListener('touchstart', event => {
    if (event.touches.length !== 1) return;
    const touch = event.touches[0];
    startX = touch.clientX;
    startY = touch.clientY;
    startLeft = el.scrollLeft;
    axis = '';
    el.style.overflowX = '';
  }, { passive: true });
  el.addEventListener('touchmove', event => {
    if (event.touches.length !== 1) return;
    const touch = event.touches[0];
    const dx = touch.clientX - startX;
    const dy = touch.clientY - startY;
    const ax = Math.abs(dx);
    const ay = Math.abs(dy);
    if (!axis && Math.max(ax, ay) >= threshold) {
      axis = ay >= ax * 1.15 ? 'y' : ax >= ay * 1.15 ? 'x' : '';
    }
    if (axis === 'y') {
      el.style.overflowX = 'hidden';
      if (!raf && el.scrollLeft !== startLeft) {
        raf = requestAnimationFrame(() => {
          el.scrollLeft = startLeft;
          raf = 0;
        });
      }
    }
  }, { passive: true });
  el.addEventListener('touchend', reset, { passive: true });
  el.addEventListener('touchcancel', reset, { passive: true });
}
async function loadCaseCollections() {
  const archiveQuery = state.archivedQ ? `&q=${encodeURIComponent(state.archivedQ)}` : '';
  const [archived, trash] = await Promise.all([
    api(`/api/case-manager/cases?status=archived&limit=500${archiveQuery}`),
    api('/api/case-manager/cases?status=trash&limit=500'),
  ]);
  state.archivedCases = archived.items || [];
  state.trashCases = trash.items || [];
}
let archivedLoadTimer = null;
function debounceLoadArchivedCases() {
  clearTimeout(archivedLoadTimer);
  archivedLoadTimer = setTimeout(async () => {
    await loadCaseCollections();
    renderTable();
  }, 260);
}
function toggleCaseSelection(id, checked) {
  if (checked) state.selectedCaseIds.add(id);
  else state.selectedCaseIds.delete(id);
}
function toggleAllCases(checked) {
  (state.items.cases || []).forEach(item => checked ? state.selectedCaseIds.add(item.id) : state.selectedCaseIds.delete(item.id));
  renderTable();
}
function selectedCaseIds() {
  return [...state.selectedCaseIds];
}
function toggleCaseListEditing() {
  state.caseListEditing = !state.caseListEditing;
  if (!state.caseListEditing) state.selectedCaseIds.clear();
  render();
  renderTable();
}
async function bulkDeleteCases() {
  if (!requireOnlineAction()) return;
  const ids = selectedCaseIds();
  if (!ids.length) return toast('请先勾选案件');
  openCaseActionDialog('delete', ids, `确定删除选中的 ${ids.length} 个案件？删除后会进入垃圾站，关联提醒也会从列表和日历中移除。`);
}
async function bulkArchiveCases() {
  if (!requireOnlineAction()) return;
  const ids = selectedCaseIds();
  if (!ids.length) return toast('请先勾选案件');
  openCaseActionDialog('archive', ids, `确认选中的 ${ids.length} 个案件均已结案并归档？归档后将不纳入搜索和提醒。`);
}
async function executeBulkArchiveCases(ids) {
  const seriesIds = ids.filter(id => (state.items.cases || []).find(item => Number(item.id) === Number(id))?.case_kind === 'series');
  const ordinaryIds = ids.filter(id => !seriesIds.includes(id));
  if (ordinaryIds.length) await api('/api/case-manager/cases/bulk-archive', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ ids: ordinaryIds }) });
  for (const seriesId of seriesIds) {
    const series = await api(`/api/case-manager/series/${seriesId}`);
    const childIds = (series.children || []).filter(child => child.source_status === 'active').map(child => Number(child.id));
    if (childIds.length) await api('/api/case-manager/cases/bulk-archive', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ ids: childIds }) });
    await api(`/api/case-manager/series/${seriesId}/archive`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({force:true}) });
  }
  toast('已归档');
  await refreshAll();
}
async function archiveCase(id) {
  if (!requireOnlineAction()) return;
  const item = (state.items.cases || []).find(entry => Number(entry.id) === Number(id));
  if (item?.case_kind === 'series') return openSeriesForArchive(id);
  openCaseActionDialog('archive', [Number(id)], '确认该案件已结案并归档？关联提醒将同步移出在办列表和案件日历。');
}
async function toggleCasePinned(id, pinned) {
  if (!requireOnlineAction()) return;
  try {
    await api(`/api/case-manager/cases/${id}/pinned`, {
      method: 'PUT',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ pinned: !!pinned })
    });
    setLocalCasePinned(id, pinned);
    toast(pinned ? '已置顶' : '已取消置顶');
    await loadList();
    scheduleCaseOfflineSnapshot(true, 5000);
  } catch (e) {
    if (/not found|404/i.test(String(e?.message || ''))) {
      setLocalCasePinned(id, pinned);
      state.items.cases = sortCasesForList(applyLocalCasePins((state.items.cases || []).map(item => (
        Number(item.id) === Number(id) ? { ...item, pinned: !!pinned } : item
      ))));
      renderTable();
      toast(pinned ? '已本地置顶' : '已取消本地置顶');
      return;
    }
    toast(e.message || '置顶操作失败');
  }
}
async function restoreCase(id) {
  if (!requireOnlineAction()) return;
  await api(`/api/case-manager/cases/${id}/restore`, { method: 'POST' });
  toast('已恢复到在办案件');
  await refreshAll();
}
async function purgeCase(id) {
  if (!requireOnlineAction()) return;
  openCaseActionDialog('purge', [Number(id)], '确定彻底删除该案件？此操作无法恢复。');
}
function toggleCollapsedList(button) {
  button.closest('.collapsed-list')?.classList.toggle('open');
}
function renderCaseCollections() {
  const archived = state.archivedCases || [];
  const trash = state.trashCases || [];
  return `
    ${caseCollectionBlock('归档案件列表', archived, 'archived')}
    ${caseCollectionBlock('垃圾站（7天后自动清理）', trash, 'trash')}
  `;
}
function caseCollectionBlock(title, items, mode) {
  if (isMobileCaseCardMode()) {
    const cards = items.length
      ? items.map(item => mobileCollectionCard(item, mode)).join('')
      : '<div class="empty">暂无数据</div>';
    const openCls = mode === 'archived' && state.archivedQ ? ' open' : '';
    const head = mode === 'archived'
      ? `<div class="collapsed-head">
          <button class="collapsed-title-btn" type="button" onclick="toggleCollapsedList(this)"><span>${esc(title)}</span><span>${items.length} 件</span></button>
          <input class="input collapsed-search" placeholder="搜索归档案件" value="${esc(state.archivedQ)}" onclick="event.stopPropagation()" oninput="state.archivedQ=this.value; debounceLoadArchivedCases()">
        </div>`
      : `<button class="collapsed-head" type="button" onclick="toggleCollapsedList(this)"><span>${esc(title)}</span><span>${items.length} 件</span></button>`;
    return `<section class="collapsed-list${openCls}">
      ${head}
      <div class="collapsed-body"><div class="mobile-record-list mobile-collection-list">${cards}</div></div>
    </section>`;
  }
  const rows = items.length ? items.map(item => `
    <tr onclick="openDetail('cases', ${item.id})">
      <td class="title-cell"><div class="row-title" title="${esc(item.title)}">${esc(item.title)}</div></td>
      <td><span class="tag stage-tag">${esc(item.current_stage || '待补充')}</span></td>
      <td>${dateBlock(mode === 'trash' ? item.deleted_at : item.archived_at)}</td>
      <td class="action-cell">
        <div class="actions">
          ${isOfflineReadonly() ? '' : `<button class="btn" onclick="event.stopPropagation(); restoreCase(${item.id})">恢复</button>`}
          ${mode === 'trash' && !isOfflineReadonly() ? `<button class="btn danger" onclick="event.stopPropagation(); purgeCase(${item.id})">彻底删除</button>` : ''}
        </div>
      </td>
    </tr>`).join('') : `<tr><td colspan="4"><div class="empty">暂无数据</div></td></tr>`;
  const openCls = mode === 'archived' && state.archivedQ ? ' open' : '';
  const head = mode === 'archived'
    ? `<div class="collapsed-head">
        <button class="collapsed-title-btn" type="button" onclick="toggleCollapsedList(this)"><span>${esc(title)}</span><span>${items.length} 件</span></button>
        <input class="input collapsed-search" placeholder="搜索归档案件" value="${esc(state.archivedQ)}" onclick="event.stopPropagation()" oninput="state.archivedQ=this.value; debounceLoadArchivedCases()">
      </div>`
    : `<button class="collapsed-head" type="button" onclick="toggleCollapsedList(this)"><span>${esc(title)}</span><span>${items.length} 件</span></button>`;
  return `<section class="collapsed-list${openCls}">
    ${head}
    <div class="collapsed-body"><table class="data-table"><colgroup><col style="width:48%"><col style="width:24%"><col style="width:14%"><col style="width:14%"></colgroup>
      <thead><tr><th>案件名称</th><th>当前阶段</th><th>${mode === 'trash' ? '删除时间' : '归档时间'}</th><th>操作</th></tr></thead><tbody>${rows}</tbody></table></div>
  </section>`;
}

function renderTable() {
  if (!['cases','todos','hearings','preservations','appeals'].includes(activeTab)) return;
  const items = state.items[activeTab] || [];
  updateListHeroMeta();
  const wrap = document.querySelector('.table-wrap');
  if (!wrap) return;
  if (isMobileCaseCardMode()) {
    const activeCards = items.length
      ? renderMobileRecordList(activeTab, items)
      : '<div class="empty">暂无数据</div>';
    wrap.innerHTML = `${activeCards}${activeTab === 'cases' ? renderCaseCollections() : ''}`;
    return;
  }
  if (!items.length) {
    wrap.innerHTML = '<div class="empty">暂无数据</div>';
    return;
  }
  const columns = {
    cases: state.caseListEditing ? ['','案件名称','当前阶段','开庭','保全','上诉/异议','更新时间','操作'] : ['案件名称','当前阶段','开庭','保全','上诉/异议','更新时间','操作'],
    todos: ['案件名称','待办事项','提醒时间','剩余时间','备注','操作'],
    hearings: ['案件名称','类型','开庭时间','剩余时间','开庭地点','受理机构','操作'],
    preservations: ['案件名称','类型','保全财产内容','起算时间','截止时间','剩余时间','操作'],
    appeals: ['案件名称','类型','起算时间','期限（天）','截止时间','剩余时间','操作'],
  }[activeTab];
  const bodyHtml = activeTab === 'cases' ? items.map(rowHtml).join('') : reminderRowsHtml(items, columns.length);
  const caseCountColumnStart = activeTab === 'cases' ? (state.caseListEditing ? 3 : 2) : -1;
  const headHtml = columns.map((c, index) => {
    if (c === '') return `<th><input type="checkbox" onchange="toggleAllCases(this.checked)"></th>`;
    const isCaseCountColumn = caseCountColumnStart >= 0 && index >= caseCountColumnStart && index < caseCountColumnStart + 3;
    return `<th${isCaseCountColumn ? ' class="count-cell"' : ''}>${c}</th>`;
  }).join('');
  const tableClass = activeTab === 'cases' ? `data-table table-cases ${state.caseListEditing ? 'case-editing' : 'case-readonly'}` : `data-table table-${activeTab}`;
  wrap.innerHTML = `<div class="table-x-scroll"><table class="${tableClass}">${tableColGroup(activeTab)}<thead><tr>${headHtml}</tr></thead><tbody>${bodyHtml}</tbody></table>${activeTab === 'cases' ? renderCaseCollections() : ''}</div>`;
  installAxisLockScroller(wrap.querySelector('.table-x-scroll'));
}

function isMobileCaseCardMode() {
  return !!(window.matchMedia && window.matchMedia('(max-width: 900px)').matches);
}

function encodeMobileRecord(item) {
  return encodeURIComponent(JSON.stringify(item || {})).replace(/'/g, '%27');
}

function mobileDetailClick(tab, item) {
  if (item.series_group) return `openSeriesReminderGroup(JSON.parse(decodeURIComponent('${encodeMobileRecord(item)}')))`;
  return tab === 'cases'
    ? `openDetail('cases', ${Number(item.id)})`
    : `openDetail('${tab}', ${Number(item.id)}, '${encodeMobileRecord(item)}')`;
}

function compactRecordDate(value) {
  return dateOnly(value) || '待补充';
}

function mobileMoreIcon() {
  return `<svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true"><circle cx="5" cy="10" r="1.35"/><circle cx="10" cy="10" r="1.35"/><circle cx="15" cy="10" r="1.35"/></svg>`;
}

function messageSourceBadge(item) {
  if (!item?.source_message_id) return '';
  const label = item.message_created_mode === 'auto' ? '短信自动创建' : '来自司法短信';
  return `<span class="jm-source-badge" onclick="event.stopPropagation(); switchTab('judicialMessages'); setTimeout(()=>openJudicialMessage(${Number(item.source_message_id)}),80)">${label}</span>`;
}
function seriesReminderSummary(item) {
  if (!item?.series_id) return '';
  const label = [item.series_code || '', item.series_title || (item.child_display_name || '')].filter(Boolean).join(' · ');
  return label ? `<div class="series-row-summary">系列案件 · ${esc(label)}</div>` : '';
}

function mobileRecordCard(tab, item, archived = false) {
  const encoded = encodeMobileRecord(item);
  const detailClick = mobileDetailClick(tab, item);
  const editing = tab === 'cases' && state.caseListEditing;
  let tag = '';
  let meta = '';
  let subline = '';

  if (tab === 'cases') {
    tag = item.case_kind === 'series'
      ? `<span class="series-badge">系列案件 · ${Number(item.series_child_count || 0)}案</span><span class="tag stage-tag">${Number(item.series_active_count || 0)}案在办</span>`
      : `<span class="tag stage-tag">${esc(item.current_stage || '待补充')}</span>`;
    meta = `<span>更新 <strong>${esc(compactRecordDate(item.updated_at))}</strong></span>
      <span class="mobile-card-counts"><span>开庭 ${Number(item.hearing_count || 0)}</span><span>保全 ${Number(item.preservation_count || 0)}</span><span>上诉 ${Number(item.appeal_count || 0)}</span></span>`;
  } else if (tab === 'todos') {
    const recurrence = TODO_RECURRENCE_LABELS[item.recurrence] || '';
    tag = `<span class="tag">${esc(item.todo_title || '待办')}</span>${recurrence ? `<span class="tag">${recurrence}</span>` : ''}${messageSourceBadge(item)}`;
    meta = `<span class="${dueClass(item.remind_at) ? 'deadline-danger' : ''}">提醒 <strong>${esc(compactRecordDate(item.remind_at))}</strong></span>`;
    subline = item.notes || '';
  } else if (tab === 'hearings') {
    tag = `<span class="tag">${esc(item.reminder_type || '开庭')}</span>${messageSourceBadge(item)}`;
    meta = `<span class="${dueClass(item.hearing_at) ? 'deadline-danger' : ''}">时间 <strong>${esc(fmt(item.hearing_at) || '待补充')}</strong></span>`;
    subline = [item.location, item.court].filter(Boolean).join(' · ');
  } else if (tab === 'preservations') {
    tag = `<span class="tag">${esc(item.preservation_type || '保全')}</span>`;
    meta = `<span class="${dueClass(item.deadline_at) ? 'deadline-danger' : ''}">截止 <strong>${esc(compactRecordDate(item.deadline_at))}</strong></span>`;
    subline = item.asset_content || '';
  } else {
    tag = `<span class="tag">${esc(item.appeal_type || '上诉/异议')}</span>`;
    meta = `<span class="${dueClass(item.deadline_at) ? 'deadline-danger' : ''}">截止 <strong>${esc(compactRecordDate(item.deadline_at))}</strong></span>${item.period_days != null ? `<span>期限 ${esc(item.period_days)} 天</span>` : ''}`;
    subline = [item.case_no, item.court].filter(Boolean).join(' · ');
  }

  return `<article class="mobile-record-card mobile-record-${tab}${item.pinned ? ' pinned' : ''}${editing ? ' editing' : ''}${archived ? ' archived' : ''}" onclick="${detailClick}">
    ${editing ? `<input class="mobile-card-select" type="checkbox" aria-label="选择案件" ${state.selectedCaseIds.has(item.id) ? 'checked' : ''} onclick="event.stopPropagation()" onchange="toggleCaseSelection(${Number(item.id)}, this.checked)">` : ''}
    <div class="mobile-card-content">
      <div class="mobile-card-title-row"><strong class="mobile-card-title">${esc(item.title || '未命名案件')}</strong></div>
      <div class="mobile-card-meta">${tag}${meta}</div>
      ${tab === 'cases' && item.pinned ? pinnedCaseDetails(item, true) : ''}
      ${seriesReminderSummary(item)}
      ${subline ? `<div class="mobile-card-subline">${esc(subline)}</div>` : ''}
    </div>
    <button class="mobile-card-more" type="button" aria-label="更多操作" onclick="openMobileRecordActions(event, '${tab}', '${encoded}')">${mobileMoreIcon()}</button>
  </article>`;
}

function mobileCollectionCard(item, mode) {
  const encoded = encodeMobileRecord(item);
  const dateValue = mode === 'trash' ? item.deleted_at : item.archived_at;
  return `<article class="mobile-record-card mobile-record-collection" onclick="openDetail('cases', ${Number(item.id)})">
    <div class="mobile-card-content">
      <div class="mobile-card-title-row"><strong class="mobile-card-title">${esc(item.title || '未命名案件')}</strong></div>
      <div class="mobile-card-meta"><span class="tag stage-tag">${esc(item.current_stage || '待补充')}</span><span>${mode === 'trash' ? '删除' : '归档'} <strong>${esc(compactRecordDate(dateValue))}</strong></span></div>
    </div>
    <button class="mobile-card-more" type="button" aria-label="更多操作" onclick="openMobileCollectionActions(event, '${mode}', '${encoded}')">${mobileMoreIcon()}</button>
  </article>`;
}

function renderMobileRecordList(tab, items) {
  if (tab === 'cases') {
    return `<div class="mobile-record-list">${items.map(item => mobileRecordCard(tab, item)).join('')}</div>`;
  }
  if (state.hideOverdue) items = items.filter(item => !isItemOverdue(item));
  // 手机上的开庭等记录必须完整呈现；只有用户主动勾选“隐藏已过期”时才过滤。
  return `<div class="mobile-record-list">${items.map(item => mobileRecordCard(tab, item)).join('')}</div>`;
}

function openMobileRecordActions(event, tab, encodedItem) {
  event?.preventDefault();
  event?.stopPropagation();
  const item = JSON.parse(decodeURIComponent(encodedItem));
  state.mobileRecordAction = { tab, item, collectionMode: '' };
  $('mobileRecordActionTitle').textContent = item.title || tabMeta[tab]?.label || '记录操作';
  const canEdit = !isOfflineReadonly() || (tab === 'cases' && canOfflineEditCase());
  const buttons = [
    tab === 'cases' ? `<button class="btn primary" type="button" onclick="runMobileRecordAction('files')">案件文件</button>` : `<button class="btn" type="button" onclick="runMobileRecordAction('view')">查看详情</button>`,
    tab === 'cases' ? `<button class="btn" type="button" onclick="runMobileRecordAction('view')">查看详情</button>` : '',
    tab !== 'cases' && canEdit ? `<button class="btn" type="button" onclick="runMobileRecordAction('local-files')">本地文件</button>` : '',
    canEdit ? `<button class="btn" type="button" onclick="runMobileRecordAction('edit')">编辑</button>` : '',
    tab === 'cases' && canEdit ? `<button class="btn" type="button" onclick="runMobileRecordAction('pin')">${item.pinned ? '取消置顶' : '置顶案件'}</button>` : '',
    tab === 'todos' && !isOfflineReadonly() ? `<button class="btn complete" type="button" onclick="runMobileRecordAction('complete')">完成待办</button>` : '',
    tab !== 'cases' && canEdit ? `<button class="btn danger" type="button" onclick="runMobileRecordAction('delete')">删除</button>` : '',
  ].filter(Boolean);
  $('mobileRecordActionButtons').innerHTML = buttons.join('');
  $('mobileRecordActionMask').classList.add('show');
}

function openMobileCollectionActions(event, mode, encodedItem) {
  event?.preventDefault();
  event?.stopPropagation();
  const item = JSON.parse(decodeURIComponent(encodedItem));
  state.mobileRecordAction = { tab: 'cases', item, collectionMode: mode };
  $('mobileRecordActionTitle').textContent = item.title || '案件操作';
  $('mobileRecordActionButtons').innerHTML = `
    <button class="btn" type="button" onclick="runMobileRecordAction('view')">查看详情</button>
    ${isOfflineReadonly() ? '' : `<button class="btn" type="button" onclick="runMobileRecordAction('restore')">恢复案件</button>`}
    ${mode === 'trash' && !isOfflineReadonly() ? `<button class="btn danger" type="button" onclick="runMobileRecordAction('purge')">彻底删除</button>` : ''}`;
  $('mobileRecordActionMask').classList.add('show');
}

function closeMobileRecordActions() {
  $('mobileRecordActionMask')?.classList.remove('show');
}

function runMobileRecordAction(action) {
  const context = state.mobileRecordAction;
  if (!context?.item) return;
  const { tab, item } = context;
  closeMobileRecordActions();
  if (action === 'local-files') return openMatterLocalFiles(tab, item.id, encodeMobileRecord(item));
  if (action === 'files') return openCaseFiles(item.id, item.title || '案件');
  if (action === 'view') return openDetail(tab, item.id, tab === 'cases' ? '' : encodeMobileRecord(item));
  if (action === 'edit') return openEditor(tab, item);
  if (action === 'pin') return toggleCasePinned(item.id, !item.pinned);
  if (action === 'complete') return openCompleteTodoDialog(item);
  if (action === 'archive') return archiveCase(item.id);
  if (action === 'delete') return deleteItem(tab, item.id);
  if (action === 'restore') return restoreCase(item.id);
  if (action === 'purge') return purgeCase(item.id);
}
function tableColGroup(tab) {
  const widths = {
    cases: state.caseListEditing ? ['4%','48%','12%','5%','5%','5%','8%','13%'] : ['52%','12%','5%','5%','5%','8%','13%'],
    todos: ['26%','17%','14%','10%','13%','20%'],
    hearings: ['26%','7%','11%','8%','18%','12%','18%'],
    preservations: ['25%','8%','20%','10%','10%','9%','18%'],
    appeals: ['38%','8%','10%','8%','10%','8%','18%'],
  }[tab] || [];
  if (tab === 'cases') {
    const classes = state.caseListEditing
      ? ['select', 'title', 'type', 'count', 'count', 'count appeal', 'updated', 'actions']
      : ['title', 'type', 'count', 'count', 'count appeal', 'updated', 'actions'];
    return `<colgroup>${widths.map((w, i) => `<col class="col-${classes[i].replace(' ', ' col-')}" style="width:${w}">`).join('')}</colgroup>`;
  }
  // Reserve a fixed action column; distribute the rest among content columns.
  const actionWidth = tab === 'todos' ? 296 : 248;
  const shares = widths.slice(0,-1).map(parseFloat);
  const total = shares.reduce((sum,value) => sum+value,0);
  return `<colgroup>${shares.map(value => {
    const share = value / total;
    return `<col style="width:calc(${share*100}% - ${share*actionWidth}px)">`;
  }).join('')}<col class="col-actions" style="width:${actionWidth}px"></colgroup>`;
}
function reminderRowsHtml(items, columnCount) {
  if (state.hideOverdue) items = items.filter(item => !isItemOverdue(item));
  const visible = [];
  const archived = [];
  items.forEach(item => (isOldOverdue(getDueValue(item)) ? archived : visible).push(item));
  const rows = visible.map(item => rowHtml(item)).join('');
  if (!archived.length) return rows;
  return rows + `
    <tr class="archive-toggle-row">
      <td colspan="${columnCount}">
        <button type="button" onclick="toggleArchivedOverdue(this)">展开 ${archived.length} 条超过半个月的已过期记录</button>
      </td>
    </tr>
    ${archived.map(item => rowHtml(item, true)).join('')}
  `;
}
function formatMulti(value) {
  return esc(value || '').replace(/\n/g, '<br>');
}
function dateBlock(value) {
  const text = fmt(value);
  if (!text) return '';
  const [date, time] = text.split(' ');
  return `<div class="date-main">${esc(date || '')}</div>${time ? `<div class="date-muted">${esc(time)}</div>` : ''}`;
}
function pinnedClientNames(item) {
  const supplied = Array.isArray(item.list_client_names) ? item.list_client_names : [];
  const parties = Array.isArray(item.parties)
    ? item.parties.filter(p => p.party_group === 'client').map(p => p.name)
    : [];
  return [...new Set([...supplied, ...parties].map(value => String(value || '').trim()).filter(Boolean))].slice(0, 3);
}
function pinnedCaseNumbers(item) {
  const supplied = Array.isArray(item.list_case_numbers) ? item.list_case_numbers : [];
  const stored = Array.isArray(item.case_numbers) ? [...item.case_numbers].reverse() : [];
  const seen = new Set();
  return [...supplied, ...stored].filter(number => {
    const text = String(number?.case_no || '').trim();
    if (!text || seen.has(text)) return false;
    seen.add(text);
    return true;
  }).slice(0, 2);
}
function pinnedCaseDetails(item, mobile = false) {
  const clients = pinnedClientNames(item);
  const numbers = pinnedCaseNumbers(item);
  const clientText = clients.join('、');
  const numberText = numbers.map(number => number.case_no).join('、');
  const primary = [
    clientText ? `<span class="case-pin-detail"><span class="case-pin-detail-label">委托人</span>${esc(clientText)}</span>` : '',
    item.case_type ? `<span class="case-pin-detail"><span class="case-pin-detail-label">案件类型</span>${esc(item.case_type)}</span>` : '',
  ].filter(Boolean).join('');
  const secondary = numberText
    ? `<div class="case-pin-detail-line"><span class="case-pin-detail"><span class="case-pin-detail-label">近期案号</span>${esc(numberText)}</span></div>`
    : '';
  if (!primary && !secondary) return '';
  return `<div class="${mobile ? 'mobile-pinned-details' : 'case-pin-details'}">${primary ? `<div class="case-pin-detail-line">${primary}</div>` : ''}${secondary}</div>`;
}
function dueTag(value) {
  return `<span class="tag ${dueClass(value)}">${esc(dateOnly(value))}</span>`;
}
function remainingDaysHtml(value) {
  const due = parseDateLoose(value);
  if (!due) return '<span class="remaining-days remaining-days-empty">—</span>';
  due.setHours(0, 0, 0, 0);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const days = Math.round((due - today) / 86400000);
  if (days < 0) {
    return `<span class="remaining-days remaining-days-overdue" title="已超过截止时间 ${Math.abs(days)} 日"><span class="remaining-days-number">已逾期 ${Math.abs(days)}</span>日</span>`;
  }
  if (days === 0) {
    return '<span class="remaining-days remaining-days-urgent" title="今日截止"><span class="remaining-days-number">今日</span>截止</span>';
  }
  const urgencyClass = days <= 3 ? ' remaining-days-urgent' : days <= 14 ? ' remaining-days-soon' : '';
  return `<span class="remaining-days${urgencyClass}" title="距截止时间还有 ${days} 日"><span class="remaining-days-number">${days}</span> 日</span>`;
}
function actionButtons(tab, item, itemJson) {
  if (tab === 'cases' && item.case_kind === 'series') {
    return `<div class="actions">
      <button class="btn" onclick='event.stopPropagation(); openCaseFiles(${Number(item.id)}, ${JSON.stringify(item.title || '系列案件').replace(/'/g, '\\u0027')})'>案件文件</button>
      <button class="btn" onclick="event.stopPropagation(); openSeriesWorkspace(${Number(item.id)})">管理系列</button>
    </div>`;
  }
  if (tab === 'cases') {
    return `<div class="actions">
      <button class="btn" onclick='event.stopPropagation(); openCaseFiles(${Number(item.id)}, ${JSON.stringify(item.title || '案件').replace(/'/g, '\\u0027')})'>案件文件</button>
      <button class="btn" onclick="event.stopPropagation(); openCaseArchive(${Number(item.id)})">案卷归档</button>
      <button class="btn" onclick='event.stopPropagation(); openDetail("cases", ${Number(item.id)})'>查看</button>
    </div>`;
  }
  if (isOfflineReadonly()) {
    return `<div class="actions">
      <button class="btn" onclick="event.stopPropagation(); openDetail('${tab}', ${item.id}, '${encodeURIComponent(itemJson)}')">查看</button>
    </div>`;
  }
  return `<div class="actions matter-row-actions">
    <button class="btn matter-local-trigger" type="button" onclick="event.stopPropagation(); openMatterLocalFiles('${tab}', ${Number(item.id)}, '${encodeMobileRecord(item)}', this)">本地文件</button>
    <button class="btn" onclick="event.stopPropagation(); openDetail('${tab}', ${item.id}, '${encodeURIComponent(itemJson)}')">查看</button>
    <button class="btn" onclick='event.stopPropagation(); openEditor("${tab}", ${itemJson})'>编辑</button>
    ${tab === 'todos' ? `<button class="btn complete" onclick='event.stopPropagation(); openCompleteTodoDialog(${itemJson})'>完成</button>` : ''}
    <button class="btn danger" onclick="event.stopPropagation(); deleteItem('${tab}', ${item.id})">删除</button>
  </div>`;
}

function openCompleteTodoDialog(item) {
  if (!requireOnlineAction()) return;
  state.completingTodo = item;
  $('completeDialogTitle').textContent = `完成：${item.todo_title || '待办事项'}`;
  $('completeDialogDescription').textContent = `完成后将自动录入“${item.title || '对应案件'}”的案件台账。`;
  $('todoCompletedAt').value = formatDateInput(new Date());
  $('completeDialogMask').classList.add('show');
  $('todoCompletedAt').focus();
}

function closeCompleteTodoDialog() {
  $('completeDialogMask').classList.remove('show');
  state.completingTodo = null;
}

async function confirmCompleteTodo() {
  const item = state.completingTodo;
  const completedAt = $('todoCompletedAt').value;
  if (!item) return;
  if (!completedAt) return toast('请选择完成日期');
  const button = $('confirmCompleteTodoBtn');
  button.disabled = true;
  button.textContent = '正在完成…';
  try {
    await api(`/api/case-manager/todos/${item.id}/complete`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ completed_at: completedAt }),
    });
    closeCompleteTodoDialog();
    toast('待办已完成，并已录入案件台账');
    await refreshAll();
  } catch (e) {
    toast(e.message || '完成操作失败');
  } finally {
    button.disabled = false;
    button.textContent = '确定完成';
  }
}
function rowHtml(item, archived = false) {
  const itemJson = JSON.stringify(item).replace(/'/g, '&#39;');
  const actions = actionButtons(activeTab, item, itemJson);
  const rowCls = archived ? ' class="archived-overdue"' : '';
  if (item.series_group) {
    const columnCount = {todos:6,hearings:7,preservations:7,appeals:7}[activeTab] || 5;
    return `<tr${rowCls} onclick='openSeriesReminderGroup(${itemJson})'><td colspan="${columnCount}"><div class="row-title"><span class="series-badge">系列汇总 · ${Number(item.group_count||0)}项</span>${esc(item.series_title||item.title||'')}</div><div class="series-row-summary">${esc(item.group_date||'')} · 涉及 ${(item.group_items||[]).map(x=>`${x.series_code||''} ${x.child_display_name||''}`).join('、')}</div></td></tr>`;
  }
  if (activeTab === 'cases') {
    return `<tr class="${item.pinned ? 'case-row-pinned' : ''}" data-stella-case-id="${Number(item.id)}" data-stella-case-title="${esc(item.title)}" onclick="openDetail('cases', ${item.id})">
      ${state.caseListEditing ? `<td onclick="event.stopPropagation()"><input type="checkbox" ${state.selectedCaseIds.has(item.id) ? 'checked' : ''} onchange="toggleCaseSelection(${item.id}, this.checked)"></td>` : ''}
      <td class="title-cell">
        <div class="case-title-inline">
          ${state.caseListEditing ? `<button class="pin-case-btn ${item.pinned ? 'pinned' : ''}" type="button" ${isOfflineReadonly() ? 'disabled' : ''} onclick="event.stopPropagation(); toggleCasePinned(${item.id}, ${item.pinned ? 'false' : 'true'})">${item.pinned ? '取消置顶' : '置顶'}</button>` : ''}
          <div class="case-title-content">
            <div class="case-title-heading"><div class="row-title" title="${esc(item.title)}">${item.case_kind === 'series' ? `<span class="series-badge">系列案件 · ${Number(item.series_child_count || 0)}案</span>` : ''}${esc(item.title)}</div></div>
            ${item.case_kind === 'series' ? `<div class="series-row-summary">已结 ${Number(item.series_archived_count || 0)}/${Number(item.series_child_count || 0)} · ${esc(seriesStageText(item.series_stage_summary || {}))}</div>` : ''}
            ${item.pinned ? pinnedCaseDetails(item) : ''}
          </div>
        </div>
      </td>
      <td><span class="tag stage-tag">${esc(item.case_kind === 'series' ? `${Number(item.series_active_count || 0)}案在办` : (item.current_stage || '待补充'))}</span></td>
      <td class="count-cell"><span class="count-badge">${item.hearing_count || 0}</span></td>
      <td class="count-cell"><span class="count-badge">${item.preservation_count || 0}</span></td>
      <td class="count-cell"><span class="count-badge">${item.appeal_count || 0}</span></td>
      <td>${dateBlock(item.updated_at)}</td>
      <td class="action-cell">${actions}</td>
    </tr>`;
  }
  if (activeTab === 'todos') {
    return `<tr${rowCls} onclick="openDetail('todos', ${item.id}, '${encodeURIComponent(itemJson)}')">
      <td class="title-cell"><div class="row-title" title="${esc(item.title)}">${esc(item.title)}${messageSourceBadge(item)}</div>${seriesReminderSummary(item)}</td>
      <td class="todo-cell"><div class="todo-tags"><span class="tag todo-tag">${esc(item.todo_title || '待办事项')}</span>${TODO_RECURRENCE_LABELS[item.recurrence] ? `<span class="tag todo-tag">${TODO_RECURRENCE_LABELS[item.recurrence]}</span>` : ''}</div></td>
      <td>${dateBlock(item.remind_at)}</td>
      <td>${remainingDaysHtml(item.remind_at)}</td>
      <td><div class="multi-text">${formatMulti(item.notes)}</div></td>
      <td class="action-cell">${actions}</td>
    </tr>`;
  }
  if (activeTab === 'hearings') {
    return `<tr${rowCls} onclick="openDetail('hearings', ${item.id}, '${encodeURIComponent(itemJson)}')">
      <td class="title-cell"><div class="row-title" title="${esc(item.title)}">${esc(item.title)}${messageSourceBadge(item)}</div>${seriesReminderSummary(item)}</td>
      <td><span class="tag">${esc(item.reminder_type)}</span></td>
      <td>${dateBlock(item.hearing_at)}</td>
      <td>${remainingDaysHtml(item.hearing_at)}</td>
      <td><div class="multi-text">${formatMulti(item.location)}</div></td>
      <td><div class="multi-text">${formatMulti(item.court)}</div></td>
      <td class="action-cell">${actions}</td>
    </tr>`;
  }
  if (activeTab === 'preservations') {
    return `<tr${rowCls} onclick="openDetail('preservations', ${item.id}, '${encodeURIComponent(itemJson)}')">
      <td class="title-cell"><div class="row-title" title="${esc(item.title)}">${esc(item.title)}</div>${seriesReminderSummary(item)}</td>
      <td><span class="tag">${esc(item.preservation_type || '保全')}</span></td>
      <td><div class="multi-text">${formatMulti(item.asset_content)}</div></td>
      <td>${dateBlock(item.start_at)}</td>
      <td>${dueTag(item.deadline_at)}</td>
      <td>${remainingDaysHtml(item.deadline_at)}</td>
      <td class="action-cell">${actions}</td>
    </tr>`;
  }
  return `<tr${rowCls} onclick="openDetail('appeals', ${item.id}, '${encodeURIComponent(itemJson)}')">
    <td class="title-cell"><div class="row-title" title="${esc(item.title)}">${esc(item.title)}</div>${seriesReminderSummary(item)}</td>
    <td><span class="tag">${esc(item.appeal_type)}</span></td>
    <td>${dateBlock(item.start_at)}</td>
    <td><strong>${esc(item.period_days ?? '')}</strong></td>
    <td>${dueTag(item.deadline_at)}</td>
    <td>${remainingDaysHtml(item.deadline_at)}</td>
    <td class="action-cell">${actions}</td>
  </tr>`;
}
function getDueValue(item) {
  return activeTab === 'todos' ? item.remind_at : activeTab === 'hearings' ? item.hearing_at : item.deadline_at;
}
function isItemOverdue(item) {
  const value = item.series_group ? item.group_date : getDueValue(item);
  if (!value) return false;
  const today = new Date(); today.setHours(0,0,0,0);
  const due = new Date(String(value).slice(0,10)); due.setHours(0,0,0,0);
  if (Number.isNaN(due.getTime())) return false;
  return due < today;
}
function isEventOverdue(event) {
  const due = parseDateLoose(event.due_at);
  if (!due) return false;
  const today = new Date(); today.setHours(0,0,0,0);
  due.setHours(0,0,0,0);
  return due < today;
}
function setHideOverdue(value) {
  state.hideOverdue = !!value;
  try { localStorage.setItem('cm_hide_overdue', state.hideOverdue ? '1' : '0'); } catch (e) {}
  document.querySelectorAll('[data-hide-overdue-toggle]').forEach(el => el.classList.toggle('active', state.hideOverdue));
  if (activeTab === 'caseCalendar') loadCaseCalendar();
  else if (['todos','hearings','preservations','appeals'].includes(activeTab)) renderTable();
  renderMobileFilters();
}
function hideOverdueToggle() {
  return `<label class="check-pill hide-overdue-toggle${state.hideOverdue ? ' active' : ''}" data-hide-overdue-toggle title="${state.hideOverdue ? '显示已过期事项' : '隐藏已过期事项'}"><input type="checkbox" ${state.hideOverdue ? 'checked' : ''} onchange="setHideOverdue(this.checked)">隐藏已过期</label>`;
}
function isOldOverdue(value) {
  if (!value) return false;
  const today = new Date(); today.setHours(0,0,0,0);
  const due = new Date(String(value).slice(0,10)); due.setHours(0,0,0,0);
  if (Number.isNaN(due.getTime())) return false;
  return (today - due) / 86400000 > 15;
}
function toggleArchivedOverdue(btn) {
  const rows = document.querySelectorAll('tr.archived-overdue');
  const show = rows.length && !rows[0].classList.contains('show');
  rows.forEach(row => row.classList.toggle('show', show));
  btn.textContent = show ? '收起超过半个月的已过期记录' : `展开 ${rows.length} 条超过半个月的已过期记录`;
}
function dueClass(value) {
  if (!value) return '';
  const today = new Date(); today.setHours(0,0,0,0);
  const due = new Date(String(value).slice(0,10));
  return due < today ? 'danger' : '';
}

async function openDetail(tab, id, encodedItem = '') {
  clearContractWorkspaceChrome();
  setSeriesChildDetailOverlay(false);
  let item = null;
  if (tab === 'cases') {
    const listed = (state.items.cases || []).find(x => Number(x.id) === Number(id)) || offlineCaseById(id);
    if (listed?.case_kind === 'series') return openSeriesWorkspace(id);
    item = await api(`/api/case-manager/cases?case_id=${id}`);
    if (item?.case_kind === 'series') return openSeriesWorkspace(id);
  } else if (encodedItem) {
    item = JSON.parse(decodeURIComponent(encodedItem));
  } else {
    item = (state.items[tab] || []).find(x => x.id === id);
  }
  if (!item) return;
  if (tab === 'cases') {
    if (item.case_kind === 'series_child') {
      const seriesId = Number(item.parent_series_id || 0);
      const series = seriesId
        ? (isOfflineReadonly() ? offlineSeriesData(seriesId) : await api(`/api/case-manager/series/${seriesId}`))
        : null;
      const child = seriesId && !isOfflineReadonly()
        ? await api(`/api/case-manager/series/${seriesId}/children/${item.id}`)
        : item;
      return openCaseDetailDrawer(applySeriesDetailMappings(child, series), seriesId);
    }
    return openCaseDetailDrawer(item);
  }
  if (tab !== 'cases' || Number(state.caseResearch?.caseId || 0) !== Number(item.id || 0)) {
    resetCaseResearchWorkspace();
    $('drawer')?.classList.remove('case-research-active');
    renderCaseResearchFloatHost();
  }
  state.editing = { tab, item, mode: 'detail', inlineSection: '', isNew: false, caseNumbersExpanded: false };
  if (tab === 'cases') rememberOpenCaseDetail(item);
  $('drawerTitle').textContent = tab === 'cases'
    ? (item.title || '案件详情')
    : `${tabMeta[tab]?.label || '记录'}详情`;
  $('drawerBody').innerHTML = detailHtml(tab, item) + (['todos','hearings','preservations','appeals'].includes(tab) ? matterLocalLinksSection(tab, item.id) : '');
  if (['todos','hearings','preservations','appeals'].includes(tab)) loadMatterLocalLinks(tab, item.id);
  if (tab === 'hearings') loadHearingContactSection(item);
  makeDetailFieldsCopyable($('drawerBody'));
  $('drawerFoot').innerHTML = `
    ${tab === 'cases' ? `<div class="case-detail-shortcuts">
      <button class="btn case-detail-shortcut" type="button" onclick="toggleCaseResearchWorkspace(${Number(item.id)}, 'ledger')">案件台账</button>
      <button class="btn case-detail-shortcut" type="button" onclick="toggleCaseResearchWorkspace(${Number(item.id)}, 'memo')">案件备忘录</button>
    </div>` : ''}
    <button class="btn" onclick="closeEditor()">关闭</button>
    ${tab === 'appeals' && Number(item.case_id || 0) ? `<button class="btn" onclick="closeEditor();switchTab('cases');openDetail('cases', ${Number(item.case_id)})">查看案件信息</button>` : ''}
    ${tab === 'cases' ? '' : `<button class="btn primary" onclick="openEditor('${tab}', state.editing.item)">编辑</button>`}
  `;
  $('drawerMask').classList.add('show');
  $('drawer').classList.add('show');
  $('drawer').classList.add('detail-mode');
  $('drawer').classList.remove('edit-wide');
  if (tab === 'cases') loadCaseAutomationPanel(Number(item.id));
  notifyCaseManagerContext(
    item.title || `${tabMeta[tab]?.label || '记录'}详情`,
    currentCaseManagerPageLabel(),
    tab === 'cases' ? { id: item.id, title: item.title } : null
  );
}

function openCaseDetailDrawer(item, seriesId = 0) {
  resetCaseResearchWorkspace();
  $('drawer')?.classList.remove('case-research-active');
  renderCaseResearchFloatHost();
  setSeriesChildDetailOverlay(Number(seriesId || 0) > 0);
  state.editing = { tab: 'cases', item, mode: 'detail', inlineSection: '', isNew: false, caseNumbersExpanded: false, seriesDetailMappingSeriesId: Number(seriesId || 0) };
  rememberOpenCaseDetail(item, seriesId);
  $('drawerTitle').textContent = item.title || '案件详情';
  $('drawerBody').innerHTML = detailHtml('cases', item);
  makeDetailFieldsCopyable($('drawerBody'));
  $('drawerFoot').innerHTML = `<div class="case-detail-shortcuts">
    <button class="btn case-detail-shortcut" type="button" onclick="toggleCaseResearchWorkspace(${Number(item.id)}, 'ledger')">案件台账</button>
    <button class="btn case-detail-shortcut" type="button" onclick="toggleCaseResearchWorkspace(${Number(item.id)}, 'memo')">案件备忘录</button>
    ${Number(seriesId || 0) ? '<button class="btn case-detail-shortcut" type="button" onclick="openSeriesDetailMappingPanel()">主表字段映射</button>' : ''}
  </div><button class="btn" onclick="closeEditor()">关闭</button>`;
  $('drawerMask').classList.add('show');
  $('drawer').classList.add('show', 'detail-mode');
  $('drawer').classList.remove('edit-wide');
  loadCaseAutomationPanel(Number(item.id));
  notifyCaseManagerContext(item.title || '案件详情', currentCaseManagerPageLabel(), { id: item.id, title: item.title });
}

function setSeriesChildDetailOverlay(active) {
  const enabled = !!active;
  $('drawerMask')?.classList.toggle('series-child-detail-overlay', enabled);
  $('drawer')?.classList.toggle('series-child-detail-overlay', enabled);
  $('caseResearchFloatHost')?.classList.toggle('series-child-detail-overlay', enabled);
}

function openNewCaseDetail() {
  clearContractWorkspaceChrome();
  forgetOpenCaseDetail();
  setSeriesChildDetailOverlay(false);
  resetCaseResearchWorkspace();
  renderCaseResearchFloatHost();
  const item = {
    title: '', case_type: '', current_stage: '', court_contact: '', party_contact: '', memo: '',
    parties: [], case_numbers: [], todos: [], hearings: [], preservations: [], appeals: [], audit_logs: []
  };
  state.editing = { tab: 'cases', item, mode: 'detail', inlineSection: '', isNew: true, caseNumbersExpanded: false };
  $('drawerFoot').innerHTML = `<button class="btn" onclick="closeEditor()">关闭</button>`;
  $('drawerMask').classList.add('show');
  $('drawer').classList.add('show', 'detail-mode');
  $('drawer').classList.remove('edit-wide');
  renderOpenCaseDetail();
  notifyCaseManagerContext('新建案件', currentCaseManagerPageLabel());
}

function resetCaseResearchWorkspace() {
  state.caseResearch = { caseId: 0, section: '', projectId: 0, data: null, loading: false, query: '', sideExpanded: true };
}

function caseResearchLabel(section) {
  return section === 'memo' ? '案件备忘录' : '案件台账';
}

function caseResearchItems() {
  const data = state.caseResearch.data || {};
  return state.caseResearch.section === 'memo' ? (data.memo_entries || []) : (data.ledgers || []);
}

function caseResearchFilteredItems() {
  const query = String(state.caseResearch.query || '').trim().toLowerCase();
  if (!query) return caseResearchItems();
  return caseResearchItems().filter(item => [item.title, item.content, item.happened_at, item.created_at, item.updated_at]
    .join(' ').toLowerCase().includes(query));
}

function caseResearchEntriesHtml() {
  const items = caseResearchFilteredItems();
  const label = caseResearchLabel(state.caseResearch.section);
  if (!items.length) {
    const hasQuery = String(state.caseResearch.query || '').trim();
    return `<div class="case-research-empty">${hasQuery ? `未找到匹配的${label}` : `暂无${label}，可点击右上角“新增”记录案件进展。`}</div>`;
  }
  return `<div class="case-research-timeline">${items.map(item => {
    const text = String(item.content || '');
    const brief = text.length > 220 ? `${text.slice(0, 220)}…` : text;
    return `<article class="case-research-entry">
      <div class="case-research-entry-head"><strong>${esc(item.title || `未命名${label.replace('案件', '')}`)}</strong><time>${esc(dateOnly(item.happened_at || item.created_at))}</time></div>
      <p>${esc(brief)}</p>
      <div class="case-research-entry-actions">
        <button type="button" onclick="openCaseResearchEntryView(${Number(item.id)})">查看</button>
        <button type="button" onclick="openCaseResearchEntryEditor(${Number(item.id)})">修改</button>
        <button class="danger" type="button" onclick="deleteCaseResearchEntry(${Number(item.id)})">删除</button>
      </div>
    </article>`;
  }).join('')}</div>`;
}

function caseResearchWorkspaceHtml(item) {
  const research = state.caseResearch;
  const label = caseResearchLabel(research.section);
  if (research.loading) {
    return `<section class="case-research-workspace"><div class="case-research-workspace-head"><div><span class="case-research-workspace-kicker">CASE WORKSPACE</span><h3>${label}</h3></div></div><div class="case-research-empty">正在读取${label}…</div></section>`;
  }
  const error = research.error ? `<div class="case-research-empty">${esc(research.error)}</div>` : '';
  return `<section class="case-research-workspace" aria-label="${label}">
    <header class="case-research-workspace-head">
      <div><span class="case-research-workspace-kicker">${research.section === 'memo' ? 'CASE MEMOS' : 'CASE TIMELINE'}</span><h3>${label}</h3></div>
      <div class="case-research-workspace-actions">
        <button class="btn" type="button" onclick="exportCaseResearchEntries()">导出 Excel</button>
        <button class="btn primary" type="button" onclick="openCaseResearchEntryEditor()">新增${research.section === 'memo' ? '备忘录' : '台账'}</button>
      </div>
    </header>
    <div class="case-research-workspace-body">
      <label class="case-research-search">
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true"><circle cx="6.5" cy="6.5" r="4.7" stroke="currentColor" stroke-width="1.5"/><path d="M10.2 10.2L14 14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
        <input id="caseResearchSearch" type="search" value="${esc(research.query)}" placeholder="检索标题、内容或日期" oninput="setCaseResearchSearch(this.value)">
        <button type="button" onclick="setCaseResearchSearch('')" ${research.query ? '' : 'hidden'}>清除</button>
      </label>
      <div class="case-research-timeline-results" id="caseResearchTimelineResults">${error || caseResearchEntriesHtml()}</div>
    </div>
  </section>`;
}

function refreshCaseResearchWorkspace() {
  if (state.editing?.tab !== 'cases' || !state.editing?.item) return;
  $('drawer')?.classList.toggle('case-research-active', !!state.caseResearch.section);
  renderCaseResearchFloatHost();
}

function renderCaseResearchFloatHost() {
  const host = $('caseResearchFloatHost');
  if (!host) return;
  const show = state.editing?.tab === 'cases' && !!state.caseResearch.section && !!state.editing?.item;
  if (!show) {
    host.classList.remove('show', 'closing');
    host.innerHTML = '';
    return;
  }
  host.classList.remove('closing');
  host.classList.add('show');
  host.innerHTML = caseResearchWorkspaceHtml(state.editing.item);
  requestAnimationFrame(() => {
    const card = host.querySelector('.case-research-workspace');
    if (!card || !host.classList.contains('show')) return;
    positionCaseResearchFloatCard();
    card.classList.add('is-visible');
    // The detail drawer animates its width/transform. Recalculate after the
    // transition so the card's right edge keeps exactly the same gutter
    // from the settled drawer as it has from the viewport edges.
    window.setTimeout(() => positionCaseResearchFloatCard(), 460);
  });
}

function positionCaseResearchFloatCard() {
  const host = $('caseResearchFloatHost');
  const card = host?.querySelector('.case-research-workspace');
  const drawer = $('drawer');
  if (!card || !drawer || !host?.classList.contains('show')) return;
  const drawerRect = drawer.getBoundingClientRect();
  const viewportWidth = Math.max(document.documentElement.clientWidth || 0, window.innerWidth || 0);
  const gutter = 8;
  // Do not clamp to an arbitrary minimum here: on narrow windows that
  // minimum was wider than the actual space and caused the float card to
  // cover the detail drawer. The card occupies exactly the space between
  // the left viewport gutter and the drawer's left gutter.
  const drawerLeft = Math.min(viewportWidth, Math.max(0, drawerRect.left));
  const availableWidth = Math.max(0, Math.floor(drawerLeft - gutter * 2));
  card.style.setProperty('--case-research-float-left', `${gutter}px`);
  card.style.setProperty('--case-research-float-width', `${availableWidth}px`);
  // 左侧悬浮工作区不受详情抽屉的标题和底栏限制，始终填满应用内容区的上下空间。
  card.style.setProperty('--case-research-float-top', `${gutter}px`);
  card.style.setProperty('--case-research-float-bottom', `${gutter}px`);
}

let caseResearchFloatResizeTimer = 0;
window.addEventListener('resize', () => {
  if (!$('caseResearchFloatHost')?.classList.contains('show')) return;
  positionCaseResearchFloatCard();
  // 详情抽屉的宽度带过渡动画；在动画结束后再重算一次，避免取到
  // 过渡中的左边界而把台账卡片暂时压成几像素。
  window.clearTimeout(caseResearchFloatResizeTimer);
  caseResearchFloatResizeTimer = window.setTimeout(() => {
    positionCaseResearchFloatCard();
  }, 460);
});

async function openCaseResearchWorkspace(caseId, section) {
  const id = Number(caseId || 0);
  if (!id) return toast('当前案件无法打开案件台账');
  const target = section === 'memo' ? 'memo' : 'ledger';
  if (state.editing?.tab !== 'cases' || Number(state.editing?.item?.id) !== id) {
    return openCaseResearchShortcut(id, target);
  }
  state.caseResearch = { caseId: id, section: target, projectId: 0, data: null, loading: true, error: '', query: '', sideExpanded: true };
  refreshCaseResearchWorkspace();
  try {
    const data = await api(`/api/case-research/cases/${id}`);
    if (state.caseResearch.caseId !== id || state.caseResearch.section !== target) return;
    state.caseResearch.data = data;
    state.caseResearch.projectId = Number(data.project?.id || data.case?.project_id || 0);
    state.caseResearch.loading = false;
    refreshCaseResearchWorkspace();
  } catch (e) {
    if (state.caseResearch.caseId !== id) return;
    state.caseResearch.loading = false;
    state.caseResearch.error = e.message || `${caseResearchLabel(target)}加载失败`;
    refreshCaseResearchWorkspace();
  }
}

function toggleCaseResearchWorkspace(caseId, section) {
  const id = Number(caseId || 0);
  const target = section === 'memo' ? 'memo' : 'ledger';
  if (Number(state.caseResearch.caseId) === id && state.caseResearch.section === target) {
    closeCaseResearchWorkspace();
    return;
  }
  openCaseResearchWorkspace(id, target);
}

async function openCaseResearchShortcut(caseId, section) {
  const id = Number(caseId || 0);
  if (!id) return toast('当前案件无法打开案件台账');
  const target = section === 'memo' ? 'memo' : 'ledger';
  if (state.editing?.tab === 'cases' && Number(state.editing?.item?.id) === id) {
    return openCaseResearchWorkspace(id, target);
  }
  const series = state.seriesWorkspace;
  const seriesId = Number(series?.id || 0);
  if (seriesId) {
    try {
      const child = isOfflineReadonly()
        ? (series.children || []).find(item => Number(item.id) === id)
        : await api(`/api/case-manager/series/${seriesId}/children/${id}`);
      if (child) {
        openCaseDetailDrawer(applySeriesDetailMappings(child, series), seriesId);
        return openCaseResearchWorkspace(id, target);
      }
    } catch (error) {
      toast(error.message || '子案详情加载失败');
      return;
    }
  }
  if (window.parent && window.parent !== window) {
    window.parent.postMessage({ type: 'openCaseResearch', caseId: id, section: target }, location.origin);
    return;
  }
  location.href = `/?open_case_research=${id}&section=${target}`;
}

function closeCaseResearchWorkspace() {
  if (!state.caseResearch.section) return;
  resetCaseResearchWorkspace();
  $('drawer')?.classList.remove('case-research-active');
  const host = $('caseResearchFloatHost');
  const card = host?.querySelector('.case-research-workspace');
  if (!host || !card) return renderCaseResearchFloatHost();
  host.classList.add('closing');
  card.classList.remove('is-visible');
  setTimeout(() => {
    if (state.caseResearch.section) return;
    renderCaseResearchFloatHost();
  }, 330);
}

function setCaseResearchSearch(value) {
  state.caseResearch.query = String(value || '');
  const results = $('caseResearchTimelineResults');
  if (results) results.innerHTML = caseResearchEntriesHtml();
  const clear = $('drawerBody')?.querySelector('.case-research-search button');
  if (clear) clear.hidden = !state.caseResearch.query;
  const input = $('caseResearchSearch');
  if (input && input.value !== state.caseResearch.query) input.value = state.caseResearch.query;
}

function exportCaseResearchEntries() {
  const id = Number(state.caseResearch.caseId || 0);
  if (!id) return;
  const endpoint = state.caseResearch.section === 'memo' ? 'memo-entries' : 'ledgers';
  window.open(`/api/case-research/cases/${id}/${endpoint}/export`, '_blank');
}

function ensureCaseResearchTimelineModal() {
  let modal = $('caseResearchTimelineModal');
  if (modal) return modal;
  modal = document.createElement('div');
  modal.id = 'caseResearchTimelineModal';
  modal.className = 'case-timeline-modal-mask';
  modal.onclick = event => { if (event.target === modal) closeCaseResearchTimelineModal(); };
  document.body.appendChild(modal);
  return modal;
}

function closeCaseResearchTimelineModal() {
  $('caseResearchTimelineModal')?.classList.remove('show');
  document.body.classList.remove('case-memo-modal-open');
}

function showCaseResearchTimelineModal(title, kicker, body, foot, titleEditor = '') {
  const modal = ensureCaseResearchTimelineModal();
  modal.innerHTML = `<section class="case-timeline-modal" role="dialog" aria-modal="true"><header class="case-timeline-modal-head"><div><small>${esc(kicker)}</small><h3>${titleEditor || esc(title)}</h3></div><button class="case-timeline-modal-close" type="button" onclick="closeCaseResearchTimelineModal()" aria-label="关闭">×</button></header><div class="case-timeline-modal-body">${body}</div><footer class="case-timeline-modal-foot">${foot}</footer></section>`;
  const memo = state.caseResearch.section === 'memo';
  modal.classList.toggle('case-memo-modal', memo);
  document.body.classList.toggle('case-memo-modal-open', memo);
  modal.classList.add('show');
}

function resizeCaseMemoContent(input) {
  input.style.height = '0px';
  input.style.height = `${input.scrollHeight}px`;
}

window.addEventListener('resize', () => {
  const input = $('caseResearchEntryContent');
  if (input?.classList.contains('case-memo-content-editor')) resizeCaseMemoContent(input);
});

function cancelCaseMemoEditing(entryId = 0) {
  if (entryId) return openCaseResearchEntryView(entryId);
  closeCaseResearchTimelineModal();
}

function openCaseResearchEntryEditor(entryId = 0) {
  const item = caseResearchItems().find(entry => Number(entry.id) === Number(entryId));
  const label = caseResearchLabel(state.caseResearch.section);
  const now = new Date();
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
  if (state.caseResearch.section === 'memo') {
    showCaseResearchTimelineModal(item?.title || '新增案件备忘录', label,
      `<label class="case-timeline-view-date case-memo-date">记录日期：<input id="caseResearchEntryDate" type="date" aria-label="记录日期" value="${esc(dateOnly(item?.happened_at || item?.created_at || today))}"></label><textarea class="case-timeline-view-content case-memo-content-editor" id="caseResearchEntryContent" aria-label="备忘录内容" placeholder="记录事实进展、沟通结论、待办事项、风险判断或下一步安排。" oninput="resizeCaseMemoContent(this)">${esc(item?.content || '')}</textarea>`,
      `<button class="btn" type="button" onclick="cancelCaseMemoEditing(${Number(entryId || 0)})">取消</button><button class="btn primary" type="button" onclick="saveCaseResearchEntry(${Number(entryId || 0)})">保存</button>`,
      `<input class="case-memo-title-editor" id="caseResearchEntryTitle" aria-label="案件备忘录标题" value="${esc(item?.title || '')}" placeholder="未命名备忘录">`);
    resizeCaseMemoContent($('caseResearchEntryContent'));
    setTimeout(() => $('caseResearchEntryTitle')?.focus(), 0);
    return;
  }
  showCaseResearchTimelineModal(entryId ? `修改${label}` : `新增${label}`, entryId ? 'EDIT ENTRY' : 'NEW ENTRY', `<div class="case-timeline-form"><label><span>${label}标题</span><input id="caseResearchEntryTitle" value="${esc(item?.title || '')}" placeholder="例如：立案材料核对、庭前沟通要点"></label><label><span>记录日期</span><input id="caseResearchEntryDate" type="date" value="${esc(dateOnly(item?.happened_at || today))}"></label><label class="wide"><span>内容</span><textarea id="caseResearchEntryContent" placeholder="记录事实进展、沟通结论、待办事项、风险判断或下一步安排。">${esc(item?.content || '')}</textarea></label></div>`, `<button class="btn" type="button" onclick="closeCaseResearchTimelineModal()">取消</button><button class="btn primary" type="button" onclick="saveCaseResearchEntry(${Number(entryId || 0)})">保存</button>`);
  setTimeout(() => $('caseResearchEntryTitle')?.focus(), 0);
}

async function saveCaseResearchEntry(entryId = 0) {
  const content = $('caseResearchEntryContent')?.value.trim() || '';
  if (!content) { toast('请填写记录内容'); $('caseResearchEntryContent')?.focus(); return; }
  const payload = { title: $('caseResearchEntryTitle')?.value.trim() || '', happened_at: $('caseResearchEntryDate')?.value || '', content };
  const type = state.caseResearch.section === 'memo' ? 'memo-entries' : 'ledgers';
  const url = entryId ? `/api/case-research/${type}/${entryId}` : `/api/case-research/projects/${Number(state.caseResearch.projectId)}/${type}`;
  try {
    const saved = await api(url, { method: entryId ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    if (type === 'memo-entries') {
      const data = state.caseResearch.data || (state.caseResearch.data = {});
      const items = data.memo_entries || [];
      data.memo_entries = [saved, ...items.filter(item => Number(item.id) !== Number(saved.id))];
      openCaseResearchEntryView(saved.id);
      toast(entryId ? '记录已修改' : '记录已保存');
      try { await reloadCaseResearchWorkspace(); }
      catch (e) { toast('备忘录已保存，列表刷新失败，请稍后重试'); }
    } else {
      closeCaseResearchTimelineModal();
      await reloadCaseResearchWorkspace();
      toast(entryId ? '记录已修改' : '记录已保存');
    }
  } catch (e) { toast(e.message || '保存失败'); }
}

function openCaseResearchEntryView(entryId) {
  const item = caseResearchItems().find(entry => Number(entry.id) === Number(entryId));
  if (!item) return;
  const label = caseResearchLabel(state.caseResearch.section);
  showCaseResearchTimelineModal(item.title || `未命名${label.replace('案件', '')}`, label, `<div class="case-timeline-view-date">记录日期：${esc(dateOnly(item.happened_at || item.created_at))}</div><div class="case-timeline-view-content">${esc(item.content || '')}</div>`, `<button class="btn" type="button" onclick="closeCaseResearchTimelineModal()">关闭</button><button class="btn primary" type="button" onclick="openCaseResearchEntryEditor(${Number(item.id)})">修改</button>`);
}

async function deleteCaseResearchEntry(entryId) {
  const label = caseResearchLabel(state.caseResearch.section);
  if (!confirm(`确定删除这条${label}吗？`)) return;
  const type = state.caseResearch.section === 'memo' ? 'memo-entries' : 'ledgers';
  try {
    await api(`/api/case-research/${type}/${Number(entryId)}`, { method: 'DELETE' });
    await reloadCaseResearchWorkspace();
    toast(`${label}已删除`);
  } catch (e) { toast(e.message || '删除失败'); }
}

async function reloadCaseResearchWorkspace() {
  const id = Number(state.caseResearch.caseId || 0);
  if (!id) return;
  const data = await api(`/api/case-research/cases/${id}`);
  if (Number(state.caseResearch.caseId) !== id) return;
  state.caseResearch.data = data;
  state.caseResearch.projectId = Number(data.project?.id || data.case?.project_id || 0);
  refreshCaseResearchWorkspace();
}

function openCaseFiles(caseId, caseTitle) {
  const id = Number(caseId || 0);
  if (!id) return toast('当前案件无法打开文件管理');
  if (window.parent && window.parent !== window) {
    window.parent.postMessage({ type: 'openCaseFiles', caseId: id, caseTitle: caseTitle || '案件' }, location.origin);
    return;
  }
  location.href = `/?open_case_files=${id}&title=${encodeURIComponent(caseTitle || '案件')}`;
}

// 案件管理页也可独立打开；在本页接管右键，避免依赖外层 iframe 的事件桥接。
function initCaseManagerContextMenu() {
  if (document.documentElement.dataset.caseContextMenuReady) return;
  document.documentElement.dataset.caseContextMenuReady = '1';
  const style = document.createElement('style');
  style.textContent = `.case-page-context-menu{position:fixed;z-index:2147483647;min-width:190px;padding:6px;border:1px solid rgba(128,128,135,.22);border-radius:12px;background:#fff;color:#172033;box-shadow:0 16px 45px rgba(30,30,35,.18);font:13px -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}.case-page-context-menu button{display:block;width:100%;min-height:34px;padding:7px 10px;border:0;border-radius:7px;background:transparent;color:inherit;text-align:left;font:inherit;cursor:pointer}.case-page-context-menu button:hover,.case-page-context-menu button:focus-visible{background:rgba(0,122,255,.12);outline:none}html.dark-mode .case-page-context-menu{background:#29292d;color:#f5f5f7}`;
  document.head.appendChild(style);
  let menu = null;
  const closeMenu = () => { menu?.remove(); menu = null; };
  document.addEventListener('pointerdown', event => {
    if (menu && !menu.contains(event.target)) closeMenu();
  }, true);
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') closeMenu();
  }, true);
  document.addEventListener('contextmenu', event => {
    if (event.defaultPrevented || !(event.target instanceof Element)) return;
    if (event.target.closest('input, textarea, select, [contenteditable], a, .case-page-context-menu')) return;
    if (window.getSelection()?.toString()) return;
    event.preventDefault();
    closeMenu();
    menu = document.createElement('div');
    menu.className = 'case-page-context-menu';
    menu.setAttribute('role', 'menu');
    const addAction = (label, action) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.setAttribute('role', 'menuitem');
      button.textContent = label;
      button.addEventListener('click', () => { closeMenu(); action(); });
      menu.appendChild(button);
    };
    const row = event.target.closest('[data-stella-case-id]');
    if (row) {
      const caseId = Number(row.dataset.stellaCaseId);
      const title = row.dataset.stellaCaseTitle || '案件';
      addAction('查看案件详情', () => openDetail('cases', caseId));
      addAction('打开案件文件', () => openCaseFiles(caseId, title));
      addAction('打开案卷归档', () => openCaseArchive(caseId, title));
    } else {
      const addButton = document.getElementById('topAddBtn');
      if (addButton && !addButton.disabled && addButton.getClientRects().length) {
        addAction(addButton.textContent.trim() || '新增', () => addButton.click());
      }
      if (activeTab === 'cases' && !isOfflineReadonly()) {
        addAction('新增系列案件', () => openNewSeries());
      }
      addAction('案件日历', () => switchTab('caseCalendar'));
      addAction('刷新', () => refreshAll());
    }
    document.body.appendChild(menu);
    const bounds = menu.getBoundingClientRect();
    menu.style.left = `${Math.max(8, Math.min(event.clientX, innerWidth - bounds.width - 8))}px`;
    menu.style.top = `${Math.max(8, Math.min(event.clientY, innerHeight - bounds.height - 8))}px`;
    menu.addEventListener('contextmenu', nestedEvent => nestedEvent.preventDefault());
  });
}

initCaseManagerContextMenu();

function openCaseArchive(caseId, caseTitle) {
  const id = Number(caseId || 0);
  if (!id) return toast('请先保存案件再整理案卷');
  if (window.parent && window.parent !== window) {
    window.parent.postMessage({ type: 'apex:open-case-archive', version: 1,
      caseId: id, caseTitle: caseTitle || '案件' }, location.origin);
    return;
  }
  location.href = `/?open_case_archive=${id}`;
}

async function loadCaseAutomationPanel(caseId) {
  const panel = $('caseAutomationPanel');
  if (!panel) return;
  try {
    const [binding, files, contracts] = await Promise.all([
      api(`/api/case-manager/cases/${caseId}/folder-binding`),
      api(`/api/case-manager/cases/${caseId}/files`),
      api(`/api/case-manager/cases/${caseId}/contracts`)
    ]);
    const archivedFiles = files.items || [];
    const fileRows = archivedFiles.slice(0, 8).map(file => `
      <tr><td>${esc(file.category === 'court_document' ? '法院文书' : '委托合同及授权')}</td>
      <td>${esc(file.relative_path || '')}</td><td>${esc(fmt(file.created_at))}</td>
      <td>${file.exists ? '可用' : '<span class="danger">文件缺失</span>'}</td></tr>`).join('');
    const folderPath = binding.real_path || '';
    const folderName = folderPath ? folderPath.split(/[\\\\/]/).filter(Boolean).pop() : '尚未绑定案件文件夹';
    const folderState = binding.bound
      ? (binding.available ? { text: '已连接', className: '' } : { text: '不可用', className: 'offline' })
      : { text: '未绑定', className: 'unbound' };
    panel.innerHTML = `<h3>案件文件夹与文书</h3>
      <div class="case-folder-summary">
        <span class="case-folder-name" title="${esc(folderPath)}">${esc(folderName)}</span>
        <span class="case-folder-status ${folderState.className}">${folderState.text}</span>
        ${folderPath ? `<details class="case-folder-path"><summary title="${esc(folderPath)}">${esc(folderPath)}</summary><code>${esc(folderPath)}</code></details>` : ''}
        <div class="case-folder-actions">
          ${binding.bound ? '<button class="btn primary" onclick="openCaseFolder(' + caseId + ')">在 Finder 中打开</button>' : ''}
          <button class="btn" onclick="openContractWorkspace(${caseId})">合同</button>
          <button class="btn" onclick="openCaseDocumentBundleTool(${caseId})">文书合集</button>
          <button class="btn" onclick="openCaseArchive(${caseId})">案卷归档</button>
          ${binding.bound
            ? `<button class="btn case-folder-more-btn" type="button" onclick="toggleCaseFolderMenu(this, ${caseId})">更多操作</button>`
            : `<button class="btn" onclick="selectCaseFolder(${caseId})">绑定案件文件夹</button>`}
        </div>
      </div>
      ${fileRows ? `<details class="case-archive-list"><summary>已归档 ${archivedFiles.length} 份文书</summary><div class="mini-table-wrap"><table class="mini-table"><thead><tr><th>类别</th><th>归档路径</th><th>生成/归档时间</th><th>状态</th></tr></thead><tbody>${fileRows}</tbody></table></div></details>` : ''}`;
    makeDetailFieldsCopyable(panel);
  } catch (e) {
    panel.innerHTML = `<h3>案件文件夹与文书</h3><p class="danger">${esc(e.message || '读取失败')}</p>`;
  }
}
function renderCaseFolderUnboundPanel() {
  const panel = $('caseAutomationPanel');
  if (!panel) return;
  const caseId = Number(state.editing?.item?.id || 0);
  const contractAction = caseId ? `openContractWorkspace(${caseId})` : `toast('请先保存案件后再生成合同与授权')`;
  const bundleAction = caseId ? `openCaseDocumentBundleTool(${caseId})` : `toast('请先保存案件后再打开文书合集')`;
  const bindAction = caseId ? `selectCaseFolder(${caseId})` : `toast('请先保存案件后再绑定案件文件夹')`;
  panel.innerHTML = `<h3>案件文件夹与文书</h3>
    <div class="case-folder-summary">
      <span class="case-folder-name">尚未绑定案件文件夹</span>
      <span class="case-folder-status unbound">未绑定</span>
      <div class="case-folder-actions">
        <button class="btn" type="button" onclick="${contractAction}">合同</button>
        <button class="btn" type="button" onclick="${bundleAction}">文书合集</button>
        <button class="btn" type="button" onclick="${bindAction}">绑定案件文件夹</button>
      </div>
    </div>`;
  makeDetailFieldsCopyable(panel);
}
function caseFolderMenuHost() {
  let host = $('caseFolderMenuHost');
  if (!host) {
    host = document.createElement('div');
    host.id = 'caseFolderMenuHost';
    host.className = 'case-folder-menu-host';
    document.body.appendChild(host);
  }
  return host;
}
function showCaseFolderMenu(button, caseId) {
  const host = caseFolderMenuHost();
  host.innerHTML = `<button class="btn" type="button" onclick="selectCaseFolder(${caseId});hideCaseFolderMenu()">重新绑定</button><button class="btn danger" type="button" onclick="unbindCaseFolder(${caseId});hideCaseFolderMenu()">解绑</button>`;
  host.classList.add('show');
  const rect = button.getBoundingClientRect();
  const mw = host.offsetWidth;
  const mh = host.offsetHeight;
  let left = rect.right - mw;
  left = Math.max(12, Math.min(left, window.innerWidth - mw - 12));
  let top = rect.bottom + 6;
  if (top + mh > window.innerHeight - 12) top = rect.top - mh - 6;
  host.style.left = `${left}px`;
  host.style.top = `${top}px`;
}
function hideCaseFolderMenu() {
  const host = $('caseFolderMenuHost');
  if (host) host.classList.remove('show');
}
function toggleCaseFolderMenu(button, caseId) {
  const host = $('caseFolderMenuHost');
  if (host?.classList.contains('show')) { hideCaseFolderMenu(); return; }
  showCaseFolderMenu(button, caseId);
}
document.addEventListener('mousedown', (e) => {
  const host = $('caseFolderMenuHost');
  if (!host?.classList.contains('show')) return;
  if (host.contains(e.target) || e.target.closest('.case-folder-more-btn')) return;
  hideCaseFolderMenu();
}, true);
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') hideCaseFolderMenu();
});

async function selectCaseFolder(caseId, refresh) {
  try {
    const selected = await api(`/api/case-manager/cases/${caseId}/folder-binding/select`, {method:'POST'});
    if (selected.cancelled) return;
    await api(`/api/case-manager/cases/${caseId}/folder-binding`, {
      method:'PUT', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({folder_path:selected.folder_path})
    });
    toast('案件文件夹已绑定；子目录将在首次保存时创建');
    await loadCaseAutomationPanel(caseId);
    if (refresh === 'seriesChild') await renderSeriesChildFolderPanel(caseId);
  } catch (e) { toast(e.message || '绑定失败'); }
}

async function openSeriesChildFolder(childId) {
  const child = (state.seriesWorkspace?.children || []).find(item => Number(item.id) === Number(childId));
  if (!child) return;
  showSeriesSide(`子案文件夹 · ${child.display_name || child.series_display_name || child.title || ''}`, '为这个子案单独绑定本地文件夹', `
    <section class="series-detail-block"><h3>案件文件夹</h3><div id="seriesChildFolderPanel"><p class="muted">正在读取文件夹绑定…</p></div><p class="series-paste-help">可为每个子案单独绑定本地文件夹；未绑定时电子送达等文件会暂存，不会写入系列案文件夹。</p></section>`,
    `<button class="btn" onclick="closeSeriesSide()">关闭</button>`);
  renderSeriesChildFolderPanel(Number(childId));
}

async function renderSeriesChildFolderPanel(caseId) {
  const panel = $('seriesChildFolderPanel');
  if (!panel) return;
  const id = Number(caseId || 0);
  if (!id) { panel.innerHTML = '<p class="muted">无法识别子案</p>'; return; }
  const seriesId = Number(state.seriesWorkspace?.id || 0);
  try {
    const requests = [api(`/api/case-manager/cases/${id}/folder-binding`)];
    if (seriesId) requests.push(api(`/api/case-manager/cases/${seriesId}/folder-binding`));
    const [binding, seriesBinding] = await Promise.all(requests);
    if (!$('seriesChildFolderPanel')) return;
    const folderPath = binding.real_path || '';
    const folderName = folderPath ? folderPath.split(/[\\/]/).filter(Boolean).pop() : '尚未绑定案件文件夹';
    const folderState = binding.bound
      ? (binding.available ? { text: '已连接', className: '' } : { text: '不可用', className: 'offline' })
      : { text: '未绑定', className: 'unbound' };
    const seriesReady = Boolean(seriesBinding?.bound && seriesBinding?.available);
    const readonly = isOfflineReadonly();
    let actions = '';
    if (readonly) {
      actions = binding.bound ? `<button class="btn primary" type="button" onclick="openCaseFolder(${id})">在 Finder 中打开</button>` : '';
    } else if (binding.bound) {
      actions = `<button class="btn primary" type="button" onclick="openCaseFolder(${id})">在 Finder 中打开</button>
        <button class="btn" type="button" onclick="selectCaseFolder(${id}, 'seriesChild')">重新绑定</button>
        <button class="btn danger" type="button" onclick="unbindSeriesChildFolder(${id})">解绑</button>`;
    } else {
      actions = `<button class="btn primary" type="button" onclick="selectCaseFolder(${id}, 'seriesChild')">绑定案件文件夹</button>
        ${seriesReady
          ? `<button class="btn" type="button" onclick="bindSeriesChildFolderInSeries(${id})">在系列案文件夹内新建或选择</button>`
          : '<span class="series-paste-help">系列案件尚未绑定文件夹；可先在“系列案公共信息”绑定，或直接选择任意文件夹。</span>'}`;
    }
    panel.innerHTML = `<div class="case-folder-summary">
        <span class="case-folder-name" title="${esc(folderPath)}">${esc(folderName)}</span>
        <span class="case-folder-status ${folderState.className}">${folderState.text}</span>
        ${folderPath ? `<details class="case-folder-path"><summary title="${esc(folderPath)}">${esc(folderPath)}</summary><code>${esc(folderPath)}</code></details>` : ''}
        <div class="case-folder-actions">${actions}</div>
      </div>`;
  } catch (e) { panel.innerHTML = `<p class="danger">${esc(e.message || '读取失败')}</p>`; }
}

function unbindSeriesChildFolder(caseId) {
  if (!requireOnlineAction()) return;
  openSeriesFolderDialog({ childId: caseId, mode: 'unbind' });
}

function openSeriesFolderDialog(options = {}) {
  const pending = {
    childId: Number(options.childId || 0),
    mode: options.mode === 'unbind' ? 'unbind' : 'create',
    submode: 'new',
    folders: null,
    selectedFolder: '',
    realPath: '',
    boundError: '',
  };
  if (!pending.childId) return;
  state.seriesFolderDialog = pending;
  const isUnbind = pending.mode === 'unbind';
  $('seriesFolderDialogTitle').textContent = isUnbind ? '解绑子案文件夹？' : '在系列案文件夹内绑定';
  $('seriesFolderDialogDescription').textContent = isUnbind
    ? '解绑后电子送达等文件不会再写入该文件夹；已归档的本地文件不会被删除。'
    : '在系列案已绑定的文件夹内新建子文件夹，或选择其中现有的文件夹，绑定为该子案的案件文件夹。';
  const tabs = $('seriesFolderDialogTabs');
  if (tabs) tabs.style.display = isUnbind ? 'none' : '';
  const field = $('seriesFolderDialogField');
  if (field) field.style.display = isUnbind ? 'none' : '';
  const existingField = $('seriesFolderDialogExistingField');
  if (existingField) existingField.style.display = 'none';
  const filter = $('seriesFolderDialogFilter');
  if (filter) filter.value = '';
  const optionList = $('seriesFolderOptionList');
  if (optionList) optionList.innerHTML = '';
  const input = $('seriesFolderDialogInput');
  if (input) input.value = String(options.defaultName || '');
  const confirmButton = $('confirmSeriesFolderDialogButton');
  if (confirmButton) { confirmButton.disabled = false; confirmButton.textContent = isUnbind ? '确认解绑' : '创建并绑定'; }
  $('seriesFolderDialogMask')?.classList.add('show');
  setTimeout(() => {
    if (isUnbind) confirmButton?.focus();
    else { input?.focus(); input?.select(); }
  }, 0);
}

function switchSeriesFolderDialogMode(submode) {
  const pending = state.seriesFolderDialog;
  if (!pending || pending.mode !== 'create') return;
  pending.submode = submode === 'existing' ? 'existing' : 'new';
  const tabNew = $('seriesFolderTabNew'), tabExisting = $('seriesFolderTabExisting');
  if (tabNew) tabNew.classList.toggle('active', pending.submode === 'new');
  if (tabExisting) tabExisting.classList.toggle('active', pending.submode === 'existing');
  const field = $('seriesFolderDialogField');
  if (field) field.style.display = pending.submode === 'new' ? '' : 'none';
  const existingField = $('seriesFolderDialogExistingField');
  if (existingField) existingField.style.display = pending.submode === 'existing' ? '' : 'none';
  const confirmButton = $('confirmSeriesFolderDialogButton');
  if (confirmButton) {
    confirmButton.disabled = pending.submode === 'existing';
    confirmButton.textContent = pending.submode === 'new' ? '创建并绑定' : '绑定为子案文件夹';
  }
  if (pending.submode === 'existing') {
    if (pending.folders === null) loadSeriesFolderOptions();
    else renderSeriesFolderOptionList();
  } else { const input = $('seriesFolderDialogInput'); input?.focus(); }
}

async function loadSeriesFolderOptions() {
  const pending = state.seriesFolderDialog;
  if (!pending) return;
  pending.folders = null;
  pending.selectedFolder = '';
  pending.boundError = '';
  renderSeriesFolderOptionList();
  try {
    const data = await api(`/api/case-manager/cases/${pending.childId}/folder-binding/series-options`);
    if (state.seriesFolderDialog !== pending) return;
    if (!data.bound) pending.boundError = '系列案件尚未绑定文件夹，请先为系列案件绑定总文件夹。';
    else pending.folders = data.folders || [];
    pending.realPath = data.real_path || '';
  } catch (e) {
    if (state.seriesFolderDialog !== pending) return;
    pending.folders = [];
    pending.boundError = e.message || '读取失败';
  }
  renderSeriesFolderOptionList();
}

function renderSeriesFolderOptionList() {
  const host = $('seriesFolderOptionList');
  if (!host) return;
  const pending = state.seriesFolderDialog;
  if (!pending || pending.mode !== 'create' || pending.submode !== 'existing') return;
  const hint = $('seriesFolderExistingHint');
  if (pending.folders === null) {
    host.innerHTML = '<div class="series-folder-option-empty">正在读取总文件夹…</div>';
    if (hint) hint.textContent = '';
    return;
  }
  if (pending.boundError) {
    host.innerHTML = `<div class="series-folder-option-empty">${esc(pending.boundError)}</div>`;
    if (hint) hint.textContent = '';
    return;
  }
  const keyword = String($('seriesFolderDialogFilter')?.value || '').trim().toLowerCase();
  const folders = pending.folders.filter(folder => !keyword || String(folder.name || '').toLowerCase().includes(keyword));
  if (!folders.length) {
    host.innerHTML = `<div class="series-folder-option-empty">${keyword ? '没有匹配的文件夹' : '总文件夹内暂无子文件夹，可切回“新建子文件夹”直接创建。'}</div>`;
    if (hint) hint.textContent = '';
    return;
  }
  host.innerHTML = folders.map(folder => `
    <button type="button" class="series-folder-option ${pending.selectedFolder === folder.name ? 'selected' : ''}" data-name="${esc(folder.name)}" onclick="chooseSeriesFolderOption(this)">
      <span aria-hidden="true">📁</span>
      <span class="series-folder-option-name" title="${esc(folder.path || folder.name)}">${esc(folder.name)}</span>
    </button>`).join('');
  if (hint) hint.textContent = `共 ${folders.length} 个${keyword ? '（已筛选）' : ''} · ${pending.realPath || ''}`;
}

function chooseSeriesFolderOption(option) {
  const pending = state.seriesFolderDialog;
  if (!pending) return;
  pending.selectedFolder = String(option?.dataset?.name || '');
  renderSeriesFolderOptionList();
  const confirmButton = $('confirmSeriesFolderDialogButton');
  if (confirmButton) { confirmButton.disabled = !pending.selectedFolder; confirmButton.focus(); }
}

function closeSeriesFolderDialog() {
  $('seriesFolderDialogMask')?.classList.remove('show');
  state.seriesFolderDialog = null;
}

async function confirmSeriesFolderDialog() {
  const pending = state.seriesFolderDialog;
  if (!pending) return closeSeriesFolderDialog();
  const button = $('confirmSeriesFolderDialogButton');
  if (pending.mode === 'unbind') {
    if (button) { button.disabled = true; button.textContent = '解绑中…'; }
    try {
      await api(`/api/case-manager/cases/${pending.childId}/folder-binding`, {method:'DELETE'});
      toast('已解绑，原有文件未删除');
      closeSeriesFolderDialog();
      await renderSeriesChildFolderPanel(pending.childId);
    } catch (e) {
      if (button) { button.disabled = false; button.textContent = '确认解绑'; }
      toast(e.message || '解绑失败');
    }
    return;
  }
  if (pending.submode === 'existing') {
    const folderName = String(pending.selectedFolder || '').trim();
    if (!folderName) { toast('请选择总文件夹内的文件夹'); return; }
    if (button) { button.disabled = true; button.textContent = '绑定中…'; }
    try {
      await api(`/api/case-manager/cases/${pending.childId}/folder-binding/bind-in-series`, {
        method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name: folderName})
      });
      toast('已把总文件夹内的文件夹绑定为该子案的案件文件夹');
      closeSeriesFolderDialog();
      await renderSeriesChildFolderPanel(pending.childId);
    } catch (e) {
      if (button) { button.disabled = false; button.textContent = '绑定为子案文件夹'; }
      toast(e.message || '绑定失败');
    }
    return;
  }
  const name = String($('seriesFolderDialogInput')?.value || '').trim();
  if (!name) { toast('请填写子文件夹名称'); $('seriesFolderDialogInput')?.focus(); return; }
  if (button) { button.disabled = true; button.textContent = '创建中…'; }
  try {
    await api(`/api/case-manager/cases/${pending.childId}/folder-binding/create-in-series`, {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name})
    });
    toast('已在系列案文件夹内创建子案文件夹并绑定');
    closeSeriesFolderDialog();
    await renderSeriesChildFolderPanel(pending.childId);
  } catch (e) {
    if (button) { button.disabled = false; button.textContent = '创建并绑定'; }
    toast(e.message || '创建失败');
  }
}

function bindSeriesChildFolderInSeries(caseId) {
  if (!requireOnlineAction()) return;
  const child = (state.seriesWorkspace?.children || []).find(item => Number(item.id) === Number(caseId));
  if (!child) return toast('未找到该子案');
  const parentTitle = String(state.seriesWorkspace?.title || '').trim();
  const fullTitle = String(child.title || '').trim();
  let defaultName = parentTitle && fullTitle.startsWith(parentTitle)
    ? fullTitle.slice(parentTitle.length).replace(/^[\s·•\-—_]+/, '')
    : fullTitle;
  if (!defaultName) defaultName = String(child.series_code || `子案-${caseId}`);
  openSeriesFolderDialog({ childId: caseId, mode: 'create', defaultName });
}

async function openCaseFolder(caseId) {
  try { await api(`/api/case-manager/cases/${caseId}/folder-binding/open`, {method:'POST'}); }
  catch (e) { toast(e.message || '无法打开文件夹'); }
}

async function unbindCaseFolder(caseId) {
  if (!confirm('确认解绑案件文件夹？已归档的本地文件不会被删除。')) return;
  try {
    await api(`/api/case-manager/cases/${caseId}/folder-binding`, {method:'DELETE'});
    toast('已解绑，原有文件未删除');
    await loadCaseAutomationPanel(caseId);
  } catch (e) { toast(e.message || '解绑失败'); }
}

async function openContractWorkspace(caseId) {
  try {
    const [templates, profile, contracts, presets] = await Promise.all([
      api('/api/contract-templates'),
      api(`/api/case-manager/cases/${caseId}/contract-profile`),
      api(`/api/case-manager/cases/${caseId}/contracts`),
      api('/api/contract-profile-presets')
    ]);
    const templateItems = (templates.items || []).filter(item => Number(item.active) === 1);
    if (!profile.template_id && templateItems.length) profile.template_id = templateItems[0].id;
    profile.fee_plan = profile.fee_plan || 'fixed';
    if (profile.fee_plan === 'pure_risk') profile.fee_plan = 'recovery_tiered';
    profile.fee_config = profile.fee_config || {};
    if (!profile.fee_config.base_amount && profile.fee_amount) profile.fee_config.base_amount = profile.fee_amount;
    const context = profile.context || {};
    if (!profile.entrust_type) {
      const stage = String(profile.representation_stage || context.case?.stage || '');
      profile.entrust_type = stage.includes('仲裁') ? 'arbApplicant'
        : stage.includes('执行异议') ? 'execObjection'
        : stage.includes('强制执行') || stage === '执行' ? 'execApplicant'
        : stage.includes('破产') ? 'bankruptcy'
        : stage === '一审' ? 'plaintiff'
        : stage === '二审' ? 'appellant' : '';
    }
    state.contractWorkspace = {
      caseId, profile, context, templates:templateItems, contracts:contracts.items || [],
      presets:presets.items || [], presetId:null, preview:null, previewCurrent:false,
      previewSeq:0, focusSection:null, userFocusedSection:false
    };
    const caseData = context.case || {};
    const client = context.client || {};
    const opponents = context.opponents || {};
    const options = templateItems.map(item =>
      `<option value="${Number(item.id)}" ${Number(profile.template_id)===Number(item.id)?'selected':''}>${esc(item.name)} · 第${Number(item.version)}版</option>`
    ).join('');
    const feePlans = context.fee_plans || [];
    const selectedLawyers = new Set((profile.lawyers||[]).map(x=>typeof x==='string'?x:(x.name||'')));
    const lawyerOptions = context.lawyers || [];
    const entrustTypes = context.entrust_types || [];
    const activeEntrust = entrustTypes.find(item=>item.id===profile.entrust_type) || {};
    const selectedAuthorityLines = new Set(
      (profile.authority_lines && profile.authority_lines.length)
        ? profile.authority_lines : (activeEntrust.authority_lines || [])
    );
    const stageOptions = [...new Set([
      profile.representation_stage,
      caseData.stage,
      ...(context.stages||[]).map(x=>x.name),
      ...entrustTypes.map(x=>x.stage)
    ].filter(Boolean))];
    const courtOptions = [...new Set([
      caseData.court,
      ...(context.case_numbers||[]).map(x=>x.court),
      ...(context.courts||[]).map(x=>x.name)
    ].filter(Boolean))];
    const firm = profile.firm || context.defaults?.firm || {};
    $('drawer').classList.add('detail-mode');
    $('drawer').classList.add('contract-workspace-mode');
    $('drawer').classList.remove('edit-wide');
    $('drawerTitle').textContent = '生成委托代理合同';
    $('drawerHeadActions').innerHTML = `
      <button class="btn" type="button" onclick="openCaseAuthorizationTool('power-attorney')">授权委托书</button>
      <button class="btn" type="button" onclick="openCaseAuthorizationTool('suohan')">所函</button>
      <button class="btn" type="button" onclick="openCaseAuthorizationTool('rep-identity-cert')">法定代表人证明书</button>`;
    notifyCaseManagerContext(
      caseData.title || '当前案件',
      '委托合同及授权',
      { id: caseData.id, title: caseData.title }
    );
    $('drawerBody').innerHTML = `<div class="contract-builder">
      <div class="contract-editor">
        <section class="contract-card">
          <div class="contract-card-head"><div><h3>合同方案库</h3><span>可套用其他案件已保存的收费、代理和条款设置；本案当事人资料不会被替换</span></div></div>
          <div class="contract-preset-bar">
            <div><label>已有方案</label><select id="contractPresetSelect"><option value="">选择已保存方案</option>${(presets.items||[]).map(item=>`<option value="${Number(item.id)}">${esc(item.name)}</option>`).join('')}</select></div>
            <div><label>当前方案名称（保存时可修改）</label><input class="input" id="contractPresetName" value="${esc(`${caseData.title||'委托代理合同'}方案`)}"></div>
            <button class="btn" type="button" onclick="applyContractPreset()">套用</button>
          </div>
        </section>
        <section class="contract-card" data-preview-section="case">
          <div class="contract-card-head"><div><h3>合同首部与案件资料</h3><span>与合同首页的出现顺序一致</span></div><span>自动同步</span></div>
          <div class="contract-auto-grid">
            <div class="contract-auto-item wide"><small>案件名称</small><strong>${esc(caseData.title || '尚未填写')}</strong></div>
            <div class="contract-auto-item"><small>委托人</small><strong>${esc(client.name || '尚未填写')}</strong></div>
            <div class="contract-auto-item"><small>案号</small><strong>${esc(caseData.number || '尚未填写')}</strong></div>
            <div class="contract-auto-item"><small>法定代表人</small><strong>${esc(client.legal_representative || '尚未填写')}</strong></div>
            <div class="contract-auto-item"><small>统一社会信用代码</small><strong>${esc(client.identity_code || '尚未填写')}</strong></div>
          </div>
          <div class="contract-form-grid" style="margin-top:10px">
            <div data-preview-section="client-contact"><label>甲方送达地址</label><input class="input" id="contractClientAddress" value="${esc(profile.custom_values?.['client.address']||client.address||'')}" placeholder="合同首部甲方送达地址" oninput="contractFormChanged()"></div>
            <div data-preview-section="client-contact"><label>甲方电子邮箱</label><input class="input" id="contractClientEmail" type="email" value="${esc(profile.custom_values?.['client.email']||client.email||'')}" placeholder="合同首部甲方电子邮箱" oninput="contractFormChanged()"></div>
          </div>
          <p class="contract-source-note">委托人、对方当事人或案由有误时，请回到案件信息修改，合同会自动同步。</p>
        </section>
        <section class="contract-card" data-preview-section="background">
          <div class="contract-card-head"><div><h3>合同订立背景</h3><span>对应“甲方因……聘请乙方律师作为……”</span></div></div>
          <div class="contract-form-grid">
            <div data-preview-section="background"><label>代理阶段</label><select id="contractStage" onchange="contractFormChanged()">${stageOptions.map(x=>`<option value="${esc(x)}" ${(profile.representation_stage||caseData.stage)===x?'selected':''}>${esc(x)}</option>`).join('')}</select></div>
            <div class="wide" data-preview-section="background"><label>合同背景中的纠纷／事项（“甲方因 XXX”）</label><input class="input" id="contractBackgroundMatter" value="${esc(profile.background_matter||(caseData.type?`${caseData.type}一案`:''))}" placeholder="例如：建设工程施工合同纠纷一案" oninput="contractFormChanged()"></div>
            <div data-preview-section="background"><label>合同背景中的代理阶段（“作为 XXX 阶段”）</label><input class="input" id="contractBackgroundStage" value="${esc(profile.background_stage||profile.representation_stage||caseData.stage||'')}" oninput="contractFormChanged()"></div>
          </div>
        </section>
        <section class="contract-card" data-preview-section="matter">
          <div class="contract-card-head"><div><h3>第一条　委托代理事项</h3><span>对应合同第一条及其案件信息</span></div></div>
          <div class="contract-auto-grid" style="margin-bottom:10px">
            <div class="contract-auto-item"><small>1. 对方当事人</small><strong>${esc(opponents.names || '尚未填写')}</strong></div>
            <div class="contract-auto-item"><small>2. 案由</small><strong>${esc(caseData.type || '尚未填写')}</strong></div>
          </div>
          <div class="contract-form-grid">
            <div data-preview-section="matter"><label>委托身份／程序</label><select id="contractEntrustType" onchange="contractEntrustTypeChanged()"><option value="">按案件当前阶段</option>${entrustTypes.map(item=>`<option value="${esc(item.id)}" ${profile.entrust_type===item.id?'selected':''}>${esc(item.label)}</option>`).join('')}</select></div>
            <div data-preview-section="matter"><label>固定条款选择</label><select id="contractMatterKind" onchange="contractFormChanged()"><option value="case" ${(profile.matter_kind||'case')==='case'?'selected':''}>案件</option><option value="matter" ${profile.matter_kind==='matter'?'selected':''}>事项</option></select></div>
            <div data-preview-section="matter-court"><label>3. 审判／仲裁机构</label><input class="input" id="contractCourt" list="contractCourtOptions" value="${esc(profile.custom_values?.['case.court']||caseData.court||'')}" placeholder="从本案案号与机构库选择" oninput="contractFormChanged()"><datalist id="contractCourtOptions">${courtOptions.map(x=>`<option value="${esc(x)}"></option>`).join('')}</datalist></div>
            <div data-preview-section="matter-subject"><label>4. 争议标的额</label><input class="input" id="contractSubjectAmount" value="${esc(profile.subject_amount||'')}" placeholder="例如：人民币500万元" oninput="contractFormChanged()"></div>
          </div>
          <div class="contract-form-grid" style="margin-top:10px"><div class="wide" data-preview-section="matter"><label>具体委托代理事项</label><textarea id="contractScope" rows="2" placeholder="选择委托身份后自动生成，也可补充特别限制" oninput="contractFormChanged()">${esc(profile.engagement_scope||'')}</textarea></div></div>
        </section>
        <section class="contract-card" data-preview-section="authority">
          <div class="contract-card-head"><div><h3>第二条　委托代理权限</h3><span>与授权委托书生成器完全共用</span></div></div>
          <div class="contract-permissions" id="contractAuthorityLines" data-preview-section="authority">${(activeEntrust.authority_lines||[]).map(line=>`<label class="contract-permission"><input type="checkbox" name="contractAuthorityLine" value="${esc(line)}" ${selectedAuthorityLines.has(line)?'checked':''} onchange="contractFormChanged()"><span>${esc(line)}</span></label>`).join('')}</div>
        </section>
        <section class="contract-card" data-preview-section="lawyer">
          <div class="contract-card-head"><div><h3>第三条　代理律师</h3><span>对应“乙方委派……律师”条款</span></div></div>
          <div data-preview-section="lawyer"><label>代理律师（与授权委托书共用律师库）</label><div class="contract-permissions" id="contractLawyerOptions">${lawyerOptions.map(item=>`<label class="contract-permission"><input type="checkbox" name="contractLawyer" value="${esc(item.name)}" ${selectedLawyers.has(item.name)?'checked':''} onchange="contractFormChanged()"><span>${esc(item.name)}${item.phone?` · ${esc(item.phone)}`:''}</span></label>`).join('')}</div>
            <div style="display:grid;grid-template-columns:minmax(120px,1fr) minmax(150px,1fr) auto;gap:8px;margin-top:8px"><input class="input" id="newContractLawyerName" placeholder="新增律师姓名"><input class="input" id="newContractLawyerPhone" placeholder="联系电话"><button class="btn" type="button" onclick="addContractLawyer()">添加并同步律师库</button></div>
          </div>
        </section>
        <section class="contract-card" data-preview-section="fee">
          <div class="contract-card-head"><div><h3>第五条　律师代理费</h3><span>只显示当前收费方案需要填写的内容</span></div></div>
          <div class="fee-plan-grid">${feePlans.map(item=>`<label class="fee-plan"><input type="radio" name="contractFeePlan" value="${esc(item.id)}" ${profile.fee_plan===item.id?'checked':''} onchange="contractFeePlanChanged()"><strong>${esc(item.label)}</strong><span>${esc(item.description)}</span></label>`).join('')}</div>
          <div id="contractFeeFields" style="margin-top:12px"></div>
        </section>
        <section class="contract-card" data-preview-section="sign">
          <div class="contract-card-head"><div><h3>第十条　合同生效与签署</h3><span>通常只需确认日期与份数</span></div></div>
          <div class="contract-form-grid">
            <div><label>签署日期</label><input class="input" type="date" id="contractSignDate" value="${esc(profile.sign_date||new Date().toISOString().slice(0,10))}" oninput="contractFormChanged()"></div>
            <div><label>合同份数</label><input class="input" id="contractCopies" value="${esc(profile.contract_copies||'3')}" oninput="contractFormChanged()"></div>
          </div>
          <details class="contract-advanced"><summary>律所资料与模板设置（一般无需修改）</summary>
            <div class="contract-form-grid" style="margin-top:10px">
              <div><label>律所名称</label><input class="input" id="contractFirmName" value="${esc(firm.name||'')}" oninput="contractFormChanged()"></div>
              <div><label>统一社会信用代码</label><input class="input" id="contractFirmCode" value="${esc(firm.credit_code||'')}" oninput="contractFormChanged()"></div>
              <div class="wide"><label>律所地址</label><input class="input" id="contractFirmAddress" value="${esc(firm.address||'')}" oninput="contractFormChanged()"></div>
              <div><label>开户银行</label><input class="input" id="contractFirmBank" value="${esc(firm.bank||'')}" oninput="contractFormChanged()"></div>
              <div><label>银行账号</label><input class="input" id="contractFirmAccount" value="${esc(firm.account||'')}" oninput="contractFormChanged()"></div>
              <div class="wide"><label>Word 模板</label><div style="display:flex;gap:8px"><select id="contractTemplateId" onchange="contractFormChanged()" style="flex:1"><option value="">请选择模板</option>${options}</select><button class="btn" type="button" onclick="uploadContractTemplate(${caseId})">上传模板</button><button class="btn" type="button" onclick="reviewSelectedTemplate()">模板识别校对</button></div></div>
            </div>
          </details>
          ${(contracts.items||[]).length ? `<details class="contract-advanced"><summary>历史生成文件（${contracts.items.length}）</summary><ul class="contract-history">${contracts.items.map(x=>`<li>${esc(x.relative_path)} · ${esc(fmt(x.created_at))}</li>`).join('')}</ul></details>` : ''}
        </section>
      </div>
      <aside class="contract-preview-pane">
        <div class="contract-preview-toolbar"><strong>实际 Word 合同预览</strong><span class="contract-preview-status" id="contractPreviewStatus">正在根据原始模板生成…</span></div>
        <div class="contract-paper" id="contractLivePreview"><div class="contract-preview-loading">正在生成与导出文件完全一致的预览…</div></div>
      </aside>
    </div>`;
    $('drawerBody').querySelector('.contract-editor')?.addEventListener('focusin', event => {
      const section = event.target.closest('[data-preview-section]')?.dataset.previewSection;
      if (section) {
        state.contractWorkspace.userFocusedSection = true;
        contractFocusSection(section);
      }
    });
    $('drawerBody').querySelector('.contract-editor')?.addEventListener('pointerdown', () => {
      const editor = $('drawerBody')?.querySelector('.contract-editor');
      state.contractWorkspace.lockedEditorScrollTop = editor?.scrollTop ?? 0;
      state.contractWorkspace.lockEditorScrollUntil = Date.now() + 1800;
    }, true);
    renderContractFeeFields();
    if (profile.entrust_type && !profile.engagement_scope) contractEntrustTypeChanged(false);
    updateContractLivePreview(true);
    setContractFooter();
    $('drawerMask').classList.add('show');
    $('drawer').classList.add('show');
    requestAnimationFrame(() => {
      const editor = $('drawerBody').querySelector('.contract-editor');
      if (editor) editor.scrollTop = 0;
    });
  } catch (e) { toast(e.message || '合同生成器加载失败'); }
}

function selectedContractFeePlan() {
  return document.querySelector('input[name="contractFeePlan"]:checked')?.value || 'fixed';
}

function renderContractFeeFields() {
  const holder = $('contractFeeFields'); if (!holder) return;
  const workspace = state.contractWorkspace || {};
  const config = workspace.profile?.fee_config || {};
  const plan = selectedContractFeePlan();
  let specific = '';
  if (plan === 'fixed') {
    specific = `<div><label>律师服务费（元）</label><input class="input" id="feeBaseAmount" value="${esc(config.base_amount||'')}" placeholder="例如：50000" oninput="contractFormChanged()"></div>`;
  } else if (plan === 'staged_fixed') {
    const configured = (config.stage_fees||[]).length ? config.stage_fees : [
      {stage:'一审',amount:config.first_amount||''},{stage:'二审',amount:config.second_amount||''}
    ];
    const stageNames = [...new Set([
      ...(workspace.context?.stages||[]).map(item=>item.name),
      ...(workspace.context?.entrust_types||[]).map(item=>item.stage),
      '一审','仲裁','二审','再审审查','申请再审','强制执行','执行异议','执行复议','破产程序'
    ].filter(Boolean))];
    const stageMap = new Map(configured.map(item=>[item.stage,item.amount]));
    specific = `<div class="wide"><label>选择收费阶段（仅勾选的阶段写入合同）</label>
      <div class="contract-stage-fees">${stageNames.map(stage=>`<label class="contract-stage-fee"><input type="checkbox" data-stage-fee-check data-stage="${esc(stage)}" ${stageMap.has(stage)?'checked':''} onchange="contractFormChanged()"><span>${esc(stage)}</span><input class="input" data-stage-fee-amount data-stage="${esc(stage)}" value="${esc(stageMap.get(stage)||'')}" placeholder="律师费/元" oninput="this.closest('label').querySelector('[data-stage-fee-check]').checked=true;contractFormChanged()"></label>`).join('')}</div>
    </div>`;
  } else if (plan === 'base_risk') {
    specific = `<div><label>基础代理费（元）</label><input class="input" id="feeBaseAmount" value="${esc(config.base_amount||'')}" placeholder="例如：30000" oninput="contractFormChanged()"></div>
      <div><label>风险代理费比例（%）</label><input class="input" id="feeRiskRate" value="${esc(config.rate||'')}" placeholder="例如：20" oninput="contractFormChanged()"></div>
      <div><label>生效裁判确定甲方应当</label><input class="input" id="feeLiabilityAction" value="${esc(config.liability_action||'承担付款责任')}" oninput="contractFormChanged()"></div>
      <div><label>款项支付对象</label><input class="input" id="feePayeeName" value="${esc(config.payee_name||workspace.context?.opponents?.names||'')}" oninput="contractFormChanged()"></div>
      <div><label>对方主张金额（万元）</label><input class="input" id="feeClaimAmountWan" value="${esc(config.claim_amount_wan||'')}" oninput="contractFormChanged()"></div>
      <div><label>最终承担基准金额（万元）</label><input class="input" id="feeBaselineAmountWan" value="${esc(config.baseline_amount_wan||'')}" oninput="contractFormChanged()"></div>
      <div><label>如无需承担何种责任</label><input class="input" id="feeNoLiabilityAction" value="${esc(config.no_liability_action||'就本案争议承担付款责任')}" oninput="contractFormChanged()"></div>
      <div><label>付款责任示例</label><input class="input" id="feeLiabilityExamples" value="${esc(config.liability_examples||'本金、利息及其他费用')}" oninput="contractFormChanged()"></div>
      <div><label>无需付款时风险代理费（万元）</label><input class="input" id="feeSuccessAmountWan" value="${esc(config.success_amount_wan||'')}" oninput="contractFormChanged()"></div>`;
  } else {
    const tiers = (config.tiers||[]).length ? config.tiers : [
      {lower:'',upper:config.tier1_upper_wan||'',rate:config.tier1_rate||''},
      {lower:config.tier2_lower_wan||'',upper:config.tier2_upper_wan||'',rate:config.tier2_rate||''},
      {lower:config.tier3_lower_wan||'',upper:config.tier3_upper_wan||'',rate:config.tier3_rate||''},
      {lower:config.tier4_lower_wan||'',upper:'',rate:config.tier4_rate||''}
    ].filter(item=>item.lower||item.upper||item.rate);
    if (!tiers.length) tiers.push({lower:'',upper:'',rate:''});
    specific = `<div><label>基础代理费（元）</label><input class="input" id="feeBaseAmount" value="${esc(config.base_amount||'')}" placeholder="例如：30000" oninput="contractFormChanged()"></div>
      <div><label>全额回款判断线（万元，可不填）</label><input class="input" id="feeGuaranteeThresholdWan" value="${esc(config.guarantee_threshold_wan||'')}" oninput="contractFormChanged()"></div>
      <div><label>达到判断线的固定风险费（万元，可不填）</label><input class="input" id="feeGuaranteeFeeWan" value="${esc(config.guarantee_fee_wan||'')}" oninput="contractFormChanged()"></div>
      <div class="wide fee-tier-editor">
        <label>分段回款风险费率（可设置一档或多档）</label>
        <div id="contractRiskTiers">${tiers.map((tier,index)=>`<div class="fee-tier-row" data-risk-tier><span>第${index+1}档</span><input class="input" data-tier-lower value="${esc(tier.lower||'')}" placeholder="下限/万元（可空）" oninput="contractFormChanged()"><span>至</span><input class="input" data-tier-upper value="${esc(tier.upper||'')}" placeholder="上限/万元（可空）" oninput="contractFormChanged()"><span>按</span><input class="input" data-tier-rate value="${esc(tier.rate||'')}" placeholder="%" oninput="contractFormChanged()"><button class="btn" type="button" onclick="removeContractRiskTier(this)">移除</button></div>`).join('')}</div>
        <button class="btn" type="button" style="margin-top:8px" onclick="addContractRiskTier()">＋增加一档</button>
      </div>`;
  }
  holder.innerHTML = `<div class="contract-form-grid">${specific}</div><p class="contract-source-note">付款期限、风险费触发条件及条款结构均沿用你上传模板的原文，不再由系统改写。</p>`;
}

function contractFeePlanChanged() {
  state.contractWorkspace.profile.fee_plan = selectedContractFeePlan();
  renderContractFeeFields();
  contractFocusSection('fee');
  contractFormChanged();
}

function addContractRiskTier() {
  const holder = $('contractRiskTiers'); if (!holder) return;
  const row = document.createElement('div');
  row.className = 'fee-tier-row';
  row.dataset.riskTier = '';
  const number = holder.querySelectorAll('[data-risk-tier]').length + 1;
  row.innerHTML = `<span>第${number}档</span><input class="input" data-tier-lower placeholder="下限/万元（可空）" oninput="contractFormChanged()"><span>至</span><input class="input" data-tier-upper placeholder="上限/万元（可空）" oninput="contractFormChanged()"><span>按</span><input class="input" data-tier-rate placeholder="%" oninput="contractFormChanged()"><button class="btn" type="button" onclick="removeContractRiskTier(this)">移除</button>`;
  holder.appendChild(row);
  row.querySelector('[data-tier-lower]')?.focus();
  contractFocusSection('fee');
}

function removeContractRiskTier(button) {
  const holder = $('contractRiskTiers');
  if (!holder || holder.querySelectorAll('[data-risk-tier]').length <= 1) {
    const row = button.closest('[data-risk-tier]');
    row?.querySelectorAll('input').forEach(input=>input.value='');
  } else button.closest('[data-risk-tier]')?.remove();
  [...holder.querySelectorAll('[data-risk-tier]')].forEach((row,index)=>{
    const label = row.querySelector('span'); if (label) label.textContent = `第${index+1}档`;
  });
  contractFormChanged();
}

async function addContractLawyer() {
  const name = $('newContractLawyerName')?.value.trim() || '';
  const phone = $('newContractLawyerPhone')?.value.trim() || '';
  if (!name) return toast('请填写律师姓名');
  try {
    await api('/api/suohan/options', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:'lawyer',name,phone})});
    const workspace = state.contractWorkspace;
    workspace.context.lawyers = [...(workspace.context.lawyers||[]).filter(item=>item.name!==name),{name,phone}];
    const holder = $('contractLawyerOptions');
    holder.insertAdjacentHTML('beforeend', `<label class="contract-permission"><input type="checkbox" name="contractLawyer" value="${esc(name)}" checked onchange="contractFormChanged()"><span>${esc(name)}${phone?` · ${esc(phone)}`:''}</span></label>`);
    $('newContractLawyerName').value = ''; $('newContractLawyerPhone').value = '';
    toast('律师已加入共用律师库并选中');
    contractFormChanged();
  } catch (e) { toast(e.message || '添加律师失败'); }
}

function openCaseAuthorizationTool(tool) {
  const caseId = Number(state.contractWorkspace?.caseId || 0);
  if (!caseId) return;
  if (window.parent && window.parent !== window) {
    window.parent.postMessage({type:'openCaseAuthorizationTool',tool,caseId}, location.origin);
  }
}

// 在主窗口新标签页打开文书合集生成工具，并携带案件 id 自动关联已录入案号。
function openCaseDocumentBundleTool(caseId) {
  const id = Number(caseId || 0);
  if (!id) return toast('请先保存案件后再打开文书合集');
  if (window.parent && window.parent !== window) {
    window.parent.postMessage({type:'openCaseAuthorizationTool',tool:'document-bundle',caseId:id}, location.origin);
    return;
  }
  location.href = `/document-bundle-generator?v=2026090402&case_id=${id}`;
}

function contractEntrustTypeChanged(refresh=true) {
  const workspace = state.contractWorkspace;
  if (!workspace) return;
  const typeId = $('contractEntrustType')?.value || '';
  const rule = (workspace.context?.entrust_types || []).find(item => item.id === typeId);
  if (rule) {
    if ($('contractStage')) $('contractStage').value = rule.stage || '';
    if ($('contractScope')) $('contractScope').value = rule.matter || '';
    const holder = $('contractAuthorityLines');
    if (holder) holder.innerHTML = (rule.authority_lines || []).map(line =>
      `<label class="contract-permission"><input type="checkbox" name="contractAuthorityLine" value="${esc(line)}" checked onchange="contractFormChanged()"><span>${esc(line)}</span></label>`
    ).join('');
  }
  if (refresh) contractFocusSection('matter');
  if (refresh) contractFormChanged();
}

function contractFeeConfigPayload() {
  const stageFees = [...document.querySelectorAll('[data-stage-fee-check]:checked')].map(check => {
    const stage = check.dataset.stage || '';
    const amount = document.querySelector(`[data-stage-fee-amount][data-stage="${CSS.escape(stage)}"]`)?.value || '';
    return {stage, amount};
  }).filter(item=>item.stage && item.amount);
  const tiers = [...document.querySelectorAll('[data-risk-tier]')].map(row=>({
    lower:row.querySelector('[data-tier-lower]')?.value||'',
    upper:row.querySelector('[data-tier-upper]')?.value||'',
    rate:row.querySelector('[data-tier-rate]')?.value||''
  })).filter(item=>item.lower||item.upper||item.rate);
  const config = {
    base_amount:$('feeBaseAmount')?.value||'',
    stage_fees:stageFees,
    rate:$('feeRiskRate')?.value||'',
    liability_action:$('feeLiabilityAction')?.value||'',
    payee_name:$('feePayeeName')?.value||'',
    claim_amount_wan:$('feeClaimAmountWan')?.value||'',
    baseline_amount_wan:$('feeBaselineAmountWan')?.value||'',
    no_liability_action:$('feeNoLiabilityAction')?.value||'',
    liability_examples:$('feeLiabilityExamples')?.value||'',
    success_amount_wan:$('feeSuccessAmountWan')?.value||'',
    guarantee_threshold_wan:$('feeGuaranteeThresholdWan')?.value||'',
    guarantee_fee_wan:$('feeGuaranteeFeeWan')?.value||'',
    tiers
  };
  return config;
}

function contractProfilePayload() {
  const lawyers = [...document.querySelectorAll('input[name="contractLawyer"]:checked')]
    .map(input => ({name:input.value}));
  const feePlan = selectedContractFeePlan();
  const feeConfig = contractFeeConfigPayload();
  const planLabel = state.contractWorkspace?.context?.fee_plans?.find(x=>x.id===feePlan)?.label || '';
  return {
    template_id:Number($('contractTemplateId')?.value||0)||null, lawyers,
    entrust_type:$('contractEntrustType')?.value||'',
    representation_stage:$('contractStage')?.value||'', engagement_scope:$('contractScope')?.value||'',
    background_matter:$('contractBackgroundMatter')?.value||'',
    background_stage:$('contractBackgroundStage')?.value||'',
    matter_kind:$('contractMatterKind')?.value||'case',
    fee_plan:feePlan, fee_config:feeConfig, fee_type:planLabel,
    fee_amount:feeConfig.base_amount||feeConfig.stage_fees?.[0]?.amount||'',
    payment_terms:'', contract_copies:$('contractCopies')?.value||'3',
    sign_date:$('contractSignDate')?.value||'', subject_amount:$('contractSubjectAmount')?.value||'',
    authority_lines:[...document.querySelectorAll('input[name="contractAuthorityLine"]:checked')].map(x=>x.value),
    authorizations:[],
    custom_values:{
      'case.court':$('contractCourt')?.value||'',
      'client.address':$('contractClientAddress')?.value||'',
      'client.email':$('contractClientEmail')?.value||''
    },
    firm:{name:$('contractFirmName')?.value||'',address:$('contractFirmAddress')?.value||'',credit_code:$('contractFirmCode')?.value||'',bank:$('contractFirmBank')?.value||'',account:$('contractFirmAccount')?.value||''}
  };
}

function contractFormChanged() {
  if (!state.contractWorkspace) return;
  const editor = $('drawerBody')?.querySelector('.contract-editor');
  const locked = state.contractWorkspace.lockEditorScrollUntil > Date.now()
    ? state.contractWorkspace.lockedEditorScrollTop : null;
  state.contractWorkspace.editorScrollTop = Number.isFinite(locked)
    ? locked : (editor?.scrollTop ?? 0);
  if (Number.isFinite(locked)) {
    requestAnimationFrame(() => { if (editor) editor.scrollTop = locked; });
    setTimeout(() => { if (editor) editor.scrollTop = locked; }, 120);
  }
  state.contractWorkspace.previewCurrent = false;
  state.contractWorkspace.profile = {...state.contractWorkspace.profile,...contractProfilePayload()};
  if ($('contractPreviewStatus')) $('contractPreviewStatus').textContent = '内容已变化，正在更新实际 Word 预览…';
  updateContractLivePreview();
  setContractFooter();
}

function contractFocusSection(section) {
  const workspace = state.contractWorkspace;
  if (!workspace || !section) return;
  workspace.focusSection = section;
  const editor = $('drawerBody')?.querySelector('.contract-editor');
  const editorTop = editor?.scrollTop;
  const frame = $('contractLivePreview')?.querySelector('iframe');
  if (frame?.contentWindow) {
    frame.contentWindow.postMessage({type:'contract-focus', section}, '*');
  }
  requestAnimationFrame(() => {
    if (editor && Number.isFinite(editorTop)) editor.scrollTop = editorTop;
  });
  setTimeout(() => {
    if (editor && Number.isFinite(editorTop)) editor.scrollTop = editorTop;
  }, 180);
}

function previewValue(value, label='待填写') {
  return value ? esc(value) : `<span class="preview-empty">${esc(label)}</span>`;
}

function formatContractFeePreview(profile) {
  const config = profile.fee_config || {};
  const money = value => value ? (/^[\d,.]+$/.test(value)?`${value}元`:value) : '【待填写】';
  const payment = config.payment_terms || '【待填写付款安排】';
  if (profile.fee_plan === 'fixed') return `本案采用固定收费方式，律师服务费共计${money(config.base_amount)}；${payment}。`;
  if (profile.fee_plan === 'staged_fixed') return `本案按阶段固定收费：一审或仲裁阶段${money(config.first_amount)}，二审阶段${money(config.second_amount)}；${payment}。`;
  const prefix = profile.fee_plan === 'base_risk' ? `本案采用基础费加风险代理费方式，基础律师服务费为${money(config.base_amount)}；` : '本案采用纯风险代理方式，不预先收取基础律师服务费；';
  let risk = '';
  if (config.risk_method === 'reduction_rate') risk = `以对方主张金额与最终承担金额之差额为基数，按${config.rate||'【待填写】'}%计收风险代理费`;
  else if (config.risk_method === 'success_fixed') risk = `如实现“${config.success_condition||'约定结果'}”，收取成功代理费${money(config.success_amount)}`;
  else if (config.risk_method === 'recovery_tiered') risk = (config.tiers||[]).filter(x=>x.threshold&&x.rate).map(x=>`实际回款${x.threshold}按${x.rate}%计收`).join('；') || '【待填写分段回款费率】';
  else risk = `以实际收回款项为基数，按${config.rate||'【待填写】'}%计收风险代理费`;
  return `${prefix}${risk}；${payment}。`;
}

function updateContractLivePreview(immediate=false) {
  const workspace = state.contractWorkspace;
  if (!workspace || !$('contractLivePreview')) return;
  clearTimeout(workspace.previewTimer);
  workspace.previewTimer = setTimeout(() => generateContractLivePreview(), immediate ? 0 : 850);
}

async function generateContractLivePreview() {
  const workspace = state.contractWorkspace;
  if (!workspace || !$('contractLivePreview')) return null;
  const profile = contractProfilePayload();
  const templateId = Number(profile.template_id || 0);
  if (!templateId) {
    $('contractPreviewStatus').textContent = '请先选择 Word 模板';
    $('contractLivePreview').innerHTML = '<div class="contract-preview-loading">请在左侧选择 Word 模板</div>';
    return null;
  }
  const caseId = workspace.caseId;
  const seq = ++workspace.previewSeq;
  workspace.profile = {...workspace.profile, ...profile};
  workspace.previewCurrent = false;
  $('contractPreviewStatus').textContent = '正在生成实际 Word 预览…';
  setContractFooter();
  try {
    const preview = await api(`/api/case-manager/cases/${caseId}/contracts/preview`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        template_id:templateId,
        profile,
        supersedes_token:workspace.preview?.preview_token || ''
      })
    });
    if (state.contractWorkspace !== workspace || workspace.caseId !== caseId || seq !== workspace.previewSeq) return null;
    workspace.preview = preview;
    workspace.previewCurrent = true;
    const missing = preview.missing || [];
    $('contractPreviewStatus').innerHTML = missing.length
      ? `<span class="danger">当前版本还缺：${esc(missing.join('、'))}</span>`
      : '预览与待导出的 Word 为同一版本';
    $('contractLivePreview').innerHTML = `<iframe class="contract-pdf-frame" title="委托代理合同实际预览" src="${esc(preview.html_url)}"></iframe>`;
    const frame = $('contractLivePreview').querySelector('iframe');
    frame.addEventListener('load', () => {
      const editor = $('drawerBody')?.querySelector('.contract-editor');
      const restoreTop = workspace.editorScrollTop;
      if (workspace.userFocusedSection && workspace.focusSection) {
        contractFocusSection(workspace.focusSection);
      }
      requestAnimationFrame(() => {
        if (editor && Number.isFinite(restoreTop)) editor.scrollTop = restoreTop;
      });
      setTimeout(() => {
        if (editor && Number.isFinite(restoreTop)) editor.scrollTop = restoreTop;
      }, 220);
    });
    setContractFooter();
    return preview;
  } catch (e) {
    if (state.contractWorkspace === workspace && seq === workspace.previewSeq) {
      workspace.previewCurrent = false;
      $('contractPreviewStatus').innerHTML = `<span class="danger">${esc(e.message || '预览生成失败')}</span>`;
      $('contractLivePreview').innerHTML = `<div class="contract-preview-loading danger">${esc(e.message || '预览生成失败')}</div>`;
      setContractFooter();
    }
    return null;
  }
}

function setContractFooter() {
  const workspace = state.contractWorkspace; if (!workspace) return;
  const preview = workspace.preview;
  const current = Boolean(preview && workspace.previewCurrent);
  $('drawerFoot').innerHTML = `<span class="contract-footer-hint">${current?'右侧与待导出的 Word 完全一致':'正在生成当前版本，旧版本不能导出'}</span>
    <button class="btn" onclick="returnToContractCase()">返回案件</button>
    <button class="btn" onclick="saveContractProfile(${workspace.caseId})">保存</button>
    ${current?`<button class="btn" onclick="downloadContractPreview('${preview.download_url}')">打开当前 Word</button><button class="btn primary" ${preview.can_export?'':'disabled'} onclick="exportContract(${workspace.caseId})">确认并归档当前版本</button>`:`<button class="btn primary" disabled>预览更新中…</button>`}`;
}

function downloadContractPreview(url) {
  const link = document.createElement('a');
  link.href = url;
  link.download = '委托代理合同_预览.docx';
  link.style.display = 'none';
  document.body.appendChild(link);
  link.click();
  setTimeout(() => link.remove(), 1000);
}

async function saveContractProfile(caseId, notify=true, savePreset=true) {
  const payload = contractProfilePayload();
  await api(`/api/case-manager/cases/${caseId}/contract-profile`, {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const workspace = state.contractWorkspace;
  if (!savePreset) {
    if (notify) toast('委托合同信息已保存');
    return payload;
  }
  const presetName = $('contractPresetName')?.value.trim() || `${workspace?.context?.case?.title||'委托代理合同'}方案`;
  const preset = await api('/api/contract-profile-presets', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({
      id:workspace?.presetId || null,
      name:presetName,
      source_case_id:caseId,
      profile:payload
    })
  });
  if (workspace) {
    workspace.presetId = preset.id;
    const existing = (workspace.presets||[]).find(item=>Number(item.id)===Number(preset.id));
    if (existing) Object.assign(existing,preset);
    else workspace.presets = [preset,...(workspace.presets||[])];
    const select = $('contractPresetSelect');
    if (select && ![...select.options].some(option=>Number(option.value)===Number(preset.id))) {
      select.insertAdjacentHTML('beforeend', `<option value="${Number(preset.id)}">${esc(preset.name)}</option>`);
    }
    if (select) select.value = String(preset.id);
  }
  if (notify) toast('合同已保存，并存入合同方案库');
  return payload;
}

async function applyContractPreset() {
  const workspace = state.contractWorkspace;
  const presetId = Number($('contractPresetSelect')?.value || 0);
  const preset = (workspace?.presets||[]).find(item=>Number(item.id)===presetId);
  if (!workspace || !preset) return toast('请先选择合同方案');
  const imported = JSON.parse(JSON.stringify(preset.profile || {}));
  const current = workspace.profile || {};
  imported.custom_values = {
    ...(imported.custom_values||{}),
    'case.court':current.custom_values?.['case.court'] || workspace.context?.case?.court || '',
    'client.address':current.custom_values?.['client.address'] || workspace.context?.client?.address || '',
    'client.email':current.custom_values?.['client.email'] || workspace.context?.client?.email || ''
  };
  imported.subject_amount = current.subject_amount || '';
  const merged = {...current,...imported};
  await api(`/api/case-manager/cases/${workspace.caseId}/contract-profile`, {
    method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(merged)
  });
  workspace.presetId = presetId;
  await openContractWorkspace(workspace.caseId);
  state.contractWorkspace.presetId = presetId;
  if ($('contractPresetSelect')) $('contractPresetSelect').value = String(presetId);
  if ($('contractPresetName')) $('contractPresetName').value = preset.name || '';
  toast('已套用合同方案；本案委托人和对方当事人保持不变');
}

async function uploadContractTemplate(caseId) {
  const input = document.createElement('input');
  input.type = 'file'; input.accept = '.docx';
  input.onchange = async () => {
    const file = input.files?.[0]; if (!file) return;
    const name = prompt('请输入模板名称', file.name.replace(/\.docx$/i,'')); if (!name) return;
    const form = new FormData(); form.append('file', file);
    try {
      const template = await api(`/api/contract-templates?name=${encodeURIComponent(name)}`, {method:'POST',body:form});
      await api(`/api/contract-templates/${template.id}/analyze`, {method:'POST'});
      toast('模板已上传并完成识别');
      await saveContractProfile(caseId, false, false);
      await openContractWorkspace(caseId);
      if ($('contractTemplateId')) {
        $('contractTemplateId').value = String(template.id);
        contractFormChanged();
      }
    } catch (e) { toast(e.message || '模板上传失败'); }
  };
  input.click();
}

function reviewSelectedTemplate() {
  const templateId = Number($('contractTemplateId')?.value||0);
  const caseId = Number(state.editing?.item?.id||0);
  if (!templateId) return toast('请先选择模板');
  openTemplateMappings(templateId, caseId);
}

async function openTemplateMappings(templateId, caseId) {
  try {
    const data = await api(`/api/contract-templates/${templateId}/mappings`);
    const fields = Object.entries(data.semantic_fields || {});
    $('drawerTitle').textContent = '审核模板字段映射';
    $('drawerBody').innerHTML = `<section class="detail-section"><h3>逐项确认填充位置</h3>
      <p class="jm-help">系统只提供语义建议。收费、身份、付款与代理范围均由你确认，不会由 AI 自行决定。</p>
      <div id="templateMappingRows">${(data.items||[]).map((item,index)=>`
        <div class="contact-group" data-map-index="${index}" style="margin:10px 0;padding:12px;border:1px solid var(--border)">
          <div><label>模板内容</label><code>${esc(item.token_text || item.label || '空白位置')}</code></div>
          <div><label>对应字段</label><select class="mapping-key">${fields.map(([key,info])=>`<option value="${esc(key)}" ${key===item.semantic_key?'selected':''}>${esc(info.label)}（${esc(key)}）</option>`).join('')}</select></div>
          <label><input type="checkbox" class="mapping-required" ${item.required?'checked':''}> 正式导出前必须填写</label>
          <input type="hidden" class="mapping-data" value="${esc(encodeURIComponent(JSON.stringify(item)))}">
        </div>`).join('') || '<p class="danger">未识别到可稳定填充的位置。请先在模板中加入 {{案件名称}} 等明确占位符后重新上传。</p>'}</div>
    </section>`;
    $('drawerFoot').innerHTML = `<button class="btn" onclick="openContractWorkspace(${caseId})">取消</button><button class="btn primary" onclick="saveTemplateMappings(${templateId},${caseId})">确认并保存映射</button>`;
  } catch (e) { toast(e.message || '读取映射失败'); }
}

async function saveTemplateMappings(templateId, caseId) {
  const items = [...document.querySelectorAll('#templateMappingRows [data-map-index]')].map(row => {
    const item = JSON.parse(decodeURIComponent(row.querySelector('.mapping-data').value));
    item.semantic_key = row.querySelector('.mapping-key').value;
    item.required = row.querySelector('.mapping-required').checked;
    return item;
  });
  if (!items.length) return toast('模板中没有可确认的字段');
  try {
    await api(`/api/contract-templates/${templateId}/mappings`, {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({items})});
    toast('字段映射已确认');
    await openContractWorkspace(caseId);
    if ($('contractTemplateId')) $('contractTemplateId').value = String(templateId);
  } catch (e) { toast(e.message || '保存映射失败'); }
}

async function previewContract(caseId) {
  const preview = await generateContractLivePreview();
  if (preview) downloadContractPreview(preview.download_url);
}

async function exportContract(caseId) {
  try {
    const workspace = state.contractWorkspace;
    const preview = workspace?.preview;
    if (!workspace || workspace.caseId !== caseId || !workspace.previewCurrent || !preview) {
      return toast('请等待右侧当前版本预览完成');
    }
    const profile = await saveContractProfile(caseId, false, false);
    const item = await api(`/api/case-manager/cases/${caseId}/contracts/export`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({preview_token:preview.preview_token,profile})});
    toast(`已保存到 ${item.relative_path}`);
    await openContractWorkspace(caseId);
  } catch (e) { toast(e.message || '正式导出失败'); }
}

function detailHtml(tab, item) {
  if (tab === 'cases') {
    const newCaseGuide = !item.title ? `<div class="new-case-flow-card"><p class="new-case-flow-label">新建案件流程</p><ol class="new-case-flow-steps"><li><span class="step-no">1</span><span class="step-body"><b>客户信息</b><i>选定并保存委托客户</i></span></li><li><span class="step-no">2</span><span class="step-body"><b>当事人</b><i>补委托人地位、录入对方</i></span></li><li><span class="step-no">3</span><span class="step-body"><b>案由</b><i>选择案件类型</i></span></li><li><span class="step-no">4</span><span class="step-body"><b>案件名称</b><i>自动生成，可修改</i></span></li></ol></div>` : '';
    const basicLocked = !hasCaseClient(item);
    const basicSection = basicLocked
      ? `<section class="detail-section case-section-locked"><h3 class="case-section-head case-section-head-locked"><span>基础信息</span><button class="case-section-edit case-section-edit-disabled" type="button" title="先完成“客户信息”添加与保存后方可编辑" disabled>${caseEditIcon()}</button></h3><div class="case-edit-note">请先在下方“客户信息”选定并保存委托客户，随后补充<b>案由</b>与<b>案件名称</b>。</div></section>`
      : caseDetailSection('基础信息', 'basic', item, detailListHtml([
        ['案件名称', item.title],
        ['案件类型', item.case_type],
        ['当前阶段', item.current_stage || '待补充'],
        ['提交时间', fmt(item.created_at)],
        ['更新时间', fmt(item.updated_at)]
      ]));
    return `
      <div class="case-detail-layout">
      <div class="case-detail-main">
      ${newCaseGuide}
      ${basicSection}
      <section class="detail-section" id="caseAutomationPanel">
        <h3>案件文件夹与文书</h3>
        <p class="muted">正在读取案件文件夹和归档文件…</p>
      </section>
      ${caseMiniTable('客户信息', 'clients', item, ['客户名称','统一社会信用代码'], customerRows(item))}
      ${caseMiniTable('当事人', 'parties', item, ['类别','地位','名称','统一社会信用代码/公民身份号码'], (item.parties || []).map(p => [p.party_group === 'client' ? '委托人' : '其他当事人', p.role, p.name, p.credit_code]))}
      ${caseNumbersSectionHtml(item)}
      ${caseContactHub(item, true)}
      ${recordList('待办事项', item.todos || [], t => `${fmt(t.remind_at)} ${t.todo_title || ''}`, [
        ['待办事项', t => t.todo_title],
        ['提醒时间', t => fmt(t.remind_at)],
        ['状态', t => t.status],
        ['备注', t => t.notes, true],
        ['更新时间', t => fmt(t.updated_at)]
      ])}
      ${recordList('开庭提醒', item.hearings || [], h => `${fmt(h.hearing_at)} ${h.location || ''}`, [
        ['类型', h => h.reminder_type],
        ['开庭时间', h => fmt(h.hearing_at)],
        ['开庭地点', h => h.location],
        ['案号', h => h.case_no],
        ['受理机构', h => h.court],
        ['更新时间', h => fmt(h.updated_at)],
        ['裁判机关经办人联系方式', h => h.court_contact, true],
        ['委托方及对方联系方式', h => h.party_contact, true]
      ])}
      ${recordList('财产保全', item.preservations || [], p => `${dateOnly(p.deadline_at)} ${p.preservation_type || ''}`, [
        ['类型', p => p.preservation_type],
        ['起算时间', p => dateOnly(p.start_at)],
        ['截止时间', p => dateOnly(p.deadline_at)],
        ['期限（年）', p => p.period_years || ''],
        ['保全财产内容', p => p.asset_content, true],
        ['备注', p => p.notes, true],
        ['更新时间', p => fmt(p.updated_at)]
      ])}
      ${recordList('上诉/异议期', item.appeals || [], a => `${dateOnly(a.deadline_at)} ${a.appeal_type || ''}`, [
        ['类型', a => a.appeal_type],
        ['起算时间', a => dateOnly(a.start_at)],
        ['期限（天）', a => a.period_days || ''],
        ['截止时间', a => dateOnly(a.deadline_at)],
        ['案号及受理机构', a => formatCaseNoCourt(a.case_no, a.court), true],
        ['更新时间', a => fmt(a.updated_at)],
        ['裁判机关经办人联系方式', a => a.court_contact, true],
        ['委托方及对方联系方式', a => a.party_contact, true]
      ])}
      </div>
      <div class="case-detail-side" aria-label="案件同步与数据日志">
        <div class="case-detail-side-content">
          ${courtOnlineAsideHtml(item)}
          ${auditLogPanel(item.audit_logs || [])}
        </div>
      </div>
      </div>
      ${courtOnlineActivityPanel(item)}
    `;
  }
  if (tab === 'todos') {
    return detailSection('待办事项', [
      ['案件名称', item.title],
      ['待办事项', item.todo_title],
      ['首次提醒时间', fmt(item.remind_at)],
      ['重复提醒', TODO_RECURRENCE_LABELS[item.recurrence] || '不重复'],
      ['状态', item.status],
      ['备注', item.notes, true],
      ['更新时间', fmt(item.updated_at)]
    ]);
  }
  if (tab === 'hearings') {
    return `
      ${detailSection('开庭提醒', [
        ['案件名称', item.title],
        ['类型', item.reminder_type],
        ['开庭时间', fmt(item.hearing_at)],
        ['开庭地点', item.location],
        ['更新时间', fmt(item.updated_at)]
      ])}
      ${miniTable('案号及受理机构', ['案号','受理机构'], caseNoCourtRows(item.case_no, item.court))}
      <div id="hearingContactSection" data-contact-token="drawer-hearing-${Number(item.id || 0)}" data-contact-case-id="${Number(item.case_id || 0)}"><section class="detail-section contact-section"><h3>联系与备忘</h3><div class="contact-hub"><div class="contact-hub-grid"><span class="contact-empty">正在加载联系方式…</span></div></div></section></div>
    `;
  }
  if (tab === 'preservations') {
    return detailSection('财产保全', [
      ['案件名称', item.title],
      ['类型', item.preservation_type],
      ['保全财产内容', item.asset_content],
      ['起算时间', dateOnly(item.start_at)],
      ['截止时间', dateOnly(item.deadline_at)],
      ['期限（年）', item.period_years ?? ''],
      ['备注', item.notes],
      ['更新时间', fmt(item.updated_at)]
    ]);
  }
  return `
    ${detailSection('上诉/异议期', [
      ['案件名称', item.title],
      ['类型', item.appeal_type],
      ['起算时间', dateOnly(item.start_at)],
      ['期限（天）', item.period_days ?? ''],
      ['截止时间', dateOnly(item.deadline_at)],
      ['更新时间', fmt(item.updated_at)]
    ])}
    ${miniTable('案号及受理机构', ['案号','受理机构'], caseNoCourtRows(item.case_no, item.court))}
    ${detailSection('联系方式', [
      ['裁判机关经办人联系方式', item.court_contact, true],
      ['委托方及对方联系方式', item.party_contact, true]
    ])}
  `;
}

function detailSection(title, rows) {
  return `<section class="detail-section"><h3>${esc(title)}</h3>${detailListHtml(rows)}</section>`;
}
function detailListHtml(rows) {
  return `<dl class="detail-list">${rows.map(([k, v, wide]) => {
    const value = v || '';
    const isWide = wide || String(value).length > 100 || String(value).includes('\n');
    return `<dt class="${isWide ? 'wide-label' : ''}">${esc(k)}</dt><dd class="${isWide ? 'wide-value' : ''}">${esc(value)}</dd>`;
  }).join('')}</dl>`;
}
function caseEditIcon() {
  return `<svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="m10.9 2.2 2.9 2.9M3 13l2.2-.5 8.2-8.2a1.15 1.15 0 0 0-1.6-1.6L3.6 10.8 3 13Z" stroke="currentColor" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
}
function courtOnlineAsideHtml(item) {
  const co = item.court_online || { cases: [], layy: [] };
  const metaPartsHtml = parts => parts.filter(Boolean)
    .map(part => `<span class="co-link-meta-part">${esc(part)}</span>`).join('');
  const caseCards = (co.cases || []).map(c => {
    const updatedAt = fmt(c.update_date || c.filing_date) || '';
    return `
    <div class="co-link-row co-link-expandable" onclick="toggleCourtOnlineCard(this,'cases',${Number(c.id)})" title="点击展开官网详情">
      <div class="co-link-head">
        <div class="co-link-badges">
          <span class="co-link-caret" aria-hidden="true"></span>
          <span class="court-kind-badge kind-cases">${esc(c.business_type || '案件')}</span>
          ${courtStageBadge(c.stage)}
        </div>
        <span class="co-link-date" title="更新时间：${esc(updatedAt || '—')}">${esc(dateOnly(c.update_date || c.filing_date) || '—')}</span>
      </div>
      <div class="co-link-title" title="${esc(c.case_name || '')}">${esc(c.case_name || c.case_number || '官网案件')}</div>
      <div class="co-link-meta">${metaPartsHtml([c.case_number, c.court_name, c.judge ? `承办 ${c.judge}` : ''])}</div>
      <div class="co-link-foot">
        <div class="co-link-actions">
          <button class="court-action co-link-secondary" type="button" onclick="event.stopPropagation();courtJumpToKind('cases', '${esc(c.case_number || '')}')">在一张网中查看</button>
          <button class="court-action primary" type="button" onclick="event.stopPropagation();openCourtSyncPlan(${Number(item.id)}, ${Number(c.id)})" title="智能检测官网案件信息并同步到本案对应字段">同步到案件</button>
        </div>
      </div>
      <div class="co-link-expand"><div class="co-link-expand-inner"></div></div>
    </div>`;
  }).join('');
  const layyCards = (co.layy || []).map(l => {
    const updatedAt = fmt(l.update_date || l.filed_date) || '';
    const layyRows = [
      ['法院', l.court_name], ['案件类型', l.case_type],
      ['案由', l.cause], ['法院审核状态', courtLayyReviewStatusText(l)],
      ['官网流程状态', courtLayyStatusText(l.status)],
      ['申请人', l.applicant], ['申请时间', fmt(l.apply_time || l.filed_date)],
      ['提交时间', fmt(l.submit_time)], ['承办人', l.judge],
      ['当事人', l.parties], ['审核意见', l.review_comment],
      ['登记日期', fmt(l.filed_date)], ['更新时间', fmt(l.update_date)],
    ].filter(([, v]) => String(v || '').trim());
    return `
    <div class="co-link-row co-link-expandable" onclick="toggleCourtOnlineCard(this,'layy',0)" title="点击展开详情">
      <div class="co-link-head">
        <div class="co-link-badges">
          <span class="co-link-caret" aria-hidden="true"></span>
          <span class="court-kind-badge kind-layy">立案预约</span>
        </div>
        <span class="co-link-date" title="更新时间：${esc(updatedAt || '—')}">${esc(dateOnly(l.update_date || l.filed_date) || '—')}</span>
      </div>
      <div class="co-link-title" title="${esc(l.case_name || '')}">${esc(l.case_name || l.cause || '立案预约')}</div>
      <div class="co-link-meta">${metaPartsHtml([l.court_name, l.case_type, courtLayyReviewStatusText(l)])}</div>
      <div class="co-link-foot">
        <div class="co-link-actions">
          <button class="court-action co-link-secondary" type="button" onclick="event.stopPropagation();courtJumpToKind('layy', '${esc(l.case_name || l.cause || '')}')">在一张网中查看</button>
        </div>
      </div>
      <div class="co-link-expand"><div class="co-link-expand-inner">${layyRows.length ? `<div class="co-expand-grid">${courtInlineFieldRows(layyRows)}</div>` : '<div class="co-link-loading">暂无更多信息</div>'}</div></div>
    </div>`;
  }).join('');
  const cards = (caseCards ? `<div class="co-link-group">${caseCards}</div>` : '') + (layyCards ? `<div class="co-link-group">${layyCards}</div>` : '');
  if (!cards) return '';
  return `<aside class="audit-panel co-online-panel">
    <div class="audit-panel-head"><h3>一张网同步</h3><span>${(co.cases || []).length + (co.layy || []).length} 条记录</span></div>
    <div class="audit-list">${cards}</div>
  </aside>`;
}
function courtOnlineActivityPanel(item) {
  const co = item.court_online || {};
  const records = co.records || [];
  const hearings = co.hearings || [];
  const kindLabel = { todo: '待办', message: '消息', delivery: '电子送达' };
  const deliveryPending = records.filter(row => row.kind === 'delivery' && row.delivery_status === '1').length;
  const unread = records.filter(row => row.unread).length;
  const countPills = [
    records.filter(row => row.kind === 'delivery').length ? `电子送达 ${records.filter(row => row.kind === 'delivery').length}` : '',
    records.filter(row => row.kind === 'message').length ? `消息 ${records.filter(row => row.kind === 'message').length}` : '',
    hearings.length ? `开庭 ${hearings.length}` : '',
  ].filter(Boolean);
  const recordCards = records.map(row => {
    const title = row.title || (row.kind === 'delivery' ? '电子送达' : '法院通知');
    const desc = row.content || [row.case_number || row.case_name, row.court_name].filter(Boolean).join(' · ') || '暂无摘要';
    const status = row.kind === 'delivery'
      ? (row.delivery_status === '1' ? '待签收' : row.delivery_status === '2' ? '已签收' : '')
      : row.unread ? '未读' : '';
    const meta = [row.case_number || row.case_name, row.court_name, status].filter(Boolean).join(' · ');
    const query = row.case_number || row.case_name || title;
    return `<button class="court-activity-item" type="button" data-court-kind="${esc(row.kind || '')}" data-court-query="${esc(query)}" onclick="courtJumpToKindFromElement(this)" title="在一张网中查看">
      <div class="court-activity-item-top"><span class="court-kind-badge kind-${esc(row.kind || 'default')}">${esc(kindLabel[row.kind] || '法院通知')}</span><time>${esc(fmt(row.published_at || row.updated_at) || '—')}</time></div>
      <div class="court-activity-item-title">${esc(title)}</div>
      <div class="court-activity-item-desc">${esc(desc)}</div>
      ${meta ? `<div class="court-activity-item-meta">${esc(meta)}</div>` : ''}
    </button>`;
  });
  const hearingCards = hearings.map(row => {
    const title = row.hearing_type || '开庭提醒';
    const desc = [row.case_name || row.case_number, row.location].filter(Boolean).join(' · ') || '暂无地点信息';
    const meta = [row.court_name, row.judge ? `承办 ${row.judge}` : '', row.status].filter(Boolean).join(' · ');
    const query = row.case_number || row.case_name || '';
    return `<button class="court-activity-item" type="button" data-court-kind="hearings" data-court-query="${esc(query)}" onclick="courtJumpToKindFromElement(this)" title="在一张网中查看">
      <div class="court-activity-item-top"><span class="court-kind-badge kind-hearings">开庭提醒</span><time>${esc(fmt(row.hearing_at || row.updated_at) || '—')}</time></div>
      <div class="court-activity-item-title">${esc(title)}</div>
      <div class="court-activity-item-desc">${esc(desc)}</div>
      ${meta ? `<div class="court-activity-item-meta">${esc(meta)}</div>` : ''}
    </button>`;
  });
  // 卡片保持简要浏览：优先展示最近的送达/消息和最多三条开庭提醒，完整记录仍可在一张网中查看。
  const cards = [...recordCards.slice(0, 5), ...hearingCards.slice(0, 3)];
  return `<section class="court-activity-panel" aria-label="一张网关联动态">
    <div class="court-activity-head">
      <div class="court-activity-title"><h3>一张网关联动态</h3><span class="court-activity-source">送达、消息、开庭提醒</span></div>
      <div class="court-activity-summary"><span class="court-activity-count">共 ${records.length + hearings.length} 条</span>${countPills.map(label => `<span class="court-activity-count">${esc(label)}</span>`).join('')}${unread || deliveryPending ? `<span class="court-activity-count has-unread">${deliveryPending ? `待签收 ${deliveryPending}` : `未读 ${unread}`}</span>` : ''}</div>
    </div>
    ${cards.length ? `<div class="court-activity-list">${cards.join('')}</div>` : '<div class="court-activity-empty">暂无关联的一张网送达、消息或开庭提醒。</div>'}
  </section>`;
}
function courtJumpToKindFromElement(element) {
  courtJumpToKind(element?.dataset?.courtKind || '', element?.dataset?.courtQuery || '');
}
function courtInlineFieldRows(rows) {
  return rows.map(([label, value]) => {
    const text = String(value || '');
    const full = text.length > 16 || /[\n，,、]/.test(text);
    return `<div class="co-expand-field${full ? ' co-expand-full' : ''}"><dt>${esc(label)}</dt><dd>${esc(text)}</dd></div>`;
  }).join('');
}
function courtInlineCaseHtml(d) {
  const rows = [
    ['案由', d.cause],
    ['案件类别', d.case_category], ['审理程序', d.procedure],
    ['原审案号', d.original_number], ['承办法院', d.current_court],
    ['移送法院', d.transfer_court], ['承办部门', d.department],
    ['承办法官', d.judge], ['裁判方式', d.adjudication],
    ['立案日期', d.filing_date], ['结案日期', d.judgment_date],
    ['送达日期', d.served_date], ['开庭时间', d.hearing_at],
    ['立案标的额', d.amount], ['官网账号', d.account],
  ].filter(([, v]) => String(v || '').trim());
  const linked = Number(d.linked_case_id || 0);
  const footer = linked
    ? `<div class="co-expand-foot"><span>已关联本地案件</span><button class="court-action primary" type="button" onclick="event.stopPropagation();openDetail('cases', ${linked})">打开本地案件</button></div>`
    : '';
  return `<div class="co-expand-grid">${courtInlineFieldRows(rows)}</div>${footer}`;
}
async function toggleCourtOnlineCard(row, kind, id) {
  if (!row) return;
  const expanding = !row.classList.contains('expanded');
  row.classList.toggle('expanded', expanding);
  if (!expanding || kind !== 'cases') return;
  const inner = row.querySelector('.co-link-expand-inner');
  if (!inner) return;
  try {
    inner.innerHTML = '<div class="co-link-loading">正在加载官网详情…</div>';
    const d = await api(`${CO_API}/cases/${Number(id)}/detail`);
    if (!row.isConnected || !row.classList.contains('expanded')) return;
    inner.innerHTML = courtInlineCaseHtml(d);
    makeDetailFieldsCopyable(inner);
    row.dataset.loaded = '1';
  } catch (e) {
    if (row.isConnected && row.classList.contains('expanded')) {
      inner.innerHTML = `<div class="co-link-loading">${esc(e.message || '详情加载失败')}</div>`;
    }
  }
}
function courtJumpToKind(kind, query) {
  if (window.parent && window.parent !== window) {
    window.parent.postMessage({ type: 'openCourtOnline', kind, query: String(query || '').trim() }, location.origin);
    return;
  }
  if (activeTab !== 'courtOnline') switchTab('courtOnline');
  state.courtOnline.kind = kind;
  state.courtOnline.q = String(query || '').trim();
  state.courtOnline.page = 1;
  state.courtOnline.unread = false;
  loadCourtOnline();
}
function hasCaseClient(item) {
  const it = item || state.editing?.item;
  if (!it) return false;
  return ((it.client_profiles || []).length) > 0 || ((it.parties || []).some(p => p.party_group === 'client'));
}
function caseSectionHead(title, section) {
  const titleText = esc(title);
  const editing = state.editing?.inlineSection === section;
  const locked = section !== 'clients' && !hasCaseClient();
  const tools = editing
    ? `<span class="case-section-tools"><button class="btn" type="button" onclick="cancelCaseSectionEdit()">取消</button><button class="btn primary" type="button" onclick="saveCaseSection('${section}')">保存</button></span>`
    : locked
      ? `<button class="case-section-edit case-section-edit-disabled" type="button" aria-label="编辑${titleText}" title="先完成“客户信息”添加与保存后方可编辑" disabled>${caseEditIcon()}</button>`
      : `<button class="case-section-edit" type="button" onclick="editCaseSection('${section}')" aria-label="编辑${titleText}" title="编辑${titleText}">${caseEditIcon()}</button>`;
  return `<h3 class="case-section-head${locked ? ' case-section-head-locked' : ''}"><span>${titleText}</span>${tools}</h3>`;
}
function caseDetailSection(title, section, item, content) {
  const editing = state.editing?.inlineSection === section;
  const locked = section !== 'clients' && !hasCaseClient();
  return `<section class="detail-section case-editable-section${locked ? ' case-section-locked' : ''}" data-case-inline-section="${section}">${caseSectionHead(title, section)}${editing ? caseSectionEditorHtml(section, item) : content}</section>`;
}
function caseMiniTable(title, section, item, headers, rows) {
  const content = rows.length
    ? `<div class="detail-table-wrap"><table class="${section === 'numbers' ? 'mini-table case-number-mini' : 'mini-table'}"><thead><tr>${headers.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(r => `<tr>${r.map(c => `<td>${esc(c || '')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`
    : section === 'clients'
      ? `<div class="case-add-client-empty"><button class="case-add-client-btn" type="button" onclick="editCaseSection('clients')">添加客户</button></div>`
      : '<div class="empty">暂无数据</div>';
  return caseDetailSection(title, section, item, content);
}
function caseNumberDisplayKey(n) {
  return [n.number_type, n.case_no, n.court].map(v => String(v || '').trim()).join('||');
}
function caseNumbersSelectionKey(caseId) { return `cm_case_numbers_display:${caseId}`; }
function saveCaseNumbersSelection(caseId, keys) {
  try { localStorage.setItem(caseNumbersSelectionKey(caseId), JSON.stringify(keys || [])); } catch (_) {}
}
function readCaseNumbersSelection(caseId, keys) {
  let stored = [];
  try { stored = JSON.parse(localStorage.getItem(caseNumbersSelectionKey(caseId)) || '[]'); } catch (_) { stored = []; }
  if (!Array.isArray(stored)) stored = [];
  const valid = (keys || []).filter(key => stored.includes(key));
  if (valid.length !== stored.length) saveCaseNumbersSelection(caseId, valid);
  return valid;
}
function caseNumbersSectionHtml(item) {
  const rows = item.case_numbers || [];
  const content = rows.length ? caseNumberViewTableHtml(item, rows) : '<div class="empty">暂无数据</div>';
  return caseDetailSection('案号', 'numbers', item, content);
}
function caseNumberViewTableHtml(item, rows) {
  const keys = rows.map(caseNumberDisplayKey);
  const selection = readCaseNumbersSelection(item.id || 'new', keys);
  const selectedSet = new Set(selection);
  const expanded = state.editing?.caseNumbersExpanded === true;
  const hasSelection = selection.length > 0 && selection.length < rows.length;
  const showAll = !hasSelection || expanded;
  const visibleRows = showAll ? rows : rows.filter(n => selectedSet.has(caseNumberDisplayKey(n)));
  const table = `<div class="detail-table-wrap"><table class="mini-table case-number-mini"><thead><tr><th>性质</th><th>案号</th><th>受理机构</th><th>一审立案时间</th><th>一审判决送达时间</th><th>二审立案时间</th><th>二审判决生效时间</th></tr></thead><tbody>${visibleRows.map(n => {
    const cells = [n.number_type, n.case_no, n.court, dateOnly(n.first_filing_at), dateOnly(n.first_judgment_served_at), dateOnly(n.second_filing_at), dateOnly(n.second_judgment_effective_at)];
    return `<tr>${cells.map(c => `<td>${esc(c || '')}</td>`).join('')}</tr>`;
  }).join('')}</tbody></table></div>`;
  const bar = !hasSelection ? '' : `<div class="case-no-collapse-bar">${showAll
    ? `<span class="case-no-collapse-text">已展示全部 ${rows.length} 个案号</span><button class="btn" type="button" onclick="toggleCaseNumbersExpand()">收起</button>`
    : `<span class="case-no-collapse-text">已展示 ${visibleRows.length} 个案号，其余 ${rows.length - visibleRows.length} 个已折叠（编辑中可调整展示的案号）</span><button class="btn" type="button" onclick="toggleCaseNumbersExpand()">展开全部</button>`}</div>`;
  return table + bar;
}
function rerenderCaseNumbersSection() {
  const item = state.editing?.item;
  if (!item || state.editing?.tab !== 'cases') return;
  const section = document.querySelector('[data-case-inline-section="numbers"]');
  if (!section) return renderOpenCaseDetail();
  section.outerHTML = caseNumbersSectionHtml(item);
  makeDetailFieldsCopyable(document.querySelector('[data-case-inline-section="numbers"]'));
}
function toggleCaseNumbersExpand() {
  if (!state.editing) return;
  state.editing.caseNumbersExpanded = !state.editing.caseNumbersExpanded;
  rerenderCaseNumbersSection();
}
function inlinePartyRow(p = {}, section = 'parties') {
  const clientOnly = section === 'clients';
  const group = clientOnly ? 'client' : (p.party_group || 'client');
  return `<tr data-inline-party-row>
    <td><select class="input" data-party-group onchange="syncInlinePartyGroupLookup(this)" ${clientOnly ? 'disabled' : ''}><option value="client" ${group === 'client' ? 'selected' : ''}>委托人</option><option value="other" ${group === 'other' ? 'selected' : ''}>其他当事人</option></select></td>
    <td><input class="input" data-party-role value="${esc(p.role || '')}" placeholder="地位" autocomplete="off" oninput="lookupPartyRoles(this)" onfocus="lookupPartyRoles(this)"></td>
    <td><div class="lookup-field"><input class="input" data-party-name value="${esc(p.name || '')}" placeholder="点击选择或搜索名称" autocomplete="off" oninput="lookupPartyName(this)" onfocus="lookupPartyName(this)"><div class="lookup-results"></div></div></td>
    <td><input class="input" data-party-credit-code value="${esc(p.credit_code || '')}" placeholder="统一社会信用代码或身份证号"></td>
    <td class="detail-edit-remove"><button class="btn" type="button" onclick="this.closest('tr').remove()" title="删除">×</button></td>
  </tr>`;
}
async function lookupPartyName(input) {
  hideLookupResults();
  const row = input.closest('[data-inline-party-row]');
  const group = row?.querySelector('[data-party-group]')?.value === 'client' ? 'clients' : 'opponents';
  const q = input.value.trim();
  try {
    const items = group === 'clients' && window.ApexAPI
      ? (await ApexAPI.searchClients(q, 12)).map(client => ({
          id: client.id, value: client.name, label: client.name,
          identity_code: client.identity_code,
          meta: [client.client_type, client.identity_code].filter(Boolean).join(' · '),
        }))
      : (await api(`/api/case-manager/series-options?kind=${encodeURIComponent(group)}&q=${encodeURIComponent(q)}&limit=12`)).items || [];
    renderProfileLookup(input, items, q, '使用当前名称', (profile, target) => {
      const code = target.closest('[data-inline-party-row]')?.querySelector('[data-party-credit-code]');
      if (code) code.value = profile.identity_code || '';
    });
  } catch (e) {}
}
let mountedClientPickers = [];
function destroyMountedClientPickers() {
  mountedClientPickers.forEach(picker => { try { picker.destroy(); } catch (_) { /* 已销毁则忽略 */ } });
  mountedClientPickers = [];
}
function mountMasterClientPickers(root) {
  if (!window.ApexClientPicker) return;
  (root || document).querySelectorAll('[data-client-table-row]').forEach(row => {
    const input = row.querySelector('[data-client-name]');
    const menu = row.querySelector('.lookup-results');
    if (!input || !menu || ApexClientPicker.forInput(input)) return;
    mountedClientPickers.push(ApexClientPicker.attach({
      input,
      menu,
      mode: 'single',
      onInput() { renderMasterClientSyncHint(); },
      onSelect(item) {
        row.dataset.clientId = String(Number(item.id || 0));
        const code = row.querySelector('[data-client-code]');
        if (code) code.value = item.identity_code || '';
        syncMasterClientToParties({ id: Number(item.id || 0), name: item.name, identity_code: item.identity_code || '' });
        renderMasterClientSyncHint();
        toast('客户已同步到“当事人·委托人”，可在“当事人”卡片设置委托人地位');
      },
    }));
  });
}
function renderProfileLookup(input, items, query, createLabel, onSelect) {
  const box = lookupBoxForInput(null, input);
  if (!box) return;
  const profiles = (items || []).filter(item => item?.value || item?.label).slice(0, 12);
  if (!profiles.length && !query) { box.classList.remove('show'); box.innerHTML = ''; return; }
  box._lookupInput = input;
  box._profileItems = profiles;
  box._profileOnSelect = onSelect;
  const optionHtml = profiles.map((profile, index) => `<button class="lookup-option" type="button" onclick="selectProfileLookup(this,${index})"><strong>${esc(profile.label || profile.value)}</strong>${profile.meta ? `<span>${esc(profile.meta)}</span>` : ''}</button>`).join('');
  const createHtml = query ? `<button class="lookup-option create-option" type="button" onclick="acceptLookupInput(this)"><strong>${esc(createLabel || '使用当前输入')}</strong><span>${esc(query)}</span></button>` : '';
  box.innerHTML = optionHtml + createHtml;
  box.classList.add('show');
  if (box.classList.contains('floating')) positionFloatingLookup(input, box);
}
function selectProfileLookup(button, index) {
  const box = button.closest('.lookup-results');
  const input = box?._lookupInput;
  const profile = box?._profileItems?.[Number(index)];
  if (input && profile) {
    input.value = profile.value || profile.label || '';
    input.dispatchEvent(new Event('change', { bubbles: true }));
    box?._profileOnSelect?.(profile, input);
  }
  if (box) box.classList.remove('show');
}
function syncInlinePartyGroupLookup(select) {
  const row = select.closest('[data-inline-party-row]');
  const input = row?.querySelector('[data-party-name]');
  if (input) lookupPartyName(input);
}
function inlinePartyEditorHtml(section, item) {
  const rows = (item.parties || []).filter(p => section !== 'clients' || p.party_group === 'client');
  return `<p class="case-edit-note">委托人由<b>客户信息</b>自动带出；点“添加当事人”录入<b>对方当事人</b>。“地位”可填写或选择<b>委托人地位</b>。</p><div class="detail-table-wrap"><table class="mini-table detail-edit-table"><thead><tr><th>类别</th><th>地位</th><th>名称</th><th>统一社会信用代码/公民身份号码</th><th></th></tr></thead>
    <tbody data-inline-party-list="${section}">${(rows.length ? rows : [{ party_group: 'client', role: '' }]).map(p => inlinePartyRow(p, section)).join('')}</tbody></table></div>
    <button class="btn case-inline-add" type="button" onclick="addInlinePartyRow('${section}')">添加当事人</button>`;
}
function clientMasterEditorHtml(item) {
  const profiles = item.client_profiles || [];
  const parties = (item.parties || []).filter(p => p.party_group === 'client');
  const sources = profiles.length ? profiles : parties.map(party => ({ id: party.client_id || 0, name: party.name, identity_code: party.credit_code || '' }));
  return `<p class="case-edit-note">先选定或录入<b>客户</b>，选定后会同步到下方<b>当事人</b>卡片的“委托人”记录；保存后请到“当事人”卡片设置其<b>委托人地位</b>。</p>
    <div class="detail-table-wrap"><table class="mini-table detail-edit-table"><thead><tr><th>客户名称</th><th>统一社会信用代码</th><th></th></tr></thead>
    <tbody class="case-client-table-body">${(sources.length ? sources : [{}]).map(clientTableRow).join('')}</tbody></table></div>
    <div class="client-sync-hint" id="clientSyncHint"></div>
    <button class="btn case-inline-add" type="button" onclick="addMasterClient()">添加客户</button>`;
}
function clientTableRow(client = {}) {
  return `<tr data-client-table-row data-client-id="${Number(client.id || 0)}"><td><div class="lookup-field"><input class="input" data-client-name value="${esc(client.name || '')}" placeholder="点击选择或搜索客户名称" autocomplete="off"><div class="lookup-results"></div></div></td><td><input class="input" data-client-code value="${esc(client.identity_code || '')}" placeholder="统一社会信用代码"></td><td class="detail-edit-remove"><button class="btn" type="button" onclick="this.closest('tr').remove()">×</button></td></tr>`;
}
function addMasterClient() {
  document.querySelector('.case-client-table-body')?.insertAdjacentHTML('beforeend', clientTableRow());
  mountMasterClientPickers(document);
}
function addInlinePartyRow(section) {
  const host = document.querySelector(`[data-inline-party-list="${section}"]`);
  if (host) host.insertAdjacentHTML('beforeend', inlinePartyRow({ party_group: section === 'clients' ? 'client' : 'client', role: section === 'clients' ? '委托人' : '' }, section));
}
function caseSectionEditorHtml(section, item) {
  let body = '';
  if (section === 'basic') {
    body = `<p class="case-edit-note">建议先填好<b>客户信息</b>与<b>当事人</b>（委托人、对方），再选择<b>案由</b>，案件名称会根据当事人与案由自动生成，可直接修改。</p>
    <dl class="detail-list detail-edit-list">
      <dt>案件名称</dt><dd class="case-name-cell" style="display:flex;gap:6px;align-items:center"><input class="input" name="title" value="${esc(item.title || '')}" placeholder="可自动生成（委托人、对方当事人、案由）" oninput="onCaseTitleInput(this)"><button class="btn case-name-gov" type="button" onclick="autoFillCaseTitle()" title="根据当事人与案由自动生成案件名称">自动生成</button></dd>
      <dt>案件类型（案由）</dt><dd><div class="lookup-field detail-edit-lookup"><input class="input" name="case_type" value="${esc(item.case_type || '')}" placeholder="搜索或输入案件类型" autocomplete="off" oninput="lookupCaseTypes(this);caseTypeChanged()" onchange="caseTypeChanged()" onfocus="lookupCaseTypes(this)"><div class="lookup-results"></div></div></dd>
      <dt>当前阶段</dt><dd><div class="lookup-field detail-edit-lookup"><input class="input" name="current_stage" value="${esc(item.current_stage || '')}" placeholder="搜索或输入当前阶段" autocomplete="off" oninput="lookupCaseStages(this)" onfocus="lookupCaseStages(this)"><div class="lookup-results stage-lookup-results"></div></div></dd>
      <dt>提交时间</dt><dd>${esc(fmt(item.created_at))}</dd>
      <dt>更新时间</dt><dd>${esc(fmt(item.updated_at))}</dd>
    </dl>`;
  } else if (section === 'clients') {
    body = clientMasterEditorHtml(item);
  } else if (section === 'parties') {
    body = inlinePartyEditorHtml(section, item);
  } else if (section === 'numbers') {
    body = caseNumberEditorHtml(item);
  } else if (section === 'contacts') {
    body = contactEditorHtml(item);
  }
  return `<div class="case-section-editor">${body}</div>`;
}
function buildCaseNameSuggestion(caseType) {
  const item = state.editing?.item || {};
  const cause = String(caseType !== undefined ? caseType : (document.querySelector('[data-case-inline-section="basic"] [name="case_type"]')?.value.trim() || '') || item.case_type || '');
  const parties = item.parties || [];
  const clientNames = [...new Set(parties.filter(p => p.party_group === 'client' && p.name).map(p => p.name))];
  const opponentNames = [...new Set(parties.filter(p => p.party_group !== 'client' && p.name).map(p => p.name))];
  const parts = [];
  if (clientNames.length) parts.push(clientNames.join('、'));
  if (opponentNames.length) parts.push(opponentNames.join('、'));
  if (cause) parts.push(cause);
  return parts.join('、');
}
function onCaseTitleInput(input) {
  if (!state.editing) return;
  const val = input.value.trim();
  const last = state.editing.lastSuggestedTitle || '';
  if (val && val !== last) state.editing.titleTouched = true;
}
function caseTypeChanged() {
  const causeInput = document.querySelector('[data-case-inline-section="basic"] [name="case_type"]');
  if (state.editing?.item) state.editing.item.case_type = causeInput?.value.trim() || '';
  maybeAutoFillCaseTitle();
}
function maybeAutoFillCaseTitle() {
  const input = document.querySelector('[data-case-inline-section="basic"] [name="title"]');
  if (!input) return;
  const suggestion = buildCaseNameSuggestion();
  if (!suggestion) return;
  const current = input.value.trim();
  const last = state.editing?.lastSuggestedTitle || '';
  if (current && current !== last) return;
  input.value = suggestion;
  if (state.editing) { state.editing.lastSuggestedTitle = suggestion; state.editing.titleTouched = false; }
}
function autoFillCaseTitle() {
  const input = document.querySelector('[data-case-inline-section="basic"] [name="title"]');
  if (!input) return;
  const suggestion = buildCaseNameSuggestion();
  if (!suggestion) return toast('请先在“当事人”填写委托人／对方当事人，并选择案由，即可自动生成名称');
  input.value = suggestion;
  if (state.editing) { state.editing.lastSuggestedTitle = suggestion; state.editing.titleTouched = false; }
}
function syncMasterClientToParties(client) {
  const item = state.editing?.item;
  if (!item) return;
  const name = String(client.name || '').trim();
  if (!name) return;
  const id = Number(client.id || 0);
  if (!item.client_profiles) item.client_profiles = [];
  const profile = item.client_profiles.find(p => (id && Number(p.id) === id) || p.name === name);
  if (profile) Object.assign(profile, { id: id || profile.id, name, identity_code: client.identity_code || profile.identity_code || '' });
  else item.client_profiles.push({ id, name, identity_code: client.identity_code || '' });
  if (!item.parties) item.parties = [];
  const party = item.parties.find(p => p.party_group === 'client' && ((id && Number(p.client_id) === id) || p.name === name));
  if (party) {
    party.name = name;
    party.credit_code = client.identity_code || party.credit_code || '';
    party.role = party.role || '委托人';
  } else {
    item.parties.push({ party_group: 'client', role: '委托人', name, credit_code: client.identity_code || '' });
  }
}
function renderMasterClientSyncHint() {
  const box = $('clientSyncHint');
  if (!box) return;
  const clients = readMasterClients().filter(c => c.name);
  box.innerHTML = clients.length
    ? `<span class="client-sync-label">将同步到<b>当事人</b>：</span>` + clients.map(c => `<span class="tag case-client-sync-tag">委托人·${esc(c.name)}</span>`).join('')
    : '';
}
async function prepareCaseSection(section) {
  if (section === 'basic') await Promise.all([loadCaseTypes(''), loadCaseStages()]);
  if (section === 'clients') {
    const parties = (state.editing?.item?.parties || []).filter(party => party.party_group === 'client' && party.name);
    const profiles = await Promise.all(parties.map(async party => {
      const result = await api(`/api/case-manager/clients?q=${encodeURIComponent(party.name)}&limit=20`);
      const profile = (result.items || []).find(entry => entry.name === party.name);
      return profile?.id ? api(`/api/case-manager/clients/${profile.id}`) : null;
    }));
    state.editing.item.client_profiles = profiles.filter(Boolean);
  }
  if (section === 'parties') await loadPartyRoles();
  if (section === 'numbers') await Promise.all([loadCaseNumberTypes(), loadCourts()]);
}
function renderOpenCaseDetail() {
  const item = state.editing?.item;
  if (!item || state.editing?.tab !== 'cases') return;
  destroyMountedClientPickers();
  $('drawerTitle').textContent = item.title || (state.editing.isNew ? '新建案件' : '案件详情');
  $('drawerBody').innerHTML = detailHtml('cases', item);
  makeDetailFieldsCopyable($('drawerBody'));
  mountMasterClientPickers($('drawerBody'));
  requestAnimationFrame(() => $('drawerBody')?.querySelectorAll('.contact-edit-notes textarea, .contact-edit-memo-input').forEach(resizeContactNote));
  if (item.id) loadCaseAutomationPanel(Number(item.id));
  else renderCaseFolderUnboundPanel();
}
async function editCaseSection(section) {
  // Case fields use the existing durable pending-operation queue while offline.
  // Master-client records remain server-backed and are the only section blocked.
  if (isOfflineReadonly() && section === 'clients') return requireOnlineAction();
  const item = state.editing?.item;
  if (!item || state.editing?.tab !== 'cases') return;
  if (section !== 'clients' && !hasCaseClient()) return toast('请先在下方“客户信息”添加并保存客户后再编辑该字段');
  try {
    await prepareCaseSection(section);
    if (section === 'basic') { state.editing.titleTouched = false; state.editing.lastSuggestedTitle = ''; }
    state.editing.inlineSection = section;
    renderOpenCaseDetail();
  } catch (e) { toast(e.message || '无法打开编辑区'); }
}
function cancelCaseSectionEdit() {
  if (!state.editing?.item) return;
  state.editing.inlineSection = '';
  renderOpenCaseDetail();
}
function readInlineParties(section) {
  const changed = [...document.querySelectorAll('[data-inline-party-row]')].map(row => ({
    party_group: /^(委托人|client)$/i.test(row.querySelector('[data-party-group]')?.value.trim() || '') ? 'client' : 'other',
    role: row.querySelector('[data-party-role]')?.value.trim() || '',
    name: row.querySelector('[data-party-name]')?.value.trim() || '',
    credit_code: row.querySelector('[data-party-credit-code]')?.value.trim() || '',
  })).filter(p => p.role || p.name || p.credit_code);
  return changed;
}
function readMasterClients() {
  return [...document.querySelectorAll('[data-client-table-row]')].map(row => ({
    id: Number(row.dataset.clientId || 0),
    name: row.querySelector('[data-client-name]')?.value.trim() || '',
    identity_code: row.querySelector('[data-client-code]')?.value.trim() || '',
  })).filter(client => client.name);
}
function readInlineCaseNumbers() {
  return [...document.querySelectorAll('[data-case-number-row]')].map(row => ({
    number_type: row.querySelector('[name=number_type]')?.value.trim() || '',
    case_no: row.querySelector('[name=case_no]')?.value.trim() || '',
    court: row.querySelector('[name=court]')?.value.trim() || '',
    first_filing_at: row.querySelector('[name=first_filing_at]')?.value || '',
    first_judgment_served_at: row.querySelector('[name=first_judgment_served_at]')?.value || '',
    second_filing_at: row.querySelector('[name=second_filing_at]')?.value || '',
    second_judgment_effective_at: row.querySelector('[name=second_judgment_effective_at]')?.value || '',
  })).filter(n => Object.values(n).some(Boolean));
}
function readCaseNumberShowSelection() {
  return [...document.querySelectorAll('[data-case-number-row]')]
    .map(row => {
      const n = {
        number_type: row.querySelector('[name=number_type]')?.value.trim() || '',
        case_no: row.querySelector('[name=case_no]')?.value.trim() || '',
        court: row.querySelector('[name=court]')?.value.trim() || '',
      };
      return { key: caseNumberDisplayKey(n), filled: Boolean(n.number_type || n.case_no || n.court), show: row.querySelector('[data-case-no-show]')?.checked };
    })
    .filter(e => e.show && e.filled)
    .map(e => e.key);
}
function updatedCaseFromSection(section) {
  const item = state.editing.item;
  const next = { ...item, parties: [...(item.parties || [])], case_numbers: [...(item.case_numbers || [])] };
  const root = document.querySelector(`[data-case-inline-section="${section}"]`);
  if (section === 'basic') {
    next.title = root?.querySelector('[name=title]')?.value.trim() || '';
    next.case_type = root?.querySelector('[name=case_type]')?.value.trim() || '';
    next.current_stage = root?.querySelector('[name=current_stage]')?.value.trim() || '';
    if (!next.title) {
      const suggestion = buildCaseNameSuggestion(next.case_type);
      if (suggestion) next.title = suggestion;
    }
  } else if (section === 'parties') next.parties = readInlineParties(section);
  else if (section === 'numbers') {
    next.case_numbers = readInlineCaseNumbers();
    if (!String(next.current_stage || '').trim()) {
      next.current_stage = next.case_numbers.find(n => n.number_type)?.number_type || '';
    }
    saveCaseNumbersSelection(state.editing.item.id || 'new', readCaseNumberShowSelection());
  }
  else if (section === 'contacts') {
    const contacts = collectContactGroups();
    next.court_contact = serializeContactGroups(contacts, 'court');
    next.party_contact = serializeContactGroups(contacts, 'party');
    next.memo = root?.querySelector('[name=memo]')?.value.trim() || '';
    if (Number(state.editing?.seriesDetailMappingSeriesId || 0)) next.detail_contact_selection = readContactDisplaySelections();
  }
  return next;
}
function caseSavePayload(item) {
  const payload = {
    title: item.title || '未命名案件', case_type: item.case_type || '', current_stage: item.current_stage || '',
    court_contact: item.court_contact || '', party_contact: item.party_contact || '', memo: item.memo || '',
    parties: item.parties || [], case_numbers: item.case_numbers || []
  };
  if (Number(state.editing?.seriesDetailMappingSeriesId || 0)) {
    payload.series_code = item.series_code || '';
    payload.display_name = item.display_name || item.series_display_name || item.title || '';
    payload.detail_contact_selection = normalizeDetailContactSelection(item.detail_contact_selection);
  }
  return payload;
}
function caseDetailSaveUrl(caseId) {
  const seriesId = Number(state.editing?.seriesDetailMappingSeriesId || 0);
  return seriesId
    ? `/api/case-manager/series/${seriesId}/children/${Number(caseId)}`
    : `/api/case-manager/cases/${Number(caseId)}`;
}
async function saveCaseSection(section) {
  const next = updatedCaseFromSection(section);
  const original = state.editing.item;
  if (section === 'basic' && !next.title) return toast('请先在“客户信息/当事人”填写当事人并选择案由，或直接填写案件名称');
  try {
    if (section === 'clients') {
      const clients = readMasterClients();
      const profiles = [];
      for (const client of clients) {
        const existing = (original.client_profiles || []).find(profile => Number(profile.id) === Number(client.id));
        const firstContact = client.contacts?.[0] || {};
        const full = {
          ...(existing || {}), ...client,
          contacts: [firstContact, ...((existing?.contacts || []).slice(1))]
            .filter(contact => contact?.name || contact?.phone)
        };
        const savedClient = await api(client.id ? `/api/case-manager/clients/${client.id}` : '/api/case-manager/clients', {
          method: client.id ? 'PUT' : 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(full)
        });
        profiles.push(savedClient);
      }
      if (!profiles.length) return toast('请先填写客户名称后再保存');
      next.client_profiles = profiles;
      const savedClientParties = (original.parties || []).filter(p => p.party_group === 'client');
      next.parties = [
        ...profiles.map(profile => {
          const prev = savedClientParties.find(p => p.name === profile.name);
          return { party_group: 'client', role: prev?.role || '委托人', name: profile.name, credit_code: profile.identity_code || '' };
        }),
        ...(original.parties || []).filter(party => party.party_group !== 'client')
      ];
      state.editing.item = next;
      if (original.id) {
        const payload = caseSavePayload(next);
        const saved = await api(caseDetailSaveUrl(original.id), {
          method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload)
        });
        const seriesId = Number(state.editing?.seriesDetailMappingSeriesId || 0);
        state.editing.item = seriesId ? applySeriesDetailMappings(saved, state.seriesWorkspace) : saved;
        toast('已保存');
        if (saved.id) rememberOpenCaseDetail(state.editing.item, seriesId);
        renderOpenCaseDetail();
        if (seriesId) await reloadSeriesWorkspace(); else await refreshAll(false);
      } else {
        state.editing.inlineSection = '';
        renderOpenCaseDetail();
        toast('客户已保存；请到“基础信息”填写案由，案件名称会自动生成');
      }
      return;
    }
    if (!original.id && !next.title) {
      state.editing.item = next;
      state.editing.inlineSection = '';
      renderOpenCaseDetail();
      return;
    }
    const payload = caseSavePayload(next);
    let saved;
    if (isOfflineReadonly()) {
      const id = original.id || makeTempCaseId();
      enqueueCaseOp({ action: 'upsert', id, payload });
      saved = { ...next, id };
      toast('案件已离线保存，联网后自动同步');
    } else {
      saved = await api(original.id ? caseDetailSaveUrl(original.id) : '/api/case-manager/cases', {
        method: original.id ? 'PUT' : 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload)
      });
      toast('已保存');
    }
    const seriesId = Number(state.editing?.seriesDetailMappingSeriesId || 0);
    state.editing.item = seriesId ? applySeriesDetailMappings(saved, state.seriesWorkspace) : saved;
    state.editing.isNew = false;
    state.editing.inlineSection = '';
    if (saved.id) rememberOpenCaseDetail(state.editing.item, seriesId);
    renderOpenCaseDetail();
    if (seriesId) await reloadSeriesWorkspace(); else await refreshAll(false);
  } catch (e) { toast(e.message || '保存失败'); }
}

// 所有案件详情视图共用这一套字段标记，确保复制内容为浏览器可见的纯文本。
const DETAIL_COPYABLE_SELECTOR = [
  '.detail-list dd',
  '.record-fields dd',
  '.detail-table-wrap td',
  '.mini-table-wrap td',
  '.contact-card-content',
  '.audit-value',
  '.case-folder-name',
  '.case-folder-status',
  '.case-folder-path summary',
  '.case-folder-path code',
  '.co-expand-field dd'
].join(',');

function makeDetailFieldsCopyable(root) {
  if (!root) return;
  root.querySelectorAll(DETAIL_COPYABLE_SELECTOR).forEach(field => {
    if (field.closest('button, a, input, textarea, select')) return;
    field.dataset.copyField = 'true';
    field.tabIndex = 0;
    field.setAttribute('role', 'button');
    field.setAttribute('aria-label', '复制字段内容');
    field.title = '单击复制';
  });
}

function plainTextFromDetailField(field) {
  return String(field?.innerText || field?.textContent || '')
    .replace(/\u00a0/g, ' ')
    .replace(/\r\n/g, '\n')
    .trim();
}

async function copyPlainText(text) {
  if (!text) return false;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (_) {}
  const input = document.createElement('textarea');
  input.value = text;
  input.setAttribute('readonly', '');
  input.style.cssText = 'position:fixed;opacity:0;pointer-events:none';
  document.body.appendChild(input);
  input.select();
  const copied = document.execCommand('copy');
  input.remove();
  return copied;
}

function copyDetailField(field) {
  const selectedText = window.getSelection?.().toString();
  if (selectedText) return;
  const text = plainTextFromDetailField(field);
  if (!text) return;
  copyPlainText(text).then(copied => {
    if (!copied) return toast('复制失败，请检查浏览器权限');
    field.classList.add('copied');
    window.setTimeout(() => field.classList.remove('copied'), 700);
    toast('已复制');
  });
}
function classifyCourtContact(value) {
  const sections = { judicial: [], enforcement: [], investigation: [], other: [] };
  const text = String(value || '').trim();
  if (!text) return sections;
  const headingTypes = {
    '审判机关与承办人员': 'judicial',
    '执行、保全与联调': 'enforcement',
    '调查取证与办事窗口': 'investigation',
    '其他机关联系信息': 'other',
  };
  const headingPattern = /【(审判机关与承办人员|执行、保全与联调|调查取证与办事窗口|其他机关联系信息)】/g;
  let explicitType = '';
  const normalized = text.replace(headingPattern, (_, heading) => `\n\n__CONTACT_SECTION_${headingTypes[heading]}__\n\n`);
  const blocks = normalized.split(/\n\s*\n|(?:—{3,}|_{3,})/).map(part => part.trim()).filter(Boolean);
  blocks.forEach(block => {
    const marker = block.match(/^__CONTACT_SECTION_(judicial|enforcement|investigation|other)__$/);
    if (marker) {
      explicitType = marker[1];
      return;
    }
    let type = explicitType || 'other';
    if (!explicitType) {
      if (/调查令|档案馆|档案窗口|自然资源/.test(block)) type = 'investigation';
      else if (/执行|执保|财产保全|财保|查封|冻结|复议|诉前联调/.test(block)) type = 'enforcement';
      else if (/法院|法官|书记员|仲裁|审判|一审|二审|中院/.test(block)) type = 'judicial';
    }
    sections[type].push(block);
  });
  return sections;
}
function contactCard(title, value, type) {
  const content = String(value || '').trim();
  const highlighted = content ? esc(content).replace(/(?<!\d)(?:1\d{2}[ -]?\d{4}[ -]?\d{4}|0\d{2,3}[ -]?\d{7,8}|\d{8})(?!\d)/g, match => `<span class="contact-phone">${match}</span>`) : '';
  return `<article class="contact-card ${type}"><div class="contact-card-title">${esc(title)}</div><div class="contact-card-content">${highlighted || '<span class="contact-empty">暂无记录</span>'}</div></article>`;
}
function caseContactHub(item, editable = false) {
  const contactData = seriesPublicContactData(item);
  const groups = parseContactGroups(contactData);
  // 系列案主表映射出的联系人不是新的联系人分组；它们默认归入第一个
  // “联调/诉讼/仲裁阶段”分组，并沿用普通联系人卡片的展示方式。
  const mappedContacts = (item._seriesDetailMappedContacts || []).filter(contactGroupHasData);
  if (mappedContacts.length) groups.litigation = [...mappedContacts, ...(groups.litigation || [])];
  const orderedCategories = CONTACT_CATEGORIES.map((category, index) => ({
    category,
    index,
    filled: (groups[category.key] || []).some(contactGroupHasData),
  })).sort((a, b) => Number(b.filled) - Number(a.filled) || a.index - b.index);
  const content = `<div class="contact-hub"><div class="contact-hub-grid">
    ${orderedCategories.map(({category}) => contactDetailCard(category, groups[category.key])).join('')}
    ${contactCard('案件备忘', contactData.memo, 'memo')}
  </div></div>`;
  return editable ? caseDetailSection('联系与备忘', 'contacts', item, content) : `<section class="detail-section contact-section"><h3>联系与备忘</h3>${content}</section>`;
}
async function loadHearingContactSection(item) {
  const host = $('hearingContactSection');
  if (!host) return;
  const token = host.dataset.contactToken || '';
  const fallback = () => {
    host.innerHTML = detailSection('联系方式', [
      ['裁判机关经办人联系方式', item.court_contact, true],
      ['委托方及对方联系方式', item.party_contact, true]
    ]);
    makeDetailFieldsCopyable(host);
  };
  const caseId = Number(item.case_id || 0);
  if (!caseId) { fallback(); return; }
  try {
    const caseDetail = isOfflineReadonly() ? offlineCaseById(caseId) : await api(`/api/case-manager/cases?case_id=${caseId}`);
    if (!caseDetail) throw new Error('未找到对应案件');
    let html;
    if (caseDetail.case_kind === 'series_child') {
      const seriesId = Number(caseDetail.parent_series_id || item.series_id || 0);
      if (!seriesId) throw new Error('未找到所属系列案件');
      const seriesData = isOfflineReadonly() ? offlineSeriesData(seriesId) : await api(`/api/case-manager/series/${seriesId}`);
      html = hearingContactSectionHtml(caseDetail, seriesData);
    } else if (caseDetail.case_kind === 'series') {
      const seriesData = isOfflineReadonly() ? offlineSeriesData(caseId) : await api(`/api/case-manager/series/${caseId}`);
      html = caseContactHub(seriesPublicContactData(seriesData), false);
    } else {
      html = caseContactHub(caseDetail, false);
    }
    const current = $('hearingContactSection');
    if (!current || current.dataset.contactToken !== token) return;
    current.innerHTML = html;
    makeDetailFieldsCopyable(current);
  } catch (e) {
    fallback();
  }
}
function hearingContactSectionHtml(caseDetail, seriesData) {
  const columns = (seriesData?.profile?.table_columns?.length ? seriesData.profile.table_columns : SERIES_DEFAULT_COLUMNS).filter(column => column.hidden !== true);
  const rawChild = (seriesData?.children || []).find(item => Number(item.id) === Number(caseDetail.id));
  const child = rawChild ? applySeriesDetailMappings(rawChild, seriesData) : null;
  const contacts = child ? seriesChildContactGroups(child, columns, String(seriesData?.title || '')) : [];
  if (!contacts.length) {
    return `<section class="detail-section contact-section"><h3>联系与备忘</h3><span class="contact-empty">子案信息主表中暂无被识别为联系人的单元格</span></section>`;
  }
  const content = `<div class="contact-hub"><div class="contact-hub-grid">${contacts.map(({label, group}) => seriesChildContactCard(label, group)).join('')}</div></div>`;
  return `<section class="detail-section contact-section"><h3>联系与备忘</h3>${content}</section>`;
}
async function loadSeriesGroupChildContacts(event) {
  const seriesId = Number(event.series_id || 0);
  if (!seriesId) return;
  const entries = (event.group_items || []).filter(entry => Number(entry.case_id || 0) > 0);
  if (!entries.length) return;
  const hostBody = $('drawerBody');
  try {
    const seriesData = isOfflineReadonly() ? offlineSeriesData(seriesId) : await api(`/api/case-manager/series/${seriesId}`);
    if (!seriesData) return;
    const columns = (seriesData.profile?.table_columns?.length ? seriesData.profile.table_columns : SERIES_DEFAULT_COLUMNS).filter(column => column.hidden !== true);
    const childById = new Map((seriesData.children || []).map(child => [Number(child.id), child]));
    let filled = 0;
    entries.forEach(entry => {
      const slot = document.querySelector(`.series-group-contact-slot[data-slot-token="calendar-series-${seriesId}-${Number(entry.case_id || 0)}"]`);
      if (!slot || slot.closest('.drawer-body') !== hostBody) return;
      const rawChild = childById.get(Number(entry.case_id || 0));
      const child = rawChild ? applySeriesDetailMappings(rawChild, seriesData) : null;
      const contacts = child ? seriesChildContactGroups(child, columns, String(seriesData.title || '')) : [];
      if (!contacts.length) return;
      slot.innerHTML = `<div class="contact-hub"><div class="contact-hub-grid">${contacts.map(({label, group}) => seriesChildContactCard(label, group)).join('')}</div></div>`;
      filled += 1;
    });
    if (filled) makeDetailFieldsCopyable(hostBody);
  } catch (e) { /* 加载失败时保持汇总原状 */ }
}
function seriesChildContactGroups(child, columns, seriesTitle) {
  const contacts = [];
  (columns || []).forEach(column => {
    const raw = String(seriesCellValue(child, column.key) ?? '');
    const phone = seriesExtractPhone(raw);
    const email = seriesExtractEmail(raw);
    if (!phone && !email) return;
    const name = seriesContactNameFromCell(raw) || seriesContactNameForRow(child, columns) || phone || email;
    const caseNumber = String(seriesCellValue(child, 'case_no') || child.case_no || '').split(/\r?\n/).map(value => value.trim()).find(Boolean) || '';
    contacts.push({
      label: String(column.label || column.key || '联系人'),
      group: {
        roleType: '联系人',
        name,
        phone,
        email,
        caseNumber,
        notes: `系列案「${seriesTitle}」${column.label || ''}列`,
      },
    });
  });
  return contacts;
}
function seriesChildContactCard(label, group) {
  const encoded = encodeURIComponent(JSON.stringify(group)).replace(/'/g, '%27');
  const text = [
    group.name && `${group.roleType || '联系人'}：${group.name}`,
    group.phone && `电话：${group.phone}`,
    group.email && `邮箱：${group.email}`,
    group.caseNumber && `案号：${group.caseNumber}`,
  ].filter(Boolean).join('\n');
  const highlighted = esc(text).replace(/(?<!\d)(?:1\d{2}[ -]?\d{4}[ -]?\d{4}|0\d{2,3}[ -]?\d{7,8}|\d{8})(?!\d)/g, match => `<span class="contact-phone">${match}</span>`);
  return `<article class="contact-card"><div class="contact-card-title">${esc(label)}</div><div class="contact-detail-groups"><div class="contact-detail-group"><div class="contact-card-content">${highlighted}</div><button class="btn contact-detail-sync contact-sync-icon" type="button" aria-label="同步通讯录" title="同步到 iCloud 通讯录" onclick="syncContactToICloud(this, '${encoded}')">${contactSyncIcon()}</button></div></div></article>`;
}
function contactSyncIcon() {
  return '<svg width="16" height="16" viewBox="0 0 1024 1024" fill="none" aria-hidden="true"><path d="M452.923077 630.153846a39.384615 39.384615 0 0 1 39.108923 34.776616L492.307692 669.538462v196.923076a39.384615 39.384615 0 0 1-57.422769 35.052308l-3.820308-2.284308-59.076923-39.384615a39.384615 39.384615 0 0 1 39.739077-67.859692l1.811693 1.024V669.538462a39.384615 39.384615 0 0 1 34.776615-39.108924L452.923077 630.153846z m136.192 4.450462l3.820308 2.244923 59.076923 39.384615a39.384615 39.384615 0 0 1-39.739077 67.859692l-1.811693-1.024v123.47077a39.384615 39.384615 0 0 1-34.776615 39.108923l-4.608 0.275692a39.384615 39.384615 0 0 1-39.108923-34.816l-0.275692-4.568615v-196.923077a39.384615 39.384615 0 0 1 57.422769-35.052308zM512 118.153846a354.658462 354.658462 0 0 1 338.904615 250.289231l3.111385 10.909538 6.695385 3.465847a236.386462 236.386462 0 0 1 123.667692 198.183384L984.615385 590.769231a236.465231 236.465231 0 0 1-218.112 235.598769l-8.822154 0.512-8.546462 0.196923a39.384615 39.384615 0 0 1-6.262154-78.375385l4.608-0.393846 7.68-0.157538a157.538462 157.538462 0 0 0 50.76677-304.088616 39.384615 39.384615 0 0 1-24.14277-28.553846 275.810462 275.810462 0 0 0-539.529846 0 39.384615 39.384615 0 0 1-24.142769 28.553846A157.577846 157.577846 0 0 0 275.692308 748.307692a39.384615 39.384615 0 0 1 0 78.769231A236.307692 236.307692 0 0 1 163.328 382.818462l6.616615-3.426462 0.196923-0.630154a354.579692 354.579692 0 0 1 331.145847-260.450461L512 118.153846z" fill="currentColor"/></svg>';
}
function contactDetailCard(category, groups = []) {
  const filled = groups.filter(contactGroupHasData);
  const content = filled.length ? filled.map(group => {
    const encoded = encodeURIComponent(JSON.stringify(group)).replace(/'/g, '%27');
    const text = formatContactGroups([group]);
    const highlighted = esc(text).replace(/(?<!\d)(?:1\d{2}[ -]?\d{4}[ -]?\d{4}|0\d{2,3}[ -]?\d{7,8}|\d{8})(?!\d)/g, match => `<span class="contact-phone">${match}</span>`);
    const disabled = group.name ? '' : 'disabled title="请先在编辑状态补充姓名"';
    return `<div class="contact-detail-group"><div class="contact-card-content">${highlighted}</div><button class="btn contact-detail-sync contact-sync-icon" type="button" ${disabled} aria-label="同步通讯录" title="同步通讯录" onclick="syncContactToICloud(this, '${encoded}')">${contactSyncIcon()}</button></div>`;
  }).join('') : '<span class="contact-empty">暂无记录</span>';
  return `<article class="contact-card ${category.key}"><div class="contact-card-title">${esc(category.label)}</div><div class="contact-detail-groups">${content}</div></article>`;
}
function formatContactGroups(groups = []) {
  return groups.map(group => [
    group.name && `${group.roleType || '联系人'}：${group.name}`,
    group.phone && `电话：${group.phone}`,
    group.email && `邮箱：${group.email}`,
    group.notes && `备注：${group.notes}`,
  ].filter(Boolean).join('\n')).filter(Boolean).join('\n\n');
}
function auditActionLabel(action) {
  return ({
    created: '创建',
    updated: '修改',
    deleted: '删除',
    archived: '结案',
    restored: '恢复',
    imported: '导入',
    synced: '同步'
  })[action] || '变更';
}
function formatAuditValue(value) {
  const text = String(value || '').trim();
  if (!text) return '';
  if (!(text.startsWith('[') || text.startsWith('{'))) return text;
  try {
    const parsed = JSON.parse(text);
    if (!Array.isArray(parsed)) return text;
    return parsed.map(item => {
      if (!item || typeof item !== 'object') return String(item || '');
      if ('party_group' in item) {
        const group = item.party_group === 'client' ? '委托人' : '其他当事人';
        return [group, item.role, item.name, item.credit_code].filter(Boolean).join(' · ');
      }
      if ('case_no' in item) {
        const dates = [
          item.first_filing_at && `一审立案 ${item.first_filing_at}`,
          item.first_judgment_served_at && `一审送达 ${item.first_judgment_served_at}`,
          item.second_filing_at && `二审立案 ${item.second_filing_at}`,
          item.second_judgment_effective_at && `二审生效 ${item.second_judgment_effective_at}`
        ].filter(Boolean).join('；');
        return [[item.number_type, item.case_no, item.court].filter(Boolean).join(' · '), dates].filter(Boolean).join('；');
      }
      return Object.values(item).filter(Boolean).join(' · ');
    }).filter(Boolean).join('\n');
  } catch (_) {
    return text;
  }
}
function auditDiffHtml(before, after) {
  if (!before && !after) return '';
  if (!before) {
    return `<div class="audit-value after"><div class="audit-diff-label">新值 · 新增</div><span class="audit-inline-added">${esc(after)}</span></div>`;
  }
  if (!after) {
    return `<div class="audit-value after"><div class="audit-diff-label">新值 · 已删除</div><span class="audit-inline-removed">${esc(before)}</span><span class="audit-delete-note">已删除</span></div>`;
  }
  const parts = auditTextDiff(before, after);
  const content = parts.map(part => {
    if (part.type === 'removed') return `<span class="audit-inline-removed">${esc(part.text)}</span>`;
    if (part.type === 'added') return `<span class="audit-inline-added">${esc(part.text)}</span>`;
    return esc(part.text);
  }).join('');
  return `<div class="audit-value diff"><div class="audit-diff-label">修改后 · 仅高亮差异</div>${content}</div>`;
}
function auditTextDiff(before, after) {
  const oldChars = Array.from(before);
  const newChars = Array.from(after);
  let prefix = 0;
  const limit = Math.min(oldChars.length, newChars.length);
  while (prefix < limit && oldChars[prefix] === newChars[prefix]) prefix += 1;
  let suffix = 0;
  while (
    suffix < oldChars.length - prefix &&
    suffix < newChars.length - prefix &&
    oldChars[oldChars.length - 1 - suffix] === newChars[newChars.length - 1 - suffix]
  ) suffix += 1;
  const oldMiddle = oldChars.slice(prefix, oldChars.length - suffix);
  const newMiddle = newChars.slice(prefix, newChars.length - suffix);
  const parts = [];
  const append = (type, chars) => {
    if (!chars.length) return;
    const text = Array.isArray(chars) ? chars.join('') : chars;
    const previous = parts[parts.length - 1];
    if (previous && previous.type === type) previous.text += text;
    else parts.push({ type, text });
  };
  append('same', oldChars.slice(0, prefix));

  // A character-level LCS keeps unchanged text visible when a user inserts or
  // removes a small fragment in the middle of a multi-line value.
  if (oldMiddle.length * newMiddle.length <= 2000000) {
    const rows = Array.from({ length: oldMiddle.length + 1 }, () => new Uint32Array(newMiddle.length + 1));
    for (let i = oldMiddle.length - 1; i >= 0; i -= 1) {
      for (let j = newMiddle.length - 1; j >= 0; j -= 1) {
        rows[i][j] = oldMiddle[i] === newMiddle[j]
          ? rows[i + 1][j + 1] + 1
          : Math.max(rows[i + 1][j], rows[i][j + 1]);
      }
    }
    let i = 0;
    let j = 0;
    while (i < oldMiddle.length && j < newMiddle.length) {
      if (oldMiddle[i] === newMiddle[j]) {
        append('same', oldMiddle[i]);
        i += 1;
        j += 1;
      } else if (rows[i + 1][j] >= rows[i][j + 1]) {
        append('removed', oldMiddle[i]);
        i += 1;
      } else {
        append('added', newMiddle[j]);
        j += 1;
      }
    }
    append('removed', oldMiddle.slice(i));
    append('added', newMiddle.slice(j));
  } else {
    // Avoid excessive memory use for exceptionally large, completely changed values.
    append('removed', oldMiddle);
    append('added', newMiddle);
  }
  if (suffix) append('same', oldChars.slice(oldChars.length - suffix));
  return parts;
}
function auditLogPanel(logs) {
  const cards = logs.map(log => {
    const changes = (log.changes || []).map(change => {
      const before = formatAuditValue(change.before);
      const after = formatAuditValue(change.after);
      return `<div class="audit-change">
        <div class="audit-field">${esc(change.label || change.field || '字段')}</div>
        ${auditDiffHtml(before, after)}
      </div>`;
    }).join('');
    return `<article class="audit-card">
      <div class="audit-meta"><span class="audit-actor">${esc(log.actor || '本机用户')}</span><span class="audit-time">${esc(fmt(log.created_at))}</span></div>
      <div class="audit-title"><div class="audit-summary">${esc(log.summary || `${log.entity_name || '记录'}发生变更`)}</div><span class="audit-action ${esc(log.action || 'updated')}">${esc(auditActionLabel(log.action))}</span></div>
      ${changes}
    </article>`;
  }).join('');
  return `<aside class="audit-panel">
    <div class="audit-panel-head"><h3>数据日志</h3><span>${logs.length} 条记录</span></div>
    <div class="audit-list">${cards || '<div class="audit-empty">暂无数据日志</div>'}</div>
  </aside>`;
}
function customerRows(item) {
  const profiles = item.client_profiles || [];
  const clients = profiles.length
    ? profiles.map(profile => [profile.name, profile.identity_code || ''])
    : (item.parties || []).filter(p => p.party_group === 'client' && p.name).map(p => [p.name, p.credit_code || '']);
  return clients.length ? clients : [];
}
function caseNoCourtRows(caseNo, court) {
  const caseNos = String(caseNo || '').split('\n').map(x => x.trim()).filter(Boolean);
  const courts = String(court || '').split('\n').map(x => x.trim()).filter(Boolean);
  const count = Math.max(caseNos.length, courts.length);
  return Array.from({ length: count }, (_, i) => [caseNos[i] || '', courts[i] || '']);
}
function formatCaseNoCourt(caseNo, court) {
  const rows = caseNoCourtRows(caseNo, court);
  return rows.map(([no, org]) => [no, org].filter(Boolean).join('　')).join('\n');
}
function miniTable(title, headers, rows) {
  if (!rows.length) return `<section class="detail-section"><h3>${esc(title)}</h3><div class="empty">暂无数据</div></section>`;
  const tableClass = title === '案号' ? 'mini-table case-number-mini' : 'mini-table';
  return `<section class="detail-section"><h3>${esc(title)}</h3><div class="detail-table-wrap"><table class="${tableClass}"><thead><tr>${headers.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(r => `<tr>${r.map(c => `<td>${esc(c || '')}</td>`).join('')}</tr>`).join('')}</tbody></table></div></section>`;
}
function recordList(title, records, heading, fields) {
  const toggle = `<button class="record-section-toggle" type="button" aria-expanded="false" onclick="toggleDetailRecordSection(this)"><span>${esc(title)}<span class="record-section-count">${records.length}</span></span></button>`;
  if (!records.length) return `<section class="detail-section record-section collapsed">${toggle}<div class="empty compact">暂无数据</div></section>`;
  return `<section class="detail-section record-section collapsed">${toggle}<div class="record-list">${records.map((record, index) => {
    const head = heading(record) || `${title} ${index + 1}`;
    const matterTab = {'待办事项':'todos','开庭提醒':'hearings','财产保全':'preservations','上诉/异议期':'appeals'}[title];
    const localAction = matterTab ? `<button class="btn" type="button" onclick="openMatterLocalFiles('${matterTab}',${Number(record.id)},'${encodeMobileRecord(record)}',this)">本地文件</button>` : '';
    return `<article class="record-card">
      <div class="record-card-head"><span>${index + 1}. ${esc(head)}</span>${localAction}</div>
      <dl class="record-fields">${fields.map(([label, getter, full]) => {
        const value = typeof getter === 'function' ? getter(record) : record[getter];
        const isFull = full || String(value || '').length > 90 || String(value || '').includes('\n');
        return `<dt class="${isFull ? 'full-label' : ''}">${esc(label)}</dt><dd class="${isFull ? 'full-value' : ''}">${esc(value || '')}</dd>`;
      }).join('')}</dl>
    </article>`;
  }).join('')}</div></section>`;
}
function toggleDetailRecordSection(button) {
  const section = button.closest('.record-section');
  if (!section) return;
  const collapsed = section.classList.toggle('collapsed');
  button.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
}

async function openEditor(tab, item = null) {
  // 案件不再存在整页编辑模式：所有入口统一回到详情页的分区就地编辑。
  if (tab === 'cases') {
    if (item?.id) return openDetail('cases', item.id);
    return openNewCaseDetail();
  }
  if (isOfflineReadonly() && tab !== 'cases') {
    requireOnlineAction();
    return;
  }
  state.editing = { tab, item, returnToDetail: false };
  $('drawerTitle').textContent = `${item ? '编辑' : '新增'}${tabMeta[tab]?.label || ''}`;
  $('drawerFoot').innerHTML = `
    <button class="btn" onclick="closeEditor()">取消</button>
    <button class="btn primary" onclick="saveEditor()">保存</button>
  `;
  if (tab === 'todos') {
  } else if (tab === 'hearings') {
    await loadCourts();
  } else if (tab === 'preservations') {
    await loadPreservationTypes();
  } else if (tab === 'appeals') {
    await loadCourts();
  }
  $('drawerBody').innerHTML = editorHtml(tab, item || {});
  attachRelatedCasePicker();
  $('drawerMask').classList.add('show');
  $('drawer').classList.add('show');
  $('drawer').classList.remove('detail-mode');
  $('drawer').classList.add('edit-wide');
  notifyCaseManagerContext(
    item?.title || `${item ? '编辑' : '新增'}${tabMeta[tab]?.label || '记录'}`,
    currentCaseManagerPageLabel()
  );
}
function closeEditor() {
  ApexCasePicker.closeAll();
  if (state.contractWorkspace?.caseId) {
    return returnToContractCase();
  }
  closeSeriesSide();
  closeOptionManager();
  $('drawerMask').classList.remove('show');
  $('drawer').classList.remove('show');
  $('drawer').classList.remove('detail-mode');
  $('drawer').classList.remove('edit-wide');
  $('drawer').classList.remove('case-research-active');
  setSeriesChildDetailOverlay(false);
  clearContractWorkspaceChrome();
  if (state.editing?.mode === 'detail' && state.editing?.tab === 'cases') forgetOpenCaseDetail();
  state.editing = null;
  resetCaseResearchWorkspace();
  renderCaseResearchFloatHost();
  $('drawerFoot').innerHTML = `
    <button class="btn" onclick="closeEditor()">取消</button>
    <button class="btn primary" onclick="saveEditor()">保存</button>
  `;
  notifyCaseManagerContext(currentCaseManagerPageLabel());
}

function clearContractWorkspaceChrome() {
  $('drawer')?.classList.remove('contract-workspace-mode');
  if ($('drawerHeadActions')) $('drawerHeadActions').innerHTML = '';
}

async function returnToContractCase() {
  const caseId = Number(state.contractWorkspace?.caseId || 0);
  if (!caseId) return closeEditor();
  state.contractWorkspace = null;
  clearContractWorkspaceChrome();
  await openDetail('cases', caseId);
}
const MANAGED_OPTION_META = {
  case_type: { label: '案件类型', unit: '个案件' },
  current_stage: { label: '当前阶段', unit: '个案件' },
  opponent: { label: '对方当事人名称', unit: '个案件' },
};
async function openOptionManager(kind) {
  if (isOfflineReadonly()) {
    requireOnlineAction();
    return;
  }
  const meta = MANAGED_OPTION_META[kind];
  if (!meta) return;
  hideLookupResults();
  state.managedOptionKind = kind;
  state.managedOptionQuery = '';
  $('optionManagerTitle').textContent = `管理${meta.label}`;
  $('optionManagerSubtitle').textContent = kind === 'opponent'
    ? '改名会同步更新相关案件；删除会移除相关案件中的该对方当事人记录'
    : '改名会同步更新相关案件；删除会清空相关案件中的该字段';
  $('optionManagerSearch').value = '';
  $('optionManagerSearch').placeholder = `搜索${meta.label}`;
  $('optionManagerList').innerHTML = '<div class="empty">加载中...</div>';
  $('optionManager').classList.add('show');
  $('optionManager').setAttribute('aria-hidden', 'false');
  try {
    const data = await api(`/api/case-manager/managed-options/${kind}`);
    state.managedOptions = data.items || [];
    renderManagedOptions();
    setTimeout(() => $('optionManagerSearch')?.focus(), 0);
  } catch (e) {
    closeOptionManager();
    toast(e.message);
  }
}
function closeOptionManager() {
  const manager = $('optionManager');
  if (!manager) return;
  manager.classList.remove('show');
  manager.setAttribute('aria-hidden', 'true');
  state.managedOptionKind = '';
  state.managedOptions = [];
  state.managedOptionQuery = '';
}
function filterManagedOptions(value) {
  state.managedOptionQuery = String(value || '').trim();
  renderManagedOptions();
}
function renderManagedOptions() {
  const q = state.managedOptionQuery;
  const items = (state.managedOptions || []).filter(item => !q || fuzzyIncludes(item.value, q));
  if (!items.length) {
    $('optionManagerList').innerHTML = `<div class="empty">${q ? '没有匹配结果' : '暂无可管理的数据'}</div>`;
    return;
  }
  $('optionManagerList').innerHTML = items.map((item, index) => `
    <div class="option-manager-row">
      <input class="input" id="managedOptionValue${index}" value="${esc(item.value)}" aria-label="名称">
      <span class="option-use-count">${item.use_count ? `已用于 ${esc(item.use_count)} 个案件` : '尚未使用'}</span>
      <div class="option-row-actions">
        <button class="btn" type="button" onclick="saveManagedOption(${index})">保存修改</button>
        <button class="btn danger" type="button" onclick="deleteManagedOption(${index})">删除</button>
      </div>
    </div>`).join('');
  $('optionManagerList')._visibleItems = items;
}
function updateOpenFormManagedValue(kind, oldValue, newValue) {
  if (!$('drawer')?.classList.contains('show')) return;
  if (kind === 'case_type' || kind === 'current_stage') {
    const input = $('drawerBody')?.querySelector(`[name="${kind}"]`);
    if (input && input.value.trim() === oldValue) input.value = newValue;
  } else {
    document.querySelectorAll('[data-inline-party-row]').forEach(row => {
      if (row.querySelector('[data-party-group]')?.value === 'client') return;
      const input = row.querySelector('[data-party-name]');
      if (input && input.value.trim() === oldValue) input.value = newValue;
    });
  }
}
async function reloadManagedOptionSources() {
  state.caseTypes = [];
  state.caseTypeQuery = '';
  state.caseStages = [];
  await Promise.all([loadCaseTypes(''), loadCaseStages()]);
  const caseTypeList = $('civilCauseList');
  if (caseTypeList) caseTypeList.innerHTML = caseTypeOptionsHtml();
}
async function saveManagedOption(index) {
  const item = $('optionManagerList')._visibleItems?.[index];
  const input = $(`managedOptionValue${index}`);
  const nextValue = input?.value.trim() || '';
  if (!item || !nextValue) {
    toast('名称不能为空');
    return;
  }
  if (nextValue === item.value) {
    toast('名称未发生变化');
    return;
  }
  const kind = state.managedOptionKind;
  const result = await api(`/api/case-manager/managed-options/${kind}`, {
    method: 'PUT', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ old_value: item.value, new_value: nextValue }),
  });
  updateOpenFormManagedValue(kind, item.value, nextValue);
  await reloadManagedOptionSources();
  toast(`已修改${result.updated ? `，同步更新 ${result.updated} 条记录` : ''}`);
  await openOptionManager(kind);
}
async function deleteManagedOption(index) {
  const item = $('optionManagerList')._visibleItems?.[index];
  if (!item) return;
  const kind = state.managedOptionKind;
  const label = MANAGED_OPTION_META[kind]?.label || '名称';
  const impact = item.use_count
    ? (kind === 'opponent'
      ? `这会从 ${item.use_count} 个案件中移除该对方当事人记录。`
      : `这会清空 ${item.use_count} 个案件中的“${label}”字段。`)
    : '这会将该名称从可选列表中移除。';
  if (!confirm(`确定删除“${item.value}”？\n${impact}\n此操作无法撤销。`)) return;
  const result = await api(`/api/case-manager/managed-options/${kind}`, {
    method: 'DELETE', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ value: item.value }),
  });
  updateOpenFormManagedValue(kind, item.value, '');
  await reloadManagedOptionSources();
  toast(`已删除${result.deleted ? `，更新 ${result.deleted} 条记录` : ''}`);
  await openOptionManager(kind);
}
function editorHtml(tab, item) {
  if (tab === 'todos') return `
    ${formSection('关联案件', '可搜索并带入既有案件信息', `<div class="form-grid">${casePickerField(item)}</div>`)}
    ${formSection('待办事项', '可选择循环频率；提醒会按设定时间显示在案件日历并同步到 iCloud 日历', `<div class="form-grid">
      ${field('todo_title','待办事项', item.todo_title || '', 'full')}
      ${field('remind_at','首次提醒时间', toInputDateTime(item.remind_at), '', 'datetime-local')}
      <div class="field"><label>重复提醒</label><select class="input" name="recurrence">
        ${[['','不重复'],['weekly','每星期'],['semimonthly','每半个月'],['monthly','每月'],['bimonthly','每两个月'],['quarterly','每三个月'],['semiannual','每半年']].map(([value,label]) => `<option value="${value}" ${String(item.recurrence || '') === value ? 'selected' : ''}>${label}</option>`).join('')}
      </select></div>
      ${area('notes','备注', item.notes, 'full tall', 'tall')}
    </div>`)}
  `;
  if (tab === 'hearings') return `
    ${hearingNoticeRecognizerHtml()}
    ${formSection('关联案件', '可搜索并带入既有案件信息', `<div class="form-grid">${casePickerField(item)}</div>`)}
    ${formSection('开庭信息', '时间、地点与案号', `<div class="form-grid">
      ${hearingTypeField(item.reminder_type || '一审开庭')}
      ${field('hearing_at','开庭时间', toInputDateTime(item.hearing_at), '', 'datetime-local')}
      ${field('location','开庭地点', item.location, 'full')}
      ${field('case_no','案号', item.case_no)}
      ${courtField('court','受理机构', item.court)}
      <datalist id="hearingTypeList">${hearingTypeOptions()}</datalist>
      <datalist id="courtList">${courtOptionsHtml()}</datalist>
    </div>`)}
    ${formSection('联系方式', '裁判机关与当事人联系信息', `<div class="form-grid">
      ${area('court_contact','裁判机关经办人联系方式', item.court_contact, 'full tall', 'xlarge')}
      ${area('party_contact','委托方及对方联系方式', item.party_contact, 'full tall', 'tall')}
    </div>`)}
  `;
  if (tab === 'preservations') return `
    ${preservationNoticeRecognizerHtml()}
    ${formSection('关联案件', '可搜索并带入既有案件信息', `<div class="form-grid">${casePickerField(item)}</div>`)}
    ${preservationEditorGroupsHtml(item)}
  `;
  return `
    ${formSection('关联案件', '可搜索并带入既有案件信息', `<div class="form-grid">${casePickerField(item)}</div>`)}
    ${formSection('期限信息', '上诉、异议、再审等期限', `<div class="form-grid">
      ${field('appeal_type','类型', item.appeal_type)}
      ${field('start_at','起算时间', dateOnly(item.start_at), '', 'date', `onchange="syncAppealDates('start_at')" oninput="syncAppealDates('start_at')"`) }
      ${field('period_days','期限（天）', item.period_days ?? '', '', 'number', `step="1" min="0" oninput="syncAppealDates('period_days')"`) }
      ${field('deadline_at','截止时间', dateOnly(item.deadline_at), '', 'date', `onchange="syncAppealDates('deadline_at')" oninput="syncAppealDates('deadline_at')"`) }
      ${field('case_no','案号', item.case_no)}
      ${courtField('court','受理机构', item.court)}
      <datalist id="courtList">${courtOptionsHtml()}</datalist>
    </div>`)}
    ${formSection('联系方式', '裁判机关与当事人联系信息', `<div class="form-grid">
      ${area('court_contact','裁判机关经办人联系方式', item.court_contact, 'full tall', 'xlarge')}
      ${area('party_contact','委托方及对方联系方式', item.party_contact, 'full tall', 'tall')}
    </div>`)}
  `;
}

function preservationEditorItems(item = {}) {
  const groups = Array.isArray(item.items) && item.items.length ? item.items
    : Array.isArray(item.preservations) && item.preservations.length ? item.preservations
      : [item];
  return groups.map(group => ({...group}));
}
function preservationEditorGroupsHtml(item = {}) {
  const groups = preservationEditorItems(item);
  return formSection('财产保全信息', '每项银行账户、房产、股权等保全财产分别记录，可继续添加', `
    <div id="preservationGroups" class="preservation-groups">
      ${groups.map((group, index) => preservationGroupHtml(group, index)).join('')}
    </div>
    <button class="btn preservation-add-group" type="button" onclick="addPreservationGroup()">＋ 添加一组保全信息</button>
  `);
}
function preservationGroupHtml(group = {}, index = 0) {
  return `<article class="preservation-group-card" data-preservation-group>
    <div class="preservation-group-head"><strong>第 ${index + 1} 组保全信息</strong><button class="btn preservation-remove-group" type="button" onclick="removePreservationGroup(this)">移除本组</button></div>
    <div class="form-grid">
      ${preservationTypeField(group.preservation_type || '')}
      ${field('start_at','起算时间', dateOnly(group.start_at), '', 'date', `onchange="syncPreservationGroupDates('start_at', this)" oninput="syncPreservationGroupDates('start_at', this)"`) }
      ${field('deadline_at','截止时间', dateOnly(group.deadline_at), '', 'date', `onchange="syncPreservationGroupDates('deadline_at', this)" oninput="syncPreservationGroupDates('deadline_at', this)"`) }
      ${field('period_years','期限（年）', group.period_years ?? '', '', 'number', `step="0.01" min="0" oninput="syncPreservationGroupDates('period_years', this)"`) }
      ${area('asset_content','保全财产内容', group.asset_content, 'full tall', 'tall')}
      ${area('notes','保全情况 / 备注', group.notes, 'full tall', 'tall')}
    </div>
  </article>`;
}
function refreshPreservationGroupHeadings() {
  document.querySelectorAll('[data-preservation-group]').forEach((group, index) => {
    const title = group.querySelector('.preservation-group-head strong');
    if (title) title.textContent = `第 ${index + 1} 组保全信息`;
  });
}
function addPreservationGroup(group = {}) {
  const box = $('preservationGroups');
  if (!box) return;
  box.insertAdjacentHTML('beforeend', preservationGroupHtml(group, box.querySelectorAll('[data-preservation-group]').length));
  refreshPreservationGroupHeadings();
}
function removePreservationGroup(button) {
  const box = $('preservationGroups');
  const groups = box?.querySelectorAll('[data-preservation-group]') || [];
  if (groups.length <= 1) return toast('至少保留一组财产保全信息');
  button.closest('[data-preservation-group]')?.remove();
  refreshPreservationGroupHeadings();
}
function collectPreservationGroups() {
  return [...document.querySelectorAll('[data-preservation-group]')].map(group => {
    const value = name => group.querySelector(`[name="${name}"]`)?.value?.trim() || '';
    const years = value('period_years');
    return {
      preservation_type: value('preservation_type'),
      start_at: value('start_at'),
      deadline_at: value('deadline_at'),
      period_years: years === '' ? null : Number(years),
      asset_content: value('asset_content'),
      notes: value('notes'),
    };
  }).filter(group => Object.values(group).some(value => value !== '' && value !== null));
}
function contactEditorHtml(item, options = {}) {
  const groups = parseContactGroups(item);
  const legacyMappedContacts = (item._seriesDetailMappedContacts || []).filter(contactGroupHasData);
  if (legacyMappedContacts.length) groups.litigation = [...legacyMappedContacts, ...(groups.litigation || []).filter(contactGroupHasData)];
  const displayColumns = options.includeDisplayColumns === false ? [] : seriesDetailContactDisplayColumns();
  const selection = normalizeDetailContactSelection(item.detail_contact_selection);
  const contactGroups = Object.values(groups).flat().filter(contactGroupHasData);
  const defaultGroupId = contactGroups.length === 1 ? contactGroupId(contactGroups[0]) : '';
  const publicClass = options.publicEditor ? ' series-public-contact-editor' : '';
  return `<div class="contact-hub contact-editor-hub${publicClass}"><div class="contact-editor-grid">
    ${displayColumns.length ? `<p class="case-edit-note contact-display-note">主表显示列可分别勾选要展示的联系人组；未勾选时不在主表显示。当前只有一组联系人时，每个映射列默认展示该组。</p>` : ''}
    ${CONTACT_CATEGORIES.map(category => contactCategoryHtml(category, groups[category.key], {displayColumns, selection, defaultGroupId})).join('')}
    <article class="contact-card memo contact-edit-memo"><div class="contact-card-title">案件备忘</div><textarea class="contact-edit-inline contact-edit-memo-input" name="memo" rows="${Math.max(1, String(item.memo || '').split('\n').length)}" placeholder="暂无备注" oninput="resizeContactNote(this)">${esc(item.memo || '')}</textarea></article>
  </div></div>`;
}
const CONTACT_CATEGORIES = [
  { key: 'litigation', label: '联调/诉讼/仲裁阶段', target: 'court' },
  { key: 'enforcement', label: '执行及执异阶段', target: 'court' },
  { key: 'retrial', label: '再审审查及再审阶段', target: 'court' },
  { key: 'investigation', label: '调查取证及其他', target: 'court' },
  { key: 'client', label: '委托方', target: 'party' },
  { key: 'opponent', label: '对方及其他方当事人', target: 'party' },
];
function emptyContactGroup(notes = '') {
  return { groupId: '', roleType: '联系人', name: '', phone: '', email: '', notes };
}
function newContactGroupId() {
  const random = Math.random().toString(36).slice(2, 9);
  return `contact_${Date.now().toString(36)}_${random}`;
}
function contactGroupId(group = {}) {
  return String(group.groupId || group.id || '').trim();
}
function fallbackContactGroupId(categoryKey, index, group = {}) {
  const source = [categoryKey, index, group.roleType, group.name, group.phone, group.email, group.notes].join('|');
  let hash = 0;
  for (const char of source) hash = ((hash << 5) - hash + char.charCodeAt(0)) | 0;
  return `contact_${categoryKey}_${Math.abs(hash).toString(36)}`;
}
function contactGroupHasData(group = {}) {
  return ['name','phone','email','notes'].some(key => String(group[key] || '').trim());
}
function parseStructuredContactText(value, allowedKeys) {
  const result = Object.fromEntries(allowedKeys.map(key => [key, []]));
  const labelToKey = {
    ...Object.fromEntries(CONTACT_CATEGORIES.map(category => [category.label, category.key])),
    '执行执异阶段': 'enforcement',
    '执行异议阶段': 'enforcement',
  };
  const headingPattern = /【(联调\/诉讼\/仲裁阶段|执行及执异阶段|执行执异阶段|执行异议阶段|再审审查及再审阶段|调查取证及其他|委托方|对方及其他方当事人)】/g;
  const text = String(value || '');
  const matches = [...text.matchAll(headingPattern)];
  matches.forEach((match, index) => {
    const key = labelToKey[match[1]];
    if (!result[key]) return;
    const start = match.index + match[0].length;
    const end = matches[index + 1]?.index ?? text.length;
    const section = text.slice(start, end).trim();
    const chunks = section.split(/\n?【联系人组】\n?/).map(part => part.trim()).filter(Boolean);
    result[key] = chunks.map(chunk => {
      const fields = emptyContactGroup();
      const lines = chunk.split('\n');
      const loose = [];
      let legacyContact = '';
      let legacyHandler = '';
      lines.forEach(line => {
        const field = line.match(/^(组ID|身份|姓名|联系人|承办人姓名|电话|邮箱|备注)：(.*)$/);
        if (!field) { if (line.trim()) loose.push(line.trim()); return; }
        const value = field[2].trim();
        if (field[1] === '组ID') fields.groupId = value;
        else if (field[1] === '身份') fields.roleType = value === '承办人' ? '承办人' : '联系人';
        else if (field[1] === '姓名') fields.name = value;
        else if (field[1] === '联系人') legacyContact = value;
        else if (field[1] === '承办人姓名') legacyHandler = value;
        else fields[{ '电话': 'phone', '邮箱': 'email', '备注': 'notes' }[field[1]]] = value;
      });
      if (!fields.name) {
        fields.roleType = legacyHandler ? '承办人' : '联系人';
        fields.name = legacyHandler || legacyContact;
        if (legacyHandler && legacyContact) loose.unshift(`联系人：${legacyContact}`);
      }
      if (loose.length) fields.notes = [fields.notes, ...loose].filter(Boolean).join('\n');
      return fields;
    });
  });
  return result;
}
function parseContactGroups(item) {
  const court = parseStructuredContactText(item.court_contact, ['litigation','enforcement','retrial','investigation']);
  const party = parseStructuredContactText(item.party_contact, ['client','opponent']);
  const hasStructuredCourt = Object.values(court).some(items => items.length);
  const hasStructuredParty = Object.values(party).some(items => items.length);
  if (!hasStructuredCourt && String(item.court_contact || '').trim()) {
    const legacy = classifyCourtContact(item.court_contact);
    court.litigation = [emptyContactGroup(legacy.judicial.join('\n\n'))];
    court.enforcement = [emptyContactGroup(legacy.enforcement.join('\n\n'))];
    court.investigation = [emptyContactGroup([...legacy.investigation, ...legacy.other].join('\n\n'))];
  }
  if (!hasStructuredParty && String(item.party_contact || '').trim()) party.client = [emptyContactGroup(item.party_contact.trim())];
  const merged = { ...court, ...party };
  CONTACT_CATEGORIES.forEach(category => {
    merged[category.key] = (merged[category.key] || []).filter(contactGroupHasData).map((group, index) => ({
      ...group,
      groupId: contactGroupId(group) || fallbackContactGroupId(category.key, index, group),
    }));
    if (!merged[category.key].length) merged[category.key] = [emptyContactGroup()];
  });
  return merged;
}
function normalizeDetailContactSelection(value) {
  if (typeof value === 'string') {
    try { value = JSON.parse(value || '{}'); } catch (_) { value = {}; }
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  return Object.fromEntries(Object.entries(value).map(([key, ids]) => {
    const values = Array.isArray(ids) ? ids : [ids];
    return [key, values.map(item => String(item || '').trim()).filter(Boolean)];
  }).filter(([key]) => String(key || '').trim()));
}
function seriesDetailContactDisplayColumns(seriesData = state.seriesWorkspace) {
  if (!Number(state.editing?.seriesDetailMappingSeriesId || 0)) return [];
  return seriesDetailMappings(seriesData).filter(mapping => mapping.target_key === 'contacts').map(mapping => {
    const column = seriesDetailMappingColumn(mapping.source_key, seriesData);
    return {key: mapping.source_key, label: column?.label || mapping.source_key};
  });
}
function contactGroupDisplayChecked(selection, columnKey, groupId, defaultGroupId) {
  const ids = selection[columnKey];
  return ids ? ids.includes(groupId) : groupId === defaultGroupId;
}
function contactDisplayOptionsHtml(group, options = {}) {
  const displayColumns = options.displayColumns || [];
  if (!displayColumns.length || (!contactGroupHasData(group) && !group.showDisplayOptions)) return '';
  const groupId = contactGroupId(group) || newContactGroupId();
  return `<div class="contact-display-options"><span>主表显示：</span>${displayColumns.map(column => {
    const checked = contactGroupDisplayChecked(options.selection || {}, column.key, groupId, options.defaultGroupId);
    return `<label title="在主表“${esc(column.label)}”列显示本联系人组"><input type="checkbox" data-contact-display-column="${esc(column.key)}" data-contact-group-id="${esc(groupId)}" ${checked ? 'checked' : ''}>${esc(column.label)}</label>`;
  }).join('')}</div>`;
}
function contactCategoryHtml(category, groups = [], options = {}) {
  return `<article class="contact-card ${category.key} contact-edit-category" data-contact-category="${category.key}" data-contact-target="${category.target}">
    <div class="contact-card-title contact-edit-category-head"><strong>${esc(category.label)}</strong><span class="contact-category-drop-hint">可拖入 · 保存后生效</span><button class="btn" type="button" onclick="addContactGroup('${category.key}', this)">添加一组</button></div>
    <div class="contact-detail-groups contact-edit-groups" ondragover="contactCategoryDragOver(event)" ondragleave="contactCategoryDragLeave(event)" ondrop="contactCategoryDrop(event)">${groups.map(group => contactGroupHtml(group, options)).join('')}</div>
  </article>`;
}
function currentContactDisplayEditorOptions(root = document) {
  const publicEditor = Boolean(root?.closest?.('.series-public-contact-editor') || root?.querySelector?.('.series-public-contact-editor'));
  return {
    displayColumns: publicEditor ? [] : seriesDetailContactDisplayColumns(),
    selection: normalizeDetailContactSelection(state.editing?.item?.detail_contact_selection),
    defaultGroupId: '',
  };
}
function contactGroupHtml(group = {}, options = {}) {
  const groupId = contactGroupId(group) || newContactGroupId();
  return `<div class="contact-detail-group contact-group" data-contact-group-id="${esc(groupId)}" ondragover="contactGroupDragOver(event)" ondragleave="contactGroupDragLeave(event)" ondrop="contactGroupDrop(event)">
    <div class="contact-edit-content">
      <div class="contact-edit-line"><input class="contact-edit-inline contact-edit-role" name="contact_role_type" value="${esc(group.roleType || '联系人')}" placeholder="联系人">：<input class="contact-edit-inline contact-edit-value" name="contact_name" value="${esc(group.name || '')}" placeholder="姓名或单位"></div>
      <div class="contact-edit-line"><span>电话：</span><input class="contact-edit-inline contact-edit-value" name="contact_phone" type="tel" value="${esc(group.phone || '')}" placeholder="电话号码"></div>
      <div class="contact-edit-line"><span>邮箱：</span><input class="contact-edit-inline contact-edit-value" name="contact_email" type="email" value="${esc(group.email || '')}" placeholder="电子邮箱"></div>
      <div class="contact-edit-line contact-edit-notes"><span>备注：</span><textarea class="contact-edit-inline contact-edit-value" name="contact_notes" rows="${Math.max(1, String(group.notes || '').split('\n').length)}" placeholder="备注" oninput="resizeContactNote(this)">${esc(group.notes || '')}</textarea></div>
      ${contactDisplayOptionsHtml({...group, groupId}, options)}
    </div>
    <div class="contact-edit-actions"><button class="btn contact-edit-drag-handle" type="button" draggable="false" aria-label="拖动排序" title="按住并拖动排序" onpointerdown="contactGroupPointerDown(event)">⋮⋮</button><button class="btn contact-sync-btn contact-sync-icon" type="button" aria-label="同步通讯录" title="同步通讯录" onclick="syncContactToICloud(this)">${contactSyncIcon()}</button><button class="btn contact-group-remove" type="button" title="删除本组" aria-label="删除本组" onclick="removeContactGroup(this)">×</button></div>
  </div>`;
}
function resizeContactNote(textarea) {
  textarea.style.height = 'auto';
  textarea.style.setProperty('height', `${Math.max(22, textarea.scrollHeight)}px`, 'important');
}
function addContactGroup(categoryKey, button = null) {
  const root = button?.closest?.('.contact-edit-category') || document;
  const box = root.querySelector?.(`[data-contact-category="${categoryKey}"] .contact-edit-groups`);
  if (box) box.insertAdjacentHTML('afterbegin', contactGroupHtml({groupId: newContactGroupId(), showDisplayOptions: true}, currentContactDisplayEditorOptions(root)));
}
function removeContactGroup(button) {
  const box = button.closest('.contact-edit-groups');
  button.closest('.contact-group')?.remove();
  if (box && !box.querySelector('.contact-group')) box.insertAdjacentHTML('beforeend', contactGroupHtml({groupId: newContactGroupId(), showDisplayOptions: true}, currentContactDisplayEditorOptions()));
}
let draggingContactGroup = null;
let contactGroupDropCommitted = false;
function clearContactDragIndicators() {
  document.querySelectorAll('.contact-group.drag-over, .contact-group.drag-insert-before, .contact-group.drag-insert-after').forEach(group => group.classList.remove('drag-over', 'drag-insert-before', 'drag-insert-after'));
  document.querySelectorAll('.contact-edit-groups.drop-target, .contact-edit-category.drop-target').forEach(group => group.classList.remove('drop-target'));
}
function animateContactGroupReorder(container, mutate) {
  const before = captureApexReorderRects(container, ':scope > .contact-group');
  mutate();
  animateApexReorder(container, before);
}
function moveContactGroupToPreview(target, insertBefore) {
  const source = draggingContactGroup;
  const container = target?.parentElement;
  if (!source || !container || source === target) return false;
  if ((insertBefore && source.nextElementSibling === target) || (!insertBefore && target.nextElementSibling === source)) return false;
  if (source.parentElement === container) {
    animateContactGroupReorder(container, () => container.insertBefore(source, insertBefore ? target : target.nextSibling));
  } else {
    container.insertBefore(source, insertBefore ? target : target.nextSibling);
  }
  return true;
}
function contactGroupDragStart(event) {
  draggingContactGroup = event.target.closest('.contact-group');
  if (!draggingContactGroup) return;
  contactGroupDropCommitted = false;
  draggingContactGroup.classList.add('dragging');
  draggingContactGroup.closest('.contact-edit-groups')?.classList.add('contact-dragging');
  draggingContactGroup.closest('.contact-edit-category')?.classList.add('contact-dragging');
  event.dataTransfer.effectAllowed = 'move';
  event.dataTransfer.setData('text/plain', 'contact-group');
}
function contactGroupDragOver(event) {
  const target = event.currentTarget;
  if (!draggingContactGroup || target === draggingContactGroup) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = 'move';
  const insertBefore = event.clientY < target.getBoundingClientRect().top + target.getBoundingClientRect().height / 2;
  clearContactDragIndicators();
  target.classList.add('drag-over', insertBefore ? 'drag-insert-before' : 'drag-insert-after');
  if (moveContactGroupToPreview(target, insertBefore)) contactGroupDropCommitted = true;
}
function contactGroupDragLeave(event) {
  if (!event.currentTarget.contains(event.relatedTarget)) event.currentTarget.classList.remove('drag-over', 'drag-insert-before', 'drag-insert-after');
}
function contactGroupDrop(event) {
  const target = event.currentTarget;
  event.preventDefault();
  clearContactDragIndicators();
  if (!draggingContactGroup || target === draggingContactGroup) return;
  const box = target.getBoundingClientRect();
  if (moveContactGroupToPreview(target, event.clientY < box.top + box.height / 2)) contactGroupDropCommitted = true;
}
function contactCategoryDragOver(event) {
  if (!draggingContactGroup || event.target.closest('.contact-group')) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = 'move';
  clearContactDragIndicators();
  event.currentTarget.classList.add('drop-target');
  event.currentTarget.closest('.contact-edit-category')?.classList.add('drop-target');
}
function contactCategoryDragLeave(event) {
  if (!event.currentTarget.contains(event.relatedTarget)) {
    event.currentTarget.classList.remove('drop-target');
    event.currentTarget.closest('.contact-edit-category')?.classList.remove('drop-target');
  }
}
function contactCategoryDrop(event) {
  if (!draggingContactGroup || event.target.closest('.contact-group')) return;
  event.preventDefault();
  const container = event.currentTarget;
  clearContactDragIndicators();
  if (draggingContactGroup.parentElement !== container) {
    container.appendChild(draggingContactGroup);
    contactGroupDropCommitted = true;
  }
}
function ensureContactEditorPlaceholders() {
  const options = currentContactDisplayEditorOptions();
  document.querySelectorAll('[data-contact-category] .contact-edit-groups').forEach(box => {
    if (!box.querySelector('.contact-group')) box.insertAdjacentHTML('beforeend', contactGroupHtml({groupId: newContactGroupId(), showDisplayOptions: true}, options));
  });
}
function contactGroupDragEnd() {
  const committedGroup = draggingContactGroup;
  const committed = contactGroupDropCommitted;
  clearContactDragIndicators();
  document.querySelectorAll('.contact-edit-groups.contact-dragging, .contact-edit-category.contact-dragging').forEach(group => group.classList.remove('contact-dragging'));
  committedGroup?.classList.remove('dragging');
  if (committed) markApexReorderCommitted(committedGroup);
  ensureContactEditorPlaceholders();
  draggingContactGroup = null;
  contactGroupDropCommitted = false;
}
let contactPointerDrag = null;
function beginContactPointerDrag(group) {
  draggingContactGroup = group;
  contactGroupDropCommitted = false;
  group.classList.add('dragging');
  group.closest('.contact-edit-groups')?.classList.add('contact-dragging');
  group.closest('.contact-edit-category')?.classList.add('contact-dragging');
}
function getContactDropContainer(target) {
  const group = target?.closest?.('.contact-group');
  if (group) return { group, container: group.parentElement };
  const category = target?.closest?.('.contact-edit-category');
  return { group: null, container: category?.querySelector('.contact-edit-groups') || null };
}
function contactGroupPointerDown(event) {
  if (event.button !== 0 || contactPointerDrag) return;
  const handle = event.currentTarget;
  const group = handle.closest('.contact-group');
  if (!group) return;
  event.preventDefault();
  event.stopPropagation();
  const pointerId = event.pointerId;
  const startX = event.clientX;
  const startY = event.clientY;
  const drag = { handle, group, pointerId, startX, startY, active: false, moved: false };
  contactPointerDrag = drag;
  const finish = endEvent => {
    if (!contactPointerDrag || endEvent.pointerId !== pointerId) return;
    document.removeEventListener('pointermove', move, true);
    document.removeEventListener('pointerup', finish, true);
    document.removeEventListener('pointercancel', finish, true);
    const committedGroup = drag.group;
    const committed = drag.active && drag.moved;
    clearContactDragIndicators();
    document.querySelectorAll('.contact-edit-groups.contact-dragging, .contact-edit-category.contact-dragging').forEach(item => item.classList.remove('contact-dragging'));
    committedGroup.classList.remove('dragging');
    if (committed) markApexReorderCommitted(committedGroup);
    ensureContactEditorPlaceholders();
    draggingContactGroup = null;
    contactGroupDropCommitted = false;
    contactPointerDrag = null;
  };
  const move = moveEvent => {
    if (!contactPointerDrag || moveEvent.pointerId !== pointerId) return;
    const distance = Math.hypot(moveEvent.clientX - startX, moveEvent.clientY - startY);
    if (!drag.active) {
      if (distance < 4) return;
      drag.active = true;
      beginContactPointerDrag(group);
    }
    moveEvent.preventDefault();
    const hit = document.elementFromPoint(moveEvent.clientX, moveEvent.clientY);
    const { group: target, container } = getContactDropContainer(hit);
    if (!container) return;
    if (target && target !== group) {
      const box = target.getBoundingClientRect();
      const insertBefore = moveEvent.clientY < box.top + box.height / 2;
      clearContactDragIndicators();
      target.classList.add('drag-over', insertBefore ? 'drag-insert-before' : 'drag-insert-after');
      if (moveContactGroupToPreview(target, insertBefore)) {
        drag.moved = true;
        contactGroupDropCommitted = true;
      }
      return;
    }
    clearContactDragIndicators();
    container.classList.add('drop-target');
    container.closest('.contact-edit-category')?.classList.add('drop-target');
    if (group.parentElement !== container) {
      container.appendChild(group);
      drag.moved = true;
      contactGroupDropCommitted = true;
    }
  };
  document.addEventListener('pointermove', move, true);
  document.addEventListener('pointerup', finish, true);
  document.addEventListener('pointercancel', finish, true);
  handle.setPointerCapture?.(pointerId);
}
async function syncContactToICloud(button, encodedGroup = '') {
  if (!requireOnlineAction()) return;
  const group = button.closest('.contact-group');
  let body;
  if (encodedGroup) {
    const saved = JSON.parse(decodeURIComponent(encodedGroup));
    body = { role_type: saved.roleType || '联系人', name: saved.name || '', phone: saved.phone || '', email: saved.email || '', notes: saved.notes || '', case_number: saved.caseNumber || '' };
  } else {
    body = {
      role_type: group.querySelector('[name=contact_role_type]')?.value || '联系人',
      name: group.querySelector('[name=contact_name]')?.value.trim() || '',
      phone: group.querySelector('[name=contact_phone]')?.value.trim() || '',
      email: group.querySelector('[name=contact_email]')?.value.trim() || '',
      notes: group.querySelector('[name=contact_notes]')?.value.trim() || '',
    };
  }
  if (!body.name) { toast('请先填写联系人或承办人姓名'); return; }
  body.case_id = Number(
    button.closest('[data-contact-case-id]')?.dataset.contactCaseId
      || (state.editing?.tab === 'cases' ? state.editing.item?.id
        : state.editing?.tab === 'hearings' ? state.editing.item?.case_id
          : state.seriesWorkspace?.id)
  ) || 0;
  const oldHtml = button.innerHTML;
  button.disabled = true;
  button.setAttribute('aria-busy', 'true');
  button.innerHTML = '<svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M8 2.2a5.8 5.8 0 1 1-4.1 1.7" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="M2.2 2.5v3.1h3.1" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  try {
    const result = await api('/api/case-manager/contacts/sync', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
    toast(result.action === 'created' ? '已新增到 iCloud 通讯录' : '已更新 iCloud 通讯录联系人');
  } catch (e) {
    toast(e.message);
  } finally {
    button.disabled = false;
    button.removeAttribute('aria-busy');
    button.innerHTML = oldHtml;
  }
}
function formSection(title, subtitle, body) {
  return `<section class="form-section">
    <div class="form-section-head"><h3>${esc(title)}</h3>${subtitle ? `<span>${esc(subtitle)}</span>` : ''}</div>
    <div class="form-section-body">${body}</div>
  </section>`;
}
function field(name, label, value = '', cls = '', type = 'text', attrs = '') {
  return `<div class="field ${cls}"><label>${label}</label><input class="input" name="${name}" type="${type}" value="${esc(value ?? '')}" ${attrs}></div>`;
}
function area(name, label, value = '', cls = '', textareaCls = '') {
  return `<div class="field ${cls}"><label>${label}</label><textarea class="${textareaCls}" name="${name}">${esc(value ?? '')}</textarea></div>`;
}
function hearingTypeOptions() {
  return HEARING_TYPE_OPTIONS.map(type => `<option value="${esc(type)}"></option>`).join('');
}
function hearingTypeField(value = '') {
  return `<div class="field"><label>类型</label>
    <input class="input" name="reminder_type" list="hearingTypeList" value="${esc(value || '')}" placeholder="搜索或选择开庭类型">
  </div>`;
}
let hearingNoticePastedFiles = [];
function hearingNoticeRecognizerHtml() {
  hearingNoticePastedFiles = [];
  return formSection('AI 智能识别', '使用 DeepSeek V4.1 Flash 识别并预填开庭信息', `
    <div class="notice-ai-grid" onpaste="pasteHearingNoticeScreenshot(event)">
      <div class="field">
        <label>开庭通知短信文本</label>
        <textarea class="input tall" id="hearingNoticeText" placeholder="粘贴法院或仲裁委短信、微信通知文本"></textarea>
        <div class="notice-ai-actions">
          <button class="btn primary" type="button" id="recognizeHearingBtn" onclick="recognizeHearingNotice()">识别并填入</button>
          <button class="btn" type="button" onclick="clearHearingNoticeRecognition()">清空识别区</button>
        </div>
      </div>
      <div class="notice-ai-file" tabindex="0" role="button" aria-label="粘贴或选择传票截图">
        <label>传票 PDF / 截图</label>
        <input id="hearingNoticeFiles" type="file" accept=".pdf,image/*,.txt" multiple onchange="updateHearingNoticePasteStatus()">
        <div class="form-hint">可在此区域或左侧文本框直接按 ⌘V 粘贴截图；也可选择文件。图片先用本机 OCR，再由 DeepSeek V4.1 Flash 校正并提取字段。</div>
        <div class="notice-paste-status" id="hearingNoticePasteStatus">尚未添加传票截图</div>
      </div>
    </div>
    <div class="notice-ai-result" id="hearingNoticeResult"></div>
  `);
}
function pasteHearingNoticeScreenshot(event) {
  const imageFiles = [...(event.clipboardData?.items || [])]
    .filter(item => item.kind === 'file' && (item.type || '').startsWith('image/'))
    .map(item => item.getAsFile())
    .filter(Boolean);
  if (!imageFiles.length) return;
  event.preventDefault();
  const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
  const renamed = imageFiles.map((file, index) => {
    const extension = (file.type || '').split('/')[1]?.replace('jpeg', 'jpg') || 'png';
    return new File([file], `传票截图-${stamp}${imageFiles.length > 1 ? `-${index + 1}` : ''}.${extension}`, {
      type: file.type || 'image/png',
      lastModified: Date.now(),
    });
  });
  hearingNoticePastedFiles.push(...renamed);
  updateHearingNoticePasteStatus();
  toast(`已粘贴 ${renamed.length} 张传票截图`);
}
function updateHearingNoticePasteStatus() {
  const status = $('hearingNoticePasteStatus');
  if (!status) return;
  const selected = [...($('hearingNoticeFiles')?.files || [])];
  const files = [...selected, ...hearingNoticePastedFiles];
  status.classList.toggle('has-files', files.length > 0);
  status.textContent = files.length
    ? `已添加 ${files.length} 个文件：${files.map(file => file.name).join('、')}`
    : '尚未添加传票截图';
}
function clearHearingNoticeRecognition() {
  const text = $('hearingNoticeText');
  const files = $('hearingNoticeFiles');
  const result = $('hearingNoticeResult');
  hearingNoticePastedFiles = [];
  if (text) text.value = '';
  if (files) files.value = '';
  updateHearingNoticePasteStatus();
  if (result) {
    result.classList.remove('show');
    result.innerHTML = '';
  }
}
async function recognizeHearingNotice() {
  if (!requireOnlineAction()) return;
  const button = $('recognizeHearingBtn');
  const result = $('hearingNoticeResult');
  const form = new FormData();
  form.append('text', $('hearingNoticeText')?.value || '');
  [...($('hearingNoticeFiles')?.files || [])].forEach(file => form.append('files', file));
  hearingNoticePastedFiles.forEach(file => form.append('files', file));
  if (button) button.disabled = true;
  if (result) {
    result.classList.add('show');
    result.textContent = '正在使用 DeepSeek V4.1 Flash 识别开庭通知...';
  }
  try {
    const data = await api('/api/case-manager/hearings/recognize', { method: 'POST', body: form });
    applyHearingRecognition(data);
    if (result) result.innerHTML = hearingRecognitionSummary(data);
    toast('已识别并填入开庭信息，请核对后保存');
  } catch (e) {
    if (result) result.innerHTML = `<strong>识别失败</strong><br>${esc(e.message)}`;
  } finally {
    if (button) button.disabled = false;
  }
}
function applyHearingRecognition(data) {
  const item = data.item || {};
  if (item.case_id) {
    setNamedValue('case_id', item.case_id);
    setNamedValue('title', item.title || '');
  } else if (item.title) {
    setNamedValue('title', item.title, false);
  }
  if (item.reminder_type) setNamedValue('reminder_type', item.reminder_type);
  if (item.hearing_at) setNamedValue('hearing_at', toInputDateTime(item.hearing_at));
  if (item.location) setNamedValue('location', item.location);
  if (item.case_no) setNamedValue('case_no', item.case_no);
  if (item.court) setNamedValue('court', item.court);
  if (item.court_contact) setNamedValue('court_contact', item.court_contact);
  if (item.party_contact) setNamedValue('party_contact', item.party_contact, false);
  const caseLookupBox = $('caseLookupResults');
  if (caseLookupBox) caseLookupBox.classList.remove('show');
}
function hearingRecognitionSummary(data) {
  const item = data.item || {};
  const files = (data.files || []).filter(f => f.filename).map(f => `${esc(f.filename)}${f.error ? `：${esc(f.error)}` : ''}`).join('<br>');
  const ai = data.ai || {};
  const aiStatus = ai.used
    ? `AI 增强：${esc(['deepseek-flash', 'deepseek-v4-flash'].includes(ai.model) ? 'DeepSeek V4.1 Flash' : ai.model || '已启用')}`
    : `AI 增强：<span style="color:#9a3412">暂不可用，已使用本机规则识别${ai.error ? `（${esc(ai.error)}）` : ''}</span>`;
  return `<strong>识别完成</strong>　置信度 ${esc(data.confidence || 0)}%
    <br>${aiStatus}
    <br>匹配案件：${data.matched_case ? esc(data.matched_case.title || '') : '<span style="color:#9a3412">未按案号匹配到既有案件</span>'}
    <br>案号：${esc(item.case_no || '-')}
    <br>时间：${esc(fmt(item.hearing_at || '') || '-')}
    <br>地点：${esc(item.location || '-')}
    <br>机构：${esc(item.court || '-')}
    ${files ? `<br>文件：${files}` : ''}`;
}
let preservationNoticePastedFiles = [];
function preservationNoticeRecognizerHtml() {
  preservationNoticePastedFiles = [];
  return formSection('AI 智能识别', '使用 DeepSeek V4.1 Flash 识别并预填财产保全信息', `
    <div class="notice-ai-grid" onpaste="pastePreservationNoticeScreenshot(event)">
      <div class="field">
        <label>财产保全情况告知书 / 短信文本</label>
        <textarea class="input tall" id="preservationNoticeText" placeholder="粘贴法院财产保全情况告知书或告知短信文本"></textarea>
        <div class="notice-ai-actions">
          <button class="btn primary" type="button" id="recognizePreservationBtn" onclick="recognizePreservationNotice()">识别并填入</button>
          <button class="btn" type="button" onclick="clearPreservationNoticeRecognition()">清空识别区</button>
        </div>
      </div>
      <div class="notice-ai-file" tabindex="0" role="button" aria-label="粘贴或选择财产保全告知书截图">
        <label>告知书 PDF / 截图</label>
        <input id="preservationNoticeFiles" type="file" accept=".pdf,image/*,.txt" multiple onchange="updatePreservationNoticePasteStatus()">
        <div class="form-hint">可在此区域或左侧文本框直接按 ⌘V 粘贴截图；也可选择文件。图片先用本机 OCR，再由 DeepSeek V4.1 Flash 校正并提取字段。</div>
        <div class="notice-paste-status" id="preservationNoticePasteStatus">尚未添加保全告知书截图</div>
      </div>
    </div>
    <div class="notice-ai-result" id="preservationNoticeResult"></div>
  `);
}
function pastePreservationNoticeScreenshot(event) {
  const imageFiles = [...(event.clipboardData?.items || [])]
    .filter(item => item.kind === 'file' && (item.type || '').startsWith('image/'))
    .map(item => item.getAsFile())
    .filter(Boolean);
  if (!imageFiles.length) return;
  event.preventDefault();
  const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
  const renamed = imageFiles.map((file, index) => {
    const extension = (file.type || '').split('/')[1]?.replace('jpeg', 'jpg') || 'png';
    return new File([file], `保全告知书截图-${stamp}${imageFiles.length > 1 ? `-${index + 1}` : ''}.${extension}`, {
      type: file.type || 'image/png',
      lastModified: Date.now(),
    });
  });
  preservationNoticePastedFiles.push(...renamed);
  updatePreservationNoticePasteStatus();
  toast(`已粘贴 ${renamed.length} 张保全告知书截图`);
}
function updatePreservationNoticePasteStatus() {
  const status = $('preservationNoticePasteStatus');
  if (!status) return;
  const selected = [...($('preservationNoticeFiles')?.files || [])];
  const files = [...selected, ...preservationNoticePastedFiles];
  status.classList.toggle('has-files', files.length > 0);
  status.textContent = files.length
    ? `已添加 ${files.length} 个文件：${files.map(file => file.name).join('、')}`
    : '尚未添加保全告知书截图';
}
function clearPreservationNoticeRecognition() {
  const text = $('preservationNoticeText');
  const files = $('preservationNoticeFiles');
  const result = $('preservationNoticeResult');
  preservationNoticePastedFiles = [];
  if (text) text.value = '';
  if (files) files.value = '';
  updatePreservationNoticePasteStatus();
  if (result) {
    result.classList.remove('show');
    result.innerHTML = '';
  }
}
async function recognizePreservationNotice() {
  if (!requireOnlineAction()) return;
  const button = $('recognizePreservationBtn');
  const result = $('preservationNoticeResult');
  const form = new FormData();
  form.append('text', $('preservationNoticeText')?.value || '');
  [...($('preservationNoticeFiles')?.files || [])].forEach(file => form.append('files', file));
  preservationNoticePastedFiles.forEach(file => form.append('files', file));
  if (button) button.disabled = true;
  if (result) {
    result.classList.add('show');
    result.textContent = '正在使用 DeepSeek V4.1 Flash 识别财产保全告知信息...';
  }
  try {
    const data = await api('/api/case-manager/preservations/recognize', { method: 'POST', body: form });
    applyPreservationRecognition(data);
    if (result) result.innerHTML = preservationRecognitionSummary(data);
    toast('已识别并填入财产保全信息，请核对后保存');
  } catch (e) {
    if (result) result.innerHTML = `<strong>识别失败</strong><br>${esc(e.message)}`;
  } finally {
    if (button) button.disabled = false;
  }
}
function applyPreservationRecognition(data) {
  const item = data.item || {};
  if (item.case_id) {
    setNamedValue('case_id', item.case_id);
    setNamedValue('title', item.title || '');
  } else if (item.title) {
    setNamedValue('title', item.title, false);
  }
  const groups = Array.isArray(data.items) && data.items.length ? data.items : [item];
  const box = $('preservationGroups');
  if (box) {
    box.innerHTML = groups.map((group, index) => preservationGroupHtml(group, index)).join('');
    refreshPreservationGroupHeadings();
  } else {
    if (item.preservation_type) setNamedValue('preservation_type', item.preservation_type);
    if (item.start_at) setNamedValue('start_at', dateOnly(item.start_at));
    if (item.deadline_at) setNamedValue('deadline_at', dateOnly(item.deadline_at));
    if (item.period_years !== undefined && item.period_years !== null && item.period_years !== '') setNamedValue('period_years', item.period_years);
    if (item.asset_content) setNamedValue('asset_content', item.asset_content);
    if (item.notes) setNamedValue('notes', item.notes, false);
  }
  const caseLookupBox = $('caseLookupResults');
  if (caseLookupBox) caseLookupBox.classList.remove('show');
}
function preservationRecognitionSummary(data) {
  const item = data.item || {};
  const groups = Array.isArray(data.items) && data.items.length ? data.items : [item];
  const files = (data.files || []).filter(f => f.filename).map(f => `${esc(f.filename)}${f.error ? `：${esc(f.error)}` : ''}`).join('<br>');
  const ai = data.ai || {};
  const aiStatus = ai.used
    ? `AI 增强：${esc(['deepseek-flash', 'deepseek-v4-flash'].includes(ai.model) ? 'DeepSeek V4.1 Flash' : ai.model || '已启用')}`
    : `AI 增强：<span style="color:#9a3412">暂不可用，已使用本机规则识别${ai.error ? `（${esc(ai.error)}）` : ''}</span>`;
  return `<strong>识别完成</strong>　置信度 ${esc(data.confidence || 0)}%
    <br>${aiStatus}
    <br>匹配案件：${data.matched_case ? `${esc(data.matched_case.title || '')}（${data.match_method === 'party' ? '按当事人匹配' : '按案号匹配'}）` : '<span style="color:#9a3412">暂未匹配既有案件，可手动选择</span>'}
    <br>识别到 ${groups.length} 组保全信息：
    ${groups.map((group, index) => `<div class="preservation-recognition-item"><strong>第${index + 1}组：${esc(group.preservation_type || '财产保全')}</strong>　截止 ${esc(dateOnly(group.deadline_at) || '-')}　期限 ${esc(group.period_years ?? '-')} 年<br>${esc(group.asset_content || '未识别到财产内容')}</div>`).join('')}
    ${files ? `<br>文件：${files}` : ''}`;
}
async function loadCaseTypes(q = '') {
  const query = q || '';
  if (state.caseTypes.length && state.caseTypeQuery === query) return;
  const data = await api(`/api/case-manager/case-types?q=${encodeURIComponent(query)}&limit=180`);
  state.caseTypes = data.items || [];
  state.caseTypeQuery = query;
}
let caseTypeTimer = null;
async function refreshCaseTypeOptions(value) {
  clearTimeout(caseTypeTimer);
  caseTypeTimer = setTimeout(async () => {
    try {
      await loadCaseTypes(value);
      const list = $('civilCauseList');
      if (list) list.innerHTML = caseTypeOptionsHtml();
    } catch (e) {
      toast(e.message);
    }
  }, 220);
}
function lookupCaseTypes(input) {
  hideLookupResults();
  clearTimeout(caseTypeTimer);
  const q = input.value.trim();
  const field = input.closest('.lookup-field');
  const box = field?.querySelector('.lookup-results');
  caseTypeTimer = setTimeout(async () => {
    try {
      await loadCaseTypes(q);
      const list = $('civilCauseList');
      if (list) list.innerHTML = caseTypeOptionsHtml();
      renderSimpleLookup(box, state.caseTypes, input, q, '使用当前案由并新建');
    } catch (e) {
      toast(e.message);
    }
  }, 160);
}
function caseTypeOptionsHtml() {
  return state.caseTypes.map(type => `<option value="${esc(type)}"></option>`).join('');
}
function caseTypeField(value = '') {
  return `<div class="field lookup-field"><label class="field-label-actions"><span>案件类型</span><button class="field-manage-button" type="button" onclick="openOptionManager('case_type')">管理</button></label>
    <input class="input" name="case_type" value="${esc(value || '')}" oninput="lookupCaseTypes(this)" onfocus="lookupCaseTypes(this)" autocomplete="new-case-type" placeholder="搜索或选择民事案件案由">
    <div class="lookup-results"></div>
    <datalist id="civilCauseList">${caseTypeOptionsHtml()}</datalist>
  </div>`;
}
async function loadCaseStages() {
  const data = await api('/api/case-manager/case-stages?limit=300');
  state.caseStages = data.items || [];
}
function currentStageField(value = '') {
  return `<div class="field lookup-field"><label class="field-label-actions"><span>当前阶段</span><button class="field-manage-button" type="button" onclick="openOptionManager('current_stage')">管理</button></label>
    <input class="input" name="current_stage" value="${esc(value || '')}" oninput="lookupCaseStages(this)" onfocus="lookupCaseStages(this)" onclick="lookupCaseStages(this)" autocomplete="new-case-stage" placeholder="搜索或选择当前阶段">
    <div class="lookup-results stage-lookup-results"></div>
  </div>`;
}
function lookupCaseStages(input) {
  hideLookupResults();
  const q = input.value.trim();
  const box = input.closest('.lookup-field')?.querySelector('.stage-lookup-results');
  const values = (state.caseStages || []).filter(stage => !q || stage.includes(q) || fuzzyIncludes(stage, q));
  renderSimpleLookup(box, values, input, q, '使用当前阶段并新建');
}
async function loadCaseNumberTypes() {
  if (state.caseNumberTypes.length) return;
  const data = await api('/api/case-manager/case-number-types?limit=220');
  state.caseNumberTypes = data.items || [];
}
function caseNumberTypeOptions() {
  return state.caseNumberTypes.map(type => `<option value="${esc(type)}"></option>`).join('');
}
function lookupCaseNumberTypes(input) {
  hideLookupResults();
  const q = input.value.trim();
  const box = input.closest('.lookup-cell')?.querySelector('.number-type-lookup-results');
  const values = (state.caseNumberTypes || []).filter(type => !q || type.includes(q) || fuzzyIncludes(type, q));
  renderSimpleLookup(box, values, input, q, '使用当前性质/阶段并新建');
}
async function loadPreservationTypes() {
  if (state.preservationTypes.length) return;
  const data = await api('/api/case-manager/preservation-types?limit=180');
  state.preservationTypes = data.items || [];
}
function preservationTypeField(value = '') {
  return `<div class="field preservation-type-picker"><label>类型</label>
    <input class="input" name="preservation_type" value="${esc(value || '')}" autocomplete="off" placeholder="搜索或选择保全类型" oninput="lookupPreservationTypes(this)" onfocus="lookupPreservationTypes(this)" onclick="lookupPreservationTypes(this)">
    <div class="lookup-results preservation-type-results"></div>
  </div>`;
}
function lookupPreservationTypes(input) {
  hideLookupResults();
  const q = input.value.trim();
  const box = input.closest('.preservation-type-picker')?.querySelector('.preservation-type-results');
  const values = (state.preservationTypes || []).filter(type => !q || fuzzyIncludes(type, q));
  renderSimpleLookup(box, values, input, q, '使用当前保全类型');
}
async function loadCourts(q = '') {
  const query = q || '';
  if (state.courts.length && state.courtQuery === query) return;
  const data = await api(`/api/case-manager/court-options?q=${encodeURIComponent(query)}&limit=220`);
  state.courts = data.items || [];
  state.courtQuery = query;
}
let courtTimer = null;
function refreshCourtOptions(value) {
  clearTimeout(courtTimer);
  courtTimer = setTimeout(async () => {
    try {
      await loadCourts(value);
      document.querySelectorAll('#courtList').forEach(list => { list.innerHTML = courtOptionsHtml(); });
    } catch (e) {
      toast(e.message);
    }
  }, 220);
}
function lookupCourts(input) {
  hideLookupResults();
  clearTimeout(courtTimer);
  const q = input.value.trim();
  const field = input.closest('.lookup-field, .subrow, .case-number-card, .lookup-cell');
  const box = field?.querySelector('.court-lookup-results');
  courtTimer = setTimeout(async () => {
    try {
      await loadCourts(q);
      document.querySelectorAll('#courtList').forEach(list => { list.innerHTML = courtOptionsHtml(); });
      renderSimpleLookup(box, state.courts, input, q, '使用当前机构并新建');
    } catch (e) {
      toast(e.message);
    }
  }, 160);
}
function courtOptionsHtml() {
  return state.courts.map(court => `<option value="${esc(court)}"></option>`).join('');
}
function courtField(name, label, value = '', cls = '') {
  return `<div class="field ${cls} lookup-field"><label>${label}</label>
    <input class="input" name="${name}" value="${esc(value || '')}" oninput="lookupCourts(this)" onfocus="lookupCourts(this)" autocomplete="new-court" placeholder="搜索法院或仲裁委员会">
    <div class="lookup-results court-lookup-results"></div>
  </div>`;
}
function fuzzyIncludes(text, query) {
  const source = String(text || '').replace(/\s+/g, '');
  const q = String(query || '').replace(/\s+/g, '');
  if (!q) return true;
  if (source.includes(q)) return true;
  let pos = 0;
  for (const ch of q) {
    const found = source.indexOf(ch, pos);
    if (found < 0) return false;
    pos = found + 1;
  }
  return true;
}
function floatingLookupBox() {
  let box = $('floatingLookupResults');
  if (!box) {
    box = document.createElement('div');
    box.id = 'floatingLookupResults';
    box.className = 'lookup-results floating';
    document.body.appendChild(box);
  }
  return box;
}
function lookupAnchorForInput(input) {
  return input?.closest('.detail-edit-list dd, .detail-edit-table td') || input;
}
function positionFloatingLookup(input, box) {
  const rect = lookupAnchorForInput(input).getBoundingClientRect();
  const width = Math.min(rect.width, window.innerWidth - 24);
  const left = Math.min(Math.max(12, rect.left), window.innerWidth - width - 12);
  const dropdownHeight = Math.min(box.scrollHeight || 0, 260);
  const roomBelow = window.innerHeight - rect.bottom - 12;
  const roomAbove = rect.top - 12;
  const openAbove = roomBelow < Math.min(dropdownHeight, 120) && roomAbove > roomBelow;
  const maxHeight = Math.max(72, Math.min(260, (openAbove ? roomAbove : roomBelow)));
  box.style.width = `${width}px`;
  box.style.left = `${left}px`;
  box.style.maxHeight = `${maxHeight}px`;
  box.style.top = `${openAbove ? Math.max(12, rect.top - Math.min(dropdownHeight, maxHeight) - 4) : rect.bottom + 4}px`;
}
function lookupBoxForInput(box, input) {
  if (input?.closest('.case-section-editor')) {
    if (box) {
      box.classList.remove('show');
      box.innerHTML = '';
    }
    return floatingLookupBox();
  }
  return box;
}
function hideLookupResults() {
  document.querySelectorAll('.lookup-results.show').forEach(box => {
    box.classList.remove('show');
    box.innerHTML = '';
  });
}
function renderSimpleLookup(box, items, input, query, createLabel, afterSelect = null) {
  box = lookupBoxForInput(box, input);
  if (!box) return;
  const values = (items || []).filter(Boolean).slice(0, 12);
  if (!values.length && !query) {
    box.classList.remove('show');
    box.innerHTML = '';
    return;
  }
  const optionHtml = values.map(value => `<button class="lookup-option" type="button" onclick="selectLookupValue(this, '${encodeURIComponent(value)}')"><strong>${esc(value)}</strong></button>`).join('');
  const createHtml = query
    ? `<button class="lookup-option create-option" type="button" onclick="acceptLookupInput(this)"><strong>${esc(createLabel || '使用当前输入并新建')}</strong><span>${esc(query)}</span></button>`
    : '';
  box.innerHTML = optionHtml + createHtml;
  box.classList.add('show');
  box._lookupInput = input;
  box._afterSelect = afterSelect;
  if (box.classList.contains('floating')) positionFloatingLookup(input, box);
}
function selectLookupValue(button, encodedValue) {
  const box = button.closest('.lookup-results');
  const input = box?._lookupInput || button.closest('.lookup-field, .subrow')?.querySelector('input.input');
  if (input) {
    input.value = decodeURIComponent(encodedValue);
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }
  if (box?._afterSelect) box._afterSelect(input);
  if (box) box.classList.remove('show');
}
function acceptLookupInput(button) {
  const box = button.closest('.lookup-results');
  const input = box?._lookupInput || button.closest('.lookup-field, .subrow')?.querySelector('input.input');
  if (input) {
    input.value = input.value.trim();
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }
  if (box?._afterSelect) box._afterSelect(input);
  if (box) box.classList.remove('show');
  toast('已使用当前输入，保存后会加入本地数据库');
}
function casePickerField(item = {}) {
  return `<div class="field full case-picker">
    <label>案件名称</label>
    <input type="hidden" name="case_id" value="${esc(item.case_id || '')}">
    <input class="input" name="title" value="${esc(item.title || '')}" autocomplete="new-related-case" placeholder="输入案件名称搜索既有案件">
    <div class="lookup-results" id="caseLookupResults"></div>
  </div>`;
}
function attachRelatedCasePicker() {
  const input = document.querySelector('#drawerBody .case-picker [name="title"]');
  if (!input) return;
  const hidden = input.closest('.case-picker').querySelector('[name=case_id]');
  ApexCasePicker.attach({ input, menu: $('caseLookupResults'), request: api, value: hidden.value,
    onInput: () => { hidden.value = ''; },
    onSelect: item => selectExistingCase(Number(item.id)).catch(error => toast(error.message)) });
}
function setNamedValue(name, value, overwrite = true) {
  const el = $('drawerBody').querySelector(`[name="${name}"]`);
  if (!el) return;
  if (overwrite || !el.value) el.value = value || '';
}
async function selectExistingCase(caseId) {
  const input = document.querySelector('#drawerBody .case-picker [name=title]');
  const item = await api(`/api/case-manager/cases?case_id=${caseId}`);
  if (!input?.isConnected || !ApexCasePicker.get(input)?.selected.has(Number(caseId))) return;
  setNamedValue('case_id', item.id);
  setNamedValue('title', item.title);
  const caseNos = (item.case_numbers || []).map(n => n.case_no).filter(Boolean).join('\n');
  const courts = (item.case_numbers || []).map(n => n.court).filter(Boolean).join('\n');
  setNamedValue('case_no', caseNos);
  setNamedValue('court', courts);
  setNamedValue('court_contact', item.court_contact || '');
  setNamedValue('party_contact', item.party_contact || '');
  const box = $('caseLookupResults');
  if (box) box.classList.remove('show');
  toast('已填入既有案件信息');
}
async function loadPartyRoles() {
  if (state.partyRoles.length) return;
  const data = await api('/api/case-manager/party-roles?limit=160');
  state.partyRoles = data.items || [];
}
function partyRoleOptions() {
  return state.partyRoles.map(role => `<option value="${esc(role)}"></option>`).join('');
}
function lookupPartyRoles(input) {
  hideLookupResults();
  const q = input.value.trim();
  const box = input.closest('.lookup-field')?.querySelector('.lookup-results');
  renderSimpleLookup(box, state.partyRoles || [], input, q, '使用当前地位');
}
function caseNumberEditorHtml(item) {
  const rows = item.case_numbers?.length ? item.case_numbers : [{}];
  const selection = new Set(readCaseNumbersSelection(item.id || 'new', rows.map(caseNumberDisplayKey)));
  return `<div class="detail-table-wrap"><table class="mini-table case-number-mini detail-edit-table"><thead><tr><th class="case-no-drag-head" title="按住拖动可调整案号顺序"></th><th class="case-no-col-show" title="勾选后该案号在详情页常驻展示，未勾选的默认折叠（可在详情页点击“展开全部”临时查看）">展示</th><th>性质</th><th>案号</th><th>受理机构</th><th>一审立案时间</th><th>一审判决送达时间</th><th>二审立案时间</th><th>二审判决生效时间</th><th></th></tr></thead><tbody id="caseNoRows">${rows.map(c => caseNoRow(c, selection)).join('')}</tbody></table></div>
  <button class="btn case-inline-add" onclick="addCaseNoRow()" type="button">添加案号</button>`;
}
function caseNoRow(c = {}, selection = new Set()) {
  const key = caseNumberDisplayKey(c);
  return `<tr data-case-number-row ondragover="caseNoDragOver(event)" ondragleave="caseNoDragLeave(event)" ondrop="caseNoDrop(event)">
    <td class="case-no-drag-cell"><button class="btn case-no-drag-handle" type="button" draggable="true" aria-label="拖动排序" title="按住并拖动排序" ondragstart="caseNoDragStart(event)" ondragend="caseNoDragEnd(event)">⋮⋮</button></td>
    <td class="case-no-show-cell"><input type="checkbox" class="case-no-show-toggle" data-case-no-show${selection.has(key) ? ' checked' : ''} title="勾选后在详情页展示该案号"></td>
      <td><input class="input" name="number_type" placeholder="性质" value="${esc(c.number_type || '')}" autocomplete="new-number-type" oninput="lookupCaseNumberTypes(this)" onfocus="lookupCaseNumberTypes(this)"></td>
    <td><input class="input" name="case_no" placeholder="案号" value="${esc(c.case_no || '')}"></td>
    <td><input class="input" name="court" placeholder="受理机构" value="${esc(c.court || '')}" oninput="lookupCourts(this)" onfocus="lookupCourts(this)" autocomplete="new-court"></td>
    <td><input class="input" name="first_filing_at" type="date" value="${esc(dateOnly(c.first_filing_at))}"></td>
    <td><input class="input" name="first_judgment_served_at" type="date" value="${esc(dateOnly(c.first_judgment_served_at))}"></td>
    <td><input class="input" name="second_filing_at" type="date" value="${esc(dateOnly(c.second_filing_at))}"></td>
    <td><input class="input" name="second_judgment_effective_at" type="date" value="${esc(dateOnly(c.second_judgment_effective_at))}"></td>
    <td class="detail-edit-remove"><button class="btn" onclick="this.closest('tr').remove()" type="button">×</button></td>
  </tr>`;
}
function addCaseNoRow() { $('caseNoRows').insertAdjacentHTML('afterbegin', caseNoRow()); }
let draggingCaseNoRow = null;
let caseNoDragMoved = false;
function clearCaseNoDragIndicators() {
  document.querySelectorAll('tr[data-case-number-row].drag-over, tr[data-case-number-row].drag-insert-before, tr[data-case-number-row].drag-insert-after')
    .forEach(row => row.classList.remove('drag-over', 'drag-insert-before', 'drag-insert-after'));
}
function caseNoDragStart(event) {
  const row = event.target.closest('tr[data-case-number-row]');
  if (!row) return;
  draggingCaseNoRow = row;
  caseNoDragMoved = false;
  row.classList.add('dragging');
  row.parentElement?.classList.add('case-no-dragging');
  event.dataTransfer.effectAllowed = 'move';
  event.dataTransfer.setData('text/plain', 'case-number-row');
  try { event.dataTransfer.setDragImage(row, 30, 18); } catch (_) {}
}
function caseNoDragOver(event) {
  const target = event.currentTarget;
  if (!draggingCaseNoRow || target === draggingCaseNoRow || target.parentElement !== draggingCaseNoRow.parentElement) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = 'move';
  const box = target.getBoundingClientRect();
  const insertBefore = event.clientY < box.top + box.height / 2;
  clearCaseNoDragIndicators();
  target.classList.add('drag-over', insertBefore ? 'drag-insert-before' : 'drag-insert-after');
  if ((insertBefore && draggingCaseNoRow.nextElementSibling === target) || (!insertBefore && target.nextElementSibling === draggingCaseNoRow)) return;
  const container = target.parentElement;
  const beforeRects = captureApexReorderRects(container, ':scope > tr[data-case-number-row]');
  container.insertBefore(draggingCaseNoRow, insertBefore ? target : target.nextSibling);
  caseNoDragMoved = true;
  animateApexReorder(container, beforeRects, { skip: draggingCaseNoRow });
}
function caseNoDragLeave(event) {
  if (!event.currentTarget.contains(event.relatedTarget)) event.currentTarget.classList.remove('drag-over', 'drag-insert-before', 'drag-insert-after');
}
function caseNoDrop(event) {
  event.preventDefault();
  clearCaseNoDragIndicators();
}
function caseNoDragEnd() {
  const committedRow = draggingCaseNoRow;
  const committed = caseNoDragMoved;
  clearCaseNoDragIndicators();
  document.querySelectorAll('tbody.case-no-dragging').forEach(box => box.classList.remove('case-no-dragging'));
  committedRow?.classList.remove('dragging');
  if (committed) markApexReorderCommitted(committedRow);
  draggingCaseNoRow = null;
  caseNoDragMoved = false;
}
function toInputDateTime(v) { return v ? String(v).replace(' ', 'T').slice(0,16) : ''; }
function parseDateInput(value) {
  if (!value) return null;
  const date = new Date(`${value}T00:00:00`);
  return Number.isNaN(date.getTime()) ? null : date;
}
function formatDateInput(date) {
  if (!date || Number.isNaN(date.getTime())) return '';
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}
function addDays(date, days) {
  const next = new Date(date);
  next.setDate(next.getDate() + Number(days || 0));
  return next;
}
function addYears(date, years) {
  const next = new Date(date);
  const value = Number(years || 0);
  const whole = value < 0 ? Math.ceil(value) : Math.floor(value);
  const fraction = value - whole;
  next.setFullYear(next.getFullYear() + whole);
  if (fraction) next.setDate(next.getDate() + Math.round(fraction * 365));
  return next;
}
function dateDiffDays(start, end) {
  const a = Date.UTC(start.getFullYear(), start.getMonth(), start.getDate());
  const b = Date.UTC(end.getFullYear(), end.getMonth(), end.getDate());
  return Math.round((b - a) / 86400000);
}
function readNamedDate(name) {
  return parseDateInput($('drawerBody')?.querySelector(`[name="${name}"]`)?.value || '');
}
function setNamedInput(name, value) {
  const el = $('drawerBody')?.querySelector(`[name="${name}"]`);
  if (el) el.value = value ?? '';
}
function syncPreservationGroupDates(changed, input) {
  if (state.editing?.tab !== 'preservations') return;
  const group = input?.closest('[data-preservation-group]');
  if (!group) return;
  const read = name => parseDateInput(group.querySelector(`[name="${name}"]`)?.value || '');
  const set = (name, value) => {
    const el = group.querySelector(`[name="${name}"]`);
    if (el) el.value = value ?? '';
  };
  const start = read('start_at');
  const deadline = read('deadline_at');
  const years = parseFloat(group.querySelector('[name="period_years"]')?.value || '');
  if (changed === 'start_at') {
    if (start && !Number.isNaN(years)) set('deadline_at', formatDateInput(addYears(start, years)));
    else if (start && deadline) set('period_years', (dateDiffDays(start, deadline) / 365).toFixed(2).replace(/\.?0+$/, ''));
  } else if (changed === 'deadline_at') {
    if (start && deadline) set('period_years', (dateDiffDays(start, deadline) / 365).toFixed(2).replace(/\.?0+$/, ''));
    else if (deadline && !Number.isNaN(years)) set('start_at', formatDateInput(addYears(deadline, -years)));
  } else if (changed === 'period_years') {
    if (!Number.isNaN(years) && start) set('deadline_at', formatDateInput(addYears(start, years)));
    else if (!Number.isNaN(years) && deadline) set('start_at', formatDateInput(addYears(deadline, -years)));
  }
}
function syncPreservationDates(changed) {
  if (state.editing?.tab !== 'preservations') return;
  const start = readNamedDate('start_at');
  const deadline = readNamedDate('deadline_at');
  const years = parseFloat($('drawerBody')?.querySelector('[name="period_years"]')?.value || '');
  if (changed === 'start_at') {
    if (start && !Number.isNaN(years)) setNamedInput('deadline_at', formatDateInput(addYears(start, years)));
    else if (start && deadline) setNamedInput('period_years', (dateDiffDays(start, deadline) / 365).toFixed(2).replace(/\.?0+$/, ''));
  } else if (changed === 'deadline_at') {
    if (start && deadline) setNamedInput('period_years', (dateDiffDays(start, deadline) / 365).toFixed(2).replace(/\.?0+$/, ''));
    else if (deadline && !Number.isNaN(years)) setNamedInput('start_at', formatDateInput(addYears(deadline, -years)));
  } else if (changed === 'period_years') {
    if (!Number.isNaN(years) && start) setNamedInput('deadline_at', formatDateInput(addYears(start, years)));
    else if (!Number.isNaN(years) && deadline) setNamedInput('start_at', formatDateInput(addYears(deadline, -years)));
  }
}
function syncAppealDates(changed) {
  if (state.editing?.tab !== 'appeals') return;
  const start = readNamedDate('start_at');
  const deadline = readNamedDate('deadline_at');
  const days = parseInt($('drawerBody')?.querySelector('[name="period_days"]')?.value || '', 10);
  if (changed === 'start_at') {
    if (start && !Number.isNaN(days)) setNamedInput('deadline_at', formatDateInput(addDays(start, days)));
    else if (start && deadline) setNamedInput('period_days', dateDiffDays(start, deadline));
  } else if (changed === 'deadline_at') {
    if (start && deadline) setNamedInput('period_days', dateDiffDays(start, deadline));
    else if (deadline && !Number.isNaN(days)) setNamedInput('start_at', formatDateInput(addDays(deadline, -days)));
  } else if (changed === 'period_days') {
    if (!Number.isNaN(days) && start) setNamedInput('deadline_at', formatDateInput(addDays(start, days)));
    else if (!Number.isNaN(days) && deadline) setNamedInput('start_at', formatDateInput(addDays(deadline, -days)));
  }
}
function collectForm() {
  const body = {};
  $('drawerBody').querySelectorAll('input, textarea, select').forEach(el => {
    if (!el.closest('.subrow, .contact-group')) body[el.name] = el.value;
  });
  return body;
}
function collectContactGroups(root = document) {
  const result = {};
  root.querySelectorAll('[data-contact-category]').forEach(category => {
    const key = category.dataset.contactCategory;
    result[key] = [...category.querySelectorAll('.contact-group')].map(group => ({
      groupId: group.dataset.contactGroupId || newContactGroupId(),
      roleType: group.querySelector('[name=contact_role_type]')?.value || '联系人',
      name: group.querySelector('[name=contact_name]')?.value.trim() || '',
      phone: group.querySelector('[name=contact_phone]')?.value.trim() || '',
      email: group.querySelector('[name=contact_email]')?.value.trim() || '',
      notes: group.querySelector('[name=contact_notes]')?.value.trim() || '',
    })).filter(contactGroupHasData);
  });
  return result;
}
function readContactDisplaySelections() {
  const result = {};
  seriesDetailContactDisplayColumns().forEach(column => { result[column.key] = []; });
  if (seriesDetailMappings().some(mapping => mapping.target_key === 'memo')) result.__memo__ = ['initialized'];
  document.querySelectorAll('[data-contact-display-column]:checked').forEach(input => {
    const columnKey = input.dataset.contactDisplayColumn || '';
    const groupId = input.dataset.contactGroupId || '';
    if (!columnKey || !groupId) return;
    if (!result[columnKey]) result[columnKey] = [];
    if (!result[columnKey].includes(groupId)) result[columnKey].push(groupId);
  });
  return result;
}
function serializeContactGroups(groups, target) {
  return CONTACT_CATEGORIES.filter(category => category.target === target).map(category => {
    const items = groups[category.key] || [];
    if (!items.length) return '';
    const content = items.map(item => `【联系人组】\n组ID：${item.groupId || newContactGroupId()}\n身份：${item.roleType || '联系人'}\n姓名：${item.name}\n电话：${item.phone}\n邮箱：${item.email}\n备注：${item.notes}`).join('\n\n');
    return `【${category.label}】\n${content}`;
  }).filter(Boolean).join('\n\n');
}
async function saveEditor() {
  const { tab, item } = state.editing;
  if (isOfflineReadonly()) {
    requireOnlineAction();
    return;
  }
  const meta = tabMeta[tab];
  const body = collectForm();
  if (tab === 'preservations') {
    const groups = collectPreservationGroups();
    if (!groups.length) {
      toast('请至少填写一组财产保全信息');
      return;
    }
    const common = { case_id: body.case_id || '', title: body.title || '' };
    for (let index = 0; index < groups.length; index += 1) {
      const payload = {...common, ...groups[index]};
      const isExisting = Boolean(item?.id) && index === 0;
      const url = isExisting ? `${meta.endpoint}/${item.id}` : meta.endpoint;
      await api(url, {
        method: isExisting ? 'PUT' : 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify(payload),
      });
    }
    toast(groups.length > 1 ? `已保存 ${groups.length} 组财产保全信息` : '已保存');
    await refreshAll();
    closeEditor();
    return;
  }
  if (tab === 'todos' && !body.remind_at) {
    toast('请先设置待办提醒时间');
    return;
  }
  const url = item?.id ? `${meta.endpoint}/${item.id}` : meta.endpoint;
  await api(url, { method: item?.id ? 'PUT' : 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
  toast('已保存');
  await refreshAll();
  closeEditor();
}
async function deleteItem(tab, id) {
  if (isOfflineReadonly() && tab !== 'cases') {
    requireOnlineAction();
    return;
  }
  const message = tab === 'cases'
    ? '确定删除该案件？删除后会进入垃圾站，关联开庭、财产保全、上诉/异议期也会从在办列表和日历中移除。'
    : '确定删除该记录？此操作会同步删除对应的日历事件。';
  openCaseActionDialog('delete', [Number(id)], message, tab);
}
function openCaseActionDialog(action, ids, message, tab='cases') {
  state.pendingCaseDelete = {action, tab, ids: (Array.isArray(ids) ? ids : [ids]).map(Number)};
  const title = $('caseDeleteDialogTitle'), description = $('caseDeleteDialogDescription');
  if (title) title.textContent = action === 'archive' || action === 'series_archive'
    ? '结案并归档？'
    : action === 'series_delete' ? '删除系列案件？'
    : action === 'series_child_archive' ? '结案子案？'
    : action === 'series_child_restore' ? '恢复子案？'
    : action === 'purge' ? '彻底删除案件？' : (tab === 'cases' ? '删除案件？' : '删除记录？');
  if (description) description.textContent = message;
  const confirmButton = $('confirmCaseDeleteButton');
  if (confirmButton) confirmButton.textContent = action === 'archive' || action === 'series_archive' || action === 'series_child_archive' ? '确认结案' : action === 'series_child_restore' ? '确认恢复' : '确认删除';
  $('caseDeleteDialogMask')?.classList.add('show');
  setTimeout(() => $('confirmCaseDeleteButton')?.focus(), 0);
}
function closeCaseDeleteDialog() {
  $('caseDeleteDialogMask')?.classList.remove('show');
  state.pendingCaseDelete = null;
}
async function confirmCaseDelete() {
  const pending = state.pendingCaseDelete;
  if (!pending) return closeCaseDeleteDialog();
  const button = $('confirmCaseDeleteButton');
  if (button) { button.disabled = true; button.textContent = '处理中…'; }
  const {action, tab, ids} = pending;
  try {
  if (action === 'archive') {
    closeCaseDeleteDialog();
    await executeBulkArchiveCases(ids);
    return;
  }
  if (action === 'series_archive') {
    closeCaseDeleteDialog();
    await archiveSeries(false, true);
    return;
  }
  if (action === 'series_delete') {
    await api(`/api/case-manager/series/${ids[0]}`, {method:'DELETE'});
    closeCaseDeleteDialog();
    closeSeriesWorkspace();
    await refreshAll();
    toast('系列案件已移入垃圾站');
    return;
  }
  if (action === 'series_child_archive' || action === 'series_child_restore') {
    closeCaseDeleteDialog();
    await setSeriesChildStatus(ids[0], action === 'series_child_archive' ? 'archive' : 'restore', true);
    return;
  }
  if (action === 'purge') {
    await api(`/api/case-manager/cases/${ids[0]}/purge`, {method:'POST'});
    closeCaseDeleteDialog();
    toast('已彻底删除');
    await refreshAll();
    return;
  }
  if (isOfflineReadonly() && tab === 'cases') {
    if (ids.length > 1) ids.forEach(id => enqueueCaseOp({ action: 'delete', id, payload: {} }));
    else enqueueCaseOp({ action: 'delete', id: ids[0], payload: {} });
    closeCaseDeleteDialog();
    toast('案件已离线删除，联网后自动同步');
    await refreshAll(false);
    return;
  }
  if (ids.length > 1 && tab === 'cases') await api('/api/case-manager/cases/bulk-delete', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ ids }) });
  else await api(`${tabMeta[tab].endpoint}/${ids[0]}`, { method: 'DELETE' });
  closeCaseDeleteDialog();
  toast(tab === 'cases' ? (ids.length > 1 ? `已将 ${ids.length} 个案件移入垃圾站` : '已移入垃圾站') : '已删除');
  await refreshAll();
  } catch (e) {
    if (button) {
      button.disabled = false;
      button.textContent = action === 'archive' || action === 'series_archive' || action === 'series_child_archive' ? '确认结案' : action === 'series_child_restore' ? '确认恢复' : '确认删除';
    }
    toast(e.message || '删除失败');
  }
}

function calendarRange() {
  const base = state.caseCalendarDate;
  const first = new Date(base.getFullYear(), base.getMonth(), 1);
  const gridStart = new Date(first);
  gridStart.setDate(first.getDate() - first.getDay());
  const last = new Date(base.getFullYear(), base.getMonth() + 1, 0);
  const gridEnd = new Date(last);
  gridEnd.setDate(last.getDate() + (6 - last.getDay()));
  return { start: formatDateInput(gridStart), end: formatDateInput(gridEnd) };
}
async function loadCaseCalendar() {
  const types = Object.entries(state.caseCalendarTypes).filter(([, on]) => on).map(([type]) => type).join(',');
  const range = calendarRange();
  const data = await api(`/api/case-manager/events?types=${encodeURIComponent(types)}&start=${range.start}&end=${range.end}&limit=2000`);
  let events = data.items || [];
  if (state.hideOverdue) events = events.filter(event => !isEventOverdue(event));
  state.caseCalendarEvents = groupSeriesCalendarEvents(events);
  renderCaseCalendar();
}
function groupSeriesCalendarEvents(items) {
  const ordinary=[]; const groups=new Map();
  items.forEach(item=>{if(!item.series_id){ordinary.push(item);return;}const key=`${item.series_id}|${dateOnly(item.due_at)}|${item.item_type}`;if(!groups.has(key))groups.set(key,{...item,id:`series-calendar-${key}`,title:item.series_title,series_group:true,group_items:[],group_date:dateOnly(item.due_at)});groups.get(key).group_items.push(item);});
  return [...ordinary,...groups.values()].map(item=>item.series_group?{...item,group_count:item.group_items.length,detail:item.group_items.map(x=>`${x.series_code||''} ${x.child_display_name||''}：${x.event_type||''}`).join('\n')}:item);
}
function renderCaseCalendar() {
  const monthText = `${state.caseCalendarDate.getFullYear()}年${state.caseCalendarDate.getMonth() + 1}月`;
  const eventCount = (state.caseCalendarEvents || []).length;
  $('content').innerHTML = `<div class="case-calendar">
    <section class="calendar-board">
      <div class="calendar-head">
        <div class="calendar-heading">
          <div class="calendar-title">案件日历</div>
          <span class="calendar-month">${esc(monthText)}</span>
        </div>
        <div class="calendar-toolbar">
          <div class="calendar-month-nav" aria-label="切换月份">
            <button class="btn calendar-arrow-btn" onclick="moveCaseCalendarMonth(-1)" aria-label="上月" title="上月"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M10.25 3.5 5.75 8l4.5 4.5"/></svg></button>
            <button class="btn calendar-today-btn" onclick="goTodayCaseCalendar()">今天</button>
            <button class="btn calendar-arrow-btn" onclick="moveCaseCalendarMonth(1)" aria-label="下月" title="下月"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m5.75 3.5 4.5 4.5-4.5 4.5"/></svg></button>
          </div>
          <div class="calendar-type-filters">${calendarTypeToggles()}</div>
          ${hideOverdueToggle()}
          <button class="btn calendar-sync-entry" type="button" onclick="switchTab('calendar')" title="设置 iCloud 日历并同步案件事项">
            <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M4.2 11.8A3.2 3.2 0 014 5.4a4.2 4.2 0 018-1.1 3 3 0 01-.1 6H9.8" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/><path d="M8 8v5m0 0l-1.8-1.8M8 13l1.8-1.8" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>
            日历同步
          </button>
        </div>
      </div>
      ${calendarSummaryHtml()}
      <div class="mobile-calendar-list">${mobileCalendarListHtml()}</div>
      ${calendarMonthGrid()}
    </section>
    <aside class="agenda-board">
      <div class="calendar-head agenda-head">
        <div class="calendar-heading"><div class="calendar-title">日程清单</div></div>
        <span class="agenda-count">${eventCount} 项</span>
      </div>
      <div class="agenda-list">${agendaListHtml()}</div>
    </aside>
  </div>`;
}
function calendarTypeToggles() {
  return [
    ['todo', '待办'],
    ['hearing', '开庭'],
    ['preservation', '财产保全'],
    ['appeal', '上诉/异议'],
  ].map(([type, label]) => `<label class="check-pill"><input type="checkbox" ${state.caseCalendarTypes[type] ? 'checked' : ''} onchange="state.caseCalendarTypes.${type}=this.checked; loadCaseCalendar()">${label}</label>`).join('');
}
function calendarSummaryHtml() {
  const year = state.caseCalendarDate.getFullYear();
  const month = state.caseCalendarDate.getMonth();
  const counts = { todo: 0, hearing: 0, preservation: 0, appeal: 0 };
  (state.caseCalendarEvents || []).forEach(event => {
    const d = parseDateLoose(event.due_at);
    if (!d || d.getFullYear() !== year || d.getMonth() !== month) return;
    const type = event.item_type || event.event_type;
    if (counts[type] !== undefined) counts[type] += Number(event.group_count || 1);
  });
  return `<div class="calendar-summary-strip">
    <div class="calendar-summary-card todo"><span>本月待办</span><strong>${counts.todo}</strong></div>
    <div class="calendar-summary-card hearing"><span>本月开庭</span><strong>${counts.hearing}</strong></div>
    <div class="calendar-summary-card preservation"><span>保全截止</span><strong>${counts.preservation}</strong></div>
    <div class="calendar-summary-card appeal"><span>上诉/异议</span><strong>${counts.appeal}</strong></div>
  </div>`;
}
function moveCaseCalendarMonth(delta) {
  state.caseCalendarDate = new Date(state.caseCalendarDate.getFullYear(), state.caseCalendarDate.getMonth() + delta, 1);
  loadCaseCalendar();
}
function goTodayCaseCalendar() {
  state.caseCalendarDate = new Date();
  loadCaseCalendar();
}
function eventsByDate() {
  return (state.caseCalendarEvents || []).reduce((acc, event) => {
    const key = dateOnly(event.due_at);
    if (!acc[key]) acc[key] = [];
    acc[key].push(event);
    return acc;
  }, {});
}
function calendarMonthGrid() {
  const weekdays = ['日','一','二','三','四','五','六'].map(d => `<div class="weekday">${d}</div>`).join('');
  const byDate = eventsByDate();
  const base = state.caseCalendarDate;
  const first = new Date(base.getFullYear(), base.getMonth(), 1);
  const start = new Date(first);
  start.setDate(first.getDate() - first.getDay());
  const today = formatDateInput(new Date());
  const cells = [];
  for (let i = 0; i < 42; i++) {
    const day = new Date(start);
    day.setDate(start.getDate() + i);
    const key = formatDateInput(day);
    const events = byDate[key] || [];
    const cls = [day.getMonth() !== base.getMonth() ? 'muted' : '', key === today ? 'today' : ''].filter(Boolean).join(' ');
    cells.push(`<div class="day-cell ${cls}">
      <div class="day-num">${day.getDate()}</div>
      ${events.slice(0, 4).map(event => eventPill(event)).join('')}
      ${events.length > 4 ? `<button class="cal-event appeal" onclick="openDayAgenda('${key}')">还有 ${events.length - 4} 项</button>` : ''}
    </div>`);
  }
  return `<div class="calendar-grid">${weekdays}${cells.join('')}</div>`;
}
function eventPill(event) {
  const urgency = event.days_left !== null && event.days_left !== undefined && event.days_left <= 3 ? ' urgent' : '';
  return `<button class="cal-event ${event.item_type}${urgency}" title="${esc(event.title)}" onclick='openCalendarEvent(${JSON.stringify(event).replace(/'/g, '&#39;')})'>${esc(eventShortLabel(event))}</button>`;
}
function eventShortLabel(event) {
  const prefix = { todo: '待办', hearing: '开庭', preservation: '保全', appeal: '期限' }[event.item_type] || '事项';
  return `${prefix}${event.message_created_mode === 'auto' ? ' · 短信自动' : event.source_message_id ? ' · 短信' : ''}${event.series_group ? ` · ${event.group_count}项` : ''} ${event.title || ''}`;
}
function daysLeftText(days) {
  if (days === null || days === undefined) return '';
  if (days < 0) return `已过 ${Math.abs(days)} 天`;
  if (days === 0) return '今天';
  return `还有 ${days} 天`;
}
function agendaRemainingDaysHtml(days) {
  if (days === null || days === undefined || days === '') return '';
  const value = Number(days);
  if (!Number.isFinite(value)) return esc(daysLeftText(days));
  if (value < 0) {
    return `<span class="remaining-days remaining-days-overdue" title="已过期 ${Math.abs(value)} 天">已过 <span class="remaining-days-number">${Math.abs(value)}</span> 天</span>`;
  }
  if (value === 0) {
    return '<span class="remaining-days remaining-days-urgent" title="今天截止"><span class="remaining-days-number">今天</span>截止</span>';
  }
  const urgencyClass = value <= 3 ? ' remaining-days-urgent' : value <= 14 ? ' remaining-days-soon' : '';
  return `<span class="remaining-days${urgencyClass}" title="还有 ${value} 天">还有 <span class="remaining-days-number">${value}</span> 天</span>`;
}
function agendaListHtml() {
  const events = [...(state.caseCalendarEvents || [])].sort((a, b) => String(a.due_at).localeCompare(String(b.due_at)));
  if (!events.length) return '<div class="empty">当前筛选下暂无日历事项</div>';
  const tagClass = event => event.item_type === 'todo' ? 'success' : event.item_type === 'preservation' ? 'success' : event.item_type === 'appeal' ? '' : 'danger';
  const attentionClass = event => event.days_left < 0 ? 'overdue' : event.days_left <= 3 ? 'due-soon' : event.item_type === 'todo' ? 'todo' : '';
  return events.map(event => `<button class="agenda-item ${event.item_type || ''} ${attentionClass(event)}" onclick='openCalendarEvent(${JSON.stringify(event).replace(/'/g, '&#39;')})'>
    <div class="agenda-item-title"><span class="tag ${tagClass(event)}">${esc(event.label)}</span>${messageSourceBadge(event)} ${esc(event.title || '')}</div>
    <div class="agenda-meta"><span>${esc(fmt(event.due_at))}</span><span class="days-left">${agendaRemainingDaysHtml(event.days_left)}</span></div>
  </button>`).join('');
}
function mobileCalendarListHtml() {
  const base = state.caseCalendarDate;
  const weekdays = ['日', '一', '二', '三', '四', '五', '六'];
  const events = [...(state.caseCalendarEvents || [])]
    .filter(event => {
      const date = parseDateLoose(event.due_at);
      return date && date.getFullYear() === base.getFullYear() && date.getMonth() === base.getMonth();
    })
    .sort((a, b) => String(a.due_at).localeCompare(String(b.due_at)));
  if (!events.length) return '<div class="empty mobile-calendar-empty">本月暂无日程事项</div>';
  const grouped = new Map();
  events.forEach(event => {
    const key = dateOnly(event.due_at);
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(event);
  });
  const typeLabels = { todo: '待办', hearing: '开庭', preservation: '保全', appeal: '上诉/异议' };
  return [...grouped.entries()].map(([date, items]) => {
    const day = parseDateLoose(date);
    const dayText = day ? `${day.getDate()}日 · 周${weekdays[day.getDay()]}` : date;
    return `<section class="mobile-calendar-day">
      <div class="mobile-calendar-day-head"><strong>${esc(dayText)}</strong><span>${items.length} 项</span></div>
      <div class="mobile-calendar-events">${items.map(event => {
        const attention = event.days_left < 0 ? ' overdue' : event.days_left <= 3 ? ' due-soon' : '';
        const detail = String(event.detail || '').trim();
        return `<button class="mobile-calendar-event ${esc(event.item_type || '')}${attention}" onclick='openCalendarEvent(${JSON.stringify(event).replace(/'/g, '&#39;')})'>
          <div class="mobile-calendar-event-head"><span class="tag">${esc(typeLabels[event.item_type] || event.label || '事项')}</span>${messageSourceBadge(event)}<span class="mobile-calendar-event-time">${esc(fmt(event.due_at).slice(11) || '全天')}</span></div>
          <strong>${esc(event.title || '未命名案件')}</strong>
          ${detail ? `<span class="mobile-calendar-event-detail">${esc(detail)}</span>` : ''}
          <span class="mobile-calendar-event-due">${agendaRemainingDaysHtml(event.days_left)}</span>
        </button>`;
      }).join('')}</div>
    </section>`;
  }).join('');
}
function openDayAgenda(date) {
  const events = (eventsByDate()[date] || []);
  $('drawerTitle').textContent = `${date} 日历事项`;
  $('drawerBody').innerHTML = `<section class="detail-section"><h3>事项清单</h3><div class="record-list">${events.map((event, index) => `<article class="record-card"><div class="record-card-head"><span>${index + 1}. ${esc(event.label)} ${esc(event.title || '')}</span><button class="btn" onclick='openCalendarEvent(${JSON.stringify(event).replace(/'/g, '&#39;')})'>查看</button></div></article>`).join('')}</div></section>`;
  $('drawerFoot').innerHTML = `<button class="btn" onclick="closeEditor()">关闭</button>`;
  $('drawerMask').classList.add('show');
  $('drawer').classList.add('show');
  $('drawer').classList.add('detail-mode');
}
function openCalendarEvent(event) {
  if (event.series_group) {
    const isHearingGroup = event.item_type === 'hearing';
    $('drawerTitle').textContent = `${event.series_title || event.title} · ${event.group_date} · ${event.group_count}项`;
    $('drawerBody').innerHTML = `<section class="detail-section"><h3>${esc(event.label)}汇总</h3><div class="record-list">${(event.group_items||[]).map((entry,index)=>`<article class="record-card"><div class="record-card-head"><span>${index+1}. ${esc(entry.series_code||'')} ${esc(entry.child_display_name||'')}</span></div><dl class="record-fields"><dt>事项</dt><dd>${esc(entry.event_type||'')}</dd><dt>时间</dt><dd>${esc(fmt(entry.due_at))}</dd><dt class="full-label">内容</dt><dd class="full-value">${esc(entry.detail||'')}</dd></dl>${isHearingGroup?`<div class="series-group-contact-slot" data-slot-token="calendar-series-${Number(event.series_id||0)}-${Number(entry.case_id||0)}" data-contact-case-id="${Number(entry.case_id||0)}"></div>`:''}</article>`).join('')}</div></section>`;
    $('drawerFoot').innerHTML = `<button class="btn" onclick="closeEditor()">关闭</button><button class="btn primary" onclick="closeEditor();openSeriesWorkspace(${Number(event.series_id)})">打开系列案件</button>`;
    $('drawerMask').classList.add('show'); $('drawer').classList.add('show','detail-mode');
    if (isHearingGroup) loadSeriesGroupChildContacts(event);
    return;
  }
  $('drawerTitle').textContent = `${event.label}详情`;
  const isHearing = event.item_type === 'hearing';
  const hearingContactHtml = isHearing
    ? `<div id="hearingContactSection" data-contact-token="calendar-hearing-${Number(event.id || 0)}" data-contact-case-id="${Number(event.case_id || 0)}"><section class="detail-section contact-section"><h3>联系与备忘</h3><div class="contact-hub"><div class="contact-hub-grid"><span class="contact-empty">正在加载联系方式…</span></div></div></section></div>`
    : detailSection('联系方式', [
      ['裁判机关经办人联系方式', event.court_contact, true],
      ['委托方及对方联系方式', event.party_contact, true],
    ]);
  $('drawerBody').innerHTML = `
    ${detailSection('重要信息', [
      ['案件名称', event.title],
      ['案件类型', event.case_type],
      ['事项类型', `${event.label}${event.event_type ? `：${event.event_type}` : ''}`],
      ['时间', fmt(event.due_at)],
      ['剩余时间', daysLeftText(event.days_left)],
      ['事项内容', event.detail, true],
      ['来源', event.source_message_id ? (event.message_created_mode === 'auto' ? '司法短信自动创建' : '司法短信人工确认') : '人工录入'],
    ])}
    ${miniTable('案号及受理机构', ['案号','受理机构'], caseNoCourtRows(event.case_no, event.court))}
    ${hearingContactHtml}
  `;
  if (isHearing) loadHearingContactSection(event);
  $('drawerFoot').innerHTML = `
    <button class="btn" onclick="closeEditor()">关闭</button>
    ${event.source_message_id ? `<button class="btn" onclick="closeEditor();switchTab('judicialMessages');setTimeout(()=>openJudicialMessage(${Number(event.source_message_id)}),80)">查看原短信</button>` : ''}
    <button class="btn primary" onclick="openDetail('cases', ${event.case_id})">打开案件</button>
  `;
  $('drawerMask').classList.add('show');
  $('drawer').classList.add('show');
  $('drawer').classList.add('detail-mode');
  $('drawer').classList.remove('edit-wide');
}

function renderImport() {
  $('content').innerHTML = `<div class="import-grid">
    <div class="import-panel">
      <h3>导入中心</h3>
      <p class="import-help">支持导入简道云导出的案件信息、开庭提醒、财产保全、上诉/异议期 Excel。请先预览，确认识别类型、数量和样例记录无误后再导入。</p>
      <input type="file" id="importFiles" multiple accept=".xlsx,.xls" onchange="state.selectedFiles=this.files; updateSelectedImportFiles()">
      <div class="import-files" id="selectedImportFiles">尚未选择文件</div>
      <div class="filters">
        <button class="btn" onclick="previewImport()">预览</button>
        <button class="btn primary" onclick="applyImport()">确认导入</button>
      </div>
    </div>
    <div class="preview-box import-preview" id="importPreview">
      <div class="empty">选择 Excel 后点击“预览”，这里会显示识别结果、风险提示和样例记录。</div>
    </div>
  </div>`;
}
function updateSelectedImportFiles() {
  const files = [...(state.selectedFiles || [])];
  const target = $('selectedImportFiles');
  if (!target) return;
  if (!files.length) {
    target.textContent = '尚未选择文件';
    return;
  }
  target.innerHTML = files.map(file => `<div class="import-file"><strong>${esc(file.name)}</strong><span>${formatFileSize(file.size)}</span></div>`).join('');
}
function formatFileSize(size) {
  if (!size && size !== 0) return '';
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}
function formDataFiles() {
  if (!state.selectedFiles || !state.selectedFiles.length) throw new Error('请选择 Excel 文件');
  const fd = new FormData();
  [...state.selectedFiles].forEach(file => fd.append('files', file));
  return fd;
}
async function previewImport() {
  try {
    const data = await api('/api/case-manager/import/preview', { method: 'POST', body: formDataFiles() });
    $('importPreview').innerHTML = renderImportResult(data, false);
  } catch (e) { toast(e.message); }
}
async function applyImport() {
  try {
    const data = await api('/api/case-manager/import/apply', { method: 'POST', body: formDataFiles() });
    $('importPreview').innerHTML = renderImportResult(data, true);
    toast('导入完成');
    await loadDashboard();
  } catch (e) { toast(e.message); }
}
function renderImportResult(data, applied) {
  const s = data.summary || {};
  const analysis = data.analysis || {};
  const total = (s.cases || 0) + (s.hearings || 0) + (s.preservations || 0) + (s.appeals || 0);
  const missing = importTypes().reduce((sum, type) => sum + ((analysis[type.key] || {}).missing_required || 0), 0);
  const duplicates = importTypes().reduce((sum, type) => sum + ((analysis[type.key] || {}).duplicate_in_file || 0), 0);
  const existing = importTypes().reduce((sum, type) => sum + ((analysis[type.key] || {}).existing_matches || 0), 0);
  const statusTitle = applied ? '导入完成' : (total ? '可以导入，请核对下方明细' : '未识别到可导入数据');
  const statusText = applied
    ? '系统已按自然键去重处理；相同案件或相同提醒会更新合并，不会重复生成。'
    : (missing ? '存在缺少关键字段的记录，请先核对样例和原始 Excel。' : '已识别到结构化记录，建议重点核对案件名称、日期、案号和受理机构。');
  return `<div class="import-status">
      <div><strong>${esc(statusTitle)}</strong><p>${esc(statusText)}</p></div>
      <div class="import-issues">
        ${missing ? `<span class="tag danger">缺少关键字段 ${missing}</span>` : '<span class="tag success">关键字段完整</span>'}
        ${duplicates ? `<span class="tag">文件内疑似重复 ${duplicates}</span>` : '<span class="tag success">未发现文件内重复</span>'}
        ${existing ? `<span class="tag">库内已存在/将更新 ${existing}</span>` : '<span class="tag">库内匹配 0</span>'}
      </div>
    </div>
    <div class="import-metrics">
      ${importMetric('案件信息', s.cases || 0, analysis.cases)}
      ${importMetric('开庭提醒', s.hearings || 0, analysis.hearings)}
      ${importMetric('财产保全', s.preservations || 0, analysis.preservations)}
      ${importMetric('上诉/异议', s.appeals || 0, analysis.appeals)}
    </div>
    ${renderImportFileSection(data.files || [])}
    ${importTypes().map(type => renderImportSampleSection(type, analysis[type.key]?.samples || data.samples?.[type.key] || [])).join('')}`;
}
function importTypes() {
  return [
    { key: 'cases', label: '案件信息', columns: [['title','案件名称'], ['case_type','案件类型'], ['parties','当事人'], ['case_numbers','案号/机构']] },
    { key: 'hearings', label: '开庭提醒', columns: [['title','案件名称'], ['reminder_type','类型'], ['hearing_at','开庭时间'], ['location','地点'], ['case_no','案号'], ['court','受理机构']] },
    { key: 'preservations', label: '财产保全', columns: [['title','案件名称'], ['preservation_type','类型'], ['start_at','起算'], ['deadline_at','截止'], ['period_years','期限'], ['asset_content','保全内容']] },
    { key: 'appeals', label: '上诉/异议', columns: [['title','案件名称'], ['appeal_type','类型'], ['start_at','起算'], ['period_days','期限'], ['deadline_at','截止'], ['case_no','案号'], ['court','受理机构']] },
  ];
}
function importMetric(label, count, stat = {}) {
  return `<div class="import-metric">
    <span>${esc(label)}</span>
    <strong>${count || 0}</strong>
    <small>唯一 ${stat.unique ?? count ?? 0} · 已存在 ${stat.existing_matches || 0} · 缺字段 ${stat.missing_required || 0}</small>
  </div>`;
}
function renderImportFileSection(files) {
  return `<section class="import-section">
    <div class="import-section-head"><h4>文件识别结果</h4><span class="tag">${files.length} 个工作簿</span></div>
    <div class="import-table-wrap"><table class="import-table"><thead><tr><th>文件</th><th>工作表</th><th>识别类型</th><th>解析数量</th></tr></thead><tbody>
      ${files.length ? files.map(file => `<tr>
        <td>${esc(file.name)}</td>
        <td>${esc(file.sheet)}</td>
        <td><span class="tag">${esc(importKindLabel(file.kind))}</span></td>
        <td>${importCountSummary(file.counts || {})}</td>
      </tr>`).join('') : '<tr><td colspan="4" class="empty">暂无文件识别结果</td></tr>'}
    </tbody></table></div>
  </section>`;
}
function importKindLabel(kind) {
  return ({ cases: '案件信息', hearings: '开庭提醒', preservations: '财产保全', appeals: '上诉/异议' })[kind] || kind || '未识别';
}
function importCountSummary(counts) {
  return importTypes().map(type => counts[type.key] ? `${type.label} ${counts[type.key]}` : '').filter(Boolean).join('，') || '0';
}
function renderImportSampleSection(type, samples) {
  return `<section class="import-section">
    <div class="import-section-head">
      <h4>${esc(type.label)}样例</h4>
      <span class="tag">${samples.length ? `显示前 ${samples.length} 条` : '暂无样例'}</span>
    </div>
    <div class="import-table-wrap"><table class="import-table"><thead><tr>${type.columns.map(([, label]) => `<th>${esc(label)}</th>`).join('')}</tr></thead><tbody>
      ${samples.length ? samples.map(item => `<tr>${type.columns.map(([field]) => `<td>${formatImportCell(item, field)}</td>`).join('')}</tr>`).join('') : `<tr><td colspan="${type.columns.length}" class="empty">未解析到${esc(type.label)}数据</td></tr>`}
    </tbody></table></div>
  </section>`;
}
function formatImportCell(item, field) {
  if (!item) return '';
  if (field === 'parties') {
    return esc((item.parties || []).slice(0, 5).map(p => `${p.role || ''}${p.name ? `：${p.name}` : ''}`).filter(Boolean).join('\n') || '-').replace(/\n/g, '<br>');
  }
  if (field === 'case_numbers') {
    return esc((item.case_numbers || []).slice(0, 5).map(n => `${n.number_type || ''} ${n.case_no || ''} ${n.court || ''}`.trim()).filter(Boolean).join('\n') || '-').replace(/\n/g, '<br>');
  }
  const value = item[field];
  if (value === null || value === undefined || value === '') return '<span style="color:var(--muted)">-</span>';
  return esc(String(value)).replace(/\n/g, '<br>');
}

function renderCalendar() {
  const settings = state.calendarSettings || state.dashboard?.calendar || {};
  const current = settings.calendar_name || '案件管理提醒';
  const options = Array.from(new Set([...(state.calendarOptions || [])].filter(Boolean)));
  const hasCurrent = options.includes(current);
  const riskyLocalDefault = current === '案件管理提醒';
  $('content').innerHTML = `<div class="calendar-page">
    <div class="calendar-sync-page-head">
      <div><strong>日历同步</strong><span>案件日历的 iCloud 同步设置</span></div>
      <button class="btn" type="button" onclick="switchTab('caseCalendar')">返回案件日历</button>
    </div>
    <div class="drop">
      <label>目标日历（iCloud）</label>
      <select id="calendarSelect">
        <option value="">请选择 iCloud 日历</option>
        ${options.map(name => `<option value="${esc(name)}" ${name === current ? 'selected' : ''}>${esc(name)}</option>`).join('')}
      </select>
      ${hasCurrent ? '' : `<div class="form-hint warn">当前设置“${esc(current)}”不在日历列表中，请先点击“读取日历”或在 macOS 日历 App 中创建该日历。</div>`}
      ${state.calendarWarning ? `<div class="form-hint warn">${esc(state.calendarWarning)}</div>` : ''}
      ${riskyLocalDefault ? `<div class="form-hint warn">你截图里的“案件管理提醒”在 Mac 分组下，选择它只会同步成本地日程。建议选择你在 iCloud 分组下新建的“案件管理系统-iCloud”。</div>` : ''}
      <label><input type="checkbox" id="calendarEnabled" ${settings.enabled ? 'checked' : ''}> 自动同步</label>
      <div class="filters">
        <button class="btn" id="loadCalendarBtn" onclick="loadCalendar(true)">读取日历</button>
        <button class="btn" id="saveCalendarBtn" onclick="saveCalendarSettings()">保存设置</button>
        <button class="btn primary" id="syncCalendarBtn" onclick="syncCalendar()">立即同步</button>
      </div>
    </div>
    <div class="preview-box">
      <h3>提醒规则</h3>
      <div class="calendar-rule-grid">
        ${calendarRuleRow('hearing', '开庭', settings)}
        ${calendarRuleRow('preservation', '财产保全', settings)}
        ${calendarRuleRow('appeal', '上诉/异议', settings)}
      </div>
      <p class="calendar-note">请在 macOS 日历 App 的 iCloud 分组下创建或选择目标日历；本页不会自动创建“在我的 Mac 上”的本地日历。仅同步未超过截止期限/开庭时间的事项。</p>
      <div id="calendarResult" class="calendar-status">${renderCalendarStatus()}</div>
    </div>
  </div>`;
}
function renderCalendarStatus() {
  const result = state.calendarLastResult;
  if (!result) return '<div class="calendar-status-card"><div class="calendar-status-head">同步状态</div><div style="color:var(--muted)">尚未开始同步。读取 iCloud 日历后，选择目标日历并点击“立即同步”。</div></div>';
  const details = result.details || [];
  const rows = details.slice(0, 160).map(item => `<tr>
    <td><span class="sync-state ${esc(item.status || '')}">${syncStatusText(item.status)}</span></td>
    <td>${esc(item.title || '')}</td>
    <td>${esc(fmt(item.due_at || ''))}</td>
    <td>${esc(item.message || '')}</td>
  </tr>`).join('');
  return `<div class="calendar-status-card">
    <div class="calendar-status-head"><span>${esc(result.title || '同步结果')}</span><span>${esc(result.calendar_name || '')}</span></div>
    <div class="calendar-sync-summary">
      <span class="tag">成功 ${result.synced || 0}</span>
      <span class="tag">跳过 ${result.skipped || 0}</span>
      <span class="tag">失败 ${result.failed || 0}</span>
      <span class="tag">合计 ${details.length || 0}</span>
    </div>
    ${details.length ? `<div class="calendar-sync-details" style="margin-top:10px"><table><thead><tr><th style="width:72px">状态</th><th>事项</th><th style="width:132px">时间</th><th>结果</th></tr></thead><tbody>${rows}</tbody></table></div>` : ''}
  </div>`;
}
function syncStatusText(status) {
  return status === 'synced' ? '成功' : status === 'skipped' ? '跳过' : status === 'failed' ? '失败' : '处理中';
}
function reminderDaysText(settings, key, fallback) {
  const value = settings?.[`${key}_reminder_days`];
  if (Array.isArray(value)) return value.join(',');
  if (typeof value === 'string' && value.trim()) {
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) return parsed.join(',');
    } catch (e) {}
    return value;
  }
  return fallback;
}
function calendarRuleRow(key, label, settings) {
  const fallbackDays = key === 'preservation' ? '45,30,15,10,5' : '30,15,10,5';
  const time = settings?.[`${key}_reminder_time`] || '09:00';
  return `<div class="calendar-rule-row">
    <strong>${esc(label)}</strong>
    <label>提前天数<input class="input" id="${key}ReminderDays" value="${esc(reminderDaysText(settings, key, fallbackDays))}" placeholder="${fallbackDays}"></label>
    <label>提醒时间<input class="input" id="${key}ReminderTime" type="time" value="${esc(time)}"></label>
  </div>`;
}
async function loadCalendar(force = false) {
  renderCalendar();
  if (state.calendarsLoaded && !force) return;
  setCalendarBusy('load', true, '正在读取 iCloud 日历...');
  try {
    const data = await api('/api/case-manager/calendar/calendars');
    state.calendarOptions = data.calendars || [];
    state.calendarDetails = data.calendar_details || [];
    state.calendarSettings = data.settings || {};
    state.calendarWarning = data.warning || '';
    state.calendarIcloudVerified = !!data.icloud_verified;
    state.calendarLastResult = {
      title: data.error ? '读取日历失败' : '读取日历完成',
      calendar_name: data.source || 'iCloud',
      synced: 0,
      skipped: 0,
      failed: data.error ? 1 : 0,
      details: data.error
        ? [{status: 'failed', title: '读取 iCloud 日历', message: data.error}]
        : [{status: 'synced', title: `已读取 ${state.calendarOptions.length} 个日历`, message: data.warning || (state.calendarOptions.join('、') || '未读取到日历')}],
    };
    renderCalendar();
    state.calendarsLoaded = true;
  } catch (e) {
    state.calendarLastResult = { title: '读取日历失败', failed: 1, details: [{status: 'failed', title: '读取 iCloud 日历', message: e.message}] };
    renderCalendar();
  } finally {
    setCalendarBusy('load', false);
  }
}
function collectCalendarSettings() {
  const calendarName = $('calendarSelect')?.value || '';
  if (!calendarName) throw new Error('请先选择 iCloud 分组下的目标日历。你截图里的“案件管理提醒”位于 Mac 分组，不会同步到苹果设备。');
  if (calendarName === '案件管理提醒') {
    throw new Error('根据你的截图，“案件管理提醒”位于 Mac 分组下。请改选 iCloud 分组下的“案件管理系统-iCloud”，避免继续同步成本地日程。');
  }
  return {
    calendar_name: calendarName,
    enabled: $('calendarEnabled').checked,
    hearing_reminder_days: $('hearingReminderDays').value,
    hearing_reminder_time: $('hearingReminderTime').value,
    preservation_reminder_days: $('preservationReminderDays').value,
    preservation_reminder_time: $('preservationReminderTime').value,
    appeal_reminder_days: $('appealReminderDays').value,
    appeal_reminder_time: $('appealReminderTime').value,
  };
}
function setCalendarBusy(kind, busy, text = '') {
  const ids = ['loadCalendarBtn', 'saveCalendarBtn', 'syncCalendarBtn'];
  ids.forEach(id => { const el = $(id); if (el) el.disabled = busy; });
  if (text && $('calendarResult')) {
    state.calendarLastResult = { title: text, synced: 0, skipped: 0, failed: 0, details: [{status: 'pending', title: text, message: '请稍候'}] };
    $('calendarResult').innerHTML = renderCalendarStatus();
  }
}
async function saveCalendarSettings() {
  if (!requireOnlineAction()) return;
  try {
    const body = collectCalendarSettings();
    setCalendarBusy('save', true, '正在保存日历设置...');
    const data = await api('/api/case-manager/calendar/settings', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
    state.calendarSettings = data.settings || body;
    state.calendarLastResult = { title: '设置已保存', calendar_name: body.calendar_name, synced: 0, skipped: 0, failed: 0, details: [{status: 'synced', title: '日历设置', message: `目标日历：${body.calendar_name}`} ] };
    toast('已保存日历设置');
    await loadDashboard();
    renderCalendar();
  } catch (e) {
    state.calendarLastResult = { title: '保存设置失败', failed: 1, details: [{status: 'failed', title: '日历设置', message: e.message}] };
    renderCalendar();
  } finally {
    setCalendarBusy('save', false);
  }
}
async function syncCalendar() {
  if (!requireOnlineAction()) return;
  try {
    const body = collectCalendarSettings();
    setCalendarBusy('sync', true, '正在同步到 iCloud 日历...');
    const saved = await api('/api/case-manager/calendar/settings', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
    state.calendarSettings = saved.settings || body;
    const data = await api('/api/case-manager/calendar/sync', { method: 'POST' });
    state.calendarLastResult = { ...data, title: '同步完成' };
    renderCalendar();
  } catch (e) {
    state.calendarLastResult = { title: '同步失败', failed: 1, details: [{status: 'failed', title: 'iCloud 日历同步', message: e.message}] };
    renderCalendar();
  } finally {
    setCalendarBusy('sync', false);
  }
}

// ── 系列案件工作台 ─────────────────────────────────────────────
const SERIES_MODE_LABELS = { inherit:'继承', supplement:'补充', replace:'替换', not_applicable:'不适用' };
const SERIES_STATUS_LABELS = { active:'在办', archived:'已结案', deleted:'已删除' };
const SERIES_DEFAULT_COLUMNS = [
  {key:'series_code',label:'编号',field_type:'text',source:'builtin',width:92},
  {key:'display_name',label:'子案名称',field_type:'text',source:'builtin',width:210},
  {key:'clients',label:'委托人',field_type:'lookup',source:'clients',width:170},
  {key:'opponents',label:'对方当事人',field_type:'lookup',source:'opponents',width:190},
  {key:'case_type',label:'案由',field_type:'lookup',source:'case_types',width:170},
  {key:'case_no',label:'案号',field_type:'text',source:'builtin',width:165},
  {key:'court',label:'法院/仲裁委',field_type:'lookup',source:'courts',width:180},
  {key:'current_stage',label:'阶段',field_type:'lookup',source:'stages',width:120},
  {key:'other_differences',label:'差异',field_type:'textarea',source:'builtin',width:190},
  {key:'case_focus',label:'侧重点',field_type:'textarea',source:'builtin',width:180},
  {key:'memo',label:'备忘',field_type:'textarea',source:'builtin',width:180}
];
const SERIES_DETAIL_MAPPING_TARGETS = [
  {key:'parties.other', section:'当事人', label:'其他当事人'},
  {key:'contacts', section:'联系与备忘', label:'联系人组（详情 → 主表列）'},
  {key:'memo', section:'联系与备忘', label:'案件备忘（详情 → 主表列）'},
  {key:'case_type', section:'基础信息', label:'案件类型'},
  {key:'current_stage', section:'基础信息', label:'当前阶段'},
  {key:'case_no', section:'案号', label:'案号'},
  {key:'court', section:'案号', label:'受理机构'},
];
const SERIES_SOURCE_LABELS = {
  builtin:'案件基础字段', derived:'系统自动汇总', custom:'本系列自定义', clients:'关联委托人库',
  opponents:'关联对方当事人库', parties:'关联全部当事人库', case_types:'关联案由库', stages:'关联阶段库',
  courts:'关联法院/仲裁委库', party_roles:'关联诉讼地位库', number_types:'关联案号性质库'
};
function seriesColumnKindLabel(column={}) {
  if(column.semantic_type==='amount')return `金额列 · 自动汇总${column.currency?`（${column.currency}）`:''}`;
  return SERIES_SOURCE_LABELS[column.source]||'普通字段';
}
function seriesParseAmount(value){const raw=String(value??'').trim();if(!raw)return NaN;const negative=/^\(.*\)$/.test(raw);const match=raw.replace(/[，,\s]/g,'').match(/[-+]?\d+(?:\.\d+)?/);if(!match)return NaN;const amount=Number(match[0]);return negative&&amount>0?-amount:amount;}
let seriesEditorRowSeed = 0;
let seriesFilterOutsideHandler = null;
const seriesLookupTimers = new WeakMap();
function seriesLookupInput(id,value,kind,placeholder='搜索或直接输入') {
  return `<div class="lookup-field series-lookup-field"><input class="input" id="${id}" value="${esc(value||'')}" placeholder="${esc(placeholder)}" data-series-lookup="${esc(kind)}" autocomplete="off"><div class="lookup-results"></div></div>`;
}
function activateSeriesLookups(root=document) {
  root.querySelectorAll?.('[data-series-lookup]').forEach(input => {
    if (input.dataset.seriesLookupReady) return;
    input.dataset.seriesLookupReady = '1';
    input.addEventListener('focus',()=>loadSeriesLookupInput(input));
    input.addEventListener('input',()=>loadSeriesLookupInput(input));
    input.addEventListener('click',()=>loadSeriesLookupInput(input));
  });
}
function loadSeriesLookupInput(input) {
  clearTimeout(seriesLookupTimers.get(input));
  seriesLookupTimers.set(input,setTimeout(()=>loadSeriesLookup(input),120));
}
async function loadSeriesLookup(input) {
  const kind=input.dataset.seriesLookup; if(!kind)return;
  hideLookupResults();
  const q=String(input.value||'').split(/[、,，]/).pop().trim();
  try {
    const data=await api(`/api/case-manager/series-options?kind=${encodeURIComponent(kind)}&q=${encodeURIComponent(q)}&limit=80`);
    renderSeriesLookup(input,data.items||[],q,kind);
  } catch(e) {}
}
function renderSeriesLookup(input,items,query,kind) {
  const profileLike=kind==='clients'||kind==='opponents'||kind==='parties';
  const box=floatingLookupBox();
  box._lookupInput=input;
  if(profileLike){
    const profiles=(items||[]).filter(item=>item?.value||item?.label).slice(0,12);
    if(!profiles.length&&!query){box.classList.remove('show');box.innerHTML='';return;}
    box._profileItems=profiles;
    box._profileOnSelect=(profile,target)=>{ const row=target.closest('[data-series-party-row]'); const code=row?.querySelector('[data-party-code]'); if(code) code.value=profile.identity_code||''; };
    const optionHtml=profiles.map((profile,index)=>`<button class="lookup-option" type="button" onclick="selectProfileLookup(this,${index})"><strong>${esc(profile.label||profile.value)}</strong>${profile.meta?`<span>${esc(profile.meta)}</span>`:''}</button>`).join('');
    const createHtml=query?`<button class="lookup-option create-option" type="button" onclick="acceptLookupInput(this)"><strong>${esc('使用当前名称')}</strong><span>${esc(query)}</span></button>`:'';
    box.innerHTML=optionHtml+createHtml;
  } else {
    const values=(items||[]).map(item=>item.value||item.label||'').filter(Boolean).slice(0,12);
    if(!values.length&&!query){box.classList.remove('show');box.innerHTML='';return;}
    const optionHtml=values.map(value=>`<button class="lookup-option" type="button" onclick="selectLookupValue(this, '${encodeURIComponent(value)}')"><strong>${esc(value)}</strong></button>`).join('');
    const createHtml=query?`<button class="lookup-option create-option" type="button" onclick="acceptLookupInput(this)"><strong>${esc('使用当前输入并新建')}</strong><span>${esc(query)}</span></button>`:'';
    box.innerHTML=optionHtml+createHtml;
  }
  box.classList.add('show');
  positionFloatingLookup(input,box);
}
function seriesPartyRowHtml(party={},prefix='seriesForm') {
  const rowId=`${prefix}Party${++seriesEditorRowSeed}`; const group=party.party_group==='client'?'client':'other';
  return `<div class="series-party-row" data-series-party-row>
    <select class="input" data-party-group onchange="syncSeriesPartyLookup(this)"><option value="client" ${group==='client'?'selected':''}>委托人</option><option value="other" ${group==='other'?'selected':''}>其他当事人</option></select>
    ${seriesLookupInput(`${rowId}Role`,party.role||'', 'party_roles','诉讼地位')}
    ${seriesLookupInput(`${rowId}Name`,party.name||'', group==='client'?'clients':'opponents','点击选择或搜索名称')}
    <input class="input" data-party-code value="${esc(party.credit_code||'')}" placeholder="证件/信用代码">
    <button class="btn danger" type="button" onclick="this.closest('[data-series-party-row]').remove()">删除</button>
  </div>`;
}
function seriesPartyEditorHtml(items=[],id='seriesFormParties') {
  const rows=(items.length?items:[{party_group:'client',role:'委托人'}]).map(item=>seriesPartyRowHtml(item,id)).join('');
  return `<div class="series-party-editor" id="${id}">${rows}</div><button class="btn" type="button" style="margin-top:8px" onclick="addSeriesPartyRow('${id}')">＋ 添加当事人</button><span class="series-lookup-note">名称、诉讼地位均直接引用案件管理数据库；输入时可搜索，也可录入新名称。</span>`;
}
function addSeriesPartyRow(id,item={}) { const host=$(id);if(!host)return;host.insertAdjacentHTML('beforeend',seriesPartyRowHtml(item,id));activateSeriesLookups(host); }
function syncSeriesPartyLookup(select) { const row=select.closest('[data-series-party-row]');const input=row?.querySelector('[data-series-lookup="clients"],[data-series-lookup="opponents"]');if(!input)return;input.dataset.seriesLookup=select.value==='client'?'clients':'opponents';input.removeAttribute('data-series-lookup-ready');activateSeriesLookups(row); }
function collectSeriesPartyEditor(id) { return [...($(id)?.querySelectorAll('[data-series-party-row]')||[])].map(row=>({party_group:row.querySelector('[data-party-group]').value,role:row.querySelector('[data-series-lookup="party_roles"]')?.value.trim()||'',name:row.querySelector('[data-series-lookup="clients"],[data-series-lookup="opponents"]')?.value.trim()||'',credit_code:row.querySelector('[data-party-code]')?.value.trim()||''})).filter(item=>item.name||item.role); }
const SERIES_HASH_PREFIX = '#series/';
const initialSeriesViewState = (() => {
  const params = new URLSearchParams(location.search);
  const number = key => Math.max(0, Number(params.get(key) || 0));
  return {
    bodyScrollTop: number('series_body_scroll'),
    tableScrollTop: number('series_table_scroll_top'),
    tableScrollLeft: number('series_table_scroll_left')
  };
})();
let initialSeriesViewRestored = false;
let seriesViewStateTimer = null;
function seriesHashForState() {
  const id = state.seriesWorkspace?.id;
  if (!id) return '';
  return `${SERIES_HASH_PREFIX}${Number(id)}${state.seriesWorkspaceTab === 'public' ? '/public' : ''}`;
}
function notifyCaseManagerViewState() {
  if (!window.parent || window.parent === window) return;
  const table = document.querySelector('#seriesChildTableHost .series-table-wrap');
  window.parent.postMessage({
    type: 'caseManagerViewState',
    seriesId: Number(state.seriesWorkspace?.id || 0),
    seriesTab: state.seriesWorkspaceTab === 'public' ? 'public' : 'children',
    bodyScrollTop: Number($('seriesWorkspaceBody')?.scrollTop || 0),
    tableScrollTop: Number(table?.scrollTop || 0),
    tableScrollLeft: Number(table?.scrollLeft || 0)
  }, location.origin);
}
function syncSeriesTableStickyOffset() {
  const table = document.querySelector('#seriesChildTableHost .series-table-wrap');
  const tabs = document.querySelector('#seriesWorkspace .series-workspace-tabs');
  if (!table || !tabs) return;
  const tableRect = table.getBoundingClientRect();
  const tabsRect = tabs.getBoundingClientRect();
  let anchorBottom = tabsRect.bottom;
  const toolbar = document.querySelector('#seriesWorkspace .series-toolbar');
  if (toolbar) {
    const toolbarRect = toolbar.getBoundingClientRect();
    if (toolbarRect.height > 0 && toolbarRect.bottom > anchorBottom && toolbarRect.top < window.innerHeight) anchorBottom = toolbarRect.bottom;
  }
  const offset = Math.max(0, Math.ceil(anchorBottom - tableRect.top));
  table.style.setProperty('--series-table-sticky-top', `${offset}px`);
}
function scheduleSeriesViewStateSync() {
  syncSeriesTableStickyOffset();
  clearTimeout(seriesViewStateTimer);
  seriesViewStateTimer = setTimeout(notifyCaseManagerViewState, 120);
}
function restoreInitialSeriesViewPosition() {
  if (initialSeriesViewRestored) return;
  initialSeriesViewRestored = true;
  requestAnimationFrame(() => requestAnimationFrame(() => {
    const body = $('seriesWorkspaceBody');
    const table = document.querySelector('#seriesChildTableHost .series-table-wrap');
    if (body) body.scrollTop = initialSeriesViewState.bodyScrollTop;
    if (table) {
      table.scrollTop = initialSeriesViewState.tableScrollTop;
      table.scrollLeft = initialSeriesViewState.tableScrollLeft;
    }
    syncSeriesTableStickyOffset();
    notifyCaseManagerViewState();
  }));
}
function persistSeriesHash() {
  const target = seriesHashForState();
  if (!target) return clearSeriesHash();
  if (location.hash !== target) {
    history.replaceState(null, '', `${location.pathname}${location.search}${target}`);
  }
  notifyCaseManagerViewState();
}
function clearSeriesHash() {
  if (location.hash.startsWith(SERIES_HASH_PREFIX)) {
    history.replaceState(null, '', `${location.pathname}${location.search}`);
  }
  notifyCaseManagerViewState();
}
function seriesResumeTargetFromHash() {
  const match = location.hash.match(new RegExp(`^${SERIES_HASH_PREFIX.replace('#', '\\#')}(\\d+)(?:/(children|public))?$`));
  if (!match) return null;
  return { id: Number(match[1]), tab: match[2] || 'children' };
}
function showSeriesWorkspace() {
  $('seriesWorkspace').classList.add('show');
  $('seriesWorkspace').setAttribute('aria-hidden', 'false');
  document.body.style.overflow = 'hidden';
}
$('seriesWorkspaceBody')?.addEventListener('scroll', scheduleSeriesViewStateSync, { passive: true });
function closeSeriesWorkspace() {
  closeSeriesFilterPopover();
  closeSeriesSide();
  $('seriesWorkspace').classList.remove('show');
  $('seriesWorkspace').classList.remove('table-focus');
  $('seriesWorkspace').setAttribute('aria-hidden', 'true');
  document.body.style.overflow = '';
  state.seriesWorkspace = null;
  state.seriesMobileCardLayout = null;
  state.seriesSelectedChildIds.clear();
  state.seriesCreateImportPreview = null;
  state.seriesColumnFilters = {};
  state.seriesSortKey = '';
  state.seriesTableEditMode = false;
  state.seriesShowHiddenRows = false;
  state.seriesTableFocusMode = false;
  state.seriesWorkspaceTab = 'children';
  state.seriesPublicEditMode = false;
  state.seriesPublicInlineEditKey = '';
  state.seriesCellSelection = null;
  state.seriesCellMultiSelection.clear();
  state.seriesSelectionDragging = false;
  state.seriesUndoStack = [];
  state.seriesRedoStack = [];
  state.seriesHistoryBusy = false;
  state.seriesDraggingRowId = 0;
  closeSeriesDeleteDialog();
  clearSeriesHash();
  notifyCaseManagerContext(currentCaseManagerPageLabel());
}
function openNewSeries() {
  if (!requireOnlineAction()) return;
  clearSeriesHash();
  state.seriesWorkspace = { creating: true };
  state.seriesCreateImportPreview = null;
  showSeriesWorkspace();
  $('seriesWorkspaceTitle').textContent = '新增系列案件';
  $('seriesWorkspaceSubtitle').textContent = '先设置共同当事人，也可直接上传电子表格生成首批子案';
  $('seriesWorkspaceActions').innerHTML = `<button class="btn series-close-btn" onclick="closeSeriesWorkspace()">取消</button><button class="btn primary" id="seriesCreateButton" onclick="createSeriesFromForm()">创建系列</button>`;
  $('seriesWorkspaceBody').innerHTML = seriesParentFormHtml({}, true);
  activateSeriesLookups($('seriesWorkspaceBody'));
  notifySeriesWorkspaceContext();
}
function seriesParentFormHtml(data = {}, creating = false) {
  const profile = data.profile || {};
  const claimLines = (data.common_claims || []).map(c => [c.claim_code || '', c.claim_text || '', c.amount_text || '', c.currency || 'CNY', c.calculation_basis || '', c.legal_basis || '', c.notes || ''].join('\t')).join('\n');
  const parentParties = (data.parties||[]).length ? data.parties : seriesAssociatedParties(data);
  const contactData = seriesPublicContactData(data);
  return `<div class="series-form-notice" id="seriesFormNotice" role="alert" aria-live="assertive"></div><section class="series-detail-block"><div class="series-form-grid">
    <div class="full"><label>共同当事人</label>${seriesPartyEditorHtml(parentParties,'seriesFormParties')}<div class="series-paste-help">已自动带出系列关联的委托人/对方当事人；输入时可继续搜索案件管理数据库。</div></div>
    <div class="full"><label>系列案件名称 *</label><input class="input" id="seriesFormTitle" value="${esc(data.title || '')}" placeholder="例如：某公司商品房预售合同系列纠纷"></div>
    <div><label>案件类型（案由）</label>${seriesLookupInput('seriesFormCaseType',data.case_type||'','case_types','点击选择或搜索案由')}</div>
    <div><label>当前阶段（系列层）</label>${seriesLookupInput('seriesFormStage',data.current_stage||'','stages','可留空，由子案进度汇总')}</div>
    <div class="full"><label>共同基本案情</label><textarea class="input" id="seriesFormFacts">${esc(profile.common_facts || '')}</textarea></div>
    <div class="full"><label>共同合同条款</label><textarea class="input" id="seriesFormContract">${esc(profile.common_contract_terms || '')}</textarea></div>
    <div class="full"><label>共同诉讼/仲裁请求</label><textarea class="input" id="seriesFormClaims" placeholder="每行：请求编号 [Tab] 请求内容 [Tab] 金额 [Tab] 币种 [Tab] 计算口径 [Tab] 依据 [Tab] 备注">${esc(claimLines)}</textarea></div>
    <div class="full"><label>共同联系与备忘</label><div class="series-paste-help" style="margin:4px 0 9px">与普通案件使用相同的联系人分类、字段和通讯录同步能力；这里记录的是整个系列共同适用的信息。</div>${contactEditorHtml(contactData,{includeDisplayColumns:false,publicEditor:true})}</div>
    ${creating ? `<div class="full"><label>首批子案</label><div class="series-import-create"><div class="series-import-create-head"><div><strong>上传电子表格智能识别</strong><div class="series-paste-help">自动识别表头、当事人、案号、阶段、标的金额和本系列自定义列。</div></div><button class="btn primary" type="button" onclick="$('seriesInitialImportFile').click()">选择 Excel 文件</button></div><input type="file" id="seriesInitialImportFile" accept=".xlsx" hidden onchange="previewInitialSeriesImport(this.files?.[0])"><div id="seriesInitialImportPreview"></div></div><details style="margin-top:10px"><summary class="series-paste-help" style="cursor:pointer">也可以直接从表格复制后粘贴</summary><textarea class="input" id="seriesFormChildren" style="min-height:130px;margin-top:8px" placeholder="每行：子案编号 [Tab] 子案名称 [Tab] 当前阶段 [Tab] 委托人 [Tab] 对方 [Tab] 案号 [Tab] 受理机构 [Tab] 侧重点 [Tab] 备忘"></textarea><div class="series-paste-help">多名当事人可用“、”分隔。</div></details></div>` : ''}
  </div></section>`;
}
function seriesAssociatedParties(data={}) {
  const rows=[...(data.parties||[])];
  const seen=new Set(rows.map(item=>`${item.party_group||'other'}\u0000${item.name||''}`));
  for(const child of data.children||[]){
    for(const name of String(child.clients||'').split(/[、,，]/).map(x=>x.trim()).filter(Boolean)){
      const key=`client\u0000${name}`; if(!seen.has(key)){rows.push({party_group:'client',role:'委托人',name});seen.add(key);}
    }
    for(const name of String(child.opponents||'').split(/[、,，]/).map(x=>x.trim()).filter(Boolean)){
      const key=`other\u0000${name}`; if(!seen.has(key)){rows.push({party_group:'other',role:'对方当事人',name});seen.add(key);}
    }
  }
  return rows;
}
function tabLines(value) {
  return String(value || '').split(/\r?\n/).map(line => line.trim()).filter(Boolean).map(line => line.split('\t').map(v => v.trim()));
}
function parseSeriesParties(value) {
  return tabLines(value).map(cols => ({ party_group: cols[0] === '委托人' || cols[0] === 'client' ? 'client' : 'other', role: cols[1] || '', name: cols[2] || '', credit_code: cols[3] || '' })).filter(p => p.name || p.role);
}
function parseSeriesCommonClaims(value) {
  return tabLines(value).map(cols => ({ claim_code:cols[0]||'', claim_text:cols[1]||'', amount_text:cols[2]||'', currency:cols[3]||'CNY', calculation_basis:cols[4]||'', legal_basis:cols[5]||'', notes:cols[6]||'' })).filter(c => c.claim_text || c.amount_text);
}
function seriesPublicContactData(data = {}) {
  const profile = data?.profile || {};
  const memo = String(data?.memo || '').trim() || String(profile.series_memo || '').trim();
  return {...data, memo};
}
function collectSeriesPublicContactFields(root = document) {
  const contacts = collectContactGroups(root);
  const memo = root?.querySelector?.('[name="memo"]')?.value.trim() || '';
  return {
    court_contact: serializeContactGroups(contacts, 'court'),
    party_contact: serializeContactGroups(contacts, 'party'),
    memo,
  };
}
function collectSeriesParentForm(includeChildren = false) {
  const contacts = collectSeriesPublicContactFields($('seriesWorkspaceBody') || document);
  const body = {
    title: $('seriesFormTitle')?.value.trim() || '', case_type: $('seriesFormCaseType')?.value.trim() || '', current_stage: $('seriesFormStage')?.value.trim() || '',
    court_contact: contacts.court_contact, party_contact: contacts.party_contact, memo:contacts.memo,
    profile: { common_facts:$('seriesFormFacts')?.value.trim() || '', common_contract_terms:$('seriesFormContract')?.value.trim() || '', series_memo:contacts.memo },
    parties: collectSeriesPartyEditor('seriesFormParties'), common_claims: parseSeriesCommonClaims($('seriesFormClaims')?.value)
  };
  if (includeChildren) {
    body.children = tabLines($('seriesFormChildren')?.value||'').map((cols, index) => {
      const clients = String(cols[3] || '').split(/[、,，]/).map(x => x.trim()).filter(Boolean);
      const opponents = String(cols[4] || '').split(/[、,，]/).map(x => x.trim()).filter(Boolean);
      return { series_code:cols[0] || String(index + 1).padStart(3,'0'), display_name:cols[1] || '', current_stage:cols[2] || '',
        parties:[...clients.map(name => ({party_group:'client',role:'委托人',name})), ...opponents.map(name => ({party_group:'other',role:'对方当事人',name}))],
        case_numbers:(cols[5] || cols[6]) ? [{case_no:cols[5]||'',court:cols[6]||''}] : [], case_focus:cols[7]||'', memo:cols[8]||'' };
    }).filter(c => c.display_name);
    body.initial_import_preview_id = state.seriesCreateImportPreview?.preview_id || '';
  }
  return body;
}
function renderInitialSeriesImportPreview(){const host=$('seriesInitialImportPreview');if(!host)return;const data=state.seriesCreateImportPreview;if(!data){host.innerHTML='';return;}const amountColumns=(data.columns||[]).filter(c=>c.semantic_type==='amount');const samples=(data.samples||[]).slice(0,4);const sampleColumns=(data.columns||[]).slice(0,6);host.innerHTML=`<div class="series-import-preview"><strong>已识别 ${Number(data.counts?.children||0)} 个子案、${Number(data.counts?.columns||0)} 列</strong>${amountColumns.length?`<div class="series-paste-help" style="margin-top:5px">金额汇总列：${amountColumns.map(c=>esc(c.label)).join('、')}</div>`:''}${data.errors?.length?`<div class="series-risk" style="margin-top:6px">发现 ${data.errors.length} 个错误，请修改文件后重新上传。</div>`:`<div class="series-paste-help" style="margin-top:5px">创建系列后，主表将自动采用这些列。</div>`}${samples.length?`<div style="overflow:auto;margin-top:8px"><table class="series-import-map"><thead><tr>${sampleColumns.map(c=>`<th>${esc(c.label)}</th>`).join('')}</tr></thead><tbody>${samples.map(row=>`<tr>${sampleColumns.map(c=>`<td>${esc(row[c.key]||'')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`:''}<button class="btn" type="button" style="margin-top:8px" onclick="state.seriesCreateImportPreview=null;renderInitialSeriesImportPreview()">移除该文件</button></div>`;}
async function previewInitialSeriesImport(file){if(!file)return;const form=new FormData();form.append('file',file);try{const data=await api('/api/case-manager/series-create/import-preview',{method:'POST',body:form});state.seriesCreateImportPreview=data;renderInitialSeriesImportPreview();toast(data.errors?.length?'表格存在错误，尚不能创建':'已智能识别首批子案');}catch(e){toast(e.message);}finally{if($('seriesInitialImportFile'))$('seriesInitialImportFile').value='';}}
function setSeriesFormNotice(message='') {
  const notice=$('seriesFormNotice');
  if(!notice)return;
  notice.textContent=String(message||'');
  notice.classList.toggle('show',!!message);
  if(message)$('seriesWorkspaceBody')?.scrollTo({top:0,behavior:'smooth'});
}
function setSeriesCreateBusy(busy) {
  const button=$('seriesCreateButton');
  if(!button)return;
  button.disabled=!!busy;
  button.textContent=busy?'正在创建…':'创建系列';
}
async function createSeriesFromForm() {
  const body = collectSeriesParentForm(true);
  setSeriesFormNotice('');
  if (!body.title) {
    setSeriesFormNotice('请填写系列案件名称');
    $('seriesFormTitle')?.focus();
    return toast('请填写系列案件名称');
  }
  if(state.seriesCreateImportPreview?.errors?.length){
    setSeriesFormNotice('请先修正首批子案表格中的错误');
    return toast('请先修正首批子案表格中的错误');
  }
  setSeriesCreateBusy(true);
  try {
    const data = await api('/api/case-manager/series', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    toast('系列案件已创建');
    await refreshAll();
    await openSeriesWorkspace(data.id);
  } catch (e) {
    const message=e?.message||'系列案件创建失败，请稍后重试';
    setSeriesFormNotice(message);
    toast(message);
    if(/名称|同名/.test(message)){
      $('seriesFormTitle')?.focus();
      $('seriesFormTitle')?.select();
    }
  } finally {
    setSeriesCreateBusy(false);
  }
}
function offlineSeriesData(id) {
  const item = offlineCaseById(id);
  if (!item) return null;
  const children = (item.series_children || []).map(child => ({...child, display_name:child.series_display_name || child.title, clients:(child.parties||[]).filter(p=>p.party_group==='client').map(p=>p.name).join('、'), opponents:(child.parties||[]).filter(p=>p.party_group!=='client').map(p=>p.name).join('、'), case_no:(child.case_numbers||[]).map(n=>n.case_no).filter(Boolean).join('\n'), court:(child.case_numbers||[]).map(n=>n.court).filter(Boolean).join('\n'), claim_totals:{}, reminder_stats:{overdue:0,next_7_days:0,total:0} }));
  const visibleChildren = children.filter(c => c.source_status !== 'deleted');
  const stages = {}; visibleChildren.forEach(c => { const k=c.current_stage||'待补充'; stages[k]=(stages[k]||0)+1; });
  const profile=item.profile||{};const amountColumns=(profile.table_columns||[]).filter(column=>column.semantic_type==='amount');const tableTotals={};let amountCount=0;children.filter(child=>child.source_status!=='deleted').forEach(child=>amountColumns.forEach(column=>{const amount=seriesParseAmount(child[column.key]??child.custom_values?.[column.key]);if(Number.isNaN(amount))return;amountCount+=1;const currency=column.currency||'CNY';tableTotals[currency]=(tableTotals[currency]||0)+amount;}));
  return {...item, profile, common_claims:item.common_claims||[], children, stats:{total:visibleChildren.length,active:visibleChildren.filter(c=>c.source_status==='active').length,archived:visibleChildren.filter(c=>c.source_status==='archived').length,deleted:children.filter(c=>c.source_status==='deleted').length,overdue:0,next_7_days:0,total_reminders:0,stage_distribution:stages,claim_totals:tableTotals,amount_source:amountCount?'table_columns':'structured_claims',amount_columns:amountColumns.map(column=>column.label)}};
}
async function openSeriesWorkspace(id, tab) {
  showSeriesWorkspace();
  state.seriesTableEditMode = false;
  state.seriesShowHiddenRows = false;
  state.seriesTableFocusMode = false;
  state.seriesWorkspaceTab = tab === 'public' ? 'public' : 'children';
  state.seriesMobileCardLayout = null;
  state.seriesPublicEditMode = false;
  state.seriesCellSelection = null;
  state.seriesCellMultiSelection.clear();
  state.seriesUndoStack = [];
  state.seriesRedoStack = [];
  state.seriesHistoryBusy = false;
  $('seriesWorkspace').classList.remove('table-focus');
  $('seriesWorkspaceBody').innerHTML = '<div class="empty">正在加载系列案件...</div>';
  try {
    const data = isOfflineReadonly() ? offlineSeriesData(id) : await api(`/api/case-manager/series/${id}`);
    if (!data) throw new Error('离线缓存中未找到系列案件');
    state.seriesWorkspace = decorateSeriesWorkspaceChildren(data);
    state.seriesSelectedChildIds.clear();
    renderSeriesWorkspace();
    restoreInitialSeriesViewPosition();
    persistSeriesHash();
    notifySeriesWorkspaceContext();
  } catch (e) { toast(e.message); closeSeriesWorkspace(); }
}
function seriesMoney(totals = {}) {
  const parts = Object.entries(totals).map(([currency,value]) => `${currency} ${Number(value || 0).toLocaleString('zh-CN',{maximumFractionDigits:2})}`);
  return parts.join('；') || '—';
}
function seriesStageText(stages = {}) { return Object.entries(stages).map(([k,v])=>`${k} ${v}`).join(' · ') || '暂无阶段'; }
function toggleSeriesTableFocusMode(){state.seriesTableFocusMode=!state.seriesTableFocusMode;$('seriesWorkspace').classList.toggle('table-focus',state.seriesTableFocusMode);const button=$('seriesTableFocusButton');if(button)button.textContent=state.seriesTableFocusMode?'退出主表全屏':'放大主表';setTimeout(()=>prepareSeriesCellLayout($('seriesChildTableHost')),30);}
function toggleSeriesTableEditMode(){if(isOfflineReadonly())return requireOnlineAction();state.seriesTableEditMode=!state.seriesTableEditMode;if(!state.seriesTableEditMode){state.seriesSelectedChildIds.clear();state.seriesCellSelection=null;state.seriesCellMultiSelection.clear();state.seriesShowHiddenRows=false;}renderSeriesWorkspace();toast(state.seriesTableEditMode?'已进入编辑模式：可编辑、选择区域、计算及批量填充':'已退出编辑模式');}
function switchSeriesWorkspaceTab(tab) {
  if (!['children','public'].includes(tab) || state.seriesWorkspaceTab === tab) return;
  if(state.seriesPublicEditMode&&!confirm('尚未保存公共信息修改，确认放弃并切换页面？'))return;
  closeSeriesFilterPopover();
  state.seriesPublicEditMode = false;
  state.seriesWorkspaceTab = tab;
  state.seriesCellSelection = null;
  state.seriesCellMultiSelection.clear();
  renderSeriesWorkspace();
  persistSeriesHash();
  notifySeriesWorkspaceContext();
}
function seriesWorkspaceMainToolsHtml(stats={}) {
  if(state.seriesWorkspaceTab!=='children')return '';
  const hiddenCount=(state.seriesWorkspace?.children||[]).filter(item=>item.source_status!=='deleted'&&Number(item.series_row_hidden||0)===1).length;
  return `<span class="series-workspace-divider" aria-hidden="true"></span><div class="series-workspace-tools">
    ${isOfflineReadonly()?'':`<button class="btn ${state.seriesTableEditMode?'primary':''}" onclick="toggleSeriesTableEditMode()">${state.seriesTableEditMode?'完成编辑':'编辑主表'}</button>`}
    <input class="input series-main-search" placeholder="搜索全部表格内容" value="${esc(state.seriesChildQuery)}" oninput="state.seriesChildQuery=this.value; renderSeriesChildTable()">
    <select class="input" id="seriesStageFilter" onchange="renderSeriesChildTable()"><option value="">全部阶段</option>${Object.keys(stats.stage_distribution||{}).map(x=>`<option>${esc(x)}</option>`).join('')}</select>
    <button class="btn" onclick="clearSeriesTableFilters()">清除筛选/排序</button>
    ${(!isOfflineReadonly()&&state.seriesTableEditMode)?`<button class="btn" id="seriesUndoButton" onclick="undoSeriesEdit()" ${state.seriesUndoStack.length?'':'disabled'} title="撤销上一次主表操作">↶ 撤销</button><button class="btn" id="seriesRedoButton" onclick="redoSeriesEdit()" ${state.seriesRedoStack.length?'':'disabled'} title="恢复刚撤销的操作">↷ 重做</button><button class="btn primary" onclick="openSeriesInsertRowsPanel()">＋ 插入行</button><button class="btn" onclick="openSeriesInsertColumnsPanel()">＋ 插入列</button><button class="btn" onclick="openSeriesColumnManager()">管理列</button><button class="btn" id="seriesHiddenRowsToggle" type="button" onclick="toggleSeriesHiddenRowsView()">${state.seriesShowHiddenRows?'收起隐藏行':'显示隐藏行'}${hiddenCount?`（${hiddenCount}）`:''}</button><button class="btn" id="seriesHideSelectedRows" type="button" onclick="setSelectedSeriesRowsHidden(${state.seriesShowHiddenRows?'false':'true'})" ${state.seriesSelectedChildIds.size?'':'disabled'}>${state.seriesShowHiddenRows?'恢复所选行':'隐藏所选行'}</button><button class="btn danger" id="seriesDeleteSelectedRows" type="button" onclick="deleteSelectedSeriesRows()" ${state.seriesSelectedChildIds.size?'':'disabled'}>删除所选行</button>`:''}
    <span id="seriesSelectionSummary" class="series-paste-help"></span>
    <span class="series-paste-help">${state.seriesTableEditMode?'拖动鼠标选择连续单元格':'列宽智能适配 · 长文本自动换行'}</span>
  </div>`;
}
function seriesWorkspaceTabsHtml(stats={}) {
  return `<nav class="series-workspace-tabs" aria-label="系列案件工作区">
    <button class="series-workspace-tab ${state.seriesWorkspaceTab==='children'?'active':''}" type="button" onclick="switchSeriesWorkspaceTab('children')">子案信息主表</button>
    <button class="series-workspace-tab ${state.seriesWorkspaceTab==='public'?'active':''}" type="button" onclick="switchSeriesWorkspaceTab('public')">系列案公共信息</button>
    ${seriesWorkspaceMainToolsHtml(stats)}
  </nav>`;
}
function seriesPublicInfoHtml(data) {
  if(state.seriesPublicEditMode)return `<div class="series-tab-panel public series-public-edit">
    <div class="series-public-edit-intro"><strong>编辑系列案公共信息</strong><span>这里的当事人、案情、合同、请求、联系信息和备忘共同适用于整个系列。</span></div>
    ${seriesParentFormHtml(data,false)}
  </div>`;
  const stats=data.stats||{}, profile=data.profile||{}, contactData=seriesPublicContactData(data);
  const parties=(data.parties||[]).length?data.parties:seriesAssociatedParties(data);
  const partyHtml=parties.filter(item=>item.party_group==='client').map(item=>`<div class="series-public-party"><strong>${esc(item.name||'未填写名称')} <span class="tag">${esc(item.client_type||'委托人')}</span></strong><span class="series-public-party-meta">联系人：${esc(item.client_contact_person||'未录入')} · 电话：${esc(item.client_phone||'未录入')}${item.client_legal_representative?` · 法定代表人：${esc(item.client_legal_representative)}`:''}</span><span class="series-public-party-meta">${esc([item.client_identity_code?`统一社会信用代码：${item.client_identity_code}`:'',item.client_registration_status,item.client_registered_capital,item.client_address].filter(Boolean).join(' · '))}</span></div>`).join('')||'<span class="contact-empty">暂无共同委托人</span>';
  const claims=(data.common_claims||[]).map(item=>`<li><strong>${esc(item.claim_text||item.claim_code||'请求项')}</strong>${item.amount_text?` · ${esc(item.currency||'CNY')} ${esc(item.amount_text)}`:''}${item.legal_basis?`<br><span class="series-paste-help">${esc(item.legal_basis)}</span>`:''}</li>`).join('')||'<li>暂无共同请求</li>';
  const inline=state.seriesPublicInlineEditKey;
  const fieldAttrs=key=>`data-series-public-field-key="${esc(key)}"`;
  const textSection=(field,label,value,content='')=>{if(seriesPublicFieldHidden(field))return '';label=seriesPublicFieldLabel(field,label);return inline===field?`<section class="series-public-section series-public-inline-edit" ${fieldAttrs(field)}><h3>${esc(label)}</h3><textarea class="input series-public-inline-value" id="seriesPublicInlineValue" oninput="resizeSeriesPublicInlineEditor(this)">${esc(value)}</textarea><p><button class="btn" type="button" onclick="cancelSeriesPublicInlineEdit()">取消</button><button class="btn primary" type="button" onclick="saveSeriesPublicField('${esc(field)}')">保存</button></p></section>`:`<section class="series-public-section" ${fieldAttrs(field)}><h3>${esc(label)} <button class="btn" type="button" onclick="openSeriesPublicFieldEditor('${esc(field)}')">编辑</button></h3>${content||`<p>${formatMulti(String(value||'暂无记录'))}</p>`}</section>`;};
  const customFields=(profile.custom_fields||[]).map(field=>{
    const fieldKey=`custom:${field.key}`;
    if(seriesPublicFieldHidden(fieldKey))return '';
    const label=seriesPublicFieldLabel(fieldKey,field.label);
    if(inline===fieldKey)return `<section class="series-public-section series-public-inline-edit" ${fieldAttrs(fieldKey)}><h3>编辑自定义字段</h3><input class="input" id="seriesCustomFieldLabel" value="${esc(label||'')}" placeholder="字段名称"><textarea class="input series-public-inline-value" id="seriesCustomFieldValue" oninput="resizeSeriesPublicInlineEditor(this)">${esc(field.value||'')}</textarea><p><button class="btn" type="button" onclick="cancelSeriesPublicInlineEdit()">取消</button><button class="btn primary" type="button" onclick="saveSeriesCustomField('${esc(field.key)}')">保存</button></p></section>`;
    return `<section class="series-public-section" ${fieldAttrs(fieldKey)}><h3>${esc(label)} <button class="btn" type="button" onclick="openSeriesCustomFieldEditor('${esc(field.key)}')">编辑</button></h3><p>${formatMulti(String(field.value||'暂无记录'))}</p></section>`;
  }).join('');
  const newCustomField=inline==='custom:new'?`<section class="series-public-section series-public-inline-edit"><h3>新增自定义字段</h3><input class="input" id="seriesCustomFieldLabel" placeholder="字段名称，例如：共同争议焦点"><textarea class="input series-public-inline-value" id="seriesCustomFieldValue" oninput="resizeSeriesPublicInlineEditor(this)" placeholder="字段内容"></textarea><p><button class="btn" type="button" onclick="cancelSeriesPublicInlineEdit()">取消</button><button class="btn primary" type="button" onclick="saveSeriesCustomField()">保存</button></p></section>`:`<section class="series-public-section"><h3>自定义字段</h3><p><button class="btn" type="button" onclick="openSeriesCustomFieldEditor()">＋ 新增自定义字段</button></p></section>`;
  return `<div class="series-tab-panel public">
    <div class="series-stats">${seriesStat('子案总数',stats.total||0)}${seriesStat('在办',stats.active||0)}${seriesStat('已结案',stats.archived||0)}${seriesStat('逾期事项',stats.overdue||0,'series-risk')}${seriesStat('未来7日',stats.next_7_days||0)}${seriesStat('请求金额',seriesMoney(stats.claim_totals),'',stats.amount_source==='table_columns'?`汇总：${(stats.amount_columns||[]).join('、')}`:'汇总结构化请求项')}</div>
    <div class="series-public-grid">
      ${inline==='parties'?`<section class="series-public-section series-public-inline-edit full" ${fieldAttrs('parties')}><h3>${esc(seriesPublicFieldLabel('parties','共同当事人'))}</h3>${seriesLookupInput('seriesPublicClientNames',parties.filter(item=>item.party_group==='client').map(item=>item.name).filter(Boolean).join('、'),'clients','搜索委托人管理库，可用“、”分隔多个委托人').replace('autocomplete="off"','autocomplete="off" oninput="previewSeriesPublicClients(this.value)"')}<div class="series-public-parties" id="seriesPublicClientPreview"></div><p><button class="btn" type="button" onclick="cancelSeriesPublicInlineEdit()">取消</button><button class="btn primary" type="button" onclick="saveSeriesPublicField('parties')">保存</button></p></section>`:`<section class="series-public-section full" ${fieldAttrs('parties')}><h3>${esc(seriesPublicFieldLabel('parties','共同当事人'))} <button class="btn" type="button" onclick="openSeriesPublicFieldEditor('parties')">编辑</button></h3><div class="series-public-parties">${partyHtml}</div></section>`}
      ${textSection('title','系列案件名称',data.title||'')}
      ${inline==='case_type'?`<section class="series-public-section series-public-inline-edit" ${fieldAttrs('case_type')}><h3>${esc(seriesPublicFieldLabel('case_type','案件类型（案由）'))}</h3>${seriesLookupInput('seriesPublicCaseType',data.case_type||'','case_types','搜索或选择案件类型')}<p><button class="btn" type="button" onclick="cancelSeriesPublicInlineEdit()">取消</button><button class="btn primary" type="button" onclick="saveSeriesPublicField('case_type')">保存</button></p></section>`:textSection('case_type','案件类型（案由）',data.case_type||'')}
      ${textSection('current_stage','当前阶段（系列层）',data.current_stage||'')}
      ${textSection('common_facts','共同基本案情',profile.common_facts||'')}
      ${textSection('common_contract_terms','共同合同条款',profile.common_contract_terms||'')}
      ${textSection('common_claims','共同诉讼／仲裁请求',seriesCommonClaimsText(data.common_claims||[]),`<ol class="series-public-list">${claims}</ol>`)}
      <section class="series-public-section" ${fieldAttrs('stage_distribution')}><h3>子案阶段分布</h3><p>${esc(seriesStageText(stats.stage_distribution))}</p></section>
      ${customFields}${newCustomField}
      ${inline==='series_memo'?`<section class="series-public-section series-public-inline-edit full series-public-contact" ${fieldAttrs('series_memo')}><h3>共同联系与备忘</h3><div class="series-paste-help series-public-contact-help">可添加多组联系人和案件备忘；保存后，非编辑模式将按相同分类显示。</div><div class="series-form-grid series-public-inline-contact-form"><div class="full">${contactEditorHtml(contactData,{includeDisplayColumns:false,publicEditor:true})}</div></div><p><button class="btn" type="button" onclick="cancelSeriesPublicInlineEdit()">取消</button><button class="btn primary" type="button" onclick="saveSeriesPublicField('series_memo')">保存</button></p></section>`:`<section class="series-public-section full series-public-contact" ${fieldAttrs('series_memo')}><h3>共同联系与备忘 <button class="btn" type="button" onclick="openSeriesPublicFieldEditor('series_memo')">编辑联系与备忘</button></h3>${caseContactHub(contactData)}</section>`}
    </div>
  </div>`;
}
function seriesCommonClaimsText(items=[]){return items.map(item=>[item.claim_code||'',item.claim_text||'',item.amount_text||'',item.currency||'CNY',item.calculation_basis||'',item.legal_basis||'',item.notes||''].join('\t')).join('\n');}
function resizeSeriesPublicInlineEditor(input){if(input?.tagName!=='TEXTAREA')return;input.style.height='auto';input.style.height=`${input.scrollHeight}px`;}
async function previewSeriesPublicClients(value){const host=$('seriesPublicClientPreview'),names=String(value||'').split(/[、,，]/).map(item=>item.trim()).filter(Boolean);if(!host)return;if(!names.length){host.innerHTML='';return;}try{const data=await api(`/api/case-manager/clients?q=${encodeURIComponent(names.join(' '))}`),items=(data.items||[]).filter(item=>names.includes(item.name));host.innerHTML=items.map(item=>`<div class="series-public-party"><strong>${esc(item.name)} <span class="tag">${esc(item.client_type||'委托人')}</span></strong><span class="series-public-party-meta">联系人：${esc(item.contact_person||'未录入')} · 电话：${esc(item.phone||'未录入')}${item.legal_representative?` · 法定代表人：${esc(item.legal_representative)}`:''}</span><span class="series-public-party-meta">${esc([item.identity_code?`统一社会信用代码：${item.identity_code}`:'',item.registration_status,item.address].filter(Boolean).join(' · '))}</span></div>`).join('')||'<span class="series-paste-help">未在委托人管理库中匹配到该名称。</span>';}catch(e){host.innerHTML='';}}
function seriesPublicFieldSettings(){return state.seriesWorkspace?.profile?.public_field_settings||[];}
function seriesPublicFieldSetting(key){return seriesPublicFieldSettings().find(item=>item.key===key)||{};}
function seriesPublicFieldLabel(key,fallback){return seriesPublicFieldSetting(key).label||fallback;}
function seriesPublicFieldHidden(key){return seriesPublicFieldSetting(key).hidden===true;}
function seriesPublicUpdateBody(){const data=seriesPublicContactData(state.seriesWorkspace||{}),profile=data.profile||{};return {title:data.title||'',case_type:data.case_type||'',current_stage:data.current_stage||'',court_contact:data.court_contact||'',party_contact:data.party_contact||'',memo:data.memo||'',profile:{common_facts:profile.common_facts||'',common_contract_terms:profile.common_contract_terms||'',series_memo:data.memo||'',custom_fields:(profile.custom_fields||[]).map(field=>({...field})),public_field_order:[...(profile.public_field_order||[])],public_field_settings:(profile.public_field_settings||[]).map(field=>({...field}))},parties:data.parties||[],common_claims:data.common_claims||[]};}
function prepareSeriesPublicFieldOrder(){const grid=document.querySelector('#seriesWorkspace .series-public-grid');if(!grid)return;const order=state.seriesWorkspace?.profile?.public_field_order||[],rank=new Map(order.map((key,index)=>[key,index]));const cards=[...grid.children];cards.sort((a,b)=>{const ar=rank.has(a.dataset.seriesPublicFieldKey)?rank.get(a.dataset.seriesPublicFieldKey):Number.MAX_SAFE_INTEGER,br=rank.has(b.dataset.seriesPublicFieldKey)?rank.get(b.dataset.seriesPublicFieldKey):Number.MAX_SAFE_INTEGER;return ar-br;}).forEach(card=>grid.appendChild(card));}
function seriesPublicFieldDefinitions(){const custom=(state.seriesWorkspace?.profile?.custom_fields||[]).map(field=>({key:`custom:${field.key}`,label:seriesPublicFieldLabel(`custom:${field.key}`,field.label||'未命名自定义字段'),custom:true}));return [{key:'parties',label:'共同当事人'},{key:'title',label:'系列案件名称'},{key:'case_type',label:'案件类型（案由）'},{key:'current_stage',label:'当前阶段（系列层）'},{key:'common_facts',label:'共同基本案情'},{key:'common_contract_terms',label:'共同合同条款'},{key:'common_claims',label:'共同诉讼／仲裁请求'},{key:'stage_distribution',label:'子案阶段分布'},...custom,{key:'series_memo',label:'共同联系与备忘'}].map(field=>({...field,label:seriesPublicFieldLabel(field.key,field.label)}));}
function currentSeriesPublicFieldOrder(){const fields=seriesPublicFieldDefinitions(),valid=new Set(fields.map(field=>field.key)),saved=state.seriesWorkspace?.profile?.public_field_order||[];return [...saved.filter(key=>valid.has(key)),...fields.map(field=>field.key).filter(key=>!saved.includes(key))];}
function renderSeriesPublicFieldOrderPanel(){const host=$('seriesPublicFieldOrderList');if(!host)return;const definitions=new Map(seriesPublicFieldDefinitions().map(field=>[field.key,field]));host.innerHTML=(state.seriesPublicFieldOrderDraft||[]).map((key,index)=>{const field=definitions.get(key)||{label:key},hidden=seriesPublicFieldHidden(key),custom=key.startsWith('custom:');return `<div class="series-column-item ${hidden?'is-hidden':''}" data-series-public-field-key="${esc(key)}" draggable="true" ondragstart="startSeriesPublicFieldOrderDrag(event,'${esc(key)}')" ondragover="dragOverSeriesPublicFieldOrder(event)" ondragleave="event.currentTarget.classList.remove('drag-over')" ondrop="dropSeriesPublicFieldOrder(event,'${esc(key)}')" ondragend="finishSeriesPublicFieldOrderDrag()"><span>${index+1}</span><strong>⋮⋮</strong><input class="input" value="${esc(field.label)}" oninput="updateSeriesPublicFieldLabel('${esc(key)}',this.value)"><button class="btn" type="button" onclick="toggleSeriesPublicFieldHidden('${esc(key)}')">${hidden?'恢复':'删除'}</button>${custom?`<button class="btn danger" type="button" onclick="deleteSeriesCustomFieldFromManager('${esc(key)}')">彻底删除</button>`:''}</div>`;}).join('');}
function openSeriesPublicFieldOrderPanel(){if(!requireOnlineAction())return;state.seriesPublicFieldOrderDraft=currentSeriesPublicFieldOrder();showSeriesSide('编辑字段','拖动字段目录调整顺序；可改名或删除字段。自定义字段仅在此处提供彻底删除。',`<div class="series-column-list" id="seriesPublicFieldOrderList"></div>`,`<button class="btn" onclick="closeSeriesSide()">取消</button><button class="btn" onclick="resetSeriesPublicFieldOrder()">恢复默认</button><button class="btn primary" onclick="saveSeriesPublicFieldOrder()">保存字段设置</button>`);renderSeriesPublicFieldOrderPanel();}
function updateSeriesPublicFieldLabel(key,label){const body=seriesPublicUpdateBody(),settings=body.profile.public_field_settings,entry=settings.find(item=>item.key===key);if(entry)entry.label=label.trim();else settings.push({key,label:label.trim(),hidden:false});state.seriesWorkspace.profile.public_field_settings=settings;}
function toggleSeriesPublicFieldHidden(key){const settings=state.seriesWorkspace.profile.public_field_settings||[],entry=settings.find(item=>item.key===key);if(entry)entry.hidden=!entry.hidden;else settings.push({key,label:'',hidden:true});state.seriesWorkspace.profile.public_field_settings=settings;renderSeriesPublicFieldOrderPanel();}
function deleteSeriesCustomFieldFromManager(key){const raw=key.replace(/^custom:/,'');if(!confirm('确定彻底删除这个自定义字段？'))return;state.seriesWorkspace.profile.custom_fields=(state.seriesWorkspace.profile.custom_fields||[]).filter(field=>field.key!==raw);state.seriesWorkspace.profile.public_field_settings=(state.seriesWorkspace.profile.public_field_settings||[]).filter(field=>field.key!==key);state.seriesPublicFieldOrderDraft=(state.seriesPublicFieldOrderDraft||[]).filter(item=>item!==key);renderSeriesPublicFieldOrderPanel();}
function startSeriesPublicFieldOrderDrag(event,key){event.dataTransfer.effectAllowed='move';event.dataTransfer.setData('text/plain',key);event.currentTarget.classList.add('dragging');}
function dragOverSeriesPublicFieldOrder(event){event.preventDefault();event.dataTransfer.dropEffect='move';event.currentTarget.classList.add('drag-over');}
function finishSeriesPublicFieldOrderDrag(){document.querySelectorAll('#seriesPublicFieldOrderList .dragging,#seriesPublicFieldOrderList .drag-over').forEach(item=>item.classList.remove('dragging','drag-over'));}
function syncSeriesPublicFieldOrderNumbers(host){host?.querySelectorAll(':scope > .series-column-item').forEach((item,index)=>{const number=item.querySelector(':scope > span');if(number)number.textContent=String(index+1);});}
function dropSeriesPublicFieldOrder(event,targetKey){event.preventDefault();const sourceKey=event.dataTransfer.getData('text/plain');const host=$('seriesPublicFieldOrderList'),sourceEl=host?.querySelector(`[data-series-public-field-key="${CSS.escape(sourceKey)}"]`),targetEl=event.currentTarget;finishSeriesPublicFieldOrderDrag();const order=[...(state.seriesPublicFieldOrderDraft||[])],from=order.indexOf(sourceKey),to=order.indexOf(targetKey);if(from<0||to<0||from===to)return;order.splice(from,1);order.splice(to,0,sourceKey);state.seriesPublicFieldOrderDraft=order;if(sourceEl&&targetEl&&host){const beforeRects=captureApexReorderRects(host,':scope > .series-column-item'),reference=from<to?targetEl.nextElementSibling:targetEl;if(reference!==sourceEl&&sourceEl.nextElementSibling!==reference){host.insertBefore(sourceEl,reference);animateApexReorder(host,beforeRects,{skip:sourceEl});markApexReorderCommitted(sourceEl);syncSeriesPublicFieldOrderNumbers(host);}}}
function resetSeriesPublicFieldOrder(){state.seriesPublicFieldOrderDraft=seriesPublicFieldDefinitions().map(field=>field.key);renderSeriesPublicFieldOrderPanel();}
async function saveSeriesPublicFieldOrder(){const body=seriesPublicUpdateBody();body.profile.public_field_order=[...(state.seriesPublicFieldOrderDraft||[])];await persistSeriesPublicUpdate(body,'公共字段顺序已保存');}
function startSeriesPublicFieldDrag(event,key){if(state.seriesPublicInlineEditKey)return;event.dataTransfer.effectAllowed='move';event.dataTransfer.setData('text/plain',key);event.currentTarget.classList.add('public-field-dragging');}
function dragOverSeriesPublicField(event){if(state.seriesPublicInlineEditKey)return;event.preventDefault();event.dataTransfer.dropEffect='move';event.currentTarget.classList.add('public-field-drop-target');}
function finishSeriesPublicFieldDrag(){document.querySelectorAll('.public-field-dragging,.public-field-drop-target').forEach(item=>item.classList.remove('public-field-dragging','public-field-drop-target'));}
async function dropSeriesPublicField(event,targetKey){event.preventDefault();const sourceKey=event.dataTransfer.getData('text/plain');finishSeriesPublicFieldDrag();if(!sourceKey||sourceKey===targetKey)return;const grid=document.querySelector('#seriesWorkspace .series-public-grid'),order=[...(grid?.querySelectorAll(':scope > [data-series-public-field-key]')||[])].map(item=>item.dataset.seriesPublicFieldKey),from=order.indexOf(sourceKey),to=order.indexOf(targetKey);if(from<0||to<0)return;order.splice(from,1);order.splice(to,0,sourceKey);const body=seriesPublicUpdateBody();body.profile.public_field_order=order;await persistSeriesPublicUpdate(body,'公共字段顺序已保存');}
async function persistSeriesPublicUpdate(body,successMessage){try{state.seriesWorkspace=await api(`/api/case-manager/series/${state.seriesWorkspace.id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});state.seriesPublicInlineEditKey='';renderSeriesWorkspace();await refreshAll();toast(successMessage);}catch(e){toast(e.message);}}
function cancelSeriesPublicInlineEdit(){state.seriesPublicInlineEditKey='';renderSeriesWorkspace();}
function openSeriesPublicFieldEditor(field){if(!requireOnlineAction())return;state.seriesPublicInlineEditKey=field;renderSeriesWorkspace();}
async function saveSeriesPublicField(field){const body=seriesPublicUpdateBody(),value=field==='case_type'?($('seriesPublicCaseType')?.value||''):field==='parties'?($('seriesPublicClientNames')?.value||''):($('seriesPublicInlineValue')?.value||'');if(field==='common_claims')body.common_claims=parseSeriesCommonClaims(value);else if(field==='parties'){const names=value.split(/[、,，]/).map(item=>item.trim()).filter(Boolean);body.parties=names.map(name=>({party_group:'client',role:'委托人',name}));}else if(['title','case_type','current_stage'].includes(field))body[field]=value.trim();else if(field==='series_memo'){const contacts=collectSeriesPublicContactFields($('seriesWorkspaceBody')||document);body.court_contact=contacts.court_contact;body.party_contact=contacts.party_contact;body.memo=contacts.memo;body.profile.series_memo=contacts.memo;}else body.profile[field]=value.trim();if(!body.title)return toast('请填写系列案件名称');await persistSeriesPublicUpdate(body,'公共信息已保存');}
function openSeriesCustomFieldEditor(key=''){if(!requireOnlineAction())return;state.seriesPublicInlineEditKey=key?`custom:${key}`:'custom:new';renderSeriesWorkspace();}
async function saveSeriesCustomField(key=''){
  const label=$('seriesCustomFieldLabel')?.value.trim()||'',value=$('seriesCustomFieldValue')?.value.trim()||'';if(!label)return toast('请填写字段名称');
  const body=seriesPublicUpdateBody(),fields=body.profile.custom_fields;const index=fields.findIndex(item=>item.key===key);const next={key:key||`custom_${Date.now().toString(36)}`,label,value};if(index>=0)fields[index]=next;else fields.push(next);await persistSeriesPublicUpdate(body,'自定义字段已保存');
}
async function deleteSeriesCustomField(key){if(!requireOnlineAction()||!confirm('确定删除该自定义字段？'))return;const body=seriesPublicUpdateBody();body.profile.custom_fields=body.profile.custom_fields.filter(field=>field.key!==key);await persistSeriesPublicUpdate(body,'自定义字段已删除');}
function seriesChildrenToolbarHtml(stats) {
  return state.seriesTableEditMode?`<div class="series-toolbar">${seriesSheetBarHtml()}</div>`:'';
}
function renderSeriesWorkspace() {
  const data = state.seriesWorkspace;
  if (!data || data.creating) return;
  const stats = data.stats || {};
  $('seriesWorkspaceTitle').textContent = data.title || '系列案件';
  $('seriesWorkspaceSubtitle').textContent = `${data.case_type || '待补充案由'} · ${stats.total || 0} 个子案 · ${seriesStageText(stats.stage_distribution)}`;
  const childActions=state.seriesWorkspaceTab==='children'
    ? `<button class="btn" onclick="$('seriesImportFile').click()">Excel 导入</button><button class="btn" onclick="exportSeriesWorkbook()">Excel 导出</button><button class="btn" onclick="openSeriesImportHistory()">导入历史</button>${state.seriesTableEditMode?'<button class="btn" onclick="openSeriesBatchPanel()">批量操作</button>':''}`
    : (state.seriesPublicEditMode?'<button class="btn" onclick="cancelSeriesPublicEdit()">取消编辑</button><button class="btn primary" onclick="saveSeriesTemplate()">保存公共信息</button>':'<button class="btn" onclick="openSeriesPublicFieldOrderPanel()">排列字段</button><button class="btn" onclick="editSeriesTemplate()">编辑公共信息</button>');
  const lifecycleActions=state.seriesPublicEditMode?'':`<button class="btn" onclick="archiveSeries(false)">结案归档</button><button class="btn danger" onclick="deleteSeries(${Number(data.id)})">删除</button>`;
  $('seriesWorkspaceActions').innerHTML = `${isOfflineReadonly() ? '<span class="tag">离线只读</span>' : `${childActions}${lifecycleActions}`}<button class="btn series-close-btn" onclick="closeSeriesWorkspace()">返回案件列表</button>`;
  const profile = data.profile || {};
  $('seriesWorkspaceBody').innerHTML = `${seriesWorkspaceTabsHtml(stats)}${state.seriesWorkspaceTab==='public'?seriesPublicInfoHtml(data):`<div class="series-tab-panel children">${seriesChildrenToolbarHtml(stats)}<div id="seriesChildTableHost"></div></div>`}`;
  if(state.seriesWorkspaceTab==='children'){renderSeriesChildTable();scheduleSeriesMobileLayoutSync();}
  else {prepareSeriesPublicFieldOrder();activateSeriesLookups($('seriesWorkspaceBody'));requestAnimationFrame(()=>{document.querySelectorAll('#seriesWorkspace textarea.series-public-inline-value').forEach(resizeSeriesPublicInlineEditor);const clients=$('seriesPublicClientNames');if(clients)previewSeriesPublicClients(clients.value);});}
}
function seriesStat(label,value,cls='',hint='') { return `<article class="series-stat ${cls}"><span>${esc(label)}</span><strong>${esc(value)}</strong>${hint?`<small class="series-paste-help">${esc(hint)}</small>`:''}</article>`; }
function childSearchText(item) { return [item.series_code,item.display_name,item.clients,item.opponents,item.case_no,item.court,item.current_stage,item.case_focus,item.other_differences,item.memo,...Object.values(item.custom_values||{})].join(' ').toLowerCase(); }
function currentSeriesColumns(){return state.seriesWorkspace?.profile?.table_columns?.length?state.seriesWorkspace.profile.table_columns:SERIES_DEFAULT_COLUMNS;}
function currentSeriesVisibleColumns(){return currentSeriesColumns().filter(column=>column.hidden!==true);}
const SERIES_EDITOR_FIXED_KEYS=new Set(['series_code','display_name','case_type','current_stage','clients','opponents','case_no','court','facts_difference','contract_difference','other_differences','case_focus','memo']);
const SERIES_EDITOR_DIRECT_DYNAMIC_KEYS=new Set(['court_contact','party_contact']);
function seriesEditorColumnLabel(key,fallback){return currentSeriesColumns().find(column=>column.key===key)?.label||fallback;}
function seriesEditorGroupLabel(keys,fallback){const labels=keys.map(key=>currentSeriesColumns().find(column=>column.key===key)?.label).filter(Boolean);return labels.length?labels.join(' / '):fallback;}
function seriesEditorTableFieldHtml(item,column,index){
  const value=String(seriesCellValue(item,column.key)??'');
  const readonly=column.field_type==='readonly'||column.source==='derived'||column.key==='source_status'||seriesDetailDisplayColumn(column.key);
  const id=`childTableField${index}${String(column.key).replace(/[^a-zA-Z0-9]/g,'')}`;
  const lookupKinds=['clients','opponents','parties','case_types','stages','courts','party_roles','number_types'];
  const lookup=lookupKinds.includes(column.source)?` data-series-lookup="${esc(column.source)}" list="${id}List" autocomplete="off"`:'';
  const target=SERIES_EDITOR_DIRECT_DYNAMIC_KEYS.has(column.key)?'direct':'custom';
  const multiline=value.includes('\n');
  const full=column.field_type==='textarea'||multiline||value.length>60?' full':'';
  if(readonly)return `<div class="${full.trim()}"><label>${esc(column.label)} <span class="tag">${seriesDetailDisplayColumn(column.key)?'详情页展示':'系统汇总'}</span></label><div class="series-editor-readonly">${formatMulti(value||'—')}</div></div>`;
  const attrs=`data-series-editor-field="${esc(column.key)}" data-series-editor-target="${target}"`;
  const hint=column.semantic_type==='amount'?` <span class="series-paste-help">${esc(column.currency||'CNY')} · 纳入顶部汇总</span>`:'';
  if(column.field_type==='textarea'||multiline||value.length>60)return `<div class="full"><label>${esc(column.label)}${hint}</label><textarea class="input" id="${id}" ${attrs}>${esc(value)}</textarea></div>`;
  return `<div><label>${esc(column.label)}${hint}</label><input class="input" id="${id}" value="${esc(value)}" ${attrs}${column.semantic_type==='amount'?' inputmode="decimal"':''}${lookup}>${lookup?`<datalist id="${id}List"></datalist>`:''}</div>`;
}
function seriesEditorTableFieldsHtml(item={}){
  const columns=currentSeriesVisibleColumns().filter(column=>!SERIES_EDITOR_FIXED_KEYS.has(column.key));
  if(!columns.length)return '';
  return `<section class="series-detail-block series-editor-table-section"><h3>主表其他字段（与当前表格一致）</h3><div class="series-paste-help">这里的字段、名称和顺序直接采用当前系列主表；保存后主表与详情同步更新。</div><div class="series-form-grid">${columns.map((column,index)=>seriesEditorTableFieldHtml(item,column,index)).join('')}</div></section>`;
}
function collectSeriesEditorTableFields(){
  const direct={},custom={};
  document.querySelectorAll('#seriesSideBody [data-series-editor-field]').forEach(input=>{
    const key=input.dataset.seriesEditorField,value=input.value.trim();
    if(input.dataset.seriesEditorTarget==='direct')direct[key]=value;else custom[key]=value;
  });
  return {direct,custom};
}
function currentSeriesSettings(){const raw=state.seriesWorkspace?.profile?.table_settings||{};return {freeze_columns:Math.max(0,Number(raw.freeze_columns??2)),freeze_rows:Math.max(0,Number(raw.freeze_rows??0))};}
function seriesCellValue(item,key){
  if(item?._seriesDetailDisplayValues && Object.prototype.hasOwnProperty.call(item._seriesDetailDisplayValues,key))return item._seriesDetailDisplayValues[key]??'';
  return seriesRawCellValue(item,key);
}
function seriesRawCellValue(item,key){
  if(key==='latest_milestone')return item.latest_milestone?.title||'';
  if(key==='next_milestone')return item.next_milestone?.title||'';
  if(key==='claim_totals')return seriesMoney(item.claim_totals);
  if(key==='source_status')return SERIES_STATUS_LABELS[item.source_status]||item.source_status||'';
  if(Object.prototype.hasOwnProperty.call(item,key))return item[key]??'';
  return item.custom_values?.[key]??'';
}
function seriesDetailMappings(seriesData = state.seriesWorkspace){
  const mappings = seriesData?.profile?.detail_field_mappings;
  return Array.isArray(mappings) ? mappings : [];
}
function seriesDetailDisplayColumn(key, seriesData = state.seriesWorkspace){
  return seriesDetailMappings(seriesData).some(mapping => mapping.source_key === key && ['contacts', 'memo'].includes(mapping.target_key));
}
function seriesDetailMappingColumn(key, seriesData = state.seriesWorkspace){
  return (seriesData?.profile?.table_columns || SERIES_DEFAULT_COLUMNS).find(column => column.key === key);
}
function seriesMappedValue(child, key){
  return String(seriesRawCellValue(child, key) ?? '').trim();
}
function splitSeriesMappedValues(value){
  return String(value || '').split(/[、，,；;\n]+/).map(item => item.trim()).filter(Boolean);
}
function applySeriesDetailMappings(child, seriesData){
  const mappings = seriesDetailMappings(seriesData);
  if (!mappings.length) return {...child, detail_contact_selection: normalizeDetailContactSelection(child.detail_contact_selection || child.detail_contact_selection_json)};
  const item = {...child, parties:[...(child.parties || [])], case_numbers:[...(child.case_numbers || [])]};
  const mappedContacts = [];
  const displayValues = {};
  const detailContactGroups = CONTACT_CATEGORIES.flatMap(category => {
    const parsed = parseContactGroups(child)[category.key] || [];
    return parsed.filter(contactGroupHasData).map(group => ({...group, category: category.key}));
  });
  const selection = normalizeDetailContactSelection(child.detail_contact_selection || child.detail_contact_selection_json);
  mappings.forEach(mapping => {
    const value = seriesMappedValue(child, mapping.source_key);
    if (!value && !['contacts', 'memo'].includes(mapping.target_key)) return;
    const sourceLabel = seriesDetailMappingColumn(mapping.source_key, seriesData)?.label || mapping.source_key;
    if (mapping.target_key === 'parties.other') {
      const known = new Set(item.parties.map(party => String(party.name || '').trim()).filter(Boolean));
      splitSeriesMappedValues(value).forEach(name => {
        if (!known.has(name)) item.parties.push({party_group:'other', role:'', name, credit_code:'', source:'series_mapping'});
      });
    } else if (mapping.target_key === 'contacts') {
      const ids = selection[mapping.source_key];
      const selected = ids
        ? detailContactGroups.filter(group => ids.includes(contactGroupId(group)))
        : detailContactGroups.length === 1 ? detailContactGroups : [];
      if (selected.length) {
        displayValues[mapping.source_key] = formatContactGroups(selected);
      } else if (!Object.prototype.hasOwnProperty.call(selection, mapping.source_key) && !detailContactGroups.length && value) {
        const legacy = seriesMappedContactGroup(sourceLabel, value);
        mappedContacts.push(legacy);
        displayValues[mapping.source_key] = value;
      }
    } else if (mapping.target_key === 'memo') {
      const memo = String(child.memo || '').trim();
      if (memo) displayValues[mapping.source_key] = memo;
      else if (!Object.prototype.hasOwnProperty.call(selection, '__memo__')) {
        item.memo = value;
        displayValues[mapping.source_key] = value;
      } else displayValues[mapping.source_key] = '';
    } else if (mapping.target_key === 'case_type' || mapping.target_key === 'current_stage') {
      item[mapping.target_key] = value;
    } else if (mapping.target_key === 'case_no' || mapping.target_key === 'court') {
      if (!item.case_numbers.length) item.case_numbers.push({number_type:'',case_no:'',court:''});
      item.case_numbers[0] = {...item.case_numbers[0], [mapping.target_key]: value};
    }
  });
  item.detail_contact_selection = selection;
  item._seriesDetailDisplayValues = displayValues;
  item._seriesDetailMappedContacts = mappedContacts;
  return item;
}
function seriesMappedContactGroup(label, value) {
  const raw = String(value || '').trim();
  const name = seriesContactNameFromCell(raw);
  const phone = seriesExtractPhone(raw);
  const email = seriesExtractEmail(raw);
  const remaining = raw.split(/\r?\n/).map(line => line.trim()).filter(line => {
    if (!line || line === name || line === phone || line === email) return false;
    return !/(?:电话|手机|邮箱|email)\s*[：:]/i.test(line);
  }).join('\n');
  return { groupId: `mapped_${String(label || 'contact').replace(/[^a-zA-Z0-9一-龥]+/g, '_')}`, roleType: label || '联系人', name, phone, email, notes: remaining };
}
function decorateSeriesWorkspaceChildren(seriesData = state.seriesWorkspace) {
  if (!seriesData?.children) return seriesData;
  seriesData.children = seriesData.children.map(child => applySeriesDetailMappings(child, seriesData));
  return seriesData;
}
function seriesTextUnits(value){
  return Math.max(0,...String(value??'').split(/\r?\n/).map(line=>[...line].reduce((sum,char)=>sum+(/[\u2e80-\u9fff\uf900-\ufaff]/.test(char)?2:1),0)));
}
function seriesAutoColumnWidth(column,items=[]){
  if(column.manual_width)return Math.max(80,Math.min(420,Number(column.width||150)));
  const headerWidth=Math.ceil(seriesTextUnits(column.label||'')*6.3)+76;
  const lengths=items.map(item=>seriesTextUnits(seriesCellValue(item,column.key))).filter(Boolean).sort((a,b)=>a-b);
  const representative=lengths.length?lengths[Math.min(lengths.length-1,Math.floor(lengths.length*.9))]:0;
  const contentWidth=Math.ceil(representative*6.2)+30;
  let min=118,max=240;
  if(column.key==='series_code'){min=92;max=132;}
  else if(column.semantic_type==='amount'||column.field_type==='number'||column.field_type==='amount'){min=132;max=190;}
  else if(['current_stage','source_status'].includes(column.key)){min=118;max=166;}
  else if(['display_name','clients','opponents','case_type','case_no','court','other_differences','case_focus','memo'].includes(column.key)||column.field_type==='textarea'){min=158;max=280;}
  return Math.max(min,Math.min(max,Math.max(headerWidth,contentWidth)));
}
function seriesColumnsWithSmartWidths(columns,items){return columns.map(column=>({...column,width:seriesAutoColumnWidth(column,items)}));}
function seriesShouldWrapCell(column,value){
  if(column.field_type==='textarea')return true;
  if(['display_name','case_no','other_differences','case_focus','memo'].includes(column.key))return true;
  return column.source==='custom'&&column.semantic_type!=='amount'&&String(value??'').length>18;
}
function seriesAutoGrowCell(input){if(input?.tagName!=='TEXTAREA')return;input.style.height='30px';const height=Math.min(156,Math.max(30,input.scrollHeight));input.style.height=`${height}px`;input.style.overflowY=input.scrollHeight>156?'auto':'hidden';}
function seriesColumnLetters(index) {
  let value=Number(index)+1, result='';
  while(value>0){value-=1;result=String.fromCharCode(65+(value%26))+result;value=Math.floor(value/26);}
  return result;
}
function seriesCellAddress(row,column){return `${seriesColumnLetters(column)}${Number(row)+1}`;}
function seriesSelectionBounds() {
  const selection=state.seriesCellSelection;
  if(!selection)return null;
  return {rowStart:Math.min(selection.startRow,selection.endRow),rowEnd:Math.max(selection.startRow,selection.endRow),columnStart:Math.min(selection.startColumn,selection.endColumn),columnEnd:Math.max(selection.startColumn,selection.endColumn)};
}
function seriesMultiCellKey(row,column){return `${row}:${column}`;}
function seriesSelectedCellKeySet(){
  const bounds=seriesSelectionBounds(),keys=new Set();
  if(bounds)for(let row=bounds.rowStart;row<=bounds.rowEnd;row++)for(let column=bounds.columnStart;column<=bounds.columnEnd;column++)keys.add(seriesMultiCellKey(row,column));
  (state.seriesCellMultiSelection||new Set()).forEach(key=>keys.add(key));
  return keys;
}
function seriesSelectionAnchorBounds(){
  const bounds=seriesSelectionBounds();
  if(bounds)return bounds;
  const first=(state.seriesCellMultiSelection||new Set()).values().next().value;
  if(first===undefined)return null;
  const [row,column]=first.split(':').map(Number);
  return {rowStart:row,rowEnd:row,columnStart:column,columnEnd:column};
}
function seriesSelectionRangeLabel() {
  const bounds=seriesSelectionBounds();
  const extra=(state.seriesCellMultiSelection||new Set()).size;
  if(!bounds)return extra?`${extra} 个单元格`:'未选择';
  const start=seriesCellAddress(bounds.rowStart,bounds.columnStart),end=seriesCellAddress(bounds.rowEnd,bounds.columnEnd);
  const base=start===end?start:`${start}:${end}`;
  return extra?`${base} +${extra} 个单元格`:base;
}
function seriesSheetBarHtml() {
  return `<div class="series-sheet-bar">
    <span class="series-range-label" id="seriesRangeLabel">${seriesSelectionRangeLabel()}</span>
    <input class="input series-formula-input" id="seriesFormulaInput" placeholder="输入值或公式，如 =SUM(F1:F10)" onkeydown="if(event.key==='Enter'){event.preventDefault();applySeriesFormulaBar()}">
    <button class="btn" type="button" onclick="prepareSeriesSumFormula()" title="只计算当前区域，不改动任何单元格">Σ 计算求和</button>
    <button class="btn" type="button" onclick="fillSeriesSelectionDown()" title="仅将第一行内容填入下方空白单元格">向下填充空白格</button>
    <button class="btn primary" type="button" onclick="applySeriesFormulaBar()">填入空白格</button>
  </div><div class="series-sheet-status" id="seriesSheetStatus">所有批量写入默认跳过已有内容，并可用“撤销”恢复。</div>`;
}
let seriesSelectionAutoScrollFrame = 0;
let seriesSelectionPointer = null;
function seriesSelectionCellAtPoint(x,y){
  const host=document.querySelector('#seriesChildTableHost .series-table-wrap');if(!host)return null;
  const direct=document.elementFromPoint(x,y)?.closest?.('td[data-series-row-index]');
  if(direct&&host.contains(direct))return direct;
  const cells=[...host.querySelectorAll('td[data-series-row-index]')];if(!cells.length)return null;
  const rows=new Map();
  cells.forEach(cell=>{const row=Number(cell.dataset.seriesRowIndex);if(!rows.has(row))rows.set(row,[]);rows.get(row).push(cell);});
  const rowEntries=[...rows.entries()].sort((a,b)=>a[0]-b[0]);
  let selectedRow=rowEntries[0];let rowDistance=Infinity;
  rowEntries.forEach(entry=>{
    const rect=entry[1][0].getBoundingClientRect();
    const distance=y<rect.top?rect.top-y:y>rect.bottom?y-rect.bottom:0;
    if(distance<rowDistance){rowDistance=distance;selectedRow=entry;}
  });
  const rowCells=selectedRow?.[1]||[];if(!rowCells.length)return null;
  let selectedCell=rowCells[0],cellDistance=Infinity;
  rowCells.forEach(cell=>{
    const rect=cell.getBoundingClientRect();
    const distance=x<rect.left?rect.left-x:x>rect.right?x-rect.right:0;
    if(distance<cellDistance){cellDistance=distance;selectedCell=cell;}
  });
  return selectedCell;
}
function scheduleSeriesSelectionAutoScroll(){
  if(seriesSelectionAutoScrollFrame||!state.seriesSelectionDragging)return;
  seriesSelectionAutoScrollFrame=requestAnimationFrame(seriesSelectionAutoScrollStep);
}
function seriesSelectionScrollContainers(){
  const host=document.querySelector('#seriesChildTableHost .series-table-wrap');if(!host)return [];
  const containers=[];let node=host;
  while(node&&node!==document.body){
    const style=getComputedStyle(node),scrollable=['auto','scroll'].includes(style.overflowY||style.overflow);
    if(scrollable&&node.scrollHeight>node.clientHeight+1)containers.push(node);
    node=node.parentElement;
  }
  const documentScroller=document.scrollingElement;
  if(documentScroller&&documentScroller.scrollHeight>documentScroller.clientHeight+1&&!containers.includes(documentScroller))containers.push(documentScroller);
  return containers;
}
function seriesSelectionAutoScrollStep(){
  seriesSelectionAutoScrollFrame=0;
  if(!state.seriesSelectionDragging||!seriesSelectionPointer)return;
  const containers=seriesSelectionScrollContainers();
  for(const container of containers){
    const rect=container===document.scrollingElement?{top:0,bottom:window.innerHeight,height:window.innerHeight}:container.getBoundingClientRect();
    if(rect.height<=0)continue;
    const edge=Math.min(72,Math.max(30,rect.height*.18));
    let delta=0;
    if(seriesSelectionPointer.y<rect.top+edge)delta=-Math.min(32,Math.max(2,Math.ceil((rect.top+edge-seriesSelectionPointer.y)/edge*24)));
    else if(seriesSelectionPointer.y>rect.bottom-edge)delta=Math.min(32,Math.max(2,Math.ceil((seriesSelectionPointer.y-(rect.bottom-edge))/edge*24)));
    if(delta){
      const previous=container.scrollTop;
      container.scrollTop=Math.max(0,Math.min(container.scrollHeight-container.clientHeight,container.scrollTop+delta));
      if(container.scrollTop!==previous){
        const cell=seriesSelectionCellAtPoint(seriesSelectionPointer.x,seriesSelectionPointer.y);
        if(cell)extendSeriesCellSelection(Number(cell.dataset.seriesRowIndex),Number(cell.dataset.seriesColumnIndex));
        break;
      }
    }
  }
  scheduleSeriesSelectionAutoScroll();
}
function handleSeriesSelectionPointerMove(event){
  if(!state.seriesSelectionDragging)return;
  event.preventDefault();
  seriesSelectionPointer={x:event.clientX,y:event.clientY};
  const cell=seriesSelectionCellAtPoint(event.clientX,event.clientY);
  if(cell)extendSeriesCellSelection(Number(cell.dataset.seriesRowIndex),Number(cell.dataset.seriesColumnIndex));
  scheduleSeriesSelectionAutoScroll();
}
function startSeriesSelectionAutoScroll(event,listen=true){
  seriesSelectionPointer={x:event.clientX,y:event.clientY};
  if(listen)window.addEventListener('mousemove',handleSeriesSelectionPointerMove);
  scheduleSeriesSelectionAutoScroll();
}
function stopSeriesSelectionAutoScroll(){
  window.removeEventListener('mousemove',handleSeriesSelectionPointerMove);
  if(seriesSelectionAutoScrollFrame)cancelAnimationFrame(seriesSelectionAutoScrollFrame);
  seriesSelectionAutoScrollFrame=0;seriesSelectionPointer=null;
}
function startSeriesCellSelection(event,row,column) {
  if(!state.seriesTableEditMode||event.button!==0||event.target.closest('input,textarea,button,select,a,[contenteditable="true"]'))return;
  event.preventDefault();
  event.currentTarget?.closest('.series-table-wrap')?.focus({preventScroll:true});
  if(event.metaKey||event.ctrlKey){
    const key=seriesMultiCellKey(row,column);
    if(state.seriesCellMultiSelection.has(key))state.seriesCellMultiSelection.delete(key);
    else state.seriesCellMultiSelection.add(key);
    state.seriesSelectionDragging=false;
    applySeriesCellSelectionStyles();
    return;
  }
  state.seriesCellMultiSelection.clear();
  state.seriesCellSelection={startRow:row,startColumn:column,endRow:row,endColumn:column};
  state.seriesSelectionDragging=true;
  applySeriesCellSelectionStyles();
  startSeriesSelectionAutoScroll(event);
  window.addEventListener('mouseup',finishSeriesCellSelection,{once:true});
}
function beginSeriesEditorSelection(event,childId,key) {
  if(!state.seriesTableEditMode||event.button!==0)return;
  const columns=currentSeriesVisibleColumns(),items=seriesFilteredItems(columns),row=items.findIndex(item=>Number(item.id)===Number(childId)),column=columns.findIndex(item=>item.key===key);
  if(row<0||column<0)return;
  const startX=event.clientX,startY=event.clientY;
  let selecting=false;
  const move=moveEvent=>{
    if(!selecting&&Math.hypot(moveEvent.clientX-startX,moveEvent.clientY-startY)<5)return;
    if(!selecting){
      selecting=true;
      state.seriesCellMultiSelection.clear();
      state.seriesCellSelection={startRow:row,startColumn:column,endRow:row,endColumn:column};
      state.seriesSelectionDragging=true;
    }
    moveEvent.preventDefault();
    startSeriesSelectionAutoScroll(moveEvent,false);
    const cell=seriesSelectionCellAtPoint(moveEvent.clientX,moveEvent.clientY);
    if(cell)extendSeriesCellSelection(Number(cell.dataset.seriesRowIndex),Number(cell.dataset.seriesColumnIndex));
  };
  const up=()=>{window.removeEventListener('mousemove',move);if(selecting)finishSeriesCellSelection();};
  window.addEventListener('mousemove',move);
  window.addEventListener('mouseup',up,{once:true});
}
function extendSeriesCellSelection(row,column) {
  if(!state.seriesSelectionDragging||!state.seriesCellSelection)return;
  state.seriesCellSelection.endRow=row;state.seriesCellSelection.endColumn=column;
  applySeriesCellSelectionStyles();
}
function finishSeriesCellSelection(){state.seriesSelectionDragging=false;stopSeriesSelectionAutoScroll();applySeriesCellSelectionStyles();}
function selectSeriesColumn(event,column) {
  if(!state.seriesTableEditMode||event.target.closest('input,button,select,textarea'))return;
  const rows=seriesFilteredItems(currentSeriesVisibleColumns()).length;
  if(!rows)return;
  event.preventDefault();
  state.seriesCellMultiSelection.clear();
  state.seriesCellSelection={startRow:0,startColumn:column,endRow:rows-1,endColumn:column};
  applySeriesCellSelectionStyles();
}
function seriesSelectedCellModels() {
  const columns=currentSeriesVisibleColumns(),items=seriesFilteredItems(columns),result=[];
  seriesSelectedCellKeySet().forEach(key=>{
    const [row,column]=key.split(':').map(Number);
    if(items[row]&&columns[column])result.push({row,column,item:items[row],columnDef:columns[column],value:seriesCellValue(items[row],columns[column].key)});
  });
  return result;
}
function applySeriesCellSelectionStyles() {
  const bounds=seriesSelectionBounds();
  const multi=state.seriesCellMultiSelection||new Set();
  document.querySelectorAll('#seriesChildTableHost td[data-series-row-index]').forEach(cell=>{
    const row=Number(cell.dataset.seriesRowIndex),column=Number(cell.dataset.seriesColumnIndex);
    const inRect=!!bounds&&row>=bounds.rowStart&&row<=bounds.rowEnd&&column>=bounds.columnStart&&column<=bounds.columnEnd;
    const inMulti=multi.has(seriesMultiCellKey(row,column));
    const selected=inRect||inMulti;
    cell.classList.toggle('series-cell-selected',selected);
    cell.classList.toggle('series-cell-anchor',inRect&&row===state.seriesCellSelection.startRow&&column===state.seriesCellSelection.startColumn);
  });
  const label=$('seriesRangeLabel');if(label)label.textContent=seriesSelectionRangeLabel();
  const status=$('seriesSheetStatus');
  if(status){
    const models=seriesSelectedCellModels(),numbers=models.map(model=>seriesParseAmount(model.value)).filter(value=>!Number.isNaN(value));
    status.textContent=models.length?`已选择 ${models.length} 个单元格${numbers.length?` · 数值 ${numbers.length} 项 · 求和 ${numbers.reduce((sum,value)=>sum+value,0).toLocaleString('zh-CN',{maximumFractionDigits:8})} · 平均值 ${(numbers.reduce((sum,value)=>sum+value,0)/numbers.length).toLocaleString('zh-CN',{maximumFractionDigits:8})}`:''}`:'选择单元格后可计算、填充或粘贴；批量写入可撤销，且默认不覆盖已有内容。';
  }
}
function seriesFormulaReferenceValue(reference) {
  const match=String(reference||'').match(/^([A-Z]+)(\d+)$/i);if(!match)return NaN;
  let column=0;for(const char of match[1].toUpperCase())column=column*26+char.charCodeAt(0)-64;column-=1;
  const row=Number(match[2])-1,columns=currentSeriesVisibleColumns(),items=seriesFilteredItems(columns);
  return seriesParseAmount(items[row]?seriesCellValue(items[row],columns[column]?.key):'');
}
function seriesFormulaRangeValues(range) {
  const [start,end]=String(range).split(':');const first=String(start||'').match(/^([A-Z]+)(\d+)$/i),last=String(end||start||'').match(/^([A-Z]+)(\d+)$/i);
  if(!first||!last)return [];
  const letterIndex=value=>{let result=0;for(const char of value.toUpperCase())result=result*26+char.charCodeAt(0)-64;return result-1;};
  const rowStart=Math.min(Number(first[2]),Number(last[2]))-1,rowEnd=Math.max(Number(first[2]),Number(last[2]))-1,columnStart=Math.min(letterIndex(first[1]),letterIndex(last[1])),columnEnd=Math.max(letterIndex(first[1]),letterIndex(last[1]));
  const columns=currentSeriesVisibleColumns(),items=seriesFilteredItems(columns),values=[];
  for(let row=rowStart;row<=rowEnd;row++)for(let column=columnStart;column<=columnEnd;column++){const value=seriesParseAmount(items[row]?seriesCellValue(items[row],columns[column]?.key):'');if(!Number.isNaN(value))values.push(value);}
  return values;
}
function evaluateSeriesFormula(formula) {
  const source=String(formula||'').trim();if(!source.startsWith('='))return source;
  const functionMatch=source.match(/^=(SUM|AVERAGE|MIN|MAX)\(([A-Z]+\d+(?::[A-Z]+\d+)?)\)$/i);
  if(functionMatch){
    const values=seriesFormulaRangeValues(functionMatch[2]);if(!values.length)throw new Error('公式引用范围中没有可计算的数字');
    const operation=functionMatch[1].toUpperCase();
    if(operation==='SUM')return values.reduce((sum,value)=>sum+value,0);
    if(operation==='AVERAGE')return values.reduce((sum,value)=>sum+value,0)/values.length;
    return operation==='MIN'?Math.min(...values):Math.max(...values);
  }
  const expression=source.slice(1).replace(/[A-Z]+\d+/gi,reference=>{const value=seriesFormulaReferenceValue(reference);if(Number.isNaN(value))throw new Error(`单元格 ${reference.toUpperCase()} 不是数字`);return `(${value})`;});
  if(!/^[\d+\-*/().\s]+$/.test(expression))throw new Error('仅支持单元格引用、数字和 + - * / 四则运算');
  const result=Function(`"use strict";return (${expression})`)();
  if(!Number.isFinite(result))throw new Error('公式计算结果无效');
  return result;
}
function prepareSeriesSumFormula() {
  const bounds=seriesSelectionBounds();if(!bounds)return toast('请先拖动选择需要求和的单元格');
  const formula=`=SUM(${seriesCellAddress(bounds.rowStart,bounds.columnStart)}:${seriesCellAddress(bounds.rowEnd,bounds.columnEnd)})`;
  try{
    const result=evaluateSeriesFormula(formula);
    const input=$('seriesFormulaInput');if(input)input.value=formula;
    const status=$('seriesSheetStatus');if(status)status.textContent=`求和结果：${Number(result).toLocaleString('zh-CN',{maximumFractionDigits:8})}（仅计算，未修改表格）`;
  }catch(e){toast(e.message);}
}
function seriesCellEditable(column){return column&&column.field_type!=='readonly'&&column.source!=='derived'&&!seriesDetailDisplayColumn(column.key)&&!isOfflineReadonly();}
function updateSeriesHistoryButtons(){
  const undo=$('seriesUndoButton'),redo=$('seriesRedoButton');
  if(undo)undo.disabled=!state.seriesUndoStack.length||state.seriesHistoryBusy;
  if(redo)redo.disabled=!state.seriesRedoStack.length||state.seriesHistoryBusy;
}
function pushSeriesHistory(entry){
  if(!entry||state.seriesHistoryBusy)return;
  state.seriesUndoStack.push(entry);if(state.seriesUndoStack.length>80)state.seriesUndoStack.shift();
  state.seriesRedoStack=[];updateSeriesHistoryButtons();
}
function handleSeriesWorkspaceKeydown(event){
  if(!state.seriesTableEditMode||!(event.metaKey||event.ctrlKey)||event.target.closest('input,textarea,select,[contenteditable="true"]'))return;
  const key=String(event.key||'').toLowerCase();
  if(key==='z'&&!event.shiftKey){event.preventDefault();undoSeriesEdit();}
  else if(key==='y'||(key==='z'&&event.shiftKey)){event.preventDefault();redoSeriesEdit();}
}
function cloneSeriesCellFormat(format={}){
  const cloned={};
  if(Array.isArray(format?.runs)&&format.runs.length)cloned.runs=format.runs.map(run=>({...run}));
  if(format?.align)cloned.align=format.align;
  if(format?.vertical_align)cloned.vertical_align=format.vertical_align;
  if(format?.cell_background)cloned.cell_background=format.cell_background;
  return cloned;
}
function seriesCellFormatHasContent(format={}){return Boolean(format?.runs?.length||format?.align||format?.vertical_align||format?.cell_background);}
async function saveSeriesCellFormatBatch(updates,{label='设置单元格格式',recordHistory=true}={}){
  if(!updates.length)return;
  const normalized=updates.map(update=>({childId:Number(update.childId??update.model?.item?.id),field:String(update.field??update.model?.columnDef?.key??''),before:cloneSeriesCellFormat(update.before),format:cloneSeriesCellFormat(update.format)})).filter(update=>update.childId&&update.field);
  if(!normalized.length)return;
  await Promise.all(normalized.map(update=>api(`/api/case-manager/series/${state.seriesWorkspace.id}/children/${update.childId}/cell-format`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({field:update.field,format:update.format})})));
  normalized.forEach(update=>{
    const item=(state.seriesWorkspace.children||[]).find(child=>Number(child.id)===update.childId);if(!item)return;
    item.cell_formats={...(item.cell_formats||{})};
    if(seriesCellFormatHasContent(update.format))item.cell_formats[update.field]=update.format;else delete item.cell_formats[update.field];
  });
  if(recordHistory)pushSeriesHistory({type:'cell_formats',label,before:normalized.map(update=>({childId:update.childId,field:update.field,format:update.before})),after:normalized.map(update=>({childId:update.childId,field:update.field,format:update.format}))});
}
async function saveSeriesCellBatch(updates,{label='编辑单元格',recordHistory=true}={}) {
  if(!updates.length)return toast('所选区域没有可编辑的单元格');
  const unique=new Map();
  updates.forEach(update=>unique.set(`${Number(update.childId)}::${update.field}`,{...update,childId:Number(update.childId),value:String(update.value??'')}));
  const normalized=[...unique.values()];
  const children=state.seriesWorkspace?.children||[];
  const before=normalized.map(update=>{
    const item=children.find(child=>Number(child.id)===update.childId);
    return {...update,value:String(item?seriesCellValue(item,update.field)??'':'')};
  });
  const effective=normalized.filter((update,index)=>String(update.value)!==String(before[index].value));
  if(!effective.length)return toast('没有需要写入的变化');
  const effectiveBefore=before.filter((_,index)=>String(normalized[index].value)!==String(before[index].value));
  try{
    await Promise.all(effective.map(update=>api(`/api/case-manager/series/${state.seriesWorkspace.id}/children/${update.childId}/cell`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({field:update.field,value:update.value})})));
    await reloadSeriesWorkspace();
    if(recordHistory)pushSeriesHistory({type:'cells',label,before:effectiveBefore,after:effective});
    toast(`已更新 ${effective.length} 个单元格${recordHistory?'，可撤销':''}`);
  }catch(e){toast(e.message);}
}
async function applySeriesFormulaBar() {
  const models=seriesSelectedCellModels();if(!models.length)return toast('请先拖动选择要编辑的单元格');
  const input=$('seriesFormulaInput'),source=input?.value??'';if(!String(source).trim())return toast('请输入要填入的内容或公式');
  try{
    const value=String(source).trim().startsWith('=')?evaluateSeriesFormula(source):source;
    const editable=models.filter(model=>seriesCellEditable(model.columnDef));
    const blank=editable.filter(model=>!String(model.value??'').trim());
    const skipped=editable.length-blank.length;
    if(!blank.length)return toast('所选区域没有空白单元格；为防止覆盖，未作修改');
    await saveSeriesCellBatch(blank.map(model=>({childId:Number(model.item.id),field:model.columnDef.key,value})),{label:'填入空白单元格'});
    if(skipped)toast(`已跳过 ${skipped} 个原有数据单元格，可撤销本次填入`);
  }catch(e){toast(e.message);}
}
async function fillSeriesSelectionDown() {
  const bounds=seriesSelectionBounds();if(!bounds||bounds.rowStart===bounds.rowEnd)return toast('请至少选择两行单元格');
  const models=seriesSelectedCellModels(),updates=[];
  for(let column=bounds.columnStart;column<=bounds.columnEnd;column++){
    const source=models.find(model=>model.row===bounds.rowStart&&model.column===column);if(!source)continue;
    models.filter(model=>model.column===column&&model.row>bounds.rowStart&&seriesCellEditable(model.columnDef)&&!String(model.value??'').trim()).forEach(model=>updates.push({childId:Number(model.item.id),field:model.columnDef.key,value:source.value}));
  }
  if(!updates.length)return toast('下方没有空白单元格；原有数据未被覆盖');
  await saveSeriesCellBatch(updates,{label:'向下填充空白单元格'});
}
async function applySeriesRowOrder(ids,{recordHistory=true,before=null}={}){
  const next=ids.map(Number);
  const previous=before||seriesBaseItemsIgnoringColumn('').map(item=>Number(item.id));
  await api(`/api/case-manager/series/${state.seriesWorkspace.id}/children/order`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({child_ids:next})});
  await reloadSeriesWorkspace();
  if(recordHistory)pushSeriesHistory({type:'row_order',label:'调整行顺序',before:previous,after:next});
}
async function applySeriesHistory(entry,direction){
  const target=direction==='undo'?'before':'after';
  if(entry.type==='cells')await saveSeriesCellBatch(entry[target],{label:entry.label,recordHistory:false});
  else if(entry.type==='cell_formats'){await saveSeriesCellFormatBatch(entry[target],{label:entry.label,recordHistory:false});renderSeriesChildTable();}
  else if(entry.type==='row_order')await applySeriesRowOrder(entry[target],{recordHistory:false});
  else if(entry.type==='columns')await persistSeriesColumns(entry[target],[],entry[`${target}Settings`]||currentSeriesSettings(),{recordHistory:false});
  else if(entry.type==='insert_rows'){
    const operation=direction==='undo'?'delete':'restore';
    await api(`/api/case-manager/series/${state.seriesWorkspace.id}/children/bulk`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({child_ids:entry.ids,operation,payload:{}})});
    if(direction==='redo')await applySeriesRowOrder(entry.afterOrder,{recordHistory:false});
    else await reloadSeriesWorkspace();
  }
}
async function undoSeriesEdit(){
  if(state.seriesHistoryBusy||!state.seriesUndoStack.length)return;
  const entry=state.seriesUndoStack.pop();state.seriesHistoryBusy=true;updateSeriesHistoryButtons();
  try{await applySeriesHistory(entry,'undo');state.seriesRedoStack.push(entry);toast(`已撤销：${entry.label}`);}
  catch(e){state.seriesUndoStack.push(entry);toast(`撤销失败：${e.message}`);}
  finally{state.seriesHistoryBusy=false;updateSeriesHistoryButtons();}
}
async function redoSeriesEdit(){
  if(state.seriesHistoryBusy||!state.seriesRedoStack.length)return;
  const entry=state.seriesRedoStack.pop();state.seriesHistoryBusy=true;updateSeriesHistoryButtons();
  try{await applySeriesHistory(entry,'redo');state.seriesUndoStack.push(entry);toast(`已重做：${entry.label}`);}
  catch(e){state.seriesRedoStack.push(entry);toast(`重做失败：${e.message}`);}
  finally{state.seriesHistoryBusy=false;updateSeriesHistoryButtons();}
}
function seriesSelectionInsertPosition(axis){
  const bounds=seriesSelectionBounds();
  if(axis==='row'){
    const items=seriesFilteredItems(currentSeriesVisibleColumns());
    return bounds&&items[bounds.rowStart]?{index:bounds.rowStart,label:`第 ${bounds.rowStart+1} 行（${seriesCellValue(items[bounds.rowStart],currentSeriesVisibleColumns()[0]?.key)||'当前行'}）`}:{index:items.length,label:'表格末尾'};
  }
  const columns=currentSeriesVisibleColumns();
  return bounds&&columns[bounds.columnStart]?{index:bounds.columnStart,label:`“${columns[bounds.columnStart].label}”列`}:{index:columns.length,label:'最右侧'};
}
function openSeriesInsertRowsPanel(){
  if(!requireOnlineAction())return;
  const reference=seriesSelectionInsertPosition('row');
  showSeriesSide('插入行',`当前参照位置：${reference.label}`,`<section class="series-detail-block"><h3>插入位置和数量</h3><div class="series-form-grid"><div><label>位置</label><select class="input" id="seriesInsertRowSide"><option value="before">当前行之前</option><option value="after" ${reference.index>=(seriesFilteredItems(currentSeriesVisibleColumns()).length)?'selected':''}>当前行之后／表格末尾</option></select></div><div><label>插入行数</label><input class="input" id="seriesInsertRowCount" type="number" min="1" max="100" value="1"></div></div><p class="series-paste-help">先在主表选择任意单元格，即可把新行插入该行之前或之后。</p></section>`,`<button class="btn" onclick="closeSeriesSide()">取消</button><button class="btn primary" onclick="confirmInsertSeriesRows()">插入</button>`);
}
async function confirmInsertSeriesRows(){
  const reference=seriesSelectionInsertPosition('row'),count=Math.max(1,Math.min(100,Number($('seriesInsertRowCount')?.value||1))),side=$('seriesInsertRowSide')?.value||'before';
  const total=seriesFilteredItems(currentSeriesVisibleColumns()).length;
  const position=Math.min(total,reference.index+(side==='after'&&reference.index<total?1:0));
  try{
    const beforeOrder=seriesBaseItemsIgnoringColumn('').map(item=>Number(item.id));
    const data=await api(`/api/case-manager/series/${state.seriesWorkspace.id}/children/insert`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({position,count})});
    closeSeriesSide();await reloadSeriesWorkspace();
    const afterOrder=seriesBaseItemsIgnoringColumn('').map(item=>Number(item.id));
    pushSeriesHistory({type:'insert_rows',label:`插入 ${count} 行`,ids:(data.items||[]).map(item=>Number(item.id)),beforeOrder,afterOrder});
    toast(`已插入 ${count} 行，可撤销`);
  }catch(e){toast(e.message);}
}
function openSeriesInsertColumnsPanel(){
  if(!requireOnlineAction())return;
  const reference=seriesSelectionInsertPosition('column');
  showSeriesSide('插入列',`当前参照位置：${reference.label}`,`<section class="series-detail-block"><h3>插入位置和列名</h3><div class="series-form-grid"><div><label>位置</label><select class="input" id="seriesInsertColumnSide"><option value="before">当前列之前</option><option value="after" ${reference.index>=currentSeriesVisibleColumns().length?'selected':''}>当前列之后／最右侧</option></select></div><div><label>插入列数</label><input class="input" id="seriesInsertColumnCount" type="number" min="1" max="50" value="1"></div><div class="full"><label>列名（可选，每行一个）</label><textarea class="input" id="seriesInsertColumnLabels" placeholder="例如：房号&#10;合同金额&#10;经办律师"></textarea></div></div><p class="series-paste-help">未填写的列名将自动命名为“新列 1、 新列 2……”。</p></section>`,`<button class="btn" onclick="closeSeriesSide()">取消</button><button class="btn primary" onclick="confirmInsertSeriesColumns()">插入</button>`);
}
async function confirmInsertSeriesColumns(){
  const reference=seriesSelectionInsertPosition('column'),count=Math.max(1,Math.min(50,Number($('seriesInsertColumnCount')?.value||1))),side=$('seriesInsertColumnSide')?.value||'before';
  const labels=String($('seriesInsertColumnLabels')?.value||'').split(/\r?\n/).map(value=>value.trim()).filter(Boolean);
  const before=currentSeriesColumns().map(column=>({...column})),beforeSettings={...currentSeriesSettings()};
  const visible=currentSeriesVisibleColumns(),target=visible[reference.index],rawIndex=target?before.findIndex(column=>column.key===target.key):before.length;
  const position=Math.max(0,Math.min(before.length,rawIndex+(side==='after'&&target?1:0)));
  const stamp=Date.now().toString(36);
  const additions=Array.from({length:count},(_,index)=>({key:`custom_${stamp}_${index}`,label:labels[index]||`新列 ${index+1}`,source:'custom',field_type:'text',semantic_type:'',currency:'CNY',width:160}));
  const after=[...before.slice(0,position),...additions,...before.slice(position)];
  if(await persistSeriesColumns(after,[],beforeSettings,{recordHistory:false})){
    pushSeriesHistory({type:'columns',label:`插入 ${count} 列`,before,after,beforeSettings,afterSettings:beforeSettings});
    closeSeriesSide();toast(`已插入 ${count} 列，可撤销`);
  }
}
function selectSeriesCellFromEditor(childId,key){
  const columns=currentSeriesVisibleColumns(),items=seriesFilteredItems(columns),row=items.findIndex(item=>Number(item.id)===Number(childId)),column=columns.findIndex(item=>item.key===key);
  if(row<0||column<0)return;
  state.seriesCellMultiSelection.clear();
  state.seriesCellSelection={startRow:row,startColumn:column,endRow:row,endColumn:column};applySeriesCellSelectionStyles();
}
function seriesEditorHasTextSelection(target){
  const editor=target instanceof Element?target.closest('.series-cell-rich-input'):null;
  if(editor){const selection=window.getSelection();return !!selection&&!selection.isCollapsed&&editor.contains(selection.anchorNode)&&editor.contains(selection.focusNode);}
  return (target instanceof HTMLTextAreaElement||target instanceof HTMLInputElement)&&Number.isInteger(target.selectionStart)&&target.selectionStart!==target.selectionEnd;
}
function seriesSelectedCellMatrix(){
  const keys=seriesSelectedCellKeySet();if(!keys.size)return [];
  const columns=currentSeriesVisibleColumns(),items=seriesFilteredItems(columns);
  const rows=[...new Set([...keys].map(key=>Number(key.split(':')[0])))].sort((a,b)=>a-b);
  const cols=[...new Set([...keys].map(key=>Number(key.split(':')[1])))].sort((a,b)=>a-b);
  const matrix=[];
  rows.forEach(row=>{
    if(!items[row])return;
    const values=[];
    cols.forEach(column=>values.push(keys.has(seriesMultiCellKey(row,column))?String(seriesCellValue(items[row],columns[column]?.key)??''):''));
    matrix.push(values);
  });
  return matrix;
}
function seriesClipboardTableHtml(matrix){
  return `<table><tbody>${matrix.map(row=>`<tr>${row.map(value=>`<td>${esc(value).replace(/\n/g,'<br>')}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
}
function handleSeriesTableCopy(event){
  if(!state.seriesTableEditMode||seriesEditorHasTextSelection(event.target))return;
  const matrix=seriesSelectedCellMatrix();if(!matrix.length||!event.clipboardData)return;
  event.preventDefault();
  event.clipboardData.setData('text/plain',matrix.map(row=>row.join('\t')).join('\n'));
  event.clipboardData.setData('text/html',seriesClipboardTableHtml(matrix));
}
function seriesClipboardHasTable(clipboardData){
  return /<table[\s>]/i.test(String(clipboardData?.getData('text/html')||''));
}
function seriesClipboardIsGrid(clipboardData){
  return seriesClipboardHasTable(clipboardData)||String(clipboardData?.getData('text/plain')||'').includes('\t');
}
function seriesClipboardMatrix(clipboardData){
  const text=String(clipboardData?.getData('text/plain')||'');
  const html=String(clipboardData?.getData('text/html')||'');
  if(html&&/<table[\s>]/i.test(html)){
    const table=new DOMParser().parseFromString(html,'text/html').querySelector('table');
    const rows=[...(table?.rows||[])];
    if(rows.length){
      const matrix=[];
      rows.forEach((sourceRow,rowIndex)=>{
        matrix[rowIndex]??=[];
        let columnIndex=0;
        [...sourceRow.cells].forEach(cell=>{
          while(matrix[rowIndex][columnIndex]!==undefined)columnIndex++;
          const content=cell.cloneNode(true);content.querySelectorAll('br').forEach(br=>br.replaceWith('\n'));
          const value=String(content.textContent??'').replace(/\r\n?/g,'\n');
          const rowSpan=Math.max(1,Number(cell.rowSpan||1)),columnSpan=Math.max(1,Number(cell.colSpan||1));
          for(let targetRow=rowIndex;targetRow<rowIndex+rowSpan;targetRow++){
            matrix[targetRow]??=[];
            for(let targetColumn=columnIndex;targetColumn<columnIndex+columnSpan;targetColumn++)matrix[targetRow][targetColumn]=targetRow===rowIndex&&targetColumn===columnIndex?value:'';
          }
          columnIndex+=columnSpan;
        });
      });
      return matrix.map(row=>row.map(value=>value??''));
    }
  }
  return text.replace(/\r\n/g,'\n').replace(/\r/g,'\n').replace(/\n$/,'').split('\n').map(row=>row.split('\t'));
}
async function handleSeriesTablePaste(event){
  if(!state.seriesTableEditMode||isOfflineReadonly())return;
  // 纯文本换行属于一个单元格的内容，应交给 textarea 的原生粘贴处理。
  // 只有 HTML 表格或制表符分列的数据，才按连续单元格区域写入。
  if(!seriesClipboardIsGrid(event.clipboardData))return;
  event.preventDefault();
  const bounds=seriesSelectionAnchorBounds();if(!bounds)return toast('请先点击要开始粘贴的单元格');
  const matrix=seriesClipboardMatrix(event.clipboardData);
  if(!matrix.length||!matrix.some(row=>row.length))return;
  let columns=currentSeriesVisibleColumns(),items=seriesFilteredItems(columns);
  const neededRows=bounds.rowStart+matrix.length-items.length;
  const neededColumns=bounds.columnStart+Math.max(...matrix.map(row=>row.length))-columns.length;
  try{
    if(neededRows>0){
      await api(`/api/case-manager/series/${state.seriesWorkspace.id}/children/insert`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({position:items.length,count:neededRows})});
      await reloadSeriesWorkspace();items=seriesFilteredItems(currentSeriesVisibleColumns());
    }
    if(neededColumns>0){
      const before=currentSeriesColumns().map(column=>({...column})),stamp=Date.now().toString(36);
      const additions=Array.from({length:neededColumns},(_,index)=>({key:`custom_${stamp}_${index}`,label:`粘贴列 ${index+1}`,source:'custom',field_type:'text',semantic_type:'',currency:'CNY',width:160}));
      await persistSeriesColumns([...before,...additions],[],currentSeriesSettings(),{recordHistory:false});
      columns=currentSeriesVisibleColumns();items=seriesFilteredItems(columns);
    }
    const updates=[];
    matrix.forEach((row,rowOffset)=>row.forEach((value,columnOffset)=>{
      const item=items[bounds.rowStart+rowOffset],column=columns[bounds.columnStart+columnOffset];
      if(item&&seriesCellEditable(column))updates.push({childId:Number(item.id),field:column.key,value});
    }));
    await saveSeriesCellBatch(updates,{label:`从电子表格粘贴 ${matrix.length}×${Math.max(...matrix.map(row=>row.length))} 区域`});
  }catch(e){toast(`粘贴失败：${e.message}`);}
}
function prepareSeriesCellLayout(host){
  host.querySelectorAll('textarea.series-cell-input').forEach(seriesAutoGrowCell);
  const frozenRows=currentSeriesSettings().freeze_rows;if(!frozenRows)return;
  const table=host.querySelector('.series-table'),head=table?.tHead;if(!table||!head)return;
  let top=head.getBoundingClientRect().height;
  [...table.tBodies[0].rows].slice(0,frozenRows).forEach(row=>{[...row.cells].forEach(cell=>cell.style.top=`${top}px`);top+=row.getBoundingClientRect().height;});
}
function copySeriesCellText(el){
  const raw=String(el?.dataset?.copy??'');
  if(!raw.trim())return toast('该单元格暂无内容');
  const preview=raw.replace(/\s+/g,' ').slice(0,14)+(raw.length>14?'…':'');
  const done=()=>{el.classList.add('copied');toast(`已复制：${preview}`);setTimeout(()=>el.classList.remove('copied'),1200);};
  const fallback=()=>{const area=document.createElement('textarea');area.value=raw;area.style.cssText='position:fixed;top:0;left:0;opacity:0;pointer-events:none;';document.body.appendChild(area);area.focus();area.select();try{document.execCommand('copy');done();}catch(e){toast('复制失败，请手动选择文本复制');}area.remove();};
  if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(raw).then(done).catch(fallback);}
  else fallback();
}
function seriesRichFormatSegments(value,format={}){
  const text=String(value??''),length=text.length;
  const runs=(format?.runs||[]).map(run=>({
    start:Math.max(0,Math.min(length,Number(run.start)||0)),end:Math.max(0,Math.min(length,Number(run.end)||0)),
    bold:!!run.bold,italic:!!run.italic,underline:!!run.underline,color:run.color==='red'?'red':'',highlight:run.highlight==='yellow'?'yellow':''
  })).filter(run=>run.end>run.start&&(run.bold||run.italic||run.underline||run.color||run.highlight));
  const points=[0,length,...runs.flatMap(run=>[run.start,run.end])].filter((point,index,all)=>all.indexOf(point)===index).sort((a,b)=>a-b),segments=[];
  for(let index=0;index<points.length-1;index++){
    const start=points[index],end=points[index+1],style={};
    runs.filter(run=>run.start<=start&&run.end>=end).forEach(run=>{if(run.bold)style.bold=true;if(run.italic)style.italic=true;if(run.underline)style.underline=true;if(run.color)style.color=run.color;if(run.highlight)style.highlight=run.highlight;});
    segments.push({start,end,style});
  }
  return segments;
}
function seriesRichTextHtml(value,format={}){
  const text=String(value??'');if(!text)return '';
  return seriesRichFormatSegments(text,format).map(segment=>{
    const classes=[segment.style.bold?'series-rich-bold':'',segment.style.italic?'series-rich-italic':'',segment.style.underline?'series-rich-underline':'',segment.style.color==='red'?'series-rich-red':'',segment.style.highlight==='yellow'?'series-rich-highlight':''].filter(Boolean).join(' ');
    const content=esc(text.slice(segment.start,segment.end)).replace(/\n/g,'<br>');
    return classes?`<span class="${classes}">${content}</span>`:content;
  }).join('');
}
function seriesPlainTextFromFragment(node){
  let result='';
  const walk=current=>{
    if(current.nodeType===Node.TEXT_NODE){result+=current.nodeValue||'';return;}
    if(current.nodeType!==Node.ELEMENT_NODE&&current.nodeType!==Node.DOCUMENT_FRAGMENT_NODE)return;
    const tag=current.nodeType===Node.ELEMENT_NODE?current.tagName:'';
    if(tag==='BR'){result+='\n';return;}
    const isBlock=['DIV','P','LI'].includes(tag);
    // 块级分隔符要加在块“前面”：WebKit 回车后 DOM 是 `第一行<div>第二行</div>`，
    // 若只在块后面补 \n，会得到 `第一行第二行\n`，末尾 \n 又被去掉，换行就丢了。
    if(isBlock&&result&&!result.endsWith('\n'))result+='\n';
    const before=result.length;
    current.childNodes.forEach(walk);
    if(isBlock&&result.length>before&&!result.endsWith('\n'))result+='\n';
  };
  walk(node);return result.replace(/\r/g,'');
}
function seriesRichEditorValue(editor){return seriesPlainTextFromFragment(editor).replace(/\n$/,'');}
function seriesEditorSelectionOffsets(editor){
  const selection=window.getSelection();if(!selection||selection.isCollapsed||!selection.rangeCount||!editor.contains(selection.anchorNode)||!editor.contains(selection.focusNode))return null;
  const range=selection.getRangeAt(0),before=range.cloneRange();before.selectNodeContents(editor);before.setEnd(range.startContainer,range.startOffset);
  const start=seriesPlainTextFromFragment(before.cloneContents()).length,end=start+seriesPlainTextFromFragment(range.cloneContents()).length;
  return end>start?{start,end}:null;
}
function seriesFormatModelFromSegments(segments){
  const runs=[];
  segments.forEach(segment=>{
    const style=segment.style||{};if(!style.bold&&!style.italic&&!style.underline&&!style.color&&!style.highlight)return;
    const previous=runs[runs.length-1];
    const same=previous&&previous.end===segment.start&&previous.bold===!!style.bold&&previous.italic===!!style.italic&&previous.underline===!!style.underline&&(previous.color||'')===(style.color||'')&&(previous.highlight||'')===(style.highlight||'');
    if(same){previous.end=segment.end;return;}
    runs.push({start:segment.start,end:segment.end,...(style.bold?{bold:true}:{}),...(style.italic?{italic:true}:{}),...(style.underline?{underline:true}:{}),...(style.color?{color:style.color}:{}),...(style.highlight?{highlight:style.highlight}:{})});
  });
  return runs.length?{runs}:{};
}
function toggleSeriesRichFormat(value,format,start,end,key){
  const segments=seriesRichFormatSegments(value,format),affected=segments.filter(segment=>segment.end>start&&segment.start<end);
  if(!affected.length)return format||{};
  const enabled=affected.every(segment=>!!segment.style[key]);
  affected.forEach(segment=>{if(enabled)delete segment.style[key];else segment.style[key]=key==='color'?'red':key==='highlight'?'yellow':true;});
  return seriesFormatModelFromSegments(segments);
}
async function saveSeriesRichCell(editor,childId,field){
  const original=String(editor.dataset.original??''),next=seriesRichEditorValue(editor);if(original===next)return;
  editor.classList.add('saving');
  try{
    const updated=await api(`/api/case-manager/series/${state.seriesWorkspace.id}/children/${childId}/cell`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({field,value:next})});
    const index=(state.seriesWorkspace.children||[]).findIndex(item=>Number(item.id)===Number(childId));
    if(index>=0)state.seriesWorkspace.children[index]={...state.seriesWorkspace.children[index],...updated,cell_formats:{...(updated.cell_formats||{})}};
    editor.dataset.original=next;editor.classList.remove('saving');editor.classList.add('saved');
    pushSeriesHistory({type:'cells',label:'编辑单元格',before:[{childId:Number(childId),field,value:original}],after:[{childId:Number(childId),field,value:next}]});
    setTimeout(()=>editor.classList.remove('saved'),700);
  }catch(e){editor.textContent=original;editor.classList.remove('saving');toast(e.message);}
}
function closeSeriesTableContextMenu(){
  $('seriesTableContextMenu')?.classList.remove('show');state.seriesTableContext=null;
}
function selectSeriesRow(row){
  const columns=currentSeriesVisibleColumns();if(!columns.length)return;
  state.seriesCellMultiSelection.clear();
  state.seriesCellSelection={startRow:row,startColumn:0,endRow:row,endColumn:columns.length-1};applySeriesCellSelectionStyles();
}
function selectSeriesColumnIndex(column){
  const rows=seriesFilteredItems(currentSeriesVisibleColumns()).length;if(!rows)return;
  state.seriesCellMultiSelection.clear();
  state.seriesCellSelection={startRow:0,startColumn:column,endRow:rows-1,endColumn:column};applySeriesCellSelectionStyles();
}
function seriesExtractPhone(text){
  const match=String(text||'').match(/(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)|(?<!\d)0\d{2,3}[-\s]?\d{7,8}(?!\d)/);
  return match?match[0].trim():'';
}
function seriesExtractEmail(text){
  const match=String(text||'').match(/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/);
  return match?match[0].trim():'';
}
function seriesContactNameForRow(item, columns){
  if(!item)return '';
  const cols = Array.isArray(columns) && columns.length ? columns : currentSeriesColumns();
  const nameColumns=cols.filter(column=>/姓名|联系人|负责人|名称/.test(String(column.label||'')));
  for(const column of nameColumns){
    const value=String(seriesCellValue(item,column.key)||'').trim();
    if(value&&!/[\d@]/.test(value))return value;
  }
  for(const key of ['display_name','clients','opponents']){
    const value=String(seriesCellValue(item,key)||'').trim();
    if(value&&!/[\d@]/.test(value))return value;
  }
  const party=Array.isArray(item.parties)?item.parties.find(entry=>String(entry?.name||'').trim()):null;
  if(party)return String(party.name).trim();
  return '';
}
function seriesContactNameFromCell(raw){
  const excluded=/公司|集团|事务所|法院|银行|合作社|委员会|中心|机构/;
  const lines=String(raw||'').split(/\r?\n/).map(line=>line.trim()).filter(Boolean);
  for(const line of lines){
    if(/电话|手机|邮箱|email|@/i.test(line))continue;
    const candidate=line.replace(/^(?:联系人|承办人|经办人|立案人|姓名|秘书)\s*[：:]\s*/,'').split(/[，,；;]/)[0].trim();
    if(candidate.length<2||excluded.test(candidate)||/[\d]/.test(candidate))continue;
    if(/[\u4e00-\u9fff]/.test(candidate))return candidate;
  }
  return '';
}
function seriesCellContactSyncHtml(context){
  if(context.scope!=='cell')return '';
  const columns=currentSeriesVisibleColumns();
  const items=seriesFilteredItems(columns);
  const item=items[context.row];
  const column=columns[context.column];
  if(!item||!column)return '';
  const raw=String(seriesCellValue(item,column.key)||'');
  const phone=seriesExtractPhone(raw),email=seriesExtractEmail(raw);
  if(!phone&&!email)return '';
  const name=seriesContactNameFromCell(raw)||seriesContactNameForRow(item)||phone||email;
  const caseNumber=String(seriesCellValue(item,'case_no')||item.case_no||'').split(/\r?\n/).map(value=>value.trim()).find(Boolean)||'';
  const contact={roleType:'联系人',name,phone,email,caseNumber,notes:`系列案「${String(state.seriesWorkspace?.title||'')}」${column.label||''}列`};
  const encoded=encodeURIComponent(JSON.stringify(contact));
  return `<button type="button" class="series-context-menu-item" onclick="closeSeriesTableContextMenu();syncContactToICloud(this,'${encoded}')">${contactSyncIcon()} 同步到 iCloud 通讯录</button>`;
}
function seriesContextMenuTitle(context){
  if(context.scope==='text')return '已选文字';
  if(context.scope==='row')return `第 ${context.row+1} 行`;
  if(context.scope==='column')return `${seriesColumnLetters(context.column)} 列`;
  return seriesCellAddress(context.row,context.column);
}
function openSeriesTableContextMenu(event,context){
  if(isOfflineReadonly())return;
  event.preventDefault();event.stopPropagation();
  state.seriesTableContext=context;
  const menu=$('seriesTableContextMenu');if(!menu)return;
  if(!state.seriesTableEditMode){
    // 非编辑模式：仅当单元格包含电话或邮箱时，提供“同步到 iCloud 通讯录”。
    const syncEntry=seriesCellContactSyncHtml(context);
    if(!syncEntry)return;
    menu.innerHTML=`<div class="series-context-menu-title">${esc(seriesContextMenuTitle(context))}</div><div class="series-context-menu-group">${syncEntry}</div>`;
    menu.classList.add('show');
    const width=226,height=menu.offsetHeight||276,left=Math.max(8,Math.min(event.clientX,window.innerWidth-width-8)),top=Math.max(8,Math.min(event.clientY,window.innerHeight-height-8));
    menu.style.left=`${left}px`;menu.style.top=`${top}px`;
    return;
  }
  const insertRows=context.scope!=='text'&&context.scope!=='column';
  const insertColumns=context.scope!=='text'&&context.scope!=='row';
  const formats=`<div class="series-context-menu-group"><button type="button" class="series-context-menu-item" onmousedown="event.preventDefault()" onclick="applySeriesContextTextFormat('bold')"><strong>B</strong> 加粗</button><button type="button" class="series-context-menu-item" onmousedown="event.preventDefault()" onclick="applySeriesContextTextFormat('highlight')"><strong>▇</strong> 文字高亮</button><button type="button" class="series-context-menu-item" onmousedown="event.preventDefault()" onclick="applySeriesContextTextFormat('color')"><strong style="color:#dc2626">A</strong> 标红</button><button type="button" class="series-context-menu-item" onmousedown="event.preventDefault()" onclick="applySeriesContextTextFormat('underline')"><strong><u>U</u></strong> 下划线</button><button type="button" class="series-context-menu-item" onmousedown="event.preventDefault()" onclick="applySeriesContextTextFormat('italic')"><strong><i>I</i></strong> 倾斜</button></div>`;
  const cellBackground=context.scope==='text'?'':`<div class="series-context-menu-group"><button type="button" class="series-context-menu-item" onmousedown="event.preventDefault()" onclick="applySeriesContextCellBackground('yellow')"><strong style="background:#fde68a">▇</strong> 高亮单元格</button></div>`;
  const alignments=context.scope==='text'?'':`<div class="series-context-menu-group"><div class="series-context-menu-label">水平对齐</div><button type="button" class="series-context-menu-item" onmousedown="event.preventDefault()" onclick="applySeriesContextAlign('left')"><strong>⯇</strong> 左对齐</button><button type="button" class="series-context-menu-item" onmousedown="event.preventDefault()" onclick="applySeriesContextAlign('center')"><strong>≡</strong> 居中</button><button type="button" class="series-context-menu-item" onmousedown="event.preventDefault()" onclick="applySeriesContextAlign('right')"><strong>⯈</strong> 右对齐</button></div>`;
  const verticalAlignments=context.scope==='text'?'':`<div class="series-context-menu-group"><div class="series-context-menu-label">垂直对齐</div><button type="button" class="series-context-menu-item" onmousedown="event.preventDefault()" onclick="applySeriesContextVerticalAlign('top')"><strong>↥</strong> 上对齐</button><button type="button" class="series-context-menu-item" onmousedown="event.preventDefault()" onclick="applySeriesContextVerticalAlign('center')"><strong>↕</strong> 居中</button><button type="button" class="series-context-menu-item" onmousedown="event.preventDefault()" onclick="applySeriesContextVerticalAlign('bottom')"><strong>↧</strong> 下对齐</button></div>`;
  menu.innerHTML=`<div class="series-context-menu-title">${esc(seriesContextMenuTitle(context))}</div>${insertRows?`<div class="series-context-menu-group"><button type="button" class="series-context-menu-item" onclick="insertSeriesContextRows('before')">在上方插入行</button><button type="button" class="series-context-menu-item" onclick="insertSeriesContextRows('after')">在下方插入行</button></div>`:''}${insertColumns?`<div class="series-context-menu-group"><button type="button" class="series-context-menu-item" onclick="insertSeriesContextColumns('before')">在左侧插入列</button><button type="button" class="series-context-menu-item" onclick="insertSeriesContextColumns('after')">在右侧插入列</button></div>`:''}${formats}${cellBackground}${alignments}${verticalAlignments}`;
  menu.classList.add('show');
  const width=226,height=menu.offsetHeight||276,left=Math.max(8,Math.min(event.clientX,window.innerWidth-width-8)),top=Math.max(8,Math.min(event.clientY,window.innerHeight-height-8));
  menu.style.left=`${left}px`;menu.style.top=`${top}px`;
}
function openSeriesCellContextMenu(event,row,column){
  const editor=event.target instanceof Element?event.target.closest('.series-cell-rich-input'):null;
  const offsets=editor?seriesEditorSelectionOffsets(editor):null;
  if(offsets){
    selectSeriesCellFromEditor(Number(editor.closest('td')?.dataset.seriesChildId||0),editor.closest('td')?.dataset.seriesColumnKey||'');
    return openSeriesTableContextMenu(event,{scope:'text',row,column,start:offsets.start,end:offsets.end});
  }
  const bounds=seriesSelectionBounds(),inside=!!bounds&&row>=bounds.rowStart&&row<=bounds.rowEnd&&column>=bounds.columnStart&&column<=bounds.columnEnd;
  if(!inside){state.seriesCellMultiSelection.clear();state.seriesCellSelection={startRow:row,startColumn:column,endRow:row,endColumn:column};applySeriesCellSelectionStyles();}
  openSeriesTableContextMenu(event,{scope:'cell',row,column});
}
function openSeriesRowContextMenu(event,row){selectSeriesRow(row);openSeriesTableContextMenu(event,{scope:'row',row,column:0});}
function openSeriesColumnContextMenu(event,column){selectSeriesColumnIndex(column);openSeriesTableContextMenu(event,{scope:'column',row:0,column});}
async function insertSeriesContextRows(side){
  const context=state.seriesTableContext;if(!context)return;
  const items=seriesFilteredItems(currentSeriesVisibleColumns()),position=Math.min(items.length,Math.max(0,context.row+(side==='after'?1:0)));
  try{
    const beforeOrder=seriesBaseItemsIgnoringColumn('').map(item=>Number(item.id));
    const data=await api(`/api/case-manager/series/${state.seriesWorkspace.id}/children/insert`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({position,count:1})});
    await reloadSeriesWorkspace();const afterOrder=seriesBaseItemsIgnoringColumn('').map(item=>Number(item.id));
    pushSeriesHistory({type:'insert_rows',label:`在${side==='before'?'上方':'下方'}插入行`,ids:(data.items||[]).map(item=>Number(item.id)),beforeOrder,afterOrder});
    closeSeriesTableContextMenu();toast('已插入一行，可直接编辑');
  }catch(e){toast(e.message);}
}
async function insertSeriesContextColumns(side){
  const context=state.seriesTableContext;if(!context)return;
  const before=currentSeriesColumns().map(column=>({...column})),visible=currentSeriesVisibleColumns(),target=visible[context.column];
  const rawIndex=target?before.findIndex(column=>column.key===target.key):before.length,position=Math.max(0,Math.min(before.length,rawIndex+(side==='after'&&target?1:0))),stamp=Date.now().toString(36);
  const addition={key:`custom_${stamp}`,label:'新列',source:'custom',field_type:'text',semantic_type:'',currency:'CNY',width:160};
  const after=[...before.slice(0,position),addition,...before.slice(position)];
  if(await persistSeriesColumns(after,[],{...currentSeriesSettings()},{recordHistory:false})){
    pushSeriesHistory({type:'columns',label:`在${side==='before'?'左侧':'右侧'}插入列`,before,after,beforeSettings:{...currentSeriesSettings()},afterSettings:{...currentSeriesSettings()}});
    closeSeriesTableContextMenu();toast('已插入“新列”，可直接修改列名');
  }
}
async function applySeriesContextTextFormat(key){
  const context=state.seriesTableContext;if(!context)return;
  const models=context.scope==='text'
    ? seriesSelectedCellModels().filter(model=>model.row===context.row&&model.column===context.column)
    : seriesSelectedCellModels();
  const updates=models.map(model=>{
    const value=String(model.value??'');if(!value)return null;
    const start=context.scope==='text'?context.start:0,end=context.scope==='text'?context.end:value.length;
    const existing=model.item.cell_formats?.[model.columnDef.key]||{};
    return {model,before:cloneSeriesCellFormat(existing),format:{...toggleSeriesRichFormat(value,existing,start,end,key),...(existing.align?{align:existing.align}:{}),...(existing.vertical_align?{vertical_align:existing.vertical_align}:{}),...(existing.cell_background?{cell_background:existing.cell_background}:{})}};
  }).filter(Boolean);
  if(!updates.length){closeSeriesTableContextMenu();return toast('所选单元格没有可设置格式的文字');}
  try{
    await saveSeriesCellFormatBatch(updates.map(({model,before,format})=>({model,before,format})),{label:`设置${key==='highlight'?'文字高亮':key==='bold'?'加粗':key==='color'?'标红':key==='underline'?'下划线':'倾斜'}`});
    closeSeriesTableContextMenu();renderSeriesChildTable();
    const names={bold:'加粗',highlight:'文字高亮',color:'标红',underline:'下划线',italic:'倾斜'};toast(`已${names[key]||'设置格式'} ${updates.length} 个单元格；再次点击同一选项可取消`);
  }catch(e){toast(`设置格式失败：${e.message}`);}
}
async function applySeriesContextCellBackground(value='yellow'){
  const context=state.seriesTableContext;if(!context||context.scope==='text')return;
  const models=seriesSelectedCellModels();if(!models.length){closeSeriesTableContextMenu();return toast('请先选择需要高亮的单元格');}
  const allEnabled=models.every(model=>model.item.cell_formats?.[model.columnDef.key]?.cell_background===value);
  const updates=models.map(model=>{
    const existing=model.item.cell_formats?.[model.columnDef.key]||{};
    const format={...(existing.runs?.length?{runs:existing.runs}:{}),...(existing.align?{align:existing.align}:{}),...(existing.vertical_align?{vertical_align:existing.vertical_align}:{}),...(allEnabled?{}:{cell_background:value})};
    return {model,before:cloneSeriesCellFormat(existing),format};
  });
  try{
    await saveSeriesCellFormatBatch(updates,{label:`${allEnabled?'取消':'设置'}单元格高亮`});
    closeSeriesTableContextMenu();renderSeriesChildTable();
    toast(`${allEnabled?'已取消':'已设置'}单元格高亮 ${updates.length} 个单元格；再次点击可${allEnabled?'重新设置':'取消'}`);
  }catch(e){toast(`设置单元格底色失败：${e.message}`);}
}
async function applySeriesContextAlign(value){
  const context=state.seriesTableContext;if(!context||context.scope==='text')return;
  const models=seriesSelectedCellModels();if(!models.length){closeSeriesTableContextMenu();return;}
  // 对齐是幂等设置：已是该对齐的单元格保持原状，不做切换或清除。
  const updates=models.map(model=>{
    const existing=model.item.cell_formats?.[model.columnDef.key]||{};
    if(existing.align===value)return null;
    return {model,before:cloneSeriesCellFormat(existing),format:{...(existing.runs?.length?{runs:existing.runs}:{}),...(existing.vertical_align?{vertical_align:existing.vertical_align}:{}),...(existing.cell_background?{cell_background:existing.cell_background}:{}),align:value}};
  }).filter(Boolean);
  if(!updates.length){closeSeriesTableContextMenu();return toast('所选单元格已是该对齐方式，保持原状');}
  try{
    await saveSeriesCellFormatBatch(updates,{label:`设置${value==='left'?'左对齐':value==='center'?'居中':'右对齐'}`});
    closeSeriesTableContextMenu();renderSeriesChildTable();
    const names={left:'左对齐',center:'居中',right:'右对齐'};toast(`已设置${names[value]} ${updates.length} 个单元格`);
  }catch(e){toast(`设置对齐失败：${e.message}`);}
}
async function applySeriesContextVerticalAlign(value){
  const context=state.seriesTableContext;if(!context||context.scope==='text')return;
  const models=seriesSelectedCellModels();if(!models.length){closeSeriesTableContextMenu();return;}
  const updates=models.map(model=>{
    const existing=model.item.cell_formats?.[model.columnDef.key]||{};
    if(existing.vertical_align===value)return null;
    return {model,before:cloneSeriesCellFormat(existing),format:{...(existing.runs?.length?{runs:existing.runs}:{}),...(existing.align?{align:existing.align}:{}),...(existing.cell_background?{cell_background:existing.cell_background}:{}),vertical_align:value}};
  }).filter(Boolean);
  if(!updates.length){closeSeriesTableContextMenu();return toast('所选单元格已是该垂直对齐方式，保持原状');}
  try{
    await saveSeriesCellFormatBatch(updates,{label:`设置${value==='top'?'上对齐':value==='center'?'垂直居中':'下对齐'}`});
    closeSeriesTableContextMenu();renderSeriesChildTable();
    const names={top:'上对齐',center:'垂直居中',bottom:'下对齐'};toast(`已设置${names[value]} ${updates.length} 个单元格`);
  }catch(e){toast(`设置垂直对齐失败：${e.message}`);}
}
document.addEventListener('pointerdown',event=>{const menu=$('seriesTableContextMenu');if(menu?.classList.contains('show')&&!menu.contains(event.target))closeSeriesTableContextMenu();});
document.addEventListener('keydown',event=>{if(event.key==='Escape')closeSeriesTableContextMenu();});
function seriesCellHtml(item,column){
  const value=seriesCellValue(item,column.key),format=item.cell_formats?.[column.key]||{};const readonly=!seriesCellEditable(column);
  const alignStyle=format.align?`text-align:${format.align};`:'';
  if(readonly||!state.seriesTableEditMode)return `<div class="series-cell-display series-cell-copyable" style="${alignStyle}" data-copy="${esc(String(value||''))}" title="单击复制单元格内容" onclick="copySeriesCellText(this)">${value?seriesRichTextHtml(String(value),format):'—'}</div>`;
  const id=`seriesCell${Number(item.id)}${String(column.key).replace(/[^a-zA-Z0-9]/g,'')}`;
  return `<div class="series-cell-rich-input" id="${id}" contenteditable="true" role="textbox" aria-multiline="true" spellcheck="true" style="${alignStyle}" data-original="${esc(String(value??''))}" title="直接编辑；选中文字后右键可设置格式；从单元格拖动可多选" onclick="event.stopPropagation()" onmousedown="beginSeriesEditorSelection(event,${Number(item.id)},'${esc(column.key)}')" onfocus="selectSeriesCellFromEditor(${Number(item.id)},'${esc(column.key)}')" onblur="saveSeriesRichCell(this,${Number(item.id)},'${esc(column.key)}')" onkeydown="if((event.metaKey||event.ctrlKey)&&event.key==='Enter'){event.preventDefault();this.blur()}">${seriesRichTextHtml(String(value??''),format)}</div>`;
}
function seriesCellVerticalAlignStyle(item,column){
  const value=item.cell_formats?.[column.key]?.vertical_align;
  return value?`vertical-align:${value==='center'?'middle':value};`:'';
}
function seriesCellBackgroundClass(item,column){
  return item.cell_formats?.[column.key]?.cell_background==='yellow'?' series-cell-background-yellow':'';
}
function seriesMobileChildCardHtml(item){
  // 子案标识可能是纯数字；移动端卡片标题应优先显示案件正式名称。
  const title=String(item.title||'').trim()||seriesCellValue(item,'display_name')||item.series_display_name||'未命名子案';
  const code=seriesCellValue(item,'series_code');
  const stage=seriesCellValue(item,'current_stage')||'待补充';
  const caseNo=String(seriesCellValue(item,'case_no')||'').replace(/\s*\n\s*/g,'、');
  const court=String(seriesCellValue(item,'court')||'').replace(/\s*\n\s*/g,'、');
  const subline=[caseNo,court].filter(Boolean).join(' · ')||seriesCellValue(item,'opponents')||seriesCellValue(item,'clients')||'';
  const archived=item.source_status==='archived';
  const detailLabel=`查看子案详情：${String(title)}`;
  return `<article class="mobile-record-card mobile-record-cases series-mobile-child-card${archived?' archived':''}" role="button" tabindex="0" aria-label="${esc(detailLabel)}" onclick="openSeriesChildDetail(${Number(item.id)})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();openSeriesChildDetail(${Number(item.id)})}">
    <div class="mobile-card-content">
      <div class="mobile-card-title-row"><strong class="mobile-card-title">${esc(title)}</strong></div>
      <div class="mobile-card-meta"><span class="tag stage-tag">${esc(stage)}</span>${archived?'<span class="tag">已结案</span>':''}<span>编号 <strong>${esc(code||'待补充')}</strong></span><span>更新 <strong>${esc(compactRecordDate(item.updated_at))}</strong></span></div>
      ${subline?`<div class="mobile-card-subline">${esc(subline)}</div>`:''}
    </div>
  </article>`;
}
function seriesMobileChildListHtml(items){
  if(!items.length)return `<div class="empty series-mobile-child-empty">没有匹配的子案</div>`;
  return `<div class="mobile-record-list series-mobile-child-list">${items.map(seriesMobileChildCardHtml).join('')}</div>`;
}
function seriesStickyColumnStyle(columnIndex,columns,header=false){const freeze=currentSeriesSettings().freeze_columns;if(columnIndex<0)return `position:sticky;left:0;z-index:${header?20:5};background:var(--panel);width:62px;min-width:62px;max-width:62px;`;if(columnIndex>=freeze)return '';const base=state.seriesTableEditMode?62:0;const left=base+columns.slice(0,columnIndex).reduce((sum,column)=>sum+Number(column.width||150),0);return `position:sticky;left:${left}px;z-index:${header?15:5};background:var(--panel);`;}
function seriesFrozenRowStyle(rowIndex,columnIndex=null){const count=currentSeriesSettings().freeze_rows;if(rowIndex>=count)return '';const zIndex=columnIndex==='actions'?8:(columnIndex===-1||Number(columnIndex)<currentSeriesSettings().freeze_columns?6:4);return `position:sticky;top:${70+rowIndex*48}px;z-index:${zIndex};background:var(--panel);`;}
function seriesFilterValue(item,key){const value=seriesCellValue(item,key);return value===null||value===undefined?'':String(value);}
function seriesMatchesColumnFilter(item,key,filter){
  const value=seriesFilterValue(item,key);
  if(filter&&typeof filter==='object'&&Array.isArray(filter.values))return filter.values.includes(value);
  const query=String(filter||'').trim().toLowerCase();
  return !query||value.toLowerCase().includes(query);
}
function seriesBaseItemsIgnoringColumn(ignoreKey=''){
  const q=String(state.seriesChildQuery||'').trim().toLowerCase(),stage=$('seriesStageFilter')?.value||'';
  let items=(state.seriesWorkspace?.children||[]).filter(item=>item.source_status!=='deleted'&&(state.seriesShowHiddenRows||Number(item.series_row_hidden||0)!==1)&&(!q||childSearchText(item).includes(q))&&(!stage||item.current_stage===stage));
  return items.filter(item=>Object.entries(state.seriesColumnFilters||{}).every(([key,filter])=>key===ignoreKey||seriesMatchesColumnFilter(item,key,filter)));
}
function seriesColumnValueOptions(key){
  const counts=new Map();
  seriesBaseItemsIgnoringColumn(key).forEach(item=>{const value=seriesFilterValue(item,key);counts.set(value,(counts.get(value)||0)+1);});
  return [...counts.entries()].map(([value,count])=>({value,count})).sort((a,b)=>String(a.value).localeCompare(String(b.value),'zh-CN',{numeric:true}));
}
function ensureSeriesFilterPopover(){
  let host=$('seriesFilterPopover');
  if(host)return host;
  host=document.createElement('div');host.id='seriesFilterPopover';host.className='series-filter-popover';host.setAttribute('role','dialog');host.setAttribute('aria-modal','false');host.onclick=event=>event.stopPropagation();document.body.appendChild(host);
  return host;
}
function closeSeriesFilterPopover(){
  const host=$('seriesFilterPopover');if(host){host.classList.remove('show');host.innerHTML='';}
  state.seriesFilterDraft=null;state.seriesFilterComposing=false;
  if(seriesFilterOutsideHandler){document.removeEventListener('pointerdown',seriesFilterOutsideHandler);seriesFilterOutsideHandler=null;}
}
function openSeriesColumnFilter(event,key){
  event.preventDefault();event.stopPropagation();
  const column=currentSeriesColumns().find(item=>item.key===key);if(!column)return;
  const options=seriesColumnValueOptions(key),current=state.seriesColumnFilters?.[key];
  const currentValues=current&&typeof current==='object'&&Array.isArray(current.values)?current.values:options.map(item=>item.value);
  state.seriesFilterDraft={key,column,options,selected:new Set(currentValues),query:''};
  const host=ensureSeriesFilterPopover();
  host.innerHTML=`<div class="series-filter-head"><strong>${esc(column.label)} · 筛选</strong><button class="btn" type="button" onclick="closeSeriesFilterPopover()">关闭</button></div><div class="series-filter-sort-actions"><button class="btn ${state.seriesSortKey===key&&state.seriesSortDirection==='asc'?'primary':''}" type="button" onclick="applySeriesFilterSort('asc')">A→Z 升序</button><button class="btn ${state.seriesSortKey===key&&state.seriesSortDirection==='desc'?'primary':''}" type="button" onclick="applySeriesFilterSort('desc')">Z→A 降序</button><button class="btn" type="button" onclick="clearCurrentSeriesColumnFilter()">清除本列筛选</button></div><input class="input series-filter-search" id="seriesFilterSearch" placeholder="搜索候选内容，支持中文输入" oncompositionstart="state.seriesFilterComposing=true" oncompositionend="state.seriesFilterComposing=false;updateSeriesFilterSearch(this.value)" oninput="if(!state.seriesFilterComposing)updateSeriesFilterSearch(this.value)"><div class="series-filter-quick"><button type="button" onclick="selectSeriesFilterValues('all')">全选</button><button type="button" onclick="selectSeriesFilterValues('invert')">反选</button><button type="button" onclick="selectSeriesFilterValues('matching')">仅选匹配项</button></div><div class="series-filter-options" id="seriesFilterOptions"></div><div class="series-filter-foot"><span class="series-paste-help" id="seriesFilterCount"></span><button class="btn" type="button" onclick="closeSeriesFilterPopover()">取消</button><button class="btn primary" type="button" onclick="confirmSeriesColumnFilter()">确定</button></div>`;
  host.onkeydown=keyEvent=>{if(keyEvent.key==='Escape'){keyEvent.preventDefault();closeSeriesFilterPopover();}else if(keyEvent.key==='Enter'&&keyEvent.target?.id==='seriesFilterSearch'&&!state.seriesFilterComposing){keyEvent.preventDefault();selectSeriesFilterValues('matching');confirmSeriesColumnFilter();}};
  const rect=event.currentTarget.getBoundingClientRect(),width=Math.min(380,window.innerWidth-24),left=Math.max(12,Math.min(rect.left,window.innerWidth-width-12)),top=Math.max(12,Math.min(rect.bottom+6,window.innerHeight-Math.min(650,window.innerHeight-24)-12));
  host.style.left=`${left}px`;host.style.top=`${top}px`;host.classList.add('show');renderSeriesFilterOptions();
  const outsideHandler=outsideEvent=>{if(!host.contains(outsideEvent.target))closeSeriesFilterPopover();};seriesFilterOutsideHandler=outsideHandler;setTimeout(()=>{if(seriesFilterOutsideHandler===outsideHandler)document.addEventListener('pointerdown',outsideHandler);},0);
  $('seriesFilterSearch')?.focus();
}
function visibleSeriesFilterOptions(){const draft=state.seriesFilterDraft;if(!draft)return[];const query=String(draft.query||'').trim().toLowerCase();return draft.options.filter(item=>!query||String(item.value).toLowerCase().includes(query));}
function renderSeriesFilterOptions(){
  const draft=state.seriesFilterDraft,host=$('seriesFilterOptions');if(!draft||!host)return;
  const visible=visibleSeriesFilterOptions();
  host.innerHTML=visible.length?visible.slice(0,500).map(item=>{const index=draft.options.indexOf(item),label=item.value||'(空白)';return `<label class="series-filter-option"><input type="checkbox" ${draft.selected.has(item.value)?'checked':''} onchange="toggleSeriesFilterValue(${index},this.checked)"><span>${esc(label)}</span><small>(${item.count})</small></label>`;}).join(''):`<div class="series-filter-empty">没有匹配的候选内容</div>`;
  const count=$('seriesFilterCount');if(count)count.textContent=`已选 ${draft.selected.size}/${draft.options.length} 项${visible.length>500?' · 仅显示前500项':''}`;
}
function updateSeriesFilterSearch(value){if(!state.seriesFilterDraft)return;state.seriesFilterDraft.query=value;renderSeriesFilterOptions();}
function toggleSeriesFilterValue(index,checked){const draft=state.seriesFilterDraft,item=draft?.options?.[index];if(!item)return;if(checked)draft.selected.add(item.value);else draft.selected.delete(item.value);renderSeriesFilterOptions();}
function selectSeriesFilterValues(mode){
  const draft=state.seriesFilterDraft;if(!draft)return;const visible=visibleSeriesFilterOptions();
  if(mode==='all')visible.forEach(item=>draft.selected.add(item.value));
  else if(mode==='invert')visible.forEach(item=>draft.selected.has(item.value)?draft.selected.delete(item.value):draft.selected.add(item.value));
  else if(mode==='matching'){draft.selected.clear();visible.forEach(item=>draft.selected.add(item.value));}
  renderSeriesFilterOptions();
}
function confirmSeriesColumnFilter(){const draft=state.seriesFilterDraft;if(!draft)return;if(draft.selected.size===draft.options.length)delete state.seriesColumnFilters[draft.key];else state.seriesColumnFilters[draft.key]={values:[...draft.selected]};closeSeriesFilterPopover();renderSeriesChildTable();}
function clearCurrentSeriesColumnFilter(){const key=state.seriesFilterDraft?.key;if(!key)return;delete state.seriesColumnFilters[key];closeSeriesFilterPopover();renderSeriesChildTable();}
function applySeriesFilterSort(direction){const key=state.seriesFilterDraft?.key;if(!key)return;state.seriesSortKey=key;state.seriesSortDirection=direction;closeSeriesFilterPopover();renderSeriesChildTable();}
function toggleSeriesColumnSort(key){closeSeriesFilterPopover();if(state.seriesSortKey===key)state.seriesSortDirection=state.seriesSortDirection==='asc'?'desc':'asc';else{state.seriesSortKey=key;state.seriesSortDirection='asc';}renderSeriesChildTable();}
function clearSeriesTableFilters(){closeSeriesFilterPopover();state.seriesColumnFilters={};state.seriesSortKey='';state.seriesSortDirection='asc';state.seriesChildQuery='';renderSeriesWorkspace();}
function seriesFilteredItems(columns){let items=seriesBaseItemsIgnoringColumn('');if(state.seriesSortKey){const column=columns.find(item=>item.key===state.seriesSortKey)||{};const direction=state.seriesSortDirection==='desc'?-1:1;items=[...items].sort((a,b)=>{const av=seriesCellValue(a,state.seriesSortKey),bv=seriesCellValue(b,state.seriesSortKey);if(column.semantic_type==='amount'||column.field_type==='number'){const an=seriesParseAmount(av),bn=seriesParseAmount(bv);if(!Number.isNaN(an)||!Number.isNaN(bn))return ((Number.isNaN(an)?-Infinity:an)-(Number.isNaN(bn)?-Infinity:bn))*direction;}return String(av||'').localeCompare(String(bv||''),'zh-CN',{numeric:true})*direction;});}return items;}
function seriesColumnDragStart(event,key){state.seriesDraggingColumnKey=key;event.dataTransfer.effectAllowed='move';event.dataTransfer.setData('text/plain',key);event.currentTarget.classList.add('dragging');}
function seriesColumnDragOver(event){event.preventDefault();event.dataTransfer.dropEffect='move';event.currentTarget.classList.add('drag-over');}
function seriesColumnDragLeave(event){event.currentTarget.classList.remove('drag-over');}
function seriesColumnDragEnd(event){event.currentTarget.classList.remove('dragging');document.querySelectorAll('.series-column-head.drag-over').forEach(el=>el.classList.remove('drag-over'));state.seriesDraggingColumnKey='';}
async function seriesColumnDrop(event,targetKey){event.preventDefault();event.currentTarget.classList.remove('drag-over');const sourceKey=event.dataTransfer.getData('text/plain')||state.seriesDraggingColumnKey;if(!sourceKey||sourceKey===targetKey)return;const before=currentSeriesColumns().map(column=>({...column})),columns=before.map(column=>({...column}));const from=columns.findIndex(item=>item.key===sourceKey),to=columns.findIndex(item=>item.key===targetKey);if(from<0||to<0)return;const [moved]=columns.splice(from,1);columns.splice(to,0,moved);const settings=currentSeriesSettings();const previousColumns=state.seriesWorkspace?.profile?.table_columns;state.seriesWorkspace.profile.table_columns=columns;renderSeriesChildTable();const committedHead=Array.from(document.querySelectorAll('.series-column-head')).find(head=>head.closest('th')?.dataset.seriesColumnKey===sourceKey);if(committedHead)markApexReorderCommitted(committedHead);if(await persistSeriesColumns(columns,[],settings,{recordHistory:false,skipRender:true}))pushSeriesHistory({type:'columns',label:'调整列顺序',before,after:columns,beforeSettings:settings,afterSettings:settings});else{state.seriesWorkspace.profile.table_columns=previousColumns;renderSeriesChildTable();}}
function seriesRowDragStart(event,childId){
  if(state.seriesChildQuery||state.seriesSortKey||Object.keys(state.seriesColumnFilters||{}).length||$('seriesStageFilter')?.value){event.preventDefault();return toast('请先清除搜索、筛选和排序，再拖动排列行');}
  state.seriesDraggingRowId=Number(childId);event.currentTarget.closest('tr')?.classList.add('dragging');event.dataTransfer.effectAllowed='move';event.dataTransfer.setData('text/plain',String(childId));
}
function seriesRowDragOver(event){if(!state.seriesDraggingRowId)return;event.preventDefault();event.currentTarget.classList.add('series-row-drop-target');}
function seriesRowDragLeave(event){event.currentTarget.classList.remove('series-row-drop-target');}
function seriesRowDragEnd(){state.seriesDraggingRowId=0;document.querySelectorAll('.series-row-drop-target').forEach(row=>row.classList.remove('series-row-drop-target'));document.querySelectorAll('#seriesChildTableHost tr.dragging').forEach(row=>row.classList.remove('dragging'));}
async function seriesRowDrop(event,targetId){
  event.preventDefault();seriesRowDragLeave(event);
  const sourceId=Number(event.dataTransfer.getData('text/plain')||state.seriesDraggingRowId);if(!sourceId||sourceId===Number(targetId))return seriesRowDragEnd();
  const before=seriesBaseItemsIgnoringColumn('').map(item=>Number(item.id)),next=[...before],from=next.indexOf(sourceId),to=next.indexOf(Number(targetId));if(from<0||to<0)return seriesRowDragEnd();
  const sourceRow=document.querySelector(`#seriesChildTableHost tr[data-series-child-id="${sourceId}"]`),targetRow=event.currentTarget,tbody=targetRow?.parentElement;
  const [moved]=next.splice(from,1);next.splice(to,0,moved);seriesRowDragEnd();
  if(sourceRow&&targetRow&&tbody){const beforeRects=captureApexReorderRects(tbody,':scope > tr[data-series-child-id]'),reference=from<to?targetRow.nextElementSibling:targetRow;if(reference!==sourceRow&&sourceRow.nextElementSibling!==reference){tbody.insertBefore(sourceRow,reference);animateApexReorder(tbody,beforeRects,{skip:sourceRow});markApexReorderCommitted(sourceRow);}}
  try{await applySeriesRowOrder(next,{before});toast('行顺序已保存，可撤销');}catch(e){await reloadSeriesWorkspace();toast(e.message);}
}
function startSeriesColumnResize(event,key){
  if(!state.seriesTableEditMode)return;event.preventDefault();event.stopPropagation();
  const raw=currentSeriesColumns(),column=raw.find(item=>item.key===key);if(!column)return;
  const startX=event.clientX,startWidth=document.querySelector(`th[data-series-column-key="${CSS.escape(key)}"]`)?.getBoundingClientRect().width||column.width||150;
  const handle=event.currentTarget;handle.classList.add('resizing');
  const move=moveEvent=>{const width=Math.max(80,Math.min(420,Math.round(startWidth+moveEvent.clientX-startX)));document.querySelectorAll(`[data-series-column-key="${CSS.escape(key)}"]`).forEach(cell=>{cell.style.width=`${width}px`;cell.style.minWidth=`${width}px`;cell.style.maxWidth=`${width}px`;});};
  const up=async upEvent=>{window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',up);handle.classList.remove('resizing');const width=Math.max(80,Math.min(420,Math.round(startWidth+upEvent.clientX-startX)));await persistSeriesColumns(raw.map(item=>item.key===key?{...item,width,manual_width:true}:item));};
  window.addEventListener('pointermove',move);window.addEventListener('pointerup',up,{once:true});
}
async function resetSeriesColumnWidth(event,key){event.preventDefault();event.stopPropagation();const next=currentSeriesColumns().map(item=>item.key===key?{...item,manual_width:false}:item);await persistSeriesColumns(next);toast('已恢复按内容智能调整列宽');}
let seriesMobileLayoutTimer = null;
function isSeriesMobileCardMode(){
  const host=$('seriesChildTableHost'),width=host?.getBoundingClientRect?.().width||document.documentElement.clientWidth||window.innerWidth||0;
  return width>0?width<=900:isMobileCaseCardMode();
}
function syncSeriesMobileLayout(){
  if(!state.seriesWorkspace||state.seriesWorkspaceTab!=='children'||!$('seriesChildTableHost'))return;
  const next=isSeriesMobileCardMode();
  if(state.seriesMobileCardLayout===next)return;
  state.seriesMobileCardLayout=next;
  renderSeriesChildTable();
}
function scheduleSeriesMobileLayoutSync(){
  clearTimeout(seriesMobileLayoutTimer);
  seriesMobileLayoutTimer=setTimeout(()=>requestAnimationFrame(syncSeriesMobileLayout),40);
}
function renderSeriesChildTable() {
  const host = $('seriesChildTableHost'); if (!host) return;
  const q = String(state.seriesChildQuery||'').trim().toLowerCase(); const stage=$('seriesStageFilter')?.value||'';
  const sourceColumns=currentSeriesVisibleColumns();
  const items = seriesFilteredItems(sourceColumns);
  const mobileCards=isSeriesMobileCardMode();
  state.seriesMobileCardLayout=mobileCards;
  if(mobileCards&&!state.seriesTableEditMode){
    host.innerHTML=seriesMobileChildListHtml(items);
    updateSeriesSelectionSummary();
    return;
  }
  const widthSourceItems=(state.seriesWorkspace?.children||[]).filter(item=>item.source_status!=='deleted');
  const columns=seriesColumnsWithSmartWidths(sourceColumns,widthSourceItems);
  const actionWidth=state.seriesTableEditMode?238:150;
  const rows = items.map((item,rowIndex) => `<tr class="${Number(item.series_row_hidden||0)===1?'series-row-hidden':''}" data-series-child-id="${Number(item.id)}" ${state.seriesTableEditMode?`ondragover="seriesRowDragOver(event)" ondragleave="seriesRowDragLeave(event)" ondrop="seriesRowDrop(event,${Number(item.id)})"`:''}>
    <td class="series-select-cell ${state.seriesTableEditMode?'':'view-hidden'}" style="${seriesStickyColumnStyle(-1,columns)}${seriesFrozenRowStyle(rowIndex,-1)}" onclick="event.stopPropagation()" oncontextmenu="openSeriesRowContextMenu(event,${rowIndex})" ondblclick="openSeriesRowContextMenu(event,${rowIndex})"><button class="series-row-drag" type="button" draggable="true" title="拖动排列行；右键可编辑整行" aria-label="拖动排列行" ondragstart="seriesRowDragStart(event,${Number(item.id)})" ondragend="seriesRowDragEnd()">⋮⋮</button><input type="checkbox" ${state.seriesSelectedChildIds.has(Number(item.id))?'checked':''} onchange="toggleSeriesChildSelection(${Number(item.id)},this.checked)"></td>
    ${columns.map((column,columnIndex)=>`<td class="${state.seriesTableEditMode&&seriesCellEditable(column)?'series-cell-editing':''}${seriesCellBackgroundClass(item,column)}" data-series-column-key="${esc(column.key)}" data-series-mobile-label="${esc(column.label)}" data-series-row-index="${rowIndex}" data-series-column-index="${columnIndex}" data-series-child-id="${Number(item.id)}" style="width:${Number(column.width||150)}px;min-width:${Number(column.width||150)}px;max-width:${Number(column.width||150)}px;${seriesCellVerticalAlignStyle(item,column)}${seriesStickyColumnStyle(columnIndex,columns)}${seriesFrozenRowStyle(rowIndex,columnIndex)}" onmousedown="startSeriesCellSelection(event,${rowIndex},${columnIndex})" onmouseenter="extendSeriesCellSelection(${rowIndex},${columnIndex})" oncontextmenu="openSeriesCellContextMenu(event,${rowIndex},${columnIndex})" ondblclick="openSeriesCellContextMenu(event,${rowIndex},${columnIndex})">${seriesCellHtml(item,column)}</td>`).join('')}
    <td class="series-actions-cell" style="${seriesFrozenRowStyle(rowIndex,'actions')}" onclick="event.stopPropagation()"><div class="series-row-actions">${Number(item.series_row_hidden||0)===1?'<span class="series-row-hidden-label">已隐藏</span>':''}<button class="btn" type="button" onclick="openSeriesChildFolder(${Number(item.id)})">文件夹</button><button class="btn" type="button" onclick="openSeriesChildDetail(${Number(item.id)})">详情</button><button class="btn" type="button" onclick="openSeriesChildLedger(${Number(item.id)})">台账</button>${!isOfflineReadonly()&&state.seriesTableEditMode?`<button class="btn" type="button" onclick="setSeriesChildStatus(${Number(item.id)},'${item.source_status==='archived'?'restore':'archive'}')">${item.source_status==='archived'?'恢复在办':'结案'}</button><button class="btn danger" type="button" onclick="deleteSeriesInlineRow(${Number(item.id)})">删除行</button>`:''}</div></td></tr>`).join('');
  const heads=columns.map((column,columnIndex)=>`<th data-series-column-key="${esc(column.key)}" class="${state.seriesTableEditMode?'series-cell-editing':''}" style="width:${Number(column.width||150)}px;min-width:${Number(column.width||150)}px;max-width:${Number(column.width||150)}px;${seriesStickyColumnStyle(columnIndex,columns,true)}" oncontextmenu="openSeriesColumnContextMenu(event,${columnIndex})" ondblclick="openSeriesColumnContextMenu(event,${columnIndex})"><div class="series-column-head" draggable="${state.seriesTableEditMode&&!isOfflineReadonly()?'true':'false'}" ${state.seriesTableEditMode?`ondragstart="seriesColumnDragStart(event,'${esc(column.key)}')" ondragover="seriesColumnDragOver(event)" ondragleave="seriesColumnDragLeave(event)" ondragend="seriesColumnDragEnd(event)" ondrop="seriesColumnDrop(event,'${esc(column.key)}')"`:''}>${state.seriesTableEditMode?`<span class="series-column-drag-handle" title="拖动排列列；右键可编辑整列">⋮⋮</span><input class="series-column-title-input" value="${esc(column.label)}" aria-label="编辑列标题${esc(column.label)}" title="直接编辑列标题" onmousedown="event.stopPropagation()" onclick="event.stopPropagation()" onkeydown="if(event.key==='Enter'){event.preventDefault();this.blur();}" onblur="saveSeriesColumnLabel('${esc(column.key)}',this.value)">`:`<span class="series-column-title">${esc(column.label)}</span>`}<button class="series-sort-btn ${state.seriesSortKey===column.key?'active':''}" type="button" aria-label="排序${esc(column.label)}" title="按本列排序" onclick="event.stopPropagation();toggleSeriesColumnSort('${esc(column.key)}')">${state.seriesSortKey===column.key?(state.seriesSortDirection==='asc'?'↑':'↓'):'↕'}</button><button class="series-filter-btn ${state.seriesColumnFilters[column.key]?'active':''}" type="button" aria-label="筛选${esc(column.label)}" title="筛选本列" onclick="openSeriesColumnFilter(event,'${esc(column.key)}')">${state.seriesColumnFilters[column.key]?'▼':'⌄'}</button>${state.seriesTableEditMode?`<button class="series-column-remove" title="删除此列" onclick="event.stopPropagation();removeSeriesColumn('${esc(column.key)}')">×</button>`:''}</div>${state.seriesTableEditMode?`<span class="series-column-resizer" title="拖动调整列宽；双击恢复智能列宽" onpointerdown="startSeriesColumnResize(event,'${esc(column.key)}')" ondblclick="resetSeriesColumnWidth(event,'${esc(column.key)}')"></span>`:''}</th>`).join('');
  host.innerHTML = `<div class="series-table-wrap" tabindex="0" aria-label="系列案件主表" oncopy="handleSeriesTableCopy(event)" onpaste="handleSeriesTablePaste(event)" onscroll="scheduleSeriesViewStateSync()"><table class="series-table" style="min-width:${Math.max(900,columns.reduce((sum,c)=>sum+Number(c.width||150),0)+actionWidth+(state.seriesTableEditMode?62:0))}px"><thead><tr><th class="series-select-cell ${state.seriesTableEditMode?'':'view-hidden'}" style="${seriesStickyColumnStyle(-1,columns,true)}"><input type="checkbox" onchange="toggleAllSeriesChildren(this.checked)"></th>${heads}<th class="series-actions-cell" style="width:${actionWidth}px;min-width:${actionWidth}px;max-width:${actionWidth}px">操作</th></tr></thead><tbody>${rows||`<tr><td colspan="${columns.length+2}"><div class="empty">没有匹配的子案${state.seriesTableEditMode?'，点击“插入行”即可直接录入':''}</div></td></tr>`}</tbody></table></div>`;
  syncSeriesTableStickyOffset();
  activateSeriesLookups(host);
  prepareSeriesCellLayout(host);
  requestAnimationFrame(()=>{prepareSeriesCellLayout(host);syncSeriesTableStickyOffset();});
  requestAnimationFrame(applySeriesCellSelectionStyles);
  updateSeriesSelectionSummary();
}
async function saveSeriesInlineCell(input,childId,field){const original=input.defaultValue,next=input.value;if(String(original)===String(next))return;input.classList.add('saving');try{const updated=await api(`/api/case-manager/series/${state.seriesWorkspace.id}/children/${childId}/cell`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({field,value:next})});const index=(state.seriesWorkspace.children||[]).findIndex(x=>Number(x.id)===Number(childId));if(index>=0)state.seriesWorkspace.children[index]={...state.seriesWorkspace.children[index],...updated};input.defaultValue=next;input.classList.remove('saving');input.classList.add('saved');pushSeriesHistory({type:'cells',label:'编辑单元格',before:[{childId:Number(childId),field,value:original}],after:[{childId:Number(childId),field,value:next}]});const column=currentSeriesColumns().find(item=>item.key===field);if(column?.semantic_type==='amount'){await reloadSeriesWorkspace();}else setTimeout(()=>input.classList.remove('saved'),700);}catch(e){input.value=original;input.classList.remove('saving');toast(e.message);}}
async function addSeriesInlineRow(){if(!requireOnlineAction())return;const count=(state.seriesWorkspace.children||[]).length+1;try{const item=await api(`/api/case-manager/series/${state.seriesWorkspace.id}/children`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({display_name:`新子案 ${count}`})});state.seriesWorkspace.children.push(item);state.seriesWorkspace.stats.total=Number(state.seriesWorkspace.stats.total||0)+1;state.seriesWorkspace.stats.active=Number(state.seriesWorkspace.stats.active||0)+1;renderSeriesWorkspace();setTimeout(()=>document.querySelector(`#seriesChildTableHost .series-cell-rich-input[id^="seriesCell${item.id}"]`)?.focus(),0);toast('已新增一行，可直接在表格中填写');}catch(e){toast(e.message);}}
async function setSeriesChildStatus(childId,operation,skipConfirm=false){const archive=operation==='archive';if(!skipConfirm){openCaseActionDialog(archive?'series_child_archive':'series_child_restore',[Number(childId)],archive?'确认将这个子案单独结案？':'确认恢复这个子案为在办状态？');return;}try{await api(`/api/case-manager/series/${state.seriesWorkspace.id}/children/bulk`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({child_ids:[Number(childId)],operation,payload:{}})});await reloadSeriesWorkspace();toast(archive?'该子案已单独结案':'该子案已恢复在办');if(archive&&Number(state.seriesWorkspace?.stats?.active||0)===0)await archiveSeries(false);}catch(e){toast(e.message);}}
function openSeriesDeleteDialog(ids){
  if(!requireOnlineAction())return;
  const normalized=[...new Set((ids||[]).map(Number).filter(Boolean))];
  if(!normalized.length)return toast('请先勾选需要删除的行');
  state.seriesPendingDeleteIds=normalized;
  $('seriesDeleteDialogTitle').textContent=normalized.length===1?'删除这一行？':`删除所选的 ${normalized.length} 行？`;
  $('seriesDeleteDialogDescription').textContent=`对应的 ${normalized.length} 个子案将移入垃圾站，可在垃圾站中恢复。`;
  const button=$('confirmSeriesDeleteRowsButton');button.disabled=false;button.textContent='确认删除';
  $('seriesDeleteDialogMask').classList.add('show');
  setTimeout(()=>button.focus(),0);
}
function closeSeriesDeleteDialog(){
  $('seriesDeleteDialogMask')?.classList.remove('show');
  state.seriesPendingDeleteIds=[];
}
function deleteSeriesInlineRow(childId){openSeriesDeleteDialog([childId]);}
function deleteSelectedSeriesRows(){openSeriesDeleteDialog([...state.seriesSelectedChildIds]);}
async function confirmDeleteSeriesRows(){
  const ids=[...(state.seriesPendingDeleteIds||[])];
  if(!ids.length)return closeSeriesDeleteDialog();
  const button=$('confirmSeriesDeleteRowsButton');button.disabled=true;button.textContent='删除中…';
  try{
    await api(`/api/case-manager/series/${state.seriesWorkspace.id}/children/bulk`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({child_ids:ids,operation:'delete',payload:{}})});
    closeSeriesDeleteDialog();
    state.seriesSelectedChildIds.clear();
    await reloadSeriesWorkspace();
    await refreshAll();
    toast(`已将 ${ids.length} 行移入垃圾站`);
  }catch(e){
    button.disabled=false;button.textContent='确认删除';
    toast(e.message);
  }
}
async function persistSeriesColumns(columns,deletedKeys=[],settings=currentSeriesSettings(),options={}){try{const data=await api(`/api/case-manager/series/${state.seriesWorkspace.id}/columns`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({columns,deleted_keys:deletedKeys,settings})});state.seriesWorkspace.profile.table_columns=data.items;state.seriesWorkspace.profile.table_settings=data.settings||settings;if(!options.skipRender)renderSeriesWorkspace();return true;}catch(e){toast(e.message);return false;}}
async function saveSeriesColumnLabel(key,value){const column=currentSeriesColumns().find(item=>item.key===key);const label=String(value||'').trim();if(!column)return;if(!label){toast('列标题不能为空');renderSeriesWorkspace();return;}if(label===column.label)return;const next=currentSeriesColumns().map(item=>item.key===key?{...item,label}:item);if(await persistSeriesColumns(next))toast(`已更新列标题：${label}`);}
async function removeSeriesColumn(key){const column=currentSeriesColumns().find(x=>x.key===key);if(!column)return;if(!confirm(`删除“${column.label}”列？${String(key).startsWith('custom_')?'该列已填写的内容也会删除。':'案件原始数据不会删除，只是不再显示在本系列主表中。'}`))return;const next=currentSeriesColumns().filter(x=>x.key!==key);await persistSeriesColumns(next,String(key).startsWith('custom_')?[key]:[]);}
function openSeriesColumnManager(){const columns=currentSeriesColumns(),visibleColumns=currentSeriesVisibleColumns(),settings=currentSeriesSettings();const rows=columns.map((column,index)=>`<div class="series-column-item ${column.hidden===true?'is-hidden':''}"><span>${index+1}</span><strong>${esc(column.label)}${column.hidden===true?' <span class="tag">已隐藏</span>':''}</strong><span class="tag">${esc(seriesColumnKindLabel(column))}</span><button class="btn series-column-visibility ${column.hidden===true?'primary':''}" type="button" aria-pressed="${column.hidden===true?'false':'true'}" onclick="toggleSeriesColumnVisibility('${esc(column.key)}')">${column.hidden===true?'显示':'隐藏'}</button>${column.source==='derived'?'<span></span>':`<button class="btn" onclick="toggleSeriesAmountColumn('${esc(column.key)}')">${column.semantic_type==='amount'?'取消金额汇总':'设为金额列'}</button>`}<button class="btn danger" onclick="removeSeriesColumn('${esc(column.key)}');closeSeriesSide()">删除</button></div>`).join('');const freezeOptions=[`<option value="0" ${settings.freeze_columns===0?'selected':''}>不冻结数据列</option>`,...visibleColumns.map((column,index)=>`<option value="${index+1}" ${settings.freeze_columns===index+1?'selected':''}>冻结至：${esc(column.label)}</option>`)].join('');showSeriesSide('管理主表列',`选择列的显示状态；已显示 ${visibleColumns.length} 列，共 ${columns.length} 列。隐藏不会删除任何数据。`,`<div style="display:flex;justify-content:flex-end;margin-bottom:10px"><button class="btn" type="button" onclick="showAllSeriesColumns()" ${visibleColumns.length===columns.length?'disabled':''}>全部显示</button></div><div class="series-column-list">${rows||'<div class="empty">暂无列</div>'}</div><section class="series-detail-block"><h3>冻结行列</h3><div class="series-freeze-controls"><div><label>冻结到某一列</label><select class="input" id="seriesFreezeColumns">${freezeOptions}</select></div><div><label>冻结前几行子案</label><input class="input" id="seriesFreezeRows" type="number" min="0" max="20" value="${Number(settings.freeze_rows||0)}"></div></div><p class="series-paste-help">表头始终冻结；冻结列只计算当前显示的列，冻结行从第一条子案向下计算。</p></section><section class="series-detail-block"><h3>新增列</h3><div class="series-form-grid"><div class="full"><label>列名称</label><input class="input" id="seriesNewColumnLabel" placeholder="例如：房号、合同金额、经办律师"></div><div><label>关联案件字段</label><select class="input" id="seriesNewColumnBinding" onchange="syncSeriesNewColumnSource()"><option value="custom">自定义字段</option><option value="series_code">子案编号</option><option value="display_name">子案名称</option><option value="clients">委托人</option><option value="opponents">对方当事人</option><option value="case_type">案由</option><option value="case_no">案号</option><option value="court">法院/仲裁委</option><option value="current_stage">阶段</option><option value="other_differences">案件差异</option><option value="case_focus">侧重点</option><option value="memo">备忘</option></select></div><div><label>列类型</label><select class="input" id="seriesNewColumnType"><option value="text">普通文本</option><option value="amount">金额（纳入顶部汇总）</option></select></div><div><label>候选数据来源</label><select class="input" id="seriesNewColumnSource"><option value="custom">普通文本</option><option value="parties">全部当事人库</option><option value="clients">委托人库</option><option value="opponents">对方当事人库</option><option value="case_types">案由库</option><option value="stages">阶段库</option><option value="courts">法院/仲裁委库</option><option value="party_roles">诉讼地位库</option><option value="number_types">案号性质库</option></select></div><div><label>默认币种</label><select class="input" id="seriesNewColumnCurrency"><option value="CNY">人民币 CNY</option><option value="USD">美元 USD</option><option value="HKD">港币 HKD</option><option value="EUR">欧元 EUR</option></select></div></div></section>`,`<button class="btn" onclick="closeSeriesSide()">关闭</button><button class="btn" onclick="saveSeriesFreezeSettings()">保存冻结设置</button><button class="btn primary" onclick="addSeriesColumnFromPanel()">新增列</button>`);}
async function toggleSeriesColumnVisibility(key){const columns=currentSeriesColumns(),column=columns.find(item=>item.key===key);if(!column)return;const visibleCount=columns.filter(item=>item.hidden!==true).length;if(column.hidden!==true&&visibleCount<=1)return toast('主表至少保留一列显示');delete state.seriesColumnFilters[key];if(state.seriesSortKey===key){state.seriesSortKey='';state.seriesSortDirection='asc';}const next=columns.map(item=>item.key===key?{...item,hidden:item.hidden!==true}:item);if(await persistSeriesColumns(next)){openSeriesColumnManager();toast(column.hidden===true?`已显示“${column.label}”列`:`已隐藏“${column.label}”列，数据仍完整保留`);}}
async function showAllSeriesColumns(){const columns=currentSeriesColumns();if(columns.every(column=>column.hidden!==true))return;const next=columns.map(column=>({...column,hidden:false}));if(await persistSeriesColumns(next)){openSeriesColumnManager();toast('已显示全部列');}}
function syncSeriesNewColumnSource(){const binding=$('seriesNewColumnBinding').value;const map={clients:'clients',opponents:'opponents',case_type:'case_types',current_stage:'stages',court:'courts'};if(map[binding])$('seriesNewColumnSource').value=map[binding];}
async function toggleSeriesAmountColumn(key){const lookupSources=['clients','opponents','parties','case_types','stages','courts','party_roles','number_types'];const next=currentSeriesColumns().map(column=>column.key===key?{...column,semantic_type:column.semantic_type==='amount'?'':'amount',field_type:column.semantic_type==='amount'?(lookupSources.includes(column.source)?'lookup':'text'):'amount',currency:column.currency||'CNY'}:column);if(await persistSeriesColumns(next)){openSeriesColumnManager();toast(next.find(item=>item.key===key)?.semantic_type==='amount'?'已纳入顶部金额汇总':'已取消金额汇总');}}
async function saveSeriesFreezeSettings(){const settings={freeze_columns:Number($('seriesFreezeColumns')?.value||0),freeze_rows:Number($('seriesFreezeRows')?.value||0)};if(await persistSeriesColumns(currentSeriesColumns(),[],settings)){closeSeriesSide();toast('冻结设置已保存');}}
async function addSeriesColumnFromPanel(){const label=$('seriesNewColumnLabel').value.trim();const binding=$('seriesNewColumnBinding').value;const source=$('seriesNewColumnSource').value;const semantic=$('seriesNewColumnType').value==='amount'?'amount':'';const currency=$('seriesNewColumnCurrency').value||'CNY';if(!label)return toast('请填写列名称');if(binding!=='custom'&&currentSeriesColumns().some(x=>x.key===binding))return toast('该案件字段已经显示在主表中');const key=binding==='custom'?`custom_${Date.now().toString(36)}`:binding;const fieldType=semantic==='amount'?'amount':(source==='custom'?'text':'lookup');const linkedSource={clients:'clients',opponents:'opponents',case_type:'case_types',current_stage:'stages',court:'courts'}[binding]||'builtin';const next=[...currentSeriesColumns(),{key,label,source:binding==='custom'?source:linkedSource,field_type:binding==='custom'?fieldType:(semantic==='amount'?'amount':(linkedSource==='builtin'?'text':'lookup')),semantic_type:semantic,currency,width:160}];if(await persistSeriesColumns(next)){closeSeriesSide();toast('新列已添加，可直接填写');}}
function toggleSeriesHiddenRowsView(){if(!state.seriesTableEditMode)return;state.seriesShowHiddenRows=!state.seriesShowHiddenRows;state.seriesSelectedChildIds.clear();renderSeriesChildTable();}
async function setSelectedSeriesRowsHidden(hidden){if(!requireOnlineAction())return;const ids=[...state.seriesSelectedChildIds].map(Number).filter(Boolean);if(!ids.length)return toast(hidden?'请先勾选需要隐藏的行':'请先勾选需要恢复显示的行');try{await api(`/api/case-manager/series/${state.seriesWorkspace.id}/children/bulk`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({child_ids:ids,operation:hidden?'hide':'unhide',payload:{}})});state.seriesSelectedChildIds.clear();await reloadSeriesWorkspace();await refreshAll();toast(hidden?`已隐藏 ${ids.length} 行，数据仍保留`:`已恢复显示 ${ids.length} 行`);}catch(e){toast(e.message);}}
function toggleSeriesChildSelection(id,checked){ if(checked)state.seriesSelectedChildIds.add(id);else state.seriesSelectedChildIds.delete(id); updateSeriesSelectionSummary(); }
function toggleAllSeriesChildren(checked){ const items=seriesFilteredItems(currentSeriesVisibleColumns());items.forEach(x=>checked?state.seriesSelectedChildIds.add(Number(x.id)):state.seriesSelectedChildIds.delete(Number(x.id)));renderSeriesChildTable(); }
function updateSeriesSelectionSummary(){const size=state.seriesSelectedChildIds.size;const el=$('seriesSelectionSummary');if(el)el.textContent=size?`已选择 ${size} 个子案`:'点击子案查看完整详情';const deleteButton=$('seriesDeleteSelectedRows');if(deleteButton)deleteButton.disabled=!size;const hiddenButton=$('seriesHideSelectedRows');if(hiddenButton)hiddenButton.disabled=!size;}
function closeSeriesSide(){ $('seriesSide').classList.remove('show','series-child-detail-overlay');$('seriesSide').setAttribute('aria-hidden','true'); }
function openSeriesChildLedger(childId){ const id=Number(childId||0); if(!id)return toast('当前子案无法打开案件台账'); openCaseResearchShortcut(id,'ledger'); }
function showSeriesSide(title,subtitle,body,foot=''){
  const side = $('seriesSide');
  $('seriesSideTitle').textContent=title;$('seriesSideSubtitle').textContent=subtitle||'';$('seriesSideBody').innerHTML=body;$('seriesSideFoot').innerHTML=foot;
  side.classList.toggle('series-child-detail-overlay', Number(state.editing?.seriesDetailMappingSeriesId || 0) > 0);
  side.classList.add('show');side.setAttribute('aria-hidden','false');activateSeriesLookups($('seriesSideBody'));
}
async function detailMappingSeriesData(){
  const seriesId = Number(state.editing?.seriesDetailMappingSeriesId || 0);
  if (!seriesId) return null;
  if (Number(state.seriesWorkspace?.id || 0) !== seriesId && !isOfflineReadonly()) {
    state.seriesWorkspace = decorateSeriesWorkspaceChildren(await api(`/api/case-manager/series/${seriesId}`));
  }
  return state.seriesWorkspace;
}
function detailMappingTarget(key){ return SERIES_DETAIL_MAPPING_TARGETS.find(item => item.key === key); }
function renderSeriesDetailMappingPanel(){
  const series = state.seriesWorkspace;
  const draft = state.seriesDetailMappingDraft || {};
  const columns = currentSeriesColumns().filter(column => column.field_type !== 'readonly' && column.source !== 'derived');
  const mappings = seriesDetailMappings(series);
  const sourceOptions = columns.map(column => `<button class="series-detail-mapping-option ${draft.sourceKey===column.key?'selected':''}" type="button" aria-pressed="${draft.sourceKey===column.key}" onclick="selectSeriesDetailMappingSource('${esc(column.key)}')"><span>${esc(column.label)}</span><small>主表列</small></button>`).join('') || '<div class="empty">暂无可映射的主表列</div>';
  const targetOptions = SERIES_DETAIL_MAPPING_TARGETS.map(target => `<button class="series-detail-mapping-option ${draft.targetKey===target.key?'selected':''}" type="button" aria-pressed="${draft.targetKey===target.key}" onclick="selectSeriesDetailMappingTarget('${target.key}')"><span>${esc(target.label)}</span><small>${esc(target.section)}</small></button>`).join('');
  const selectedSource = seriesDetailMappingColumn(draft.sourceKey, series)?.label || '选择主表列';
  const selectedTarget = detailMappingTarget(draft.targetKey)?.label || '选择详情字段';
  const mappingRows = mappings.map(mapping => {
    const source = seriesDetailMappingColumn(mapping.source_key, series)?.label || mapping.source_key;
    const target = detailMappingTarget(mapping.target_key);
    return `<div class="series-detail-mapping-row"><strong title="${esc(source)}">${esc(source)}</strong><span class="mapping-arrow" aria-hidden="true">→</span><strong title="${esc(target?.section || '')} · ${esc(target?.label || mapping.target_key)}">${esc(target?.section || '')} · ${esc(target?.label || mapping.target_key)}</strong><button class="series-detail-mapping-remove" type="button" aria-label="删除映射" title="删除映射" onclick="removeSeriesDetailMapping('${esc(mapping.source_key)}','${esc(mapping.target_key)}')">×</button></div>`;
  }).join('') || '<div class="empty">尚未建立映射。详情页将只显示子案本身已录入的信息。</div>';
  $('seriesSideBody').innerHTML = `<p class="series-detail-mapping-intro">依次点击左侧主表列和右侧详情字段，再建立映射。联系人组和案件备忘映射后，详情页可勾选要显示的内容，主表相应列只显示勾选结果；如果只有一组联系人，则默认显示该组。规则会应用到本系列的全部子案。</p><div class="series-detail-mapping-grid"><section class="series-detail-mapping-column"><h3>1. 选择主表列</h3><div class="series-detail-mapping-options">${sourceOptions}</div></section><section class="series-detail-mapping-column"><h3>2. 映射到详情字段</h3><div class="series-detail-mapping-options">${targetOptions}</div></section></div><div class="series-detail-mapping-cta"><strong>${esc(selectedSource)}</strong><span class="mapping-arrow" aria-hidden="true">→</span><strong>${esc(selectedTarget)}</strong><button class="btn primary" type="button" onclick="addSeriesDetailMapping()" ${draft.sourceKey&&draft.targetKey?'':'disabled'}>建立映射</button></div><section class="series-detail-block"><h3>已建立的映射</h3><div class="series-detail-mapping-list">${mappingRows}</div></section>`;
}
async function openSeriesDetailMappingPanel(){
  if (!requireOnlineAction()) return;
  showSeriesSide('主表字段映射','正在读取本系列的主表字段…','<div class="empty">正在加载字段映射设置…</div>');
  try {
    const series = await detailMappingSeriesData();
    if (!series) return toast('未找到所属系列案');
    state.seriesDetailMappingDraft = {sourceKey:'',targetKey:''};
    showSeriesSide('主表字段映射','选择一个主表列，并指定它在普通案件详情页中的显示位置。','');
    renderSeriesDetailMappingPanel();
  } catch (e) { toast(e.message || '无法读取字段映射'); }
}
function selectSeriesDetailMappingSource(key){ state.seriesDetailMappingDraft.sourceKey = key; renderSeriesDetailMappingPanel(); }
function selectSeriesDetailMappingTarget(key){ state.seriesDetailMappingDraft.targetKey = key; renderSeriesDetailMappingPanel(); }
async function persistSeriesDetailMappings(mappings){
  try {
    const seriesId = Number(state.seriesWorkspace?.id || 0);
    const data = await api(`/api/case-manager/series/${seriesId}/detail-field-mappings`, {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({mappings})});
    state.seriesWorkspace.profile.detail_field_mappings = data.mappings || [];
    decorateSeriesWorkspaceChildren(state.seriesWorkspace);
    if (state.seriesWorkspaceTab === 'children') renderSeriesChildTable();
    await refreshSeriesMappedDetailPreview();
    return true;
  } catch (e) { toast(e.message || '字段映射保存失败'); return false; }
}
async function refreshSeriesMappedDetailPreview(){
  const item = state.editing?.item;
  const seriesId = Number(state.editing?.seriesDetailMappingSeriesId || 0);
  if (!item?.id || !seriesId || isOfflineReadonly()) return;
  const child = await api(`/api/case-manager/series/${seriesId}/children/${item.id}`);
  state.editing.item = applySeriesDetailMappings(child, state.seriesWorkspace);
  $('drawerBody').innerHTML = detailHtml('cases', state.editing.item);
  makeDetailFieldsCopyable($('drawerBody'));
  loadCaseAutomationPanel(Number(item.id));
}
async function addSeriesDetailMapping(){
  const {sourceKey,targetKey} = state.seriesDetailMappingDraft || {};
  if (!sourceKey || !targetKey) return;
  const existing = seriesDetailMappings();
  if (existing.some(item => item.source_key===sourceKey && item.target_key===targetKey)) return toast('该映射已存在');
  if (await persistSeriesDetailMappings([...existing,{source_key:sourceKey,target_key:targetKey}])) {
    state.seriesDetailMappingDraft = {sourceKey:'',targetKey:''};
    renderSeriesDetailMappingPanel();
    toast('字段映射已建立');
  }
}
async function removeSeriesDetailMapping(sourceKey,targetKey){
  const mappings = seriesDetailMappings().filter(item => item.source_key!==sourceKey || item.target_key!==targetKey);
  if (await persistSeriesDetailMappings(mappings)) { renderSeriesDetailMappingPanel(); toast('字段映射已删除'); }
}
async function openSeriesChildDetail(childId){
  try {
    const series = state.seriesWorkspace;
    const sid = Number(series?.id || 0);
    const child = isOfflineReadonly()
      ? (series?.children || []).find(item => Number(item.id) === Number(childId))
      : await api(`/api/case-manager/series/${sid}/children/${childId}`);
    if (!child) return;
    closeSeriesSide();
    openCaseDetailDrawer(applySeriesDetailMappings(child, series), sid);
  } catch(e) { toast(e.message); }
}
function seriesDetailBlock(title,text){return `<section class="series-detail-block"><h3>${esc(title)}</h3><p>${esc(text||'')}</p></section>`;}
function seriesDetailBlockHtml(title,html){return `<section class="series-detail-block"><h3>${esc(title)}</h3><div>${html||''}</div></section>`;}
function editSeriesTemplate(){if(!requireOnlineAction())return;closeSeriesSide();state.seriesWorkspaceTab='public';state.seriesPublicEditMode=true;renderSeriesWorkspace();}
function cancelSeriesPublicEdit(){state.seriesPublicEditMode=false;renderSeriesWorkspace();}
async function saveSeriesTemplate(){try{const body=collectSeriesParentForm(false);if(!body.title)return toast('请填写系列案件名称');const data=await api(`/api/case-manager/series/${state.seriesWorkspace.id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});state.seriesWorkspace=data;state.seriesPublicEditMode=false;renderSeriesWorkspace();await refreshAll();toast('系列案公共信息已保存');}catch(e){toast(e.message);}}
const CHILD_CLAIM_MODE_LABELS={inherit:'沿用共同请求',replace:'替换共同请求',supplement:'补充共同请求',exclude:'本案不提出',add:'新增本案请求'};
const CHILD_MILESTONE_STATUS_LABELS={planned:'计划中',completed:'已完成',cancelled:'已取消'};
function childCommonClaimOptions(selected){const claims=state.seriesWorkspace?.common_claims||[];return `<option value="">不关联共同请求</option>${claims.map((claim,index)=>{const label=[claim.claim_code||`共同请求${index+1}`,claim.claim_text].filter(Boolean).join(' · ');return `<option value="${Number(claim.id)||''}" ${Number(selected)===Number(claim.id)?'selected':''}>${esc(label)}</option>`;}).join('')}`;}
function childClaimRowHtml(claim={}){const mode=claim.claim_mode||'add';return `<article class="series-subrecord" data-child-claim-row><div class="series-subrecord-toolbar"><select class="input" data-claim-mode>${Object.entries(CHILD_CLAIM_MODE_LABELS).map(([value,label])=>`<option value="${value}" ${mode===value?'selected':''}>${label}</option>`).join('')}</select><select class="input" data-claim-parent title="选择要替换、补充或排除的系列共同请求">${childCommonClaimOptions(claim.parent_claim_id)}</select><button class="btn danger" type="button" onclick="removeChildSubrecord(this,'claim')">删除</button></div><div class="series-subrecord-grid"><input class="input" data-claim-code value="${esc(claim.claim_code||'')}" placeholder="请求编号（可不填）"><input class="input" data-claim-amount value="${esc(claim.amount_text||'')}" inputmode="decimal" placeholder="请求金额（可不填）"><textarea class="input wide" data-claim-text placeholder="本案的请求内容">${esc(claim.claim_text||'')}</textarea><select class="input" data-claim-currency><option value="CNY" ${(claim.currency||'CNY')==='CNY'?'selected':''}>人民币 CNY</option><option value="USD" ${claim.currency==='USD'?'selected':''}>美元 USD</option><option value="HKD" ${claim.currency==='HKD'?'selected':''}>港币 HKD</option><option value="EUR" ${claim.currency==='EUR'?'selected':''}>欧元 EUR</option></select><input class="input" data-claim-calculation value="${esc(claim.calculation_basis||'')}" placeholder="金额计算方法"><input class="input wide" data-claim-legal value="${esc(claim.legal_basis||'')}" placeholder="法律或合同依据"><textarea class="input wide" data-claim-notes placeholder="备注（可不填）">${esc(claim.notes||'')}</textarea></div></article>`;}
function childClaimEditorHtml(items=[]){return `<section class="series-subrecord-section"><div class="series-subrecord-head"><div><h4>本案请求</h4><div class="series-paste-help">默认沿用系列的共同请求。只有这个子案需要新增、替换、补充或排除请求时，才在这里添加。</div></div><button class="btn" type="button" onclick="addChildClaimRow()">＋ 添加本案请求</button></div><div class="series-subrecord-list" id="childClaimsList">${items.length?items.map(childClaimRowHtml).join(''):'<div class="series-subrecord-empty">本案没有单独调整，当前完全沿用系列共同请求。</div>'}</div></section>`;}
function childMilestoneTypeOptions(selected){const values=['立案/受理','送达','开庭','裁判','执行','回款','结案','自定义'];const current=String(selected||'自定义');if(current&&!values.includes(current))values.unshift(current);return values.map(value=>`<option value="${esc(value)}" ${current===value?'selected':''}>${esc(value)}</option>`).join('');}
function childMilestoneRowHtml(item={}){const status=item.milestone_status||'planned';return `<article class="series-subrecord" data-child-milestone-row><div class="series-subrecord-toolbar"><select class="input" data-milestone-type>${childMilestoneTypeOptions(item.milestone_type)}</select><input class="input" data-milestone-title value="${esc(item.title||'')}" placeholder="节点标题，例如：第一次开庭"><button class="btn danger" type="button" onclick="removeChildSubrecord(this,'milestone')">删除</button></div><div class="series-subrecord-grid"><select class="input" data-milestone-status>${Object.entries(CHILD_MILESTONE_STATUS_LABELS).map(([value,label])=>`<option value="${value}" ${status===value?'selected':''}>${label}</option>`).join('')}</select><input class="input" data-milestone-date type="datetime-local" value="${esc(String(item.happened_at||'').slice(0,16))}"><textarea class="input wide" data-milestone-notes placeholder="备注（可不填）">${esc(item.notes||'')}</textarea></div></article>`;}
function childMilestoneEditorHtml(items=[]){return `<section class="series-subrecord-section"><div class="series-subrecord-head"><div><h4>案件进度</h4><div class="series-paste-help">记录本案的重要时间点，例如立案、送达、开庭、裁判、执行或回款。普通待办和开庭提醒仍可在对应页面新增。</div></div><button class="btn" type="button" onclick="addChildMilestoneRow()">＋ 添加进度</button></div><div class="series-subrecord-list" id="childMilestonesList">${items.length?items.map(childMilestoneRowHtml).join(''):'<div class="series-subrecord-empty">尚未记录关键进度。</div>'}</div></section>`;}
function addChildClaimRow(){const host=$('childClaimsList');if(!host)return;host.querySelector('.series-subrecord-empty')?.remove();host.insertAdjacentHTML('beforeend',childClaimRowHtml({claim_mode:'add',currency:'CNY'}));}
function addChildMilestoneRow(){const host=$('childMilestonesList');if(!host)return;host.querySelector('.series-subrecord-empty')?.remove();host.insertAdjacentHTML('beforeend',childMilestoneRowHtml({milestone_type:'自定义',milestone_status:'planned'}));}
function removeChildSubrecord(button,kind){button.closest(kind==='claim'?'[data-child-claim-row]':'[data-child-milestone-row]')?.remove();const host=$(kind==='claim'?'childClaimsList':'childMilestonesList');if(host&&!host.children.length)host.innerHTML=`<div class="series-subrecord-empty">${kind==='claim'?'本案没有单独调整，当前完全沿用系列共同请求。':'尚未记录关键进度。'}</div>`;}
function collectChildClaims(){return [...document.querySelectorAll('#childClaimsList [data-child-claim-row]')].map(row=>({claim_mode:row.querySelector('[data-claim-mode]').value,parent_claim_id:Number(row.querySelector('[data-claim-parent]').value)||null,claim_code:row.querySelector('[data-claim-code]').value.trim(),claim_text:row.querySelector('[data-claim-text]').value.trim(),amount_text:row.querySelector('[data-claim-amount]').value.trim(),currency:row.querySelector('[data-claim-currency]').value||'CNY',calculation_basis:row.querySelector('[data-claim-calculation]').value.trim(),legal_basis:row.querySelector('[data-claim-legal]').value.trim(),notes:row.querySelector('[data-claim-notes]').value.trim()}));}
function collectChildMilestones(){return [...document.querySelectorAll('#childMilestonesList [data-child-milestone-row]')].map(row=>({milestone_type:row.querySelector('[data-milestone-type]').value||'自定义',title:row.querySelector('[data-milestone-title]').value.trim(),milestone_status:row.querySelector('[data-milestone-status]').value||'planned',happened_at:row.querySelector('[data-milestone-date]').value,notes:row.querySelector('[data-milestone-notes]').value.trim()}));}
function seriesNumberRowHtml(item={},prefix='childNumbers'){const rowId=`${prefix}${++seriesEditorRowSeed}`;return `<div class="series-number-row" data-series-number-row>${seriesLookupInput(`${rowId}Type`,item.number_type||'','number_types','案号性质')}<input class="input" data-number-case-no value="${esc(item.case_no||'')}" placeholder="案号">${seriesLookupInput(`${rowId}Court`,item.court||'','courts','法院/仲裁委') }<input class="input" data-number-contact value="${esc(item.handler_contact||'')}" placeholder="承办人/联系方式"><button class="btn danger" type="button" onclick="this.closest('[data-series-number-row]').remove()">删除</button></div>`;}
function seriesNumberEditorHtml(items=[],id='childNumbers'){return `<div class="series-number-editor" id="${id}">${(items.length?items:[{}]).map(item=>seriesNumberRowHtml(item,id)).join('')}</div><button class="btn" type="button" style="margin-top:8px" onclick="addSeriesNumberRow('${id}')">＋ 添加案号</button><span class="series-lookup-note">案号性质和法院/仲裁委均从现有案件数据中搜索选择。</span>`;}
function addSeriesNumberRow(id,item={}){const host=$(id);if(!host)return;host.insertAdjacentHTML('beforeend',seriesNumberRowHtml(item,id));activateSeriesLookups(host);}
function collectSeriesNumberEditor(id){return [...($(id)?.querySelectorAll('[data-series-number-row]')||[])].map(row=>({number_type:row.querySelector('[data-series-lookup="number_types"]')?.value.trim()||'',case_no:row.querySelector('[data-number-case-no]')?.value.trim()||'',court:row.querySelector('[data-series-lookup="courts"]')?.value.trim()||'',handler_contact:row.querySelector('[data-number-contact]')?.value.trim()||''})).filter(item=>Object.values(item).some(Boolean));}
async function openSeriesChildEditor(childId=0){
  try{const rawItem=childId?await api(`/api/case-manager/series/${state.seriesWorkspace.id}/children/${childId}`):{};const item=childId?applySeriesDetailMappings(rawItem,state.seriesWorkspace):rawItem;showSeriesSide(childId?'编辑子案':'新增子案','主表字段与当前表格完全一致；下方保留案件专项信息',`${seriesEditorTableFieldsHtml(item)}<section class="series-detail-block"><h3>案件基础与专项信息</h3><div class="series-form-grid">
    <div><label>${esc(seriesEditorColumnLabel('series_code','子案编号'))}</label><input class="input" id="childFormCode" value="${esc(item.series_code||'')}"></div><div><label>子案标识（${esc(seriesEditorColumnLabel('display_name','子案名称'))}）*</label><input class="input" id="childFormName" value="${esc(item.display_name||item.series_display_name||'')}"><span class="series-lookup-note">案件名称会根据对方当事人自动生成。</span></div>
    <div><label>${esc(seriesEditorColumnLabel('case_type','案件类型（案由）'))}</label>${seriesLookupInput('childFormType',item.case_type||state.seriesWorkspace.case_type||'','case_types','点击选择或搜索案由')}</div><div><label>${esc(seriesEditorColumnLabel('current_stage','当前阶段'))}</label>${seriesLookupInput('childFormStage',item.current_stage||'','stages','点击选择或搜索阶段')}</div>
    ${seriesModeField('案情处理方式','childFactsMode',item.facts_mode||'inherit')}<div><label>${esc(seriesEditorColumnLabel('facts_difference','案情差异/替换内容'))}</label><textarea class="input" id="childFactsDiff">${esc(item.facts_difference||'')}</textarea></div>
    ${seriesModeField('合同条款处理方式','childContractMode',item.contract_mode||'inherit')}<div><label>${esc(seriesEditorColumnLabel('contract_difference','合同条款差异/替换内容'))}</label><textarea class="input" id="childContractDiff">${esc(item.contract_difference||'')}</textarea></div>
    <div class="full"><label>${esc(seriesEditorColumnLabel('other_differences','其他差异'))}</label><textarea class="input" id="childOtherDiff">${esc(item.other_differences||'')}</textarea></div><div class="full"><label>${esc(seriesEditorColumnLabel('case_focus','案件侧重点'))}</label><textarea class="input" id="childFocus">${esc(item.case_focus||'')}</textarea></div><div class="full"><label>${esc(seriesEditorColumnLabel('memo','子案备忘'))}</label><textarea class="input" id="childMemo">${esc(item.memo||'')}</textarea></div>
    <div class="full"><label>${esc(seriesEditorGroupLabel(['clients','opponents'],'当事人'))}</label>${seriesPartyEditorHtml(item.parties||[],'childParties')}</div>
    <div class="full"><label>${esc(seriesEditorGroupLabel(['case_no','court'],'案号及受理机构'))}</label>${seriesNumberEditorHtml(item.case_numbers||[],'childNumbers')}</div>
    <div class="full">${childClaimEditorHtml(item.claims||[])}</div>
    <div class="full">${childMilestoneEditorHtml(item.milestones||[])}</div>
  </div></section>`,`<button class="btn" onclick="closeSeriesSide()">取消</button><button class="btn primary" onclick="saveSeriesChild(${Number(childId)})">保存子案</button>`);}catch(e){toast(e.message);}
}
function seriesModeField(label,id,value){return `<div><label>${esc(label)}</label><select class="input" id="${id}">${Object.entries(SERIES_MODE_LABELS).map(([k,v])=>`<option value="${k}" ${k===value?'selected':''}>${v}</option>`).join('')}</select></div>`;}
function collectChildForm(){const tableFields=collectSeriesEditorTableFields();return {...tableFields.direct,series_code:$('childFormCode').value.trim(),display_name:$('childFormName').value.trim(),case_type:$('childFormType').value.trim(),current_stage:$('childFormStage').value.trim(),facts_mode:$('childFactsMode').value,facts_difference:$('childFactsDiff').value.trim(),contract_mode:$('childContractMode').value,contract_difference:$('childContractDiff').value.trim(),other_differences:$('childOtherDiff').value.trim(),case_focus:$('childFocus').value.trim(),memo:$('childMemo').value.trim(),custom_values:tableFields.custom,parties:collectSeriesPartyEditor('childParties'),case_numbers:collectSeriesNumberEditor('childNumbers'),claims:collectChildClaims(),milestones:collectChildMilestones()};}
async function saveSeriesChild(childId){const body=collectChildForm();if(!body.display_name)return toast('请填写子案名称');try{const base=`/api/case-manager/series/${state.seriesWorkspace.id}/children`;await api(childId?`${base}/${childId}`:base,{method:childId?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});closeSeriesSide();await reloadSeriesWorkspace();toast('子案已保存');}catch(e){toast(e.message);}}
async function reloadSeriesWorkspace(){const id=state.seriesWorkspace.id;state.seriesWorkspace=decorateSeriesWorkspaceChildren(await api(`/api/case-manager/series/${id}`));renderSeriesWorkspace();scheduleCaseOfflineSnapshot(true,3000);}
function openSeriesBatchPanel(){if(!state.seriesSelectedChildIds.size)return toast('请先勾选子案');showSeriesSide('批量操作',`已选择 ${state.seriesSelectedChildIds.size} 个子案`,`<div class="series-form-grid"><div class="full"><label>操作</label><select class="input" id="seriesBatchOperation" onchange="renderSeriesBatchFields()"><option value="set_fields">修改业务字段</option><option value="add_milestone">增加关键节点</option><option value="add_todo">创建待办</option><option value="add_hearing">创建开庭</option><option value="archive">结案/归档</option><option value="restore">恢复在办</option><option value="delete">移入垃圾站</option></select></div><div class="full" id="seriesBatchFields"></div></div>`,`<button class="btn" onclick="closeSeriesSide()">取消</button><button class="btn primary" onclick="runSeriesBatch()">预览并执行</button>`);renderSeriesBatchFields();}
function renderSeriesBatchFields() {
  const op = $('seriesBatchOperation')?.value;
  const host = $('seriesBatchFields');
  if (!host) return;
  if (op === 'set_fields') {
    host.innerHTML = `<div class="series-batch-panel"><label>字段或关联记录操作</label><select class="input" id="seriesBatchField">
      <option value="current_stage">当前阶段</option><option value="case_focus">案件侧重点</option><option value="other_differences">其他差异</option><option value="memo">备忘</option>
      <option value="court_contact">裁判机关联系方式</option><option value="party_contact">当事人联系方式</option><option value="facts_difference">案情差异</option><option value="contract_difference">合同差异</option>
      <option value="parties_append">追加当事人</option><option value="parties_replace">替换当事人</option><option value="parties_remove">移除当事人</option>
      <option value="case_numbers_append">追加案号</option><option value="case_numbers_replace">替换案号</option><option value="case_numbers_remove">移除案号</option>
      <option value="claims_append">追加请求项</option><option value="claims_replace">替换请求项</option><option value="claims_remove">移除请求项</option>
    </select><label style="margin-top:9px">新值/关联记录</label><textarea class="input" id="seriesBatchValue" placeholder="普通字段直接填写；当事人、案号和请求项使用与子案编辑页相同的 Tab 分列格式"></textarea></div>`;
  } else if (op === 'add_milestone') {
    host.innerHTML = `<div class="series-batch-panel"><input class="input" id="seriesBatchType" placeholder="节点类型"><input class="input" id="seriesBatchTitle" placeholder="节点标题"><select class="input" id="seriesBatchStatus"><option value="completed">已完成</option><option value="planned">计划中</option><option value="cancelled">已取消</option></select><input class="input" id="seriesBatchDate" type="datetime-local"><textarea class="input" id="seriesBatchNotes" placeholder="备注"></textarea><label><input type="checkbox" id="seriesBatchSyncStage"> 同时把当前阶段改为节点类型</label></div>`;
  } else if (op === 'add_todo') {
    host.innerHTML = `<div class="series-batch-panel"><input class="input" id="seriesBatchTitle" placeholder="待办事项"><input class="input" id="seriesBatchDate" type="datetime-local"><textarea class="input" id="seriesBatchNotes" placeholder="备注"></textarea></div>`;
  } else if (op === 'add_hearing') {
    host.innerHTML = `<div class="series-batch-panel"><input class="input" id="seriesBatchType" placeholder="开庭类型"><input class="input" id="seriesBatchDate" type="datetime-local"><input class="input" id="seriesBatchLocation" placeholder="地点"><input class="input" id="seriesBatchCourt" placeholder="受理机构"><textarea class="input" id="seriesBatchNotes" placeholder="备注"></textarea></div>`;
  } else {
    host.innerHTML = `<div class="series-batch-panel">该操作将影响已选择的 ${state.seriesSelectedChildIds.size} 个子案，提交前会再次确认。</div>`;
  }
}
async function runSeriesBatch() {
  const op = $('seriesBatchOperation').value;
  let payload = {};
  if (op === 'set_fields') {
    const field = $('seriesBatchField').value;
    const value = $('seriesBatchValue').value;
    const [kind, operation] = field.split('_').length > 1 && /_(append|replace|remove)$/.test(field)
      ? [field.replace(/_(append|replace|remove)$/, ''), field.match(/(append|replace|remove)$/)[1]] : ['', ''];
    if (kind === 'parties') payload = { parties:parseSeriesParties(value), party_operation:operation };
    else if (kind === 'case_numbers') payload = { case_numbers:tabLines(value).map(c=>({number_type:c[0]||'',case_no:c[1]||'',court:c[2]||'',handler_contact:c[3]||''})), number_operation:operation };
    else if (kind === 'claims') payload = { claims:tabLines(value).map(c=>({claim_mode:c[0]||'add',parent_claim_id:Number(c[1])||null,claim_code:c[2]||'',claim_text:c[3]||'',amount_text:c[4]||'',currency:c[5]||'CNY'})), claim_operation:operation };
    else payload = {[field]:value};
  } else if (op === 'add_milestone') payload = {milestone:{milestone_type:$('seriesBatchType').value||'自定义',title:$('seriesBatchTitle').value,milestone_status:$('seriesBatchStatus').value,happened_at:$('seriesBatchDate').value,notes:$('seriesBatchNotes').value},sync_stage:$('seriesBatchSyncStage').checked,current_stage:$('seriesBatchType').value};
  else if (op === 'add_todo') payload = {todo_title:$('seriesBatchTitle').value,remind_at:$('seriesBatchDate').value,notes:$('seriesBatchNotes').value};
  else if (op === 'add_hearing') payload = {reminder_type:$('seriesBatchType').value||'开庭',hearing_at:$('seriesBatchDate').value,location:$('seriesBatchLocation').value,court:$('seriesBatchCourt').value,notes:$('seriesBatchNotes').value};
  if (!confirm(`确认对 ${state.seriesSelectedChildIds.size} 个子案执行该操作？`)) return;
  try {
    const ids = [...state.seriesSelectedChildIds];
    if (op === 'archive') await api('/api/case-manager/cases/bulk-archive',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ids})});
    if (op === 'delete') await api('/api/case-manager/cases/bulk-delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ids})});
    if (op === 'restore') for (const id of ids) await api(`/api/case-manager/cases/${id}/restore`,{method:'POST'});
    await api(`/api/case-manager/series/${state.seriesWorkspace.id}/children/bulk`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({child_ids:ids,operation:op,payload})});
    closeSeriesSide(); state.seriesSelectedChildIds.clear(); await reloadSeriesWorkspace(); await refreshAll(); toast('批量操作已完成');
  } catch (e) { toast(e.message); }
}
function seriesImportCountsText(data){const counts=data?.counts||{};return [['Excel数据行',counts.children],['识别字段列',counts.columns]].filter(([,value])=>value!==undefined&&value!==null).map(([label,value])=>`${label} ${esc(String(Number(value)||0))}`).join(' · ');}
function seriesImportRecognizedLabel(column={}){const labels={series_code:'子案编号',display_name:'子案名称',clients:'委托人',opponents:'对方当事人',case_type:'案由',case_no:'案号',court:'法院/仲裁委',current_stage:'当前阶段',latest_milestone:'最近节点',next_milestone:'下一节点',claim_totals:'请求金额',other_differences:'其他差异',case_focus:'侧重点',memo:'备忘'};const key=String(column.key||'').trim(),recognized=String(column.recognized_as||'').trim();return labels[recognized]||labels[key]||recognized||(/^[a-z][a-z0-9_]*$/i.test(key)?'自定义列':key)||'自定义列';}
function seriesImportHasStableKey(data){if(Object.prototype.hasOwnProperty.call(data||{},'has_stable_key'))return Boolean(data.has_stable_key);return (data?.columns||[]).some(column=>String(column.key||'')==='series_code'||['编号','序号','子案编号','案件编号','序列号'].includes(String(column.label||'').replace(/\s+/g,'')));}
function seriesImportCompletenessHtml(data){
  const diff=data?.diff,summary=diff?.summary||{},counts=data?.counts||{};
  const activeChildren=(state.seriesWorkspace?.children||[]).filter(item=>item.source_status!=='deleted'),hasDiff=Boolean(diff&&diff.summary),before=Number(summary.before??activeChildren.length),after=Number(summary.after??counts.children??0),added=Number(summary.added||0),updated=Number(summary.updated||0),deleted=Number(summary.deleted||0),unchanged=Number(summary.unchanged||0),columns=Number(counts.columns??data?.columns?.length??0),missingRows=data?.missing_stable_key_rows||[];
  const hasStableKey=seriesImportHasStableKey(data),balanced=hasDiff&&after===Math.max(0,before-deleted+added),hasErrors=Boolean(data?.errors?.length);
  const status=hasErrors?['danger','不可导入']:!hasDiff?['warn','待系统对比']:!balanced?['danger','行数不闭合']:deleted?['warn','需确认删除']:['ok','结构完整'];
  const check=(title,value,note,cls='')=>`<div class="series-import-check ${cls}"><strong>${title}：${value}</strong><small>${note}</small></div>`;
  const rowFormula=hasDiff?`${before} - ${deleted} + ${added} = ${after}`:`当前 ${before} 个子案 ↔ Excel ${after} 行`;
  return `<section class="series-import-completeness"><div class="series-import-completeness-head"><h3>导入完整性检查</h3><span class="series-import-status ${status[0]==='ok'?'':status[0]}">${status[1]}</span></div><div class="series-import-check-grid">${check('Excel数据行',`${after} 行`,`当前系统有 ${before} 个子案，导入后预计保留 ${Math.max(0,before-deleted+added)} 个子案`)}${check('数量核对',rowFormula,hasDiff?(balanced?'数量可以闭合：当前子案扣除删除项，再加上新增项。':'数量无法闭合，请先修正 Excel。'):'当前服务尚未返回逐行差异，暂不能判断增删。',hasDiff&&!balanced?'is-danger':!hasDiff?'is-warn':'')}${check('编号匹配',hasStableKey?'已识别编号列':'未识别编号列',hasStableKey?(missingRows.length?`第 ${missingRows.slice(0,8).join('、')} 行缺少编号，请补齐后再导入。`:'编号将用于逐行匹配、识别修改和判断删除。'):'已有子案时必须保留“编号/序号/子案编号”列。',!hasStableKey||missingRows.length?'is-danger':'')}${check('字段完整',`${columns} 列`,`下方内容预览将展示全部 ${columns} 列，可横向滚动查看。`)}</div>${hasDiff?`<p class="series-paste-help" style="margin:9px 0 0">分类合计：新增 ${added} · 修改 ${updated} · 保持不变 ${unchanged} · Excel共 ${after} 行。</p>`:''}</section>`;
}
function seriesImportDiffValue(value){const raw=String(value??'');return raw?esc(raw).replace(/\n/g,'<br>'):'<span class="before">—</span>';}
function seriesImportDiffFields(change){
  if(change.type==='deleted')return '<span class="before">整行将移入垃圾站，可从导入历史回退</span>';
  const fields=change.fields||[];
  if(!fields.length)return '<span class="before">无字段变化</span>';
  return fields.map(field=>`<div><strong>${esc(field.label||field.key)}</strong><div><span class="before">${seriesImportDiffValue(field.before)}</span><span class="arrow">→</span><span class="after">${seriesImportDiffValue(field.after)}</span></div></div>`).join('');
}
function seriesImportDiffHtml(diff){
  if(!diff)return '';
  const summary=diff.summary||{},changes=diff.changes||[];
  const stat=(label,key,cls)=>`<div class="series-import-stat ${cls}"><span>${label}</span><strong>${Number(summary[key]||0)}</strong></div>`;
  const rows=changes.map(change=>`<tr><td><span class="series-import-change-badge ${esc(change.type||'')}">${change.type==='added'?'新增':change.type==='updated'?'修改':'删除'}</span></td><td><strong>${esc(change.code||'—')}</strong><br><span class="series-paste-help">${esc(change.name||'未命名子案')}</span></td><td>${seriesImportDiffFields(change)}</td></tr>`).join('');
  return `<section class="series-detail-block"><h3>写入前差异预览</h3><div class="series-import-summary">${stat('新增行','added','added')}${stat('修改行','updated','updated')}${stat('删除行','deleted','deleted')}${stat('保持不变','unchanged','')}</div>${summary.deleted?`<div class="series-import-safety is-danger"><strong>注意：${Number(summary.deleted)} 行在 Excel 中已不存在。</strong><br>确认后将先移入案件垃圾站，不会立即物理删除；需要时可从“导入历史”一键回退。</div>`:''}${!diff.deletions_enabled?'<div class="series-import-safety"><strong>当前文件没有可识别的编号列。</strong><br>为避免误更新，已有系列要求保留“编号/序号/子案编号”列。</div>':''}${rows?`<div class="series-import-diff"><table><thead><tr><th>动作</th><th>编号 / 子案</th><th>字段变化（当前值 → 导入值）</th></tr></thead><tbody>${rows}</tbody></table></div>${diff.truncated?'<p class="series-paste-help">变化较多，仅展示前 300 条；统计数字仍为完整结果。</p>':''}`:'<p class="series-paste-help">没有检测到字段变化，确认后仍会保存一个可回退版本。</p>'}</section>`;
}
function seriesImportSampleHtml(data){
  const samples=data?.samples||[],columns=data?.columns||[];
  if(!samples.length)return '<section class="series-detail-block"><h3>内容预览</h3><p class="series-paste-help">没有读取到有效数据行。</p></section>';
  const tableWidth=Math.max(760,62+columns.reduce((sum,column)=>sum+Math.max(120,Math.min(260,Number(column.width)||150)),0));
  const headers=columns.map(column=>`<th>${esc(column.label||column.key)}</th>`).join('');
  const rows=samples.map(row=>`<tr><td class="series-import-row-head">第 ${Number(row._row)||'—'} 行</td>${columns.map(column=>`<td>${seriesImportDiffValue(row[column.key]??'')}</td>`).join('')}</tr>`).join('');
  return `<section class="series-detail-block"><h3>内容预览（前 ${samples.length} 行 / 全部 ${columns.length} 列）</h3><div class="series-import-sample"><div class="series-import-sample-note">已读取 Excel 第 ${Number(samples[0]._row)||'—'} 至第 ${Number(samples[samples.length-1]._row)||'—'} 行；下方保留全部字段，横向滚动可查看右侧列。</div><table style="min-width:${tableWidth}px"><thead><tr><th class="series-import-row-head">Excel行</th>${headers}</tr></thead><tbody>${rows}</tbody></table></div></section>`;
}
function seriesImportHistoryOperationLabel(operation){return operation==='history_restore'?'回退前版本':'Excel 导入前版本';}
function seriesImportHistorySummary(item){const summary=item.summary||{};return `新增 ${Number(summary.added||0)} · 修改 ${Number(summary.updated||0)} · 删除 ${Number(summary.deleted||0)}${summary.restored_history_id?` · 回退版本 #${Number(summary.restored_history_id)}`:''}`;}
function seriesImportHistoryItemHtml(item,pending){
  const id=Number(item.history_id||0),confirming=pending===id;
  const action=confirming
    ? `<div class="series-import-safety is-danger" style="margin:0"><strong>确认回退到这个版本？</strong><div style="margin-top:7px;display:flex;gap:7px"><button class="btn" type="button" onclick="state.seriesHistoryPendingId=0;renderSeriesImportHistoryPanel()">取消</button><button class="btn danger" type="button" onclick="restoreSeriesImportHistory(${id})">确认回退</button></div></div>`
    : `<button class="btn" type="button" onclick="requestRestoreSeriesHistory(${id})">回退到此版本</button>`;
  return `<article class="series-import-history-item"><div class="series-import-history-item-main"><strong>#${id} · ${esc(seriesImportHistoryOperationLabel(item.operation))}</strong><span>${esc(String(item.created_at||'').replace('T',' '))}<br>${esc(seriesImportHistorySummary(item))}</span></div>${action}</article>`;
}
function renderSeriesImportHistoryPanel(){
  const data=state.seriesImportHistory||{},items=data.items||[],pending=Number(state.seriesHistoryPendingId||0);
  const body=items.length?`<div class="series-import-history-list">${items.map(item=>seriesImportHistoryItemHtml(item,pending)).join('')}</div>`:'<div class="empty">暂无 Excel 导入历史。完成一次导入后，这里会保留最多 10 个可回退版本。</div>';
  $('seriesSideBody').innerHTML=`<div class="series-import-safety"><strong>最多保留 ${Number(data.limit||10)} 个版本。</strong><br>每个版本保存导入前的子表、列设置、当事人、案号、请求项和进度节点；回退也会生成新的保护版本。</div>${body}`;
  activateSeriesLookups($('seriesSideBody'));
}
async function openSeriesImportHistory(){
  if(!requireOnlineAction())return;
  try{state.seriesHistoryPendingId=0;state.seriesImportHistory=await api(`/api/case-manager/series/${state.seriesWorkspace.id}/history`);showSeriesSide('Excel 导入历史','最近 10 个可回退的表单版本','');renderSeriesImportHistoryPanel();}catch(e){toast(e.message);}
}
function requestRestoreSeriesHistory(historyId){state.seriesHistoryPendingId=Number(historyId||0);renderSeriesImportHistoryPanel();}
async function restoreSeriesImportHistory(historyId){
  if(!requireOnlineAction())return;
  try{await api(`/api/case-manager/series/${state.seriesWorkspace.id}/history/${Number(historyId)}/restore`,{method:'POST'});state.seriesHistoryPendingId=0;closeSeriesSide();await reloadSeriesWorkspace();await refreshAll();toast(`已回退到历史版本 #${Number(historyId)}`);}catch(e){toast(e.message);}
}
async function previewSeriesImport(file){
  if(!file)return;
  const form=new FormData();form.append('file',file);
  try{
    const data=await api(`/api/case-manager/series/${state.seriesWorkspace.id}/import-preview`,{method:'POST',body:form});
    state.seriesImportPreview=data;
    const counts=seriesImportCountsText(data);
    let body=seriesDetailBlockHtml('识别结果',`${data.sheet?`工作表：${esc(data.sheet)}；表头位于第 ${Number(data.header_row)||'—'} 行；`:''}${esc(counts)}<div class="series-paste-help" style="margin-top:5px">数据库尚未写入，以下内容只是预览。</div>`);
    if(data.mode==='smart_table'){
      body+=seriesImportCompletenessHtml(data);
      body+=seriesImportDiffHtml(data.diff);
      body+=`<section class="series-detail-block"><h3>智能列映射</h3><div class="series-import-table-scroll"><table class="series-import-map"><thead><tr><th>原表列名</th><th>系统识别</th><th>字段性质</th></tr></thead><tbody>${(data.columns||[]).map(c=>`<tr><td>${esc(c.label)}</td><td>${esc(seriesImportRecognizedLabel(c))}</td><td>${esc(seriesColumnKindLabel(c))}</td></tr>`).join('')}</tbody></table></div><p class="series-paste-help">未识别的列会自动成为本系列的自定义列；金额列会自动纳入顶部汇总。确认导入后，主表会按这些列重新排列。</p></section>`;
      body+=seriesImportSampleHtml(data);
    }
    if(data.mode==='smart_table'&&!data.diff)body+='<div class="series-import-safety is-danger"><strong>当前服务没有返回逐行差异对比。</strong><br>为避免把整张表误写入，请刷新或重启 APEX 后重新上传；数据库尚未写入。</div>';
    if(data.errors?.length)body+=data.errors.map(e=>seriesDetailBlock(`${e.sheet} 第${e.row||'-'}行`,e.message)).join('');
    if(data.errors?.length){
      showSeriesSide('电子表格导入检查',`发现 ${data.errors.length} 个错误，数据库尚未写入`,body,'<button class="btn" onclick="closeSeriesSide()">关闭并修改文件</button>');
    }else if(data.mode==='smart_table'&&!data.diff){
      showSeriesSide('电子表格导入检查','未完成安全对比，数据库尚未写入',body,'<button class="btn" onclick="closeSeriesSide()">关闭并重新上传</button>');
    }else if(data.mode==='smart_table'){
      const deleted=Number(data.diff?.summary?.deleted||0);
      showSeriesSide('确认智能导入',deleted?`发现 ${deleted} 行将移入垃圾站，请核对后确认`:'请核对写入前差异，确认后才会更新子表',body,`<button class="btn" onclick="closeSeriesSide()">取消</button><button class="btn primary" onclick="commitSeriesImport()">${deleted?`确认导入并处理 ${deleted} 行删除`:'确认导入'}</button>`);
    }else{
      showSeriesSide('确认 Excel 导入','标准六表工作簿检查通过，提交后将整批写入',body,'<button class="btn" onclick="closeSeriesSide()">取消</button><button class="btn primary" onclick="commitSeriesImport()">确认导入</button>');
    }
  }catch(e){toast(e.message);}finally{$('seriesImportFile').value='';}
}
async function commitSeriesImport(){try{const result=await api(`/api/case-manager/series/${state.seriesWorkspace.id}/import-commit`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({preview_id:state.seriesImportPreview.preview_id})});closeSeriesSide();await reloadSeriesWorkspace();await refreshAll();toast(`Excel 已导入；已保存导入前版本 #${Number(result.history_id||0)}`);}catch(e){toast(e.message);}}
function exportSeriesWorkbook(){if(isOfflineReadonly())return requireOnlineAction();window.location.href=`/api/case-manager/series/${state.seriesWorkspace.id}/export`;}
async function archiveSeries(force=false,skipConfirm=false){if(!force&&!skipConfirm){openCaseActionDialog('series_archive',[Number(state.seriesWorkspace?.id||0)],'确认归档该系列？仍在办子案将按系列规则处理。');return;}try{if(force){const ids=(state.seriesWorkspace.children||[]).filter(x=>x.source_status==='active').map(x=>Number(x.id));if(ids.length)await api('/api/case-manager/cases/bulk-archive',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ids})});}await api(`/api/case-manager/series/${state.seriesWorkspace.id}/archive`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({force})});closeSeriesWorkspace();await refreshAll();toast('系列案件已归档');}catch(e){toast(e.message);}}
async function openSeriesForArchive(seriesId){ await openSeriesWorkspace(seriesId); if(state.seriesWorkspace?.id===seriesId) await archiveSeries(false); }
async function deleteSeries(seriesId){openCaseActionDialog('series_delete',[Number(seriesId)],'确定删除该系列及全部子案？删除后进入垃圾站并保留原状态。');}

const JM_API = '/api/case-manager/judicial-messages';
const JM_STATUS_LABELS = { pending:'待分类', suggested:'建议确认', confirmed:'已归类/关联', auto_written:'自动写入', ignored:'已忽略' };
const JM_DEST_LABELS = { hearing:'开庭/听证记录', todo:'待办提醒', ledger:'案件台账', memo:'研究备忘录' };

function linkifyJudicialMessageText(value, completeValue = value) {
  const text = String(value ?? '');
  const completeText = String(completeValue ?? text);
  const pattern = /https?:\/\/[^\s<>"'，。；！！？）\]】]+/gi;
  let html = '';
  let cursor = 0;
  for (const match of text.matchAll(pattern)) {
    let url = match[0].replace(/[.,;:!?]+$/g, '');
    if (!url) continue;
    html += esc(text.slice(cursor, match.index));
    const clippedInsideUrl = completeText.length > text.length
      && Number(match.index) + match[0].length === text.length
      && /[A-Za-z0-9/?#&=._%+\-]/.test(completeText.charAt(text.length));
    html += clippedInsideUrl ? esc(url) : `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer" title="在新页面打开（请先核对域名）" onclick="event.stopPropagation()">${esc(url)}</a>`;
    cursor = Number(match.index) + url.length;
  }
  return html + esc(text.slice(cursor));
}

function judicialStatusBadge(status) {
  const cls = status === 'auto_written' ? 'auto' : status === 'confirmed' ? 'confirmed' : status === 'pending' ? 'pending' : '';
  return `<span class="jm-badge ${cls}">${esc(JM_STATUS_LABELS[status] || status || '待处理')}</span>`;
}

async function loadJudicialMessages(preserveScroll = false) {
  if (state.offlineMode) {
    state.judicialMessages.statusData = null;
    return renderJudicialMessages();
  }
  const jm = state.judicialMessages;
  const params = new URLSearchParams({ page:String(jm.page), page_size:String(jm.pageSize) });
  if (jm.q) params.set('q', jm.q);
  if (jm.status) params.set('status', jm.status);
  if (jm.category) params.set('category', jm.category);
  if (jm.dateFrom) params.set('date_from', jm.dateFrom);
  if (jm.dateTo) params.set('date_to', jm.dateTo);
  if (jm.newOnly) params.set('new_only', '1');
  try {
    const previousNewCount = Number(jm.statusData?.new_count || 0);
    const hadPreviousStatus = Boolean(jm.statusData);
    const [statusData, listData] = await Promise.all([api(`${JM_API}/status`), api(`${JM_API}?${params}`)]);
    jm.statusData = statusData;
    jm.items = listData.items || [];
    jm.total = Number(listData.total || 0);
    jm.categories = listData.categories || [];
    const pending = Number(statusData.counts?.pending || 0) + Number(statusData.counts?.suggested || 0);
    const currentNewCount = Number(statusData.new_count || 0);
    const badge = $('judicialMessageBadge');
    if (badge) {
      badge.textContent = pending;
      badge.classList.toggle('has-new', currentNewCount > 0);
      badge.title = currentNewCount ? `待处理 ${pending} 条，其中新增 ${currentNewCount} 条` : `待处理 ${pending} 条`;
    }
    if (hadPreviousStatus && currentNewCount > previousNewCount) {
      toast(`新收到 ${currentNewCount - previousNewCount} 条司法短信，请及时查看`);
    }
  } catch (e) {
    toast(e.message || '司法短信加载失败');
  }
  if (activeTab === 'judicialMessages') renderJudicialMessages(preserveScroll);
}

function setJudicialFilter(key, value) {
  const jm = state.judicialMessages;
  jm[key] = value;
  jm.page = 1;
  jm.selectedIds = [];
  loadJudicialMessages();
}

function toggleJmCategoryDropdown(event) {
  event.stopPropagation();
  const dd = $('jmCategoryDd');
  if (!dd) return;
  const wasOpen = dd.classList.contains('open');
  closeJmCategoryDropdown();
  if (!wasOpen) {
    dd.classList.add('open');
    dd.querySelector('.jm-dd-trigger')?.setAttribute('aria-expanded', 'true');
  }
}

function closeJmCategoryDropdown() {
  document.querySelectorAll('.jm-dd.open').forEach(el => {
    el.classList.remove('open');
    el.querySelector('.jm-dd-trigger')?.setAttribute('aria-expanded', 'false');
  });
  document.querySelectorAll('.list-hero-wrap.filter-menu-open').forEach(el => el.classList.remove('filter-menu-open'));
}

document.addEventListener('click', event => {
  const option = event.target.closest('.jm-dd-option');
  if (option) {
    const dd = option.closest('.jm-dd');
    closeJmCategoryDropdown();
    if (dd && dd.id === 'jmCategoryDd') {
      const value = option.getAttribute('data-value') || '';
      if (String(state.judicialMessages.category || '') !== value) setJudicialFilter('category', value);
    } else if (dd && dd.id === 'listFieldDd') {
      const value = option.getAttribute('data-value') || 'all';
      const labelEl = dd.querySelector('.jm-dd-label');
      if (labelEl) labelEl.textContent = (LIST_FIELD_OPTIONS.find(([field]) => field === value) || LIST_FIELD_OPTIONS[0])[1];
      dd.querySelectorAll('.jm-dd-option').forEach(el => el.classList.toggle('active', (el.getAttribute('data-value') || 'all') === value));
      if (state.searchField !== value) { state.searchField = value; loadList(); }
    }
    return;
  }
  if (!event.target.closest('.jm-dd')) closeJmCategoryDropdown();
});
document.addEventListener('keydown', event => { if (event.key === 'Escape') closeJmCategoryDropdown(); });

function toggleListFieldDropdown(event) {
  event.stopPropagation();
  const dd = $('listFieldDd');
  if (!dd) return;
  const wasOpen = dd.classList.contains('open');
  closeJmCategoryDropdown();
  if (!wasOpen) {
    dd.classList.add('open');
    dd.querySelector('.jm-dd-trigger')?.setAttribute('aria-expanded', 'true');
    dd.closest('.list-hero-wrap')?.classList.add('filter-menu-open');
  }
}
function setListDue(value) {
  if (state.due === value) return;
  state.due = value;
  loadList();
}

function syncJudicialSelectionControls() {
  const selected = new Set(state.judicialMessages.selectedIds || []);
  const pageIds = state.judicialMessages.items.map(item => Number(item.id));
  const count = $('jmBulkSelectedCount');
  if (count) count.textContent = `已选择 ${selected.size} 条`;
  const selectAll = $('jmSelectAllMessages');
  if (selectAll) {
    const selectedOnPage = pageIds.filter(id => selected.has(id)).length;
    selectAll.checked = pageIds.length > 0 && selectedOnPage === pageIds.length;
    selectAll.indeterminate = selectedOnPage > 0 && selectedOnPage < pageIds.length;
  }
  document.querySelectorAll('[data-jm-bulk-action]').forEach(button => { button.disabled = selected.size === 0; });
  const bulkFloat = $('jmBulkFloat');
  if (bulkFloat) bulkFloat.classList.toggle('is-visible', selected.size > 0);
}

function toggleJudicialSelection(messageId, checked, checkbox = null) {
  const selected = new Set(state.judicialMessages.selectedIds || []);
  if (checked) selected.add(Number(messageId)); else selected.delete(Number(messageId));
  state.judicialMessages.selectedIds = [...selected];
  checkbox?.closest('.jm-card')?.classList.toggle('selected', checked);
  syncJudicialSelectionControls();
}

function toggleJudicialPageSelection(checked) {
  const jm = state.judicialMessages;
  const selected = new Set(jm.selectedIds || []);
  jm.items.forEach(item => {
    if (checked) selected.add(Number(item.id)); else selected.delete(Number(item.id));
  });
  jm.selectedIds = [...selected];
  document.querySelectorAll('.jm-card-select').forEach(input => {
    input.checked = checked;
    input.closest('.jm-card')?.classList.toggle('selected', checked);
  });
  syncJudicialSelectionControls();
}

async function markJudicialMessagesRead(messageIds = [], allNew = false) {
  try {
    const result = await api(`${JM_API}/read-bulk`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message_ids:messageIds,all_new:allNew})});
    const ids = new Set((messageIds || []).map(Number));
    state.judicialMessages.items.forEach(item => { if (allNew || ids.has(Number(item.id))) item.is_new = 0; });
    if (state.judicialMessages.statusData) {
      state.judicialMessages.statusData.new_count = Math.max(0, Number(state.judicialMessages.statusData.new_count || 0) - Number(result.read_count || 0));
    }
    const badge = $('judicialMessageBadge');
    if (badge) badge.classList.toggle('has-new', Number(state.judicialMessages.statusData?.new_count || 0) > 0);
    if (allNew) {
      state.judicialMessages.newOnly = false;
      await loadJudicialMessages();
      toast(`已将 ${Number(result.read_count || 0)} 条新增短信标为已读`);
    } else if (activeTab === 'judicialMessages') {
      renderJudicialMessages(true);
    }
  } catch (e) { toast(e.message || '标记已读失败'); }
}

function setJudicialNewOnly(enabled) {
  const jm = state.judicialMessages;
  jm.newOnly = Boolean(enabled);
  jm.page = 1;
  jm.selectedIds = [];
  loadJudicialMessages();
}

async function bulkDeleteJudicialMessages(messageIds = null) {
  if (!requireOnlineAction()) return;
  const ids = messageIds || state.judicialMessages.selectedIds || [];
  if (!ids.length) return toast('请先选择需要删除的短信');
  if (!confirm(`确认从司法短信模块删除选中的 ${ids.length} 条短信？\n\n删除后无法撤销。这里只会清除本模块中的短信正文与分析数据，不会删除 Mac/iCloud“信息”中的原短信，也不会删除已经写入的开庭、待办、台账或备忘录。系统仍会保留不可逆去重指纹，防止同一条短信被重新导入。`)) return;
  try {
    const result = await api(`${JM_API}/delete-bulk`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message_ids:ids})});
    state.judicialMessages.selectedIds = [];
    closeEditor();
    const linked = Number(result.linked_count || 0);
    toast(`已删除 ${Number(result.deleted_count || 0)} 条短信${linked ? `；${linked} 条的案件记录已安全保留` : ''}`);
    await loadJudicialMessages();
    await loadDashboard();
  } catch (e) { toast(e.message || '批量删除失败'); }
}

async function bulkIgnoreJudicialMessages() {
  if (!requireOnlineAction()) return;
  const ids = state.judicialMessages.selectedIds || [];
  if (!ids.length) return toast('请先选择需要忽略的短信');
  if (!confirm(`确认忽略选中的 ${ids.length} 条短信？\n\n仅忽略这些短信，不会屏蔽相关案件、案号或发件人，也不会影响此后收到的新短信。原文将立即清除，仅保留不可逆去重指纹。`)) return;
  try {
    const result = await api(`${JM_API}/ignore-bulk`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message_ids:ids})});
    state.judicialMessages.selectedIds = [];
    toast(`已忽略 ${Number(result.ignored_count || 0)} 条短信；不影响后续新短信`);
    await loadJudicialMessages();
    await loadDashboard();
  } catch (e) { toast(e.message || '批量处理失败'); }
}

function judicialHealthHtml() {
  const health = state.judicialMessages.statusData;
  if (!health) return `<div class="jm-status-strip"><div class="jm-status-item error"><i class="jm-dot"></i><span class="jm-status-label">运行状态</span><strong>${state.offlineMode ? '离线模式不可读取短信' : '正在检查…'}</strong></div></div>`;
  const permissionText = health.permission_granted ? '已获读取权限' : '需要完全磁盘访问权限';
  const syncText = health.source_stale ? '数据库超过24小时未更新' : (health.database_mtime ? `更新于 ${fmt(health.database_mtime)}` : '尚无更新时间');
  const scanText = health.settings?.last_success_at ? fmt(health.settings.last_success_at) : (health.settings?.last_error ? '最近扫描失败' : '尚未成功扫描');
  const aiText = health.settings?.ai_enabled ? (health.ai_ready ? `已就绪 · ${health.settings.ai_model}` : '已启用但模型密钥不可用') : '已关闭';
  const item = (label, value, tone, title = '') => `<div class="jm-status-item ${tone}"${title ? ` title="${esc(title)}"` : ''}><i class="jm-dot"></i><span class="jm-status-label">${esc(label)}</span><strong>${esc(value)}</strong></div>`;
  return `<div class="jm-status-strip">
    ${item('数据库权限', permissionText, health.permission_granted ? 'ok' : 'error')}
    <i class="jm-status-sep"></i>
    ${item('Mac 同步', syncText, health.source_stale ? 'warn' : 'ok')}
    <i class="jm-status-sep"></i>
    ${item('最近扫描', scanText, health.settings?.last_error ? 'error' : 'ok', health.settings?.last_error || '')}
    <i class="jm-status-sep"></i>
    ${item('智能分析', aiText, health.settings?.ai_enabled && !health.ai_ready ? 'warn' : 'ok')}
  </div>`;
}

function renderJudicialMessages(preserveScroll = false) {
  const content = $('content');
  if (!content) return;
  const previousScrollTop = preserveScroll ? Number(content.querySelector('.jm-list')?.scrollTop || 0) : 0;
  const jm = state.judicialMessages;
  const counts = jm.statusData?.counts || {};
  const newCount = Number(jm.statusData?.new_count || 0);
  const statusTabs = ['', 'pending', 'suggested', 'confirmed', 'auto_written'].map(status => {
    const label = status ? JM_STATUS_LABELS[status] : '全部';
    const count = status ? Number(counts[status] || 0) : Object.values(counts).reduce((sum,value)=>sum+Number(value||0),0);
    return `<button class="jm-seg-item ${jm.status === status ? 'active' : ''}" role="tab" aria-selected="${jm.status === status}" onclick="setJudicialFilter('status','${status}')">${label}<em>${count}</em></button>`;
  }).join('');
  const categories = jm.categories || jm.statusData?.settings?.categories || [];
  const selectedIds = new Set(jm.selectedIds || []);
  const selectablePageIds = jm.items.map(item => Number(item.id));
  const allPageSelected = selectablePageIds.length > 0 && selectablePageIds.every(id => selectedIds.has(id));
  const cards = jm.items.length ? jm.items.map(item => {
    const action = item.workflow_status === 'auto_written'
      ? `<button class="btn" onclick="event.stopPropagation(); undoJudicialMessage(${item.id})">撤销自动写入</button>`
      : item.workflow_status === 'pending' || item.workflow_status === 'suggested'
        ? `<button class="btn primary" onclick="event.stopPropagation(); openJudicialMessage(${item.id})">确认关联</button><button class="btn" title="仅忽略本条，不影响后续短信" onclick="event.stopPropagation(); ignoreJudicialMessage(${item.id})">忽略本条</button>`
        : `<button class="btn" onclick="event.stopPropagation(); openJudicialMessage(${item.id})">查看</button>`;
    return `<article class="jm-card ${Number(item.is_new||0) ? 'is-new' : ''} ${selectedIds.has(Number(item.id)) ? 'selected' : ''}" onclick="openJudicialMessage(${item.id})">
      <div><div class="jm-card-head"><input class="jm-card-select" type="checkbox" aria-label="选择短信" ${selectedIds.has(Number(item.id))?'checked':''} onclick="event.stopPropagation()" onchange="toggleJudicialSelection(${item.id},this.checked,this)">${Number(item.is_new||0) ? '<span class="jm-new-badge">本次新增</span>' : ''}${judicialStatusBadge(item.workflow_status)}${item.category ? `<span class="tag">${esc(item.category)}</span>` : ''}<strong>${esc(item.institution || item.sender || '疑似司法机构')}</strong></div>
      <p class="jm-card-body">${linkifyJudicialMessageText(item.raw_body_preview || '正文已按隐私规则清除', item.raw_body || item.raw_body_preview || '')}</p>
      <div class="jm-card-meta"><span>收到：${esc(fmt(item.received_at))}</span><span>案号：${esc((JSON.parse(item.case_numbers_json || '[]')).join('、') || '未识别')}</span><span>关联：${esc(item.case_title || '待关联')}</span><span>类别/案件置信：${Number(item.category_confidence||0)}% / ${Number(item.case_confidence||0)}%</span></div></div>
      <div class="jm-actions">${action}</div>
    </article>`;
  }).join('') : `<div class="empty">当前筛选条件下没有司法短信</div>`;
  const totalPages = Math.max(1, Math.ceil(jm.total / jm.pageSize));
  const pagerHtml = totalPages > 1 ? `<div class="jm-pager"><button class="btn" ${jm.page<=1?'disabled':''} onclick="state.judicialMessages.page--;loadJudicialMessages()">上一页</button><span>第 ${jm.page}/${totalPages} 页 · 共 ${jm.total} 条</span><button class="btn" ${jm.page>=totalPages?'disabled':''} onclick="state.judicialMessages.page++;loadJudicialMessages()">下一页</button></div>` : '';
  content.innerHTML = `<section class="jm-page">
    <div class="jm-hero-wrap">
      <div class="jm-aurora" aria-hidden="true"><i></i><i></i><i></i></div>
      <header class="jm-hero">
        <div class="jm-hero-top">
          <div class="jm-hero-title"><h2>司法短信</h2><span class="jm-hero-total">共 ${jm.total} 条</span>${newCount ? `<span class="jm-hero-new">${newCount} 条新增</span>` : ''}</div>
          ${judicialHealthHtml()}
          <div class="jm-hero-actions">
            <button class="jm-ghost-btn" title="同步与权限诊断" onclick="openJudicialPermissionGuide()"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12h4l2.5-6.5 4.5 13L16.5 12H21"/></svg>权限诊断</button>
            <button class="jm-ghost-btn" title="司法短信设置" onclick="openJudicialSettings()"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h9M19 7h1M4 17h3M13 17h7"/><circle cx="16" cy="7" r="2.4"/><circle cx="10" cy="17" r="2.4"/></svg>设置</button>
            <button class="jm-scan-btn" onclick="scanJudicialMessages(this)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3.5l1.9 4.9 4.9 1.9-4.9 1.9L12 17l-1.9-4.8-4.9-1.9 4.9-1.9L12 3.5z"/><path d="M19.2 15.6l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8.8-2z"/></svg><span class="jm-scan-label">立即扫描</span></button>
          </div>
        </div>
        <div class="jm-filter-row">
          <div class="jm-seg" role="tablist">${statusTabs}</div>
          <label class="jm-search-field"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="6.4"/><path d="m20.3 20.3-3.9-3.9"/></svg><input placeholder="搜索正文、机构、案件或案号" value="${esc(jm.q)}" onkeydown="if(event.key==='Enter')setJudicialFilter('q',this.value)" onchange="setJudicialFilter('q',this.value)"></label>
          <div class="jm-dd" id="jmCategoryDd"><button type="button" class="jm-field jm-dd-trigger" onclick="toggleJmCategoryDropdown(event)" aria-haspopup="listbox" aria-expanded="false"><span class="jm-dd-label">${jm.category ? esc(jm.category) : '全部类别'}</span><i class="jm-dd-caret"></i></button><div class="jm-dd-menu" role="listbox" aria-label="按类别筛选"><button type="button" class="jm-dd-option${jm.category ? '' : ' active'}" data-value="">全部类别</button>${categories.map(value=>`<button type="button" class="jm-dd-option${jm.category===value?' active':''}" data-value="${esc(value)}">${esc(value)}</button>`).join('')}</div></div>
          <span class="jm-field"><input type="date" value="${esc(jm.dateFrom)}" title="开始日期" onchange="setJudicialFilter('dateFrom',this.value)"></span>
          <span class="jm-field"><input type="date" value="${esc(jm.dateTo)}" title="结束日期" onchange="setJudicialFilter('dateTo',this.value)"></span>
          ${selectablePageIds.length ? `<label class="jm-select-all"><input id="jmSelectAllMessages" type="checkbox" ${allPageSelected?'checked':''} onchange="toggleJudicialPageSelection(this.checked)">全选本页</label>` : ''}
        </div>
      </header>
      ${(newCount || jm.newOnly) ? `<div class="jm-new-banner"><div><strong>${newCount ? `有 ${newCount} 条新增司法短信` : '当前没有未读新增短信'}</strong><span>${jm.statusData?.latest_new_at ? `最近导入 ${esc(fmt(jm.statusData.latest_new_at))}` : ''}</span></div><div class="jm-new-banner-actions"><button class="btn ${jm.newOnly?'primary':''}" onclick="setJudicialNewOnly(${jm.newOnly?'false':'true'})">${jm.newOnly?'查看全部':'只看新增'}</button>${newCount?'<button class="btn" onclick="markJudicialMessagesRead([],true)">全部标为已读</button>':''}</div></div>` : ''}
    </div>
    <div class="jm-list-wrap">
      <div class="jm-list">${cards}${pagerHtml}</div>
      ${selectablePageIds.length ? `<div class="jm-bulk-float${selectedIds.size ? ' is-visible' : ''}" id="jmBulkFloat"><span class="jm-bulk-count" id="jmBulkSelectedCount">已选择 ${selectedIds.size} 条</span><button class="btn" data-jm-bulk-action title="仅忽略所选的待处理短信，不影响后续短信" ${selectedIds.size?'':'disabled'} onclick="bulkIgnoreJudicialMessages()">批量忽略</button><button class="btn danger" data-jm-bulk-action ${selectedIds.size?'':'disabled'} onclick="bulkDeleteJudicialMessages()">批量删除</button></div>` : ''}
    </div>
  </section>`;
  if (preserveScroll) {
    const list = content.querySelector('.jm-list');
    if (list) list.scrollTop = previousScrollTop;
  }
}

async function scanJudicialMessages(button) {
  if (!requireOnlineAction()) return;
  const label = button?.querySelector('.jm-scan-label');
  const old = label ? label.textContent : button?.textContent;
  if (button) {
    button.disabled = true;
    if (label) label.textContent = '扫描中…'; else button.textContent = '扫描中…';
  }
  try {
    const result = await api(`${JM_API}/scan`, { method:'POST' });
    const repaired = Number(result.repaired_count || 0);
    toast(`扫描完成：读取 ${result.scanned || 0} 条，新增 ${result.candidates || 0} 条${repaired ? `，补全 ${repaired} 条` : ''}，自动写入 ${result.auto_written || 0} 条`);
    await loadJudicialMessages();
    await loadDashboard();
  } catch (e) { toast(e.message || '扫描失败'); }
  finally {
    if (button) {
      button.disabled = false;
      if (label) label.textContent = old; else button.textContent = old || '立即扫描';
    }
  }
}

async function openJudicialMessage(messageId) {
  if (!requireOnlineAction()) return;
  try {
    const [item, caseData] = await Promise.all([api(`${JM_API}/${messageId}`), ApexCasePicker.load('', {request: api})]);
    state.judicialMessages.selected = item;
    let cases = ApexCasePicker.flatten(caseData);
    (item.candidate_cases || []).forEach(candidate => { if (!cases.some(row=>Number(row.id)===Number(candidate.id))) cases.push({id:candidate.id,title:candidate.title}); });
    state.judicialMessages.cases = cases;
    const extracted = item.extracted || {};
    const selectedCase = Number(item.matched_case_id || item.suggested_case_id || 0);
    const selectedDestinations = new Set(item.default_destinations || ['ledger']);
    const selectedCaseTitle = cases.find(row=>Number(row.id)===selectedCase)?.title || '';
    const categoryOptions = (state.judicialMessages.categories || []).map(value=>`<option value="${esc(value)}" ${value===item.category?'selected':''}>${esc(value)}</option>`).join('');
    const destinationHtml = Object.entries(JM_DEST_LABELS).map(([value,label])=>`<label><input type="checkbox" name="jmDestination" value="${value}" ${selectedDestinations.has(value)?'checked':''}> ${label}</label>`).join('');
    const links = (item.links || []).map(link=>`<span class="tag">${esc(JM_DEST_LABELS[link.target_type] || link.target_type)} #${Number(link.target_id)}</span>`).join(' ');
    const documentStatus = {discovered:'待下载',downloading:'下载中',needs_login:'需要页面操作',waiting_confirmation:'待确认案件',downloaded:'已下载',verified:'已校验',archived:'已归档',failed:'失败',cancelled:'已取消'};
    const documentRows = (item.documents || []).map(doc => {
      const isCourtDelivery = /zxfw\.court\.gov\.cn\/zxfw\/.*#\/pagesAjkj\/app\/wssd\/index/i.test(doc.source_url || '');
      const isGzacDelivery = ['gzac_delivery','gzac_delivery_item'].includes(doc.source_kind || '');
      const isEmbeddedVerification = /^https:\/\/sd\.gdems\.com\/v3\/dzsd\/[A-Za-z0-9_-]+\/?$/i.test(doc.source_url || '');
      const canDownload = ['discovered','failed','needs_login'].includes(doc.status) || ((isCourtDelivery || isGzacDelivery) && doc.status === 'archived' && ['url','gzac_delivery'].includes(doc.source_kind));
      const canArchive = ['waiting_confirmation','downloaded','verified'].includes(doc.status);
      const legacyBrowserError = /BrowserType\.|Target page, context or browser has been closed|Browser logs:/i.test(doc.last_error || '');
      const documentHint = legacyBrowserError
        ? '上次接管窗口未正常启动或已关闭，请点击“登录接管”重试。'
        : (doc.last_error || doc.relative_path || (isGzacDelivery ? '已识别广州仲裁委短信中的案件年份、编号与查询码；点击后将经官网验证并自动获取全部材料。' : ''));
      const takeoverLabel = /无需账号登录|短信验证码|手机号/.test(documentHint)
        ? '验证并下载'
        : (/页面内/.test(documentHint) ? '打开并下载' : '登录并下载');
      return `<tr><td>${esc(doc.original_filename || doc.source_url || '法院文书')}</td><td data-jm-download-status="${item.id}:${doc.id}">${esc(documentStatus[doc.status] || doc.status)}</td>
        <td>${esc(documentHint)}</td><td style="white-space:nowrap">
          ${canDownload?`<button class="btn" data-jm-download="${item.id}:${doc.id}" onclick="downloadJudicialDocument(${item.id},${doc.id})">${isCourtDelivery?(doc.status==='archived'?'补齐全部文书':'自动获取全部'):(isGzacDelivery?(doc.status==='failed'?'重试官网验证':'官网验证并获取全部'):(doc.status==='failed'?'重试':'下载'))}</button>`:''}
          ${doc.status==='needs_login'&&doc.source_kind==='url'&&!isCourtDelivery?`<button class="btn" onclick="${isEmbeddedVerification?'openJudicialVerification':'browserJudicialDocument'}(${item.id},${doc.id})">${isEmbeddedVerification?'在此验证并归档':takeoverLabel}</button>`:''}
          ${doc.status==='needs_login'?`<button class="btn" onclick="importJudicialDocument(${item.id},${doc.id})">手动导入</button>`:''}
          ${canArchive?`<button class="btn primary" onclick="archiveJudicialDocument(${item.id},${doc.id})">确认案件并归档</button>`:''}
          ${doc.status==='archived'?`<button class="btn" onclick="openJudicialDocument(${item.id},${doc.id})">打开文件</button>`:''}
        </td></tr>`;
    }).join('');
    $('drawerTitle').textContent = `司法短信 · ${item.status_label || ''}`;
    $('drawerBody').innerHTML = `<div class="jm-detail-view"><section class="detail-section jm-detail-section"><h3>原始短信</h3><div class="jm-section-content jm-source-content"><div class="jm-raw">${linkifyJudicialMessageText(item.raw_body || '正文已按隐私规则清除')}</div><div class="jm-meta-grid"><div class="jm-meta-item"><small>发件人</small><span>${esc(item.sender || '')}</span></div><div class="jm-meta-item"><small>接收时间</small><span>${esc(fmt(item.received_at))}</span></div><div class="jm-meta-item"><small>识别机构</small><span>${esc(item.institution || '')}</span></div><div class="jm-meta-item"><small>识别案号</small><span>${esc((item.case_numbers || []).join('、'))}</span></div><div class="jm-meta-item"><small>AI 模型</small><span>${esc(item.ai_model || '未使用/不可用')}</span></div><div class="jm-meta-item"><small>已写入</small><span>${links || '无'}</span></div>${item.analysis_error ? `<div class="jm-meta-item"><small>分析提示</small><span>${esc(item.analysis_error)}</span></div>` : ''}</div></div></section>
      <section class="detail-section jm-detail-section"><h3>送达文书</h3><div class="jm-section-content">
        <div id="jmDownloadProgress" hidden></div>
        ${documentRows?`<div class="mini-table-wrap jm-document-table"><table class="mini-table"><thead><tr><th>文件/来源</th><th>状态</th><th>提示/归档位置</th><th>操作</th></tr></thead><tbody>${documentRows}</tbody></table></div>`:'<p class="muted">这条短信中暂未发现文书链接或附件。</p>'}
        <p class="jm-help">已识别的广州仲裁委短信会自动提取年份、案件编号与查询码，经官网验证后下载全部材料。案件未确认或尚未绑定本地文件夹时，文件会保存在应用暂存区，绑定后点击“确认案件并归档”即可写入案件文件夹；正式归档时才按需创建 <code>#Stella电子送达归档</code>。</p>
      </div></section>
      <section class="detail-section jm-detail-section"><h3>${item.workflow_status === 'auto_written' ? '自动写入结果' : '确认分类与关联'}</h3><div class="jm-confirm-grid jm-section-content">
        <div class="full case-picker jm-case-picker"><label>关联案件</label><input type="hidden" id="jmCaseId" value="${selectedCase || ''}"><input class="input" id="jmCaseSearch" value="${esc(selectedCaseTitle)}" placeholder="输入案件名称、案号或当事人搜索" autocomplete="off" role="combobox" aria-autocomplete="list" aria-controls="jmCaseLookupResults"><div class="lookup-results" id="jmCaseLookupResults" role="listbox"></div><p class="jm-help">可按案件名称、案号、当事人、案由或系列子案信息搜索。</p></div>
        <div><label>事项类别</label><select id="jmCategory">${categoryOptions}</select></div>
        <div><label>案号</label><input class="input" id="jmCaseNo" value="${esc((item.case_numbers || [])[0] || '')}"></div>
        <div><label>事项类型</label><input class="input" id="jmEventType" value="${esc(extracted.event_type || item.category || '')}"></div>
        <div><label>时间/截止时间</label><input class="input" id="jmEventAt" type="datetime-local" value="${esc(String(extracted.event_at || '').replace(' ','T').slice(0,16))}"></div>
        <div class="full"><label>地点</label><input class="input" id="jmLocation" value="${esc(extracted.location || '')}"></div>
        <div class="full"><label>事项摘要</label><textarea id="jmSummary">${esc(extracted.summary || '')}</textarea></div>
        <div class="full"><label>写入目标（可多选）</label><div class="jm-destinations">${destinationHtml}</div><p class="jm-help">开庭记录会复用现有案件台账和日历同步。研究备忘录会单独创建，不覆盖案件基本信息中的备忘字段。</p></div>
      </div></section></div>`;
    const controls = item.workflow_status === 'auto_written'
      ? `<button class="btn" onclick="closeEditor()">关闭</button><button class="btn danger" onclick="bulkDeleteJudicialMessages([${item.id}])">删除短信</button><button class="btn danger" onclick="undoJudicialMessage(${item.id})">撤销自动写入</button>`
      : `<button class="btn" onclick="closeEditor()">关闭</button><button class="btn danger" onclick="bulkDeleteJudicialMessages([${item.id}])">删除短信</button>${['pending','suggested'].includes(item.workflow_status)?`<button class="btn" onclick="reanalyzeJudicialMessage(${item.id})">重新分析</button><button class="btn danger" title="仅忽略本条，不影响后续短信" onclick="ignoreJudicialMessage(${item.id})">忽略本条</button>`:''}<button class="btn primary" onclick="confirmJudicialMessage(${item.id})">${item.workflow_status==='confirmed'?'补充写入':'确认并写入'}</button>`;
    ApexCasePicker.attach({ input: $('jmCaseSearch'), menu: $('jmCaseLookupResults'), request: api, value: selectedCase,
      onInput: () => { $('jmCaseId').value = ''; },
      onSelect: selected => { $('jmCaseId').value = String(selected.id); $('jmCaseSearch').value = selected.title || ''; } });
    $('drawerFoot').innerHTML = controls;
    $('drawerMask').classList.add('show'); $('drawer').classList.add('show','detail-mode');
    renderJudicialDownloadProgress();
    resumeJudicialDownloadProgress();
    if (Number(item.is_new || 0)) markJudicialMessagesRead([item.id], false);
  } catch (e) { toast(e.message || '短信详情加载失败'); }
}

const judicialDownloads = new Map();

function judicialDownloadSize(bytes) {
  const value = Math.max(0, Number(bytes) || 0);
  return value < 1024 * 1024 ? `${(value / 1024).toFixed(1)} KB` : `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function judicialDownloadProgressHtml(progress) {
  const completed = Number(progress.completed_files) || 0;
  const failed = Number(progress.failed_files) || 0;
  const total = Number(progress.total_files) || 0;
  const received = Number(progress.received_bytes) || 0;
  const size = Number(progress.total_bytes) || 0;
  const running = progress.status === 'running';
  const known = total > 0 && size > 0;
  const fraction = Math.min(1, received / (size || 1));
  const percent = progress.status === 'completed' ? 100 : Math.min(99, Math.floor(100 * (completed + failed + fraction) / (total || 1)));
  const label = {completed:'文书获取完成', partial:'部分文书获取失败', failed:'文书获取失败', needs_action:'需要完成页面验证'}[progress.status]
    || {preparing:'正在读取文书清单…', downloading:'正在下载文书…', saving:'正在校验并保存…'}[progress.phase] || '正在获取文书…';
  const counts = total ? `已完成 ${completed} / ${total} 份${failed ? ` · 失败 ${failed} 份` : ''}` : '正在确认文件数量';
  const bytes = received || size ? `已下载 ${judicialDownloadSize(received)}${size ? ` / ${judicialDownloadSize(size)}` : ' · 文件总大小未知'}` : '';
  const indeterminate = running && !known;
  const valueText = indeterminate ? '文件总大小未知' : `${percent}%`;
  return `<div class="jm-download-progress ${indeterminate?'is-indeterminate':''} ${['failed','partial','needs_action'].includes(progress.status)?'has-error':''}">
    <div class="jm-download-head"><strong role="status">${esc(label)}</strong><span>${indeterminate?'下载中':valueText}</span></div>
    <div class="jm-download-track" role="progressbar" aria-label="文书获取进度" aria-valuemin="0" aria-valuemax="100" ${indeterminate?'':`aria-valuenow="${percent}"`} aria-valuetext="${esc(`${label}，${counts}，${bytes}`)}"><i style="width:${indeterminate?30:percent}%"></i></div>
    <div class="jm-download-meta"><span>${esc(counts)}</span><span>${esc(bytes)}</span></div>
    ${progress.filename?`<div class="jm-download-file">${esc(progress.filename)}</div>`:''}
    ${progress.error?`<div class="jm-download-error">${esc(progress.error)}</div>`:''}
  </div>`;
}

function renderJudicialDownloadProgress() {
  const host = $('jmDownloadProgress');
  if (!host) return;
  const messageId = Number(state.judicialMessages.selected?.id);
  const entries = [...judicialDownloads.values()].filter(entry=>entry.messageId === messageId);
  host.hidden = entries.length === 0;
  host.innerHTML = entries.map(entry=>judicialDownloadProgressHtml(entry.progress)).join('');
  document.querySelectorAll('[data-jm-download]').forEach(button => {
    const entry = judicialDownloads.get(button.dataset.jmDownload);
    button.disabled = Boolean(entry?.pending || entry?.progress.status === 'running');
    if (button.disabled) {
      button.textContent = '正在获取…';
      const status = document.querySelector(`[data-jm-download-status="${button.dataset.jmDownload}"]`);
      if (status) status.textContent = '下载中';
    }
  });
}

function judicialDownloadVisible(entry) {
  return !document.hidden && window.ApexLifecycle?.active !== false
    && Number(state.judicialMessages.selected?.id) === entry.messageId
    && $('drawer')?.classList.contains('show') && Boolean($('jmDownloadProgress'));
}

async function pollJudicialDownloadProgress(entry) {
  if (entry.polling || !entry.pending || !judicialDownloadVisible(entry)) return;
  entry.polling = true;
  try {
    const progress = await api(`${JM_API}/${entry.messageId}/documents/${entry.documentId}/download-progress`, {bypassOffline:true});
    if (entry.pending && progress.status !== 'idle') {
      entry.progress = progress;
      entry.connectionError = '';
    }
  } catch (_) {
    entry.connectionError = '进度暂时无法更新，正在重连…';
  } finally {
    entry.polling = false;
    if (judicialDownloadVisible(entry)) {
      renderJudicialDownloadProgress();
      if (entry.connectionError) {
        const host = $('jmDownloadProgress');
        const hint = document.createElement('div');
        hint.className = 'jm-download-error'; hint.textContent = entry.connectionError;
        host?.appendChild(hint);
      }
    }
    if (entry.pending && judicialDownloadVisible(entry)) {
      entry.timer = setTimeout(()=>{ entry.timer = null; pollJudicialDownloadProgress(entry); }, 600);
    }
  }
}

function resumeJudicialDownloadProgress() {
  judicialDownloads.forEach(entry => {
    if (!judicialDownloadVisible(entry)) { clearTimeout(entry.timer); entry.timer = null; }
    else if (entry.pending && !entry.timer) pollJudicialDownloadProgress(entry);
  });
}
document.addEventListener('visibilitychange', resumeJudicialDownloadProgress);
window.addEventListener('apex:page-visibility', resumeJudicialDownloadProgress);

async function downloadJudicialDocument(messageId, documentId) {
  const key = `${messageId}:${documentId}`;
  if (judicialDownloads.get(key)?.pending) return;
  while (judicialDownloads.size >= 64) {
    const oldest = [...judicialDownloads].find(([,entry])=>!entry.pending);
    if (!oldest) { toast('下载任务较多，请稍后重试'); return; }
    judicialDownloads.delete(oldest[0]);
  }
  const entry = {messageId:Number(messageId), documentId:Number(documentId), pending:true,
    progress:{status:'running', phase:'preparing'}, timer:null, polling:false};
  judicialDownloads.set(key, entry);
  renderJudicialDownloadProgress();
  $('jmDownloadProgress')?.scrollIntoView({block:'nearest'});
  // Start the request before polling, so a retry cannot display a prior result.
  const request = api(`${JM_API}/${messageId}/documents/${documentId}/download`, {method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  entry.timer = setTimeout(()=>{ entry.timer = null; pollJudicialDownloadProgress(entry); }, 200);
  try {
    const result = await request;
    entry.progress = result.progress || {status:'completed', total_files:1, completed_files:1};
    toast(entry.progress.status === 'partial' ? '部分文书获取失败，请查看进度与文件状态'
      : entry.progress.status === 'needs_action' ? (result.document.last_error || '请完成页面验证')
      : '文书已获取；请查看文件归档状态');
  } catch (e) {
    entry.progress = {...entry.progress, status:'failed', error:e.message || '文书下载失败'};
    toast(entry.progress.error);
  } finally {
    entry.pending = false;
    clearTimeout(entry.timer); entry.timer = null;
    if (judicialDownloadVisible(entry)) {
      renderJudicialDownloadProgress();
      await openJudicialMessage(messageId);
    }
  }
}

async function browserJudicialDocument(messageId, documentId) {
  toast('正在打开送达页；如页面要求，请完成收件验证并点击文书下载');
  try {
    await api(`${JM_API}/${messageId}/documents/${documentId}/browser-download`, {method:'POST'});
    toast('页面中的文书已获取，请确认司法短信后归档');
  } catch (e) { toast(e.message || '浏览器接管未完成'); }
  await openJudicialMessage(messageId);
}

async function openJudicialVerification(messageId, documentId) {
  const caseId = Number($('jmCaseId')?.value || state.judicialMessages.selected?.matched_case_id || state.judicialMessages.selected?.suggested_case_id || 0);
  $('drawerTitle').textContent = '司法短信 · 收件验证';
  $('drawerBody').innerHTML = '<div class="empty">正在获取图形验证码…</div>';
  $('drawerFoot').innerHTML = `<button class="btn" onclick="openJudicialMessage(${messageId})">返回短信</button>`;
  try {
    const [data, settings] = await Promise.all([
      api(`${JM_API}/${messageId}/documents/${documentId}/verification/start`, {method:'POST'}),
      api(`${JM_API}/settings`),
    ]);
    const phones = settings.recipient_phones || [];
    const phoneOptions = phones.map(phone=>`<option value="${esc(phone)}">${esc(phone)}</option>`).join('');
    $('drawerBody').innerHTML = `<section class="detail-section jm-detail-section"><h3>电子送达收件验证</h3><div class="jm-section-content">
      <p class="jm-help">该平台无需账号登录，但法院要求核验收件手机号。手机号、图形码和短信码仅用于本次送达，不会保存。</p>
      <div class="jm-confirm-grid">
        <div class="full"><label>收件手机号</label><div class="jm-phone-row"><select id="jmDeliveryPhonePreset" onchange="$('jmDeliveryPhone').value=this.value"><option value="">选择预置手机号</option>${phoneOptions}</select><input class="input" id="jmDeliveryPhone" inputmode="numeric" autocomplete="tel" maxlength="11" value="${esc(phones[0]||'')}" placeholder="也可输入其他手机号"><button class="btn" onclick="saveJudicialRecipientPhone()">设为预置</button></div><p class="jm-help">预置手机号同步用于所有需要收件验证的司法短信，可在“司法短信设置”统一增删。</p></div>
        <div><label>图形验证码</label><input class="input" id="jmDeliveryCaptcha" autocomplete="off" maxlength="8" placeholder="输入图片字符"></div>
        <div><label>验证码图片</label><div style="display:flex;align-items:center;gap:10px;min-height:42px"><img src="${data.captcha}" alt="图形验证码" style="max-width:150px;max-height:46px;border:1px solid var(--border);border-radius:6px"><button class="btn" onclick="openJudicialVerification(${messageId},${documentId})">换一张</button></div></div>
        <div class="full"><button class="btn" id="jmSendDeliveryCode" onclick="sendJudicialVerificationCode(${messageId},${documentId})">发送短信验证码</button></div>
        <div class="full"><label>短信验证码</label><input class="input" id="jmDeliverySmsCode" inputmode="numeric" autocomplete="one-time-code" maxlength="8" placeholder="请输入收到的短信验证码"></div>
      </div>
      <p class="jm-help" id="jmDeliveryVerificationHint">验证通过后，系统会继续下载全部文书；${caseId?'并直接归档到当前关联案件的本地绑定文件夹。':'请先返回短信选择关联案件，文书下载后将保存在暂存区。'}</p>
    </div></section>`;
    $('drawerFoot').innerHTML = `<button class="btn" onclick="openJudicialMessage(${messageId})">取消并返回</button><button class="btn primary" onclick="completeJudicialVerification(${messageId},${documentId},${caseId})">验证、下载并${caseId?'归档':'暂存'}</button>`;
  } catch (e) {
    $('drawerBody').innerHTML = `<div class="empty">${esc(e.message || '图形验证码获取失败')}</div>`;
  }
}

async function sendJudicialVerificationCode(messageId, documentId) {
  const button = $('jmSendDeliveryCode');
  const phone = ($('jmDeliveryPhone')?.value || '').replace(/\D/g,'');
  const captcha = ($('jmDeliveryCaptcha')?.value || '').trim();
  if (!/^1\d{10}$/.test(phone)) return toast('请输入正确的 11 位收件手机号');
  if (!captcha) return toast('请输入图形验证码');
  try {
    button.disabled = true;
    await api(`${JM_API}/${messageId}/documents/${documentId}/verification/send-code`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({phone,captcha})});
    toast('短信验证码已发送');
    let remain = 120;
    const timer = setInterval(() => {
      const current = $('jmSendDeliveryCode');
      if (!current) return clearInterval(timer);
      remain -= 1;
      current.textContent = remain > 0 ? `${remain} 秒后可重发` : '重新发送短信验证码';
      current.disabled = remain > 0;
      if (remain <= 0) clearInterval(timer);
    }, 1000);
  } catch (e) {
    button.disabled = false;
    toast(e.message || '验证码发送失败');
  }
}

async function saveJudicialRecipientPhone() {
  const phone = ($('jmDeliveryPhone')?.value || '').replace(/\D/g,'');
  if (!/^1\d{10}$/.test(phone)) return toast('请输入正确的 11 位手机号');
  try {
    const settings = await api(`${JM_API}/settings`);
    const recipient_phones = [...new Set([...(settings.recipient_phones||[]), phone])];
    await api(`${JM_API}/settings`, {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({...settings,recipient_phones})});
    const preset = $('jmDeliveryPhonePreset');
    if (preset && ![...preset.options].some(item=>item.value===phone)) preset.add(new Option(phone,phone));
    if (preset) preset.value=phone;
    toast('已加入全局预置收件手机号');
  } catch (e) { toast(e.message || '保存预置手机号失败'); }
}

async function completeJudicialVerification(messageId, documentId, caseId) {
  const code = ($('jmDeliverySmsCode')?.value || '').trim();
  if (!code) return toast('请输入短信验证码');
  const primary = $('drawerFoot')?.querySelector('.btn.primary');
  try {
    if (primary) { primary.disabled = true; primary.textContent = '正在验证并下载…'; }
    const result = await api(`${JM_API}/${messageId}/documents/${documentId}/verification/complete`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code,case_id:Number(caseId)||0})});
    toast(`已下载 ${Number(result.downloaded_count||0)} 份文书${result.archived?'并归档到案件文件夹':'到暂存区'}`);
    await openJudicialMessage(messageId);
  } catch (e) {
    const verified = /验证已通过/.test(e.message || '');
    if (primary) {
      primary.disabled = false;
      primary.textContent = verified ? '重试自动下载并归档' : `验证、下载并${caseId?'归档':'暂存'}`;
      if (verified) primary.setAttribute('onclick',`retryJudicialVerifiedDownload(${messageId},${documentId},${Number(caseId)||0})`);
    }
    toast(e.message || '验证或文书下载失败');
  }
}

async function retryJudicialVerifiedDownload(messageId, documentId, caseId) {
  const primary = $('drawerFoot')?.querySelector('.btn.primary');
  try {
    if (primary) { primary.disabled=true; primary.textContent='正在重试自动下载…'; }
    const result = await api(`${JM_API}/${messageId}/documents/${documentId}/verification/complete`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:'',case_id:Number(caseId)||0})});
    toast(`已下载 ${Number(result.downloaded_count||0)} 份文书并归档`);
    await openJudicialMessage(messageId);
  } catch(e) {
    if (primary) { primary.disabled=false; primary.textContent='重试自动下载并归档'; }
    toast(e.message||'重试下载失败');
  }
}

function importJudicialDocument(messageId, documentId) {
  const input = document.createElement('input');
  input.type='file'; input.accept='.pdf,.docx,.jpg,.jpeg,.png,.tif,.tiff';
  input.onchange = async () => {
    const file=input.files?.[0]; if(!file) return;
    const form=new FormData(); form.append('file',file);
    try {
      await api(`${JM_API}/${messageId}/documents/${documentId}/import`, {method:'POST',body:form});
      toast('文书已导入暂存区');
      await openJudicialMessage(messageId);
    } catch(e) { toast(e.message||'导入失败'); }
  };
  input.click();
}

async function archiveJudicialDocument(messageId, documentId) {
  const caseId=Number($('jmCaseId')?.value||0);
  if(!caseId) return toast('请先选择关联案件');
  try {
    await api(`${JM_API}/${messageId}/documents/${documentId}/archive`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({case_id:caseId})});
    toast('法院文书已归档');
    await openJudicialMessage(messageId);
  } catch(e) { toast(e.message||'归档失败'); }
}

async function openJudicialDocument(messageId, documentId) {
  try { await api(`${JM_API}/${messageId}/documents/${documentId}/open`, {method:'POST'}); }
  catch(e) { toast(e.message||'文件当前不可用'); }
}

async function confirmJudicialMessage(messageId) {
  const destinations = [...document.querySelectorAll('input[name="jmDestination"]:checked')].map(input=>input.value);
  const payload = {
    case_id:Number($('jmCaseId')?.value || 0), category:$('jmCategory')?.value || '', destinations,
    fields:{ case_no:$('jmCaseNo')?.value || '', event_type:$('jmEventType')?.value || '', event_at:$('jmEventAt')?.value || '', location:$('jmLocation')?.value || '', summary:$('jmSummary')?.value || '' }
  };
  if (!payload.case_id || !payload.category || !destinations.length) return toast('请选择案件、类别和至少一个写入目标');
  try {
    await api(`${JM_API}/${messageId}/confirm`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
    closeEditor(); toast('短信已确认，链接中的全部文书已自动下载并归档'); await loadJudicialMessages(); await loadDashboard();
  } catch (e) { toast(e.message || '确认失败'); }
}

async function reanalyzeJudicialMessage(messageId) {
  try { await api(`${JM_API}/${messageId}/reanalyze`, {method:'POST'}); toast('重新分析完成'); closeEditor(); await loadJudicialMessages(); await openJudicialMessage(messageId); }
  catch (e) { toast(e.message || '分析失败'); }
}

async function ignoreJudicialMessage(messageId) {
  if (!confirm('确认仅忽略本条短信？\n\n这不会屏蔽相关案件、案号或发件人，也不会影响此后收到的新短信。原文将立即清除，仅保留不可逆去重指纹。')) return;
  try { await api(`${JM_API}/${messageId}/ignore`, {method:'POST'}); closeEditor(); toast('已忽略本条短信；不影响后续新短信'); await loadJudicialMessages(); }
  catch (e) { toast(e.message || '操作失败'); }
}

async function undoJudicialMessage(messageId) {
  if (!confirm('确认撤销该短信自动创建的案件记录？已被人工修改的记录不会被撤销。')) return;
  try { await api(`${JM_API}/${messageId}/undo`, {method:'POST'}); closeEditor(); toast('自动写入已撤销'); await loadJudicialMessages(); await loadDashboard(); }
  catch (e) { toast(e.message || '无法撤销'); }
}

function openJudicialPermissionGuide() {
  const health = state.judicialMessages.statusData || {};
  $('drawerTitle').textContent = '短信同步与权限诊断';
  $('drawerBody').innerHTML = `<section class="detail-section"><h3>当前诊断</h3><dl class="record-fields"><dt>信息数据库</dt><dd>${health.database_exists?'已找到':'未找到'}</dd><dt>读取权限</dt><dd>${health.permission_granted?'已授权':'未授权'}</dd><dt>需要授权的程序</dt><dd><code>${esc(health.python_executable || '')}</code></dd><dt>最近错误</dt><dd>${esc(health.settings?.last_error || health.permission_error || '无')}</dd></dl></section>
    <section class="detail-section"><h3>1. 先修复 iPhone 手机号激活</h3><p class="jm-help">在 iPhone“设置 → App → 信息 → 发送与接收”中，必须能看到并勾选手机号。确认有效 SIM/eSIM、自动日期时间和短信收发正常；关闭 iMessage 与 FaceTime，重启 iPhone 后重新开启。运营商验证可能需要最长 24 小时。</p></section>
    <section class="detail-section"><h3>2. 恢复 Mac 信息同步</h3><p class="jm-help">手机号激活后，在 Mac“信息 → 设置 → iMessage”中勾选手机号和邮箱，保持“启用 iCloud 云端信息”，点击“现在同步”，直到主窗口不再显示“已暂停与 iCloud 同步”。</p></section>
    <section class="detail-section"><h3>3. 授予后台服务读取权限</h3><p class="jm-help">打开“系统设置 → 隐私与安全性 → 完全磁盘访问权限”，添加上方显示的 Python 程序并开启权限，然后重启案件服务。仅授权终端并不能让 LaunchAgent 自动获得权限。</p><button class="btn" onclick="navigator.clipboard?.writeText('${esc(health.python_executable || '')}');toast('路径已复制')">复制程序路径</button></section>`;
  $('drawerFoot').innerHTML = `<button class="btn" onclick="closeEditor()">关闭</button><button class="btn primary" onclick="closeEditor();scanJudicialMessages()">重新检测</button>`;
  $('drawerMask').classList.add('show'); $('drawer').classList.add('show','detail-mode');
}

async function openJudicialSettings() {
  try {
    const settings = await api(`${JM_API}/settings`); state.judicialMessages.settings = settings;
    const senderLines = (settings.trusted_senders || []).map(item=>`${item.sender} | ${item.institution || ''} | ${item.verified ? '是' : '否'}`).join('\n');
    const recipientPhoneLines = (settings.recipient_phones || []).join('\n');
    $('drawerTitle').textContent = '司法短信设置';
    $('drawerBody').innerHTML = `<div class="jm-confirm-grid">
      <div><label>启用定时读取</label><select id="jmEnabled"><option value="1" ${settings.enabled?'selected':''}>启用</option><option value="0" ${!settings.enabled?'selected':''}>停用</option></select></div>
      <div><label>扫描间隔（分钟）</label><input class="input" id="jmInterval" type="number" min="1" max="60" value="${Math.round(Number(settings.poll_interval_seconds||300)/60)}"></div>
      <div><label>首次补扫天数</label><input class="input" id="jmBackfill" type="number" min="1" max="3650" value="${Number(settings.backfill_days||90)}"></div>
      <div><label>云端智能分析</label><select id="jmAiEnabled"><option value="1" ${settings.ai_enabled?'selected':''}>启用（仅候选短信）</option><option value="0" ${!settings.ai_enabled?'selected':''}>关闭</option></select></div>
      <div class="full"><label>AI 模型</label><select id="jmAiModel">${(settings.available_models||[]).map(model=>`<option value="${esc(model)}" ${model===settings.ai_model?'selected':''}>${esc(model)}</option>`).join('')}</select></div>
      <div class="full"><label>电子送达预置收件手机号（每行一个）</label><textarea id="jmRecipientPhones" placeholder="每行输入一个 11 位手机号">${esc(recipientPhoneLines)}</textarea><p class="jm-help">这些号码会同步出现在所有需要收件验证的司法短信中，可随时新增或删除。</p></div>
      <div class="full"><label>受信发件人（每行：发件人 | 机构 | 是否验证）</label><textarea class="jm-settings-senders" id="jmTrustedSenders">${esc(senderLines)}</textarea><p class="jm-help">只有“是否验证”为“是”、机构相符、案号唯一、规则与 AI 完全一致且时间明确时，才允许自动写入。12368 默认仅作为候选来源，不默认授予自动写入资格。</p></div>
    </div>`;
    $('drawerFoot').innerHTML = `<button class="btn" onclick="closeEditor()">取消</button><button class="btn primary" onclick="saveJudicialSettings()">保存设置</button>`;
    $('drawerMask').classList.add('show'); $('drawer').classList.add('show');
  } catch (e) { toast(e.message || '设置加载失败'); }
}

async function saveJudicialSettings() {
  const trusted_senders = ($('jmTrustedSenders')?.value || '').split(/\n/).map(line=>line.trim()).filter(Boolean).map(line=>{
    const [sender,institution,verified] = line.split('|').map(value=>value.trim());
    return { sender, institution, verified:/^(是|1|true|verified)$/i.test(verified || '') };
  });
  const recipient_phones = [...new Set(($('jmRecipientPhones')?.value || '').split(/\n/).map(value=>value.replace(/\D/g,'')).filter(Boolean))];
  const payload = { enabled:$('jmEnabled').value==='1', poll_interval_seconds:Math.max(1,Number($('jmInterval').value||5))*60, backfill_days:Number($('jmBackfill').value||90), ai_enabled:$('jmAiEnabled').value==='1', ai_model:$('jmAiModel').value, trusted_senders, recipient_phones };
  try { await api(`${JM_API}/settings`, {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}); closeEditor(); toast('司法短信设置已保存'); await loadJudicialMessages(); }
  catch (e) { toast(e.message || '保存失败'); }
}

window.addEventListener('online', recoverOnlineIfPossible);
// Safari 的 online/offline 只代表网络接口状态，不能证明 Tailscale 或桌面服务可达。
// 两种事件都通过真实会话探针复核，避免网络切换时错误覆盖可用的离线工作区。
window.addEventListener('offline', recoverOnlineIfPossible);
window.addEventListener('pageshow', recoverOnlineIfPossible);
window.addEventListener('focus', recoverOnlineIfPossible);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) recoverOnlineIfPossible();
});
(window.ApexLifecycle?.interval || window.setInterval)(() => {
  if (!document.hidden) recoverOnlineIfPossible();
}, 5000);
(window.ApexLifecycle?.interval || window.setInterval)(() => {
  if (!document.hidden && activeTab === 'judicialMessages' && !state.offlineMode) loadJudicialMessages(true);
}, 60000);
let lastMobileRecordLayout = isMobileCaseCardMode();
window.addEventListener('resize', () => {
  updateTopAdd();
  scheduleSeriesMobileLayoutSync();
  syncSeriesTableStickyOffset();
  const mobileLayout = isMobileCaseCardMode();
  if (mobileLayout !== lastMobileRecordLayout) {
    lastMobileRecordLayout = mobileLayout;
    renderTable();
  }
});
document.addEventListener('pointerdown', (event) => {
  if (!event.target.closest('#tabs, #mobileTabToggle')) closeMobileTabs();
  if (event.target.closest('.lookup-results, .lookup-cell, .lookup-field, .case-picker')) return;
  hideLookupResults();
});
document.addEventListener('click', event => {
  const field = event.target instanceof Element ? event.target.closest('[data-copy-field]') : null;
  if (!field || !$('drawerBody')?.contains(field)) return;
  if (field.matches('summary')) event.preventDefault();
  copyDetailField(field);
});
document.addEventListener('keydown', event => {
  if (event.key !== 'Enter' && event.key !== ' ') return;
  const field = event.target instanceof Element ? event.target.closest('[data-copy-field]') : null;
  if (!field || !$('drawerBody')?.contains(field)) return;
  event.preventDefault();
  copyDetailField(field);
});
window.addEventListener('scroll', () => {
  const box = $('floatingLookupResults');
  if (!box?.classList.contains('show') || !box._lookupInput) return;
  positionFloatingLookup(box._lookupInput, box);
}, true);

let initialWorkspaceRestoreStarted = false;

function showCaseDetailRestoreShell(caseId, seriesId = 0) {
  resetCaseResearchWorkspace();
  setSeriesChildDetailOverlay(Number(seriesId || 0) > 0);
  state.editing = {
    tab: 'cases', item: { id: Number(caseId || 0), title: '正在恢复案件详情…' }, mode: 'detail',
    inlineSection: '', isNew: false, caseNumbersExpanded: false,
    seriesDetailMappingSeriesId: Number(seriesId || 0),
  };
  $('drawerTitle').textContent = '正在恢复案件详情…';
  $('drawerBody').innerHTML = '<section class="detail-section"><h3>案件详情</h3><div class="empty">正在恢复刷新前打开的页面…</div></section>';
  $('drawerFoot').innerHTML = '<button class="btn" onclick="closeEditor()">关闭</button>';
  $('drawerMask').classList.add('show');
  $('drawer').classList.add('show', 'detail-mode');
  $('drawer').classList.remove('edit-wide');
}

async function refreshRestoredCaseDetail(snapshot) {
  const caseId = Number(snapshot?.id || 0);
  if (!caseId) return;
  try {
    const latest = await api(`/api/case-manager/cases?case_id=${caseId}`);
    if (!latest) throw new Error('案件不存在');
    const seriesId = Number(snapshot?.seriesId || latest.parent_series_id || 0);
    if (latest.case_kind === 'series_child' && seriesId) {
      const target = seriesResumeTargetFromHash();
      await openSeriesWorkspace(seriesId, target?.id === seriesId ? target.tab : 'children');
      const child = isOfflineReadonly()
        ? (state.seriesWorkspace?.children || []).find(item => Number(item.id) === caseId)
        : await api(`/api/case-manager/series/${seriesId}/children/${caseId}`);
      if (Number(state.editing?.item?.id || 0) === caseId && child) {
        openCaseDetailDrawer(applySeriesDetailMappings(child, state.seriesWorkspace), seriesId);
      }
      return;
    }
    if (Number(state.editing?.item?.id || 0) === caseId) openCaseDetailDrawer(latest);
  } catch (_) {
    // 网络暂不可用时保留已绘制的会话快照；离线初始化完成后会使用本地缓存。
  }
}

function beginInitialWorkspaceRestore() {
  const requestedCaseId = Number(initialPageParams.get('case_id') || 0);
  if (Number.isInteger(requestedCaseId) && requestedCaseId > 0) {
    showCaseDetailRestoreShell(requestedCaseId);
    void openDetail('cases', requestedCaseId).catch(error => {
      $('drawerBody').textContent = error.message || '无法读取该案件';
    });
    return true;
  }
  const snapshot = rememberedOpenCaseDetailState();
  const detailId = snapshot?.id || rememberedOpenCaseDetailId();
  const seriesTarget = seriesResumeTargetFromHash();
  const seriesId = Number(snapshot?.seriesId || (seriesTarget && detailId ? seriesTarget.id : 0));
  if (snapshot) {
    if (seriesId) showSeriesWorkspace();
    openCaseDetailDrawer(snapshot.item, seriesId);
    void refreshRestoredCaseDetail({ ...snapshot, seriesId });
    return true;
  }
  if (detailId) {
    if (seriesId) showSeriesWorkspace();
    showCaseDetailRestoreShell(detailId, seriesId);
    void refreshRestoredCaseDetail({ id: detailId, seriesId });
    return true;
  }
  if (seriesTarget) {
    void resumeSeriesFromHash();
    return true;
  }
  return false;
}

async function boot() {
  rememberActiveTab(activeTab);
  syncActiveTabNav();
  notifyCaseManagerContext(currentCaseManagerPageLabel());
  updateTopAdd();
  updateMobileTabLabel();
  renderMobileFilters();
  // 必须在总览、列表和离线同步之前恢复详情；这些后台请求可能持续数秒。
  initialWorkspaceRestoreStarted = beginInitialWorkspaceRestore();
  const initialSessionProbe = readPwaSessionStatus(1500).catch(error => ({
    server_reachable: false,
    authenticated: false,
    shell_version: '',
    error_kind: error?.kind || 'offline',
  }));
  await initOfflineSupport();
  const quickStatus = await Promise.race([
    initialSessionProbe.then(status => ({ settled: true, status })),
    new Promise(resolve => setTimeout(() => resolve({ settled: false, status: null }), 100)),
  ]);
  if (state.offlineReady) {
    state.serverOnline = false;
    enterOfflineMode();
    await refreshAll(false);
    markCaseManagerInteractive('offline-cache');
    void resumeInitialWorkspace();
    initialSessionProbe.then(status => {
      if (status.server_reachable && !status.authenticated) return redirectToCaseManagerLogin();
      if (status.authenticated) void applyCaseServerConnection(true);
    });
    return;
  }

  if (!quickStatus.settled) {
    showNoOfflineSnapshot('当前未发现可用的本机缓存。正在继续检查桌面服务器…');
    initialSessionProbe.then(status => {
      if (status.server_reachable && !status.authenticated) return redirectToCaseManagerLogin();
      if (status.authenticated) void startOnlineCaseManager();
      else showNoOfflineSnapshot('请连接 Tailscale 并确认桌面端服务器正在运行。');
    });
    return;
  }

  const status = quickStatus.status;
  if (status.server_reachable && !status.authenticated) {
    redirectToCaseManagerLogin();
    return;
  }
  if (!status.authenticated) {
    showNoOfflineSnapshot('请连接 Tailscale 并确认桌面端服务器正在运行。');
    return;
  }
  await startOnlineCaseManager();
}

function showNoOfflineSnapshot(detail) {
  state.serverOnline = false;
  state.offlineMode = true;
  window.apexShowStartupState?.(
    '离线缓存尚未准备完成',
    detail || '请先联网打开一次案件管理，APEX 会自动保存可离线使用的数据。',
    true,
  );
  markCaseManagerInteractive('offline-no-cache');
}

function markCaseManagerInteractive(outcome) {
  if (window.__apexCaseManagerInteractive) return;
  window.__apexMarkCaseManagerInteractive?.(outcome);
  const events = Array.isArray(window.__apexStartupEvents) ? window.__apexStartupEvents : [];
  const elapsed = Number(events[events.length - 1]?.elapsed_ms || 0);
  fetch('/api/diagnostics/frontend', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      visible: document.visibilityState === 'visible',
      startupPage: 'case-manager',
      startupOutcome: String(outcome || 'unknown'),
      startupMs: elapsed,
      startupCacheReady: state.offlineReady,
    }),
    keepalive: true,
  }).catch(() => {});
}

async function startOnlineCaseManager() {
  noteCaseServerSuccess();
  try {
    await refreshAll(false);
    markCaseManagerInteractive('online');
    void resumeInitialWorkspace();
    // 同步队列和完整快照不再阻塞首屏；当前内容可操作后再在后台完成。
    void syncPendingCaseOps()
      .then(() => syncOfflineSnapshot(true))
      .catch(() => {});
  } catch (e) {
    if (e?.kind === 'unauthenticated') {
      redirectToCaseManagerLogin();
      return;
    }
    if (state.offlineReady) {
      state.offlineMode = true;
      updateOfflineStatus();
      await refreshAll(false);
      markCaseManagerInteractive('offline-fallback');
      void resumeInitialWorkspace();
    } else {
      showNoOfflineSnapshot(e?.kind === 'timeout'
        ? '桌面服务器响应超时，且本机尚无案件缓存。请检查连接后重试。'
        : '无法读取桌面服务器，且本机尚无案件缓存。请连接后重试。');
    }
  }
}

async function resumeInitialWorkspace() {
  if (initialWorkspaceRestoreStarted) return;
  // 系列案件使用 URL hash 恢复，优先级高于普通案件详情抽屉。
  if (seriesResumeTargetFromHash()) return resumeSeriesFromHash();
  const manager = rememberedOpenManager();
  if (manager) {
    // 委托人管理 / 对方管理在刷新后保持打开，并回到刷新前浏览的位置。
    try {
      if (manager.kind === 'client') await openClientManager(manager.selectedId || null);
      else await openOpponentManager(manager.selectedId || null);
      restoreManagerScroll(manager.kind, manager);
    } catch (_) {
      forgetOpenManager();
    }
    return;
  }
  const caseId = rememberedOpenCaseDetailId();
  if (!caseId) return;
  try {
    await openDetail('cases', caseId);
    if (Number(state.editing?.item?.id || 0) !== caseId) forgetOpenCaseDetail();
  } catch (_) {
    // 案件已删除或当前不可读取时，不应让后续刷新反复尝试恢复。
    forgetOpenCaseDetail();
  }
}

async function resumeSeriesFromHash() {
  const target = seriesResumeTargetFromHash();
  if (!target) return;
  try {
    await openSeriesWorkspace(target.id, target.tab);
  } catch (e) {
    clearSeriesHash();
  }
}
window.addEventListener('hashchange', () => {
  const target = seriesResumeTargetFromHash();
  if (!target) return;
  if (state.seriesWorkspace?.id === target.id) return;
  openSeriesWorkspace(target.id, target.tab);
});

// ── 智能立案（仅本地准备与官网辅助填写） ───────────────────────────────
const FILING_API = '/api/case-manager/filing-drafts';
async function loadFilingDrafts() {
  if (state.offlineMode) { state.filing.items = []; state.filing.current = null; renderFilingWorkspace(); return; }
  state.filing.loading = true;
  try {
    const data = await api(FILING_API);
    state.filing.items = data.items || [];
    const selectedId = Number(state.filing.current?.id || 0);
    const selected = state.filing.items.find(item => Number(item.id) === selectedId) || state.filing.items[0];
    if (selected) {
      state.filing.current = await api(`${FILING_API}/${Number(selected.id)}`);
      state.filing.validation = await api(`${FILING_API}/${Number(selected.id)}/validate`, { method:'POST' });
    } else { state.filing.current = null; state.filing.validation = null; }
  } catch (e) { toast(e.message || '预立案草稿加载失败'); }
  finally { state.filing.loading = false; if (activeTab === 'filing') renderFilingWorkspace(); }
}
async function selectFilingDraft(id) {
  try {
    state.filing.current = await api(`${FILING_API}/${Number(id)}`);
    state.filing.validation = await api(`${FILING_API}/${Number(id)}/validate`, { method:'POST' });
    renderFilingWorkspace();
  } catch (e) { toast(e.message || '草稿读取失败'); }
}
function filingValidationHtml(validation) {
  if (!validation) return '<div class="filing-alert warnings">正在检查材料与字段…</div>';
  const blockers = validation.blockers || [], warnings = validation.warnings || [];
  return `${blockers.length ? `<div class="filing-alert blockers"><strong>尚不能生成提交包</strong><br>${blockers.map(esc).join('；')}</div>` : '<div class="filing-alert warnings">校验通过。生成提交包后，材料版本将被锁定。</div>'}${warnings.length ? `<div class="filing-alert warnings">${warnings.map(esc).join('；')}</div>` : ''}`;
}
function renderFilingWorkspace() {
  const drafts = state.filing.items || [], current = state.filing.current;
  const list = drafts.length ? drafts.map(item => `<button class="filing-draft-row ${Number(item.id)===Number(current?.id)?'active':''}" type="button" onclick="selectFilingDraft(${Number(item.id)})"><strong>${esc(item.case_title || '未命名案件')}</strong><span>${esc(item.court_name || '未确认法院')} · ${esc(item.status_label || '')}${(item.blockers || []).length ? ` · 缺 ${item.blockers.length} 项` : ''}</span></button>`).join('') : '<div class="empty">暂无预立案草稿。请从案件详情的“智能立案”区创建。</div>';
  const detail = !current ? '<div class="filing-detail"><div class="filing-body"><h2>从本地案件开始</h2><p class="muted">创建草稿后，系统会集中核验立案要素与材料；通过一次总核对后再进入人民法院在线服务。</p></div></div>' : filingDetailHtml(current, state.filing.validation);
  $('content').innerHTML = `<div class="toolbar"><div class="filters"><strong>智能立案</strong><span class="muted">民商事一审 · 专业快通道 · 最终提交须律师在官网确认</span></div><div class="jm-actions"><button class="btn" type="button" onclick="loadFilingDrafts()">刷新状态</button></div></div><div class="filing-workspace"><aside class="filing-draft-list">${list}</aside>${detail}</div>`;
}
function filingDetailHtml(draft, validation) {
  const materials = (draft.materials || []).map(item => `<div class="filing-material"><div><strong>${esc(item.label || '材料')}</strong>${item.filename ? `<small>${esc(item.filename)}</small>` : '<small>尚未关联案件文件</small>'}</div><span class="filing-status">${item.exists ? (item.locked ? '已锁定' : '可读取') : '待补充'}</span></div>`).join('') || '<div class="muted">暂无材料</div>';
  const logs = (draft.logs || []).slice(0, 5).map(log => `<li>${esc(fmt(log.created_at) || '')}　${esc(log.summary || log.action)}</li>`).join('') || '<li>暂无操作记录</li>';
  const isReady = draft.status === 'ready', isSubmitted = draft.status === 'submitted';
  const mode = draft.representation_mode || 'lawyer_agent';
  return `<section class="filing-detail"><div class="filing-head"><div><h2>${esc(draft.case_title || '预立案')}</h2><p>一次性总核对后再进入官网。验证码、身份验证、签名和最终提交均由律师完成。</p></div><span class="filing-status">${esc(draft.status_label || '')}</span></div><div class="filing-body">${filingValidationHtml(validation)}<div class="filing-grid"><label>受诉法院<input class="input" id="filingCourt" value="${esc(draft.court_name)}" placeholder="例如：广州市中级人民法院"></label><label>案由<input class="input" id="filingCause" value="${esc(draft.cause)}" placeholder="例如：买卖合同纠纷"></label><label>立案身份<select class="input" id="filingRepresentationMode"><option value="lawyer_agent" ${mode==='lawyer_agent'?'selected':''}>律师代理</option><option value="legal_representative" ${mode==='legal_representative'?'selected':''}>法定代表人出庭</option><option value="employee_agent" ${mode==='employee_agent'?'selected':''}>公司员工代理</option><option value="self" ${mode==='self'?'selected':''}>当事人自行立案</option></select></label><label>标的额<input class="input" id="filingAmount" value="${esc(draft.claim_amount)}" placeholder="非金钱给付可留空"></label><label class="filing-check"><input id="filingCourtConfirmed" type="checkbox" ${draft.court_confirmed?'checked':''}> 已核对管辖及受诉法院</label><label class="wide">诉讼请求<textarea class="input" id="filingRequest" placeholder="请粘贴经律师确认的诉讼请求">${esc(draft.lawsuit_request)}</textarea></label><label class="filing-check wide"><input id="filingAuthorityConfirmed" type="checkbox" ${draft.authority_confirmed?'checked':''}> 已核验本次立案身份、代理权限及对应材料</label></div><div class="filing-section"><h3>提交材料</h3>${materials}<p class="muted">按立案身份集中校验起诉状、证据目录及证据、主体材料、送达地址与代理材料；来源均为案件文件。生成提交包后将记录文件哈希和版本。</p></div><div class="filing-actions"><button class="btn" type="button" onclick="saveFilingDraft()">保存并校验</button><button class="btn" type="button" onclick="refreshFilingMaterials()">刷新案件文件</button><button class="btn primary" type="button" onclick="packageFilingDraft()" ${validation?.blockers?.length ? 'disabled' : ''}>锁定提交包</button><button class="btn" type="button" onclick="openOfficialFiling()" ${isReady || isSubmitted ? '' : 'disabled'}>进入官网立案</button>${isReady ? '<button class="btn primary" type="button" onclick="markFilingSubmitted()">已在官网提交</button>' : ''}${draft.status==='supplement' || draft.status==='failed' ? '<button class="btn" type="button" onclick="reopenFilingDraft()">按补正重新准备</button>' : ''}</div><div class="filing-section"><h3>操作留痕</h3><ul class="muted">${logs}</ul></div></div></section>`;
}
function filingDraftBody() {
  return { court_name:$('filingCourt')?.value || '', cause:$('filingCause')?.value || '', claim_amount:$('filingAmount')?.value || '', lawsuit_request:$('filingRequest')?.value || '', representation_mode:$('filingRepresentationMode')?.value || 'lawyer_agent', court_confirmed:$('filingCourtConfirmed')?.checked || false, authority_confirmed:$('filingAuthorityConfirmed')?.checked || false };
}
async function saveFilingDraft() {
  const draft = state.filing.current; if (!draft) return;
  try { await api(`/api/case-manager/cases/${Number(draft.case_id)}/filing-draft`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(filingDraftBody())}); toast('已保存并重新校验'); await loadFilingDrafts(); } catch(e) { toast(e.message || '保存失败'); }
}
async function refreshFilingMaterials() { await saveFilingDraft(); }
async function packageFilingDraft() {
  const draft = state.filing.current; if (!draft) return;
  try { await saveFilingDraft(); const result = await api(`${FILING_API}/${Number(draft.id)}/package`, {method:'POST'}); toast(`已锁定 ${result.package.materials.length} 份提交材料`); await loadFilingDrafts(); } catch(e) { toast(e.message || '无法生成提交包'); }
}
function openOfficialFiling() {
  window.open('https://zxfw.court.gov.cn/zxfw/index.html', '_blank', 'noopener');
  toast('已打开官网。请按本页锁定清单完成填写、身份验证、材料复核与最终提交。');
}
async function markFilingSubmitted() {
  const draft = state.filing.current; if (!draft) return;
  if (!confirm('请确认：您已在人民法院在线服务官网完成最终提交。该操作只记录本地状态，不会向法院发送任何数据。')) return;
  const reference = window.prompt('可选：填写官网申请编号或备注，用于后续核对', '') || '';
  try { await api(`${FILING_API}/${Number(draft.id)}/mark-submitted`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reference})}); toast('已记录提交，后续审核意见将随一张网同步回写'); await loadFilingDrafts(); } catch(e) { toast(e.message || '状态记录失败'); }
}
async function reopenFilingDraft() { const draft = state.filing.current; if (!draft) return; try { await api(`${FILING_API}/${Number(draft.id)}/reopen`, {method:'POST'}); toast('材料已解锁，请补正后重新确认'); await loadFilingDrafts(); } catch(e) { toast(e.message || '无法重新准备'); } }
async function openFilingFromCase(caseId) {
  try { const draft = await api(`/api/case-manager/cases/${Number(caseId)}/filing-draft`, {method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}); state.filing.current = draft; state.filing.validation = null; switchTab('filing'); } catch(e) { toast(e.message || '无法创建预立案草稿'); }
}

// ── 人民法院在线服务 ──────────────────────────────────────────────────
const CO_API = '/api/case-manager/court-online';
function courtIsEntityKind() { return state.courtOnline.kind === 'cases' || state.courtOnline.kind === 'layy' || state.courtOnline.kind === 'hearings' || state.courtOnline.kind === 'readings'; }
let courtOnlineLoadSequence = 0;
async function loadCourtOnline() {
  const requestSequence = ++courtOnlineLoadSequence;
  const co = state.courtOnline;
  const searchInput = $('courtSearch');
  const restoreSearch = searchInput && document.activeElement === searchInput
    ? { start: searchInput.selectionStart, end: searchInput.selectionEnd } : null;
  const isEntityKind = courtIsEntityKind();
  const params = new URLSearchParams({ page: String(co.page), page_size: String(co.pageSize) });
  if (co.q) params.set('q', co.q);
  if (!isEntityKind) {
    if (co.kind) params.set('kind', co.kind);
    if (co.unread) params.set('unread', 'true');
  }
  const adv = co.advSearch || {};
  if (adv.case_no) params.set('case_no', adv.case_no);
  if (adv.court) params.set('court', adv.court);
  if (adv.party) params.set('party', adv.party);
  if (co.kind === 'cases' && co.caseAjlb) params.set('ajlb', co.caseAjlb);
  if (co.kind === 'layy' && co.layyAjlb) params.set('ajlb', co.layyAjlb);
  if (co.kind === 'readings' && co.readingStatus) params.set('status', co.readingStatus);
  if (co.kind === 'readings' && co.readingRefresh) { params.set('refresh','true'); co.readingRefresh=false; }
  const endpoint = isEntityKind ? `${CO_API}/${co.kind}` : `${CO_API}/records`;
  try {
    const recordsRequest = api(`${endpoint}?${params}`);
    // Fetch the unfiltered reading count on entry, without requiring its tab to open.
    // Reuse the list request when it already carries the complete total.
    const readingCountRequest = co.kind === 'readings' && !co.q && !co.readingStatus
      ? recordsRequest
      : api(`${CO_API}/readings?page_size=1`).catch(() => null);
    const [status, records, readingCounts] = await Promise.all([
      api(`${CO_API}/status`), recordsRequest, readingCountRequest,
    ]);
    if (requestSequence !== courtOnlineLoadSequence) return;
    co.status = status; co.items = records.items || []; co.total = Number(records.total || 0); co.readingWarning = records.warning || '';
    // 实体列表（案件、预约、开庭）不返回普通记录的 kind_counts；保留最近一次
    // 已知计数，避免切换标签时把待办、消息、电子送达误显示为 0。
    co.counts = { ...(co.counts || {}), ...(records.kind_counts || {}), ...(readingCounts ? {readings:Number(readingCounts.total || 0)} : {}) };
    courtUpdateStatusButton();
    const badge = $('courtOnlineBadge');
    if (badge) { badge.textContent = String(status.unread_count || 0); badge.classList.toggle('has-new', Number(status.unread_count || 0) > 0); }
    if (activeTab === 'courtOnline') {
      renderCourtOnline();
      courtUpdateStatusButton();
      courtObserveSync();
      if (restoreSearch) requestAnimationFrame(() => {
        const input = $('courtSearch'); if (!input) return;
        input.focus(); input.setSelectionRange(restoreSearch.start, restoreSearch.end);
      });
    }
  } catch (e) {
    if (requestSequence === courtOnlineLoadSequence && activeTab === 'courtOnline') {
      $('content').innerHTML = `<div class="empty">${esc(e.message || '一张网加载失败')}</div>`;
    }
  }
}
// 一张网子标签页配置：未来新增类型只需在此追加并保持后端 ALLOWED_KINDS 一致。
const courtKindTabs = [
  { value: '', label: '全部' },
  { value: 'todo', label: '待办' },
  { value: 'message', label: '消息' },
  { value: 'delivery', label: '电子送达' },
  { value: 'cases', label: '我的案件' },
  { value: 'layy', label: '立案预约' },
  { value: 'hearings', label: '开庭扫描' },
  { value: 'readings', label: '在线阅卷' },
];
let courtCaseDetailId = 0;
function openCourtCaseDetail(id) {
  const old = $('courtCaseDetailModal'); if (old) old.remove();
  const modal = document.createElement('div');
  modal.className = 'court-link-modal';
  modal.id = 'courtCaseDetailModal';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-label', '官网案件详情');
  modal.innerHTML = `<section class="court-link-dialog court-case-detail-dialog">
    <div class="court-link-head">
      <div><strong>官网案件详情</strong><span>数据来源：人民法院在线服务 · “我的案件”</span></div>
      <button class="btn" type="button" onclick="closeCourtCaseDetail()">关闭</button>
    </div>
    <div class="court-dialog-body court-case-detail-body" id="courtCaseDetailBody"><div class="court-link-empty">正在加载详情…</div></div>
    <div class="court-dialog-foot">
      <span class="court-foot-hint">单击字段可复制 · 信息以人民法院在线服务官网为准</span>
      <button class="btn" type="button" id="courtCaseDetailLocalBtn" onclick="courtCaseDetailOpenLocal()" hidden>打开本地案件</button>
      <button class="btn primary" type="button" id="courtCaseDetailLinkBtn" onclick="courtCaseDetailLink()">关联案件</button>
    </div>
  </section>`;
  document.body.appendChild(modal);
  revealCourtModal();
  renderCourtCaseDetail(Number(id));
}
async function renderCourtCaseDetail(id) {
  courtCaseDetailId = Number(id);
  const body = $('courtCaseDetailBody'); if (!body) return;
  try {
    const d = await api(`${CO_API}/cases/${courtCaseDetailId}/detail`);
    if (courtCaseDetailId !== Number(d.id || 0) || !$('courtCaseDetailBody')) return;
    body.innerHTML = courtCaseDetailHtml(d);
    makeDetailFieldsCopyable(body);
    const linked = Number(d.linked_case_id || 0);
    const localBtn = $('courtCaseDetailLocalBtn');
    if (localBtn) { localBtn.hidden = !linked; localBtn.dataset.caseId = String(linked); }
    const linkBtn = $('courtCaseDetailLinkBtn');
    if (linkBtn) { linkBtn.textContent = linked ? '重新关联' : '关联案件'; linkBtn.dataset.linkedCaseId = String(linked); }
  } catch (e) {
    body.innerHTML = `<div class="court-link-empty">${esc(e.message || '详情读取失败')}</div>`;
  }
}
function courtCaseDetailHtml(d) {
  const caseRows = [
    ['案件编号', d.case_identifier],
    ['案件标识', d.case_mark],
    ['案件类别', d.case_category],
    ['业务类型', d.business_type],
    ['审理程序', d.procedure],
    ['原审案号', d.original_number],
    ['立案标的额', d.amount],
    ['开庭时间', d.hearing_at],
  ].filter(([, v]) => String(v || '').trim());
  const orgRows = [
    ['承办法院', d.current_court],
    ['移送法院', d.transfer_court],
    ['承办部门', d.department],
    ['承办法官', d.judge],
  ].filter(([, v]) => String(v || '').trim());
  const adjRows = [
    ['裁判方式', d.adjudication],
    ['立案日期', d.filing_date],
    ['结案日期', d.judgment_date],
    ['送达日期', d.served_date],
  ].filter(([, v]) => String(v || '').trim());
  const syncRows = [
    ['官网账号', d.account],
    ['官网记录时间', d.record_time],
    ['数据更新时间', d.update_date],
    ['首次同步', d.first_seen],
  ].filter(([, v]) => String(v || '').trim());
  const linked = Number(d.linked_case_id || 0);
  const linkedBanner = linked ? `<div class="court-linked-banner"><strong>已关联本地案件</strong><span>${esc(d.linked_case_title || '案件')}</span></div>` : '';
  const parties = String(d.parties || '').trim();
  const partyItems = parties ? parties.split(/[，,、;；\n]+/).map(s => s.trim()).filter(Boolean) : [];
  const partyHtml = partyItems.length ? `<section class="detail-section"><h3>当事人</h3><div class="court-party-list">${partyItems.map((p, i) => `<div class="court-party-item"><span class="court-party-index">${i + 1}</span><span>${esc(p)}</span></div>`).join('')}</div></section>` : '';
  const rawFields = d.raw_fields || [];
  const rawHtml = rawFields.length ? `<details class="court-raw-collapse"><summary><span>官网原始数据</span><span>${rawFields.length} 项</span></summary><div class="court-raw-grid">${rawFields.map(f => `<div class="court-raw-row"><dt>${esc(f.key)}</dt><dd>${esc(f.value)}</dd></div>`).join('')}</div></details>` : '';
  const main = [
    caseRows.length ? detailSection('案件信息', caseRows) : '',
    orgRows.length ? detailSection('审理组织', orgRows) : '',
    adjRows.length ? detailSection('审理与裁判', adjRows) : '',
  ].join('');
  const side = [
    linkedBanner,
    partyHtml,
    syncRows.length ? detailSection('同步信息', syncRows) : '',
  ].join('');
  const hero = `<div class="court-case-hero">
    <div class="court-case-hero-badges"><span class="court-kind-badge kind-cases">${esc(d.business_type || courtCaseAjlbLabel(d.ajlb))}</span>${courtStageBadge(d.stage)}</div>
    <div class="court-case-hero-title">${esc(d.case_name || '未命名案件')}</div>
    <div class="court-case-hero-number"><span class="court-hero-no">${esc(d.case_number || '—')}</span></div>
    ${d.cause ? `<div class="court-case-hero-cause"><span class="court-meta-label">案由</span><span>${esc(d.cause)}</span></div>` : ''}
  </div>`;
  return `${hero}<div class="court-case-detail-grid"><div class="court-case-detail-main">${main}</div><div class="court-case-detail-side">${side}</div></div>${rawHtml}`;
}
function courtCaseDetailLink() {
  const linked = Number($('courtCaseDetailLinkBtn')?.dataset?.linkedCaseId || 0);
  closeCourtCaseDetail();
  courtLinkCase(courtCaseDetailId, linked);
}
function courtCaseDetailOpenLocal() {
  const caseId = Number($('courtCaseDetailLocalBtn')?.dataset?.caseId || 0);
  if (!caseId) return;
  closeCourtCaseDetail();
  openDetail('cases', caseId);
}
function closeCourtCaseDetail() {
  const modal = $('courtCaseDetailModal');
  if (modal) modal.remove();
  courtCaseDetailId = 0;
}
let courtSyncState = null;
async function openCourtSyncPlan(caseId, courtRowId) {
  if (isOfflineReadonly() && Number(caseId)) {
    toast('同步一张网信息需要联网，请联网后重试');
    return;
  }
  const old = $('courtSyncModal'); if (old) old.remove();
  const modal = document.createElement('div');
  modal.className = 'court-link-modal';
  modal.id = 'courtSyncModal';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-label', '同步一张网信息到案件');
  modal.innerHTML = `<section class="court-link-dialog court-sync-dialog">
    <div class="court-link-head">
      <div><strong>同步一张网信息到案件</strong><span>智能检测官网案件信息，勾选后写入本地案件对应字段，请确认后再执行</span></div>
      <button class="btn" type="button" onclick="closeCourtSyncPlan()">关闭</button>
    </div>
    <div class="court-dialog-body court-sync-body" id="courtSyncBody"><div class="court-link-empty">正在智能检测可同步字段…</div></div>
    <div class="court-dialog-foot">
      <span class="court-foot-hint">信息以人民法院在线服务官网为准，确认后写入案件对应字段</span>
      <button class="btn" type="button" onclick="toggleCourtSyncAll(true)">全选</button>
      <button class="btn" type="button" onclick="toggleCourtSyncAll(false)">全不选</button>
      <button class="btn primary" type="button" id="courtSyncConfirmBtn" onclick="confirmCourtSync()">确认同步</button>
    </div>
  </section>`;
  document.body.appendChild(modal);
  revealCourtModal();
  courtSyncState = { caseId: Number(caseId), courtRowId: Number(courtRowId), plan: null };
  try {
    const plan = await api(`${CO_API}/cases/${courtRowId}/sync-plan?case_id=${caseId}`, { bypassOffline: true });
    if (!modal.isConnected) return;
    courtSyncState.plan = plan;
    renderCourtSyncPlan(plan);
  } catch (e) {
    if (modal.isConnected) {
      const body = $('courtSyncBody');
      if (body) body.innerHTML = `<div class="court-link-empty">${esc(e.message || '智能检测失败')}</div>`;
      const btn = $('courtSyncConfirmBtn');
      if (btn) btn.disabled = true;
    }
  }
}
function courtSyncActionBadge(action) {
  return {
    new: '<span class="court-sync-badge new">新增</span>',
    overwrite: '<span class="court-sync-badge overwrite">覆盖</span>',
    append: '<span class="court-sync-badge append">追加</span>',
    same: '<span class="court-sync-badge same">已一致</span>',
  }[action] || '';
}
function courtSyncDisplayText(value) {
  const text = String(value || '').trim();
  if (!text) return '';
  return text.split(/\n+/).map(s => s.trim()).filter(Boolean).join(' / ');
}
function courtSyncCurValue(f) {
  const text = courtSyncDisplayText(f.current_value);
  if (!text) return '<span class="court-sync-empty">（空）</span>';
  const raw = String(f.current_value || '');
  const long = raw.length > 56 || raw.includes('\n');
  const title = long ? ` title="${esc(raw)}"` : '';
  return `<span${title} class="court-sync-val${long ? ' court-sync-clamp' : ''}">${esc(text)}</span>`;
}
function renderCourtSyncPlan(plan) {
  const body = $('courtSyncBody'); if (!body) return;
  const cc = plan.court_case || {};
  const target = plan.target || {};
  const fields = plan.fields || [];
  const selectable = fields.filter(f => f.action !== 'same');
  const cards = fields.map(f => {
    const same = f.action === 'same';
    const checked = !same;
    const srcText = courtSyncDisplayText(f.source_value);
    return `<label class="court-sync-card${same ? ' court-sync-card-same' : ''}">
      <span class="court-sync-checkbox">${same ? '' : `<input type="checkbox" data-court-sync-field="${esc(f.key)}" ${checked ? 'checked' : ''}>`}</span>
      <span class="court-sync-card-main">
        <span class="court-sync-card-head">
          <span class="court-sync-card-title">${esc(f.label)}</span>
          ${courtSyncActionBadge(f.action)}
        </span>
        <span class="court-sync-card-pos">写入：${esc(f.target_label || '案件信息')}</span>
        <span class="court-sync-card-row"><span class="court-sync-lbl">一张网</span><span class="court-sync-val">${esc(f.source_label || '')} ${esc(srcText)}</span></span>
        <span class="court-sync-card-row"><span class="court-sync-lbl">当前值</span>${courtSyncCurValue(f)}</span>
        ${f.reason ? `<span class="court-sync-reason">${esc(f.reason)}</span>` : ''}
      </span>
    </label>`;
  }).join('');
  const targetNote = target.create_new
    ? `<div class="court-sync-target-note">本地暂无匹配案号，将为官网案号 <strong>${esc(cc.case_number || '—')}</strong> 新建一条案号记录（性质：${esc(cc.instance_label || '一审')}）</div>`
    : `<div class="court-sync-target-note">同步到案号记录：<strong>${esc([target.number_type, target.case_no].filter(Boolean).join(' · ') || '本地案号')}</strong>${target.matched_case_no ? '' : `（未精确匹配案号，使用本地${esc(cc.instance_label || '')}案号记录）`}</div>`;
  const hero = `<div class="court-case-hero">
    <div class="court-case-hero-badges"><span class="court-kind-badge kind-cases">官网案件</span><span class="court-stage-badge stage-active">判定为${esc(cc.instance_label || '一审')}案件</span></div>
    <div class="court-case-hero-title">${esc(cc.case_name || '未命名案件')}</div>
    <div class="court-case-hero-number"><span class="court-hero-no">${esc(cc.case_number || '—')}</span>${cc.procedure ? `<span class="court-meta-label">审理程序：${esc(cc.procedure)}</span>` : ''}</div>
  </div>`;
  body.innerHTML = hero + targetNote +
    `<div class="court-sync-fields">${cards || '<div class="court-link-empty">无可同步字段</div>'}</div>
    <div class="court-sync-total">共检测到 ${fields.length} 个字段，其中 <strong>${selectable.length}</strong> 个可同步，勾选后请确认</div>`;
}
function toggleCourtSyncAll(checked) {
  document.querySelectorAll('#courtSyncBody [data-court-sync-field]').forEach(el => { el.checked = checked; });
}
async function confirmCourtSync() {
  if (!courtSyncState?.plan) return;
  const fields = [...document.querySelectorAll('#courtSyncBody [data-court-sync-field]:checked')].map(el => el.dataset.courtSyncField);
  if (!fields.length) return toast('请先勾选要同步的字段');
  if (!confirm(`确定将所选 ${fields.length} 个字段从一张网同步到本地案件？\n\n${fields.map(key => {
    const field = (courtSyncState.plan.fields || []).find(f => f.key === key);
    return field ? `${field.label}：${field.source_value}` : key;
  }).join('\n')}`)) return;
  const btn = $('courtSyncConfirmBtn');
  if (btn) { btn.disabled = true; btn.textContent = '正在同步…'; }
  try {
    const result = await api(`${CO_API}/cases/${courtSyncState.courtRowId}/sync`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ case_id: courtSyncState.caseId, fields })
    });
    const count = Number(result.synced?.length || 0);
    toast(count ? `已同步 ${count} 个字段到案件` : '没有字段需要同步');
    const caseId = courtSyncState.caseId;
    closeCourtSyncPlan();
    if (Number(caseId)) openDetail('cases', caseId);
  } catch (e) {
    toast(e.message || '同步失败');
    if (btn) { btn.disabled = false; btn.textContent = '确认同步'; }
  }
}
function closeCourtSyncPlan() {
  const modal = $('courtSyncModal');
  if (modal) modal.remove();
  courtSyncState = null;
}
function courtStageBadge(stage) {
  const text = String(stage || '').trim();
  let cls = 'stage-default', label = text || '—';
  if (text.includes('审理')) { cls = 'stage-active'; label = '审理中'; }
  else if (text.includes('结案')) { cls = 'stage-closed'; label = '已结案'; }
  else if (text.includes('归档')) { cls = 'stage-archived'; label = '已归档'; }
  else if (text.includes('立案')) { cls = 'stage-pending'; label = '立案阶段'; }
  return `<span class="court-stage-badge ${cls}">${esc(label)}</span>`;
}
function courtDetailRow(label, value) {
  const text = String(value || '').trim();
  if (!text) return '';
  return `<span><span class="court-meta-label">${esc(label)}</span><span title="${esc(text)}">${esc(text)}</span></span>`;
}
function courtCaseCard(item) {
  const linked = Number(item.linked_case_id || 0);
  const time = fmt(item.update_date || item.filing_date) || '—';
  const title = item.case_name || item.case_number || '未命名案件';
  const metaParts = [
    `<span class="court-meta-case">${esc(item.case_number || '—')}</span>`,
    item.court_name ? `<span>${esc(item.court_name)}</span>` : '',
    item.judge ? `<span>承办 ${esc(item.judge)}</span>` : '',
    courtStageBadge(item.stage),
  ].filter(Boolean);
  const detailParts = [courtDetailRow('案由', item.cause), courtDetailRow('当事人', item.parties)].join('');
  return `<article class="court-card court-card-clickable" onclick="openCourtCaseDetail(${Number(item.id)})" title="点击查看官网案件详情">
    <header class="court-card-head">
      <div class="court-card-title">
        <span class="court-kind-badge kind-cases">${esc(item.business_type || courtCaseAjlbLabel(item.ajlb))}</span>
        <strong title="${esc(title)}">${esc(title)}</strong>
      </div>
      <time class="court-card-time">${esc(time)}</time>
    </header>
    <div class="court-card-meta">${metaParts.join('<span class="court-meta-sep">·</span>')}</div>
    ${detailParts ? `<div class="court-card-detail">${detailParts}</div>` : ''}
    <div class="court-card-actions">${linked ? `<button class="court-action primary" onclick="event.stopPropagation();openDetail('cases', ${linked})">打开本地案件</button>` : ''}<button class="court-action ${linked ? '' : 'primary'}" onclick="event.stopPropagation();courtLinkCase(${Number(item.id)}, ${linked})">${linked ? '重新关联' : '关联案件'}</button></div>
  </article>`;
}
function courtHearingCardsHtml(items) {
  const cutoff = new Date();
  cutoff.setMonth(cutoff.getMonth() - 2);
  const recent = [];
  const old = [];
  for (const item of items || []) {
    const atDate = parseDateLoose(String(item.hearing_at || ''));
    (atDate && atDate < cutoff ? old : recent).push(item);
  }
  const recentHtml = recent.map(courtHearingCard).join('');
  if (!old.length) return recentHtml;
  return `${recentHtml}
    <details class="court-hearing-collapse">
      <summary>已过去 2 个月以上的开庭（${old.length} 条）<span class="court-hearing-collapse-caret" aria-hidden="true"></span></summary>
      <div class="court-hearing-collapse-body">${old.map(courtHearingCard).join('')}</div>
    </details>`;
}
const LAYY_STATUS_TEXT = {
  '11800007-1': '待提交',
  '11800007-2': '审查合格',
  '11800007-3': '审查不通过',
  '11800007-4': '已立案',
  '11800007-5': '待审核',
  '11800007-6': '退回补充材料',
  '11800007-31': '不予立案',
  '11800007-100': '待补充材料',
  '11800007-101': '提交失败',
  '11800007-255': '申请失效',
  '11800007-500': '已撤回',
};
function courtLayyStatusText(status) {
  const s = String(status || '').trim();
  if (!s) return '';
  return LAYY_STATUS_TEXT[s] || s;
}
function courtLayyStatusClass(status) {
  const t = courtLayyStatusText(status);
  if (/^审查合格|^审查通过|^已立案/.test(t)) return 'ok';
  if (/^审查不通过|^不予立案|^申请失效|^提交失败/.test(t)) return 'err';
  if (/^待提交|^待审核|^退回补充材料|^待补充材料/.test(t)) return 'pending';
  return '';
}
function courtLayyLatestAudit(item) {
  const audits = Array.isArray(item.audits) ? item.audits : [];
  return audits.length ? audits[audits.length - 1] : null;
}
function courtLayyReviewStatusText(item) {
  const latestAudit = courtLayyLatestAudit(item);
  if (latestAudit?.shjg_text || latestAudit?.shjg) return latestAudit.shjg_text || latestAudit.shjg;
  const processStatus = courtLayyStatusText(item.status);
  // “待提交”是官网申请流程码；只要已经有提交时间，它不能代表法院尚未收到材料。
  if (processStatus === '待提交' && item.submit_time) return '待法院审核';
  if (processStatus === '待审核') return '待法院审核';
  return processStatus || (item.submit_time ? '待法院审核' : '尚未提交');
}
function courtLayyDisplayTitle(item) {
  return item.case_name || item.cause || item.parties || '立案预约';
}
function courtLayyCard(item) {
  const linked = Number(item.linked_case_id || 0);
  const time = fmt(item.update_date || item.filed_date) || '—';
  const title = courtLayyDisplayTitle(item);
  const statusText = courtLayyReviewStatusText(item);
  const statusRaw = String(item.status || '').trim();
  const statusTitle = `法院审核状态：${statusText || '未知'}${statusRaw ? `；官网流程状态码 ${statusRaw}` : ''}`;
  const metaParts = [
    item.court_name ? `<span>${esc(item.court_name)}</span>` : '',
    item.case_type ? `<span>${esc(item.case_type)}</span>` : '',
    statusText ? `<span class="court-meta-status ${courtLayyStatusClass(item.status)}" title="${esc(statusTitle)}">${esc(statusText)}</span>` : '',
    item.review_comment ? `<span class="court-meta-review" title="审核意见：${esc(item.review_comment)}">${esc(item.review_comment)}</span>` : '',
  ].filter(Boolean);
  const detailParts = [courtDetailRow('当事人', item.parties), courtDetailRow('案由', item.cause), courtDetailRow('审核意见', item.review_comment)].join('');
  const cardTitle = ['法院审核状态：' + (statusText || '—'), item.review_comment ? '审核意见：' + item.review_comment : ''].filter(Boolean).join('；') || '立案预约';
  return `<article class="court-card court-card-clickable" onclick="openCourtLayyDetail(${Number(item.id)})" title="点击查看立案预约详情">
    <header class="court-card-head">
      <div class="court-card-title">
        <span class="court-kind-badge kind-layy">立案预约</span>
        <strong title="${esc(title)}">${esc(title)}</strong>
      </div>
      <time class="court-card-time">${esc(time)}</time>
    </header>
    <div class="court-card-meta">${metaParts.join('<span class="court-meta-sep">·</span>')}</div>
    ${detailParts ? `<div class="court-card-detail">${detailParts}</div>` : ''}
    <div class="court-card-actions">${linked ? `<button class="court-action primary" onclick="event.stopPropagation();openDetail('cases', ${linked})">打开本地案件</button>` : ''}<button class="court-action ${linked ? '' : 'primary'}" onclick="event.stopPropagation();courtLinkCase(${Number(item.id)}, ${linked})">${linked ? '重新关联' : '关联案件'}</button></div>
  </article>`;
}
let courtLayyDetailId = 0;
function openCourtLayyDetail(id) {
  const item = state.courtOnline.items.find(row => Number(row.id) === Number(id));
  if (!item) return;
  courtLayyDetailId = Number(id);
  const old = $('courtLayyDetailModal'); if (old) old.remove();
  const modal = document.createElement('div');
  modal.className = 'court-link-modal';
  modal.id = 'courtLayyDetailModal';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-label', '立案预约详情');
  modal.innerHTML = `<section class="court-link-dialog court-layy-detail-dialog">
    <div class="court-link-head">
      <div><strong>立案预约详情</strong><span>数据来源：人民法院在线服务 · “我的立案”</span></div>
      <button class="btn" type="button" onclick="closeCourtLayyDetail()">关闭</button>
    </div>
    <div class="court-dialog-body court-layy-detail-body" id="courtLayyDetailBody"></div>
    <div class="court-dialog-foot">
      <span class="court-foot-hint">单击字段可复制 · 信息以人民法院在线服务官网为准</span>
      <button class="btn" type="button" id="courtLayyDetailLocalBtn" onclick="courtLayyDetailOpenLocal()" hidden>打开本地案件</button>
      <button class="btn primary" type="button" id="courtLayyDetailLinkBtn" onclick="courtLayyDetailLink()">关联案件</button>
    </div>
  </section>`;
  document.body.appendChild(modal);
  revealCourtModal();
  const body = $('courtLayyDetailBody');
  if (body) { body.innerHTML = courtLayyDetailHtml(item); makeDetailFieldsCopyable(body); }
  const linked = Number(item.linked_case_id || 0);
  const localBtn = $('courtLayyDetailLocalBtn');
  if (localBtn) { localBtn.hidden = !linked; localBtn.dataset.caseId = String(linked); }
  const linkBtn = $('courtLayyDetailLinkBtn');
  if (linkBtn) { linkBtn.textContent = linked ? '重新关联' : '关联案件'; linkBtn.dataset.linkedCaseId = String(linked); }
}
function courtLayyDetailHtml(item) {
  const statusText = courtLayyReviewStatusText(item);
  const processStatusText = courtLayyStatusText(item.status);
  const statusRaw = String(item.status || '').trim();
  const statusLabel = statusText || '—';
  const processStatusLabel = statusRaw && processStatusText !== statusRaw ? `${processStatusText}（${statusRaw}）` : processStatusText || '—';
  const baseRows = [
    ['法院', item.court_name],
    ['案件类型', item.case_type],
    ['案由', item.cause],
    ['立案方式', item.filing_method ? (String(item.filing_method) === '2' ? '网上立案' : String(item.filing_method) === '1' ? '现场立案' : String(item.filing_method)) : ''],
    ['案号', item.case_number],
    ['申请标的额', item.claim_amount],
  ].filter(([, v]) => String(v || '').trim());
  const applyRows = [
    ['申请人', item.applicant],
    ['申请时间', item.apply_time || item.filed_date],
    ['提交时间', item.submit_time],
    ['承办人', item.judge],
    ['补充材料次数', item.material_count ? `${item.material_count} 次` : ''],
    ['补充材料时间', item.material_time],
    ['撤回时间', item.withdraw_time],
    ['数据更新时间', item.update_date],
  ].filter(([, v]) => String(v || '').trim());
  const syncRows = [
    ['法院审核状态', statusLabel],
    ['官网流程状态', processStatusLabel],
    ['首次同步', item.first_seen],
  ].filter(([, v]) => String(v || '').trim());
  const requestRows = [
    ['诉讼请求', item.lawsuit_request, true],
    ['审核意见', item.review_comment, true],
  ].filter(([, v]) => String(v || '').trim());
  const audits = item.audits || [];
  const auditHtml = audits.length ? `<section class="detail-section court-layy-audits"><h3>审核记录（${audits.length} 次）</h3>${audits.map(a => {
    const rows = [
      ['审核结果', [a.shjg_text, a.shjg && a.shjg_text !== a.shjg ? `（${a.shjg}）` : ''].filter(Boolean).join(' ') || '—'],
      ['审核人', a.reviewer],
      ['审核时间', a.review_time],
      ['备注期限', a.remark_term],
      ['驳回原因', a.reject_reason],
      ['审核意见', a.review_comment, true],
    ].filter(([, v]) => String(v || '').trim());
    return `<div class="court-layy-audit">${detailListHtml(rows)}</div>`;
  }).join('')}</section>` : '';
  const linked = Number(item.linked_case_id || 0);
  const linkedBanner = linked ? `<div class="court-linked-banner"><strong>已关联本地案件</strong><span>${esc(item.linked_case_title || '案件')}</span></div>` : '';
  const hero = `<div class="court-case-hero">
    <div class="court-case-hero-badges"><span class="court-kind-badge kind-layy">立案预约</span><span class="court-kind-badge kind-cases">${esc(courtCaseAjlbLabel(item.category))}</span><span class="court-meta-status ${courtLayyStatusClass(statusText)}" title="法院审核状态">${esc(statusText || '—')}</span></div>
    <div class="court-case-hero-title">${esc(courtLayyDisplayTitle(item))}</div>
    <div class="court-case-hero-cause"><span class="court-meta-label">当事人</span><span>${esc(item.parties || '—')}</span></div>
  </div>`;
  return `${hero}${linkedBanner}
    <div class="court-case-detail-grid"><div class="court-case-detail-main">
      ${baseRows.length ? detailSection('基本信息', baseRows) : ''}
      ${applyRows.length ? detailSection('申请与办理', applyRows) : ''}
      ${requestRows.length ? detailSection('申请内容', requestRows) : ''}
      ${auditHtml}
    </div><div class="court-case-detail-side">
      ${syncRows.length ? detailSection('同步信息', syncRows) : ''}
    </div></div>`;
}
function courtLayyDetailLink() {
  const linked = Number($('courtLayyDetailLinkBtn')?.dataset?.linkedCaseId || 0);
  closeCourtLayyDetail();
  courtLinkCase(courtLayyDetailId, linked);
}
function courtLayyDetailOpenLocal() {
  const caseId = Number($('courtLayyDetailLocalBtn')?.dataset?.caseId || 0);
  if (!caseId) return;
  closeCourtLayyDetail();
  openDetail('cases', caseId);
}
function closeCourtLayyDetail() {
  const modal = $('courtLayyDetailModal');
  if (modal) modal.remove();
  courtLayyDetailId = 0;
}
function courtHearingStampHtml(at) {
  const atDate = parseDateLoose(at);
  if (!atDate) return '<span class="court-hearing-stamp is-empty">—</span>';
  const now = new Date();
  const isToday = atDate.toDateString() === now.toDateString();
  const past = atDate < now;
  const weekday = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][atDate.getDay()];
  const dateLabel = isToday ? '今天' : `${atDate.getMonth() + 1}月${atDate.getDate()}日`;
  const clock = `${String(atDate.getHours()).padStart(2, '0')}:${String(atDate.getMinutes()).padStart(2, '0')}`;
  const cls = isToday ? 'is-today' : past ? 'is-past' : '';
  return `<time class="court-hearing-stamp ${cls}" datetime="${esc(at)}" title="开庭时间：${esc(fmt(at))}">
    <span class="court-hearing-stamp-date">${esc(dateLabel)} · ${esc(weekday)}</span>
    <span class="court-hearing-stamp-clock">${esc(clock)}</span>
  </time>`;
}
function courtHearingCard(item) {
  const linked = Number(item.linked_case_id || 0);
  const added = !!Number(item.added || 0);
  const at = String(item.hearing_at || '');
  const atDate = parseDateLoose(at);
  const past = !!atDate && atDate < new Date();
  const title = item.case_name || item.case_number || '开庭通知';
  const metaParts = [
    item.case_number ? `<span class="court-meta-case">${esc(item.case_number)}</span>` : '',
    item.court_name ? `<span>${esc(item.court_name)}</span>` : '',
    item.hearing_type ? `<span>${esc(item.hearing_type)}</span>` : '',
    linked ? `<span class="court-meta-linked">已关联：${esc(item.linked_case_title || '本地案件')}</span>` : '',
  ].filter(Boolean);
  const detailParts = [courtDetailRow('开庭地点', item.location), courtDetailRow('承办人', item.judge), courtDetailRow('状态', item.status)].join('');
  const actions = [
    `<button class="court-action" type="button" onclick="openCourtHearingDetail(${Number(item.id)})">查看详情</button>`,
    linked ? `<button class="court-action primary" type="button" onclick="event.stopPropagation();openDetail('cases', ${linked})">打开本地案件</button>` : '',
    `<button class="court-action ${linked ? '' : 'primary'}" type="button" onclick="event.stopPropagation();courtLinkCase(${Number(item.id)}, ${linked})">${linked ? '重新关联' : '关联案件'}</button>`,
    added
      ? `<button class="court-action court-action-added" type="button" onclick="event.stopPropagation();switchTab('hearings')">已添加到开庭提醒</button>`
      : `<button class="court-action" type="button" onclick="event.stopPropagation();courtAddHearingReminder(${Number(item.id)})">添加到开庭提醒</button>`,
  ].join('');
  return `<article class="court-card court-card-clickable court-hearing-card ${past ? 'is-past' : ''}" onclick="openCourtHearingDetail(${Number(item.id)})" title="点击查看开庭扫描详情">
    <header class="court-card-head">
      <div class="court-card-title">
        <span class="court-kind-badge kind-hearings">开庭扫描</span>
        <strong title="${esc(title)}">${esc(title)}</strong>
      </div>
      ${courtHearingStampHtml(at)}
    </header>
    ${metaParts.length ? `<div class="court-card-meta">${metaParts.join('<span class="court-meta-sep">·</span>')}</div>` : ''}
    <div class="court-card-detail court-hearing-detail">
      <div class="court-hearing-details">${detailParts}</div>
      <div class="court-card-actions court-hearing-actions">${actions}</div>
    </div>
  </article>`;
}
function courtCaseAjlbLabel(ajlb) {
  return ajlb === 'zx' ? '执行案件' : ajlb === 'pc' ? '破产案件' : '审判案件';
}
function courtCaseAjlbMenuHtml(co, status) {
  const items = [
    { value: 'sp', label: '审判案件', count: Number(status.case_trial_count || 0) },
    { value: 'zx', label: '执行案件', count: Number(status.execute_case_count || 0) },
    { value: 'pc', label: '破产案件', count: Number(status.bankruptcy_case_count || 0) },
  ];
  return items.map(item => `<button class="court-case-ajlb-item ${co.caseAjlb === item.value ? 'active' : ''}" type="button" data-ajlb="${item.value}" onclick="courtSelectCaseAjlb('${item.value}')"><span>${item.label}</span><b>${item.count}</b></button>`).join('');
}
function courtCaseAjlbTabHtml(co, status) {
  const menu = courtCaseAjlbMenuHtml(co, status);
  return `<span class="court-kind-tab-wrap"><button class="tab ${co.kind==='cases'?'active':''}" data-kind="cases" onclick="courtSelectKind('cases')">我的案件<span class="tab-count">${Number(status.case_count || 0)}</span></button><div class="court-kind-hover-menu" id="courtCaseAjlbMenu">${menu}</div></span>`;
}
function courtSelectCaseAjlb(ajlb) {
  state.courtOnline.caseAjlb = ajlb;
  state.courtOnline.kind = 'cases';
  state.courtOnline.page = 1;
  loadCourtOnline();
}
function courtLayyAjlbMenuHtml(co, status) {
  let sp = Number(status.layy_trial_count || 0);
  let zx = Number(status.layy_execute_count || 0);
  let pc = Number(status.layy_bankruptcy_count || 0);
  if (!sp && !zx && !pc && Array.isArray(co.items) && co.items.length) {
    co.items.forEach(i => {
      const c = i.category === 'zx' ? 'zx' : i.category === 'pc' ? 'pc' : 'sp';
      if (c === 'zx') zx += 1; else if (c === 'pc') pc += 1; else sp += 1;
    });
  }
  const items = [
    { value: 'sp', label: '审判案件', count: sp },
    { value: 'zx', label: '执行案件', count: zx },
    { value: 'pc', label: '破产案件', count: pc },
  ];
  return items.map(item => `<button class="court-case-ajlb-item ${co.layyAjlb === item.value ? 'active' : ''}" type="button" data-ajlb="${item.value}" onclick="courtSelectLayyAjlb('${item.value}')"><span>${item.label}</span><b>${item.count}</b></button>`).join('');
}
function courtLayyAjlbTabHtml(co, status) {
  const menu = courtLayyAjlbMenuHtml(co, status);
  return `<span class="court-kind-tab-wrap"><button class="tab ${co.kind==='layy'?'active':''}" data-kind="layy" onclick="courtSelectKind('layy')">立案预约<span class="tab-count">${Number(status.layy_count || 0)}</span></button><div class="court-kind-hover-menu" id="courtLayyAjlbMenu">${menu}</div></span>`;
}
function courtSyncBannerHtml(sync = state.courtOnline.sync) {
  if (!sync || sync.phase === 'idle') return '';
  const phase = sync.phase === 'running' ? 'running' : sync.phase === 'success' ? 'success' : 'error';
  const title = phase === 'running' ? '正在同步一张网' : phase === 'success' ? '同步完成' : '同步失败';
  return `<div class="court-sync-banner is-${phase}" role="status" aria-live="polite"><span class="court-sync-indicator"></span><div class="court-sync-copy"><strong>${title}</strong><span>${esc(sync.message || '')}</span></div><span class="court-sync-progress" aria-hidden="true"><i></i></span></div>`;
}
function courtUpdateSyncBanner() {
  const host = $('courtSyncBanner');
  if (host) host.innerHTML = courtSyncBannerHtml();
  const syncing = state.courtOnline.sync?.phase === 'running';
  document.querySelectorAll('[data-court-sync]').forEach(button => {
    button.disabled = syncing;
    button.setAttribute('aria-busy', syncing ? 'true' : 'false');
  });
}
function courtSetSyncFeedback(phase, message) {
  state.courtOnline.sync = { phase, message };
  courtUpdateSyncBanner();
}
function courtSelectLayyAjlb(ajlb) {
  state.courtOnline.layyAjlb = ajlb;
  state.courtOnline.kind = 'layy';
  state.courtOnline.page = 1;
  loadCourtOnline();
}
function courtRefreshZeroMenuCounts(wrap) {
  const menu = wrap && wrap.querySelector('.court-kind-hover-menu');
  if (!menu || state.offlineMode) return;
  const badges = menu.querySelectorAll('.court-case-ajlb-item b');
  if (!badges.length) return;
  const zero = Array.from(badges).every(b => b.textContent === '0');
  if (!zero) return;
  const st = state.courtOnline.status || {};
  if (!Number(st.layy_count) && !Number(st.case_count)) return;
  api(`${CO_API}/status`, { bypassOffline: true })
    .then(s => { state.courtOnline.status = s; if (activeTab === 'courtOnline') renderCourtOnline(); })
    .catch(() => {});
}
function bindCourtKindHoverMenus() {
  document.querySelectorAll('#courtKindTabs .court-kind-tab-wrap').forEach(wrap => {
    if (wrap.dataset.hoverBound) return;
    wrap.dataset.hoverBound = '1';
    const menu = wrap.querySelector('.court-kind-hover-menu');
    const tabs = wrap.closest('.court-kind-tabs');
    let timer = null;
    const show = () => {
      clearTimeout(timer);
      wrap.classList.add('menu-open');
      if (tabs) tabs.classList.add('menu-open');
      courtRefreshZeroMenuCounts(wrap);
    };
    const scheduleHide = () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        if (wrap.matches(':hover') || (menu && menu.matches(':hover'))) { show(); return; }
        wrap.classList.remove('menu-open');
        if (tabs) tabs.classList.remove('menu-open');
      }, 180);
    };
    wrap.addEventListener('mouseenter', show);
    wrap.addEventListener('mouseleave', scheduleHide);
    if (menu) {
      menu.addEventListener('mouseenter', show);
      menu.addEventListener('mouseleave', scheduleHide);
    }
    wrap.addEventListener('focusin', show);
    wrap.addEventListener('focusout', scheduleHide);
  });
}
let courtOnlineDetailState = null;
function courtRecordFileExt(file) {
  return (file.extension || String(file.filename || '').split('.').pop() || 'file').toLowerCase().slice(0, 5);
}
function courtRecordFilesHtml(attachments, linked = 0) {
  return (attachments || []).map(file => {
    const ext = esc(courtRecordFileExt(file));
    return `<span class="court-file">
    <span class="court-file-ext" data-ext="${ext}">${ext}</span>
    <button class="court-file-name" type="button" title="点击预览" onclick="event.stopPropagation();courtPreview(${Number(file.id)})">${esc(file.filename || '附件')}</button>
    <button class="court-file-btn" type="button" onclick="event.stopPropagation();courtDownload(${Number(file.id)})">下载</button>
    ${linked ? `<button class="court-file-btn" type="button" onclick="event.stopPropagation();courtArchive(${Number(file.id)},${Number(linked)})">归档</button>` : ''}
  </span>`;
  }).join('');
}
function courtRecordStatusHtml(item) {
  if (item.kind !== 'delivery') return item.unread ? '<span class="court-meta-pending">未读</span>' : '';
  if (item.delivery_status === '1') return '<span class="court-meta-pending">待签收</span>';
  if (item.delivery_status === '2') return '<span class="court-meta-done">已签收</span>';
  return '';
}
function openCourtRecordDetail(id) {
  const item = state.courtOnline.items.find(row => Number(row.id) === Number(id));
  if (!item) return;
  courtOnlineDetailState = { type: 'record', item };
  renderCourtOnlineDetail();
}
function openCourtHearingDetail(id) {
  const item = state.courtOnline.items.find(row => Number(row.id) === Number(id));
  if (!item) return;
  courtOnlineDetailState = { type: 'hearing', item };
  renderCourtOnlineDetail();
}
function closeCourtOnlineDetail() {
  $('courtOnlineDetailModal')?.remove();
  courtOnlineDetailState = null;
}
function courtOnlineDetailOpenLocal() {
  const linked = Number(courtOnlineDetailState?.item?.linked_case_id || 0);
  if (!linked) return;
  closeCourtOnlineDetail();
  openDetail('cases', linked);
}
function courtOnlineDetailLink() {
  const state = courtOnlineDetailState;
  if (!state) return;
  const linked = Number(state.item.linked_case_id || 0);
  const id = Number(state.item.id || 0);
  closeCourtOnlineDetail();
  courtLinkCase(id, linked);
}
function courtOnlineDetailMarkRead() {
  const id = Number(courtOnlineDetailState?.item?.id || 0);
  closeCourtOnlineDetail();
  if (id) courtMarkRead(id);
}
function courtRecordDetailHtml(item) {
  const kindName = { todo: '待办', message: '消息', delivery: '电子送达' }[item.kind] || '法院通知';
  const linked = Number(item.linked_case_id || 0);
  const attachments = item.attachments || [];
  const status = courtRecordStatusHtml(item);
  const infoRows = [
    ['案件', item.case_number || item.case_name],
    ['法院', item.court_name],
    ['送达状态', item.kind === 'delivery' ? (item.delivery_status === '1' ? '待签收' : item.delivery_status === '2' ? '已签收' : '') : ''],
    ['送达时间', fmt(item.published_at)],
    ['文书数量', attachments.length ? `${attachments.length} 份` : ''],
  ].filter(([, value]) => String(value || '').trim());
  const syncRows = [
    ['记录类型', kindName],
    ['最近更新', fmt(item.updated_at)],
    ['本地状态', item.unread ? '未读' : '已读'],
  ].filter(([, value]) => String(value || '').trim());
  const linkedBanner = linked ? `<div class="court-linked-banner"><strong>已关联本地案件</strong><span>${esc(item.linked_case_title || '案件')}</span></div>` : '';
  const body = String(item.content || '').trim();
  return `<div class="court-case-hero">
    <div class="court-case-hero-badges"><span class="court-kind-badge kind-${esc(item.kind || 'default')}">${esc(kindName)}</span>${status}</div>
    <div class="court-case-hero-title">${esc(item.title || kindName)}</div>
    <div class="court-case-hero-number"><span class="court-hero-no">${esc(item.case_number || item.case_name || '未标注案号')}</span></div>
    ${item.court_name ? `<div class="court-case-hero-cause"><span class="court-meta-label">受理法院</span><span>${esc(item.court_name)}</span></div>` : ''}
  </div>${linkedBanner}
  <div class="court-case-detail-grid"><div class="court-case-detail-main">
    <section class="detail-section"><h3>通知内容</h3><div class="court-record-detail-content">${esc(body || '本条记录未返回可展示的正文内容。')}</div></section>
    ${attachments.length ? `<section class="detail-section court-record-detail-files"><h3>附件（${attachments.length}）</h3><div class="court-card-files">${courtRecordFilesHtml(attachments, linked)}</div></section>` : ''}
  </div><div class="court-case-detail-side">
    ${infoRows.length ? detailSection('基本信息', infoRows) : ''}
    ${syncRows.length ? detailSection('同步信息', syncRows) : ''}
  </div></div>`;
}
function courtHearingDetailHtml(item) {
  const linked = Number(item.linked_case_id || 0);
  const infoRows = [
    ['案号', item.case_number], ['法院', item.court_name], ['开庭类型', item.hearing_type],
    ['开庭时间', fmt(item.hearing_at)], ['开庭地点', item.location], ['承办人', item.judge], ['状态', item.status],
  ].filter(([, value]) => String(value || '').trim());
  const syncRows = [['最近更新', fmt(item.updated_at)], ['本地开庭提醒', Number(item.added || 0) ? '已添加' : '未添加']]
    .filter(([, value]) => String(value || '').trim());
  const linkedBanner = linked ? `<div class="court-linked-banner"><strong>已关联本地案件</strong><span>${esc(item.linked_case_title || '案件')}</span></div>` : '';
  return `<div class="court-case-hero">
    <div class="court-case-hero-badges"><span class="court-kind-badge kind-hearings">开庭扫描</span></div>
    <div class="court-case-hero-title">${esc(item.case_name || item.case_number || '开庭通知')}</div>
    <div class="court-case-hero-number"><span class="court-hero-no">${esc(fmt(item.hearing_at) || '待补充开庭时间')}</span></div>
    ${item.location ? `<div class="court-case-hero-cause"><span class="court-meta-label">开庭地点</span><span>${esc(item.location)}</span></div>` : ''}
  </div>${linkedBanner}
  <div class="court-case-detail-grid"><div class="court-case-detail-main">${infoRows.length ? detailSection('开庭信息', infoRows) : ''}</div><div class="court-case-detail-side">${syncRows.length ? detailSection('同步信息', syncRows) : ''}</div></div>`;
}
function renderCourtOnlineDetail() {
  const state = courtOnlineDetailState;
  if (!state) return;
  const item = state.item;
  const isHearing = state.type === 'hearing';
  const linked = Number(item.linked_case_id || 0);
  const old = $('courtOnlineDetailModal'); if (old) old.remove();
  const modal = document.createElement('div');
  modal.className = 'court-link-modal'; modal.id = 'courtOnlineDetailModal';
  modal.setAttribute('role', 'dialog'); modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-label', isHearing ? '开庭扫描详情' : '法院记录详情');
  modal.innerHTML = `<section class="court-link-dialog court-case-detail-dialog court-record-detail-dialog">
    <div class="court-link-head"><div><strong>${isHearing ? '开庭扫描详情' : '法院记录详情'}</strong><span>数据来源：人民法院在线服务</span></div><button class="btn" type="button" onclick="closeCourtOnlineDetail()">关闭</button></div>
    <div class="court-dialog-body court-case-detail-body">${isHearing ? courtHearingDetailHtml(item) : courtRecordDetailHtml(item)}</div>
    <div class="court-dialog-foot"><span class="court-foot-hint">信息以人民法院在线服务官网为准</span>
      ${!isHearing && item.unread ? `<button class="btn" type="button" onclick="courtOnlineDetailMarkRead()">标为已读</button>` : ''}
      ${item.chat_available && !isHearing ? `<button class="btn" type="button" onclick="closeCourtOnlineDetail();courtLoadChat(${Number(item.id)})">查看私信</button>` : ''}
      ${linked ? `<button class="btn" type="button" onclick="courtOnlineDetailOpenLocal()">打开本地案件</button>` : ''}
      ${isHearing && !Number(item.added || 0) ? `<button class="btn" type="button" onclick="closeCourtOnlineDetail();courtAddHearingReminder(${Number(item.id)})">添加到开庭提醒</button>` : ''}
      <button class="btn primary" type="button" onclick="courtOnlineDetailLink()">${linked ? '重新关联' : '关联案件'}</button>
    </div></section>`;
  document.body.appendChild(modal);
  revealCourtModal();
}
function renderCourtOnline() {
  const co = state.courtOnline, status = co.status || {};
  if (co.kind === 'readings') { renderCourtReadings(co, status); return; }
  const isEntityKind = courtIsEntityKind();
  const kindLabel = { todo: '待办', message: '消息', delivery: '电子送达' };
  const counts = {
    ...(co.counts || {}),
    total: Number(status.record_count ?? co.counts?.total ?? 0),
    todo: Number(status.todo_count ?? co.counts?.todo ?? 0),
    message: Number(status.message_count ?? co.counts?.message ?? 0),
    delivery: Number(status.delivery_count ?? co.counts?.delivery ?? 0),
    cases: Number(status.case_count || 0),
    layy: Number(status.layy_count || 0),
    hearings: Number(status.hearing_count || 0),
  };
  const subtabs = courtKindTabs.map(({ value, label }) => value === 'cases' ? courtCaseAjlbTabHtml(co, status) : value === 'layy' ? courtLayyAjlbTabHtml(co, status) : `<button class="tab ${co.kind===value?'active':''}" data-kind="${value}" onclick="courtSelectKind('${value}')">${label}<span class="tab-count">${counts[value === '' ? 'total' : value] ?? 0}</span></button>`).join('');
  const cards = isEntityKind
    ? co.kind === 'hearings' ? courtHearingCardsHtml(co.items) : co.items.map(item => co.kind === 'cases' ? courtCaseCard(item) : courtLayyCard(item)).join('') || '<div class="empty">暂无数据。完成登录后可点击“立即同步”。</div>'
    : co.items.map(item => {
    const attachments = item.attachments || [];
    const bodyText = item.content || (attachments.length
      ? `已同步 ${attachments.length} 份文书，可点击查看详情或直接预览。`
      : '暂无可展示的内容');
    const title = item.title || (item.kind === 'delivery' ? '电子送达' : '法院通知');
    const caseText = item.case_number || item.case_name || '';
    const linked = Number(item.linked_case_id || 0);
    const kindName = kindLabel[item.kind] || '法院通知';
    const deliveryPending = item.kind === 'delivery' && item.delivery_status === '1';
    const deliveryDone = item.kind === 'delivery' && item.delivery_status === '2';
    const metaParts = [];
    if (caseText) metaParts.push(`<span class="court-meta-case">${esc(caseText)}</span>`);
    if (item.court_name) metaParts.push(`<span>${esc(item.court_name)}</span>`);
    if (deliveryPending) metaParts.push('<span class="court-meta-pending">待签收</span>');
    if (deliveryDone) metaParts.push('<span class="court-meta-done">已签收</span>');
    if (linked) metaParts.push(`<button class="court-meta-link" title="点击查看关联案件详情" onclick="event.stopPropagation();openDetail('cases', ${linked})">已关联：${esc(item.linked_case_title || '案件')}</button>`);
    const metaLine = metaParts.length ? `<div class="court-card-meta" title="${esc(metaParts.map(p => (p.match(/>([^<]+)</) || ['', ''])[1]).join(' · '))}">${metaParts.join('<span class="court-meta-sep">·</span>')}</div>` : '';
    const actionsHtml = [
      `<button class="court-action" type="button" onclick="openCourtRecordDetail(${Number(item.id)})">查看详情</button>`,
      item.unread ? `<button class="court-action" type="button" onclick="event.stopPropagation();courtMarkRead(${Number(item.id)})">标为已读</button>` : '',
      item.case_space_url ? `<button class="court-action" type="button" onclick="event.stopPropagation();courtOpenSpace(${Number(item.id)})">打开案件空间</button>` : '',
      item.chat_available ? `<button class="court-action" type="button" onclick="event.stopPropagation();courtLoadChat(${Number(item.id)})">查看私信</button>` : '',
      `<button class="court-action primary" type="button" onclick="event.stopPropagation();courtLinkCase(${Number(item.id)}, ${linked})">${linked ? '重新关联' : '关联案件'}</button>`,
      attachments.length ? `<button class="court-action" type="button" onclick="event.stopPropagation();courtDownloadAll(${Number(item.id)})">下载全部（${attachments.length}）</button>` : '',
    ].join('');
    return `<article id="court-record-${Number(item.id)}" class="court-card court-card-clickable court-record-card ${item.unread ? 'is-new' : ''}" onclick="openCourtRecordDetail(${Number(item.id)})" title="点击查看详情">
      <header class="court-card-head">
        <div class="court-card-title">
          ${item.unread ? '<span class="court-unread-dot" title="未读"></span>' : ''}
          <span class="court-kind-badge kind-${esc(item.kind || 'default')}">${esc(kindName)}</span>
          <strong>${esc(title)}</strong>
        </div>
        <time class="court-card-time">${esc(fmt(item.published_at) || '—')}</time>
      </header>
      <p class="court-card-body">${esc(bodyText)}</p>
      ${metaLine}
      ${attachments.length ? `<div class="court-card-files">${courtRecordFilesHtml(attachments, linked)}</div>` : ''}
      <div class="court-card-actions">${actionsHtml}</div>
    </article>`;
  }).join('') || '<div class="empty">暂无一张网记录。完成登录后可点击“立即同步”。</div>';
  const searchPlaceholder = co.kind === 'cases' ? '搜索案号、案件名称、法院、法官或当事人'
    : co.kind === 'layy' ? '搜索法院、案件类型、当事人、案由或审核意见'
    : co.kind === 'hearings' ? '搜索案号、案件名称、法院、开庭类型或地点'
    : '搜索案件名称、案号、法院或内容';
  const listHost = $('courtOnlineListHost');
  if (!listHost) {
    $('content').innerHTML = `<div class="toolbar"><div class="filters"><div class="court-kind-tabs" id="courtKindTabs">${subtabs}</div><input class="input search" id="courtSearch" value="${esc(co.q)}" placeholder="${searchPlaceholder}" autocomplete="off" oninput="courtSearchInput(this)">${isEntityKind ? '' : `<label><input type="checkbox" id="courtUnreadOnly" onchange="courtToggleUnread(this)" ${co.unread?'checked':''}> 仅未读</label>`}<button class="btn court-adv-toggle" id="courtAdvToggle" type="button" onclick="courtToggleAdvancedSearch()">高级搜索</button></div><span id="courtTotalCount">共 ${co.total} 条</span></div><div class="court-adv-panel" id="courtAdvancedSearch"><div class="court-adv-panel-inner"><span class="court-as-field"><input class="input" id="coAsCaseNo" value="${esc(co.advSearch?.case_no || '')}" placeholder="案号，如（2023）京01民初1号" autocomplete="off" onfocus="courtAdvDropOpen('case_no', this)" oninput="courtAdvDropFilter('case_no', this)" onkeydown="courtAdvDropKey(event, 'case_no')"><div class="court-as-drop" id="coAsCaseNoDrop" hidden></div></span><span class="court-as-field"><input class="input" id="coAsCourt" value="${esc(co.advSearch?.court || '')}" placeholder="法院名称，如北京市第一中级人民法院" autocomplete="off" onfocus="courtAdvDropOpen('court', this)" oninput="courtAdvDropFilter('court', this)" onkeydown="courtAdvDropKey(event, 'court')"><div class="court-as-drop" id="coAsCourtDrop" hidden></div></span><span class="court-as-field"><input class="input" id="coAsParty" value="${esc(co.advSearch?.party || '')}" placeholder="当事人名称" autocomplete="off" onfocus="courtAdvDropOpen('party', this)" oninput="courtAdvDropFilter('party', this)" onkeydown="courtAdvDropKey(event, 'party')"><div class="court-as-drop" id="coAsPartyDrop" hidden></div></span><button class="btn primary" type="button" onclick="courtApplyAdvancedSearch()">查询</button><button class="btn" type="button" onclick="courtResetAdvancedSearch()">重置</button></div></div><div class="toolbar"><div class="court-status-wrap" id="courtStatusWrap"><button class="court-status-btn" id="courtStatusBtn" type="button" onclick="courtToggleStatusMenu(event)" aria-haspopup="true" aria-expanded="false"><span class="court-status-dot" id="courtStatusDot"></span><span id="courtStatusBtnText">正在读取状态…</span><svg class="court-status-caret" width="10" height="10" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg></button><div class="court-status-menu" id="courtStatusMenu" role="menu" aria-label="法院在线状态" hidden><div class="court-status-menu-head"><strong>法院在线状态</strong><span class="court-status-menu-detail" id="csStatusDetail">—</span></div><dl class="court-status-rows"><dt>登录会话</dt><dd id="csSession">—</dd><dt>最近同步</dt><dd id="csLastSync">—</dd><dt>未读 / 待签收</dt><dd id="csUnread">—</dd><dt>同步间隔</dt><dd id="csInterval">—</dd></dl><div class="court-status-menu-actions"><button class="btn" type="button" data-court-sync onclick="closeCourtStatusMenu();courtSync()">立即同步</button><button class="btn" type="button" onclick="closeCourtStatusMenu();courtLogin()">登录官网</button><button class="btn" type="button" onclick="closeCourtStatusMenu();courtLogout()">退出登录</button><button class="btn primary" type="button" onclick="closeCourtStatusMenu();openCourtSettings()">设置</button></div></div></div><div class="jm-actions"><button class="btn" onclick="courtAutoLink()">自动关联</button><button class="btn primary" id="courtLoginBtn" onclick="courtLogin()">${status.session_active?'重新登录':'登录官网'}</button><button class="btn" onclick="courtOpenDownloadDirectory()">打开文书文件夹</button><button class="btn" onclick="openCourtSettings()">设置</button><button class="btn" onclick="openCourtLogs()">日志</button><button class="btn court-refresh-icon" data-court-sync onclick="courtSync()" title="立即同步" aria-label="立即同步"><svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true"><path d="M13.2 5.7A5.6 5.6 0 102.8 10.2M13.2 2.8v2.9h-2.9" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></button></div></div><div class="court-sync-banner-wrap" id="courtSyncBanner">${courtSyncBannerHtml()}</div><div class="record-list court-online-list" id="courtOnlineListHost">${cards}</div>`;
  } else {
    const total = $('courtTotalCount'); if (total) total.textContent = `共 ${co.total} 条`;
    const loginBtn = $('courtLoginBtn'); if (loginBtn) loginBtn.textContent = status.session_active ? '重新登录' : '登录官网';
    document.querySelectorAll('#courtKindTabs .tab').forEach(btn => {
      const value = btn.dataset.kind || '';
      btn.classList.toggle('active', value === co.kind);
      const badge = btn.querySelector('.tab-count');
      if (badge) badge.textContent = String(counts[value === '' ? 'total' : value] ?? 0);
    });
    const ajlbMenu = $('courtCaseAjlbMenu');
    if (ajlbMenu) {
      const items = [
        { value: 'sp', count: Number(status.case_trial_count || 0) },
        { value: 'zx', count: Number(status.execute_case_count || 0) },
        { value: 'pc', count: Number(status.bankruptcy_case_count || 0) },
      ];
      for (const item of items) {
        const entry = ajlbMenu.querySelector(`[data-ajlb="${item.value}"]`);
        if (!entry) continue;
        entry.classList.toggle('active', item.value === co.caseAjlb);
        const badge = entry.querySelector('b');
        if (badge) badge.textContent = String(item.count);
      }
    }
    const layyAjlbMenu = $('courtLayyAjlbMenu');
    if (layyAjlbMenu) {
      // 悬浮菜单在首屏创建后会复用 DOM。这里同步更新预约分类计数，
      // 防止首次状态尚未完整返回时，菜单一直保留为 0。
      layyAjlbMenu.innerHTML = courtLayyAjlbMenuHtml(co, status);
    }
    const searchBox = $('courtSearch'); if (searchBox) searchBox.placeholder = searchPlaceholder;
    const unreadBox = $('courtUnreadOnly'); if (unreadBox && unreadBox.checked !== co.unread) unreadBox.checked = co.unread;
    if (unreadBox) unreadBox.closest('label')?.toggleAttribute('hidden', isEntityKind);
    listHost.innerHTML = cards;
  }
  bindCourtKindHoverMenus();
  courtUpdateSyncBanner();
  if (co.focusRecordId) {
    const target = $(`court-record-${Number(co.focusRecordId)}`);
    if (target) { target.scrollIntoView({ behavior: 'smooth', block: 'center' }); target.classList.add('is-new'); co.focusRecordId = 0; }
  }
}
function courtSelectKind(kind) { state.courtOnline.kind = kind; state.courtOnline.page = 1; loadCourtOnline(); }
function courtStatusPlain(status) {
  if (!status) return '';
  if (status.login_in_progress) return '正在登录法院官网…';
  if (status.session_active) return status.session_logged_in_at ? `已登录 · ${fmt(status.session_logged_in_at)}` : '已登录';
  return status.credentials_configured ? '会话已失效' : '尚未配置登录';
}
function courtStatusDotClass(status) {
  if (!status) return '';
  if (status.login_in_progress) return 'pending';
  if (status.session_active) return 'active';
  return 'error';
}
function courtUpdateStatusButton() {
  const btn = $('courtStatusBtn'); if (!btn) return;
  const status = state.courtOnline.status || {};
  const dot = $('courtStatusDot'); if (dot) dot.className = `court-status-dot ${courtStatusDotClass(status)}`;
  const text = $('courtStatusBtnText'); if (text) text.textContent = courtStatusPlain(status) || '正在读取状态…';
  const detail = $('csStatusDetail'); if (detail) detail.textContent = courtStatusPlain(status) || '—';
  const set = (id, v) => { const el = $(id); if (el) el.textContent = v; };
  set('csSession', status.session_active
    ? `已登录${status.session_logged_in_at ? ` · ${fmt(status.session_logged_in_at)}` : ''}`
    : (status.credentials_configured ? '会话已失效，请重新登录' : '尚未配置登录信息'));
  set('csLastSync', status.last_sync_at ? fmt(status.last_sync_at) : '尚未同步');
  set('csUnread', String(status.unread_count ?? 0));
  set('csInterval', status.sync_interval_minutes ? `${status.sync_interval_minutes} 分钟` : '—');
  const rows = document.querySelector('#courtStatusMenu .court-status-rows');
  const accounts = Array.isArray(status.accounts) ? status.accounts : [];
  const activeAccount = accounts.find(item => item.active) || null;
  if (rows && !$('csAccount')) {
    rows.insertAdjacentHTML('afterbegin', '<dt>当前账号</dt><dd id="csAccount">—</dd>');
  }
  set('csAccount', activeAccount?.label || status.account || '尚未配置');
  const actions = document.querySelector('#courtStatusMenu .court-status-menu-actions');
  if (actions && !$('courtSwitchAccountBtn')) {
    const button = document.createElement('button');
    button.className = 'btn'; button.type = 'button'; button.id = 'courtSwitchAccountBtn';
    button.textContent = '切换账号'; button.onclick = courtToggleAccountPicker;
    actions.prepend(button);
    const picker = document.createElement('div');
    picker.className = 'court-account-picker'; picker.id = 'courtAccountPicker'; picker.hidden = true;
    actions.parentElement.insertBefore(picker, actions);
  }
  const loginAction = actions?.querySelector('button[onclick*="courtLogin"]');
  const statusWrap = $('courtStatusWrap');
  const openServiceButton = $('courtLoginBtn');
  if (loginAction && statusWrap && openServiceButton && !$('courtOpenServiceBtn')) {
    const statusActions = document.createElement('div');
    statusActions.className = 'court-status-actions';
    statusWrap.parentElement?.insertBefore(statusActions, statusWrap);
    openServiceButton.id = 'courtOpenServiceBtn';
    openServiceButton.classList.remove('primary');
    openServiceButton.classList.add('court-open-service-btn');
    openServiceButton.textContent = '打开法院诉讼服务网';
    statusActions.append(statusWrap, openServiceButton);
    loginAction.remove();
  }
  const picker = $('courtAccountPicker');
  if (picker) {
    picker.innerHTML = accounts.length > 1
      ? accounts.map(item => `<button class="court-account-option ${item.active ? 'active' : ''}" type="button" onclick="courtSwitchAccount('${esc(item.id)}')"><span>${esc(item.label)}</span><small>${item.active ? '当前使用' : (item.credentials_configured ? '切换至此账号' : '未配置密码')}</small></button>`).join('')
      : '<div class="court-link-empty">可在“设置”中录入另一账号后，在这里切换。</div>';
  }
  // 登录改为页内浮窗模式：检测到后台自动登录进行中（含定时任务的
  // 静默自动登录）时，自动弹出小浮窗展示实时画面；用户手动收起后
  // 在本轮登录结束前不再打扰，登录结束后恢复。
  if (status.login_in_progress) {
    if (!$('courtLoginFloat') && !courtLoginFloatSuppressed) courtOpenLoginFloat();
  } else {
    courtLoginFloatSuppressed = false;
  }
}
function courtToggleStatusMenu(event) {
  event.stopPropagation();
  const menu = $('courtStatusMenu'); const btn = $('courtStatusBtn');
  if (!menu) return;
  const open = menu.hidden;
  menu.hidden = !open;
  btn?.setAttribute('aria-expanded', String(open));
  if (open) courtUpdateStatusButton();
}
function closeCourtStatusMenu() {
  const menu = $('courtStatusMenu'); const btn = $('courtStatusBtn');
  if (menu) menu.hidden = true;
  btn?.setAttribute('aria-expanded', 'false');
}
function courtToggleAccountPicker() {
  const picker = $('courtAccountPicker');
  if (!picker) return;
  picker.hidden = !picker.hidden;
}
async function courtSwitchAccount(accountId) {
  try {
    const current = state.courtOnline.status?.active_account_id;
    if (!accountId || accountId === current) { $('courtAccountPicker')?.setAttribute('hidden', ''); return; }
    const result = await api(`${CO_API}/accounts/switch`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({account_id:accountId})});
    state.courtOnline.status = result;
    state.courtOnline.page = 1; state.courtOnline.q = ''; state.courtOnline.advSearch = {case_no:'', court:'', party:''};
    closeCourtStatusMenu();
    toast(`已切换至 ${result.account || '所选账号'}，正在显示该账号已加载的信息`);
    await loadCourtOnline();
  } catch (e) { toast(e.message || '账号切换失败'); }
}
document.addEventListener('click', (event) => {
  const wrap = $('courtStatusWrap');
  if (wrap && !wrap.contains(event.target)) closeCourtStatusMenu();
});
function courtSearchInput(input) {
  state.courtOnline.q = input.value;
  clearTimeout(window._courtSearchTimer);
  window._courtSearchTimer = setTimeout(loadCourtOnline, 350);
}
function courtToggleUnread(checkbox) { state.courtOnline.unread = checkbox.checked; state.courtOnline.page = 1; loadCourtOnline(); }
function courtToggleAdvancedSearch() {
  const panel = $('courtAdvancedSearch');
  if (!panel) return;
  const open = !panel.classList.contains('open');
  panel.classList.toggle('open', open);
  $('courtAdvToggle')?.classList.toggle('active', open);
  if (open) setTimeout(() => $('coAsCaseNo')?.focus(), 200);
}
function courtApplyAdvancedSearch() {
  state.courtOnline.advSearch = {
    case_no: ($('coAsCaseNo')?.value || '').trim(),
    court: ($('coAsCourt')?.value || '').trim(),
    party: ($('coAsParty')?.value || '').trim(),
  };
  state.courtOnline.page = 1;
  loadCourtOnline();
}
function courtResetAdvancedSearch() {
  state.courtOnline.advSearch = { case_no: '', court: '', party: '' };
  ['coAsCaseNo', 'coAsCourt', 'coAsParty'].forEach(id => { const el = $(id); if (el) el.value = ''; });
  state.courtOnline.page = 1;
  loadCourtOnline();
}
const courtAsDropMap = { case_no: 'coAsCaseNoDrop', court: 'coAsCourtDrop', party: 'coAsPartyDrop' };
let courtAdvOptions = null;
let courtAdvDropIndex = -1;
async function courtLoadAdvOptions(force) {
  if (courtAdvOptions && !force) return courtAdvOptions;
  try { courtAdvOptions = await api(`${CO_API}/search-options`); }
  catch (e) { courtAdvOptions = { case_no: [], court: [], party: [] }; }
  return courtAdvOptions;
}
function courtAdvDropEl(field) { return $(courtAsDropMap[field]); }
function courtAdvDropClose(field) { const el = courtAdvDropEl(field); if (el) el.hidden = true; }
function courtAdvDropCloseAll() { Object.values(courtAsDropMap).forEach(id => { const el = $(id); if (el) el.hidden = true; }); courtAdvDropIndex = -1; }
function courtAdvDropOpen(field, input) {
  if (!$('courtAdvancedSearch')?.classList.contains('open')) return;
  courtAdvDropCloseAll();
  courtLoadAdvOptions().then(() => courtAdvDropRender(field, input));
}
function courtAdvDropRender(field, input) {
  const list = courtAdvOptions?.[field] || [];
  const kw = (input.value || '').trim().toLowerCase();
  const matched = kw ? list.filter(v => v.toLowerCase().includes(kw)) : list;
  const drop = courtAdvDropEl(field);
  if (!drop) return;
  courtAdvDropIndex = -1;
  if (!matched.length) {
    drop.innerHTML = '<div class="court-as-empty">无匹配项，可直接输入后点击查询</div>';
    drop.hidden = false;
    return;
  }
  const shown = matched.slice(0, 60);
  drop.innerHTML = shown.map(v => `<div class="court-as-item" data-v="${esc(v)}" onmousedown="event.preventDefault();courtAdvDropPick('${field}', this.dataset.v)">${esc(v)}</div>`).join('')
    + (matched.length > shown.length ? `<div class="court-as-more">共 ${matched.length} 项，输入关键字进一步筛选</div>` : '');
  drop.hidden = false;
}
function courtAdvDropFilter(field, input) { courtAdvDropRender(field, input); }
function courtAdvDropPick(field, value) {
  const input = $(courtAsDropMap[field].replace('Drop', ''));
  if (input) { input.value = value; input.focus(); }
  courtAdvDropClose(field);
}
function courtAdvDropKey(event, field) {
  if (event.key === 'Escape') { courtAdvDropClose(field); return; }
  const drop = courtAdvDropEl(field);
  if (!drop || drop.hidden) {
    if (event.key === 'Enter') { event.preventDefault(); courtApplyAdvancedSearch(); }
    return;
  }
  const items = drop.querySelectorAll('.court-as-item');
  if (event.key === 'Enter') {
    event.preventDefault();
    if (items[courtAdvDropIndex]) courtAdvDropPick(field, items[courtAdvDropIndex].dataset.v);
    else courtApplyAdvancedSearch();
    return;
  }
  if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
  event.preventDefault();
  items.forEach((el, i) => el.classList.toggle('hover', i === courtAdvDropIndex));
  const dir = event.key === 'ArrowDown' ? 1 : -1;
  courtAdvDropIndex = courtAdvDropIndex < 0 ? (dir > 0 ? 0 : items.length - 1) : (courtAdvDropIndex + dir + items.length) % items.length;
  items[courtAdvDropIndex]?.scrollIntoView({ block: 'nearest' });
  items.forEach((el, i) => el.classList.toggle('hover', i === courtAdvDropIndex));
}
document.addEventListener('mousedown', (event) => {
  if (!event.target.closest('.court-as-field')) courtAdvDropCloseAll();
});
async function courtAutoLink() { try { const r = await api(`${CO_API}/auto-link`, {method:'POST'}); toast(r.linked ? `已按案号自动关联 ${r.linked} 条法院记录` : '未发现可自动关联的记录'); await loadCourtOnline(); } catch(e) { toast(e.message || '自动关联失败'); } }
let courtSyncObserver = null;
async function courtObserveSync(initial = null) {
  if (courtSyncObserver || activeTab !== 'courtOnline' || state.offlineMode) return;
  courtSyncObserver = (async () => {
    try {
      let status = initial || await api(`${CO_API}/sync/status`, { bypassOffline: true });
      if (!status.running && !initial && state.courtOnline.sync?.phase !== 'running') return;
      while (status.running && activeTab === 'courtOnline') {
        courtSetSyncFeedback('running', status.stage || '正在同步一张网…');
        await new Promise(resolve => window.setTimeout(resolve, 1500));
        if (activeTab !== 'courtOnline') return;
        status = await api(`${CO_API}/sync/status`, { bypassOffline: true });
      }
      if (status.running) return;
      const result = status.result || {};
      const message = result.message || (result.needs_login ? '会话不存在，请打开法院诉讼服务网登录' : `已完成${result.added ? `，发现 ${result.added} 条新记录` : ''}${result.removed ? `，移除 ${result.removed} 条已删除记录` : ''}`);
      courtSetSyncFeedback(result.ok === false ? 'error' : 'success', message);
      toast(result.ok === false ? message : `同步完成：${message}`);
      await loadCourtOnline();
      window.setTimeout(() => {
        if (state.courtOnline.sync?.message === message) courtSetSyncFeedback('idle', '');
      }, 5200);
    } catch (e) {
      courtSetSyncFeedback('error', e.message || '无法查询同步进度');
    } finally {
      courtSyncObserver = null;
    }
  })();
  await courtSyncObserver;
}
async function courtSync() {
  if (state.courtOnline.sync?.phase === 'running') return;
  courtSetSyncFeedback('running', '正在启动同步…');
  try {
    const status = await api(`${CO_API}/sync/start`, {method:'POST'});
    await courtObserveSync(status);
  } catch (e) {
    const message = e.message || '同步失败，请稍后重试';
    courtSetSyncFeedback('error', message);
    toast(message);
  }
}
// ---- 法院官网登录浮窗：页内小浮窗实时展示自动登录过程 ----
let courtLoginFrameSeq = 0, courtLoginFrameTimer = null, courtLoginStatusTimer = null;
let courtLoginFloatSuppressed = false, courtLoginFloatClosing = false;
function courtOpenLoginFloat() {
  let float = $('courtLoginFloat');
  if (!float) {
    document.body.insertAdjacentHTML('beforeend', `
      <div class="court-login-float" id="courtLoginFloat" role="dialog" aria-label="法院官网自动登录浮窗">
        <div class="court-login-float-head">
          <span class="court-status-dot pending" id="courtLoginFloatDot"></span>
          <strong>人民法院在线服务网 · 自动登录</strong>
          <button class="court-float-close" type="button" title="收起浮窗（登录会在后台继续）" onclick="courtCloseLoginFloat(true)">&times;</button>
        </div>
        <div class="court-login-float-stage" id="courtLoginFloatStage">正在启动自动登录…</div>
        <div class="court-login-float-body">
          <img id="courtLoginFrame" alt="人民法院在线服务网实时画面" hidden>
          <div class="court-login-float-empty" id="courtLoginFloatEmpty">正在启动受控浏览器…<br>登录全程在本机后台自动完成，不会弹出其他窗口。</div>
        </div>
        <div class="court-login-float-foot">
          <button class="btn" type="button" onclick="courtRevealLoginWindow()">打开原生窗口</button>
          <button class="btn" type="button" id="courtLoginRetryBtn" onclick="courtLoginRetry()" hidden>重试</button>
          <span class="court-float-note" id="courtLoginFloatNote">自动登录中</span>
        </div>
      </div>`);
  } else {
    courtResetLoginFloat('正在启动自动登录…');
  }
  courtLoginFloatSuppressed = false;
  courtLoginFloatClosing = false;
  if (!courtLoginFrameTimer) courtLoginFrameTimer = (window.ApexLifecycle?.interval || window.setInterval)(courtRefreshLoginFrame, 700);
  if (!courtLoginStatusTimer) courtLoginStatusTimer = (window.ApexLifecycle?.interval || window.setInterval)(courtPollLoginFloat, 1500);
  courtRefreshLoginFrame();
  courtPollLoginFloat();
}
function courtResetLoginFloat(stageText) {
  courtLoginFloatClosing = false;
  const dot = $('courtLoginFloatDot'); if (dot) dot.className = 'court-status-dot pending';
  const stage = $('courtLoginFloatStage'); if (stage) stage.textContent = stageText || '自动登录中…';
  const note = $('courtLoginFloatNote'); if (note) note.textContent = '自动登录中';
  const retry = $('courtLoginRetryBtn'); if (retry) retry.hidden = true;
  const empty = $('courtLoginFloatEmpty'); if (empty) empty.hidden = false;
  const img = $('courtLoginFrame'); if (img) img.hidden = true;
}
function courtStopLoginFloatTimers() {
  if (courtLoginFrameTimer) { clearInterval(courtLoginFrameTimer); courtLoginFrameTimer = null; }
  if (courtLoginStatusTimer) { clearInterval(courtLoginStatusTimer); courtLoginStatusTimer = null; }
}
function courtCloseLoginFloat(manual = false) {
  if (manual) courtLoginFloatSuppressed = true;
  courtStopLoginFloatTimers();
  $('courtLoginFloat')?.remove();
}
function courtRefreshLoginFrame() {
  const img = $('courtLoginFrame'); if (!img) return;
  const probe = new Image();
  probe.onload = () => {
    if (!$('courtLoginFrame')) return;
    img.src = probe.src; img.hidden = false;
    const empty = $('courtLoginFloatEmpty'); if (empty) empty.hidden = true;
  };
  probe.onerror = () => {
    if (!$('courtLoginFrame')) return;
    img.hidden = true;
    const empty = $('courtLoginFloatEmpty');
    if (empty) { empty.hidden = false; empty.innerHTML = '受控浏览器正在启动或未打开…<br>点击“重试”可再次发起自动登录。'; }
  };
  // clip=root：只截取官网页面主内容区，去掉四周空白
  probe.src = `${CO_API}/browser/frame?frame=${++courtLoginFrameSeq}&clip=root`;
}
function courtLogFresh(created_at) {
  const ts = new Date(String(created_at || '').replace(' ', 'T')).getTime();
  return Number.isFinite(ts) && Date.now() - ts < 120000;
}
async function courtPollLoginFloat() {
  if (courtLoginFloatClosing) return;
  const float = $('courtLoginFloat');
  if (!float) { courtStopLoginFloatTimers(); return; }
  let status;
  try { status = await api(`${CO_API}/status`); } catch (e) { return; }
  if (!$('courtLoginFloat') || courtLoginFloatClosing) return;
  const dot = $('courtLoginFloatDot'), stage = $('courtLoginFloatStage'), note = $('courtLoginFloatNote');
  if (status.session_active && !status.login_in_progress) {
    courtLoginFloatClosing = true;
    courtStopLoginFloatTimers();
    if (dot) dot.className = 'court-status-dot active';
    if (stage) stage.textContent = '登录成功，正在刷新一张网登录状态…';
    if (note) note.textContent = '完成';
    loadCourtOnline();
    // 状态文字更新后停留约 1 秒，再淡出关闭（纯 CSS 过渡，无额外资源）。
    setTimeout(() => {
      const floatEl = $('courtLoginFloat');
      if (!floatEl) { toast('法院官网登录成功，一张网登录状态已刷新'); return; }
      floatEl.classList.add('closing');
      setTimeout(() => { courtCloseLoginFloat(); toast('法院官网登录成功，一张网登录状态已刷新'); }, 300);
    }, 1500);
    return;
  }
  if (status.login_in_progress) {
    if (dot) dot.className = 'court-status-dot pending';
    if (note) note.textContent = '自动登录中';
    let stageText = '';
    try {
      const logs = await api(`${CO_API}/logs`);
      const item = (logs.items || []).find(it => /登录|验证码|浏览器|会话/.test(it.message || '') && courtLogFresh(it.created_at));
      if (item) stageText = item.message;
    } catch (e) { }
    if (stage && stageText) stage.textContent = stageText;
    return;
  }
  // 登录任务已结束但没有有效会话：展示错误并允许重试。
  courtLoginFloatClosing = true;
  courtStopLoginFloatTimers();
  const message = status.last_error || '登录未完成';
  if (dot) dot.className = 'court-status-dot error';
  if (stage) stage.textContent = message;
  if (note) note.textContent = '待处理';
  const retry = $('courtLoginRetryBtn'); if (retry) retry.hidden = false;
  const empty = $('courtLoginFloatEmpty');
  if (empty) { empty.hidden = false; empty.innerHTML = `自动登录未完成：<br>${esc(message)}`; }
}
function courtLoginRetry() {
  const retry = $('courtLoginRetryBtn'); if (retry) retry.hidden = true;
  courtResetLoginFloat('正在重新发起自动登录…');
  courtLoginFloatClosing = false;
  courtLoginFloatSuppressed = false;
  if (!courtLoginFrameTimer) courtLoginFrameTimer = (window.ApexLifecycle?.interval || window.setInterval)(courtRefreshLoginFrame, 700);
  if (!courtLoginStatusTimer) courtLoginStatusTimer = (window.ApexLifecycle?.interval || window.setInterval)(courtPollLoginFloat, 1500);
  courtLogin().catch(() => { });
}
async function courtLogout() {
  if (!confirm('确定退出法院官网登录吗？\n已保存的账号密码会保留，仅结束当前登录会话；需要时重新登录即可。')) return;
  try {
    await api(`${CO_API}/logout`, { method: 'POST' });
    toast('已退出法院官网登录');
  } catch (e) { toast(e.message || '退出登录失败'); }
  await loadCourtOnline();
}
async function courtRevealLoginWindow() {
  try {
    const r = await api(`${CO_API}/browser/reveal`, { method: 'POST' });
    if (r?.ok) toast('已在原生 Chrome 窗口打开官网，完成登录后浮窗会自动收起');
    else toast('无法唤出原生窗口，请在浮窗中重试');
  } catch (e) { toast(e.message || '无法唤出原生窗口'); }
}
async function courtLogin() {
  try {
    if (state.courtOnline.status?.session_active) {
      courtCloseLoginFloat(true);
      try {
        const opened = await api(`${CO_API}/browser/reveal`, { method: 'POST' });
        if (opened?.ok) return;
        throw new Error('一张网窗口已恢复，但未能切到前台，请检查 Chrome 窗口');
      } catch (e) {
        if (e?.status !== 409) throw e;
      }
    }
    courtOpenLoginFloat();
    const r = await api(`${CO_API}/login`, { method: 'POST' });
    toast(r.message || '正在浮窗中自动登录官网');
  } catch (e) {
    if (!$('courtLoginFloat')) { toast(e.message || '无法打开法院官网'); return; }
    courtLoginFloatClosing = true;
    courtStopLoginFloatTimers();
    const dot = $('courtLoginFloatDot'), stage = $('courtLoginFloatStage'), note = $('courtLoginFloatNote');
    if (dot) dot.className = 'court-status-dot error';
    if (stage) stage.textContent = e.message || '无法启动登录';
    if (note) note.textContent = '待处理';
    const retry = $('courtLoginRetryBtn'); if (retry) retry.hidden = false;
    toast(e.message || '无法启动登录');
  }
}
async function courtMarkRead(id) { try { await api(`${CO_API}/records/${id}/read`, {method:'POST'}); await loadCourtOnline(); } catch(e) { toast(e.message || '操作失败'); } }
async function courtSaveSettings() { try { await api(`${CO_API}/settings`, {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({account:$('coAccount')?.value||'',password:$('coPassword')?.value||'',baidu_api_key:$('coBaiduKey')?.value||'',baidu_secret_key:$('coBaiduSecret')?.value||'',sync_interval_minutes:Number($('coInterval')?.value||5),auto_login_enabled:$('coAutoLogin')?.checked,ocr_enabled:$('coOcr')?.checked,enabled:true})}); toast('设置已安全保存到 macOS 钥匙串'); closeCourtSettings(); await loadCourtOnline(); } catch(e) { toast(e.message || '保存失败'); } }
async function courtChooseDownloadDirectory() { try { const r = await api(`${CO_API}/download-directory/select`, {method:'POST'}); if (r.cancelled) return; toast('已更新文书下载目录'); await loadCourtOnline(); } catch(e) { toast(e.message || '选择目录失败'); } }
async function courtOpenDownloadDirectory() { try { await api(`${CO_API}/download-directory/open`, {method:'POST'}); } catch(e) { toast(e.message || '无法打开文件夹'); } }
async function courtClearCredentials() { if (!confirm('确定清除法院账号、OCR 密钥和登录会话吗？')) return; try { await api(`${CO_API}/credentials`, {method:'DELETE'}); toast('已清除凭据'); closeCourtSettings(); await loadCourtOnline(); } catch(e) { toast(e.message || '清除失败'); } }
function openCourtSettings() {
  const status = state.courtOnline.status || {};
  closeCourtSettings(); closeCourtLogs();
  document.body.insertAdjacentHTML('beforeend', `
    <div class="court-link-modal" id="courtSettingsModal" role="dialog" aria-modal="true" aria-label="登录、同步与下载设置">
      <section class="court-link-dialog court-settings-dialog">
        <div class="court-link-head">
          <div><strong>登录、同步与下载设置</strong><span>账号、密码与 OCR 密钥仅保存在本机 macOS 钥匙串中</span></div>
          <button class="btn" type="button" onclick="closeCourtSettings()">关闭</button>
        </div>
        <div class="court-dialog-body">
          <div class="court-settings-note">启用 OCR 后，验证码优先使用本机 ddddocr 免费识别（不联网上传）；未识别成功时，如配置了百度密钥则自动兜底。</div>
          <div class="court-settings-grid">
            <label>法院账号<input class="input" id="coAccount" autocomplete="username" placeholder="${esc(status.account || '首次填写')}"></label>
            <label>法院密码<input class="input" id="coPassword" type="password" autocomplete="current-password" placeholder="留空则不修改"></label>
            <label>百度 API Key（可选兜底）<input class="input" id="coBaiduKey" placeholder="留空则仅用本机识别"></label>
            <label>百度 Secret Key（可选兜底）<input class="input" id="coBaiduSecret" type="password" placeholder="留空则仅用本机识别"></label>
            <label>同步间隔（分钟）<input class="input" id="coInterval" type="number" min="1" max="1440" value="${Number(status.sync_interval_minutes || 5)}"></label>
            <label>文书下载目录<div class="jm-actions"><input class="input" id="coDownloadDir" value="${esc(status.download_directory || 'APEX 默认法院文书目录')}" readonly><button class="btn" onclick="courtChooseDownloadDirectory()">选择目录</button><button class="btn" onclick="courtOpenDownloadDirectory()">打开文件夹</button></div></label>
            <label class="court-settings-check"><input type="checkbox" id="coAutoLogin" ${status.auto_login_enabled?'checked':''}> 会话过期时自动登录</label>
            <label class="court-settings-check"><input type="checkbox" id="coOcr" ${status.ocr_enabled?'checked':''}> 自动 OCR 验证码</label>
          </div>
        </div>
        <div class="court-dialog-foot">
          <span class="court-foot-hint">修改后点击“保存设置”立即生效</span>
          <button class="btn danger" type="button" onclick="courtClearCredentials()">清除凭据与会话</button>
          <button class="btn" type="button" onclick="closeCourtSettings()">取消</button>
          <button class="btn primary" type="button" onclick="courtSaveSettings()">保存设置</button>
        </div>
      </section>
    </div>`);
  revealCourtModal();
}
function closeCourtSettings() { $('courtSettingsModal')?.remove(); }
function openCourtLogs() {
  closeCourtLogs(); closeCourtSettings();
  document.body.insertAdjacentHTML('beforeend', `
    <div class="court-link-modal" id="courtLogsModal" role="dialog" aria-modal="true" aria-label="同步日志">
      <section class="court-link-dialog court-logs-dialog">
        <div class="court-link-head">
          <div><strong>同步日志</strong><span>最近一次的法院官网同步与文书下载记录</span></div>
          <button class="btn" type="button" onclick="closeCourtLogs()">关闭</button>
        </div>
        <div class="court-dialog-body court-dialog-list" id="courtLogs"><div class="court-link-empty">正在加载…</div></div>
        <div class="court-dialog-foot">
          <span class="court-foot-hint">仅保留最近若干条记录</span>
          <button class="btn" type="button" onclick="courtLoadLogs()">刷新</button>
          <button class="btn primary" type="button" onclick="closeCourtLogs()">关闭</button>
        </div>
      </section>
    </div>`);
  courtLoadLogs();
  revealCourtModal();
}
function closeCourtLogs() { $('courtLogsModal')?.remove(); }
async function courtLoadLogs() { try { const r = await api(`${CO_API}/logs`); const host = $('courtLogs'); if (host) { host.innerHTML = (r.items || []).length ? (r.items || []).map(item => { const level = esc(String(item.level || 'info').toLowerCase()); return `<div class="court-log-item"><div class="court-log-head"><span class="court-log-level ${level}">${level === 'error' ? '错误' : level === 'warn' || level === 'warning' ? '警告' : '信息'}</span><span class="court-log-time">${esc(fmt(item.created_at) || '')}</span></div><div class="court-log-msg">${esc(item.message || '')}</div></div>`; }).join('') : '<div class="court-link-empty">暂无日志</div>'; void host.offsetWidth; } } catch(e) { const host = $('courtLogs'); if (host) { host.innerHTML = `<div class="court-link-empty">${esc(e.message || '日志读取失败')}</div>`; void host.offsetWidth; } } }
async function courtDownload(id) { try { await ApexDownloads.court({kind:'attachment',id}); toast('下载已开始，可查看右下角实时进度'); } catch(e) { toast(e.message || '下载未开始'); } }
async function courtDownloadAll(id) { try { await ApexDownloads.court({kind:'record',id}); toast('全部附件下载已开始，可在下载中心查看逐个文件和案件'); } catch(e) { toast(e.message || '下载未开始'); } }
function courtPreview(id) { window.open(`${CO_API}/attachments/${id}/preview`, '_blank', 'noopener'); }
async function courtArchive(id, caseId) { try { const r = await api(`${CO_API}/attachments/${id}/archive`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({case_id:caseId})}); toast(`已归档至 ${r.path}`); } catch(e) { toast(e.message || '归档失败'); } }
function courtLinkTarget() {
  const kind = state.courtOnline.kind;
  if (kind === 'cases') return 'cases';
  if (kind === 'hearings') return 'hearings';
  if (kind === 'readings') return 'readings';
  return 'records';
}
async function courtLinkCase(recordId, current) {
  closeCourtLinkModal();
  state.courtOnline.linkingRecordId = Number(recordId); state.courtOnline.linkCaseQuery = '';
  const targetLabel = courtLinkTarget() === 'hearings' ? '开庭扫描记录' : '官网记录';
  document.body.insertAdjacentHTML('beforeend', `
    <div class="court-link-modal" id="courtLinkModal" role="dialog" aria-modal="true" aria-label="关联案件">
      <section class="court-link-dialog">
        <div class="court-link-head">
          <div><strong>关联案件</strong><span>为${targetLabel}匹配案件管理系统中的对应案件</span></div>
          <button class="btn" type="button" onclick="closeCourtLinkModal()">关闭</button>
        </div>
        <div class="court-link-search">
          <input class="input" id="courtLinkCaseSearch" placeholder="输入案件名称、案号或当事人搜索" autocomplete="off">
        </div>
        <div class="court-link-list" id="courtLinkCaseResults" role="listbox"></div>
        <div class="court-link-foot">支持定向检索：案号:（2023）京01民初1号 · 法院:北京 · 当事人:示七某；从待选案件中选择一条完成关联。</div>
      </section>
    </div>`);
  revealCourtModal();
  setTimeout(() => $('courtLinkCaseSearch')?.focus(), 0);
  const picker = ApexCasePicker.attach({ input: $('courtLinkCaseSearch'), menu: $('courtLinkCaseResults'), request: api, inline: true, value: current,
    onSelect: item => courtConfirmCaseLink(Number(item.id)) });
  await picker.open();
}
function revealCourtModal() {
  requestAnimationFrame(() => requestAnimationFrame(() => {
    const modal = document.querySelector('.court-link-modal:not(.show)');
    if (modal) modal.classList.add('show');
  }));
}
function closeCourtLinkModal() {
  const modal = $('courtLinkModal');
  if (modal) modal.remove();
  state.courtOnline.linkingRecordId = 0;
}
async function courtConfirmCaseLink(caseId) {
  try {
    const target = courtLinkTarget();
    await api(`${CO_API}/${target}/${state.courtOnline.linkingRecordId}/case`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({case_id:Number(caseId)})});
    closeCourtLinkModal(); toast('已关联案件'); await loadCourtOnline();
  } catch(e) { toast(e.message || '关联失败'); }
}
async function courtAddHearingReminder(id) {
  const item = state.courtOnline.items.find(row => Number(row.id) === Number(id));
  if (!item) return;
  if (!Number(item.linked_case_id)) { toast('请先关联本地案件，再添加到开庭提醒'); return; }
  try {
    await api('/api/case-manager/hearings', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        case_id: Number(item.linked_case_id),
        title: item.case_name || item.case_number || '开庭提醒',
        reminder_type: item.hearing_type || '开庭',
        hearing_at: item.hearing_at || '',
        location: item.location || '',
        case_no: item.case_number || '',
        court: item.court_name || '',
        notes: `来源：一张网开庭扫描${(item.case_name || item.case_number || '').trim() ? `\n${(item.case_name || item.case_number).trim()}` : ''}`,
        source_key: `court-hearing:${Number(item.id)}`,
      }),
    });
    toast('已添加到开庭提醒');
    await loadCourtOnline();
  } catch(e) { toast(e.message || '添加失败'); }
}
function courtOpenSpace(id) { const item = state.courtOnline.items.find(row => Number(row.id)===Number(id)); if (item?.case_space_url) window.open(item.case_space_url, '_blank', 'noopener'); }
async function courtLoadChat(id) { try { const r = await api(`${CO_API}/records/${id}/chat`, {method:'POST'}); const lines = (r.items || []).map(item => { if(typeof item==='string') return esc(item); const text=esc(item.content||item.msg||item.text||JSON.stringify(item)); const fileUrl=item.url||item.fileUrl||item.previewUrl||item.downloadUrl||''; const fileName=esc(item.fileName||item.filename||item.name||'预览附件'); return `${text}${fileUrl?`<div><a class="btn" target="_blank" rel="noopener" href="${CO_API}/chat-file-preview?url=${encodeURIComponent(fileUrl)}">${fileName}</a></div>`:''}`; }).join('<hr>') || esc(r.message || '暂无可读取的私信'); $('drawerTitle').textContent='法院私信'; $('drawerBody').innerHTML=`<section class="detail-section"><div class="full-value">${lines}</div></section>`; $('drawerFoot').innerHTML='<button class="btn" onclick="closeEditor()">关闭</button>'; $('drawerMask').classList.add('show');$('drawer').classList.add('show','detail-mode'); } catch(e) { toast(e.message || '私信读取失败'); } }

// 从会话恢复案件详情或系列案后，不能再用默认“案件列表”覆盖已上报的具体名称。
boot().catch(error => {
  window.apexShowStartupState?.(
    '案件工作台未能完成启动',
    error?.message || '请重试连接；如仍无法启动，可重建应用壳。',
    true,
  );
  markCaseManagerInteractive('startup-error');
}).finally(() => {
  if (state.seriesWorkspace) notifySeriesWorkspaceContext();
  else if (state.editing?.tab === 'cases' && state.editing?.item) {
    const item = state.editing.item;
    notifyCaseManagerContext(
      item.title || '当前案件',
      currentCaseManagerPageLabel(),
      { id: item.id, title: item.title }
    );
  } else notifyCaseManagerContext(currentCaseManagerPageLabel());
});

/* ==========================================================
   抽屉展开性能守护：动画窗口期降级玻璃合成
   —— transform 滑动时 backdrop-filter 需每帧重采样整屏背景，
      且背景中的 jm-aurora 无限动画会持续失效该采样，
      叠加 drawer 内十余层毛玻璃小卡导致展开明显掉帧。
   —— 监听 #drawer 类名变化标记动画窗口（打开与关闭都覆盖），
      窗口内由 CSS 关闭全部 backdrop-filter；420ms 后恢复。
   ========================================================== */
(function () {
  const drawer = document.getElementById('drawer');
  if (!drawer || drawer.dataset.animGuardReady === '1') return;
  drawer.dataset.animGuardReady = '1';
  let settleTimer = null;
  const setFlag = (name, on) => document.body.classList.toggle(name, on);
  new MutationObserver(() => {
    const open = drawer.classList.contains('show');
    setFlag('drawer-open', open);
    setFlag('drawer-animating', true);
    if (settleTimer) clearTimeout(settleTimer);
    settleTimer = setTimeout(() => { settleTimer = null; setFlag('drawer-animating', false); }, 420);
  }).observe(drawer, { attributes: true, attributeFilter: ['class'] });
})();


// Online reading uses the same account and case-picker as the other court tabs.
function courtDownloadProgress(jobId = '') {
  const payload = { type: 'apex:open-court-downloads', version: 1, jobId };
  if (window.parent !== window) window.parent.postMessage(payload, location.origin);
  else window.open('/court-online-downloads' + (jobId ? '?job=' + encodeURIComponent(jobId) : ''), '_blank', 'noopener');
}
function renderCourtReadings(co, status) {
  const counts = {...(co.counts || {}), total: status.record_count, todo: status.todo_count, message: status.message_count, delivery: status.delivery_count, cases: status.case_count, layy: status.layy_count, hearings: status.hearing_count};
  const tabs = courtKindTabs.map(({value,label}) => `<button class="tab ${co.kind===value?'active':''}" data-kind="${value}" onclick="courtSelectKind('${value}')">${label}<span class="tab-count">${Number(counts[value || 'total'] || 0)}</span></button>`).join('');
  const filters = [['','全部状态'],['11800006-2','待审查'],['11800006-3','已通过'],['11800006-5','已失效']].map(([value,label]) => `<button class="btn ${co.readingStatus===value?'primary':''}" onclick="courtReadingFilter('${value}')">${label}</button>`).join('');
  const cards = co.items.map(item => `<article class="court-card">
    <header class="court-card-head"><div class="court-card-title"><span class="court-kind-badge kind-delivery">在线阅卷</span><strong>${esc(item.case_number)}</strong></div><span>${esc(item.status_label)}</span></header>
    <div class="court-card-meta"><span>${esc(item.court_name)}</span>${item.linked_case_id ? `<button class="court-meta-link" onclick="openDetail('cases',${Number(item.linked_case_id)})">已关联：${esc(item.linked_case_title || '案件')}</button>`:''}</div>
    <p class="court-card-body">阅卷有效期：${esc(item.valid_from || '尚未开放')} ${item.valid_until ? '至 '+esc(item.valid_until):''}</p>
    <div class="court-card-actions"><button class="court-action" onclick="courtReadingDetail(${item.id})">申请详情</button><button class="court-action" onclick="courtLinkCase(${item.id},${Number(item.linked_case_id || 0)})">${item.linked_case_id?'重新关联':'关联案件'}</button>
    ${item.can_download ? `<button class="court-action" onclick="courtReadingDirectory(${item.id})">查看卷宗目录</button><button class="court-action primary" onclick="courtReadingDownload(${item.id})">一键打包开放卷宗</button>` : '<span class="court-foot-hint">目前没有有效开放的卷宗</span>'}</div></article>`).join('');
  $('content').innerHTML = `<div class="toolbar"><div class="filters"><div class="court-kind-tabs">${tabs}</div><input class="input search" id="courtSearch" value="${esc(co.q)}" placeholder="搜索案号或法院" oninput="courtSearchInput(this)"></div><span>共 ${co.total} 条</span></div>
    <div class="toolbar"><div class="filters">${filters}</div><div class="filters"><button class="btn" onclick="courtLogin()">登录官网</button><button class="btn" onclick="courtReadingOfficial()">前往官网申请阅卷</button><button class="btn" onclick="courtDownloadProgress()">下载进度</button><button class="btn" onclick="state.courtOnline.readingRefresh=true;loadCourtOnline()">刷新记录</button></div></div>
    ${co.readingWarning ? `<p class="court-card-body" role="status">${esc(co.readingWarning)}</p>`:''}
    <div class="record-list court-online-list">${cards || '<div class="empty">暂无阅卷申请记录，可前往官网办理申请。</div>'}
    <div class="court-card-actions"><button class="btn" ${co.page<=1?'disabled':''} onclick="courtReadingPage(-1)">上一页</button><span>第 ${co.page} 页</span><button class="btn" ${co.page*co.pageSize>=co.total?'disabled':''} onclick="courtReadingPage(1)">下一页</button></div></div>`;
}
function courtReadingFilter(value) { state.courtOnline.readingStatus=value; state.courtOnline.page=1; loadCourtOnline(); }
function courtReadingPage(delta) { state.courtOnline.page+=delta; loadCourtOnline(); }
function courtReadingModal(title, body) {
  $('courtReadingModal')?.remove();
  document.body.insertAdjacentHTML('beforeend', `<div id="courtReadingModal" class="court-link-modal show" role="dialog" aria-modal="true" aria-label="${esc(title)}"><section class="court-link-dialog court-case-detail-dialog"><div class="court-link-head"><strong>${esc(title)}</strong><button class="btn" onclick="closeCourtReadingModal()">关闭</button></div><div class="court-dialog-body" id="courtReadingModalBody">${body}</div></section></div>`);
  $('courtReadingModal').querySelector('button').focus();
}
function closeCourtReadingModal() { $('courtReadingModal')?.remove(); }
async function courtReadingDetail(id) {
  courtReadingModal('阅卷申请详情', '正在加载…');
  try {
    const data = await api(`${CO_API}/readings/${id}/detail`);
    if (!$('courtReadingModalBody')) return;
    $('courtReadingModalBody').innerHTML = `<h3>${esc(data.item.case_number)}</h3><p>${esc(data.item.court_name)}</p><p>申请目的：${esc(data.purpose || '—')}</p><p>申请查阅内容：${esc(data.requested_content || '—')}</p><p>审核意见：${esc(data.review_comment || '—')}</p><h4>申请材料</h4><p>以下文件为申请时提交的材料。</p>${data.materials.map(f=>`<p>PDF · ${esc(f.name)}</p>`).join('')}${data.materials.length ? `<button class="btn" onclick="courtReadingDownload(${id},'application-test')">申请材料打包测试</button>`:''}`;
  } catch(e) { if ($('courtReadingModalBody')) $('courtReadingModalBody').textContent=e.message; }
}
let courtReadingFiles = [];
let courtReadingFilePage = 0;
let courtReadingDirectoryId = 0;
async function courtReadingDirectory(id) {
  courtReadingModal('开放卷宗目录', '正在读取开放目录…');
  try {
    const data = await api(`${CO_API}/readings/${id}/directory`);
    courtReadingFiles=data.files || []; courtReadingFilePage=0; courtReadingDirectoryId=id;
    if (!$('courtReadingModalBody')) return;
    $('courtReadingModalBody').innerHTML=`<p>${esc(data.notice || '仅列出已开放下载的卷宗文件')} · ${courtReadingFiles.length} 个文件</p><div id="courtReadingFiles"></div>`;
    courtReadingRenderFiles();
  } catch(e) { if ($('courtReadingModalBody')) $('courtReadingModalBody').textContent=e.message; }
}
function courtReadingRenderFiles() {
  const el=$('courtReadingFiles'); if (!el) return;
  const start=courtReadingFilePage*50;
  el.innerHTML=courtReadingFiles.slice(start,start+50).map((f,i)=>`<div class="court-card-actions"><span style="flex:1">${esc(f.relative_path)} · ${f.size_bytes===null?'大小待确认':(f.size_bytes/1024/1024).toFixed(2)+' MB'}</span><button class="btn" onclick="courtReadingDownloadFile(${start+i})">下载</button></div>`).join('') + (courtReadingFiles.length ? `<div class="court-card-actions"><button class="btn" ${start===0?'disabled':''} onclick="courtReadingFilePage--;courtReadingRenderFiles()">上一页</button><button class="btn" ${start+50>=courtReadingFiles.length?'disabled':''} onclick="courtReadingFilePage++;courtReadingRenderFiles()">下一页</button><button class="btn primary" onclick="courtReadingDownload(${courtReadingDirectoryId})">打包全部开放卷宗</button></div>`:'');
}
function courtReadingDownloadFile(index) { courtReadingDownload(courtReadingDirectoryId,'dossier',[courtReadingFiles[index].remote_id]); }
async function courtReadingDownload(id, source='dossier', fileIds=null) {
  try {
    const body={source}; if(fileIds) body.file_ids=fileIds;
    const data=await api(`${CO_API}/readings/${id}/downloads`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    toast('下载任务已创建'); courtDownloadProgress(data.id);
  } catch(e) { toast(e.message || '无法创建下载任务'); }
}
document.addEventListener('keydown', event=>{if(event.key==='Escape') closeCourtReadingModal();});

async function courtReadingOfficial() { try { await api(`${CO_API}/browser/open-reading`,{method:'POST'}); } catch(e) { toast(e.message || '请先登录法院官网'); } }

// Each persisted reminder owns its own local shortcuts, independent of case folders.
function matterLocalLinksSection(tab, id) {
  return `<section class="detail-section matter-local-links" id="matterLocalLinks" data-matter="${esc(tab)}" data-item-id="${Number(id)}"><h3>本地文件与文件夹</h3><p class="muted">正在读取绑定…</p></section>`;
}
function currentMatterLinks(tab, id) {
  const host = $('matterLocalLinks');
  return host?.dataset.matter === tab && Number(host.dataset.itemId) === Number(id) ? host : null;
}
async function loadMatterLocalLinks(tab, id) {
  const host = currentMatterLinks(tab, id);
  if (!host) return;
  if (isOfflineReadonly()) { host.innerHTML = '<h3>本地文件与文件夹</h3><p class="muted">请联网后在本机 Stella 中打开或管理绑定。</p>'; return; }
  try {
    const data = await api(`/api/case-manager/matters/${tab}/${id}/local-links`, {bypassOffline:true});
    if (currentMatterLinks(tab, id) !== host) return;
    host.innerHTML = `<h3>本地文件与文件夹</h3><p class="muted">只关联本事项。点击打开原文件或文件夹；解除绑定保留原文件。</p>
      <div class="record-list">${data.items.map(link => `<article class="record-card"><div class="record-card-head"><button type="button" class="btn" ${link.exists ? '' : 'disabled'} onclick="openMatterLocalLink('${tab}',${id},${Number(link.id)})">${esc(link.kind === 'folder' ? '文件夹' : '文件')} · ${esc(link.name)}</button><button type="button" class="btn" onclick="removeMatterLocalLink('${tab}',${id},${Number(link.id)})">解除绑定</button></div><p class="matter-local-path">${esc(link.path)}</p>${link.exists ? '' : '<p class="danger">原位置不存在，请重新绑定。</p>'}</article>`).join('') || '<p class="muted">尚未绑定本地文件或文件夹。</p>'}</div>
      <div class="matter-local-bind-actions"><button class="btn" type="button" onclick="selectMatterLocalLink('${tab}',${id},'file',this)">绑定文件</button><button class="btn" type="button" onclick="selectMatterLocalLink('${tab}',${id},'folder',this)">绑定文件夹</button></div>
      <div class="matter-local-path-entry"><label for="matterLocalPath">或粘贴本地绝对路径</label><input class="input" id="matterLocalPath" placeholder="/Users/…/文件或文件夹"><button class="btn" type="button" onclick="saveMatterLocalLink('${tab}',${id},null,this)">绑定路径</button></div>`;
  } catch (e) { if (currentMatterLinks(tab,id) === host) host.innerHTML = `<h3>本地文件与文件夹</h3><p class="muted">${esc(e.message || '读取失败')}</p>`; }
}
async function saveMatterLocalLink(tab, id, path = null, button = null) {
  path = path || $('matterLocalPath')?.value?.trim();
  if (!path) return toast('请选择文件或文件夹，或粘贴本地绝对路径');
  if (button) button.disabled = true;
  try {
    await api(`/api/case-manager/matters/${tab}/${id}/local-links`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({path})});
    toast('已绑定到本事项');
    await loadMatterLocalLinks(tab,id);
  } catch(e) { toast(e.message || '绑定失败'); }
  finally { if(button) button.disabled = false; }
}
async function selectMatterLocalLink(tab, id, kind, button) {
  button.disabled = true;
  try {
    const result = await api(`/api/case-manager/matters/${tab}/${id}/local-links/select?kind=${kind}`, {method:'POST'});
    if (!result.cancelled && result.path) await saveMatterLocalLink(tab,id,result.path);
  } catch(e) { toast(e.message || '选择失败，请粘贴路径'); }
  finally { button.disabled = false; }
}
async function openMatterLocalLink(tab, id, linkId) {
  try { await api(`/api/case-manager/matters/${tab}/${id}/local-links/${linkId}/open`, {method:'POST'}); }
  catch(e) { toast(e.message || '打开失败'); await loadMatterLocalLinks(tab,id); }
}
async function removeMatterLocalLink(tab,id,linkId) {
  try {
    await api(`/api/case-manager/matters/${tab}/${id}/local-links/${linkId}`, {method:'DELETE'});
    await loadMatterLocalLinks(tab,id);
  } catch(e) { toast(e.message || '解除绑定失败'); }
}

async function openMatterLocalFiles(tab, id, encodedItem, button = null) {
  if (!requireOnlineAction()) return;
  hideMatterLocalMenu();
  if (button) button.disabled = true;
  try {
    const data = await api(`/api/case-manager/matters/${tab}/${id}/local-links`, {bypassOffline:true});
    const links = data.items || [];
    if (!links.length) {
      await openDetail(tab,id,encodedItem);
      $('matterLocalLinks')?.scrollIntoView({block:'nearest'});
    } else if (links.length === 1 && links[0].exists) {
      await openMatterLocalLink(tab,id,links[0].id);
    } else {
      if (button) button.disabled = false;
      showMatterLocalMenu(tab,id,encodedItem,links,button);
    }
  } catch(e) { toast(e.message || '读取本地文件失败'); }
  finally { if (button) button.disabled = false; }
}
let matterLocalMenuAnchor = null;
function hideMatterLocalMenu(restoreFocus = false) {
  const host = $('matterLocalMenu');
  host?.classList.remove('show');
  matterLocalMenuAnchor?.setAttribute('aria-expanded','false');
  if (restoreFocus && matterLocalMenuAnchor?.isConnected) matterLocalMenuAnchor.focus();
  matterLocalMenuAnchor = null;
}
function showMatterLocalMenu(tab,id,encodedItem,links,button) {
  let host = $('matterLocalMenu');
  if (!host) {
    host = document.createElement('div');
    host.id = 'matterLocalMenu';
    host.className = 'case-folder-menu-host matter-local-menu';
    host.setAttribute('role','dialog');
    host.setAttribute('aria-label','选择要打开的本地文件或文件夹');
    document.body.appendChild(host);
    host.addEventListener('keydown', e => {
      const buttons = [...host.querySelectorAll('button:not(:disabled)')];
      const index = buttons.indexOf(document.activeElement);
      if (e.key === 'Escape') { e.preventDefault(); hideMatterLocalMenu(true); }
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault(); buttons[(index + (e.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length]?.focus();
      }
    });
    host.addEventListener('focusout', () => setTimeout(() => {
      if (!host.contains(document.activeElement)) hideMatterLocalMenu();
    },0));
  }
  // Keep labels as text and attach handlers directly; paths never enter inline code.
  host.replaceChildren();
  links.forEach(link => {
    const entry = document.createElement('button');
    entry.type = 'button'; entry.className = 'btn'; entry.disabled = !link.exists;
    entry.textContent = `${link.kind === 'folder' ? '文件夹' : '文件'} · ${link.name}${link.exists ? '' : '（位置失效）'}`;
    entry.title = link.path;
    entry.addEventListener('click', () => { hideMatterLocalMenu(); openMatterLocalLink(tab,id,link.id); });
    host.appendChild(entry);
  });
  const manage = document.createElement('button');
  manage.type = 'button'; manage.className = 'btn matter-local-manage'; manage.textContent = '管理绑定';
  manage.addEventListener('click', async () => {
    hideMatterLocalMenu(); await openDetail(tab,id,encodedItem);
    $('matterLocalLinks')?.scrollIntoView({block:'nearest'});
  });
  host.appendChild(manage);
  host.classList.add('show');
  matterLocalMenuAnchor = button;
  button?.setAttribute('aria-expanded','true');
  const rect = button?.getBoundingClientRect() || {right:window.innerWidth / 2, top:window.innerHeight / 2, bottom:window.innerHeight / 2};
  host.style.left = `${Math.max(12,Math.min(rect.right-host.offsetWidth,window.innerWidth-host.offsetWidth-12))}px`;
  host.style.top = `${Math.max(12,rect.bottom+6+host.offsetHeight > window.innerHeight-12 ? rect.top-host.offsetHeight-6 : rect.bottom+6)}px`;
  host.querySelector('button:not(:disabled)')?.focus();
}
document.addEventListener('pointerdown', e => {
  const host = $('matterLocalMenu');
  if (host?.classList.contains('show') && !host.contains(e.target) && !e.target.closest('.matter-local-trigger')) hideMatterLocalMenu();
},true);
window.addEventListener('resize', () => hideMatterLocalMenu());
document.addEventListener('scroll', e => {
  if (!$('matterLocalMenu')?.contains(e.target)) hideMatterLocalMenu();
},true);
