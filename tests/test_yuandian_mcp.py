import json
import unittest
from unittest.mock import AsyncMock, patch

from backend import yuandian_mcp


class YuandianQueryPlanTests(unittest.TestCase):
    def test_appointment_query_removes_delivery_noise_and_adds_synonyms(self):
        plan = yuandian_mcp.build_case_query_plan(
            '检索支持“预约合同不能强制履行”这一观点的裁判案例'
        )
        self.assertIn("预约合同", plan["essential_terms"])
        self.assertIn("强制履行", plan["essential_terms"])
        self.assertIn("本约合同", plan["essential_terms"])
        self.assertNotIn("裁判案例", plan["keyword_queries"][0])
        self.assertEqual(plan["keyword_queries"][0], "预约合同 强制履行 本约合同")

    def test_terrace_query_keeps_causal_factors_instead_of_generic_words(self):
        plan = yuandian_mcp.build_case_query_plan(
            "赠送露台排水口堵塞，暴雨后从烟道倒灌，物业是否担责？找真实案例"
        )
        self.assertEqual(plan["keyword_queries"][0], "露台 排水口 暴雨")
        self.assertIn("物业公司", plan["essential_terms"])
        self.assertIn("共有部分", plan["essential_terms"])

    def test_revocation_fee_query_strips_filter_noise_and_builds_issue_routes(self):
        plan = yuandian_mcp.build_case_query_plan(
            "案例检索：广东省内或其他省的中级人民法院法院的以下案件是如何收费的："
            "债务人无偿放弃到期债权，债权人就此提起撤销权诉讼的诉讼费如何收取？"
        )
        terms = " ".join(plan["essential_terms"])
        for noise in ("中级", "广东省", "以下"):
            self.assertNotIn(noise, terms)
        joined = " ".join(plan["keyword_queries"])
        self.assertIn("撤销权", joined)
        self.assertIn("放弃", joined)
        self.assertIn("受理费", joined)
        constraints = plan["search_constraints"]
        self.assertEqual(constraints["court_levels"], ["intermediate"])
        self.assertEqual(constraints["strict_regions"], [])

    def test_guarantee_query_adds_directional_routes(self):
        plan = yuandian_mcp.build_case_query_plan(
            "债权人先起诉连带责任保证人，后另行起诉主债务人，是否构成重复起诉"
        )
        self.assertEqual(plan["fact_fingerprint"]["direction"], "guarantor_to_debtor")
        self.assertEqual(plan["keyword_queries"][1], "保证责任 后 仍可 主债务人")
        self.assertEqual(len(plan["semantic_queries"]), 2)


class YuandianLayeredResearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_directional_research_includes_orders_and_always_runs_semantic_supplement(self):
        direct = {
            "id": "p5989", "ah": "（2021）粤01民终5989号",
            "title": "黄某民间借贷纠纷二审民事裁定书", "jbdw": "广东省广州市中级人民法院",
            "cprq": "2021年04月15日", "spcx": "二审案件", "cj": "中级",
            "content": "另案向保证人主张连带保证责任后，仍可向主债务人主张清偿责任。主债务人与连带保证人责任各自独立，可分之诉，不构成重复起诉。",
        }
        analogical = {
            "id": "p31", "ah": "（2022）浙06民终31号",
            "title": "沈某债权人代位权纠纷二审民事判决书", "jbdw": "浙江省绍兴市中级人民法院",
            "cprq": "2022年02月14日", "spcx": "二审案件", "cj": "中级",
            "content": "向连带责任保证人主张权利后，仍可另行向主债务人主张权利，不构成重复起诉。",
        }
        calls = []

        async def fake_call(kind, tool_name, arguments, timeout=35.0):
            calls.append((tool_name, arguments))
            if tool_name == "yuandian_rh_qwal_search":
                return json.dumps({"data": {"lst": []}}, ensure_ascii=False)
            if tool_name == "yuandian_rh_ptal_search":
                rows = [direct] if "责任各自独立" in (arguments.get("fxgc") or "") else []
                return json.dumps({"data": {"lst": rows}}, ensure_ascii=False)
            if tool_name == "yuandian_case_vector_search":
                return json.dumps({"extra": {"wenshu": [analogical]}}, ensure_ascii=False)
            if tool_name == "yuandian_rh_case_details":
                row = direct if arguments.get("ah") == direct["ah"] or arguments.get("id") == direct["id"] else analogical
                return json.dumps({"data": [{
                    **row, "fxgc": row["content"], "pjjg": "驳回上诉，维持原判。"
                }]}, ensure_ascii=False)
            raise AssertionError(f"unexpected tool: {tool_name}")

        query = "债权人先起诉连带责任保证人，后另行起诉主债务人，是否构成重复起诉"
        with patch.object(yuandian_mcp, "call_yuandian_tool", new=AsyncMock(side_effect=fake_call)):
            result = await yuandian_mcp.research_cases(query, top_k=10)

        payload = json.loads(result["result"])
        self.assertEqual(payload["案例"][0]["案号"], "（2021）粤01民终5989号")
        self.assertIn("（2022）浙06民终31号", [item["案号"] for item in payload["案例"]])
        ptal_args = [args for tool, args in calls if tool == "yuandian_rh_ptal_search"]
        self.assertTrue(all(args["wszl"] == ["判决书", "裁定书"] for args in ptal_args))
        self.assertEqual(len([1 for tool, _ in calls if tool == "yuandian_case_vector_search"]), 2)

    async def test_authority_then_keyword_then_detail_and_no_false_original_label(self):
        qwal = json.dumps({
            "data": {"lst": [{
                "id": "q1", "title": "预约合同典型案例", "type": "典型案例",
                "content": "预约合同与本约合同有别，不能当然强制履行本约合同。",
                "url": "https://example.test/qwcase/q1",
            }]}
        }, ensure_ascii=False)
        ptal = json.dumps({
            "data": {"lst": [{
                "id": "p1", "ah": "（2021）黔23民终810号",
                "title": "王某商品房预约合同纠纷二审判决书",
                "jbdw": "某中级人民法院", "cprq": "2021年05月10日",
                "content": "预约合同不能强制履行本约合同，只能承担违约责任。",
                "url": "https://example.test/case/p1",
            }]}
        }, ensure_ascii=False)
        qwal_detail = json.dumps({
            "data": [{
                "id": "q1", "title": "预约合同典型案例",
                "content": "裁判摘要：预约合同违约应承担损害赔偿责任。",
            }]
        }, ensure_ascii=False)
        ptal_detail = json.dumps({
            "data": [{
                "id": "p1", "ah": "（2021）黔23民终810号",
                "title": "王某商品房预约合同纠纷二审判决书",
                "jbdw": "某中级人民法院", "cprq": "2021年05月10日",
                "fxgc": "本院认为，预约合同本身不具强制履行力，签订本约合同的义务不能强制履行。",
                "pjjg": "驳回上诉，维持原判。",
                "url": "https://example.test/case/p1",
            }]
        }, ensure_ascii=False)

        async def fake_call(kind, tool_name, arguments, timeout=35.0):
            if tool_name == "yuandian_rh_qwal_search":
                return qwal
            if tool_name == "yuandian_rh_ptal_search":
                return ptal
            if tool_name == "yuandian_case_vector_search":
                return json.dumps({"extra": {"wenshu": []}}, ensure_ascii=False)
            if tool_name == "yuandian_rh_case_details":
                return qwal_detail if arguments.get("type") == "qwal" else ptal_detail
            raise AssertionError(f"unexpected tool: {tool_name}")

        with patch.object(yuandian_mcp, "call_yuandian_tool", new=AsyncMock(side_effect=fake_call)) as call:
            result = await yuandian_mcp.research_cases(
                "检索支持预约合同不能强制履行的裁判案例", top_k=6
            )

        tools = [item.args[1] for item in call.await_args_list]
        self.assertEqual(tools[0], "yuandian_rh_qwal_search")
        self.assertIn("yuandian_rh_ptal_search", tools)
        self.assertIn("yuandian_case_vector_search", tools)
        self.assertLess(tools.index("yuandian_rh_ptal_search"), tools.index("yuandian_case_vector_search"))
        payload = json.loads(result["result"])
        self.assertEqual(result["verified_count"], 2)
        ordinary = next(item for item in payload["案例"] if item["案号"])
        self.assertEqual(ordinary["详情核验状态"], "已调用详情接口核验")
        self.assertEqual(ordinary["证据类型"], "裁判文书分析过程字段（详情接口）")
        authoritative = next(item for item in payload["案例"] if not item["案号"])
        self.assertIn("非逐字全文", authoritative["证据类型"])


if __name__ == "__main__":
    unittest.main()
