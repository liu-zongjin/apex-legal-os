"""Fada source boundaries and integration with the shared AI request lifecycle."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from backend import ai_context, ai_input, main


def item(number, ident, answer, topic='合同', procedure='民事审判'):
    return dict(idx=number, id=ident, question='合同责任如何承担？', answer=answer,
                batch='示例批次', topic=topic, procedure=procedure, legal_basis=[],
                holding=answer, summary=answer, keywords=[], expert='')


class FadaAiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patches = [
            patch.object(main, 'DB_PATH', Path(self.temp.name) / 'anonymous.db'),
            patch.object(ai_context, 'CALL_AI', None),
            patch.object(main, '_plan_ask_intent', new=AsyncMock(return_value={'status': 'skipped', 'tasks': []})),
            patch.object(main, '_resolve_follow_up_question', new=AsyncMock(side_effect=lambda q, history: q)),
            patch.object(main, '_load_fada_structured_items', return_value=[
                item(1, 'fada-11111111', '合同责任依据合同约定确定。'),
                item(2, 'fada-22222222', '另一条答问明确应返还财产。', procedure='执行程序')]),
        ]
        for p in self.patches:
            p.start()
        main.init_db()
        self.call = AsyncMock(return_value=('结论。', None, 'deepseek-flash'))
        p = patch.object(main, '_call_ai_answer_with_continuation', new=self.call)
        p.start()
        self.patches.append(p)

    async def asyncTearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    async def ask(self, **kwargs):
        return await main.fada_ask_question(question='合同责任', model='deepseek-flash', memory_enabled=False, **kwargs)

    async def test_empty_or_missing_scope_never_expands(self):
        for scope in ({'scope_ids': '__empty__'}, {'scope_ids': 'fada-deadbeef'},
                      {'scope_topic': '不存在'}, {'scope_query': '绝无匹配关键词'}):
            result = await self.ask(**scope)
            self.assertEqual(result['retrieved_count'], 0)
            self.assertEqual(result['cited_sources'], [])
        self.call.assert_not_awaited()

    async def test_procedure_scope_and_original_quote(self):
        self.call.return_value = ('应返还。[REF:#2:错误标题]应返还财产。[/REF]', None, 'deepseek-flash')
        result = await self.ask(scope_procedure='执行程序')
        self.assertEqual(result['retrieved_count'], 1)
        self.assertEqual([s['id'] for s in result['cited_sources']], ['fada-22222222'])
        self.assertEqual(result['cited_sources'][0]['source_type'], 'fada')
        self.assertEqual(result['cited_sources'][0]['title'], '合同责任如何承担？')
        sent = self.call.await_args.args[1][-1]['content']
        self.assertNotIn('ID：fada-11111111', sent)

    async def test_unselected_or_fabricated_quotes_are_not_citations(self):
        self.call.return_value = ('结论。[REF:#2:合同]应返还财产。[/REF][REF:#1:合同]虚构原文[/REF]', None, 'deepseek-flash')
        result = await self.ask(scope_ids='fada-11111111')
        self.assertEqual(result['cited_sources'], [])
        self.assertTrue(result['warnings'])

    async def test_uncited_answer_does_not_get_automatic_sources(self):
        result = await self.ask(scope_ids='fada-11111111')
        self.assertEqual(result['cited_sources'], [])

    async def test_shared_reasoning_skill_progress_and_followup(self):
        captured = {}
        async def generate(model, messages, **kwargs):
            captured['scope'] = dict(ai_input.SCOPE.get())
            captured['messages'] = messages
            return '完整结论。', 'reasoning', model
        self.call.side_effect = generate
        with patch.object(main, '_ask_skill_instruction', return_value='所选Skill指令') as skill, \
             patch.object(main, '_resolve_follow_up_question', new=AsyncMock(return_value='补全后的合同责任')):
            result = await self.ask(scope_ids='fada-11111111', reasoning_effort='high', skill_id='sample',
                                    request_id='fada_test_request', conversation_context='[{"role":"user","content":"上文"}]')
        skill.assert_called_once_with('sample', '合同责任')
        self.assertEqual(captured['scope']['reasoning_effort'], 'high')
        self.assertIn('所选Skill指令', captured['messages'][0]['content'])
        self.assertIn('用户原始问题', captured['messages'][-1]['content'])
        self.assertIn('补全后的合同责任', captured['messages'][-1]['content'])
        self.assertEqual(result['reasoning'], 'reasoning')
        self.assertIn('request_usage', result)
        progress = main.get_ask_progress('fada_test_request')
        self.assertEqual(progress['status'], 'complete')
        self.assertIn('searching', [e['stage'] for e in progress['events']])

    async def test_cancel_uses_shared_terminal_state(self):
        started = asyncio.Event()
        async def generate(*args, **kwargs):
            started.set()
            await asyncio.Event().wait()
        self.call.side_effect = generate
        task = asyncio.create_task(self.ask(scope_ids='fada-11111111', request_id='fada_cancel_test'))
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with self.assertRaises(HTTPException) as raised:
            await task
        self.assertEqual(raised.exception.status_code, 499)
        self.assertEqual(main.get_ask_progress('fada_cancel_test')['status'], 'cancelled')

    async def test_legacy_form_contract_keeps_new_fields_optional(self):
        result = await main.fada_ask_question('合同责任', 'deepseek-flash', 'fada-11111111')
        self.assertEqual(result['retrieved_count'], 1)


if __name__ == '__main__':
    unittest.main()
