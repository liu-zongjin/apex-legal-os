import json
import unittest
from unittest.mock import AsyncMock, patch

from backend import main, ai_client, ai_config


class DirectAITests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_mode_never_opens_knowledge_database(self):
        response = {'choices': [{'message': {'content': '原始回答'}}]}
        call = AsyncMock(return_value=(response, 'deepseek-chat'))
        with patch.object(main, 'get_db', side_effect=AssertionError('KB accessed')), patch.object(
                main, '_resolve_follow_up_question', side_effect=AssertionError('KB routing')), patch.object(
                main, '_call_ai_with_fallback', call), patch('backend.case_files._general_web_context',
                side_effect=AssertionError('search not requested')):
            result = await main.ask_question(question='你是什么模型', model='deepseek-chat',
                source_mode='direct_ai', conversation_context=json.dumps([
                    {'role': 'user', 'content': '记住数字8'}, {'role': 'ai', 'content': '好的'}]),
                skill_id=None, request_id=None)
        self.assertEqual(result['answer'], '原始回答')
        self.assertEqual(result['sources'], [])
        self.assertEqual(result['external_sources'], [])
        messages = call.call_args.args[1]
        self.assertEqual(messages[-1], {'role': 'user', 'content': '你是什么模型'})
        self.assertTrue(any(m['role'] == 'assistant' for m in messages))

    async def test_web_results_are_available_to_every_provider(self):
        for model in ['deepseek-chat', 'doubao:Doubao-Seed-2.0-mini', 'cc2api:claude-sonnet-4-6']:
            source = {'title': '匿名网页', 'url': 'https://example.org', 'source_type': 'public_web'}
            call = AsyncMock(return_value=({'choices': [{'message': {'content': '回答'}}]}, model))
            with patch.object(main, 'get_db', side_effect=AssertionError('KB accessed')), patch.object(
                    main, '_call_ai_with_fallback', call), patch.object(main, '_plan_direct_web_search',
                    AsyncMock(return_value={'search_needed':True,'queries':['最新消息'],'required_terms':['消息']})), patch('backend.case_files._general_web_context',
                    AsyncMock(return_value=('匿名网页内容', [source], ''))):
                result = await main.ask_question(question='最新消息', model=model,
                    source_mode='direct_ai_web', conversation_context=None, skill_id=None, request_id=None)
            self.assertTrue(result['web_search_used'])
            self.assertEqual(result['external_sources'], [source])
            self.assertTrue(any('匿名网页内容' in m['content'] for m in call.call_args.args[1]))
            self.assertEqual(result['sources'], [])

    def test_doubao_catalog_and_mini_endpoint(self):
        for model in ['doubao:doubao-seed-2-1-pro-260915', 'doubao:doubao-seed-2-1-lite-260915']:
            self.assertIn(model, ai_config.ALLOWED_MODELS)
            self.assertEqual(ai_client.api_config(model)[2], model.split(':', 1)[1])
        self.assertEqual(ai_client.api_config('doubao:Doubao-Seed-2.0-mini')[2], 'doubao-seed-2-0-mini-260428')
