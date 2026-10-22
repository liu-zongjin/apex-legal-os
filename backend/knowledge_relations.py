"""Native bidirectional links for the legal knowledge base.

The module is intentionally provider-free.  It discovers deterministic
mentions, reuses already extracted legal claims, and enforces the long-article
AI guard independently from the UI.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import math
import re
import sqlite3
from typing import Any, Iterable

from .legal_knowledge import article_processing_text, content_hash as knowledge_content_hash


LONG_ARTICLE_CHARS = 200_000
AI_BATCH_CHARS = 18_000
NODE_TYPES = {"statute_provision", "issue", "case"}
MENTION_STATUSES = {"candidate", "confirmed", "rejected", "stale"}
RELATION_TYPES = {
    "cites", "applies", "discusses", "supports", "opposes",
    "limits", "distinguishes", "related_to",
}

_RELATION_LABELS = {
    "cites": "引用",
    "applies": "适用",
    "discusses": "讨论",
    "supports": "支持",
    "opposes": "反对",
    "limits": "限制",
    "distinguishes": "区别",
    "related_to": "一般相关",
}
_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}
_CASE_TITLE_RE = re.compile(r"(?:案例|裁判|判决|纠纷|案$|案——|案—|案号|人民法院案例库)")
_BRACKETED_PROVISION_RE = re.compile(
    r"《(?P<law>[^》\n]{2,100})》\s*第(?P<number>[0-9〇零一二两三四五六七八九十百千万]+)条"
)
_CONTINUED_PROVISION_RE = re.compile(
    r"\s*(?:、|以及|及|和|与|或|至|到|/|／)\s*"
    r"(?P<article>第?\s*(?P<number>[0-9〇零一二两三四五六七八九十百千万]+)\s*条)"
)


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _normalize(text: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", (text or "").casefold())


def _json(value: Any, default: Any) -> Any:
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def chinese_number(value: str) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    total = section = number = 0
    for char in value:
        if char in _CN_DIGITS:
            number = _CN_DIGITS[char]
        elif char in _CN_UNITS:
            unit = _CN_UNITS[char]
            if unit == 10000:
                section = (section + number) * unit
                total += section
                section = number = 0
            else:
                section += (number or 1) * unit
                number = 0
        else:
            return None
    return total + section + number


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS knowledge_nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node_type TEXT NOT NULL,
            canonical_key TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            normalized_title TEXT NOT NULL,
            article_id INTEGER,
            issue_id INTEGER,
            paragraph_index INTEGER,
            provision_number INTEGER,
            source_status TEXT NOT NULL DEFAULT 'available',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_type_title
            ON knowledge_nodes(node_type, normalized_title);
        CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_article
            ON knowledge_nodes(article_id, paragraph_index);

        CREATE TABLE IF NOT EXISTS knowledge_node_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id INTEGER NOT NULL,
            alias TEXT NOT NULL,
            normalized_alias TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(node_id, normalized_alias),
            FOREIGN KEY(node_id) REFERENCES knowledge_nodes(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_alias_normalized
            ON knowledge_node_aliases(normalized_alias);

        CREATE TABLE IF NOT EXISTS knowledge_mentions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_article_id INTEGER NOT NULL,
            source_kind TEXT NOT NULL,
            source_ref_id INTEGER NOT NULL DEFAULT 0,
            paragraph_index INTEGER,
            char_start INTEGER NOT NULL DEFAULT 0,
            char_end INTEGER NOT NULL DEFAULT 0,
            mention_text TEXT NOT NULL,
            context_text TEXT NOT NULL DEFAULT '',
            target_node_id INTEGER NOT NULL,
            relation_type TEXT NOT NULL DEFAULT 'related_to',
            status TEXT NOT NULL DEFAULT 'candidate',
            detection_method TEXT NOT NULL DEFAULT 'rule',
            confidence REAL NOT NULL DEFAULT 0,
            content_hash TEXT NOT NULL,
            reviewed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(source_article_id, source_kind, source_ref_id, char_start,
                   char_end, target_node_id, content_hash),
            FOREIGN KEY(target_node_id) REFERENCES knowledge_nodes(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_mentions_source
            ON knowledge_mentions(source_article_id, status, source_kind);
        CREATE INDEX IF NOT EXISTS idx_knowledge_mentions_target
            ON knowledge_mentions(target_node_id, status, updated_at DESC);

        CREATE TABLE IF NOT EXISTS article_relation_state (
            article_id INTEGER PRIMARY KEY,
            first_opened_at TEXT,
            last_opened_at TEXT,
            last_rule_scan_hash TEXT DEFAULT '',
            ai_prompted_hash TEXT DEFAULT '',
            ai_authorized_hash TEXT DEFAULT '',
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS relation_backfill_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT NOT NULL DEFAULT 'queued',
            cursor_article_id INTEGER NOT NULL DEFAULT 0,
            total_articles INTEGER NOT NULL DEFAULT 0,
            processed_articles INTEGER NOT NULL DEFAULT 0,
            ai_jobs_created INTEGER NOT NULL DEFAULT 0,
            error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_relation_backfill_status
            ON relation_backfill_jobs(status, id DESC);
        """
    )
    state_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(article_relation_state)").fetchall()
    }
    if "ai_authorized_hash" not in state_columns:
        conn.execute(
            "ALTER TABLE article_relation_state ADD COLUMN ai_authorized_hash TEXT DEFAULT ''"
        )


def relation_labels() -> dict[str, str]:
    return dict(_RELATION_LABELS)


def _upsert_node(
    conn: sqlite3.Connection,
    node_type: str,
    canonical_key: str,
    title: str,
    *,
    article_id: int | None = None,
    issue_id: int | None = None,
    paragraph_index: int | None = None,
    provision_number: int | None = None,
    source_status: str = "available",
    metadata: dict[str, Any] | None = None,
) -> int:
    if node_type not in NODE_TYPES:
        raise ValueError(f"unsupported node type: {node_type}")
    stamp = _now()
    conn.execute(
        """INSERT INTO knowledge_nodes
           (node_type,canonical_key,title,normalized_title,article_id,issue_id,
            paragraph_index,provision_number,source_status,metadata_json,created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(canonical_key) DO UPDATE SET
             title=excluded.title,
             normalized_title=excluded.normalized_title,
             article_id=COALESCE(excluded.article_id,knowledge_nodes.article_id),
             issue_id=COALESCE(excluded.issue_id,knowledge_nodes.issue_id),
             paragraph_index=COALESCE(excluded.paragraph_index,knowledge_nodes.paragraph_index),
             provision_number=COALESCE(excluded.provision_number,knowledge_nodes.provision_number),
             source_status=CASE WHEN excluded.source_status='available' THEN 'available'
                                ELSE knowledge_nodes.source_status END,
             metadata_json=excluded.metadata_json,
             updated_at=excluded.updated_at
           WHERE knowledge_nodes.title IS NOT excluded.title
              OR knowledge_nodes.normalized_title IS NOT excluded.normalized_title
              OR (excluded.article_id IS NOT NULL AND knowledge_nodes.article_id IS NOT excluded.article_id)
              OR (excluded.issue_id IS NOT NULL AND knowledge_nodes.issue_id IS NOT excluded.issue_id)
              OR (excluded.paragraph_index IS NOT NULL AND knowledge_nodes.paragraph_index IS NOT excluded.paragraph_index)
              OR (excluded.provision_number IS NOT NULL AND knowledge_nodes.provision_number IS NOT excluded.provision_number)
              OR (excluded.source_status='available' AND knowledge_nodes.source_status<>'available')
              OR knowledge_nodes.metadata_json IS NOT excluded.metadata_json""",
        (
            node_type, canonical_key, title, _normalize(title), article_id, issue_id,
            paragraph_index, provision_number, source_status,
            json.dumps(metadata or {}, ensure_ascii=False), stamp, stamp,
        ),
    )
    return int(conn.execute(
        "SELECT id FROM knowledge_nodes WHERE canonical_key=?", (canonical_key,)
    ).fetchone()[0])


def _add_aliases(conn: sqlite3.Connection, node_id: int, aliases: Iterable[str]) -> None:
    stamp = _now()
    for alias in aliases:
        alias = (alias or "").strip()
        normalized = _normalize(alias)
        if len(normalized) < 2:
            continue
        conn.execute(
            """INSERT OR IGNORE INTO knowledge_node_aliases
               (node_id,alias,normalized_alias,created_at) VALUES (?,?,?,?)""",
            (node_id, alias, normalized, stamp),
        )


def sync_issue_nodes(conn: sqlite3.Connection) -> int:
    ensure_schema(conn)
    try:
        rows = conn.execute(
            "SELECT id,title,domain FROM knowledge_issues WHERE status='active'"
        ).fetchall()
    except sqlite3.OperationalError:
        return 0
    for row in rows:
        title = row["title"]
        node_id = _upsert_node(
            conn, "issue", f"issue:{int(row['id'])}", title,
            issue_id=int(row["id"]), metadata={"domain": row["domain"] or ""},
        )
        _add_aliases(conn, node_id, [title])
    return len(rows)


def _case_articles(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    try:
        return conn.execute(
            """SELECT id,title FROM articles
               WHERE length(title) BETWEEN 6 AND 100 ORDER BY length(title) DESC"""
        ).fetchall()
    except sqlite3.OperationalError:
        return []


def sync_case_nodes(conn: sqlite3.Connection) -> int:
    count = 0
    for row in _case_articles(conn):
        title = row["title"] or ""
        if not _CASE_TITLE_RE.search(title):
            continue
        node_id = _upsert_node(
            conn, "case", f"case:article:{int(row['id'])}", title,
            article_id=int(row["id"]),
        )
        _add_aliases(conn, node_id, [title])
        count += 1
    return count


def _law_alias_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    items_by_article: dict[int, dict[str, Any]] = {}
    try:
        rows = conn.execute(
            """SELECT a.id,a.title,n.official_title
               FROM articles a
               LEFT JOIN national_law_articles n ON n.article_id=a.id"""
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    for row in rows:
        raw_title = (row["title"] or "").strip()
        official = (row["official_title"] or raw_title).strip()
        cleaned_title = re.sub(
            r"(?:[（(][^）)]*(?:修正|修订|施行|公布|版本|现行|失效|废止|20\d{2})[^）)]*[）)])+$",
            "",
            official,
        ).strip()
        cleaned_title = re.sub(r"\.(?:docx?|pdf|txt|html?)$", "", cleaned_title, flags=re.I)

        # Some authoritative laws were imported before national_law_articles
        # metadata existed. Recognise those documents from their legislation-like
        # title plus their own numbered provisions, rather than treating them as
        # absent merely because the auxiliary metadata row is missing.
        if not row["official_title"]:
            looks_like_law = bool(re.search(
                r"(?:法|条例|规定|办法|规则|解释|决定)$", cleaned_title
            ))
            if not looks_like_law:
                continue
            try:
                provision_count = int(conn.execute(
                    """SELECT COUNT(*) FROM article_paragraphs
                       WHERE article_id=? AND
                             (trim(text) LIKE '第%条%' OR trim(heading) LIKE '第%条%')""",
                    (row["id"],),
                ).fetchone()[0])
            except sqlite3.OperationalError:
                provision_count = 0
            if provision_count < 2:
                continue

        official = cleaned_title or official
        aliases = {official, raw_title, cleaned_title}
        for value in list(aliases):
            if value.startswith("中华人民共和国") and len(value) > 9:
                aliases.add(value[7:])
        if "民法典" in official:
            aliases.add("民法典")
        items_by_article[int(row["id"])] = {
            "article_id": int(row["id"]),
            "official": official,
            "aliases": sorted((a for a in aliases if len(a) >= 2), key=len, reverse=True),
        }
    return list(items_by_article.values())


def _reconcile_statute_node(
    conn: sqlite3.Connection, node: sqlite3.Row | dict[str, Any]
) -> sqlite3.Row | dict[str, Any]:
    if node["node_type"] != "statute_provision":
        return node
    if node["source_status"] == "available" and node["article_id"]:
        paragraph = _provision_paragraph(conn, node["article_id"], int(node["provision_number"] or 0))
        if paragraph != node["paragraph_index"]:
            conn.execute("UPDATE knowledge_nodes SET paragraph_index=? WHERE id=?", (paragraph, node["id"]))
            return conn.execute("SELECT * FROM knowledge_nodes WHERE id=?", (node["id"],)).fetchone()
        return node
    metadata = _json(node["metadata_json"] or "{}", {})
    law_title = (metadata.get("law_title") or "").strip()
    if not law_title:
        match = re.match(r"《(.+?)》第", node["title"] or "")
        law_title = match.group(1) if match else ""
    normalized = _normalize(law_title)
    known_law = next(
        (
            law for law in _law_alias_rows(conn)
            if normalized in {_normalize(alias) for alias in law["aliases"]}
        ),
        None,
    )
    if not known_law:
        return node
    paragraph_index = _provision_paragraph(
        conn, known_law["article_id"], int(node["provision_number"] or 0)
    )
    if paragraph_index is None:
        return node
    stamp = _now()
    conn.execute(
        """UPDATE knowledge_nodes
           SET article_id=?,paragraph_index=?,source_status='available',
               metadata_json=?,updated_at=?
           WHERE id=?""",
        (
            known_law["article_id"],
            paragraph_index,
            json.dumps({"law_title": known_law["official"]}, ensure_ascii=False),
            stamp,
            node["id"],
        ),
    )
    _add_aliases(
        conn,
        int(node["id"]),
        [
            f"《{alias}》第{int(node['provision_number'])}条"
            for alias in known_law["aliases"]
        ],
    )
    return conn.execute("SELECT * FROM knowledge_nodes WHERE id=?", (node["id"],)).fetchone()


def _provision_paragraph(
    conn: sqlite3.Connection, article_id: int, number: int
) -> int | None:
    rows = conn.execute(
        """SELECT paragraph_index,text,heading FROM article_paragraphs
           WHERE article_id=? ORDER BY paragraph_index""", (article_id,)
    ).fetchall()
    # Headings are inherited by following paragraphs in the index. They must
    # never hide a paragraph's own article label or turn a citation into a label.
    pattern = r"^\s*第\s*([0-9〇零一二两三四五六七八九十百千万]+)\s*条(?!之)"
    for row in rows:
        match = re.match(pattern, row['text'] or '')
        if match and chinese_number(match.group(1)) == number:
            return int(row["paragraph_index"])
    for row in rows:
        heading = (row['heading'] or '').strip()
        match = re.fullmatch(pattern + r"\s*", heading)
        if match and chinese_number(match.group(1)) == number:
            return int(row["paragraph_index"])
    return None


def _statute_node(
    conn: sqlite3.Connection, law_title: str, number: int,
    known_law: dict[str, Any] | None = None,
) -> int:
    canonical_law = (known_law or {}).get("official") or law_title.strip("《》 ")
    article_id = (known_law or {}).get("article_id")
    paragraph_index = _provision_paragraph(conn, article_id, number) if article_id else None
    key = f"statute:{_normalize(canonical_law)}:{number}"
    title = f"《{canonical_law}》第{number}条"
    node_id = _upsert_node(
        conn, "statute_provision", key, title, article_id=article_id,
        paragraph_index=paragraph_index, provision_number=number,
        source_status="available" if article_id else "missing_source",
        metadata={"law_title": canonical_law},
    )
    aliases = [title, f"{canonical_law}第{number}条"]
    for alias in (known_law or {}).get("aliases", []):
        aliases.extend([f"《{alias}》第{number}条", f"{alias}第{number}条"])
    _add_aliases(conn, node_id, aliases)
    return node_id


def _paragraph_for_offset(conn: sqlite3.Connection, article_id: int, offset: int) -> int | None:
    try:
        row = conn.execute(
            """SELECT paragraph_index FROM article_paragraphs
               WHERE article_id=? AND char_start<=? AND char_end>=?
               ORDER BY paragraph_index LIMIT 1""",
            (article_id, offset, offset),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    return int(row[0]) if row else None


def _relation_from_context(node_type: str, context: str) -> str:
    if re.search(r"区别|不同于|不适用", context):
        return "distinguishes"
    if re.search(r"限制|但书|除外|仅限", context):
        return "limits"
    if re.search(r"反对|否定|不予支持|相反", context):
        return "opposes"
    if re.search(r"支持|证明|表明|认定|裁判认为", context):
        return "supports" if node_type != "statute_provision" else "applies"
    if node_type == "statute_provision":
        return "applies" if re.search(r"依据|依照|适用|根据", context) else "cites"
    if node_type == "issue":
        return "discusses"
    return "related_to"


def _local_context(text: str, start: int, end: int, radius: int = 45) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    prefix = text[left:start]
    suffix = text[end:right]
    boundary = max(prefix.rfind(mark) for mark in "。！？；\n")
    if boundary >= 0:
        prefix = prefix[boundary + 1:]
    suffix_boundaries = [suffix.find(mark) for mark in "。！？；\n" if suffix.find(mark) >= 0]
    if suffix_boundaries:
        suffix = suffix[:min(suffix_boundaries)]
    return f"{prefix}{text[start:end]}{suffix}"


def _store_mention(
    conn: sqlite3.Connection,
    *,
    article_id: int,
    source_kind: str,
    source_ref_id: int,
    paragraph_index: int | None,
    start: int,
    end: int,
    mention_text: str,
    context: str,
    target_node_id: int,
    relation_type: str,
    detection_method: str,
    confidence: float,
    content_hash: str,
) -> bool:
    if relation_type not in RELATION_TYPES:
        relation_type = "related_to"
    stamp = _now()
    before = conn.total_changes
    conn.execute(
        """INSERT OR IGNORE INTO knowledge_mentions
           (source_article_id,source_kind,source_ref_id,paragraph_index,char_start,char_end,
            mention_text,context_text,target_node_id,relation_type,status,detection_method,
            confidence,content_hash,created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,'candidate',?,?,?,?,?)""",
        (
            article_id, source_kind, source_ref_id, paragraph_index, start, end,
            mention_text, context, target_node_id, relation_type, detection_method,
            confidence, content_hash, stamp, stamp,
        ),
    )
    return conn.total_changes > before


def _mark_changed_stale(
    conn: sqlite3.Connection, article_id: int, source_kind: str,
    source_ref_id: int, content_hash: str,
) -> None:
    conn.execute(
        """UPDATE knowledge_mentions SET status='stale',updated_at=?
           WHERE source_article_id=? AND source_kind=? AND source_ref_id=?
             AND content_hash<>? AND status IN ('candidate','confirmed')""",
        (_now(), article_id, source_kind, source_ref_id, content_hash),
    )


def _scan_text(
    conn: sqlite3.Connection,
    *,
    article_id: int,
    source_kind: str,
    source_ref_id: int,
    text: str,
    issue_aliases: list[tuple[str, int]],
    case_aliases: list[tuple[str, int, int]],
    law_rows: list[dict[str, Any]],
) -> int:
    if not text:
        return 0
    source_hash = _hash(text)
    _mark_changed_stale(conn, article_id, source_kind, source_ref_id, source_hash)
    found: set[tuple[int, int, int]] = set()
    created = 0

    law_alias_map: dict[str, dict[str, Any]] = {}
    for law in law_rows:
        for alias in law["aliases"]:
            law_alias_map[alias] = law
    aliases = sorted(law_alias_map, key=len, reverse=True)
    if aliases:
        law_pattern = re.compile(
            rf"(?P<law>{'|'.join(re.escape(a) for a in aliases)})\s*"
            r"第(?P<number>[0-9〇零一二两三四五六七八九十百千万]+)条"
        )
        law_matches = list(law_pattern.finditer(text))
    else:
        law_matches = []
    law_matches.extend(_BRACKETED_PROVISION_RE.finditer(text))
    for match in law_matches:
        number = chinese_number(match.group("number"))
        if not number:
            continue
        law_text = match.group("law")
        known = law_alias_map.get(law_text)
        node_id = _statute_node(conn, law_text, number, known)
        key = (match.start(), match.end(), node_id)
        if key in found:
            continue
        found.add(key)
        context = _local_context(text, match.start(), match.end())
        paragraph = _paragraph_for_offset(conn, article_id, match.start()) if source_kind == "content" else None
        created += _store_mention(
            conn, article_id=article_id, source_kind=source_kind, source_ref_id=source_ref_id,
            paragraph_index=paragraph, start=match.start(), end=match.end(),
            mention_text=match.group(0), context=context, target_node_id=node_id,
            relation_type=_relation_from_context("statute_provision", context),
            detection_method="law_rule", confidence=0.99, content_hash=source_hash,
        )

        # A legal citation commonly states the law only once and then lists
        # several provisions: "民事诉讼法第249条、第250条".  Continue inheriting
        # the same law only across an explicit coordination/range connector.
        # Expressions such as "和本规定第41条" do not match and therefore stop the
        # inheritance before the target statute changes.
        continuation_cursor = match.end()
        while True:
            continued = _CONTINUED_PROVISION_RE.match(text, continuation_cursor)
            if not continued:
                break
            continued_number = chinese_number(continued.group("number"))
            if not continued_number:
                break
            continued_start, continued_end = continued.span("article")
            continued_node_id = _statute_node(
                conn, law_text, continued_number, known
            )
            continued_key = (continued_start, continued_end, continued_node_id)
            if continued_key not in found:
                found.add(continued_key)
                continued_context = _local_context(
                    text, continued_start, continued_end
                )
                continued_paragraph = (
                    _paragraph_for_offset(conn, article_id, continued_start)
                    if source_kind == "content" else None
                )
                created += _store_mention(
                    conn,
                    article_id=article_id,
                    source_kind=source_kind,
                    source_ref_id=source_ref_id,
                    paragraph_index=continued_paragraph,
                    start=continued_start,
                    end=continued_end,
                    mention_text=text[continued_start:continued_end],
                    context=continued_context,
                    target_node_id=continued_node_id,
                    relation_type=_relation_from_context(
                        "statute_provision", continued_context
                    ),
                    detection_method="law_rule_continuation",
                    confidence=0.98,
                    content_hash=source_hash,
                )
            continuation_cursor = continued.end()

    # Exact aliases are intentionally conservative: short generic phrases would
    # flood the review queue and are therefore excluded.
    issue_map = {alias: node_id for alias, node_id in issue_aliases}
    if issue_map:
        issue_pattern = re.compile("|".join(re.escape(alias) for alias in issue_map))
        for match in issue_pattern.finditer(text):
            alias = match.group(0)
            node_id = issue_map[alias]
            start, end = match.span()
            key = (start, end, node_id)
            if key in found:
                continue
            found.add(key)
            context = _local_context(text, start, end)
            paragraph = _paragraph_for_offset(conn, article_id, start) if source_kind == "content" else None
            created += _store_mention(
                conn, article_id=article_id, source_kind=source_kind,
                source_ref_id=source_ref_id, paragraph_index=paragraph,
                start=start, end=end, mention_text=alias, context=context,
                target_node_id=node_id, relation_type=_relation_from_context("issue", context),
                detection_method="issue_alias", confidence=0.9, content_hash=source_hash,
            )

    for alias, node_id, target_article_id in case_aliases:
        if target_article_id == article_id:
            continue
        start = text.find(alias)
        if start < 0:
            continue
        end = start + len(alias)
        context = _local_context(text, start, end)
        paragraph = _paragraph_for_offset(conn, article_id, start) if source_kind == "content" else None
        created += _store_mention(
            conn, article_id=article_id, source_kind=source_kind, source_ref_id=source_ref_id,
            paragraph_index=paragraph, start=start, end=end, mention_text=alias,
            context=context, target_node_id=node_id, relation_type="related_to",
            detection_method="case_title", confidence=0.97, content_hash=source_hash,
        )
    return created


def _alias_inputs(conn: sqlite3.Connection) -> tuple[list[tuple[str, int]], list[tuple[str, int, int]]]:
    issue_rows = conn.execute(
        """SELECT a.alias,a.node_id FROM knowledge_node_aliases a
           JOIN knowledge_nodes n ON n.id=a.node_id
           WHERE n.node_type='issue' AND length(a.alias)>=4
           ORDER BY length(a.alias) DESC LIMIT 5000"""
    ).fetchall()
    case_rows = conn.execute(
        """SELECT a.alias,a.node_id,n.article_id FROM knowledge_node_aliases a
           JOIN knowledge_nodes n ON n.id=a.node_id
           WHERE n.node_type='case' AND length(a.alias)>=6
           ORDER BY length(a.alias) DESC LIMIT 1000"""
    ).fetchall()
    return (
        [(r["alias"], int(r["node_id"])) for r in issue_rows],
        [(r["alias"], int(r["node_id"]), int(r["article_id"] or 0)) for r in case_rows],
    )


def seed_existing_claim_mentions(conn: sqlite3.Connection, article_id: int) -> int:
    """Reuse paid-for extraction results as candidates; never auto-confirm them."""
    try:
        rows = conn.execute(
            """SELECT DISTINCT e.paragraph_index,e.char_start,e.char_end,e.quote,e.stance,
                              i.id AS issue_id,i.title AS issue_title
               FROM knowledge_claim_evidence e
               JOIN knowledge_claims c ON c.id=e.claim_id
               JOIN knowledge_claim_issues ci ON ci.claim_id=c.id
               JOIN knowledge_issues i ON i.id=ci.issue_id
               WHERE e.article_id=? AND e.verified=1
                 AND c.review_status IN ('approved','pending','needs_review')""",
            (article_id,),
        ).fetchall()
        article = conn.execute("SELECT content FROM articles WHERE id=?", (article_id,)).fetchone()
    except sqlite3.OperationalError:
        return 0
    if not article:
        return 0
    content = article["content"] or ""
    source_hash = _hash(content)
    stance_map = {"supports": "supports", "opposes": "opposes", "limits": "limits"}
    created = 0
    for row in rows:
        issue_id = int(row["issue_id"])
        node_id = _upsert_node(
            conn, "issue", f"issue:{issue_id}", row["issue_title"], issue_id=issue_id
        )
        quote = row["quote"] or ""
        start = row["char_start"]
        if start is None or start < 0:
            start = content.find(quote)
        if start < 0:
            start = 0
        end = row["char_end"] if row["char_end"] is not None else start + len(quote)
        created += _store_mention(
            conn, article_id=article_id, source_kind="content", source_ref_id=0,
            paragraph_index=row["paragraph_index"], start=int(start), end=int(end),
            mention_text=quote or row["issue_title"], context=quote,
            target_node_id=node_id, relation_type=stance_map.get(row["stance"], "discusses"),
            detection_method="existing_claim", confidence=0.98, content_hash=source_hash,
        )
    return created


def scan_article_rules(conn: sqlite3.Connection, article_id: int) -> dict[str, Any]:
    ensure_schema(conn)
    try:
        revision = conn.execute("SELECT revision FROM health_revisions WHERE key='relations'").fetchone()[0]
    except sqlite3.OperationalError:
        revision = None
    previous = conn.execute('SELECT last_rule_scan_hash FROM article_relation_state WHERE article_id=?', (article_id,)).fetchone()
    if revision is not None and previous and previous[0] == 'rules-v2:' + str(revision):
        row = conn.execute('SELECT content FROM articles WHERE id=?', (article_id,)).fetchone()
        if row is None:
            raise LookupError('文章不存在')
        return {'article_id': article_id, 'created': 0, 'content_hash': knowledge_content_hash(row[0] or ''), 'cached': True}
    sync_issue_nodes(conn)
    sync_case_nodes(conn)
    article = conn.execute(
        "SELECT id,title,content,summary FROM articles WHERE id=?", (article_id,)
    ).fetchone()
    if not article:
        raise LookupError("文章不存在")
    issue_aliases, case_aliases = _alias_inputs(conn)
    laws = _law_alias_rows(conn)
    created = 0
    processing_text = article_processing_text(article["content"] or "")
    created += _scan_text(
        conn, article_id=article_id, source_kind="content", source_ref_id=0,
        text=processing_text, issue_aliases=issue_aliases,
        case_aliases=case_aliases, law_rows=laws,
    )
    created += _scan_text(
        conn, article_id=article_id, source_kind="summary", source_ref_id=0,
        text=article["summary"] or "", issue_aliases=issue_aliases,
        case_aliases=case_aliases, law_rows=laws,
    )
    try:
        notes = conn.execute(
            "SELECT id,content FROM notes WHERE article_id=? ORDER BY id", (article_id,)
        ).fetchall()
    except sqlite3.OperationalError:
        notes = []
    for note in notes:
        created += _scan_text(
            conn, article_id=article_id, source_kind="note", source_ref_id=int(note["id"]),
            text=note["content"] or "", issue_aliases=issue_aliases,
            case_aliases=case_aliases, law_rows=laws,
        )
    created += seed_existing_claim_mentions(conn, article_id)
    content_hash = knowledge_content_hash(article["content"] or "")
    conn.execute(
        """INSERT INTO article_relation_state(article_id,last_rule_scan_hash,updated_at)
           VALUES (?,?,?) ON CONFLICT(article_id) DO UPDATE SET
           last_rule_scan_hash=excluded.last_rule_scan_hash,updated_at=excluded.updated_at""",
        (article_id, ('rules-v2:' + str(conn.execute("SELECT revision FROM health_revisions WHERE key='relations'").fetchone()[0])) if revision is not None else content_hash, _now()),
    )
    return {"article_id": article_id, "created": created, "content_hash": content_hash, "cached": False}


def scan_estimate(conn: sqlite3.Connection, article_id: int) -> dict[str, Any]:
    ensure_schema(conn)
    row = conn.execute(
        """SELECT a.id,a.content,s.first_opened_at,s.ai_prompted_hash
           FROM articles a LEFT JOIN article_relation_state s ON s.article_id=a.id
           WHERE a.id=?""", (article_id,)
    ).fetchone()
    if not row:
        raise LookupError("文章不存在")
    processing_text = article_processing_text(row["content"] or "")
    chars = len(processing_text)
    content_hash = knowledge_content_hash(row["content"] or "")
    cached = False
    try:
        cached = bool(conn.execute(
            """SELECT 1 FROM knowledge_extraction_jobs
               WHERE article_id=? AND content_hash=? AND status='completed' LIMIT 1""",
            (article_id, content_hash),
        ).fetchone())
    except sqlite3.OperationalError:
        pass
    is_long = chars >= LONG_ARTICLE_CHARS
    return {
        "article_id": article_id,
        "characters": chars,
        "estimated_batches": max(1, math.ceil(chars / AI_BATCH_CHARS)) if chars else 0,
        "long_article": is_long,
        "opened": bool(row["first_opened_at"]),
        "cached_ai": cached,
        "content_hash": content_hash,
        "requires_confirmation": bool(is_long and not cached),
        "prompted_for_current_content": row["ai_prompted_hash"] == content_hash,
    }


def mark_article_opened(conn: sqlite3.Connection, article_id: int) -> dict[str, Any]:
    estimate = scan_estimate(conn, article_id)
    stamp = _now()
    conn.execute(
        """INSERT INTO article_relation_state(article_id,first_opened_at,last_opened_at,updated_at)
           VALUES (?,?,?,?) ON CONFLICT(article_id) DO UPDATE SET
           first_opened_at=COALESCE(article_relation_state.first_opened_at,excluded.first_opened_at),
           last_opened_at=excluded.last_opened_at,updated_at=excluded.updated_at""",
        (article_id, stamp, stamp, stamp),
    )
    estimate["opened"] = True
    estimate["prompt_required"] = bool(
        estimate["long_article"] and not estimate["cached_ai"]
        and not estimate["prompted_for_current_content"]
    )
    return estimate


def mark_ai_prompted(conn: sqlite3.Connection, article_id: int, content_hash: str) -> None:
    conn.execute(
        """INSERT INTO article_relation_state(article_id,ai_prompted_hash,updated_at)
           VALUES (?,?,?) ON CONFLICT(article_id) DO UPDATE SET
           ai_prompted_hash=excluded.ai_prompted_hash,updated_at=excluded.updated_at""",
        (article_id, content_hash, _now()),
    )


def authorize_ai_scan(conn: sqlite3.Connection, article_id: int, content_hash: str) -> None:
    conn.execute(
        """INSERT INTO article_relation_state
           (article_id,ai_prompted_hash,ai_authorized_hash,updated_at)
           VALUES (?,?,?,?) ON CONFLICT(article_id) DO UPDATE SET
           ai_prompted_hash=excluded.ai_prompted_hash,
           ai_authorized_hash=excluded.ai_authorized_hash,
           updated_at=excluded.updated_at""",
        (article_id, content_hash, content_hash, _now()),
    )


def ai_scan_allowed(conn: sqlite3.Connection, article_id: int, confirmed: bool) -> tuple[bool, dict[str, Any]]:
    estimate = scan_estimate(conn, article_id)
    if estimate["cached_ai"]:
        return False, {**estimate, "reason": "cached"}
    if estimate["long_article"] and not (estimate["opened"] and confirmed):
        return False, {**estimate, "reason": "long_article_confirmation_required"}
    return True, {**estimate, "reason": "allowed"}


def article_relations(conn: sqlite3.Connection, article_id: int) -> dict[str, Any]:
    ensure_schema(conn)
    outgoing = conn.execute(
        """SELECT m.*,n.node_type,n.title AS target_title,n.source_status
           FROM knowledge_mentions m JOIN knowledge_nodes n ON n.id=m.target_node_id
           WHERE m.source_article_id=? AND m.status IN ('candidate','confirmed')
           ORDER BY CASE m.status WHEN 'confirmed' THEN 0 ELSE 1 END,m.source_kind,m.char_start""",
        (article_id,),
    ).fetchall()
    node_rows = conn.execute(
        "SELECT id FROM knowledge_nodes WHERE article_id=?", (article_id,)
    ).fetchall()
    node_ids = [int(r[0]) for r in node_rows]
    backlinks: list[dict[str, Any]] = []
    if node_ids:
        placeholders = ",".join("?" for _ in node_ids)
        backlinks = [dict(r) for r in conn.execute(
            f"""SELECT m.*,a.title AS source_title,n.title AS target_title
                FROM knowledge_mentions m
                JOIN articles a ON a.id=m.source_article_id
                JOIN knowledge_nodes n ON n.id=m.target_node_id
                WHERE m.target_node_id IN ({placeholders}) AND m.status='confirmed'
                  AND m.source_article_id<>?
                ORDER BY m.updated_at DESC""",
            (*node_ids, article_id),
        ).fetchall()]
    items = [dict(r) for r in outgoing]
    return {
        "confirmed": [r for r in items if r["status"] == "confirmed"],
        "candidates": [r for r in items if r["status"] == "candidate"],
        "backlinks": backlinks,
        "relation_labels": relation_labels(),
        "estimate": scan_estimate(conn, article_id),
    }


def review_mention(
    conn: sqlite3.Connection, mention_id: int, *,
    status: str, relation_type: str | None = None, target_node_id: int | None = None,
) -> dict[str, Any]:
    if status not in {"confirmed", "rejected"}:
        raise ValueError("审核状态只能是 confirmed 或 rejected")
    row = conn.execute("SELECT * FROM knowledge_mentions WHERE id=?", (mention_id,)).fetchone()
    if not row:
        raise LookupError("候选关系不存在")
    relation_type = relation_type or row["relation_type"]
    if relation_type not in RELATION_TYPES:
        raise ValueError("不支持的关系类型")
    target_node_id = int(target_node_id or row["target_node_id"])
    if not conn.execute("SELECT 1 FROM knowledge_nodes WHERE id=?", (target_node_id,)).fetchone():
        raise ValueError("目标知识节点不存在")
    stamp = _now()
    conn.execute(
        """UPDATE knowledge_mentions SET status=?,relation_type=?,target_node_id=?,
           reviewed_at=?,updated_at=? WHERE id=?""",
        (status, relation_type, target_node_id, stamp, stamp, mention_id),
    )
    result = conn.execute(
        """SELECT m.*,n.title AS target_title,n.node_type
           FROM knowledge_mentions m JOIN knowledge_nodes n ON n.id=m.target_node_id
           WHERE m.id=?""", (mention_id,)
    ).fetchone()
    return dict(result)


def search_nodes(conn: sqlite3.Connection, query: str, limit: int = 30) -> list[dict[str, Any]]:
    ensure_schema(conn)
    normalized = _normalize(query)
    if not normalized:
        return []
    rows = conn.execute(
        """SELECT DISTINCT n.* FROM knowledge_nodes n
           LEFT JOIN knowledge_node_aliases a ON a.node_id=n.id
           WHERE n.normalized_title LIKE ? OR a.normalized_alias LIKE ?
           ORDER BY CASE WHEN n.normalized_title=? THEN 0 ELSE 1 END,
                    length(n.title),n.title LIMIT ?""",
        (f"%{normalized}%", f"%{normalized}%", normalized, max(1, min(limit, 100))),
    ).fetchall()
    return [dict(r) for r in rows]


def node_detail(conn: sqlite3.Connection, node_id: int) -> dict[str, Any] | None:
    ensure_schema(conn)
    node = conn.execute("SELECT * FROM knowledge_nodes WHERE id=?", (node_id,)).fetchone()
    if not node:
        return None
    node = _reconcile_statute_node(conn, node)
    result = dict(node)
    result["metadata"] = _json(result.pop("metadata_json", "{}"), {})
    result["aliases"] = [r[0] for r in conn.execute(
        "SELECT alias FROM knowledge_node_aliases WHERE node_id=? ORDER BY length(alias),alias",
        (node_id,),
    ).fetchall()]
    result["backlinks"] = [dict(r) for r in conn.execute(
        """SELECT m.*,a.title AS source_title FROM knowledge_mentions m
           JOIN articles a ON a.id=m.source_article_id
           WHERE m.target_node_id=? AND m.status='confirmed'
           ORDER BY m.updated_at DESC""", (node_id,)
    ).fetchall()]
    result["source_text"] = ""
    result["source_article_title"] = ""
    result["source_char_start"] = None
    result["claims"] = []

    if result["node_type"] == "statute_provision" and result.get("article_id"):
        source = conn.execute(
            "SELECT id,title,content FROM articles WHERE id=?", (result["article_id"],)
        ).fetchone()
        if source:
            result["source_article_title"] = source["title"] or ""
            paragraph_index = result.get("paragraph_index")
            if paragraph_index is not None:
                paragraphs = conn.execute(
                    """SELECT paragraph_index,text,char_start,char_end,heading
                       FROM article_paragraphs
                       WHERE article_id=? AND paragraph_index>=?
                       ORDER BY paragraph_index LIMIT 12""",
                    (result["article_id"], paragraph_index),
                ).fetchall()
                provision_parts: list[str] = []
                first_heading = (paragraphs[0]["heading"] or "").strip() if paragraphs else ""
                for index, paragraph in enumerate(paragraphs):
                    lead = (paragraph['text'] or '').lstrip()[:100]
                    if index and re.match(
                        r"第\s*[0-9〇零一二两三四五六七八九十百千万]+\s*条", lead
                    ):
                        break
                    if index and first_heading and (
                        (paragraph["heading"] or "").strip() != first_heading
                    ):
                        break
                    text = (paragraph["text"] or "").strip()
                    if text:
                        provision_parts.append(text)
                    if index == 0:
                        result["source_char_start"] = paragraph["char_start"]
                result["source_text"] = "\n".join(provision_parts)

    elif result["node_type"] == "issue" and result.get("issue_id"):
        try:
            claims = conn.execute(
                """SELECT DISTINCT c.id,c.statement,c.claim_type,c.conditions_text,
                                  c.exceptions_text,c.review_status,c.confidence
                   FROM knowledge_claims c
                   JOIN knowledge_claim_issues ci ON ci.claim_id=c.id
                   WHERE ci.issue_id=? AND c.review_status NOT IN ('rejected','merged')
                   ORDER BY CASE c.review_status WHEN 'approved' THEN 0 ELSE 1 END,
                            c.confidence DESC,c.id DESC LIMIT 20""",
                (result["issue_id"],),
            ).fetchall()
            for claim in claims:
                item = dict(claim)
                item["evidence"] = [dict(row) for row in conn.execute(
                    """SELECT e.article_id,e.paragraph_index,e.char_start,e.char_end,
                              e.stance,e.quote,a.title AS article_title
                       FROM knowledge_claim_evidence e
                       JOIN articles a ON a.id=e.article_id
                       WHERE e.claim_id=? AND e.verified=1
                       ORDER BY e.id LIMIT 8""",
                    (claim["id"],),
                ).fetchall()]
                result["claims"].append(item)
        except sqlite3.OperationalError:
            result["claims"] = []

    elif result["node_type"] == "case" and result.get("article_id"):
        source = conn.execute(
            "SELECT id,title,summary,content FROM articles WHERE id=?", (result["article_id"],)
        ).fetchone()
        if source:
            result["source_article_title"] = source["title"] or ""
            result["source_text"] = (
                (source["summary"] or "").strip()
                or (source["content"] or "").strip()[:1200]
            )
            result["source_char_start"] = 0
    return result


def create_backfill_job(conn: sqlite3.Connection) -> int:
    ensure_schema(conn)
    existing = conn.execute(
        "SELECT id FROM relation_backfill_jobs WHERE status IN ('queued','running','paused') ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if existing:
        return int(existing[0])
    total = int(conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0])
    stamp = _now()
    cur = conn.execute(
        """INSERT INTO relation_backfill_jobs
           (status,total_articles,created_at,updated_at) VALUES ('queued',?,?,?)""",
        (total, stamp, stamp),
    )
    return int(cur.lastrowid)


def backfill_job(conn: sqlite3.Connection, job_id: int | None = None) -> dict[str, Any] | None:
    ensure_schema(conn)
    if job_id:
        row = conn.execute("SELECT * FROM relation_backfill_jobs WHERE id=?", (job_id,)).fetchone()
    else:
        row = conn.execute("SELECT * FROM relation_backfill_jobs ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None
