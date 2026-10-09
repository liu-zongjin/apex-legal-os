import asyncio
import json
import unittest
from unittest.mock import patch

import httpx

from backend import ai_client, ai_config, cc2api_bridge as bridge


class FakeProcess:
    returncode = 0
    killed = False
    inputs = []

    async def communicate(self, data=None):
        self.inputs.append(data)
        return json.dumps({"subtype": "success", "is_error": False, "result": "OK",
                           "stop_reason": "end_turn", "usage": {"input_tokens": 9,
                           "output_tokens": 4}}).encode(), b""

    def kill(self):
        self.killed = True
        self.returncode = -9


class CC2APITests(unittest.TestCase):
    def test_catalog_routes_every_gateway_model(self):
        for model, _ in ai_config.ask_models('cc2api'):
            self.assertIn(model, ai_config.ALLOWED_MODELS)
            self.assertEqual(ai_client.api_config(model)[2], model.split(':', 1)[1])

    def test_base_url_keeps_gateway_prefix(self):
        self.assertEqual(bridge.base_url('https://example.invalid/proxy/v1/messages'),
                         'https://example.invalid/proxy')
        self.assertEqual(bridge.base_url('https://example.invalid/'), 'https://example.invalid')
        with self.assertRaises(ValueError):
            bridge.base_url('http://example.invalid')

    def test_history_and_system_instructions_are_preserved(self):
        prompt, system = bridge.conversation_prompt([
            {'role': 'system', 'content': 'Instructions'},
            {'role': 'user', 'content': 'Remember number 8'},
            {'role': 'assistant', 'content': 'Noted'},
            {'role': 'user', 'content': 'Which number?'},
        ])
        turns = json.loads(prompt.split('\n', 1)[1])
        self.assertEqual(system, 'Instructions')
        self.assertEqual([m['role'] for m in turns], ['user', 'assistant', 'user'])
        self.assertEqual(turns[-1]['content'], 'Which number?')
        self.assertEqual(bridge.conversation_prompt([{'role': 'user', 'content': 'OK'}]), ('OK', ''))

    def test_response_preserves_usage_and_truncation(self):
        data = bridge.result_response({'subtype': 'success', 'result': 'Answer',
            'stop_reason': 'max_tokens', 'usage': {'input_tokens': 9, 'output_tokens': 4}}, 'sonnet').json()
        self.assertEqual(data['choices'][0]['message']['content'], 'Answer')
        self.assertEqual(data['choices'][0]['finish_reason'], 'length')
        self.assertEqual(data['usage']['completion_tokens'], 4)
        error = bridge.result_response({'is_error': True, 'api_error_status': 429,
                                        'result': 'sensitive diagnostics'}, 'sonnet')
        self.assertEqual(error.status_code, 429)
        self.assertNotIn('sensitive', error.text)

    def test_shared_client_runs_isolated_official_client(self):
        async def run():
            process = FakeProcess()
            seen = {}
            async def spawn(*args, **kw):
                seen.update(args=args, **kw)
                return process
            with patch.object(ai_client, 'CC2API_API_KEY', 'fixture'), patch.object(
                bridge, 'client_path', return_value='/official/claude'), patch.object(
                bridge.asyncio, 'create_subprocess_exec', side_effect=spawn):
                result, model = await ai_client.call_ai_with_fallback(
                    'cc2api:claude-sonnet-4-6', [{'role': 'user', 'content': 'OK'}])
            self.assertEqual(result['choices'][0]['message']['content'], 'OK')
            self.assertEqual(model, 'cc2api:claude-sonnet-4-6')
            self.assertEqual(seen['args'][0], '/official/claude')
            self.assertIn('--bare', seen['args'])
            self.assertEqual(seen['args'][seen['args'].index('--tools') + 1], '')
            self.assertIn('--no-session-persistence', seen['args'])
            self.assertEqual(seen['env']['ANTHROPIC_AUTH_TOKEN'], 'fixture')
            self.assertEqual(seen['env']['CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC'], '1')
            self.assertEqual(process.inputs[-1], b'OK')
        asyncio.run(run())

    def test_cancellation_and_timeout_kill_child(self):
        class BlockingProcess(FakeProcess):
            returncode = None
            async def communicate(self, data=None):
                if self.killed:
                    return b'', b''
                await asyncio.sleep(100)
        async def run():
            for cancel in (False, True):
                process = BlockingProcess()
                async def spawn(*args, **kw):
                    return process
                with patch.object(bridge, 'client_path', return_value='/official/claude'), patch.object(
                    bridge.asyncio, 'create_subprocess_exec', side_effect=spawn):
                    task = asyncio.create_task(bridge.call_cc2api('https://example.invalid/v1/messages',
                        'fixture', 'sonnet', [{'role': 'user', 'content': 'OK'}], timeout=.01))
                    if cancel:
                        await asyncio.sleep(.001)
                        task.cancel()
                    with self.assertRaises(asyncio.CancelledError if cancel else httpx.ReadTimeout):
                        await task
                    self.assertTrue(process.killed)
        asyncio.run(run())
