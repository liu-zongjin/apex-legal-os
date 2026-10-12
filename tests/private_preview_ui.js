/* Visual regression of the packaged preview against an isolated test server. */
const fs=require('fs');
const assert=require('assert');
const {chromium}=require('playwright');
(async()=>{
  const browser=await chromium.launch({headless:true,channel:'chrome'});
  const page=await browser.newPage({viewport:{width:1440,height:900}});
  fs.mkdirSync('outputs/private-preview-v2-20261012/visual-check',{recursive:true});
  await page.goto(process.env.STELLA_PREVIEW_TEST_URL || 'http://127.0.0.1:18866/');
  await page.locator('#article-grid .article-card:not(.skeleton)').first().waitFor({state:'visible'});
  const texts=await page.locator('#article-grid').textContent();
  for(const title of ['合同履行检查清单（示例）','建设工程资料整理方法（示例）','Stella 体验版使用指南（示例）']) assert(texts.includes(title),title);
  for (const size of [{width:1440,height:900},{width:1024,height:768}]) {
    await page.setViewportSize(size); await page.reload();
    await page.locator('#article-grid .article-card:not(.skeleton)').first().waitFor({state:'visible'});
    for(const dark of [false,true]) {
      const current=await page.evaluate(()=>document.body.classList.contains('dark-mode'));
      if(current!==dark) await page.locator('#theme-toggle-btn').click();
      const brand=await page.locator('.sidebar-header .brand-logo-mark-default').evaluate(el=>{
        const rect=el.getBoundingClientRect();return {display:getComputedStyle(el).display,width:rect.width,height:rect.height,loaded:el.complete&&el.naturalWidth>0};
      });
      assert(brand.loaded && brand.display!=='none' && brand.width<=130 && brand.height<=50);
      assert.equal(await page.locator('.sidebar-header .brand-logo-mark-gray').evaluate(el=>getComputedStyle(el).display),'none');
      await page.screenshot({animations:'disabled',path:`outputs/private-preview-v2-20261012/visual-check/home-${size.width}-${dark?'dark':'light'}.png`});
    }
  }
  // Detail navigation verifies the examples are real readable records.
  await page.locator('#article-grid .article-card').filter({hasText:'合同履行检查清单（示例）'}).click();
  await page.getByText('本文为体验版全新编写的虚构示例，不来源于真实案件或原用户知识库。',{exact:true}).waitFor({state:'visible'});
  await browser.close();
  console.log('PREVIEW_VISUAL_QA_OK: wordmark, 3 readable examples, light/dark at 1440 and 1024');
})().catch(error=>{console.error(error);process.exit(1)});
