import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import calculator_history


class CalculatorHistoryRouterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / "calculator_history.db"
        with self.db() as conn:
            calculator_history.add_schema(conn)
        app = FastAPI()
        app.include_router(calculator_history.create_router(self.db))
        self.client = TestClient(app)

    def db(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def test_create_list_update_delete_and_clear_preserve_pinned(self):
        first = self.client.post(
            "/api/calculator-history",
            json={
                "calculatorType": "litigation_arbitration",
                "amount": 100000,
                "payload": {"institution": "示例仲裁委"},
            },
        )
        self.assertEqual(first.status_code, 200)
        first_item = first.json()["history"]
        self.assertEqual(first_item["calculatorType"], "litigation_arbitration")
        self.assertEqual(first_item["payload"], {"institution": "示例仲裁委"})
        self.assertFalse(first_item["pinned"])

        second = self.client.post(
            "/api/calculator-history",
            json={
                "calculatorType": "litigation_arbitration",
                "amount": 250000,
                "payload": {"institution": "另一机构"},
            },
        )
        self.assertEqual(second.status_code, 200)
        second_id = second.json()["history"]["id"]

        updated = self.client.put(
            f"/api/calculator-history/{first_item['id']}",
            json={"note": "重要备注", "pinned": True},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertTrue(updated.json()["history"]["pinned"])
        self.assertEqual(updated.json()["history"]["note"], "重要备注")

        listed = self.client.get("/api/calculator-history/litigation_arbitration")
        self.assertEqual(listed.status_code, 200)
        items = listed.json()["history"]
        self.assertEqual([item["id"] for item in items], [first_item["id"], second_id])

        cleared = self.client.delete(
            "/api/calculator-history",
            params={"calculatorType": "litigation_arbitration", "includePinned": "false"},
        )
        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(cleared.json(), {"ok": True, "deleted": 1})

        remaining = self.client.get("/api/calculator-history/litigation_arbitration").json()["history"]
        self.assertEqual([item["id"] for item in remaining], [first_item["id"]])

        deleted = self.client.delete(f"/api/calculator-history/{first_item['id']}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.delete(f"/api/calculator-history/{first_item['id']}").status_code, 404)

    def test_validation_and_error_responses(self):
        self.assertEqual(self.client.get("/api/calculator-history/invalid_type").status_code, 400)
        self.assertEqual(
            self.client.post(
                "/api/calculator-history",
                json={"calculatorType": "risk_agency", "amount": 0, "payload": {}},
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.put("/api/calculator-history/999999", json={}).status_code,
            400,
        )
        self.assertEqual(
            self.client.put("/api/calculator-history/999999", json={"note": "x"}).status_code,
            404,
        )
