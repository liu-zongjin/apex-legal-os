/* Anonymous contact sheet browser checks. No backend or live database is used. */
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict'),acorn=require('acorn');
const {chromium}=require(process.env.STELLA_PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'..'),read=f=>fs.readFileSync(path.join(root,f),'utf8');
const source=read('frontend/case-manager.js'),tree=acorn.parse(source,{ecmaVersion:'latest'});
const names=new Set(['CONTACT_CATEGORIES']);
const declarations=tree.body.filter(n=>(n.type==='FunctionDeclaration'&&!['api','esc','toast'].includes(n.id.name))||(n.type==='VariableDeclaration'&&n.declarations.some(d=>names.has(d.id.name)))).map(n=>source.slice(n.start,n.end)).join('\n');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 try {
 const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.setContent(`<style>${read('frontend/apex-design-tokens.css')}\n${read('frontend/case-manager.css')}</style><main class="drawer show" style="position:static;width:auto;height:auto;transform:none;padding:24px"><section class="detail-section contact-section"><h3 class="case-section-head"><span>联系与备忘</span><button class="case-section-edit" aria-label="编辑联系与备忘">✎</button></h3><div id="mount" style="display:contents"></div></section></main>`);
 await page.addScriptTag({content:`const state={};let notices=[],pending,requests=0;function toast(v){notices.push(v)};function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))};async function api(){requests++;return new Promise(resolve=>pending=resolve)};${declarations}`});
 await page.evaluate(()=>{
 window.fixture={litigation:[{groupId:'anon1',name:'陈法官',phone:'020-81234567',department:'原文待核对'.repeat(180),organization:'示例区人民法院',notes:'仅为界面验证，非真实案件。'.repeat(120)}],client:[{groupId:'anon2',name:'张三',phone:'13800000000',organization:'示例公司'}]};
 window.render=editable=>document.querySelector('#mount').innerHTML=contactTableHtml(fixture,{}, {editable,includeMemo:false});render(false);
 });
 for(const [width,height] of [[1440,900],[1024,768],[600,850]])for(const dark of [false,true]){
 await page.setViewportSize({width,height});await page.evaluate(d=>document.body.classList.toggle('dark-mode',d),dark);
 assert(await page.locator('.contact-row').first().evaluate(el=>el.getBoundingClientRect().height<130));
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 const headers=await page.locator('thead th').allTextContents();assert.deepEqual(headers.slice(1,6),['分类','联系人','电话','审级 / 部门 / 岗位','单位']);
 await page.locator('details summary').first().evaluate(el=>el.click());assert(await page.locator('details').first().evaluate(e=>e.open));
 await page.locator('details summary').first().evaluate(el=>el.click());
 }
 await page.setViewportSize({width:1440,height:900});await page.evaluate(()=>document.body.classList.remove('dark-mode'));
 const alignment=await page.evaluate(()=>{const toolbar=document.querySelector('.contact-toolbar').getBoundingClientRect(), header=document.querySelector('.contact-section h3 > span').getBoundingClientRect();return Math.abs((toolbar.top+toolbar.height/2)-(header.top+header.height/2))});
 assert(alignment<8,'toolbar and section title should share a row');
 const widths=await page.evaluate(()=>({table:document.querySelector('.contact-table-shell').getBoundingClientRect().width,hub:document.querySelector('.contact-section').clientWidth}));
 assert(widths.table>=widths.hub-40,'table should use the full available width');
 const drawerWidth=await page.evaluate(()=>{const drawer=document.createElement('div');drawer.className='drawer detail-mode contact-editing';document.body.append(drawer);const width=drawer.getBoundingClientRect().width;drawer.remove();return width});
 assert(drawerWidth<=1440*.77,'contact editing must leave room for the left card');
 fs.mkdirSync(path.join(root,'.tmp'),{recursive:true});await page.locator('main').screenshot({path:path.join(root,'.tmp/contact-sheet-light.png')});
 await page.evaluate(()=>{render(true);const note=document.querySelector('.contact-notes-input');resizeContactNote(note);if(note.scrollWidth>note.clientWidth+1 || note.clientHeight<60)throw Error('long notes must wrap and expand');});
 await page.evaluate(()=>{render(true);const groups=collectContactGroups();const encoded=serializeContactGroups(groups,'court');const parsed=parseStructuredContactText(encoded,['litigation']);if(parsed.litigation[0].department!==fixture.litigation[0].department || parsed.litigation[0].phone!==fixture.litigation[0].phone || parsed.litigation[0].notes!==fixture.litigation[0].notes)throw Error('contact serialization changed');});
 await page.evaluate(()=>{render(true);document.querySelector('[name=contact_name]').value='张三 020-81234567';document.querySelector('[name=contact_department]').value='旧的错误内容'});
 await page.locator('.contact-ai-btn').first().click();
 await page.evaluate(()=>pending({contact:{name:'张三',phone:'020-81234567',department:'',organization:'',email:'',notes:''}}));
 await page.waitForFunction(()=>!document.querySelector('.contact-ai-btn').disabled);
 assert.equal(await page.locator('[name=contact_department]').first().inputValue(),'');
 assert.equal(await page.locator('.contact-ai-btn svg').first().count(),1);
 await page.locator('.contact-ai-btn').first().click();await page.locator('[name=contact_name]').first().fill('新编辑');
 await page.evaluate(()=>pending({contact:{name:'过时结果'}}));await page.waitForFunction(()=>!document.querySelector('.contact-ai-btn').disabled);
 assert.equal(await page.locator('[name=contact_name]').first().inputValue(),'新编辑');
 await page.evaluate(()=>{let called=false;handleContactSmartKey({key:'Enter',isComposing:true,preventDefault(){called=true}});if(called)throw Error('IME submitted')});
 await page.evaluate(()=>{render(true);const row=document.querySelector('.contact-row');row.dataset.pinned='true';row.querySelector('[name=contact_role_type]').value='承办人';});
 const originalId=await page.locator('.contact-row').first().getAttribute('data-contact-group-id');
 await page.locator('.contact-ai-btn').first().click();
 await page.evaluate(()=>pending({contacts:[{name:'王法官',phone:'020-81234567',department:'一审'},{name:'王法官',phone:'020-87654321',department:'一审'},{name:'李法官',phone:'13900000000',department:'二审'}]}));
 await page.waitForFunction(()=>document.querySelectorAll('.contact-row').length===4);
 assert.equal(await page.locator('.contact-row').first().getAttribute('data-contact-group-id'),originalId);
 assert.deepEqual(await page.locator('[name=contact_phone]').evaluateAll(elements=>elements.map(element=>element.value)),['020-81234567','020-87654321','13900000000','13800000000']);
 assert.deepEqual(await page.locator('[name=contact_department]').evaluateAll(elements=>elements.map(element=>element.value)),['一审','一审','二审','']);
 assert.equal(new Set(await page.locator('.contact-row').evaluateAll(rows=>rows.map(row=>row.dataset.contactGroupId))).size,4);
 assert.equal(await page.locator('.contact-row[data-pinned="true"]').count(),3);
 // Smart add must consume every row, not only the legacy first contact.
 await page.getByLabel('粘贴整段联系人信息').fill('一审 张三 13800000001\n二审 李四 13900000002');
 assert((await page.getByLabel('粘贴整段联系人信息').inputValue()).includes('\n'));
 const requestCount=await page.evaluate(()=>requests);
 await page.getByLabel('粘贴整段联系人信息').press('Shift+Enter');
 assert.equal(await page.evaluate(()=>requests),requestCount);
 await page.getByLabel('粘贴整段联系人信息').fill('匿名测试多人多号');
 await page.getByRole('button',{name:'AI 分列并添加',exact:true}).click();
 await page.evaluate(()=>pending({contacts:[{name:'张三',phone:'13800000001',department:'执行'},{name:'张三',phone:'13800000002',department:'执行'}]}));
 await page.waitForFunction(()=>document.querySelectorAll('.contact-row').length===6);
 assert.deepEqual((await page.locator('[name=contact_phone]').evaluateAll(elements=>elements.map(element=>element.value))).slice(-2),['13800000001','13800000002']);
 await page.getByLabel('搜索联系人').fill('不匹配');assert.equal(await page.locator('.contact-row:visible').count(),0);
 await page.setViewportSize({width:1000,height:800});
 await page.evaluate(()=>{fixture.litigation[0].department='立案庭';fixture.litigation[0].notes='可粘贴完整备注，内容自动换行。';render(true);document.querySelectorAll('.contact-notes-input').forEach(resizeContactNote);});
 await page.locator('.contact-section').screenshot({path:path.join(root,'.tmp/contact-sheet-edit-reviewed.png')});
 assert.deepEqual(errors,[]);console.log('Contact sheet multi-person/multi-phone insertion and smart add, plus: 6 viewport/theme combinations, disclosure, header alignment, split clearing, stale response, icon, IME and search passed');
 } finally {await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
