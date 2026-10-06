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
        article_id = self._article()

        async def fake_ai(*_args, **_kwargs):
            answer = {"domains": ["建设工程"], "subcategories": [],
                      "suggestion": {"name": "工程价款优先受偿", "parent_id": root["id"], "keywords": ["工程款"]}}
            return {"choices": [{"message": {"content": json.dumps(answer, ensure_ascii=False)}, "finish_reason": "stop"}]}, "test"

        with patch.object(main, "_call_ai_with_fallback", fake_ai):
            # A child under the root makes the rule pass uncertain, so AI is consulted.
            self.client.post("/api/domains/categories", json={"name": "工程工期", "parent_id": root["id"],
                                                             "keywords": ["工期延误"]})
            asyncio.run(main._classify_queued_article(article_id))
        suggestions = self.client.get("/api/domains/suggestions").json()
        self.assertEqual(len(suggestions), 1)
        self.assertFalse(any(child["name"] == "工程价款优先受偿" for child in
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
        article_id = self._article()

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


if __name__ == "__main__":
    unittest.main()
