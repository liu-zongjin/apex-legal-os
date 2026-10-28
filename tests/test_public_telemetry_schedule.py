"""Verify the actual public-Mac scheduler with anonymous, simulated time."""
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PublicTelemetryTests(unittest.TestCase):
    def test_consent_and_rolling_six_hour_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            main = root / 'main.swift'
            main.write_text('''import Foundation
let interval = PublicTelemetrySchedule.interval
precondition(interval == 21600)
precondition(!PublicTelemetrySchedule.canSend(consented: false, now: 100000, lastAttempt: 0))
precondition(PublicTelemetrySchedule.canSend(consented: true, now: 100000, lastAttempt: 0))
precondition(!PublicTelemetrySchedule.canSend(consented: true, now: 100001, lastAttempt: 100000))
precondition(!PublicTelemetrySchedule.canSend(consented: true, now: 121599, lastAttempt: 100000))
precondition(PublicTelemetrySchedule.canSend(consented: true, now: 121600, lastAttempt: 100000))
precondition(!PublicTelemetrySchedule.canSend(consented: true, now: 99999, lastAttempt: 100000))
precondition(PublicTelemetrySchedule.nextDelay(now: 100001, lastAttempt: 100000) == 21599)
precondition(PublicTelemetrySchedule.nextDelay(now: 121600, lastAttempt: 100000) == 1)
''')
            binary = root / 'schedule'
            subprocess.run(['xcrun','swiftc',str(ROOT/'native-shell/Sources/PublicTelemetrySchedule.swift'),str(main),'-o',str(binary)],check=True,capture_output=True)
            subprocess.run([str(binary)],check=True)
        source = (ROOT/'native-shell/Sources/PublicDistribution.swift').read_text()
        self.assertLess(source.index('defaults.set(now, forKey: "StellaMetricsLastAttempt")'), source.index('session.dataTask(with: request)'))
        self.assertIn('repeats: false', source)
        self.assertIn('self?.startHeartbeat()', source)

if __name__ == '__main__': unittest.main()
