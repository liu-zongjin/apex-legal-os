from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ResourceEfficiencyContracts(unittest.TestCase):
    def test_normal_source_start_does_not_enable_reload_by_default(self):
        source = (ROOT / "start.py").read_text(encoding="utf-8")
        self.assertIn("LEGAL_KB_DEV_RELOAD", source)
        self.assertNotIn("'--reload',\n        '--reload-dir'", source)

    def test_legacy_feishu_listener_is_configuration_gated(self):
        source = (ROOT / "start.py").read_text(encoding="utf-8")
        self.assertIn("FEISHU_LISTENER_ENABLED", source)
        self.assertIn("feishu_config.py", source)
        self.assertIn("subprocess.DEVNULL", source)

    def test_smart_hibernation_starts_with_low_risk_pages_only(self):
        source = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
        block = source.split("const HIBERNATION_ELIGIBLE_TAB_TYPES", 1)[1].split("]);", 1)[0]
        for allowed in ("KB_STATS", "RECOMMENDATIONS", "DOWNLOAD_CENTER", "USER_MANUAL"):
            self.assertIn(f"TAB_TYPES.{allowed}", block)
        for protected in ("CASE_MANAGER", "RECORDING", "AUTOMATED_FILING", "DOCUMENT_BUNDLE"):
            self.assertNotIn(f"TAB_TYPES.{protected}", block)

    def test_connectivity_monitor_uses_adaptive_timeout_not_five_second_interval(self):
        source = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
        block = source.split("function startConnectivityMonitor()", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("setTimeout", block)
        self.assertIn("300000", block)
        self.assertNotIn("setInterval", block)

    def test_mcp_refresh_obeys_parent_page_lifecycle(self):
        source = (ROOT / "frontend" / "mcp-manager.html").read_text(encoding="utf-8")
        self.assertIn("apex-page-lifecycle.js", source)
        self.assertIn("ApexLifecycle.interval", source)


if __name__ == "__main__":
    unittest.main()
