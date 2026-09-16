import json
import unittest
from unittest.mock import AsyncMock, patch

from backend import qcc_mcp


def payload_text(payload: dict) -> str:
    """call_qcc_tool 被 mock 后直接返回工具文本（真实实现会先解包 JSON-RPC 信封）。"""
    return json.dumps(payload, ensure_ascii=False)


class QccResolveCompanyTests(unittest.IsolatedAsyncioTestCase):
    async def test_unique_exact_match_locks_entity(self):
        raw = payload_text({
            "匹配结果": "唯一精确匹配",
            "摘要": "已锁定唯一精确主体，可直接调用下游工具。",
            "企业信息": {"企业名称": "腾讯科技（深圳）有限公司", "统一社会信用代码": "919999000000000006"},
        })
        with patch.object(qcc_mcp, "call_qcc_tool", new=AsyncMock(return_value=raw)) as call:
            entity = await qcc_mcp.resolve_company("腾讯科技（深圳）有限公司")
        call.assert_awaited_once_with("company", "get_company_by_query", {"searchKey": "腾讯科技（深圳）有限公司"})
        self.assertEqual(entity["name"], "腾讯科技（深圳）有限公司")
        self.assertEqual(entity["credit_code"], "919999000000000006")
        self.assertEqual(entity["candidates"], [])

    async def test_multi_candidate_picks_unique_substring_match(self):
        raw = payload_text({
            "匹配结果": "多候选",
            "企业信息": [
                {"企业名称": "深圳市腾讯计算机系统有限公司", "统一社会信用代码": "919999000000000005"},
                {"企业名称": "腾讯科技（深圳）有限公司", "统一社会信用代码": "919999000000000006"},
            ],
        })
        with patch.object(qcc_mcp, "call_qcc_tool", new=AsyncMock(return_value=raw)):
            entity = await qcc_mcp.resolve_company("腾讯科技（深圳）有限公司")
        self.assertEqual(entity["name"], "腾讯科技（深圳）有限公司")
        self.assertEqual(len(entity["candidates"]), 2)

    async def test_no_match_raises(self):
        raw = payload_text({"匹配结果": "未匹配", "摘要": "未匹配到搜索关键词"})
        with patch.object(qcc_mcp, "call_qcc_tool", new=AsyncMock(return_value=raw)):
            with self.assertRaises(qcc_mcp.QccMCPError):
                await qcc_mcp.resolve_company("不存在的企业名字有限公司")


class QccSearchTests(unittest.IsolatedAsyncioTestCase):
    def test_select_company_tools_routes_specialized_intents(self):
        tools = [item[0] for item in qcc_mcp.select_company_tools(
            "请给我某某有限公司的发票信息、联系电话和开户行"
        )]
        self.assertEqual(tools, ["get_tax_invoice_info", "get_contact_info"])

    def test_select_company_tools_uses_profile_fallback_for_generic_query(self):
        tools = [item[0] for item in qcc_mcp.select_company_tools("查一下某某有限公司")]
        self.assertEqual(tools, [
            "get_company_registration_info", "get_company_profile", "get_shareholder_info",
        ])

    def test_select_company_tools_routes_all_common_specialized_dimensions(self):
        cases = {
            "企业年报": "get_annual_reports",
            "有哪些分支机构": "get_branches",
            "工商变更记录": "get_change_records",
            "对外投资情况": "get_external_investments",
            "营业收入和资产负债率": "get_financial_data",
            "董事监事等主要人员": "get_key_personnel",
            "股票代码和上市信息": "get_listing_info",
            "最终受益所有人 UBO": "get_beneficial_owners",
            "实际控制人是谁": "get_actual_controller",
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                tools = [item[0] for item in qcc_mcp.select_company_tools(query)]
                self.assertIn(expected, tools)

    async def test_search_company_calls_tax_invoice_tool_for_invoice_question(self):
        resolve_raw = payload_text({
            "匹配结果": "唯一精确匹配",
            "企业信息": {"企业名称": "佛山市新一建贸易有限公司", "统一社会信用代码": "919999000000000008"},
        })
        invoice_raw = payload_text({
            "企业名称": "佛山市新一建贸易有限公司",
            "纳税人识别号": "919999000000000008",
            "开户行": "招商银行佛山南海支行",
            "开户行账号": "757903540810201",
        })

        async def fake_call(category, tool_name, arguments, timeout=35.0):
            if tool_name == "get_company_by_query":
                return resolve_raw
            if tool_name == "get_tax_invoice_info":
                return invoice_raw
            raise AssertionError(f"unexpected tool: {tool_name}")

        with patch.object(qcc_mcp, "plan_qcc_tool_calls", new=AsyncMock(side_effect=RuntimeError("offline planner"))), \
             patch.object(qcc_mcp, "call_qcc_tool", new=AsyncMock(side_effect=fake_call)) as call:
            payload = json.loads(await qcc_mcp.search_company(
                "佛山市新一建贸易有限公司的发票信息"
            ))

        tools = [item.args[1] for item in call.call_args_list]
        self.assertEqual(tools, ["get_company_by_query", "get_tax_invoice_info"])
        self.assertEqual(payload["开户行"], "招商银行佛山南海支行")
        self.assertEqual(payload["本次调用的企查查能力"], ["税号开票信息"])

    async def test_requested_specialized_tool_failure_does_not_fallback_to_profile(self):
        resolve_raw = payload_text({
            "匹配结果": "唯一精确匹配",
            "企业信息": {"企业名称": "某某有限公司", "统一社会信用代码": "919999000000000001"},
        })

        async def fake_call(category, tool_name, arguments, timeout=35.0):
            if tool_name == "get_company_by_query":
                return resolve_raw
            if tool_name == "get_tax_invoice_info":
                raise qcc_mcp.QccMCPError("专项接口暂不可用")
            raise AssertionError(f"unexpected tool: {tool_name}")

        with patch.object(qcc_mcp, "plan_qcc_tool_calls", new=AsyncMock(side_effect=RuntimeError("offline planner"))), \
             patch.object(qcc_mcp, "call_qcc_tool", new=AsyncMock(side_effect=fake_call)):
            with self.assertRaisesRegex(qcc_mcp.QccMCPError, "税号开票信息"):
                await qcc_mcp.search_company("某某有限公司的开票资料")

    async def test_search_cases_calls_dual_route_and_truncates(self):
        rows = [{"案号": f"（2024）粤0{i}民1号", "案件标题": f"案例{i}", "案例摘要": "本院认为…"} for i in range(10)]
        ordinary = payload_text({"摘要": "共检索到 20 条", "案例列表": rows})
        authoritative = payload_text({"摘要": "共检索到 2 条", "案例列表": [{"案号": "指导案例1号", "案件标题": "权威案例"}]})

        async def fake_call(category, tool_name, arguments, timeout=35.0):
            if tool_name == "get_judicial_case_search":
                return ordinary
            if tool_name == "get_judicial_authoritative_case_search":
                return authoritative
            raise AssertionError(f"unexpected tool: {tool_name}")

        with patch.object(qcc_mcp, "plan_qcc_tool_calls", new=AsyncMock(side_effect=RuntimeError("offline planner"))), \
             patch.object(qcc_mcp, "call_qcc_tool", new=AsyncMock(side_effect=fake_call)) as call:
            result = await qcc_mcp.search_cases("预约合同 强制履行", top_k=3)

        tools = [item.args[1] for item in call.call_args_list]
        self.assertEqual(tools, ["get_judicial_case_search", "get_judicial_authoritative_case_search"])
        first, second = result.split("\n\n---\n\n")
        self.assertEqual(len(json.loads(first)["案例列表"]), 3)
        self.assertIn("权威案例", second)

    async def test_search_laws_calls_semantic_and_keyword(self):
        articles = [{"法条ID": f"a{i}", "所属法规名称": "中华人民共和国民法典", "条号": f"第{i}条", "条文正文": "内容", "时效性": "现行有效"} for i in range(8)]
        semantic = payload_text({"摘要": "共检索到 240 条", "法条列表": articles})
        keyword = payload_text({"摘要": "共检索到 3 条", "法条列表": [articles[0]]})

        async def fake_call(category, tool_name, arguments, timeout=35.0):
            if tool_name == "get_legal_article_semantic_search":
                return semantic
            if tool_name == "get_legal_article_search":
                return keyword
            raise AssertionError(f"unexpected tool: {tool_name}")

        with patch.object(qcc_mcp, "plan_qcc_tool_calls", new=AsyncMock(side_effect=RuntimeError("offline planner"))), \
             patch.object(qcc_mcp, "call_qcc_tool", new=AsyncMock(side_effect=fake_call)) as call:
            result = await qcc_mcp.search_laws("预约合同能否强制履行", top_k=4)

        tools = [item.args[1] for item in call.call_args_list]
        self.assertEqual(tools, ["get_legal_article_semantic_search", "get_legal_article_search"])
        first, second = result.split("\n\n---\n\n")
        self.assertEqual(len(json.loads(first)["法条列表"]), 4)
        self.assertIn("民法典", second)

    async def test_search_company_merges_registration_fields(self):
        registration = payload_text({"企业名称": "腾讯科技（深圳）有限公司", "法定代表人": "马化腾", "注册资本": "200万美元"})
        profile = payload_text({"企业简介": "互联网企业"})
        shareholders = payload_text({"股东列表": [{"股东名称": "某股东", "持股比例": "100%"}]})
        resolve_raw = payload_text({
            "匹配结果": "唯一精确匹配",
            "企业信息": {"企业名称": "腾讯科技（深圳）有限公司", "统一社会信用代码": "919999000000000006"},
        })

        async def fake_call(category, tool_name, arguments, timeout=35.0):
            if tool_name == "get_company_by_query":
                return resolve_raw
            if tool_name == "get_company_registration_info":
                return registration
            if tool_name == "get_company_profile":
                return profile
            if tool_name == "get_shareholder_info":
                return shareholders
            raise AssertionError(f"unexpected tool: {tool_name}")

        with patch.object(qcc_mcp, "plan_qcc_tool_calls", new=AsyncMock(side_effect=RuntimeError("offline planner"))), \
             patch.object(qcc_mcp, "call_qcc_tool", new=AsyncMock(side_effect=fake_call)):
            payload = json.loads(await qcc_mcp.search_company("腾讯科技（深圳）有限公司"))

        self.assertEqual(payload["企业名称"], "腾讯科技（深圳）有限公司")
        self.assertEqual(payload["法定代表人"], "马化腾")
        self.assertEqual(payload["股东列表"][0]["持股比例"], "100%")

    async def test_search_risk_returns_scan_counts(self):
        resolve_raw = payload_text({
            "匹配结果": "唯一精确匹配",
            "企业信息": {"企业名称": "腾讯科技（深圳）有限公司", "统一社会信用代码": "919999000000000006"},
        })
        scan_raw = payload_text({
            "企业名称": "腾讯科技（深圳）有限公司",
            "有记录因子数": 1,
            "风险因子扫描": [{"风险因子": "失信信息", "条目数": 0}, {"风险因子": "裁判文书", "条目数": 10}],
        })

        async def fake_call(category, tool_name, arguments, timeout=35.0):
            if tool_name == "get_company_by_query":
                return resolve_raw
            if tool_name == "get_company_risk_scan":
                return scan_raw
            raise AssertionError(f"unexpected tool: {tool_name}")

        with patch.object(qcc_mcp, "plan_qcc_tool_calls", new=AsyncMock(side_effect=RuntimeError("offline planner"))), \
             patch.object(qcc_mcp, "call_qcc_tool", new=AsyncMock(side_effect=fake_call)) as call:
            payload = json.loads(await qcc_mcp.search_risk("腾讯科技（深圳）有限公司"))

        self.assertEqual(payload["有记录因子数"], 1)
        factors = [item["风险因子"] for item in payload["风险因子扫描"]]
        self.assertIn("裁判文书", factors)
        tools = [item.args[1] for item in call.call_args_list]
        self.assertEqual(tools, ["get_company_by_query", "get_company_risk_scan"])


class QccServerConfigTests(unittest.TestCase):
    def test_default_urls_and_shared_authorization(self):
        url, authorization = qcc_mcp.server_config("company")
        self.assertEqual(url, "https://agent.qcc.com/mcp/company/stream")
        self.assertEqual(authorization, qcc_mcp.QCC_MCP_AUTHORIZATION)

    def test_unknown_category_raises(self):
        with self.assertRaises(ValueError):
            qcc_mcp.server_config("unknown")


class QccEntityRoutingTests(unittest.TestCase):
    def test_extracts_all_company_names_in_order(self):
        query = "对比佛山市铜色商贸有限公司、佛山市先机投资有限公司的历史工商登记信息"
        self.assertEqual(
            qcc_mcp.extract_company_names(query),
            ["佛山市铜色商贸有限公司", "佛山市先机投资有限公司"],
        )
        self.assertEqual(qcc_mcp.extract_company_name(query), "佛山市铜色商贸有限公司")

    def test_comparison_intent_is_true_for_cross_appointment_questions(self):
        self.assertTrue(
            qcc_mcp.asks_for_company_comparison(
                "比对两家公司哪些人员存在交叉任职"
            )
        )

    def test_explicit_history_and_people_dimensions_are_selected(self):
        tools = [name for name, _title, _args in qcc_mcp.select_company_tools(
            "对比两家公司所有历史工商登记信息和交叉任职人员"
        )]
        self.assertIn("get_company_registration_info", tools)
        self.assertIn("get_change_records", tools)
        self.assertIn("get_key_personnel", tools)


class QccMultiCompanySearchTests(unittest.IsolatedAsyncioTestCase):
    def test_company_response_does_not_treat_error_field_as_evidence(self):
        raw = payload_text({
            "查询类型": "多企业工商信息对比",
            "各企业结果": [
                {
                    "企业名称": "示丆某",
                    "查询状态": "成功",
                    "结果": {"变更记录": {"_error": "积分不足"}},
                },
                {
                    "企业名称": "示一某",
                    "查询状态": "成功",
                    "结果": {"变更记录": []},
                },
            ],
        })
        self.assertFalse(qcc_mcp.company_response_covers_fields(raw, ("变更记录",)))

    def test_company_response_requires_every_target_company(self):
        raw = payload_text({
            "查询类型": "多企业工商信息对比",
            "各企业结果": [
                {
                    "企业名称": "示丆某",
                    "查询状态": "成功",
                    "结果": {"主要人员": [{"姓名": "甲"}]},
                },
                {
                    "企业名称": "示一某",
                    "查询状态": "失败",
                    "错误": "未返回",
                },
            ],
        })
        self.assertFalse(qcc_mcp.company_response_covers_fields(raw, ("主要人员",)))

    def test_company_response_accepts_successful_empty_result(self):
        raw = payload_text({
            "查询类型": "多企业工商信息对比",
            "各企业结果": [
                {"企业名称": "示丆某", "查询状态": "成功", "结果": {"变更记录": []}},
                {"企业名称": "示一某", "查询状态": "成功", "结果": {"变更记录": []}},
            ],
        })
        self.assertTrue(qcc_mcp.company_response_covers_fields(raw, ("变更记录",)))

    async def test_search_companies_keeps_each_subject_in_separate_evidence_group(self):
        async def fake_single(query, *, _single=False):
            name = qcc_mcp.extract_company_name(query)
            return json.dumps({"主体": {"企业名称": name}, "本次调用的企查查能力": ["企业工商信息"]})

        with patch.object(qcc_mcp, "search_company", new=AsyncMock(side_effect=fake_single)):
            raw = await qcc_mcp.search_companies(
                "对比佛山市铜色商贸有限公司、佛山市先机投资有限公司的工商信息"
            )

        payload = json.loads(raw)
        self.assertEqual(payload["主体数量"], 2)
        self.assertEqual(
            [item["企业名称"] for item in payload["各企业结果"]],
            ["佛山市铜色商贸有限公司", "佛山市先机投资有限公司"],
        )
        self.assertEqual(len(payload["各企业结果"]), 2)

    async def test_history_server_receives_each_company_as_a_separate_entity(self):
        tools = [{
            "name": "get_history_changes",
            "title": "历史工商变更",
            "description": "查询企业历史工商登记变更",
            "inputSchema": {
                "type": "object",
                "properties": {"searchKey": {"type": "string"}},
                "required": ["searchKey"],
            },
        }]

        async def fake_plan(category, query, *, argument_overrides=None, **_kwargs):
            company_name = argument_overrides["searchKey"]
            return ([{
                "name": "get_history_changes",
                "arguments": {"searchKey": company_name},
            }], {"get_history_changes": "历史工商变更"})

        async def fake_call(category, tool_name, arguments, timeout=35.0):
            return payload_text({"企业名称": arguments["searchKey"], "变更记录": []})

        with patch.object(qcc_mcp, "discover_qcc_tools", new=AsyncMock(return_value=tools)), \
             patch.object(qcc_mcp, "plan_qcc_tool_calls", new=AsyncMock(side_effect=fake_plan)), \
             patch.object(qcc_mcp, "call_qcc_tool", new=AsyncMock(side_effect=fake_call)):
            payload = json.loads(await qcc_mcp.search_history(
                "对比佛山市铜色商贸有限公司、佛山市先机投资有限公司的历史工商登记"
            ))

        self.assertEqual(
            [row["企业名称"] for row in payload["各企业结果"]],
            ["佛山市铜色商贸有限公司", "佛山市先机投资有限公司"],
        )
        self.assertEqual(
            [row["调用结果"]["历史工商变更"]["企业名称"] for row in payload["各企业结果"]],
            ["佛山市铜色商贸有限公司", "佛山市先机投资有限公司"],
        )

    async def test_executive_server_uses_company_and_intersection_person_as_double_anchor(self):
        evidence = json.dumps({
            "查询类型": "多企业工商信息对比",
            "各企业结果": [
                {
                    "企业名称": "佛山市铜色商贸有限公司",
                    "结果": {
                        "主要人员": [{"姓名": "张优旭", "职务": "监事"}],
                        "变更记录": [{"变更内容": '变更前"张优旭(监事)"'}],
                    },
                },
                {
                    "企业名称": "佛山市先机投资有限公司",
                    "结果": {
                        "主要人员": [{"姓名": "张优旭", "职务": "董事"}],
                        "变更记录": [{"变更内容": '变更后"张优旭(董事长)"'}],
                    },
                },
            ],
        }, ensure_ascii=False)
        tools = [{
            "name": "get_executive_historical_positions",
            "title": "董监高-历史在外任职",
            "description": "查询自然人历史在外任职",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "searchKey": {"type": "string"},
                    "personName": {"type": "string"},
                },
                "required": ["searchKey", "personName"],
            },
        }]

        async def fake_call(category, tool_name, arguments, timeout=35.0):
            return payload_text({
                "企业名称": arguments["searchKey"],
                "人员姓名": arguments["personName"],
                "任职记录": [],
            })

        with patch.object(qcc_mcp, "discover_qcc_tools", new=AsyncMock(return_value=tools)), \
             patch.object(qcc_mcp, "call_qcc_tool", new=AsyncMock(side_effect=fake_call)) as call:
            payload = json.loads(await qcc_mcp.search_executive(
                "对比佛山市铜色商贸有限公司、佛山市先机投资有限公司的交叉任职",
                company_evidence=evidence,
            ))

        self.assertEqual(payload["交集候选人员"], ["张优旭"])
        self.assertEqual(call.await_count, 2)
        self.assertEqual(
            {(item.args[2]["searchKey"], item.args[2]["personName"]) for item in call.call_args_list},
            {
                ("佛山市铜色商贸有限公司", "张优旭"),
                ("佛山市先机投资有限公司", "张优旭"),
            },
        )

    def test_fallback_category_calls_uses_advertised_required_entity_field(self):
        tools = [
            {
                "name": "get_history_changes",
                "title": "历史工商变更",
                "description": "查询企业历史工商登记变更",
                "inputSchema": {
                    "type": "object",
                    "properties": {"searchKey": {"type": "string"}},
                    "required": ["searchKey"],
                },
            },
            {
                "name": "get_unrelated_tool",
                "title": "企业简介",
                "description": "查询企业简介",
                "inputSchema": {
                    "type": "object",
                    "properties": {"searchKey": {"type": "string"}},
                    "required": ["searchKey"],
                },
            },
        ]
        calls = qcc_mcp._fallback_category_calls(
            tools, "history", "佛山市铜色商贸有限公司", "查询历史工商变更", 4
        )
        self.assertEqual(calls, [{
            "name": "get_history_changes",
            "arguments": {"searchKey": "佛山市铜色商贸有限公司"},
        }])


if __name__ == "__main__":
    unittest.main()
