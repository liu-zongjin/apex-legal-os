import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend import fada_resources, package_integrity, native_helpers


class PackagedResourceTests(unittest.TestCase):
    def test_fada_catalog_works_without_runtime_cache_and_never_includes_notes(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'page.html'
            data = root / 'userdata/fada.json'
            answers = [{'batch': '公开答问', 'url': 'https://example.test/public', 'date': '2026-10-21',
                        'question': '公开问题', 'answer': '公开答复', 'note': 'PRIVATE-NOTE'}]
            source.write_text('const qaData = ' + json.dumps(answers) + ';\n')
            batches = fada_resources.read_batches(data, source)
            self.assertEqual(batches[0]['qa_pairs'][0]['question'], '公开问题')
            self.assertNotIn('PRIVATE-NOTE', json.dumps(batches))
            data.parent.mkdir()
            data.write_text(json.dumps([{'title': '新版公开数据', 'qa_pairs': []}]))
            self.assertEqual(fada_resources.read_batches(data, source)[0]['title'], '新版公开数据')
            self.assertEqual(source.read_text(), 'const qaData = ' + json.dumps(answers) + ';\n')

    def test_refresh_renders_current_answers_without_injecting_markup(self):
        original = '<script>const qaData = [];\n</script>'
        page = fada_resources.render_page(original, [{'title': '公开数据', 'qa_pairs': [
            {'question': '问题', 'answer': '</script><script>BAD</script>'}]}])
        self.assertEqual(page.count('</script>'), 1)
        self.assertEqual(fada_resources.embedded_answers(page)[0]['question'], '问题')

    def test_manifest_discovers_pages_and_rejects_missing_actual_package_asset(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'backend').mkdir()
            (root / 'frontend').mkdir()
            (root / 'backend/main.py').write_text('@app.get("/example")\ndef page():\n return read("example.html")\n')
            (root / 'frontend/example.html').write_text('<script src="/static/example.js"></script>')
            manifest = package_integrity.create_manifest(root, 'macos')
            self.assertIn('/example', manifest['pages'])
            self.assertIn('/fada-wang', manifest['pages'])
            self.assertIn('/static/example.js', manifest['assets'])
            client = SimpleNamespace(get=lambda route: SimpleNamespace(status_code=404))
            with self.assertRaisesRegex(RuntimeError, 'HTTP 404'):
                package_integrity.verify_package(client, root)

    def test_missing_resource_is_rejected_even_when_page_returns_200(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'backend').mkdir()
            (root / 'frontend').mkdir()
            path = root / 'frontend/index.html'
            path.write_text('<html>application</html>')
            package_integrity.create_manifest(root, 'macos')
            path.unlink()
            with self.assertRaisesRegex(RuntimeError, 'frontend/index.html'):
                package_integrity.verify_package(None, root)

    def test_frozen_helpers_resolve_inside_app_instead_of_source_dist(self):
        with TemporaryDirectory() as directory:
            app = Path(directory) / 'Stella.app/Contents'
            executable = app / 'Resources/Server/service'
            executable.parent.mkdir(parents=True)
            executable.touch()
            helper = app / 'MacOS/APEXVisionOCR'
            helper.parent.mkdir()
            helper.touch()
            with patch.object(native_helpers.sys, 'platform', 'darwin'), \
                 patch.object(native_helpers.sys, 'frozen', True, create=True), \
                 patch.object(native_helpers.sys, 'executable', str(executable)):
                self.assertEqual(native_helpers.macos_helper('APEXVisionOCR'), helper.resolve())
            with patch.object(native_helpers.sys, 'platform', 'win32'):
                self.assertIsNone(native_helpers.macos_helper('APEXVisionOCR'))
