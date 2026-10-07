import shutil
import subprocess
import unittest
from pathlib import Path


class SidebarDirectoryRegressions(unittest.TestCase):
    def test_real_directory_state_functions(self):
        if not shutil.which("node"):
            self.skipTest("Node.js is not installed")
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(["node", "tests/sidebar_directory_state.js"], cwd=root,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
