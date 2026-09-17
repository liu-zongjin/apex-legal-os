import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend.database import connect_database, reset_runtime_configuration_for_tests


class DatabaseRuntimeTests(unittest.TestCase):
    def setUp(self):
        reset_runtime_configuration_for_tests()

    def test_connection_enables_foreign_keys_busy_timeout_and_wal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.db"
            with connect_database(path) as connection:
                self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                self.assertEqual(connection.execute("PRAGMA busy_timeout").fetchone()[0], 5000)
                self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
                self.assertEqual(connection.execute("PRAGMA synchronous").fetchone()[0], 1)

    def test_wal_can_be_disabled_for_compatibility(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ, {"LEGAL_KB_SQLITE_WAL": "0"}
        ):
            path = Path(directory) / "runtime.db"
            with sqlite3.connect(path) as seed:
                seed.execute("CREATE TABLE item (id INTEGER PRIMARY KEY)")
            with connect_database(path) as connection:
                self.assertNotEqual(connection.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")


if __name__ == "__main__":
    unittest.main()
