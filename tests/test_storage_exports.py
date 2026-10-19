import tempfile
import unittest
from pathlib import Path
from backend.storage_exports import export_inventory, export_path, delete_exports


class ExportFilesTests(unittest.TestCase):
    def test_complete_inventory_and_selected_cleanup(self):
        with tempfile.TemporaryDirectory() as value:
            root = Path(value) / 'outputs'
            (root / 'public-preview' / 'app').mkdir(parents=True)
            for n in range(153):
                (root / 'public-preview' / 'app' / f'{n}.txt').write_text(str(n))
            outside = Path(value) / 'business.docx'
            outside.write_text('keep')
            (root / 'outside').symlink_to(outside)
            rows = export_inventory(root)
            self.assertEqual(len(rows), 153)
            self.assertTrue(all(r['purpose'] == '公开版打包、发布与验证产物' for r in rows))
            freed, errors = delete_exports(root, rows[:2])
            self.assertFalse(errors)
            self.assertGreater(freed, 0)
            self.assertEqual(len(export_inventory(root)), 151)
            self.assertEqual(outside.read_text(), 'keep')

    def test_escape_symlinks_and_stale_selection_rejected(self):
        with tempfile.TemporaryDirectory() as value:
            root = Path(value) / 'outputs'
            root.mkdir()
            path = root / 'a.txt'
            path.write_text('old')
            row = export_inventory(root)[0]
            path.write_text('changed')
            with self.assertRaises(ValueError):
                delete_exports(root, [row])
            for name in ['../business.docx', str(path.absolute()), 'missing']:
                with self.assertRaises(ValueError):
                    export_path(root, name)
            (root / 'link').symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError):
                export_path(root, 'link/a.txt')
            with self.assertRaises(ValueError):
                delete_exports(root, [export_inventory(root)[0], {'name': '../bad'}])
            self.assertTrue(path.exists())
