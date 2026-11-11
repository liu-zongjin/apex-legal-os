import ast
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from backend import case_research as cr, public_case_web as wiki
from backend.public_case_answer import apply_semantic_plan, answer_public_cases
from backend.public_case_discovery import parse_page

QUESTION = '即使工程发包人不是建设工程的所有权人，承包人能否主张工程款优先受偿权？'
HOLDING = '本院认为，发包人不是所有权人的抗辩不能成立，承包人对工程享有优先受偿权。'
BODY = '某市人民法院\n（2024）示民初123号\n原告诉称：发包人不是所有权人也有优先受偿权。\n' + HOLDING + '\n判决如下：一、支持请求。'

class PrecisionTests(unittest.TestCase):
    def test_ownership_is_required(self):
        from backend.public_case_planning import generic_case_plan
        plan = apply_semantic_plan(generic_case_plan(QUESTION), {'groups':[['优先受偿权','优先受偿'],['发包人'],['所有权人','所有人','产权人']], 'queries':['动态查询']})
        self.assertTrue(plan['strict_issue_match'])
        self.assertIn(['所有权人', '所有人', '产权人'], plan['required_term_groups'])
        unrelated = wiki.parse_judgment_page('某判决书', BODY.replace(HOLDING, '本院认为，承包人对工程享有优先受偿权。'))
        self.assertEqual(cr.rank_cases([unrelated], plan)[0]['issue_match'], 'related')

    def test_number_in_body_and_late_reasoning_preserved(self):
        body = BODY.replace(HOLDING, '本院认为，' + '本案另有争议。'*160 + HOLDING.replace('本院认为，',''))
        case = wiki.parse_judgment_page('某判决书', body)
        self.assertEqual(case['case_number'], '（2024）示民初123号')
        self.assertIn('所有权人', case['holding'])
        self.assertTrue(case['body_fetched'])

    def test_snippet_not_verified(self):
        case = wiki.parse_search_hit('某判决书', HOLDING)
        self.assertEqual(cr._archive_verification(case)['status'], 'unverified')

    def test_fulltext_beats_high_scoring_snippet(self):
        full = wiki.parse_judgment_page('某判决书', BODY, remote_score=.3)
        snippet = wiki.parse_search_hit('某判决书', HOLDING, remote_score=.9)
        snippet['case_number'] = full['case_number']
        for cases in ([snippet, full], [full, snippet]):
            self.assertTrue(cr.deduplicate_cases(cases)[0]['body_fetched'])

    def test_model_plan_is_not_overridden_by_topic_template(self):
        plan = cr.build_case_query_plan(QUESTION)
        adapted = apply_semantic_plan(plan, {'groups':[['工程'],['优先受偿权']], 'queries':['工程 优先受偿权']})
        self.assertEqual(adapted['required_term_groups'], [['工程'],['优先受偿权']])
        self.assertEqual(apply_semantic_plan(plan, {'groups':'bad'}), plan)

    def test_public_page_requires_number_and_court_reasoning(self):
        case = parse_page('某判决书', 'https://example.org/judgment', '<article>'+BODY+'</article>', ['所有权人'])
        self.assertIn('发包人', case['holding'])
        self.assertIsNone(parse_page('某文章', 'https://example.org', '<p>发包人优先受偿权</p>', []))

    def test_route_exits_before_kb(self):
        tree = ast.parse(Path('backend/main.py').read_text())
        ask = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == 'ask_question')
        route = next(n for n in ask.body if isinstance(n, ast.If) and isinstance(n.test, ast.Compare) and isinstance(n.test.left, ast.Name) and n.test.left.id == "source_mode" and any(isinstance(c, ast.Constant) and c.value == "public_web_cases" for c in n.test.comparators))
        self.assertIsInstance(route.body[-1], ast.Return)
        self.assertLess(route.lineno, next(n.lineno for n in ast.walk(ask) if isinstance(n, ast.Assign) and any(isinstance(t,ast.Name) and t.id=='local_only' for t in n.targets)))

class PrecisionAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_snippets_and_pleadings_do_not_become_support_cases(self):
        snippet = wiki.parse_search_hit('某判决书', HOLDING)
        pleading = wiki.parse_judgment_page('某判决书', BODY.replace(HOLDING,'本院认为，本案诉请超过期限，予以驳回。'))
        with patch.object(wiki, 'search_public_cases', AsyncMock(return_value={'cases':[snippet,pleading], 'retrieval_runs':[], 'errors':[]})), patch.object(cr,'search_authoritative_cases', AsyncMock()) as mcp:
            result = await cr.search_cases_structured(QUESTION, sources=cr.CASE_SOURCE_PUBLIC, query_plan={'required_term_groups':[['发包人'],['所有权人'],['优先受偿权']],'strict_issue_match':True,'essential_terms':[],'search_constraints':{},'fact_fingerprint':{}})
        self.assertEqual(result['cases'], [])
        self.assertEqual(len(result['leads']), 1)
        mcp.assert_not_awaited()

    async def test_invalid_source_selection_never_falls_back_to_mcp(self):
        for sources in [[],['unsupported_source'],'wikisource']:
            with self.subTest(sources=sources),patch.object(cr,'search_authoritative_cases',AsyncMock()) as mcp:
                with self.assertRaises(cr.AlurisMCPError):await cr.search_cases_structured(QUESTION,sources=sources)
                mcp.assert_not_awaited()

    async def test_throttle_fallback_preserves_all_issue_terms(self):
        with patch.object(wiki,'_api_search',AsyncMock(side_effect=wiki.PublicCaseError('HTTP 429'))), patch.object(wiki,'_html_search',AsyncMock(side_effect=wiki.PublicCaseError('网页不可达'))), patch.object(wiki,'_rest_search',AsyncMock(return_value=[])) as rest:
            with self.assertRaises(wiki.PublicCaseError):
                await wiki._search_titles(AsyncMock(), '优先受偿权 发包人 所有权人', 4)
        self.assertEqual(rest.await_args.args[1], '优先受偿权 发包人 所有权人')


class AnswerEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_second_round_keeps_timed_out_document_when_query_refinement_fails(self):
        archive = 'https://archive.example.org/decision'
        failure = {'document_url':archive, 'document_title':'劳动争议判决',
                   'document_number':'（2024）示民终9号', 'retryable':True}
        forbidden = dict(failure, document_url='https://example.org/blocked', retryable=False)
        question = '检索劳动报酬判决'
        def result(errors):
            return {'cases':[], 'result':'', 'coverage':{}, 'metrics':{}, 'errors':errors, 'retrieval_runs':[]}

        search = AsyncMock(side_effect=[result([failure, forbidden]), result([])])
        model = AsyncMock(return_value=({'text':'{}'}, 'fixture-model'))
        with patch('backend.public_case_answer.search_cases_structured', search), patch(
            'backend.public_case_planning.refined_paths', return_value=[]
        ):
            await answer_public_cases(question, 'fixture', None, None, resolve=AsyncMock(return_value=question),
                call_plan=model, extract=lambda data: (data['text'],'',''), call_answer=AsyncMock(), progress=lambda *a,**k:None)
        self.assertEqual(search.await_count, 2)
        self.assertEqual(search.await_args.kwargs['query_plan']['retry_documents'], [failure])

    async def test_fabricated_quote_cannot_create_support(self):
        case = wiki.parse_judgment_page('匿名判决书', BODY)
        result = {'cases':[case], 'result':'候选', 'coverage':{}, 'metrics':{}, 'errors':[], 'retrieval_runs':[]}
        async def planner(*args, **kwargs):
            return {'text':'assessment'}, 'fixture-model'
        outputs = iter(['{}', '{"cases":[{"index":0,"stance":"support","quote":"这是并未出现在法院原文中的虚构引文文本"}]}'])
        with patch('backend.public_case_answer.search_cases_structured', AsyncMock(return_value=result)):
            value = await answer_public_cases(QUESTION,'fixture',None,None,resolve=AsyncMock(return_value=QUESTION),
                call_plan=planner,extract=lambda _: (next(outputs),'',''), call_answer=AsyncMock(),progress=lambda *a,**k:None)
        self.assertNotIn('缺少通过原文比对', value['answer'])
        self.assertTrue(value['case_research']['pending_cases'])
        self.assertNotIn('虚构引文', value['answer'])
        self.assertEqual(value['case_research']['coverage']['counts']['support'], 0)

    async def test_public_endpoint_does_not_open_local_kb(self):
        from backend import main
        with patch('backend.user_memory.snapshot',return_value={'enabled':False,'auto_save':False,'revision':0,'items':[]}), patch.object(main,'get_db',side_effect=AssertionError('local KB accessed')), patch('backend.public_case_answer.answer_public_cases',AsyncMock(return_value={'answer':'公开结果','sources':[]})) as public:
            value = await main.ask_question(question=QUESTION,model='deepseek-chat',source_mode='public_web_cases',conversation_context=None,request_id=None)
        public.assert_awaited_once()
        self.assertEqual(value['answer'],'公开结果')


class NetworkAndIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_html_search_when_json_busy(self):
        with patch.object(wiki,'_api_search',AsyncMock(side_effect=wiki.PublicCaseError('HTTP 429'))), patch.object(wiki,'_html_search',AsyncMock(return_value=[{'title':'某判决书'}])) as html, patch.object(wiki,'_rest_search',AsyncMock(side_effect=wiki.PublicCaseError('REST不可达'))):
            value=await wiki._search_titles(AsyncMock(),'优先受偿权 发包人 所有权人',5)
        html.assert_awaited_once()
        self.assertEqual(len(value),1)

    def test_system_proxy_detected_without_exposing_credentials(self):
        from backend.public_case_transport import case_proxy
        with patch('backend.public_case_transport.getproxies',return_value={'https':'http://127.0.0.1:12345'}):
            self.assertEqual(case_proxy(),'http://127.0.0.1:12345')

    def test_compilation_cannot_bind_first_number_to_other_cases(self):
        html = '<article>（2024）示民初1号 案例一 本院认为原告有权。案件来源 （2024）示民初2号 案例二 本院认为原告无权。案件来源</article>'
        self.assertIsNone(parse_page('案例汇编','https://example.org',html,[]))


class HtmlBodyFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_reader_body_is_used_when_json_api_fails(self):
        with patch.object(wiki,'_page_cache_load',return_value={}), patch.object(wiki,'_page_cache_store'), patch.object(wiki,'_api_get',AsyncMock(side_effect=wiki.PublicCaseError('HTTP 429'))), patch.object(wiki,'_html_page',AsyncMock(return_value=BODY)) as html:
            pages=await wiki._fetch_pages(AsyncMock(),['匿名判决书'])
        html.assert_awaited_once()
        self.assertEqual(pages['匿名判决书'],BODY)


class OwnershipPrecisionTests(unittest.TestCase):
    def test_generic_ownership_transfer_is_not_non_owner_issue(self):
        case=wiki.parse_judgment_page('匿名工程判决书', BODY.replace(HOLDING,'本院认为，发包人未付工程款，承包人享有优先受偿权，但不得对抗消费者转移房屋所有权的请求权。'))
        ranked=cr.rank_cases([case],cr.build_case_query_plan(QUESTION))
        self.assertNotEqual(ranked[0]['issue_match'],'direct')


class DirectionalRecallTests(unittest.TestCase):
    def test_public_adapter_does_not_discard_directional_queries(self):
        plan=cr.build_case_query_plan(QUESTION)
        routes=wiki.build_wikisource_queries(plan)
        self.assertTrue(any(r['id']=='support' for r in routes))
        self.assertTrue(any(r['id']=='oppose' for r in routes))
