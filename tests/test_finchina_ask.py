import unittest
from unittest.mock import AsyncMock, patch

from backend import finchina_mcp


class FinChinaNameExtractionTests(unittest.TestCase):
    def test_full_width_name_extracted(self):
        self.assertEqual(
            finchina_mcp._extract_company_name("查询腾讯科技（深圳）有限公司的涉诉情况"),
            "腾讯科技（深圳）有限公司",
        )

    def test_book_quoted_name_extracted(self):
        self.assertEqual(
            finchina_mcp._extract_company_name("查一下《华为技术有限公司》的处罚记录"),
            "华为技术有限公司",
        )

    def test_bare_group_suffix_extracted(self):
        self.assertEqual(
            finchina_mcp._extract_company_name("请帮我检索阿里巴巴集团的司法案件"),
            "阿里巴巴集团",
        )

    def test_no_company_returns_empty(self):
        self.assertEqual(finchina_mcp._extract_company_name("预约合同能否强制履行？"), "")

    def test_searchable_variants_order(self):
        variants = finchina_mcp._searchable_name("腾讯科技（深圳）有限公司")
        self.assertEqual(variants[0], "腾讯科技(深圳)有限公司")
        self.assertIn("腾讯科技", variants)
        self.assertIn("腾讯科技有限公司", variants)


class FinChinaProfileRowsTests(unittest.TestCase):
    def test_parses_current_three_column_profile_response(self):
        payload = {
            "data": {"records": {
                "headInfo": [
                    {"field": "company_name", "name": "企业名称"},
                    {"field": "index_name", "name": "指标名"},
                    {"field": "index_value", "name": "指标值"},
                ],
                "data": [
                    ["广州市粤达轮胎贸易有限公司", "成立日期", "2023-01-05"],
                    ["广州市粤达轮胎贸易有限公司", "法定代表人", "王星"],
                ],
            }},
        }
        self.assertEqual(finchina_mcp._profile_rows(payload), {
            "成立日期": "2023-01-05",
            "法定代表人": "王星",
        })

    def test_keeps_legacy_two_column_profile_response_compatible(self):
        payload = {"data": {"records": {"data": [["成立日期", "2023-01-05"]]}}}
        self.assertEqual(finchina_mcp._profile_rows(payload), {"成立日期": "2023-01-05"})


class FinChinaPickBestCandidateTests(unittest.TestCase):
    def test_exact_normalised_name_wins(self):
        candidates = [
            {"name": "林芝腾讯科技有限公司"},
            {"name": "腾讯科技(深圳)有限公司"},
            {"name": "广州腾讯科技有限公司"},
        ]
        best = finchina_mcp._pick_best_candidate(candidates, "腾讯科技（深圳）有限公司")
        self.assertEqual(best["name"], "腾讯科技(深圳)有限公司")

    def test_closest_suffix_wins_when_no_exact(self):
        candidates = [
            {"name": "阿里巴巴集团(全球)投资控股有限公司"},
            {"name": "阿里巴巴集团(中国)有限公司"},
            {"name": "阿里巴巴集团控股有限公司"},
        ]
        best = finchina_mcp._pick_best_candidate(candidates, "阿里巴巴集团")
        self.assertIn("阿里巴巴集团", best["name"])


class FinChinaSearchCompanyTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_company_returns_compact_profile_and_scan(self):
        profile = {
            "name": "华为技术有限公司", "identity_code": "919999000000000004",
            "legal_representative": "赵明路", "registration_status": "存续",
            "registered_capital": "4064113.2686万元", "establishment_date": "1987-09-15",
            "region": "广东省 / 深圳市", "business_scope": "程控交换机",
            "data_source": "财汇企业预警通",
        }
        events = [
            {
                "title": "华为技术有限公司 · 司法案件", "date": "2026-01-01",
                "domain": "企业诉讼", "category": "judicial", "risk_level": "high",
                "risk_score": 58, "summary": "合同纠纷", "body_text": "x" * 200,
            }
        ]
        with patch.object(finchina_mcp, "_extract_company_name", return_value="华为技术有限公司"), \
             patch.object(finchina_mcp, "_resolve_company_candidates", new=AsyncMock(
                 return_value=("华为技术有限公司", [{"name": "华为技术有限公司"}])
             )), \
             patch.object(finchina_mcp, "_pick_best_candidate", return_value={"name": "华为技术有限公司"}), \
             patch.object(finchina_mcp, "lookup_company_profile", new=AsyncMock(return_value=profile)), \
             patch.object(finchina_mcp, "plan_finchina_intelligence_categories", new=AsyncMock(
                 return_value=["judicial"]
             )), \
             patch.object(finchina_mcp, "query_company_intelligence", new=AsyncMock(return_value={
                 "results": events, "total_returned": 1, "total_matches": 5,
                 "totals": {"judicial": 5}, "errors": {}, "companies": ["华为技术有限公司"],
                 "categories": finchina_mcp._ASK_INTELLIGENCE_CATEGORIES,
                 "days": 3650, "risk_counts": {}, "risk_score": 58,
                 "data_source": "财汇企业预警通",
             })):
            payload = await finchina_mcp.search_company("查一下华为技术有限公司的风险")

        import json
        data = json.loads(payload)
        self.assertEqual(data["工商画像"]["name"], "华为技术有限公司")
        scan = data["风险扫描"]
        self.assertEqual(scan["总命中数"], 5)
        self.assertEqual(scan["各维度"]["judicial"]["事件"][0]["标题"], "华为技术有限公司 · 司法案件")

    async def test_search_company_raises_when_name_missing(self):
        with patch.object(finchina_mcp, "_extract_company_name", return_value=""):
            with self.assertRaises(finchina_mcp.FinChinaError):
                await finchina_mcp.search_company("合同纠纷怎么处理")

    async def test_search_company_raises_when_no_candidates(self):
        with patch.object(finchina_mcp, "_extract_company_name", return_value="不存在的公司有限公司"), \
             patch.object(finchina_mcp, "_resolve_company_candidates", new=AsyncMock(side_effect=finchina_mcp.FinChinaError("未找到"))):
            with self.assertRaises(finchina_mcp.FinChinaError):
                await finchina_mcp.search_company("查询不存在的公司有限公司的情况")


if __name__ == "__main__":
    unittest.main()
