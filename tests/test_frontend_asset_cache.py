"""Exercise the production cache middleware without importing the live app."""
import ast
import asyncio
from pathlib import Path
import re
from types import SimpleNamespace
import unittest

from starlette.requests import Request
from starlette.responses import Response


class FrontendAssetCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(__file__).resolve().parents[1] / 'backend' / 'main.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        node = next(node for node in tree.body
                    if isinstance(node, ast.AsyncFunctionDef) and node.name == 'disable_frontend_asset_cache')
        node.decorator_list = []
        namespace = {'Request': Request, 're': re}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), namespace)
        cls.middleware = staticmethod(namespace[node.name])

    def response(self, *, status=200, media_type='text/css', version='abc123'):
        request = SimpleNamespace(url=SimpleNamespace(path='/static/case-workflows.css'),
                                  query_params={'v': version})
        original = Response(status_code=status, media_type=media_type,
                            headers={'WWW-Authenticate': 'Basic realm="Anonymous test"'} if status == 401 else {})

        async def downstream(_):
            return original

        return asyncio.run(self.middleware(request, downstream))

    def test_failures_and_redirects_never_become_immutable(self):
        for status in (302, 401, 403, 404, 500, 503):
            with self.subTest(status=status):
                response = self.response(status=status)
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                if status == 401:
                    self.assertIn('WWW-Authenticate', response.headers)

    def test_login_html_never_occupies_a_versioned_asset_url(self):
        self.assertEqual(self.response(media_type='text/html').headers['Cache-Control'], 'no-store')

    def test_successful_asset_caching_and_revalidation_are_preserved(self):
        for status in (200, 206, 304):
            with self.subTest(status=status):
                self.assertEqual(self.response(status=status).headers['Cache-Control'],
                                 'public, max-age=31536000, immutable')
        for version in ('', 'invalid version'):
            with self.subTest(version=version):
                self.assertEqual(self.response(version=version).headers['Cache-Control'], 'no-cache')
