"""Production-path regressions: real assembly/guard, anonymous data, no paid APIs."""
import asyncio
import json
import sqlite3
import tempfile
import unittest
from contextlib import asynccontextmanager, ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend import ai_context, ai_input, case_ai, case_files, main, ask_cancel


def response(content, finish='stop'):
    return {'choices': [{'message': {'content': content}, 'finish_reason': finish}]}


class ReliabilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(main, 'DB_PATH', self.root / 'anonymous.db'))
        self.stack.enter_context(patch.object(ai_context, 'CALL_AI', None))
        main.init_db()
        self.sent = []

    async def asyncTearDown(self):
        self.stack.close()
        self.temp.cleanup()

    def mock_http(self, handler):
        async def inspect_request(request):
            payload = json.loads(request.content)
            self.sent.append(payload)
            self.assertLessEqual(ai_input.size(payload['messages']) + payload['max_tokens'],
                                 ai_context.model_budget(payload['model']))
            return handler(payload)
        @asynccontextmanager
        async def client(**kwargs):
            async with httpx.AsyncClient(transport=httpx.MockTransport(inspect_request)) as value:
                yield value
        self.stack.enter_context(patch.object(main, 'ai_http_client', client))
        self.stack.enter_context(patch.object(main, '_get_api_config',
            side_effect=lambda model: ('https://anonymous.invalid/chat', 'fixture-key', model)))

    async def test_full_multi_document_sized_input_uses_verified_model_capacity(self):
        # 90,000 Chinese characters used to fail the 64KB guard even with no history.
        content = '\n'.join(f'材料{i}：' + '合同履行后不得忽略例外与否定条件。' * 2000 for i in range(3))
        self.mock_http(lambda payload: httpx.Response(200, json=response('完整回答。')))
        token = ai_input.SCOPE.set({'sections': [], 'audit': []})
        try:
            answer, used = await main._call_ai_with_fallback('deepseek-flash',
                [{'role': 'system', 'content': '完整阅读，不裁切。'}, {'role': 'user', 'content': content}], max_tokens=8000)
        finally:
            ai_input.SCOPE.reset(token)
        self.assertEqual(self.sent[0]['messages'][-1]['content'], content)
        self.assertEqual(used, 'deepseek-flash')

    async def test_multi_source_retrieval_fits_small_fallback_without_mutating_evidence(self):
        self.mock_http(lambda payload: httpx.Response(503) if payload['model'] == 'deepseek-flash'
                       else httpx.Response(200, json=response('完整回答。')))
        self.stack.enter_context(patch.object(main, '_ai_fallback_models', return_value=['fixture-small']))
        sections = [(name, f'【{name}】\n' + ('原文条件不得省略。\n' * 12000)) for name in ('甲来源', '乙来源', '丙来源')]
        messages = [{'role': 'system', 'content': 'MANDATORY_RULE\n' + ''.join(text for _, text in sections)},
                    {'role': 'user', 'content': '比较各来源的合同条件。'}]
        original = json.dumps(messages, ensure_ascii=False)
        token = ai_input.SCOPE.set({'sections': [], 'audit': []})
        try:
            ai_input.register('合同条件', sections)
            _, used = await main._call_ai_with_fallback('deepseek-flash', messages, max_tokens=8000)
            self.assertEqual(len(ai_input.SCOPE.get()['audit']), 3)
        finally:
            ai_input.SCOPE.reset(token)
        self.assertEqual(used, 'fixture-small')
        self.assertEqual(json.dumps(messages, ensure_ascii=False), original)
        self.assertTrue(all(name in self.sent[-1]['messages'][0]['content'] for name, _ in sections))
        self.assertIn('MANDATORY_RULE', self.sent[-1]['messages'][0]['content'])

    async def test_small_incompatible_fallback_does_not_abort_larger_candidate(self):
        self.mock_http(lambda payload: httpx.Response(503) if payload['model'] == 'deepseek-flash'
                       else httpx.Response(200, json=response('完成。')))
        self.stack.enter_context(patch.object(main, '_ai_fallback_models', return_value=['fixture-small', 'deepseek-v4-pro']))
        token = ai_input.SCOPE.set({'sections': [], 'audit': []})
        try:
            _, used = await main._call_ai_with_fallback('deepseek-flash',
                [{'role': 'user', 'content': '完整材料。' * 7000}], max_tokens=8000)
        finally:
            ai_input.SCOPE.reset(token)
        self.assertEqual(used, 'deepseek-v4-pro')
        self.assertEqual([item['model'] for item in self.sent], ['deepseek-flash', 'deepseek-v4-pro'])

    async def test_empty_or_wrong_content_envelope_enters_fallback(self):
        for invalid in ('', None, [{'text': 'un-normalized'}]):
            with self.subTest(invalid=invalid):
                self.mock_http(lambda payload: httpx.Response(200, json=response(invalid if payload['model'] == 'deepseek-flash' else '有效回答。')))
                self.stack.enter_context(patch.object(main, '_ai_fallback_models', return_value=['deepseek-v4-pro']))
                _, used = await main._call_ai_with_fallback('deepseek-flash', [{'role': 'user', 'content': '问题'}])
                self.assertEqual(used, 'deepseek-v4-pro')

    async def test_semantic_task_switch_does_not_retrieve_legal_materials(self):
        for question in ('给我讲一个法律相关的冷笑话', '把“合同已经履行”翻译成英文', '润色这句话：感谢配合'):
            with self.subTest(question=question):
                calls = 0
                def handler(payload):
                    nonlocal calls
                    calls += 1
                    return httpx.Response(200, json=response(json.dumps({'task': 'answer', 'sources': []}) if calls == 1 else '已按当前任务回答。'))
                self.mock_http(handler)
                with patch.object(main, 'search_articles_for_qa', side_effect=AssertionError('unnecessary KB retrieval')):
                    result = await main.ask_question(question=question, model='deepseek-flash', source_mode='hybrid')
                self.assertEqual(result['task_route'], 'answer')
                self.assertEqual(calls, 2)

    async def test_internal_default_model_has_same_budget_as_http_and_positional_calls(self):
        with main.get_db() as conn:
            conn.execute("INSERT INTO case_manager_cases(id,title,created_at,updated_at) VALUES(901,'匿名案件','2026-10-28','2026-10-28')")
        def handler(payload):
            if len(self.sent) == 1:
                return httpx.Response(200, json=response(json.dumps({'queries': [{'sql': 'SELECT count(*) AS n FROM case_manager_cases'}]})))
            return httpx.Response(200, json=response(json.dumps({'answer': '共1件。【依据1】'}, ensure_ascii=False)))
        self.mock_http(handler)
        result = await main.ask_question('有多少案件', source_mode='case_database')
        self.assertIn('1', result['answer'])
        self.assertTrue(all(payload['model'] == main.DEFAULT_AI_MODEL for payload in self.sent))
        self.assertLess(max(ai_input.size(payload['messages']) for payload in self.sent), 24000)

    async def test_all_case_identity_prefetch_reaches_model_not_only_source_cards(self):
        with main.get_db() as conn:
            conn.execute("INSERT INTO case_manager_cases(id,title,created_at,updated_at) VALUES(901,'匿名甲公司合同案','2026-10-28','2026-10-28')")
            conn.execute("INSERT INTO case_manager_case_numbers(case_id,case_no,court,created_at,updated_at) VALUES(901,'匿名案号','湛江市霞山区人民法院','2026-10-28','2026-10-28')")
        def handler(payload):
            sent = json.dumps(payload['messages'],ensure_ascii=False)
            self.assertIn('湛江市霞山区人民法院',sent)
            self.assertIn('匿名案号',sent)
            self.assertIn('匿名甲公司合同案',sent)
            return httpx.Response(200,json=response(json.dumps({'answer':'霞山法院在已登记资料中为湛江市霞山区人民法院，关联匿名甲公司合同案，匿名案号。【依据1】'},ensure_ascii=False)))
        self.mock_http(handler)
        result = await main.ask_question(question='霞山法院是什么',model='deepseek-flash',source_mode='case_database',memory_enabled=False)
        self.assertIn('匿名案号',result['answer'])
        self.assertEqual(len(self.sent),2)

    async def test_real_schema_and_long_six_turn_results_remain_bounded(self):
        with main.get_db() as conn:
            for index in range(12):
                conn.execute('INSERT INTO case_manager_cases(title,memo,created_at,updated_at) VALUES(?,?,?,?)',
                             (f'匿名案件{index}', '金额有条件，不得提前退款。' * 1500, '2026-10-28', '2026-10-28'))
        calls = 0
        async def call(model, messages, **options):
            nonlocal calls
            calls += 1
            ai_context.guard_messages(messages, options['max_tokens'], model=model)
            self.assertLessEqual(ai_input.size(messages) + options['max_tokens'], 24000)
            if calls < 7:
                return response(json.dumps({'queries': [{'sql': 'SELECT id AS case_id,title AS case_title,memo FROM case_manager_cases'}]})), model
            text = json.dumps(messages, ensure_ascii=False)
            self.assertIn('不能据此断言不存在', text)
            return response(json.dumps({'answer': '已核对现有记录，长正文需继续分页。【依据1】'}, ensure_ascii=False)), model
        token = ai_input.SCOPE.set({'sections': [], 'audit': []})
        try:
            result = await case_ai.answer_case_database(main.get_db, call, '核对全部案件备注', 'fixture-small')
        finally:
            ai_input.SCOPE.reset(token)
        self.assertEqual(calls, 7)
        self.assertIn('轮次上限', result['answer'])

    async def test_short_answers_do_not_trigger_paid_rewrites_and_length_does_continue(self):
        mock = AsyncMock(side_effect=[(response('42'), 'deepseek-flash'),
                                     (response('第一部分', 'length'), 'deepseek-flash'),
                                     (response('第二部分。'), 'deepseek-v4-pro')])
        with patch.object(main, '_call_ai_with_fallback', mock):
            first = await main._call_ai_answer_with_continuation('deepseek-flash', [{'role': 'user', 'content': '数字'}])
            second = await main._call_ai_answer_with_continuation('deepseek-flash', [{'role': 'user', 'content': '分析'}])
        self.assertEqual(first[0], '42')
        self.assertEqual(second[0], '第一部分第二部分。')
        self.assertEqual(second[2], 'deepseek-v4-pro')
        self.assertEqual(mock.await_count, 3)

    async def test_completed_result_survives_late_cancel(self):
        key = 'fixture_late_cancel'
        main._ask_store_result(key, {'answer': '已经完成。'})
        result = await main.cancel_ask_question(key)
        self.assertFalse(result['success'])
        self.assertEqual(main.get_ask_progress(key)['status'], 'complete')
        main._AI_ASK_PROGRESS.pop(key, None)

    async def test_old_done_callback_cannot_erase_new_cancellation_handle(self):
        key = 'fixture_reused_id'
        ready = asyncio.Event()
        async def job():
            ask_cancel.register_current_task(key)
            ready.set()
            await asyncio.sleep(60)
        task = asyncio.create_task(job())
        await ready.wait()
        with self.assertRaises(HTTPException):
            ask_cancel.register_current_task(key)
        self.assertTrue(ask_cancel.cancel_task(key))
        with self.assertRaises(asyncio.CancelledError):
            await task


class MaterialExtractionTests(unittest.TestCase):
    def test_word_body_tables_nested_tables_and_hyperlinks_keep_source_order(self):
        from docx import Document
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'anonymous.docx'
            document = Document()
            document.add_paragraph('开头原文。')
            table = document.add_table(rows=1, cols=2)
            table.cell(0, 0).text = '第一类：已履行。'
            table.cell(0, 1).text = '第二类：期间届满，不得遗漏。'
            table.cell(0, 1).add_table(rows=1, cols=1).cell(0, 0).text = '嵌套表格：金额983.25元。'
            paragraph = document.add_paragraph('【本院认为】')
            link = OxmlElement('w:hyperlink'); run = OxmlElement('w:r'); text = OxmlElement('w:t')
            text.text = '链接中的裁判原文。'; run.append(text); link.append(run); paragraph._p.append(link)
            document.add_paragraph('文末例外：只有尚未履行才适用。')
            document.save(path)
            parsed = main._parse_case_local_file(path)
        text = parsed['content']
        markers = ['开头原文', '第一类', '第二类', '嵌套表格', '链接中的裁判原文', '文末例外']
        self.assertEqual([text.index(marker) for marker in markers], sorted(text.index(marker) for marker in markers))
        chunks = case_files._located_chunks(text)
        self.assertIn('【本院认为】', ''.join(row[0] for row in chunks))
        self.assertTrue(all('工作表' not in row[1] for row in chunks))
        self.assertEqual(case_files._plain_text('条件：金额 < 500 且余额 > 0。'), '条件：金额 < 500 且余额 > 0。')

    def test_mixed_pdf_requires_consent_only_for_scanned_pages_and_does_not_lose_native_text(self):
        import fitz
        from PIL import Image
        import io
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'mixed.pdf'
            doc = fitz.open()
            page = doc.new_page(); page.insert_text((50, 50), 'NATIVE_TEXT ' * 12)
            image = io.BytesIO(); Image.new('RGB', (100, 100), 'white').save(image, format='PNG')
            page = doc.new_page(); page.insert_image(fitz.Rect(20, 20, 120, 120), stream=image.getvalue())
            doc.save(path); doc.close()
            parsed = main._parse_case_local_file(path)
            self.assertTrue(parsed['needs_ocr']); self.assertEqual(parsed['ocr_pages'], [2])
            with patch.object(main, '_ocr_page_image', return_value='SCANNED_TEXT') as ocr:
                parsed = main._parse_case_local_file(path, True)
            self.assertIn('NATIVE_TEXT', parsed['content']); self.assertIn('SCANNED_TEXT', parsed['content'])
            self.assertEqual(ocr.call_count, 1)
            with patch.object(main, '_ocr_page_image', return_value=''):
                with self.assertRaises(HTTPException):
                    main._parse_case_local_file(path, True)

    def test_entity_abbreviations_resolve_registered_court_and_company_names(self):
        conn = sqlite3.connect(':memory:')
        conn.executescript("CREATE TABLE case_manager_cases(id INTEGER,title TEXT,court TEXT,source_status TEXT);"
                           "INSERT INTO case_manager_cases VALUES(1,'匿名星河置业有限公司合同案','湛江市霞山区人民法院','active');")
        try:
            schema = case_ai.database_schema(conn)
            for question in ('霞山法院是什么', '星河公司是什么'):
                self.assertEqual(case_ai.entity_lookup(conn, schema, question)['returned_rows'], 1)
        finally:
            conn.close()

    def test_long_material_batches_cover_every_span_and_keep_global_citation_ids(self):
        rows = [{'relative_path': 'a', 'display_name': '匿名材料.txt', 'chunk_index': index,
                 'locator': f'原文段{index}', 'chunk_text': f'UNIQUE_{index:03d}：' + '合同条件与金额不得删除。' * 160}
                for index in range(35)]
        captured = []
        async def call(model, messages):
            ai_context.guard_messages(messages, 5000, model=model)
            self.assertLessEqual(ai_input.size(messages) + 8000, 24000)
            captured.append(json.dumps(messages, ensure_ascii=False))
            return '已核对本批原文。[FILE:1]', '', model
        async def execute():
            token = ai_input.SCOPE.set({'sections': [], 'audit': []})
            try:
                return await case_files._answer_complete_files('完整分析全部条款', rows, 'fixture-small', '', call)
            finally:
                ai_input.SCOPE.reset(token)
        answer, _, _, selected, count = asyncio.run(execute())
        self.assertGreater(count, 1)
        all_sent = '\n'.join(captured)
        self.assertTrue(all(f'UNIQUE_{index:03d}' in all_sent for index in range(35)))
        self.assertIn(f'[FILE:{len(selected)}]', all_sent)
        self.assertTrue(answer)
