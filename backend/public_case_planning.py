"""Public research planning without topic branches, case IDs or canned answers."""
from .case_issue import build_search_constraints


def generic_case_plan(question):
    question=str(question or '').strip()
    return {'original_query':question,'core_issue':question,'essential_terms':[],
            'required_term_groups':[],'strict_issue_match':False,'fact_fingerprint':{},
            'queries':[{'id':'original','query':question[:220],'viewpoint':'neutral'}],
            'search_constraints':build_search_constraints(question)}


def refined_paths(paths, value, used_queries, anchors=(), corpus=''):
    """Only query wording may change; fact requirements and path IDs stay fixed."""
    import re
    from .public_case_web import _CASE_NUMBER_RE
    def key(query):
        if anchors and not has_relation_anchor(query, anchors):query=anchors[0]+' '+query
        return re.sub(r'\s+','',query)
    used={key(q) for q in used_queries if isinstance(q,str)}
    raw=value.get('paths',[]) if isinstance(value,dict) else []
    proposed={}
    for row in raw[:6] if isinstance(raw,list) else []:
        if isinstance(row,dict) and isinstance(row.get('id'),str) and isinstance(row.get('queries'),list):proposed[row['id']]=row['queries']
    result=[]
    for path in paths:
        queries=[]
        for query in proposed.get(path['id'],[])+path['queries']:
            if not isinstance(query,str) or not 3<len(query.strip())<=180:continue
            query=query.strip()
            if any(number not in corpus for number in _CASE_NUMBER_RE.findall(query)):continue
            normalized=key(query)
            if normalized in used:continue
            used.add(normalized);queries.append(query)
            if len(queries)>=2:break
        if queries:
            # Refined wording has already passed novelty and observed-docket checks.
            # Keep one unexpanded angle so the same anchor cannot suppress recall again.
            result.append(dict(path,queries=queries,discovery_queries=queries[:1]))
    return result


def distinct_fact_paths(paths):
    """Different labels do not make identical proof requirements independent."""
    sets=[frozenset(p.get('required_facts',[])) for p in paths]
    if not sets or any(not facts for facts in sets):return False
    if len(sets)==1:return True
    shared=set.intersection(*(set(facts) for facts in sets))
    return len(set(sets))==len(sets) and all(set(facts)-shared for facts in sets)


def path_balanced_indices(indices, assessments, path_ids):
    """Reserve an existing verified/assessed representative per requested path."""
    indices=list(indices);selected=[]
    def matches(index,path_id):
        item=assessments.get(index,{})
        return item.get('path_id')==path_id or any(v.get('path_id')==path_id for v in item.get('verified_paths',[]))
    for path_id in path_ids:
        if any(matches(i,path_id) for i in selected):continue
        candidate=next((i for i in indices if i not in selected and matches(i,path_id)),None)
        if candidate is not None:selected.append(candidate)
    return selected+[i for i in indices if i not in selected]


def has_relation_anchor(query, anchors):
    # Generic remedies cannot replace a concrete legal relationship. Short
    # aliases are ambiguous; the primary anchor remains authoritative for them.
    return any(anchor in query for i, anchor in enumerate(anchors) if i == 0 or len(anchor) >= 4)


def recall_query_family(queries, anchors=()):
    """Reserve a broad discovery query without weakening proof requirements."""
    import re
    result = []
    for query in queries:
        pieces = re.findall(r'"[^"\n]+"|\S+', query)
        overlaps = anchors and any(len(piece.strip('"')) >= 4 and piece.strip('"') in anchors[0] for piece in pieces)
        if anchors and not overlaps and not has_relation_anchor(query, anchors):
            query = anchors[0] + ' ' + query
        if query not in result:
            result.append(query)
    if result:
        terms = re.findall(r'"[^"\n]+"|\S+', result[0])
        if len(terms) > 2:
            broad = ' '.join(terms[:2]).replace('"', '')
            result = [broad] + [q for q in result if q != broad]
    return result[:4]
