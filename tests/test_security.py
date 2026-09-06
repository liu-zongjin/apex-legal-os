import unittest

from backend.security import is_loopback_client


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


if __name__ == "__main__":
    unittest.main()
