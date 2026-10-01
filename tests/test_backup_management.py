import json
import plistlib
import tempfile
import unittest
from pathlib import Path
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
        self.plist_path.write_bytes(plistlib.dumps({
            "Label": backups.BACKUP_LABEL,
            "StartCalendarInterval": {"Hour": 3, "Minute": 20},
            "RunAtLoad": True,
        }))
        for target, value in (("backup_root", self.backup_dir), ("launch_agent_path", self.plist_path)):
            patcher = patch.object(backups, target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_save_schedule_and_retention(self):
        settings = backups.BackupSettingsInput(
            frequency="weekdays", hour=22, minute=45, weekday=0, retention_days=7,
        )
        with patch.object(backups, "_reload_agent") as reload_agent:
            result = backups.save_backup_settings(settings)
        self.assertTrue(result["ok"])
        reload_agent.assert_called_once_with(self.plist_path)
        plist = plistlib.loads(self.plist_path.read_bytes())
        self.assertEqual(plist["StartCalendarInterval"], [
            {"Hour": 22, "Minute": 45, "Weekday": day} for day in range(1, 6)
        ])
        self.assertFalse(plist["RunAtLoad"])
        self.assertEqual(json.loads((self.backup_dir / "backup-settings.json").read_text())["retention_days"], 7)

    def test_failed_reload_rolls_back_files(self):
        original = self.plist_path.read_bytes()
        settings = backups.BackupSettingsInput(
            frequency="weekly", hour=4, minute=10, weekday=0, retention_days=30,
        )
        with patch.object(backups, "_reload_agent", side_effect=[RuntimeError("reload failed"), None]):
            with self.assertRaises(HTTPException):
                backups.save_backup_settings(settings)
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
            backups.delete_backup_file("databases", "../legal_kb-20261001-032333.db")
        self.assertEqual(backups.delete_backup_file("databases", backup.name)["freed_bytes"], 11)
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
            backups.delete_backup_file("databases", name)
        self.assertEqual((outside / name).read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
