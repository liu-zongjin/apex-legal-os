import unittest

from backend.authoritative_legal_search import (
    authority_name,
    is_authoritative_url,
    parse_search_results,
)


class AuthoritativeLegalSearchTests(unittest.TestCase):
    def test_authority_allow_list(self):
        self.assertTrue(is_authoritative_url("https://www.gov.cn/zhengce/content/1.htm"))
        self.assertTrue(is_authoritative_url("https://www.court.gov.cn/fabu/1.html"))
        self.assertTrue(is_authoritative_url("https://www.shiac.org/Rules/1"))
        self.assertFalse(is_authoritative_url("https://court.gov.cn.example.com/not-official"))
        self.assertFalse(is_authoritative_url("javascript:alert(1)"))

    def test_authority_name_prefers_known_institution(self):
        self.assertEqual(authority_name("https://gongbao.court.gov.cn/Details/1"), "最高人民法院公报")
        self.assertEqual(authority_name("https://www.samr.gov.cn/zw/zfxxgk/1.html"), "samr.gov.cn")

    def test_parse_results_filters_and_deduplicates(self):
        page = """
        <ol>
          <li class="b_algo"><h2><a href="https://www.shiac.org/Rules/2024">上海仲裁委员会仲裁规则</a></h2><div class="b_caption"><p>官方发布的现行仲裁规则。</p></div></li>
          <li class="b_algo"><h2><a href="https://www.shiac.org/Rules/2024#top">重复结果</a></h2></li>
          <li class="b_algo"><h2><a href="https://example.com/copy">转载页面</a></h2></li>
          <li class="b_algo"><h2><a href="https://www.court.gov.cn/fabu/1.html">司法文件</a></h2></li>
        </ol>
        """
        rows = parse_search_results(page, 10)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["source"], "上海国际经济贸易仲裁委员会（上海国际仲裁中心）")
        self.assertEqual(rows[0]["snippet"], "官方发布的现行仲裁规则。")
        self.assertEqual(rows[1]["source"], "最高人民法院")

    def test_dynamic_page_reuses_official_download_for_import(self):
        page = """
        <ol>
          <li class="b_algo"><h2><a href="https://www.shiac.org/api/fileOperation/download/rules">SHIAC 2024 仲裁规则</a></h2></li>
          <li class="b_algo"><h2><a href="https://www.shiac.org/pc/SHIAC?moduleCode=arbitrate_rules">上海国际仲裁中心仲裁规则</a></h2></li>
        </ol>
        """
        rows = parse_search_results(page, 10)
        self.assertEqual(rows[0]["import_url"], rows[0]["url"])
        self.assertEqual(rows[1]["import_url"], rows[0]["url"])
        self.assertNotEqual(rows[1]["url"], rows[1]["import_url"])


if __name__ == "__main__":
    unittest.main()
