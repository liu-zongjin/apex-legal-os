// Exercise the real host and menu, including the fixed body portal used on phones.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
module.exports = async function checkEfficiencyMenu(page, engine) {
  const output = process.env.STELLA_TOOLS_QA_OUTPUT;
  if (output) fs.mkdirSync(output, {recursive:true});
  const widths = [320, 390, 430, 768, 1024, 1440];
  for (const width of widths) {
    for (const dark of [false,true]) {
      await page.setViewportSize({width,height:width===320?568:844});
      const mobile=await page.evaluate(()=>matchMedia('(max-width: 768px), (max-width: 1024px) and (hover: none) and (pointer: coarse)').matches);
      await page.evaluate(dark => document.body.classList.toggle('dark-mode',dark),dark);
      await page.evaluate(()=>openToolsMenu());
      await page.waitForTimeout(300);
      const bounds = await page.locator('#tools-header').boundingBox();
      const size = page.viewportSize();
      assert(bounds.width>200 && bounds.x>=-1 && bounds.x+bounds.width<=width+1, JSON.stringify({width,bounds}));
      if (mobile) {
        assert(Math.abs(bounds.width-width)<2 && Math.abs(bounds.height-size.height)<2 && bounds.y===0,JSON.stringify({width,bounds}));
        assert.equal(await page.locator('#tools-popup').getAttribute('aria-modal'),'true');
        const close = page.locator('.tools-popup-close-mobile');
        assert(await close.isVisible());
        await page.locator('#tools-popup-edit-actions button').focus();
        await page.keyboard.press('Shift+Tab');
        assert(await page.locator('#tools-popup').evaluate(n=>n.contains(document.activeElement)),'keyboard focus must stay inside the full-screen menu');
        await page.keyboard.press('Tab');
        assert(await page.locator('#tools-popup-edit-actions button').evaluate(n=>n===document.activeElement),'Tab must wrap back to the first control');
        assert.equal(await page.locator('#tools-popup-categories button').count(),5);
        const initialHead = await page.locator('.tools-popup-head').boundingBox();
        for (const group of ['mail','case','tool','ai','document']) {
          await page.locator(`#tools-popup-categories button`).filter({hasText:({mail:'邮件',case:'案件',tool:'工具',ai:'AI',document:'文书'})[group]}).click();
          const title = page.locator(`[data-tools-group="${group}"] .tools-popup-col-title`);
          const r=await title.boundingBox();
          const scroller=await page.locator('#tools-popup-list').boundingBox();
          assert(r.y>=scroller.y-2 && r.y<scroller.y+scroller.height,JSON.stringify({width,group,r,scroller}));
        }
        assert.deepEqual(await page.locator('.tools-popup-head').boundingBox(),initialHead,'header must stay fixed while content scrolls');
        const overflow=await page.locator('#tools-popup-list').evaluate(n=>n.scrollWidth>n.clientWidth+2);
        assert(!overflow,'tool cards overflow horizontally');
        await page.locator('#tools-popup-categories button').first().click();
        // Editing uses the same persisted settings controls; it stays inside the full-screen header.
        await page.locator('#tools-popup-edit-actions button').click();
        const cancel=page.locator('#tools-popup-edit-actions button').filter({hasText:'取消'});
        assert(await cancel.isVisible());
        const editOverflow=await page.locator('#tools-popup-list').evaluate(n=>n.scrollWidth>n.clientWidth+2);
        assert(!editOverflow,'edit inputs overflow horizontally');
        await cancel.click();
        if(output)await page.screenshot({path:path.join(output,`${engine}-${width}-${dark?'dark':'light'}.png`)});
        await page.keyboard.press('Escape');
        await page.waitForTimeout(250);
        assert.equal(await page.evaluate(()=>window.toolsMenuOpen),false);
        assert.equal(await page.evaluate(()=>!!window.toolsBackgroundState),false);
        assert.equal(await page.locator('#tools-header').evaluate(n=>n.parentElement.id),'tools-anchor');
        // Repeated opens must not leave the underlying workspace inert.
        for(let i=0;i<3;i++)await page.evaluate(()=>{openToolsMenu();closeToolsMenu();openToolsMenu();});
        await close.click();await page.waitForTimeout(250);
        assert.equal(await page.locator('.tab-content-area').evaluate(n=>n.inert),false);
      } else {
        assert(bounds.width<width && bounds.height<size.height,'desktop should remain an anchored menu');
        assert.equal(await page.locator('#tools-popup').getAttribute('aria-modal'),null);
        await page.evaluate(()=>closeToolsMenu());await page.waitForTimeout(700);
      }
    }
  }
  // Resize while open, including the mobile/desktop portal boundary.
  await page.mouse.move(0,0);await page.setViewportSize({width:390,height:844});await page.evaluate(()=>openToolsMenu());
  for(const size of [{width:844,height:390},{width:320,height:568},{width:768,height:600},{width:390,height:844}]) {
    await page.setViewportSize(size);await page.waitForTimeout(50);
    // A synthetic mouse may leave the desktop popup during resize; isolate viewport geometry from desktop hover dismissal.
    await page.evaluate(()=>cancelHideTimer());await page.waitForTimeout(250);
    if(size.width<=768){const r=await page.locator('#tools-header').boundingBox();assert(Math.abs(r.height-size.height)<2,JSON.stringify({size,r,open:await page.evaluate(()=>window.toolsMenuOpen)}));}
  }
  // Launch a real existing tool from the menu; only the fixture service is used.
  await page.locator('[data-tool-id="case_manager"]').click();
  await page.waitForFunction(()=>!window.toolsMenuOpen && document.querySelector('.tab-page.active iframe[src*="case-manager"]'));
  await page.waitForTimeout(250);
  assert.equal(await page.locator('.tab-content-area').evaluate(n=>n.inert),false);
  await page.locator('#tab-bar-home-btn').click();
  console.log(JSON.stringify({efficiencyMenu:engine,passed:true,widths,darkAndLight:true}));
};
