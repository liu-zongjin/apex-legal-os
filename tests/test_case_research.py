import unittest
from unittest.mock import AsyncMock, patch

from backend import case_research
from backend.case_authority import sort_cases_by_authority


FIXED_QUERY = (
    "建设工程价款债权转让后，受让人能否主张建设工程价款优先受偿权？"
    "请检索最高人民法院及高级人民法院的代表性案例，每案给出原文链接。"
)


def card(
    title="示丆某与示一某建设工程施工合同纠纷案",
    number="（2024）最高法民终1号",
    rule="建设工程价款债权转让后，受让人可以随主债权取得优先受偿权。",
    score="0.8000",
):
    return f"""权威案例与司法规则检索—— 返回 1 个结果

## 1. {title}

来源：公报案例  |  权威类型：最高法公报案例  |  引用价值：权威参考  |  规则质量：A  |  案号：{number}  |  年份：2024  |  综合分：{score}

案例详情摘要：类别 民事；法院 最高人民法院；案号 {number}

命中原文依据：{rule}
来源位置：裁判摘要

裁判规则：{rule}

原文链接：[原文](https://gongbao.court.gov.cn/Details/example.html)
"""


class CaseQueryPlannerTests(unittest.TestCase):
    def test_strips_delivery_requirements_and_builds_three_routes(self):
        plan = case_research.build_case_query_plan(FIXED_QUERY)
        self.assertNotIn("每案给出", plan["core_issue"])
        self.assertEqual([item["id"] for item in plan["queries"]], ["neutral", "support", "oppose"])
        self.assertIn("从权利随主债权转让", plan["queries"][1]["query"])
        self.assertIn("专属于承包人", plan["queries"][2]["query"])
        self.assertTrue(plan["strict_issue_match"])

    def test_generic_question_still_gets_balanced_queries(self):
        plan = case_research.build_case_query_plan("表见代理如何认定？请列出案例")
        self.assertEqual(plan["core_issue"], "表见代理如何认定")
        self.assertIn("不予支持", plan["queries"][2]["query"])
        self.assertFalse(plan["strict_issue_match"])

    def test_sequential_guarantee_query_keeps_direction_as_hard_constraint(self):
        plan = case_research.build_case_query_plan(
            "债权人先起诉连带责任保证人承担保证责任，后另行起诉主债务人，是否构成重复起诉"
        )
        self.assertTrue(plan["strict_issue_match"])
        self.assertEqual(plan["fact_fingerprint"]["direction"], "guarantor_to_debtor")

    def test_revocation_fee_query_uses_fee_routes_and_records_constraints(self):
        plan = case_research.build_case_query_plan(
            "案例检索：广东省内或其他省的中级人民法院法院的以下案件是如何收费的："
            "债务人无偿放弃到期债权，债权人就此提起撤销权诉讼的诉讼费如何收取？"
        )
        queries = {item["id"]: item["query"] for item in plan["queries"]}
        self.assertIn("受理费", queries["neutral"])
        self.assertIn("按件收费", queries["support"])
        self.assertIn("标的额", queries["oppose"])
        self.assertEqual(plan["search_constraints"]["court_levels"], ["intermediate"])
        for query in queries.values():
            self.assertNotIn("中级人民法院", query)
            self.assertNotIn("广东省", query)


class CaseMarkdownParserTests(unittest.TestCase):
    def test_cases_follow_the_required_six_level_authority_order(self):
        cases = [
            {"title": "基层案", "court": "广州市天河区人民法院", "final_score": 1},
            {"title": "其他高院案", "court": "四川省高级人民法院", "final_score": 1},
            {"title": "广东高院案", "court": "广东省高级人民法院", "final_score": 1},
            {"title": "最高院案", "case_number": "（2024）最高法民终1号", "final_score": 1},
            {"title": "参考案例案", "authority_type": "人民法院案例库参考案例", "final_score": 1},
            {"title": "指导案例案", "authority_type": "最高人民法院指导性案例", "final_score": 1},
        ]
        ordered = sort_cases_by_authority(cases)
        self.assertEqual(
            [item["title"] for item in ordered],
            ["指导案例案", "参考案例案", "最高院案", "广东高院案", "其他高院案", "基层案"],
        )
        self.assertEqual(
            [item["authority_order_label"] for item in ordered],
            ["指导案例", "参考案例", "普通最高院案例", "广东高院案例", "其他高院案例", "其他法院案例"],
        )

    def test_parses_stable_case_fields_without_inventing_missing_date(self):
        cases = case_research.parse_case_search_markdown(card(), "support")
        self.assertEqual(len(cases), 1)
        parsed = cases[0]
        self.assertEqual(parsed["case_number"], "（2024）最高法民终1号")
        self.assertEqual(parsed["court"], "最高人民法院")
        self.assertEqual(parsed["judgment_date"], "")
        self.assertEqual(parsed["viewpoint"], "support")
        self.assertEqual(parsed["retrieved_by"], ["support"])

    def test_deduplicates_by_case_number_and_preserves_query_routes(self):
        one = case_research.parse_case_search_markdown(card(score="0.6"), "neutral")[0]
        two = case_research.parse_case_search_markdown(card(score="0.9"), "support")[0]
        merged = case_research.deduplicate_cases([one, two])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["remote_score"], 0.9)
        self.assertEqual(merged[0]["retrieved_by"], ["neutral", "support"])

    def test_strict_issue_ranking_rejects_generic_priority_case(self):
        generic = card(rule="承包人可以在执行程序中对建设工程价款主张优先受偿权。")
        parsed = case_research.parse_case_search_markdown(generic)[0]
        ranked = case_research.rank_cases([parsed], case_research.build_case_query_plan(FIXED_QUERY))
        self.assertEqual(ranked[0]["issue_match"], "related")

    def test_directional_ranking_places_5989_structure_before_reverse_case(self):
        query = "债权人先诉连带责任保证人，后另行起诉主债务人，是否构成重复起诉"
        plan = case_research.build_case_query_plan(query)
        direct = {
            "title": "黄某民间借贷纠纷二审裁定书", "case_number": "（2021）粤01民终5989号",
            "court": "广东省广州市中级人民法院", "authority_type": "普通案例",
            "factual_summary": "另案向保证人主张连带保证责任后，仍可向主债务人主张清偿责任。",
            "matched_excerpt": "主债务人与连带保证人责任各自独立，两者为不同法律关系。",
            "holding": "属于可分之诉，可以分别起诉；双重受益属于判项或执行问题。",
            "remote_score": 0.5, "retrieved_by": ["directional_2"], "viewpoint": "support",
        }
        reverse = {
            "title": "某保证合同纠纷二审判决书", "case_number": "（2018）某民终1号",
            "court": "某高级人民法院", "authority_type": "普通案例",
            "factual_summary": "前案起诉主债务人，此后又另行起诉连带责任保证人。",
            "matched_excerpt": "不构成重复起诉。", "holding": "保证人承担责任。",
            "remote_score": 0.9, "retrieved_by": ["neutral"], "viewpoint": "support",
        }
        ranked = case_research.rank_cases([reverse, direct], plan)
        self.assertEqual(ranked[0]["case_number"], "（2021）粤01民终5989号")
        self.assertEqual(ranked[0]["match_tier"], "highly_similar")
        self.assertEqual(ranked[1]["match_tier"], "reverse_direction")


class StructuredSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_multi_route_search_returns_compatible_text_and_structured_cases(self):
        with patch.object(
            case_research, "search_authoritative_cases", AsyncMock(return_value=card())
        ) as search, patch.object(
            case_research,
            "verify_case_source",
            AsyncMock(return_value={
                "authority_status": "official",
                "link_status": "reachable",
                "identifier_match": True,
                "holding_match": True,
                "status": "verified",
                "notes": [],
            }),
        ):
            result = await case_research.search_cases_structured(FIXED_QUERY, top_k=5)
        self.assertEqual(search.await_count, 3)
        self.assertEqual(len(result["cases"]), 1)
        self.assertEqual(result["cases"][0]["verification"]["status"], "verified")
        self.assertIn("裁判规则", result["result"])
        self.assertIn("query_plan", result)
        self.assertNotIn("raw_markdown", result["cases"][0])

    async def test_strict_query_returns_empty_instead_of_generic_fillers(self):
        generic = card(rule="承包人可以在执行程序中对建设工程价款主张优先受偿权。")
        with patch.object(
            case_research, "search_authoritative_cases", AsyncMock(return_value=generic)
        ):
            result = await case_research.search_cases_structured(
                FIXED_QUERY, top_k=5, verify_sources=False
            )
        self.assertEqual(result["cases"], [])
        self.assertIn("未检得符合当前争点约束", result["result"])


if __name__ == "__main__":
    unittest.main()
