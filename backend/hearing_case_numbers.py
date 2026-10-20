"""Add saved hearing numbers to their linked case without replacing manual data.

All writes use the caller's transaction. No schema or calendar changes occur here.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any, Dict, List


def normalize_number(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).translate(str.maketrans({
        "(": "（", ")": "）", "﹙": "（", "﹚": "）",
    }))


def extract_numbers(value: Any) -> List[str]:
    text = normalize_number(value)
    # Legacy imports can concatenate several numbers or append explanatory notes.
    # Keep each identifiable number, rather than copying the entire annotation.
    found = re.findall(r"（\d{4}）[^（）\n,，;；【\[]{1,80}?号", text)
    return list(dict.fromkeys(found)) if found else [part for part in re.split(r"[;；,，、]+", text) if part]


def number_type(number: str, reminder_type: str = "") -> str:
    for pattern, label in (
        (r"(?:民|刑|行|知)(?:辖)?终", "二审"),
        (r"(?:民|刑|行|知)(?:辖)?初", "一审"),
        (r"(?:民|刑|行|知)再", "再审"),
        (r"执异", "执行异议"), (r"执复", "执行复议"),
        (r"执保", "执行保全"), (r"执恢", "恢复执行"),
        (r"执", "执行"), (r"仲", "仲裁"),
    ):
        if re.search(pattern, number):
            return label
    for label in ("一审", "二审", "再审", "仲裁", "执行"):
        if label in reminder_type:
            return label
    return ""


def sync_hearing_case_numbers(conn: Any, hearing: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Idempotent, additive merge, scoped strictly to the hearing's linked case."""
    case_id = int(hearing.get("case_id") or 0)
    if not case_id or not str(hearing.get("case_no") or "").strip():
        return []
    case = conn.execute(
        "SELECT id FROM case_manager_cases WHERE id=? AND COALESCE(source_status,'active')<>'deleted'",
        (case_id,),
    ).fetchone()
    if not case:
        return []
    columns = "id,number_type,case_no,court,sort_order"
    before = [dict(row) for row in conn.execute(
        f"SELECT {columns} FROM case_manager_case_numbers WHERE case_id=? ORDER BY sort_order,id", (case_id,)
    )]
    current = [dict(row) for row in before]
    stamp = dt.datetime.now().isoformat(timespec="seconds")
    courts = [line.strip() for line in str(hearing.get("court") or "").splitlines() if line.strip()]
    lines = [line.strip() for line in str(hearing.get("case_no") or "").splitlines() if line.strip()]
    changes = []
    for index, line in enumerate(lines):
        # Newline pairs match the hearing detail's case-number/court table.
        # A sole court applies to each number; never guess when multiple courts
        # were provided without a corresponding position.
        court = courts[index] if index < len(courts) else (courts[0] if len(courts) == 1 else "")
        for number in extract_numbers(line):
            if not number or number in {"无", "暂无", "待定", "待补充", "未立案", "—", "-"}:
                continue
            inferred = number_type(number, str(hearing.get("reminder_type") or ""))
            existing = next((row for row in current if number in extract_numbers(row["case_no"])), None)
            if existing:
                updates = {}
                if court and not str(existing.get("court") or "").strip():
                    updates["court"] = court
                if inferred and len(extract_numbers(existing["case_no"])) == 1 and not str(existing.get("number_type") or "").strip():
                    updates["number_type"] = inferred
                if not updates:
                    continue
                conn.execute(
                    "UPDATE case_manager_case_numbers SET " + ",".join(f"{key}=?" for key in updates) + ",updated_at=? WHERE id=? AND case_id=?",
                    (*updates.values(), stamp, existing["id"], case_id),
                )
                existing.update(updates)
                changes.append({"action": "filled", "id": existing["id"], "case_no": number})
            else:
                order = max((int(row["sort_order"] or 0) for row in current), default=-1) + 1
                cursor = conn.execute(
                    """INSERT INTO case_manager_case_numbers
                       (case_id,number_type,case_no,court,sort_order,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    (case_id, inferred, number, court, order, stamp, stamp),
                )
                current.append({"id": cursor.lastrowid, "number_type": inferred, "case_no": number, "court": court, "sort_order": order})
                changes.append({"action": "added", "id": cursor.lastrowid, "case_no": number})
    if changes:
        conn.execute("UPDATE case_manager_cases SET updated_at=? WHERE id=?", (stamp, case_id))
        audit = [{"field": "case_numbers", "label": "案号及审理节点",
                  "before": json.dumps(before, ensure_ascii=False), "after": json.dumps(current, ensure_ascii=False)}]
        conn.execute(
            """INSERT INTO case_manager_audit_logs
               (case_id,entity_type,entity_id,action,summary,changes_json,actor,created_at)
               VALUES (?,'case',?,'updated',?,?, '本机用户',?)""",
            (case_id, case_id, "由开庭提醒同步案号及受理机构", json.dumps(audit, ensure_ascii=False), stamp),
        )
    return changes
