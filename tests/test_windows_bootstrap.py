"""Installer invariants use only disposable keys, fake components and temporary profiles."""
import base64
import copy
import importlib.util
import io
import json
import os
import shutil
from pathlib import Path
import tempfile
import time
import unittest
from types import SimpleNamespace
import threading
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
    def test_office_console_launcher_is_preferred_with_gui_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            component = Path(directory)
            (component / 'program').mkdir()
            self.assertEqual(engine.office_executable(component), component / 'program/soffice.exe')
            (component / 'program/soffice.com').touch()
            self.assertEqual(engine.office_executable(component), component / 'program/soffice.com')

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


class StartupTests(unittest.TestCase):
    def test_exited_service_does_not_accept_stale_ready_marker(self):
        child = SimpleNamespace(poll=lambda: 7)
        with tempfile.TemporaryDirectory() as directory:
            ready = Path(directory) / 'ready'
            ready.touch()
            with self.assertRaisesRegex(engine.InstallError, '退出码 7'):
                engine.wait_for_server(child, ready, threading.Event(), lambda *a, **kw: None)

    def test_wait_reports_elapsed_time_and_timeout_without_terminating_service(self):
        events = []
        child = SimpleNamespace(poll=lambda: None)
        stop = SimpleNamespace(is_set=lambda: False, wait=lambda seconds: None)
        with tempfile.TemporaryDirectory() as directory, patch.object(engine.time, 'monotonic', side_effect=[0, 0, 2, 120]):
            with self.assertRaisesRegex(engine.InstallError, 'server.log'):
                engine.wait_for_server(child, Path(directory) / 'ready', stop,
                    lambda event, **payload: events.append((event, payload)))
        self.assertEqual([p['elapsed_seconds'] for _, p in events], [0, 2])

    def test_ready_service_returns_without_waiting(self):
        with tempfile.TemporaryDirectory() as directory:
            ready = Path(directory) / 'ready'
            ready.touch()
            engine.wait_for_server(SimpleNamespace(poll=lambda: None), ready, threading.Event(),
                                   lambda *a, **kw: self.fail('already ready'))


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

    def test_startup_failure_is_reported_before_waiting_for_safe_shutdown(self):
        self.installer.install(self.envelope, self.assets)
        def finish(**kwargs):
            failures = [p for event, p in self.events if event == 'launch_failed']
            self.assertEqual(len(failures), 1)
            self.assertTrue(failures[0]['cleanup_pending'])
            self.assertIn('server.log', failures[0]['message'])
        child = SimpleNamespace(poll=lambda: None, wait=finish)
        with patch.object(self.installer, 'intact', side_effect=AssertionError('full scan on launch')), \
                patch.object(engine.subprocess, 'Popen', return_value=child), \
                patch.object(engine, 'wait_for_server', side_effect=engine.InstallError('请查看 server.log')), \
                patch.object(engine.sys, 'stdin', io.StringIO('')):
            with self.assertRaisesRegex(engine.InstallError, 'server.log'):
                self.installer.launch()
        self.assertFalse(list((self.installer.root / 'userdata').glob('stop-*')))

    def test_launch_skips_full_scan_but_rejects_missing_entrypoint(self):
        self.installer.install(self.envelope, self.assets)
        server = next(c for c in self.data['components'] if c['id'] == 'server')
        (self.installer.component_dir(server) / 'StellaServer.exe').unlink()
        with patch.object(self.installer, 'intact', side_effect=AssertionError('full scan on launch')):
            with self.assertRaisesRegex(engine.InstallError, '修复'):
                self.installer.launch()

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

    def response(self, raw, status=200, headers=None):
        class Response:
            status_code = status
            def __init__(self): self.headers = headers or {}
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def raise_for_status(self): pass
            def iter_content(self, size): yield raw
        return Response()

    def test_online_hash_is_streamed_without_duplicate_archive_reads(self):
        c = self.data['components'][0]
        raw = (self.assets / 'server.zip').read_bytes()
        with patch.object(self.installer, 'get', return_value=self.response(raw)), patch.object(engine, 'digest', side_effect=AssertionError('duplicate disk read')):
            target = self.installer.download(c, None)
        self.assertEqual(target.read_bytes(), raw)
        self.assertTrue(any(event == 'download_complete' for event, _ in self.events))

    def test_extraction_hashes_stream_and_rejects_wrong_file_hash(self):
        c = copy.deepcopy(self.data['components'][0])
        with patch.object(engine, 'digest', side_effect=AssertionError('duplicate extraction read')):
            self.installer.extract(c, self.assets / 'server.zip')
        c['files']['StellaServer.exe'] = '0' * 64
        with self.assertRaises(engine.InstallError):
            self.installer.extract(c, self.assets / 'server.zip')

    def test_post_health_disk_tampering_cannot_activate(self):
        def tamper(data):
            c = data['components'][0]
            (self.installer.component_dir(c) / 'StellaServer.exe').write_bytes(b'changed during self test')
        self.health_mock.side_effect = tamper
        with self.assertRaises(engine.InstallError):
            self.installer.install(self.envelope, self.assets)
        self.assertFalse((self.installer.root / 'active.json').exists())

    def test_reused_components_checked_once_before_and_once_after_health(self):
        self.installer.install(self.envelope, self.assets)
        with patch.object(self.installer, 'intact', wraps=self.installer.intact) as check:
            self.installer.install(self.envelope, self.assets)
        self.assertEqual(check.call_count, 2 * len(self.data['components']))

    def test_signed_mirror_is_allowlisted_and_resumes_interrupted_source(self):
        c = copy.deepcopy(self.data['components'][0])
        c['mirrors'] = ['https://mirror.example.test/server.zip']
        self.installer.config['allowed_hosts'].append('mirror.example.test')
        self.installer.verify(catalog.sign({**self.data, 'components': [c, *self.data['components'][1:]]}, self.key))
        raw = (self.assets / 'server.zip').read_bytes()
        first = self.response(raw)
        def interrupted(size):
            yield raw[:10]
            raise engine.requests.ConnectionError()
        first.iter_content = interrupted
        second = self.response(raw[10:], 206, {'Content-Range': f'bytes 10-{len(raw)-1}/{len(raw)}'})
        with patch.object(self.installer, 'get', side_effect=[first, second]) as get:
            target = self.installer.download(c, None)
        self.assertEqual(target.read_bytes(), raw)
        self.assertEqual(get.call_args_list[1].args, (c['mirrors'][0], {'Range': 'bytes=10-'}))
        retry = [data for event, data in self.events if event == 'retry']
        self.assertTrue(retry[0]['switching_source'])

    def test_sustained_low_speed_reconnects_and_keeps_partial_bytes(self):
        c = self.data['components'][0]
        raw = (self.assets / 'server.zip').read_bytes()
        clock = [0.0]
        first = self.response(raw)
        def slow(size):
            clock[0] = 31.0
            yield raw[:10]
        first.iter_content = slow
        second = self.response(raw[10:], 206, {'Content-Range': f'bytes 10-{len(raw)-1}/{len(raw)}'})
        with patch.object(engine.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(self.installer, 'get', side_effect=[first, second]):
            target = self.installer.download(c, None)
        self.assertEqual(target.read_bytes(), raw)
        self.assertIn('slow', [data['reason'] for event, data in self.events if event == 'retry'])

    def test_ignored_resume_restarts_hash_and_replaces_partial_file(self):
        c = self.data['components'][0]
        raw = (self.assets / 'server.zip').read_bytes()
        cache = self.installer.root / 'cache'
        cache.mkdir(parents=True)
        (cache / (c['sha256'] + '.part')).write_bytes(b'bad prefix')
        with patch.object(self.installer, 'get', return_value=self.response(raw)):
            self.assertEqual(self.installer.download(c, None).read_bytes(), raw)

    def test_corrupt_online_file_never_becomes_cached_archive(self):
        c = self.data['components'][0]
        raw = bytearray((self.assets / 'server.zip').read_bytes())
        raw[-1] ^= 1
        with patch.object(self.installer, 'get', return_value=self.response(bytes(raw))):
            with self.assertRaises(engine.InstallError): self.installer.download(c, None)
        self.assertFalse((self.installer.root / 'cache' / (c['sha256'] + '.zip')).exists())

    def test_untrusted_or_malformed_mirrors_are_rejected_before_install(self):
        for mirrors in (['https://untrusted.example.test/server.zip'], ['http://download.example.test/server.zip'], 'https://download.example.test', [None], ['https://download.example.test/server.zip'] * 4):
            data = copy.deepcopy(self.data)
            data['components'][0]['mirrors'] = mirrors
            with self.subTest(mirrors=mirrors), self.assertRaises(engine.InstallError):
                self.installer.install(catalog.sign(data, self.key), self.assets)
        self.assertFalse(self.installer.root.exists())

    def test_catalog_tool_signs_mirrors_and_emits_matching_host_policy(self):
        sources = self.root / 'catalog-input'
        sources.mkdir()
        for c in self.data['components']:
            shutil.copytree(self.root / c['id'], sources / c['id'])
        output = self.root / 'catalog-output'
        argv = ['make_catalog', '--components', str(sources), '--output', str(output),
                '--version', '0.1.0', '--build', '1', '--base-url', 'https://download.example.test/v1',
                '--mirror-base-url', 'https://mirror.example.test/v1', '--development-key']
        with patch('sys.argv', argv), patch('sys.stdout', new_callable=io.StringIO):
            catalog.main()
        config = json.loads((output / 'bootstrap-config.json').read_bytes())
        verifier = engine.Installer(self.root / 'catalog-check', config)
        data = verifier.verify(json.loads((output / 'catalog.json').read_bytes()))
        self.assertEqual(config['allowed_hosts'], ['download.example.test', 'mirror.example.test'])
        for c in data['components']:
            self.assertEqual(c['mirrors'], ['https://mirror.example.test/v1/' + c['id'] + '.zip'])

    def test_inconsistent_resume_range_is_rejected_without_appending(self):
        c = self.data['components'][0]
        raw = (self.assets / 'server.zip').read_bytes()
        cache = self.installer.root / 'cache'
        cache.mkdir(parents=True)
        part = cache / (c['sha256'] + '.part')
        part.write_bytes(raw[:10])
        response = self.response(raw[10:], 206, {'Content-Range': f'bytes 0-{len(raw)-1}/{len(raw)}'})
        with patch.object(self.installer, 'get', return_value=response):
            with self.assertRaises(engine.InstallError): self.installer.download(c, None)
        self.assertEqual(part.read_bytes(), raw[:10])

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
