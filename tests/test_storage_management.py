import asyncio
import os
import tempfile
import unittest
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import backend.main as main
from backend.main import (
    _storage_classify_path,
    _storage_db_backup_candidates,
    _storage_history_backup_candidates,
    _storage_is_browser_runtime_cache,
    _storage_is_db_backup_file,
    _storage_is_upload_file,
    _storage_upload_associations,
    _storage_runtime_log_candidates,
)
from backend.court_online_service import (
    COURT_BROWSER_DISK_CACHE_BYTES,
    _court_browser_launch_args,
)
from scripts.private_server import _trim_log_tail
from backend.backup_management import backup_revision


class StorageManagementPathTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve()
        (self.root / "logs").mkdir()
        (self.root / ".tmp").mkdir()
        self.environment = patch.dict(os.environ, {"LEGAL_KB_BACKUP_DIR": str(self.root / "scheduled")})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        db_path = patch.object(main, "DB_PATH", self.root / "legal_kb.db")
        db_path.start()
        self.addCleanup(db_path.stop)
        os.environ.pop("LEGAL_KB_DATA_DIR", None)
        os.environ.pop("LEGAL_KB_CONFIG_DIR", None)

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

    def test_migration_backups_are_history_backups(self):
        historical = self.root / "data" / "schema_backups" / "legal_kb-before-v1-20260908.db"
        future = self.root / "data" / "history_backups" / "legal_kb-before-v2-20260909.db"
        unrelated = self.root / "data" / "unrelated" / "other.db"
        for path in (historical, future, unrelated):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"db")

        candidates = set(_storage_history_backup_candidates(self.root))

        self.assertEqual(candidates, {historical, future})
        self.assertEqual(_storage_classify_path(historical, self.root), "history_backups")
        self.assertEqual(_storage_classify_path(future, self.root), "history_backups")
        self.assertEqual(_storage_classify_path(unrelated, self.root), "app_runtime_data")

    def test_court_browser_cache_excludes_login_profile_data(self):
        cache = self.root / "backend" / "court_online_service" / "browser-profile" / "Default" / "Cache" / "data"
        cookies = self.root / "backend" / "court_online_service" / "browser-profile" / "Default" / "Cookies"
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(b"cache")
        cookies.write_bytes(b"login")

        self.assertTrue(_storage_is_browser_runtime_cache(cache, self.root))
        self.assertFalse(_storage_is_browser_runtime_cache(cookies, self.root))
        self.assertEqual(_storage_classify_path(cache, self.root), "browser_runtime_cache")
        self.assertEqual(_storage_classify_path(cookies, self.root), "backend")

    def test_court_browser_launch_args_bound_background_component_and_disk_cache(self):
        background = _court_browser_launch_args(background=True)
        windowed = _court_browser_launch_args(background=False)

        self.assertIn("--disable-component-update", background)
        self.assertIn(f"--disk-cache-size={COURT_BROWSER_DISK_CACHE_BYTES}", background)
        self.assertIn("--hide-crash-restore-bubble", background)
        self.assertNotIn("--window-position=-32000,-32000", background)
        self.assertIn("--window-position=-32000,-32000", windowed)
        self.assertNotIn("--hide-crash-restore-bubble", windowed)

    def test_browser_cache_cleanup_stops_browser_before_deleting_and_preserves_cookies(self):
        cache = self.root / "backend" / "court_online_service" / "browser-profile" / "Default" / "Cache" / "data"
        cookies = self.root / "backend" / "court_online_service" / "browser-profile" / "Default" / "Cookies"
        cache.mkdir(parents=True)
        cache.joinpath("entry").write_bytes(b"cache")
        cookies.parent.mkdir(parents=True, exist_ok=True)
        cookies.write_bytes(b"login")
        events = []

        async def prepare_browser_cleanup():
            events.append(("prepare", cache.exists()))

        request = SimpleNamespace(
            client=SimpleNamespace(host="127.0.0.1"),
            json=AsyncMock(return_value={"type": "browser_runtime_cache"}),
        )
        with patch.object(main, "BASE_DIR", self.root), patch.object(
            main.app.state,
            "prepare_court_browser_runtime_cache_cleanup",
            new=prepare_browser_cleanup,
            create=True,
        ):
            result = asyncio.run(main.cleanup_storage(request))

        self.assertTrue(result["ok"])
        self.assertEqual(events, [("prepare", True)])
        self.assertFalse(cache.parent.exists())
        self.assertEqual(cookies.read_bytes(), b"login")

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
            "history_backups",
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
        self.assertEqual(self.classify("legal_kb.db.bak-20260809"), "history_backups")
        self.assertEqual(self.classify("legal_kb.db.before-court-dedup-20260901-1640.bak"), "history_backups")
        self.assertEqual(self.classify("legal_kb.before-note-markup-repair-20260902174514.db"), "history_backups")
        self.assertEqual(self.classify("README_Feishu.md"), "feishu")
        self.assertEqual(self.classify("restart.py"), "project_scripts")
        self.assertEqual(self.classify("requirements-private.txt"), "package_files")
        self.assertEqual(self.classify("scripts.zip"), "project_archives")
        self.assertEqual(self.classify("SETUP_SUMMARY.md"), "project_docs")
        self.assertEqual(self.classify("node_modules/pkg/index.js"), "node_modules")
        self.assertEqual(self.classify("node_modules/pkg/test/helper.js"), "node_aux")

    def test_project_breakdown_protects_business_and_database_files(self):
        for name, category in {
            "data/cc2api-runtime/node_modules/runtime/bin/claude": "ai_runtime",
            "data/download-center/record/document.pdf": "download_records",
            "data/invoice_auto_collections/mail/month/invoices.zip": "invoice_collections",
            "data/mail_summary_account.json": "mail_invoice_data",
            "data/invoice_automation.json": "mail_invoice_data",
            "legal_kb.db-wal": "database_sidecars",
            "data/history_backups/snapshot.db-shm": "database_sidecars",
            "docs/architecture/SYSTEM_MAP.md": "project_docs",
            "data/mobile-brand.json": "app_runtime_data",
            "data/dossier-ui-review/contract.pdf": "app_runtime_data",
            "data/dossier-ui-review/completed-1440-light.png": "review_artifacts",
        }.items():
            self.assertEqual(self.classify(name), category, name)

    def test_review_cleanup_validates_all_paths_and_rejects_symlinks(self):
        screenshot = self.root / "data/dossier-ui-review/completed-1440-light.png"
        screenshot.parent.mkdir(parents=True)
        screenshot.write_bytes(b"review")
        business = self.root / "data/contract.pdf"
        business.write_bytes(b"business")
        def cleanup(paths):
            request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"),
                json=AsyncMock(return_value={"type": "review_artifact_files", "paths": paths}))
            with patch.object(main, "BASE_DIR", self.root):
                return asyncio.run(main.cleanup_storage(request))
        relative = screenshot.relative_to(self.root).as_posix()
        self.assertFalse(cleanup([relative, "data/contract.pdf"])["ok"])
        self.assertTrue(screenshot.exists())
        self.assertFalse(cleanup(["data/dossier-ui-review/../../contract.pdf"])["ok"])
        screenshot.unlink()
        screenshot.symlink_to(business)
        self.assertFalse(cleanup([relative])["ok"])
        self.assertEqual(business.read_bytes(), b"business")
        screenshot.unlink()
        screenshot.write_bytes(b"review")
        result = cleanup([relative])
        self.assertTrue(result["ok"])
        self.assertEqual(result["bytes"], 6)
        self.assertFalse(screenshot.exists())

    def test_storage_breakdown_details_reconcile_with_inventory(self):
        self.classify("data/cc2api-runtime/bin/claude")
        self.classify("data/dossier-ui-review/completed-1440-light.png")
        self.classify("legal_kb.db-wal")
        with patch.object(main, "BASE_DIR", self.root), \
             patch.object(main, "DB_PATH", self.root / "legal_kb.db"), \
             patch.object(main, "UPLOAD_DIR", self.root / "uploads"), \
             patch.object(main, "ARTICLE_IMAGE_DIR", self.root / "article_images"):
            result = main.get_storage_info()
        self.assertEqual(result["total"], result["listed_total"])
        self.assertEqual(result["total"], 3)
        for item in result["items"]:
            if "files" in item:
                self.assertEqual(item["size"], sum(f["size"] for f in item["files"]))
                self.assertEqual(item["count"], len(item["files"]))
                self.assertTrue(all(f["cleanable"] == (item["raw"] == "review_artifacts") for f in item["files"]))

    def test_inventory_counts_external_data_sidecars_backups_and_overlaps_once(self):
        with tempfile.TemporaryDirectory() as external:
            ext = Path(external).resolve()
            files = {
                self.root / "article_images" / ".cache" / "page.png": 17,
                self.root / ".tmp" / "build" / "temp.txt": 7,
                self.root / ".tmp" / "other-worktree" / ".git": 11,
                self.root / ".tmp" / "other-worktree" / "frontend" / "unrelated.js": 19,
                self.root / "scheduled" / "databases" / "legal_kb-20261122-032000.db": 13,
                ext / "preferences" / "settings.json": 3,
                ext / "profile" / "custom.sqlite": 23,
                ext / "profile" / "custom.sqlite-wal": 31,
                ext / "profile" / "data" / "history_backups" / "progress.sqlite3": 37,
                ext / "services" / "uploads" / "document.pdf": 41,
                ext / "services" / "uploads" / "empty.txt": 0,
                ext / "services" / "court_online_service" / "browser-profile" / "Default" / "Cache" / "data": 43,
                ext / "services" / "court_online_service" / "browser-profile" / "Default" / "Cookies": 47,
            }
            for path, size in files.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"x" * size)
            (self.root / "linked-profile").symlink_to(ext / "profile", target_is_directory=True)
            with patch.multiple(main, BASE_DIR=self.root, DB_PATH=ext / "profile" / "custom.sqlite",
                                UPLOAD_DIR=ext / "services" / "uploads", ARTICLE_IMAGE_DIR=self.root / "article_images"), \
                 patch.dict(os.environ, {"LEGAL_KB_DATA_DIR": str(ext / "services"),
                                         "LEGAL_KB_CONFIG_DIR": str(ext / "preferences")}):
                report = main.get_storage_info()
                backup_files = main.get_history_backup_files(check_integrity=False)["files"]
            self.assertEqual(report["total"], sum(files.values()) - 30)
            self.assertEqual(report["total"], report["listed_total"])
            items = {row["raw"]: (row["size"], row["count"]) for row in report["items"]}
            self.assertEqual(items["project_config"], (3, 1))
            self.assertEqual(items["article_images"], (17, 1))
            self.assertEqual(items["scheduled_backups"], (13, 1))
            self.assertEqual(items["database_sidecars"], (31, 1))
            self.assertEqual(items["history_backups"], (37, 1))
            self.assertEqual(items["uploads"], (41, 2))
            self.assertEqual(items["browser_runtime_cache"], (43, 1))
            self.assertEqual(items["court_runtime_data"], (47, 1))
            self.assertEqual(report["file_types"], {".pdf": 1, ".txt": 1})
            self.assertEqual(backup_files[0]["name"], "progress.sqlite3")
            self.assertIsNone(backup_files[0]["created_at"])

    def test_history_rejects_changed_records_aliases_and_configured_live_database(self):
        directory = self.root / "data" / "history_backups"
        directory.mkdir(parents=True)
        backup = directory / "before-source-start-20261122-112233-0a0b0c.db"
        backup.write_bytes(b"backup")
        live = directory / "active.db"
        live.write_bytes(b"database")
        alias = directory / "alias.db"
        alias.symlink_to(backup)
        def delete(paths, revisions=None):
            request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), json=AsyncMock(
                return_value={"type": "history_backup_files", "paths": paths, "revisions": revisions}))
            return asyncio.run(main.cleanup_storage(request))
        with patch.multiple(main, BASE_DIR=self.root, DB_PATH=live):
            inventory = main.get_history_backup_files(check_integrity=False)
            self.assertEqual([file["name"] for file in inventory["files"]], [backup.name])
            self.assertEqual(inventory["files"][0]["display_name"], "应用更新前备份")
            self.assertEqual(inventory["files"][0]["created_at"], "2026-11-22 11:22:33")
            for blocked in (live, alias):
                self.assertFalse(delete([str(backup), str(blocked)])["ok"])
                self.assertTrue(backup.exists())
            self.assertFalse(delete([str(backup)], {str(backup): "old-revision"})["ok"])
            result = delete([str(backup), str(backup)], {str(backup): backup_revision(backup.stat())})
            self.assertEqual(result["count"], 1)
            self.assertEqual(result["bytes"], 6)
            self.assertTrue(live.exists())

    def test_cache_cleanup_uses_inventory_and_keeps_protected_data(self):
        with patch.multiple(main, BASE_DIR=self.root, DB_PATH=self.root / "legal_kb.db",
                            UPLOAD_DIR=self.root / "uploads", ARTICLE_IMAGE_DIR=self.root / "article_images"):
            for rel in ("backend/__pycache__/main.pyc", "article_images/.cache/original.png",
                        "pending_tasks.db", "legal_knowledge.db"):
                self.classify(rel)
            before = main.get_storage_info()
            request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), json=AsyncMock())
            for cleanup_type in ("pending_tasks.db", "legacy_databases"):
                request.json.return_value = {"type": cleanup_type}
                self.assertFalse(asyncio.run(main.cleanup_storage(request))["ok"])
            request.json.return_value = {"type": "safe_cache"}
            result = asyncio.run(main.cleanup_storage(request))
            self.assertTrue(result["ok"])
            self.assertEqual(result["bytes"], 1)
            self.assertEqual(before["total"] - main.get_storage_info()["total"], 1)
            self.assertTrue((self.root / "article_images" / ".cache" / "original.png").exists())
            self.assertTrue((self.root / "pending_tasks.db").exists())
            self.assertTrue((self.root / "legal_knowledge.db").exists())

    def test_upload_metadata_files_are_not_user_uploads(self):
        contract = self.root / "contract.pdf"
        contract.write_bytes(b"x")
        self.assertTrue(_storage_is_upload_file(contract))
        self.assertFalse(_storage_is_upload_file(self.root / ".DS_Store"))
        self.assertFalse(_storage_is_upload_file(self.root / "contract.pyc"))

    def test_upload_associations_use_exact_paths_and_safe_unique_fallbacks(self):
        uploads = self.root / "uploads"
        first = uploads / "2026" / "contract.pdf"
        second = uploads / "2027" / "contract.pdf"
        unique = uploads / "unique.pdf"
        for path in (first, second, unique):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, title TEXT, source_localpath TEXT, source_filename TEXT)")
        conn.executemany(
            "INSERT INTO articles (id, title, source_localpath, source_filename) VALUES (?, ?, ?, ?)",
            [
                (1, "精确路径", str(first), "contract.pdf"),
                (2, "旧式唯一文件名", None, "unique.pdf"),
                (3, "重名无法判断", None, "contract.pdf"),
            ],
        )
        conn.commit()
        associations = _storage_upload_associations([first, second, unique], uploads, self.root, conn)
        conn.close()

        self.assertEqual(associations[first.resolve()]["ids"], {1})
        self.assertEqual(associations[unique.resolve()]["ids"], {2})
        self.assertEqual(associations[second.resolve()]["ids"], set())
        self.assertTrue(associations[first.resolve()]["ambiguous"])
        self.assertTrue(associations[second.resolve()]["ambiguous"])


if __name__ == "__main__":
    unittest.main()
