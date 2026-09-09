import sqlite3
import unittest

from backend import main


class ExhaustiveArticleContextTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE articles (id INTEGER PRIMARY KEY, content TEXT);
            CREATE TABLE article_paragraphs (
                article_id INTEGER,
                paragraph_index INTEGER,
                text TEXT,
                char_start INTEGER,
                char_end INTEGER,
                heading TEXT,
                created_at TEXT
            );
        """)
        self.conn.execute(
            "INSERT INTO articles(id, content) VALUES(?, ?)",
            (7, "一、第一项\\n核心要求甲。\\n\\n二、第二项\\n核心要求乙。\\n\\n三、第三项\\n核心要求丙。"),
        )

    def tearDown(self):
        self.conn.close()

    def test_full_article_context_keeps_every_paragraph_in_source_order(self):
        paragraphs = main.load_all_article_paragraphs_for_qa(self.conn, 7, "测试通知")
        context, _sources, _map = main.build_paragraph_context(paragraphs, max_chars=90000)

        self.assertEqual([item["paragraph_index"] for item in paragraphs], list(range(1, len(paragraphs) + 1)))
        self.assertIn("核心要求甲。", context)
        self.assertIn("核心要求乙。", context)
        self.assertIn("核心要求丙。", context)
        self.assertLess(context.index("核心要求甲。"), context.index("核心要求乙。"))
        self.assertLess(context.index("核心要求乙。"), context.index("核心要求丙。"))


if __name__ == "__main__":
    unittest.main()
