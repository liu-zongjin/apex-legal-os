"""Topic-independent recall, proof requirements and result boundaries."""
import json
import unittest
from unittest.mock import AsyncMock, patch

from backend.public_case_semantics import research_paths
from backend.public_case_web import build_wikisource_queries
from backend.public_case_planning import refined_paths
from backend.public_case_discovery import article_case_leads, discover_cases
from backend.public_case_answer import answer_public_cases


class QueryDiversityTests(unittest.TestCase):
    def test_discovery_angle_keeps_role_vocabulary_without_changing_proof(self):
        paths = research_paths('某机构退还服务费后能否解除合同', {'paths':[{
            'required_facts':['机构已经退还服务费'], 'queries':['服务合同 退费'],
            'discovery_queries':['培训机构 退费凭证 解除', '（2024）示民初999号'],
        }]})
        queries = build_wikisource_queries({'research_paths':paths, 'context_terms':['服务合同纠纷']})
        self.assertIn('培训机构 退费凭证 解除', [item['query'] for item in queries])
        self.assertFalse(any('999号' in item['query'] for item in queries))
        self.assertEqual(paths[0]['required_facts'], ['机构已经退还服务费'])

    def test_one_proof_path_can_have_four_retrieval_angles(self):
        for anchor in ('股东出资责任', '保证责任', '合同解除'):
            queries=[anchor+' '+word for word in ('未缴出资', '加速到期', '债权保护', '执行不能')]
            paths=research_paths('测试问题', {'paths':[{'required_facts':['必要条件甲','必要条件乙'], 'queries':queries}]})
            self.assertEqual(len(paths), 1)
            self.assertEqual([r['query'] for r in build_wikisource_queries({'research_paths':paths})], queries)
            self.assertEqual(paths[0]['required_facts'], ['必要条件甲','必要条件乙'])

    def test_valid_synonym_does_not_accumulate_first_anchor(self):
        plan={'research_paths':[{'id':'p0','queries':['担保责任 未通知']}], 'context_terms':['保证责任','担保责任']}
        self.assertEqual(build_wikisource_queries(plan)[0]['query'], '担保责任 未通知')
        paths=[{'id':'p0','queries':[], 'required_facts':['事实']}]
        result=refined_paths(paths,{'paths':[{'id':'p0','queries':['担保责任 未通知']}]},['担保责任 未通知'],plan['context_terms'])
        self.assertEqual(result, [])

    def test_query_budget_stays_bounded(self):
        paths=[{'id':f'p{i}','queries':[f'角度{i}{j}' for j in range(4)]} for i in range(3)]
        queries=build_wikisource_queries({'research_paths':paths})
        self.assertEqual(len(queries),4)
        self.assertEqual([r['id'] for r in queries[:3]],['p0_0','p1_0','p2_0'])

    def test_broad_recall_query_is_reserved_even_if_model_overconstrains(self):
        from backend.public_case_planning import recall_query_family
        for anchor in ('保证责任', '商标侵权', '股东出资责任'):
            family=recall_query_family([anchor+' 核心事实 限定状态 期待结论', anchor+' 另一表述 条件'], [anchor])
            self.assertEqual(family[0],anchor+' 核心事实')
            self.assertIn(anchor+' 核心事实 限定状态 期待结论',family)
            self.assertLessEqual(len(family),4)


class SearchPageTests(unittest.TestCase):
    def test_normal_links_survive_without_issue_words_in_party_title(self):
        from backend.public_case_discovery import parse_360_results
        html='<li class="res-list"><h3><a href="https://example.org/judgment">甲公司与乙公司判决书</a></h3></li>'
        self.assertEqual(parse_360_results(html),[('甲公司与乙公司判决书','https://example.org/judgment')])

    def test_docket_followup_ranks_by_original_issue_before_read_budget(self):
        from backend.public_case_discovery import rank_web_links
        found=[('其他争议'+str(i),'https://example.org/'+str(i)) for i in range(5)]+[('保证方式约定不明应如何承担保证责任','https://example.org/target')]
        ranked=rank_web_links(found,{'core_issue':'保证方式约定不明的责任'})
        self.assertEqual(ranked[0][1],'https://example.org/target')

    def test_source_snippet_guides_reading_when_case_title_has_only_names(self):
        from backend.public_case_discovery import rank_web_links,parse_360_results
        html='<li class="res-list"><h3><a href="https://example.org/party">甲与乙判决</a></h3>保证方式未约定，应承担一般保证责任。</li>'
        hits=[('其他标题','https://example.org/other','与目标无关')]+parse_360_results(html,with_snippets=True)
        ranked=rank_web_links(hits,{'core_issue':'保证方式未约定的一般保证责任'})
        self.assertEqual(ranked[0],('甲与乙判决','https://example.org/party'))

    def test_ai_answers_video_and_navigation_are_not_judgment_leads(self):
        from backend.public_case_discovery import parse_360_results
        html='<li class="res-list"><h3><a href="https://ai.so.com/generated">AI观点</a></h3><h3><a href="https://example.org/movie">案例视频</a></h3></li><h3><a href="https://example.org/trending">热门新闻</a></h3>'
        self.assertEqual(parse_360_results(html),[])


class ArticleLeadsTests(unittest.TestCase):
    def test_links_are_assigned_to_the_named_docket_in_a_multi_case_page(self):
        html = '''<article>（2024）示民初1号、（2024）示民初2号。
        <a href="https://cn.govopendata.com/anonymous/">（2024）示民初2号判决书全文</a>
        <a href="https://cn.govopendata.com.example.org/">（2024）示民初1号判决书全文</a></article>'''
        first, second = article_case_leads(html, 'https://m.thepaper.cn/example')
        self.assertNotIn('document_links', first)
        self.assertEqual(second['document_links'], ['https://cn.govopendata.com/anonymous/'])

    def test_compilation_numbers_are_bounded_deduplicated_and_sourced(self):
        html='<nav>（2020）示民初999号</nav><article>案例一（2024）示民初1号；重复(2024)示民初1号；案例二（2024）示民初2号；案例三（2024）示民初3号；案例四（2024）示民初4号</article>'
        leads=article_case_leads(html,'https://example.org/article')
        self.assertEqual([v['case_number'] for v in leads],['（2024）示民初1号','（2024）示民初2号','（2024）示民初3号'])
        self.assertTrue(all(v['source_url']=='https://example.org/article' for v in leads))

    def test_explicit_court_prefix_is_preserved_in_normalized_docket(self):
        lead=article_case_leads('<article>最高院(2024)民终678号判决</article>','https://example.org')[0]
        self.assertEqual(lead['case_number'],'(2024)最高法民终678号')
        self.assertEqual(lead['raw_citation'],'(2024)民终678号')
        self.assertIn('最高院',lead['context'])

    def test_incomplete_docket_is_not_invented(self):
        self.assertEqual(article_case_leads('<p>最高法民终212号</p>','https://example.org'),[])


class OutputBoundariesTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_assessment_is_retried_before_finishing(self):
        court='本院认为，已经通知保证人，应承担保证责任。'
        case=dict(title='匿名保证纠纷判决',case_number='（2024）示民初8号',source_url='https://example.org/8',source='公开存档',holding=court,adjudicated_facts='',source_kind='public_web',retrieved_by=[],remote_score=.5)
        plan={'groups':[['保证']], 'queries':['保证 通知'], 'paths':[{'required_facts':['已通知保证人'], 'queries':['保证 通知']}]}
        assessment={'cases':[{'index':0,'path_id':'p0','stance':'support','quote':court,'fact_checks':[{'fact_index':0,'status':'established','proof_kind':'court_finding','quote':'已经通知保证人'}]}]}
        replies=[plan, {'cases':[]}, assessment, {'reviews':[{'index':0,'verdict':'supported'}]}]
        async def model(*a,**kw):return {'text':json.dumps(replies.pop(0),ensure_ascii=False)},'fixture'
        result=dict(cases=[case],coverage={},metrics={},retrieval_runs=[{'lead_case_number':'（2024）示民初99号','lead_source_url':'https://example.org/99','lead_from_snippet':True}],errors=[])
        search=AsyncMock(return_value=result)
        with patch('backend.public_case_answer.search_cases_structured',search):
            value=await answer_public_cases('保证通知事实测试','fixture',None,None,resolve=AsyncMock(return_value='保证通知事实测试'),call_plan=model,extract=lambda d:(d['text'],'',''),call_answer=AsyncMock(),progress=lambda *a,**kw:None)
        self.assertEqual(search.await_count,1)
        self.assertEqual(replies,[])
        self.assertEqual(value['case_research']['coverage']['counts']['support'],1)
        self.assertEqual(value['case_research']['pending_cases'],[])
        self.assertEqual(len(value['case_research']['source_leads']),1)
        self.assertNotIn('示民初99',value['answer'])
        self.assertIn('示民初8',value['answer'])

    async def test_partial_support_and_unreviewed_are_not_exclusions(self):
        court='本院认为，应当结合通知及履行情况确定保证责任。'
        case=dict(title='匿名保证纠纷判决',case_number='（2024）示民初1号',source_url='https://example.org/1',source='公开存档',holding=court,adjudicated_facts='',source_kind='public_web',retrieved_by=[],remote_score=.5)
        pending=dict(case,title='匿名另一判决',case_number='（2024）示民初2号',source_url='https://example.org/2')
        replies=[{'groups':[['保证']], 'queries':['保证 通知'], 'paths':[{'required_facts':['已通知保证人'], 'queries':['保证 通知']}]}, {'cases':[{'index':0,'path_id':'p0','stance':'related','quote':court,'fact_checks':[],'reason':'尚未证明已通知'}]}, {}]
        async def model(*a,**kw):return {'text':json.dumps(replies.pop(0),ensure_ascii=False)},'fixture'
        result=dict(cases=[case,pending],coverage={},metrics={},retrieval_runs=[],errors=[])
        with patch('backend.public_case_answer.search_cases_structured',AsyncMock(return_value=result)):
            value=await answer_public_cases('保证通知事实测试','fixture',None,None,resolve=AsyncMock(return_value='保证通知事实测试'),call_plan=model,extract=lambda d:(d['text'],'',''),call_answer=AsyncMock(),progress=lambda *a,**kw:None)
        self.assertEqual(value['case_research']['coverage']['counts']['support'],0)
        self.assertEqual(len(value['case_research']['cases']),1)
        self.assertEqual(len(value['case_research']['pending_cases']),1)
        self.assertEqual(value['case_research']['excluded_cases'],[])
        self.assertIn('关系：仅部分相关',value['answer'])
        self.assertIn('尚缺：已通知保证人',value['answer'])
        self.assertNotIn('待核验线索',value['answer'])
        self.assertNotIn('（2024）示民初2号',value['answer'])
        self.assertNotIn('排除记录',value['answer'])


class LeadFollowTests(unittest.IsolatedAsyncioTestCase):
    async def test_index_discovers_links_without_accepting_search_text_as_evidence(self):
        import httpx
        archive = 'https://wenshu.nlaw.org/Civil/anonymous.html'
        summary = 'https://www.chinalawyer.co/blog/anonymous'
        html = '<main>某县人民法院 民事判决书（2024）示民终18号。法院查明，双方完成对账。' \
               '本院认为，应根据对账金额支付劳动报酬。判决如下：驳回上诉。</main>'
        index = AsyncMock(return_value=[('劳动争议判决书', archive, '双方完成对账'),
                                        ('劳动争议判决书', summary, html)])

        async def get(url, **options):
            content = {archive:html, summary:'<main>某律师解读劳动争议裁判规则。</main>'}.get(url, '<rss><channel/></rss>')
            return httpx.Response(200, text=content, headers={'content-type':'text/html'}, request=httpx.Request('GET',url))

        with patch('backend.public_case_transport.CaseRoutes.public_get', side_effect=get), patch(
            'backend.public_case_indexes.search_exa', index
        ):
            result = await discover_cases({'core_issue':'劳动报酬裁判', 'indexed_web_discovery':True})
        self.assertIn('wenshu.nlaw.org', index.await_args.args[1])
        self.assertEqual([case['source_url'] for case in result['cases']], [archive])
        run = next(run for run in result['retrieval_runs'] if run['engines'] == ['Exa'])
        self.assertEqual(run['result_count'], 2)
        self.assertTrue(run['search_hints'])

    async def test_index_accepts_structured_rows_and_distinguishes_service_error(self):
        import json
        from backend.public_case_indexes import search_exa

        rows = [{'url':'https://example.org/case','title':'公开判决','text':'原始搜索摘要'},
                {'url':'https://account@example.org/case','title':'凭证链接'}]
        event = {'jsonrpc':'2.0','id':1,'result':{'content':[{'type':'text','text':json.dumps({'results':rows})}]}}
        with patch('backend.public_case_indexes._post', AsyncMock(return_value='event: message\ndata: '+json.dumps(event))) as post:
            self.assertEqual(await search_exa(['劳动争议','劳动报酬'], ['example.org']),
                             [('公开判决','https://example.org/case','原始搜索摘要')])
            self.assertEqual(post.await_args.args[1]['params']['arguments']['additionalQueries'], ['劳动报酬'])
        with patch('backend.public_case_indexes._post', AsyncMock(return_value='{"id":1,"error":{"code":-32000}}')):
            with self.assertRaisesRegex(ValueError, '不可用或达到请求上限'):
                await search_exa(['劳动争议'], ['example.org'])

    async def test_explicit_document_and_retry_reads_retain_their_evidence_checks(self):
        import httpx
        archive = 'https://example.org/document'
        retry = 'https://example.org/retry'
        html = '<main>某县人民法院 民事判决书（2024）示民终18号。法院查明，双方完成对账。' \
               '本院认为，应根据对账金额支付劳动报酬。判决如下：驳回上诉。</main>'
        requested = []

        async def get(url, **options):
            if url in (archive, retry):
                requested.append((url, options['document']))
                content = html
            else:
                content = '<rss><channel/></rss>'
            return httpx.Response(200, text=content, headers={'content-type':'text/html'}, request=httpx.Request('GET',url))

        with patch('backend.public_case_transport.CaseRoutes.public_get', side_effect=get):
            result = await discover_cases({
                'core_issue':'工资结算', 'document_urls':[archive],
                'retry_documents':[{'document_url':retry,'document_title':'工资结算','document_number':'（2024）示民终19号'}],
            })
        self.assertCountEqual(requested, [(archive, True), (retry, True)])
        self.assertEqual([case['source_url'] for case in result['cases']], [archive])
        self.assertTrue(any(e.get('document_url') == retry and not e['retryable'] for e in result['errors']))

    async def test_scoped_archive_retrieves_full_body_without_unscoped_result(self):
        import httpx
        from urllib.parse import unquote_plus, urlsplit

        archive = 'https://cn.govopendata.com/caipanwenshu/anonymous/'
        fake = 'https://cn.govopendata.com.example.org/judgment'
        fetched = []

        async def get(url, **options):
            host = urlsplit(url).hostname
            query = unquote_plus(url)
            content = ''
            if host == 'www.so.com' and 'site:cn.govopendata.com' in query:
                self.assertNotIn(' OR site:', query)
                content = f'<li class="res-list"><h3><a href="/link?m=1" data-mdurl="{fake}">匿名判决</a></h3></li><li class="res-list"><h3><a href="/link?m=2" data-mdurl="{archive}">匿名判决</a></h3></li>'
            elif host == 'cn.bing.com':
                content = '<rss><channel/></rss>'
            elif host not in {'www.so.com', 'www.google.com', 'www.sogou.com'}:
                self.assertTrue(options['document'])
                fetched.append(url)
                content = '<main><h1>匿名文书</h1><p>某县人民法院 民 事 判 决 书（2014） 示民初字 第 18 号</p><p>经审理查明，甲方按约付款。</p><p>本院认为，争议合同已经履行。判决如下：驳回请求。</p></main>'
            return httpx.Response(200, text=content, headers={'content-type':'text/html'}, request=httpx.Request('GET',url))

        with patch('backend.public_case_transport.CaseRoutes.public_get', side_effect=get):
            result = await discover_cases({'core_issue':'合同履行', 'semantic_review':True})

        self.assertEqual(fetched, [archive])
        self.assertEqual(len(result['cases']), 1)
        self.assertIn('示民初字 第 18 号', result['cases'][0]['case_number'])
        self.assertEqual(result['cases'][0]['source'], '裁判文书公开存档（转载）')
        self.assertTrue(any(r.get('returned_sites') == ['cn.govopendata.com'] for r in result['retrieval_runs']))

    async def test_known_court_and_media_articles_are_docket_leads(self):
        from backend.public_case_discovery import parse_page
        html = '<article><h1>审判案例评析</h1>文章评析某县人民法院（2024）示民初1号。本院认为，合同已经履行。判决如下：驳回。</article>'
        for url in ('https://www.gzcourt.gov.cn/example', 'https://m.thepaper.cn/example'):
            self.assertIsNone(parse_page('', url, html, []))
            self.assertEqual(article_case_leads(html, url)[0]['case_number'], '（2024）示民初1号')

    async def test_cited_docket_is_followed_but_similar_docket_cannot_replace_it(self):
        import httpx
        article='<article>案例一（2024）示民初1号；案例二（2024）示民初2号；本文分析责任。</article>'
        body='<article>某市人民法院（2024）示民初99号。本院认为，应当依法支持该项责任。判决如下：支持。</article>'
        async def get(url, **options):
            if 'google.com/search' in url:
                content='<h3>empty</h3>' if '判决书' not in __import__('urllib.parse',fromlist=['unquote_plus']).unquote_plus(url) else '<a href="https://example.org/wrong"><h3>判决书</h3></a>'
            elif 'bing.com/search' in url:content='<rss><channel><item><title>保证责任</title><link>https://example.org/article</link><description>保证责任</description></item></channel></rss>'
            elif 'sogou.com' in url:content=''
            elif url.endswith('/article'):content=article
            else:content=body
            return httpx.Response(200,text=content,headers={'content-type':'text/html'},request=httpx.Request('GET',url))
        with patch('backend.public_case_transport.CaseRoutes.public_get',side_effect=get), patch('backend.public_case_web._search_wikisource_cases',AsyncMock(return_value={'cases':[],'retrieval_runs':[],'errors':[]})):
            result=await discover_cases({'semantic_review':True,'required_term_groups':[['保证责任']],'research_paths':[{'id':'p0','queries':['保证责任 未通知']}]})
        self.assertEqual(result['cases'],[])
        queries=[r['query'] for r in result['retrieval_runs']]
        self.assertIn('（2024）示民初1号 判决书',queries)
        self.assertIn('（2024）示民初2号 判决书',queries)
        self.assertLessEqual(len(queries),11)  # five additional site queries
        self.assertTrue(all(r.get('lead_source_url')=='https://example.org/article' for r in result['retrieval_runs'] if r['query'].endswith('判决书')))
