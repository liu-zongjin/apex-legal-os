import unittest
from unittest.mock import patch, AsyncMock

import httpx

from backend import public_web_search as web, main


class PublicWebSearchTests(unittest.IsolatedAsyncioTestCase):
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
