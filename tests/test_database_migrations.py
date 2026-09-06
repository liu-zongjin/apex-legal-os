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
                self.assertEqual(migrate_database(database, backup_root), [1])
                self.assertEqual(migrate_database(database, backup_root), [])
                with sqlite3.connect(database) as connection:
                    self.assertEqual(connection.execute("SELECT count(*) FROM existing_record").fetchone()[0], 1)
                    self.assertEqual(connection.execute("SELECT version FROM schema_migrations").fetchall(), [(1,)])
                self.assertEqual(len(list(backup_root.glob("*.db"))), 1)


if __name__ == "__main__":
    unittest.main()
