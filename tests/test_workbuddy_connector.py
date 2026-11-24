import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.database import connect_database
from backend.workbuddy_connector import SCOPES, create_router


class WorkBuddyConnectorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.runtime = Path(temporary.name)
        self.config = self.runtime / "mcp.json"
        self.original = {"mcpServers": {"other": {"type": "stdio", "command": "fixture"}}, "settings": {"check": True}}
        self.config.write_text(json.dumps(self.original), encoding="utf-8")
        self.pairing = self.runtime / "data" / "workbuddy-connector" / "connection.json"
        self.database = self.runtime / "fictional.db"
        with sqlite3.connect(self.database) as conn:
            conn.executescript("""
                CREATE TABLE case_manager_cases (
                    id INTEGER, title TEXT, series_display_name TEXT, series_code TEXT, case_type TEXT,
                    current_stage TEXT, source_status TEXT, case_kind TEXT, parent_series_id INTEGER, memo TEXT
                );
                CREATE TABLE case_manager_case_numbers (id INTEGER, case_id INTEGER, case_no TEXT, court TEXT, sort_order INTEGER);
                CREATE TABLE case_manager_hearings (id INTEGER, case_id INTEGER, reminder_type TEXT, hearing_at TEXT, notes TEXT);
                CREATE TABLE case_manager_todos (
                    id INTEGER, case_id INTEGER, title TEXT, todo_title TEXT, remind_at TEXT, status TEXT, notes TEXT
                );
                CREATE TABLE articles (id INTEGER, title TEXT, content TEXT);
                CREATE TABLE notes (id INTEGER, article_id INTEGER, content TEXT, selected_text TEXT, created_at TEXT);
                CREATE TABLE case_manager_local_file_index (
                    id INTEGER, case_id INTEGER, display_name TEXT, extracted_text TEXT, absolute_path TEXT
                );
                INSERT INTO articles VALUES (8,'测试文章','这是全文。');
                INSERT INTO notes VALUES (1,8,'测试笔记','原文','2099-12-01');
                INSERT INTO notes VALUES (2,88,'孤立笔记','原文','2099-12-01');
                INSERT INTO case_manager_local_file_index VALUES
                    (1,1,'测试文档','可供读取的索引正文','/fictional-only/private.pdf'),
                    (2,2,'已删除案件文档','不应看到的正文','/fictional-only/deleted.pdf');
                INSERT INTO case_manager_cases VALUES
                    (1,'示例合同争议','',NULL,'合同','一审','active','ordinary',NULL,'敏感备注'),
                    (2,'示例删除事项','','DEL','合同','二审','deleted','ordinary',NULL,'敏感备注'),
                    (3,'示例子案','样例简称','A017','合同','一审','active','series_child',4,'敏感备注'),
                    (4,'示例系列','','','合同','一审','active','series',NULL,''),
                    (5,'示例归档','','ARC','合同','一审','archived','ordinary',NULL,'');
                INSERT INTO case_manager_case_numbers VALUES (1,1,'（2099）示例01号','示例法院',0);
                INSERT INTO case_manager_hearings VALUES
                    (1,1,'开庭','2099-12-09 09:00','敏感备注'),
                    (2,3,'开庭','2099-12-02 09:00','敏感备注'),
                    (3,2,'开庭','2099-12-03 09:00','敏感备注');
                INSERT INTO case_manager_todos VALUES
                    (1,1,'已办待办','已完成事项','2099-12-10','completed','敏感备注'),
                    (2,1,'示例待办','准备目录','2099-12-12','pending','敏感备注'),
                    (3,NULL,'独立待办','分类测试样稿',NULL,'pending','敏感备注');
            """)
        app = FastAPI()
        app.include_router(create_router(
            self.runtime, self.get_db, self.list_articles, lambda value: value, workbuddy_config=self.config
        ))
        self.origin = "http://127.0.0.1:17650"
        self.client = TestClient(app, base_url=self.origin, client=("127.0.0.1", 49200))
        self.addCleanup(self.client.close)

    def get_db(self):
        return connect_database(self.database)

    def list_articles(self, **params):
        self.assertEqual(params, {"q": "示例检索", "page": 1, "page_size": 5})
        with self.assertRaisesRegex(sqlite3.OperationalError, "readonly"):
            self.get_db().execute("DELETE FROM case_manager_cases")
        return {"articles": [{"id": 8, "title": "测试文章", "summary": "备用摘要",
                              "source_localpath": "/fictional-only/secret", "content_snippets": [{"text": "实际命中"}]}]}

    def enable(self, **permissions):
        response = self.client.put("/api/workbuddy/settings", headers={"Origin": self.origin}, json=permissions)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def call(self, tool, arguments, token=None, **extra_headers):
        token = json.loads(self.pairing.read_bytes())["token"] if token is None else token
        return self.client.post("/api/workbuddy/call", headers={"Authorization": f"Bearer {token}", **extra_headers},
                                json={"name": tool, "arguments": arguments})

    def test_setup_permissions_and_revoke(self):
        self.assertFalse(self.pairing.exists())
        self.assertEqual(self.client.put("/api/workbuddy/settings", json={}).status_code, 403)
        self.assertEqual(self.client.put("/api/workbuddy/settings", headers={"Origin": "http://outside.invalid"}, json={}).status_code, 403)
        self.assertTrue(self.enable()["registered"])
        configured = json.loads(self.config.read_bytes())
        self.assertEqual(configured["settings"], self.original["settings"])
        self.assertEqual(configured["mcpServers"]["other"], self.original["mcpServers"]["other"])
        old_token = json.loads(self.pairing.read_bytes())["token"]
        self.assertNotIn(old_token, self.config.read_text())
        self.assertEqual(self.call("stella_get_case", {"case_id": 1}).status_code, 403)
        self.assertEqual(self.call("stella_search_knowledge", {"query": "示例检索"}, token="wrong").status_code, 401)
        self.assertEqual(self.call("stella_search_knowledge", {"query": "示例检索"}, Origin=self.origin).status_code, 403)
        self.assertEqual(self.call("stella_search_knowledge", {"query": "示例检索"},
                                   **{"X-Forwarded-For": "127.0.0.1"}).status_code, 403)
        result = self.call("stella_search_knowledge", {"query": "示例检索"}).json()
        self.assertEqual(result["items"][0], {"type": "article", "title": "测试文章", "excerpt": "实际命中",
                                               "open_in_stella": f"{self.origin}/?open_article=8"})
        self.assertEqual(self.client.delete("/api/workbuddy/settings", headers={"Origin": self.origin}).status_code, 200)
        self.assertEqual(self.call("stella_get_case", {"case_id": 1}, token=old_token).status_code, 401)
        self.enable(cases=True)
        self.assertNotEqual(json.loads(self.pairing.read_bytes())["token"], old_token)

    def test_case_and_schedule_only_project_allowed_fields(self):
        self.enable(knowledge=False, cases=True, schedule=True)
        self.assertEqual(self.call("stella_find_cases", {"query": "A017"}).json()["items"][0]["case_id"], 3)
        self.assertEqual(self.call("stella_find_cases", {"query": "(2099)示例01号"}).json()["items"][0]["case_id"], 1)
        self.assertEqual(self.call("stella_find_cases", {"query": "%"}).json()["items"], [])
        self.assertEqual(self.call("stella_find_cases", {"query": "DEL"}).json()["items"], [])
        case = self.call("stella_get_case", {"case_id": 1}).json()
        self.assertEqual(case["case_numbers"], [{"number": "（2099）示例01号", "court": "示例法院"}])
        self.assertNotIn("memo", case)
        self.assertEqual(self.call("stella_get_case", {"case_id": 2}).status_code, 404)
        schedule = self.call("stella_list_schedule", {"case_id": 1}).json()["items"]
        self.assertEqual([item["title"] for item in schedule], ["开庭", "准备目录"])
        self.assertNotIn("notes", schedule[0])
        self.assertEqual(self.call("stella_list_schedule", {"case_id": 4}).json()["items"][0]["case_id"], 3)
        self.assertEqual(len(self.call("stella_list_schedule", {"start_date": "2099-12-09",
                                                               "end_date": "2099-12-09"}).json()["items"]), 1)
        self.assertEqual(self.call("stella_list_schedule", {"start_date": "2099-12-30",
                                                           "end_date": "2099-12-09"}).status_code, 422)

    def test_extended_grants_preserve_legacy_defaults_and_block_ungranted_types(self):
        self.enable()
        state = json.loads(self.pairing.read_text())
        state["permissions"] = {"knowledge": True, "cases": True, "schedule": True}
        self.pairing.write_text(json.dumps(state))
        permissions = self.client.get("/api/workbuddy/settings").json()["permissions"]
        self.assertEqual(set(permissions), set(SCOPES))
        self.assertFalse(permissions["article_details"])
        self.assertEqual(self.call("stella_list_readable_data", {}).json()["data_types"], [])
        self.assertEqual(self.call("stella_read_records", {"type": "article_notes"}).status_code, 403)
        authorized = self.enable(**{scope: True for scope in SCOPES})
        self.assertTrue(all(authorized["permissions"].values()))
        self.assertIn("article_notes", [r["type"] for r in self.call("stella_list_readable_data", {}).json()["data_types"]])
        notes = self.call("stella_read_records", {"type": "article_notes", "article_id": 8}).json()["items"]
        self.assertEqual([item["content"] for item in notes], ["测试笔记"])
        text = self.call("stella_read_records", {"type": "article_text", "record_id": 8}).json()
        self.assertEqual(text["text"], "这是全文。")
        file_text = self.call("stella_read_records", {"type": "indexed_file_text", "record_id": 1}).json()
        self.assertNotIn("/fictional-only/", json.dumps(file_text))
        self.assertEqual(self.call("stella_read_records", {"type": "indexed_file_text", "record_id": 2}).status_code, 404)
        self.assertEqual(self.call("stella_read_records", {"type": "auth"}).status_code, 422)
        self.enable(article_details=True)
        self.assertEqual(self.call("stella_read_records", {"type": "indexed_file_text", "record_id": 1}).status_code, 403)

    def test_schedule_count_includes_all_active_rows_by_month(self):
        self.enable(schedule=True)
        with self.get_db() as conn:
            conn.executemany("INSERT INTO case_manager_hearings VALUES (?,1,'开庭','2099-11-23','')",
                             [(index,) for index in range(10, 35)])
        counts = self.call("stella_list_schedule", {"kind": "hearing", "count_only": True, "group_by": "month"}).json()
        self.assertEqual(counts["total"], 27)
        self.assertEqual([(group["month"], group["count"]) for group in counts["by_type"]],
                         [("2099-11", 25), ("2099-12", 2)])

    def test_open_desktop_app_requires_same_origin_and_returns_launch_errors(self):
        path = "/api/workbuddy/open"
        with patch("backend.workbuddy_connector._open_workbuddy") as launch:
            self.assertEqual(self.client.post(path).status_code, 403)
            self.assertEqual(self.client.post(path, headers={"Origin": "http://outside.invalid"}).status_code, 403)
            launch.assert_not_called()
            self.assertEqual(self.client.post(path, headers={"Origin": self.origin}).json(), {"opened": True})
            launch.assert_called_once_with()
            launch.side_effect = OSError
            self.assertEqual(self.client.post(path, headers={"Origin": self.origin}).status_code, 409)
        self.assertFalse(self.pairing.exists())

    def test_registration_leaves_unrecognized_and_other_installation_config_intact(self):
        unrecognized = b'// Preserve existing settings format\n{}'
        self.config.write_bytes(unrecognized)
        self.assertFalse(self.enable()["registered"])
        self.assertEqual(self.config.read_bytes(), unrecognized)
        foreign = {"mcpServers": {"stella-local": {"type": "stdio", "command": "fixture", "args": ["other"]}}}
        self.config.write_text(json.dumps(foreign), encoding="utf-8")
        self.assertFalse(self.enable()["registered"])
        self.assertEqual(json.loads(self.config.read_bytes()), foreign)
