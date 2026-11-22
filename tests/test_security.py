import base64
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend import main
from backend.pwa import PWA_SHELL_VERSION
from backend.security import (
    _BIOMETRIC_LOGIN_BRIDGE_SECRET,
    authenticate_access_credentials,
    check_basic_auth_header,
    check_session_cookie,
    create_session_token,
    complete_biometric_login_challenge,
    consume_biometric_login_ticket,
    create_biometric_login_challenge,
    is_biometric_login_enabled,
    is_local_access_trusted,
    is_loopback_client,
)


class LocalAccessSecurityTests(unittest.TestCase):
    def test_loopback_addresses_bypass_remote_authentication(self):
        self.assertTrue(is_loopback_client("127.0.0.1"))
        self.assertTrue(is_loopback_client("::1"))
        self.assertTrue(is_loopback_client("localhost"))

    def test_network_and_spoofed_values_are_not_loopback(self):
        self.assertFalse(is_loopback_client("100.114.58.43"))
        self.assertFalse(is_loopback_client("192.168.1.8"))
        self.assertFalse(is_loopback_client("127.0.0.1, 100.64.0.2"))
        self.assertFalse(is_loopback_client(None))

    def test_private_mode_keeps_loopback_connections_behind_login(self):
        with patch.dict("os.environ", {"LEGAL_KB_PRIVATE_MODE": "1"}):
            self.assertFalse(is_local_access_trusted("127.0.0.1"))
        with patch.dict("os.environ", {"LEGAL_KB_PRIVATE_MODE": "0"}):
            self.assertTrue(is_local_access_trusted("127.0.0.1"))

    def test_biometric_login_proof_is_single_use(self):
        challenge = create_biometric_login_challenge()
        ticket = complete_biometric_login_challenge(challenge, _BIOMETRIC_LOGIN_BRIDGE_SECRET)

        self.assertTrue(ticket)
        self.assertIsNone(complete_biometric_login_challenge(challenge, _BIOMETRIC_LOGIN_BRIDGE_SECRET))
        self.assertTrue(consume_biometric_login_ticket(ticket))
        self.assertFalse(consume_biometric_login_ticket(ticket))

    def test_biometric_login_rejects_an_invalid_bridge_secret(self):
        challenge = create_biometric_login_challenge()
        self.assertIsNone(complete_biometric_login_challenge(challenge, "not-the-native-shell"))

    def test_biometric_login_can_be_disabled_by_local_setting(self):
        with patch.dict("os.environ", {"LEGAL_KB_BIOMETRIC_LOGIN_ENABLED": "0"}):
            self.assertFalse(is_biometric_login_enabled())
        with patch.dict("os.environ", {"LEGAL_KB_BIOMETRIC_LOGIN_ENABLED": "yes"}):
            self.assertTrue(is_biometric_login_enabled())

    def test_access_password_accepts_unicode_after_persisting_the_private_setting(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = Path(directory) / ".env.private"
            environment.write_text("KEEP=unchanged\nLEGAL_KB_ACCESS_PASSWORD=fixture-old\n", encoding="utf-8")
            with patch.dict("os.environ", {"LEGAL_KB_PRIVATE_ENV_PATH": str(environment),
                                          "LEGAL_KB_ACCESS_USER": "测试用户", "LEGAL_KB_ACCESS_PASSWORD": "fixture-old"}):
                self.assertTrue(main.access_user_settings()["login_settings_available"])
                password = "本地测试密码一二三"
                main._persist_private_environment({"LEGAL_KB_ACCESS_PASSWORD": password})
                self.assertIn(password, environment.read_text(encoding="utf-8"))
                self.assertIn("KEEP=unchanged", environment.read_text(encoding="utf-8"))
                self.assertEqual(list(Path(directory).iterdir()), [environment])
                with patch.dict("os.environ", {"LEGAL_KB_ACCESS_PASSWORD": password}):
                    self.assertTrue(authenticate_access_credentials("测试用户", password))
                    self.assertFalse(authenticate_access_credentials("测试用户", "另一个密码"))
                    basic = base64.b64encode(f"测试用户:{password}".encode()).decode()
                    self.assertTrue(check_basic_auth_header("Basic " + basic))
                    self.assertTrue(check_session_cookie(create_session_token("测试用户")))

    def test_loopback_management_requests_remain_available_in_private_mode(self):
        request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
        with patch.object(main, "allow_remote_management", return_value=False):
            main.require_remote_management_enabled(request)


class PrivateAccessWhitelistTests(unittest.TestCase):
    def _client(self):
        from fastapi.testclient import TestClient

        return TestClient(main.app)

    def test_native_shell_biometric_bridge_paths_are_public(self):
        with patch.dict(
            "os.environ",
            {"LEGAL_KB_PRIVATE_MODE": "1", "LEGAL_KB_ACCESS_PASSWORD": "test-password"},
        ):
            client = self._client()
            challenge = client.get("/api/personal-center/biometric/challenge")
            self.assertEqual(challenge.status_code, 200)
            self.assertTrue(challenge.json().get("challenge"))

            verify = client.post(
                "/api/personal-center/verify/biometric",
                json={"challenge": challenge.json()["challenge"], "secret": "wrong-secret"},
            )
            self.assertEqual(verify.status_code, 401)
            self.assertEqual(verify.json().get("detail"), "指纹验证凭证无效或已过期")

    def test_personal_center_api_still_requires_access_login(self):
        with patch.dict(
            "os.environ",
            {"LEGAL_KB_PRIVATE_MODE": "1", "LEGAL_KB_ACCESS_PASSWORD": "test-password"},
        ):
            client = self._client()
            self.assertEqual(
                client.get("/api/personal-center/security/status").status_code, 401
            )

    def test_mobile_shell_and_status_are_public_but_case_data_remains_private(self):
        with patch.dict(
            "os.environ",
            {"LEGAL_KB_PRIVATE_MODE": "1", "LEGAL_KB_ACCESS_PASSWORD": "test-password"},
        ):
            client = self._client()
            home_shell = client.get("/app-shell", headers={"Accept": "text/html"})
            self.assertEqual(home_shell.status_code, 200)
            self.assertEqual(home_shell.headers.get("x-apex-shell-version"), PWA_SHELL_VERSION)
            self.assertIn('id="tab-bar"', home_shell.text)
            login = client.get("/", headers={"Accept": "text/html"})
            self.assertNotIn("x-apex-shell-version", login.headers)
            self.assertIn("/login", login.text)
            self.assertEqual(client.get("/static/app.js").status_code, 200)
            shell = client.get("/case-manager", headers={"Accept": "text/html"})
            self.assertEqual(shell.status_code, 200)
            self.assertEqual(shell.headers.get("x-apex-shell-version"), PWA_SHELL_VERSION)
            self.assertIn("caseManagerBoot", shell.text)

            script = client.get(f"/static/case-manager.js?v={PWA_SHELL_VERSION}")
            self.assertEqual(script.status_code, 200)
            self.assertIn("javascript", script.headers.get("content-type", ""))

            for asset in ("series-table-advanced.js", "apex-case-record-editor.js", "apex-case-record-editor.css", "apex-record-typography.css"):
                self.assertEqual(client.get(f"/static/{asset}?v=2026102104").status_code, 200, asset)

            status = client.get("/api/pwa/session-status")
            self.assertEqual(status.status_code, 200)
            self.assertEqual(status.headers.get("cache-control"), "no-store, max-age=0")
            self.assertEqual(status.json(), {
                "server_reachable": True,
                "authenticated": False,
                "shell_version": PWA_SHELL_VERSION,
            })
            self.assertEqual(client.get("/api/case-manager/dashboard").status_code, 401)


if __name__ == "__main__":
    unittest.main()
