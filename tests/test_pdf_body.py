"""Anonymous layout fixtures; furniture filtering must not erase legal content."""
import unittest

from backend.pdf_body import clean_pages


def line(text, top, bottom=None):
    return {'text': text, 'top': top, 'bottom': bottom if bottom is not None else top + .02}


class PDFBodyTests(unittest.TestCase):
    def test_spaced_bilingual_masthead_and_page_numbers(self):
        pages = [[line('示 例 律 师 事 务 所', .03), line('EXAMPLE LAW OFFICES', .06),
                  line('民事起诉状', .15), line('原告主张尚未收到10000元。', .22),
                  line(str(number), .96)] for number in (1, 2, 3)]
        bodies, removed = clean_pages(pages)
        self.assertEqual(bodies, ['民事起诉状\n原告主张尚未收到10000元。'] * 3)
        self.assertEqual(len(removed), 9)
        self.assertEqual([row['page'] for row in removed if row['reason'] == 'footer'], [1, 2, 3])

    def test_single_page_bilingual_logo_without_brand_dictionary(self):
        bodies, _ = clean_pages([[line('虚构律师事务所', .02), line('FICTIONAL LAW FIRM', .05),
                                  line('合同价款为10000元。', .18)]])
        self.assertEqual(bodies, ['合同价款为10000元。'])

    def test_repeated_body_and_substantive_edge_clauses_survive(self):
        page = [line('原告：匿名公司', .01), line('乙方应当支付10000元。', .04), line('示例律师事务所代理本案。', .2),
                line('EXAMPLE LAW OFFICES', .3), line('双方同意按约履行。', .5),
                line('付款期限为2026年1月1日。', .93), line('1000', .97)]
        bodies, removed = clean_pages([page, page])
        self.assertEqual(removed, [])
        self.assertTrue(all('尚未' not in body and '1000' in body for body in bodies))
        self.assertEqual(bodies[0], '\n'.join(row['text'] for row in page))

    def test_ocr_without_layout_only_removes_recognizable_furniture(self):
        bodies, removed = clean_pages([[{'text': text} for text in (
            '示 例 律 师 事 务 所', 'EXAMPLE LAW OFFICES', '价款尚未支付。', '1000')]])
        self.assertEqual(bodies, ['价款尚未支付。\n1000'])
        self.assertEqual(len(removed), 2)

    def test_page_count_and_blank_pages_survive(self):
        bodies, _ = clean_pages([[line('示例律师事务所', .02), line('EXAMPLE LAW OFFICES', .05)],
                                 [line('证据正文', .2)]])
        self.assertEqual(bodies, ['', '证据正文'])

    def test_repetition_is_not_a_reason_to_erase_substantive_text(self):
        page = [line('债务已全部清偿，双方互不追究。', .03), line('合同签订经过', .2),
                line('货物均已交付完毕。', .94)]
        bodies, removed = clean_pages([page, page, page])
        self.assertEqual(removed, [])
        self.assertEqual(bodies, ['\n'.join(row['text'] for row in page)] * 3)

    def test_ocr_trailing_numbers_and_shares_are_not_assumed_page_numbers(self):
        for value in ('1', '1/2', '2/3'):
            body, removed = clean_pages([[{'text': text} for text in ('双方约定如下', '份额记载为', value)]])
            self.assertTrue(body[0].endswith(value))
            self.assertEqual(removed, [])
        body, removed = clean_pages([[{'text': text} for text in ('双方约定如下', '合同正文', '第 1 页')]])
        self.assertEqual(body, ['双方约定如下\n合同正文'])
        self.assertEqual(len(removed), 1)

    def test_bilingual_masthead_with_english_on_a_separate_line(self):
        body, _ = clean_pages([[line('虚构律师事务所', .02), line('LAW OFFICES', .05),
                               line('当事人否认已付款。', .2)]])
        self.assertEqual(body, ['当事人否认已付款。'])
