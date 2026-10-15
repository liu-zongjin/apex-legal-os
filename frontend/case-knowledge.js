/* Case-scoped library results. All article/case text is escaped before display. */
(function () {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const types = {support:'支持论证',risk:'风险提示',procedure:'程序取证',background:'背景参考'};
  let key = '', limit = 10;
  const cache = new Map();
  const pending = new Set();
  const questionDrafts = new Map();
  document.addEventListener('input',event=>{
    if(event.target.id==='knowledgeQuestions'&&key){
      questionDrafts.set(key,event.target.value);
      if(questionDrafts.size>40)questionDrafts.delete(questionDrafts.keys().next().value);
    }
  });
  function render(job) {
    if(job.kind !== 'knowledge_match' || job.status !== 'completed') return '';
    const currentQuestions=document.getElementById('knowledgeQuestions');
    if(currentQuestions&&key)questionDrafts.set(key,currentQuestions.value);
    if(key!==job.id){key=job.id;limit=10;cache.clear();}
    const coverage=job.knowledge_coverage||{}, rows=job.knowledge_recommendations||[];
    return `<section class="knowledge-results"><h2>本案可参考的知识库文章</h2>
      <p class="note">本地知识库 ${coverage.library_total||0} 篇 · 去重候选 ${coverage.candidate_count||0} 篇 · 实际分析 ${coverage.assessed||0} 篇 · 分析或引用检查未通过 ${coverage.failed||0} 篇 · 正文不足 ${coverage.insufficient_body||0} 篇</p>
      <p class="note">${esc(coverage.limitation)}</p>
      <details><summary>查看研究问题与检索范围</summary><ol>${(job.knowledge_topics||[]).map(t=>`<li>${esc(t.question)}<small class="note"> · ${esc(t.terms.join('、'))}</small></li>`).join('')}</ol><p class="note">已处理案件材料 ${coverage.material_chunks||0} 个片段；文章分析仅使用相关正文片段及上下文。</p></details>
      <label>调整研究问题后重新分析<textarea id="knowledgeQuestions" rows="3" maxlength="4000">${esc(questionDrafts.get(job.id)??(job.knowledge_topics||[]).map(t=>t.question).join('\n'))}</textarea></label><button id="rerunKnowledge" class="button" type="button">按修改后的问题新建分析</button>
      <div class="knowledge-cards">${rows.slice(0,limit).map((row,i)=>`<article class="knowledge-card" data-knowledge-card="${row.article_id}"><header><h3>${i+1}. ${esc(row.title)}</h3><span class="note">${row.types.map(t=>esc(types[t])).join(' · ')}</span></header>
        <p class="note">关联问题：${esc((job.knowledge_topics||[]).filter(t=>row.topic_ids.includes(t.id)).map(t=>t.question).join('；'))}</p>
        <p>${esc(row.reason)}</p><p class="knowledge-boundary"><strong>适用边界：</strong>${esc(row.limits)}</p>
        <p class="note" data-article-state>以下依据为分析时快照；展开可核对当前文章状态。</p>
        <details data-knowledge-details="${row.article_id}"><summary>查看文章与案件两侧依据</summary>
          <h4>文章原文</h4>${row.article_evidence.map(ref=>`<blockquote class="quote">${esc(ref.locator)}<br>${esc(ref.quote)}</blockquote>`).join('')}<div data-article-context></div>
          <h4>案件原文</h4>${row.case_evidence.map((ref,j)=>`<button class="button small" type="button" data-knowledge-source="${i}" data-knowledge-ref="${j}">${esc(ref.path)} · ${esc(ref.locator)}</button><blockquote class="quote">${esc(ref.quote)}</blockquote>`).join('')}
        </details><div class="entry-controls"><button class="button small" type="button" data-knowledge-open="${row.article_id}">打开知识库原文</button><button class="button small" type="button" data-knowledge-add="${row.article_id}">加入案件研究</button></div></article>`).join('')||'<p class="empty-state">本次未取得有充分双向依据的相关文章。不代表知识库不存在相关内容，可调整研究问题再分析。</p>'}</div>
      ${rows.length>10?`<button class="button" id="moreKnowledge" type="button">${limit===10?'展开更多推荐（最多20篇）':'收起至10篇'}</button>`:''}
      ${coverage.failed?'<p class="warning">部分候选分析失败或引句检查未通过，未列为推荐；可新建分析重试，详细记录见核验底稿。</p>':''}</section>`;
  }
  async function handle(event,ctx) {
    const button=event.target.closest('#moreKnowledge,#rerunKnowledge,[data-knowledge-open],[data-knowledge-add],[data-knowledge-source]');
    if(ctx.job?.kind!=='knowledge_match'||!button)return false;
    if(ctx.busy)return true;
    if(button.id==='moreKnowledge'){limit=limit===10?20:10;ctx.render();return true;}
    if(button.id==='rerunKnowledge'){
      const questions=document.getElementById('knowledgeQuestions').value.trim();
      if(!questions)return ctx.toast('请填写研究问题'),true;
      await ctx.rerun(questions);return true;
    }
    if(button.dataset.knowledgeSource!==undefined){
      ctx.openSource(ctx.job.knowledge_recommendations[Number(button.dataset.knowledgeSource)].case_evidence[Number(button.dataset.knowledgeRef)]);return true;
    }
    const articleId=Number(button.dataset.knowledgeOpen||button.dataset.knowledgeAdd),id=ctx.job.id;
    button.disabled=true;
    try{
      const data=await ctx.api(`${ctx.base}/${id}/knowledge-articles/${articleId}`);
      if(!ctx.current())return true;
      updateCard(articleId,data);cache.set(`${id}:${articleId}`,data);
      if(data.current.state==='deleted'){ctx.toast('文章已删除，可查看保留的分析依据');return true;}
      if(button.dataset.knowledgeOpen){
        if(parent===window)ctx.toast('请在 Stella 主窗口打开文章；本页可展开查看分析时上下文');
        else parent.postMessage({type:'apex:workflow-open-article',version:1,articleId},location.origin);
      }else{
        await ctx.api(`/api/case-research/cases/${ctx.job.case_id}/articles/${articleId}`,{method:'POST',body:new URLSearchParams({added_from:'case_knowledge_match'})});
        if(ctx.current()){button.textContent='已加入案件研究';ctx.toast('已加入案件研究，重复添加不会产生副本');}
      }
    }catch(error){if(ctx.current())ctx.toast(error.message);}finally{if(ctx.current())button.disabled=false;}
    return true;
  }
  function updateCard(id,data){
    const card=document.querySelector(`[data-knowledge-card="${id}"]`);if(!card)return;
    card.querySelector('[data-article-state]').textContent=data.current.label;
    card.querySelector('[data-article-context]').innerHTML=`<details><summary>展开分析时的文章上下文</summary>${data.fragments.map(f=>`<p class="note">${esc(f.locator)}</p><blockquote class="quote">${esc(f.text)}</blockquote>`).join('')}</details>`;
  }
  async function showContext(details,ctx){
    if(!details.open)return;
    const articleId=Number(details.dataset.knowledgeDetails),cacheKey=`${ctx.job.id}:${articleId}`;
    try{
      const data=cache.get(cacheKey)||await ctx.api(`${ctx.base}/${ctx.job.id}/knowledge-articles/${articleId}`);
      if(!ctx.current())return;
      cache.set(cacheKey,data);updateCard(articleId,data);
    }catch(error){if(ctx.current())ctx.toast(error.message);}
  }
  async function hydrate(ctx){
    const rows=(ctx.job.knowledge_recommendations||[]).slice(0,limit);
    let next=0;
    async function worker(){
      while(next<rows.length&&ctx.current()&&document.visibilityState==='visible'){
        const id=rows[next++].article_id,k=`${ctx.job.id}:${id}`;
        if(cache.has(k)){updateCard(id,cache.get(k));continue;}
        if(pending.has(k))continue;
        pending.add(k);
        try{const data=await ctx.api(`${ctx.base}/${ctx.job.id}/knowledge-articles/${id}`);if(ctx.current()){cache.set(k,data);updateCard(id,data);}}
        catch(error){if(ctx.current()){const card=document.querySelector(`[data-knowledge-card="${id}"]`);if(card)card.querySelector('[data-article-state]').textContent='当前文章状态读取失败；分析依据仍为历史快照。';}}
        finally{pending.delete(k);}
      }
    }
    await Promise.all(Array.from({length:Math.min(4,rows.length)},worker));
  }
  window.StellaCaseKnowledge={render,handle,showContext,hydrate,invalidate:()=>cache.clear()};
})();
