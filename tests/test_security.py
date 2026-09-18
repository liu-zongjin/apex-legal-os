import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend import main
from backend.security import (
    _BIOMETRIC_LOGIN_BRIDGE_SECRET,
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
            shell = client.get("/case-manager", headers={"Accept": "text/html"})
            self.assertEqual(shell.status_code, 200)
            self.assertEqual(shell.headers.get("x-apex-shell-version"), "212")
            self.assertIn("caseManagerBoot", shell.text)

            script = client.get("/static/case-manager.js?v=212")
            self.assertEqual(script.status_code, 200)
            self.assertIn("javascript", script.headers.get("content-type", ""))

            status = client.get("/api/pwa/session-status")
            self.assertEqual(status.status_code, 200)
            self.assertEqual(status.headers.get("cache-control"), "no-store, max-age=0")
            self.assertEqual(status.json(), {
                "server_reachable": True,
                "authenticated": False,
                "shell_version": "212",
            })
            self.assertEqual(client.get("/api/case-manager/dashboard").status_code, 401)


if __name__ == "__main__":
    unittest.main()
