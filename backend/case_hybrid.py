"""Domain-neutral BM25 + pretrained dense-vector reciprocal-rank fusion."""
from __future__ import annotations
import math
import re
from collections import Counter


def terms(text):
    import jieba
    words=[word.lower() for word in jieba.cut(text) if re.search(r'[\w\u4e00-\u9fff]',word) and len(word.strip())>1]
    # Character bigrams remove segmentation-boundary dependence, not legal meaning.
    for run in re.findall(r'[\u4e00-\u9fff]+',text):words.extend('c2:'+run[i:i+2] for i in range(len(run)-1))
    return words


def bm25(query,documents):
    rows=[Counter(terms(text)) for text in documents];q=set(terms(query));n=len(rows)
    lengths=[sum(row.values()) for row in rows]
    average=sum(lengths)/max(n,1) or 1
    df=Counter(t for row in rows for t in row)
    return [sum(math.log(1+(n-df[t]+.5)/(df[t]+.5))*row[t]*2.2/(row[t]+1.2*(.25+.75*length/average)) for t in q if row[t]) for row,length in zip(rows,lengths)]


def chunks(case,query):
    # Head/tail and term-focused windows together; no legal-topic dictionaries.
    source='\n'.join(str(case.get(k) or '') for k in ('title','adjudicated_facts','holding','holding_conclusion'))
    windows=[source[i:i+220] for i in range(0,len(source),180)] or ['']
    if len(windows)<=6:return windows
    lexical=bm25(query,windows)
    indices={0,len(windows)-1,len(windows)//3,2*len(windows)//3}
    indices.update(sorted(range(len(windows)),key=lambda i:-lexical[i])[:2])
    return [windows[i] for i in sorted(indices)]


def hybrid_rank(query,cases,encoder=None,paths=None):
    if not cases:return [],{'method':'empty','vector_available':False}
    cases=cases[:64]
    documents=['\n'.join(str(c.get(k) or '') for k in ('title','adjudicated_facts','holding','holding_conclusion')) for c in cases]
    sparse=bm25(query,documents);sparse_order=sorted(range(len(cases)),key=lambda i:-sparse[i])
    dense=None;error=''
    try:
        import numpy as np
        if encoder is None:
            from .case_embeddings import local_embeddings
            encoder=local_embeddings
        groups=[chunks(c,query) for c in cases]
        vectors=encoder(['为这个句子生成表示以用于检索相关文章：'+query]+[p for group in groups for p in group])
        vectors=np.asarray(vectors,dtype=float)
        if vectors.ndim!=2 or vectors.shape[0]!=1+sum(map(len,groups)) or not np.isfinite(vectors).all():
            raise ValueError('向量维度或数值无效')
        norms=np.linalg.norm(vectors,axis=1,keepdims=True)
        if np.any(norms<=0):raise ValueError('空向量')
        vectors=vectors/norms;offset=1;dense=[]
        for group in groups:
            scores=vectors[offset:offset+len(group)]@vectors[0]
            dense.append(float(np.max(scores)));offset+=len(group)
    except Exception as exc:error=type(exc).__name__+': '+str(exc)
    fused=[0.0]*len(cases)
    for rank,index in enumerate(sparse_order):
        if sparse[index]>0:fused[index]+=1/(60+rank+1)
    if dense is not None:
        for rank,index in enumerate(sorted(range(len(cases)),key=lambda i:-dense[i])):fused[index]+=1/(60+rank+1)
    order=sorted(range(len(cases)),key=lambda i:(-fused[i],-(dense[i] if dense is not None else sparse[i])))
    for i,c in enumerate(cases):
        c['retrieval_scores']={'bm25':round(sparse[i],6),'cosine':round(dense[i],6) if dense is not None else None,'rrf':round(fused[i],6)}
    info={'method':'bm25+dense_rrf' if dense is not None else 'bm25_only','vector_available':dense is not None,'vector_model':'bge-small-zh-v1.5-local' if dense is not None else None,'fallback_reason':error,'candidate_count':len(cases)}
    # Each OR path competes in its own retrieval space. No legal-topic rules.
    path_channels=[]
    for path in (paths or [])[:3]:
        path_id=path.get('id');parts=[path.get('context',''),path.get('label','')]+list(path.get('required_facts',[]))
        path_query=' '.join(v for v in parts if isinstance(v,str) and v.strip())
        if not isinstance(path_id,str) or not path_query:continue
        copies=[dict(c) for c in cases]
        _,path_info=hybrid_rank(path_query,copies,encoder=encoder)
        for original,copy in zip(cases,copies):
            original['retrieval_scores'].setdefault('paths',{})[path_id]=copy['retrieval_scores']
        path_channels.append({'id':path_id,'method':path_info['method'],'candidate_count':len(copies)})
    if path_channels:info['path_channels']=path_channels
    return [cases[i] for i in order],info



def hybrid_shortlist(cases,limit):
    """Reserve places for BOTH channels instead of trusting any single ranking."""
    if not cases:return []
    limit=max(1,int(limit));selected=[];seen=set()
    channels=[]
    path_ids=list(dict.fromkeys(p for c in cases for p in c.get('retrieval_scores',{}).get('paths',{})))
    def orders(path_id=None):
        def score(index,kind):
            row=cases[index].get('retrieval_scores',{})
            if path_id is not None:row=row.get('paths',{}).get(path_id,{})
            value=row.get(kind)
            return float(value) if value is not None else -math.inf
        result=[sorted(range(len(cases)),key=lambda i:-score(i,'bm25'))]
        if any(score(i,'cosine')!=-math.inf for i in range(len(cases))):result.append(sorted(range(len(cases)),key=lambda i:-score(i,'cosine')))
        return result
    for path_id in path_ids:channels.extend(orders(path_id))
    channels.extend(orders())
    for rank in range(len(cases)):
        for order in channels:
            if order[rank] not in seen:
                seen.add(order[rank]);selected.append(cases[order[rank]])
                if len(selected)>=limit:return selected
    return selected
