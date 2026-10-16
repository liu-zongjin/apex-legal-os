"""Restart verification with anonymous credentials and a disposable local server."""
import base64
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import threading
import unittest
import urllib.error
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("restart_helper", ROOT / "restart.py")
restart = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restart)


class RestartTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.base = patch.object(restart, "BASE_DIR", self.folder)
        self.base.start()
        self.addCleanup(self.base.stop)

    def test_environment_credentials_take_precedence(self):
        os.environ.update(LEGAL_KB_ACCESS_USER="fixture", LEGAL_KB_ACCESS_PASSWORD="anonymous")
        (self.folder / ".env.private").write_text("exit 9\n")
        self.assertEqual(restart.access_credentials(), ("fixture", "anonymous"))

    def test_private_file_shell_escaping_and_empty_user_default(self):
        (self.folder / ".env.private").write_text(
            "LEGAL_KB_ACCESS_USER=''\nLEGAL_KB_ACCESS_PASSWORD='anonymous $ ! value'\n"
        )
        self.assertEqual(restart.access_credentials(), ("lawyer", "anonymous $ ! value"))

    def test_missing_or_invalid_configuration_does_not_invent_credentials(self):
        self.assertIsNone(restart.access_credentials())
        (self.folder / ".env.private").write_text("return 3\n")
        self.assertIsNone(restart.access_credentials())

    def test_configuration_timeout_is_bounded_and_does_not_expose_secrets(self):
        (self.folder / ".env.private").touch()
        output = io.StringIO()
        with patch.object(restart.subprocess, "run", side_effect=subprocess.TimeoutExpired("fixture", 5)) as run:
            with redirect_stdout(output):
                self.assertFalse(restart.wait_for_verified_server())
        self.assertEqual(run.call_args.kwargs["timeout"], 5)
        self.assertIn("无法读取本地登录配置", output.getvalue())

    def verify_responses(self, responses, previous=None):
        opener = Mock()
        def respond(*args, **kwargs):
            item = responses.pop(0) if len(responses) > 1 else responses[0]
            if isinstance(item, Exception):
                raise item
            return io.BytesIO(json.dumps(item).encode())
        opener.open.side_effect = respond
        with patch.object(restart, "status_opener", return_value=opener), patch.object(restart.time, "sleep"):
            with redirect_stdout(io.StringIO()):
                return restart.wait_for_verified_server(previous, timeout=.01)

    def test_old_process_and_stale_source_are_not_success(self):
        self.assertFalse(self.verify_responses([{"pid": 11, "source_status": "current"}], {11}))
        self.assertFalse(self.verify_responses([{"pid": 12, "source_status": "stale"}], {11}))

    def test_malformed_status_is_retried_until_verified(self):
        self.assertTrue(self.verify_responses([
            [], {"pid": [], "source_status": "current"},
            {"pid": 12, "source_status": "current", "runtime_source_version": "fixture"},
        ], {11}))

    def test_unauthorized_response_is_never_success(self):
        error = urllib.error.HTTPError("http://127.0.0.1/", 401, "Unauthorized", {}, None)
        self.assertFalse(self.verify_responses([error]))

    def test_authenticated_loopback_verification(self):
        auth = "Basic " + base64.b64encode(b"fixture:anonymous").decode()
        observed = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                authorized = self.headers.get("Authorization") == auth
                observed.append(authorized)
                self.send_response(200 if authorized else 401)
                if not authorized:
                    self.send_header("WWW-Authenticate", 'Basic realm="fixture"')
                self.end_headers()
                if authorized:
                    self.wfile.write(b'{"pid":12,"source_status":"current"}')
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            os.environ.update(LEGAL_KB_ACCESS_USER="fixture", LEGAL_KB_ACCESS_PASSWORD="anonymous")
            with patch.object(restart, "PORT", str(server.server_port)), redirect_stdout(io.StringIO()):
                self.assertTrue(restart.wait_for_verified_server({11}, timeout=2))
            self.assertEqual(observed, [False, True])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_already_exited_process_does_not_abort_restart(self):
        with patch.object(restart, "listening_pids", side_effect=[[11], [], []]):
            with patch.object(restart.os, "kill", side_effect=ProcessLookupError), redirect_stdout(io.StringIO()):
                self.assertTrue(restart.stop_listeners())

    def run_wrapper(self, result):
        script = self.folder / "restart.command"
        script.write_bytes((ROOT / "重启法律操作系统.command").read_bytes())
        (self.folder / "restart.py").write_text("import sys\nsys.exit(%d)\n" % result)
        launch = self.folder / "open"
        launch.write_text('#!/bin/sh\nprintf "%s" "$1" > "$RESTART_TEST_OPEN_PATH"\n')
        launch.chmod(0o755)
        output_path = self.folder / "opened.txt"
        env = dict(os.environ, PATH=str(self.folder) + ":/usr/bin:/bin", PORT="18761",
                   RESTART_TEST_OPEN_PATH=str(output_path), TERM="dumb")
        completed = subprocess.run(["/bin/zsh", str(script)], input="\n", text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=5)
        return completed, output_path

    def test_desktop_wrapper_uses_verified_result_and_configured_port(self):
        completed, opened = self.run_wrapper(0)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(opened.read_text(), "http://localhost:18761")
        self.assertIn("已通过源码版本校验", completed.stdout)

    def test_desktop_wrapper_propagates_failure_without_opening_browser(self):
        completed, opened = self.run_wrapper(1)
        self.assertEqual(completed.returncode, 1)
        self.assertFalse(opened.exists())
        self.assertNotIn("重启完成", completed.stdout)


if __name__ == "__main__":
    unittest.main()
