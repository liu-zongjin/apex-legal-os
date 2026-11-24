import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from backend import main


class NationalLawReplacementTests(unittest.IsolatedAsyncioTestCase):
    async def test_review_replacement_preserves_notes_and_rejects_stale_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_path = main.DB_PATH
            main.DB_PATH = Path(tmp) / 'test.db'
            try:
                main.init_db()
                before = '<p>第一条 原文。</p>'
                after = '<p>第一条 新文。</p>'
                article_id = main.save_article('示例条例', before, '', [], 'national_law', tags=[])
                with main.get_db() as conn:
                    conn.execute(
                        'INSERT INTO notes(article_id,content,selected_text,selection_anchor,created_at) VALUES(?,?,?,?,?)',
                        (article_id, '我的笔记', '原文', '{}', '2026-01-01'),
                    )
                    scan_id = conn.execute(
                        "INSERT INTO national_law_update_scans(mode,status,created_at) VALUES('manual','completed','2026-01-01')"
                    ).lastrowid
                    comparison = {
                        'comparison_version': 2, 'content_changed': True, 'target_bbbs': 'test-law',
                        'local_content_hash': main.compute_hash(before),
                        'official_content_hash': main.compute_hash(after),
                    }
                    item_id = conn.execute(
                        """INSERT INTO national_law_update_items
                           (scan_id,article_id,status,local_title,matched_bbbs,detail_json,confirmed,created_at,updated_at)
                           VALUES(?,?,'review','示例条例','test-law',?,1,'2026-01-01','2026-01-01')""",
                        (scan_id, article_id, json.dumps(comparison)),
                    ).lastrowid
                    conn.commit()
                detail = {'bbbs': 'test-law', 'title': '示例条例', 'normalized_title': '示例条例',
                          'status_code': 3, 'status_label': '有效'}
                with patch.object(main, '_load_official_law_document', AsyncMock(
                    return_value=(detail, after, main.compute_hash(after))
                )), patch.object(main, 'is_knowledge_article', return_value=False):
                    payload = main.NationalLawApplyPayload(items=[{'item_id': item_id, 'action': 'replace'}])
                    result = (await main.apply_national_law_updates(scan_id, payload))['results'][0]
                    self.assertTrue(result['success'])
                    with main.get_db() as conn:
                        self.assertEqual(conn.execute('SELECT content FROM articles WHERE id=?', (article_id,)).fetchone()[0], after)
                        note = conn.execute('SELECT content,selected_text FROM notes WHERE article_id=?', (article_id,)).fetchone()
                        self.assertEqual(tuple(note), ('我的笔记', '原文'))
                        snapshot = conn.execute('SELECT content FROM national_law_update_snapshots WHERE id=?', (result['snapshot_id'],)).fetchone()
                        self.assertEqual(snapshot[0], before)
                    with self.assertRaises(ValueError):
                        await main._write_national_law_article(
                            'test-law', existing_article_id=article_id, action='replace',
                            expected_local_hash=main.compute_hash(before), expected_official_hash=main.compute_hash(after),
                        )
            finally:
                main.DB_PATH = old_path
