import asyncio
import unittest
from unittest.mock import patch

import httpx

from backend import ai_client, ai_config


class CC2APITests(unittest.TestCase):
    def test_catalog_routes_every_gateway_model(self):
        for model, _ in ai_config.ask_models('cc2api'):
            self.assertIn(model, ai_config.ALLOWED_MODELS)
            self.assertEqual(ai_client.api_config(model)[2], model.split(':', 1)[1])

    def test_system_blocks_are_separate_and_input_is_unchanged(self):
        payload = {'model': 'claude-sonnet-4-6', 'max_tokens': 64, 'messages': [
            {'role': 'system', 'content': 'Instructions'},
            {'role': 'user', 'content': 'Question'},
            {'role': 'assistant', 'content': 'Previous answer'},
        ]}
        headers, body = ai_client.prepare_cc2api_request('fixture', payload)
        self.assertEqual(body['system'], [{'type': 'text', 'text': 'Instructions'}])
        self.assertEqual([m['role'] for m in body['messages']], ['user', 'assistant'])
        self.assertEqual(payload['messages'][0]['role'], 'system')
        self.assertEqual(headers['User-Agent'], 'Stella/1.0')
        self.assertEqual(headers['anthropic-version'], '2023-06-01')

    def test_response_preserves_thinking_and_truncation(self):
        response = httpx.Response(200, json={'type': 'message', 'content': [
            {'type': 'thinking', 'thinking': 'Reason'},
            {'type': 'text', 'text': 'Answer'},
        ], 'stop_reason': 'max_tokens', 'usage': {'input_tokens': 9, 'output_tokens': 4}})
        data = ai_client.normalize_cc2api_response(response).json()
        self.assertEqual(data['choices'][0]['message']['content'], 'Answer')
        self.assertEqual(data['choices'][0]['message']['reasoning_content'], 'Reason')
        self.assertEqual(data['choices'][0]['finish_reason'], 'length')
        self.assertEqual(data['usage']['completion_tokens'], 4)
        error = httpx.Response(503, json={'error': {'message': 'restricted'}})
        self.assertIs(ai_client.normalize_cc2api_response(error), error)

    def test_shared_client_uses_messages_and_returns_choices(self):
        async def run():
            seen = []
            def handler(request):
                seen.append(request)
                return httpx.Response(200, json={'type': 'message', 'content': [
                    {'type': 'text', 'text': 'OK'}], 'stop_reason': 'end_turn'})
            factory = httpx.AsyncClient
            transport = httpx.MockTransport(handler)
            with patch.object(ai_client, 'CC2API_API_KEY', 'fixture'), patch.object(
                ai_client.httpx, 'AsyncClient', side_effect=lambda **kw: factory(transport=transport, **kw)
            ):
                result, model = await ai_client.call_ai_with_fallback(
                    'cc2api:claude-sonnet-4-6', [{'role': 'user', 'content': 'OK'}])
            self.assertEqual(result['choices'][0]['message']['content'], 'OK')
            self.assertEqual(model, 'cc2api:claude-sonnet-4-6')
            self.assertEqual(seen[0].url.path, '/v1/messages')
            self.assertEqual(seen[0].headers['Authorization'], 'Bearer fixture')
        asyncio.run(run())
