import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend import filing_workspace as filing


class _Request:
    def __init__(self, body): self.body = body
    async def json(self): return self.body


class _App:
    def __init__(self): self.routes = {}
    def get(self, path):
        def deco(fn): self.routes[("GET", path)] = fn; return fn
        return deco
    def post(self, path):
        def deco(fn): self.routes[("POST", path)] = fn; return fn
        return deco


class FilingWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "test.db"
        self.evidence = Path(self.temp.name) / "证据目录"
        self.evidence.mkdir()
        self.files = {
            "complaint": self.evidence / "民事起诉状.pdf",
            "evidence_index": self.evidence / "证据目录.pdf",
            "evidence": self.evidence / "买卖合同及对账单.pdf",
            "identity": self.evidence / "原告营业执照.pdf",
            "service_address": self.evidence / "送达地址确认书.pdf",
            "authority": self.evidence / "授权委托书.pdf",
            "lawyer_certificate": self.evidence / "律师执业证.pdf",
            "law_firm_letter": self.evidence / "律师事务所函.pdf",
            "agent_identity": self.evidence / "代理人身份证.pdf",
        }
        for path in self.files.values(): path.write_bytes(b"%PDF-1.7\nexample")
        with self.get_db() as conn:
            conn.executescript("""
                CREATE TABLE case_manager_cases (id INTEGER PRIMARY KEY, title TEXT);
                CREATE TABLE case_manager_parties (id INTEGER PRIMARY KEY, case_id INTEGER, party_group TEXT, role TEXT, name TEXT, credit_code TEXT, sort_order INTEGER);
                CREATE TABLE case_manager_files (id INTEGER PRIMARY KEY, case_id INTEGER, filename TEXT, absolute_path TEXT, metadata_json TEXT, created_at TEXT);
                CREATE TABLE case_manager_court_online_layy (id INTEGER PRIMARY KEY, linked_case_id INTEGER, case_name TEXT, status TEXT, review_comment TEXT, case_number TEXT, update_date TEXT, first_seen TEXT);
                INSERT INTO case_manager_cases(id,title) VALUES(1,'示丆某与示一某买卖合同纠纷');
                INSERT INTO case_manager_parties VALUES(1,1,'client','原告','示丆某','91440101TEST',1);
                INSERT INTO case_manager_parties VALUES(2,1,'opponent','被告','示一某','91440102TEST',2);
            """)
            for index, path in enumerate(self.files.values(), start=1):
                conn.execute("INSERT INTO case_manager_files VALUES(?,?,?,?,?,?)", (index, 1, path.name, str(path), "{}", "2026-01-01"))
            conn.commit()
        self.app = _App()
        filing.register_filing_workspace_routes(self.app, self.get_db)

    def tearDown(self): self.temp.cleanup()

    def get_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def test_package_requires_all_checks_then_locks_local_material_versions(self):
        create = self.app.routes[("POST", "/api/case-manager/cases/{case_id}/filing-draft")]
        draft = asyncio.run(create(1, _Request({
            "court_name": "广州市中级人民法院", "cause": "买卖合同纠纷", "claim_amount": "100000",
            "lawsuit_request": "请求判令被告支付货款。", "court_confirmed": True, "authority_confirmed": True,
        })))
        validation = self.app.routes[("POST", "/api/case-manager/filing-drafts/{draft_id}/validate")](draft["id"])
        self.assertEqual(validation["blockers"], [])
        result = self.app.routes[("POST", "/api/case-manager/filing-drafts/{draft_id}/package")](draft["id"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "ready")
        loaded = self.app.routes[("GET", "/api/case-manager/filing-drafts/{draft_id}")](draft["id"])
        self.assertTrue(all(item["locked"] for item in loaded["materials"] if item["selected"] and item["exists"]))
        self.assertEqual(len(loaded["package"]["materials"]), 9)

    def test_missing_authority_and_materials_block_packaging(self):
        self.files["authority"].unlink()
        create = self.app.routes[("POST", "/api/case-manager/cases/{case_id}/filing-draft")]
        draft = asyncio.run(create(1, _Request({"court_name": "广州市中级人民法院", "cause": "买卖合同纠纷", "lawsuit_request": "请求判令付款。", "court_confirmed": True})))
        validation = self.app.routes[("POST", "/api/case-manager/filing-drafts/{draft_id}/validate")](draft["id"])
        self.assertIn("请确认已核验代理权限", validation["blockers"])
        self.assertIn("缺少授权委托书", validation["blockers"])

    def test_self_filing_uses_a_smaller_material_profile(self):
        for key in ("authority", "lawyer_certificate", "law_firm_letter", "agent_identity"):
            self.files[key].unlink()
        with self.get_db() as conn:
            conn.executemany("DELETE FROM case_manager_files WHERE filename=?", [(self.files[key].name,) for key in ("authority", "lawyer_certificate", "law_firm_letter", "agent_identity")])
            conn.commit()
        create = self.app.routes[("POST", "/api/case-manager/cases/{case_id}/filing-draft")]
        draft = asyncio.run(create(1, _Request({
            "court_name": "广州市中级人民法院", "cause": "买卖合同纠纷", "lawsuit_request": "请求判令付款。",
            "court_confirmed": True, "representation_mode": "self",
        })))
        validation = self.app.routes[("POST", "/api/case-manager/filing-drafts/{draft_id}/validate")](draft["id"])
        self.assertEqual(validation["blockers"], [])

    def test_court_sync_reconciles_submitted_draft_without_court_write(self):
        create = self.app.routes[("POST", "/api/case-manager/cases/{case_id}/filing-draft")]
        draft = asyncio.run(create(1, _Request({
            "court_name": "广州市中级人民法院", "cause": "买卖合同纠纷", "lawsuit_request": "请求判令付款。",
            "court_confirmed": True, "authority_confirmed": True,
        })))
        self.app.routes[("POST", "/api/case-manager/filing-drafts/{draft_id}/package")](draft["id"])
        asyncio.run(self.app.routes[("POST", "/api/case-manager/filing-drafts/{draft_id}/mark-submitted")](draft["id"], _Request({"reference": "TEST-1"})))
        with self.get_db() as conn:
            conn.execute("INSERT INTO case_manager_court_online_layy VALUES(1,1,'示丆某与示一某买卖合同纠纷','审核通过','材料齐全','（2026）粤01民初1号','2026-01-02','2026-01-02')")
            conn.commit()
        self.assertEqual(filing.reconcile_filing_drafts(self.get_db), 1)
        loaded = self.app.routes[("GET", "/api/case-manager/filing-drafts/{draft_id}")](draft["id"])
        self.assertEqual(loaded["status"], "filed")
        self.assertEqual(loaded["official_case_number"], "（2026）粤01民初1号")


if __name__ == "__main__":
    unittest.main()
