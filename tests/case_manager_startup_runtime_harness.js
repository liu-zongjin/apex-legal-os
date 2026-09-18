const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(process.argv[2], 'utf8');
const start = source.indexOf('function openOfflineDb(');
const end = source.indexOf('function pendingCaseOps()', start);
assert.ok(start >= 0 && end > start, 'unable to locate IndexedDB startup functions');
const functions = source.slice(start, end);

function contextWith(indexedDB, timeout = 120) {
  const window = { indexedDB, setTimeout, clearTimeout };
  const context = vm.createContext({ window, indexedDB, setTimeout, clearTimeout });
  vm.runInContext(`
    const OFFLINE_DB_STARTUP_TIMEOUT_MS = ${timeout};
    const OFFLINE_DB_NAME = 'legal-kb-case-manager';
    const OFFLINE_DB_VERSION = 1;
    const OFFLINE_STORE = 'snapshots';
    const OFFLINE_KEY = 'latest';
    ${functions}
  `, context);
  return context;
}

async function testOpenWithoutCallbackTimesOut() {
  const context = contextWith({ open() { return {}; } });
  const started = Date.now();
  await assert.rejects(context.openOfflineDb(120), error => error.kind === 'timeout');
  assert.ok(Date.now() - started < 400, 'IndexedDB open timeout exceeded startup budget');
}

async function testBlockedOpenExitsImmediately() {
  const context = contextWith({
    open() {
      const request = {};
      queueMicrotask(() => request.onblocked());
      return request;
    },
  });
  const started = Date.now();
  await assert.rejects(context.openOfflineDb(800), error => error.kind === 'blocked');
  assert.ok(Date.now() - started < 200, 'blocked IndexedDB did not exit promptly');
}

async function testSnapshotReadWithoutCallbackTimesOut() {
  const db = {
    close() {},
    transaction() {
      return { objectStore() { return { get() { return {}; } }; } };
    },
  };
  const context = contextWith({
    open() {
      const request = {};
      queueMicrotask(() => { request.result = db; request.onsuccess(); });
      return request;
    },
  });
  const started = Date.now();
  await assert.rejects(context.readOfflineSnapshot(), error => error.kind === 'timeout');
  assert.ok(Date.now() - started < 400, 'snapshot read timeout exceeded startup budget');
}

(async () => {
  await testOpenWithoutCallbackTimesOut();
  await testBlockedOpenExitsImmediately();
  await testSnapshotReadWithoutCallbackTimesOut();
  process.stdout.write('IndexedDB startup runtime scenarios passed\n');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
