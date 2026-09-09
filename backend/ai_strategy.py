"""Versioned, user-editable execution policy for AI enhancement.

The editable document intentionally contains data only.  Security invariants stay in
code and are never interpreted as executable expressions or prompt fragments.
"""
from __future__ import annotations

import copy
import datetime
import json
import re
import sqlite3
from typing import Any, Callable, Dict, Iterable, List, Optional


ALL_MCP_SOURCES = (
    "aluris", "national_law", "yuandian_case", "yuandian_law",
    "pkulaw_case", "pkulaw_law", "qcc_company", "qcc_risk",
    "qcc_case", "qcc_law", "finchina", "quark_drive", "qq_mail",
    "qq_exmail",
)

DEFAULT_STRATEGY: Dict[str, Any] = {
    "schema_version": 4,
    "classification": {
        "case_enabled": True,
        "law_enabled": True,
        "integrate_enabled": True,
        "exact_provision_enabled": True,
        "case_keywords": ["案例", "类案", "裁判", "判决", "判例", "案号", "法院观点", "司法实践", "支持与不支持", "相反观点", "裁判要旨"],
        "law_keywords": ["法律", "法规", "法条", "规定", "条文", "司法解释", "效力", "原文"],
        "integrate_keywords": ["整理", "汇总", "列举", "全部", "所有", "梳理", "总结", "归纳", "逐一", "逐条", "逐项", "逐点", "小点", "要点", "有哪些", "有什么", "哪些规定", "哪些条文", "哪些条款", "有何规定", "如何规定", "相关规定", "相关条文", "原文", "规定了什么", "规定是什么", "是如何", "怎么规定"],
        "priority": ["scope", "meta_casual", "forced_case", "exact_provision", "case", "law", "integrate", "ordinary"],
    },
    "retrieval": {
        "case_top_k": 8,
        "ordinary_top_k": 20,
        "collection_top_k": 6,
        "case_total_budget": 16000,
        "ordinary_total_budget": 30000,
        "collection_total_budget": 60000,
        "case_per_article_limit": 6000,
        "ordinary_per_article_limit": 10000,
        "collection_per_article_limit": 10000,
        "authority_order": ["指导案例", "参考案例", "最高人民法院", "广东省高级人民法院", "其他高级人民法院", "其他法院"],
    },
    "routing": {
        "allowed_sources": list(ALL_MCP_SOURCES),
        "max_auto_sources": 3,
        "mandatory": {
            "company_info": ["qcc_company"],
            "company_risk": ["qcc_risk"],
        },
    },
    "generation": {
        "require_local_citations": True,
        "missing_field_policy": "mark_missing",
        "forbid_evidence_fabrication": True,
        "ordinary_temperature": 0.3,
        "legal_temperature": 0.12,
        "ordinary_max_tokens": 2000,
        "integrate_max_tokens": 4000,
        "additional_instruction": "",
    },
    "locked_security": {
        "mcp_only_no_local_fallback": True,
        "never_expose_secrets": True,
        "never_expose_chain_of_thought": True,
        "never_fabricate_source_text": True,
        "executable_code_forbidden": True,
    },
}

EDITABLE_SECTIONS = {"classification", "retrieval", "routing", "generation"}
PRIORITY_STEPS = set(DEFAULT_STRATEGY["classification"]["priority"])


def utcnow() -> str:
    return datetime.datetime.now().isoformat()


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ai_strategy_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_label TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'archived',
            config_json TEXT NOT NULL,
            change_summary TEXT DEFAULT '',
            source_version_id INTEGER,
            is_system INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (source_version_id) REFERENCES ai_strategy_versions(id)
        );
        CREATE TABLE IF NOT EXISTS ai_strategy_state (
            singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
            active_version_id INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (active_version_id) REFERENCES ai_strategy_versions(id)
        );
        CREATE INDEX IF NOT EXISTS idx_ai_strategy_versions_created
            ON ai_strategy_versions(created_at DESC);
    """)
    row = conn.execute("SELECT id FROM ai_strategy_versions WHERE is_system=1 ORDER BY id LIMIT 1").fetchone()
    if row is None:
        cursor = conn.execute(
            "INSERT INTO ai_strategy_versions(version_label,status,config_json,change_summary,is_system,created_at) VALUES(?,?,?,?,1,?)",
            ("系统默认 v1.0", "active", json.dumps(DEFAULT_STRATEGY, ensure_ascii=False), "系统内置默认策略", utcnow()),
        )
        system_id = cursor.lastrowid
    else:
        system_id = int(row[0])
    state = conn.execute("SELECT active_version_id FROM ai_strategy_state WHERE singleton_id=1").fetchone()
    if state is None:
        conn.execute(
            "INSERT INTO ai_strategy_state(singleton_id,active_version_id,updated_at) VALUES(1,?,?)",
            (system_id, utcnow()),
        )
    conn.commit()


def _clean_keywords(value: Any, path: str, errors: List[dict]) -> List[str]:
    if not isinstance(value, list):
        errors.append({"path": path, "message": "必须是关键词列表"})
        return []
    result: List[str] = []
    for index, item in enumerate(value):
        keyword = str(item or "").strip()
        if not keyword:
            errors.append({"path": f"{path}.{index}", "message": "关键词不能为空"})
        elif len(keyword) > 30:
            errors.append({"path": f"{path}.{index}", "message": "单个关键词不能超过30个字"})
        elif keyword not in result:
            result.append(keyword)
    return result


def validate_config(candidate: Any) -> Dict[str, Any]:
    errors: List[dict] = []
    warnings: List[dict] = []
    if not isinstance(candidate, dict):
        return {"valid": False, "errors": [{"path": "config", "message": "策略内容格式无效"}], "warnings": []}
    unknown = set(candidate) - (EDITABLE_SECTIONS | {"schema_version", "locked_security"})
    if unknown:
        errors.append({"path": "config", "message": "包含不支持的设置：" + "、".join(sorted(unknown))})
    config = copy.deepcopy(DEFAULT_STRATEGY)
    for section in EDITABLE_SECTIONS:
        value = candidate.get(section)
        if not isinstance(value, dict):
            errors.append({"path": section, "message": "该设置组不能为空"})
            continue
        config[section].update(copy.deepcopy(value))
    c = config["classification"]
    for name in ("case_keywords", "law_keywords", "integrate_keywords"):
        c[name] = _clean_keywords(c.get(name), f"classification.{name}", errors)
        if not c[name]:
            errors.append({"path": f"classification.{name}", "message": "至少保留一个关键词"})
    priority = c.get("priority")
    if not isinstance(priority, list) or set(priority) != PRIORITY_STEPS or len(priority) != len(PRIORITY_STEPS):
        errors.append({"path": "classification.priority", "message": "处理顺序必须包含每个固定阶段且不能重复"})
    overlap = (set(c["case_keywords"]) & set(c["law_keywords"])) - {"原文"}
    if overlap:
        warnings.append({"path": "classification", "message": "案例与法规关键词有重叠，将同时触发：" + "、".join(sorted(overlap))})

    r = config["retrieval"]
    limits = {
        "case_top_k": (1, 30), "ordinary_top_k": (1, 50), "collection_top_k": (1, 30),
        "case_total_budget": (4000, 80000), "ordinary_total_budget": (4000, 100000),
        "collection_total_budget": (8000, 150000), "case_per_article_limit": (1000, 30000),
        "ordinary_per_article_limit": (1000, 40000), "collection_per_article_limit": (1000, 40000),
    }
    for field, (low, high) in limits.items():
        value = r.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
            errors.append({"path": f"retrieval.{field}", "message": f"请输入 {low} 至 {high} 之间的整数"})
    if isinstance(r.get("case_total_budget"), int) and isinstance(r.get("case_per_article_limit"), int) and r["case_per_article_limit"] > r["case_total_budget"]:
        errors.append({"path": "retrieval.case_per_article_limit", "message": "单篇预算不能超过总预算"})
    if isinstance(r.get("ordinary_total_budget"), int) and isinstance(r.get("ordinary_per_article_limit"), int) and r["ordinary_per_article_limit"] > r["ordinary_total_budget"]:
        errors.append({"path": "retrieval.ordinary_per_article_limit", "message": "单篇预算不能超过总预算"})
    if r.get("ordinary_total_budget", 0) > 60000:
        warnings.append({"path": "retrieval.ordinary_total_budget", "message": "较大的证据预算可能增加响应时间和模型费用"})

    routing = config["routing"]
    allowed = routing.get("allowed_sources")
    if not isinstance(allowed, list) or len(set(allowed)) != len(allowed):
        errors.append({"path": "routing.allowed_sources", "message": "来源列表不能为空或重复"})
        allowed = []
    # v2 新增夸克网盘来源。只迁移旧版本，用户在 v2 策略中主动关闭后不再补回。
    if int(candidate.get("schema_version") or 1) < 2 and "quark_drive" not in allowed:
        allowed.append("quark_drive")
        routing["allowed_sources"] = allowed
    # v3 新增 QQ 邮箱来源。只迁移旧版本，用户在 v3 策略中主动关闭后不再补回。
    if int(candidate.get("schema_version") or 1) < 3 and "qq_mail" not in allowed:
        allowed.append("qq_mail")
        routing["allowed_sources"] = allowed
    # v4 新增腾讯企业邮箱来源。只迁移旧版本，用户在 v4 策略中主动关闭后不再补回。
    if int(candidate.get("schema_version") or 1) < 4 and "qq_exmail" not in allowed:
        allowed.append("qq_exmail")
        routing["allowed_sources"] = allowed
    invalid_sources = set(allowed) - set(ALL_MCP_SOURCES)
    if invalid_sources:
        errors.append({"path": "routing.allowed_sources", "message": "未知来源：" + "、".join(sorted(invalid_sources))})
    max_sources = routing.get("max_auto_sources")
    if not isinstance(max_sources, int) or isinstance(max_sources, bool) or not 1 <= max_sources <= 5:
        errors.append({"path": "routing.max_auto_sources", "message": "自动调用来源数必须在1至5之间"})
    mandatory = routing.get("mandatory")
    if not isinstance(mandatory, dict):
        errors.append({"path": "routing.mandatory", "message": "必选来源设置无效"})
    else:
        for scenario in ("company_info", "company_risk"):
            values = mandatory.get(scenario, [])
            if not isinstance(values, list) or set(values) - set(allowed):
                errors.append({"path": f"routing.mandatory.{scenario}", "message": "必选来源必须包含在允许来源内"})

    g = config["generation"]
    for field in ("ordinary_temperature", "legal_temperature"):
        value = g.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
            errors.append({"path": f"generation.{field}", "message": "温度必须在0至1之间"})
    for field in ("ordinary_max_tokens", "integrate_max_tokens"):
        value = g.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or not 500 <= value <= 12000:
            errors.append({"path": f"generation.{field}", "message": "回答长度必须在500至12000之间"})
    instruction = str(g.get("additional_instruction") or "").strip()
    if len(instruction) > 1000:
        errors.append({"path": "generation.additional_instruction", "message": "附加要求不能超过1000个字"})
    suspicious = re.compile(r"(<script|javascript:|\b(import|exec|eval|subprocess|os\.system)\b)", re.I)
    if suspicious.search(instruction):
        errors.append({"path": "generation.additional_instruction", "message": "附加要求不能包含代码或可执行指令"})
    g["additional_instruction"] = instruction
    config["locked_security"] = copy.deepcopy(DEFAULT_STRATEGY["locked_security"])
    config["schema_version"] = 4
    return {"valid": not errors, "errors": errors, "warnings": warnings, "normalized_config": config}


def _row_payload(row: sqlite3.Row, include_config: bool = True) -> dict:
    payload = {
        "id": int(row["id"]), "version_label": row["version_label"],
        "status": row["status"], "change_summary": row["change_summary"] or "",
        "source_version_id": row["source_version_id"], "is_system": bool(row["is_system"]),
        "created_at": row["created_at"],
    }
    if include_config:
        payload["config"] = json.loads(row["config_json"])
    return payload


def active_strategy(conn: sqlite3.Connection) -> dict:
    ensure_schema(conn)
    row = conn.execute(
        "SELECT v.* FROM ai_strategy_state s JOIN ai_strategy_versions v ON v.id=s.active_version_id WHERE s.singleton_id=1"
    ).fetchone()
    try:
        payload = _row_payload(row)
        checked = validate_config(payload["config"])
        if not checked["valid"]:
            raise ValueError("invalid active strategy")
        payload["config"] = checked["normalized_config"]
        payload["recovery_notice"] = ""
        return payload
    except Exception:
        valid_rows = conn.execute("SELECT * FROM ai_strategy_versions ORDER BY is_system ASC, id DESC").fetchall()
        for candidate in valid_rows:
            try:
                payload = _row_payload(candidate)
                checked = validate_config(payload["config"])
                if checked["valid"]:
                    conn.execute("UPDATE ai_strategy_versions SET status='archived' WHERE status='active'")
                    conn.execute("UPDATE ai_strategy_versions SET status='active' WHERE id=?", (payload["id"],))
                    conn.execute("UPDATE ai_strategy_state SET active_version_id=?,updated_at=? WHERE singleton_id=1", (payload["id"], utcnow()))
                    conn.commit()
                    payload["config"] = checked["normalized_config"]
                    payload["recovery_notice"] = "原生效策略无法读取，系统已自动恢复最近一个有效版本。"
                    return payload
            except Exception:
                continue
        raise RuntimeError("no valid AI strategy")


def strategy_snapshot(get_db: Callable[[], sqlite3.Connection]) -> dict:
    conn = get_db()
    try:
        return copy.deepcopy(active_strategy(conn))
    finally:
        conn.close()


def list_versions(conn: sqlite3.Connection, limit: int = 50) -> List[dict]:
    ensure_schema(conn)
    rows = conn.execute("SELECT * FROM ai_strategy_versions ORDER BY id DESC LIMIT ?", (max(1, min(limit, 100)),)).fetchall()
    return [_row_payload(row, include_config=False) for row in rows]


def create_and_activate(conn: sqlite3.Connection, config: Any, summary: str, base_version_id: Optional[int]) -> dict:
    current = active_strategy(conn)
    if base_version_id is not None and int(base_version_id) != current["id"]:
        raise ValueError("策略已被其他修改更新，请重新载入当前版本后再保存")
    checked = validate_config(config)
    if not checked["valid"]:
        return checked
    latest = conn.execute("SELECT COUNT(*) FROM ai_strategy_versions WHERE is_system=0").fetchone()[0]
    label = f"自定义 v{latest + 1}.0"
    now = utcnow()
    with conn:
        cursor = conn.execute(
            "INSERT INTO ai_strategy_versions(version_label,status,config_json,change_summary,source_version_id,is_system,created_at) VALUES(?,?,?,?,?,0,?)",
            (label, "active", json.dumps(checked["normalized_config"], ensure_ascii=False), str(summary or "更新 AI 增强策略")[:200], current["id"], now),
        )
        new_id = cursor.lastrowid
        conn.execute("UPDATE ai_strategy_versions SET status='archived' WHERE id<>? AND status='active'", (new_id,))
        conn.execute("UPDATE ai_strategy_state SET active_version_id=?,updated_at=? WHERE singleton_id=1", (new_id, now))
        # Keep the most recent 50 custom versions plus every version referenced
        # by saved answer history. The system version is never removed.
        has_messages = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ai_ask_messages'"
        ).fetchone()
        referenced = set()
        if has_messages:
            referenced = {
                int(row[0]) for row in conn.execute(
                    "SELECT DISTINCT strategy_version_id FROM ai_ask_messages WHERE strategy_version_id IS NOT NULL"
                ).fetchall()
            }
        recent = {
            int(row[0]) for row in conn.execute(
                "SELECT id FROM ai_strategy_versions WHERE is_system=0 ORDER BY id DESC LIMIT 50"
            ).fetchall()
        }
        protected = referenced | recent | {int(new_id)}
        placeholders = ",".join("?" for _ in protected)
        conn.execute(
            f"DELETE FROM ai_strategy_versions WHERE is_system=0 AND status<>'active' AND id NOT IN ({placeholders})",
            tuple(sorted(protected)),
        )
    return {"valid": True, "warnings": checked["warnings"], "strategy": active_strategy(conn)}


def activate_as_new_version(conn: sqlite3.Connection, version_id: int) -> dict:
    source = conn.execute("SELECT * FROM ai_strategy_versions WHERE id=?", (version_id,)).fetchone()
    if source is None:
        raise LookupError("指定策略版本不存在")
    checked = validate_config(json.loads(source["config_json"]))
    if not checked["valid"]:
        raise ValueError("指定版本已损坏，不能恢复")
    return create_and_activate(conn, checked["normalized_config"], f"恢复到 {source['version_label']}", active_strategy(conn)["id"])


def classify_question(question: str, config: dict, *, forced_case: bool = False, is_meta: bool = False, is_casual: bool = False) -> dict:
    text = str(question or "").strip()
    c = config["classification"]
    case_hits = [item for item in c["case_keywords"] if item in text]
    law_hits = [item for item in c["law_keywords"] if item in text]
    integrate_hits = [item for item in c["integrate_keywords"] if item in text]
    # "逐一提炼 31 个小点"一类请求本质上要求穷尽式阅读。这个最小集合
    # 固化在代码中，保证已保存的旧策略版本即使没有新增关键词也不会退化为
    # 普通的 Top-K 段落问答。
    exhaustive_markers = ("逐一", "逐条", "逐项", "逐点", "小点", "要点", "每一")
    for marker in exhaustive_markers:
        if marker in text and marker not in integrate_hits:
            integrate_hits.append(marker)
    case_intent = bool(c["case_enabled"] and (forced_case or case_hits)) and not is_meta and not is_casual
    law_intent = bool(c["law_enabled"] and (forced_case or law_hits)) and not is_meta and not is_casual
    integrate = bool(c["integrate_enabled"] and integrate_hits) and not is_meta and not is_casual
    candidates = {
        "meta_casual": "知识库元信息" if is_meta else ("日常闲聊" if is_casual else ""),
        "forced_case": "案例任务" if forced_case else "",
        "case": "案例任务" if case_intent else "",
        "law": "法规任务" if law_intent else "",
        "integrate": "整合型问答" if integrate else "",
        "ordinary": "普通法律问答",
    }
    route = "普通法律问答"
    for step in c["priority"]:
        if candidates.get(step):
            route = candidates[step]
            break
    return {
        "route": route, "case_intent": case_intent, "law_intent": law_intent,
        "is_integrate": integrate, "case_hits": case_hits, "law_hits": law_hits,
        "integrate_hits": integrate_hits, "forced_case": bool(forced_case),
    }


def simulate(question: str, config: dict, *, source_mode: str = "hybrid", case_search: bool = False) -> dict:
    classification = classify_question(question, config, forced_case=case_search)
    route = classification["route"]
    routing = config["routing"]
    proposed: List[str] = []
    text = str(question or "")
    company_info_markers = ("发票", "开票", "税号", "纳税人识别号", "开户行", "工商信息", "注册资本", "法定代表人", "股东", "实控人", "联系方式", "企业年报")
    company_risk_markers = ("失信", "被执行", "限高", "欠税", "司法风险", "经营异常")
    if source_mode == "hybrid":
        if any(item in text for item in company_info_markers): proposed.extend(routing["mandatory"]["company_info"])
        if any(item in text for item in company_risk_markers): proposed.extend(routing["mandatory"]["company_risk"])
        if classification["case_intent"]: proposed.extend(["aluris", "yuandian_case", "pkulaw_case"])
        if classification["law_intent"]: proposed.extend(["national_law", "yuandian_law"])
        proposed = [item for item in dict.fromkeys(proposed) if item in routing["allowed_sources"]][:routing["max_auto_sources"]]
    elif source_mode.startswith("mcp:"):
        proposed = [item for item in source_mode[4:].split(",") if item in routing["allowed_sources"]]
    retrieval = config["retrieval"]
    case = classification["case_intent"]
    events = [
        {"stage": "范围", "matched": True, "detail": "仅本地知识库" if source_mode == "local_only" else ("用户指定 MCP" if source_mode.startswith("mcp:") else "综合问答")},
        {"stage": "分类", "matched": True, "detail": route},
        {"stage": "案例规则", "matched": classification["case_intent"], "detail": "、".join(classification["case_hits"]) or ("案例检索开关" if case_search else "未命中")},
        {"stage": "法规规则", "matched": classification["law_intent"], "detail": "、".join(classification["law_hits"]) or "未命中"},
        {"stage": "整合规则", "matched": classification["is_integrate"], "detail": "、".join(classification["integrate_hits"]) or "未命中"},
        {"stage": "工具路由", "matched": bool(proposed), "detail": "、".join(proposed) or "本次不拟调用 MCP"},
    ]
    return {
        "classification": classification,
        "events": events,
        "proposed_mcp_sources": proposed,
        "retrieval_plan": {
            "top_k": retrieval["case_top_k"] if case else retrieval["ordinary_top_k"],
            "total_budget": retrieval["case_total_budget"] if case else retrieval["ordinary_total_budget"],
            "per_article_limit": retrieval["case_per_article_limit"] if case else retrieval["ordinary_per_article_limit"],
        },
        "generation": {
            "temperature": config["generation"]["legal_temperature"] if (case or classification["law_intent"]) else config["generation"]["ordinary_temperature"],
            "require_local_citations": config["generation"]["require_local_citations"],
            "missing_field_policy": config["generation"]["missing_field_policy"],
        },
        "external_calls_performed": False,
    }
