"""Static contracts for the system appearance theme synchronisation."""

from pathlib import Path
import subprocess
import unittest
from backend.pwa import PWA_SHELL_VERSION


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class ThemeSyncContractTests(unittest.TestCase):
    def test_shared_theme_script_reads_and_listens_to_system_appearance(self):
        source = (FRONTEND / "color-theme.js").read_text(encoding="utf-8")

        self.assertIn("(prefers-color-scheme: dark)", source)
        self.assertIn("systemThemeMedia.addEventListener('change'", source)
        self.assertIn("systemThemeMedia.addListener", source)
        self.assertIn("applyMode(currentDarkMode())", source)
        self.assertIn("if (!savedMode()) applyMode(!!event.matches)", source)

    def test_main_app_reads_system_appearance_and_reacts_to_changes(self):
        source = (FRONTEND / "app.js").read_text(encoding="utf-8")

        self.assertIn("const APEX_SYSTEM_THEME_QUERY = '(prefers-color-scheme: dark)'", source)
        self.assertIn("state.darkMode = getPreferredDarkMode()", source)
        self.assertIn("const syncSystemTheme = event =>", source)
        self.assertIn("systemThemeMedia.addEventListener('change', syncSystemTheme)", source)
        self.assertIn("saveTheme(false)", source)

    def test_offline_shell_precaches_the_updated_theme_assets(self):
        worker = (FRONTEND / "case-manager-sw.js").read_text(encoding="utf-8")

        # The mobile worker deliberately excludes the desktop home bundle: a
        # large unrelated asset must not be able to break case-manager install.
        self.assertIn('/static/app.js?v=529', worker)
        self.assertIn(f'/static/case-manager.js?v={PWA_SHELL_VERSION}', worker)
        self.assertIn("/static/color-theme.js?v=7", worker)

    def test_entry_pages_respect_saved_theme_for_initial_mode(self):
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
            self.assertTrue("localStorage.getItem('theme')" in source or 'color-theme.js?v=7' in source, path.name)

    def test_shared_theme_follows_system_until_user_picks_a_mode(self):
        script = r'''
const fs = require('fs'), vm = require('vm');
let saved = null, systemDark = true;
const events = {}, media = {matches: true, addEventListener: (_, callback) => events.system = callback};
const root = {classList: {values: new Set(), toggle(name, on) {on ? this.values.add(name) : this.values.delete(name);}}, dataset: {}};
const context = {
  document: {documentElement: root, body: null, readyState: 'complete', querySelector: () => null, getElementById: () => null},
  localStorage: {getItem: () => saved}, location: {pathname: '/'},
  matchMedia: () => media, addEventListener: (name, callback) => events[name] = callback,
  BroadcastChannel: class {addEventListener() {}},
};
context.window = context;
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), context);
const dark = () => root.classList.values.has('dark-mode');
if (!dark()) throw Error('system dark was not applied');
saved = 'light'; events.storage({key: 'theme', newValue: 'light'});
if (dark()) throw Error('explicit light was not applied');
events.system({matches: true});
if (dark()) throw Error('system change overrode explicit light');
saved = 'dark'; events.storage({key: 'theme', newValue: 'dark'});
if (!dark()) throw Error('explicit dark was not applied');
saved = null; systemDark = false; media.matches = false;
events.storage({key: 'theme', newValue: null});
if (dark()) throw Error('clearing preference did not return to system light');
'''
        subprocess.run(['node', '-e', script, str(FRONTEND / 'color-theme.js')], check=True)


if __name__ == "__main__":
    unittest.main()
