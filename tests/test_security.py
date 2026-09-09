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


if __name__ == "__main__":
    unittest.main()
