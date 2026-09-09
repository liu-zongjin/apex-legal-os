import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import court_online_service as court
from backend.case_automation import COURT_DOCUMENT_SUBDIR, ensure_case_automation_schema


class CourtOnlineServiceTests(unittest.TestCase):
    def setUp(self):
        # Python 3.8 下 IsolatedAsyncioTestCase 结束时会 set_event_loop(None)，
        # 而 register_court_online_service_routes 构造 asyncio.Lock() 需要当前循环；
        # 每个用例前恢复主线程事件循环，保证全量测试顺序无关。
        asyncio.set_event_loop(asyncio.new_event_loop())
        # Tests must not inherit the developer's real active court account from
        # the macOS Keychain. Keep all fixture rows inside the anonymous legacy scope.
        self.active_account_patch = patch.object(court, "_active_account_id", return_value="legacy")
        self.active_account_patch.start()
        self.directory = tempfile.TemporaryDirectory()
        self.db_path = Path(self.directory.name) / "apex.sqlite"

        def get_db():
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            return conn
        self.get_db = get_db
        court._ensure_schema(self.get_db)

    def tearDown(self):
        self.active_account_patch.stop()
        self.directory.cleanup()

    def test_court_url_is_strictly_scoped(self):
        self.assertEqual(court._validate_court_url("https://zxfw.court.gov.cn/zxfw/"), "https://zxfw.court.gov.cn/zxfw/")
        for value in ("http://zxfw.court.gov.cn/", "https://example.com/", "file:///tmp/a"):
            with self.assertRaises(Exception):
                court._validate_court_url(value)

    def test_schema_deduplicates_records_and_keeps_attachments_separate(self):
        with self.get_db() as conn:
            conn.execute("""INSERT INTO case_manager_court_online_records
                (remote_id,kind,title,stored_at,updated_at) VALUES(?,?,?,?,?)""",
                ("notice-1", "message", "法院消息", court._now(), court._now()))
            record_id = conn.execute("SELECT id FROM case_manager_court_online_records").fetchone()[0]
            conn.execute("""INSERT INTO case_manager_court_online_attachments
                (record_id,remote_id,filename) VALUES(?,?,?)""", (record_id, "file-1", "裁定书.pdf"))
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("""INSERT INTO case_manager_court_online_records
                    (remote_id,kind,title,stored_at,updated_at) VALUES(?,?,?,?,?)""",
                    ("notice-1", "message", "重复消息", court._now(), court._now()))

    def test_schema_extends_layy_with_detail_columns_and_audits_table(self):
        with self.get_db() as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(case_manager_court_online_layy)").fetchall()}
            for name in ("applicant", "apply_time", "submit_time", "judge", "filing_method",
                         "claim_amount", "lawsuit_request", "case_number", "cause_code",
                         "material_count", "material_time", "withdraw_time", "detail_json"):
                self.assertIn(name, columns, f"layy 缺少详情列 {name}")
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            self.assertIn("case_manager_court_online_layy_audits", tables)
            conn.execute("""INSERT INTO case_manager_court_online_layy(remote_id,case_name,status,category,first_seen,updated_at)
                VALUES('ly-d-1','测试预约','11800007-3','zx','2026-01-01','2026-01-01')""")
            layy_id = conn.execute("SELECT id FROM case_manager_court_online_layy").fetchone()[0]
            conn.execute("""INSERT INTO case_manager_court_online_layy_audits(layy_id,remote_id,shjg,shjg_text,review_comment,review_time,reviewer,created_at)
                VALUES(?,?,?,?,?,?,?,?)""", (layy_id, "a-1", "11800007-3", "审查不通过", "缺材料", "2026-01-02", "王丽娟", "2026-01-02"))
            conn.commit()
            row = conn.execute("SELECT * FROM case_manager_court_online_layy_audits WHERE layy_id=?", (layy_id,)).fetchone()
            self.assertEqual(row["shjg_text"], "审查不通过")
            self.assertEqual(row["reviewer"], "王丽娟")
            self.assertEqual(row["review_time"], "2026-01-02")

    def test_layy_snapshot_reconciliation_only_removes_successfully_refreshed_categories(self):
        """官网遗漏旧预约时，已成功刷新的分类要与官网列表一致。"""
        account_id = "legacy"
        with self.get_db() as conn:
            for remote_id, category in (("sp-current", "sp"), ("sp-stale", "sp"), ("zx-stale", "zx"), ("pc-unknown", "pc")):
                conn.execute(
                    """INSERT INTO case_manager_court_online_layy
                       (remote_id, account_id, category, case_name, first_seen, updated_at)
                       VALUES(?,?,?,?,?,?)""",
                    (f"{account_id}:{remote_id}", account_id, category, remote_id, "2026-09-09", "2026-09-09"),
                )
            stale_id = conn.execute(
                "SELECT id FROM case_manager_court_online_layy WHERE remote_id=?",
                (f"{account_id}:sp-stale",),
            ).fetchone()[0]
            conn.execute(
                """INSERT INTO case_manager_court_online_layy_audits
                   (layy_id, remote_id, created_at) VALUES(?,?,?)""",
                (stale_id, "audit-stale", "2026-09-09"),
            )
            removed = court._reconcile_layy_snapshot(
                conn,
                account_id,
                {
                    "sp": {f"{account_id}:sp-current"},
                    "zx": set(),
                    # The bankruptcy request failed, so it deliberately does
                    # not appear in the snapshot and must be preserved.
                },
            )
            self.assertEqual(removed, 2)
            remaining = {
                row[0] for row in conn.execute(
                    "SELECT remote_id FROM case_manager_court_online_layy ORDER BY remote_id"
                ).fetchall()
            }
            self.assertEqual(remaining, {f"{account_id}:pc-unknown", f"{account_id}:sp-current"})
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM case_manager_court_online_layy_audits").fetchone()[0],
                0,
            )

    def test_sensitive_values_are_not_rendered_in_status_text(self):
        self.assertEqual(court._redact_account("123"), "***")
        self.assertNotIn("12345678", court._redact_account("12345678"))
        self.assertEqual(court._safe_filename('../../坏:名.pdf'), "_.._坏_名.pdf")

    def test_document_filename_keeps_or_recovers_extension(self):
        self.assertEqual(court._document_filename("中山盈昌达", "pdf"), "中山盈昌达.pdf")
        self.assertEqual(court._document_filename("通知书.pdf", "pdf"), "通知书.pdf")
        self.assertEqual(court._document_filename("裁定书", "", "application/pdf"), "裁定书.pdf")

    def test_hearing_duplicates_from_legacy_and_account_scoped_ids_are_merged(self):
        """切换账号升级前后的三种内部 ID 只能保留一个开庭记录。"""
        account_id = "acct-test"
        with self.get_db() as conn:
            conn.executescript("""
                CREATE TABLE case_manager_hearings (id INTEGER PRIMARY KEY, source_key TEXT);
            """)
            for remote_id, linked_case_id in [
                ("case:court-1", None),
                ("case:sp:sp:court-1", 7),
                ("acct-test:case:sp:acct-test:sp:court-1", None),
            ]:
                conn.execute("""INSERT INTO case_manager_court_online_hearings
                    (remote_id,source,case_number,case_name,court_name,hearing_at,raw_json,linked_case_id,first_seen,updated_at,account_id)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (remote_id, "case_sp", "（2026）粤01民初1号", "测试案件", "测试法院", "2026-08-01 09:30",
                     '{"cbh":"court-1"}', linked_case_id, "2026-08-01", "2026-08-01", account_id))
            duplicate_id = conn.execute("SELECT MAX(id) FROM case_manager_court_online_hearings").fetchone()[0]
            conn.execute("INSERT INTO case_manager_hearings(source_key) VALUES(?)", (f"court-hearing:{duplicate_id}",))
            self.assertEqual(court._merge_duplicate_court_hearings(conn), 2)
            row = conn.execute("SELECT * FROM case_manager_court_online_hearings").fetchone()
            self.assertEqual(row["remote_id"], "acct-test:case:sp:court-1")
            self.assertEqual(row["linked_case_id"], 7)
            self.assertEqual(conn.execute("SELECT source_key FROM case_manager_hearings").fetchone()[0], f"court-hearing:{row['id']}")

    def test_download_uses_bound_case_folder_for_one_and_all_attachments(self):
        class FakeApp:
            def __init__(self):
                self.routes = {}

            def _register(self, path):
                def deco(fn):
                    self.routes[path] = fn
                    return fn
                return deco

            def get(self, path): return self._register(path)
            def put(self, path): return self._register(path)
            def post(self, path): return self._register(path)
            def delete(self, path): return self._register(path)

            def on_event(self, _event):
                def deco(fn): return fn
                return deco

        class FakeResponse:
            content = b"%PDF-1.7\nexample"
            headers = {"content-type": "application/pdf"}

            def raise_for_status(self):
                return None

        class FakeClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *_args): return None
            async def get(self, _url): return FakeResponse()

        ensure_case_automation_schema(self.get_db)
        case_root = Path(self.directory.name) / "bound-case"
        case_root.mkdir()
        stat = case_root.stat()
        with self.get_db() as conn:
            conn.execute("CREATE TABLE case_manager_cases (id INTEGER PRIMARY KEY, title TEXT)")
            conn.execute("INSERT INTO case_manager_cases(id,title) VALUES(7,'已关联案件')")
            conn.execute("""INSERT INTO case_manager_folder_bindings
                (case_id,folder_path,real_path,device_id,inode,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?)""", (7, str(case_root), str(case_root), stat.st_dev, stat.st_ino, court._now(), court._now()))
            conn.execute("""INSERT INTO case_manager_court_online_records
                (remote_id,kind,title,linked_case_id,account_id,stored_at,updated_at)
                VALUES('delivery-1','delivery','电子送达',7,'legacy',?,?)""", (court._now(), court._now()))
            record_id = conn.execute("SELECT id FROM case_manager_court_online_records").fetchone()[0]
            for remote_id, filename in (("file-1", "送达文书一"), ("file-2", "送达文书二")):
                conn.execute("""INSERT INTO case_manager_court_online_attachments
                    (record_id,remote_id,filename,extension,source_url)
                    VALUES(?,?,?,?,?)""", (record_id, remote_id, filename, "pdf", "https://zxfw.court.gov.cn/file.pdf"))
            conn.commit()

        app = FakeApp()
        with patch.object(court, "_read_secret", return_value={"_account_id": "legacy"}), \
             patch.object(court.httpx, "AsyncClient", return_value=FakeClient()):
            court.register_court_online_service_routes(app, self.get_db)
            first_id = 1
            one = asyncio.run(app.routes["/api/case-manager/court-online/attachments/{attachment_id}/download"](first_id))
            all_result = asyncio.run(app.routes["/api/case-manager/court-online/records/{record_id}/download-all"](record_id))

        expected_dir = case_root / COURT_DOCUMENT_SUBDIR
        self.assertTrue(one["saved_to_case"])
        self.assertEqual(Path(one["path"]).parent, expected_dir)
        self.assertTrue(all(item["saved_to_case"] for item in all_result["results"]))
        self.assertEqual(len(list(expected_dir.iterdir())), 3)

    def test_probe_route_target_keeps_whitelist_and_drops_sensitive_query(self):
        target = court._probe_route_target(
            "https://zxfw.court.gov.cn/yzw-zxfw-xxfw/api/v1/znxx/list?pageNo=1&xxlb=1&zjhm=990000199001010070&sjh=13800000500")
        self.assertEqual(target, "https://zxfw.court.gov.cn/yzw-zxfw-xxfw/api/v1/znxx/list?xxlb=1")
        self.assertNotIn("110101", target)
        self.assertNotIn("13800000500", target)

    def test_probe_route_target_filters_non_gateway_and_static(self):
        self.assertEqual(court._probe_route_target("https://zxfw.court.gov.cn/zxfw/static/js/app.js"), "")
        self.assertEqual(court._probe_route_target("https://example.com/yzw-zxfw-xxfw/api/v1/znxx/list"), "")
        self.assertEqual(court._probe_route_target("https://zxfw.court.gov.cn/portal-chat/api/v1/chat/msgs?limit=100"),
                         "https://zxfw.court.gov.cn/portal-chat/api/v1/chat/msgs")

    def test_probe_route_record_aggregates_by_method_and_url(self):
        with self.get_db() as conn:
            court._record_probe_route(conn, "POST", "https://zxfw.court.gov.cn/yzw-zxfw-sdfw/api/v1/sdfw/getSdListByZjhmAndAhdmNew?pageNum=1&sdzt=1&ajbh=xxx", 200)
            court._record_probe_route(conn, "POST", "https://zxfw.court.gov.cn/yzw-zxfw-sdfw/api/v1/sdfw/getSdListByZjhmAndAhdmNew?pageNum=2&sdzt=1&ajbh=yyy", 200)
            conn.commit()
            rows = conn.execute("SELECT * FROM case_manager_court_online_probe_routes").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["hit_count"], 2)
        self.assertNotIn("ajbh", rows[0]["url"])

    def test_probe_route_body_keys_keeps_only_key_names(self):
        with self.get_db() as conn:
            court._record_probe_route(conn, "POST", "https://zxfw.court.gov.cn/yzw-zxfw-ajfw/api/v1/ajlist", 200,
                                      '{"pageNum":1,"pageSize":10,"zjhm":"990000199001010070","x":"abc"}')
            conn.commit()
            row = conn.execute("SELECT body_keys FROM case_manager_court_online_probe_routes").fetchone()
        self.assertEqual(row[0], "pageNum,pageSize,zjhm,x")
        self.assertNotIn("110101", row[0])

    def test_request_body_keys_handles_invalid_payloads(self):
        for raw in ("not-json", "", '{"ok":1}'):
            with self.get_db() as conn:
                keys = court._request_body_keys(type("R", (), {"post_data": raw})())
            if raw == '{"ok":1}':
                self.assertEqual(keys, "ok")
            else:
                self.assertEqual(keys, "")

    def test_case_and_layy_tables_upsert_idempotently(self):
        with self.get_db() as conn:
            for stage in ("正在审理", "已经结案"):
                conn.execute("""INSERT INTO case_manager_court_online_cases(remote_id,case_number,case_name,cause,business_type,court_name,judge,department,stage,adjudication,status,parties,filing_date,judgment_date,update_date,raw_json,first_seen,updated_at)
                    VALUES('c-1','（2026）粤01民初1号','测试案','合同纠纷','民事一审案件','广州市中级人民法院','示七某','民一庭',?, '',1,'甲,乙','2026-01-01','','2026-01-02','{}','2026-01-01','2026-01-02')
                    ON CONFLICT(remote_id) DO UPDATE SET stage=excluded.stage,updated_at=excluded.updated_at""", (stage,))
            conn.execute("""INSERT INTO case_manager_court_online_layy(remote_id,court_name,case_type,parties,case_name,status,cause,category,review_comment,filed_date,update_date,raw_json,first_seen,updated_at)
                VALUES('l-1','广州市白云区人民法院','首次执行案件','甲','执行案','11800007-100','','zx','','2026-08-01','2026-08-01','{}','2026-08-01','2026-08-01')""")
            conn.commit()
            cases = conn.execute("SELECT COUNT(*) FROM case_manager_court_online_cases").fetchone()[0]
            layy = conn.execute("SELECT COUNT(*) FROM case_manager_court_online_layy").fetchone()[0]
            stage = conn.execute("SELECT stage FROM case_manager_court_online_cases WHERE remote_id='c-1'").fetchone()[0]
        self.assertEqual(cases, 1)
        self.assertEqual(layy, 1)
        self.assertEqual(stage, "已经结案")

    def test_court_online_links_matches_by_link_and_normalized_case_number(self):
        from backend.case_manager import court_online_links
        with self.get_db() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS case_manager_cases (id INTEGER PRIMARY KEY, title TEXT);
                CREATE TABLE IF NOT EXISTS case_manager_case_numbers (id INTEGER PRIMARY KEY, case_id INTEGER, case_no TEXT);
                INSERT INTO case_manager_cases(id,title) VALUES(7,'广州某公司与某公司租赁合同纠纷一案');
                INSERT INTO case_manager_case_numbers(case_id,case_no) VALUES(7,'（2026）粤01民初1234号'),(7,'(2026)粤01民初1234号');
                INSERT INTO case_manager_court_online_cases(remote_id,case_number,case_name,linked_case_id,first_seen,updated_at)
                    VALUES('co-1','（2026）粤01民初1234号','官网案件一',7,'2026-01-01','2026-01-02');
                INSERT INTO case_manager_court_online_cases(remote_id,case_number,case_name,linked_case_id,first_seen,updated_at)
                    VALUES('co-2','（2025）粤01民初99号','官网案件二',NULL,'2026-01-01','2026-01-02');
                INSERT INTO case_manager_court_online_layy(remote_id,court_name,parties,case_name,status,first_seen,updated_at)
                    VALUES('ly-1','广州市中级人民法院','甲,乙','广州某公司与某公司租赁合同纠纷一案','11800007-100','2026-08-01','2026-08-01');
                INSERT INTO case_manager_court_online_layy(remote_id,court_name,parties,case_name,status,first_seen,updated_at)
                    VALUES('ly-2','白云区人民法院','丙','无关预约','11800007-100','2026-08-01','2026-08-01');
            """)
            conn.commit()
            case = {"id": 7, "title": "广州某公司与某公司租赁合同纠纷一案",
                    "case_numbers": [{"case_no": "（2026）粤01民初1234号"}, {"case_no": "(2026)粤01民初1234号"}]}
            result = court_online_links(conn, case)
        self.assertEqual(len(result["cases"]), 1)
        self.assertEqual(result["cases"][0]["case_number"], "（2026）粤01民初1234号")
        self.assertEqual(len(result["layy"]), 1)
        self.assertEqual(result["layy"][0]["case_name"], "广州某公司与某公司租赁合同纠纷一案")

    def test_my_cases_list_orders_linked_first_filing_date_then_closed_last(self):
        class FakeApp:
            def __init__(self):
                self.routes = {}
            def _register(self, path):
                def deco(fn):
                    self.routes[path] = fn
                    return fn
                return deco
            def get(self, path):
                return self._register(path)
            def put(self, path):
                return self._register(path)
            def post(self, path):
                return self._register(path)
            def delete(self, path):
                return self._register(path)
            def on_event(self, _event):
                def deco(fn):
                    return fn
                return deco

        with self.get_db() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS case_manager_cases (id INTEGER PRIMARY KEY, title TEXT)")
            for i, (remote, linked, stage, filing, update) in enumerate([
                ("co-1", 1, "正在审理", "2026-01-01", "2026-01-02"),
                ("co-2", 2, "已经结案", "2026-02-01", "2026-02-02"),
                ("co-3", None, "正在审理", "2026-05-01", "2026-05-02"),
                ("co-4", None, "等待分派", "2026-03-01", "2026-03-02"),
                ("co-5", None, "已经归档", "2026-06-01", "2026-06-02"),
            ], start=1):
                conn.execute("INSERT INTO case_manager_cases(id,title) VALUES(?,?)", (i, f"本地案件{i}"))
                conn.execute("""INSERT INTO case_manager_court_online_cases
                    (remote_id,case_number,case_name,stage,linked_case_id,filing_date,update_date,first_seen,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?)""",
                    (remote, f"（2026）粤01民初{i}号", f"官网案件{i}", stage, linked, filing, update, "2026-01-01", "2026-01-01"))
            conn.commit()

        app = FakeApp()
        court.register_court_online_service_routes(app, self.get_db)
        handler = app.routes["/api/case-manager/court-online/cases"]
        result = handler()
        names = [item["case_name"] for item in result["items"]]
        self.assertEqual(names, ["官网案件1", "官网案件2", "官网案件3", "官网案件4", "官网案件5"])

    def test_legacy_case_rows_get_sp_prefix_on_schema_setup(self):
        with self.get_db() as conn:
            conn.execute("""INSERT INTO case_manager_court_online_cases
                (remote_id,case_number,case_name,first_seen,updated_at)
                VALUES('legacy-1','（2026）粤01民初1号','旧案件','2026-01-01','2026-01-01')""")
            conn.commit()
        court._ensure_schema(self.get_db)
        with self.get_db() as conn:
            row = conn.execute("SELECT remote_id,ajlb FROM case_manager_court_online_cases WHERE case_number='（2026）粤01民初1号'").fetchone()
        self.assertEqual(row[0], "legacy:sp:legacy-1")
        self.assertEqual(row[1], "sp")

    def test_cases_list_filters_by_ajlb(self):
        class FakeApp:
            def __init__(self):
                self.routes = {}
            def _register(self, path):
                def deco(fn):
                    self.routes[path] = fn
                    return fn
                return deco
            def get(self, path):
                return self._register(path)
            def put(self, path):
                return self._register(path)
            def post(self, path):
                return self._register(path)
            def delete(self, path):
                return self._register(path)
            def on_event(self, _event):
                def deco(fn):
                    return fn
                return deco

        with self.get_db() as conn:
            for i, (remote, ajlb) in enumerate([("sp:c-1", "sp"), ("zx:c-2", "zx"), ("pc:c-3", "pc")], start=1):
                conn.execute("""INSERT INTO case_manager_court_online_cases
                    (remote_id,ajlb,case_number,case_name,first_seen,updated_at)
                    VALUES(?,?,?,?,?,?)""",
                    (remote, ajlb, f"（2026）粤01民初{i}号", f"官网案件{i}", "2026-01-01", "2026-01-01"))
            conn.commit()
        app = FakeApp()
        court.register_court_online_service_routes(app, self.get_db)
        handler = app.routes["/api/case-manager/court-online/cases"]
        self.assertEqual([item["case_name"] for item in handler(ajlb="sp")["items"]], ["官网案件1"])
        self.assertEqual([item["case_name"] for item in handler(ajlb="zx")["items"]], ["官网案件2"])
        self.assertEqual([item["case_name"] for item in handler(ajlb="pc")["items"]], ["官网案件3"])
        self.assertEqual(len(handler()["items"]), 3)
        with self.assertRaises(Exception):
            handler(ajlb="bad")

    def test_status_reports_case_category_counts(self):
        class FakeApp:
            def __init__(self):
                self.routes = {}
            def _register(self, path):
                def deco(fn):
                    self.routes[path] = fn
                    return fn
                return deco
            def get(self, path):
                return self._register(path)
            def put(self, path):
                return self._register(path)
            def post(self, path):
                return self._register(path)
            def delete(self, path):
                return self._register(path)
            def on_event(self, _event):
                def deco(fn):
                    return fn
                return deco

        with self.get_db() as conn:
            for remote, kind in [("todo-1", "todo"), ("message-1", "message"), ("message-2", "message"), ("delivery-1", "delivery")]:
                conn.execute("""INSERT INTO case_manager_court_online_records
                    (remote_id,kind,title,stored_at,updated_at)
                    VALUES(?,?,?,?,?)""",
                    (remote, kind, "法院记录", "2026-01-01", "2026-01-01"))
            for remote, ajlb in [("sp:c-1", "sp"), ("sp:c-2", "sp"), ("zx:c-3", "zx"), ("pc:c-4", "pc")]:
                conn.execute("""INSERT INTO case_manager_court_online_cases
                    (remote_id,ajlb,case_number,case_name,first_seen,updated_at)
                    VALUES(?,?,?,?,?,?)""",
                    (remote, ajlb, f"（2026）粤01民初{remote}号", "案件", "2026-01-01", "2026-01-01"))
            for remote, category in [("layy-1", "sp"), ("layy-2", "sp"), ("layy-3", "zx"), ("layy-4", "pc")]:
                conn.execute("""INSERT INTO case_manager_court_online_layy
                    (remote_id,category,case_name,status,first_seen,updated_at)
                    VALUES(?,?,?,?,?,?)""",
                    (remote, category, "立案预约", "审核中", "2026-01-01", "2026-01-01"))
            conn.commit()
        app = FakeApp()
        court.register_court_online_service_routes(app, self.get_db)
        status = app.routes["/api/case-manager/court-online/status"]()
        self.assertEqual(status["record_count"], 4)
        self.assertEqual(status["todo_count"], 1)
        self.assertEqual(status["message_count"], 2)
        self.assertEqual(status["delivery_count"], 1)
        self.assertEqual(status["case_count"], 4)
        self.assertEqual(status["case_trial_count"], 2)
        self.assertEqual(status["execute_case_count"], 1)
        self.assertEqual(status["bankruptcy_case_count"], 1)
        # Schema setup merges business-identical appointments even when the
        # court returns different remote ids, so the duplicate trial row is one card.
        self.assertEqual(status["layy_count"], 3)
        self.assertEqual(status["layy_trial_count"], 1)
        self.assertEqual(status["layy_execute_count"], 1)
        self.assertEqual(status["layy_bankruptcy_count"], 1)
