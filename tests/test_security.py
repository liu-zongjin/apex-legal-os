import unittest
from unittest.mock import patch

from backend.security import is_local_access_trusted, is_loopback_client


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


if __name__ == "__main__":
    unittest.main()
