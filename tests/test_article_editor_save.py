import sqlite3
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import main


def test_editor_save_is_atomic_and_detects_stale_content(tmp_path):
    database = tmp_path / "editor.db"

    def connection():
        conn = sqlite3.connect(database, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    with connection() as conn:
        conn.executescript("""
            CREATE TABLE articles(id INTEGER PRIMARY KEY,title TEXT,content TEXT,summary TEXT,domains TEXT);
            CREATE TABLE app_preferences(preference_key TEXT PRIMARY KEY,value_json TEXT,updated_at TEXT);
            CREATE TABLE knowledge_claim_evidence(article_id INTEGER);
            INSERT INTO articles VALUES(1,'旧标题','<p>旧正文</p>','','[]');
        """)

    margins = {"top": 2.2, "bottom": 2.8, "left": 2.6, "right": 3.1}
    with patch.object(main, "get_db", connection), \
         patch.object(main, "mark_article_claims_needs_review", return_value=[]), \
         patch.object(main, "rebuild_article_paragraphs") as rebuild, \
         patch.object(main, "is_knowledge_article", return_value=False):
        client = TestClient(main.app)
        payload = {"title": "新标题", "content": "<p>新正文</p>",
                   "base_content": "<p>旧正文</p>", "base_title": "旧标题", "margins": margins}
        response = client.put("/api/articles/1/editor", json=payload)
        assert response.status_code == 200
        assert client.get("/api/articles/1/editor-layout").json()["margins"] == margins
        stale = client.put("/api/articles/1/editor", json={**payload, "title": "误覆盖"})
        assert stale.status_code == 409
        rebuild.side_effect = RuntimeError("索引更新失败")
        failed = TestClient(main.app, raise_server_exceptions=False).put(
            "/api/articles/1/editor", json={**payload, "title": "不能部分保存",
                                            "content": "<p>再次修改</p>",
                                            "base_title": "新标题", "base_content": "<p>新正文</p>"})
        assert failed.status_code == 500

    with connection() as conn:
        article = conn.execute("SELECT title,content FROM articles WHERE id=1").fetchone()
        assert tuple(article) == ("新标题", "<p>新正文</p>")
