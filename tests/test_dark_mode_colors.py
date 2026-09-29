"""Static contracts for dark-mode surface and control colors across APEX pages."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class DarkModeColorContractTests(unittest.TestCase):
    def read(self, name):
        return (FRONTEND / name).read_text(encoding="utf-8")

    def test_screenshot_pages_cover_their_light_surface_regressions(self):
        interest = self.read("interest-calculator.html")
        self.assertIn("body.dark-mode .history-btn { background: #1b2432", interest)
        self.assertIn("body.dark-mode .tool-tab.active { background: #222c3d", interest)

        personal = self.read("personal-center.html")
        self.assertIn("html.dark-mode .tabs, body.dark-mode .tabs", personal)
        self.assertIn("html.dark-mode .btn, body.dark-mode .btn", personal)
        self.assertIn("html.dark-mode .pc-quick-chip, body.dark-mode .pc-quick-chip", personal)

        cases = self.read("case-manager.css")
        self.assertIn("html.dark-mode .court-online-list, body.dark-mode .court-online-list", cases)
        self.assertIn("html.dark-mode .court-login-float, body.dark-mode .court-login-float", cases)
        self.assertIn("html.dark-mode .court-kind-badge.kind-message", cases)

    def test_legacy_pages_load_shared_system_theme_and_dark_surfaces(self):
        for name in ("automation-filing.html", "mingsi-meeting.html", "scanner-inbox.html", "oa-system.html"):
            source = self.read(name)
            self.assertIn('/static/color-theme.js?v=7', source, name)
            self.assertIn("html.dark-mode", source, name)
            self.assertIn("color-scheme: dark", source, name)

    def test_standalone_management_pages_follow_system_theme(self):
        for name in ("ai-api-manager.html", "mcp-manager.html", "skill-manager.html"):
            source = self.read(name)
            self.assertIn("prefers-color-scheme: dark", source, name)
            self.assertIn("systemThemeMedia", source, name)
            self.assertIn("classList.toggle('dark'", source, name)

    def test_imported_article_inline_colors_are_remapped_in_dark_mode(self):
        source = self.read("style.css")
        self.assertIn(".tab-article-detail .tab-article-body-text :is(", source)
        self.assertIn('[style*="color: rgb(0, 0, 0)" i]', source)
        self.assertIn("color: var(--reader-text, var(--text)) !important;", source)
        self.assertIn('[style*="background: rgb(0, 255, 0)" i]', source)
        self.assertIn("background: rgba(245, 158, 11, .22) !important;", source)
        self.assertIn("body.dark-mode .detail-body :is(", source)


if __name__ == "__main__":
    unittest.main()
