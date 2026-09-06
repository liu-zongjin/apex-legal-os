import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from backend import feishu_article_sync
from backend.feishu_article_sync import FeishuArticleSync, ensure_schema


class FeishuArticleSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "kb.db"
        self.config_path = Path(self.temp_dir.name) / "feishu.json"

        def get_db():
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            return conn

        self.get_db = get_db
        ensure_schema(get_db)
        self.config_patch = patch.object(feishu_article_sync, "CONFIG_PATH", self.config_path)
        self.config_patch.start()
        self.config_path.write_text(
            '{"app_id":"cli_test","app_secret":"secret","app_token":"app","table_id":"tbl"}',
            encoding="utf-8",
        )

    def tearDown(self):
        self.config_patch.stop()
        self.temp_dir.cleanup()

    def test_imports_once_and_replays_existing_record_without_reimporting(self):
        imported_urls = []

        async def importer(url):
            imported_urls.append(url)
            return {"success": True, "id": 42}

        syncer = FeishuArticleSync(self.get_db, importer)
        records = [{"record_id": "rec1", "fields": {"文章链接": "https://example.com/article"}}]
        syncer._token_for = AsyncMock(return_value="token")
        syncer._records = AsyncMock(return_value=records)
        syncer._writeback = AsyncMock()

        first = asyncio.run(syncer.sync())
        second = asyncio.run(syncer.sync())

        self.assertTrue(first["ok"])
        self.assertEqual(first["imported"], 1)
        self.assertEqual(second["existing"], 1)
        self.assertEqual(imported_urls, ["https://example.com/article"])
        self.assertEqual(syncer._writeback.await_count, 2)

    def test_invalid_url_is_recorded_as_actionable_issue(self):
        async def importer(_url):
            raise AssertionError("invalid links must not be imported")

        syncer = FeishuArticleSync(self.get_db, importer)
        syncer._token_for = AsyncMock(return_value="token")
        syncer._records = AsyncMock(return_value=[{"record_id": "rec2", "fields": {"文章链接": "not-a-url"}}])
        syncer._writeback = AsyncMock()

        result = asyncio.run(syncer.sync())

        self.assertTrue(result["ok"])
        self.assertEqual(result["invalid"], 1)
        update = syncer._writeback.await_args.args[3][0]
        self.assertEqual(update["fields"]["同步状态"], "需修正")
        self.assertIn("http", update["fields"]["同步说明"])

    def test_pending_ai_summary_is_not_marked_imported_and_retries(self):
        calls = []

        async def importer(url):
            calls.append(url)
            return {
                "success": True,
                "id": 43,
                "ai_summary": False,
                "ai_summary_pending": True,
            }

        syncer = FeishuArticleSync(self.get_db, importer)
        records = [{"record_id": "rec3", "fields": {"文章链接": "https://example.com/pending"}}]
        syncer._token_for = AsyncMock(return_value="token")
        syncer._records = AsyncMock(return_value=records)
        syncer._writeback = AsyncMock()

        first = asyncio.run(syncer.sync())
        second = asyncio.run(syncer.sync())

        self.assertEqual(first["invalid"], 1)
        self.assertEqual(second["invalid"], 1)
        self.assertEqual(calls, ["https://example.com/pending", "https://example.com/pending"])
        update = syncer._writeback.await_args.args[3][0]
        self.assertEqual(update["fields"]["同步状态"], "摘要待重试")
        with self.get_db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM feishu_article_imports").fetchone()[0], 0)
