import json
import os
import sqlite3
import subprocess
import sys
import tarfile
from contextlib import closing
import plistlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from backend import backup_management as backups


class BackupManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.backup_dir = self.root / "backups"
        self.plist_path = self.root / "backup.plist"
        self.request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
        self.plist_path.write_bytes(plistlib.dumps({
            "Label": backups.BACKUP_LABEL,
            "StartCalendarInterval": {"Hour": 3, "Minute": 20},
            "RunAtLoad": True,
        }))
        for target, value in (("backup_root", self.backup_dir), ("launch_agent_path", self.plist_path)):
            patcher = patch.object(backups, target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    @patch.object(backups.sys, "platform", "darwin")
    def test_save_schedule_and_retention(self):
        settings = backups.BackupSettingsInput(
            frequency="weekdays", hour=22, minute=45, weekday=0, retention_days=7,
        )
        with patch.object(backups, "_reload_agent") as reload_agent:
            result = backups.save_backup_settings(settings, self.request)
        self.assertTrue(result["ok"])
        reload_agent.assert_called_once_with(self.plist_path)
        plist = plistlib.loads(self.plist_path.read_bytes())
        self.assertEqual(plist["StartCalendarInterval"], [
            {"Hour": 22, "Minute": 45, "Weekday": day} for day in range(1, 6)
        ])
        self.assertFalse(plist["RunAtLoad"])
        self.assertEqual(json.loads((self.backup_dir / "backup-settings.json").read_text())["retention_days"], 7)

    @patch.object(backups.sys, "platform", "darwin")
    def test_disable_and_reenable_schedule_preserves_configuration(self):
        payload = backups.BackupSettingsInput(enabled=False, frequency="weekly", hour=4, minute=10, weekday=5, retention_days=30)
        with patch.object(backups, "_reload_agent"):
            backups.save_backup_settings(payload, self.request)
            self.assertNotIn("StartCalendarInterval", plistlib.loads(self.plist_path.read_bytes()))
            self.assertFalse(backups.read_settings()["enabled"])
            payload.enabled = True
            backups.save_backup_settings(payload, self.request)
        self.assertEqual(plistlib.loads(self.plist_path.read_bytes())["StartCalendarInterval"], {"Hour": 4, "Minute": 10, "Weekday": 5})
        self.assertTrue(backups.read_settings()["enabled"])

    @patch.object(backups.sys, "platform", "darwin")
    def test_failed_reload_rolls_back_files(self):
        original = self.plist_path.read_bytes()
        settings = backups.BackupSettingsInput(
            frequency="weekly", hour=4, minute=10, weekday=0, retention_days=30,
        )
        with patch.object(backups, "_reload_agent", side_effect=[RuntimeError("reload failed"), None]):
            with self.assertRaises(HTTPException):
                backups.save_backup_settings(settings, self.request)
        self.assertEqual(self.plist_path.read_bytes(), original)
        self.assertFalse((self.backup_dir / "backup-settings.json").exists())

    def test_file_listing_and_deletion_stay_within_backup_folder(self):
        directory = self.backup_dir / "databases"
        directory.mkdir(parents=True)
        backup = directory / "legal_kb-20261001-032333.db"
        backup.write_bytes(b"test backup")
        unrelated = self.root / "legal_kb-20261001-032333.db"
        unrelated.write_bytes(b"live")
        listing = backups.get_backup_management()
        self.assertEqual([item["name"] for item in listing["files"]], [backup.name])
        with self.assertRaises(HTTPException):
            backups.delete_backup_file("databases", "../legal_kb-20261001-032333.db", self.request)
        self.assertEqual(backups.delete_backup_file("databases", backup.name, self.request)["freed_bytes"], 11)
        self.assertFalse(backup.exists())
        self.assertEqual(unrelated.read_bytes(), b"live")

    def test_symlinked_backup_directory_cannot_delete_elsewhere(self):
        outside = self.root / "outside"
        outside.mkdir()
        name = "legal_kb-20261001-032333.db"
        (outside / name).write_bytes(b"keep")
        self.backup_dir.mkdir()
        (self.backup_dir / "databases").symlink_to(outside, target_is_directory=True)
        self.assertEqual(backups.get_backup_management()["files"], [])
        with self.assertRaises(HTTPException):
            backups.delete_backup_file("databases", name, self.request)
        self.assertEqual((outside / name).read_bytes(), b"keep")

    @patch.object(backups.sys, "platform", "darwin")
    def test_schedule_write_failure_rolls_back_config_before_reload(self):
        payload = backups.BackupSettingsInput(frequency="daily", hour=4, minute=10, retention_days=30)
        original = self.plist_path.read_bytes()
        writer = backups._atomic_write
        def fail_plist(path, data):
            if path == self.plist_path:
                raise OSError("write failed")
            writer(path, data)
        with patch.object(backups, "_atomic_write", side_effect=fail_plist), patch.object(backups, "_reload_agent") as reload_agent:
            with self.assertRaises(HTTPException):
                backups.save_backup_settings(payload, self.request)
        self.assertEqual(self.plist_path.read_bytes(), original)
        self.assertFalse(backups.settings_path().exists())
        reload_agent.assert_not_called()

    def test_corrupt_schedule_does_not_hide_backups_on_windows(self):
        directory = self.backup_dir / "databases"
        directory.mkdir(parents=True)
        (directory / "legal_kb-20261109-120012.db").write_bytes(b"earlier backup")
        (directory / "legal_kb-20261121-120012.db").write_bytes(b"latest backup")
        newest_empty = directory / "legal_kb-20261122-120012.db"
        newest_empty.touch()
        backups.settings_path().write_text("null", encoding="utf-8")
        with patch.object(backups.sys, "platform", "win32"):
            data = backups.get_backup_management()
        empty, latest, earlier = data["files"]
        self.assertFalse(data["schedule_available"])
        self.assertIn("格式", data["schedule_error"])
        self.assertIn("文件为空", empty["retention_note"])
        self.assertEqual(latest["display_name"], "定时数据库备份")
        self.assertEqual(latest["created_at"], "2026-11-21 12:00:12")
        self.assertIn("建议保留", latest["retention_note"])
        self.assertIn("较新的", earlier["retention_note"])
        self.assertEqual(len(latest["revision"].split(":")), 4)

    def test_delete_rejects_changed_backup(self):
        directory = self.backup_dir / "databases"
        directory.mkdir(parents=True)
        path = directory / "legal_kb-20261122-032000.db"
        path.write_bytes(b"original")
        self.request.query_params = {"revision": backups.get_backup_management()["files"][0]["revision"]}
        path.write_bytes(b"modified backup")
        with self.assertRaises(HTTPException) as error:
            backups.delete_backup_file("databases", path.name, self.request)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(path.read_bytes(), b"modified backup")

    @unittest.skipUnless(sys.platform == "darwin", "private service uses macOS bsdtar")
    def test_private_script_snapshots_wal_and_preserves_archive_root(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "backup_private.sh"
        isolated_script = self.root / "scripts" / script.name
        isolated_script.parent.mkdir()
        isolated_script.write_bytes(script.read_bytes())
        db_path = self.root / "external ' data.sqlite"
        uploads = self.root / "custom uploads"
        uploads.mkdir()
        (uploads / "测试.txt").write_text("fixture", encoding="utf-8")
        self.backup_dir.mkdir()
        backups.settings_path().write_text('{"frequency":"weekly","retention_days":7}', encoding="utf-8")
        env = {**os.environ, "LEGAL_KB_DB_PATH": str(db_path), "LEGAL_KB_UPLOAD_DIR": str(uploads),
               "LEGAL_KB_BACKUP_DIR": str(self.backup_dir)}
        with closing(sqlite3.connect(db_path)) as conn:
            conn.execute("PRAGMA journal_mode=wal")
            conn.execute("CREATE TABLE notes (content TEXT)")
            conn.execute("INSERT INTO notes VALUES ('from WAL')")
            conn.commit()
            subprocess.run(["bash", str(isolated_script)], env=env, check=True, capture_output=True, text=True)
        files = {file["category"]: file for file in backups.get_backup_management()["files"]}
        with closing(sqlite3.connect(self.backup_dir / "databases" / files["databases"]["name"])) as copied:
            self.assertEqual(copied.execute("SELECT content FROM notes").fetchone(), ("from WAL",))
        with tarfile.open(self.backup_dir / "uploads" / files["uploads"]["name"]) as archive:
            self.assertIn("uploads/测试.txt", archive.getnames())
        self.assertEqual(list(self.backup_dir.glob("*/.staging.*")), [])

    def test_remote_management_policy_applies_to_deletion(self):
        remote = SimpleNamespace(client=SimpleNamespace(host="192.0.2.10"))
        with patch.object(backups, "allow_remote_management", return_value=False):
            with self.assertRaises(HTTPException) as error:
                backups.delete_backup_file("databases", "legal_kb-20261001-032333.db", remote)
        self.assertEqual(error.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
