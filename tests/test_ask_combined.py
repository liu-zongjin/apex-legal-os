import json
import sqlite3
import unittest
from unittest.mock import patch

from backend import ask_combined


class _Connection:
    def close(self):
        pass


class ArticleScopeTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.execute('CREATE TABLE articles (id INTEGER, title TEXT, tags TEXT, domains TEXT, created_at TEXT)')
        self.conn.execute('CREATE TABLE tag_groups (id INTEGER, name TEXT, category_id INTEGER)')
        self.conn.executemany('INSERT INTO articles VALUES (?,?,?,?,?)', [
            (1, 'a', '["合同","作者:张三"]', '["建设工程"]', '2026-01-01'),
            (2, 'b', '["破产"]', '["公司"]', '2026-01-02'),
            (3, 'c', '["合同"]', '["建设工程"]', '2026-01-03'),
        ])
        self.conn.execute("INSERT INTO tag_groups VALUES (1,'合同',7)")

    def test_each_scope_matches_its_ask_route(self):
        cases = {
            'article': ({'type': 'article', 'id': 2}, [2]),
            'results': ({'type': 'results', 'ids': [1, '3', 'x']}, [1, 3]),
            'tag': ({'type': 'tag', 'tag': '合同'}, [1, 3]),
            'author': ({'type': 'author', 'author': '张三'}, [1]),
            'domain': ({'type': 'domain', 'domain': '建设工程'}, [1, 3]),
            'category': ({'type': 'category', 'catId': 7}, [1, 3]),
        }
        for name, (scope, expected) in cases.items():
            with self.subTest(scope=name):
                self.assertEqual(sorted(ask_combined.article_ids_for_scope(self.conn, scope) or []), expected)

    def test_invalid_explicit_scope_never_searches_the_whole_library(self):
        for scope in ({'type': 'unknown'}, {'type': 'results', 'ids': '123'}, {'type': 'article', 'id': 'abc'}):
            self.assertEqual(ask_combined.article_ids_for_scope(self.conn, scope), [])

    def test_whole_library_returns_none(self):
        self.assertIsNone(ask_combined.article_ids_for_scope(self.conn, {'type': 'section'}))


class CitationTests(unittest.TestCase):
    items = [
        {'kind': 'knowledge', 'article_id': 11, 'title': '文章甲', 'source': '最高法', 'excerpt': '摘要甲',
         'block': '正文甲'},
        {'kind': 'fada', 'id': 'fada-12345678', 'idx': 5, 'batch': '第1批', 'topic': '合同',
         'question': '违约金如何调整', 'title': '违约金如何调整', 'excerpt': '答问原文', 'block': '答问原文'},
        {'kind': 'files', 'file_index': 1, 'title': '起诉状.pdf', 'source': '材料/起诉状.pdf', 'locator': '第 2 页',
         'case_id': 9, 'session_id': '', 'excerpt': '诉讼请求', 'block': '诉讼请求'},
    ]

    def test_only_cited_evidence_is_renumbered(self):
        answer = '第一点【依据2】；第二点【依据3】；重复【依据2】；越界【依据9】'
        clean, cited, matched = ask_combined.map_citations(answer, self.items)
        self.assertTrue(matched)
        self.assertEqual(clean, '第一点【依据1】；第二点【依据2】；重复【依据1】；越界')
        self.assertEqual([item['kind'] for item in cited], ['fada', 'files'])

    def test_unsupported_citation_markers_are_removed_even_when_none_match(self):
        self.assertEqual(ask_combined.map_citations('结论【依据99】', self.items), ('结论', [], False))

    def test_payload_keeps_the_shape_each_source_already_renders(self):
        knowledge = ask_combined.citation_payload(self.items[0], 1)
        fada = ask_combined.citation_payload(self.items[1], 2)
        files = ask_combined.citation_payload(self.items[2], 3)
        self.assertEqual(knowledge['source_type'], 'article')
        self.assertEqual(knowledge['article_id'], 11)
        self.assertEqual(fada['source_type'], 'fada')
        self.assertEqual(fada['id'], 'fada-12345678')
        self.assertEqual(files['source_type'], 'local_file')
        self.assertEqual(files['case_id'], 9)
        self.assertEqual(files['id'], 'file-3')

    def test_materials_carry_one_numbering(self):
        messages = ask_combined.build_messages('违约金能否调整？', self.items, '')
        self.assertEqual(len(messages), 2)
        self.assertIn('【依据1｜知识库文章】', messages[1]['content'])
        self.assertIn('【依据2｜法答网答问】', messages[1]['content'])
        self.assertIn('【依据3｜所选文件】', messages[1]['content'])
        self.assertIn('违约金能否调整？', messages[1]['content'])
        self.assertIn('不得补写', messages[0]['content'])


class AnswerFlowTests(unittest.IsolatedAsyncioTestCase):
    async def run_answer(self, reply, sources=('knowledge', 'fada'), file_scope=None):
        calls = []

        async def call_ai(model, messages, **options):
            calls.append(messages)
            return reply, '', model

        with patch.object(ask_combined, 'knowledge_evidence',
                          return_value=([CitationTests.items[0]], [])), \
                patch.object(ask_combined, 'fada_evidence',
                             return_value=([CitationTests.items[1]], [])), \
                patch.object(ask_combined, 'file_evidence',
                             return_value=([CitationTests.items[2]], [])):
            result = await ask_combined.answer_combined(
                '违约金能否调整？', 'deepseek-chat', set(sources), get_db=_Connection,
                call_ai=call_ai, parse_file=lambda *_a, **_k: None,
                kb_scope={'type': 'section'}, fada_scope={'ids': []}, file_scope=file_scope)
        return result, calls

    async def test_two_sources_answer_once_with_unified_citations(self):
        result, calls = await self.run_answer('结论【依据1】与【依据2】')
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['source_mode'], 'combined')
        self.assertEqual([item['source_type'] for item in result['cited_sources']], ['article', 'fada'])
        self.assertEqual(result['source_breakdown'], {'knowledge': 1, 'fada': 1})
        self.assertEqual(result['warnings'], [])
        self.assertEqual(result['answer'], '结论【依据1】与【依据2】')

    async def test_missing_markers_keep_every_material_and_warn(self):
        result, _calls = await self.run_answer('没有任何引用的结论')
        self.assertEqual(len(result['cited_sources']), 2)
        self.assertTrue(any('未标注' in warning for warning in result['warnings']))

    async def test_file_span_markers_are_removed_from_the_shared_numbering(self):
        result, _calls = await self.run_answer('结论[FILE:3]【依据1】')
        self.assertNotIn('[FILE:', result['answer'])

    async def test_no_material_is_a_clear_failure(self):
        async def call_ai(model, messages, **options):
            return '不应调用', '', model

        with patch.object(ask_combined, 'knowledge_evidence', return_value=([], ['知识库未命中'])), \
                patch.object(ask_combined, 'fada_evidence', return_value=([], ['法答网未命中'])):
            with self.assertRaises(Exception) as context:
                await ask_combined.answer_combined(
                    '问题', 'deepseek-chat', {'knowledge', 'fada'}, get_db=_Connection,
                    call_ai=call_ai, parse_file=lambda *_a, **_k: None)
        self.assertIn('没有取得可用材料', str(getattr(context.exception, 'detail', context.exception)))

    async def test_files_only_uses_its_own_evidence(self):
        result, calls = await self.run_answer('结论【依据1】', sources=('files',),
                                              file_scope={'case_id': 9, 'paths': ['材料/起诉状.pdf']})
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['combined_sources'], ['files'])
        self.assertEqual(result['cited_sources'][0]['source_type'], 'local_file')


if __name__ == '__main__':
    unittest.main()
