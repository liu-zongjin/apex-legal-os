import json
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import main


ARTICLE = ('<h2>第一部分</h2><p>本段被错误</p><p>切开。'
           '<span style="background-color:#fff2a8">重复条款。重复条款。</span></p>'
           '<table><tbody><tr><td>原表格</td></tr></tbody></table><p>结语。</p>')
QUOTE = '重复条款。'
START = len('第一部分本段被错误切开。重复条款。')


def choice(groups):
    return ({"choices": [{"message": {"content": json.dumps({"groups": groups})},
                           "finish_reason": "stop"}]}, "test-model")


@contextmanager
def layout_fixture():
    with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
        database = Path(directory) / 'layout.db'

        def connect():
            conn = sqlite3.connect(database)
            conn.row_factory = sqlite3.Row
            return conn

        with connect() as conn:
            conn.executescript('''
                CREATE TABLE articles(id INTEGER PRIMARY KEY,title TEXT,content TEXT,summary TEXT,domains TEXT,tags TEXT,created_at TEXT);
                CREATE TABLE domain_classification_jobs(article_id INTEGER,status TEXT);
                CREATE TABLE knowledge_claim_evidence(article_id INTEGER);
                CREATE TABLE notes(id INTEGER PRIMARY KEY,article_id INTEGER,content TEXT,selected_text TEXT,selection_anchor TEXT,created_at TEXT);
            ''')
            conn.execute("INSERT INTO articles VALUES(1,'匿名排版示例',?,'','[]','[]','2026-01-01')", (ARTICLE,))
            anchor = json.dumps({"version": 1, "start": START, "end": START + len(QUOTE), "quote": QUOTE})
            conn.execute("INSERT INTO notes VALUES(1,1,'第二处的笔记',?,?,'2026-01-01')", (QUOTE, anchor))
            conn.execute("INSERT INTO notes VALUES(2,1,'跨段旧笔记','本段被错误切开。',NULL,'2026-01-02')")

        stack.enter_context(patch.object(main, 'get_db', connect))
        # TestClient does not start the production runtime monitor in this fixture.
        stack.enter_context(patch.object(main, 'runtime_source_status', return_value={'restart_required': False}))
        stack.enter_context(patch.object(main, 'article_subcategory_labels', return_value={1: []}))
        stack.enter_context(patch.object(main, 'mark_article_claims_needs_review', return_value=[]))
        stack.enter_context(patch.object(main, 'is_knowledge_article', return_value=False))
        rebuild = stack.enter_context(patch.object(main, 'rebuild_article_paragraphs'))
        model = stack.enter_context(patch.object(main, '_call_ai_with_fallback'))
        yield TestClient(main.app), connect, model, rebuild


class ArticleLayoutTest(unittest.TestCase):
    def test_preview_validates_boundaries_and_is_read_only(self):
        with layout_fixture() as (client, _, model, rebuild):
            url = '/api/articles/1/layout/preview'
            payload = {'runs': [['标题', '正文'], ['下一段']]}
            groups = [[1, 'h2'], [2, 'p'], [3, 'p']]
            model.return_value = choice(groups)
            self.assertEqual(client.post(url, json=payload).json(), {'groups': groups})
            self.assertEqual(json.loads(model.call_args.args[1][1]['content']), [[[1, '标题'], [2, '正文']], [[3, '下一段']]])
            for invalid in ([[1, 'p']], [[1, 'script'], [3, 'p']], [[0, 'p'], [1, 'p'], [3, 'p']], [[1, 'p'], [3, 'p'], [4, 'p']]):
                model.return_value = choice(invalid)
                self.assertEqual(client.post(url, json=payload).status_code, 502)
            self.assertEqual(client.get('/api/articles/1').json()['content'], ARTICLE)
            rebuild.assert_not_called()

    def test_confirm_conflict_and_note_records(self):
        with layout_fixture() as (client, _, _, rebuild):
            notes = client.get('/api/notes/1').json()
            path = '/api/articles/1/content'
            content = ARTICLE.replace('<h2>', '<h2 class="body-ai-layout">')
            self.assertEqual(client.put(path, json={'content': content, 'base_content': '旧版本'}).status_code, 409)
            rebuild.assert_not_called()
            self.assertEqual(client.put(path, json={'content': content, 'base_content': ARTICLE}).status_code, 200)
            self.assertEqual(client.get('/api/articles/1').json()['content'], content)
            self.assertEqual(client.get('/api/notes/1').json(), notes)
            rebuild.assert_called_once()
