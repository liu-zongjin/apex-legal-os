import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.windows.source_server import mark_source_ready, prepare_runtime


class SourceBackupTests(unittest.TestCase):
    def test_backup_on_version_change_and_after_failed_start(self):
        with tempfile.TemporaryDirectory(prefix='stella-#-') as directory:
            runtime = Path(directory)
            with closing(sqlite3.connect(runtime / 'legal_kb.db')) as db:
                db.execute('create table cases (title text)')
                db.execute("insert into cases values ('anonymous')")
                db.commit()
            first, second = 'a' * 40, 'b' * 40
            def backups():
                return list((runtime / 'data' / 'history_backups').glob('*.db'))
            with patch.dict('os.environ', {}, clear=True):
                prepare_runtime(runtime, 18865, first)
                self.assertEqual(len(backups()), 1)
                with closing(sqlite3.connect(backups()[0])) as db:
                    self.assertEqual(db.execute('select title from cases').fetchone()[0], 'anonymous')
                mark_source_ready(runtime, first)
                prepare_runtime(runtime, 18865, first)
                self.assertEqual(len(backups()), 1)
                prepare_runtime(runtime, 18865, second)
                prepare_runtime(runtime, 18865, second)  # unsuccessful startup never advances marker
                self.assertEqual(len(backups()), 3)
                mark_source_ready(runtime, second)
                prepare_runtime(runtime, 18865, second)
                self.assertEqual(len(backups()), 3)
                prepare_runtime(runtime, 18865, None)  # unknown or modified source remains conservative
                self.assertEqual(len(backups()), 4)


if __name__ == '__main__':
    unittest.main()
