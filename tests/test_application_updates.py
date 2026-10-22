import importlib.util
import plistlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('configure_local_updates', ROOT/'scripts/distribution/configure_local_updates.py')
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)


class ApplicationUpdateTests(unittest.TestCase):
    def test_shared_trust_and_architecture_config_preserves_source_identity_and_data_paths(self):
        import base64
        key = base64.b64encode(bytes(32)).decode()
        original = {
            'CFBundleIdentifier': 'com.example.source', 'CFBundleVersion': '15',
            'CFBundleShortVersionString': '1.1.2',
            'LegalKBFrontendPath': '/anonymous/workspace/frontend',
        }
        for arch in ('arm64', 'x86_64'):
            with self.subTest(arch=arch), tempfile.TemporaryDirectory() as directory:
                info_path = Path(directory)/'Info.plist'
                info_path.write_bytes(plistlib.dumps(original))
                with patch.object(config, 'public_key', return_value=key):
                    config.configure(info_path, Path(directory), arch)
                info = plistlib.loads(info_path.read_bytes())
                for name, value in original.items():
                    self.assertEqual(info[name], value)
                expected = config.public_bundle_info('1.0.0', '1', key, 'https://metrics.example.test/v1/events', arch)
                self.assertEqual(info['SUFeedURL'], expected['SUFeedURL'])
                self.assertEqual(info['SUPublicEDKey'], expected['SUPublicEDKey'])
                self.assertFalse(info['SUAutomaticallyUpdate'])
                self.assertFalse(info['SUAllowsAutomaticUpdates'])
                self.assertTrue(info['SUVerifyUpdateBeforeExtraction'])
                self.assertNotIn('StellaMetricsURL', info)

    @unittest.skipUnless(sys.platform == 'darwin' and shutil.which('xcrun'), 'requires Mac Swift toolchain')
    def test_installation_policy_fails_closed_for_source_and_unknown_shells(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            main = root/'main.swift'
            main.write_text('''import Foundation
let publicInfo: [String: Any] = ["CFBundleIdentifier": "com.stella.public.native", "LegalKBFrontendPath": ""]
assert(!UpdateInstallationPolicy.isSourceWorkspace(publicInfo))
var sourceInfo = publicInfo
sourceInfo["LegalKBFrontendPath"] = "/anonymous/workspace/frontend"
assert(UpdateInstallationPolicy.isSourceWorkspace(sourceInfo))
assert(UpdateInstallationPolicy.isSourceWorkspace(["CFBundleIdentifier": "com.example.old-local"]))
assert(UpdateInstallationPolicy.isSourceWorkspace([:]))
assert(UpdateInstallationPolicy.isSourceWorkspace(["LegalKBFrontendPath": " "]))
print("UPDATE_INSTALLATION_POLICY_OK")
''')
            binary = root/'policy-check'
            subprocess.run(['xcrun', 'swiftc', str(ROOT/'native-shell/Sources/UpdateInstallationPolicy.swift'), str(main), '-o', str(binary)], check=True, capture_output=True)
            result = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
            self.assertIn('UPDATE_INSTALLATION_POLICY_OK', result.stdout)

    def test_both_builds_wire_the_shared_native_updater_and_unconditional_menu(self):
        shell = (ROOT/'native-shell/Sources/main.swift').read_text()
        menu = shell.split('private func buildMainMenu()', 1)[1].split('// WKWebView', 1)[0]
        self.assertLess(menu.index('ApplicationUpdates.shared.addMenuItem'), menu.index('#if STELLA_PUBLIC'))
        for filename in ('native-shell/build_native_app.sh', 'scripts/build_private_preview.py'):
            source = (ROOT/filename).read_text()
            self.assertIn('Sources/ApplicationUpdates.swift', source)
            self.assertIn('Sources/UpdateInstallationPolicy.swift', source)
        public = (ROOT/'native-shell/Sources/PublicDistribution.swift').read_text()
        self.assertNotIn('SPUStandardUpdaterController', public)


if __name__ == '__main__':
    unittest.main()
