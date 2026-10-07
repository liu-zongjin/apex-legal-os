import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend import main


class TagManagementApiTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.old_db_path = main.DB_PATH
        main.DB_PATH = Path(self.tempdir.name) / "test.db"
        main.init_db()
        self.client = TestClient(main.app)
        self.article_counter = 0
        with main.get_db() as conn:
            category = conn.execute(
                "SELECT id FROM tag_categories ORDER BY sort_order, id LIMIT 1"
            ).fetchone()
            if category is None:
                self.category_id = conn.execute(
                    """INSERT INTO tag_categories(name, sort_order, created_at)
                       VALUES ('测试默认目录', 0, '2026-01-01T00:00:00')"""
                ).lastrowid
                conn.commit()
            else:
                self.category_id = category[0]

    def tearDown(self):
        main.DB_PATH = self.old_db_path
        self.tempdir.cleanup()

    def test_reorder_rejects_duplicate_stale_and_other_parent_ids_atomically(self):
        first = self._insert_tag("第一个标签")
        second = self._insert_tag("第二个标签")
        self._insert_tag("https://example.org/source")  # hidden source label is outside the visible collection
        other_cat = self.client.post("/api/tag-categories", json={"name": "其他集合"}).json()["id"]
        other = self.client.post("/api/tag-groups", json={"name": "其他集合标签", "category_id": other_cat}).json()["id"]
        with main.get_db() as conn:
            before = list(conn.execute("SELECT id,sort_order FROM tag_groups ORDER BY id"))
            category_ids = [row[0] for row in conn.execute("SELECT id FROM tag_categories")]
        for ids in ([first, first], [second, 999999], [first, other], [first]):
            response = self.client.post("/api/tag-groups/reorder", json={"category_id": self.category_id, "ids": ids})
            self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.client.post("/api/tag-categories/reorder", json={"ids": category_ids[:-1]}).status_code, 409)
        with main.get_db() as conn:
            after = list(conn.execute("SELECT id,sort_order FROM tag_groups ORDER BY id"))
        self.assertEqual([tuple(row) for row in before], [tuple(row) for row in after])
        self.assertEqual(self.client.post("/api/tag-groups/reorder", json={"category_id": self.category_id, "ids": [second, first]}).status_code, 200)

    def _insert_article(self, domains, tags):
        self.article_counter += 1
        with main.get_db() as conn:
            article_id = conn.execute(
                """INSERT INTO articles
                   (title, content, summary, domains, source_type, source_hash, created_at, tags)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "标签管理测试文章", "正文", "摘要", json.dumps(domains, ensure_ascii=False),
                    "file", f"tag-test-{self.article_counter}", "2026-01-01T00:00:00",
                    json.dumps(tags, ensure_ascii=False),
                ),
            ).lastrowid
            conn.commit()
        return article_id

    def _insert_tag(self, name):
        with main.get_db() as conn:
            tag_id = conn.execute(
                """INSERT INTO tag_groups(name, category_id, sort_order, created_at)
                   VALUES (?, ?, 99, '2026-01-01T00:00:00')""",
                (name, self.category_id),
            ).lastrowid
            conn.commit()
        return tag_id

    def test_category_count_is_distinct_articles_and_facet_counts_deduplicate(self):
        self._insert_tag("分类标签一")
        self._insert_tag("分类标签二")
        self._insert_article(
            ["测试领域", "测试领域"],
            ["作者:测试作者", "作者:测试作者", "分类标签一", "分类标签二"],
        )

        categories = self.client.get("/api/tag-categories").json()
        category = next(item for item in categories if item["id"] == self.category_id)
        self.assertEqual(category["count"], 1)

        domains = next(item for item in self.client.get("/api/domains").json() if item["domain"] == "测试领域")
        authors = next(item for item in self.client.get("/api/authors").json() if item["author"] == "测试作者")
        self.assertEqual(domains["count"], 1)
        self.assertEqual(authors["count"], 1)
        flat_tag = next(item for item in self.client.get("/api/tag-groups").json() if item["name"] == "分类标签一")
        custom_tag = next(item for item in self.client.get("/api/tags/custom").json() if item["tag"] == "分类标签一")
        self.assertEqual(flat_tag["count"], 1)
        self.assertEqual(custom_tag["count"], 1)

    def test_purged_tag_stays_out_of_auto_discovered_library(self):
        tag_id = self._insert_tag("仅文章保留标签")
        self._insert_article([], ["仅文章保留标签"])

        response = self.client.delete(f"/api/tag-groups/{tag_id}/purge")
        self.assertEqual(response.status_code, 200, response.text)
        categories = self.client.get("/api/tag-categories").json()
        names = {tag["name"] for category in categories for tag in category["tags"]}
        self.assertNotIn("仅文章保留标签", names)

    def test_tag_name_conflicts_return_client_errors(self):
        first_category = self.client.post("/api/tag-categories", json={"name": "测试目录一"}).json()
        second_category = self.client.post("/api/tag-categories", json={"name": "测试目录二"}).json()
        created = self.client.post(
            "/api/tag-groups", json={"name": "全局唯一标签", "category_id": first_category["id"]}
        )
        self.assertEqual(created.status_code, 200, created.text)

        duplicate = self.client.post(
            "/api/tag-groups", json={"name": "全局唯一标签", "category_id": second_category["id"]}
        )
        self.assertEqual(duplicate.status_code, 409, duplicate.text)

        other = self.client.post(
            "/api/tag-groups", json={"name": "其他标签", "category_id": second_category["id"]}
        )
        self.assertEqual(other.status_code, 200, other.text)
        conflict = self.client.put(
            f"/api/tag-groups/{other.json()['id']}/rename", json={"name": "全局唯一标签"}
        )
        self.assertEqual(conflict.status_code, 409, conflict.text)

    def test_tag_editor_save_renames_author_and_related_tags(self):
        tag_id = self._insert_tag("原标签")
        self._insert_article(["原领域"], ["作者:旧作者", "原标签"])
        payload = {
            "categories": [{
                "id": self.category_id,
                "name": "测试默认目录",
                "tags": [{"id": tag_id, "name": "新标签"}],
            }],
            "facets": {
                "domain": {
                    "rows": [{"original": "原领域", "name": "新领域"}],
                    "deletes": [],
                    "order": ["新领域"],
                },
                "author": {
                    "rows": [{"original": "旧作者", "name": "新作者"}],
                    "deletes": [],
                    "order": ["新作者"],
                },
            },
        }

        response = self.client.post("/api/tag-editor/save", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        with main.get_db() as conn:
            article = conn.execute("SELECT domains, tags FROM articles").fetchone()
            self.assertEqual(json.loads(article["domains"]), ["新领域"])
            self.assertEqual(json.loads(article["tags"]), ["作者:新作者", "新标签"])
            self.assertEqual(
                conn.execute("SELECT name FROM tag_groups WHERE id = ?", (tag_id,)).fetchone()[0],
                "新标签",
            )

    def test_tag_editor_save_validates_before_mutating(self):
        tag_id = self._insert_tag("不可变标签")
        self._insert_article([], ["作者:原作者"])
        self._insert_article([], ["作者:目标作者"])
        payload = {
            "categories": [{
                "id": self.category_id,
                "name": "已提交前不应改变",
                "tags": [{"id": tag_id, "name": "也不应改变"}],
            }],
            "facets": {
                "domain": {"rows": [], "deletes": [], "order": []},
                "author": {
                    "rows": [
                        {"original": "原作者", "name": "目标作者"},
                        {"original": "目标作者", "name": "目标作者"},
                    ],
                    "deletes": [],
                    "order": ["目标作者", "目标作者"],
                },
            },
        }

        response = self.client.post("/api/tag-editor/save", json=payload)
        self.assertEqual(response.status_code, 409, response.text)
        with main.get_db() as conn:
            self.assertEqual(
                conn.execute("SELECT name FROM tag_categories WHERE id = ?", (self.category_id,)).fetchone()[0],
                "测试默认目录",
            )
            self.assertEqual(
                conn.execute("SELECT name FROM tag_groups WHERE id = ?", (tag_id,)).fetchone()[0],
                "不可变标签",
            )


if __name__ == "__main__":
    unittest.main()
