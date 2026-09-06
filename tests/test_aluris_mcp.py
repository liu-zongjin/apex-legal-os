import unittest
from unittest.mock import AsyncMock, patch

from backend import aluris_mcp


CASE_TITLE = "张励与徐州市同力创展房地产有限公司商品房预售合同纠纷案"
DETAIL_URL = (
    "http://gongbao.court.gov.cn/Details/7412288408c0c6ded637b38b364595.html"
)


class AlurisGongbaoFallbackTests(unittest.IsolatedAsyncioTestCase):
    def test_extracts_only_an_explicit_full_case_title(self):
        self.assertEqual(aluris_mcp._extract_exact_case_title(CASE_TITLE), CASE_TITLE)
        self.assertEqual(
            aluris_mcp._extract_exact_case_title(f"请查找《{CASE_TITLE}》"), CASE_TITLE
        )
        self.assertEqual(aluris_mcp._extract_exact_case_title("商品房预约合同有哪些公报案例"), "")
        self.assertIn(
            CASE_TITLE,
            aluris_mcp._GONGBAO_VERIFIED_CASES,
        )

    def test_parses_exact_official_search_hit(self):
        html = f"""
        <ul><li><span><a href="/Details/7412288408c0c6ded637b38b364595.html?sw=x">
        {CASE_TITLE}</a>2012年11期</span></li></ul>
        """
        self.assertEqual(
            aluris_mcp._parse_gongbao_search_html(html, CASE_TITLE),
            (CASE_TITLE, DETAIL_URL, "2012年11期"),
        )

    def test_query_echo_is_not_mistaken_for_an_mcp_case_hit(self):
        remote = f"权威案例与司法规则检索「{CASE_TITLE}」—— 返回 1 个结果\n\n## 1. 其他案例"
        self.assertFalse(aluris_mcp._mcp_result_has_case_title(remote, CASE_TITLE))

    def test_formats_citable_judgment_summary(self):
        html = f"""
        <div id="gb_content">
          <p>{CASE_TITLE}</p><p>【裁判摘要】</p>
          <p>预约合同是一种约定将来订立一定合同的合同。</p>
          <p>判断认购协议性质，应审查其是否具备商品房买卖合同主要内容。</p>
          <p>原告：张励。</p>
        </div>
        """
        result = aluris_mcp._format_gongbao_detail_html(
            html, CASE_TITLE, DETAIL_URL, "2012年11期"
        )
        self.assertIn(aluris_mcp.GONGBAO_EXACT_HIT_MARKER, result)
        self.assertIn("最高法公报案例", result)
        self.assertIn("2012年11期", result)
        self.assertIn("预约合同是一种约定", result)
        self.assertNotIn("原告：张励", result)
        self.assertIn(DETAIL_URL, result)

    async def test_prepends_official_hit_when_mcp_misses_exact_title(self):
        official = f"{aluris_mcp.GONGBAO_EXACT_HIT_MARKER}\n{CASE_TITLE}"
        with patch.object(
            aluris_mcp, "call_aluris_tool", AsyncMock(return_value="远端返回其他相似案例")
        ), patch.object(
            aluris_mcp, "_search_gongbao_exact_case", AsyncMock(return_value=official)
        ):
            result = await aluris_mcp.search_authoritative_cases(CASE_TITLE)
        self.assertTrue(result.startswith(official))
        self.assertIn("【法随·案例库 MCP 语义检索结果】", result)

    async def test_does_not_duplicate_case_already_returned_by_mcp(self):
        remote = f"## 1. {CASE_TITLE}\n来源：公报案例"
        official = f"{aluris_mcp.GONGBAO_EXACT_HIT_MARKER}\n{CASE_TITLE}"
        with patch.object(
            aluris_mcp, "call_aluris_tool", AsyncMock(return_value=remote)
        ), patch.object(
            aluris_mcp, "_search_gongbao_exact_case", AsyncMock(return_value=official)
        ):
            result = await aluris_mcp.search_authoritative_cases(CASE_TITLE)
        self.assertEqual(result, remote)


if __name__ == "__main__":
    unittest.main()
