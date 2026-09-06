"""Legal knowledge layer helpers.

The module deliberately contains no web or model-provider code.  It owns the
SQLite schema, citation validation, review state transitions and retrieval of
approved claims so the safety boundary remains testable without network calls.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import sqlite3
from difflib import SequenceMatcher
from typing import Any, Iterable


CLAIM_STATUSES = {"pending", "approved", "rejected", "needs_review", "merged"}
CLAIM_TYPES = {"rule", "exception", "procedure", "risk", "practice"}
EVIDENCE_STANCES = {"supports", "opposes", "limits", "background"}
RELATION_TYPES = {"conflicts_with", "limits", "supersedes", "distinguishes", "related_to"}
DEFAULT_KNOWLEDGE_DOMAIN = "综合法律"
DOMAIN_ALIASES = {"执行异议与复议": "执行异议"}


def now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def normalize_text(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", (value or "").casefold())


def content_hash(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS knowledge_issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            normalized_title TEXT NOT NULL,
            domain TEXT NOT NULL DEFAULT '综合法律',
            status TEXT NOT NULL DEFAULT 'active',
            merged_into_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(merged_into_id) REFERENCES knowledge_issues(id) ON DELETE SET NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_issue_key
            ON knowledge_issues(normalized_title, domain) WHERE status='active';

        CREATE TABLE IF NOT EXISTS knowledge_claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            statement TEXT NOT NULL,
            normalized_statement TEXT NOT NULL,
            claim_type TEXT NOT NULL DEFAULT 'rule',
            conditions_text TEXT DEFAULT '',
            exceptions_text TEXT DEFAULT '',
            procedural_stage TEXT DEFAULT '',
            jurisdiction TEXT DEFAULT '',
            court_level TEXT DEFAULT '',
            authority_type TEXT DEFAULT '',
            authority_level TEXT DEFAULT '',
            valid_from TEXT DEFAULT '',
            valid_to TEXT DEFAULT '',
            review_status TEXT NOT NULL DEFAULT 'pending',
            confidence REAL DEFAULT 0,
            model TEXT DEFAULT '',
            extraction_job_id INTEGER,
            possible_duplicate_id INTEGER,
            merged_into_id INTEGER,
            reviewer_note TEXT DEFAULT '',
            reviewed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(extraction_job_id) REFERENCES knowledge_extraction_jobs(id) ON DELETE SET NULL,
            FOREIGN KEY(possible_duplicate_id) REFERENCES knowledge_claims(id) ON DELETE SET NULL,
            FOREIGN KEY(merged_into_id) REFERENCES knowledge_claims(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_claim_status ON knowledge_claims(review_status, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_knowledge_claim_normalized ON knowledge_claims(normalized_statement);

        CREATE TABLE IF NOT EXISTS knowledge_claim_issues (
            claim_id INTEGER NOT NULL,
            issue_id INTEGER NOT NULL,
            is_primary INTEGER DEFAULT 1,
            PRIMARY KEY(claim_id, issue_id),
            FOREIGN KEY(claim_id) REFERENCES knowledge_claims(id) ON DELETE CASCADE,
            FOREIGN KEY(issue_id) REFERENCES knowledge_issues(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_claim_issue ON knowledge_claim_issues(issue_id, claim_id);

        CREATE TABLE IF NOT EXISTS knowledge_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            domain TEXT NOT NULL,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            parent_id INTEGER,
            description TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 0,
            source TEXT NOT NULL DEFAULT 'ai',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(parent_id) REFERENCES knowledge_categories(id) ON DELETE CASCADE
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_category_key
            ON knowledge_categories(domain,normalized_name,COALESCE(parent_id,0)) WHERE status='active';
        CREATE INDEX IF NOT EXISTS idx_knowledge_category_parent
            ON knowledge_categories(domain,parent_id,sort_order,name);

        CREATE TABLE IF NOT EXISTS knowledge_issue_categories (
            issue_id INTEGER PRIMARY KEY,
            category_id INTEGER NOT NULL,
            confidence REAL DEFAULT 0,
            assignment_source TEXT NOT NULL DEFAULT 'ai',
            reviewed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(issue_id) REFERENCES knowledge_issues(id) ON DELETE CASCADE,
            FOREIGN KEY(category_id) REFERENCES knowledge_categories(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_issue_category
            ON knowledge_issue_categories(category_id,issue_id);

        CREATE TABLE IF NOT EXISTS knowledge_issue_merge_suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_issue_id INTEGER NOT NULL,
            target_issue_id INTEGER NOT NULL,
            recommended_title TEXT DEFAULT '',
            similarity REAL DEFAULT 0,
            reason TEXT DEFAULT '',
            source TEXT NOT NULL DEFAULT 'ai',
            status TEXT NOT NULL DEFAULT 'pending',
            model TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            reviewed_at TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(source_issue_id,target_issue_id),
            FOREIGN KEY(source_issue_id) REFERENCES knowledge_issues(id) ON DELETE CASCADE,
            FOREIGN KEY(target_issue_id) REFERENCES knowledge_issues(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_merge_suggestion_status
            ON knowledge_issue_merge_suggestions(status,similarity DESC,updated_at DESC);

        CREATE TABLE IF NOT EXISTS knowledge_issue_merge_effects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_id INTEGER NOT NULL,
            target_issue_id INTEGER NOT NULL,
            claim_id INTEGER NOT NULL,
            effect_type TEXT NOT NULL,
            before_status TEXT DEFAULT '',
            before_merged_into_id INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY(issue_id) REFERENCES knowledge_issues(id) ON DELETE CASCADE,
            FOREIGN KEY(target_issue_id) REFERENCES knowledge_issues(id) ON DELETE CASCADE,
            FOREIGN KEY(claim_id) REFERENCES knowledge_claims(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_issue_merge_effect
            ON knowledge_issue_merge_effects(issue_id,target_issue_id,id);

        CREATE TABLE IF NOT EXISTS knowledge_organization_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            domain TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            model TEXT DEFAULT '',
            error TEXT DEFAULT '',
            warnings_json TEXT DEFAULT '[]',
            total_issues INTEGER DEFAULT 0,
            total_batches INTEGER DEFAULT 0,
            processed_batches INTEGER DEFAULT 0,
            assigned_issues INTEGER DEFAULT 0,
            suggestion_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_organization_job_status
            ON knowledge_organization_jobs(status,created_at);

        CREATE TABLE IF NOT EXISTS knowledge_claim_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id INTEGER NOT NULL,
            article_id INTEGER NOT NULL,
            paragraph_index INTEGER NOT NULL,
            stance TEXT NOT NULL DEFAULT 'supports',
            quote TEXT NOT NULL,
            char_start INTEGER,
            char_end INTEGER,
            source_hash TEXT DEFAULT '',
            verified INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            UNIQUE(claim_id, article_id, paragraph_index, stance),
            FOREIGN KEY(claim_id) REFERENCES knowledge_claims(id) ON DELETE CASCADE,
            FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_evidence_article ON knowledge_claim_evidence(article_id, paragraph_index);

        CREATE TABLE IF NOT EXISTS knowledge_claim_relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_claim_id INTEGER NOT NULL,
            to_claim_id INTEGER NOT NULL,
            relation_type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(from_claim_id, to_claim_id, relation_type),
            FOREIGN KEY(from_claim_id) REFERENCES knowledge_claims(id) ON DELETE CASCADE,
            FOREIGN KEY(to_claim_id) REFERENCES knowledge_claims(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS knowledge_extraction_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER NOT NULL,
            content_hash TEXT NOT NULL,
            trigger_type TEXT NOT NULL DEFAULT 'manual',
            status TEXT NOT NULL DEFAULT 'queued',
            model TEXT DEFAULT '',
            error TEXT DEFAULT '',
            warnings_json TEXT DEFAULT '[]',
            extracted_claims INTEGER DEFAULT 0,
            total_batches INTEGER DEFAULT 0,
            processed_batches INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_jobs_status ON knowledge_extraction_jobs(status, created_at);
        CREATE INDEX IF NOT EXISTS idx_knowledge_jobs_article ON knowledge_extraction_jobs(article_id, id DESC);

        CREATE TABLE IF NOT EXISTS knowledge_extraction_exclusions (
            article_id INTEGER PRIMARY KEY,
            reason TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS knowledge_audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            object_type TEXT NOT NULL,
            object_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            before_json TEXT DEFAULT '{}',
            after_json TEXT DEFAULT '{}',
            actor TEXT DEFAULT 'local_user',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_audit_object
            ON knowledge_audit_logs(object_type, object_id, created_at DESC);
        """
    )
    # Reconcile older pending records whenever the schema is initialized. The helper
    # is idempotent because it only considers records still in pending status.
    auto_approve_confident_claims(conn)


def _json_load(value: str | None, default: Any) -> Any:
    try:
        return json.loads(value or "")
    except Exception:
        return default


def _dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def article_knowledge_domains(article: sqlite3.Row | dict[str, Any]) -> list[str]:
    """Return the article's declared professional fields in stable order."""
    item = dict(article)
    raw = item.get("domains") or []
    if isinstance(raw, str):
        raw = _json_load(raw, [])
    if not isinstance(raw, list):
        raw = []
    result: list[str] = []
    for value in raw:
        domain = re.sub(r"\s+", " ", str(value or "").strip())[:80]
        domain = DOMAIN_ALIASES.get(domain, domain)
        if domain and domain not in result:
            result.append(domain)
    return result


def resolve_knowledge_domain(
    article: sqlite3.Row | dict[str, Any], suggested: str = ""
) -> str:
    """Keep model output inside the article's existing field classification."""
    domains = article_knowledge_domains(article)
    suggestion = re.sub(r"\s+", " ", str(suggested or "").strip())[:80]
    suggestion = DOMAIN_ALIASES.get(suggestion, suggestion)
    if suggestion and suggestion in domains:
        return suggestion
    return domains[0] if domains else DEFAULT_KNOWLEDGE_DOMAIN


def is_knowledge_article(article: sqlite3.Row | dict[str, Any]) -> bool:
    """All substantive articles can enter the knowledge layer, regardless of field."""
    item = dict(article)
    return len(normalize_text(str(item.get("content") or ""))) >= 8


def knowledge_candidate_ids(
    conn: sqlite3.Connection, domain: str = "", include_excluded: bool = False
) -> list[int]:
    rows = conn.execute("SELECT id,title,summary,domains,content FROM articles ORDER BY id").fetchall()
    excluded = set()
    if not include_excluded:
        excluded = {
            int(row[0]) for row in conn.execute(
                "SELECT article_id FROM knowledge_extraction_exclusions"
            ).fetchall()
        }
    wanted = str(domain or "").strip()
    return [
        int(row["id"])
        for row in rows
        if is_knowledge_article(row)
        and int(row["id"]) not in excluded
        and (not wanted or wanted in article_knowledge_domains(row) or resolve_knowledge_domain(row) == wanted)
    ]


# Compatibility aliases for installations or tests that still import the first-stage names.
is_pilot_article = is_knowledge_article
pilot_candidate_ids = knowledge_candidate_ids


def create_extraction_job(
    conn: sqlite3.Connection,
    article_id: int,
    trigger_type: str = "manual",
    model: str = "",
    force: bool = False,
) -> tuple[int, bool]:
    article = conn.execute("SELECT id,content FROM articles WHERE id=?", (article_id,)).fetchone()
    if not article:
        raise ValueError("文章不存在")
    digest = content_hash(article["content"] or "")
    if not force:
        active = conn.execute(
            """SELECT id FROM knowledge_extraction_jobs
               WHERE article_id=? AND content_hash=? AND status IN ('queued','running')
               ORDER BY id DESC LIMIT 1""",
            (article_id, digest),
        ).fetchone()
        if active:
            return int(active["id"]), False
        completed = conn.execute(
            """SELECT id FROM knowledge_extraction_jobs
               WHERE article_id=? AND content_hash=? AND status='completed'
               ORDER BY id DESC LIMIT 1""",
            (article_id, digest),
        ).fetchone()
        if completed:
            return int(completed["id"]), False
    now = now_iso()
    cur = conn.execute(
        """INSERT INTO knowledge_extraction_jobs
           (article_id,content_hash,trigger_type,status,model,created_at,updated_at)
           VALUES (?,?,?,'queued',?,?,?)""",
        (article_id, digest, trigger_type, model, now, now),
    )
    return int(cur.lastrowid), True


def split_paragraph_batches(paragraphs: Iterable[sqlite3.Row | dict[str, Any]], max_chars: int = 18000) -> list[list[dict[str, Any]]]:
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    size = 0
    for raw in paragraphs:
        item = dict(raw)
        item_size = len(item.get("text") or "") + 40
        if current and size + item_size > max_chars:
            batches.append(current)
            current, size = [], 0
        current.append(item)
        size += item_size
    if current:
        batches.append(current)
    return batches


def parse_model_json(text: str) -> dict[str, Any]:
    value = (text or "").strip()
    value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.I)
    value = re.sub(r"\s*```$", "", value)
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        start, end = value.find("{"), value.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("AI未返回可解析的JSON")
        data = json.loads(value[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("AI返回结构不是对象")
    return data


def _get_or_create_issue(
    conn: sqlite3.Connection, title: str, domain: str = DEFAULT_KNOWLEDGE_DOMAIN
) -> int:
    title = re.sub(r"\s+", " ", (title or "").strip())[:180]
    if not title:
        raise ValueError("法律问题名称为空")
    key = normalize_text(title)
    row = conn.execute(
        "SELECT id FROM knowledge_issues WHERE normalized_title=? AND domain=? AND status='active'",
        (key, domain),
    ).fetchone()
    if row:
        return int(row["id"])
    now = now_iso()
    cur = conn.execute(
        """INSERT INTO knowledge_issues(title,normalized_title,domain,status,created_at,updated_at)
           VALUES (?,?,?,'active',?,?)""",
        (title, key, domain, now, now),
    )
    return int(cur.lastrowid)


def _possible_duplicate(conn: sqlite3.Connection, normalized: str, issue_id: int) -> int | None:
    if not normalized:
        return None
    rows = conn.execute(
        """SELECT c.id,c.normalized_statement FROM knowledge_claims c
           JOIN knowledge_claim_issues ci ON ci.claim_id=c.id
           WHERE ci.issue_id=? AND c.review_status<>'merged' ORDER BY c.updated_at DESC LIMIT 80""",
        (issue_id,),
    ).fetchall()
    best_id, best_score = None, 0.0
    for row in rows:
        other = row["normalized_statement"] or ""
        if not other:
            continue
        score = SequenceMatcher(None, normalized, other).ratio()
        if normalized in other or other in normalized:
            score = max(score, 0.88)
        if score > best_score:
            best_id, best_score = int(row["id"]), score
    return best_id if best_score >= 0.82 else None


def auto_approve_confident_claims(
    conn: sqlite3.Connection, claim_ids: Iterable[int] | None = None
) -> list[int]:
    """Approve exact-100% claims only after at least one citation passed verification."""
    where = ["c.review_status='pending'", "c.confidence>=1.0"]
    params: list[Any] = []
    ids = sorted({int(value) for value in (claim_ids or []) if int(value) > 0})
    if claim_ids is not None:
        if not ids:
            return []
        where.append(f"c.id IN ({','.join('?' for _ in ids)})")
        params.extend(ids)
    rows = conn.execute(
        f"""SELECT c.* FROM knowledge_claims c
            WHERE {' AND '.join(where)}
              AND EXISTS (
                SELECT 1 FROM knowledge_claim_evidence e
                WHERE e.claim_id=c.id AND e.verified=1
              )
            ORDER BY c.id""",
        params,
    ).fetchall()
    approved: list[int] = []
    for row in rows:
        before = dict(row)
        now = now_iso()
        note = "置信度100%且原文依据已核验，系统自动通过"
        conn.execute(
            """UPDATE knowledge_claims
               SET review_status='approved',reviewer_note=?,reviewed_at=?,updated_at=?
               WHERE id=? AND review_status='pending'""",
            (note, now, now, row["id"]),
        )
        after_row = conn.execute("SELECT * FROM knowledge_claims WHERE id=?", (row["id"],)).fetchone()
        if not after_row or after_row["review_status"] != "approved":
            continue
        after = dict(after_row)
        audit(conn, "claim", int(row["id"]), "auto_approve_confidence", before, after, "system")
        approved.append(int(row["id"]))
    return approved


def save_extraction_batch(
    conn: sqlite3.Connection,
    job_id: int,
    article_id: int,
    payload: dict[str, Any],
    model: str,
) -> tuple[int, list[str]]:
    warnings: list[str] = []
    claims = payload.get("claims") or []
    if not isinstance(claims, list):
        return 0, ["claims字段不是数组"]
    paragraph_rows = conn.execute(
        "SELECT paragraph_index,text,char_start,char_end FROM article_paragraphs WHERE article_id=?",
        (article_id,),
    ).fetchall()
    paragraph_map = {int(row["paragraph_index"]): dict(row) for row in paragraph_rows}
    article = conn.execute("SELECT content,domains FROM articles WHERE id=?", (article_id,)).fetchone()
    source_digest = content_hash(article["content"] if article else "")
    created = 0
    touched_claim_ids: set[int] = set()

    for raw in claims:
        if not isinstance(raw, dict):
            warnings.append("忽略非对象结论")
            continue
        statement = re.sub(r"\s+", " ", str(raw.get("statement") or "").strip())[:1200]
        issue_title = str(raw.get("issue_title") or "").strip()
        normalized = normalize_text(statement)
        if len(normalized) < 8 or not issue_title:
            warnings.append("忽略缺少法律问题或内容过短的结论")
            continue
        evidence_items = raw.get("evidence") or []
        verified: list[tuple[dict[str, Any], str]] = []
        for evidence in evidence_items if isinstance(evidence_items, list) else []:
            try:
                para_idx = int(evidence.get("paragraph_index") or 0)
            except Exception:
                para_idx = 0
            paragraph = paragraph_map.get(para_idx)
            quoted = re.sub(r"\s+", "", str(evidence.get("quote") or ""))
            canonical = re.sub(r"\s+", "", paragraph.get("text") or "") if paragraph else ""
            if not paragraph or len(quoted) < 8 or quoted not in canonical:
                warnings.append(f"结论“{statement[:28]}”的第{para_idx or '?'}段引文未通过核验")
                continue
            stance = str(evidence.get("stance") or "supports")
            if stance not in EVIDENCE_STANCES:
                stance = "supports"
            verified.append((paragraph, stance))
        if not verified:
            warnings.append(f"结论“{statement[:28]}”没有可核验依据，已忽略")
            continue

        issue_domain = resolve_knowledge_domain(article or {}, str(raw.get("domain") or ""))
        issue_id = _get_or_create_issue(conn, issue_title, issue_domain)
        existing = conn.execute(
            """SELECT c.id FROM knowledge_claims c
               JOIN knowledge_claim_issues ci ON ci.claim_id=c.id
               JOIN knowledge_claim_evidence e ON e.claim_id=c.id
               WHERE c.extraction_job_id=? AND c.normalized_statement=? AND ci.issue_id=? AND e.article_id=?
               LIMIT 1""",
            (job_id, normalized, issue_id, article_id),
        ).fetchone()
        if existing:
            claim_id = int(existing["id"])
        else:
            claim_type = str(raw.get("claim_type") or "rule")
            if claim_type not in CLAIM_TYPES:
                claim_type = "rule"
            try:
                confidence = max(0.0, min(float(raw.get("confidence") or 0), 1.0))
            except (TypeError, ValueError):
                confidence = 0.0
            duplicate_id = _possible_duplicate(conn, normalized, issue_id)
            now = now_iso()
            cur = conn.execute(
                """INSERT INTO knowledge_claims
                   (statement,normalized_statement,claim_type,conditions_text,exceptions_text,
                    procedural_stage,jurisdiction,court_level,authority_type,authority_level,
                    valid_from,valid_to,review_status,confidence,model,extraction_job_id,
                    possible_duplicate_id,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'pending',?,?,?,?,?,?)""",
                (
                    statement, normalized, claim_type,
                    str(raw.get("conditions") or "")[:1200], str(raw.get("exceptions") or "")[:1200],
                    str(raw.get("procedural_stage") or "")[:120], str(raw.get("jurisdiction") or "")[:120],
                    str(raw.get("court_level") or "")[:120], str(raw.get("authority_type") or "")[:120],
                    str(raw.get("authority_level") or "")[:120], str(raw.get("valid_from") or "")[:40],
                    str(raw.get("valid_to") or "")[:40], confidence,
                    model, job_id, duplicate_id, now, now,
                ),
            )
            claim_id = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO knowledge_claim_issues(claim_id,issue_id,is_primary) VALUES (?,?,1)",
                (claim_id, issue_id),
            )
            created += 1
        touched_claim_ids.add(claim_id)
        for paragraph, stance in verified:
            conn.execute(
                """INSERT OR IGNORE INTO knowledge_claim_evidence
                   (claim_id,article_id,paragraph_index,stance,quote,char_start,char_end,source_hash,verified,created_at)
                   VALUES (?,?,?,?,?,?,?,?,1,?)""",
                (
                    claim_id, article_id, paragraph["paragraph_index"], stance, paragraph["text"],
                    paragraph.get("char_start"), paragraph.get("char_end"), source_digest, now_iso(),
                ),
            )
    auto_approve_confident_claims(conn, touched_claim_ids)
    return created, warnings


def save_category_taxonomy(
    conn: sqlite3.Connection, domain: str, categories: list[dict[str, Any]], source: str = "ai"
) -> dict[tuple[str, str], int]:
    """Upsert the two category levels beneath a legal domain and return path IDs."""
    domain = re.sub(r"\s+", " ", (domain or DEFAULT_KNOWLEDGE_DOMAIN).strip())[:120]
    now = now_iso()
    paths: dict[tuple[str, str], int] = {}

    def upsert(name: str, parent_id: int | None, description: str, order: int) -> int:
        clean = re.sub(r"\s+", " ", (name or "").strip())[:80]
        if not clean:
            raise ValueError("分类名称为空")
        key = normalize_text(clean)
        row = conn.execute(
            """SELECT id FROM knowledge_categories
               WHERE domain=? AND normalized_name=? AND COALESCE(parent_id,0)=COALESCE(?,0)
                 AND status='active'""",
            (domain, key, parent_id),
        ).fetchone()
        if row:
            category_id = int(row["id"])
            conn.execute(
                """UPDATE knowledge_categories SET name=?,description=?,sort_order=?,source=?,updated_at=?
                   WHERE id=?""",
                (clean, description[:500], order, source, now, category_id),
            )
            return category_id
        cur = conn.execute(
            """INSERT INTO knowledge_categories
               (domain,name,normalized_name,parent_id,description,sort_order,source,status,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,'active',?,?)""",
            (domain, clean, key, parent_id, description[:500], order, source, now, now),
        )
        return int(cur.lastrowid)

    for major_order, raw_major in enumerate(categories[:16], 1):
        if not isinstance(raw_major, dict):
            continue
        major_name = str(raw_major.get("name") or "").strip()
        if not major_name:
            continue
        major_id = upsert(major_name, None, str(raw_major.get("description") or ""), major_order)
        paths[(major_name, "")] = major_id
        children = raw_major.get("children") or []
        if not isinstance(children, list):
            children = []
        for child_order, raw_child in enumerate(children[:14], 1):
            if not isinstance(raw_child, dict):
                continue
            child_name = str(raw_child.get("name") or "").strip()
            if not child_name:
                continue
            child_id = upsert(
                child_name, major_id, str(raw_child.get("description") or ""), child_order
            )
            paths[(major_name, child_name)] = child_id
    return paths


def knowledge_category_rows(conn: sqlite3.Connection, domain: str = "") -> list[dict[str, Any]]:
    params: list[Any] = []
    where = ["c.status='active'"]
    if domain.strip():
        where.append("c.domain=?")
        params.append(domain.strip())
    rows = conn.execute(
        f"""SELECT c.*,p.name AS parent_name,
                   COUNT(DISTINCT assigned_issue.id) AS direct_issue_count
            FROM knowledge_categories c
            LEFT JOIN knowledge_categories p ON p.id=c.parent_id
            LEFT JOIN knowledge_issue_categories ic ON ic.category_id=c.id
            LEFT JOIN knowledge_issues assigned_issue
                ON assigned_issue.id=ic.issue_id AND assigned_issue.status='active'
            WHERE {' AND '.join(where)}
            GROUP BY c.id
            ORDER BY c.domain,COALESCE(p.sort_order,c.sort_order),COALESCE(p.name,c.name),
                     CASE WHEN c.parent_id IS NULL THEN 0 ELSE 1 END,c.sort_order,c.name""",
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def save_issue_organization_batch(
    conn: sqlite3.Connection,
    domain: str,
    payload: dict[str, Any],
    category_paths: dict[tuple[str, str], int],
    allowed_issue_ids: set[int],
    model: str,
) -> tuple[int, int, list[str]]:
    """Validate and save AI assignments/suggestions. No issue is ever merged here."""
    now = now_iso()
    assigned = 0
    suggested = 0
    warnings: list[str] = []
    assignments = payload.get("assignments") or []
    if not isinstance(assignments, list):
        assignments = []
    for raw in assignments:
        if not isinstance(raw, dict):
            continue
        try:
            issue_id = int(raw.get("issue_id") or 0)
        except (TypeError, ValueError):
            continue
        path = raw.get("category_path") or []
        if issue_id not in allowed_issue_ids or not isinstance(path, list) or not path:
            continue
        major = str(path[0] or "").strip()
        child = str(path[1] or "").strip() if len(path) > 1 else ""
        category_id = category_paths.get((major, child)) or category_paths.get((major, ""))
        if not category_id:
            warnings.append(f"问题#{issue_id}返回了不存在的分类路径")
            continue
        try:
            confidence = max(0.0, min(float(raw.get("confidence") or 0), 1.0))
        except (TypeError, ValueError):
            confidence = 0.0
        conn.execute(
            """INSERT INTO knowledge_issue_categories
               (issue_id,category_id,confidence,assignment_source,reviewed,created_at,updated_at)
               VALUES (?,?,?,'ai',0,?,?)
               ON CONFLICT(issue_id) DO UPDATE SET category_id=excluded.category_id,
                 confidence=excluded.confidence,assignment_source='ai',reviewed=0,updated_at=excluded.updated_at
               WHERE knowledge_issue_categories.reviewed=0""",
            (issue_id, category_id, confidence, now, now),
        )
        assigned += int(conn.execute("SELECT changes()").fetchone()[0] > 0)

    groups = payload.get("merge_groups") or []
    if not isinstance(groups, list):
        groups = []
    for raw in groups:
        if not isinstance(raw, dict):
            continue
        ids = sorted({int(value) for value in (raw.get("issue_ids") or []) if str(value).isdigit()})
        ids = [value for value in ids if value in allowed_issue_ids]
        try:
            score = max(0.0, min(float(raw.get("confidence") or 0), 1.0))
        except (TypeError, ValueError):
            score = 0.0
        if len(ids) < 2 or score < 0.75:
            continue
        # Preserve the oldest issue as the canonical target and merge newer variants into it.
        target_id = ids[0]
        for source_id in ids[1:]:
            conn.execute(
                """INSERT INTO knowledge_issue_merge_suggestions
                   (source_issue_id,target_issue_id,recommended_title,similarity,reason,source,status,
                    model,created_at,updated_at)
                   VALUES (?,?,?,?,?,'ai','pending',?,?,?)
                   ON CONFLICT(source_issue_id,target_issue_id) DO UPDATE SET
                     recommended_title=excluded.recommended_title,similarity=excluded.similarity,
                     reason=excluded.reason,model=excluded.model,updated_at=excluded.updated_at,
                     status=CASE WHEN knowledge_issue_merge_suggestions.status IN ('rejected','accepted')
                                 THEN knowledge_issue_merge_suggestions.status ELSE 'pending' END""",
                (
                    source_id, target_id, str(raw.get("recommended_title") or "")[:180], score,
                    str(raw.get("reason") or "")[:800], model, now, now,
                ),
            )
            suggested += int(conn.execute("SELECT changes()").fetchone()[0] > 0)
    return assigned, suggested, warnings


def add_heuristic_issue_suggestions(
    conn: sqlite3.Connection, domain: str, category_id: int | None = None
) -> int:
    """Add conservative title-similarity suggestions inside the same leaf category."""
    params: list[Any] = [domain]
    category_filter = ""
    if category_id:
        category_filter = " AND ic.category_id=?"
        params.append(category_id)
    rows = conn.execute(
        f"""SELECT i.id,i.title,i.normalized_title,ic.category_id
            FROM knowledge_issues i JOIN knowledge_issue_categories ic ON ic.issue_id=i.id
            WHERE i.status='active' AND i.domain=?{category_filter}
            ORDER BY ic.category_id,i.id""",
        params,
    ).fetchall()
    created = 0
    now = now_iso()
    by_category: dict[int, list[sqlite3.Row]] = {}
    for row in rows:
        by_category.setdefault(int(row["category_id"]), []).append(row)
    for items in by_category.values():
        for index, left in enumerate(items):
            for right in items[index + 1:]:
                a, b = left["normalized_title"] or "", right["normalized_title"] or ""
                if min(len(a), len(b)) < 5:
                    continue
                score = SequenceMatcher(None, a, b).ratio()
                if a in b or b in a:
                    score = max(score, 0.9)
                if score < 0.86:
                    continue
                target_id, source_id = sorted((int(left["id"]), int(right["id"])))
                exists = conn.execute(
                    """SELECT id FROM knowledge_issue_merge_suggestions
                       WHERE (source_issue_id=? AND target_issue_id=?)
                          OR (source_issue_id=? AND target_issue_id=?)""",
                    (source_id, target_id, target_id, source_id),
                ).fetchone()
                if exists:
                    continue
                conn.execute(
                    """INSERT INTO knowledge_issue_merge_suggestions
                       (source_issue_id,target_issue_id,recommended_title,similarity,reason,source,status,
                        model,created_at,updated_at)
                       VALUES (?,?,?,?,?,'heuristic','pending','',?,?)""",
                    (source_id, target_id, left["title"], score, "同一细分类下标题高度相似，建议人工核对", now, now),
                )
                created += 1
    return created


def audit(
    conn: sqlite3.Connection,
    object_type: str,
    object_id: int,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    actor: str = "local_user",
) -> None:
    conn.execute(
        """INSERT INTO knowledge_audit_logs
           (object_type,object_id,action,before_json,after_json,actor,created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (
            object_type, object_id, action,
            json.dumps(before or {}, ensure_ascii=False), json.dumps(after or {}, ensure_ascii=False),
            actor, now_iso(),
        ),
    )


def mark_article_claims_needs_review(conn: sqlite3.Connection, article_id: int, reason: str) -> list[int]:
    rows = conn.execute(
        """SELECT DISTINCT c.* FROM knowledge_claims c
           JOIN knowledge_claim_evidence e ON e.claim_id=c.id
           WHERE e.article_id=? AND c.review_status='approved'""",
        (article_id,),
    ).fetchall()
    ids: list[int] = []
    for row in rows:
        before = dict(row)
        now = now_iso()
        conn.execute(
            """UPDATE knowledge_claims SET review_status='needs_review',reviewer_note=?,updated_at=?
               WHERE id=?""",
            (reason[:500], now, row["id"]),
        )
        after = {**before, "review_status": "needs_review", "reviewer_note": reason, "updated_at": now}
        audit(conn, "claim", int(row["id"]), "invalidate", before, after, "system")
        ids.append(int(row["id"]))
    return ids


def claim_detail(conn: sqlite3.Connection, claim_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM knowledge_claims WHERE id=?", (claim_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    item["issues"] = [dict(r) for r in conn.execute(
        """SELECT i.* FROM knowledge_issues i JOIN knowledge_claim_issues ci ON ci.issue_id=i.id
           WHERE ci.claim_id=? AND i.status='active' ORDER BY ci.is_primary DESC,i.title""", (claim_id,)
    ).fetchall()]
    evidence_claim_ids = [claim_id] + [int(r[0]) for r in conn.execute(
        "SELECT id FROM knowledge_claims WHERE merged_into_id=?", (claim_id,)
    ).fetchall()]
    placeholders = ",".join("?" for _ in evidence_claim_ids)
    item["evidence"] = [dict(r) for r in conn.execute(
        f"""SELECT e.*,a.title AS article_title FROM knowledge_claim_evidence e
            JOIN articles a ON a.id=e.article_id WHERE e.claim_id IN ({placeholders})
            ORDER BY e.stance,e.article_id,e.paragraph_index""", evidence_claim_ids
    ).fetchall()]
    item["relations"] = [dict(r) for r in conn.execute(
        """SELECT r.*,c.statement AS target_statement FROM knowledge_claim_relations r
           JOIN knowledge_claims c ON c.id=r.to_claim_id WHERE r.from_claim_id=? ORDER BY r.id""",
        (claim_id,),
    ).fetchall()]
    item["audit"] = [
        {**dict(r), "before": _json_load(r["before_json"], {}), "after": _json_load(r["after_json"], {})}
        for r in conn.execute(
            "SELECT * FROM knowledge_audit_logs WHERE object_type='claim' AND object_id=? ORDER BY id DESC LIMIT 50",
            (claim_id,),
        ).fetchall()
    ]
    return item


def article_knowledge(conn: sqlite3.Connection, article_id: int) -> dict[str, Any]:
    latest_job = conn.execute(
        "SELECT * FROM knowledge_extraction_jobs WHERE article_id=? ORDER BY id DESC LIMIT 1", (article_id,)
    ).fetchone()
    rows = conn.execute(
        """SELECT DISTINCT c.id,c.statement,c.claim_type,c.review_status,c.updated_at,
                  i.id AS issue_id,i.title AS issue_title
           FROM knowledge_claims c
           JOIN knowledge_claim_issues ci ON ci.claim_id=c.id
           JOIN knowledge_issues i ON i.id=ci.issue_id
           JOIN knowledge_claim_evidence e ON e.claim_id=c.id
           WHERE e.article_id=? ORDER BY c.updated_at DESC""",
        (article_id,),
    ).fetchall()
    claims = [dict(row) for row in rows]
    claim_ids = sorted({int(item["id"]) for item in claims})
    evidence_by_claim: dict[int, list[dict[str, Any]]] = {claim_id: [] for claim_id in claim_ids}
    if claim_ids:
        placeholders = ",".join("?" for _ in claim_ids)
        evidence_rows = conn.execute(
            f"""SELECT e.claim_id,e.article_id,e.paragraph_index,e.stance,e.quote,
                       e.char_start,e.char_end,p.heading
                FROM knowledge_claim_evidence e
                LEFT JOIN article_paragraphs p
                  ON p.article_id=e.article_id AND p.paragraph_index=e.paragraph_index
                WHERE e.article_id=? AND e.verified=1 AND e.claim_id IN ({placeholders})
                ORDER BY e.claim_id,e.paragraph_index,e.id""",
            (article_id, *claim_ids),
        ).fetchall()
        for row in evidence_rows:
            evidence_by_claim[int(row["claim_id"])].append(dict(row))
    for claim in claims:
        claim["evidence"] = evidence_by_claim.get(int(claim["id"]), [])
    return {"job": _dict(latest_job), "claims": claims}


def approved_knowledge_context(
    conn: sqlite3.Connection,
    question: str,
    article_ids: list[int] | None = None,
    limit: int = 6,
) -> tuple[str, list[dict[str, Any]]]:
    raw_tokens = re.findall(r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", question or "")
    token_set: set[str] = set()
    for token in raw_tokens:
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            if len(token) <= 8:
                token_set.add(token)
            for width in (2, 3, 4, 5, 6):
                if len(token) >= width:
                    token_set.update(token[index:index + width] for index in range(len(token) - width + 1))
        else:
            token_set.add(token.casefold())
    stop_tokens = {"什么", "哪些", "如何", "是否", "可以", "问题", "规定", "关于", "以及", "相关"}
    tokens = [token for token in token_set if token not in stop_tokens]
    if not tokens:
        return "", []
    params: list[Any] = []
    scope = ""
    if article_ids:
        placeholders = ",".join("?" for _ in article_ids)
        scope = f" AND e.article_id IN ({placeholders})"
        params.extend(article_ids)
    rows = conn.execute(
        f"""SELECT c.*,i.title AS issue_title,e.article_id,e.paragraph_index,e.stance,e.quote,
                   e.char_start,e.char_end,a.title AS article_title
            FROM knowledge_claims c
            JOIN knowledge_claim_issues ci ON ci.claim_id=c.id
            JOIN knowledge_issues i ON i.id=ci.issue_id
            JOIN knowledge_claim_evidence e ON e.verified=1
            JOIN knowledge_claims evidence_claim ON evidence_claim.id=e.claim_id
                AND (evidence_claim.id=c.id OR evidence_claim.merged_into_id=c.id)
            JOIN articles a ON a.id=e.article_id
            WHERE c.review_status='approved' AND i.status='active' {scope}
            ORDER BY c.reviewed_at DESC,c.id DESC""",
        params,
    ).fetchall()
    scored: list[tuple[int, sqlite3.Row]] = []
    for row in rows:
        haystack = " ".join(str(row[key] or "") for key in (
            "issue_title", "statement", "conditions_text", "exceptions_text", "procedural_stage", "quote"
        ))
        score = sum((haystack.count(token) * max(2, len(token))) for token in tokens)
        if score:
            scored.append((score, row))
    scored.sort(key=lambda item: (-item[0], -int(item[1]["id"])))
    selected: list[sqlite3.Row] = []
    seen_claims: set[int] = set()
    for _, row in scored:
        if int(row["id"]) in seen_claims:
            continue
        selected.append(row)
        seen_claims.add(int(row["id"]))
        if len(selected) >= limit:
            break
    if not selected:
        return "", []
    blocks: list[str] = []
    citations: list[dict[str, Any]] = []
    for index, row in enumerate(selected, 1):
        scope_bits = [
            row["conditions_text"] and f"适用条件：{row['conditions_text']}",
            row["exceptions_text"] and f"例外：{row['exceptions_text']}",
            row["procedural_stage"] and f"程序阶段：{row['procedural_stage']}",
            row["jurisdiction"] and f"地域：{row['jurisdiction']}",
            row["court_level"] and f"法院层级：{row['court_level']}",
        ]
        blocks.append(
            f"【已审核知识{index}】问题：{row['issue_title']}\n"
            f"结论：{row['statement']}\n" + "；".join(bit for bit in scope_bits if bit) +
            f"\n核验依据：[REF:{row['article_id']}:{row['paragraph_index']}]{row['quote']}[/REF]"
        )
        citations.append({
            "article_id": int(row["article_id"]), "id": int(row["article_id"]),
            "title": row["article_title"], "paragraph_index": int(row["paragraph_index"]),
            "quote": row["quote"], "excerpt": row["quote"][:240],
            "char_start": row["char_start"], "char_end": row["char_end"], "verified": True,
        })
    return "\n\n".join(blocks), citations
