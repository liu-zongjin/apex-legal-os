from pathlib import Path
import unittest


class NativeShellContractTests(unittest.TestCase):
    def test_native_shell_recovers_webkit_content_process(self):
        source = (Path(__file__).parents[1] / "native-shell" / "Sources" / "main.swift").read_text()
        self.assertIn("webViewWebContentProcessDidTerminate", source)
        self.assertIn("webContentRecoveryTimes.count <= 3", source)
        self.assertIn("loadFreshApplicationDocument", source)


if __name__ == "__main__":
    unittest.main()
