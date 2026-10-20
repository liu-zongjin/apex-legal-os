import json
import ast
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend import fada_resources, package_integrity, native_helpers


class PackagedResourceTests(unittest.TestCase):
    def test_court_download_page_is_independent_of_legacy_windows_codepage(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from backend.court_dossiers import register_dossier_routes
        app = FastAPI()
        with TemporaryDirectory() as directory:
            register_dossier_routes(app, lambda: None, account_id=lambda: 'anonymous',
                session_headers=lambda: {}, download_directory=lambda: directory,
                validate_url=lambda url: None, court_origin='https://example.test', frontend_dir=directory)
            original = Path.read_text
            def read(path, encoding=None, errors=None):
                if path.name == 'court-online-downloads.html':
                    if encoding != 'utf-8':
                        raise UnicodeDecodeError('cp1252', b'\x81', 0, 1, 'legacy Windows codepage')
                    return '<html><body>法院在线下载</body></html>'
                return original(path, encoding=encoding, errors=errors)
            with patch.object(Path, 'read_text', read):
                response = TestClient(app).get('/court-online-downloads')
            self.assertEqual(response.status_code, 200)
            self.assertIn('法院在线下载', response.text)

    def test_frozen_runtime_and_readonly_resources_have_distinct_roots(self):
        tree = ast.parse((Path(__file__).parents[1] / 'backend/main.py').read_text())
        nodes = [node for node in tree.body if
                 isinstance(node, ast.FunctionDef) and node.name in {'_get_base_dir', '_get_resource_dir'} or
                 isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and
                    t.id in {'BASE_DIR', '_RESOURCE_DIR', 'RUNTIME_DIR'} for t in node.targets)]
        with TemporaryDirectory() as directory:
            recipient = Path(directory).resolve() / 'recipient'
            resource = Path(directory).resolve() / 'app-resources'
            scope = dict(Path=Path, os=os, _sys=sys)
            with patch.dict(os.environ, {'LEGAL_KB_RUNTIME_DIR': str(recipient)}), \
                 patch.object(sys, '_MEIPASS', str(resource), create=True), \
                 patch.object(sys, 'executable', str(resource / 'signed-server')):
                exec(compile(ast.Module(body=nodes, type_ignores=[]), '<runtime-paths>', 'exec'), scope)
            self.assertEqual(scope['BASE_DIR'], recipient)
            self.assertEqual(scope['RUNTIME_DIR'], recipient)
            self.assertEqual(scope['_RESOURCE_DIR'], resource)

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
