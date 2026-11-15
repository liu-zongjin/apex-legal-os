"""Run asynchronous case/editor interactions without a live server or data."""
from pathlib import Path
import shutil
import subprocess
import unittest


class CaseManagerAsyncUITests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js required')
    def test_async_case_and_reminder_interactions(self):
        result = subprocess.run(['node', 'tests/case_manager_async_ui.js'],
                                cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count('PASS '), 9, result.stdout + result.stderr)
