const assert=require('node:assert/strict'),fs=require('node:fs'),acorn=require('acorn');
const {webkit}=require(process.env.STELLA_PLAYWRIGHT_MODULE||'playwright');
const source=fs.readFileSync('frontend/case-manager.js','utf8');
const names=['esc','fmt','dateOnly','parseDateLoose','getReminderSortValue','compareReminderItems','groupSeriesReminderItems','getDueValue','reminderDaysLeft','isItemOverdue','isOldOverdue','dueClass','remainingDaysHtml','reminderRowsHtml','toggleArchivedOverdue','listHeroStatusItems','listStatusItem','updateListHeroMeta','setListDue','setHideOverdue','hideOverdueToggle','rowHtml','tableColGroup','dateBlock','formatMulti','dueTag','messageSourceBadge','seriesReminderSummary','renderTable','isMobileCaseCardMode','renderMobileRecordList','mobileRecordCard','encodeMobileRecord','mobileDetailClick','compactRecordDate','mobileMoreIcon'];
const functions=acorn.parse(source,{ecmaVersion:'latest'}).body.filter(n=>n.type==='FunctionDeclaration'&&names.includes(n.id.name)).map(n=>source.slice(n.start,n.end)).join('\n');
(async()=>{
const browser=await webkit.launch({headless:true});
const page=await browser.newPage({viewport:{width:1440,height:900}});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.setContent('<div id="content"><div class="jm-seg"><button data-list-due="" onclick="setListDue(\'\')">全部期限</button><button data-list-due="overdue" onclick="setListDue(\'overdue\')">逾期</button><button data-list-due="7d" onclick="setListDue(\'7d\')">7日内</button></div><div id="toggle"></div><div id="listHeroTotal"></div><div id="listHeroStatus"></div><div class="table-wrap"></div></div>');
for(const file of ['apex-design-tokens.css','color-theme.css','case-manager.css'])await page.addStyleTag({content:fs.readFileSync('frontend/'+file,'utf8')});
await page.addScriptTag({content:`
const $=id=>document.getElementById(id);let activeTab='hearings';
const today=new Date();today.setHours(0,0,0,0);
function at(days,time='09:00'){const d=new Date(today);d.setDate(d.getDate()+days);return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')+' '+time}
const records=[{id:1,hearing_at:at(-20)},{id:2,hearing_at:at(-1)},{id:3,hearing_at:at(0,'14:00')},{id:4,hearing_at:at(0,'09:00')},{id:5,hearing_at:at(3)},{id:6,hearing_at:''}].map(x=>({...x,title:'匿名案件 '+x.id,reminder_type:'开庭',location:'示例法庭',court:'示例机构'}));
const state={items:{hearings:records},hideOverdue:false,due:'',offlineReady:true};
function offlineStatusText(){return '已缓存'}function actionButtons(){return '<div class="actions"><button class="btn">查看</button><button class="btn">编辑</button></div>'}function isOfflineReadonly(){return false}function renderMobileFilters(){}function installAxisLockScroller(){}function loadList(){state.items.hearings=groupSeriesReminderItems(records.filter(x=>state.due!=='overdue'||isItemOverdue(x)),activeTab);renderTable()}
${functions}
$('toggle').innerHTML=hideOverdueToggle();loadList();
`});
assert.equal(await page.locator('tr.archived-overdue:visible').count(),0);
await page.getByRole('button',{name:/展开 1 条/}).click();
assert.equal(await page.locator('tr.archived-overdue:visible').count(),1);
assert.deepEqual(await page.locator('tbody tr:not(.archive-toggle-row) .row-title').allTextContents(),['匿名案件 1','匿名案件 2','匿名案件 4','匿名案件 3','匿名案件 5','匿名案件 6']);
assert.equal(await page.locator('th[aria-sort="ascending"]').count(),1);
await page.getByLabel('隐藏已过期').check();
assert.equal(await page.locator('tbody .row-title').count(),4);
await page.getByRole('button',{name:'逾期',exact:true}).click();
assert.equal(await page.getByLabel('隐藏已过期').isChecked(),false);
assert.equal(await page.locator('[data-list-due="overdue"]').getAttribute('aria-selected'),'true');
assert.equal(await page.locator('tbody .row-title').count(),2);
await page.getByRole('button',{name:'全部期限',exact:true}).click();
await page.getByRole('button',{name:/展开 1 条/}).click();
for(const size of [{width:1440,height:900},{width:1024,height:768}]){
 await page.setViewportSize(size);
 for(const dark of [false,true]){await page.evaluate(dark=>document.documentElement.classList.toggle('dark-mode',dark),dark);await page.screenshot({path:'/tmp/stella-reminders-'+size.width+'-'+(dark?'dark':'light')+'.png'});}
}
await page.setViewportSize({width:390,height:844});await page.evaluate(()=>renderTable());
assert.equal(await page.locator('.mobile-record-card').count(),6);
await page.getByLabel('隐藏已过期').check();assert.equal(await page.locator('.mobile-record-card').count(),4);
await page.screenshot({path:'/tmp/stella-reminders-mobile.png'});
assert.deepEqual(errors,[]);await browser.close();console.log('WebKit desktop light/dark, historical expansion, filter state and mobile card checks passed');
})().catch(e=>{console.error(e);process.exit(1)});
