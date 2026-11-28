"""Exercise the registered research and authority APIs against a disposable database."""

from contextlib import ExitStack
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch
from zipfile import ZipFile

from fastapi.testclient import TestClient

from backend import main, series_manager


class ResearchRouteTests(unittest.TestCase):
    def setUp(self):
        fixtures = ExitStack()
        self.addCleanup(fixtures.close)
        directory = fixtures.enter_context(TemporaryDirectory())
        fixtures.enter_context(patch.object(main, "DB_PATH", Path(directory) / "research.db"))
        main.init_db()
        series_manager.ensure_series_schema(main.get_db)
        main._SOURCE_MONITOR.refresh()
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)
        with main.get_db() as conn:
            self.case_id = conn.execute(
                "INSERT INTO case_manager_cases (title, created_at, updated_at) VALUES (?, ?, ?)",
                ("匿名案件", "2026-01-01", "2026-01-01"),
            ).lastrowid

    def request(self, method, path, **kwargs):
        response = self.client.request(method, path, **kwargs)
        self.assertEqual(response.status_code, 200, response.text[:300])
        return response

    def test_case_snapshot_and_exports_share_project_data(self):
        project = self.request("POST", "/api/research-projects", json={
            "case_id": self.case_id, "name": "匿名研究项目",
        }).json()["project"]
        project_id = project["id"]
        case = f"/api/case-research/cases/{self.case_id}"
        for index in range(3):
            article_id = main.save_article(
                f"匿名文章{index}", f"正文测试{index}", "测试摘要", [], "url",
                source_url=f"https://example.org/article/{index}",
            )
            linked = self.request("POST", f"{case}/articles/{article_id}").json()
            self.assertEqual(linked["project_id"], project_id)
        body = {"question": "匿名问题", "answer": "匿名答案", "source_ref": "fixture:one"}
        first = self.request("POST", f"{case}/questions/import", json=body).json()
        repeated = self.request("POST", f"{case}/questions/import", json=body).json()
        self.assertEqual(first["question_id"], repeated["question_id"])
        self.assertTrue(repeated["already_linked"])
        ledgers = f"/api/case-research/projects/{project_id}/ledgers"
        self.request("POST", ledgers, json={"title": "匿名台账", "content": "<p>台账正文</p>"})
        detail = self.request("GET", case).json()
        self.assertEqual(len(detail["articles"]), 3)
        self.assertNotIn("resources_json", detail["ledgers"][0])
        snapshot = self.request("GET", "/api/case-research/offline-snapshot").json()
        self.assertIn(str(self.case_id), snapshot["details"])

        package = self.request("GET", f"{case}/articles/export")
        with ZipFile(BytesIO(package.content)) as archive:
            self.assertEqual(sum(name.endswith(".docx") for name in archive.namelist()), 3)
        workbook = self.request("GET", f"{case}/ledgers/export")
        with ZipFile(BytesIO(workbook.content)) as archive:
            self.assertIn("xl/worksheets/sheet1.xml", archive.namelist())
        for path in (
            f"/api/research-projects/{project_id}/questions/export",
            f"/api/research-project-questions/{first['question_id']}/export",
        ):
            self.assertIn("匿名答案", self.request("GET", path).content.decode("utf-8-sig"))
        document = self.request("GET", path + "?format=docx")
        with ZipFile(BytesIO(document.content)) as archive:
            self.assertIn("匿名答案", archive.read("word/document.xml").decode())

    def test_watch_import_can_attach_to_project_and_schedule_summary(self):
        project = self.request("POST", "/api/research-projects", json={"name": "匿名订阅研究"}).json()["project"]
        prefix = "/api/authority-watch"
        task = self.request("POST", f"{prefix}/tasks", json={"name": "匿名订阅", "enabled": 0}).json()
        updated = self.request("PUT", f"{prefix}/tasks/{task['id']}", json={
            "name": "修改后的订阅", "enabled": 0,
        }).json()
        self.assertEqual(updated["name"], "修改后的订阅")
        runner = AsyncMock(return_value={"success": True})
        with patch.object(main, "_run_radar_task", runner):
            self.assertTrue(self.request("POST", f"{prefix}/tasks/{task['id']}/run").json()["success"])
        runner.assert_awaited_once_with(task["id"])
        with main.get_db() as conn:
            result = conn.execute(
                "INSERT INTO authority_watch_results (task_id, title, url, content_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                (task["id"], "匿名权威动态", "https://example.org/watch", "fixture-hash", "2026-01-01"),
            ).lastrowid
        content = "这是一段用于验证摘要调度的匿名测试正文，包含合同履行、争议焦点和证据说明。" * 6
        summary = AsyncMock()
        with patch.object(main, "fetch_webpage", return_value={"content": content}), \
             patch.object(main, "_generate_and_store_ai_summary", summary):
            self.request("POST", f"{prefix}/results/{result}/add-to-project", data={"project_id": project["id"]})
            imported = self.request("POST", f"{prefix}/results/{result}/import").json()
        self.assertTrue(imported["already_imported"])
        summary.assert_awaited_once()
        linked = self.request("GET", f"/api/research-projects/{project['id']}").json()["articles"]
        self.assertEqual([(row["id"], row["added_from"]) for row in linked],
                         [(imported["article_id"], "authority_watch")])
