import asyncio
import copy
import json
import sqlite3
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from backend import court_filing_ocr as guard
from backend import court_online_service as court


class CourtFilingOcrTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute("CREATE TABLE automated_filing_jobs(id INTEGER,status TEXT,facts_json TEXT)")
        self.db.execute("INSERT INTO automated_filing_jobs VALUES(1,?,?)", (
            "api_service_address_generated", json.dumps({"api_draft_id": "draft"})))
        self.rows = [
            {"id": "original-" + str(i), "ssdw": str(i), "xm": "当事人" + str(i),
             "zjhm": "ID" + str(i), "dz": "地址", "dsrlx": "1"}
            for i in (1, 2, 3)
        ]
        self.agents = [{"id": "agent", "bdlrid": "original-1,original-3"}]
        self.calls = []
        self.counter = 0
        self.delete_noop = False
        self.handler = guard.make_ocr_handler(lambda: self.db, self.call, lambda *args: None)

    def tearDown(self):
        self.db.close()

    async def call(self, method, path):
        self.calls.append((method, path))
        if method == "DELETE":
            if not self.delete_noop:
                self.rows = [row for row in self.rows if row["id"] != path.rsplit("/", 1)[-1]]
            return None
        return {"layy": {"id": "draft", "zt": "11800007-100"},
                "dsrs": copy.deepcopy(self.rows), "dlrs": copy.deepcopy(self.agents)}

    def route(self, draft="draft", extra=None):
        test = self

        class Route:
            request = type("Request", (), {"method": "GET", "url":
                "https://zxfw.court.gov.cn" + guard.OCR_PATH + "?layyId=" + draft})()
            continued = False
            result = None
            fetched = 0

            async def continue_(self):
                self.continued = True

            async def fetch(self, **kwargs):
                self.fetched += 1
                test.assertEqual(kwargs["max_retries"], 0)
                test.counter += 1
                for i in (1, 2, 3):
                    test.rows.append({"id": f"ocr-{test.counter}-{i}", "ssdw": str(i),
                                      "xm": "当事人" + str(i), "dz": "地址", "dsrlx": "1"})
                if extra:
                    test.rows.append(copy.deepcopy(extra))
                # Simulate two tabs clicking concurrently.
                await asyncio.sleep(0)
                return type("Response", (), {"status": 200,
                    "json": AsyncMock(return_value={"code": 200, "data": {"ocrText": "原文"}})})()

            async def fulfill(self, **kwargs):
                self.result = kwargs
                if "response" in kwargs:
                    test.assertEqual(len([r for r in test.rows if r["id"].startswith("ocr-")]), 0)

        return Route()

    async def test_material_next_click_twice_and_new_tab_preserve_ids_and_agents(self):
        original = copy.deepcopy(self.rows)
        routes = [self.route(), self.route()]
        await asyncio.gather(*(self.handler(route) for route in routes))
        self.assertEqual(self.rows, original)
        self.assertEqual(self.agents[0]["bdlrid"], "original-1,original-3")
        self.assertEqual(len([x for x in self.calls if x[0] == "DELETE"]), 6)
        for route in routes:
            self.assertFalse(route.continued)
            self.assertEqual(route.fetched, 1)
            self.assertIn("response", route.result)

    async def test_unrelated_new_party_is_preserved(self):
        new = {"id": "new-party", "ssdw": "2", "xm": "新增当事人"}
        await self.handler(self.route(extra=new))
        self.assertIn(new, self.rows)
        self.assertEqual(len(self.rows), 4)

    async def test_no_success_until_delete_is_verified(self):
        self.delete_noop = True
        route = self.route()
        await self.handler(route)
        self.assertEqual(route.result["status"], 409)
        self.assertFalse(route.continued)
        self.assertEqual(route.fetched, 1)

    async def test_ocr_timeout_is_not_replayed(self):
        route = self.route()
        route.fetch = AsyncMock(side_effect=TimeoutError())
        await self.handler(route)
        self.assertEqual(route.result["status"], 409)
        route.fetch.assert_awaited_once()
        self.assertFalse(route.continued)

    async def test_unmanaged_draft_is_untouched(self):
        route = self.route("unmanaged")
        await self.handler(route)
        self.assertTrue(route.continued)
        self.assertEqual(route.fetched, 0)
        self.assertEqual(self.calls, [])

    async def test_active_api_write_does_not_race_browser_ocr(self):
        self.db.execute("UPDATE automated_filing_jobs SET status='api_writing_parties'")
        route = self.route()
        await self.handler(route)
        self.assertEqual(route.result["status"], 409)
        self.assertEqual(route.fetched, 0)

    async def test_same_name_other_role_document_conflicts_and_references_are_kept(self):
        before = [self.rows[0]]
        rows = [
            {"id": "other-role", "ssdw": "2", "xm": "当事人1"},
            {"id": "other-id", "ssdw": "1", "xm": "当事人1", "zjhm": "DIFFERENT"},
            {"id": "referenced", "ssdw": "1", "xm": "当事人1"},
            {"id": "other-address", "ssdw": "1", "xm": "当事人1", "dz": "不同地址"},
        ]
        self.assertEqual(guard.duplicate_ids(before, rows, [{"bdlrid": "referenced"}]), [])
        self.assertEqual(guard.duplicate_ids(before + [dict(before[0], id="ambiguous", zjhm="OTHER")],
                                             [{"id": "ocr", "ssdw": "1", "xm": "当事人1"}], []), [])

    async def test_token_api_does_not_retry_mutating_ocr_get(self):
        client = AsyncMock()
        client.get.side_effect = httpx.ReadTimeout("timeout")
        with patch.object(court, "_read_secret", return_value={"session_token": "test"}), \
                patch.object(court.httpx, "AsyncClient", return_value=client):
            with self.assertRaises(court.CourtOnlineError):
                await court.automated_filing_api_call("GET", "/yzw-zxfw-lafw/api/v3/layy/ocr", {"layyId": "draft"})
        client.get.assert_awaited_once()

    async def test_screenshot_organisation_missing_uncommon_character(self):
        original = {"id": "original-org", "ssdw": "3", "dwmc": "新园街道菉塘村第十四集体经济组织",
                    "zzhm": "EXAMPLE", "dwzsd": "新园街道菉塘上坡塘村85号", "fddbrxm": "代表甲"}
        ocr = dict(original, id="ocr-org", dwmc="新园街道塘村第十四集体经济组织", zzhm="", dsrlx="1501_000011-3")
        self.assertEqual(guard.duplicate_ids([original], [original, ocr], []), ["ocr-org"])
        self.assertEqual(guard.duplicate_ids([original], [dict(ocr, dwzsd="新园街道塘上坡塘村85号")], []), ["ocr-org"])
        for changed in [dict(ocr, fddbrxm="代表乙"), dict(ocr, dwzsd="另一个地址"),
                        dict(ocr, dwzsd="新园街道菉塘上坡塘村86号"),
                        dict(ocr, ssdw="2"), dict(ocr, zzhm="OTHER"), dict(ocr, fddbrxm="")]:
            self.assertEqual(guard.duplicate_ids([original], [changed], []), [])

    async def test_page_response_uses_verified_rows_even_when_upstream_is_stale(self):
        original = {"id": "original-org", "ssdw": "3", "dwmc": "新园街道菉塘村第十四集体经济组织",
                    "zzhm": "EXAMPLE", "dwzsd": "新园街道菉塘上坡塘村85号", "fddbrxm": "代表甲"}
        self.rows.append(original)
        stale = dict(original, id="already-deleted", dwmc="新园街道塘村第十四集体经济组织",
                     dwzsd="新园街道塘上坡塘村85号", zzhm="")
        upstream = {"code": 200, "data": {"dsrs": copy.deepcopy(self.rows) + [stale],
                    "layy": {"id": "draft", "zt": "11800007-100"}, "dlrs": copy.deepcopy(self.agents),
                    "sscls": [{"id": "keep-attachment"}]}}
        route = self.route()
        route.request = type("Request", (), {"method": "GET", "url":
            "https://zxfw.court.gov.cn/yzw/yzw-zxfw-lafw/api/v3/layy/layyxq/draft/0"})()
        route.fetch = AsyncMock(return_value=type("Response", (), {"status": 200,
            "headers": {"content-length": "99999", "content-encoding": "gzip", "token": "test"},
            "json": AsyncMock(return_value=upstream)})())
        await self.handler(route)
        # This is the JSON actually delivered to the page, not just the
        # backend count. The old OCR-only route let the stale card through.
        self.assertEqual(route.result["json"]["data"]["dsrs"], self.rows)
        self.assertEqual(route.result["json"]["data"]["sscls"], [{"id": "keep-attachment"}])
        self.assertNotIn("content-length", route.result["headers"])
        self.assertNotIn("content-encoding", route.result["headers"])
        self.assertEqual(route.result["headers"]["token"], "test")
        self.assertFalse(any(method == "DELETE" for method, _ in self.calls))

    async def test_page_response_never_hides_unmatched_manual_party(self):
        route = self.route()
        route.request = type("Request", (), {"method": "GET", "url":
            "https://zxfw.court.gov.cn/yzw/yzw-zxfw-lafw/api/v3/layy/layyxq/draft/0"})()
        upstream = {"code": 200, "data": {"dsrs": copy.deepcopy(self.rows) + [
            {"id": "manual", "ssdw": "3", "xm": "新的主体"}]}}
        route.fetch = AsyncMock(return_value=type("Response", (), {"status": 200, "json": AsyncMock(return_value=upstream)})())
        await self.handler(route)
        self.assertEqual(route.result["status"], 409)


if __name__ == "__main__":
    unittest.main()
