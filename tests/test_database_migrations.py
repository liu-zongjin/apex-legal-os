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
                self.assertEqual(migrate_database(database, backup_root), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])
                self.assertEqual(migrate_database(database, backup_root), [])
                with sqlite3.connect(database) as connection:
                    self.assertEqual(connection.execute("SELECT count(*) FROM existing_record").fetchone()[0], 1)
                    self.assertEqual(connection.execute("SELECT version FROM schema_migrations").fetchall(), [(1,), (2,), (3,), (4,), (5,), (6,), (7,), (8,), (9,), (10,), (11,), (12,)])
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

            self.assertEqual(migrate_database(database), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])

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


if __name__ == "__main__":
    unittest.main()
