"""Exercise actual reminder functions with anonymous records across time zones."""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]

class CaseReminderDateTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js required for frontend runtime tests')
    def test_reminder_dates_and_filters_across_timezones(self):
        for zone in ('Asia/Shanghai', 'America/Los_Angeles', 'UTC'):
            with self.subTest(zone=zone):
                result = subprocess.run(['node', 'tests/case_reminder_dates_runtime.js'], cwd=ROOT,
                    env={**os.environ, 'TZ':zone}, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

if __name__ == '__main__':
    unittest.main()
