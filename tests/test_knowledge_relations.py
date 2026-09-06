import sqlite3
import unittest

from backend import knowledge_relations as kr


class KnowledgeRelationsTests(unittest.TestCase):
    def make_conn(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(
            """
            CREATE TABLE articles (
              id INTEGER PRIMARY KEY, title TEXT, content TEXT, summary TEXT
            );
            CREATE TABLE notes (
              id INTEGER PRIMARY KEY, article_id INTEGER, content TEXT
            );
            CREATE TABLE article_paragraphs (
              id INTEGER PRIMARY KEY, article_id INTEGER, paragraph_index INTEGER,
              text TEXT, char_start INTEGER, char_end INTEGER, heading TEXT
            );
            CREATE TABLE knowledge_issues (
              id INTEGER PRIMARY KEY, title TEXT, domain TEXT, status TEXT
            );
            CREATE TABLE national_law_articles (
              article_id INTEGER PRIMARY KEY, official_title TEXT
            );
            CREATE TABLE knowledge_claims (
              id INTEGER PRIMARY KEY, statement TEXT, claim_type TEXT,
              conditions_text TEXT, exceptions_text TEXT, review_status TEXT,
              confidence REAL
            );
            CREATE TABLE knowledge_claim_issues (
              claim_id INTEGER, issue_id INTEGER
            );
            CREATE TABLE knowledge_claim_evidence (
              id INTEGER PRIMARY KEY, claim_id INTEGER, article_id INTEGER,
              paragraph_index INTEGER, stance TEXT, quote TEXT,
              char_start INTEGER, char_end INTEGER, verified INTEGER
            );
            CREATE TABLE knowledge_extraction_jobs (
              id INTEGER PRIMARY KEY, article_id INTEGER, content_hash TEXT, status TEXT
            );
            """
        )
        kr.ensure_schema(conn)
        return conn

    def add_article(self, conn, article_id, title, content, summary=""):
        conn.execute(
            "INSERT INTO articles(id,title,content,summary) VALUES (?,?,?,?)",
            (article_id, title, content, summary),
        )
        conn.execute(
            """INSERT INTO article_paragraphs
               (id,article_id,paragraph_index,text,char_start,char_end,heading)
               VALUES (?,?,?,?,0,?,'')""",
            (article_id, article_id, 1, content, len(content)),
        )

    def test_chinese_and_arabic_provisions_share_one_node(self):
        conn = self.make_conn()
        text = (
            "法院依据《中华人民共和国民法典》第五百六十三条解除合同。"
            "《中华人民共和国民法典》第563条亦有规定。"
        )
        self.add_article(conn, 1, "合同解除案例", text)
        result = kr.scan_article_rules(conn, 1)
        self.assertEqual(result["created"], 2)
        nodes = conn.execute(
            "SELECT * FROM knowledge_nodes WHERE node_type='statute_provision'"
        ).fetchall()
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["provision_number"], 563)
        mentions = conn.execute(
            "SELECT relation_type,status FROM knowledge_mentions ORDER BY id"
        ).fetchall()
        self.assertEqual([r["relation_type"] for r in mentions], ["applies", "cites"])
        self.assertTrue(all(r["status"] == "candidate" for r in mentions))

    def test_continued_provisions_inherit_the_explicit_law_only(self):
        conn = self.make_conn()
        law = "第七十一条 规定一。\n第七十二条 规定二。\n第七十三条 规定三。"
        conn.execute("INSERT INTO articles VALUES (10,'中华人民共和国公司法',?,'')", (law,))
        conn.execute("INSERT INTO national_law_articles VALUES (10,'中华人民共和国公司法')")
        conn.executemany(
            "INSERT INTO article_paragraphs VALUES (?,?,?,?,?,?,?)",
            [
                (101, 10, 1, "第七十一条 规定一。", 0, 9, ""),
                (102, 10, 2, "第七十二条 规定二。", 10, 19, ""),
                (103, 10, 3, "第七十三条 规定三。", 20, 29, ""),
            ],
        )
        text = "依照《公司法》第71条、第七十二条及73条处理，和本规定第41条无关。"
        self.add_article(conn, 1, "公司案例", text)

        result = kr.scan_article_rules(conn, 1)
        self.assertEqual(result["created"], 3)
        numbers = [
            row[0] for row in conn.execute(
                """SELECT n.provision_number FROM knowledge_mentions m
                   JOIN knowledge_nodes n ON n.id=m.target_node_id
                   ORDER BY m.char_start"""
            ).fetchall()
        ]
        self.assertEqual(numbers, [71, 72, 73])
        methods = {
            row[0] for row in conn.execute(
                "SELECT detection_method FROM knowledge_mentions"
            ).fetchall()
        }
        self.assertEqual(methods, {"law_rule", "law_rule_continuation"})

    def test_summary_notes_and_claims_are_candidates_until_reviewed(self):
        conn = self.make_conn()
        self.add_article(conn, 1, "履行案例", "正文没有关键词。", "涉及合同解除")
        conn.execute("INSERT INTO notes VALUES (1,1,'本案支持合同解除')")
        conn.execute("INSERT INTO knowledge_issues VALUES (1,'合同解除','合同法','active')")
        result = kr.scan_article_rules(conn, 1)
        self.assertEqual(result["created"], 2)
        kinds = {
            row["source_kind"] for row in conn.execute(
                "SELECT source_kind FROM knowledge_mentions"
            ).fetchall()
        }
        self.assertEqual(kinds, {"summary", "note"})
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM knowledge_mentions WHERE status='confirmed'"
            ).fetchone()[0],
            0,
        )

    def test_confirmed_link_appears_as_backlink_and_rejected_does_not(self):
        conn = self.make_conn()
        self.add_article(conn, 1, "来源文章", "讨论合同解除。")
        conn.execute("INSERT INTO knowledge_issues VALUES (1,'合同解除','合同法','active')")
        kr.scan_article_rules(conn, 1)
        mention_id = conn.execute("SELECT id FROM knowledge_mentions").fetchone()[0]
        kr.review_mention(conn, mention_id, status="confirmed", relation_type="discusses")
        node_id = conn.execute("SELECT target_node_id FROM knowledge_mentions").fetchone()[0]
        detail = kr.node_detail(conn, node_id)
        self.assertEqual(len(detail["backlinks"]), 1)
        self.assertEqual(detail["backlinks"][0]["source_title"], "来源文章")
        kr.review_mention(conn, mention_id, status="rejected")
        self.assertEqual(kr.node_detail(conn, node_id)["backlinks"], [])

    def test_statute_node_detail_includes_provision_text_and_location(self):
        conn = self.make_conn()
        law = "第一条 总则。\n第九十三条 重整计划不能执行时，人民法院应当宣告破产。\n第九十四条 后续规定。"
        conn.execute("INSERT INTO articles VALUES (10,'中华人民共和国企业破产法',?,'')", (law,))
        conn.execute("INSERT INTO national_law_articles VALUES (10,'中华人民共和国企业破产法')")
        paragraphs = [
            (101, 10, 1, "第一条 总则。", 0, 7, ""),
            (102, 10, 2, "第九十三条 重整计划不能执行时，人民法院应当宣告破产。", 8, 35, ""),
            (103, 10, 3, "第九十四条 后续规定。", 36, 48, ""),
        ]
        conn.executemany(
            "INSERT INTO article_paragraphs VALUES (?,?,?,?,?,?,?)", paragraphs
        )
        self.add_article(conn, 1, "案例", "依据《中华人民共和国企业破产法》第93条处理。")
        kr.scan_article_rules(conn, 1)
        node_id = conn.execute(
            "SELECT id FROM knowledge_nodes WHERE node_type='statute_provision'"
        ).fetchone()[0]
        detail = kr.node_detail(conn, node_id)
        self.assertIn("重整计划不能执行", detail["source_text"])
        self.assertNotIn("第九十四条", detail["source_text"])
        self.assertEqual(detail["source_char_start"], 8)

    def test_missing_statute_node_reconciles_with_unregistered_law_article(self):
        conn = self.make_conn()
        law = "第一条 基本原则。\n第一百五十四条 有下列情形之一的，终结诉讼。"
        conn.execute("INSERT INTO articles VALUES (10,'中华人民共和国民事诉讼法',?,'')", (law,))
        conn.executemany(
            "INSERT INTO article_paragraphs VALUES (?,?,?,?,?,?,?)",
            [
                (101, 10, 1, "第一条 基本原则。", 0, 8, ""),
                (102, 10, 2, "第一百五十四条 有下列情形之一的，终结诉讼。", 9, 32, ""),
            ],
        )
        self.add_article(conn, 1, "案例", "依照《中华人民共和国民事诉讼法》第154条裁定。")

        # Simulate the old state: the reference was created before the law
        # article had an entry in national_law_articles.
        node_id = kr._statute_node(conn, "中华人民共和国民事诉讼法", 154, None)
        before = conn.execute(
            "SELECT source_status FROM knowledge_nodes WHERE id=?", (node_id,)
        ).fetchone()[0]
        self.assertEqual(before, "missing_source")

        detail = kr.node_detail(conn, node_id)
        self.assertEqual(detail["source_status"], "available")
        self.assertEqual(detail["article_id"], 10)
        self.assertIn("终结诉讼", detail["source_text"])

    def test_issue_node_detail_includes_claim_and_evidence(self):
        conn = self.make_conn()
        self.add_article(conn, 1, "案例", "债务人资不抵债时，出资人权益为零。")
        conn.execute("INSERT INTO knowledge_issues VALUES (1,'出资人权益价值认定','破产法','active')")
        conn.execute(
            """INSERT INTO knowledge_claims
               VALUES (1,'资不抵债时出资人权益为零','rule','','','approved',0.98)"""
        )
        conn.execute("INSERT INTO knowledge_claim_issues VALUES (1,1)")
        conn.execute(
            """INSERT INTO knowledge_claim_evidence
               VALUES (1,1,1,1,'supports','债务人资不抵债时，出资人权益为零。',0,18,1)"""
        )
        kr.sync_issue_nodes(conn)
        node_id = conn.execute(
            "SELECT id FROM knowledge_nodes WHERE node_type='issue'"
        ).fetchone()[0]
        detail = kr.node_detail(conn, node_id)
        self.assertEqual(detail["claims"][0]["statement"], "资不抵债时出资人权益为零")
        self.assertEqual(detail["claims"][0]["evidence"][0]["article_title"], "案例")

    def test_changed_content_marks_old_relationship_stale(self):
        conn = self.make_conn()
        self.add_article(conn, 1, "来源文章", "讨论合同解除。")
        conn.execute("INSERT INTO knowledge_issues VALUES (1,'合同解除','合同法','active')")
        kr.scan_article_rules(conn, 1)
        mention_id = conn.execute("SELECT id FROM knowledge_mentions").fetchone()[0]
        kr.review_mention(conn, mention_id, status="confirmed")
        conn.execute("UPDATE articles SET content='正文已删除原有法律问题。' WHERE id=1")
        conn.execute(
            "UPDATE article_paragraphs SET text='正文已删除原有法律问题。',char_end=12 WHERE article_id=1"
        )
        kr.scan_article_rules(conn, 1)
        self.assertEqual(
            conn.execute(
                "SELECT status FROM knowledge_mentions WHERE id=?", (mention_id,)
            ).fetchone()[0],
            "stale",
        )

    def test_long_article_requires_open_and_explicit_confirmation(self):
        conn = self.make_conn()
        self.add_article(conn, 1, "超长汇编", "法" * kr.LONG_ARTICLE_CHARS)
        estimate = kr.scan_estimate(conn, 1)
        self.assertTrue(estimate["long_article"])
        self.assertFalse(estimate["opened"])
        allowed, guard = kr.ai_scan_allowed(conn, 1, confirmed=True)
        self.assertFalse(allowed)
        self.assertEqual(guard["reason"], "long_article_confirmation_required")
        opened = kr.mark_article_opened(conn, 1)
        self.assertTrue(opened["prompt_required"])
        allowed, _ = kr.ai_scan_allowed(conn, 1, confirmed=False)
        self.assertFalse(allowed)
        allowed, guard = kr.ai_scan_allowed(conn, 1, confirmed=True)
        self.assertTrue(allowed)
        kr.authorize_ai_scan(conn, 1, guard["content_hash"])
        authorized = conn.execute(
            "SELECT ai_authorized_hash FROM article_relation_state WHERE article_id=1"
        ).fetchone()[0]
        self.assertEqual(authorized, guard["content_hash"])

    def test_same_completed_content_is_reused(self):
        conn = self.make_conn()
        self.add_article(conn, 1, "超长汇编", "法" * kr.LONG_ARTICLE_CHARS)
        estimate = kr.scan_estimate(conn, 1)
        conn.execute(
            "INSERT INTO knowledge_extraction_jobs VALUES (1,1,?,'completed')",
            (estimate["content_hash"],),
        )
        estimate = kr.scan_estimate(conn, 1)
        self.assertTrue(estimate["cached_ai"])
        allowed, guard = kr.ai_scan_allowed(conn, 1, confirmed=False)
        self.assertFalse(allowed)
        self.assertEqual(guard["reason"], "cached")


if __name__ == "__main__":
    unittest.main()
