"""Internet-only case answering, returning before any local KB or MCP retrieval."""
from __future__ import annotations

import asyncio
import json
import re

from .case_research import search_cases_structured, CASE_SOURCE_PUBLIC
from .public_case_planning import generic_case_plan


def apply_semantic_plan(base, value):
    """Bound model-generated retrieval hints; they are never judicial evidence."""
    if not isinstance(value, dict):
        return base
    raw_groups = value.get('groups')
    raw_queries = value.get('queries')
    if not isinstance(raw_groups, list) or not isinstance(raw_queries, list):
        return base
    groups = [[t.strip() for t in g if isinstance(t, str) and 1 < len(t.strip()) <= 30][:5]
              for g in raw_groups[:6] if isinstance(g, list)]
    groups = [g for g in groups if g]
    queries = [q.strip() for q in raw_queries if isinstance(q, str) and 2 < len(q.strip()) <= 220][:4]
    if len(groups) < 2 or not queries:
        return base
    return dict(base, required_term_groups=groups, essential_terms=[g[0] for g in groups],
                strict_issue_match=True, queries=[{'id': f'semantic_{i}', 'query': q, 'viewpoint': 'neutral'} for i,q in enumerate(queries)])


def _evidence_identity(case):
    """A changed document must not inherit an earlier semantic assessment."""
    return tuple(case.get(k,'') for k in ('case_number','source_url','adjudicated_facts')) + (case.get('holding_original',case.get('holding','')),)


async def answer_public_cases(question, model, history, request_id, *, resolve, call_plan, extract, call_answer, progress):
    import time
    from .main import _normalise_ask_conversation_context
    from .public_case_semantics import research_paths, evidence_cases, validate_assessments, json_value, ASSESS_PROMPT
    from .case_research import deduplicate_cases
    resolved = await resolve(question, _normalise_ask_conversation_context(history))
    plan = generic_case_plan(resolved)
    paths = research_paths(resolved)
    warnings, trace, assessments = [], [], {}
    actual_model, reasoning = model, ''
    end = time.monotonic()+180
    progress(request_id, 'searching', '正在拆解待证明命题、可选事实路径与排除条件')
    try:
        data, _ = await asyncio.wait_for(call_plan(model, [
            {'role':'system','content':'仅输出JSON命题卡，不生成案例或案号。格式 {"common_facts":["所有路径共同的必要事实"],"common_fact_kinds":["actual|agreement|legal_fiction|unspecified"],"groups":[["同义表达"]],"queries":["短查询"],"paths":[{"label":"独立路径","required_facts":["必要事实"],"fact_kinds":["actual|agreement|legal_fiction|unspecified"],"queries":["查询式一","查询式二"]}]}。完全依据当前用户问题，最多3条路径，每路径1至3个必要事实、2条查询。保留主体、对象、行为状态、否定、时序、条件和命题强度。用户用或连接的事实拆分路径；共同必要事实放common_facts并在每条路径保留。没有或的合取命题默认只有一条完整事实路径，不能把辅助检索角度拆成删掉条件的替代路径。不得添加用户未要求的事实、规则或法律领域。把事实描述改写为不同常用表达，检索式只用制度锚点和关键事实，不同时堆叠全部条件及期待结果。法院层级地域日期等硬约束独立保留，不与语义相似度混淆。'},
            {'role':'user','content':resolved}],max_tokens=1600),timeout=15)
        raw=json_value(extract(data)[0]); plan=apply_semantic_plan(plan,raw)
        paths=research_paths(resolved,raw)
    except Exception as exc:
        warnings.append('命题分析未完成，已按原问题的可选路径继续：'+type(exc).__name__)
    plan=dict(plan,research_paths=paths,semantic_review=True)
    pooled, errors, runs, assessments, last_raw = [], [], [], {}, {}
    result=None
    for round_index in range(2):
        remaining=end-time.monotonic()
        if remaining<20: break
        progress(request_id,'searching',f'第{round_index+1}轮：按事实路径检索并读取裁判正文')
        try:
            result=await asyncio.wait_for(search_cases_structured(resolved,top_k=10,sources=CASE_SOURCE_PUBLIC,verify_sources=True,query_plan=plan),timeout=min(75,remaining-15))
        except asyncio.TimeoutError:
            warnings.append('本轮检索达到总时间上限，保留此前已核验的资料。');break
        errors.extend(result['errors']); runs.extend(result['retrieval_runs'])
        hybrid=result.get('hybrid_retrieval') or {}
        if hybrid:
            trace.append('候选重排：'+str(hybrid.get('method'))+'；候选数：'+str(hybrid.get('candidate_count',0)))
            if not hybrid.get('vector_available'):warnings.append('本地向量通道未启用，本次按关键词与模型语义复核继续。')
        prior={_evidence_identity(c):assessments[i] for i,c in enumerate(pooled) if i in assessments}
        proved=[c for c in pooled if prior.get(_evidence_identity(c),{}).get('stance') in ('support','oppose')]
        pooled=deduplicate_cases(proved+result['cases']+pooled)[:16]
        assessments={i:prior[_evidence_identity(c)] for i,c in enumerate(pooled) if _evidence_identity(c) in prior}
        if not pooled:
            last_raw={}
        else:
            progress(request_id,'generating',f'第{round_index+1}轮：逐项核对事实、法院立场和排除原因')
            evidence=evidence_cases(pooled,paths)
            try:
                completed=[]
                semaphore=asyncio.Semaphore(2)
                async def assess_batch(batch):
                    async with semaphore:
                        prompt_batch=[{k:v for k,v in row.items() if not k.startswith('_')} for row in batch]
                        data,used_model=await asyncio.wait_for(call_plan(model,[
                            {'role':'system','content':ASSESS_PROMPT},
                            {'role':'user','content':json.dumps({'question':resolved,'original_question':question,'paths':paths,'evidence':prompt_batch},ensure_ascii=False)}],max_tokens=4500),timeout=min(35,max(1,end-time.monotonic())))
                        batch_text,_,_=extract(data)
                        raw=json_value(batch_text)
                        checked=validate_assessments(raw,evidence,paths,allowed_indices={r['index'] for r in batch})
                        completed.append((raw,used_model,checked))
                jobs=[asyncio.create_task(assess_batch(evidence[i:i+4])) for i in range(0,len(evidence),4)]
                try:
                    await asyncio.wait_for(asyncio.gather(*jobs,return_exceptions=True),timeout=min(50,max(1,end-time.monotonic())))
                finally:
                    for job in jobs:
                        if not job.done():job.cancel()
                    await asyncio.gather(*jobs,return_exceptions=True)
                    if completed:
                        actual_model=completed[-1][1]
                        last_raw={'next_queries':[q for raw,_,_ in completed
                                  for q in (raw.get('next_queries',[]) if isinstance(raw.get('next_queries'),list) else []) if isinstance(q,str)]}
                        for _,_,checked in completed:assessments.update(checked)
                    if len(completed)<len(jobs):warnings.append('部分候选的语义核验未完成，未将其当作支持案例。')
            except Exception as exc:
                warnings.append('本轮语义核验未完成：'+type(exc).__name__)
        direct={i:a for i,a in assessments.items() if a['stance'] in ('support','oppose')}
        if direct:
            from .public_case_semantics import REVIEW_PROMPT,apply_counter_review
            progress(request_id,'generating','正在独立复核必要条件、命题强弱与反例')
            review={}
            try:
                data,_=await asyncio.wait_for(call_plan(model,[
                    {'role':'system','content':REVIEW_PROMPT},
                    {'role':'user','content':json.dumps({'question':resolved,'original_question':question,'paths':paths,'assessments':direct},ensure_ascii=False)}],max_tokens=2500),timeout=min(25,max(1,end-time.monotonic())))
                review=json_value(extract(data)[0])
            except Exception as exc:
                warnings.append('独立反证复核未完成，相关候选暂不计为直接支持：'+type(exc).__name__)
            assessments=apply_counter_review(assessments,review)
        covered={v['path_id'] for v in assessments.values() if v['stance']=='support'}
        missing=[p for p in paths if p['id'] not in covered]
        if not missing:break
        if round_index==0:
            # The second round is an explicit response to a coverage gap.
            trace.append('首轮未覆盖：'+'、'.join(p['label'] for p in missing)+'；继续补检。')
            corpus=' '.join(c.get('facts_text','')+' '+c.get('holding','')+' '+c.get('case_number','') for c in pooled)
            proposals=last_raw.get('next_queries',[]) if isinstance(last_raw,dict) else []
            from .public_case_web import _CASE_NUMBER_RE
            own_numbers={c['case_number'] for c in pooled}
            referenced=[n for n in dict.fromkeys(_CASE_NUMBER_RE.findall(corpus)) if n not in own_numbers]
            queries=['intitle:'+n for n in referenced[:1]]
            if referenced: trace.append('根据已取得裁判中的关联案号倒查：'+referenced[0])
            for q in proposals if isinstance(proposals,list) else []:
                if isinstance(q,str) and 3<len(q)<=180 and all(n in corpus for n in _CASE_NUMBER_RE.findall(q)):
                    queries.append(q)
            used={r.get('query') for r in runs}
            queries=list(dict.fromkeys(queries+[q for p in missing for q in p['queries'] if q not in used]))[:4]
            if not queries:break
            # Keep the meaning of paths stable; only retrieval wording changes.
            plan=dict(plan,research_paths=[dict(p,queries=queries[i::len(missing)][:2]) for i,p in enumerate(missing)])
    if result is None:
        result={'cases':[],'coverage':{},'metrics':{},'errors':[],'retrieval_runs':[]}
    labels={'support':'直接支持','oppose':'限制或反向','related':'仅部分相关','uncertain':'尚未核实','exclude':'排除'}
    counts={k:sum(v['stance']==k for v in assessments.values()) for k in labels}
    blocks=['本次按'+str(len(paths))+'条事实路径检索。经逐项原文核对，直接支持'+str(counts['support'])+'件；未覆盖的路径不能据此认定不存在相关裁判。']
    displayed=[]; excluded=[]
    priority={'support':0,'oppose':1,'related':2,'uncertain':3,'exclude':4}
    ordered=sorted(range(len(pooled)),key=lambda i:(priority.get(assessments.get(i,{}).get('stance'),4),pooled[i].get('authority_rank',5)))
    partial_count=0
    for index in ordered:
        c=pooled[index]
        assessment=assessments.get(index)
        if not assessment or assessment['stance'] in {'exclude','uncertain'}:
            excluded.append({'title':c['title'],'case_number':c['case_number'],'reason':assessment['reason'] if assessment else '缺少通过原文比对的事实及裁判依据'})
            continue
        if assessment['stance']=='related':
            partial_count+=1
            if partial_count>2:continue
        if len(displayed)>=8:continue
        displayed.append(c);c['semantic_assessment']=assessment
        c['viewpoint']=assessment['stance'] if assessment['stance'] in ('support','oppose') else 'neutral'
        path=next(p for p in paths if p['id']==assessment['path_id'])
        facts='\n'.join('> '+check['quote'].replace('\n','\n> ') for check in assessment['fact_checks'])
        blocks.append('## '+str(len(displayed))+'. '+c['title']+'\n'
            +'案号：'+c['case_number']+'；法院：'+(c.get('court') or '未提供')+'\n'
            +'对应路径：'+path['label']+'；关系：'+labels[assessment['stance']]+'\n'
            +assessment['reason']+'\n'
            +('关键事实原文：\n'+facts+'\n' if facts else '关键事实尚未全部核实。\n')
            +'法院说理：\n> '+assessment['quote'].replace('\n','\n> ')+'\n'
            +'来源：'+c['source']+'；生效状态未独立核验。\n[查看原文]('+c['source_url']+')')
    if not displayed:blocks.append('已取得的候选尚不足以证明用户要求的事实与裁判结论；未将一般案件作为直接支持案例。')
    if excluded:
        blocks.append('排除记录：\n'+'\n'.join('- '+v['case_number']+'：'+v['reason'] for v in excluded[:4]))
    warnings=list(dict.fromkeys(warnings+(['部分公开来源读取未完成；保留已取得资料，详见检索记录。'] if errors else [])))
    result.update(cases=displayed,errors=errors,retrieval_runs=runs,research_paths=paths,excluded_cases=excluded,semantic_assessments=assessments)
    result['coverage'].update(counts={'support':counts['support'],'oppose':counts['oppose'],'neutral':counts['related']},candidate_count=len(pooled),selected_count=len(displayed),covered_paths=sorted({v['path_id'] for v in assessments.values() if v['stance']=='support'}))
    result['coverage']['missing_viewpoints']=[label for key,label in (('support','支持'),('oppose','反对')) if not counts[key]]
    result['metrics']['opposing_viewpoint_covered']=bool(counts['support'] and counts['oppose'])
    result['metrics'].update(semantic_reviewed_count=len(assessments),semantic_support_rate=round(counts['support']/len(assessments),4) if assessments else 0)
    answer='\n\n'.join(blocks);result['result']=answer
    progress(request_id,'complete','多轮类案检索与原文核对完成',status='complete')
    return {'answer':answer,'reasoning':reasoning,'model_used':actual_model,'source_mode':'public_web_cases',
            'sources':[],'cited_sources':[],'external_sources':[{'title':c['title'],'url':c['source_url'],'source_type':'public_case'} for c in displayed],
            'case_research':result,'warnings':warnings,'web_search_used':bool(runs),'web_search_available':True,
            'research_trace':trace+[r['query'] for r in runs if r.get('query')]+[str(e.get('source','公开来源'))+'：'+str(e.get('message','')) for e in errors],
            'strategy_version':'多路径语义类案研究','strategy_version_id':None}
