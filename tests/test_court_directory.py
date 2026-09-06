import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.court_directory import register_court_directory_routes


class CourtDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "directory.db"

        def get_db():
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            return conn

        self.get_db = get_db
        app = FastAPI()
        register_court_directory_routes(app, get_db, Path(self.temp_dir.name))
        self.client = TestClient(app)

    def tearDown(self):
        self.temp_dir.cleanup()

    def import_entries(self, entries):
        with self.get_db() as conn:
            cur = conn.execute(
                """INSERT INTO court_directory_import_batches
                   (url,title,raw_text,published_at,status,extraction_json,created_at)
                   VALUES(?,?,?,?,?,?,?)""",
                ("https://example.com/%s" % len(entries), "样例", "", "2026-01-01", "preview", json.dumps(entries, ensure_ascii=False), "2026-01-02"),
            )
            conn.commit()
        response = self.client.post(f"/api/court-directory/import-batches/{cur.lastrowid}/confirm")
        self.assertEqual(response.status_code, 200, response.text)

    def test_same_name_isolated_by_court_and_department_contact_kept(self):
        self.import_entries([
            {"court": "广州市中级人民法院", "department": "民一庭", "name": "示七某", "position": "法官", "phone": "13800000500"},
            {"court": "深圳市中级人民法院", "department": "民一庭", "name": "示七某", "position": "法官", "phone": "13900000800"},
            {"court": "广州市中级人民法院", "department": "执行局", "name": "", "position": "", "phone": "020-12345678"},
        ])
        items = self.client.get("/api/court-directory/contacts?q=示七某").json()["items"]
        self.assertEqual(len(items), 2)
        self.assertEqual(len({item["court_id"] for item in items}), 2)
        department = self.client.get("/api/court-directory/contacts?q=执行局").json()["items"]
        self.assertEqual(department[0]["entity_kind"], "department")

    def test_history_is_preserved_and_manual_status_overrides_default_search(self):
        self.import_entries([
            {"court": "广州市中级人民法院", "department": "民一庭", "name": "李四", "position": "法官", "phone": "13800000500"},
            {"court": "广州市中级人民法院", "department": "民二庭", "name": "李四", "position": "法官", "phone": "13900000800"},
        ])
        person = self.client.get("/api/court-directory/contacts?q=李四").json()["items"][0]
        detail = self.client.get(f"/api/court-directory/people/{person['person_id']}").json()
        self.assertEqual(len(detail["contacts"]), 2)
        self.assertEqual(len(detail["affiliations"]), 2)
        first_contact = detail["contacts"][0]["id"]
        response = self.client.put("/api/court-directory/status", json={"target_kind": "contact", "target_id": first_contact, "status": "invalid"})
        self.assertEqual(response.status_code, 200)
        visible = self.client.get("/api/court-directory/contacts?q=李四").json()["items"]
        self.assertEqual(len(visible), 1)
        visible_response = self.client.get("/api/court-directory/contacts?q=李四").json()
        self.assertEqual(visible_response["total"], 1)
        historical_response = self.client.get("/api/court-directory/contacts?q=李四&include_history=true").json()
        historical = historical_response["items"]
        # 列表按人员归集，同一人员的历史号码在详情时间线中保留。
        self.assertEqual(len(historical), 1)
        self.assertEqual(historical_response["total"], 1)
        detail_after = self.client.get(f"/api/court-directory/people/{person['person_id']}").json()
        self.assertEqual(len(detail_after["contacts"]), 2)

    def test_unknown_court_in_case_or_import_text_never_creates_tree_node(self):
        self.import_entries([
            {"court": "2026年3月20日收到材料", "department": "", "name": "示七某", "position": "法官", "phone": "13800000500"},
        ])
        courts = self.client.get("/api/court-directory/courts").json()["items"]
        self.assertFalse(any(item["name"] == "2026年3月20日收到材料" for item in courts))
        self.assertEqual(self.client.get("/api/court-directory/contacts?q=示七某").json()["items"], [])

    def test_line_based_wechat_directory_pairs_names_with_the_following_phone_only(self):
        raw = """广州市中级人民法院通讯录
立案庭（诉讼服务中心）
内勤组
组长
车莉
83210306
法官助理
刘莹莹
83210285
刑事审判第一庭
内勤组
王智
83210341
刑一庭外线
83210400"""
        response = self.client.post("/api/court-directory/import-preview", json={
            "raw_text": raw,
            "court": "广州市中级人民法院",
        })
        self.assertEqual(response.status_code, 200, response.text)
        entries = response.json()["entries"]
        self.assertEqual(
            {(item["name"], item["phone"]) for item in entries},
            {("车莉", "83210306"), ("刘莹莹", "83210285"), ("王智", "83210341")},
        )
        self.assertTrue(all(item["department"] in {"立案庭", "刑事审判第一庭"} for item in entries))

    def test_table_directory_uses_external_phone_and_applies_title_department(self):
        raw = """刑庭通讯录
姓名 | 外线电话 | 内线电话
杨扬 | 81852023 | 82023
杨虹虹 | 81852019 | 82019
姚莉雅 | 81852029 | 82029
潘巧茹〔内勤〕 | 81852028 | 82028
"""
        response = self.client.post("/api/court-directory/import-preview", json={
            "raw_text": raw,
            "court": "佛山市南海区人民法院",
        })
        self.assertEqual(response.status_code, 200, response.text)
        entries = response.json()["entries"]
        self.assertEqual(
            [(item["name"], item["phone"]) for item in entries],
            [("杨扬", "81852023"), ("杨虹虹", "81852019"), ("姚莉雅", "81852029"), ("潘巧茹", "81852028")],
        )
        self.assertTrue(all(item["department"] == "刑事审判庭" for item in entries))

    def test_html_table_rows_never_borrow_a_later_row_phone(self):
        raw = """网页正文被压平，不应用于表格导入
部门\t姓名\t电话
立案庭（诉讼服务中心）\t冯静雯\t39122570
立案庭（诉讼服务中心）\t莫晓雪\t
立案庭（诉讼服务中心）\t张继辉\t39122564
"""
        response = self.client.post("/api/court-directory/import-preview", json={
            "raw_text": raw,
            "court": "广州市番禺区人民法院",
        })
        self.assertEqual(response.status_code, 200, response.text)
        entries = response.json()["entries"]
        self.assertEqual(
            [(item["name"], item["phone"]) for item in entries],
            [("冯静雯", "39122570"), ("张继辉", "39122564")],
        )

    def test_html_table_inherits_merged_department_and_expands_extension_prefix(self):
        raw = """拨打方式为 020-8300+以下4位号码
部 门\t人 员\t电话号码
刑事审判庭\t梁夏生\t8648
梁晓文\t8708
郑昕\t8512
"""
        response = self.client.post("/api/court-directory/import-preview", json={
            "raw_text": raw,
            "court": "广州市天河区人民法院",
        })
        self.assertEqual(response.status_code, 200, response.text)
        entries = response.json()["entries"]
        self.assertEqual(
            [(item["name"], item["phone"]) for item in entries],
            [("梁夏生", "02083008648"), ("梁晓文", "02083008708"), ("郑昕", "02083008512")],
        )
        self.assertTrue(all(item["department"] == "刑事审判庭" for item in entries))

    def test_name_accepts_any_nonempty_source_or_manual_value(self):
        self.import_entries([
            {"court": "广州市中级人民法院", "department": "立案庭", "name": "示七某", "position": "", "phone": "13800000500"},
        ])
        person = self.client.get("/api/court-directory/contacts?q=示七某").json()["items"][0]
        response = self.client.put(
            f"/api/court-directory/people/{person['person_id']}/name",
            json={"name": "值班窗口-A（夜班）"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        detail = self.client.get(f"/api/court-directory/people/{person['person_id']}").json()
        self.assertEqual(detail["person"]["name"], "值班窗口-A（夜班）")
