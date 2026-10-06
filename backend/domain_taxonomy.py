"""Two-level article taxonomy and non-destructive classification state."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import sqlite3
from typing import Any, Iterable


def _now() -> str:
    return dt.datetime.now().isoformat()


def _items(raw: Any) -> list[str]:
    try:
        values = json.loads(raw or "[]") if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        values = []
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip())) if isinstance(values, list) else []


def _json(values: Iterable[str]) -> str:
    return json.dumps(list(values), ensure_ascii=False)


def is_source_label(name: str) -> bool:
    """Only unmistakable web addresses are omitted from the topic hierarchy."""
    value = name.strip().lower()
    return bool(re.match(r"^(?:https?://|www\.)\S+|^[\w.-]+\.[a-z]{2,}(?:/\S*)?$", value))


def ensure_article_triggers(conn: sqlite3.Connection) -> None:
    """Cover imports which write articles directly instead of using save_article."""
    conn.executescript("""
        CREATE TRIGGER IF NOT EXISTS article_domain_queue_insert AFTER INSERT ON articles
        BEGIN
            INSERT OR REPLACE INTO domain_classification_jobs(article_id,status,updated_at)
            VALUES (new.id,'queued',datetime('now'));
        END;
        CREATE TRIGGER IF NOT EXISTS article_domain_queue_edit
        AFTER UPDATE OF title,content ON articles
        BEGIN
            INSERT OR REPLACE INTO domain_classification_jobs(article_id,status,updated_at)
            VALUES (new.id,'queued',datetime('now'));
        END;
    """)


def ensure_roots(conn: sqlite3.Connection, predefined: Iterable[str]) -> None:
    names = list(predefined)
    suppressed = {row[0] for row in conn.execute("SELECT name FROM domain_taxonomy_suppressed_roots")}
    for row in conn.execute("SELECT domains FROM articles"):
        names.extend(_items(row[0]))
    for name in dict.fromkeys(names):
        if name != "综合法律" and name not in suppressed and not is_source_label(name):
            conn.execute(
                "INSERT OR IGNORE INTO domain_taxonomy(name,parent_id,created_at) VALUES (?,NULL,?)",
                (name, _now()),
            )


def taxonomy(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    roots = [dict(row) for row in conn.execute(
        "SELECT id,name,keywords_json FROM domain_taxonomy WHERE parent_id IS NULL ORDER BY id"
    )]
    children = [dict(row) for row in conn.execute(
        "SELECT id,name,parent_id,keywords_json FROM domain_taxonomy WHERE parent_id IS NOT NULL ORDER BY id"
    )]
    for root in roots:
        root["children"] = [child for child in children if child["parent_id"] == root["id"]]
    return roots


def category_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    roots = taxonomy(conn)
    counts: dict[str, int] = {}
    for row in conn.execute("SELECT domains FROM articles"):
        for name in _items(row[0]):
            if not is_source_label(name):
                counts[name] = counts.get(name, 0) + 1
    child_counts = {row[0]: row[1] for row in conn.execute("""
        SELECT subcategory_id, COUNT(*) FROM article_subcategory_choices
        WHERE mode <> 'excluded' GROUP BY subcategory_id
    """)}
    for root in roots:
        root["domain"] = root["name"]
        root["count"] = counts.get(root["name"], 0)
        for child in root["children"]:
            child["count"] = child_counts.get(child["id"], 0)
    roots.sort(key=lambda row: (-row["count"], row["name"]))
    return roots


def _keywords_match(text: str, keywords: list[str], name: str) -> bool:
    terms = [term for term in keywords if len(term) >= 2] or [name]
    return bool(text and any(term in text for term in terms))


def classified_children(conn: sqlite3.Connection, article_id: int, text: str, roots: list[str]) -> list[int]:
    matches: list[int] = []
    for root in taxonomy(conn):
        if root["name"] not in roots:
            continue
        for child in root["children"]:
            if _keywords_match(text, _items(child["keywords_json"]), child["name"]):
                matches.append(child["id"])
    return matches


def apply_classification(
    conn: sqlite3.Connection, article_id: int, auto_roots: list[str], auto_children: list[int],
    *, status: str = "done", expected_hash: str | None = None,
) -> bool:
    article = conn.execute(
        "SELECT title,content,domains,manual_domains,excluded_auto_domains FROM articles WHERE id=?",
        (article_id,),
    ).fetchone()
    if article is None:
        return False
    fingerprint = hashlib.sha256(((article["title"] or "") + (article["content"] or "")).encode()).hexdigest()
    if expected_hash and fingerprint != expected_hash:
        return False
    conn.execute(
        "INSERT OR IGNORE INTO domain_classification_jobs(article_id,status,updated_at) VALUES (?,'queued',?)",
        (article_id, _now()),
    )
    manual = _items(article["manual_domains"])
    excluded = set(_items(article["excluded_auto_domains"]))
    roots = list(dict.fromkeys(
        [name for name in auto_roots if name not in excluded and name != "综合法律" and not is_source_label(name)]
        + [name for name in manual if not is_source_label(name)]
    ))
    choices = {row["subcategory_id"]: row["mode"] for row in conn.execute(
        "SELECT subcategory_id,mode FROM article_subcategory_choices WHERE article_id=?", (article_id,)
    )}
    child_parents = {row["id"]: row["parent_name"] for row in conn.execute("""
        SELECT child.id,root.name AS parent_name FROM domain_taxonomy child
        JOIN domain_taxonomy root ON root.id=child.parent_id WHERE child.parent_id IS NOT NULL
    """)}
    for child_id, mode in choices.items():
        if mode == "manual" and child_parents.get(child_id) not in roots and child_parents.get(child_id) not in excluded:
            roots.append(child_parents[child_id])
    conn.execute("DELETE FROM article_subcategory_choices WHERE article_id=? AND mode='auto'", (article_id,))
    for child_id in set(auto_children):
        if child_parents.get(child_id) in roots and choices.get(child_id) not in {"manual", "excluded"}:
            conn.execute(
                "INSERT INTO article_subcategory_choices(article_id,subcategory_id,mode) VALUES (?,?,'auto')",
                (article_id, child_id),
            )
    conn.execute(
        "UPDATE articles SET domains=?,manual_domains=? WHERE id=?",
        (_json(roots), _json(manual), article_id),
    )
    conn.execute(
        "UPDATE domain_classification_jobs SET status=?,content_hash=?,auto_domains_json=?,updated_at=?,error='' WHERE article_id=?",
        (status, fingerprint, _json(auto_roots), _now(), article_id),
    )
    return True


def suggest(conn: sqlite3.Connection, name: str, parent_id: int | None, article_id: int, keywords: list[str]) -> int | None:
    name = re.sub(r"\s+", "", str(name or ""))[:40]
    if len(name) < 2 or is_source_label(name) or any(token in name for token in ("来源", "网址", "其他", "综合")):
        return None
    siblings = conn.execute("SELECT name FROM domain_taxonomy WHERE parent_id IS ?", (parent_id,)).fetchall()
    proposals = conn.execute(
        "SELECT name FROM domain_suggestions WHERE parent_id IS ? AND status='pending'", (parent_id,)
    ).fetchall()
    def comparable(value: str) -> str:
        return re.sub(r"(法|法律|纠纷|争议)$", "", value.strip())
    normalized = comparable(name)
    if any(comparable(row[0]) == normalized for row in [*siblings, *proposals]):
        return None
    cur = conn.execute(
        "INSERT INTO domain_suggestions(name,parent_id,keywords_json,article_id,created_at) VALUES (?,?,?,?,?)",
        (name, parent_id, _json(keywords[:8]), article_id, _now()),
    )
    return cur.lastrowid


def update_job_domain_names(conn: sqlite3.Connection, renames: dict[str, str], deletes: set[str]) -> None:
    for row in conn.execute("SELECT article_id,auto_domains_json FROM domain_classification_jobs"):
        values = _items(row["auto_domains_json"])
        updated = list(dict.fromkeys(renames.get(name, name) for name in values if name not in deletes))
        if updated != values:
            conn.execute("UPDATE domain_classification_jobs SET auto_domains_json=? WHERE article_id=?",
                         (_json(updated), row["article_id"]))
