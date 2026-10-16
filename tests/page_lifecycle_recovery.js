const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('frontend/apex-page-lifecycle.js', 'utf8');

function fixture(embedded = false, initiallyVisible = true) {
  const events = {}, windowEvents = {}, classes = new Set(), timers = [];
  const classList = { toggle(name, value) { value ? classes.add(name) : classes.delete(name); } };
  const document = { visibilityState: initiallyVisible ? 'visible' : 'hidden', readyState: 'complete',
    documentElement: { classList }, body: { classList },
    addEventListener(name, fn) { events[name] = fn; } };
  const window = { addEventListener(name, fn) { windowEvents[name] = fn; },
    dispatchEvent() {}, postMessage() {}, setInterval(fn) { timers.push(fn); return timers.length; } };
  window.parent = embedded ? { postMessage() {} } : window;
  vm.runInNewContext(source, { window, document, location:{origin:'http://localhost'}, CustomEvent: function() {} });
  return { window, document, classes, timers,
    visible(value) { document.visibilityState = value ? 'visible' : 'hidden'; events.visibilitychange(); },
    host(active) { windowEvents.message({ source: window.parent, origin: 'http://localhost',
      data: { type: 'apex:page-visibility', version: 1, active } }); } };
}

for (const embedded of [false, true]) {
  const f = fixture(embedded), changes = [];
  f.window.ApexLifecycle.onChange(value => changes.push(value));
  let ticks = 0;
  f.window.ApexLifecycle.interval(() => ticks++, 1000);
  for (let i = 0; i < 30; i++) {
    f.visible(false); f.timers[0]();
    assert.equal(f.window.ApexLifecycle.active, false);
    assert(f.classes.has('apex-page-inactive'));
    f.visible(true); f.timers[0]();
    assert.equal(f.window.ApexLifecycle.active, true, 'foreground must resume without a parent message');
    assert(!f.classes.has('apex-page-inactive'));
  }
  assert.equal(ticks, 30);
  assert.equal(changes.length, 60);
}
const hidden = fixture(false, false);
hidden.visible(true);
assert.equal(hidden.window.ApexLifecycle.active, true, 'initially hidden documents must recover');
const child = fixture(true);
child.host(false); child.visible(false); child.visible(true);
assert.equal(child.window.ApexLifecycle.active, false, 'unselected iframe must remain paused');
child.visible(false); child.host(true);
assert.equal(child.window.ApexLifecycle.active, false, 'selected iframe cannot run while document is hidden');
child.visible(true);
assert.equal(child.window.ApexLifecycle.active, true);
console.log('Page lifecycle recovery: foreground, initial background, iframe selection and polling passed');
