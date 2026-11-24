"""Explicit, read-only projections of user records for the WorkBuddy connector."""

import json
import re
from pathlib import Path
from typing import NamedTuple

from fastapi import HTTPException

from .workbuddy_stdio import RECORD_KINDS


class Source(NamedTuple):
    sql: str
    search: tuple
    link: str
    case_scoped: bool = False
    article_scoped: bool = False


CASE_LINK = "/case-manager?case_id={case_id}"
RESEARCH_LINK = "/?open_case_research={case_id}&section={section}"
FILE_LINK = "/case-files?case_id={case_id}"
ACTIVE = "COALESCE(c.source_status,'active') IN ('active','archived')"


def _case_source(table, columns, match, link=CASE_LINK, *, date_column="created_at", extra=""):
    return Source(
        f"SELECT r.id,r.case_id,r.{date_column} AS record_date,{columns} FROM {table} r "
        f"JOIN case_manager_cases c ON c.id=r.case_id WHERE {ACTIVE} {extra}",
        match, link, True,
    )


SOURCES = {
    "article_notes": Source(
        "SELECT n.id,n.article_id,n.created_at AS record_date,a.title,n.selected_text,n.content "
        "FROM notes n JOIN articles a ON a.id=n.article_id",
        ("title", "selected_text", "content"), "/?open_article={article_id}", article_scoped=True,
    ),
    "clients": Source(
        "SELECT id,created_at AS record_date,name,client_type,address,legal_representative,contact_person,phone,contacts_json "
        "FROM case_manager_clients",
        ("name", "contact_person", "phone"), "/case-manager?client_id={id}",
    ),
    "opponents": Source(
        "SELECT id,created_at AS record_date,name,opponent_type,address,contact_person,phone,notes,contacts_json "
        "FROM case_manager_opponents",
        ("name", "contact_person", "phone"), "/case-manager?opponent_id={id}",
    ),
    "case_parties": _case_source(
        "case_manager_parties", "r.name,r.party_group,r.role,r.client_id,r.opponent_id",
        ("name", "role"),
    ),
    "case_claims": _case_source(
        "case_manager_claims", "r.claim_code,r.claim_text,r.amount_text,r.currency,r.calculation_basis,r.legal_basis,r.notes",
        ("claim_text", "legal_basis", "notes"),
    ),
    "case_milestones": _case_source(
        "case_manager_milestones", "r.title,r.milestone_type,r.milestone_status,r.notes",
        ("title", "notes"), date_column="happened_at",
    ),
    "case_fact_notes": Source(
        "SELECT c.id,c.id AS case_id,c.updated_at AS record_date,c.title,c.memo,c.facts_difference,c.contract_difference,"
        "c.other_differences,c.case_focus,p.common_facts,p.common_contract_terms,p.series_memo FROM case_manager_cases c "
        "LEFT JOIN case_manager_series_profiles p ON p.series_case_id=c.id WHERE " + ACTIVE,
        ("title", "memo", "facts_difference", "case_focus"), CASE_LINK, True,
    ),
    "case_ledgers": Source(
        f"""SELECT r.id,p.case_id,r.happened_at AS record_date,r.title,r.content,'ledger' AS section
        FROM research_case_ledgers r JOIN research_projects p ON p.id=r.project_id
        JOIN case_manager_cases c ON c.id=p.case_id WHERE {ACTIVE}""",
        ("title", "content"), RESEARCH_LINK, True,
    ),
    "case_memos": Source(
        f"""SELECT r.id,p.case_id,r.happened_at AS record_date,r.title,r.content,'memo' AS section
        FROM research_case_memo_entries r JOIN research_projects p ON p.id=r.project_id
        JOIN case_manager_cases c ON c.id=p.case_id WHERE {ACTIVE}""",
        ("title", "content"), RESEARCH_LINK, True,
    ),
    "research_projects": Source(
        f"""SELECT p.id,p.case_id,p.created_at AS record_date,p.name,p.client,p.case_info,p.issues,p.notes,p.status
        FROM research_projects p LEFT JOIN case_manager_cases c ON c.id=p.case_id
        WHERE COALESCE(p.case_id,0)=0 OR (c.id IS NOT NULL AND {ACTIVE})""",
        ("name", "client", "case_info", "issues", "notes"), "/", True,
    ),
    "case_files": _case_source(
        "case_manager_files", "r.original_filename AS name,r.category,r.size_bytes,r.mime_type",
        ("name", "category"), FILE_LINK,
    ),
    "indexed_case_files": _case_source(
        "case_manager_local_file_index",
        "r.display_name AS name,r.size_bytes,r.extraction_status,LENGTH(r.extracted_text) AS text_length",
        ("name",), FILE_LINK, date_column="updated_at",
    ),
    "case_archive": Source(
        f"""SELECT r.case_id,r.updated_at AS record_date,r.relative_path,r.item_code,r.position,r.review_state,r.size_bytes
        FROM case_archive_materials r JOIN case_manager_cases c ON c.id=r.case_id WHERE {ACTIVE}""",
        ("relative_path", "item_code"), "/?open_case_archive={case_id}", True,
    ),
    "preservation_deadlines": _case_source(
        "case_manager_preservations", "r.title,r.preservation_type,r.asset_content,r.start_at,r.period_years,r.notes",
        ("title", "asset_content", "notes"), date_column="deadline_at",
    ),
    "appeal_deadlines": _case_source(
        "case_manager_appeals", "r.title,r.appeal_type,r.case_no,r.court,r.start_at,r.period_days,r.notes",
        ("title", "case_no", "court", "notes"), date_column="deadline_at",
    ),
    "completed_todos": Source(
        f"""SELECT r.id,r.case_id,r.completed_at AS record_date,COALESCE(NULLIF(r.todo_title,''),r.title) AS title,
        r.notes,r.remind_at FROM case_manager_todos r LEFT JOIN case_manager_cases c ON c.id=r.case_id
        WHERE r.status='completed' AND (r.case_id IS NULL OR (c.id IS NOT NULL AND {ACTIVE}))""",
        ("title", "notes"), CASE_LINK, True,
    ),
    "expenses": Source(
        f"""SELECT r.id,r.case_id,r.occurred_on AS record_date,r.entry_type,r.project_name,r.category,
        r.description,r.amount_cents FROM case_manager_prepaid_expenses r LEFT JOIN case_manager_cases c ON c.id=r.case_id
        WHERE r.case_id IS NULL OR (c.id IS NOT NULL AND {ACTIVE})""",
        ("project_name", "category", "description"), "/case-manager?tab=prepaidExpenses&mode=team-expenses", True,
    ),
    "document_history": Source(
        "SELECT id,COALESCE(NULLIF(date,''),created_at) AS record_date,doc_type,court,clients,lawyers,parties,"
        "case_type,stages,case_number FROM document_history",
        ("doc_type", "court", "clients", "case_number"), "/document-bundle-generator",
    ),
    "contract_profiles": Source(
        f"""SELECT r.case_id AS id,r.case_id,r.updated_at AS record_date,
        r.entrust_type,r.representation_stage,r.engagement_scope,r.background_matter,r.fee_type,r.fee_amount,
        r.payment_terms,r.sign_date,r.subject_amount FROM case_manager_contract_profiles r
        JOIN case_manager_cases c ON c.id=r.case_id WHERE {ACTIVE}""",
        ("entrust_type", "engagement_scope", "background_matter", "payment_terms"), CASE_LINK, True,
    ),
    "saved_memories": Source(
        f"""SELECT r.id,r.case_id,r.updated_at AS record_date,r.kind,r.subject,r.content
        FROM user_memories r LEFT JOIN case_manager_cases c ON c.id=r.case_id
        WHERE r.source='manual' AND r.status='active' AND
        (r.kind='personal' OR (c.id IS NOT NULL AND {ACTIVE}))""",
        ("subject", "content"), CASE_LINK, True,
    ),
}


def _rows(conn, source, filters):
    fields = []
    values = []
    for key in ("case_id", "article_id", "record_id"):
        value = filters.get(key)
        if value is None:
            continue
        if ((key == "case_id" and not source.case_scoped) or (key == "article_id" and not source.article_scoped)
                or (key == "record_id" and source is SOURCES["case_archive"])):
            raise HTTPException(422, "该资料类型不支持这项筛选。")
        fields.append(("id" if key == "record_id" else key) + " = ?")
        values.append(value)
    for key, operator in (("start_date", ">="), ("end_date", "<=")):
        if filters.get(key):
            fields.append(f"date(record_date) {operator} date(?)")
            values.append(filters[key])
    if filters.get("query"):
        fields.append("(" + " OR ".join(f"instr(lower(COALESCE({field}, '')),lower(?))>0" for field in source.search) + ")")
        values.extend([filters["query"]] * len(source.search))
    where = " WHERE " + " AND ".join(fields) if fields else ""
    order = "case_id,relative_path" if source is SOURCES["case_archive"] else "id DESC"
    return conn.execute(
        f"WITH records AS ({source.sql}) SELECT * FROM records{where} "
        f"ORDER BY record_date DESC, {order} LIMIT ? OFFSET ?",
        [*values, filters["limit"] + 1, filters["offset"]],
    ).fetchall()


def _invoice_rows(runtime, filters):
    if any(filters.get(key) is not None for key in ("case_id", "article_id", "record_id")):
        raise HTTPException(422, "本地发票记录支持关键词和日期筛选。")
    columns = ("filename", "invoice_number", "issuer", "amount", "issue_time", "exported_at")
    result = []
    for account in ("qq_mail", "qq_exmail", "netease_exmail"):
        path = runtime / "data" / f"invoice_export_history_{account}.json"
        try:
            with path.open("rb") as source:
                data = source.read(8 * 1024 * 1024 + 1)
                records = json.loads(data) if len(data) <= 8 * 1024 * 1024 else []
        except (OSError, ValueError):
            continue
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            row = {field: str(record.get(field) or "")[:400] for field in columns}
            day = (row["issue_time"] or row["exported_at"])[:10]
            if ((filters.get("start_date") and day < filters["start_date"])
                    or (filters.get("end_date") and (not day or day > filters["end_date"]))):
                continue
            if filters.get("query") and not any(filters["query"].casefold() in row[field].casefold()
                                                for field in ("filename", "invoice_number", "issuer")):
                continue
            row["record_date"] = day
            result.append(row)
    result.sort(key=lambda row: row["record_date"], reverse=True)
    offset = filters["offset"]
    return result[offset:offset + filters["limit"] + 1]


def _text_record(conn, kind, record_id, offset, origin, plain_text):
    if kind == "article_text":
        row = conn.execute("SELECT id,title,content FROM articles WHERE id=?", (record_id,)).fetchone()
        link = f"{origin}/?open_article={record_id}"
    else:
        row = conn.execute(
            f"""SELECT r.id,r.display_name AS title,r.extracted_text AS content,r.case_id
            FROM case_manager_local_file_index r JOIN case_manager_cases c ON c.id=r.case_id
            WHERE r.id=? AND {ACTIVE}""", (record_id,),
        ).fetchone()
        link = origin + FILE_LINK.format(case_id=row["case_id"]) if row else None
    if not row:
        raise HTTPException(404, "没有找到这条文本记录。")
    text = plain_text(row["content"] or "") if kind == "article_text" else (row["content"] or "")
    stop = min(offset + 3500, len(text))
    return {"record_id": record_id, "title": (row["title"] or "")[:180], "text": text[offset:stop],
            "next_char_offset": stop if stop < len(text) else None, "open_in_stella": link}


def readable_data(permissions):
    return {"data_types": [{"type": key, "label": label} for key, (scope, label) in RECORD_KINDS.items()
                           if permissions.get(scope)]}


def read_user_data(conn, runtime: Path, kind, filters, origin, plain_text):
    if kind in ("article_text", "indexed_file_text"):
        if filters.get("record_id") is None or set(filters) - {"record_id", "char_offset", "limit", "offset"}:
            raise HTTPException(422, "读取正文时请提供 record_id，可选 char_offset。")
        return _text_record(conn, kind, filters["record_id"], filters.get("char_offset", 0), origin, plain_text)
    if "char_offset" in filters:
        raise HTTPException(422, "只有正文读取支持 char_offset。")
    if filters.get("start_date") and filters.get("end_date") and filters["start_date"] > filters["end_date"]:
        raise HTTPException(422, "开始日期必须早于或等于结束日期。")
    source = SOURCES.get(kind)
    rows = _rows(conn, source, filters) if source else _invoice_rows(runtime, filters)
    items, size = [], 0
    for raw in rows[:filters["limit"]]:
        row = dict(raw)
        if "relative_path" in row:
            row["name"] = re.split(r"[/\\]", row.pop("relative_path"))[-1]
        item = {key: (value[:700] if isinstance(value, str) else value) for key, value in row.items()}
        link = source.link if source else "/invoice-center"
        if "{case_id}" in link and not row.get("case_id"):
            link = "/case-manager?tab=todos" if kind == "completed_todos" else "/"
        item["open_in_stella"] = origin + link.format(**row)
        size += len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
        if size > 48000 and items:
            break
        items.append(item)
    return {"items": items, "next_offset": filters["offset"] + len(items) if len(rows) > len(items) else None}
