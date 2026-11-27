import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from backend import ask_combined, case_files


class CaseFolderScopeTests(unittest.TestCase):
    def test_whole_root_recurses_without_following_links_and_rejects_overflow(self):
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as outside:
            root = Path(temporary)
            (root / 'sub').mkdir()
            (root / 'a.txt').write_text('a')
            (root / 'sub' / 'b.txt').write_text('b')
            (Path(outside) / 'secret.txt').write_text('secret')
            (root / 'link').symlink_to(outside, target_is_directory=True)
            self.assertEqual(set(case_files._expand_ai_paths(root, ['__CASE_ROOT__'], limit=2)), {'a.txt', 'sub/b.txt'})
            with self.assertRaises(HTTPException) as error:
                case_files._expand_ai_paths(root, ['__CASE_ROOT__'], limit=1)
            self.assertEqual(error.exception.status_code, 413)


class CombinedCaseHubTests(unittest.IsolatedAsyncioTestCase):
    async def test_case_material_drives_all_retrieval_and_citations(self):
        file_item = {'kind':'files','title':'材料','source':'a.txt','case_id':1,'locator':'第1段','block':'案件材料','excerpt':'案件材料'}
        article = {'kind':'knowledge','article_id':7,'title':'文章','block':'文章正文','excerpt':'正文'}
        fada = {'kind':'fada','id':'fada-12345678','title':'答问','block':'答问正文','excerpt':'正文'}
        async def ai(model, messages, **kwargs):
            if len(messages) == 2 and '提取具体争议焦点' in messages[0]['content']:
                return ('工程款支付争议', '', model)
            return ('结论【依据1】【依据2】【依据3】【依据4】', '', model)
        class Connection:
            def close(self): pass
        search = AsyncMock(return_value={'cases':[{'title':'公开案例','source_url':'https://example.com/judgment','holding':'法院原文'}], 'errors':[]})
        with patch.object(ask_combined, 'file_evidence', AsyncMock(return_value=([file_item], []))), \
             patch.object(ask_combined, 'knowledge_evidence', return_value=([article], [])) as knowledge, \
             patch.object(ask_combined, 'fada_evidence', return_value=([fada], [])) as fada_search, \
             patch('backend.case_research.search_cases_structured', search):
            result = await ask_combined.answer_combined('生成报告','model',{'knowledge','fada','files','publicweb'},get_db=Connection,call_ai=ai,parse_file=None,file_scope={'case_id':1,'paths':['__CASE_ROOT__']},case_hub=True)
        self.assertEqual(knowledge.call_args.args[0], '工程款支付争议')
        self.assertEqual(fada_search.call_args.args[0], '工程款支付争议')
        self.assertEqual(search.call_args.args[0], '工程款支付争议')
        self.assertEqual({item['source_type'] for item in result['cited_sources']}, {'local_file','article','fada','public_web'})
        self.assertEqual(next(item['url'] for item in result['cited_sources'] if item['source_type']=='public_web'), 'https://example.com/judgment')

    async def test_unreadable_case_material_fails_before_search(self):
        with patch.object(ask_combined, 'file_evidence', AsyncMock(return_value=([], ['没有文字']))), \
             patch.object(ask_combined, 'knowledge_evidence') as knowledge:
            with self.assertRaises(HTTPException) as error:
                await ask_combined.answer_combined('问题','model',{'files','knowledge'},get_db=lambda:None,call_ai=AsyncMock(),parse_file=None,case_hub=True)
        self.assertEqual(error.exception.status_code, 422)
        knowledge.assert_not_called()

    async def test_legal_mcp_is_explicit_and_failure_does_not_invent_evidence(self):
        from backend import main
        file_item = {'kind':'files','title':'材料','source':'a.txt','case_id':1,'block':'案件原文','excerpt':'原文'}
        async def ai(model, messages, **kwargs):
            return ('合同争议' if '提取具体争议焦点' in messages[0]['content'] else '结论【依据1】【依据2】', '', model)
        national = AsyncMock(return_value=('实际法规原文', []))
        failed = AsyncMock(side_effect=RuntimeError('offline'))
        with patch.object(ask_combined, 'file_evidence', AsyncMock(return_value=([file_item], []))), \
             patch.object(main, '_national_law_qa_context', national), \
             patch.object(main, 'search_qcc_mcp_laws', failed):
            result = await ask_combined.answer_combined('问题','model',{'files'},get_db=lambda:None,call_ai=ai,parse_file=None,case_hub=True,case_mcp_sources={'national_law','qcc_law'})
        self.assertEqual(national.await_count, 1)
        self.assertEqual(failed.await_count, 1)
        self.assertEqual(result['source_breakdown']['case_mcp'], 1)
        self.assertTrue(any('企查查法律法规检索失败' in warning for warning in result['warnings']))

class KnowledgePackTests(unittest.IsolatedAsyncioTestCase):
    async def test_export_contains_separate_complete_originals(self):
        import io
        import sqlite3
        import zipfile
        from docx import Document
        from backend import main
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / 'test.sqlite')
            conn = sqlite3.connect(database)
            conn.execute('CREATE TABLE articles (id INTEGER PRIMARY KEY, title TEXT, content TEXT, summary TEXT, source_url TEXT, source_filename TEXT, created_at TEXT)')
            conn.execute('INSERT INTO articles VALUES (1, ?, ?, ?, ?, ?, ?)', ('知识文章', '文章开头\n文章结尾', '', '', '', ''))
            conn.commit(); conn.close()
            def get_db():
                conn = sqlite3.connect(database)
                conn.row_factory = sqlite3.Row
                return conn
            file_item = {'block':'案件材料', 'kind':'files'}
            fada = {'question':'如何处理争议？','answer':'答问开头\n答问结尾'}
            with patch('backend.ask_combined.file_evidence', AsyncMock(return_value=([file_item], []))), \
                 patch.object(main, 'get_db', get_db), \
                 patch.object(main, '_call_ai_answer_with_continuation', AsyncMock(return_value=('合同争议', '', 'model'))), \
                 patch.object(main, 'search_articles_for_qa', return_value=[{'id':1}]), \
                 patch.object(main, '_load_fada_structured_items', return_value=[fada]), \
                 patch.object(main, '_fada_query_tokens', return_value=['合同']), \
                 patch.object(main, '_fada_score_item', return_value=(10, [])):
                response = await main.export_case_hub_knowledge_pack('生成知识包', 1, 'model', False, '["__CASE_ROOT__"]', 'knowledge,fada')
                data = b''.join([chunk async for chunk in response.body_iterator])
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                docs = [name for name in archive.namelist() if name.endswith('.docx')]
                self.assertEqual(len(docs), 2)
                texts = ['\n'.join(p.text for p in Document(io.BytesIO(archive.read(name))).paragraphs) for name in docs]
                self.assertTrue(any('文章开头' in text and '文章结尾' in text for text in texts))
                self.assertTrue(any('答问开头' in text and '答问结尾' in text for text in texts))
                self.assertIn('检索说明.txt', archive.namelist())
