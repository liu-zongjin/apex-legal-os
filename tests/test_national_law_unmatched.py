import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from backend import main


class NationalLawUnmatchedTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = main.DB_PATH
        main.DB_PATH = Path(self.tmp.name) / 'test.db'
        main.init_db()
        self.article_id = main.save_article('示例地方条例', '<p>第一条 旧内容。</p>', '', [], 'file', tags=[])
        with main.get_db() as conn:
            conn.execute('INSERT INTO notes(article_id,content,selected_text,selection_anchor,created_at) VALUES(?,?,?,?,?)', (self.article_id,'核对笔记','旧内容','{}','2026-01-01'))
            self.scan_id = conn.execute("INSERT INTO national_law_update_scans(mode,status,created_at) VALUES('manual','completed','2026-01-01')").lastrowid
            self.item_id = conn.execute("INSERT INTO national_law_update_items(scan_id,article_id,status,local_title,created_at,updated_at) VALUES(?,?,'unmatched','示例地方条例','2026-01-01','2026-01-01')", (self.scan_id,self.article_id)).lastrowid
            conn.commit()

    async def asyncTearDown(self):
        main.DB_PATH = self.old_path
        self.tmp.cleanup()

    async def test_search_requires_explicit_confirmation_and_preserves_notes(self):
        candidate = {'bbbs':'sample123', 'title':'示例地方条例（修订）', 'status_label':'有效', 'issuer':'示例机关'}
        with patch.object(main, 'search_national_laws', AsyncMock(return_value={'results':[candidate]})):
            result = await main.search_national_law_item_candidates(self.scan_id,self.item_id,main.NationalLawCandidateSearchPayload(query='示例条例'))
        self.assertEqual(len(result['results']),1)
        with patch.object(main, 'get_national_law_detail', AsyncMock(return_value=candidate)), patch.object(main, '_evaluate_bound_national_law', AsyncMock(return_value=('review',{'content_changed': True}))):
            payload = main.NationalLawConfirmPayload(items=[{'item_id':self.item_id,'bbbs':'sample123'}])
            denied = (await main.confirm_national_law_matches(self.scan_id,payload))['results'][0]
            self.assertFalse(denied['success'])
            payload.items[0]['allow_title_mismatch'] = True
            accepted = (await main.confirm_national_law_matches(self.scan_id,payload))['results'][0]
            self.assertTrue(accepted['success'],accepted)
        with main.get_db() as conn:
            self.assertEqual(conn.execute('SELECT content FROM articles WHERE id=?',(self.article_id,)).fetchone()[0],'<p>第一条 旧内容。</p>')
            self.assertEqual(conn.execute('SELECT content FROM notes WHERE article_id=?',(self.article_id,)).fetchone()[0],'核对笔记')
            self.assertEqual(conn.execute('SELECT bbbs FROM national_law_articles WHERE article_id=?',(self.article_id,)).fetchone()[0],'sample123')

    async def test_failed_comparison_does_not_bind(self):
        candidate={'bbbs':'sample123','title':'示例地方条例','status_label':'有效'}
        with patch.object(main,'search_national_laws',AsyncMock(return_value={'results':[candidate]})):
            await main.search_national_law_item_candidates(self.scan_id,self.item_id,main.NationalLawCandidateSearchPayload(query='示例条例'))
        with patch.object(main,'get_national_law_detail',AsyncMock(return_value=candidate)), patch.object(main,'_evaluate_bound_national_law',AsyncMock(side_effect=ValueError('下载失败'))):
            result=(await main.confirm_national_law_matches(self.scan_id,main.NationalLawConfirmPayload(items=[{'item_id':self.item_id,'bbbs':'sample123'}])))['results'][0]
        self.assertFalse(result['success'])
        with main.get_db() as conn:
            self.assertIsNone(conn.execute('SELECT bbbs FROM national_law_articles WHERE article_id=?',(self.article_id,)).fetchone())

    async def test_empty_search_remains_unmatched_and_does_not_bind(self):
        with patch.object(main,'search_national_laws',AsyncMock(return_value={'results':[]})):
            result=await main.search_national_law_item_candidates(self.scan_id,self.item_id,main.NationalLawCandidateSearchPayload(query='示例条例'))
        self.assertEqual(result['results'],[])
        with main.get_db() as conn:
            self.assertEqual(conn.execute('SELECT status FROM national_law_update_items WHERE id=?',(self.item_id,)).fetchone()[0],'unmatched')
            self.assertIsNone(conn.execute('SELECT bbbs FROM national_law_articles WHERE article_id=?',(self.article_id,)).fetchone())

    async def test_report_is_explicitly_not_full_text(self):
        with main.get_db() as conn:
            conn.execute('UPDATE national_law_update_items SET local_title=? WHERE id=?', ('《广州市中级人民法院民事诉讼审判程序中财产保全反担保工作指引》',self.item_id))
            row=conn.execute('SELECT * FROM national_law_update_items WHERE id=?',(self.item_id,)).fetchone()
        ref=main._scan_item_to_dict(row)['reference']
        self.assertEqual(ref['kind'],'报道，非文件全文')
        self.assertIn('court.gov.cn',ref['url'])
