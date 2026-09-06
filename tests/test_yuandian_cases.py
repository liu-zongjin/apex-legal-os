import unittest

from backend.yuandian_cases import parse_yuandian_cases


class YuandianCaseAdapterTests(unittest.TestCase):
    def test_parses_candidate_without_claiming_summary_is_original_holding(self):
        payload = {
            "code": 201,
            "extra": {"wenshu": [{
                "scid": "abc", "type": 2, "title": "示丆某诉示一某建设工程案",
                "ah": "（2024）京01民终1号", "jbdw": "北京市第一中级人民法院",
                "jand": 2024, "jaDate": 20240506, "content": "平台整理后的案例内容",
                "score": 1.02, "db": "精选案例库",
            }]},
        }
        cases = parse_yuandian_cases(payload, "neutral")
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["judgment_date"], "2024-05-06")
        self.assertEqual(cases[0]["remote_score"], 1.0)
        self.assertEqual(cases[0]["holding"], "")
        self.assertEqual(cases[0]["citation_value"], "候选案例，须核验原文")


if __name__ == "__main__":
    unittest.main()
