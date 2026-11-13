import inspect
import unittest
from contextlib import asynccontextmanager
from unittest.mock import patch

import httpx
from fastapi import FastAPI, HTTPException

from backend import ai_input, ai_reasoning, main
from backend.ai_transport import FINAL
from backend.ask_stream import register_ask_stream


class ReasoningTests(unittest.IsolatedAsyncioTestCase):
    async def test_payload_budget_timeout_and_nonfinal_isolation(self):
        calls = []
        timeouts = []
        class Client:
            async def post(self, url, json, headers):
                calls.append(json.copy())
                return httpx.Response(200, json={'choices':[{'message':{'content':'完整回答'}, 'finish_reason':'stop'}]})
        @asynccontextmanager
        async def client(timeout):
            timeouts.append(timeout.read)
            yield Client()
        scope = ai_input.SCOPE.set(ai_input.new_scope('问题'))
        try:
            for level in ('fast', 'low', 'high', 'max'):
                ai_input.SCOPE.get()['reasoning_effort'] = level
                final = FINAL.set(True)
                try:
                    with patch.object(main, '_get_api_config', return_value=('https://example.test', 'key', 'deepseek-flash')), patch.object(main, 'ai_http_client', client):
                        await main._call_ai_with_fallback('deepseek-flash', [{'role':'user','content':'证据' * 20000}], max_tokens=8000)
                finally:
                    FINAL.reset(final)
                payload = calls[-1]
                self.assertEqual(payload['thinking']['type'], 'disabled' if level == 'fast' else 'enabled')
                self.assertEqual(payload.get('reasoning_effort'), None if level == 'fast' else level)
                self.assertEqual(payload['max_tokens'], max(8000, ai_reasoning.BUDGETS.get(level, 0)))
                self.assertEqual(timeouts[-1], ai_reasoning.TIMEOUTS.get(level, 180.0))
            with patch.object(main, '_get_api_config', return_value=('https://example.test', 'key', 'deepseek-flash')), patch.object(main, 'ai_http_client', client):
                await main._call_ai_with_fallback('deepseek-flash', [{'role':'user','content':'规划'}], max_tokens=500)
            self.assertEqual(calls[-1]['thinking']['type'], 'disabled')
            self.assertEqual(calls[-1]['max_tokens'], 500)
        finally:
            ai_input.SCOPE.reset(scope)

    async def test_truncated_thinking_recovers_with_larger_budget(self):
        calls = []
        class Client:
            async def post(self, url, json, headers):
                calls.append(json)
                message = {'content': None, 'reasoning_content': '草稿'} if len(calls) == 1 else {'content': '完整回答。'}
                return httpx.Response(200, json={'choices':[{'message':message,'finish_reason':'length' if len(calls) == 1 else 'stop'}]})
        @asynccontextmanager
        async def client(timeout):
            yield Client()
        scope = ai_input.SCOPE.set(ai_input.new_scope('问题'))
        ai_input.SCOPE.get()['reasoning_effort'] = 'high'
        try:
            with patch.object(main, '_get_api_config', return_value=('https://example.test','key','deepseek-flash')), patch.object(main, 'ai_http_client', client):
                answer, _, model = await main._call_ai_answer_with_continuation('deepseek-flash',[{'role':'user','content':'资料' * 3000}], max_tokens=8000)
            self.assertEqual((answer, model), ('完整回答。','deepseek-flash'))
            self.assertEqual([c['max_tokens'] for c in calls], [32000, 48000])
            self.assertIn('完整性修复', calls[1]['messages'][-1]['content'])
        finally:
            ai_input.SCOPE.reset(scope)

    async def test_fallback_does_not_silently_change_provider(self):
        models = []
        class Client:
            async def post(self, url, json, headers):
                models.append(json['model'])
                raise httpx.ReadTimeout('timeout')
        @asynccontextmanager
        async def client(timeout):
            yield Client()
        scope = ai_input.SCOPE.set(ai_input.new_scope('问题'))
        ai_input.SCOPE.get()['reasoning_effort'] = 'max'
        final = FINAL.set(True)
        try:
            with patch.object(main, '_get_api_config', side_effect=lambda model: ('https://example.test','key',model)), patch.object(main, 'ai_http_client', client), patch.object(main, '_ai_fallback_models', return_value=['deepseek-v4-pro','opencode:deepseek-flash']):
                with self.assertRaises(HTTPException):
                    await main._call_ai_with_fallback('deepseek-flash',[{'role':'user','content':'问题'}])
            self.assertEqual(models, ['deepseek-flash','deepseek-v4-pro'])
        finally:
            FINAL.reset(final)
            ai_input.SCOPE.reset(scope)

    async def test_truncated_answer_continues_and_unrecoverable_empty_fails(self):
        from unittest.mock import AsyncMock
        messages = [{'role':'user','content':'长材料' * 5000}]
        scope = ai_input.SCOPE.set(ai_input.new_scope('问题'))
        ai_input.SCOPE.get()['reasoning_effort'] = 'low'
        try:
            response = lambda content, finish: ({'choices':[{'message':{'content':content},'finish_reason':finish}]}, 'deepseek-flash')
            mock = AsyncMock(side_effect=[response('第一部分', 'length'), response('第二部分。', 'stop')])
            with patch.object(main, '_call_ai_with_fallback', mock):
                answer, _, _ = await main._call_ai_answer_with_continuation('deepseek-flash',messages,max_tokens=8000)
            self.assertEqual(answer, '第一部分第二部分。')
            self.assertIn('第一部分', str(mock.await_args_list[1].args[1]))
            mock = AsyncMock(side_effect=[response('', 'length'), response('', 'stop')])
            with patch.object(main, '_call_ai_with_fallback', mock):
                with self.assertRaises(HTTPException):
                    await main._call_ai_answer_with_continuation('deepseek-flash',messages,max_tokens=8000)
            self.assertEqual(mock.await_count, 2)
        finally:
            ai_input.SCOPE.reset(scope)

    async def test_stream_forwards_reasoning(self):
        seen = {}
        async def answer(**kwargs):
            seen.update(kwargs)
            return {'answer':'完成'}
        app = FastAPI()
        register_ask_stream(app, answer)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            response = await client.post('/api/ask-stream',data={'question':'问题','model':'deepseek-flash','source_mode':'direct_ai','reasoning_effort':'max'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(seen['reasoning_effort'], 'max')

    def test_validation_and_all_standard_routes_accept_effort(self):
        self.assertEqual(ai_reasoning.validate('deepseek-flash', 'max'), 'max')
        for model, value in [('opencode:deepseek-flash','max'),('deepseek-flash','wrong')]:
            with self.assertRaises(HTTPException): ai_reasoning.validate(model, value)
        for name in ('ask_question','ask_tag_question','ask_category_question','ask_article_question','ask_domain_question','ask_author_question'):
            self.assertIn('reasoning_effort', inspect.signature(getattr(main, name)).parameters)
