import unittest
from backend.case_text_matching import match_case_text


class CaseTextMatchingTests(unittest.TestCase):
    def test_abbreviated_reference(self):
        rows = [{'case_id': 1, 'title': '甲建筑公司与当代星河置业公司建设工程施工合同纠纷（湖畔花园）', 'party_name': '当代星河置业公司'},
                {'case_id': 2, 'title': '丙公司买卖合同纠纷', 'party_name': '丙公司'}]
        self.assertEqual(match_case_text('当代星河（湖畔）债权表决 2026年11月19日之前提交', rows)['case_id'], 1)

    def test_multiple_matches_do_not_auto_associate(self):
        rows = [{'case_id': 1, 'title': '当代星河置业公司合同纠纷'},
                {'case_id': 2, 'title': '当代星河置业公司借款纠纷'}]
        self.assertIsNone(match_case_text('当代星河置业明天开庭', rows))

    def test_generic_legal_terms_do_not_select_case(self):
        rows = [{'case_id': 1, 'title': '甲公司建设工程施工合同纠纷'}]
        self.assertIsNone(match_case_text('建设工程施工合同纠纷明天开庭', rows))

    def test_duplicate_party_rows_are_one_case(self):
        rows = [{'case_id': 1, 'title': '当代星河置业项目纠纷'},
                {'case_id': 1, 'title': '当代星河置业项目纠纷'}]
        self.assertEqual(match_case_text('当代星河置业明天开庭', rows)['case_id'], 1)
