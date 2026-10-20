import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.storage_temporary import inventory, delete_selected


class TemporaryStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / '.tmp').mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, data=b'fixture'):
        p = self.root / '.tmp' / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    def rows(self):
        files = [{'name':p.relative_to(self.root).as_posix(), 'size':p.stat().st_size}
                 for p in (self.root / '.tmp').rglob('*') if p.is_file() and not p.is_symlink()]
        return inventory(self.root, files)

    def selections(self, rows):
        return [{'name':r['name'], 'revision':r['revision']} for r in rows]

    def idle(self):
        return patch('backend.storage_temporary.subprocess.run', return_value=SimpleNamespace(returncode=1, stdout='', stderr=''))

    def test_classification_keeps_latest_unknown_sql_and_counts_every_record_once(self):
        for suffix in ('', '-r2', '-final'):
            self.write('public-update-package-20261020'+suffix+'/Stella.app/Contents/app')
        self.write('sparkle-2.10.0/bin/tool')
        self.write('system-messages-before.sql')
        self.write('unknown.txt')
        rows = self.rows(); by_name = {r['name']:r for r in rows}
        self.assertEqual(by_name['.tmp/public-update-package-20261020']['level'], 'priority')
        self.assertEqual(by_name['.tmp/public-update-package-20261020-final']['level'], 'optional')
        self.assertEqual(by_name['.tmp/sparkle-2.10.0']['level'], 'optional')
        self.assertFalse(by_name['.tmp/system-messages-before.sql']['cleanable'])
        self.assertFalse(by_name['.tmp/unknown.txt']['cleanable'])
        self.assertEqual(sum(r['count'] for r in rows), 6)
        self.assertEqual(sum(r['size'] for r in rows), 6*7)

    def test_delete_selected_preserves_other_candidates_and_business_data(self):
        target = self.write('public-update-package-20261020-r2/Stella.app/Contents/app')
        latest = self.write('public-update-package-20261020-final/Stella.app/Contents/app')
        sql = self.write('rollback.sql')
        rows = self.rows(); selected = [r for r in rows if r['level']=='priority']
        with self.idle():
            size, errors = delete_selected(self.root, self.selections(selected), rows)
        self.assertEqual(size, 7); self.assertEqual(errors, [])
        self.assertFalse(target.exists()); self.assertTrue(latest.exists()); self.assertTrue(sql.exists())

    def test_rejects_legacy_whole_directory_cleanup(self):
        from backend import main
        self.write('sparkle-2.10.0/bin/tool')
        request = SimpleNamespace(client=SimpleNamespace(host='127.0.0.1'), json=AsyncMock(return_value={'type':'temp_files'}))
        with patch.object(main, 'BASE_DIR', self.root), patch.object(main, 'DB_PATH', self.root/'legal_kb.db'), patch.object(main, 'UPLOAD_DIR', self.root/'uploads'), patch.object(main, 'ARTICLE_IMAGE_DIR', self.root/'article_images'):
            result = asyncio.run(main.cleanup_storage(request))
        self.assertFalse(result['ok']); self.assertTrue((self.root/'.tmp/sparkle-2.10.0/bin/tool').exists())

    def test_stale_or_protected_selection_rejects_entire_batch(self):
        first = self.write('sparkle-2.10.0/bin/tool')
        second = self.write('system-messages-ui/shot.png')
        rows = self.rows(); selected = self.selections(rows)
        second.write_bytes(b'changed')
        with self.idle(), self.assertRaises(ValueError):
            delete_selected(self.root, selected, rows)
        self.assertTrue(first.exists())
        rows = self.rows()
        with self.assertRaises(ValueError):
            delete_selected(self.root, self.selections(rows)+[{'name':'../outside', 'revision':'x'}], rows)
        self.assertTrue(first.exists())

    def test_data_and_external_symlinks_protect_otherwise_known_artifacts(self):
        self.write('system-messages-ui/rollback.db')
        self.write('document-branding-ui/secret.json')
        path = self.write('external.txt')
        directory = self.root/'.tmp/unified-settings-ui'; directory.mkdir()
        (directory/'link').symlink_to(path)
        self.write('unified-settings-ui/shot.png')
        self.assertTrue(all(not row['cleanable'] for row in self.rows()))

    def test_live_open_files_and_failed_inspection_block_cleanup(self):
        target = self.write('sparkle-2.10.0/bin/tool')
        rows = self.rows()
        for result in [SimpleNamespace(returncode=0, stdout='p123\nn'+str(target)+'\n', stderr=''), SimpleNamespace(returncode=1, stdout='', stderr='inspection error')]:
            with patch('backend.storage_temporary.subprocess.run', return_value=result), self.assertRaises(ValueError):
                delete_selected(self.root, self.selections(rows), rows)
        self.assertTrue(target.exists())

    def test_bundled_ca_certificate_and_internal_framework_links_are_allowed(self):
        self.write('public-update-package-20261020/Stella.app/Contents/Resources/Server/_internal/certifi/cacert.pem')
        framework = self.root/'.tmp/public-update-package-20261020/Stella.app/Contents/Frameworks/Sparkle.framework'
        (framework/'Versions/A').mkdir(parents=True)
        (framework/'Versions/Current').symlink_to('A')
        self.assertTrue(self.rows()[0]['cleanable'])

    def test_information_total_matches_category(self):
        from backend import main
        self.write('sparkle-2.10.0/bin/tool')
        self.write('before.sql')
        self.write('debug.log')
        with patch.object(main, 'BASE_DIR', self.root), patch.object(main, 'DB_PATH', self.root/'legal_kb.db'), patch.object(main, 'UPLOAD_DIR', self.root/'uploads'), patch.object(main, 'ARTICLE_IMAGE_DIR', self.root/'article_images'):
            result = main.get_storage_info()
        item = next(r for r in result['items'] if r['raw']=='temp_files')
        self.assertEqual(item['kind'], 'optional')
        self.assertEqual(item['size'], sum(r['size'] for r in item['temporary_items']))
        self.assertEqual(item['count'], sum(r['count'] for r in item['temporary_items']))


if __name__ == '__main__':
    unittest.main()
