import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from backend import pkulaw_mcp


class PkuLawMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_transient_503_is_retried(self):
        class FakeClient:
            def __init__(self, responses):
                self.responses = iter(responses)
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def post(self, *args, **kwargs):
                return next(self.responses)

        request = httpx.Request("POST", "https://example.test/mcp")
        unavailable = httpx.Response(503, request=request, text="unavailable")
        init_ok = httpx.Response(200, request=request, text=json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}))
        notice_ok = httpx.Response(202, request=request, text="")
        call_ok = httpx.Response(200, request=request, text=json.dumps({
            "jsonrpc": "2.0", "id": 2,
            "result": {"content": [{"type": "text", "text": "检索成功"}]},
        }, ensure_ascii=False))
        factory = MagicMock(side_effect=[FakeClient([unavailable]), FakeClient([init_ok, notice_ok, call_ok])])
        with patch.object(pkulaw_mcp, "server_config", return_value=("https://example.test/mcp", "Bearer test")), patch.object(
            pkulaw_mcp.httpx, "AsyncClient", factory
        ), patch.object(pkulaw_mcp.asyncio, "sleep", new=AsyncMock()) as sleep:
            result = await pkulaw_mcp.call_pkulaw_tool("case_semantic", "search_case", {"text": "测试"})

        self.assertEqual(result, "检索成功")
        self.assertEqual(factory.call_count, 2)
        sleep.assert_awaited_once_with(0.8)

    def test_case_type_filter_matches_the_question(self):
        self.assertEqual(pkulaw_mcp._case_type_for_query("盗窃罪如何量刑"), "刑事案件")
        self.assertEqual(pkulaw_mcp._case_type_for_query("行政处罚能否撤销"), "行政案件")
        self.assertEqual(pkulaw_mcp._case_type_for_query("执行异议之诉的案例"), "执行案件")

    async def test_case_search_merges_semantic_and_keyword_results_without_inventing_fields(self):
        semantic = json.dumps([{
            "title": "示丆某与示一某预约合同纠纷二审民事判决书",
            "case_number": "（2024）京01民终10号",
            "courthouse_name": "北京市第一中级人民法院",
            "decision_date": "2024-01-10",
            "identified": "预约合同违约责任应结合本约条款完整程度判断。",
            "url": "https://example.test/case/1",
            "case_grade": "普通案例",
        }], ensure_ascii=False)
        keyword = json.dumps({"Data": [{
            "Title": "示丆某与示一某预约合同纠纷二审民事判决书",
            "CaseFlag": "（2024）京01民终10号",
            "Court": "北京市第一中级人民法院",
            "CaseGrade": ["参考案例"],
            "Url": "https://example.test/case/1",
        }]}, ensure_ascii=False)

        async def fake_call(kind, tool, arguments, timeout=35.0):
            return semantic if kind == "case_semantic" else keyword

        with patch.object(pkulaw_mcp, "call_pkulaw_tool", new=AsyncMock(side_effect=fake_call)):
            result = await pkulaw_mcp.search_cases("预约合同能否强制履行", top_k=6)

        payload = json.loads(result["result"])
        self.assertEqual(result["case_count"], 1)
        case = payload["案例"][0]
        self.assertEqual(case["来源"], "北大法宝·案例库 MCP")
        self.assertEqual(case["案号"], "（2024）京01民终10号")
        self.assertIn("预约合同", case["裁判观点"])

    async def test_directional_case_search_uses_multiple_routes_and_ranks_direct_case_first(self):
        reverse = [{
            "title": "某保证合同纠纷二审判决书", "case_number": "（2018）某高法民终1号",
            "courthouse_name": "某省高级人民法院",
            "ascertain": "债权人前案起诉主债务人，此后又另行起诉连带责任保证人。",
            "identified": "法院认为不构成重复起诉。", "case_grade": "普通案例",
        }]
        direct = {
            "Title": "黄某民间借贷纠纷二审民事裁定书", "CaseFlag": "（2021）粤01民终5989号",
            "Court": "广东省广州市中级人民法院", "CaseGrade": ["普通案例"],
            "Ascertain": "债权人另案向保证人主张连带保证责任后，仍可向主债务人主张清偿。",
            "Identified": "主债务人与连带保证人责任各自独立，属于可分之诉；重复受偿是判项或执行问题。",
        }
        seen_queries = []

        async def fake_call(kind, tool, arguments, timeout=35.0):
            seen_queries.append(arguments.get("text") or arguments.get("fulltext"))
            if kind == "case_semantic":
                return json.dumps(reverse, ensure_ascii=False)
            rows = [direct] if "责任各自独立" in arguments.get("fulltext", "") else []
            return json.dumps({"Data": rows}, ensure_ascii=False)

        query = "债权人先起诉连带责任保证人，后另行起诉主债务人，是否构成重复起诉"
        with patch.object(pkulaw_mcp, "call_pkulaw_tool", new=AsyncMock(side_effect=fake_call)):
            result = await pkulaw_mcp.search_cases(query, top_k=10)

        payload = json.loads(result["result"])
        self.assertEqual(payload["案例"][0]["案号"], "（2021）粤01民终5989号")
        self.assertEqual(payload["案例"][0]["类案层级"], "highly_similar")
        self.assertEqual(payload["案例"][1]["类案层级"], "reverse_direction")
        self.assertIn("主债务人 连带保证人 责任各自独立", seen_queries)
        self.assertGreaterEqual(len(result["query_plan"]["retrieval_runs"]), 7)

    async def test_law_search_keeps_actual_status_and_content(self):
        semantic = json.dumps([{
            "title": "中华人民共和国民法典",
            "article": "第四百九十五条 当事人约定在将来一定期限内订立合同的，构成预约合同。",
            "timeliness": "现行有效", "effectiveness": "法律",
            "url": "https://example.test/law/1",
        }], ensure_ascii=False)
        keyword = json.dumps({"Data": []}, ensure_ascii=False)

        async def fake_call(kind, tool, arguments, timeout=35.0):
            return semantic if kind == "law_search" else keyword

        with patch.object(pkulaw_mcp, "call_pkulaw_tool", new=AsyncMock(side_effect=fake_call)):
            result = await pkulaw_mcp.search_laws("预约合同的法律规定", top_k=6)

        payload = json.loads(result["result"])
        law = payload["法规"][0]
        self.assertEqual(law["来源"], "北大法宝·法律法规 MCP")
        self.assertEqual(law["时效状态"], "现行有效")
        self.assertIn("第四百九十五条", law["条文内容"])

    def test_article_number_value_converts_chinese_numerals(self):
        self.assertEqual(pkulaw_mcp._article_number_value("五百零九"), 509)
        self.assertEqual(pkulaw_mcp._article_number_value("五百七十七"), 577)
        self.assertEqual(pkulaw_mcp._article_number_value("509"), 509)
        self.assertEqual(pkulaw_mcp._article_number_value("十"), 10)
        self.assertEqual(pkulaw_mcp._article_number_value("一百零五"), 105)
        self.assertEqual(pkulaw_mcp._article_number_value("一千零一"), 1001)
        self.assertIsNone(pkulaw_mcp._article_number_value("abc"))

    def test_article_hints_extracts_every_requested_article(self):
        hints = pkulaw_mcp._article_hints(
            "《中华人民共和国民法典》第五百零九条、第五百七十七条、第五百七十九条、第五百八十四条的原文"
        )
        self.assertEqual(hints, [
            ("中华人民共和国民法典", "五百零九"),
            ("中华人民共和国民法典", "五百七十七"),
            ("中华人民共和国民法典", "五百七十九"),
            ("中华人民共和国民法典", "五百八十四"),
        ])
        multi = pkulaw_mcp._article_hints("《民法典》第五百零九条和《刑法》第二百六十四条")
        self.assertEqual(multi, [("民法典", "五百零九"), ("刑法", "二百六十四")])
        bare = pkulaw_mcp._article_hints("民法典第五百七十七条 第五百七十九条的违约责任")
        self.assertEqual(bare, [("民法典", "五百七十七"), ("民法典", "五百七十九")])
        self.assertEqual(pkulaw_mcp._article_hints("违约责任如何认定"), [])

    def test_article_hints_handles_arabic_numerals_and_nested_titles(self):
        hints = pkulaw_mcp._article_hints(
            "《中华人民共和国民事诉讼法》第一百三十五条、154条、155条及"
            "《最高人民法院关于适用<中华人民共和国民事诉讼法>的解释》第七十三条原文"
        )
        self.assertEqual(hints, [
            ("中华人民共和国民事诉讼法", "一百三十五"),
            ("中华人民共和国民事诉讼法", "154"),
            ("中华人民共和国民事诉讼法", "155"),
            ("最高人民法院关于适用《中华人民共和国民事诉讼法》的解释", "七十三"),
        ])
        nested = pkulaw_mcp._article_hints(
            "《最高人民法院关于适用《中华人民共和国民事诉讼法》的解释》第七十三条"
        )
        self.assertEqual(nested, [("最高人民法院关于适用《中华人民共和国民事诉讼法》的解释", "七十三")])
        with_di = pkulaw_mcp._article_hints("民诉法第135条、第154条")
        self.assertEqual(with_di, [("民诉法", "135"), ("民诉法", "154")])

    def test_normalise_law_title_ignores_version_suffix_and_brackets(self):
        self.assertEqual(pkulaw_mcp._normalise_law_title("中华人民共和国民事诉讼法(2023修正)"),
                         "中华人民共和国民事诉讼法")
        self.assertEqual(pkulaw_mcp._normalise_law_title("中华人民共和国民事诉讼法"),
                         "中华人民共和国民事诉讼法")
        self.assertEqual(
            pkulaw_mcp._normalise_law_title("最高人民法院关于适用《中华人民共和国民事诉讼法》的解释(2022修正)"),
            "最高人民法院关于适用中华人民共和国民事诉讼法的解释",
        )
        self.assertEqual(
            pkulaw_mcp._normalise_law_title("最高人民法院关于适用〈中华人民共和国民事诉讼法〉的解释（2022修正文本）"),
            "最高人民法院关于适用中华人民共和国民事诉讼法的解释",
        )

    async def test_law_search_fetches_every_requested_article_precisely(self):
        articles = {
            "五百零九": "第五百零九条 当事人应当按照约定全面履行自己的义务。",
            "五百七十七": "第五百七十七条 当事人一方不履行合同义务的，应当承担违约责任。",
            "五百七十九": "第五百七十九条 当事人一方未支付价款的，对方可以请求其支付。",
            "五百八十四": "第五百八十四条 损失赔偿额应当相当于因违约所造成的损失。",
        }
        semantic = json.dumps([{
            "title": "中华人民共和国民法典",
            "article": "第五百七十七条 当事人一方不履行合同义务的，应当承担违约责任。",
            "doc_no": "中华人民共和国主席令第45号",
            "timeliness": "现行有效", "effectiveness": "法律",
            "issue_department": "全国人民代表大会", "issue_date": "2020-05-28",
            "url": "https://example.test/law/1",
        }, {
            "title": "最高人民法院关于适用《中华人民共和国民法典》合同编通则若干问题的解释",
            "article": "", "timeliness": "现行有效", "effectiveness": "司法解释",
        }], ensure_ascii=False)
        keyword = json.dumps({"Data": [], "Message": "未找到数据", "Total": 0}, ensure_ascii=False)
        precise_calls = []
        exact = {"五百零九": "第五百零九条 当事人应当按照约定全面履行自己的义务。",
                 "五百七十七": "第五百七十七条 当事人一方不履行合同义务的，应当承担违约责任。",
                 "五百七十九": "第五百七十九条 当事人一方未支付价款的，对方可以请求其支付。",
                 "五百八十四": "第五百八十四条 损失赔偿额应当相当于因违约所造成的损失。"}

        async def fake_call(kind, tool, arguments, timeout=35.0):
            if kind == "law_search" and tool == "get_article":
                precise_calls.append(arguments)
                number = arguments["number"].strip("第条")
                return json.dumps({
                    "gid": "law-1", "title": "中华人民共和国民法典",
                    "article": exact[number],
                    "timeliness": "现行有效",
                    "url": "https://example.test/law/1",
                }, ensure_ascii=False)
            if kind == "law_keyword":
                return keyword
            return semantic if tool == "search_article" else keyword

        with patch.object(pkulaw_mcp, "call_pkulaw_tool", new=AsyncMock(side_effect=fake_call)):
            result = await pkulaw_mcp.search_laws(
                "《中华人民共和国民法典》第五百零九条、第五百七十七条、第五百七十九条、第五百八十四条的原文", top_k=8
            )

        self.assertEqual(len(precise_calls), 4)
        self.assertEqual(
            sorted(call["number"] for call in precise_calls),
            ["第五百七十七条", "第五百七十九条", "第五百八十四条", "第五百零九条"],
        )
        payload = json.loads(result["result"])
        laws = payload["法规"]
        self.assertEqual(result["law_count"], 4)
        numbers = sorted(law["条文内容"].split("第", 1)[1].split("条", 1)[0] for law in laws)
        self.assertEqual(numbers, ["五百七十七", "五百七十九", "五百八十四", "五百零九"])
        self.assertEqual(laws[0]["检索方式"], "指定条文查询")
        for law in laws:
            self.assertEqual(law["文号"], "中华人民共和国主席令第45号")
            self.assertEqual(law["制定机关"], "全国人民代表大会")

    async def test_law_search_drops_precise_result_with_wrong_article(self):
        semantic = json.dumps([{
            "title": "中华人民共和国民法典", "article": "第五百七十七条 违约应当担责。",
            "timeliness": "现行有效", "url": "https://example.test/law/1",
        }], ensure_ascii=False)
        keyword = json.dumps({"Data": []}, ensure_ascii=False)

        async def fake_call(kind, tool, arguments, timeout=35.0):
            if kind == "law_search" and tool == "get_article":
                return json.dumps({
                    "title": "中华人民共和国民法典",
                    "article": "第一条 为了保护民事主体的合法权益，制定本法。",
                    "url": "https://example.test/law/1",
                }, ensure_ascii=False)
            if kind == "law_keyword":
                return keyword
            return semantic

        with patch.object(pkulaw_mcp, "call_pkulaw_tool", new=AsyncMock(side_effect=fake_call)):
            result = await pkulaw_mcp.search_laws("民法典第五百七十七条的违约责任", top_k=8)

        payload = json.loads(result["result"])
        laws = payload["法规"]
        self.assertEqual(len(laws), 1)
        self.assertEqual(laws[0]["检索方式"], "语义检索")
        self.assertIn("第五百七十七条", laws[0]["条文内容"])

    async def test_law_search_mixed_numerals_cross_version_metadata(self):
        articles = {
            "一百三十五": "第一百三十五条 必须共同进行诉讼的当事人没有参加诉讼的，人民法院应当通知其参加诉讼。",
            "154": "第一百五十四条 有下列情形之一的，终结诉讼。",
            "155": "第一百五十五条 人民法院作出的判决、裁定发生法律效力后，当事人又申请再审的，不予受理。",
            "七十三": "第七十三条 必须共同进行诉讼的当事人没有参加诉讼的，人民法院应当依照民事诉讼法第一百三十五条的规定，通知其参加。",
        }
        full = json.dumps([{
            "title": "最高人民法院关于适用《中华人民共和国民事诉讼法》的解释(2022修正)",
            "article": "",
            "doc_no": "法释〔2022〕11号",
            "timeliness": "现行有效", "effectiveness": "司法解释",
            "issue_department": "最高人民法院", "issue_date": "2022-04-01",
        }, {
            "title": "北京市高级人民法院关于印发《管辖权异议上诉案件审理工作规范(试行)》的通知",
            "article": "第二十三条 对于一审认定事实清楚、适用法律正确，二审准备维持的案件。",
            "doc_no": "京高法发〔2009〕526号", "timeliness": "现行有效", "effectiveness": "地方司法文件",
        }], ensure_ascii=False)
        keyword = json.dumps({"Data": []}, ensure_ascii=False)
        metadata = json.dumps([{
            "title": "中华人民共和国民事诉讼法(2023修正)",
            "article": "",
            "doc_no": "中华人民共和国主席令第11号",
            "timeliness": "现行有效", "effectiveness": "法律",
            "issue_department": "全国人大常委会", "issue_date": "2023-09-01",
            "url": "https://example.test/law/cps",
        }], ensure_ascii=False)
        precise_calls = []

        async def fake_call(kind, tool, arguments, timeout=35.0):
            if kind == "law_search" and tool == "get_article":
                precise_calls.append(arguments)
                number = arguments["number"].strip("第条")
                return json.dumps({
                    "title": "中华人民共和国民事诉讼法(2023修正)" if number in {"一百三十五", "154", "155"} else
                    "最高人民法院关于适用《中华人民共和国民事诉讼法》的解释(2022修正)",
                    "article": articles[number],
                    "timeliness": "现行有效",
                    "url": "https://example.test/law/" + number,
                }, ensure_ascii=False)
            if kind == "law_keyword":
                return keyword
            if tool == "search_article" and arguments.get("text") == "中华人民共和国民事诉讼法":
                return metadata
            return full if tool == "search_article" else keyword

        query = (
            "《中华人民共和国民事诉讼法》第一百三十五条、154条、155条及"
            "《最高人民法院关于适用<中华人民共和国民事诉讼法>的解释》第七十三条原文"
        )
        with patch.object(pkulaw_mcp, "call_pkulaw_tool", new=AsyncMock(side_effect=fake_call)):
            result = await pkulaw_mcp.search_laws(query, top_k=8)

        self.assertEqual(result["law_count"], 4)
        self.assertEqual(
            sorted(call["number"] for call in precise_calls),
            ["第154条", "第155条", "第一百三十五条", "第七十三条"],
        )
        payload = json.loads(result["result"])
        laws = payload["法规"]
        numbers = sorted(law["条文内容"].split("第", 1)[1].split("条", 1)[0] for law in laws)
        self.assertEqual(numbers, ["一百三十五", "一百五十五", "一百五十四", "七十三"])
        for law in laws:
            self.assertEqual(law["检索方式"], "指定条文查询")
            self.assertNotIn("京高法发", law["文号"])
        for law in laws:
            if "解释" in law["法规名称"]:
                self.assertEqual(law["文号"], "法释〔2022〕11号")
                self.assertEqual(law["制定机关"], "最高人民法院")
            else:
                self.assertEqual(law["文号"], "中华人民共和国主席令第11号")
                self.assertEqual(law["制定机关"], "全国人大常委会")
                self.assertEqual(law["公布日期"], "2023-09-01")


if __name__ == "__main__":
    unittest.main()
