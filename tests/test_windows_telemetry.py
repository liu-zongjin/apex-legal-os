"""The sender never contacts a real endpoint; profiles and transport are disposable."""
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import requests

ROOT = Path(__file__).resolve().parents[1]
def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts/windows' / (name + '.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module
metrics = load('windows_telemetry')
engine = load('bootstrap_engine')

class StatisticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.now = 100000; self.sent = []
        self.sender = self.make()
    def make(self, post=None):
        return metrics.Statistics(self.root, 2026102301, engine.exclusive_lock, engine.atomic_json,
            clock=lambda: self.now, post=post or self.sent.append, version=lambda: 'Windows 10.0.26100')
    def test_no_network_without_explicit_consent(self):
        self.assertIsNone(self.sender.status()['allowed']); self.sender.run_due()
        self.sender.consent(False); self.sender.run_due(); self.assertEqual(self.sent, [])
        self.assertEqual(self.sender.read()['install_id'], '')
    def test_immediate_then_six_hours_including_restart(self):
        self.sender.consent(True); self.sender.run_due()
        for elapsed in (0, 60, 3600, 21599):
            self.now = 100000 + elapsed; self.make().run_due()
        self.assertEqual(len(self.sent), 1)
        self.now = 121600; self.make().run_due(); self.assertEqual(len(self.sent), 2)
        self.assertEqual(self.sent[0], self.sent[1])
        self.assertEqual(set(self.sent[0]), {'install_id', 'version', 'os'})
        self.assertEqual(self.sent[0]['version'], '2026102301')
        self.assertEqual(self.sent[0]['os'], 'Windows 10.0.26100')
    def test_failure_reserves_interval_before_transport(self):
        def failed(payload):
            self.assertEqual(self.sender.read()['last_attempt'], self.now)
            self.sent.append(payload); raise requests.ConnectionError('fake offline')
        self.sender.consent(True); self.make(failed).run_due()
        self.make().run_due(); self.now += 60; self.make().run_due()
        self.assertEqual(len(self.sent), 1)
        self.now += 21540; self.make().run_due(); self.assertEqual(len(self.sent), 2)
    def test_revoke_reenable_and_upgrade_keep_identity_and_gate(self):
        self.sender.consent(True); self.sender.run_due(); identifier = self.sent[0]['install_id']
        self.sender.consent(False); self.now += 100; self.sender.run_due()
        self.sender.consent(True); upgraded = self.make(); upgraded.build = '2026102401'; upgraded.run_due()
        self.assertEqual(len(self.sent), 1); self.assertEqual(upgraded.read()['install_id'], identifier)
        self.now += 21500; upgraded.run_due(); self.assertEqual(self.sent[-1]['version'], '2026102401')
    def test_corrupt_preferences_fail_closed(self):
        self.sender.folder.mkdir()
        for data in ('invalid', '[]', '{"allowed":true,"install_id":5}', '{"allowed":true,"last_attempt":false}', '{"allowed":"true"}'):
            self.sender.path.write_text(data); self.sender.run_due(); self.assertIsNone(self.sender.status()['allowed'])
        self.assertEqual(self.sent, [])
    def test_concurrent_helpers_cannot_duplicate_attempt(self):
        self.sender.consent(True)
        threads = [threading.Thread(target=self.make().run_due) for _ in range(12)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(len(self.sent), 1)
    def test_zero_epoch_and_backward_clock_are_bounded(self):
        self.now = 0; self.sender.consent(True); self.sender.run_due(); self.sender.run_due()
        self.assertEqual(len(self.sent), 1)
        self.now = -10; self.sender.run_due(); self.assertEqual(len(self.sent), 1)
    def test_transport_disables_credentials_redirects_and_retries(self):
        with patch.object(metrics.requests, 'Session') as session:
            client = session.return_value.__enter__.return_value
            client.post.return_value.status_code = 204
            self.assertTrue(metrics.post_event({'fake': 'anonymous'}))
            self.assertFalse(client.trust_env)
            client.post.assert_called_once_with(metrics.ENDPOINT, json={'fake': 'anonymous'},
                timeout=(5, 10), allow_redirects=False, headers={'User-Agent': 'Stella-Windows-Metrics/1'})

if __name__ == '__main__': unittest.main()
