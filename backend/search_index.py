"""SQLite FTS5 helpers for article search.

All helpers are defensive: if FTS5 is unavailable or the virtual table is
temporarily inconsistent, callers can fall back to the legacy LIKE queries.
"""

import re
import sqlite3
from typing import List, Optional


FTS_TABLE = "articles_fts"


def ensure_articles_fts(conn: sqlite3.Connection) -> bool:
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (FTS_TABLE,),
        ).fetchone()
        needs_rebuild = row is None
        if row and "tokenize='trigram'" not in (row[0] or ""):
            conn.executescript(
                f"""
                DROP TRIGGER IF EXISTS articles_fts_ai;
                DROP TRIGGER IF EXISTS articles_fts_ad;
                DROP TRIGGER IF EXISTS articles_fts_au;
                DROP TABLE IF EXISTS {FTS_TABLE};
                """
            )
            needs_rebuild = True
        conn.executescript(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE}
            USING fts5(
                title,
                summary,
                content,
                tags,
                domains,
                content='articles',
                content_rowid='id',
                tokenize='trigram'
            );

            CREATE TRIGGER IF NOT EXISTS articles_fts_ai AFTER INSERT ON articles BEGIN
                INSERT INTO {FTS_TABLE}(rowid, title, summary, content, tags, domains)
                VALUES (new.id, new.title, new.summary, new.content, new.tags, new.domains);
            END;

            CREATE TRIGGER IF NOT EXISTS articles_fts_ad AFTER DELETE ON articles BEGIN
                INSERT INTO {FTS_TABLE}({FTS_TABLE}, rowid, title, summary, content, tags, domains)
                VALUES ('delete', old.id, old.title, old.summary, old.content, old.tags, old.domains);
            END;

            CREATE TRIGGER IF NOT EXISTS articles_fts_au AFTER UPDATE ON articles BEGIN
                INSERT INTO {FTS_TABLE}({FTS_TABLE}, rowid, title, summary, content, tags, domains)
                VALUES ('delete', old.id, old.title, old.summary, old.content, old.tags, old.domains);
                INSERT INTO {FTS_TABLE}(rowid, title, summary, content, tags, domains)
                VALUES (new.id, new.title, new.summary, new.content, new.tags, new.domains);
            END;
            """
        )
        article_count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        fts_count = conn.execute(f"SELECT COUNT(*) FROM {FTS_TABLE}").fetchone()[0]
        if needs_rebuild or article_count != fts_count:
            conn.execute(f"INSERT INTO {FTS_TABLE}({FTS_TABLE}) VALUES ('rebuild')")
        return True
    except sqlite3.Error as exc:
        print(f"[FTS] 初始化失败，继续使用 LIKE 搜索: {exc}")
        return False


def _escape_token(token: str) -> str:
    return token.replace('"', '""')


def build_fts_query(query: str) -> str:
    query = (query or "").strip()
    if not query:
        return ""
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", query, flags=re.UNICODE)
    candidates = []
    compact = "".join(tokens)
    if compact and compact != query:
        candidates.append(compact)
    if query:
        candidates.append(query)
    candidates.extend(tokens)

    seen = set()
    parts = []
    for token in candidates:
        token = token.strip()
        if len(token) < 2 or token in seen:
            continue
        seen.add(token)
        parts.append(f'"{_escape_token(token)}"')
    return " OR ".join(parts)


def search_article_ids(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 1000,
    columns: Optional[List[str]] = None,
) -> List[int]:
    fts_query = build_fts_query(query)
    if not fts_query:
        return []
    allowed_columns = {"title", "summary", "content", "tags", "domains"}
    scoped_columns = [column for column in (columns or []) if column in allowed_columns]
    if scoped_columns:
        fts_query = "{" + " ".join(scoped_columns) + "} : (" + fts_query + ")"
    try:
        rows = conn.execute(
            f"""
            SELECT rowid
            FROM {FTS_TABLE}
            WHERE {FTS_TABLE} MATCH ?
            ORDER BY bm25({FTS_TABLE}, 8.0, 3.0, 1.0, 1.5, 1.5)
            LIMIT ?
            """,
            (fts_query, limit),
        ).fetchall()
        return [int(row[0]) for row in rows]
    except sqlite3.Error as exc:
        print(f"[FTS] 查询失败，回退 LIKE: {exc}")
        return []


def case_order_expression(ids: List[int], column: str = "articles.id") -> str:
    clean_ids = [int(i) for i in ids if str(i).isdigit()]
    if not clean_ids:
        return ""
    clauses = " ".join(f"WHEN {article_id} THEN {idx}" for idx, article_id in enumerate(clean_ids))
    return f"CASE {column} {clauses} ELSE {len(clean_ids)} END"
