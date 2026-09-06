import unittest

from backend.main import _pdf_join_words, _pdf_page_corner_title


class PdfPageCornerTitleTests(unittest.TestCase):
    def test_corner_title_takes_first_line_in_top_left_region(self):
        words = [
            [40.0, 60.0, 90.0, 82.0, "一、"],
            [92.0, 61.0, 130.0, 83.0, "建设工程"],
            [132.0, 61.0, 170.0, 83.0, "价款"],
            [20.0, 400.0, 80.0, 420.0, "正文"],
            [90.0, 401.0, 200.0, 421.0, "内容"],
        ]
        title = _pdf_page_corner_title(words, 1000, 800, "")
        self.assertEqual(title, "一、建设工程价款")

    def test_corner_title_ignores_right_side_and_low_words(self):
        words = [
            [40.0, 60.0, 90.0, 82.0, "标题"],
            [850.0, 60.0, 900.0, 82.0, "右上角"],
            [40.0, 200.0, 90.0, 220.0, "第二行"],
        ]
        title = _pdf_page_corner_title(words, 1000, 800, "")
        self.assertEqual(title, "标题")

    def test_corner_title_falls_back_to_first_text_line(self):
        title = _pdf_page_corner_title([], 1000, 800, "\n第一部分 建设工程价款\n正文内容")
        self.assertEqual(title, "第一部分 建设工程价款")

    def test_corner_title_empty_when_no_words_and_no_text(self):
        self.assertEqual(_pdf_page_corner_title([], 1000, 800, ""), "")

    def test_corner_title_truncates_long_titles(self):
        words = [[40.0, 60.0, 90.0, 82.0, "很长的标题" * 10]]
        title = _pdf_page_corner_title(words, 1000, 800, "")
        self.assertLessEqual(len(title), 41)
        self.assertTrue(title.endswith("…"))

    def test_join_words_spaces_latin_and_digits(self):
        self.assertEqual(_pdf_join_words(["民法典", "第", "807", "条"]), "民法典第807条")
        self.assertEqual(_pdf_join_words(["Article", "1", "（a）"]), "Article 1（a）")


if __name__ == "__main__":
    unittest.main()
