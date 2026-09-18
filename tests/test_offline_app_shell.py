"""Regression checks for the iPhone offline application shell."""

from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class OfflineAppShellTests(unittest.TestCase):
    def setUp(self):
        self.worker = (ROOT / "frontend" / "case-manager-sw.js").read_text(encoding="utf-8")
        self.page = (ROOT / "frontend" / "case-manager.html").read_text(encoding="utf-8")
        self.script = (ROOT / "frontend" / "case-manager.js").read_text(encoding="utf-8")

    def test_shell_is_split_and_immediately_has_actionable_boot_content(self):
        self.assertLess(len(self.page.encode()), 50_000)
        self.assertIn('/static/case-manager.css?v=212', self.page)
        self.assertIn('/static/case-manager.js?v=212', self.page)
        self.assertIn('id="caseManagerBoot"', self.page)
        self.assertIn('window.apexRepairOfflineShell', self.page)
        self.assertIn('}, 1500);', self.page)

    def test_indexeddb_cannot_block_startup_forever(self):
        self.assertIn('OFFLINE_DB_STARTUP_TIMEOUT_MS = 800', self.script)
        self.assertIn('req.onblocked', self.script)
        self.assertIn("kind: 'blocked'", self.script)
        self.assertIn('读取本机案件快照超时', self.script)

    def test_worker_precaches_only_the_mobile_shell(self):
        self.assertIn("const SHELL_VERSION = '212'", self.worker)
        self.assertIn("const SHELL_URL = '/case-manager'", self.worker)
        self.assertIn('/static/case-manager.css?v=212', self.worker)
        self.assertIn('/static/case-manager.js?v=212', self.worker)
        self.assertNotIn("  '/',", self.worker)
        self.assertNotIn('/static/app.js', self.worker)

    def test_navigation_is_verified_cache_first(self):
        cached_at = self.worker.index('const cached = await findVerifiedShell()')
        fetch_at = self.worker.index('fetchWithTimeout(new Request(SHELL_URL', cached_at)
        self.assertLess(cached_at, fetch_at)
        self.assertIn("response.headers.get('x-apex-shell-version') !== SHELL_VERSION", self.worker)
        self.assertIn('isValidShellDocument', self.worker)
        self.assertNotIn('navigationSafe(request)', self.worker)

    def test_install_is_staged_and_previous_version_is_retained(self):
        self.assertIn('STAGING_CACHE', self.worker)
        self.assertIn('assertValidShellResponse(path, response)', self.worker)
        self.assertIn('versions.slice(0, 2)', self.worker)
        self.assertLess(self.worker.index('assertValidShellResponse(path, response)'), self.worker.index('self.skipWaiting()'))

    def test_entry_pages_request_the_current_worker(self):
        for filename in ("index.html", "case-manager.html"):
            page = (ROOT / "frontend" / filename).read_text(encoding="utf-8")
            self.assertIn('/case-manager-sw.js?v=212', page)

    def test_shell_and_assets_are_public_but_business_apis_are_not(self):
        main = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
        public_block = re.search(r"public_paths = \{(?P<body>.*?)\n    \}", main, re.S)
        self.assertIsNotNone(public_block)
        public = public_block.group('body')
        for path in ('/case-manager', '/case-manager-sw.js', '/api/pwa/session-status',
                     '/static/case-manager.css', '/static/case-manager.js'):
            self.assertIn(f'"{path}"', public)
        self.assertNotIn('/api/case-manager/', public)

    def test_shell_response_has_version_marker_and_repair_does_not_clear_user_data(self):
        backend = (ROOT / "backend" / "case_manager.py").read_text(encoding="utf-8")
        self.assertIn('"X-APEX-Shell-Version": PWA_SHELL_VERSION', backend)
        self.assertNotIn('indexedDB.deleteDatabase', self.page)
        self.assertNotIn('localStorage.clear', self.page)

    def test_login_html_is_classified_as_unauthenticated(self):
        self.assertIn('looksLikeLoginPage', self.script)
        self.assertIn("kind: 'unauthenticated'", self.script)
        self.assertIn("redirectToCaseManagerLogin", self.script)

    def test_existing_offline_storage_contract_is_preserved(self):
        self.assertIn("OFFLINE_DB_NAME = 'legal-kb-case-manager'", self.script)
        self.assertIn("OFFLINE_STORE = 'snapshots'", self.script)
        self.assertIn("OFFLINE_KEY = 'latest'", self.script)
        self.assertIn("PENDING_CASE_OPS_KEY = 'case-manager-pending-case-ops'", self.script)
        self.assertIn("enqueueCaseOp({ action: 'upsert'", self.script)
        self.assertIn("enqueueCaseOp({ action: 'delete'", self.script)

    def test_service_worker_runtime_failure_and_cache_first_scenarios(self):
        scenarios = (
            ("service_worker_runtime_harness.js", "case-manager-sw.js", "service worker runtime scenarios passed"),
            ("case_manager_startup_runtime_harness.js", "case-manager.js", "IndexedDB startup runtime scenarios passed"),
        )
        for harness, source, expected in scenarios:
            result = subprocess.run(
                ["node", str(ROOT / "tests" / harness), str(ROOT / "frontend" / source)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(expected, result.stdout)


if __name__ == "__main__":
    unittest.main()
