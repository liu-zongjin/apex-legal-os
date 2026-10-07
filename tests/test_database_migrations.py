import sqlite3
import unittest

from backend.migrations import migrate_database


class DatabaseMigrationTests(unittest.TestCase):
    def test_migrations_are_repeat_safe_and_back_up_existing_database(self):
        with self.subTest("temporary database"):
            import tempfile
            from pathlib import Path
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                database = root / "apex.db"
                with sqlite3.connect(database) as connection:
                    connection.execute("CREATE TABLE existing_record (id INTEGER PRIMARY KEY)")
                    connection.execute("INSERT INTO existing_record VALUES (1)")
                backup_root = root / "backups"
                self.assertEqual(migrate_database(database, backup_root), list(range(1, 15)))
                self.assertEqual(migrate_database(database, backup_root), [])
                with sqlite3.connect(database) as connection:
                    self.assertEqual(connection.execute("SELECT count(*) FROM existing_record").fetchone()[0], 1)
                    self.assertEqual(connection.execute("SELECT version FROM schema_migrations").fetchall(), [(i,) for i in range(1, 15)])
                    self.assertIsNotNone(connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='case_archive_saves'"
                    ).fetchone())
                self.assertEqual(len(list(backup_root.glob("*.db"))), 1)

    def test_default_update_backup_location_is_history_backups(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "legal_kb.db"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE existing_record (id INTEGER PRIMARY KEY)")

            self.assertEqual(migrate_database(database), list(range(1, 15)))

            with sqlite3.connect(database) as connection:
                indexes = {row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                )}
            # A baseline-only database does not have optional scheduler tables;
            # the migration remains safely repeatable in that shape.
            self.assertNotIn("idx_authority_watch_due", indexes)

            backups = list((root / "data" / "history_backups").glob("*.db"))
            self.assertEqual(len(backups), 1)
            self.assertFalse((root / "data" / "schema_backups").exists())

    def test_upgrade_consolidates_historical_domain_suggestions(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "apex.db"
            with sqlite3.connect(database) as connection:
                connection.executescript("""
                    CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,name TEXT,applied_at TEXT);
                    CREATE TABLE articles(id INTEGER PRIMARY KEY);
                    CREATE TABLE domain_taxonomy(id INTEGER PRIMARY KEY,name TEXT,parent_id INTEGER);
                    CREATE TABLE domain_suggestions(id INTEGER PRIMARY KEY,name TEXT,parent_id INTEGER,
                        article_id INTEGER,keywords_json TEXT DEFAULT '[]',status TEXT DEFAULT 'pending',created_at TEXT);
                    CREATE TABLE domain_suggestion_articles(suggestion_id INTEGER,article_id INTEGER,
                        PRIMARY KEY(suggestion_id,article_id));
                    INSERT INTO articles(id) VALUES (1),(2);
                    INSERT INTO domain_suggestions(id,name,article_id,created_at) VALUES
                        (1,'举证责任分配',1,'2026-01-01'),
                        (2,'民事诉讼举证责任分配与高度盖然性证明标准',2,'2026-01-01');
                    INSERT INTO domain_suggestion_articles VALUES (1,1),(2,2);
                """)
                connection.executemany("INSERT INTO schema_migrations VALUES (?,'old','2026-01-01')",
                                       [(i,) for i in range(1, 14)])
            self.assertEqual(migrate_database(database, Path(directory) / "backups"), [14])
            with sqlite3.connect(database) as connection:
                row = connection.execute("""SELECT s.name,COUNT(e.article_id) FROM domain_suggestions s
                    JOIN domain_suggestion_articles e ON e.suggestion_id=s.id
                    WHERE s.name='民事诉讼' GROUP BY s.id""").fetchone()
                self.assertEqual(row, ("民事诉讼", 2))
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM domain_suggestions WHERE status='pending' AND name<>'民事诉讼'"
                ).fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
