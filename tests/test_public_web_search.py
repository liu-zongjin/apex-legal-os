import asyncio
import unittest
from unittest.mock import patch, AsyncMock

import httpx

from backend import public_web_search as web, main


class PublicWebSearchTests(unittest.IsolatedAsyncioTestCase):
    def test_large_pages_keep_late_facts_and_qualifiers_with_bounded_input(self):
        html = '<main>' + '<p>网站新闻、订阅与重复介绍。</p>'*3000 + (
            '<p>匿名相机售价为1999元。但是该价格不含镜头，仅限2026年10月17日。</p>'
            '<p>匿名相机重量为500克。</p></main>')
        excerpt = web.page_excerpt(html, ['匿名相机', '售价|重量'])
        text, sources = web.pack_web_context([
            ('官方参数', 'https://example.org/a', excerpt),
            ('重复转载', 'https://example.org/b', excerpt),
        ], ['匿名相机', '售价|重量'], '2026-10-17', max_bytes=3000)
        self.assertLessEqual(len(text.encode()), 3000)
        for fact in ('1999元', '不含镜头', '2026年10月17日', '500克'):
            self.assertIn(fact, text)
        self.assertEqual(len(sources), 1)
        self.assertLess(len(text.encode()), len(html.encode())//20)

    def test_pack_retains_distinct_aspects_and_source_markers(self):
        pages = [('售价', 'https://example.org/price', '匿名相机售价1999元。'),
                 ('参数', 'https://example.org/spec', '匿名相机重量500克。'),
                 ('保修', 'https://example.org/warranty', '匿名相机保修期限2年。')]
        text, sources = web.pack_web_context(pages, ['匿名相机', '售价|重量|保修'], '2026-10-17', 4000)
        self.assertEqual(len(sources), 3)
        for i in range(1, 4):
            self.assertIn(f'[WEB:{i}]', text)
        for fact in ('1999元', '500克', '2年'):
            self.assertIn(fact, text)
        self.assertGreater(web.evidence_budget('逐项对比所有参数', {}), web.evidence_budget('价格是多少', {}))

    def test_small_budgets_never_advertise_unrepresented_sources(self):
        pages = [('参数', 'https://example.org/spec', '匿名相机售价1999元。')]
        self.assertEqual(web.pack_web_context(pages, ['匿名相机'], '2026-10-17', 10), ('', []))

    def test_publication_metadata_and_table_units_survive_selection(self):
        excerpt=web.page_excerpt('<meta property="article:published_time" content="2026-09-01">'
            '<main><table><tr><td>匿名相机重量</td><td>500</td><td>克</td></tr></table></main>', ['匿名相机','重量'])
        text,sources=web.pack_web_context([('规格','https://example.org/spec',excerpt)],
            ['匿名相机','重量'],'2026-10-17',3000)
        self.assertIn('页面日期字段：2026-09-01',text)
        self.assertIn('检索时间：2026-10-17',text)
        self.assertIn('匿名相机重量 | 500 | 克',text)

    async def test_identity_questions_skip_planner_and_external_search(self):
        with patch.object(main, '_call_ai_with_fallback', side_effect=AssertionError('unnecessary paid planning call')):
            plan = await main._plan_direct_web_search('你是什么模型？', 'fixture', [])
        self.assertFalse(plan['search_needed'])

    async def test_planner_timeout_has_local_query_fallback(self):
        with patch.object(main, '_call_ai_with_fallback', AsyncMock(side_effect=asyncio.TimeoutError)):
            plan=await main._plan_direct_web_search('检索 docs.python.org 官方文档：list.append 的作用是什么？', 'fixture', [])
        self.assertTrue(plan['search_needed'])
        self.assertIn('list.append',plan['required_terms'])
        self.assertIn('site:docs.python.org',plan['queries'][0])
        self.assertNotIn('docs',plan['required_terms'])

    async def test_filters_irrelevant_hits_and_uses_multiple_queries(self):
        seen = []
        def handler(request):
            seen.append(str(request.url))
            if request.url.host == 'cn.bing.com':
                return httpx.Response(200, text='''<rss><channel>
                  <item><title>明天 小说</title><link>https://irrelevant.example/story</link><description>鲁迅短篇小说</description></item>
                  <item><title>广州天气预报</title><link>https://forecast.example/guangzhou</link><description>广州气温预报</description></item>
                  <item><title>驿城天气预报</title><link>https://irrelevant.example/weather</link><description>驿城天气</description></item>
                </channel></rss>''')
            return httpx.Response(200, headers={'Content-Type':'text/html'}, text='<main>广州天气预报，10月10日最高30℃、最低24℃</main>')
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with patch.object(web.httpx, 'AsyncClient', return_value=client), patch.object(web, 'public_host', return_value=True):
            text, sources, warning = await web.general_web_context('明天广州多少度', plan={
                'queries':['"广州" "天气预报"','"广州" "气温"'], 'required_terms':['广州','天气|气温']})
        self.assertEqual(len(sources), 1)
        self.assertIn('30℃', text)
        self.assertNotIn('小说', text)
        self.assertFalse(warning)
        self.assertEqual(len([u for u in seen if 'cn.bing.com' in u]), 3)
        self.assertFalse(any('irrelevant.example' in u for u in seen))

    async def test_empty_or_unrelated_results_are_not_search_success(self):
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text='<rss><channel/></rss>')))
        with patch.object(web.httpx, 'AsyncClient', return_value=client), patch.object(web, 'public_host', return_value=True):
            text, sources, warning = await web.general_web_context('匿名相机售价', plan={
                'queries':['匿名相机 售价'],'required_terms':['匿名相机']})
        self.assertEqual((text, sources), ('', []))
        self.assertTrue(warning)

    async def test_redirect_to_private_network_is_rejected(self):
        seen = []
        def handler(r):
            seen.append(str(r.url))
            return httpx.Response(302, headers={'Location':'http://127.0.0.1/private'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with patch.object(web, 'public_host', side_effect=lambda u: '127.0.0.1' not in u):
                with self.assertRaises(ValueError):
                    await web.public_get(client,'https://public.example')
        self.assertEqual(len(seen),1)

    async def test_secondary_engine_and_meta_redirect_resolve_original_page(self):
        def handler(request):
            if request.url.host == 'cn.bing.com':
                return httpx.Response(200, text='<rss><channel/></rss>')
            if request.url.path == '/web':
                return httpx.Response(200, text='<div><h3><a href="/link">匿名相机官方说明</a></h3>匿名相机使用手册</div>')
            if request.url.path == '/link':
                return httpx.Response(200, headers={'Content-Type':'text/html'}, text='<meta http-equiv="refresh" content="0;URL=https://manual.example/camera">')
            return httpx.Response(200, headers={'Content-Type':'text/html'}, text='<main>匿名相机使用手册，具体操作步骤</main>')
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with patch.object(web.httpx, 'AsyncClient', return_value=client), patch.object(web, 'public_host', return_value=True):
            text, sources, warning = await web.general_web_context('匿名相机使用手册', plan={
                'queries':['匿名相机使用手册'], 'required_terms':['匿名相机','使用手册']})
        self.assertEqual(sources[0]['url'], 'https://manual.example/camera')
        self.assertIn('具体操作步骤', text)
        self.assertFalse(warning)

    async def test_incorrect_gzip_header_does_not_hide_plain_html(self):
        def handler(request):
            return httpx.Response(200, headers={'Content-Type':'text/html','Content-Encoding':'gzip'},
                stream=httpx.ByteStream(b'<main>content</main>'))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with patch.object(web, 'public_host', return_value=True):
                result = await web.public_get(client, 'https://public.example')
        self.assertIn('content', result.text)

    async def test_planner_passes_date_and_followup_context(self):
        response={'choices':[{'message':{'content':'{"search_needed":true,"queries":["\\"深圳\\" \\"天气\\""],"required_terms":["深圳","天气|气温"]}'}}]}
        call=AsyncMock(return_value=(response,'deepseek-flash'))
        with patch.object(main,'_call_ai_with_fallback',call):
            plan=await main._plan_direct_web_search('那深圳呢','deepseek-flash',[{'role':'user','content':'明天广州多少度'}])
        self.assertEqual(plan['required_terms'][0],'深圳')
        self.assertIn('Asia/Shanghai',call.call_args.args[1][0]['content'])
        self.assertIn('明天广州',call.call_args.args[1][1]['content'])
