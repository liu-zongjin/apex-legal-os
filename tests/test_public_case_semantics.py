import unittest
from backend.public_case_semantics import research_paths,validate_assessments
from backend.case_research import build_case_query_plan, rank_cases
from backend.public_case_web import build_wikisource_queries

class SemanticTests(unittest.TestCase):
    def setUp(self):
        self.paths=[{'id':'p0','label':'选择后反悔','required_facts':['买方选择继续履行','此后请求解除'],'queries':['买方 已选择履行 解除']}]
        self.evidence=[{'index':0,'facts':'经审理查明，买方先要求卖方继续交付，之后又诉请解除合同。','holding':'本院认为买方已经明确选择继续履行，现又要求解除合同，不予支持。'}]
    def item(self):
        return {'index':0,'path_id':'p0','stance':'support','quote':self.evidence[0]['holding'], 'fact_checks':[
            {'fact_index':0,'status':'established','proof_kind':'court_finding','quote':'买方先要求卖方继续交付'},
            {'fact_index':1,'status':'established','proof_kind':'court_finding','quote':'之后又诉请解除合同'}]}
    def test_paraphrased_facts_need_not_all_appear_in_holding_quote(self):
        value=validate_assessments({'cases':[self.item()]},self.evidence,self.paths)
        self.assertEqual(value[0]['stance'],'support')
    def test_missing_or_contradicted_fact_blocks_support(self):
        for status in ('missing','contradicted'):
            item=self.item();item['fact_checks'][0]['status']=status
            self.assertEqual(validate_assessments({'cases':[item]},self.evidence,self.paths)[0]['stance'],'related')
    def test_fabricated_fact_quote_blocks_support(self):
        item=self.item();item['fact_checks'][0]['quote']='原文没有的事实'
        self.assertEqual(validate_assessments({'cases':[item]},self.evidence,self.paths)[0]['stance'],'related')
    def test_fabricated_ruling_is_rejected(self):
        item=self.item();item['quote']='本院支持这项请求，这是原文没有的虚构理由'
        self.assertEqual(validate_assessments({'cases':[item]},self.evidence,self.paths),{})
    def test_applicability_conditions_require_source_quotes(self):
        item=self.item()
        item['limits']=[{'quote':'买方已经明确选择继续履行','meaning':'仅适用于已作出选择的情形'}, {'quote':'法院未说过这一项限制条件','meaning':'不得写入'}]
        result=validate_assessments({'cases':[item]},self.evidence,self.paths)[0]
        self.assertEqual(len(result['limits']),1)
        self.assertEqual(result['limits'][0]['meaning'],'仅适用于已作出选择的情形')

    def test_unknown_proof_kind_cannot_establish_a_fact(self):
        item=self.item();item['fact_checks'][0]['proof_kind']='definitely_true'
        self.assertEqual(validate_assessments({'cases':[item]},self.evidence,self.paths)[0]['stance'],'related')

    def test_disposition_cannot_substitute_for_substantive_reasoning(self):
        item=self.item();item['quote']='本院判决驳回原告的全部诉讼请求。'
        self.evidence[0]['disposition']=item['quote']
        self.assertEqual(validate_assessments({'cases':[item]},self.evidence,self.paths),{})

    def test_batch_cannot_assess_a_case_it_did_not_receive(self):
        self.assertEqual(validate_assessments({'cases':[self.item()]},self.evidence,self.paths,allowed_indices={1}),{})

    def test_stitched_excerpt_is_not_a_continuous_source_quote(self):
        item=self.item();first='本院认为该请求不能成立。';second='其上诉应予驳回。'
        self.evidence[0].update(holding=first+'\n'+second,_quote_sources={'facts':self.evidence[0]['facts'],'holding':first+'但其他请求应当支持。'+second})
        item['quote']=first+'\n'+second
        self.assertEqual(validate_assessments({'cases':[item]},self.evidence,self.paths),{})

    def test_layout_whitespace_is_ignored_without_deleting_source_words(self):
        item=self.item();self.evidence[0]['_quote_sources']={'facts':self.evidence[0]['facts'],'holding':item['quote'].replace('已经','已\n经')}
        self.assertEqual(validate_assessments({'cases':[item]},self.evidence,self.paths)[0]['stance'],'support')

    def test_malformed_path_id_does_not_abort_other_assessments(self):
        bad=self.item();bad['path_id']=[]
        self.assertEqual(validate_assessments({'cases':[bad,self.item()]},self.evidence,self.paths)[0]['stance'],'support')

    def test_or_paths_generate_distinct_interleaved_queries(self):
        paths=research_paths('任意问题',{'paths':[{'label':'事实甲','required_facts':['甲'],'queries':['甲1','甲2']},{'label':'事实乙','required_facts':['乙'],'queries':['乙1','乙2']}]})
        self.assertEqual(len(paths),2)
        plan=build_case_query_plan('已收楼或选择继续履行后又解除合同');plan['research_paths']=paths
        queries=build_wikisource_queries(plan)
        self.assertEqual([q['id'] for q in queries],['p0_0','p1_0','p0_1','p1_1'])
    def test_query_path_coverage_does_not_require_every_path_in_one_case(self):
        p2={'id':'p1','label':'已经收房','required_facts':['实际收房'], 'queries':['实际收房']}
        value=validate_assessments({'cases':[self.item()]},self.evidence,self.paths+[p2])
        self.assertEqual(value[0]['stance'],'support')


class QueryCacheTests(unittest.TestCase):
    def test_query_rewrite_cannot_reuse_original_result_cache(self):
        from backend.public_case_web import _cache_key
        a={'core_issue':'同一问题','research_paths':[{'id':'p0','queries':['第一轮词']} ]}
        b={'core_issue':'同一问题','research_paths':[{'id':'p0','queries':['补检改写词']} ]}
        self.assertNotEqual(_cache_key(a,6),_cache_key(b,6))


class ReceiptPolarityTests(unittest.TestCase):
    def test_deemed_delivery_after_refusal_is_not_actual_receipt(self):
        paths=[{'id':'p0','required_facts':['某实际行为已经发生'],'fact_kinds':['actual']}]
        fact='原告查验后拒绝接收房屋，故本院认定房屋于当日完成交付。'
        court='本院认为，该房屋具备交付条件，原告请求解除合同，不予支持。'
        evidence=[{'facts':fact,'holding':court}]
        item={'index':0,'path_id':'p0','stance':'support','quote':court,'fact_checks':[{'fact_index':0,'status':'established','proof_kind':'legal_fiction','quote':fact}]}
        result=validate_assessments({'cases':[item]},evidence,paths)
        self.assertEqual(result[0]['stance'],'related')


class ExactDocketTests(unittest.IsolatedAsyncioTestCase):
    async def test_unrelated_search_results_cannot_replace_requested_docket(self):
        from unittest.mock import AsyncMock,patch
        from backend.case_research import search_cases_structured,CASE_SOURCE_PUBLIC
        case={'title':'其他判决书','case_number':'（2024）示民初9号','court':'某市人民法院','holding':'本院认为双方应按约履行。','factual_summary':'','matched_excerpt':'','source_kind':'wikisource','source_url':'https://zh.wikisource.org/wiki/example','source':'公开存档','body_fetched':True,'remote_score':.8,'retrieved_by':['test'],'viewpoint':'neutral'}
        with patch('backend.public_case_web.search_public_cases',AsyncMock(return_value={'cases':[case],'retrieval_runs':[],'errors':[]})):
            result=await search_cases_structured('（2020）示民终8号',sources=CASE_SOURCE_PUBLIC)
        self.assertEqual(result['cases'],[])

class CourtSectionTests(unittest.TestCase):
    def test_wrong_case_type_can_be_excluded_with_literal_caption(self):
        paths = [{'id':'p0','required_facts':['实际交付']}]
        evidence = [{'title':'某甲诈骗罪刑事判决书','facts':'','holding':''}]
        row = {'index':0,'path_id':'p0','stance':'exclude','quote':'诈骗罪刑事判决书','reason':'案由不同'}
        self.assertEqual(validate_assessments({'cases':[row]},evidence,paths)[0]['stance'],'exclude')
        self.assertEqual(validate_assessments({'cases':[dict(row,quote='捏造的裁判事实')]},evidence,paths),{})

    def test_appellate_facts_are_extracted_separately(self):
        from backend.public_case_web import adjudicated_facts
        body = '上诉人诉称货物已经交付。二审查明，货物尚未交付。本院认为，违约责任成立。'
        self.assertEqual(adjudicated_facts(body), '二审查明，货物尚未交付。')

    def test_pleading_is_not_promoted_to_court_fact(self):
        from backend.public_case_web import adjudicated_facts
        self.assertEqual(adjudicated_facts('原告诉称，已经收房。本院认为，本案应付违约金。'), '')
    def test_disposition_and_conclusion_survive_long_reasoning(self):
        from backend.public_case_web import parse_judgment_page
        body='某法院\n（2024）示民初1号\n本院查明，买方已经收房。\n本院认为，'+'其他问题。'*2000+'买方已收房又解除，本院不予支持。判决如下：驳回原告解除合同请求。'
        case=parse_judgment_page('匿名判决书',body)
        self.assertIn('买方已收房又解除',case['holding_conclusion'])
        self.assertIn('驳回原告解除合同请求',case['disposition'])

class IterativeResearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_gap_triggers_new_queries_then_grounded_support(self):
        import json
        from unittest.mock import AsyncMock,patch
        from backend.public_case_answer import answer_public_cases
        question='买受人已收楼或选择继续履行后再主张解除合同不予支持'
        first='本院认为，买方要求交房违约金，本院予以支持。'
        second='本院认为，买方已经办理收房手续并领取钥匙，现请求解除合同，合同目的已实现，本院不予支持。'
        def case(number,holding):
            return dict(title='匿名房屋判决书',case_number=number,holding=holding,source='公开存档',source_url='https://example.org/'+number,source_kind='wikisource',body_fetched=True,adjudicated_facts='',retrieved_by=['p0'],remote_score=.6)
        def result(c):return dict(cases=[c],errors=[],retrieval_runs=[{'query':'已用原查询'}],coverage={},metrics={})
        replies=[{'groups':[['房屋'],['合同']], 'queries':['房屋 合同'], 'paths':[{'label':'实际接收后解除','required_facts':['已实际接收标的物','此后请求解除'],'queries':['接收标的物 解除','已经交接 解除']}]}, {'cases':[], 'next_queries':['商品房 领取钥匙 解除合同']}, {'cases':[]}, {'paths':[{'id':'p0','queries':['商品房 领取钥匙 解除合同']}]}, {'cases':[{'index':0,'path_id':'p0','stance':'support','quote':second,'fact_checks':[{'fact_index':0,'status':'established','proof_kind':'court_finding','quote':'买方已经办理收房手续并领取钥匙'},{'fact_index':1,'status':'established','proof_kind':'court_finding','quote':'现请求解除合同'}]}]}, {'cases':[]}, {'reviews':[{'index':0,'verdict':'supported','reason':'各项事实与裁判方向均有引文'}]}]
        async def model(*args,**kwargs):return {'text':json.dumps(replies.pop(0),ensure_ascii=False)},'fixture'
        search=AsyncMock(side_effect=[result(case('（2024）示民初1号',first)),result(case('（2024）示民初2号',second))])
        with patch('backend.public_case_answer.search_cases_structured',search):
            value=await answer_public_cases(question,'fixture',None,None,resolve=AsyncMock(return_value=question),call_plan=model,extract=lambda d:(d['text'],'',''),call_answer=AsyncMock(),progress=lambda *a,**k:None)
        self.assertEqual(search.await_count,2)
        self.assertEqual(value['case_research']['coverage']['counts']['support'],1)
        self.assertNotEqual(search.await_args_list[0].kwargs['query_plan']['research_paths'],search.await_args_list[1].kwargs['query_plan']['research_paths'])


class CounterReviewTests(unittest.TestCase):
    def test_broader_fact_is_not_a_verified_specific_condition(self):
        from backend.public_case_semantics import apply_counter_review
        assessments={0:{'stance':'support','reason':'原断言'}}
        result=apply_counter_review(assessments,{'reviews':[{'index':0,'verdict':'insufficient','reason':'证据只证明较宽范围，未证明具体子类'}]})
        self.assertEqual(result[0]['stance'],'related')
    def test_missing_independent_review_cannot_claim_verified_support(self):
        from backend.public_case_semantics import apply_counter_review
        result=apply_counter_review({0:{'stance':'support','reason':'原断言'}},{})
        self.assertEqual(result[0]['stance'],'uncertain')


class EvidenceIdentityTests(unittest.TestCase):
    def test_same_docket_with_changed_text_requires_new_assessment(self):
        from backend.public_case_answer import _evidence_identity
        case={'case_number':'（2024）示民初1号','source_url':'https://example.org/case','holding':'原文裁判理由'}
        self.assertNotEqual(_evidence_identity(case),_evidence_identity(dict(case,holding='更新后的裁判理由')))

    def test_raw_sources_are_retained_only_for_quote_validation(self):
        from backend.public_case_semantics import evidence_cases
        case={'title':'匿名判决','source_kind':'public_web','adjudicated_facts':'法院查明连续事实原文。','holding':'法院说理摘录。','holding_original':'法院说理完整连续原文。'}
        row=evidence_cases([case],[{'required_facts':['事实']}])[0]
        self.assertEqual(row['_quote_sources']['holding'],case['holding_original'])
