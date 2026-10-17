"""Anonymous Responses fixtures exercise protocol and both shared AI gateways."""
import json
import unittest
from contextlib import asynccontextmanager
from unittest.mock import patch

import httpx
from backend import ai_client, ai_config, ai_responses, main
from backend.ai_transport import DELTA, FINAL

MODEL = 'opencode:grok-4.7'
MESSAGES = [{'role': 'system', 'content': 'Answer briefly.'},
            {'role': 'user', 'content': 'Remember blue.'},
            {'role': 'assistant', 'content': 'OK'},
            {'role': 'user', 'content': 'Which color?'}]


def result(status='completed'):
    return {'status': status, 'output': [
        {'type': 'reasoning', 'summary': [{'text': 'private reasoning'}]},
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'blue'}]}],
        'usage': {'input_tokens': 12, 'output_tokens': 3, 'total_tokens': 15,
                  'input_tokens_details': {'cached_tokens': 4}}}


def sse(*events):
    return ''.join('event: ignored\ndata: ' + json.dumps(e) + '\n\n' for e in events)


class ResponsesTests(unittest.IsolatedAsyncioTestCase):
    def test_routing_and_usage(self):
        url = 'https://example.test/custom/v1/chat/completions?route=one'
        self.assertEqual(ai_config.opencode_model_url(MODEL, url),
                         'https://example.test/custom/v1/responses?route=one')
        self.assertEqual(ai_config.opencode_model_url('opencode:deepseek-flash', url), url)
        self.assertIn(MODEL, ai_config.ALLOWED_MODELS)
        self.assertEqual(ai_client.api_config(MODEL)[2], 'grok-4.7')
        self.assertEqual(main._get_api_config(MODEL)[2], 'grok-4.7')
        value = ai_responses.normalize_response(result()).json()
        self.assertEqual(value['choices'][0]['message']['content'], 'blue')
        self.assertEqual(value['choices'][0]['message']['reasoning_content'], '')
        self.assertEqual(value['usage']['total_tokens'], 15)
        self.assertEqual(value['usage']['prompt_tokens_details']['cached_tokens'], 4)
        truncated = result('incomplete')
        truncated['incomplete_details'] = {'reason': 'max_output_tokens'}
        self.assertEqual(ai_responses.normalize_response(truncated).json()['choices'][0]['finish_reason'], 'length')
        for bad in [{}, {'status': 'failed'}, {'status': 'incomplete'}, {'status': 'completed', 'error': {'message': 'bad'}}]:
            with self.assertRaises(httpx.RemoteProtocolError):
                ai_responses.normalize_response(bad)

    async def test_nonstream_payload_and_shared_gateways(self):
        requests = []
        def handle(request):
            requests.append(request)
            return httpx.Response(200, json=result())
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            @asynccontextmanager
            async def pool(**kwargs):
                yield client
            config = ('https://example.test/v1/responses', 'anonymous-key', 'grok-4.7')
            with patch.object(ai_client, 'ai_http_client', pool), patch.object(ai_client, 'api_config', return_value=config):
                value, used = await ai_client.call_ai_with_fallback(MODEL, MESSAGES, max_tokens=400)
                self.assertEqual(used, MODEL)
                self.assertEqual(value['choices'][0]['message']['content'], 'blue')
            with patch.object(main, 'ai_http_client', pool), patch.object(main, '_get_api_config', return_value=config):
                response, used = await main._call_ai_with_fallback(MODEL, MESSAGES, max_tokens=400)
                self.assertEqual(used, MODEL)
                self.assertEqual(response['choices'][0]['message']['content'], 'blue')
        for req in requests:
            payload = json.loads(req.content)
            self.assertEqual(payload['input'], MESSAGES)
            self.assertFalse(payload['store'])
            self.assertFalse(payload['stream'])
            self.assertEqual(payload['max_output_tokens'], 400)
            self.assertNotIn('previous_response_id', payload)
            self.assertNotIn('temperature', payload)
            self.assertNotIn('tools', payload)
            self.assertIn('x-opencode-session', req.headers)

    async def test_stream_text_only_and_terminal_required(self):
        events = [{'type': 'response.reasoning_summary_text.delta', 'delta': 'private'},
                  {'type': 'response.output_text.delta', 'delta': 'bl'},
                  {'type': 'response.output_text.delta', 'delta': 'ue'},
                  {'type': 'response.completed', 'response': result()}]
        calls = []
        async def callback(kind, value):
            calls.append((kind, value))
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda r: httpx.Response(200, headers={'content-type': 'text/event-stream'}, text=sse(*events)))) as client:
            value = await ai_responses.call_responses(client, 'https://example.test', 'grok-4.7', MESSAGES, 400, {}, callback)
        self.assertEqual(calls, [('reset', ''), ('delta', 'bl'), ('delta', 'ue')])
        self.assertEqual(value.json()['choices'][0]['message']['content'], 'blue')
        for body in [sse(*events[:3]), sse({'type': 'response.failed'}), 'data: broken\n\n', 'data: [DONE]\n\n']:
            async with httpx.AsyncClient(transport=httpx.MockTransport(
                    lambda r: httpx.Response(200, headers={'content-type': 'text/event-stream'}, text=body))) as client:
                with self.assertRaises(httpx.RemoteProtocolError):
                    await ai_responses.call_responses(client, 'https://example.test', 'grok-4.7', MESSAGES, 400, {}, callback)

    async def test_rate_limit_preserves_existing_fallback(self):
        requests = []
        def handle(request):
            payload = json.loads(request.content)
            requests.append(payload)
            if payload['model'] == 'grok-4.7':
                return httpx.Response(429, json={'error': 'rate limited'})
            return httpx.Response(200, json={'choices': [{'message': {'content': 'fallback'}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            @asynccontextmanager
            async def pool(**kwargs):
                yield client
            with patch.object(ai_client, 'ai_http_client', pool), patch.object(ai_client, 'fallback_model', return_value='opencode:deepseek-flash'), patch.object(ai_client, 'OPENCODE_API_KEY', 'anonymous'):
                value, used = await ai_client.call_ai_with_fallback(MODEL, MESSAGES)
        self.assertEqual(used, 'opencode:deepseek-flash')
        self.assertIn('input', requests[0])
        self.assertIn('messages', requests[1])

    async def test_foreground_uses_responses_stream(self):
        calls = []
        async def callback(kind, text):
            calls.append((kind, text))
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda r: httpx.Response(200, headers={'content-type': 'text/event-stream'}, text=sse(
                    {'type': 'response.output_text.delta', 'delta': 'blue'},
                    {'type': 'response.completed', 'response': result()})))) as client:
            @asynccontextmanager
            async def pool(**kwargs):
                yield client
            t1, t2 = DELTA.set(callback), FINAL.set(True)
            try:
                with patch.object(main, 'ai_http_client', pool), patch.object(main, '_get_api_config', return_value=('https://example.test/v1/responses', 'anonymous', 'grok-4.7')):
                    response, used = await main._call_ai_with_fallback(MODEL, MESSAGES)
                self.assertEqual(used, MODEL)
                self.assertEqual(response['choices'][0]['message']['content'], 'blue')
                self.assertEqual(calls, [('reset', ''), ('delta', 'blue')])
            finally:
                DELTA.reset(t1)
                FINAL.reset(t2)
