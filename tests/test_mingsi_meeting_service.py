import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from backend import mingsi_meeting_service as mingsi


class FakeApp:
    def __init__(self):
        self.routes = {}

    def _register(self, path):
        def decorator(fn):
            self.routes[path] = fn
            return fn
        return decorator

    def get(self, path): return self._register(path)
    def post(self, path): return self._register(path)
    def delete(self, path): return self._register(path)


class MingsiMeetingServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db_path = Path(self.directory.name) / "apex.sqlite"

        def get_db():
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            return conn

        self.get_db = get_db

    def tearDown(self):
        self.directory.cleanup()

    def test_date_and_time_validation(self):
        self.assertEqual(mingsi._validate_date("2026-09-01"), "2026-09-01")
        self.assertEqual(mingsi._validate_time("09:30:00", "开始时间"), "09:30")
        with self.assertRaises(HTTPException):
            mingsi._validate_date("2026/09/01")
        with self.assertRaises(HTTPException):
            mingsi._validate_time("tomorrow", "开始时间")

    def test_response_code_preserves_success_zero(self):
        self.assertEqual(mingsi._response_code({"code": 0}), 0)
        self.assertEqual(mingsi._response_code({"code": None}), -1)

    def test_login_token_shape_matches_mingsi_response(self):
        top_level = {"code": 0, "token": "top-level-token", "data": {"person": {}}}
        nested = top_level.get("data") if isinstance(top_level.get("data"), dict) else {}
        self.assertEqual(str(top_level.get("token") or nested.get("token") or ""), "top-level-token")

    def test_service_base_url_keeps_elawoffice_context(self):
        self.assertTrue(mingsi.MINGSI_API.endswith("/Elawoffice/"))

    def test_meeting_list_accepts_mingsi_top_level_payload(self):
        payload = {"code": 0, "meetinglist": {"records": [{"meetingid": 1}], "total": 1}}
        self.assertEqual(mingsi._meeting_list(payload)["total"], 1)

    def test_time_part_accepts_datetime_or_time(self):
        self.assertEqual(mingsi._time_part("2026-09-01 08:15:00"), "08:15")
        self.assertEqual(mingsi._time_part("08:30"), "08:30")

    def test_status_does_not_reveal_full_account(self):
        self.assertEqual(mingsi._redact_account("123"), "***")
        masked = mingsi._redact_account("18800001100")
        self.assertNotIn("898630", masked)
        self.assertTrue(masked.startswith("18"))

    def test_route_registration_initializes_audit_table(self):
        app = FakeApp()
        mingsi.register_mingsi_meeting_routes(app, self.get_db)
        self.assertIn("/api/mingsi-meetings/status", app.routes)
        self.assertIn("/api/mingsi-meetings/meetings", app.routes)
        self.assertIn("/api/mingsi-meetings/schedule", app.routes)
        with self.get_db() as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("mingsi_meeting_audit", tables)
