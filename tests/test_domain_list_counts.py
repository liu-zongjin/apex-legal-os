import shutil
import subprocess
import unittest
from pathlib import Path


class DomainListCountTests(unittest.TestCase):
    def test_sidebar_counts_follow_filtered_response_without_stale_overwrite(self):
        if not shutil.which("node"):
            self.skipTest("Node.js is not installed")
        result = subprocess.run(["node", "tests/domain_list_count_state.js"],
                                cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
