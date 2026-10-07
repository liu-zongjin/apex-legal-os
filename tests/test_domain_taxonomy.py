import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import main


class DomainTaxonomyTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_path = main.DB_PATH
        main.DB_PATH = Path(self.tempdir.name) / "taxonomy.db"
        main.init_db()
        self.client = TestClient(main.app)

    def tearDown(self):
        main.DB_PATH = self.original_path
        self.tempdir.cleanup()

    def _article(self, title="建设工程价款优先受偿权", content="建设工程施工合同的工程款与竣工结算争议。"):
        return main.save_article(title, content, "", main.classify_domains(title + content), "url",
                                 source_url="https://example.org/article", tags=["作者:测试"])

    def test_import_and_child_filter_preserve_manual_exclusion(self):
        root = next(item for item in self.client.get("/api/domains").json() if item["domain"] == "建设工程")
        child = self.client.post("/api/domains/categories", json={"name": "工程价款", "parent_id": root["id"],
                                                                   "keywords": ["工程款", "竣工结算"]}).json()
        article_id = self._article()
        asyncio.run(main._classify_queued_article(article_id))
        detail = self.client.get(f"/api/articles/{article_id}").json()
        self.assertIn("建设工程", detail["domains"])
        self.assertIn(child["id"], detail["subcategory_ids"])
        filtered = self.client.get("/api/articles", params={"domain": "建设工程", "subcategory_id": child["id"]}).json()
        self.assertEqual(filtered["total"], 1)

        self.assertEqual(self.client.put(f"/api/articles/{article_id}/subcategories", json={"ids": []}).status_code, 200)
        asyncio.run(main._classify_queued_article(article_id))
        self.assertNotIn(child["id"], self.client.get(f"/api/articles/{article_id}").json()["subcategory_ids"])
        main.init_db()
        self.assertNotIn(child["id"], self.client.get(f"/api/articles/{article_id}").json()["subcategory_ids"])

        self.assertEqual(self.client.put(f"/api/articles/{article_id}/tags",
                                         data={"tags": '["作者:测试"]', "domains": "[]"}).status_code, 200)
        asyncio.run(main._classify_queued_article(article_id))
        self.assertNotIn("建设工程", self.client.get(f"/api/articles/{article_id}").json()["domains"])

    def test_ai_suggestion_requires_approval_and_uses_accepted_child(self):
        root = next(item for item in self.client.get("/api/domains").json() if item["domain"] == "建设工程")
        article_id = self._article(title="建设工程合同价款请求", content="本文分析建设工程合同中的价款请求。")

        async def fake_ai(*_args, **_kwargs):
            answer = {"domains": ["建设工程"], "subcategories": [],
                      "suggestion": {"name": "价款请求权", "parent_id": root["id"], "keywords": ["价款请求"]}}
            return {"choices": [{"message": {"content": json.dumps(answer, ensure_ascii=False)}, "finish_reason": "stop"}]}, "test"

        with patch.object(main, "_call_ai_with_fallback", fake_ai):
            # A child under the root makes the rule pass uncertain, so AI is consulted.
            self.client.post("/api/domains/categories", json={"name": "工程工期", "parent_id": root["id"],
                                                             "keywords": ["工期延误"]})
            asyncio.run(main._classify_queued_article(article_id))
        self.assertEqual(self.client.get("/api/domains/suggestions").json(), [])
        second_id = self._article(title="建设工程合同价款请求续", content="另一个建设工程合同价款请求案例。")
        with patch.object(main, "_call_ai_with_fallback", fake_ai):
            asyncio.run(main._classify_queued_article(second_id))
        suggestions = self.client.get("/api/domains/suggestions").json()
        self.assertEqual(len(suggestions), 1)
        self.assertFalse(any(child["name"] == "价款请求权" for child in
                             next(item for item in self.client.get("/api/domains").json() if item["id"] == root["id"])["children"]))
        approved = self.client.post(f"/api/domains/suggestions/{suggestions[0]['id']}/approve").json()
        self.assertEqual(approved["parent_id"], root["id"])
        asyncio.run(main._classify_queued_article(article_id))
        self.assertIn(approved["id"], self.client.get(f"/api/articles/{article_id}").json()["subcategory_ids"])

    def test_history_preview_and_source_url_not_a_topic(self):
        article_id = self._article(title="https://example.org/path", content="建设工程施工合同的工程款与竣工结算争议。")
        with main.get_db() as conn:
            conn.execute("UPDATE articles SET domains=? WHERE id=?", (json.dumps(["https://example.org", "建设工程"]), article_id))
            conn.commit()
        preview = self.client.get("/api/domains/reclassify/preview").json()["items"]
        item = next(row for row in preview if row["id"] == article_id)
        self.assertIn("https://example.org", item["remove"])
        self.client.post("/api/domains/reclassify/apply", json={"after_id": 0, "limit": 50})
        detail = self.client.get(f"/api/articles/{article_id}").json()
        self.assertNotIn("https://example.org", detail["domains"])
        self.assertEqual(detail["source_url"], "https://example.org/article")

    def test_ai_failure_keeps_article_and_rule_domain(self):
        article_id = self._article(title="建设工程合同价款请求", content="本文分析建设工程合同中的价款请求。")

        async def unavailable(*_args, **_kwargs):
            raise RuntimeError("offline")

        with patch.object(main, "_call_ai_with_fallback", unavailable):
            asyncio.run(main._classify_queued_article(article_id))
        self.assertIn("建设工程", self.client.get(f"/api/articles/{article_id}").json()["domains"])
        with main.get_db() as conn:
            status = conn.execute("SELECT status FROM domain_classification_jobs WHERE article_id=?", (article_id,)).fetchone()[0]
        self.assertEqual(status, "needs_review")
        self.assertEqual(self.client.get("/api/domains/pending-count").json()["count"], 1)
        self.assertEqual(self.client.get("/api/articles", params={"classification_status": "needs_review"}).json()["total"], 1)

    def test_rule_discovers_child_suggestions_and_accepted_child_matches_history(self):
        first_id = self._article()
        second_id = self._article(title="工程款支付实务", content="建设工程工程款如何结算支付。")
        asyncio.run(main._classify_queued_article(first_id))
        asyncio.run(main._classify_queued_article(second_id))
        suggestions = self.client.get("/api/domains/suggestions").json()
        match = next(item for item in suggestions if item["name"] == "工程价款与优先受偿")
        self.assertEqual(match["support_count"], 2)
        root = next(item for item in self.client.get("/api/domains").json() if item["domain"] == "建设工程")
        self.assertFalse(root["children"])
        accepted = self.client.post(f"/api/domains/suggestions/{match['id']}/approve").json()
        asyncio.run(main._classify_queued_article(first_id))
        asyncio.run(main._classify_queued_article(second_id))
        for article_id in (first_id, second_id):
            self.assertIn(accepted["id"], self.client.get(f"/api/articles/{article_id}").json()["subcategory_ids"])

    def test_approved_child_order_can_be_changed_without_reclassifying_articles(self):
        root = next(item for item in self.client.get("/api/domains").json() if item["domain"] == "建设工程")
        first = self.client.post("/api/domains/categories", json={"name": "工期与索赔", "parent_id": root["id"], "keywords": ["工期"]}).json()
        second = self.client.post("/api/domains/categories", json={"name": "工程质量", "parent_id": root["id"], "keywords": ["验收"]}).json()
        response = self.client.post("/api/domains/categories/reorder", json={"parent_id": root["id"], "ids": [second["id"], first["id"]]})
        self.assertEqual(response.status_code, 200)
        children = next(item for item in self.client.get("/api/domains").json() if item["id"] == root["id"])["children"]
        self.assertEqual([child["id"] for child in children], [second["id"], first["id"]])
        main.init_db()
        children = next(item for item in self.client.get("/api/domains").json() if item["id"] == root["id"])["children"]
        self.assertEqual([child["id"] for child in children], [second["id"], first["id"]])

    def test_incidental_late_summary_mention_does_not_create_child(self):
        article_id = self._article(title="执行程序规定", content="执行程序和财产查控。")
        with main.get_db() as conn:
            conn.execute("UPDATE articles SET summary=? WHERE id=?", ("执行程序的一般规则。" + "程序说明。" * 40 + "专利权也可能是执行财产。", article_id))
            conn.commit()
            article = conn.execute("SELECT id,title,summary,content FROM articles WHERE id=?", (article_id,)).fetchone()
            candidates = main.domain_taxonomy_module.rule_child_candidates(conn, article["title"], article["summary"], ["知识产权"])
        self.assertFalse(any(item["name"] == "专利" for item in candidates))

    def test_suggestion_review_page_filters_and_paginates(self):
        root = next(item for item in self.client.get("/api/domains").json() if item["domain"] == "建设工程")
        first_id = self._article(title="工程款争议甲")
        second_id = self._article(title="工程款争议乙", content="建设工程施工合同的另一项工程款付款争议。")
        with main.get_db() as conn:
            main.domain_taxonomy_module.suggest(conn, "工程价款结算", root["id"], first_id, ["工程价款"])
            main.domain_taxonomy_module.suggest(conn, "工程价款结算", root["id"], second_id, ["工程价款"])
            main.domain_taxonomy_module.suggest(conn, "工期索赔", root["id"], second_id, ["工期"])
            self.assertIsNone(main.domain_taxonomy_module.suggest(
                conn, "民事诉讼举证责任分配与高度盖然性证明标准", root["id"], first_id, ["举证责任"]))
            # Historical proposals created before the stricter rule remain in
            # storage, but cannot be shown or approved as taxonomy nodes.
            legacy = conn.execute(
                "INSERT INTO domain_suggestions(name,parent_id,article_id,created_at) VALUES (?,?,?,?)",
                ("民事诉讼举证责任分配与高度盖然性证明标准", root["id"], first_id, "2026-01-01"),
            ).lastrowid
            for article_id in (first_id, second_id):
                conn.execute("INSERT INTO domain_suggestion_articles(suggestion_id,article_id) VALUES (?,?)",
                             (legacy, article_id))
            conn.commit()
        page = self.client.get("/api/domains/suggestions/page", params={"filter": "supported", "limit": 1}).json()
        self.assertEqual(page["total"], 1)
        self.assertEqual(page["items"][0]["support_count"], 2)
        self.assertFalse(page["has_more"])
        page = self.client.get("/api/domains/suggestions/page", params={"q": "建设工程", "limit": 1}).json()
        self.assertEqual(page["total"], 1)
        self.assertFalse(page["has_more"])
        self.assertEqual(len(self.client.get("/api/domains/suggestions/page", params={"q": "建设工程", "offset": 1}).json()["items"]), 0)
        self.assertEqual(self.client.get("/api/domains/suggestions/page", params={"q": "工程 价款"}).json()["total"], 1)
        self.assertEqual(len(self.client.get("/api/domains/suggestions").json()), 1)
        with main.get_db() as conn:
            single = conn.execute("SELECT id FROM domain_suggestions WHERE name='工期索赔'").fetchone()[0]
        self.assertEqual(self.client.post(f"/api/domains/suggestions/{single}/approve").status_code, 409)
        self.assertEqual(self.client.post(f"/api/domains/suggestions/{legacy}/approve").status_code, 409)


if __name__ == "__main__":
    unittest.main()
