import unittest
import numpy as np
from backend.case_hybrid import hybrid_rank,hybrid_shortlist
from backend.public_case_planning import distinct_fact_paths,refined_paths

class PathSelectionTests(unittest.TestCase):
    def test_a_second_path_survives_a_dominant_global_channel(self):
        cases=[{'title':'甲材料'+str(i),'holding':'甲行为已实施。'} for i in range(12)]+[{'title':'乙材料','holding':'乙行为已实施。'}]
        def encoder(texts):return np.asarray([[0,1] if '乙行为' in t else [1,0] for t in texts])
        paths=[{'id':'a','label':'甲行为','required_facts':['甲行为已实施']},{'id':'b','label':'乙行为','required_facts':['乙行为已实施']}]
        ranked,info=hybrid_rank('甲行为',cases,encoder=encoder,paths=paths)
        self.assertEqual(len(info['path_channels']),2)
        self.assertIn('乙材料',[c['title'] for c in hybrid_shortlist(ranked,4)])
    def test_path_selection_also_works_without_optional_vectors(self):
        def absent(texts):raise FileNotFoundError('not installed')
        cases=[{'title':'甲材料','holding':'甲行为'}]*6+[{'title':'乙材料','holding':'乙行为'}]
        ranked,info=hybrid_rank('甲行为',cases,encoder=absent,paths=[{'id':'b','label':'乙行为','required_facts':['乙行为']}])
        self.assertFalse(info['vector_available'])
        self.assertIn('乙材料',[c['title'] for c in hybrid_shortlist(ranked,2)])
    def test_renaming_identical_fact_requirements_does_not_prove_two_paths(self):
        paths=[{'id':'a','label':'路径甲','required_facts':['甲或乙','丙']},{'id':'b','label':'路径乙','required_facts':['甲或乙','丙']}]
        self.assertFalse(distinct_fact_paths(paths))
        paths[0]['required_facts']=['甲','丙'];paths[1]['required_facts']=['乙','丙']
        self.assertTrue(distinct_fact_paths(paths))
    def test_refinement_preserves_each_paths_facts_and_does_not_swap_queries(self):
        paths=[{'id':'a','label':'甲','required_facts':['甲事实'],'queries':['甲旧查询']},{'id':'b','label':'乙','required_facts':['乙事实'],'queries':['乙旧查询']}]
        result=refined_paths(paths,{'paths':[{'id':'b','queries':['乙新查询']},{'id':'a','queries':['甲新查询']}]},['甲旧查询','乙旧查询'])
        self.assertEqual(result[0]['queries'],['甲新查询']);self.assertEqual(result[1]['queries'],['乙新查询'])
        self.assertEqual(result[0]['required_facts'],['甲事实']);self.assertEqual(result[1]['required_facts'],['乙事实'])
    def test_unknown_docket_and_repeated_queries_are_not_new_searches(self):
        path={'id':'a','label':'甲','required_facts':['甲'],'queries':['关系 旧查询']}
        value={'paths':[{'id':'a','queries':['旧查询','（2024）示民初999号']}]}
        self.assertEqual(refined_paths([path],value,['关系 旧查询'],['关系']),[])

class VerifiedPathsTests(unittest.IsolatedAsyncioTestCase):
    async def test_second_round_checks_missing_path_without_erasing_verified_first_path(self):
        import json
        from unittest.mock import AsyncMock,patch
        from backend.public_case_answer import answer_public_cases
        holding='本院认为甲行为完成后再请求撤回，不予支持。乙行为完成后再请求撤回，同样不予支持。'
        case=dict(title='匿名判决',case_number='（2024）示民初1号',holding=holding,adjudicated_facts='',source_kind='wikisource',source='公开存档',source_url='https://example.org/case',retrieved_by=['fixture'],remote_score=.8,body_fetched=True)
        plan={'groups':[['标的'],['撤回']],'queries':['标的 撤回'],'paths':[{'label':'甲路径','required_facts':['甲行为完成'],'queries':['甲行为 撤回']},{'label':'乙路径','required_facts':['乙行为完成'],'queries':['乙行为 撤回']}]}
        def assess(index):return {'cases':[{'index':0,'path_id':'p'+str(index),'stance':'support','quote':holding,'fact_checks':[{'fact_index':0,'status':'established','proof_kind':'court_finding','quote':('甲' if index==0 else '乙')+'行为完成'}]}]}
        review={'reviews':[{'index':0,'verdict':'supported','reason':'原文明确支持'}]}
        responses=[plan,assess(0),review,{'paths':[{'id':'p1','queries':['乙行为 已完成 撤回']} ]},assess(1),review];assessed_paths=[]
        async def model(model,messages,**kwargs):
            data=json.loads(messages[-1]['content']) if messages[-1]['content'].startswith('{') else {}
            if 'evidence' in data:assessed_paths.append([p['id'] for p in data['paths']])
            return {'text':json.dumps(responses.pop(0),ensure_ascii=False)},'fixture'
        def result():return {'cases':[dict(case)],'coverage':{},'metrics':{},'errors':[],'retrieval_runs':[{'query':'原查询'}]}
        with patch('backend.public_case_answer.search_cases_structured',AsyncMock(side_effect=[result(),result()])):
            value=await answer_public_cases('甲或乙完成后撤回不获支持','fixture',None,None,resolve=AsyncMock(return_value='甲或乙完成后撤回不获支持'),call_plan=model,extract=lambda d:(d['text'],'',''),call_answer=AsyncMock(),progress=lambda *a,**k:None)
        self.assertEqual(assessed_paths,[['p0','p1'],['p1']])
        self.assertEqual(value['case_research']['coverage']['covered_paths'],['p0','p1'])
        self.assertEqual(len(value['case_research']['cases']),1)
        self.assertEqual(len(value['case_research']['cases'][0]['semantic_assessment']['verified_paths']),2)
        self.assertIn('另一路径：乙路径',value['answer'])

    async def test_review_payload_preserves_nonzero_global_case_index(self):
        import json
        from unittest.mock import AsyncMock,patch
        from backend.public_case_answer import answer_public_cases
        holding='法院认定甲行为完成，目标请求依法应予支持。'
        cases=[dict(title='匿名判决'+str(i),case_number='（2024）示民初'+str(i+1)+'号',holding=holding,adjudicated_facts='',source_kind='wikisource',source='公开存档',source_url='https://example.org/'+str(i),retrieved_by=['fixture'],remote_score=.5,body_fetched=True) for i in range(4)]
        calls=[]
        async def model(model,messages,**kwargs):
            data=json.loads(messages[-1]['content']) if messages[-1]['content'].startswith('{') else {}
            calls.append(data)
            if len(calls)==1:response={'groups':[['甲行为']],'queries':['甲行为 完成'],'paths':[{'label':'甲路径','required_facts':['甲行为完成'],'queries':['甲行为 完成']}]}
            elif 'evidence' in data:response={'cases':[{'index':3,'path_id':'p0','stance':'support','quote':holding,'fact_checks':[{'fact_index':0,'status':'established','proof_kind':'court_finding','quote':'甲行为完成'}]}]}
            else:
                self.assertIsInstance(data['assessments'],list)
                self.assertEqual(data['assessments'][0]['index'],3)
                response={'reviews':[{'index':data['assessments'][0]['index'],'verdict':'supported','reason':'事实及理由均对应'}]}
            return {'text':json.dumps(response,ensure_ascii=False)},'fixture'
        with patch('backend.public_case_answer.search_cases_structured',AsyncMock(return_value={'cases':cases,'coverage':{},'metrics':{},'errors':[],'retrieval_runs':[]})):
            value=await answer_public_cases('甲行为完成的裁判','fixture',None,None,resolve=AsyncMock(return_value='甲行为完成的裁判'),call_plan=model,extract=lambda d:(d['text'],'',''),call_answer=AsyncMock(),progress=lambda *a,**k:None)
        self.assertEqual(value['case_research']['coverage']['counts']['support'],1)
        self.assertEqual(value['case_research']['cases'][0]['case_number'],'（2024）示民初4号')

class DisplayBalanceTests(unittest.TestCase):
    def test_verified_second_path_is_not_hidden_behind_eight_first_path_cards(self):
        from backend.public_case_planning import path_balanced_indices
        assessments={i:{'path_id':'a','stance':'support'} for i in range(14)}
        assessments[14]={'path_id':'b','stance':'support'}
        order=path_balanced_indices(range(15),assessments,['a','b'])
        self.assertIn(14,order[:8]);self.assertEqual(len(set(order)),15)

class StructuredOutputTests(unittest.TestCase):
    def test_complete_root_is_retained_when_model_duplicates_trailing_fields(self):
        from backend.public_case_semantics import json_value
        self.assertEqual(json_value('{"cases":[{"index":5}],"next_queries":[]}],"next_queries":[]}'),{'cases':[{'index':5}],'next_queries':[]})
    def test_truncated_root_does_not_salvage_an_inner_case_as_a_complete_response(self):
        import json
        from backend.public_case_semantics import json_value
        with self.assertRaises(json.JSONDecodeError):json_value('{"cases":[{"index":5}')
