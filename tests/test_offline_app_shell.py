"""Regression checks for the mobile offline application shell."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class OfflineAppShellTests(unittest.TestCase):
    def test_worker_precaches_current_mobile_shell_assets(self):
        worker = (ROOT / "frontend" / "case-manager-sw.js").read_text(encoding="utf-8")
        index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

        self.assertIn("legal-kb-app-shell-v211", worker)
        for pattern in (r'/static/style\.css\?v=\d+', r'/static/app\.js\?v=\d+'):
            asset = re.search(pattern, index)
            self.assertIsNotNone(asset)
            self.assertIn(asset.group(0), worker)
        self.assertIn("/static/apex-date-picker.js?v=3", worker)
        self.assertIn("/static/search-shortcut.js?v=1", worker)

    def test_versioned_assets_never_fall_back_to_an_older_query_variant(self):
        worker = (ROOT / "frontend" / "case-manager-sw.js").read_text(encoding="utf-8")

        self.assertIn("if (!fallback && !url.search)", worker)
        self.assertNotIn("cache.match(url.pathname, { ignoreSearch: true })", worker)

    def test_entry_pages_request_the_current_worker(self):
        worker = (ROOT / "frontend" / "case-manager-sw.js").read_text(encoding="utf-8")
        cache_version = re.search(r"legal-kb-app-shell-v(\d+)", worker)
        self.assertIsNotNone(cache_version)
        worker_url = f"/case-manager-sw.js?v={cache_version.group(1)}"
        for filename in ("index.html", "case-manager.html"):
            page = (ROOT / "frontend" / filename).read_text(encoding="utf-8")
            self.assertIn(worker_url, page)


if __name__ == "__main__":
    unittest.main()
