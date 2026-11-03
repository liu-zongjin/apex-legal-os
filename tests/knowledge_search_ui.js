/* Anonymous renderer-only checks: no requests to the user's service or database. */
const fs=require('fs'),assert=require('assert/strict'),acorn=require('acorn');
const {chromium}=require(process.env.STELLA_PLAYWRIGHT_MODULE||'playwright');
const app=fs.readFileSync('frontend/app.js','utf8');
const knowledge=fs.readFileSync('frontend/legal-knowledge.html','utf8');
const tree=acorn.parse(app,{ecmaVersion:'latest'});
function fn(name){const n=tree.body.find(n=>n.type==='FunctionDeclaration'&&n.id.name===name);assert(n,name);return app.slice(n.start,n.end);}
const inline=[...knowledge.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m=>m[1]).find(s=>s.includes('function renderResults'));
const kt=acorn.parse(inline,{ecmaVersion:'latest'});
function kfn(name){const n=kt.body.find(n=>n.type==='FunctionDeclaration'&&n.id.name===name);assert(n,name);return inline.slice(n.start,n.end);}
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try{
  for(const [width,dark] of [[1440,false],[1024,false],[1440,true],[1024,true]]){
   const page=await browser.newPage({viewport:{width,height:900}});const errors=[];
   page.on('pageerror',e=>errors.push(e.message));
   await page.setContent('<main><p id="knowledge-search-feedback" class="knowledge-search-feedback" role="status" hidden></p><div id="article-grid"></div></main>');
   for(const file of ['frontend/apex-design-tokens.css','frontend/style.css'])await page.addStyleTag({content:fs.readFileSync(file,'utf8')});
   await page.evaluate(dark=>{
    if(dark)document.body.classList.add('dark-mode');
    window.$=id=>document.getElementById(id);window.state={q:'每天打卡',fuzzy:true,sortMode:'time',searchScope:'all',selectedArticleIds:new Set(),view:'all'};
    window.escapeHtml=s=>String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    window.truncate=(s,n)=>String(s||'').slice(0,n);window.renderArticleDomainTags=()=>'';
    window.getArticleStatus=()=> 'new';window.getStatusLabel=()=> '未读';window.getArticleQuality=()=>80;
    window.findSimilarArticles=()=>[];window.articleIsDragging=false;window.recordRecentArticle=()=>{};
    window.renderArticleReaderMeta=(a,b)=>a+b;window.renderArticleListProvenance=()=>'';
    for(const name of ['setupArticleTagRows','bindCardTitleScroll','renderSortModeToggle','renderSavedViews','renderHealthStrip','renderBulkActionBar','handleArticleDragStart','handleArticleDragEnd','handleArticleDragOver','handleArticleDragLeave','handleArticleDrop'])window[name]=()=>{};
    window.openDetailAtOffset=(...args)=>window.opened=args;window.openArticleInTab=(...args)=>window.opened=args;
   },dark);
   await page.addScriptTag({content:['highlightText','buildMatchBadges','buildArticleInsightBadges','renderKnowledgeSearchFeedback','renderArticles'].map(fn).join('\n')});
   await page.evaluate(()=>{
    window.fixture={id:1,title:'匿名用工资料',summary:'判断关系需要核对具体事实。',source_type:'file',source_filename:'匿名资料',tags:[],domains:[],content_snippets:[],search_match:{channels:['semantic'],field:'content',label:'正文',text:'<img src=x onerror=alert(1)>实际管理情况'+ '。'.repeat(100),offset:12}};
    renderKnowledgeSearchFeedback({method:'bm25+dense_rrf',notice:'本地索引正在更新'},state.q);renderArticles([fixture]);
   });
   assert.match(await page.locator('#knowledge-search-feedback').innerText(),/关键词与语义/);
   assert.match(await page.locator('.article-card').innerText(),/语义相关/);
   assert.equal(await page.locator('[data-search-evidence] img').count(),0);
   await page.locator('[data-search-evidence]').click();assert.equal((await page.evaluate(()=>window.opened))[1],12);
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   await page.screenshot({path:`/tmp/stella-knowledge-articles-${width}-${dark}.png`});
   await page.evaluate(()=>renderKnowledgeSearchFeedback({method:'keywords',notice:'本地语义模型暂不可用'},state.q));
   assert.match(await page.locator('#knowledge-search-feedback').innerText(),/暂不可用/);
   await page.evaluate(()=>renderKnowledgeSearchFeedback({},''));assert.equal(await page.locator('#knowledge-search-feedback').isVisible(),false);
   assert.deepEqual(errors,[]);await page.close();

   const kp=await browser.newPage({viewport:{width,height:900}});const ke=[];kp.on('pageerror',e=>ke.push(e.message));
   await kp.setContent('<div class="wrap search-page"><div id="results" class="results"></div></div>');
   await kp.addStyleTag({content:knowledge.match(/<style>([\s\S]*?)<\/style>/)[1]});
   await kp.addStyleTag({content:fs.readFileSync('frontend/apex-design-tokens.css','utf8')});
   await kp.evaluate(dark=>{
    if(dark){document.documentElement.classList.add('dark-mode');document.documentElement.dataset.theme='dark';}
    window.state={resultTotal:1,results:[],searchInfo:{method:'bm25+dense_rrf',notice:'部分内容暂仅参与关键词搜索'}};
    window.esc=s=>String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    window.claimTitle=i=>i.issue_titles;window.compactText=(s,n)=>String(s||'').slice(0,n);
    window.claimBoundary=i=>[['适用条件',i.conditions_text],['例外',i.exceptions_text]];
    window.openClaim=id=>window.opened=id;window.runSearch=()=>{};
    state.results=[{id:1,issue_titles:'匿名规则',statement:'相关规则需结合具体事实核对。',conditions_text:'需要证明实际用工',exceptions_text:'例外仍须核对',evidence_count:1,search_match:{channels:['semantic'],label:'规则结论',text:'<img src=x onerror=alert(1)>原文'},learning:{}}];
   },dark);
   await kp.addScriptTag({content:kfn('renderResults')+';renderResults();'});
   assert.match(await kp.locator('.result-count').innerText(),/请核对适用条件与原文/);
   assert.match(await kp.locator('.result-card').innerText(),/需要证明实际用工/);
   assert.equal(await kp.locator('.result-card img').count(),0);
   await kp.locator('.result-card').click();assert.equal(await kp.evaluate(()=>window.opened),1);
   assert(await kp.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   await kp.screenshot({path:`/tmp/stella-knowledge-center-${width}-${dark}.png`});
   await kp.evaluate(()=>{state.results=[];renderResults();});assert.match(await kp.locator('#results').innerText(),/部分内容暂仅/);
   assert.deepEqual(ke,[]);await kp.close();
  }
  console.log('knowledge search: article/center, field evidence, navigation, fallback, escaping, empty, 1440/1024 light/dark passed');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
