"""Regression checks for the iPhone offline application shell."""

from pathlib import Path
import re
import subprocess
import unittest
from backend.pwa import PWA_SHELL_VERSION


ROOT = Path(__file__).resolve().parents[1]


class OfflineAppShellTests(unittest.TestCase):
    def setUp(self):
        self.worker = (ROOT / "frontend" / "case-manager-sw.js").read_text(encoding="utf-8")
        self.page = (ROOT / "frontend" / "case-manager.html").read_text(encoding="utf-8")
        self.script = (ROOT / "frontend" / "case-manager.js").read_text(encoding="utf-8")

    def test_shell_is_split_and_immediately_has_actionable_boot_content(self):
        self.assertLess(len(self.page.encode()), 50_000)
        self.assertIn(f'/static/case-manager.css?v={PWA_SHELL_VERSION}', self.page)
        self.assertIn(f'/static/case-manager.js?v={PWA_SHELL_VERSION}', self.page)
        self.assertIn('id="caseManagerBoot"', self.page)
        self.assertIn('window.apexRepairOfflineShell', self.page)
        self.assertIn('}, 1500);', self.page)

    def test_indexeddb_cannot_block_startup_forever(self):
        self.assertIn('OFFLINE_DB_STARTUP_TIMEOUT_MS = 800', self.script)
        self.assertIn('req.onblocked', self.script)
        self.assertIn("kind: 'blocked'", self.script)
        self.assertIn('读取本机案件快照超时', self.script)

    def test_worker_caches_main_home_without_caching_login(self):
        self.assertIn(f"const SHELL_VERSION = '{PWA_SHELL_VERSION}'", self.worker)
        self.assertIn("const SHELL_URL = '/case-manager'", self.worker)
        self.assertIn(f'/static/case-manager.css?v={PWA_SHELL_VERSION}', self.worker)
        self.assertIn(f'/static/case-manager.js?v={PWA_SHELL_VERSION}', self.worker)
        self.assertNotIn("  '/',", self.worker)
        self.assertIn('/static/app-bootstrap.js?v=2026101601', self.worker)
        self.assertIn('/static/app-ai-lazy.js?v=2026101601', self.worker)
        self.assertIn('/static/apex-feature-loader.js?v=2026101601', self.worker)
        self.assertIn('if (!isValidShellDocument(response))', self.worker)
        self.assertIn('HOME_READY_URL', self.worker)
        self.assertIn("event.request.destination === 'document'", self.worker)
        self.assertIn('/?workspace=cases', self.worker)
        self.assertNotIn('mobile-home-link', self.page)

    def test_standalone_entry_uses_original_main_host_even_without_safari_cache(self):
        manifest = (ROOT / 'frontend/static/site.webmanifest').read_text()
        self.assertIn('"start_url": "/"', manifest)
        self.assertIn('"id": "/case-manager"', manifest)
        self.assertIn('navigator.standalone === true', self.page)
        self.assertIn('window.parent === window', self.page)
        self.assertIn("window.location.replace('/?workspace=cases')", self.page)
        self.assertIn("const HOME_SHELL_URL = '/app-shell'", self.worker)
        self.assertIn('await prepareHome();', self.worker)
        self.assertNotIn('await prepareHome().catch', self.worker)
        self.assertIn('window.parent.location.assign(target)', self.script)

    def test_navigation_is_verified_cache_first(self):
        cached_at = self.worker.index('const cached = await findVerifiedShell()')
        fetch_at = self.worker.index('fetchWithTimeout(new Request(SHELL_URL', cached_at)
        self.assertLess(cached_at, fetch_at)
        self.assertIn("response.headers.get('x-apex-shell-version') !== SHELL_VERSION", self.worker)
        self.assertIn('isValidShellDocument', self.worker)
        self.assertNotIn('navigationSafe(request)', self.worker)

    def test_series_table_sticky_layers_keep_headers_above_frozen_rows(self):
        styles = (ROOT / "frontend" / "case-manager.css").read_text(encoding="utf-8")
        self.assertIn('.series-table th { position:sticky; top:var(--series-table-sticky-top,0px); z-index:10;', styles)
        self.assertIn('.series-table thead .series-actions-cell { z-index:30; }', styles)
        self.assertIn('header?15:5', self.script)
        self.assertIn("columnIndex==='actions'?8", self.script)
        self.assertIn('seriesFrozenRowStyle(rowIndex,columnIndex)', self.script)
        self.assertIn('syncSeriesTableStickyOffset()', self.script)
        self.assertIn('--series-table-sticky-top', self.script)
        self.assertIn('seriesSelectionAutoScrollStep', self.script)
        self.assertIn('seriesSelectionCellAtPoint', self.script)
        self.assertIn('seriesSelectionScrollContainers', self.script)

    def test_series_cell_text_and_cell_highlights_are_separate(self):
        styles = (ROOT / "frontend" / "case-manager.css").read_text(encoding="utf-8")
        self.assertIn("applySeriesContextTextFormat('highlight')", self.script)
        self.assertIn('文字高亮', self.script)
        self.assertIn("applySeriesContextCellBackground('yellow')", self.script)
        self.assertIn('cell_background', self.script)
        self.assertIn('.series-table td.series-cell-background-yellow', styles)
        self.assertIn("type:'cell_formats'", self.script)
        self.assertIn('saveSeriesCellFormatBatch', self.script)

    def test_series_cells_support_vertical_alignment(self):
        styles = (ROOT / "frontend" / "case-manager.css").read_text(encoding="utf-8")
        self.assertIn("applySeriesContextVerticalAlign('top')", self.script)
        self.assertIn("applySeriesContextVerticalAlign('center')", self.script)
        self.assertIn("applySeriesContextVerticalAlign('bottom')", self.script)
        self.assertIn("vertical_align", self.script)
        self.assertIn("seriesCellVerticalAlignStyle", self.script)
        self.assertIn("垂直对齐", self.script)
        self.assertIn("series-context-menu-label", styles)

    def test_series_public_contact_editor_and_view_share_the_same_fields(self):
        self.assertIn('function seriesPublicContactData', self.script)
        self.assertIn('function collectSeriesPublicContactFields', self.script)
        self.assertIn('contactEditorHtml(contactData,{includeDisplayColumns:false,publicEditor:true})', self.script)
        self.assertIn('body.profile.series_memo=contacts.memo', self.script)

    def test_install_is_staged_and_previous_version_is_retained(self):
        self.assertIn('STAGING_CACHE', self.worker)
        self.assertIn('assertValidShellResponse(path, response)', self.worker)
        self.assertIn('versions.slice(0, 2)', self.worker)
        self.assertLess(self.worker.index('assertValidShellResponse(path, response)'), self.worker.index('self.skipWaiting()'))

    def test_entry_pages_request_the_current_worker(self):
        for filename in ("index.html", "case-manager.html"):
            page = (ROOT / "frontend" / filename).read_text(encoding="utf-8")
            self.assertIn(f'/case-manager-sw.js?v={PWA_SHELL_VERSION}', page)

    def test_shell_and_assets_are_public_but_business_apis_are_not(self):
        main = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
        public_block = re.search(r"public_paths = \{(?P<body>.*?)\n    \}", main, re.S)
        self.assertIsNotNone(public_block)
        public = public_block.group('body')
        for path in ('/case-manager', '/case-manager-sw.js', '/api/pwa/session-status',
                     '/static/case-manager.css', '/static/case-manager.js',
                     '/static/apex-case-picker.css', '/static/apex-case-picker.js'):
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
