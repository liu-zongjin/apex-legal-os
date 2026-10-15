/* Anonymous rendering fixture; no live service or database. Run with Playwright on NODE_PATH. */
const fs = require('fs');
const assert = require('assert/strict');
const { chromium } = require('playwright');
const source = fs.readFileSync('frontend/app.js', 'utf8');
const helpers = source.slice(source.indexOf('const ARTICLE_META_PERSON_ICON'), source.indexOf('async function renderArticleDetailInTab'));
const list = source.slice(source.indexOf('function renderArticles(articles)'), source.indexOf('let authoritativeSearchRequestId'));
(async () => {
  const browser = await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL || "chrome"});
  const page = await browser.newPage();
  await page.setContent('<div id="tab-page-main"><div id="article-grid"></div></div><div class="tab-article-detail"><div class="tab-article-meta" id="reader"></div></div><div id="detail-meta" class="detail-meta"></div>');
  for (const path of ['frontend/apex-design-tokens.css', 'frontend/style.css']) await page.addStyleTag({content:fs.readFileSync(path, 'utf8')});
  await page.addStyleTag({content:'.article-grid.list-view {position:static!important;padding:16px!important} #tab-page-main {position:relative!important;inset:auto!important;width:100%!important;display:block!important} .tab-article-detail {position:relative!important;inset:auto!important;height:auto!important;display:block!important} #detail-meta {position:relative!important;inset:auto!important} body {margin:0;display:block!important;height:auto!important;overflow:auto!important}'});
  await page.evaluate(() => {
    window.$ = id => document.getElementById(id);
    window.escapeHtml = x => String(x).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
    window.formatDate = x => x.slice(0,10);
    window.truncate = (s,n) => (s || '').slice(0,n);
    window.highlightText = escapeHtml;
    window._domainsEditorCache = [];
    window.state = {q:'',sortMode:'date',selectedArticleIds:new Set(),articles:[]};
    for (const name of ['handleArticleDragStart','handleArticleDragEnd','handleArticleDragOver','handleArticleDragLeave','handleArticleDrop','bindCardTitleScroll','renderSortModeToggle','renderSavedViews','renderHealthStrip','renderBulkActionBar']) window[name] = () => {};
    window.buildArticleInsightBadges = () => '';
    window.getArticleStatus = () => 'new';
    window.openLocalPath = x => window.openedPath = x;
    window.openLocalFile = x => window.openedPath = x;
    window.articleIsDragging = false;
    window.recordRecentArticle = () => {};
    window.openArticleInTab = () => window.articleOpened = true;
  });
  await page.addScriptTag({content:helpers + list});
  await page.evaluate(() => {
    const article = {id:1,title:'建设工程合同争议裁判要点',summary:'匿名测试文章：核对标签、作者、日期与来源的单行分布。',domains:['建设工程','合同法','知识产权','民事诉讼法'],tags:['作者:测试作者',...Array.from({length:18},(_,i)=>'建设工程 · 合同争议标签'+i)],created_at:'2026-10-08',source_type:'url',source_url:'https://example.com/legal/article'};
    state.articles = [article];
    renderArticles(state.articles);
    const tags = renderArticleDomainTags(article,true) + article.tags.filter(t=>!t.startsWith('作者:')).map(t=>`<span class="meta-tag tag">${t}</span>`).join('');
    for (const id of ['reader','detail-meta']) {
      $(id).innerHTML = renderArticleReaderMeta(tags,renderArticleListProvenance(article,'example.com')+'<button class="article-meta-edit-btn" aria-label="编辑标签">编辑</button>');
      setupArticleTagRows($(id));
    }
  });
  for (const width of [1440,1024]) {
    await page.setViewportSize({width,height:900});
    for (const dark of [false,true]) {
      await page.evaluate(dark=>document.body.classList.toggle('dark-mode',dark),dark);
      await page.mouse.move(width-1,899);
      await page.waitForTimeout(250);
      for (const host of ['.card-domains','#reader','#detail-meta']) {
        const bar = page.locator(host+' .article-metadata-bar');
        const row = bar.locator('.article-tag-row');
        const provenance = bar.locator('.article-reader-provenance');
        const r = await row.boundingBox(), p = await provenance.boundingBox();
        assert(Math.abs(r.y-p.y)<2,host+' metadata must share a row');
        assert(Math.abs(r.width/p.width-2)<0.05,host+' must use 2:1 columns');
        const closed = r.height;
        const clip = await row.locator('.article-tag-viewport').boundingBox();
        const labels = await row.locator('.article-tag-items > *').evaluateAll(els=>els.map(el=>{const r=el.getBoundingClientRect();return {top:r.top,bottom:r.bottom};}));
        const firstLineBottom = Math.max(...labels.filter(label=>label.top < labels[0].bottom).map(label=>label.bottom));
        assert(Math.abs(clip.y + clip.height - firstLineBottom) < 1.1,host+' must clip exactly after the first label row '+JSON.stringify({width,dark,clip,firstLineBottom,labels:labels.slice(0,10),css:await row.getAttribute('style')}));
        assert(labels.filter(label=>label.top >= firstLineBottom).every(label=>label.top >= clip.y+clip.height),host+' must not show a sliver of the next row');
        await row.hover();
        await page.waitForTimeout(240);
        assert((await row.boundingBox()).height>closed+30,host+' hover must expand');
        assert.equal(await provenance.textContent(),'测试作者2026-10-08example.com'+(host==='.card-domains'?'':'编辑'));
        await page.mouse.move(width-1,899);
        await page.waitForTimeout(240);
        assert((await row.boundingBox()).height<=closed+1,host+' leave must collapse');
        const button = row.locator('button');
        await button.focus();
        await page.keyboard.press('Enter');
        await page.waitForTimeout(240);
        assert((await row.boundingBox()).height>closed+30,'keyboard expands');
        await page.keyboard.press('Escape');
        await page.waitForTimeout(240);
        assert((await row.boundingBox()).height<=closed+1,'Escape collapses');
      }
    }
  }
  await page.evaluate(() => {
    document.body.className = 'density-compact';
    renderArticles(state.articles);
  });
  await page.waitForTimeout(240);
  const denseClip = await page.locator('.card-domains .article-tag-viewport').boundingBox();
  const denseRows = await page.locator('.card-domains .article-tag-items > *').evaluateAll(els=>els.map(el=>{const r=el.getBoundingClientRect();return {top:r.top,bottom:r.bottom};}));
  const denseBottom = Math.max(...denseRows.filter(r=>r.top<denseRows[0].bottom).map(r=>r.bottom));
  assert(denseClip.y+denseClip.height <= denseBottom+1,'compact density must not reveal the second row');
  await page.evaluate(()=>document.body.className = '');
  await page.locator('.card-domains a').click({modifiers:['Control']});
  assert.equal(await page.evaluate(()=>!!window.articleOpened),false,'source click must not open reader');
  await page.setViewportSize({width:1440,height:900});
  await page.evaluate(()=>document.body.classList.remove('dark-mode'));
  await page.mouse.move(1439,899);
  await page.waitForTimeout(250);
  await page.screenshot({path:'/tmp/article-metadata-collapsed.png',fullPage:true});
  await page.locator('#reader .article-tag-row').hover();
  await page.waitForTimeout(250);
  await page.screenshot({path:'/tmp/article-metadata-expanded.png',fullPage:true});
  await page.emulateMedia({reducedMotion:'reduce'});
  assert.equal(await page.locator('.article-tag-viewport').first().evaluate(el=>getComputedStyle(el).transitionDuration),'0s');
  await page.evaluate(() => {
    state.articles = [{...state.articles[0],domains:['合同法'],tags:['作者:测试作者'],source_type:'file',source_url:null,source_filename:'示例.docx',source_localpath:'/anonymous/示例.docx'}];
    renderArticles(state.articles);
  });
  assert(await page.locator('.card-domains .article-tag-toggle').isHidden(),'short labels need no disclosure');
  await page.locator('.card-domains button.meta-link').click();
  assert.equal(await page.evaluate(()=>window.openedPath),'/anonymous/示例.docx');
  assert.equal(await page.evaluate(()=>!!window.articleOpened),false,'local source click must not open reader');
  await browser.close();
  console.log('PASS: list + both readers, 2:1 layout, hover/leave, keyboard/Escape, source click, resize, light/dark, reduced motion');
})().catch(error=>{console.error(error);process.exit(1)});
