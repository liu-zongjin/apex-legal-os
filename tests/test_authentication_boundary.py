"""Exercise the real access middleware with anonymous requests and no live DB."""
import ast
import asyncio
from pathlib import Path
import subprocess
import unittest
from starlette.requests import Request
from starlette.responses import Response

ROOT = Path(__file__).resolve().parents[1]


class AuthenticationBoundaryTests(unittest.TestCase):
    def middleware(self, local=False, signed_in=False):
        tree = ast.parse((ROOT / 'backend/main.py').read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
                  and n.name == 'private_basic_auth')
        fn.decorator_list = []
        namespace = dict(Request=Request, Response=Response,
                         is_local_access_trusted=lambda host: local,
                         check_basic_auth_header=lambda header: False,
                         check_session_cookie=lambda cookie: signed_in,
                         get_session_cookie_name=lambda: 'test-session',
                         check_access_token=lambda token: False)
        exec(compile(ast.Module(body=[fn], type_ignores=[]), '<middleware>', 'exec'), namespace)
        return namespace['private_basic_auth']

    def request(self):
        return Request({'type':'http', 'method':'GET', 'path':'/api/case-manager/cases',
                        'query_string':b'', 'headers':[], 'client':('192.0.2.1',1234)})

    def test_only_access_gate_marks_local_authentication_failure(self):
        async def downstream(request):
            return Response('court session expired', status_code=401)
        rejected = asyncio.run(self.middleware()(self.request(), downstream))
        self.assertEqual(rejected.status_code, 401)
        self.assertEqual(rejected.headers['x-apex-auth-required'], 'local')
        for local, signed_in in [(True,False),(False,True)]:
            result = asyncio.run(self.middleware(local,signed_in)(self.request(), downstream))
            self.assertEqual(result.status_code, 401)
            self.assertNotIn('x-apex-auth-required', result.headers)
            self.assertEqual(result.body, b'court session expired')

    def test_browser_error_and_navigation_paths(self):
        result = subprocess.run(['node','tests/case_manager_api_errors_ui.js'], cwd=ROOT,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
