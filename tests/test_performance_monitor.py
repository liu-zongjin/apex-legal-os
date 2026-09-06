import unittest

from backend.performance_monitor import _clean_frontend_sample, snapshot


class PerformanceMonitorTests(unittest.TestCase):
    def test_frontend_diagnostics_only_accept_aggregate_bounded_fields(self):
        clean = _clean_frontend_sample({
            "openTabs": 4,
            "domNodes": -2,
            "longTaskMaxMs": 12.345,
            "clientName": "must not be retained",
            "url": "/private/case/1",
        })
        self.assertEqual(clean["openTabs"], 4)
        self.assertEqual(clean["domNodes"], 0)
        self.assertEqual(clean["longTaskMaxMs"], 12.3)
        self.assertNotIn("clientName", clean)
        self.assertNotIn("url", clean)

    def test_snapshot_exposes_budget_and_process_metrics(self):
        report = snapshot()
        self.assertEqual(report["budgets"]["localApiP95Ms"], 500)
        self.assertGreater(report["backend"]["pid"], 0)
        self.assertGreaterEqual(report["backend"]["rssMb"], 0)


if __name__ == "__main__":
    unittest.main()
