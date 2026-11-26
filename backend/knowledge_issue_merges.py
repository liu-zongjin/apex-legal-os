"""Merge and restore reviewed knowledge issues while preserving their audit history."""

from __future__ import annotations

import datetime
import sqlite3

from fastapi import HTTPException

from .legal_knowledge import audit as audit_knowledge_change


def _knowledge_claim_row(conn: sqlite3.Connection, claim_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM knowledge_claims WHERE id=?", (claim_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="知识结论不存在")
    return row


def _knowledge_issue_row(conn: sqlite3.Connection, issue_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM knowledge_issues WHERE id=?", (issue_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="法律问题不存在")
    return row


def _knowledge_claim_quality(row: sqlite3.Row | dict) -> tuple[int, int, int]:
    status_rank = {"approved": 4, "needs_review": 3, "pending": 2, "rejected": 1, "merged": 0}
    return (
        status_rank.get(row["review_status"], 0),
        int(row["evidence_count"] or 0),
        -int(row["id"]),
    )


def _add_claim_to_merged_issue(
    conn: sqlite3.Connection, claim_id: int, issue_id: int, target_issue_id: int, now: str
) -> None:
    exists = conn.execute(
        "SELECT 1 FROM knowledge_claim_issues WHERE claim_id=? AND issue_id=?",
        (claim_id, target_issue_id),
    ).fetchone()
    if exists:
        return
    conn.execute(
        "INSERT INTO knowledge_claim_issues(claim_id,issue_id,is_primary) VALUES (?,?,1)",
        (claim_id, target_issue_id),
    )
    conn.execute(
        """INSERT INTO knowledge_issue_merge_effects
           (issue_id,target_issue_id,claim_id,effect_type,created_at)
           VALUES (?,?,?,'added_target_link',?)""",
        (issue_id, target_issue_id, claim_id, now),
    )


def _merge_knowledge_issue_records(
    conn: sqlite3.Connection, issue_id: int, target_id: int, audit_action: str = "merge"
) -> dict:
    """Merge an issue and consolidate exact duplicate claims without deleting history."""
    source = dict(_knowledge_issue_row(conn, issue_id))
    target = dict(_knowledge_issue_row(conn, target_id))
    if issue_id == target_id:
        raise HTTPException(status_code=400, detail="请选择不同的目标问题")
    if source["status"] != "active" or target["status"] != "active":
        raise HTTPException(status_code=400, detail="只能合并活动问题")
    if source["domain"] != target["domain"]:
        raise HTTPException(status_code=400, detail="不同专业领域的法律问题不能直接合并")

    now = datetime.datetime.now().isoformat()
    conn.execute("DELETE FROM knowledge_issue_merge_effects WHERE issue_id=?", (issue_id,))
    target_claims = conn.execute(
        """SELECT c.*,COUNT(DISTINCT e.id) AS evidence_count
           FROM knowledge_claims c
           JOIN knowledge_claim_issues ci ON ci.claim_id=c.id
           LEFT JOIN knowledge_claim_evidence e ON e.claim_id=c.id AND e.verified=1
           WHERE ci.issue_id=? AND c.review_status<>'merged'
           GROUP BY c.id ORDER BY c.id""",
        (target_id,),
    ).fetchall()
    source_claims = conn.execute(
        """SELECT c.*,COUNT(DISTINCT e.id) AS evidence_count
           FROM knowledge_claims c
           JOIN knowledge_claim_issues ci ON ci.claim_id=c.id
           LEFT JOIN knowledge_claim_evidence e ON e.claim_id=c.id AND e.verified=1
           WHERE ci.issue_id=? AND c.review_status<>'merged'
           GROUP BY c.id ORDER BY c.id""",
        (issue_id,),
    ).fetchall()
    source_claim_ids = {int(claim["id"]) for claim in source_claims}
    by_statement: dict[str, list[sqlite3.Row]] = {}
    for claim in target_claims:
        by_statement.setdefault(claim["normalized_statement"] or "", []).append(claim)

    for source_claim in source_claims:
        normalized = source_claim["normalized_statement"] or ""
        duplicates = [
            claim for claim in by_statement.get(normalized, [])
            if int(claim["id"]) != int(source_claim["id"])
        ] if normalized else []
        if not duplicates:
            _add_claim_to_merged_issue(conn, int(source_claim["id"]), issue_id, target_id, now)
            by_statement.setdefault(normalized, []).append(source_claim)
            continue

        candidates = duplicates + [source_claim]
        canonical = max(candidates, key=_knowledge_claim_quality)
        if int(canonical["id"]) == int(source_claim["id"]):
            _add_claim_to_merged_issue(conn, int(source_claim["id"]), issue_id, target_id, now)
        for duplicate in candidates:
            if int(duplicate["id"]) == int(canonical["id"]) or duplicate["review_status"] == "merged":
                continue
            if int(duplicate["id"]) in source_claim_ids:
                _add_claim_to_merged_issue(conn, int(duplicate["id"]), issue_id, target_id, now)
            before = dict(_knowledge_claim_row(conn, int(duplicate["id"])))
            conn.execute(
                """INSERT INTO knowledge_issue_merge_effects
                   (issue_id,target_issue_id,claim_id,effect_type,before_status,
                    before_merged_into_id,created_at)
                   VALUES (?,?,?,'merged_claim',?,?,?)""",
                (
                    issue_id, target_id, duplicate["id"], before["review_status"],
                    before["merged_into_id"], now,
                ),
            )
            conn.execute(
                """UPDATE knowledge_claims SET review_status='merged',merged_into_id=?,updated_at=?
                   WHERE id=?""",
                (canonical["id"], now, duplicate["id"]),
            )
            after = dict(_knowledge_claim_row(conn, int(duplicate["id"])))
            audit_knowledge_change(
                conn, "claim", int(duplicate["id"]), "merge_exact_claim_with_issue", before, after
            )
        by_statement[normalized] = [canonical]

    conn.execute(
        "UPDATE knowledge_issues SET status='merged',merged_into_id=?,updated_at=? WHERE id=?",
        (target_id, now, issue_id),
    )
    after_issue = dict(_knowledge_issue_row(conn, issue_id))
    audit_knowledge_change(conn, "issue", issue_id, audit_action, source, after_issue)
    return after_issue


def _unmerge_knowledge_issue_records(conn: sqlite3.Connection, issue_id: int) -> dict:
    source = dict(_knowledge_issue_row(conn, issue_id))
    if source["status"] != "merged" or not source["merged_into_id"]:
        raise HTTPException(status_code=400, detail="该法律问题没有处于合并状态")
    collision = conn.execute(
        """SELECT id FROM knowledge_issues
           WHERE normalized_title=? AND domain=? AND status='active' AND id<>?""",
        (source["normalized_title"], source["domain"], issue_id),
    ).fetchone()
    if collision:
        raise HTTPException(status_code=409, detail="存在同名活动问题，无法撤销合并")
    now = datetime.datetime.now().isoformat()
    effects = conn.execute(
        "SELECT * FROM knowledge_issue_merge_effects WHERE issue_id=? ORDER BY id DESC", (issue_id,)
    ).fetchall()
    for effect in effects:
        if effect["effect_type"] == "merged_claim":
            before = dict(_knowledge_claim_row(conn, int(effect["claim_id"])))
            conn.execute(
                """UPDATE knowledge_claims SET review_status=?,merged_into_id=?,updated_at=? WHERE id=?""",
                (
                    effect["before_status"] or "pending", effect["before_merged_into_id"], now,
                    effect["claim_id"],
                ),
            )
            after = dict(_knowledge_claim_row(conn, int(effect["claim_id"])))
            audit_knowledge_change(
                conn, "claim", int(effect["claim_id"]), "unmerge_exact_claim_with_issue", before, after
            )
        elif effect["effect_type"] == "added_target_link":
            conn.execute(
                "DELETE FROM knowledge_claim_issues WHERE claim_id=? AND issue_id=?",
                (effect["claim_id"], effect["target_issue_id"]),
            )
    conn.execute("DELETE FROM knowledge_issue_merge_effects WHERE issue_id=?", (issue_id,))
    conn.execute(
        "UPDATE knowledge_issues SET status='active',merged_into_id=NULL,updated_at=? WHERE id=?",
        (now, issue_id),
    )
    after_issue = dict(_knowledge_issue_row(conn, issue_id))
    audit_knowledge_change(conn, "issue", issue_id, "unmerge", source, after_issue)
    return after_issue


def _repair_legacy_knowledge_issue_merges(conn: sqlite3.Connection) -> int:
    """Backfill claim links/consolidation for issue merges created before merge effects existed."""
    legacy_rows = conn.execute(
        """SELECT i.* FROM knowledge_issues i
           WHERE i.status='merged' AND i.merged_into_id IS NOT NULL
             AND NOT EXISTS (
               SELECT 1 FROM knowledge_issue_merge_effects e WHERE e.issue_id=i.id
             )
           ORDER BY i.id DESC"""
    ).fetchall()
    repaired = 0
    for legacy_row in legacy_rows:
        source = dict(legacy_row)
        target_id = int(source["merged_into_id"])
        visited = {int(source["id"])}
        target = None
        while target_id not in visited:
            visited.add(target_id)
            target_row = conn.execute(
                "SELECT * FROM knowledge_issues WHERE id=?", (target_id,)
            ).fetchone()
            if not target_row:
                break
            target = dict(target_row)
            if target["status"] == "active":
                break
            if target["status"] != "merged" or not target["merged_into_id"]:
                target = None
                break
            target_id = int(target["merged_into_id"])
        if not target or target["status"] != "active" or source["domain"] != target["domain"]:
            continue

        conn.execute(
            "UPDATE knowledge_issues SET status='active',merged_into_id=NULL WHERE id=?",
            (source["id"],),
        )
        try:
            _merge_knowledge_issue_records(
                conn, int(source["id"]), int(target["id"]), "repair_legacy_merge"
            )
        except Exception:
            conn.execute(
                """UPDATE knowledge_issues SET status='merged',merged_into_id=?,updated_at=?
                   WHERE id=?""",
                (source["merged_into_id"], source["updated_at"], source["id"]),
            )
            conn.execute(
                "DELETE FROM knowledge_issue_merge_effects WHERE issue_id=?", (source["id"],)
            )
            continue
        repaired += 1
    return repaired
