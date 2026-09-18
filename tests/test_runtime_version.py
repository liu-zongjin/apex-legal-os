import tempfile
import unittest
from pathlib import Path

from backend.runtime_version import source_fingerprint, source_status, watched_source_files


class RuntimeVersionTests(unittest.TestCase):
    def test_source_fingerprint_changes_for_code_but_ignores_runtime_data(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "backend").mkdir()
            (base / "uploads").mkdir()
            (base / "backend" / "court_online_service" / "browser-profile").mkdir(parents=True)
            code = base / "backend" / "example.py"
            runtime_data = base / "uploads" / "runtime.py"
            browser_data = base / "backend" / "court_online_service" / "browser-profile" / "metadata.json"
            code.write_text("VALUE = 1\n", encoding="utf-8")
            runtime_data.write_text("not source\n", encoding="utf-8")
            browser_data.write_text("runtime metadata\n", encoding="utf-8")

            first = source_fingerprint(base)
            self.assertIn(code.resolve(), watched_source_files(base))
            self.assertNotIn(runtime_data.resolve(), watched_source_files(base))
            self.assertNotIn(browser_data.resolve(), watched_source_files(base))

            code.write_text("VALUE = 2\n", encoding="utf-8")
            self.assertNotEqual(first, source_fingerprint(base))

    def test_source_status_rejects_stale_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "backend").mkdir()
            (base / "backend" / "example.py").write_text("VALUE = 1\n", encoding="utf-8")
            current = source_fingerprint(base)

            self.assertEqual(source_status(base, current)["source_status"], "current")
            stale = source_status(base, "old-version")
            self.assertEqual(stale["source_status"], "stale")
            self.assertTrue(stale["restart_required"])


if __name__ == "__main__":
    unittest.main()
