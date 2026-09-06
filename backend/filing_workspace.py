"""本地“预立案”工作台。

本模块只管理律师已确认的本地立案草稿、材料清单及官网回传状态。它绝不
调用或推测人民法院在线服务的写入接口；最终提交、验证码、实名认证和电子
签名必须由律师在官网页面中完成。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import mimetypes
import os
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException, Request


MAX_FILE_BYTES = 50 * 1024 * 1024
ALLOWED_SUFFIXES = {".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png"}
STATUS_LABELS = {
    "draft": "待确认",
    "ready": "待提交",
    "submitted": "已提交待审核",
    "supplement": "待补正",
    "filed": "已立案",
    "failed": "失败或撤回",
}
MATERIAL_LABELS = {
    "complaint": "民事起诉状",
    "evidence_index": "证据目录",
    "evidence": "证据材料",
    "identity": "当事人主体资格证明",
    "service_address": "送达地址确认书",
    "authority": "授权委托书",
    "lawyer_certificate": "律师执业证",
    "law_firm_letter": "律师事务所函",
    "agent_identity": "代理人身份证明",
    "legal_rep_identity": "法定代表人身份证明",
    "legal_rep_certificate": "法定代表人身份证明书",
    "other": "其他材料",
}
REPRESENTATION_MODES = {
    "lawyer_agent": "律师代理",
    "legal_representative": "法定代表人出庭",
    "employee_agent": "公司员工代理",
    "self": "当事人自行立案",
}
BASE_REQUIRED_CATEGORIES = ("complaint", "evidence_index", "evidence", "identity", "service_address")
MODE_REQUIRED_CATEGORIES = {
    "lawyer_agent": ("authority", "lawyer_certificate", "law_firm_letter", "agent_identity"),
    "legal_representative": ("legal_rep_identity", "legal_rep_certificate"),
    "employee_agent": ("authority", "agent_identity"),
    "self": (),
}


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _loads(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return fallback


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _category_from_name(filename: str) -> str:
    if "起诉状" in filename or "诉状" in filename:
        return "complaint"
    if any(token in filename for token in ("证据目录", "证据清单", "证据索引")):
        return "evidence_index"
    if any(token in filename for token in ("送达地址", "地址确认书")):
        return "service_address"
    if any(token in filename for token in ("法定代表人身份证明书", "法人身份证明书")):
        return "legal_rep_certificate"
    if any(token in filename for token in ("法定代表人身份证", "法人身份证")):
        return "legal_rep_identity"
    if any(token in filename for token in ("律师执业证", "律师证")):
        return "lawyer_certificate"
    if any(token in filename for token in ("律师事务所函", "律所函", "所函")):
        return "law_firm_letter"
    if any(token in filename for token in ("代理人身份证", "经办人身份证")):
        return "agent_identity"
    if any(token in filename for token in ("授权委托", "委托书")):
        return "authority"
    if any(token in filename for token in ("营业执照", "身份证", "主体资格", "登记", "信用代码")):
        return "identity"
    if any(token in filename for token in ("证据", "合同", "发票", "对账", "函", "聊天", "记录")):
        return "evidence"
    return "other"


def _material_label(category: str) -> str:
    return MATERIAL_LABELS.get(category, "材料")


def _required_categories(representation_mode: str) -> tuple[str, ...]:
    mode = representation_mode if representation_mode in REPRESENTATION_MODES else "lawyer_agent"
    return BASE_REQUIRED_CATEGORIES + MODE_REQUIRED_CATEGORIES[mode]


def _ensure_schema(get_db: Callable[[], Any]) -> None:
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS case_manager_filing_drafts (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              case_id INTEGER NOT NULL UNIQUE,
              filing_type TEXT NOT NULL DEFAULT 'civil_first_instance',
              status TEXT NOT NULL DEFAULT 'draft',
              court_name TEXT DEFAULT '', cause TEXT DEFAULT '', claim_amount TEXT DEFAULT '',
              lawsuit_request TEXT DEFAULT '', representation_mode TEXT NOT NULL DEFAULT 'lawyer_agent', authority_confirmed INTEGER NOT NULL DEFAULT 0,
              court_confirmed INTEGER NOT NULL DEFAULT 0, submitted_reference TEXT DEFAULT '',
              official_case_number TEXT DEFAULT '', review_comment TEXT DEFAULT '',
              package_json TEXT DEFAULT '{}', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              submitted_at TEXT DEFAULT '', filed_at TEXT DEFAULT '',
              FOREIGN KEY(case_id) REFERENCES case_manager_cases(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS case_manager_filing_materials (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              draft_id INTEGER NOT NULL, category TEXT NOT NULL DEFAULT 'other', label TEXT DEFAULT '',
              required INTEGER NOT NULL DEFAULT 0, selected INTEGER NOT NULL DEFAULT 1,
              source_file_id INTEGER, filename TEXT DEFAULT '', absolute_path TEXT DEFAULT '',
              sha256 TEXT DEFAULT '', size_bytes INTEGER DEFAULT 0, mime_type TEXT DEFAULT '',
              locked INTEGER NOT NULL DEFAULT 0, metadata_json TEXT DEFAULT '{}', sort_order INTEGER DEFAULT 0,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              FOREIGN KEY(draft_id) REFERENCES case_manager_filing_drafts(id) ON DELETE CASCADE
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_filing_material_source
              ON case_manager_filing_materials(draft_id, source_file_id) WHERE source_file_id IS NOT NULL;
            CREATE TABLE IF NOT EXISTS case_manager_filing_logs (
              id INTEGER PRIMARY KEY AUTOINCREMENT, draft_id INTEGER NOT NULL, action TEXT NOT NULL,
              summary TEXT DEFAULT '', detail_json TEXT DEFAULT '{}', created_at TEXT NOT NULL,
              FOREIGN KEY(draft_id) REFERENCES case_manager_filing_drafts(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_filing_logs_draft_time
              ON case_manager_filing_logs(draft_id, created_at DESC, id DESC);
        """)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(case_manager_filing_drafts)").fetchall()}
        if "representation_mode" not in columns:
            conn.execute("ALTER TABLE case_manager_filing_drafts ADD COLUMN representation_mode TEXT NOT NULL DEFAULT 'lawyer_agent'")
        conn.commit()


def _log(conn: Any, draft_id: int, action: str, summary: str, detail: Any = None) -> None:
    conn.execute(
        "INSERT INTO case_manager_filing_logs(draft_id,action,summary,detail_json,created_at) VALUES(?,?,?,?,?)",
        (draft_id, action, summary, _json(detail or {}), _now()),
    )


def _case_exists(conn: Any, case_id: int) -> bool:
    return bool(conn.execute("SELECT 1 FROM case_manager_cases WHERE id=?", (case_id,)).fetchone())


def _party_snapshot(conn: Any, case_id: int) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(
        "SELECT party_group,role,name,credit_code FROM case_manager_parties WHERE case_id=? ORDER BY sort_order,id",
        (case_id,),
    ).fetchall()]


def _draft_dict(conn: Any, row: Any) -> dict[str, Any]:
    if not row:
        raise HTTPException(status_code=404, detail="预立案草稿不存在")
    item = dict(row)
    item["authority_confirmed"] = bool(item["authority_confirmed"])
    item["court_confirmed"] = bool(item["court_confirmed"])
    item["representation_mode"] = item.get("representation_mode") or "lawyer_agent"
    item["representation_mode_label"] = REPRESENTATION_MODES.get(item["representation_mode"], REPRESENTATION_MODES["lawyer_agent"])
    item["status_label"] = STATUS_LABELS.get(item["status"], item["status"])
    item["package"] = _loads(item.pop("package_json", "{}"), {})
    item["parties"] = _party_snapshot(conn, int(item["case_id"]))
    item["materials"] = []
    for material in conn.execute(
        "SELECT * FROM case_manager_filing_materials WHERE draft_id=? ORDER BY required DESC,sort_order,id",
        (item["id"],),
    ).fetchall():
        value = dict(material)
        value["required"] = bool(value["required"]); value["selected"] = bool(value["selected"]); value["locked"] = bool(value["locked"])
        value["exists"] = bool(value["absolute_path"]) and Path(value["absolute_path"]).is_file()
        value["metadata"] = _loads(value.pop("metadata_json", "{}"), {})
        item["materials"].append(value)
    item["logs"] = []
    for log in conn.execute(
        "SELECT * FROM case_manager_filing_logs WHERE draft_id=? ORDER BY id DESC LIMIT 50", (item["id"],)
    ).fetchall():
        log_item = dict(log)
        log_item["detail"] = _loads(log_item.get("detail_json"), {})
        item["logs"].append(log_item)
    return item


def _upsert_default_materials(conn: Any, draft_id: int, case_id: int) -> None:
    # 先放入不可删除的必备槽位；律师可关联本地文件或保留为空以便明确提示。
    draft = conn.execute("SELECT representation_mode FROM case_manager_filing_drafts WHERE id=?", (draft_id,)).fetchone()
    required_categories = set(_required_categories(_norm(draft["representation_mode"]) if draft else "lawyer_agent"))
    for index, (category, label) in enumerate(MATERIAL_LABELS.items()):
        if category == "other":
            continue
        conn.execute("""INSERT INTO case_manager_filing_materials
          (draft_id,category,label,required,selected,sort_order,created_at,updated_at)
          SELECT ?,?,?,?,0,?,?,? WHERE NOT EXISTS(
            SELECT 1 FROM case_manager_filing_materials WHERE draft_id=? AND category=? AND source_file_id IS NULL
          )""", (draft_id, category, label, int(category in required_categories), index, _now(), _now(), draft_id, category))
    try:
        files = conn.execute(
            "SELECT id,filename,absolute_path,metadata_json,created_at FROM case_manager_files WHERE case_id=? ORDER BY id", (case_id,)
        ).fetchall()
    except Exception:
        files = []
    for index, file_row in enumerate(files, start=len(MATERIAL_LABELS)):
        filename = _norm(file_row["filename"])
        category = _category_from_name(filename)
        required = 1 if category in required_categories else 0
        # 同类别的文件可作为补充材料；必备槽位仍用于明示是否已满足。
        conn.execute("""INSERT OR IGNORE INTO case_manager_filing_materials
          (draft_id,category,label,required,selected,source_file_id,filename,absolute_path,metadata_json,sort_order,created_at,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
          (draft_id, category, _material_label(category), required, 1, file_row["id"], filename,
           _norm(file_row["absolute_path"]), file_row["metadata_json"] or "{}", index, _now(), _now()))
    conn.execute("UPDATE case_manager_filing_materials SET required=?,updated_at=? WHERE draft_id=? AND source_file_id IS NULL AND category=?",
                 (0, _now(), draft_id, "other"))
    for category in MATERIAL_LABELS:
        if category == "other":
            continue
        conn.execute("UPDATE case_manager_filing_materials SET required=?,updated_at=? WHERE draft_id=? AND category=?",
                     (int(category in required_categories), _now(), draft_id, category))


def _validate(conn: Any, draft_id: int) -> dict[str, list[str]]:
    draft = _draft_dict(conn, conn.execute("SELECT * FROM case_manager_filing_drafts WHERE id=?", (draft_id,)).fetchone())
    blockers: list[str] = []
    warnings: list[str] = []
    if not draft["court_name"] or not draft["court_confirmed"]:
        blockers.append("请确认受诉法院")
    if not draft["cause"]:
        blockers.append("请填写案由")
    if not draft["lawsuit_request"]:
        blockers.append("请填写诉讼请求")
    if draft["representation_mode"] != "self" and not draft["authority_confirmed"]:
        blockers.append("请确认已核验代理权限")
    plaintiffs = [p for p in draft["parties"] if p.get("party_group") == "client" or "原告" in _norm(p.get("role"))]
    defendants = [p for p in draft["parties"] if p.get("party_group") != "client" or "被告" in _norm(p.get("role"))]
    if not plaintiffs: blockers.append("请在案件中维护至少一名原告/委托人")
    if not defendants: blockers.append("请在案件中维护至少一名被告")
    if not draft["claim_amount"]: warnings.append("未填写标的额；非金钱给付案件可忽略")
    selected = [m for m in draft["materials"] if m["selected"]]
    for category in _required_categories(draft["representation_mode"]):
        label = _material_label(category)
        matches = [m for m in selected if m["category"] == category and m["exists"]]
        if not matches:
            blockers.append(f"缺少{label}")
    evidence_indexes = [m for m in selected if m["category"] == "evidence_index" and m["exists"]]
    evidence_files = [m for m in selected if m["category"] == "evidence" and m["exists"]]
    if evidence_indexes and evidence_files:
        warnings.append("已识别证据目录和证据文件；请在提交前核对编号、页码及排列顺序")
    for material in selected:
        path = Path(material["absolute_path"])
        if not path.is_file():
            blockers.append(f"材料不可读取：{material['filename'] or material['label']}")
            continue
        suffix = path.suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            blockers.append(f"材料格式不支持：{path.name}")
        elif path.stat().st_size > MAX_FILE_BYTES:
            blockers.append(f"材料超过 50MB：{path.name}")
    return {"blockers": list(dict.fromkeys(blockers)), "warnings": list(dict.fromkeys(warnings))}


def reconcile_filing_drafts(get_db: Callable[[], Any]) -> int:
    """将一张网已同步的“我的立案”状态映射回本地草稿，不访问官网。"""
    _ensure_schema(get_db)
    changed = 0
    with get_db() as conn:
        try:
            drafts = conn.execute("SELECT * FROM case_manager_filing_drafts WHERE status IN ('submitted','supplement')").fetchall()
            for draft in drafts:
                case = conn.execute("SELECT title FROM case_manager_cases WHERE id=?", (draft["case_id"],)).fetchone()
                if not case:
                    continue
                row = conn.execute("""SELECT * FROM case_manager_court_online_layy
                  WHERE linked_case_id=? OR (case_name<>'' AND case_name=?)
                  ORDER BY datetime(COALESCE(NULLIF(update_date,''),first_seen)) DESC,id DESC LIMIT 1""",
                  (draft["case_id"], case["title"])).fetchone()
                if not row:
                    continue
                status_text = " ".join(_norm(row[key]) for key in ("status", "review_comment") if key in row.keys())
                next_status = "submitted"
                if any(token in status_text for token in ("补正", "补充材料", "退回")):
                    next_status = "supplement"
                elif any(token in status_text for token in ("已立案", "受理", "审核通过")) or _norm(row["case_number"]):
                    next_status = "filed"
                elif any(token in status_text for token in ("不予", "不通过", "撤回", "失效")):
                    next_status = "failed"
                if next_status != draft["status"] or _norm(row["review_comment"]) != _norm(draft["review_comment"]):
                    conn.execute("""UPDATE case_manager_filing_drafts SET status=?,official_case_number=?,review_comment=?,
                      filed_at=CASE WHEN ?='filed' THEN ? ELSE filed_at END,updated_at=? WHERE id=?""",
                      (next_status, _norm(row["case_number"]), _norm(row["review_comment"]), next_status, _now(), _now(), draft["id"]))
                    _log(conn, draft["id"], "court_sync", f"一张网状态更新为“{STATUS_LABELS[next_status]}”", {"court_status": _norm(row["status"])})
                    changed += 1
            conn.commit()
        except Exception:
            return changed
    return changed


def register_filing_workspace_routes(app: Any, get_db: Callable[[], Any]) -> None:
    _ensure_schema(get_db)

    @app.get("/api/case-manager/filing-drafts")
    def list_filing_drafts():
        reconcile_filing_drafts(get_db)
        with get_db() as conn:
            rows = conn.execute("""SELECT d.*,c.title AS case_title FROM case_manager_filing_drafts d
              JOIN case_manager_cases c ON c.id=d.case_id ORDER BY datetime(d.updated_at) DESC,d.id DESC""").fetchall()
            items = []
            for row in rows:
                item = dict(row); item["status_label"] = STATUS_LABELS.get(item["status"], item["status"])
                item["blockers"] = _validate(conn, item["id"])["blockers"]
                items.append(item)
            return {"items": items, "status_labels": STATUS_LABELS}

    @app.post("/api/case-manager/cases/{case_id}/filing-draft")
    async def create_or_update_draft(case_id: int, request: Request):
        body = await request.json()
        with get_db() as conn:
            if not _case_exists(conn, case_id):
                raise HTTPException(status_code=404, detail="案件不存在")
            existing = conn.execute("SELECT * FROM case_manager_filing_drafts WHERE case_id=?", (case_id,)).fetchone()
            stamp = _now()
            if not existing:
                court = _norm(body.get("court_name"))
                cur = conn.execute("""INSERT INTO case_manager_filing_drafts
                  (case_id,court_name,cause,claim_amount,lawsuit_request,representation_mode,authority_confirmed,court_confirmed,created_at,updated_at)
                  VALUES(?,?,?,?,?,?,?,?,?,?)""", (case_id, court, _norm(body.get("cause")), _norm(body.get("claim_amount")),
                  _norm(body.get("lawsuit_request")), _representation_mode(body.get("representation_mode")), int(bool(body.get("authority_confirmed"))), int(bool(body.get("court_confirmed"))), stamp, stamp))
                draft_id = int(cur.lastrowid); _upsert_default_materials(conn, draft_id, case_id); _log(conn, draft_id, "created", "已从本地案件创建预立案草稿")
            else:
                draft_id = int(existing["id"])
                if existing["status"] not in {"draft", "ready", "supplement", "failed"}:
                    raise HTTPException(status_code=409, detail="已提交的草稿不能直接覆盖，请先按补正或撤回流程处理")
                fields = {key: body[key] for key in ("court_name", "cause", "claim_amount", "lawsuit_request") if key in body}
                if "representation_mode" in body:
                    fields["representation_mode"] = _representation_mode(body["representation_mode"])
                if "authority_confirmed" in body: fields["authority_confirmed"] = int(bool(body["authority_confirmed"]))
                if "court_confirmed" in body: fields["court_confirmed"] = int(bool(body["court_confirmed"]))
                if fields:
                    assignments = ",".join(f"{key}=?" for key in fields)
                    conn.execute(f"UPDATE case_manager_filing_drafts SET {assignments},updated_at=? WHERE id=?", [*_norm_values(fields), stamp, draft_id])
                    _log(conn, draft_id, "updated", "已更新预立案信息", {"fields": list(fields)})
                _upsert_default_materials(conn, draft_id, case_id)
            conn.commit()
            return _draft_dict(conn, conn.execute("SELECT * FROM case_manager_filing_drafts WHERE id=?", (draft_id,)).fetchone())

    @app.get("/api/case-manager/filing-drafts/{draft_id}")
    def get_filing_draft(draft_id: int):
        with get_db() as conn:
            return _draft_dict(conn, conn.execute("SELECT * FROM case_manager_filing_drafts WHERE id=?", (draft_id,)).fetchone())

    @app.post("/api/case-manager/filing-drafts/{draft_id}/validate")
    def validate_filing_draft(draft_id: int):
        with get_db() as conn:
            if not conn.execute("SELECT 1 FROM case_manager_filing_drafts WHERE id=?", (draft_id,)).fetchone():
                raise HTTPException(status_code=404, detail="预立案草稿不存在")
            return _validate(conn, draft_id)

    @app.post("/api/case-manager/filing-drafts/{draft_id}/package")
    def package_filing_draft(draft_id: int):
        with get_db() as conn:
            validation = _validate(conn, draft_id)
            if validation["blockers"]:
                raise HTTPException(status_code=422, detail="；".join(validation["blockers"]))
            materials = conn.execute("SELECT * FROM case_manager_filing_materials WHERE draft_id=? AND selected=1 ORDER BY sort_order,id", (draft_id,)).fetchall()
            manifest = []
            for item in materials:
                path = Path(item["absolute_path"]); digest = _sha256(path); size = path.stat().st_size
                conn.execute("UPDATE case_manager_filing_materials SET sha256=?,size_bytes=?,mime_type=?,locked=1,updated_at=? WHERE id=?",
                  (digest, size, mimetypes.guess_type(path.name)[0] or "application/octet-stream", _now(), item["id"]))
                manifest.append({"category": item["category"], "label": item["label"], "filename": path.name, "sha256": digest, "size_bytes": size})
            package = {"generated_at": _now(), "materials": manifest, "version": 1}
            conn.execute("UPDATE case_manager_filing_drafts SET status='ready',package_json=?,updated_at=? WHERE id=?", (_json(package), _now(), draft_id))
            _log(conn, draft_id, "package", "已生成并锁定提交材料清单", {"count": len(manifest)})
            conn.commit()
            return {"ok": True, "package": package, "status": "ready"}

    @app.post("/api/case-manager/filing-drafts/{draft_id}/mark-submitted")
    async def mark_filing_submitted(draft_id: int, request: Request):
        body = await request.json()
        with get_db() as conn:
            draft = conn.execute("SELECT * FROM case_manager_filing_drafts WHERE id=?", (draft_id,)).fetchone()
            if not draft:
                raise HTTPException(status_code=404, detail="预立案草稿不存在")
            if draft["status"] != "ready":
                raise HTTPException(status_code=409, detail="请先通过校验并生成提交材料清单")
            reference = _norm(body.get("reference"))
            conn.execute("UPDATE case_manager_filing_drafts SET status='submitted',submitted_reference=?,submitted_at=?,updated_at=? WHERE id=?",
              (reference, _now(), _now(), draft_id))
            _log(conn, draft_id, "marked_submitted", "律师已在官网完成提交，等待一张网同步审核结果", {"reference": reference})
            conn.commit()
            return {"ok": True, "status": "submitted", "status_label": STATUS_LABELS["submitted"]}

    @app.post("/api/case-manager/filing-drafts/{draft_id}/reopen")
    def reopen_filing_draft(draft_id: int):
        with get_db() as conn:
            draft = conn.execute("SELECT * FROM case_manager_filing_drafts WHERE id=?", (draft_id,)).fetchone()
            if not draft:
                raise HTTPException(status_code=404, detail="预立案草稿不存在")
            if draft["status"] not in {"supplement", "failed"}:
                raise HTTPException(status_code=409, detail="当前状态无需重新准备材料")
            conn.execute("UPDATE case_manager_filing_drafts SET status='draft',updated_at=? WHERE id=?", (_now(), draft_id))
            conn.execute("UPDATE case_manager_filing_materials SET locked=0,updated_at=? WHERE draft_id=?", (_now(), draft_id))
            _log(conn, draft_id, "reopened", "已解锁材料，待补正后重新确认")
            conn.commit()
            return {"ok": True, "status": "draft"}


def _norm_values(fields: dict[str, Any]) -> list[Any]:
    result: list[Any] = []
    for key, value in fields.items():
        result.append(int(bool(value)) if key in {"authority_confirmed", "court_confirmed"} else _norm(value))
    return result


def _representation_mode(value: Any) -> str:
    mode = _norm(value) or "lawyer_agent"
    return mode if mode in REPRESENTATION_MODES else "lawyer_agent"
