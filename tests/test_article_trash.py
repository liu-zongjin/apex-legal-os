import datetime as dt
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.article_trash import (
    TrashRestoreConflict,
    list_articles,
    move_articles,
    purge_articles,
    purge_expired,
    restore_articles,
)
from backend.database import connect_database
from backend.migrations import migrate_database


UTC = dt.timezone.utc


class ArticleTrashTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        path = Path(self.directory.name) / "test.db"
        with sqlite3.connect(path) as conn:
            conn.executescript("""
                CREATE TABLE articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_hash TEXT UNIQUE
                );
                CREATE TABLE notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article_id INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE
                );
                CREATE TABLE article_assets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article_id INTEGER NOT NULL,
                    payload BLOB NOT NULL,
                    FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE
                );
                CREATE TABLE projects (id INTEGER PRIMARY KEY);
                CREATE TABLE article_project_links (
                    article_id INTEGER NOT NULL,
                    project_id INTEGER NOT NULL,
                    PRIMARY KEY(article_id, project_id),
                    FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE,
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
                );
            """)
        migrate_database(path, Path(self.directory.name) / "backups")
        self.conn = connect_database(path)
        self.addCleanup(self.conn.close)

    def add_article(self, title, source_hash):
        cursor = self.conn.execute(
            "INSERT INTO articles(title,content,source_type,source_hash) VALUES (?,?,?,?)",
            (title, f"{title}正文", "url", source_hash),
        )
        return cursor.lastrowid

    def test_delete_and_restore_preserve_article_notes_and_cascading_blobs(self):
        article_id = self.add_article("测试文章", "hash-one")
        self.conn.execute("INSERT INTO notes(article_id,content) VALUES (?,?)", (article_id, "原有笔记"))
        self.conn.execute("INSERT INTO article_assets(article_id,payload) VALUES (?,?)", (article_id, b"\x00\xff"))
        self.conn.commit()
        deleted_at = dt.datetime(2026, 1, 1, 9, tzinfo=UTC)

        with self.conn:
            result = move_articles(self.conn, [article_id, article_id, 999], deleted_at)
        self.assertEqual(result["deleted_count"], 1)
        self.assertEqual(result["missing_article_ids"], [999])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0], 0)
        trash = list_articles(self.conn, 20, 0)
        self.assertEqual(trash["total"], 1)
        self.assertEqual(trash["items"][0]["expires_at"], "2026-01-31T09:00:00+00:00")

        with self.conn:
            restored = restore_articles(self.conn, [result["items"][0]["id"]], deleted_at + dt.timedelta(days=5))
        self.assertEqual(restored["article_ids"], [article_id])
        self.assertEqual(self.conn.execute("SELECT content FROM articles WHERE id=?", (article_id,)).fetchone()[0], "测试文章正文")
        self.assertEqual(self.conn.execute("SELECT content FROM notes WHERE article_id=?", (article_id,)).fetchone()[0], "原有笔记")
        self.assertEqual(self.conn.execute("SELECT payload FROM article_assets WHERE article_id=?", (article_id,)).fetchone()[0], b"\x00\xff")
        self.assertEqual(list_articles(self.conn, 20, 0)["total"], 0)

    def test_each_article_expires_30_days_after_its_own_deletion(self):
        first = self.add_article("第一篇", "first")
        second = self.add_article("第二篇", "second")
        self.conn.commit()
        day_one = dt.datetime(2026, 1, 1, tzinfo=UTC)
        with self.conn:
            first_item = move_articles(self.conn, [first], day_one)["items"][0]
            second_item = move_articles(self.conn, [second], day_one + dt.timedelta(days=10))["items"][0]
        with self.conn:
            self.assertEqual(purge_expired(self.conn, day_one + dt.timedelta(days=30)), 1)
        self.assertEqual(list_articles(self.conn, 20, 0)["items"][0]["id"], second_item["id"])
        with self.conn:
            self.assertEqual(restore_articles(self.conn, [first_item["id"]], day_one + dt.timedelta(days=30))["restored_count"], 0)
            self.assertEqual(restore_articles(self.conn, [second_item["id"]], day_one + dt.timedelta(days=30))["restored_count"], 1)

    def test_manual_single_and_all_purge(self):
        ids = [self.add_article(f"文章{i}", f"hash-{i}") for i in range(3)]
        self.conn.commit()
        with self.conn:
            trashed = move_articles(self.conn, ids)["items"]
            self.assertEqual(purge_articles(self.conn, [trashed[0]["id"]]), 1)
            self.assertEqual(purge_articles(self.conn), 2)
        self.assertEqual(list_articles(self.conn, 20, 0)["total"], 0)

    def test_restore_conflict_leaves_trash_snapshot_intact(self):
        article_id = self.add_article("旧文章", "same-source")
        self.conn.commit()
        with self.conn:
            trash_id = move_articles(self.conn, [article_id])["items"][0]["id"]
        self.add_article("重新导入", "same-source")
        self.conn.commit()
        with self.assertRaises(TrashRestoreConflict):
            with self.conn:
                restore_articles(self.conn, [trash_id])
        self.assertEqual(list_articles(self.conn, 20, 0)["total"], 1)
        self.assertIsNone(self.conn.execute("SELECT id FROM articles WHERE id=?", (article_id,)).fetchone())

    def test_restore_keeps_article_when_unrelated_parent_was_removed(self):
        article_id = self.add_article("关联文章", "related-source")
        self.conn.execute("INSERT INTO projects(id) VALUES (7)")
        self.conn.execute("INSERT INTO article_project_links(article_id,project_id) VALUES (?,7)", (article_id,))
        self.conn.commit()
        with self.conn:
            trash_id = move_articles(self.conn, [article_id])["items"][0]["id"]
            self.conn.execute("DELETE FROM projects WHERE id=7")
        with self.conn:
            restored = restore_articles(self.conn, [trash_id])
        self.assertEqual(restored["article_ids"], [article_id])
        self.assertEqual(restored["skipped_related_rows"], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM article_project_links").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
