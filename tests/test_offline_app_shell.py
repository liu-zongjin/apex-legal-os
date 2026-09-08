"""Regression checks for the mobile offline application shell."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class OfflineAppShellTests(unittest.TestCase):
    def test_worker_precaches_current_mobile_shell_assets(self):
        worker = (ROOT / "frontend" / "case-manager-sw.js").read_text(encoding="utf-8")

        self.assertIn("legal-kb-app-shell-v200", worker)
        self.assertIn("/static/style.css?v=2026090802", worker)
        self.assertIn("/static/app.js?v=494", worker)
        self.assertIn("/static/apex-date-picker.js?v=3", worker)
        self.assertIn("/static/search-shortcut.js?v=1", worker)

    def test_versioned_assets_never_fall_back_to_an_older_query_variant(self):
        worker = (ROOT / "frontend" / "case-manager-sw.js").read_text(encoding="utf-8")

        self.assertIn("if (!fallback && !url.search)", worker)
        self.assertNotIn("cache.match(url.pathname, { ignoreSearch: true })", worker)

    def test_entry_pages_request_the_current_worker(self):
        for filename in ("index.html", "case-manager.html"):
            page = (ROOT / "frontend" / filename).read_text(encoding="utf-8")
            self.assertIn("/case-manager-sw.js?v=200", page)


if __name__ == "__main__":
    unittest.main()
