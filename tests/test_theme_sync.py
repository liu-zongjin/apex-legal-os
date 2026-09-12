"""Static contracts for the system appearance theme synchronisation."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class ThemeSyncContractTests(unittest.TestCase):
    def test_shared_theme_script_reads_and_listens_to_system_appearance(self):
        source = (FRONTEND / "color-theme.js").read_text(encoding="utf-8")

        self.assertIn("(prefers-color-scheme: dark)", source)
        self.assertIn("systemThemeMedia.addEventListener('change'", source)
        self.assertIn("systemThemeMedia.addListener", source)
        self.assertIn("applyMode(systemPrefersDark())", source)

    def test_main_app_reads_system_appearance_and_reacts_to_changes(self):
        source = (FRONTEND / "app.js").read_text(encoding="utf-8")

        self.assertIn("const APEX_SYSTEM_THEME_QUERY = '(prefers-color-scheme: dark)'", source)
        self.assertIn("state.darkMode = getSystemDarkMode()", source)
        self.assertIn("const syncSystemTheme = event =>", source)
        self.assertIn("systemThemeMedia.addEventListener('change', syncSystemTheme)", source)

    def test_offline_shell_precaches_the_updated_theme_assets(self):
        worker = (FRONTEND / "case-manager-sw.js").read_text(encoding="utf-8")
        index = (FRONTEND / "index.html").read_text(encoding="utf-8")

        self.assertIn("/static/app.js?v=500", index)
        self.assertIn("/static/app.js?v=500", worker)
        self.assertIn("/static/color-theme.js?v=6", worker)

    def test_entry_pages_do_not_use_saved_theme_for_initial_mode(self):
        initial_sources = [
            FRONTEND / "index.html",
            FRONTEND / "case-manager.html",
            FRONTEND / "case-files.html",
            FRONTEND / "court-directory.html",
            FRONTEND / "legal-knowledge.html",
            FRONTEND / "interest-calculator.html",
        ]

        for path in initial_sources:
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("localStorage.getItem('theme') === 'dark'", source, path.name)


if __name__ == "__main__":
    unittest.main()
