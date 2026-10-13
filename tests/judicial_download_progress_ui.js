const fs = require('fs');
const assert = require('assert');
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({headless:true, channel:process.env.STELLA_UI_BROWSER || 'chrome'});
  const page = await browser.newPage({viewport:{width:1440,height:900}});
  const errors = []; page.on('pageerror', e=>errors.push(e.message));
  const html = fs.readFileSync('frontend/case-manager.html','utf8');
  const drawer = html.slice(html.indexOf('  <div class="drawer-mask"'), html.indexOf('  </aside>', html.indexOf('  <div class="drawer-mask"')) + 10);
  await page.setContent(`<style>${fs.readFileSync('frontend/case-manager.css','utf8')}</style>${drawer}`);
  const source = fs.readFileSync('frontend/case-manager.js','utf8');
  const feature = source.slice(source.indexOf('async function openJudicialMessage(messageId)'), source.indexOf('async function browserJudicialDocument'));
  const timeoutPolicy = source.slice(source.indexOf('function caseManagerApiTimeout('),source.indexOf('async function parseApiResponse('));
  await page.addScriptTag({content:`
    const $ = id=>document.getElementById(id);
    const esc = value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const fmt = value=>value, requireOnlineAction=()=>true;
    const linkifyJudicialMessageText=esc;
    const JM_API='/api/case-manager/judicial-messages', JM_DEST_LABELS={ledger:'案件台账'};
    const state={judicialMessages:{categories:[], selected:null}};
    const ApexCasePicker={load:async()=>[], flatten:()=>[], attach:()=>{}};
    window.ApexLifecycle={active:true};
    window.posts=0; window.polls=0; window.mode='known'; window.resolveDownload=null;
    const toast = value=>{window.lastToast=value;};
    const closeEditor=()=>{$('drawer').classList.remove('show'); resumeJudicialDownloadProgress();};
    async function api(path,options={}) {
      if (path.endsWith('/download-progress')) {
        if (!options.bypassOffline) throw new Error('Progress must bypass offline snapshots');
        window.polls++;
        return {status:'running', phase:'downloading', total_files:2, completed_files:1,
          failed_files:0, filename:'测试证据材料.pdf', received_bytes:50*1024*1024,
          total_bytes:window.mode==='unknown'?0:100*1024*1024};
      }
      if (path.endsWith('/download')) {
        window.posts++;
        return new Promise((resolve,reject)=>{window.resolveDownload=()=>window.mode==='failure'?
          reject(new Error('法院连接中断，请重试')):
          resolve({document:{status:'waiting_confirmation'},progress:{status:'completed',total_files:2,completed_files:2,failed_files:0,filename:'测试证据材料.pdf'}});});
      }
      return {id:8,status_label:'已归类/关联', workflow_status:'confirmed',raw_body:'【测试法院】请查收送达材料。',sender:'12368',received_at:'2026-10-13 09:00',institution:'测试法院',case_numbers:['（2026）测试民终1号'],
        documents:[{id:1,status:'discovered',source_kind:'url',source_url:'https://zxfw.court.gov.cn/zxfw/#/pagesAjkj/app/wssd/index',original_filename:'测试证据材料.pdf'}]};
    }
    ${timeoutPolicy}
    ${feature}
    window.renderFixture=progress=>{judicialDownloads.get('8:1').progress=progress;renderJudicialDownloadProgress();};
  `});
  assert.equal(await page.evaluate(()=>caseManagerApiTimeout('POST',false,'/api/case-manager/judicial-messages/8/documents/1/download')),0);
  assert.equal(await page.evaluate(()=>caseManagerApiTimeout('POST',false,'/api/case-manager/todos')),30000);
  await page.evaluate(()=>openJudicialMessage(8));
  await page.click('[data-jm-download]');
  await page.evaluate(()=>downloadJudicialDocument(8,1)); // duplicate is ignored, does not await the active request
  assert.equal(await page.evaluate(()=>posts),1);
  assert(await page.isDisabled('[data-jm-download]'));
  await page.waitForFunction(()=>document.querySelector('[role="progressbar"]').getAttribute('aria-valuenow')==='75');
  assert((await page.textContent('#jmDownloadProgress')).includes('50.0 MB / 100.0 MB'));
  assert((await page.textContent('#jmDownloadProgress')).includes('已完成 1 / 2 份'));
  fs.mkdirSync('outputs/judicial-download-progress',{recursive:true});
  for (const width of [1440,1024]) {
    await page.setViewportSize({width,height:width===1440?900:768});
    for (const dark of [false,true]) {
      await page.evaluate(value=>document.body.classList.toggle('dark-mode',value),dark);
      await page.locator('#jmDownloadProgress').scrollIntoViewIfNeeded();
      await page.screenshot({animations:'disabled',path:`outputs/judicial-download-progress/${width}-${dark?'dark':'light'}.png`});
      assert(await page.locator('#jmDownloadProgress').evaluate(el=>el.scrollWidth<=el.clientWidth+1));
    }
  }
  await page.evaluate(()=>{mode='unknown';});
  await page.waitForFunction(()=>document.querySelector('.jm-download-progress').classList.contains('is-indeterminate'));
  assert.equal(await page.getAttribute('[role="progressbar"]','aria-valuenow'),null);
  assert((await page.textContent('#jmDownloadProgress')).includes('文件总大小未知'));
  await page.evaluate(()=>{ApexLifecycle.active=false;window.dispatchEvent(new CustomEvent('apex:page-visibility'));});
  const inactiveCalls=await page.evaluate(()=>polls);
  await page.waitForTimeout(900);
  assert.equal(await page.evaluate(()=>polls),inactiveCalls);
  await page.evaluate(()=>{ApexLifecycle.active=true;window.dispatchEvent(new CustomEvent('apex:page-visibility'));});
  await page.waitForFunction(before=>polls>before,inactiveCalls);
  await page.evaluate(()=>closeEditor());
  const closedCalls=await page.evaluate(()=>polls);
  await page.waitForTimeout(900);
  assert.equal(await page.evaluate(()=>polls),closedCalls);
  await page.evaluate(()=>openJudicialMessage(8));
  await page.waitForFunction(before=>polls>before,closedCalls);
  await page.evaluate(()=>resolveDownload());
  await page.waitForFunction(()=>document.querySelector('[role="progressbar"]').getAttribute('aria-valuenow')==='100');
  assert((await page.textContent('#jmDownloadProgress')).includes('文书获取完成'));
  // Partial success must stay visibly distinct from 100% complete success.
  await page.evaluate(()=>renderFixture({status:'partial',total_files:2,completed_files:1,failed_files:1,error:'测试材料二.pdf：下载失败'}));
  assert((await page.textContent('#jmDownloadProgress')).includes('部分文书获取失败'));
  assert.notEqual(await page.getAttribute('[role="progressbar"]','aria-valuenow'),'100');
  await page.evaluate(()=>renderFixture({status:'running',phase:'downloading',total_files:2,filename:'<img src=x onerror=alert(1)>',received_bytes:1,total_bytes:100}));
  assert.equal(await page.locator('#jmDownloadProgress img').count(),0);
  await page.setViewportSize({width:390,height:844});
  assert(await page.locator('#jmDownloadProgress').evaluate(el=>el.scrollWidth<=el.clientWidth+1));
  await page.evaluate(()=>{mode='failure'; downloadJudicialDocument(8,1);});
  await page.waitForFunction(()=>posts===2);
  await page.evaluate(()=>resolveDownload());
  await page.waitForFunction(()=>document.querySelector('#jmDownloadProgress').textContent.includes('文书获取失败'));
  assert((await page.textContent('#jmDownloadProgress')).includes('法院连接中断'));
  assert.equal(errors.length,0,errors.join('\n'));
  await browser.close();
  console.log('Judicial download UI: real counters, unknown size, duplicate clicks, partial/failure states, polling lifecycle, escaping and light/dark responsive layouts passed');
})().catch(error=>{console.error(error);process.exit(1);});
