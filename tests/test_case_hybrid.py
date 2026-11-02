import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from backend.case_hybrid import bm25,hybrid_rank,hybrid_shortlist
from backend.public_case_planning import generic_case_plan
from backend.public_case_semantics import research_paths,validate_assessments

class HybridTests(unittest.TestCase):
    def test_semantic_channel_can_recall_a_paraphrase_without_query_word(self):
        cases=[{'title':'甲','holding':'雇员返家途中遭遇机动车碰撞。'}, {'title':'乙','holding':'工伤问题与公司出资问题整理。'}]
        def encoder(texts):return np.asarray([[1,0]]+[[.99,.01] if '机动车' in t else [0,1] for t in texts[1:]])
        ranked,info=hybrid_rank('通勤车祸工伤',cases,encoder)
        self.assertTrue(info['vector_available'])
        shortlist=hybrid_shortlist(ranked,2)
        self.assertEqual(len(shortlist),2)
        self.assertGreater(cases[0]['retrieval_scores']['cosine'],cases[1]['retrieval_scores']['cosine'])
    def test_missing_encoder_reports_sparse_fallback(self):
        def missing(texts):raise FileNotFoundError('no model')
        _,info=hybrid_rank('债务',[{'title':'债务纠纷','holding':'欠款'}],missing)
        self.assertEqual(info['method'],'bm25_only')
        self.assertFalse(info['vector_available'])
    def test_invalid_vectors_are_not_treated_as_semantic_success(self):
        _,info=hybrid_rank('测试',[{'title':'甲','holding':'文本'}],lambda texts:np.full((len(texts),2),np.nan))
        self.assertFalse(info['vector_available'])
    def test_sparse_tokenization_handles_different_chinese_word_boundaries(self):
        scores=bm25('政府信息公开',[ '政府信息应当依法公开。','员工申请认定工伤。'])
        self.assertGreater(scores[0],scores[1])
    def test_shortlist_preserves_lexical_and_semantic_winners(self):
        cases=[{'id':'semantic','retrieval_scores':{'bm25':0,'cosine':.9}}, {'id':'lexical','retrieval_scores':{'bm25':8,'cosine':.2}}]
        self.assertEqual({c['id'] for c in hybrid_shortlist(cases,2)},{'lexical','semantic'})
    def test_zero_cosine_outranks_negative_cosine_in_dense_channel(self):
        cases=[{'id':'lexical','retrieval_scores':{'bm25':9,'cosine':-.9}},
               {'id':'zero','retrieval_scores':{'bm25':0,'cosine':0}},
               {'id':'negative','retrieval_scores':{'bm25':1,'cosine':-.1}}]
        self.assertEqual([c['id'] for c in hybrid_shortlist(cases,2)],['lexical','zero'])
    def test_no_legal_topic_is_injected_into_fallbacks(self):
        for question in ['劳动者通勤事故','股东认缴出资','商标近似','行政信息公开','婚姻财产','共同犯罪']:
            plan=generic_case_plan(question);paths=research_paths(question)
            self.assertEqual(plan['queries'][0]['query'],question)
            self.assertEqual(paths[0]['required_facts'],[question])
            self.assertEqual(len(paths),1)
    def test_runtime_planning_has_no_sample_specific_rules(self):
        import backend.public_case_planning as planning
        import backend.public_case_semantics as semantics
        source=inspect.getsource(planning)+inspect.getsource(semantics)
        for word in ('收房','收楼','发包人','津02民终5096','京02民终13918'):
            self.assertNotIn(word,source)
    def test_agreement_or_fiction_cannot_establish_actual_fact_in_any_domain(self):
        for role in ['contract_option','legal_fiction','party_claim','hypothesis','unknown']:
            paths=[{'id':'p0','required_facts':['争议行为实际发生'],'fact_kinds':['actual']}]
            source='法院在原文中说明了某项拟制行为及其法律效果。'
            item={'index':0,'path_id':'p0','stance':'support','quote':source,'fact_checks':[{'fact_index':0,'status':'established','proof_kind':role,'quote':source}]}
            self.assertEqual(validate_assessments({'cases':[item]},[{'facts':source,'holding':source}],paths)[0]['stance'],'related')

class LocalModelTests(unittest.TestCase):
    def test_installed_model_encodes_finite_normalized_vectors_offline(self):
        from backend.case_embeddings import model_directory,local_embeddings
        if not (model_directory()/'model_quantized.onnx').exists():self.skipTest('optional model not installed')
        with patch('httpx.AsyncClient.get',side_effect=AssertionError('inference must stay local')):
            values=local_embeddings(['用于检索的句子','完全不同的句子'])
        self.assertEqual(values.shape[0],2)
        np.testing.assert_allclose(np.linalg.norm(values,axis=1),[1,1],atol=1e-5)

    def test_modified_vocabulary_is_rejected_before_inference(self):
        from backend.case_embeddings import model_directory,LocalEncoder
        model=model_directory()/'model_quantized.onnx'
        if not model.exists():self.skipTest('optional model not installed')
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder);(target/model.name).symlink_to(model)
            (target/'vocab.txt').write_text('[PAD]\nmodified vocabulary')
            with self.assertRaisesRegex(ValueError,'词表校验失败'):LocalEncoder(target)


class CommonFactsTests(unittest.TestCase):
    def test_alternatives_each_keep_common_conditions(self):
        paths=research_paths('甲且乙或丙',{'common_facts':['共同主体条件'],'common_fact_kinds':['actual'],'paths':[{'label':'乙路径','required_facts':['乙事实'],'queries':['乙查询']},{'label':'丙路径','required_facts':['丙事实'],'queries':['丙查询']}]})
        self.assertEqual(len(paths),2)
        for path in paths:
            self.assertEqual(path['required_facts'][0],'共同主体条件')
            self.assertEqual(path['fact_kinds'][0],'actual')


class PublicDefaultPlanTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_entry_never_uses_legacy_topic_planner(self):
        from unittest.mock import AsyncMock,patch
        from backend import case_research
        with patch.object(case_research,'build_case_query_plan',side_effect=AssertionError('topic planner used')), patch('backend.public_case_web.search_public_cases',AsyncMock(return_value={'cases':[],'errors':[],'retrieval_runs':[]})):
            result=await case_research.search_cases_structured('任意新的法律领域问题',sources=case_research.CASE_SOURCE_PUBLIC)
        self.assertEqual(result['query_plan']['required_term_groups'],[])
        self.assertTrue(result['query_plan']['semantic_review'])
