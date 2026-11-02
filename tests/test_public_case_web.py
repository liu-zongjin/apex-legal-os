import unittest
from unittest.mock import AsyncMock, patch

from backend import case_research, public_case_web

JUDGMENT_WIKITEXT = """{{Header/裁判文书
|title=某建设公司、某置业公司建设工程施工合同纠纷二审民事判决书
|court=中华人民共和国最高人民法院
|type=民事判决书
|案号=（2021）最高法民终958号
|year=2021
|month=12
|day=20
|docid=deadbeef
}}
{{gap}}上诉人某建设公司因与被上诉人某置业公司建设工程施工合同纠纷一案，不服高级人民法院民事判决，向本院提起上诉。

== 本院查明 ==
{{gap}}2016年，某资产公司将其对某置业公司的全部债权转让给某投资公司，转让协议约定建设工程价款优先受偿权随主债权一并转让。

== 本院认为 ==
{{gap}}建设工程价款优先受偿权系法定优先权，其功能在于保障承包人工程价款债权的实现，随主债权转让而转让，受让人可以主张建设工程价款优先受偿权。{{PRC-redact|1}}

判决如下：
驳回上诉，维持原判。

[[Category:2021年]]
[[Category:2021年12月20日]]
[[Category:中华人民共和国民事判决书]]
[[Category:中华人民共和国最高人民法院]]
"""

DISAMBIG_WIKITEXT = """{{裁判文书消歧义页
| title = 中华人民共和国最高人民法院（2021）最高法知民终2480号民事判决书
| court = 中华人民共和国最高人民法院
| type = 民事判决书
}}
* [[美国某公司、岳阳某生物科技公司等侵害发明专利权纠纷二审判决书]]
"""

PLAN = {
    "core_issue": "建设工程价款债权转让后受让人能否主张优先受偿权",
    "essential_terms": ["建设工程价款", "债权转让", "受让人", "优先受偿权"],
    "required_term_groups": [
        ["建设工程价款", "工程价款"],
        ["债权转让", "转让"],
        ["优先受偿权", "优先权"],
    ],
    "strict_issue_match": True,
}

FIXED_QUERY = "建设工程价款债权转让后，受让人能否主张建设工程价款优先受偿权？"


class WikiSourceQueryTests(unittest.TestCase):
    def test_plan_becomes_issue_queries(self):
        queries = public_case_web.build_wikisource_queries(PLAN)
        self.assertTrue(queries)
        self.assertEqual(queries[0]["id"], "issue_groups")
        self.assertIn("建设工程价款", queries[0]["query"])
        self.assertIn("债权转让", queries[0]["query"])

    def test_case_number_query_uses_intitle(self):
        plan = dict(PLAN, core_issue="参见（2021）最高法民终958号裁判观点")
        queries = public_case_web.build_wikisource_queries(plan)
        self.assertTrue(any(query["query"].startswith("intitle:") for query in queries))


class JudgmentParseTests(unittest.TestCase):
    def test_header_fields_and_excerpt(self):
        case = public_case_web.parse_judgment_page(
            "某建设公司、某置业公司建设工程施工合同纠纷二审民事判决书",
            JUDGMENT_WIKITEXT,
            required_terms=["债权转让", "优先受偿权"],
        )
        self.assertEqual(case["case_number"], "（2021）最高法民终958号")
        self.assertEqual(case["court"], "中华人民共和国最高人民法院")
        self.assertEqual(case["judgment_date"], "2021-12-20")
        self.assertEqual(case["source_kind"], "wikisource")
        self.assertEqual(case["authority_type"], "最高人民法院案例")
        self.assertIn("债权转让", case["matched_excerpt"])
        self.assertIn("优先受偿权", case["holding"])
        self.assertNotIn("{{", case["holding"])
        self.assertTrue(case["source_url"].startswith("https://zh.wikisource.org/wiki/"))

    def test_disambiguation_page_is_detected(self):
        self.assertTrue(public_case_web.is_disambiguation(DISAMBIG_WIKITEXT, "（2021）最高法民终958号民事判决书"))
        self.assertFalse(public_case_web.is_disambiguation(JUDGMENT_WIKITEXT, "某建设工程施工合同纠纷案"))

    def test_link_targets_keep_judgment_links_only(self):
        targets = public_case_web._link_targets(DISAMBIG_WIKITEXT)
        self.assertEqual(targets, ["美国某公司、岳阳某生物科技公司等侵害发明专利权纠纷二审判决书"])


class PublicCaseSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_only_search_never_touches_mcp(self):
        fake_case = public_case_web.parse_judgment_page(
            "某建设公司、某置业公司建设工程施工合同纠纷二审民事判决书",
            JUDGMENT_WIKITEXT,
            required_terms=["债权转让", "优先受偿权"],
        )
        public_result = {
            "cases": [fake_case],
            "retrieval_runs": [{"source": "wikisource", "query_id": "neutral", "query": "x", "result_count": 1}],
            "errors": [],
        }
        mcp = AsyncMock()
        with patch("backend.public_case_web.search_public_cases", AsyncMock(return_value=public_result)), patch.object(
            case_research, "search_authoritative_cases", mcp
        ):
            result = await case_research.search_cases_structured(
                FIXED_QUERY, top_k=5, sources=("wikisource",)
            )
        mcp.assert_not_awaited()
        self.assertEqual(len(result["cases"]), 1)
        self.assertEqual(result["coverage"]["sources_used"], ["wikisource"])
        self.assertEqual(result["cases"][0]["verification"]["status"], "archived")
        self.assertEqual(result["cases"][0]["verification"]["authority_status"], "public_archive")
        self.assertIn("网络公开裁判文书案例数据库（公开存档）", result["result"])
        self.assertNotIn("维基文库", result["result"])

    async def test_public_failure_returns_empty_instead_of_502(self):
        with patch(
            "backend.public_case_web.search_public_cases",
            AsyncMock(side_effect=public_case_web.PublicCaseError("维基文库暂不可达：ConnectTimeout")),
        ):
            result = await case_research.search_cases_structured(
                FIXED_QUERY, top_k=5, sources=("wikisource",)
            )
        self.assertEqual(result["cases"], [])
        self.assertTrue(result["errors"])
        self.assertIn("部分检索或正文读取未完成", result["result"])
        self.assertIn("不代表相关案例不存在", result["result"])


if __name__ == "__main__":
    unittest.main()


class AutoMcpGateTests(unittest.TestCase):
    """公开互联网案例模式、仅本地模式都不得自动补检 MCP。"""

    def test_public_web_and_local_only_block_auto_mcp(self):
        import asyncio

        # 前面的用例可能已关闭事件循环；backend.main 在导入时创建 asyncio.Lock。
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())
        from backend.main import _auto_mcp_allowed

        self.assertFalse(_auto_mcp_allowed("public_web_cases", False))
        self.assertFalse(_auto_mcp_allowed("public_web_cases", True))
        self.assertFalse(_auto_mcp_allowed("local_only", False))
        self.assertTrue(_auto_mcp_allowed("hybrid", False))
        self.assertFalse(_auto_mcp_allowed("hybrid", True))
        # 用户已显式勾选 MCP 时同样关闭自动补检，避免夹带未勾选来源。
        self.assertFalse(_auto_mcp_allowed("mcp:aluris", True))


class PublicCaseResilienceTests(unittest.IsolatedAsyncioTestCase):
    """限流、缓存与检索式去重：这三处决定了公开检索在真实网络下的可用性。"""

    def test_identical_bag_of_words_is_sent_once(self):
        plan = dict(PLAN, essential_terms=["建设工程价款", "优先受偿权", "债权转让"], required_term_groups=[
            ["建设工程价款"], ["优先受偿权"], ["债权转让"],
        ])
        queries = public_case_web.build_wikisource_queries(plan)
        bags = {tuple(sorted(query["query"].split())) for query in queries}
        self.assertEqual(len(bags), len(queries))

    async def test_fresh_cache_skips_network(self):
        plan = dict(PLAN)
        case = public_case_web.parse_judgment_page(
            "某建设公司建设工程施工合同纠纷民事判决书", JUDGMENT_WIKITEXT, required_terms=["债权转让"]
        )
        import tempfile
        from pathlib import Path
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        cache_patch = patch.object(public_case_web, "_cache_path", return_value=Path(folder.name) / "cache.db")
        cache_patch.start()
        self.addCleanup(cache_patch.stop)
        key = public_case_web._cache_key(plan, 2)
        public_case_web._cache_store(key, plan, [case], [{"source": "wikisource", "result_count": 1}])
        network = AsyncMock()
        with patch.object(public_case_web, "_search_titles", network), patch.object(
            public_case_web, "_fetch_pages", network
        ):
            result = await public_case_web._search_wikisource_cases(plan, limit=2)
        network.assert_not_awaited()
        self.assertEqual(len(result["cases"]), 1)
        self.assertEqual(result["retrieval_runs"][0]["cache"], "fresh")

    async def test_busy_search_falls_back_to_rest(self):
        session = AsyncMock()
        rest_hits = [{"title": "某判决书", "snippet": "x", "wordcount": 0}]
        with patch.object(public_case_web, "_api_search", AsyncMock(
            side_effect=public_case_web.PublicCaseError("维基文库检索排队（Search is currently too busy）")
        )), patch.object(public_case_web, "_html_search", AsyncMock(side_effect=public_case_web.PublicCaseError("网页不可达"))), patch.object(public_case_web, "_rest_search", AsyncMock(return_value=rest_hits)) as rest:
            hits = await public_case_web._search_titles(session, "建设工程价款", 2)
        rest.assert_awaited_once()
        self.assertEqual(hits, rest_hits)
