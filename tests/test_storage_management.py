import tempfile
import unittest
from pathlib import Path

from backend.main import (
    _storage_classify_path,
    _storage_db_backup_candidates,
    _storage_is_db_backup_file,
    _storage_runtime_log_candidates,
)
from scripts.private_server import _trim_log_tail


class StorageManagementPathTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "logs").mkdir()
        (self.root / ".tmp").mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_runtime_logs_include_root_and_logs_directory_only(self):
        root_log = self.root / "server.log"
        nested_log = self.root / "logs" / "private-server.log"
        rotated_log = self.root / "logs" / "private-server.log.1"
        browser_log = self.root / "backend" / "browser" / "debug.log"
        browser_log.parent.mkdir(parents=True)
        for path in (root_log, nested_log, rotated_log, browser_log):
            path.write_text("x", encoding="utf-8")

        candidates = set(_storage_runtime_log_candidates(self.root))

        self.assertEqual(candidates, {root_log, nested_log, rotated_log})

    def test_database_backups_include_all_supported_snapshots_but_not_live_db(self):
        live_db = self.root / "legal_kb.db"
        legacy_backup = self.root / "legal_kb.db.bak-20260809"
        pre_operation_backup = self.root / "legal_kb.db.before-court-dedup-20260901-1640.bak"
        note_markup_repair_backup = self.root / "legal_kb.before-note-markup-repair-20260902174514.db"
        repair_backup = self.root / ".tmp" / "legal_kb_backup_before_repair_20260809.db"
        unrelated_db = self.root / ".tmp" / "other.db"
        for path in (live_db, legacy_backup, pre_operation_backup, note_markup_repair_backup, repair_backup, unrelated_db):
            path.write_bytes(b"db")

        candidates = set(_storage_db_backup_candidates(self.root))

        self.assertEqual(candidates, {legacy_backup, pre_operation_backup, note_markup_repair_backup, repair_backup})
        self.assertFalse(_storage_is_db_backup_file(live_db, self.root))
        self.assertFalse(_storage_is_db_backup_file(unrelated_db, self.root))

    def test_existing_log_trim_keeps_newest_complete_lines(self):
        log_path = self.root / "logs" / "private-server.log"
        log_path.write_bytes(b"old-line\nsecond-line\nnewest-line\n")

        _trim_log_tail(log_path, 25)

        self.assertEqual(log_path.read_bytes(), b"second-line\nnewest-line\n")
        self.assertLessEqual(log_path.stat().st_size, 25)

    def classify(self, rel_path):
        path = self.root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        return _storage_classify_path(path, self.root)

    def test_article_images_classified_as_article_images(self):
        self.assertEqual(self.classify("article_images/pdf-token/page-001.png"), "article_images")
        self.assertEqual(self.classify("article_images/article-1.png"), "article_images")

    def test_tmp_files_classified_as_temp_files(self):
        self.assertEqual(self.classify(".tmp/contract-render/preview.png"), "temp_files")
        self.assertEqual(self.classify(".tmp/toc-backup.json"), "temp_files")

    def test_tmp_log_files_still_classified_as_runtime_logs(self):
        self.assertEqual(self.classify(".tmp/debug.log"), "runtime_logs")

    def test_tmp_database_backups_still_classified_as_db_backups(self):
        self.assertEqual(
            self.classify(".tmp/legal_kb_backup_before_repair_20260809.db"),
            "db_backups",
        )

    def test_new_top_level_directories_have_dedicated_categories(self):
        self.assertEqual(self.classify("tests/test_case_files.py"), "test_code")
        self.assertEqual(self.classify("native-shell/Sources/main.swift"), "native_shell")
        self.assertEqual(self.classify("outputs/export.xlsx"), "outputs")
        self.assertEqual(self.classify(".swift-bin/contacts_bridge"), "swift_bin")

    def test_unknown_root_files_fall_back_to_project_files(self):
        self.assertEqual(self.classify("mystery-file.bin"), "project_files")

    def test_local_json_configs_classified_as_project_config(self):
        self.assertEqual(self.classify("local_ai_prefs.json"), "project_config")
        self.assertEqual(self.classify("local_feishu_article_config.json"), "project_config")
        self.assertEqual(self.classify("local_future_feature.json"), "project_config")

    def test_known_root_classifications_are_preserved(self):
        self.assertEqual(self.classify("uploads/doc.pdf"), "uploads")
        self.assertEqual(self.classify("legal_kb.db"), "legal_kb.db")
        self.assertEqual(self.classify("frontend/app.js"), "frontend")
        self.assertEqual(self.classify("backend/main.py"), "backend")
        self.assertEqual(self.classify("server.log"), "runtime_logs")
        self.assertEqual(self.classify("legal_kb.db.bak-20260809"), "db_backups")
        self.assertEqual(self.classify("legal_kb.db.before-court-dedup-20260901-1640.bak"), "db_backups")
        self.assertEqual(self.classify("legal_kb.before-note-markup-repair-20260902174514.db"), "db_backups")
        self.assertEqual(self.classify("README_Feishu.md"), "feishu")
        self.assertEqual(self.classify("restart.py"), "project_scripts")
        self.assertEqual(self.classify("requirements-private.txt"), "package_files")
        self.assertEqual(self.classify("scripts.zip"), "project_archives")
        self.assertEqual(self.classify("SETUP_SUMMARY.md"), "project_docs")
        self.assertEqual(self.classify("node_modules/pkg/index.js"), "node_modules")
        self.assertEqual(self.classify("node_modules/pkg/test/helper.js"), "node_aux")


if __name__ == "__main__":
    unittest.main()
