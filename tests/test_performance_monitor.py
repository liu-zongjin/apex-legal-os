import unittest

from backend.performance_monitor import _clean_frontend_sample, snapshot


class PerformanceMonitorTests(unittest.TestCase):
    def test_frontend_diagnostics_only_accept_aggregate_bounded_fields(self):
        clean = _clean_frontend_sample({
            "openTabs": 4,
            "hibernatedPages": 2,
            "domNodes": -2,
            "longTaskMaxMs": 12.345,
            "startupPage": "case-manager",
            "startupOutcome": "offline-cache",
            "startupMs": 823.46,
            "startupCacheReady": True,
            "clientName": "must not be retained",
            "url": "/private/case/1",
        })
        self.assertEqual(clean["openTabs"], 4)
        self.assertEqual(clean["hibernatedPages"], 2)
        self.assertEqual(clean["domNodes"], 0)
        self.assertEqual(clean["longTaskMaxMs"], 12.3)
        self.assertEqual(clean["startupPage"], "case-manager")
        self.assertEqual(clean["startupOutcome"], "offline-cache")
        self.assertEqual(clean["startupMs"], 823.5)
        self.assertTrue(clean["startupCacheReady"])
        self.assertNotIn("clientName", clean)
        self.assertNotIn("url", clean)

    def test_snapshot_exposes_budget_and_process_metrics(self):
        report = snapshot()
        self.assertEqual(report["budgets"]["localApiP95Ms"], 500)
        self.assertGreater(report["backend"]["pid"], 0)
        self.assertGreaterEqual(report["backend"]["rssMb"], 0)
        self.assertIn("currentRssMb", report["backend"])
        self.assertIn("childProcessCount", report["backend"])
        self.assertGreaterEqual(report["backend"]["threadCount"], 1)


if __name__ == "__main__":
    unittest.main()
