const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync('frontend/case-manager.js', 'utf8');
const start = source.indexOf('async function openMatterLocalFiles(');
const end = source.indexOf('\nlet matterLocalMenuAnchor', start);
const calls = [];
let items = [];
const context = vm.createContext({
  requireOnlineAction: () => true,
  hideMatterLocalMenu: () => {},
  api: async () => ({items}),
  openDetail: async (...args) => calls.push(['detail',...args]),
  openMatterLocalLink: async (...args) => calls.push(['open',...args]),
  showMatterLocalMenu: (...args) => calls.push(['choose',...args]),
  $: () => ({scrollIntoView: () => {}}),
  toast: (...args) => calls.push(['error',...args]),
});
vm.runInContext(source.slice(start,end),context);
(async () => {
  const button = {disabled:false};
  items = [{id:7,exists:true}];
  await context.openMatterLocalFiles('hearings',42,'fixture',button);
  assert.deepEqual(calls,[['open','hearings',42,7]]);
  assert.equal(button.disabled,false);
  calls.length=0; items = [{id:7,exists:true},{id:8,exists:true}];
  await context.openMatterLocalFiles('todos',42,'fixture',button);
  assert.equal(calls[0][0],'choose');
  assert.equal(calls.length,1);
  calls.length=0;items=[];
  await context.openMatterLocalFiles('preservations',42,'fixture',button);
  assert.deepEqual(calls,[['detail','preservations',42,'fixture']]);
  calls.length=0;items=[{id:7,exists:false}];
  await context.openMatterLocalFiles('appeals',42,'fixture',button);
  assert.equal(calls[0][0],'choose');
  calls.length=0;context.api = async () => {throw new Error('权限拒绝');};
  await context.openMatterLocalFiles('hearings',42,'fixture',button);
  assert.deepEqual(calls,[['error','权限拒绝']]);
  assert.equal(button.disabled,false);
  console.log('Matter shortcut opening: passed');
})().catch(e => {console.error(e);process.exitCode=1;});
