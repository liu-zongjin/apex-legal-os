"""Exercise test collection with inherited installation settings."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RuntimeIsolationTests(unittest.TestCase):
    def test_importing_the_app_from_tests_never_uses_inherited_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory)
            inherited = {
                "LEGAL_KB_RUNTIME_DIR": str(profile),
                "LEGAL_KB_DATA_DIR": str(profile / "data"),
                "LEGAL_KB_CONFIG_DIR": str(profile / "config"),
                "LEGAL_KB_DB_PATH": str(profile / "existing.db"),
                "LEGAL_KB_UPLOAD_DIR": str(profile / "uploads"),
                "LEGAL_KB_ARTICLE_IMAGE_DIR": str(profile / "article_images"),
                "LEGAL_KB_BACKUP_DIR": str(profile / "backups"),
                "LEGAL_KB_PRIVATE_ENV_PATH": str(profile / ".env.private"),
            }
            sentinel = profile / "existing.db"
            sentinel.write_bytes(b"must stay untouched")
            child = """
import sys
from pathlib import Path

profile = Path(sys.argv[1]).resolve()

def guard(event, args):
    if event not in {'open', 'os.mkdir', 'sqlite3.connect'} or not isinstance(args[0], str):
        return
    path = Path(args[0]).resolve()
    if path == profile or profile in path.parents:
        raise AssertionError(f'test import touched the inherited runtime: {event}')

sys.addaudithook(guard)
from tests import test_article_ai_layout
main = test_article_ai_layout.main
assert main.DB_PATH.is_file()
assert main.DB_PATH.parent == main.RUNTIME_DIR
assert main._private_environment_path() == main.RUNTIME_DIR / ".env.private"
assert main.UPLOAD_DIR.parent == main.RUNTIME_DIR
assert main.ARTICLE_IMAGE_DIR.parent == main.RUNTIME_DIR
"""
            result = subprocess.run(
                [sys.executable, "-c", child, str(profile)],
                cwd=ROOT, env={**os.environ, **inherited}, capture_output=True, text=True,
                timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(sorted(p.name for p in profile.iterdir()), ["existing.db"])
            self.assertEqual(sentinel.read_bytes(), b"must stay untouched")
