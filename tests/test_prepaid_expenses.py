import asyncio
import io
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import openpyxl
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import prepaid_expenses
from backend.prepaid_expenses import FeishuExpenseSync, ensure_prepaid_expense_schema, register_prepaid_expense_routes


BASE_SCHEMA = """
CREATE TABLE case_manager_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    source_status TEXT DEFAULT 'active',
    created_at TEXT DEFAULT '',
    updated_at TEXT DEFAULT ''
);
"""


class PrepaidExpenseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "prepaid.db"
        self.config_path = Path(self.temp_dir.name) / "feishu.json"
        conn = sqlite3.connect(self.db_path)
        conn.executescript(BASE_SCHEMA)
        conn.execute("INSERT INTO case_manager_cases(title) VALUES ('大广案')")
        conn.commit()
        conn.close()

        def get_db():
            database = sqlite3.connect(self.db_path)
            database.row_factory = sqlite3.Row
            database.execute("PRAGMA foreign_keys=ON")
            return database

        self.get_db = get_db
        self.config_patch = patch.object(prepaid_expenses, "CONFIG_PATH", self.config_path)
        self.config_patch.start()
        app = FastAPI()
        register_prepaid_expense_routes(app, get_db)
        self.client = TestClient(app)

    def tearDown(self):
        self.config_patch.stop()
        self.temp_dir.cleanup()

    def create_item(self, **overrides):
        payload = {
            "occurred_on": "2026-08-03",
            "entry_type": "expense",
            "project_name": "大广案",
            "category": "快递邮寄/跑腿",
            "description": "文件快递费",
            "amount": "12.50",
        }
        payload.update(overrides)
        response = self.client.post("/api/case-manager/prepaid-expenses", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_crud_summary_and_negative_balance(self):
        advance = self.create_item(
            occurred_on="2026-08-01", entry_type="advance", project_name="", category="",
            description="团队转入", amount="10000.00",
        )
        expense = self.create_item(amount="12000.00")
        response = self.client.get("/api/case-manager/prepaid-expenses")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["summary"]["advance"], 10000)
        self.assertEqual(data["summary"]["expense"], 12000)
        self.assertEqual(data["summary"]["balance"], -2000)
        self.assertEqual(data["items"][0]["running_balance"], -2000)
        self.assertEqual(data["items"][1]["running_balance"], 10000)
        self.assertEqual(data["items"][0]["case_id"], 1)

        updated = self.client.put(
            f"/api/case-manager/prepaid-expenses/{expense['id']}",
            json={**expense, "amount": "8000.00"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(self.client.get("/api/case-manager/prepaid-expenses").json()["summary"]["balance"], 2000)
        deleted = self.client.delete(f"/api/case-manager/prepaid-expenses/{advance['id']}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get("/api/case-manager/prepaid-expenses").json()["summary"]["balance"], -8000)

    def test_validation_and_filters(self):
        missing = self.client.post(
            "/api/case-manager/prepaid-expenses",
            json={"entry_type": "expense", "amount": "10", "description": ""},
        )
        self.assertEqual(missing.status_code, 400)
        precision = self.client.post(
            "/api/case-manager/prepaid-expenses",
            json={"entry_type": "advance", "amount": "1.001"},
        )
        self.assertEqual(precision.status_code, 400)
        self.create_item(category="交通出行", description="佛山开庭交通费", amount="80")
        self.create_item(category="快递邮寄/跑腿", description="顺丰", amount="20")
        filtered = self.client.get("/api/case-manager/prepaid-expenses", params={"category": "交通出行", "q": "佛山"})
        self.assertEqual(len(filtered.json()["items"]), 1)
        self.assertEqual(filtered.json()["summary"]["expense"], 100)

    def test_editable_categories_and_advance_ignores_project(self):
        response = self.client.put(
            "/api/case-manager/prepaid-expenses/categories",
            json={"categories": ["交通出行", "自定义专项", "其他"]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["categories"], ["交通出行", "自定义专项", "其他"])
        saved = self.create_item(category="自定义专项", description="专项费用", amount="30")
        self.assertEqual(saved["category"], "自定义专项")
        advance = self.create_item(
            entry_type="advance", project_name="不应保留的项目", category="",
            description="团队预支", amount="1000",
        )
        self.assertEqual(advance["project_name"], "")

    def test_excel_export_contains_auditable_formulas(self):
        self.create_item(occurred_on="2026-08-02", amount="12.50")
        self.create_item(
            occurred_on="2026-08-01", entry_type="advance", category="", description="团队预支", amount="1000",
        )
        response = self.client.get("/api/case-manager/prepaid-expenses/export")
        self.assertEqual(response.status_code, 200, response.text)
        workbook = openpyxl.load_workbook(io.BytesIO(response.content), data_only=False)
        sheet = workbook["团队备用金使用记录"]
        self.assertEqual(sheet["A2"].value, "收支时间")
        self.assertEqual(sheet["J2"].value, "余额")
        self.assertEqual(sheet["G3"].value, "=SUM(F3:F$4)")
        self.assertEqual(sheet["I3"].value, "=SUM(H3:H$4)")
        self.assertEqual(sheet["J3"].value, "=I3-G3")
        self.assertEqual(sheet["G4"].value, "=SUM(F4:F$4)")
        self.assertEqual(sheet.freeze_panes, "A3")
        self.assertEqual(sheet.auto_filter.ref, "A2:J4")
        self.assertEqual(sheet["A3"].data_type, "d")
        self.assertIsInstance(sheet["F3"].value, (int, float))
        self.assertIsInstance(sheet["H4"].value, (int, float))

    def test_settings_route_precedes_integer_record_route(self):
        response = self.client.put(
            "/api/case-manager/prepaid-expenses/feishu-settings",
            json={
                "app_id": "cli_test",
                "app_secret": "secret-value",
                "base_url": "https://example.feishu.cn/base/appToken123?table=tbl123",
                "form_url": "https://example.feishu.cn/share/base/form/test",
                "verify": False,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["configured"])
        self.assertNotIn("secret-value", response.text)
        self.assertEqual(os.stat(self.config_path).st_mode & 0o777, 0o600)

    def test_editable_description_presets(self):
        response = self.client.put(
            "/api/case-manager/prepaid-expenses/presets",
            json={
                "expense": ["文件快递费", "打印费"],
                "advance": ["团队转入备用金"],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["presets"]["expense"], ["文件快递费", "打印费"])
        loaded = self.client.get("/api/case-manager/prepaid-expenses").json()
        self.assertEqual(loaded["presets"]["advance"], ["团队转入备用金"])

    def test_settings_returns_readable_feishu_error_instead_of_500(self):
        with patch.object(
            FeishuExpenseSync,
            "verify",
            new=AsyncMock(side_effect=RuntimeError("飞书应用身份权限未生效（错误码 99991672）")),
        ):
            response = self.client.put(
                "/api/case-manager/prepaid-expenses/feishu-settings",
                json={
                    "app_id": "cli_test",
                    "app_secret": "secret-value",
                    "base_url": "https://example.feishu.cn/base/appToken123?table=tbl123",
                    "verify": True,
                },
            )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("99991672", response.json()["detail"])

    def test_settings_rejects_share_link(self):
        response = self.client.put(
            "/api/case-manager/prepaid-expenses/feishu-settings",
            json={
                "app_id": "cli_test",
                "app_secret": "secret-value",
                "base_url": "https://example.feishu.cn/share/base/view/share-token",
                "verify": False,
            },
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("分享链接", response.json()["detail"])

    def test_feishu_sync_is_idempotent_and_marks_invalid_rows(self):
        class FakeSync(FeishuExpenseSync):
            def __init__(self, get_db):
                super().__init__(get_db)
                self.records = []
                self.updates = []

            async def _access_token(self, client, config):
                return "token"

            async def _records(self, client, token, config):
                return self.records

            async def _writeback(self, client, token, config, updates):
                self.updates.extend(updates)

        self.config_path.write_text(
            '{"app_id":"cli_test","app_secret":"secret","app_token":"app","table_id":"table"}',
            encoding="utf-8",
        )
        syncer = FakeSync(self.get_db)
        with self.get_db() as conn:
            conn.execute(
                "INSERT INTO case_manager_prepaid_sync_issues VALUES (?,?,?,?)",
                ("rec_deleted_remote", "old", "旧错误", "2026-08-03T00:00:00+08:00"),
            )
            conn.commit()
        syncer.records = [
            {
                "record_id": "rec_valid",
                "created_time": 1785686400000,
                "fields": {"流水类型": "团队预支", "发生日期": None, "金额": 10000, "同步状态": ""},
            },
            {
                "record_id": "rec_invalid",
                "created_time": 1785686400000,
                "fields": {"流水类型": "支出", "金额": 80, "支出内容/说明": "", "同步状态": ""},
            },
            {
                "record_id": "rec_example_marker",
                "created_time": 1785686400000,
                "fields": {
                    "流水类型": "支出", "金额": 20, "支出内容/说明": "打印纸",
                    "支出分类": "办公费", "同步状态": "已同步", "本地记录编号": "LZ20260803001",
                },
            },
            {
                "record_id": "rec_deleted_local",
                "created_time": 1785686400000,
                "fields": {
                    "流水类型": "支出", "金额": 30, "支出内容/说明": "不应重新导入",
                    "同步状态": "已同步", "本地记录编号": "999",
                },
            },
        ]
        first = asyncio.run(syncer.sync())
        self.assertTrue(first["ok"])
        self.assertEqual(first["imported"], 2)
        self.assertEqual(first["invalid"], 1)
        second = asyncio.run(syncer.sync())
        self.assertTrue(second["ok"])
        with self.get_db() as conn:
            count = conn.execute("SELECT COUNT(*) FROM case_manager_prepaid_expenses").fetchone()[0]
            item = conn.execute("SELECT occurred_on FROM case_manager_prepaid_expenses").fetchone()
            issue_ids = {
                row["source_record_id"]
                for row in conn.execute("SELECT source_record_id FROM case_manager_prepaid_sync_issues").fetchall()
            }
        self.assertEqual(count, 2)
        self.assertEqual(item["occurred_on"], "2026-08-03")
        self.assertEqual(issue_ids, {"rec_invalid"})
        self.assertIn("办公费", _categories := self.client.get(
            "/api/case-manager/prepaid-expenses/categories"
        ).json()["categories"])
        statuses = [update["fields"].get("同步状态") for update in syncer.updates]
        self.assertIn("已同步", statuses)
        self.assertIn("需修正", statuses)

        # Removing a Feishu row never removes an already imported local ledger row.
        syncer.records = []
        removed_remote = asyncio.run(syncer.sync())
        self.assertTrue(removed_remote["ok"])
        with self.get_db() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM case_manager_prepaid_expenses").fetchone()[0], 2
            )

    def test_case_titles_drive_feishu_project_options(self):
        with self.get_db() as conn:
            conn.execute("INSERT INTO case_manager_cases(title,source_status) VALUES ('第二案件','active')")
            conn.execute("INSERT INTO case_manager_cases(title,source_status) VALUES ('已归档案件','archived')")
            conn.commit()

        class ProjectSync(FeishuExpenseSync):
            def __init__(self, get_db):
                super().__init__(get_db)
                self.updates = []

            async def _fields(self, client, token, config):
                return [
                    {"field_id": "fld_project", "field_name": "对应项目", "type": 1, "property": None},
                    {
                        "field_id": "fld_type", "field_name": "流水类型", "type": 3,
                        "property": {"options": [{"id": "old1", "name": "支出"}, {"id": "old2", "name": "团队预支"}]},
                    },
                ]

            async def _update_select_field(self, client, token, config, field, desired_names, aliases=None):
                self.updates.append((field["field_name"], desired_names, aliases or {}))
                return True

        syncer = ProjectSync(self.get_db)
        result = asyncio.run(syncer._sync_project_options_with_client(
            None, "token", {"app_token": "app", "table_id": "table"}, True
        ))
        self.assertTrue(result["ok"])
        project_update = next(update for update in syncer.updates if update[0] == "对应项目")
        self.assertIn("大广案", project_update[1])
        self.assertIn("第二案件", project_update[1])
        self.assertNotIn("已归档案件", project_update[1])
        type_update = next(update for update in syncer.updates if update[0] == "流水类型")
        self.assertEqual(type_update[1], ["团队支出", "团队备用金"])


if __name__ == "__main__":
    unittest.main()
