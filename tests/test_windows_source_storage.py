import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.windows.source_server import mark_source_ready, prepare_runtime
from scripts.windows.source_storage import prune, record


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


class SourceEnvironmentCleanupTests(unittest.TestCase):
    def test_only_unchanged_old_managed_environments_are_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            versions, runtime = root / 'versions', root / 'runtime'
            versions.mkdir()
            runtime.mkdir()
            names = ['candidate-' + character * 32 for character in 'abcdef']
            for name in names:
                env = versions / name / '.venv'
                (env / 'Lib').mkdir(parents=True)
                (env / 'Lib' / 'package.py').write_text('original', encoding='utf-8')
            for name in names[:-1]:
                record(versions, runtime, name)
            (versions / names[1] / '.venv' / 'Lib' / 'package.py').write_text('user change', encoding='utf-8')
            (versions / names[2] / '.venv' / 'personal.txt').write_text('keep', encoding='utf-8')
            (versions / names[0] / 'user-source.txt').write_text('keep source', encoding='utf-8')
            removed = prune(versions, runtime, names[3], names[4])
            self.assertEqual(removed, [names[0]])
            self.assertFalse((versions / names[0] / '.venv').exists())
            self.assertTrue((versions / names[0] / 'user-source.txt').exists())
            for name in names[1:]:
                self.assertTrue((versions / name / '.venv').exists())
            self.assertEqual(prune(versions, runtime, names[3], names[4]), [])

    def test_links_and_untrusted_names_are_never_cleaned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            versions, runtime = root / 'versions', root / 'runtime'
            versions.mkdir()
            runtime.mkdir()
            name = 'candidate-' + 'a' * 32
            env = versions / name / '.venv'
            env.mkdir(parents=True)
            (env / 'file').write_text('content', encoding='utf-8')
            record(versions, runtime, name)
            outside = root / 'outside'
            outside.write_text('keep', encoding='utf-8')
            try:
                (env / 'link').symlink_to(outside)
            except OSError:
                self.skipTest('creating links is unavailable')
            self.assertEqual(prune(versions, runtime, '', ''), [])
            self.assertEqual(outside.read_text(encoding='utf-8'), 'keep')
            with self.assertRaises(ValueError):
                record(versions, runtime, '../outside')


if __name__ == '__main__':
    unittest.main()
