// Complete production host with anonymous API fixtures. Never force controls visible:
// responsive visibility and the position relative to neighbouring controls matter.
const assert = require('assert'), fs = require('fs'), path = require('path');
module.exports = async function reviewDisplay(page, engine) {
  const output = process.env.STELLA_DISPLAY_QA_OUTPUT || '.tmp/display-review';
  fs.mkdirSync(output, {recursive:true});
  const problems = [], measurements = [];
  const record = (condition, message, data) => { if (!condition) problems.push({message, ...data}); };
  async function checkAction(selector, width, dark) {
    const style=await page.locator(selector).evaluate(el=>{
      const s=getComputedStyle(el);return {color:s.color,background:s.backgroundColor,image:s.backgroundImage,height:el.getBoundingClientRect().height};
    });
    record((style.background!=='rgba(0, 0, 0, 0)'||style.image!=='none')&&style.height>=32,'Action button has lost its component styling',{selector,width,dark,style});
  }
  async function snapshot(name) { await page.screenshot({path:path.join(output, `${engine}-${name}.png`)}); }
  async function checkSurface(selector, label, width, dark) {
    const element = page.locator(selector);
    await element.waitFor({state:'visible'});
    await page.waitForTimeout(350);
    const result = await element.evaluate(root => {
      const r=root.getBoundingClientRect();
      const visible=e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return s.visibility!=='hidden'&&s.display!=='none'&&r.width>0&&r.height>0;};
      const clipped=[...root.querySelectorAll('button,input,textarea,[role="tab"]')].filter(visible).filter(e=>{
        // A deliberately scrollable category strip and the closed off-canvas
        // history rail are not unbounded content. Check the selected tab separately.
        if(e.closest('.settings-sidebar, .submit-source-tabs'))return false;
        if(e.closest('.ask-history-sidebar')&&!root.classList.contains('history-open'))return false;
        const r=e.getBoundingClientRect();return r.left< -1||r.right>innerWidth+1;
      }).map(e=>({label:(e.getAttribute('aria-label')||e.textContent).trim().slice(0,40),class:e.className}));
      return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height,
        opacity:parseFloat(getComputedStyle(root).opacity),scrollWidth:root.scrollWidth,clientWidth:root.clientWidth,clipped};
    });
    measurements.push({label,width,dark,...result});
    record(result.left>=-1 && result.right<=width+1, 'Surface exceeds viewport', {label,width,dark,result});
    record(result.scrollWidth<=result.clientWidth+2, 'Surface has horizontal overflow', {label,width,dark,result});
    record(result.clipped.length===0, 'Controls extend beyond viewport', {label,width,dark,result});
    record(result.opacity>=.99,'Surface remains translucent after opening',{label,width,dark,result});
    await snapshot(`${label}-${width}-${dark?'dark':'light'}`);
  }
  for (const width of [1440,1024,390,320]) for (const dark of [false,true]) {
    await page.setViewportSize({width,height:width<=390?844:900});
    await page.mouse.move(0,0);
    await page.evaluate(dark=>{document.body.classList.toggle('dark-mode',dark);},dark);
    await page.evaluate(()=>openToolsMenu());
    await page.waitForTimeout(400);
    const mobile=await page.evaluate(()=>document.getElementById('tools-header').classList.contains('tools-mobile-fullscreen'));
    const head=await page.locator('.tools-popup-head').evaluate(root=>{
      const rect=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height};};
      const actions=root.querySelector('.tools-popup-edit-actions'),close=root.querySelector('.tools-popup-close-mobile');
      return {root:rect(root),heading:rect(root.querySelector('.tools-popup-heading')),actions:rect(actions),close:rect(close),closeDisplay:getComputedStyle(close).display};
    });
    measurements.push({label:'efficiency-header',width,dark,mobile,...head});
    if(!mobile) {
      record(head.closeDisplay==='none','Desktop shows a mobile-only close control',{width,dark,head});
      record(head.root.right-head.actions.right<=20,'Efficiency edit action is not at the right edge',{width,dark,head});
    }
    record(head.actions.x>=head.heading.right-1,'Efficiency title and actions overlap',{width,dark,head});
    if(mobile) {
      const closeFont=await page.locator('.tools-popup-close-mobile').evaluate(e=>parseFloat(getComputedStyle(e).fontSize));
      record(closeFont>=20,'Mobile close glyph inherits small body font',{width,dark,closeFont});
    }
    await checkSurface('#tools-popup','efficiency',width,dark);
    if(width===1440&&!dark)await page.locator('#tools-popup').screenshot({path:path.join(output,`${engine}-efficiency-popup.png`)});
    await page.locator('#tools-popup-edit-actions button').click();
    await page.waitForTimeout(150);
    await checkSurface('#tools-popup','efficiency-edit',width,dark);
    await page.locator('#tools-popup-edit-actions button').filter({hasText:'取消'}).click();
    await page.evaluate(()=>closeToolsMenu({lockHover:true}));
    await page.waitForTimeout(400);
    for(const section of ['workspace','appearance','backup']) {
      await page.evaluate(section=>openSettingsModal(section),section);
      await page.waitForTimeout(100);
      await checkSurface('.settings-modal','settings-'+section,width,dark);
      const selected=await page.locator('.settings-nav-item.active').boundingBox();
      const strip=await page.locator('.settings-sidebar').boundingBox();
      record(selected.x>=strip.x-1&&selected.x+selected.width<=strip.x+strip.width+1,
        'Selected settings category is outside its visible strip',{width,dark,section,selected,strip});
      await page.evaluate(()=>closeSettingsModal());
    }
    await page.evaluate(()=>openOfflineCacheManager());
    await checkSurface('.offline-cache-modal','offline-cache',width,dark);
    await checkAction('#offline-cache-refresh-btn',width,dark);
    await page.evaluate(()=>closeOfflineCacheManager());
    await page.evaluate(()=>showUploadFilesModal());
    await checkSurface('.storage-submodal-error','upload-error',width,dark);
    await checkAction('.storage-submodal-error .btn-primary',width,dark);
    await checkAction('.storage-submodal-error .btn-secondary',width,dark);
    await page.evaluate(()=>closeUploadFilesModal());
    await page.evaluate(()=>openPagesOverview());
    await checkSurface('#open-pages-overview','page-overview',width,dark);
    await page.evaluate(()=>closeOpenPagesOverview());
    await page.evaluate(()=>{
      state.currentArticle={id:77,title:'匿名显示检查',tags:[],domains:[],subcategory_ids:[],content:'<p>匿名正文</p>'};
    });
    for(const [open,selector,close] of [
      ['openSubmitModal','#submit-modal-card','closeSubmitModal'],
      ['openEditTagsModal','.article-tags-editor','closeEditTagsModal'],
      ['openDomainClassificationModal','.domain-classification-modal','closeDomainClassificationModal'],
    ]) {
      await page.evaluate(name=>window[name](),open);
      await checkSurface(selector,open,width,dark);
      await page.evaluate(name=>window[name](),close);
    }
    await page.evaluate(()=>openAskPanel());
    await page.waitForTimeout(300);
    await checkSurface('#ask-panel','ai-panel',width,dark);
    record(await page.locator('#ask-panel').evaluate((el,width)=>el.classList.contains('history-open')===(width>1100),width),
      'History defaults to an overlay on a narrow panel',{width,dark});
    for(const [button,menu,close] of [
      ['#ask-model-picker-btn','#ask-model-menu','closeAskModelMenu'],
      ['#ask-mcp-source-btn','#ask-mcp-source-menu','closeAskMcpMenu'],
      ['#ask-skill-btn','#ask-skill-menu','closeAskSkillMenu'],
    ]) {
      await page.locator(button).click();
      await checkSurface(menu,menu.slice(1),width,dark);
      if(menu==='#ask-mcp-source-menu') {
        await page.locator(`${menu} .ask-mcp-menu-heading`).click();
        record(await page.locator(menu).isVisible(),'Clicking a portalled menu header closes it',{width,dark});
        const item=page.locator(`${menu} [data-mcp-source]`).first();
        const before=await item.getAttribute('aria-checked');
        await item.click();
        record(await item.getAttribute('aria-checked')!==before&&await page.locator(menu).isVisible(),
          'Source multiselect lost its menu state',{width,dark});
        await item.click();
      }
      if(menu==='#ask-model-menu') {
        await page.locator(`${menu} [data-model-value]`).first().click();
        record(!(await page.locator(menu).isVisible()),'Model selection does not dismiss menu',{width,dark});
      }
      await page.evaluate(name=>window[name](),close);
    }
    await page.evaluate(()=>closeAskPanel());
  }
  await page.setViewportSize({width:1440,height:900});
  await page.evaluate(()=>openAskPanel());
  await page.locator('#ask-model-picker-btn').click();
  for(const size of [{width:390,height:844},{width:844,height:390},{width:1440,height:900}]) {
    await page.setViewportSize(size);
    await checkSurface('#ask-model-menu','model-menu-resized',size.width,false);
  }
  await page.evaluate(()=>{closeAskModelMenu();closeAskPanel();});
  fs.writeFileSync(path.join(output,`${engine}-measurements.json`),JSON.stringify({problems,measurements},null,2));
  assert.deepEqual(problems,[],JSON.stringify(problems,null,2));
  console.log(`${engine}: production menus, edit state, settings, cache, overview and AI panel passed at 4 widths in light/dark`);
};
