import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend import automated_filing as filing


class AutomatedFilingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "网上立案"
        self.root.mkdir()
        for filename in (
            "民事起诉状.pdf", "证据目录.pdf", "买卖合同及对账单.pdf", "原告营业执照.pdf",
            "送达地址确认书.pdf", "授权委托书.pdf", "律师执业证.pdf", "律师事务所函.pdf", "代理人身份证.pdf",
        ):
            (self.root / filename).write_bytes(b"%PDF-1.7\nexample")

    def tearDown(self):
        self.temp.cleanup()

    def test_scan_maps_common_filing_materials(self):
        root, materials, facts, warnings = filing._scan_folder(str(self.root))
        self.assertEqual(root, self.root.resolve())
        mapping = {item["name"]: item["category"] for item in materials}
        self.assertEqual(mapping["民事起诉状.pdf"], "complaint")
        self.assertEqual(mapping["证据目录.pdf"], "evidence_index")
        self.assertEqual(mapping["送达地址确认书.pdf"], "service_address")
        self.assertEqual(mapping["律师事务所函.pdf"], "law_firm_letter")
        self.assertEqual(facts["court_name"], "")
        self.assertIn("未能从起诉状提取文字；请在确认页补充或核对立案信息", warnings)

    def test_ocr_readiness_requires_named_rows_not_unnamed_defaults(self):
        facts = {"party_details": {
            "plaintiffs": [{"name": "示丆某", "document_number": "919999000000000002"}],
            "defendants": [{"name": "乙", "document_number": "990000199001010050"}],
            "third_parties": [],
        }}
        unnamed_defaults = [
            {"id": "p-1", "ssdw": filing.PARTY_ROLE_CODES["plaintiffs"], "dwmc": "", "zzhm": ""},
            {"id": "p-2", "ssdw": filing.PARTY_ROLE_CODES["defendants"], "xm": "", "zjhm": ""},
        ]
        self.assertFalse(filing._official_autofill_covers_local_parties(unnamed_defaults, facts))
        self.assertTrue(filing._official_autofill_covers_local_parties(unnamed_defaults + [
            {"id": "ocr-1", "dwmc": "示丆某", "zzhm": ""},
            {"id": "ocr-2", "xm": "乙", "zjhm": ""},
        ], facts))

    def test_entity_material_alias_maps_to_identity(self):
        self.assertEqual(filing._classify("原告主体资料.pdf"), "identity")
        self.assertEqual(filing._classify("26年周律师执业证.pdf"), "lawyer_certificate")

    def test_authority_agent_names_keeps_every_authorized_lawyer(self):
        text = "受委托人：示丂某律师，联系电话：18900001242。\n受委托人：示丁某律师，联系电话：18600001011。"
        self.assertEqual(filing._authority_agent_names(text), ["示丂某", "示丁某"])
        self.assertEqual(filing._authority_agent_names("受委托人：ABE，联系电话：18900001242。"), ["示丂某"])

    def test_dedupe_parties_and_nested_official_detail(self):
        parties = filing._dedupe_parties([
            {"name": "示丈某", "document_number": "990000199001010180", "address": ""},
            {"name": "示三某", "document_number": "990000199001010180", "address": "湛江市"},
        ])
        self.assertEqual(len(parties), 1)
        self.assertEqual(parties[0]["address"], "湛江市")
        layy, official_parties, agents, materials = filing._filing_detail_sections({
            "layyxq": {"layy": {"id": "draft-1"}, "dsrs": [{"id": "party-1"}],
                       "dlrs": [{"id": "agent-1"}], "sscls": [{"id": "material-1"}]}
        })
        self.assertEqual(layy["id"], "draft-1")
        self.assertEqual([item["id"] for item in official_parties], ["party-1"])
        self.assertEqual([item["id"] for item in agents], ["agent-1"])
        self.assertEqual([item["id"] for item in materials], ["material-1"])

    def test_party_match_reuses_delayed_official_placeholder(self):
        placeholder = {"id": "placeholder-1", "ssdw": filing.PARTY_ROLE_CODES["plaintiffs"],
                       "dwmc": "示丆某", "dsrlx": "1501_000011-3", "zzhm": ""}
        matched = filing._match_official_party(
            [placeholder], filing.PARTY_ROLE_CODES["plaintiffs"], "示丆某", "919999000000000002",
        )
        self.assertEqual(matched["id"], "placeholder-1")

    def test_party_match_does_not_overwrite_a_different_named_ocr_card(self):
        existing = [{
            "id": "ocr-1", "ssdw": filing.PARTY_ROLE_CODES["third_parties"],
            "dwmc": "近似但不同的组织", "dsrlx": "1501_000011-3", "zzhm": "",
        }]
        matched = filing._match_official_party(
            existing, filing.PARTY_ROLE_CODES["third_parties"], "另一家确认组织", "919999000000000002",
        )
        self.assertIsNone(matched)

    def test_one_character_ocr_variant_requires_name_and_address_proof(self):
        placeholder = {
            "ssdw": filing.PARTY_ROLE_CODES["third_parties"], "dwmc": "甲市示范路组织",
            "dwzsd": "甲市示范街100号", "zzhm": "",
        }
        real = {
            "ssdw": filing.PARTY_ROLE_CODES["third_parties"], "dwmc": "甲市示范路组织甲",
            "dwzsd": "甲市示范街100号甲", "zzhm": "919999000000000002",
        }
        self.assertTrue(filing._same_named_or_proven_ocr_variant(placeholder, real))
        self.assertFalse(filing._same_named_or_proven_ocr_variant(
            placeholder, {**real, "dwzsd": "完全不同地址"},
        ))

    def test_party_match_reuses_foreign_role_row_by_document(self):
        # A Court Online draft may report a party under a different `ssdw`
        # value (or none) than the role code this client sent.  The document
        # number is globally unique, so the client must reuse that row instead
        # of POSTing a second copy of the same party.
        existing = [
            {"id": "row-1", "ssdw": "", "dwmc": "虚构示例企业丏有限公司", "dsrlx": "1501_000011-2", "zzhm": "919999000000000007"},
        ]
        matched = filing._match_official_party(
            existing, filing.PARTY_ROLE_CODES["plaintiffs"],
            "虚构示例企业丏有限公司", "919999000000000007",
        )
        self.assertEqual(matched["id"], "row-1")

    def test_party_match_reuses_empty_foreign_placeholder_by_name(self):
        existing = [{"id": "ph", "ssdw": "", "xm": "示三某", "zjhm": ""}]
        matched = filing._match_official_party(
            existing, filing.PARTY_ROLE_CODES["defendants"], "示三某", "990000199001010180",
        )
        self.assertEqual(matched["id"], "ph")

    def test_partial_ocr_can_reuse_one_card_and_leave_other_party_for_create(self):
        # A partial OCR result must not block the second reviewed party.  The
        # caller PATCHes the matching card, then POSTs only the missing one.
        rows = [{"id": "ocr-plaintiff", "ssdw": filing.PARTY_ROLE_CODES["plaintiffs"], "dwmc": "示丆某", "zzhm": ""}]
        self.assertEqual(
            filing._match_official_party(rows, filing.PARTY_ROLE_CODES["plaintiffs"], "示丆某", "919999000000000002")["id"],
            "ocr-plaintiff",
        )
        self.assertIsNone(filing._match_official_party(rows, filing.PARTY_ROLE_CODES["defendants"], "乙", "990000199001010050"))

    def test_effective_parties_counts_visible_incomplete_duplicates(self):
        # Named incomplete cards are visible on the official page. The review
        # must report the problem instead of hiding it behind a 2/2 count.
        rows = [
            {"id": "0", "ssdw": "1501_030109-1", "dwmc": "虚构示例企业丏有限公司", "dsrlx": "1501_000011-2", "zzhm": "919999000000000007"},
            {"id": "1", "ssdw": "1501_030109-1", "dwmc": "虚构示例企业丏有限公司", "dsrlx": "1501_000011-3", "zzhm": ""},
            {"id": "2", "ssdw": "1501_030109-1", "dwmc": "虚构示例企业丏有限公司", "dsrlx": "1501_000011-3", "zzhm": ""},
            {"id": "3", "ssdw": "1501_030109-2", "xm": "示三某", "dsrlx": "1501_000011-1", "zjhm": "990000199001010180"},
            {"id": "4", "ssdw": "1501_030109-2", "xm": "示三某", "dsrlx": "1501_000011-1", "zjhm": ""},
        ]
        effective = filing._effective_official_parties(rows)
        self.assertEqual(len(effective), 5)
        self.assertEqual({filing._party_name(p) for p in effective}, {"虚构示例企业丏有限公司", "示三某"})

    def test_exact_duplicate_cleanup_never_acts_without_draft_identifiers(self):
        # Cleanup is destructive only against exact identity duplicates and
        # refuses to make any remote request until the court supplies both
        # draft identifiers.
        result = asyncio.run(filing._remove_exact_duplicate_party_rows({}, [{
            "id": "duplicate-1", "ssdw": filing.PARTY_ROLE_CODES["plaintiffs"],
            "dwmc": "示丆某", "zzhm": "919999000000000002",
        }]))
        self.assertEqual(result["removed"], 0)
        self.assertTrue(result["delete_errors"])

    def test_facts_reason_keeps_the_complete_pleading_body(self):
        source = "民事起诉状\n诉讼请求：请求判令付款。\n事实与理由：第一项事实。\n第二项理由。\n此致\n某人民法院"
        self.assertEqual(filing._extract_full_facts_reason(source), "第一项事实。\n第二项理由。")
        self.assertEqual(filing._extract_facts(source)["facts_reason"], "第一项事实。\n第二项理由。")

    def test_cause_uses_party_capacities_not_a_nearby_execution_label(self):
        source = """民事起诉状
原告（保全申请人）：示丆某
被告（案外人）：乙
诉讼请求：请求准许继续保全查封。
事实与理由：被告提出排除执行申请，现提起执行异议之诉。"""
        facts = filing._extract_facts(source)
        self.assertEqual(facts["cause"], "申请执行人执行异议之诉")
        self.assertEqual(facts["cause_decision"]["source"], "document_party_capacity")

    def test_cause_keeps_unknown_execution_subtype_open_for_review(self):
        source = """民事起诉状
原告：示丆某
被告：示一某
事实与理由：双方就执行异议之诉发生争议。"""
        self.assertEqual(filing._extract_facts(source)["cause"], "")

    def test_verified_cause_candidates_are_data_driven(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE case_manager_court_online_layy(court_name TEXT,cause TEXT,cause_code TEXT,detail_json TEXT,updated_at TEXT,id INTEGER)")
        conn.execute("INSERT INTO case_manager_court_online_layy VALUES(?,?,?,?,?,?)", (
            "甲人民法院", "示例案由甲", "A-1", "{}", "2026-01-01", 1,
        ))
        conn.execute("INSERT INTO case_manager_court_online_layy VALUES(?,?,?,?,?,?)", (
            "乙人民法院", "示例案由乙", "B-2", "{}", "2026-01-02", 2,
        ))
        candidates = filing._verified_cause_candidates(conn, "甲人民法院")
        self.assertEqual(candidates[0]["label"], "示例案由甲")
        self.assertEqual(candidates[0]["code"], "A-1")

    def test_ai_sources_include_complaint_authority_and_party_identity_only(self):
        sources = filing._ai_source_materials([
            {"name": "起诉状.docx", "category": "complaint", "path": "/a", "readable": True, "size_bytes": 1},
            {"name": "委托书.pdf", "category": "authority", "path": "/b", "readable": True, "size_bytes": 1},
            {"name": "原告资料.pdf", "category": "identity", "path": "/c", "readable": True, "size_bytes": 1},
            {"name": "身份证.pdf", "category": "identity", "path": "/d", "readable": True, "size_bytes": 1},
            {"name": "证据册.pdf", "category": "evidence", "path": "/e", "readable": True, "size_bytes": 1},
        ])
        self.assertEqual([item["category"] for item in sources], ["complaint", "authority", "identity", "identity"])

    def test_party_payload_uses_confirmed_fields_and_verified_codes(self):
        payload = filing._party_payload({
            "name": "示丆某", "identity_type": "legal_entity", "document_number": "919999000000000002",
            "address": "甲地", "legal_representative": {"name": "示七某", "title": "经理", "document_number": "990000199001010020", "mobile": "13800000200"},
        }, "plaintiffs", {"id": "draft-1", "fyid": "court-1"})
        self.assertEqual(payload["ssdw"], "1501_030109-1")
        self.assertEqual(payload["dsrlx"], filing.LEGAL_ENTITY_CODE)
        self.assertEqual(payload["zzlx"], filing.UNIFIED_CREDIT_CODE)
        self.assertEqual(payload["layyid"], "draft-1")
        self.assertNotIn("unknown", payload.values())

    def test_party_payload_rejects_unreviewed_identity(self):
        with self.assertRaises(Exception) as blocked:
            filing._party_payload({"name": "示丆某", "identity_type": "unknown", "document_number": "x"}, "plaintiffs", {"id": "draft-1", "fyid": "court-1"})
        self.assertEqual(getattr(blocked.exception, "status_code", None), 422)

    def test_natural_party_derives_gender_and_supports_third_party(self):
        payload = filing._party_payload({
            "name": "甲", "identity_type": "natural_person", "document_number": "990000199001010050",
            "nationality": "中国", "mobile": "13800000200", "address": "甲地",
        }, "third_parties", {"id": "draft-1", "fyid": "court-1"})
        self.assertEqual(payload["ssdw"], "1501_030109-5")
        self.assertEqual(payload["cgj"], "中国")
        self.assertEqual(payload["cxb"], "男")

    def test_agent_payload_binds_lawyer_to_confirmed_plaintiff(self):
        payload = filing._agent_payload(
            {"name": "示丅某", "document_number": "990000199001010020", "practice_number": "14400000000000000", "law_firm": "示万某事务所", "mobile": "13800000200"},
            {"id": "party-1", "dwmc": "示丆某"},
            {"id": "draft-1", "fyid": "court-1"},
        )
        self.assertEqual(payload["bdlrid"], "party-1")
        self.assertEqual(payload["dlrlx"], "1501_000013-1")
        self.assertEqual(payload["cdlrlx"], "执业律师")

    def test_material_slot_maps_reviewed_categories_to_official_slots(self):
        slots = [{"id": "complaint", "clmc": "起诉状"}, {"id": "agent", "clmc": "委托代理人委托手续和身份材料"}]
        self.assertEqual(filing._material_slot({"category": "complaint"}, slots)["id"], "complaint")
        self.assertEqual(filing._material_slot({"category": "law_firm_letter"}, slots)["id"], "agent")

    def test_service_address_requires_an_attached_file_not_a_generation_flag(self):
        empty_slot = [{"id": "service", "clmc": "送达地址确认书", "wjs": []}]
        attached_slot = [{"id": "service", "clmc": "送达地址确认书", "wjs": [{"id": "file-1"}]}]
        self.assertFalse(filing._service_address_is_attached(empty_slot))
        self.assertTrue(filing._service_address_is_attached(attached_slot))

    def test_service_address_uses_only_the_lawyer_designated_signature(self):
        signatures = [
            {"version": "20260622113345", "qssj": "2026-06-22 11:33:45", "osspath": "new"},
            {"version": "20251027175751", "qssj": "2025-10-27 17:57:51", "osspath": "selected"},
        ]
        self.assertEqual(filing._service_address_signature(signatures)["osspath"], "selected")

    def test_schema_and_scan_routes_keep_the_latest_job(self):
        db_path = Path(self.temp.name) / "test.db"

        def get_db():
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            return conn

        class App:
            def __init__(self): self.routes = {}
            def get(self, path):
                def deco(fn): self.routes[("GET", path)] = fn; return fn
                return deco
            def post(self, path):
                def deco(fn): self.routes[("POST", path)] = fn; return fn
                return deco
            def delete(self, path):
                def deco(fn): self.routes[("DELETE", path)] = fn; return fn
                return deco

        async def fake_ai(model, messages):
            self.assertEqual(model, "opencode:deepseek-v4-flash")
            self.assertTrue(messages)
            return json.dumps({
                "court_name": "佛山市南海区人民法院",
                "case_type": "民事一审",
                "cause": "买卖合同纠纷",
                "lawsuit_request": "请求判令被告支付货款。",
                "claim_amount": "100000元",
                "plaintiffs": [{"name": "示丆某", "identity_type": "legal_entity", "confidence": 0.96}],
                "defendants": [{"name": "示一某", "identity_type": "legal_entity", "confidence": 0.96}],
                "representation_mode": "lawyer_agent",
                "material_classifications": [{"name": "原告营业执照.pdf", "category": "identity", "confidence": 0.98, "reason": "营业执照"}],
                "field_confidence": {"court_name": 0.9}, "review_notes": ["请核对受诉法院。"],
            }, ensure_ascii=False)

        def fake_parse(path):
            return {"content": "此致 佛山市南海区人民法院。原告示丆某诉被告示一某买卖合同纠纷。"}

        class FakeRequest:
            def __init__(self, value): self.value = value
            async def json(self): return self.value

        app = App()
        filing.register_automated_filing_routes(app, get_db, parse_file=fake_parse, call_ai=fake_ai)
        self.assertIn(("POST", "/api/automated-filing/jobs/{job_id}/api-execute/ocr"), app.routes)
        with get_db() as conn:
            conn.execute("INSERT INTO automated_filing_jobs(folder_path,real_path,folder_name,status,created_at,updated_at) VALUES(?,?,?,'draft',?,?)",
                         (str(self.root), str(self.root.resolve()), self.root.name, "2026-01-01", "2026-01-01"))
            conn.commit()
        result = app.routes[("GET", "/api/automated-filing/jobs/latest")]()
        self.assertEqual(result["job"]["folder_name"], "网上立案")
        scanned = asyncio.run(app.routes[("POST", "/api/automated-filing/scan")](FakeRequest({"folder_path": str(self.root)})))
        enhanced = asyncio.run(app.routes[("POST", "/api/automated-filing/jobs/{job_id}/ai-extract")](scanned["id"]))
        self.assertEqual(enhanced["facts"]["court_name"], "佛山市南海区人民法院")
        self.assertEqual(enhanced["facts"]["plaintiffs"], ["示丆某"])
        self.assertEqual(enhanced["ai"]["field_confidence"]["court_name"], 0.9)
        with self.assertRaises(Exception) as blocked:
            asyncio.run(app.routes[("POST", "/api/automated-filing/jobs/{job_id}/confirm")](
                scanned["id"], FakeRequest({"facts": enhanced["facts"], "materials": enhanced["materials"]})
            ))
        self.assertEqual(getattr(blocked.exception, "status_code", None), 422)
        facts = dict(enhanced["facts"])
        facts.update({
            "case_name": "示丆某与示一某买卖合同纠纷",
            "party_details": {
                "plaintiffs": [{"name": "示丆某", "identity_type": "legal_entity", "document_number": "919999000000000002", "nationality": "中国", "address": "甲地"}],
                "defendants": [{"name": "示一某", "identity_type": "legal_entity", "document_number": "919999000000000003", "nationality": "中国", "address": "乙地"}],
                "third_parties": [],
            },
            "agents": [{"name": "示万某", "document_number": "990000199001010050", "practice_number": "14400000000000000", "law_firm": "示万某事务所"}],
            "agent": {"name": "示万某", "document_number": "990000199001010050", "practice_number": "14400000000000000", "law_firm": "示万某事务所"},
            "service_contact": {"mobile": "13800000200", "address": "甲地"},
        })
        confirmed = asyncio.run(app.routes[("POST", "/api/automated-filing/jobs/{job_id}/confirm")](
            scanned["id"], FakeRequest({"facts": facts, "materials": enhanced["materials"]})
        ))
        self.assertEqual(confirmed["status"], "confirmed")


if __name__ == "__main__":
    unittest.main()
