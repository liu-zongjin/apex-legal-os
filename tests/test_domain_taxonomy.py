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

    def test_rename_preserves_identity_keywords_choices_and_suppresses_old_name(self):
        root = next(x for x in self.client.get("/api/domains").json() if x["domain"] == "建设工程")
        child = self.client.post("/api/domains/categories", json={"name": "工程价款", "parent_id": root["id"], "keywords": ["工程款"]}).json()
        other = self.client.post("/api/domains/categories", json={"name": "工程工期", "parent_id": root["id"]}).json()
        article_id = self._article()
        self.client.put(f"/api/articles/{article_id}/subcategories", json={"ids": [child["id"]]})
        response = self.client.put(f"/api/domains/categories/{child['id']}/rename", json={"name": "价款请求"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["id"], child["id"])
        detail = self.client.get(f"/api/articles/{article_id}").json()
        self.assertIn(child["id"], detail["subcategory_ids"])
        with main.get_db() as conn:
            self.assertIn("工程款", json.loads(conn.execute("SELECT keywords_json FROM domain_taxonomy WHERE id=?", (child["id"],)).fetchone()[0]))
            self.assertIsNotNone(conn.execute("SELECT 1 FROM domain_taxonomy_suppressed_children WHERE parent_id=? AND name='工程价款'", (root["id"],)).fetchone())
        with main.get_db() as conn:
            self.assertIsNone(main.domain_taxonomy_module.suggest(conn, "工程价款", root["id"], article_id, ["工程款"]))
        self.assertEqual(self.client.put(f"/api/domains/categories/{child['id']}/rename", json={"name": "工程工期"}).status_code, 409)
        self.assertEqual(self.client.put(f"/api/domains/categories/{root['id']}/rename", json={"name": "一级改名"}).status_code, 400)
        self.assertEqual(self.client.post("/api/domains/categories/reorder", json={"parent_id": root["id"], "ids": [child["id"], child["id"]]}).status_code, 409)
        children = next(x for x in self.client.get("/api/domains").json() if x["id"] == root["id"])["children"]
        self.assertEqual([x["id"] for x in children], [child["id"], other["id"]])

    def test_offline_snapshot_contains_classification_and_excludes_manual_exclusions(self):
        root = next(x for x in self.client.get("/api/domains").json() if x["domain"] == "建设工程")
        child = self.client.post("/api/domains/categories", json={"name": "工程价款", "parent_id": root["id"], "keywords": ["工程款"]}).json()
        article_id = self._article()
        asyncio.run(main._classify_queued_article(article_id))
        snapshot = self.client.get("/api/articles/offline-snapshot").json()
        self.assertEqual(snapshot["version"], 3)
        article = next(x for x in snapshot["articles"] if x["id"] == article_id)
        self.assertIn(child["id"], article["subcategory_ids"])
        self.assertEqual(article["classification_status"], self.client.get(f"/api/articles/{article_id}").json()["classification_status"])
        self.client.put(f"/api/articles/{article_id}/subcategories", json={"ids": []})
        article = next(x for x in self.client.get("/api/articles/offline-snapshot").json()["articles"] if x["id"] == article_id)
        self.assertEqual(article["subcategory_ids"], [])

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

    def test_delete_child_preserves_articles_and_prevents_automatic_recreation(self):
        root = next(item for item in self.client.get("/api/domains").json() if item["domain"] == "建设工程")
        empty = self.client.post("/api/domains/categories", json={
            "name": "过细争点", "parent_id": root["id"], "keywords": ["过细争点"]
        }).json()
        self.assertEqual(self.client.delete(f"/api/domains/categories/{empty['id']}").json()["affected_articles"], 0)

        child = self.client.post("/api/domains/categories", json={
            "name": "工程价款与优先受偿", "parent_id": root["id"], "keywords": ["工程款", "优先受偿"]
        }).json()
        article_id = self._article()
        asyncio.run(main._classify_queued_article(article_id))
        self.assertIn(child["id"], self.client.get(f"/api/articles/{article_id}").json()["subcategory_ids"])
        response = self.client.delete(f"/api/domains/categories/{child['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["affected_articles"], 1)
        self.assertEqual(self.client.delete(f"/api/domains/categories/{root['id']}").status_code, 400)
        self.assertEqual(self.client.delete(f"/api/domains/categories/{child['id']}").status_code, 404)
        self.assertEqual(self.client.get(f"/api/articles/{article_id}").status_code, 200)
        asyncio.run(main._classify_queued_article(article_id))
        self.assertNotIn(child["id"], self.client.get(f"/api/articles/{article_id}").json()["subcategory_ids"])
        self.assertFalse(any(item["name"] == child["name"] for item in self.client.get("/api/domains/suggestions").json()))
        main.init_db()
        self.assertFalse(any(item["name"] == child["name"] for item in
                             next(item for item in self.client.get("/api/domains").json() if item["id"] == root["id"])["children"]))

        recreated = self.client.post("/api/domains/categories", json={
            "name": child["name"], "parent_id": root["id"], "keywords": ["工程款"]
        }).json()
        asyncio.run(main._classify_queued_article(article_id))
        self.assertIn(recreated["id"], self.client.get(f"/api/articles/{article_id}").json()["subcategory_ids"])

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

    def test_historical_single_article_phrases_form_one_reusable_topic(self):
        first_id = self._article(title="民事举证案例甲", content="关于举证责任分配的讨论。")
        second_id = self._article(title="民事举证案例乙", content="关于高度盖然性的讨论。")
        with main.get_db() as conn:
            for article_id, name in ((first_id, "举证责任分配"),
                                     (second_id, "民事诉讼举证责任分配与高度盖然性证明标准")):
                row_id = conn.execute(
                    "INSERT INTO domain_suggestions(name,parent_id,article_id,created_at) VALUES (?,NULL,?,?)",
                    (name, article_id, "2026-01-01"),
                ).lastrowid
                conn.execute("INSERT INTO domain_suggestion_articles(suggestion_id,article_id) VALUES (?,?)",
                             (row_id, article_id))
            main.domain_taxonomy_module.backfill_reusable_suggestions(conn)
            main.domain_taxonomy_module.backfill_reusable_suggestions(conn)
            conn.commit()
        page = self.client.get("/api/domains/suggestions/page").json()
        self.assertEqual(page["total"], 1)
        self.assertEqual(page["items"][0]["name"], "民事诉讼")
        self.assertEqual(page["items"][0]["support_count"], 2)
        self.assertEqual(self.client.post(
            f"/api/domains/suggestions/{page['items'][0]['id']}/approve").status_code, 200)

    def test_all_predefined_domains_have_child_discovery_rules(self):
        self.assertFalse(set(main.LEGAL_DOMAINS_V2) - set(main.domain_taxonomy_module.CHILD_TOPIC_RULES))

    def test_missing_domains_discover_history_and_keep_manual_choices(self):
        topics = [("民事诉讼法", "举证责任分配", "证据与证明"),
                  ("民商事审判", "裁判说理方法", "裁判文书与说理"),
                  ("物权", "善意取得认定", "善意取得"),
                  ("刑事法律", "认罪认罚实务", "定罪与量刑"),
                  ("侵权责任", "医疗损害责任", "医疗损害责任"),
                  ("婚姻家事", "子女抚养权", "子女抚养"),
                  ("执行异议与复议", "执行异议之诉", "执行异议之诉"),
                  ("审判监督程序（再审程序）", "再审申请审查", "再审申请与审查")]
        articles = [(root_name, title, self._article(title=title + suffix, content=title + suffix + "专题讨论"))
                    for root_name, title, topic in topics for suffix in ("甲", "乙")]
        with main.get_db() as conn:
            for root_name, title, article_id in articles:
                main.domain_taxonomy_module.ensure_roots(conn, [root_name])
                conn.execute("UPDATE articles SET domains=?,summary=? WHERE id=?",
                             (json.dumps([root_name]), title, article_id))
            conn.commit()
            before = list(conn.execute("SELECT domains,manual_domains,excluded_auto_domains FROM articles"))
            main.domain_taxonomy_module.backfill_child_topic_coverage(conn)
            main.domain_taxonomy_module.backfill_child_topic_coverage(conn)
            after = list(conn.execute("SELECT domains,manual_domains,excluded_auto_domains FROM articles"))
            self.assertEqual([tuple(row) for row in before], [tuple(row) for row in after])
            conn.commit()
        suggestions = self.client.get("/api/domains/suggestions").json()
        for root_name, title, topic in topics:
            with self.subTest(root=root_name):
                item = next(row for row in suggestions if row["parent_name"] == root_name and row["name"] == topic)
                self.assertEqual(item["support_count"], 2)
                root = next(row for row in self.client.get("/api/domains").json() if row["domain"] == root_name)
                self.assertEqual(root["children"], [])

    def test_one_matching_domain_does_not_skip_another_domain_ai(self):
        article_id = self._article(title="工程款与特殊刑事程序", content="建设工程工程款与刑事法律程序的交叉分析。")
        roots = self.client.get("/api/domains").json()
        criminal = next(row for row in roots if row["domain"] == "刑事法律")
        construction = next(row for row in roots if row["domain"] == "建设工程")
        child = self.client.post("/api/domains/categories", json={"name": "工程价款", "parent_id": construction["id"],
                                                                  "keywords": ["工程款"]}).json()
        criminal_child = self.client.post("/api/domains/categories", json={"name": "刑事程序专题", "parent_id": criminal["id"],
                                                                           "keywords": ["刑事程序专题"]}).json()
        async def ai(*args, **kwargs):
            return {"choices": [{"message": {"content": json.dumps({"domains": ["刑事法律"],
                         "subcategories": [criminal_child["id"]]})}, "finish_reason": "stop"}]}, "test"
        with patch.object(main, "classify_domains", return_value=["建设工程", "刑事法律"]), \
             patch.object(main, "_call_ai_with_fallback", side_effect=ai) as called:
            asyncio.run(main._classify_queued_article(article_id))
        self.assertEqual(called.call_count, 1)
        detail = self.client.get(f"/api/articles/{article_id}").json()
        self.assertEqual(set(detail["domains"]), {"建设工程", "刑事法律"})
        self.assertEqual(set(detail["subcategory_ids"]), {child["id"], criminal_child["id"]})

    def test_accepted_historical_root_child_matches_automatically(self):
        with main.get_db() as conn:
            main.domain_taxonomy_module.ensure_roots(conn, ["民事诉讼法"])
            conn.commit()
        root = next(row for row in self.client.get("/api/domains").json() if row["domain"] == "民事诉讼法")
        child = self.client.post("/api/domains/categories", json={"name": "证据与证明", "parent_id": root["id"],
                                                                  "keywords": ["举证责任"]}).json()
        article_id = self._article(title="民事案件举证责任分配", content="举证责任分配的证据规则。")
        asyncio.run(main._classify_queued_article(article_id))
        detail = self.client.get(f"/api/articles/{article_id}").json()
        self.assertIn("民事诉讼法", detail["domains"])
        self.assertIn(child["id"], detail["subcategory_ids"])

    def test_sidebar_count_matches_exact_parent_and_child_filter(self):
        root = self.client.post("/api/domains/categories", json={"name": "专题_%", "keywords": []}).json()
        child = self.client.post("/api/domains/categories", json={"name": "专题主题", "parent_id": root["id"]}).json()
        ids = [self._article(title="匿名计数案例" + str(i), content="独立样本内容" + str(i)) for i in range(4)]
        with main.get_db() as conn:
            # Escaped Unicode JSON and SQL wildcard characters are legitimate domain names.
            for i, domains in enumerate(([root["name"], root["name"]], ["专题_甲"], [], [root["name"]])):
                conn.execute("UPDATE articles SET domains=? WHERE id=?", (json.dumps(domains), ids[i]))
                conn.execute("INSERT INTO article_subcategory_choices VALUES (?,?,?)",
                             (ids[i], child["id"], "excluded" if i == 3 else "manual"))
            conn.commit()
        domain = next(row for row in self.client.get("/api/domains").json() if row["id"] == root["id"])
        self.assertEqual(domain["count"], 2)
        self.assertEqual(domain["children"][0]["count"], 1)
        parent_list = self.client.get("/api/articles", params={"domain": root["name"]}).json()
        child_list = self.client.get("/api/articles", params={"domain": root["name"], "subcategory_id": child["id"]}).json()
        self.assertEqual(parent_list["total"], domain["count"])
        self.assertEqual(child_list["total"], domain["children"][0]["count"])
        self.assertEqual([article["id"] for article in child_list["articles"]], [ids[0]])


if __name__ == "__main__":
    unittest.main()
