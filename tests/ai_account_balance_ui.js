const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const source = fs.readFileSync('frontend/app.js', 'utf8');
const block = source.slice(source.indexOf('// Balance belongs'), source.indexOf('/** 清理分组标签'));
const badge = {hidden: true, textContent: ''};
const select = {selectedIndex: 0, options: [{dataset: {provider: 'deepseek'}}]};
let visible = true;
const requests = [];
const timers = new Map();
let timerId = 0;
const document = {
  hidden: false,
  getElementById(id) {
    if (id === 'ask-account-balance') return badge;
    if (id === 'ask-model-select') return select;
    return {classList: {contains: () => true}, getClientRects: () => visible ? [1] : []};
  },
  addEventListener() {},
};
const context = vm.createContext({document, window: {addEventListener() {}}, AbortController, Date,
  setTimeout(fn, ms) {timers.set(++timerId, {fn, ms}); return timerId;},
  clearTimeout(id) {timers.delete(id);},
  fetch(url, options) {return new Promise(resolve => requests.push({url, options, resolve}));},
});
vm.runInContext(block, context);
const flush = () => new Promise(resolve => setImmediate(resolve));
const answer = (request, data, ok = true) => request.resolve({ok, json: async () => data});
(async () => {
  context.syncAskAccountBalance(true);
  context.syncAskAccountBalance(true);
  assert.equal(requests.length, 1, 'requests must remain serial');
  answer(requests[0], {ok: true, balance: 0, currency: 'CNY'});
  await flush();
  assert.equal(badge.textContent, '余额 ¥0.00');
  assert.equal(badge.hidden, false);
  assert([...timers.values()].some(x => x.ms === 30000));

  context.syncAskAccountBalance(true);
  const old = requests[1];
  select.options[0].dataset.provider = 'siliconflow';
  context.syncAskAccountBalance(true);
  assert(old.options.signal.aborted);
  assert(badge.hidden, 'old account must clear immediately');
  answer(requests[2], {ok: true, balance: 12.3456, currency: 'CNY'});
  await flush();
  answer(old, {ok: true, balance: 999});
  await flush();
  assert.equal(badge.textContent, '余额 ¥12.3456', 'late response must not replace selected account');

  select.options[0].dataset.provider = 'opencode';
  context.syncAskAccountBalance(true);
  assert(badge.hidden);
  assert.equal(requests.length, 3, 'unsupported APIs must not be queried');
  assert.equal(timers.size, 0);

  select.options[0].dataset.provider = 'deepseek';
  context.syncAskAccountBalance(true);
  answer(requests[3], {ok: true, balance: 'invalid'});
  await flush();
  assert(badge.hidden);
  context.syncAskAccountBalance(true);
  visible = false;
  context.syncAskAccountBalance();
  assert(requests[4].options.signal.aborted);
  assert.equal(timers.size, 1); // only the already-in-flight request's timeout remains
  answer(requests[4], {ok: true, balance: 500});
  await flush();
  assert(badge.hidden);
  assert.equal(timers.size, 0);
  visible = true;
  context.syncAskAccountBalance(true);
  answer(requests[5], null, false);
  await flush();
  assert(badge.hidden, 'HTTP failures must hide balances');
  document.hidden = true;
  context.syncAskAccountBalance();
  assert.equal(timers.size, 0);
  console.log('AI balance: account mapping, zero, precision, races, failures, serial refresh and background pause passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
