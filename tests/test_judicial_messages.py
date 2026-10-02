import asyncio
import datetime as dt
import hashlib
import hmac
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import judicial_messages as jm
from backend.judicial_messages import (
    _attributed_text,
    _best_message_body,
    _browser_executable,
    _court_delivery_params,
    _ensure_schema,
    _friendly_browser_error,
    _gdems_delivery_id,
    _gdems_document_manifest,
    _gzac_delivery_item_key,
    _gzac_delivery_params,
    _gzac_document_params,
    _gzac_sms_ref_id,
    _gzac_sms_search_id,
    _is_gzac_search_url,
    _html_download_candidates,
    _is_court_platform_homepage,
    _message_rows,
    annotate_message_sources,
    classify_text,
    extract_document_urls,
    extract_case_numbers,
    extract_fields,
    is_verification_code_text,
    normalize_case_no,
    register_judicial_message_routes,
    _valid_document,
)


class JudicialMessageParsingTests(unittest.TestCase):
    def test_attributed_body_keeps_curly_quotes_and_commas(self):
        full = (
            "【广州法院】您好！您通过12368诉讼信息服务平台提交的工单现已办结，"
            "答复内容为“2026.7.3下午已电话联系”，满意请回复A，基本满意请回复B。"
        )
        blob = b"NSString\x00NSObject\x01" + full.encode("utf-8") + b"\x02iI\x00"
        self.assertEqual(_attributed_text(blob), full)
        truncated = full.split("“", 1)[0]
        self.assertEqual(_best_message_body(truncated, blob), full)

    def test_case_number_normalization_and_extraction(self):
        text = "广州市中级人民法院通知：案号 (2026) 粤01民终 1234号，请按时参加庭询。"
        self.assertEqual(extract_case_numbers(text), ["（2026）粤01民终1234号"])
        self.assertEqual(normalize_case_no("（2026） 粤 01 民终 1234 号"), "（2026）粤01民终1234号")

    def test_fixed_categories(self):
        self.assertEqual(classify_text("定于明日开庭审理"), "开庭/庭询/听证")
        self.assertEqual(classify_text("请在期限内完成电子送达文书查收"), "材料或电子送达")
        self.assertEqual(classify_text("举证期限截止前提交证据"), "举证/答辩/补正期限")
        self.assertEqual(classify_text("原开庭时间取消，另行通知"), "变更/取消")
        self.assertEqual(classify_text("普通快递已经到达驿站"), "")

    def test_bankruptcy_creditors_meeting_notice(self):
        body = (
            "【通知服务商】刘先生您好！某公司等18家关联企业第二次债权人会议，"
            "定于2026年10月12日14:00以网络方式召开。会议前将收到通知短信，"
            "请根据短信提示获取验证码方式登录系统观看会议直播、投票表决。\n"
            "某公司等18家关联企业管理人\n2026年9月30日"
        )
        fields = extract_fields(body, "2026-09-30 15:15:00")
        self.assertEqual(fields["category"], "其他重要通知")
        self.assertEqual(fields["event_at"], "2026-10-12 14:00")
        self.assertEqual(fields["institution"], "某公司等18家关联企业管理人")
        self.assertFalse(is_verification_code_text(body))
        self.assertFalse(jm.is_bankruptcy_meeting_notice("银行债权人会议营销活动"))

    def test_verification_codes_are_not_case_reminders(self):
        self.assertTrue(is_verification_code_text("【广州仲裁委员会】您的验证码是：899177"))
        self.assertTrue(is_verification_code_text("这是您预览司法文书材料的验证码V4A3，120秒内有效"))
        self.assertFalse(is_verification_code_text("案号（2026）粤01民终123号，开庭验证码为123456"))
        self.assertFalse(is_verification_code_text("请用手机号获取验证码方式登录系统参加债权人会议"))

    def test_extract_fields_with_afternoon_time(self):
        fields = extract_fields(
            "【广州市中级人民法院】案号：（2026）粤01民终1234号，2026年8月2日下午3时30分开庭，地点：第九法庭。",
            "2026-07-22 10:00:00",
        )
        self.assertEqual(fields["category"], "开庭/庭询/听证")
        self.assertEqual(fields["institution"], "广州市中级人民法院")
        self.assertEqual(fields["event_at"], "2026-08-02 15:30")
        self.assertIn("第九法庭", fields["location"])

    def test_document_links_and_login_pages(self):
        text = "请查收 https://example.com/doc.pdf，备用链接：https://example.com/login。"
        self.assertEqual(
            extract_document_urls(text),
            ["https://example.com/doc.pdf", "https://example.com/login"],
        )
        self.assertEqual(_valid_document(b"%PDF-1.7", "notice.bin"), (True, ".pdf"))
        self.assertEqual(
            _valid_document("<html><title>登录</title></html>".encode(), "download", "text/html"),
            (False, "login"),
        )
        verification_page = """
            <html><input placeholder="请输入您的手机号码">
            <input id="validateCode"><script>$.post('/v3/dzsd/getCode')</script>
            <label>短信验证码</label></html>
        """
        self.assertEqual(
            _valid_document(verification_page.encode(), "delivery", "text/html;charset=UTF-8"),
            (False, "verification"),
        )
        self.assertEqual(
            _valid_document(b"<html><a href='/document'>view</a></html>", "delivery", "text/html"),
            (False, "interaction"),
        )

    def test_court_delivery_url_is_distinguished_from_optional_login_homepage(self):
        delivery = (
            "https://zxfw.court.gov.cn/zxfw/#/pagesAjkj/app/wssd/index"
            "?qdbh=queue-id&sdbh=delivery-id&sdsin=sms-token"
        )
        self.assertEqual(
            _court_delivery_params(delivery),
            {
                "qdbh": "queue-id",
                "sdbh": "delivery-id",
                "sdsin": "sms-token",
                "mm": "",
            },
        )
        self.assertFalse(_is_court_platform_homepage(delivery))
        self.assertTrue(_is_court_platform_homepage("https://zxfw.court.gov.cn/"))
        self.assertTrue(_is_court_platform_homepage("https://zxfw.court.gov.cn/zxfw/"))

    def test_gdems_delivery_page_helpers(self):
        url = "https://sd.gdems.com/v3/dzsd/3KTOxA9aPL5l0UjL"
        self.assertEqual(_gdems_delivery_id(url), "3KTOxA9aPL5l0UjL")
        self.assertEqual(_gdems_delivery_id("https://example.com/v3/dzsd/abc123"), "")
        links = _html_download_candidates(
            "<script src='/static/app.js'></script><a href='/v3/dzsd/download?id=8'>下载文书</a>",
            url,
        )
        self.assertEqual(links, ["https://sd.gdems.com/v3/dzsd/download?id=8"])
        html = """
        <script>
        function downloadWs(id) {
          var url = "/v3/dzsd/d/link-123/" + "delivery-token/" + id;
          window.open(url);
        }
        </script>
        <div class="wsClass" onclick="downloadWs('doc-one')">
          <img src="/static/pdf.png"><label>保全告知书 .pdf</label>
        </div>
        <div class="wsClass" onclick="downloadWs('doc-two')">
          <label>裁定书 .pdf</label>
        </div>
        """
        self.assertEqual(
            _gdems_document_manifest(html, url),
            [
                {
                    "key": "doc-one",
                    "url": "https://sd.gdems.com/v3/dzsd/d/link-123/delivery-token/doc-one",
                    "filename": "保全告知书.pdf",
                },
                {
                    "key": "doc-two",
                    "url": "https://sd.gdems.com/v3/dzsd/d/link-123/delivery-token/doc-two",
                    "filename": "裁定书.pdf",
                },
            ],
        )

    def test_gzac_sms_lookup_credentials_are_extracted_strictly(self):
        text = (
            "【广州仲裁委员会】案号：（2024）穗仲案字第36589号，请登录 "
            "https://new.gzac.org/search/?s=delivery-id&src=sms&mc=reference-id "
            "查询案件相关材料，联系方式查询码：3f84d6。"
        )
        params = _gzac_delivery_params(text)
        self.assertEqual(
            params,
            {
                "case_year": "2024",
                "case_no": "36589",
                "query_code": "3f84d6",
                "source_url": "https://new.gzac.org/search/?s=delivery-id&src=sms&mc=reference-id",
            },
        )
        self.assertTrue(_is_gzac_search_url(params["source_url"]))
        self.assertFalse(_is_gzac_search_url("https://new.gzac.org/secretary/showEmailAndSms"))
        self.assertEqual(_gzac_delivery_params("查询码 3f84d6，请访问 https://new.gzac.org/search/"), {})
        document = {"source_path": '{"case_year":"2024","case_no":"36589","query_code":"3f84d6","key":"file-code"}'}
        self.assertEqual(_gzac_document_params(document), {"case_year": "2024", "case_no": "36589", "query_code": "3f84d6"})
        self.assertEqual(_gzac_delivery_item_key(document), "file-code")

    def test_gzac_sms_search_id_is_extracted_for_materials_lookup(self):
        url = "https://new.gzac.org/search?s=delivery-id&src=sms&mc=reference-id"
        self.assertEqual(_gzac_sms_search_id(url), "delivery-id")
        self.assertEqual(_gzac_sms_search_id("https://new.gzac.org/search"), "")
        self.assertEqual(_gzac_sms_ref_id(url), "reference-id")

    def test_browser_takeover_errors_are_user_friendly(self):
        error = RuntimeError(
            "BrowserType.launch_persistent_context: "
            "Target page, context or browser has been closed\nBrowser logs: ..."
        )
        message = _friendly_browser_error(error)
        self.assertIn("接管窗口已关闭", message)
        self.assertNotIn("BrowserType", message)
        self.assertTrue(_browser_executable() == "" or Path(_browser_executable()).is_file())


class JudicialMessageStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.app_db = self.root / "app.db"

        def get_db():
            conn = sqlite3.connect(self.app_db)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            return conn

        self.get_db = get_db
        with self.get_db() as conn:
            conn.executescript(
                """
                CREATE TABLE case_manager_cases(id INTEGER PRIMARY KEY,title TEXT,source_status TEXT DEFAULT 'active');
                CREATE TABLE case_manager_todos(id INTEGER PRIMARY KEY,case_id INTEGER,title TEXT,updated_at TEXT);
                """
            )
            conn.execute("INSERT INTO case_manager_cases(id,title) VALUES (1,'测试案件')")
            conn.execute("INSERT INTO case_manager_todos(id,case_id,title,updated_at) VALUES (7,1,'提交材料','2026-07-22 10:00:00')")
            conn.commit()
        _ensure_schema(self.get_db)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_schema_defaults_are_privacy_conscious(self):
        with self.get_db() as conn:
            settings = conn.execute("SELECT * FROM case_manager_message_settings WHERE id=1").fetchone()
            trusted = conn.execute("SELECT * FROM case_manager_trusted_senders WHERE sender='12368'").fetchone()
        self.assertEqual(settings["poll_interval_seconds"], 300)
        self.assertEqual(settings["backfill_days"], 90)
        self.assertTrue(settings["hmac_secret"])
        self.assertEqual(trusted["verified"], 0)
        with self.get_db() as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(case_manager_judicial_messages)").fetchall()}
        self.assertTrue({"imported_scan_run_id", "is_new", "is_deleted", "deleted_at"}.issubset(columns))
        with self.get_db() as conn:
            stored = conn.execute(
                "SELECT recipient_phones_json FROM case_manager_message_settings WHERE id=1"
            ).fetchone()[0]
        self.assertEqual(
            set(__import__("json").loads(stored)),
            {"18600001011", "17600000902"},
        )

    def test_message_source_annotation(self):
        with self.get_db() as conn:
            conn.execute(
                """INSERT INTO case_manager_judicial_messages
                   (id,fingerprint,received_at,workflow_status,created_at,updated_at)
                   VALUES (3,'fingerprint','2026-07-22 09:00:00','auto_written','2026-07-22','2026-07-22')"""
            )
            conn.execute(
                """INSERT INTO case_manager_message_links
                   (message_id,case_id,target_type,target_id,creation_mode,target_created_at,created_at)
                   VALUES (3,1,'todo',7,'auto','2026-07-22 10:00:00','2026-07-22 10:00:00')"""
            )
            conn.commit()
        items = annotate_message_sources(self.get_db, [{"id": 7, "title": "提交材料"}], "todo")
        self.assertEqual(items[0]["source_message_id"], 3)
        self.assertEqual(items[0]["message_created_mode"], "auto")

    @staticmethod
    def _route_app():
        class RouteApp:
            def __init__(self):
                self.routes = {}

            def _decorator(self, method, path):
                def register(fn):
                    self.routes[(method, path)] = fn
                    return fn
                return register

            def get(self, path): return self._decorator("GET", path)
            def post(self, path): return self._decorator("POST", path)
            def put(self, path): return self._decorator("PUT", path)
            def on_event(self, event): return self._decorator(event, event)

        return RouteApp()

    def _seed_gzac_delivery_message(self, body, url):
        with self.get_db() as conn:
            conn.execute(
                """CREATE TABLE case_manager_files(
                       id INTEGER PRIMARY KEY,case_id INTEGER,category TEXT,sha256 TEXT,
                       relative_path TEXT,absolute_path TEXT)"""
            )
            conn.execute(
                """INSERT INTO case_manager_judicial_messages
                   (id,fingerprint,received_at,raw_body,workflow_status,matched_case_id,created_at,updated_at)
                   VALUES (8,'gzac-fingerprint','2026-09-04 16:10:00',?,'pending',1,'2026-09-04','2026-09-04')""",
                (body,),
            )
            conn.execute(
                """INSERT INTO case_manager_message_documents
                   (message_id,source_kind,source_url,source_path,original_filename,status,created_at,updated_at)
                   VALUES (8,'gzac_delivery',?,?,'广州仲裁委电子送达','discovered','2026-09-04','2026-09-04')""",
                (url, json.dumps({"case_year": "2024", "case_no": "36589", "query_code": "3f84d6"})),
            )
            conn.commit()
        return int(
            self.get_db()
            .execute("SELECT id FROM case_manager_message_documents WHERE message_id=8")
            .fetchone()[0]
        )

    def test_gzac_delivery_stages_files_when_case_folder_not_bound(self):
        class FakeResponse:
            def __init__(self, payload=None, content=b"", headers=None):
                self.status_code = 200
                self._payload = payload
                self.content = content
                self.headers = headers or {}

            def json(self):
                return self._payload

            async def aiter_bytes(self):
                yield self.content

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def post(self, url, **kwargs):
                if "getSecretaryInfo" in url:
                    return FakeResponse(payload={"data": {"deliveryCid": "delivery-1"}})
                materials = json.dumps(
                    [
                        {"storageCode": "file-1", "name": "送达回证.pdf"},
                        {"storageCode": "file-2", "name": "仲裁通知书.pdf"},
                    ]
                )
                return FakeResponse(payload={"data": {"resultFile": {"materialContent": materials}}})

            async def get(self, url):
                return FakeResponse(payload={"data": True})

            def stream(self, method, url):
                if "downloadDeliveryAttrBefore" in url:
                    return FakeResponse(payload={"data": True})
                return FakeResponse(content=b"%PDF-1.7\nfake-gzac", headers={"content-type": "application/pdf"})

        class JsonRequest:
            async def json(self):
                return {}

        body = (
            "【广州仲裁委员会】案号：（2024）穗仲案字第36589号，"
            "请访问 https://new.gzac.org/search/?s=delivery-id&src=sms&mc=reference-id ，"
            "联系方式查询码：3f84d6。"
        )
        url = "https://new.gzac.org/search/?s=delivery-id&src=sms&mc=reference-id"
        document_id = self._seed_gzac_delivery_message(body, url)
        staging_dir = self.root / "staging"
        binding_calls = []

        def offline_binding(case_id, required=False):
            binding_calls.append(case_id)
            return {"case_id": case_id, "bound": True, "available": False}

        app = self._route_app()
        with patch.object(jm, "JUDICIAL_STAGING_DIR", staging_dir), \
             patch.object(jm, "_validate_public_url", lambda value: None), \
             patch.object(jm.httpx, "AsyncClient", return_value=FakeClient()):
            register_judicial_message_routes(
                app,
                self.get_db,
                {"get_folder_binding": offline_binding},
            )
            result = asyncio.run(
                app.routes[
                    ("POST", "/api/case-manager/judicial-messages/{message_id}/documents/{document_id}/download")
                ](8, document_id, JsonRequest())
            )
        self.assertEqual(binding_calls, [1, 1])
        parent = result["document"]
        self.assertEqual(parent["status"], "waiting_confirmation")
        self.assertIn("尚未绑定可用的本地文件夹", parent["last_error"] or "")
        self.assertTrue(parent["staging_path"])
        self.assertTrue(Path(parent["staging_path"]).is_file())
        rows = self.get_db().execute(
            "SELECT original_filename,status,last_error,staging_path FROM case_manager_message_documents WHERE message_id=8 ORDER BY id"
        ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["original_filename"], "仲裁通知书.pdf")
        self.assertEqual(rows[1]["status"], "waiting_confirmation")
        self.assertIn("尚未绑定可用的本地文件夹", rows[1]["last_error"] or "")
        self.assertTrue(rows[1]["staging_path"] and Path(rows[1]["staging_path"]).is_file())

    def test_gzac_delivery_archives_when_case_folder_available(self):
        class FakeResponse:
            def __init__(self, payload=None, content=b"", headers=None):
                self.status_code = 200
                self._payload = payload
                self.content = content
                self.headers = headers or {}

            def json(self):
                return self._payload

            async def aiter_bytes(self):
                yield self.content

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def post(self, url, **kwargs):
                if "getSecretaryInfo" in url:
                    return FakeResponse(payload={"data": {"deliveryCid": "delivery-1"}})
                materials = json.dumps([{"storageCode": "file-1", "name": "送达回证.pdf"}])
                return FakeResponse(payload={"data": {"resultFile": {"materialContent": materials}}})

            async def get(self, url):
                return FakeResponse(payload={"data": True})

            def stream(self, method, url):
                if "downloadDeliveryAttrBefore" in url:
                    return FakeResponse(payload={"data": True})
                return FakeResponse(content=b"%PDF-1.7\nfake-gzac", headers={"content-type": "application/pdf"})

        class JsonRequest:
            async def json(self):
                return {}

        body = (
            "【广州仲裁委员会】案号：（2024）穗仲案字第36589号，"
            "请访问 https://new.gzac.org/search/?s=delivery-id&src=sms&mc=reference-id ，"
            "联系方式查询码：3f84d6。"
        )
        url = "https://new.gzac.org/search/?s=delivery-id&src=sms&mc=reference-id"
        document_id = self._seed_gzac_delivery_message(body, url)
        staging_dir = self.root / "staging"
        case_dir = self.root / "bound-case"
        case_dir.mkdir()

        def online_binding(case_id, required=False):
            return {"case_id": case_id, "bound": True, "available": True, "real_path": str(case_dir)}

        def store_case_file(case_id, category, filename, content, **kwargs):
            absolute = str(case_dir / "#APEX电子送达归档" / filename)
            with self.get_db() as conn:
                cursor = conn.execute(
                    "INSERT INTO case_manager_files(case_id,category,relative_path,absolute_path) VALUES (?,?,?,?)",
                    (case_id, category, filename, absolute),
                )
                conn.commit()
                file_id = int(cursor.lastrowid)
            return {"id": file_id, "relative_path": filename, "absolute_path": absolute}

        app = self._route_app()
        with patch.object(jm, "JUDICIAL_STAGING_DIR", staging_dir), \
             patch.object(jm, "_validate_public_url", lambda value: None), \
             patch.object(jm.httpx, "AsyncClient", return_value=FakeClient()):
            register_judicial_message_routes(
                app,
                self.get_db,
                {
                    "get_folder_binding": online_binding,
                    "store_case_file": store_case_file,
                    "add_audit_log": lambda *args, **kwargs: None,
                },
            )
            result = asyncio.run(
                app.routes[
                    ("POST", "/api/case-manager/judicial-messages/{message_id}/documents/{document_id}/download")
                ](8, document_id, JsonRequest())
            )
        parent = result["document"]
        self.assertEqual(parent["status"], "archived")
        self.assertEqual(parent["case_id"], 1)
        self.assertEqual(int(parent["file_id"] or 0) > 0, True)
        self.assertNotIn("尚未绑定", parent["last_error"] or "")

    def test_gzac_sms_creates_a_single_official_delivery_task(self):
        class RouteApp:
            def __init__(self):
                self.routes = {}

            def _decorator(self, method, path):
                def register(fn):
                    self.routes[(method, path)] = fn
                    return fn
                return register

            def get(self, path): return self._decorator("GET", path)
            def post(self, path): return self._decorator("POST", path)
            def put(self, path): return self._decorator("PUT", path)
            def on_event(self, event): return self._decorator(event, event)

        body = (
            "【广州仲裁委员会】案号：（2024）穗仲案字第36589号，"
            "请访问 https://new.gzac.org/search/?s=delivery-id&src=sms&mc=reference-id ，"
            "联系方式查询码：3f84d6。"
        )
        with self.get_db() as conn:
            conn.execute("CREATE TABLE case_manager_files(id INTEGER PRIMARY KEY,relative_path TEXT,absolute_path TEXT)")
            conn.execute(
                """INSERT INTO case_manager_judicial_messages
                   (id,fingerprint,received_at,raw_body,workflow_status,created_at,updated_at)
                   VALUES (8,'gzac-fingerprint','2026-09-04 16:10:00',?,'pending','2026-09-04','2026-09-04')""",
                (body,),
            )
            conn.commit()
        app = RouteApp()
        register_judicial_message_routes(app, self.get_db, {})
        result = app.routes[("GET", "/api/case-manager/judicial-messages/{message_id}")](8)
        self.assertEqual(len(result["documents"]), 1)
        document = result["documents"][0]
        self.assertEqual(document["source_kind"], "gzac_delivery")
        self.assertEqual(document["original_filename"], "广州仲裁委电子送达")
        self.assertNotIn("3f84d6", document["source_url"])

    def test_bulk_delete_clears_message_but_preserves_linked_case_record(self):
        class RouteApp:
            def __init__(self):
                self.routes = {}

            def _decorator(self, method, path):
                def register(fn):
                    self.routes[(method, path)] = fn
                    return fn
                return register

            def get(self, path): return self._decorator("GET", path)
            def post(self, path): return self._decorator("POST", path)
            def put(self, path): return self._decorator("PUT", path)
            def on_event(self, event): return self._decorator(event, event)

        class JsonRequest:
            async def json(self):
                return {"message_ids": [4]}

        with self.get_db() as conn:
            conn.execute(
                """INSERT INTO case_manager_judicial_messages
                   (id,fingerprint,received_at,raw_body,workflow_status,is_new,created_at,updated_at)
                   VALUES (4,'delete-fingerprint','2026-07-24 09:00:00','敏感短信正文','confirmed',1,'2026-07-24','2026-07-24')"""
            )
            conn.execute(
                """INSERT INTO case_manager_message_links
                   (message_id,case_id,target_type,target_id,creation_mode,target_created_at,created_at)
                   VALUES (4,1,'todo',7,'manual','2026-07-24','2026-07-24')"""
            )
            conn.commit()
        app = RouteApp()
        register_judicial_message_routes(app, self.get_db, {})
        result = asyncio.run(app.routes[("POST", "/api/case-manager/judicial-messages/delete-bulk")](JsonRequest()))
        self.assertEqual(result["deleted_count"], 1)
        self.assertEqual(result["linked_count"], 1)
        with self.get_db() as conn:
            message = conn.execute("SELECT raw_body,is_deleted,is_new FROM case_manager_judicial_messages WHERE id=4").fetchone()
            link = conn.execute("SELECT 1 FROM case_manager_message_links WHERE message_id=4").fetchone()
            disposition = conn.execute("SELECT disposition FROM case_manager_message_fingerprints WHERE fingerprint='delete-fingerprint'").fetchone()[0]
        self.assertEqual(message["raw_body"], "")
        self.assertEqual(message["is_deleted"], 1)
        self.assertEqual(message["is_new"], 0)
        self.assertIsNotNone(link)
        self.assertEqual(disposition, "deleted")

    def test_read_only_messages_fixture_and_backfill(self):
        messages_db = self.root / "chat.db"
        conn = sqlite3.connect(messages_db)
        conn.executescript(
            """
            CREATE TABLE handle(ROWID INTEGER PRIMARY KEY,id TEXT);
            CREATE TABLE message(
                ROWID INTEGER PRIMARY KEY,guid TEXT,text TEXT,attributedBody BLOB,
                handle_id INTEGER,service TEXT,date INTEGER,is_from_me INTEGER
            );
            """
        )
        conn.execute("INSERT INTO handle(ROWID,id) VALUES (1,'12368')")
        apple_epoch = dt.datetime(2001, 1, 1)
        recent_seconds = int((dt.datetime.now() - apple_epoch).total_seconds() * 1_000_000_000)
        old_seconds = int((dt.datetime.now() - dt.timedelta(days=120) - apple_epoch).total_seconds() * 1_000_000_000)
        conn.execute("INSERT INTO message VALUES (1,'old','旧短信',NULL,1,'SMS',?,0)", (old_seconds,))
        conn.execute("INSERT INTO message VALUES (2,'new','法院开庭通知',NULL,1,'SMS',?,0)", (recent_seconds,))
        conn.execute("INSERT INTO message VALUES (3,'mine','我发送的内容',NULL,1,'SMS',?,1)", (recent_seconds,))
        conn.commit(); conn.close()

        rows, highwater = _message_rows(messages_db, 0, True, 90)
        self.assertEqual([row["source_guid"] for row in rows], ["new"])
        self.assertEqual(rows[0]["sender"], "12368")
        self.assertEqual(highwater, 2)

        conn = sqlite3.connect(messages_db)
        conn.execute("INSERT INTO message VALUES (4,'incremental','法院新增开庭通知',NULL,1,'SMS',?,0)", (recent_seconds,))
        conn.execute("INSERT INTO message VALUES (5,'old-late-row','很久以前的法院通知',NULL,1,'SMS',?,0)", (old_seconds,))
        conn.commit(); conn.close()

        incremental, next_highwater = _message_rows(messages_db, highwater, False, 90)
        self.assertEqual([row["source_guid"] for row in incremental], ["incremental"])
        self.assertEqual(next_highwater, 5)
        repeated, final_highwater = _message_rows(messages_db, next_highwater, False, 90)
        self.assertEqual(repeated, [])
        self.assertEqual(final_highwater, 5)
        replayed, replay_highwater = _message_rows(messages_db, next_highwater, False, 90, (2,))
        self.assertEqual([row["source_guid"] for row in replayed], ["new"])
        self.assertEqual(replay_highwater, next_highwater)

    def test_scan_reconsiders_previously_ignored_creditors_meeting(self):
        body = (
            "【通知服务商】某公司等18家关联企业第二次债权人会议，"
            "定于2026年10月12日14:00以网络方式召开，请获取验证码方式登录系统投票表决。\n"
            "某公司等18家关联企业管理人"
        )
        sender, guid = "1068449029613", "creditors-meeting-guid"
        received_at = dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")
        apple_seconds = int((dt.datetime.now().astimezone() - dt.datetime(2001, 1, 1, tzinfo=dt.timezone.utc)).total_seconds() * 1_000_000_000)
        received_at = jm._apple_date(apple_seconds)
        messages_db = self.root / "chat.db"
        with sqlite3.connect(messages_db) as conn:
            conn.executescript(
                "CREATE TABLE handle(ROWID INTEGER PRIMARY KEY,id TEXT);"
                "CREATE TABLE message(ROWID INTEGER PRIMARY KEY,guid TEXT,text TEXT,attributedBody BLOB,handle_id INTEGER,service TEXT,date INTEGER,is_from_me INTEGER);"
            )
            conn.execute("INSERT INTO handle VALUES (1,?)", (sender,))
            conn.execute("INSERT INTO message VALUES (1,?,?,NULL,1,'SMS',?,0)", (guid, body, apple_seconds))
        with self.get_db() as conn:
            conn.execute("ALTER TABLE case_manager_cases ADD COLUMN case_type TEXT DEFAULT ''")
            conn.execute("ALTER TABLE case_manager_cases ADD COLUMN current_stage TEXT DEFAULT ''")
            conn.execute("CREATE TABLE case_manager_case_numbers(id INTEGER PRIMARY KEY,case_id INTEGER,case_no TEXT,court TEXT)")
            conn.execute("CREATE TABLE case_manager_parties(id INTEGER PRIMARY KEY,case_id INTEGER,name TEXT)")
            conn.execute("CREATE TABLE case_manager_files(id INTEGER PRIMARY KEY,relative_path TEXT,absolute_path TEXT)")
            secret = conn.execute("SELECT hmac_secret FROM case_manager_message_settings WHERE id=1").fetchone()[0]
            digest = hmac.new(secret.encode(), "|".join((guid, sender, received_at, body)).encode(), hashlib.sha256).hexdigest()
            conn.execute(
                "INSERT INTO case_manager_message_fingerprints(fingerprint,source_guid,source_rowid,received_at,disposition,created_at) VALUES (?,?,?,?,?,?)",
                (digest, guid, 1, received_at, "irrelevant-v3", received_at),
            )
            conn.execute("UPDATE case_manager_message_settings SET last_source_rowid=1,initial_scan_completed=1,ai_enabled=0 WHERE id=1")
        app = self._route_app()
        register_judicial_message_routes(app, self.get_db, {})
        with patch.object(jm, "MESSAGE_DB", messages_db):
            result = asyncio.run(app.routes[("POST", "/api/case-manager/judicial-messages/scan")]())
        self.assertEqual(result["candidates"], 1)
        with self.get_db() as conn:
            saved = conn.execute("SELECT category,raw_body FROM case_manager_judicial_messages").fetchone()
            legacy = conn.execute("SELECT disposition FROM case_manager_message_fingerprints WHERE fingerprint=?", (digest,)).fetchone()
        self.assertEqual(saved["category"], "其他重要通知")
        self.assertEqual(saved["raw_body"], body)
        self.assertIsNone(legacy)
        with patch.object(jm, "MESSAGE_DB", messages_db):
            repeated = asyncio.run(app.routes[("POST", "/api/case-manager/judicial-messages/scan")]())
        self.assertEqual(repeated["candidates"], 0)
        with self.get_db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM case_manager_judicial_messages").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
