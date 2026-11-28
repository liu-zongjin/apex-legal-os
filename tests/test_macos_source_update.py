import importlib.util
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
INSPECT = ROOT / 'scripts/macos/source-update-inspect.py'


class UpdateInspectTests(unittest.TestCase):
    def test_real_app_identity_status_and_patch_export(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            repo, app, output = folder / 'repo', folder / 'Custom.app', folder / 'private-export'
            repo.mkdir()
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            (repo / 'tracked.txt').write_text('old\n')
            subprocess.run(['git', '-C', str(repo), 'add', 'tracked.txt'], check=True)
            subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Test', '-c',
                            'user.email=test@example.invalid', 'commit', '-qm', 'fixture'], check=True)
            (repo / 'tracked.txt').write_text('staged\n')
            subprocess.run(['git', '-C', str(repo), 'add', 'tracked.txt'], check=True)
            (repo / 'tracked.txt').write_text('new\n')
            (repo / 'untracked.txt').write_text('private\n')
            (app / 'Contents').mkdir(parents=True)
            (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({
                'CFBundleIdentifier': 'com.stella.source.native', 'StellaSourceRoot': str(repo)}))
            result = subprocess.run([sys.executable, str(INSPECT), '--app', str(app), '--patch-dir', str(output)],
                                    text=True, capture_output=True, check=True)
            self.assertIn(str(repo), result.stdout)
            self.assertIn('untracked.txt', result.stdout)
            self.assertIn('+new', (output / 'tracked-changes.patch').read_text())
            self.assertIn('+staged', (output / 'staged.patch').read_text())
            self.assertIn('-staged', (output / 'unstaged.patch').read_text())
            self.assertNotIn('private', (output / 'tracked-changes.patch').read_text())
            self.assertIn('untracked.txt', (output / 'status.txt').read_text())
            if os.name != 'nt':
                self.assertEqual((output / 'tracked-changes.patch').stat().st_mode & 0o777, 0o600)
            result = subprocess.run([sys.executable, str(INSPECT), '--app', str(app), '--patch-dir', str(output)],
                                    text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)

    def test_rejects_other_app(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / 'Other.app'
            (app / 'Contents').mkdir(parents=True)
            (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'other'}))
            result = subprocess.run([sys.executable, str(INSPECT), '--app', str(app)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)


class ChromiumProbeTests(unittest.TestCase):
    def test_requires_executable_and_headless_browser(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        spec = importlib.util.spec_from_file_location('source_chromium_probe', ROOT / 'scripts/macos/check_source_chromium.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        browser = MagicMock()
        browser.new_page.return_value.title.return_value = 'Stella browser check'
        chromium = SimpleNamespace(executable_path='/fake/chromium', launch=MagicMock(return_value=browser))
        context = MagicMock()
        context.__enter__.return_value = SimpleNamespace(chromium=chromium)
        fake_playwright = SimpleNamespace(sync_playwright=lambda: context)
        with patch.dict('sys.modules', {'playwright.sync_api': fake_playwright}), patch.object(module.subprocess, 'run') as run:
            self.assertEqual(module.main(), 0)
            run.assert_called_once()
            browser.close.assert_called_once()
            chromium.launch.side_effect = RuntimeError('browser missing')
            self.assertEqual(module.main(), 1)


@unittest.skipUnless(shutil.which('python3.12') and sys.platform == 'darwin', 'requires macOS and Python 3.12')
class InstallFallbackTests(unittest.TestCase):
    def test_failed_browser_install_requires_successful_browser_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / 'scripts/macos/source-install.sh'
            script.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / 'scripts/macos/source-install.sh', script)
            python = root / '.venv/bin/python'
            python.parent.mkdir(parents=True)
            (root / '.venv/.stella-source-managed').touch()
            python.write_text('''#!/bin/bash
if [[ "$1" == "-m" && "$2" == "playwright" ]]; then exit 1; fi
if [[ "$1" == *check_source_chromium.py ]]; then exit "$PROBE_STATUS"; fi
exit 0
''')
            python.chmod(0o755)
            env = dict(os.environ, STELLA_PYTHON=shutil.which('python3.12'))
            for probe, expected in [('0', 0), ('1', 1)]:
                result = subprocess.run(['bash', str(script), 'install'], env=dict(env, PROBE_STATUS=probe),
                                        text=True, capture_output=True)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                self.assertIn('正在检查', result.stderr)


if __name__ == '__main__':
    unittest.main()
