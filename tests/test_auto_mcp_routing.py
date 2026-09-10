import json
import unittest
from unittest.mock import AsyncMock, patch

from backend import main


def ai_json(payload):
    return {
        "choices": [{
            "message": {"content": json.dumps(payload, ensure_ascii=False)},
            "finish_reason": "stop",
        }]
    }


class AutoMCPRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_company_name_skips_remote_enterprise_planner(self):
        with patch.object(
            main,
            "_call_ai_with_fallback",
            new=AsyncMock(side_effect=AssertionError("不应调用远程规划器")),
        ):
            plan = await main._plan_enterprise_mcp_query(
                "我是化州市恒邦能源有限公司的债权人，请查询其失信、被执行和终本信息"
            )
        self.assertEqual(plan["company_name"], "化州市恒邦能源有限公司")
        self.assertEqual(plan["intent"], "company_risk")

    async def test_invoice_question_cannot_omit_qcc_company(self):
        with patch.object(
            main,
            "_call_ai_with_fallback",
            new=AsyncMock(return_value=(ai_json({"sources": [], "reason": ""}), "model")),
        ):
            selected = await main._plan_auto_mcp_sources("佛山市新一建贸易有限公司的发票信息")
        self.assertEqual(selected, {"qcc_company"})

    async def test_multi_select_routes_only_inside_user_allowed_sources(self):
        with patch.object(
            main,
            "_call_ai_with_fallback",
            new=AsyncMock(return_value=(ai_json({"sources": ["qcc_company", "finchina"]}), "model")),
        ):
            selected = await main._plan_auto_mcp_sources(
                "查询企业基本情况",
                allowed_sources={"finchina", "qcc_risk"},
            )
        self.assertEqual(selected, {"finchina"})

    async def test_local_article_summary_selects_no_mcp(self):
        with patch.object(
            main,
            "_call_ai_with_fallback",
            new=AsyncMock(return_value=(ai_json({"sources": [], "reason": "本地文章总结"}), "model")),
        ):
            selected = await main._plan_auto_mcp_sources("总结当前打开的文章")
        self.assertEqual(selected, set())

    def test_opencode_deepseek_v4_uses_bounded_report_timeout(self):
        self.assertEqual(main._get_timeout("opencode:deepseek-flash"), 180.0)
        self.assertEqual(main._get_timeout("opencode:deepseek-v4-pro"), 120.0)


if __name__ == "__main__":
    unittest.main()
