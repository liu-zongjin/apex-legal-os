import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend import main


class EfficiencyCenterPreferencesTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.old_db_path = main.DB_PATH
        main.DB_PATH = Path(self.tempdir.name) / "preferences.db"
        main.init_db()
        self.client = TestClient(main.app)
        self.path = "/api/preferences/legal-assistant-tool-order"

    def tearDown(self):
        main.DB_PATH = self.old_db_path
        self.tempdir.cleanup()

    def test_legacy_order_and_customized_group_and_subtitle_survive_reload(self):
        legacy = self.client.put(self.path, json={"order": ["qq_mail", "case_manager"]})
        self.assertEqual(legacy.status_code, 200, legacy.text)
        self.assertEqual(self.client.get(self.path).json()["groups"], {})

        saved = self.client.put(self.path, json={
            "order": ["qq_mail", "case_manager", "case_archive"],
            "groups": {"qq_mail": "case", "case_archive": "document"},
            "subtitles": {"qq_mail": "收件与发票", "case_manager": ""},
        })
        self.assertEqual(saved.status_code, 200, saved.text)
        reloaded = self.client.get(self.path).json()
        self.assertEqual(reloaded["order"][:3], ["qq_mail", "case_manager", "case_archive"])
        self.assertEqual(reloaded["groups"], {"qq_mail": "case", "case_archive": "document"})
        self.assertEqual(reloaded["subtitles"], {"qq_mail": "收件与发票", "case_manager": ""})

        self.client.put(self.path, json={"order": ["case_manager", "qq_mail"]})
        self.assertEqual(self.client.get(self.path).json()["groups"]["qq_mail"], "case")

    def test_invalid_customization_does_not_change_saved_preferences(self):
        self.client.put(self.path, json={"order": ["qq_mail"], "groups": {"qq_mail": "case"}, "subtitles": {}})
        for payload in (
            {"order": ["case_manager"], "groups": {"qq_mail": "unknown"}, "subtitles": {}},
            {"order": ["case_manager"], "groups": {}, "subtitles": {"qq_mail": "x" * 81}},
            {"order": ["case_manager"], "groups": {"unknown": "case"}, "subtitles": {}},
        ):
            response = self.client.put(self.path, json=payload)
            self.assertEqual(response.status_code, 400, response.text)
            self.assertEqual(self.client.get(self.path).json()["order"], ["qq_mail"])


if __name__ == "__main__":
    unittest.main()
