import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

from backend import knowledge_search as search
from backend import main


def encoder(texts):
    """Test-only paraphrase oracle; production has no synonym/topic dictionary."""
    vectors = []
    for text in texts:
        if any(s in text for s in ('打卡', '劳动关系', '职工')):
            vectors.append([1., 0., 0.])
        elif any(s in text for s in ('专利', '发明', '技术方案')):
            vectors.append([0., 1., 0.])
        else:
            vectors.append([0., 0., 1.])
    return np.array(vectors, dtype=np.float32)


class CorpusIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'source.db'
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        self.conn.execute('CREATE TABLE articles(id INTEGER PRIMARY KEY,title,summary,content)')
        self.conn.executemany('INSERT INTO articles VALUES (?,?,?,?)', [
            (1, '日常记录', '', '劳动关系需要综合实际用工管理情况判断。'),
            (2, '发明申请', '', '专利保护范围以权利要求为准。'),
            (3, '专利阅读', '', '职工受到实际用工管理时可能成立劳动关系。'),
        ])
        self.conn.commit()
        self.index = search.CorpusIndex(self.db, Path(self.tmp.name) / 'cache', encoder)
        self.addCleanup(self.index.close)
        self.schedule = patch.object(self.index, 'schedule')
        self.schedule.start(); self.addCleanup(self.schedule.stop)
        self.index.refresh()

    def test_vector_channel_finds_document_with_zero_lexical_overlap(self):
        hits, info = self.index.search('打卡', 'article', [1, 2], ['content'])
        self.assertEqual([h['id'] for h in hits], [1])
        self.assertEqual(hits[0]['channels'], ['semantic'])
        self.assertEqual(info['method'], 'bm25+dense_rrf')
        self.assertIn(hits[0]['text'], self.conn.execute('SELECT content FROM articles WHERE id=1').fetchone()[0])

    def test_scope_and_eligibility_are_applied_before_vector_selection(self):
        hits, _ = self.index.search('打卡', 'article', [3], ['title'])
        self.assertEqual(hits, [])
        hits, _ = self.index.search('打卡', 'article', [3], ['content'])
        self.assertEqual([h['id'] for h in hits], [3])
        hits, _ = self.index.search('打卡', 'article', [2], ['content'])
        self.assertEqual(hits, [])

    def test_incremental_refresh_reuses_vectors_and_tracks_edit_delete(self):
        calls = []
        def track(texts):
            calls.extend(texts); return encoder(texts)
        self.index.encoder = track
        self.index.refresh()
        self.assertEqual(calls, [])
        self.conn.execute("UPDATE articles SET content='发明的新技术方案' WHERE id=1")
        self.conn.execute('DELETE FROM articles WHERE id=2'); self.conn.commit()
        self.index.refresh()
        self.assertIn('发明的新技术方案', calls)
        hits, _ = self.index.search('打卡', 'article', [1, 2], ['content'])
        self.assertEqual(hits, [])
        with self.index.connect() as cache:
            self.assertIsNone(cache.execute("SELECT 1 FROM documents WHERE kind='article' AND id=2").fetchone())

    def test_reopened_index_is_persistent_and_source_is_unchanged(self):
        before = self.conn.execute("SELECT sql FROM sqlite_master WHERE type='table'").fetchall()
        reopened = search.CorpusIndex(self.db, self.index.path.parent, encoder)
        with patch.object(reopened, 'schedule'):
            hits, _ = reopened.search('打卡', 'article', [1], ['content'])
        self.assertEqual(hits[0]['id'], 1)
        self.assertEqual(before, self.conn.execute("SELECT sql FROM sqlite_master WHERE type='table'").fetchall())

    def test_model_failure_falls_back_without_claiming_vectors(self):
        def broken(_): raise FileNotFoundError('not installed')
        self.index.encoder = broken
        hits, info = self.index.search('劳动关系', 'article', [1], ['content'])
        self.assertEqual(hits[0]['id'], 1)
        self.assertEqual(info['method'], 'bm25')
        self.assertIn('关键词', info['notice'])

    def test_separate_relevance_review_rejects_vector_only_false_positive(self):
        self.index.reranker = lambda query, texts: [-9.] * len(texts)
        hits, info = self.index.search('每日打卡', 'article', [1], ['content'])
        self.assertEqual(hits, [])
        self.assertEqual(info['relevance_review'], 'local_cross_encoder')

    def test_relevance_review_failure_preserves_text_and_does_not_promote_vectors(self):
        def broken(query, texts): raise RuntimeError('unavailable')
        self.index.reranker = broken
        hits, info = self.index.search('每日打卡', 'article', [1], ['content'])
        self.assertEqual(hits, [])
        self.assertIn('复核暂不可用', info['notice'])
        hits, _ = self.index.search('劳动关系', 'article', [1], ['content'])
        self.assertEqual([h['id'] for h in hits], [1])

    def test_relevance_review_cannot_see_content_outside_title_scope(self):
        received = []
        def reviewer(query, texts):
            received.extend(texts); return [3.] * len(texts)
        self.index.reranker = reviewer
        self.index.search('发明', 'article', [2], ['title'])
        self.assertTrue(received)
        self.assertFalse(any('权利要求' in text for text in received))

    def test_freshness_check_rejects_stale_vectors_before_returning(self):
        self.conn.execute("UPDATE articles SET content='技术方案' WHERE id=1"); self.conn.commit()
        with patch.object(search, 'index_for', return_value=self.index):
            hits, info = search.retrieve(self.conn, '打卡', 'article', [1], 'content')
        self.assertEqual(hits, [])
        self.assertIn('刷新', info['notice'])

    def test_chunking_covers_middle_of_long_article_and_strips_hidden_markup(self):
        fields = search.document_fields({'content': '<script>隐藏噪音</script><p>' + '前文' * 400 + '关键原文' + '后文' * 400 + '</p>'}, 'article')
        windows = list(search.passages(fields))
        self.assertGreater(len(windows), 6)
        self.assertTrue(any('关键原文' in w[2] for w in windows))
        self.assertFalse(any('隐藏噪音' in w[2] for w in windows))

    def test_specific_identifiers_do_not_enter_semantic_channel(self):
        for query in ('（2024）甲01民终123号', '某法第十五条', '“精确词组”', '专利'):
            self.assertFalse(search.supports_semantics(query))
        self.assertTrue(search.supports_semantics('一方没有按约付款还能要求对方履行吗'))


class SearchApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'test.db'
        self.patch = patch.object(main, 'DB_PATH', self.db); self.patch.start(); self.addCleanup(self.patch.stop)
        main.init_db()
        self.client = TestClient(main.app)
        with main.get_db() as conn:
            for i, (title, content, domain) in enumerate([
                ('日常记录', '实际劳动关系需要结合管理情况认定。', '劳动法'),
                ('发明申请', '专利范围以权利要求为准。', '知识产权'),
                ('专利阅读', '劳动关系需要结合实际管理认定。', '知识产权'),
            ], 1):
                conn.execute('INSERT INTO articles(id,title,content,summary,domains,source_type,source_hash,created_at,tags) VALUES (?,?,?,?,?,?,?,?,?)', (i, title, content, '', json.dumps([domain]), 'file', str(i), '2026-01-01', '[]'))
            conn.commit()
        self.index = search.CorpusIndex(self.db, Path(self.tmp.name) / 'cache', encoder)
        self.addCleanup(self.index.close)
        self.schedule = patch.object(self.index, 'schedule'); self.schedule.start(); self.addCleanup(self.schedule.stop)
        self.index.refresh()
        self.index_patch = patch.object(search, 'index_for', return_value=self.index)
        self.index_patch.start(); self.addCleanup(self.index_patch.stop)

    def test_article_api_can_recall_without_keyword_match_and_preserves_filters(self):
        result = self.client.get('/api/articles', params={'q': '每日打卡', 'semantic': 'true', 'domain': '劳动法'}).json()
        self.assertEqual([a['id'] for a in result['articles']], [1])
        self.assertEqual(result['articles'][0]['search_match']['channels'], ['semantic'])
        result = self.client.get('/api/articles', params={'q': '每日打卡', 'semantic': 'true', 'search_scope': 'title'}).json()
        self.assertEqual(result['articles'], [])
        result = self.client.get('/api/articles', params={'q': '每日打卡', 'semantic': 'true', 'fuzzy': 'false'}).json()
        self.assertEqual(result['articles'], [])

    def test_exact_phrase_has_priority_and_pagination_is_consistent(self):
        with main.get_db() as conn:
            conn.execute("UPDATE articles SET title='每日打卡' WHERE id=3"); conn.commit()
        self.index.refresh()
        params = {'q': '每日打卡', 'semantic': 'true', 'page_size': 1}
        first = self.client.get('/api/articles', params=params).json()
        second = self.client.get('/api/articles', params=dict(params, page=2)).json()
        self.assertEqual(first['articles'][0]['id'], 3)
        self.assertNotEqual(first['articles'][0]['id'], second['articles'][0]['id'])
        self.assertEqual(first['total'], second['total'])

    def test_knowledge_api_filters_governance_validity_and_domain_before_recall(self):
        with main.get_db() as conn:
            for i, status, valid, verified, domain in [(1, 'approved', '', 1, '劳动法'), (2, 'pending', '', 1, '劳动法'), (3, 'approved', '2000-01-01', 1, '劳动法'), (4, 'approved', '', 0, '劳动法'), (5, 'approved', '', 1, '知识产权')]:
                statement = '实际劳动关系需综合管理情况认定。' + str(i)
                conn.execute("INSERT INTO knowledge_issues(id,title,normalized_title,domain,status,created_at,updated_at) VALUES (?,?,?,?, 'active','2026-01-01','2026-01-01')", (i, '用工认定' + str(i), str(i), domain))
                conn.execute("INSERT INTO knowledge_claims(id,statement,normalized_statement,conditions_text,exceptions_text,review_status,valid_to,created_at,updated_at) VALUES (?,?,?,'存在实际用工管理','须核对具体事实',?,?,'2026-01-01','2026-01-01')", (i, statement, statement, status, valid))
                conn.execute('INSERT INTO knowledge_claim_issues(claim_id,issue_id) VALUES (?,?)', (i, i))
                conn.execute("INSERT INTO knowledge_claim_evidence(claim_id,article_id,paragraph_index,quote,verified,created_at) VALUES (?,1,1,'原文',?,'2026-01-01')", (i, verified))
            conn.commit()
        self.index.refresh()
        result = self.client.get('/api/legal-knowledge/search', params={'q': '每日打卡', 'semantic': 'true', 'domain': '劳动法'}).json()
        self.assertEqual([r['id'] for r in result['results']], [1])
        self.assertEqual(result['results'][0]['search_match']['channels'], ['semantic'])
        self.assertIn('conditions_text', result['results'][0])


if __name__ == '__main__':
    unittest.main()
