import shutil
import subprocess
import unittest
from pathlib import Path


class CourtReadingCountsTests(unittest.TestCase):
    def test_initial_entry_and_filtered_navigation(self):
        if not shutil.which('node'):
            self.skipTest('Node.js is not installed')
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(['node', 'tests/court_reading_counts.js'], cwd=root,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
