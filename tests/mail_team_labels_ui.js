const fs=require('fs'),path=require('path'),http=require('http'),assert=require('assert');
const {chromium}=require('playwright');
(async()=>{
 const frontend=path.resolve('frontend'); let members=[{id:1,name:'成员甲'},{id:2,name:'成员乙'}],labels={},writes=[],fail=false;
 const mails=[{uid:'10',from:'匿名发件人 <a@example.test>',subject:'合同资料',date:'2026-10-13 09:00',read:true},{uid:'11',from:'匿名发件人 <b@example.test>',subject:'会议通知',date:'2026-10-12 09:00',read:false},{uid:'12',from:'匿名发件人 <c@example.test>',subject:'英文通知',date:'2026-10-11 09:00',read:true,mostly_english:true}];
 const json=(res,data,status=200)=>{res.writeHead(status,{'content-type':'application/json'});res.end(JSON.stringify(data));};
 const server=http.createServer(async(req,res)=>{
  const u=new URL(req.url,'http://localhost');
  if(u.pathname.startsWith('/static/')){let p=path.join(frontend,path.basename(u.pathname));if(fs.existsSync(p)){res.writeHead(200,{'content-type':p.endsWith('.js')?'text/javascript':'text/css'});res.end(fs.readFileSync(p));}else{res.writeHead(404);res.end();}return;}
  if(u.pathname==='/qq-mail'){res.writeHead(200,{'content-type':'text/html'});res.end(fs.readFileSync(path.join(frontend,'qq-mail.html')));return;}
  if(u.pathname==='/api/qq-mail/status')return json(res,{connected:true});
  if(u.pathname==='/api/qq-mail/mails')return json(res,{mails});
  if(u.pathname==='/api/qq-mail/team-labels'){
    if(req.method==='GET')return json(res,{members,assignments:u.searchParams.get('folder')==='inbox'?labels:{}});
    let body='';for await (const c of req)body+=c;body=JSON.parse(body); writes.push(body);
    if(fail)return json(res,{detail:'保存失败'},500);
    body.uids.forEach(uid=>{let m=mails.find(m=>m.uid===uid),member=members.find(m=>m.id===body.member_id);if(!member)delete labels[uid];else labels[uid]={member_id:member.id,member_name:member.name,identity:{date:m.date,from:m.from,subject:m.subject}};});
    return json(res,{assignments:labels,updated_count:body.uids.length});
  }
  if(u.pathname.match(/\/api\/qq-mail\/mails\/\d+$/)){let mail=mails.find(m=>m.uid===u.pathname.split('/').pop());return json(res,{...mail,body_text:'匿名测试正文',attachments:[],body_render_version:2});}
  return json(res,{});
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});const page=await browser.newPage({viewport:{width:1440,height:900}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const url=`http://127.0.0.1:${server.address().port}/qq-mail?account=netease_exmail`;
 const choose=async(name)=>{await page.locator('#team-menu').getByRole('menuitemradio',{name,exact:true}).click();await page.waitForFunction(()=>document.getElementById('team-menu').hidden);};
 try{
  await page.goto(url);await page.locator('.mail-item').nth(2).waitFor();
  await page.locator('[data-uid="10"] .mail-select').check();await page.locator('[data-uid="11"] .mail-select').check();
  assert.equal(await page.locator('#detail-content').isVisible(),false);
  await page.locator('#team-assign-btn').click();await choose('成员甲');await page.waitForFunction(()=>document.querySelectorAll('.team-chip').length===2);
  assert.deepEqual(writes.at(-1).uids,['10','11']);
  await page.reload();await page.waitForFunction(()=>document.querySelectorAll('.team-chip').length===2);
  await page.locator('[data-uid="12"] .mail-open').click({button:'right'});await choose('成员乙');await page.waitForFunction(()=>document.querySelectorAll('.team-chip').length===3);
  await page.locator('#team-filter-btn').click();await choose('成员甲');assert.equal(await page.locator('.mail-item').count(),2);
  await page.locator('#unread-check').check();await page.waitForFunction(()=>document.querySelectorAll('.mail-item').length===1);
  await page.locator('#unread-check').uncheck();await page.waitForFunction(()=>document.querySelectorAll('.mail-item').length===2);
  await page.locator('#team-select-all').check();await page.locator('[data-uid="10"] .mail-open').click({button:'right'});await choose('成员乙');await page.waitForFunction(()=>document.querySelectorAll('.mail-item').length===0);assert.equal(writes.at(-1).uids.length,2);
  await page.locator('#team-filter-btn').click();await choose('全部成员');
  await page.locator('[data-uid="10"] .mail-open').click();await page.locator('#detail-team-btn').click();await choose('取消成员标注');await page.waitForFunction(()=>document.querySelectorAll('.team-chip').length===2);
  await page.locator('#team-filter-btn').click();await choose('未标注');assert.equal(await page.locator('.mail-item').count(),1);
  await page.locator('#team-filter-btn').click();await choose('全部成员');
  fail=true;await page.locator('[data-uid="10"] .mail-select').check();await page.locator('#team-assign-btn').click();await choose('成员甲');await page.locator('#toast').filter({hasText:'保存失败'}).waitFor();assert.equal(await page.locator('.team-chip').count(),2);fail=false;
  mails[1].subject='UID重用的新邮件';await page.locator('#refresh-btn').click();await page.waitForFunction(()=>document.querySelectorAll('.team-chip').length===1);
  mails[1].subject='会议通知';await page.locator('#refresh-btn').click();await page.waitForFunction(()=>document.querySelectorAll('.team-chip').length===2);
  members[0].name='成员甲新名';await page.locator('#team-filter-btn').click();await page.locator('#team-menu').getByRole('menuitemradio',{name:'成员甲新名',exact:true}).waitFor();await page.keyboard.press('Escape');
  assert.equal(await page.locator('#team-menu').isVisible(),false);
  for (const [width,height,dark] of [[1440,900,false],[1024,768,false],[1440,900,true],[1024,768,true]]){
    await page.setViewportSize({width,height});await page.evaluate(dark=>{document.documentElement.classList.toggle('dark-mode',dark);document.body.classList.toggle('dark-mode',dark);},dark);
    await page.locator('#team-filter-btn').click();await page.locator('#team-menu').getByRole('menuitemradio',{name:'全部成员',exact:true}).waitFor();
    assert(await page.evaluate(()=>{let r=document.getElementById('team-menu').getBoundingClientRect();return r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight;}));
    await page.locator('#toast').evaluate(el=>el.classList.remove('show'));
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.screenshot({path:`/tmp/mail-team-${width}-${dark?'dark':'light'}.png`});await page.keyboard.press('Escape');
  }
  await page.locator('[data-folder="sent"]').click();await page.waitForFunction(()=>document.querySelectorAll('.team-chip').length===0);assert.equal(await page.locator('#team-assign-btn').isEnabled(),false);
  assert.deepEqual(errors,[]);console.log('Mail member UI: bulk, right-click, detail, filtering, refresh, error rollback, live members, keyboard, account/folder scope, light/dark layouts passed');
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);process.exit(1)});
