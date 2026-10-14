import shutil
import subprocess
import unittest
from pathlib import Path


class PageLifecycleRecoveryTests(unittest.TestCase):
    def test_background_foreground_and_iframe_selection(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node.js is required for the real lifecycle script harness')
        root = Path(__file__).resolve().parent.parent
        result = subprocess.run([node, 'tests/page_lifecycle_recovery.js'], cwd=root,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
