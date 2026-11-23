import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from backend import main
from backend.library_law_review import meeting_minutes_source, meeting_minutes_evidence


class CourtMinutesReviewTests(unittest.IsolatedAsyncioTestCase):
    def test_numbered_points_show_separate_differences(self):
        local = '前言\n1.第一点\n2.原第二点\n3.原第三点'
        official = '前言\n1.第一点\n2.新第二点\n3.新第三点'
        self.assertEqual([entry['location'] for entry in meeting_minutes_evidence(local, official)], ['第 2 点', '第 3 点'])
        self.assertEqual(meeting_minutes_evidence(local, local.replace('第一点', '第 一 点')), [])

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = main.DB_PATH
        main.DB_PATH = Path(self.tmp.name) / 'test.db'
        main.init_db()
        self.title = '【九民纪要】最高人民法院关于印发《全国法院民商事审判工作会议纪要》的通知'
        self.before = '<p>第一条 本地旧文本。</p>'
        self.after = '<p>第一条 法院公开文本。</p>'
        self.article_id = main.save_article(self.title, self.before, '', [], 'file', tags=[])
        with main.get_db() as conn:
            conn.execute('INSERT INTO notes(article_id,content,selected_text,selection_anchor,created_at) VALUES(?,?,?,?,?)',
                         (self.article_id, '保留的笔记', '旧文本', '{}', '2026-01-01'))
            self.scan_id = conn.execute("INSERT INTO national_law_update_scans(mode,status,created_at) VALUES(?,'queued','2026-01-01')", ('manual:' + str(self.article_id),)).lastrowid
            conn.commit()
        self.source = meeting_minutes_source(self.title)

    async def asyncTearDown(self):
        main.DB_PATH = self.old_path
        self.tmp.cleanup()

    async def _scan(self):
        with patch.object(main, '_load_court_minutes_document', AsyncMock(return_value=(self.after, main.compute_hash(self.after)))), \
             patch.object(main, '_court_minutes_status', AsyncMock(return_value={'label': '未查到可核验的效力状态'})):
            await main._run_national_law_scan(self.scan_id)
        with main.get_db() as conn:
            return dict(conn.execute('SELECT * FROM national_law_update_items WHERE scan_id=?', (self.scan_id,)).fetchone())

    async def test_scan_compare_replace_and_rollback_preserve_notes(self):
        item = await self._scan()
        detail = json.loads(item['detail_json'])
        self.assertEqual(item['status'], 'review')
        self.assertTrue(detail['content_changed'])
        self.assertTrue(detail['excerpts'])
        self.assertEqual(detail['court_source'], self.source)
        with patch.object(main, '_load_court_minutes_document', AsyncMock(return_value=(self.after, main.compute_hash(self.after)))):
            payload = main.NationalLawApplyPayload(items=[{'item_id': item['id'], 'action': 'replace'}])
            result = (await main.apply_national_law_updates(self.scan_id, payload))['results'][0]
        self.assertTrue(result['success'], result)
        with main.get_db() as conn:
            self.assertEqual(conn.execute('SELECT content FROM articles WHERE id=?', (self.article_id,)).fetchone()[0], self.after)
            self.assertEqual(conn.execute('SELECT content FROM notes WHERE article_id=?', (self.article_id,)).fetchone()[0], '保留的笔记')
            self.assertEqual(conn.execute('SELECT content FROM national_law_update_snapshots WHERE id=?', (result['snapshot_id'],)).fetchone()[0], self.before)
            self.assertIsNone(conn.execute('SELECT bbbs FROM national_law_articles WHERE article_id=?', (self.article_id,)).fetchone())
            conn.execute('UPDATE articles SET content=? WHERE id=?', ('替换后的新编辑', self.article_id))
            conn.commit()
        with self.assertRaises(main.HTTPException) as conflict:
            await main.rollback_national_law_update(item['id'])
        self.assertEqual(conflict.exception.status_code, 409)
        with main.get_db() as conn:
            self.assertEqual(conn.execute('SELECT content FROM articles WHERE id=?', (self.article_id,)).fetchone()[0], '替换后的新编辑')
            conn.execute('UPDATE articles SET content=? WHERE id=?', (self.after, self.article_id))
            conn.commit()
        with patch.object(main, '_enqueue_knowledge_job', return_value=(None, False)):
            await main.rollback_national_law_update(item['id'])
        with main.get_db() as conn:
            self.assertEqual(conn.execute('SELECT content FROM articles WHERE id=?', (self.article_id,)).fetchone()[0], self.before)
            self.assertEqual(conn.execute('SELECT content FROM notes WHERE article_id=?', (self.article_id,)).fetchone()[0], '保留的笔记')

    async def test_changed_court_or_local_content_rejects_replace(self):
        item = await self._scan()
        payload = main.NationalLawApplyPayload(items=[{'item_id': item['id'], 'action': 'replace'}])
        with patch.object(main, '_load_court_minutes_document', AsyncMock(return_value=('new', main.compute_hash('new')))):
            result = (await main.apply_national_law_updates(self.scan_id, payload))['results'][0]
        self.assertFalse(result['success'])
        self.assertIn('法院原文已变化', result['error'])
        with main.get_db() as conn:
            conn.execute('UPDATE articles SET content=? WHERE id=?', ('本地更改', self.article_id))
            conn.commit()
        with patch.object(main, '_load_court_minutes_document', AsyncMock(return_value=(self.after, main.compute_hash(self.after)))):
            result = (await main.apply_national_law_updates(self.scan_id, payload))['results'][0]
        self.assertFalse(result['success'])
        self.assertIn('知识库正文已变化', result['error'])

    async def test_eight_minutes_do_not_invent_status(self):
        source = meeting_minutes_source('第八次全国法院民事商事审判工作会议（民事部分）纪要')
        status = await main._court_minutes_status(source)
        self.assertIn('未查到', status['label'])
        self.assertNotIn('url', status)

    async def test_eight_minutes_uses_court_comparison(self):
        with main.get_db() as conn:
            conn.execute('UPDATE articles SET title=? WHERE id=?',
                         ('【八民纪要】最高人民法院关于印发《第八次全国法院民事商事审判工作会议（民事部分）纪要》的通知', self.article_id))
            conn.commit()
        item = await self._scan()
        self.assertEqual(item['status'], 'review')
        self.assertEqual(json.loads(item['detail_json'])['court_source']['key'], 'eight')

    async def test_status_requires_matching_document_and_named_source(self):
        response = MagicMock()
        response.content = '<p>法〔2019〕254号</p><p>效力状态 现行有效</p>'.encode()
        client = AsyncMock()
        client.get.return_value = response
        manager = MagicMock()
        manager.__aenter__ = AsyncMock(return_value=client)
        manager.__aexit__ = AsyncMock(return_value=False)
        with patch.object(main.httpx, 'AsyncClient', return_value=manager):
            status = await main._court_minutes_status(self.source)
        self.assertEqual(status['label'], '现行有效')
        self.assertEqual(status['source'], '中国证券投资基金业协会法规库')
        response.content = '<p>另一份文件</p><p>效力状态 现行有效</p>'.encode()
        with patch.object(main.httpx, 'AsyncClient', return_value=manager):
            status = await main._court_minutes_status(self.source)
        self.assertIn('未查到', status['label'])

    async def test_unknown_source_is_not_fetched(self):
        source = {**self.source, 'url': 'http://127.0.0.1/private'}
        with self.assertRaises(ValueError):
            await main._load_court_minutes_document(source)
