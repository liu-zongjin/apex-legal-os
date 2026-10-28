const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const acorn = require('acorn');
const source = fs.readFileSync('frontend/case-manager.js', 'utf8');
const names = ['parseDateLoose','filterDue','getReminderSortValue','compareReminderItems','groupSeriesReminderItems','getDueValue','reminderDaysLeft','isItemOverdue','isOldOverdue','dueClass','remainingDaysHtml','reminderRowsHtml','toggleArchivedOverdue','listHeroStatusItems','listStatusItem','esc','setListDue','setHideOverdue'];
const functions = acorn.parse(source, {ecmaVersion:'latest'}).body.filter(n => n.type === 'FunctionDeclaration' && names.includes(n.id.name)).map(n => source.slice(n.start,n.end)).join('\n');
class FixedDate extends Date {
  constructor(...args) { super(...(args.length ? args : [2026,9,27,12,0,0])); }
}
const context = vm.createContext({Date:FixedDate, console});
vm.runInContext(`
const state={due:'',hideOverdue:false}; let activeTab='hearings', loads=0;
const localStorage={setItem(){}};
const document={querySelectorAll(){return []}};
function loadList(){loads++} function renderTable(){} function renderMobileFilters(){}
function offlineStatusText(){return '已缓存'}
function rowHtml(item, archived=false){return '<tr data-id="'+item.id+'"'+(archived?' class="archived-overdue"':'')+'></tr>'}
${functions}
`,context);
function run(code){return vm.runInContext(code,context)}
assert.equal(run("reminderDaysLeft('2026-10-27')"),0);
assert.equal(run("reminderDaysLeft('2026-10-26 23:59')"),-1);
assert.equal(run("isItemOverdue({hearing_at:'2026-10-27'})"),false);
assert.equal(run("isItemOverdue({hearing_at:'2026-10-26'})"),true);
assert.equal(run("isItemOverdue({remind_at:'2026-10-26'},'todos')"),true);
assert.equal(run("isOldOverdue('2026-10-12')"),false);
assert.equal(run("isOldOverdue('2026-10-11')"),true);
assert.equal(run("dueClass('2026-10-27')"),'');
assert.equal(run("reminderDaysLeft('invalid')"),null);
assert.equal(run("filterDue([{remind_at:'2026-10-26'},{remind_at:'2026-10-27'},{remind_at:'2026-11-03'},{remind_at:'2026-11-04'}], '7d').length"),2);
assert.equal(run("filterDue([{remind_at:'2026-10-26'},{remind_at:'2026-10-27'}], 'overdue').length"),1);
const fixtures=[{id:8,hearing_at:''},{id:2,hearing_at:'2026-10-12 17:30'},{id:5,hearing_at:'2026-11-01'},{id:4,hearing_at:'2026-10-27 14:00'},{id:1,hearing_at:'2026-10-01'},{id:3,hearing_at:'2026-10-12 09:30'},{id:7,hearing_at:'invalid'},{id:6,hearing_at:'2026-10-27 09:00'}];
context.fixtures=fixtures;
assert.equal(run("groupSeriesReminderItems(fixtures,'hearings').map(x=>x.id).join(',')"),'1,3,2,6,4,5,8,7');
assert.equal(fixtures[0].id,8,'sorting must not mutate stored records');
for (const [tab,field] of [['todos','remind_at'],['preservations','deadline_at'],['appeals','deadline_at']]) {
  context.typedFixtures=fixtures.map(({hearing_at,...item})=>({...item,[field]:hearing_at}));
  context.testTab=tab;
  assert.equal(run("groupSeriesReminderItems(typedFixtures,testTab).map(x=>x.id).join(',')"),'1,3,2,6,4,5,8,7');
}

const html=run('reminderRowsHtml(fixtures,7)');
assert.ok(html.indexOf('data-id="1"')<html.indexOf('data-id="3"'));
assert.ok(html.includes('aria-expanded="false"'));
assert.ok(html.includes('展开 1 条超过15天'));
const status=run("listHeroStatusItems('hearings',fixtures)");
assert.ok(status.includes('已过期记录'));assert.ok(!status.includes('待处理'));
assert.ok(run("remainingDaysHtml('2026-10-26')").includes('已过期 1'));
run('state.hideOverdue=true');
assert.ok(run("reminderRowsHtml([{id:1,hearing_at:'2026-10-26'}],7)").includes('暂无符合条件'));
run("setListDue('overdue')");assert.equal(run('state.hideOverdue'),false);assert.equal(run('state.due'),'overdue');
run('setHideOverdue(true)');assert.equal(run('state.due'),'');
let visible=false;const rows=[{classList:{toggle(name,value){visible=value}}}];
context.btn={expanded:'false',getAttribute(){return this.expanded},setAttribute(name,value){this.expanded=value},closest(){return {querySelectorAll(){return rows}}}};
run('toggleArchivedOverdue(btn)');assert.equal(visible,true);assert.equal(context.btn.expanded,'true');
run('toggleArchivedOverdue(btn)');assert.equal(visible,false);
console.log('Reminder chronology, historical expansion, status and filtering passed in '+process.env.TZ);
