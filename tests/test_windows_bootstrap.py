"""Installer invariants use only disposable keys, fake components and temporary profiles."""
import base64
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


engine = module('windows_bootstrap', 'scripts/windows/bootstrap_engine.py')
catalog = module('windows_catalog', 'scripts/windows/make_catalog.py')
try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    HAVE_CRYPTO = True
except ImportError:
    HAVE_CRYPTO = False


class WindowsSupportTests(unittest.TestCase):
    def test_windows_10_and_11_workstations(self):
        for build in (17763, 18362, 18363, 19041, 19042, 19043, 19044, 19045, 22000, 22631, 26100):
            with self.subTest(build=build):
                version = SimpleNamespace(major=10, build=build, product_type=1)
                self.assertTrue(engine.supported_windows('x86_64', version))

    def test_older_systems_server_and_emulated_architectures_are_rejected(self):
        for major, build, product, arch in ((10, 17762, 1, 'x86_64'),
                (6, 19044, 1, 'x86_64'), (10, 20348, 3, 'x86_64'),
                (10, 19044, 2, 'x86_64'), (10, 19044, 1, 'arm64'),
                (10, 19044, 1, 'x86'), (10, 19044, 1, 'unknown')):
            with self.subTest(major=major, build=build, product=product, arch=arch):
                self.assertFalse(engine.supported_windows(arch,
                    SimpleNamespace(major=major, build=build, product_type=product)))


class PathTests(unittest.TestCase):
    def test_windows_path_attacks(self):
        for name in ('../escape.exe', '/root', 'C:/file', 'a\\b', 'a/../b', 'a//b',
                     'CON.txt', 'aux', 'x/NUL', 'file.', 'file ', 'a:stream', 'a?b'):
            with self.subTest(name=name), self.assertRaises(engine.InstallError):
                engine.safe_path(name)
        self.assertEqual(engine.safe_path('材料/normal file.txt').as_posix(), '材料/normal file.txt')

    def test_parallel_lifecycle_lock_is_exclusive(self):
        with tempfile.TemporaryDirectory() as d:
            with engine.exclusive_lock(Path(d) / 'lock'):
                with self.assertRaises(engine.InstallError):
                    with engine.exclusive_lock(Path(d) / 'lock'):
                        pass


@unittest.skipUnless(HAVE_CRYPTO, 'Install scripts/windows/requirements-bootstrap.txt for signed installer tests')
class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.assets = self.root / 'assets'
        self.assets.mkdir()
        self.key = Ed25519PrivateKey.generate()
        pub = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.events = []
        self.installer = engine.Installer(self.root / 'installed', {
            'public_key': base64.b64encode(pub).decode(), 'allowed_hosts': ['download.example.test'],
            'catalog_url': 'https://download.example.test/catalog.json'}, lambda event, **kw: self.events.append((event, kw)))
        # Fake executable fixtures must never execute. Real binaries are checked in Windows CI.
        self.health = patch.object(self.installer, 'health_check')
        self.health_mock = self.health.start()
        self.addCleanup(self.health.stop)
        entries = {'server': 'StellaServer.exe', 'browser': 'chrome.exe', 'ocr': 'tesseract.exe', 'converter': 'program/soffice.exe'}
        components = []
        for name, entry in entries.items():
            source = self.root / name
            (source / entry).parent.mkdir(parents=True, exist_ok=True)
            (source / entry).write_bytes(b'anonymous executable fixture ' + name.encode())
            components.append(catalog.pack_component(name, source, self.assets, 'https://download.example.test'))
        self.data = {'schema': 1, 'target': 'windows-x86_64', 'version': '0.1.0', 'build': 1,
                     'expires_at': int(time.time()) + 3600, 'components': components}
        self.envelope = catalog.sign(self.data, self.key)

    def test_clean_install_reuses_intact_components_and_preserves_data(self):
        before = self.installer.plan(self.data)
        self.assertGreater(before['download_bytes'], 0)
        self.installer.install(self.envelope, self.assets)
        user = self.installer.root / 'userdata/uploads'
        user.mkdir(parents=True)
        (user / 'case.txt').write_text('anonymous recipient-owned material')
        after = self.installer.plan(self.data)
        self.assertEqual(after['download_bytes'], 0)
        self.installer.install(self.envelope, self.assets)
        self.assertEqual((user / 'case.txt').read_text(), 'anonymous recipient-owned material')
        self.assertTrue(all(self.installer.intact(c) for c in self.data['components']))

    def test_invalid_signature_cannot_create_installation(self):
        envelope = copy.deepcopy(self.envelope)
        envelope['payload'] = base64.b64encode(json.dumps({**self.data, 'build': 9}).encode()).decode()
        with self.assertRaises(engine.InstallError):
            self.installer.install(envelope, self.assets)
        self.assertFalse(self.installer.root.exists())

    def test_corrupt_payload_does_not_switch_existing_version(self):
        self.installer.install(self.envelope, self.assets)
        pointer = (self.installer.root / 'active.json').read_bytes()
        new_data = copy.deepcopy(self.data)
        new_data['build'] = 2
        # A signed expected archive hash that does not match the available asset.
        new_data['components'][0]['sha256'] = '0' * 64
        with self.assertRaises(engine.InstallError):
            self.installer.install(catalog.sign(new_data, self.key), self.assets)
        self.assertEqual((self.installer.root / 'active.json').read_bytes(), pointer)

    def test_failed_final_component_keeps_active_pointer(self):
        self.installer.install(self.envelope, self.assets)
        pointer = (self.installer.root / 'active.json').read_bytes()
        data = copy.deepcopy(self.data)
        data['build'] = 2
        with patch.object(self.installer, 'intact', return_value=False), patch.object(self.installer, 'extract', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                self.installer.install(catalog.sign(data, self.key), self.assets)
        self.assertEqual((self.installer.root / 'active.json').read_bytes(), pointer)

    def test_failed_runtime_self_test_cannot_activate_an_update(self):
        self.installer.install(self.envelope, self.assets)
        pointer = (self.installer.root / 'active.json').read_bytes()
        self.health_mock.side_effect = engine.InstallError('fixture component failure')
        with self.assertRaises(engine.InstallError):
            self.installer.install(catalog.sign({**self.data,'build':2},self.key), self.assets)
        self.assertEqual((self.installer.root / 'active.json').read_bytes(),pointer)

    def test_tampered_installed_file_requires_repair(self):
        self.installer.install(self.envelope, self.assets)
        c = self.data['components'][0]
        (self.installer.component_dir(c) / 'StellaServer.exe').write_text('corrupt')
        self.assertFalse(self.installer.intact(c))
        self.installer.install(self.envelope, self.assets)
        self.assertTrue(self.installer.intact(c))

    def test_downgrade_and_redefined_build_are_rejected(self):
        self.installer.install(self.envelope, self.assets)
        for changes in ({'version': '0.2.0'}, {'build': 0}):
            with self.assertRaises(engine.InstallError):
                self.installer.install(catalog.sign({**self.data, **changes}, self.key), self.assets)
        newer = {**self.data, 'build': 2}
        self.installer.install(catalog.sign(newer, self.key), self.assets)
        with self.assertRaises(engine.InstallError):
            self.installer.install(self.envelope, self.assets)

    def test_expiry_blocks_install_but_not_existing_offline_launch_metadata(self):
        expired = catalog.sign({**self.data, 'expires_at': 1}, self.key)
        with self.assertRaises(engine.InstallError):
            self.installer.verify(expired)
        self.assertEqual(self.installer.verify(expired, installing=False)['build'], 1)

    def test_download_host_policy_applies_to_redirects(self):
        class Response:
            status_code = 302
            headers = {'Location': 'http://download.example.test/server.zip'}
            def close(self): pass
        with patch.object(self.installer.session, 'get', return_value=Response()) as get:
            with self.assertRaises(engine.InstallError):
                self.installer.get('https://download.example.test/server.zip')
            self.assertEqual(get.call_count, 1)

    def test_resume_then_verify_hash(self):
        c = self.data['components'][0]
        raw = (self.assets / 'server.zip').read_bytes()
        cache = self.installer.root / 'cache'
        cache.mkdir(parents=True)
        (cache / (c['sha256'] + '.part')).write_bytes(raw[:10])
        class Response:
            status_code = 206
            headers = {'Content-Range': f'bytes 10-{len(raw)-1}/{len(raw)}'}
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def raise_for_status(self): pass
            def iter_content(self, size): yield raw[10:]
        with patch.object(self.installer, 'get', return_value=Response()) as get:
            target = self.installer.download(c, None)
        self.assertEqual(target.read_bytes(), raw)
        self.assertEqual(get.call_args.args[1]['Range'], 'bytes=10-')

    def test_signed_zip_cannot_escape_target_or_supply_extra_files(self):
        c = self.data['components'][0]
        for name in ('../escape.exe', 'unexpected.exe'):
            archive = self.root / 'bad.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr(name, b'bad')
            with self.assertRaises(engine.InstallError):
                self.installer.extract(c, archive)
            self.assertFalse((self.root / 'escape.exe').exists())

    def test_unsigned_missing_or_wrong_architecture_component_is_rejected(self):
        for change in ({'target': 'windows-arm64'}, {'components': self.data['components'][:3]}):
            with self.assertRaises(engine.InstallError):
                self.installer.verify(catalog.sign({**self.data, **change}, self.key))


class PlatformTests(unittest.TestCase):
    def test_mac_features_are_retained_windows_scope_is_explicit(self):
        from backend import platform_capabilities as cap
        with patch.object(cap.sys, 'platform', 'darwin'):
            self.assertTrue(cap.enabled('icloud_calendar'))
            self.assertEqual(cap.snapshot()['disabled'], [])
        with patch.object(cap.sys, 'platform', 'win32'):
            for feature in ('icloud_calendar', 'icloud_contacts', 'quark', 'feishu', 'recording', 'biometric', 'finder_tags', 'messages_sync'):
                self.assertFalse(cap.enabled(feature))
            self.assertTrue(cap.enabled('case_manager'))
            self.assertEqual(cap.snapshot()['judicial_message_input'], 'manual')


if __name__ == '__main__':
    unittest.main()
