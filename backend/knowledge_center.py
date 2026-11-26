"""HTTP routes for the Legal Knowledge Center and article relations."""

from __future__ import annotations

import datetime
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Callable, List, NamedTuple, Optional

import aiofiles
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import knowledge_search
from .knowledge_issue_merges import (
    _knowledge_claim_row,
    _knowledge_issue_row,
    _merge_knowledge_issue_records,
    _unmerge_knowledge_issue_records,
)
from .knowledge_jobs import KnowledgeJobs
from .knowledge_relations import (
    LONG_ARTICLE_CHARS as RELATION_LONG_ARTICLE_CHARS,
    ai_scan_allowed as relation_ai_scan_allowed,
    authorize_ai_scan as authorize_relation_ai_scan,
    article_relations as get_article_relations,
    backfill_job as get_relation_backfill_job,
    create_backfill_job as create_relation_backfill_job,
    mark_ai_prompted as mark_relation_ai_prompted,
    mark_article_opened as mark_relation_article_opened,
    node_detail as get_relation_node_detail,
    relation_labels as knowledge_relation_labels,
    review_mention as review_knowledge_mention,
    scan_article_rules as scan_article_relation_rules,
    scan_estimate as relation_scan_estimate,
    search_nodes as search_relation_nodes,
)
from .legal_knowledge import (
    CLAIM_STATUSES as KNOWLEDGE_CLAIM_STATUSES,
    CLAIM_TYPES as KNOWLEDGE_CLAIM_TYPES,
    RELATION_TYPES as KNOWLEDGE_RELATION_TYPES,
    article_knowledge,
    article_knowledge_domains,
    audit as audit_knowledge_change,
    claim_detail as get_knowledge_claim_detail,
    content_hash as knowledge_content_hash,
    is_knowledge_article,
    knowledge_candidate_ids,
    knowledge_category_rows,
    normalize_text as normalize_knowledge_text,
)
from .performance_monitor import measure_phase


class KnowledgeClaimUpdate(BaseModel):
    statement: Optional[str] = None
    claim_type: Optional[str] = None
    conditions_text: Optional[str] = None
    exceptions_text: Optional[str] = None
    procedural_stage: Optional[str] = None
    jurisdiction: Optional[str] = None
    court_level: Optional[str] = None
    authority_type: Optional[str] = None
    authority_level: Optional[str] = None
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    reviewer_note: Optional[str] = None
    issue_titles: Optional[List[str]] = None
    relations: Optional[List[dict]] = None


class KnowledgeReviewPayload(BaseModel):
    action: str
    note: str = ""


class KnowledgeMergePayload(BaseModel):
    target_id: Optional[int] = None
    undo: bool = False


class KnowledgeBatchPayload(BaseModel):
    force: bool = False
    domain: str = ""


class KnowledgeArticleSelectionPayload(BaseModel):
    article_ids: List[int] = []


class KnowledgeOrganizePayload(BaseModel):
    domain: str


class KnowledgeSuggestionReviewPayload(BaseModel):
    action: str


class KnowledgeIssueCategoryPayload(BaseModel):
    category_id: int


class KnowledgeMentionReviewPayload(BaseModel):
    status: str
    relation_type: Optional[str] = None
    target_node_id: Optional[int] = None


class KnowledgeLearningStatePayload(BaseModel):
    is_favorite: Optional[bool] = None
    is_suspended: Optional[bool] = None


class KnowledgeLearningReviewPayload(BaseModel):
    grade: str
    case_id: Optional[int] = None


class KnowledgeKnowledgeUsePayload(BaseModel):
    action: str = "open"
    case_id: Optional[int] = None


class KnowledgeUsageEventPayload(BaseModel):
    event_type: str
    claim_id: Optional[int] = None
    issue_id: Optional[int] = None
    case_id: Optional[int] = None
    result_count: int = 0


class RelationScanPayload(BaseModel):
    use_ai: bool = False
    confirmed_long_article_cost: bool = False
    dismiss_ai_prompt: bool = False


class RelationBackfillControlPayload(BaseModel):
    action: str = "start"


def _knowledge_job_dict(row: sqlite3.Row) -> dict:
    item = dict(row)
    try:
        item["warnings"] = json.loads(item.pop("warnings_json") or "[]")
    except Exception:
        item["warnings"] = []
    return item


def _knowledge_now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _knowledge_search_tokens(value: str) -> list[str]:
    raw_tokens = re.findall(r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", value or "")
    tokens: set[str] = set()
    for token in raw_tokens:
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            if len(token) <= 8:
                tokens.add(token)
            for width in (2, 3, 4, 5, 6):
                if len(token) >= width:
                    tokens.update(token[index:index + width] for index in range(len(token) - width + 1))
        else:
            tokens.add(token.casefold())
    stop = {"什么", "哪些", "如何", "是否", "可以", "问题", "规定", "关于", "以及", "相关"}
    return [token for token in tokens if token not in stop]


_KNOWLEDGE_CASE_TOPIC_ALIASES = {
    # 只收录能表达法律争点的短语；“公司”“合同”“执行”等单独出现时信息量太低。
    "建设工程": ("建设工程", "施工合同", "工程价款", "工程款", "工程质量", "实际施工人", "挂靠", "招标投标", "发包人", "承包人", "工程结算"),
    "强制执行": ("强制执行", "执行案", "执行案件", "执行程序", "执行依据", "恢复执行", "执行立案", "被执行人", "查封", "拍卖", "终本", "执恢", "执保", "执转破"),
    "执行异议": ("执行异议", "执行异议之诉", "案外人异议", "执行行为异议", "执行复议", "执异", "排除执行"),
    "合同法": ("借款合同", "租赁合同", "买卖合同", "服务合同", "法律服务合同", "建设工程施工合同", "合同效力", "合同履行", "合同解除", "违约责任", "缔约过失"),
    "房地产": ("房地产", "房屋", "商品房", "不动产", "房产", "退房", "购房", "土地使用权", "预告登记", "房屋征收", "拆迁补偿"),
    "公司法": ("股东", "股权", "公司决议", "法定代表人", "清算责任", "公司清算", "股权转让", "公司担保"),
    "担保合同": ("担保", "保证责任", "保证合同", "抵押权", "抵押", "质押", "债务加入", "融资租赁", "预告登记排除"),
    "破产法": ("破产", "破产清算", "重整", "债权申报", "破产债权", "执转破", "破产管辖"),
    "商事仲裁": ("仲裁", "仲裁协议", "仲裁庭", "仲裁裁决", "不予执行仲裁", "佛仲", "广仲", "上仲"),
    "劳动法": ("劳动关系", "劳动合同", "用人单位", "工资", "拖欠工资", "工伤", "竞业限制", "解除劳动"),
    "行政法": ("行政处罚", "行政复议", "行政诉讼", "行政机关", "行政公益诉讼", "征收补偿", "拆迁补偿"),
    "刑事法律": ("刑事", "犯罪", "诈骗", "赃物", "赃款", "刑事判决", "检察机关", "公安机关"),
    "刑民交叉": ("刑民交叉", "民刑交叉", "合同诈骗", "经济纠纷与犯罪"),
    "金融证券": ("证券", "金融", "私募", "基金", "保险", "资管", "银行", "票据", "债券"),
    "税务": ("税务", "纳税", "税收", "发票", "企业所得税", "增值税"),
    "知识产权": ("知识产权", "商标", "专利", "著作权", "商业秘密"),
    "婚姻家事": ("离婚", "婚姻", "继承", "抚养", "赡养", "夫妻"),
    "侵权责任": ("侵权", "损害赔偿", "人身损害", "交通事故", "侵权责任"),
}

_KNOWLEDGE_CASE_CONFLICTS = {
    "行政法": ("行政", "行政机关", "行政处罚", "行政复议", "行政诉讼", "征收补偿"),
    "刑事法律": ("刑事", "犯罪", "诈骗", "赃物", "赃款", "刑事判决"),
    "刑民交叉": ("刑民交叉", "合同诈骗", "经济纠纷与犯罪"),
    "破产法": ("破产", "重整", "债权申报", "破产清算"),
    "商事仲裁": ("仲裁", "仲裁协议", "仲裁庭", "仲裁裁决"),
    "劳动法": ("劳动关系", "劳动合同", "工资", "工伤", "用人单位"),
    "税务": ("税务", "欠税", "纳税", "税收", "发票", "企业所得税", "增值税"),
    "金融证券": ("金融", "证券", "基金", "资管计划", "信托", "股票", "保险", "债券"),
    "建设工程": ("建设工程", "施工合同", "工程价款", "实际施工人", "挂靠", "招标投标"),
    "房地产": ("商品房", "房屋", "不动产", "房地产", "购房", "土地使用权"),
}

_KNOWLEDGE_DOMAIN_AFFINITY = {
    "强制执行": {"执行异议", "房地产", "担保合同", "破产法", "商事仲裁"},
    "执行异议": {"强制执行", "房地产", "担保合同", "刑事法律", "刑民交叉"},
    "建设工程": {"合同法", "房地产", "担保合同", "强制执行", "破产法"},
    "合同法": {"建设工程", "担保合同", "房地产", "商事仲裁", "金融证券"},
    "房地产": {"建设工程", "强制执行", "执行异议", "担保合同", "行政法"},
    "担保合同": {"合同法", "房地产", "强制执行", "执行异议", "金融证券"},
    "破产法": {"强制执行", "建设工程", "合同法", "金融证券"},
    "商事仲裁": {"合同法", "强制执行", "金融证券"},
    "刑事法律": {"刑民交叉", "执行异议", "强制执行"},
    "刑民交叉": {"刑事法律", "执行异议", "强制执行", "合同法"},
}


def _knowledge_profile_from_text(text: str) -> dict:
    """从案件摘要中提取可解释的法律主题，不把当事人姓名当作相关性信号。"""
    normalized = str(text or "").casefold()
    domain_hits: dict[str, int] = {}
    signal_hits: dict[str, dict] = {}
    for domain, aliases in _KNOWLEDGE_CASE_TOPIC_ALIASES.items():
        for alias in aliases:
            count = normalized.count(alias.casefold())
            if not count:
                continue
            domain_hits[domain] = domain_hits.get(domain, 0) + count
            signal = signal_hits.setdefault(alias, {"term": alias, "weight": 0, "domain": domain})
            signal["weight"] += count
    domains = [domain for domain, _ in sorted(domain_hits.items(), key=lambda pair: (-pair[1], pair[0]))]
    signals = sorted(signal_hits.values(), key=lambda item: (-len(item["term"]), -item["weight"], item["term"]))
    return {
        "text": str(text or ""),
        "domains": domains,
        "signals": signals,
        "has_focus": bool(domains or signals),
    }


def _knowledge_case_profile(conn: sqlite3.Connection, case_id: Optional[int]) -> dict:
    """汇总案件的类型、争点、办案事项和案号信号，避免只拿案件标题做模糊匹配。"""
    if not case_id:
        return _knowledge_profile_from_text("")
    row = conn.execute(
        "SELECT title,case_type,current_stage,memo FROM case_manager_cases WHERE id=? AND COALESCE(source_status,'active')='active'",
        (case_id,),
    ).fetchone()
    if not row:
        return _knowledge_profile_from_text("")
    sections: list[tuple[str, str, int]] = [
        ("案件类型", row["case_type"] or "", 6),
        ("案件标题", row["title"] or "", 4),
        ("当前阶段", row["current_stage"] or "", 2),
        ("案件备忘", row["memo"] or "", 3),
    ]
    project = conn.execute(
        "SELECT name,case_info,issues FROM research_projects WHERE case_id=? ORDER BY updated_at DESC,id DESC LIMIT 1",
        (case_id,),
    ).fetchone()
    if project:
        sections.extend([
            ("研究名称", project["name"] or "", 3),
            ("研究说明", project["case_info"] or "", 3),
            ("研究争点", project["issues"] or "", 6),
        ])
    # 办案事项里常含“恢复执行、查封、破产申请”等真正的工作争点，
    # 但刻意不读取联系方式和联系人字段，避免噪声与隐私进入排序。
    related_tables = (
        ("case_manager_todos", ("todo_title", "title", "notes")),
        ("case_manager_hearings", ("reminder_type", "title", "location", "court", "case_no", "notes")),
        ("case_manager_preservations", ("preservation_type", "title", "asset_content", "notes")),
        ("case_manager_appeals", ("appeal_type", "title", "court", "case_no", "notes")),
        ("case_manager_case_numbers", ("number_type", "case_no", "court")),
    )
    for table, columns in related_tables:
        try:
            rows = conn.execute(
                f"SELECT {','.join(columns)} FROM {table} WHERE case_id=? ORDER BY id DESC LIMIT 40", (case_id,)
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        for related in rows:
            for column in columns:
                value = related[column] or ""
                if value:
                    sections.append((table, str(value), 2 if column in {"title", "todo_title", "case_no", "appeal_type", "reminder_type", "preservation_type"} else 1))
    text = " ".join(value for _, value, _ in sections if value)
    profile = _knowledge_profile_from_text(text)
    case_type_text = str(row["case_type"] or "").casefold()
    title_text = str(row["title"] or "").casefold()
    primary_domains: list[str] = []
    for domain, aliases in _KNOWLEDGE_CASE_TOPIC_ALIASES.items():
        if any(alias.casefold() in case_type_text for alias in aliases):
            primary_domains.append(domain)
    # “执行”是案件类型中常见的简写，不能要求用户必须写成“强制执行”。
    if not primary_domains and case_type_text in {"执行", "执行案件", "申请执行", "执行案"}:
        primary_domains.append("强制执行")
    if not primary_domains:
        for domain, aliases in _KNOWLEDGE_CASE_TOPIC_ALIASES.items():
            if any(alias.casefold() in title_text for alias in aliases):
                primary_domains.append(domain)
    profile["primary_domains"] = list(dict.fromkeys(primary_domains))
    profile["case_id"] = int(case_id)
    profile["sections"] = sections
    # 同一短语在办案事项中出现时提升权重；类型/研究争点是最可信的信号。
    weighted_signals: dict[str, dict] = {}
    for source, value, source_weight in sections:
        normalized = value.casefold()
        for domain, aliases in _KNOWLEDGE_CASE_TOPIC_ALIASES.items():
            for alias in aliases:
                if alias.casefold() not in normalized:
                    continue
                current = weighted_signals.setdefault(alias, {"term": alias, "weight": 0, "domain": domain, "sources": set()})
                current["weight"] += source_weight
                current["sources"].add(source)
    profile["signals"] = sorted(
        [{**item, "sources": sorted(item["sources"])} for item in weighted_signals.values()],
        key=lambda item: (-int(item["weight"]), -len(item["term"]), item["term"]),
    )
    profile["has_focus"] = bool(profile["domains"] or profile["signals"])
    return profile


def _knowledge_case_context(conn: sqlite3.Connection, case_id: Optional[int]) -> str:
    return _knowledge_case_profile(conn, case_id).get("text", "")


def _knowledge_case_profile_for_rank(case_context: str, case_profile: Optional[dict]) -> dict:
    if case_profile and case_profile.get("text"):
        return case_profile
    return _knowledge_profile_from_text(case_context)


def _knowledge_case_relevance(item: dict, profile: dict) -> tuple[int, list[str]]:
    if not profile.get("text") or not profile.get("has_focus"):
        return 0, []
    issue_text = " ".join(str(item.get(key) or "") for key in ("issue_titles", "statement", "conditions_text", "exceptions_text", "procedural_stage", "source_titles")).casefold()
    issue_titles = str(item.get("issue_titles") or "").casefold()
    statement = str(item.get("statement") or "").casefold()
    item_domains = {value.strip() for value in str(item.get("issue_domains") or "").split(",") if value.strip()}
    score = 0
    reasons: list[str] = []
    title_score = 0
    detail_score = 0
    matched_terms: list[str] = []
    for signal in profile.get("signals", []):
        term = str(signal.get("term") or "")
        if not term or term.casefold() not in issue_text:
            continue
        importance = min(8, max(1, int(signal.get("weight") or 1)))
        if term.casefold() in issue_titles:
            title_score += 9 + importance * 2
        elif term.casefold() in statement:
            detail_score += 5 + importance
        else:
            detail_score += 2 + min(importance, 4)
        matched_terms.append(term)
    score += min(title_score, 64) + min(detail_score, 36)
    if matched_terms:
        reasons.append("争点匹配：" + "、".join(dict.fromkeys(matched_terms[:3])))
    profile_domains = set(profile.get("domains") or [])
    primary_domains = set(profile.get("primary_domains") or [])
    domain_overlap = profile_domains & item_domains
    primary_overlap = primary_domains & item_domains
    if primary_overlap:
        score += 20
        reasons.append("核心法律领域匹配：" + "、".join(sorted(primary_overlap)))
    elif domain_overlap:
        score += 12
        reasons.append("法律领域匹配：" + "、".join(sorted(domain_overlap)))
    elif any(item_domain in _KNOWLEDGE_DOMAIN_AFFINITY.get(profile_domain, set()) for profile_domain in profile_domains for item_domain in item_domains):
        score += 11
        reasons.append("相邻法律领域匹配")
    elif profile.get("domains"):
        score -= 18
    # 案件没有刑事/行政/仲裁等信号时，强制下调同领域中实际语境不同的结论。
    for conflict_domain, terms in _KNOWLEDGE_CASE_CONFLICTS.items():
        if conflict_domain in profile_domains:
            continue
        if any(term.casefold() in issue_text for term in terms):
            score -= 24
            reasons.append("排除语境不符：" + conflict_domain)
            break
    # “综合法律”不能仅凭一个领域词进入当前案件卡片，除非它确实命中了案件争点。
    if "综合法律" in item_domains and not matched_terms:
        score -= 10
    if score > 0 and not reasons:
        reasons.append("案件类型相关")
    return score, reasons[:3]


def _ensure_knowledge_learning_state(conn: sqlite3.Connection, claim_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM knowledge_learning_state WHERE claim_id=?", (claim_id,)).fetchone()
    if row:
        return row
    now = _knowledge_now()
    conn.execute(
        "INSERT OR IGNORE INTO knowledge_learning_state(claim_id,updated_at) VALUES (?,?)",
        (claim_id, now),
    )
    return conn.execute("SELECT * FROM knowledge_learning_state WHERE claim_id=?", (claim_id,)).fetchone()


def _knowledge_claim_rows(conn: sqlite3.Connection, domain: str = "", category_id: Optional[int] = None) -> list[dict]:
    today = datetime.date.today().isoformat()
    where = [
        "c.review_status='approved'", "i.status='active'",
        "EXISTS (SELECT 1 FROM knowledge_claim_evidence ve WHERE ve.claim_id=c.id AND ve.verified=1)",
        "(COALESCE(c.valid_from,'')='' OR substr(c.valid_from,1,10)<=?)",
        "(COALESCE(c.valid_to,'')='' OR substr(c.valid_to,1,10)>=?)",
    ]
    params: list[Any] = [today, today]
    if domain.strip():
        where.append("i.domain=?")
        params.append(domain.strip())
    if category_id:
        where.append("(ic.category_id=? OR cat.parent_id=?)")
        params.extend([category_id, category_id])
    rows = conn.execute(
        f"""SELECT c.*, GROUP_CONCAT(DISTINCT i.title) AS issue_titles,
                   GROUP_CONCAT(DISTINCT i.domain) AS issue_domains,
                   GROUP_CONCAT(DISTINCT CASE WHEN e.verified=1 THEN a.title END) AS source_titles,
                   COUNT(DISTINCT CASE WHEN e.verified=1 THEN e.id END) AS evidence_count
            FROM knowledge_claims c
            JOIN knowledge_claim_issues ci ON ci.claim_id=c.id
            JOIN knowledge_issues i ON i.id=ci.issue_id
            LEFT JOIN knowledge_issue_categories ic ON ic.issue_id=i.id
            LEFT JOIN knowledge_categories cat ON cat.id=ic.category_id
            LEFT JOIN knowledge_claim_evidence e ON e.claim_id=c.id
            LEFT JOIN articles a ON a.id=e.article_id
            WHERE {' AND '.join(where)}
            GROUP BY c.id ORDER BY c.updated_at DESC,c.id DESC""",
        params,
    ).fetchall()
    results = []
    for row in rows:
        item = dict(row)
        item["learning"] = dict(_ensure_knowledge_learning_state(conn, int(row["id"])))
        results.append(item)
    # Separate extraction jobs can approve the same rule with the same legal issue.
    # Keep all records for governance, but present one card in everyday views.
    unique: dict[tuple[str, str, str, str, str], dict] = {}
    for item in results:
        key = (
            str(item.get("normalized_statement") or item.get("statement") or "").strip(),
            str(item.get("issue_titles") or "").strip(),
            str(item.get("issue_domains") or "").strip(),
            str(item.get("conditions_text") or "").strip(),
            str(item.get("exceptions_text") or "").strip(),
        )
        current = unique.get(key)
        if current is None or (
            int(item["learning"].get("is_favorite") or 0),
            int(item["learning"].get("review_count") or 0),
            int(item.get("evidence_count") or 0), str(item.get("updated_at") or ""), int(item["id"])
        ) > (
            int(current["learning"].get("is_favorite") or 0),
            int(current["learning"].get("review_count") or 0),
            int(current.get("evidence_count") or 0), str(current.get("updated_at") or ""), int(current["id"])
        ):
            unique[key] = item
    return list(unique.values())


def _knowledge_rank_rows(
    rows: list[dict], query: str = "", case_context: str = "", case_profile: Optional[dict] = None,
) -> list[dict]:
    tokens = _knowledge_search_tokens(query)
    profile = _knowledge_case_profile_for_rank(case_context, case_profile)
    ranked = []
    for source_item in rows:
        # 排序是派生视图，不能把案件匹配字段回写到收藏/最近使用等其他卡片集合。
        item = dict(source_item)
        item["learning"] = dict(source_item.get("learning") or {})
        fields = {
            "issue": str(item.get("issue_titles") or "").casefold(),
            "domain": str(item.get("issue_domains") or "").casefold(),
            "statement": str(item.get("statement") or "").casefold(),
            "conditions": str(item.get("conditions_text") or "").casefold(),
            "exceptions": str(item.get("exceptions_text") or "").casefold(),
            "source": str(item.get("source_titles") or "").casefold(),
        }
        text_score = 0
        for token in tokens:
            token = token.casefold()
            text_score += fields["issue"].count(token) * 10
            text_score += fields["domain"].count(token) * 5
            text_score += fields["statement"].count(token) * 8
            text_score += fields["conditions"].count(token) * 4
            text_score += fields["exceptions"].count(token) * 4
            text_score += fields["source"].count(token)
        case_score, case_reasons = _knowledge_case_relevance(item, profile)
        score = text_score + case_score
        if int(item["learning"].get("is_favorite") or 0):
            score += 2
        item["match_score"] = score
        item["text_match_score"] = text_score
        item["case_match_score"] = case_score
        item["case_match_reasons"] = case_reasons
        item["case_match_confidence"] = (
            "high" if case_score >= 48 else "medium" if case_score >= 28 else "low"
        ) if case_score else ""
        ranked.append(item)
    ranked.sort(key=lambda item: (-int(item.get("match_score") or 0), -int(item["id"])))
    return ranked


def _knowledge_card(item: dict) -> dict:
    fields = (
        "id", "statement", "claim_type", "conditions_text", "exceptions_text", "procedural_stage",
        "jurisdiction", "court_level", "authority_type", "authority_level", "valid_from", "valid_to",
        "review_status", "confidence", "updated_at", "issue_titles", "issue_domains", "source_titles",
        "evidence_count", "match_score", "case_match_score", "case_match_reasons", "case_match_confidence",
        "text_match_score", "search_match",
    )
    card = {key: item.get(key) for key in fields if key in item}
    card["learning"] = item.get("learning") or {}
    return card


def _record_knowledge_usage(conn: sqlite3.Connection, payload: KnowledgeUsageEventPayload) -> None:
    allowed = {"open", "search", "source_open", "copy", "add_to_case", "review_start", "review_complete"}
    if payload.event_type not in allowed:
        raise HTTPException(status_code=400, detail="知识使用事件类型无效")
    conn.execute(
        """INSERT INTO knowledge_usage_events
           (event_type,claim_id,issue_id,case_id,result_count,created_at)
           VALUES (?,?,?,?,?,?)""",
        (
            payload.event_type, payload.claim_id, payload.issue_id, payload.case_id,
            max(0, min(int(payload.result_count or 0), 10000)), _knowledge_now(),
        ),
    )


class KnowledgeCenter(NamedTuple):
    router: APIRouter
    search_cards: Callable[..., dict]


def create_router(
    get_db: Callable[[], sqlite3.Connection],
    *,
    knowledge_jobs: KnowledgeJobs,
    frontend_dir: Path,
    ensure_case_research_project: Callable,
) -> KnowledgeCenter:
    router = APIRouter()

    @router.get("/api/legal-knowledge/home")
    def legal_knowledge_home(case_id: Optional[int] = None):
        with get_db() as conn:
            rows = _knowledge_claim_rows(conn)
            case_profile = _knowledge_case_profile(conn, case_id)
            ranked_for_case = _knowledge_rank_rows(rows, case_profile=case_profile)
            now = _knowledge_now()
            due = [
                item for item in rows
                if not int(item["learning"].get("is_suspended") or 0)
                and item["learning"].get("next_review_at")
                and item["learning"]["next_review_at"] <= now
            ]
            due.sort(key=lambda item: (item["learning"].get("next_review_at") or "", int(item["learning"].get("mastery_level") or 0)))
            # 仅让有明确主题或争点命中的结论进入“与你当前工作有关”，
            # 避免“强制执行”等宽泛领域把行政、刑事等语境不同的知识塞进来。
            case_related = [
                item for item in ranked_for_case
                if case_profile.get("has_focus") and int(item.get("case_match_score") or 0) >= 22
            ][:5]
            favorites = [item for item in rows if int(item["learning"].get("is_favorite") or 0) and not int(item["learning"].get("is_suspended") or 0)]
            favorite_count = len(favorites)
            favorites = _knowledge_rank_rows(favorites)[:5]
            recent_ids = [int(row["claim_id"]) for row in conn.execute(
                """SELECT claim_id FROM knowledge_usage_events
               WHERE claim_id IS NOT NULL ORDER BY id DESC LIMIT 80"""
            ).fetchall()]
            recent_seen: set[int] = set()
            recent = []
            by_id = {int(item["id"]): item for item in rows}
            for claim_id in recent_ids:
                if claim_id in recent_seen or claim_id not in by_id:
                    continue
                recent_seen.add(claim_id)
                recent.append(by_id[claim_id])
                if len(recent) >= 5:
                    break
            cases = [dict(row) for row in conn.execute(
                """SELECT id,title,case_type,memo FROM case_manager_cases
               WHERE COALESCE(source_status,'active')='active'
               ORDER BY updated_at DESC,id DESC LIMIT 100"""
            ).fetchall()]
            domains = sorted({
                domain.strip()
                for item in rows
                for domain in str(item.get("issue_domains") or "").split(",")
                if domain.strip()
            })
            _record_knowledge_usage(conn, KnowledgeUsageEventPayload(event_type="open", case_id=case_id))
            conn.commit()
        return {
            "case_id": case_id,
            "stats": {"approved": len(rows), "due": len(due), "favorites": favorite_count},
            "domains": domains,
            "case_related": [_knowledge_card(item) for item in case_related],
            "due_preview": [_knowledge_card(item) for item in due[:5]],
            "favorites": [_knowledge_card(item) for item in favorites],
            "recent": [_knowledge_card(item) for item in recent],
            "cases": cases,
        }


    @router.get("/api/legal-knowledge/search")
    def search_legal_knowledge_center(
        q: str = "", domain: str = "", category_id: Optional[int] = None,
        case_id: Optional[int] = None, limit: int = Query(30, ge=1, le=100),
        offset: int = Query(0, ge=0),
        semantic: bool = False,
    ):
        return _search_local_knowledge_cards(q, domain, category_id, case_id, limit, offset, semantic)


    def _search_local_knowledge_cards(q, domain, category_id, case_id, limit, offset, semantic, record_usage=True):
        literal_lookup = semantic and knowledge_search.is_exact_lookup(q)
        if literal_lookup and (q.strip()[0], q.strip()[-1]) in {('"', '"'), ('“', '”')}:
            q = q.strip()[1:-1]
        with get_db() as conn:
            rows = _knowledge_claim_rows(conn, domain, category_id)
            ranked = _knowledge_rank_rows(rows, q.strip(), case_profile=_knowledge_case_profile(conn, case_id))
            search_info = {"method": "keywords", "notice": ""}
            if q.strip():
                hits = []
                if semantic and knowledge_search.supports_semantics(q):
                    hits, search_info = knowledge_search.retrieve(conn, q.strip(), "claim", {int(row["id"]): row for row in rows})
                by_id = {hit["id"]: hit for hit in hits}
                if literal_lookup:
                    ranked = [item for item in ranked if any(q.strip().casefold() in str(item.get(field) or '').casefold() for field in knowledge_search.KNOWLEDGE_FIELDS)]
                else:
                    ranked = [item for item in ranked if int(item.get("text_match_score") or 0) > 0 or int(item["id"]) in by_id]
                if semantic and not literal_lookup:
                    # Case/favorite boosts cannot admit unrelated cards. They only break ties.
                    lexical = sorted((r for r in ranked if int(r.get("text_match_score") or 0) > 0), key=lambda r: -int(r["text_match_score"]))
                    scores = {int(r["id"]): 1 / (61 + rank) for rank, r in enumerate(lexical)}
                    for item in ranked:
                        hit = by_id.get(int(item["id"]))
                        if hit:
                            item["search_match"] = {key: hit[key] for key in ("channels", "field", "label", "text", "offset")}
                            scores[int(item["id"])] = hit["score"]
                    ranked.sort(key=lambda r: (-int(q.strip().casefold() in str(r.get("statement") or "").casefold()), -scores.get(int(r["id"]), 0), -int(r.get("match_score") or 0), -int(r["id"])))
            total = len(ranked)
            ranked = ranked[offset:offset + limit]
            if record_usage:
                _record_knowledge_usage(conn, KnowledgeUsageEventPayload(event_type="search", case_id=case_id, result_count=total))
                conn.commit()
        return {"query": q.strip(), "results": [_knowledge_card(item) for item in ranked], "total": total, "offset": offset, "search_info": search_info}


    @router.get("/api/legal-knowledge/review/queue")
    def legal_knowledge_review_queue(
        case_id: Optional[int] = None,
        limit: int = Query(8, ge=1, le=20),
        domains: Optional[List[str]] = Query(default=None, description="按任一所选法律领域筛选复习卡片"),
    ):
        selected_domains: list[str] = []
        for raw_domain in domains or []:
            domain = re.sub(r"\s+", " ", str(raw_domain or "").strip())[:80]
            if domain and domain not in selected_domains:
                selected_domains.append(domain)
        with get_db() as conn:
            rows = _knowledge_claim_rows(conn)
            if selected_domains:
                wanted_domains = set(selected_domains)
                rows = [
                    item for item in rows
                    if wanted_domains.intersection(
                        domain.strip() for domain in str(item.get("issue_domains") or "").split(",")
                    )
                ]
            now = _knowledge_now()
            due = [
                item for item in rows
                if not int(item["learning"].get("is_suspended") or 0)
                and item["learning"].get("next_review_at")
                and item["learning"]["next_review_at"] <= now
            ]
            due.sort(key=lambda item: (item["learning"].get("next_review_at") or "", int(item["learning"].get("mastery_level") or 0)))
            selected = due[:limit]
            selected_ids = {int(item["id"]) for item in selected}
            ranked = _knowledge_rank_rows(rows, case_profile=_knowledge_case_profile(conn, case_id))
            for item in ranked:
                if len(selected) >= limit:
                    break
                if int(item["id"]) in selected_ids or int(item["learning"].get("is_suspended") or 0):
                    continue
                if int(item["match_score"] or 0) > 0 or int(item["learning"].get("review_count") or 0) == 0:
                    selected.append(item)
                    selected_ids.add(int(item["id"]))
            _record_knowledge_usage(conn, KnowledgeUsageEventPayload(event_type="review_start", case_id=case_id, result_count=len(selected)))
            conn.commit()
        return {
            "cards": [_knowledge_card(item) for item in selected],
            "due_count": len(due),
            "limit": limit,
            "domains": selected_domains,
        }


    @router.post("/api/legal-knowledge/review/{claim_id}")
    def review_legal_knowledge_learning(claim_id: int, payload: KnowledgeLearningReviewPayload):
        if payload.grade not in {"forgot", "fuzzy", "mastered"}:
            raise HTTPException(status_code=400, detail="复习反馈无效")
        with get_db() as conn:
            claim = conn.execute("SELECT * FROM knowledge_claims WHERE id=?", (claim_id,)).fetchone()
            if not claim or claim["review_status"] != "approved":
                raise HTTPException(status_code=400, detail="只有已通过的知识才能复习")
            evidence_count = conn.execute(
                "SELECT COUNT(*) FROM knowledge_claim_evidence WHERE claim_id=? AND verified=1", (claim_id,)
            ).fetchone()[0]
            if not evidence_count:
                raise HTTPException(status_code=400, detail="该知识缺少核验依据，暂不能复习")
            previous = _ensure_knowledge_learning_state(conn, claim_id)
            previous_interval = int(previous["interval_days"] or 0)
            previous_level = int(previous["mastery_level"] or 0)
            if payload.grade == "forgot":
                next_interval, level, streak = 1, 0, 0
            elif payload.grade == "fuzzy":
                next_interval, level, streak = 3, previous_level, 0
            else:
                schedule = (7, 14, 30, 60, 120)
                level = min(len(schedule), previous_level + 1)
                next_interval, streak = schedule[level - 1], int(previous["streak"] or 0) + 1
            now = _knowledge_now()
            next_at = (datetime.datetime.now() + datetime.timedelta(days=next_interval)).isoformat(timespec="seconds")
            review_count = int(previous["review_count"] or 0) + 1
            conn.execute(
                """UPDATE knowledge_learning_state
               SET mastery_level=?,streak=?,interval_days=?,next_review_at=?,last_reviewed_at=?,review_count=?,updated_at=?
               WHERE claim_id=?""",
                (level, streak, next_interval, next_at, now, review_count, now, claim_id),
            )
            conn.execute(
                """INSERT INTO knowledge_review_events
               (claim_id,grade,case_id,previous_interval_days,next_interval_days,created_at)
               VALUES (?,?,?,?,?,?)""",
                (claim_id, payload.grade, payload.case_id, previous_interval, next_interval, now),
            )
            _record_knowledge_usage(conn, KnowledgeUsageEventPayload(event_type="review_complete", claim_id=claim_id, case_id=payload.case_id))
            state = dict(conn.execute("SELECT * FROM knowledge_learning_state WHERE claim_id=?", (claim_id,)).fetchone())
            conn.commit()
        return {"success": True, "claim_id": claim_id, "learning": state}


    @router.put("/api/legal-knowledge/claims/{claim_id}/personal-state")
    def update_legal_knowledge_personal_state(claim_id: int, payload: KnowledgeLearningStatePayload):
        with get_db() as conn:
            if not conn.execute("SELECT id FROM knowledge_claims WHERE id=?", (claim_id,)).fetchone():
                raise HTTPException(status_code=404, detail="知识结论不存在")
            current = _ensure_knowledge_learning_state(conn, claim_id)
            favorite = int(payload.is_favorite) if payload.is_favorite is not None else int(current["is_favorite"] or 0)
            suspended = int(payload.is_suspended) if payload.is_suspended is not None else int(current["is_suspended"] or 0)
            conn.execute(
                "UPDATE knowledge_learning_state SET is_favorite=?,is_suspended=?,updated_at=? WHERE claim_id=?",
                (favorite, suspended, _knowledge_now(), claim_id),
            )
            state = dict(conn.execute("SELECT * FROM knowledge_learning_state WHERE claim_id=?", (claim_id,)).fetchone())
            conn.commit()
        return {"success": True, "learning": state}


    @router.post("/api/legal-knowledge/claims/{claim_id}/use")
    def use_legal_knowledge_claim(claim_id: int, payload: KnowledgeKnowledgeUsePayload):
        if payload.action not in {"open", "source_open", "copy", "add_to_case"}:
            raise HTTPException(status_code=400, detail="知识使用动作无效")
        with get_db() as conn:
            claim = conn.execute("SELECT * FROM knowledge_claims WHERE id=?", (claim_id,)).fetchone()
            if not claim or claim["review_status"] != "approved":
                raise HTTPException(status_code=400, detail="只有已通过的知识才能使用")
            today = datetime.date.today().isoformat()
            if payload.action in {"copy", "add_to_case"} and (
                (claim["valid_from"] and str(claim["valid_from"])[:10] > today)
                or (claim["valid_to"] and str(claim["valid_to"])[:10] < today)
            ):
                raise HTTPException(status_code=400, detail="该知识不在有效期间，请核对原文后处理")
            detail = get_knowledge_claim_detail(conn, claim_id)
            memo_id = None
            if payload.action == "add_to_case":
                if not payload.case_id:
                    raise HTTPException(status_code=400, detail="加入案件研究前请选择案件")
                project_id = ensure_case_research_project(conn, int(payload.case_id))
                issue = (detail.get("issues") or [{}])[0]
                verified = [item for item in (detail.get("evidence") or []) if int(item.get("verified") or 0)]
                evidence_text = "\n".join(
                    f"- 《{item.get('article_title') or '原文'}》第{item.get('paragraph_index')}段：{item.get('quote') or ''}"
                    for item in verified[:5]
                )
                content = "\n".join(filter(None, [
                    f"<!-- knowledge-claim:{claim_id} -->",
                    f"结论：{claim['statement']}",
                    f"适用条件：{claim['conditions_text']}" if claim["conditions_text"] else "",
                    f"例外与限制：{claim['exceptions_text']}" if claim["exceptions_text"] else "",
                    f"核验依据：\n{evidence_text}" if evidence_text else "",
                ]))
                existing = conn.execute(
                    "SELECT id,content FROM research_case_memo_entries WHERE project_id=? AND content LIKE ? LIMIT 1",
                    (project_id, f"%<!-- knowledge-claim:{claim_id} -->%"),
                ).fetchone()
                if existing:
                    memo_id = int(existing["id"])
                    if existing["content"] != content:
                        now = _knowledge_now()
                        conn.execute(
                            "UPDATE research_case_memo_entries SET content=?,updated_at=? WHERE id=?",
                            (content, now, memo_id),
                        )
                        conn.execute("UPDATE research_projects SET updated_at=? WHERE id=?", (now, project_id))
                else:
                    now = _knowledge_now()
                    cur = conn.execute(
                        """INSERT INTO research_case_memo_entries
                       (project_id,title,content,happened_at,created_at,updated_at)
                       VALUES (?,?,?,?,?,?)""",
                        (project_id, f"知识结论：{issue.get('title') or '未命名问题'}", content, now, now, now),
                    )
                    memo_id = int(cur.lastrowid)
                    conn.execute("UPDATE research_projects SET updated_at=? WHERE id=?", (now, project_id))
            _record_knowledge_usage(conn, KnowledgeUsageEventPayload(event_type=payload.action, claim_id=claim_id, case_id=payload.case_id))
            conn.commit()
        return {"success": True, "action": payload.action, "claim_id": claim_id, "case_id": payload.case_id, "memo_id": memo_id}


    @router.post("/api/legal-knowledge/events")
    def record_legal_knowledge_event(payload: KnowledgeUsageEventPayload):
        with get_db() as conn:
            _record_knowledge_usage(conn, payload)
            conn.commit()
        return {"success": True}


    @router.get("/api/legal-knowledge/dashboard")
    def legal_knowledge_dashboard():
        with get_db() as conn:
            status_counts = {row["review_status"]: row["n"] for row in conn.execute(
                "SELECT review_status,COUNT(*) n FROM knowledge_claims GROUP BY review_status"
            ).fetchall()}
            # 仪表盘展示每篇文章的最新任务状态；旧失败任务继续保留在任务历史和审计记录中，
            # 但在成功重试后不再造成“仍有失败”的误解。
            job_counts = {row["status"]: row["n"] for row in conn.execute(
                """SELECT status,COUNT(*) n
               FROM knowledge_extraction_jobs
               WHERE id IN (
                   SELECT MAX(id) FROM knowledge_extraction_jobs GROUP BY article_id
               )
               GROUP BY status"""
            ).fetchall()}
            issue_count = conn.execute("SELECT COUNT(*) FROM knowledge_issues WHERE status='active'").fetchone()[0]
            evidence_count = conn.execute("SELECT COUNT(*) FROM knowledge_claim_evidence WHERE verified=1").fetchone()[0]
            all_candidates = knowledge_candidate_ids(conn, include_excluded=True)
            candidates = knowledge_candidate_ids(conn)
            excluded_count = len(all_candidates) - len(candidates)
            # “已处理”必须对应文章当前正文。文章改过后，旧版本曾经完成过
            # 不应继续算作当前版本已处理。
            completed_versions = {
                (int(row["article_id"]), row["content_hash"])
                for row in conn.execute(
                    "SELECT DISTINCT article_id,content_hash FROM knowledge_extraction_jobs WHERE status='completed'"
                ).fetchall()
            }
            candidate_rows = conn.execute(
                f"SELECT id,content FROM articles WHERE id IN ({','.join('?' for _ in all_candidates)})",
                all_candidates,
            ).fetchall() if all_candidates else []
            processed = sum(
                (int(row["id"]), knowledge_content_hash(row["content"] or "")) in completed_versions
                for row in candidate_rows
            )
            domain_counts: dict[str, int] = {}
            for row in conn.execute("SELECT domains,content FROM articles ORDER BY id").fetchall():
                if not is_knowledge_article(row):
                    continue
                domains = article_knowledge_domains(row) or ["综合法律"]
                for domain in domains:
                    domain_counts[domain] = domain_counts.get(domain, 0) + 1
        return {
            "claims": {status: int(status_counts.get(status, 0)) for status in KNOWLEDGE_CLAIM_STATUSES},
            "jobs": job_counts,
            "issues": int(issue_count),
            "verified_evidence": int(evidence_count),
            "knowledge_candidates": len(all_candidates),
            "active_knowledge_candidates": len(candidates),
            "excluded_articles": excluded_count,
            "pilot_candidates": len(all_candidates),
            "processed_articles": int(processed),
            "domains": [
                {"name": name, "article_count": count}
                for name, count in sorted(domain_counts.items(), key=lambda item: (-item[1], item[0]))
            ],
        }


    @router.get("/api/legal-knowledge/categories")
    def list_legal_knowledge_categories(domain: str = ""):
        with get_db() as conn:
            rows = knowledge_category_rows(conn, domain)
            unclassified = 0
            if domain.strip():
                unclassified = int(conn.execute(
                    """SELECT COUNT(*) FROM knowledge_issues i
                   LEFT JOIN knowledge_issue_categories ic ON ic.issue_id=i.id
                   WHERE i.status='active' AND i.domain=? AND ic.issue_id IS NULL""",
                    (domain.strip(),),
                ).fetchone()[0])
        return {"categories": rows, "unclassified_count": unclassified}


    @router.post("/api/legal-knowledge/organize")
    def organize_legal_knowledge(payload: KnowledgeOrganizePayload):
        domain = re.sub(r"\s+", " ", payload.domain.strip())[:120]
        if not domain:
            raise HTTPException(status_code=400, detail="请先选择一个法律领域")
        with get_db() as conn:
            issue_count = int(conn.execute(
                "SELECT COUNT(*) FROM knowledge_issues WHERE domain=? AND status='active'", (domain,)
            ).fetchone()[0])
            if not issue_count:
                raise HTTPException(status_code=400, detail="当前领域没有可整理的法律问题")
            active = conn.execute(
                """SELECT id,status FROM knowledge_organization_jobs
               WHERE domain=? AND status IN ('queued','running') ORDER BY id DESC LIMIT 1""",
                (domain,),
            ).fetchone()
            if active:
                return {"success": True, "job_id": int(active["id"]), "status": active["status"], "created": False}
            now = datetime.datetime.now().isoformat()
            cur = conn.execute(
                """INSERT INTO knowledge_organization_jobs
               (domain,status,total_issues,created_at,updated_at) VALUES (?,'queued',?,?,?)""",
                (domain, issue_count, now, now),
            )
            job_id = int(cur.lastrowid)
            conn.commit()
        knowledge_jobs.notify()
        return {"success": True, "job_id": job_id, "status": "queued", "created": True}


    @router.get("/api/legal-knowledge/organize/jobs")
    def list_legal_knowledge_organization_jobs(domain: str = "", limit: int = 20):
        where, params = [], []
        if domain.strip():
            where.append("domain=?")
            params.append(domain.strip())
        with get_db() as conn:
            rows = conn.execute(
                f"""SELECT * FROM knowledge_organization_jobs
                {'WHERE ' + ' AND '.join(where) if where else ''}
                ORDER BY id DESC LIMIT ?""", (*params, max(1, min(limit, 100))),
            ).fetchall()
        jobs = []
        for row in rows:
            item = dict(row)
            try:
                item["warnings"] = json.loads(item.pop("warnings_json") or "[]")
            except Exception:
                item["warnings"] = []
            jobs.append(item)
        return {"jobs": jobs}


    @router.put("/api/legal-knowledge/issues/{issue_id}/category")
    def update_legal_knowledge_issue_category(issue_id: int, payload: KnowledgeIssueCategoryPayload):
        with get_db() as conn:
            issue = _knowledge_issue_row(conn, issue_id)
            category = conn.execute(
                "SELECT * FROM knowledge_categories WHERE id=? AND status='active'", (payload.category_id,)
            ).fetchone()
            if not category or category["domain"] != issue["domain"]:
                raise HTTPException(status_code=400, detail="请选择当前法律领域内的分类")
            now = datetime.datetime.now().isoformat()
            before = conn.execute(
                "SELECT * FROM knowledge_issue_categories WHERE issue_id=?", (issue_id,)
            ).fetchone()
            conn.execute(
                """INSERT INTO knowledge_issue_categories
               (issue_id,category_id,confidence,assignment_source,reviewed,created_at,updated_at)
               VALUES (?,?,1,'manual',1,?,?)
               ON CONFLICT(issue_id) DO UPDATE SET category_id=excluded.category_id,confidence=1,
                 assignment_source='manual',reviewed=1,updated_at=excluded.updated_at""",
                (issue_id, payload.category_id, now, now),
            )
            after = dict(conn.execute(
                "SELECT * FROM knowledge_issue_categories WHERE issue_id=?", (issue_id,)
            ).fetchone())
            audit_knowledge_change(
                conn, "issue", issue_id, "categorize", dict(before) if before else {}, after
            )
            conn.commit()
        return {"success": True, "assignment": after}


    @router.get("/api/legal-knowledge/merge-suggestions")
    def list_legal_knowledge_merge_suggestions(
        domain: str = "", status: str = "pending", limit: int = 100
    ):
        where, params = ["s.status=?"], [status]
        if domain.strip():
            where.append("source.domain=?")
            params.append(domain.strip())
        with get_db() as conn:
            rows = conn.execute(
                f"""SELECT s.*,source.title AS source_title,source.domain,
                       target.title AS target_title,
                       (SELECT COUNT(*) FROM knowledge_claim_issues WHERE issue_id=source.id) AS source_claim_count,
                       (SELECT COUNT(*) FROM knowledge_claim_issues WHERE issue_id=target.id) AS target_claim_count,
                       cat.name AS category_name,parent.name AS parent_category_name
                FROM knowledge_issue_merge_suggestions s
                JOIN knowledge_issues source ON source.id=s.source_issue_id
                JOIN knowledge_issues target ON target.id=s.target_issue_id
                LEFT JOIN knowledge_issue_categories ic ON ic.issue_id=source.id
                LEFT JOIN knowledge_categories cat ON cat.id=ic.category_id
                LEFT JOIN knowledge_categories parent ON parent.id=cat.parent_id
                WHERE {' AND '.join(where)}
                  AND source.status='active' AND target.status='active'
                ORDER BY s.similarity DESC,s.updated_at DESC LIMIT ?""",
                (*params, max(1, min(limit, 500))),
            ).fetchall()
        return {"suggestions": [dict(row) for row in rows]}


    @router.post("/api/legal-knowledge/merge-suggestions/{suggestion_id}/review")
    def review_legal_knowledge_merge_suggestion(
        suggestion_id: int, payload: KnowledgeSuggestionReviewPayload
    ):
        if payload.action not in {"accept", "reject"}:
            raise HTTPException(status_code=400, detail="处理动作无效")
        with get_db() as conn:
            suggestion = conn.execute(
                "SELECT * FROM knowledge_issue_merge_suggestions WHERE id=?", (suggestion_id,)
            ).fetchone()
            if not suggestion:
                raise HTTPException(status_code=404, detail="相似问题建议不存在")
            if suggestion["status"] != "pending":
                raise HTTPException(status_code=409, detail="这条建议已经处理")
            now = datetime.datetime.now().isoformat()
            if payload.action == "accept":
                _merge_knowledge_issue_records(
                    conn, int(suggestion["source_issue_id"]), int(suggestion["target_issue_id"]),
                    "merge_from_ai_suggestion",
                )
                new_status = "accepted"
            else:
                new_status = "rejected"
            conn.execute(
                """UPDATE knowledge_issue_merge_suggestions
               SET status=?,reviewed_at=?,updated_at=? WHERE id=?""",
                (new_status, now, now, suggestion_id),
            )
            conn.commit()
        return {"success": True, "status": new_status}


    @router.get("/api/legal-knowledge/issues")
    def list_legal_knowledge_issues(
        q: str = "", status: str = "active", domain: str = "", category_id: Optional[int] = None,
        page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=200),
    ):
        with get_db() as conn:
            where, params = ["i.status=?"], [status]
            if q.strip():
                where.append("i.title LIKE ?")
                params.append(f"%{q.strip()}%")
            if domain.strip():
                where.append("i.domain=?")
                params.append(domain.strip())
            if category_id:
                where.append("(ic.category_id=? OR cat.parent_id=?)")
                params.extend([category_id, category_id])
            total = int(conn.execute(
                f"""SELECT COUNT(DISTINCT i.id)
                FROM knowledge_issues i
                LEFT JOIN knowledge_issue_categories ic ON ic.issue_id=i.id
                LEFT JOIN knowledge_categories cat ON cat.id=ic.category_id
                WHERE {' AND '.join(where)}""",
                params,
            ).fetchone()[0])
            offset = (page - 1) * page_size
            rows = conn.execute(
                f"""SELECT i.*,
                       ic.category_id,cat.name AS category_name,cat.parent_id,
                       parent.name AS parent_category_name,
                       COUNT(DISTINCT CASE WHEN c.review_status<>'merged' THEN ci.claim_id END) AS claim_count,
                       SUM(CASE WHEN c.review_status='pending' THEN 1 ELSE 0 END) AS pending_count,
                       SUM(CASE WHEN c.review_status='approved' THEN 1 ELSE 0 END) AS approved_count
                FROM knowledge_issues i
                LEFT JOIN knowledge_issue_categories ic ON ic.issue_id=i.id
                LEFT JOIN knowledge_categories cat ON cat.id=ic.category_id
                LEFT JOIN knowledge_categories parent ON parent.id=cat.parent_id
                LEFT JOIN knowledge_claim_issues ci ON ci.issue_id=i.id
                LEFT JOIN knowledge_claims c ON c.id=ci.claim_id
                WHERE {' AND '.join(where)} GROUP BY i.id
                ORDER BY i.domain,COALESCE(parent.sort_order,cat.sort_order,999),COALESCE(parent.name,cat.name,''),
                         COALESCE(cat.sort_order,999),COALESCE(cat.name,''),i.updated_at DESC,i.id DESC
                LIMIT ? OFFSET ?""",
                (*params, page_size, offset),
            ).fetchall()
        return {
            "issues": [dict(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


    @router.get("/api/legal-knowledge/issues/{issue_id}")
    def legal_knowledge_issue_detail(issue_id: int):
        with get_db() as conn:
            issue = _knowledge_issue_row(conn, issue_id)
            issue_ids = [issue_id] + [int(row[0]) for row in conn.execute(
                "SELECT id FROM knowledge_issues WHERE merged_into_id=?", (issue_id,)
            ).fetchall()]
            placeholders = ",".join("?" for _ in issue_ids)
            claims = conn.execute(
                f"""SELECT DISTINCT c.* FROM knowledge_claims c
                JOIN knowledge_claim_issues ci ON ci.claim_id=c.id
                WHERE ci.issue_id IN ({placeholders}) AND c.review_status<>'merged'
                ORDER BY c.updated_at DESC""",
                issue_ids,
            ).fetchall()
        return {"issue": dict(issue), "claims": [dict(row) for row in claims]}


    @router.get("/api/legal-knowledge/claims")
    def list_legal_knowledge_claims(
        status: str = "pending", issue_id: Optional[int] = None, q: str = "", domain: str = "",
        category_id: Optional[int] = None, limit: int = 200
    ):
        where, params = [], []
        if status and status != "all":
            where.append("c.review_status=?")
            params.append(status)
        elif status == "all":
            # “已合并”已有独立标签；全部视图仅展示当前有效记录。
            where.append("c.review_status<>'merged'")
        where.append("i.status='active'")
        if issue_id:
            where.append("ci.issue_id=?")
            params.append(issue_id)
        if q.strip():
            where.append("(c.statement LIKE ? OR i.title LIKE ?)")
            params.extend([f"%{q.strip()}%", f"%{q.strip()}%"])
        if domain.strip():
            where.append("i.domain=?")
            params.append(domain.strip())
        if category_id:
            where.append("(icategory.category_id=? OR cat.parent_id=?)")
            params.extend([category_id, category_id])
        with get_db() as conn:
            rows = conn.execute(
                f"""SELECT c.*,GROUP_CONCAT(DISTINCT i.title) AS issue_titles,
                       GROUP_CONCAT(DISTINCT i.domain) AS issue_domains,
                       COUNT(DISTINCT e.id) AS evidence_count
                FROM knowledge_claims c
                JOIN knowledge_claim_issues ci ON ci.claim_id=c.id
                JOIN knowledge_issues i ON i.id=ci.issue_id
                LEFT JOIN knowledge_issue_categories icategory ON icategory.issue_id=i.id
                LEFT JOIN knowledge_categories cat ON cat.id=icategory.category_id
                LEFT JOIN knowledge_claim_evidence e ON e.claim_id=c.id AND e.verified=1
                {'WHERE ' + ' AND '.join(where) if where else ''}
                GROUP BY c.id ORDER BY c.updated_at DESC,c.id DESC LIMIT ?""",
                (*params, max(1, min(limit, 1000))),
            ).fetchall()
        return {"claims": [dict(row) for row in rows]}


    @router.get("/api/legal-knowledge/claims/{claim_id}")
    def legal_knowledge_claim_detail(claim_id: int):
        with get_db() as conn:
            item = get_knowledge_claim_detail(conn, claim_id)
        if not item:
            raise HTTPException(status_code=404, detail="知识结论不存在")
        return item


    @router.put("/api/legal-knowledge/claims/{claim_id}")
    def update_legal_knowledge_claim(claim_id: int, payload: KnowledgeClaimUpdate):
        editable = {
            "statement", "claim_type", "conditions_text", "exceptions_text", "procedural_stage",
            "jurisdiction", "court_level", "authority_type", "authority_level", "valid_from", "valid_to",
            "reviewer_note",
        }
        values = payload.model_dump(exclude_unset=True)
        with get_db() as conn:
            before_row = _knowledge_claim_row(conn, claim_id)
            before = dict(before_row)
            updates, params = [], []
            for key in editable:
                if key not in values:
                    continue
                value = (values[key] or "").strip() if isinstance(values[key], str) or values[key] is None else values[key]
                if key == "statement":
                    if len(normalize_knowledge_text(value)) < 8:
                        raise HTTPException(status_code=400, detail="结论内容过短")
                    updates.extend(["statement=?", "normalized_statement=?"])
                    params.extend([value[:1200], normalize_knowledge_text(value)])
                elif key == "claim_type":
                    if value not in KNOWLEDGE_CLAIM_TYPES:
                        raise HTTPException(status_code=400, detail="结论类型无效")
                    updates.append("claim_type=?")
                    params.append(value)
                else:
                    updates.append(f"{key}=?")
                    params.append(value[:1200] if isinstance(value, str) else value)
            now = datetime.datetime.now().isoformat()
            if updates:
                updates.append("updated_at=?")
                params.extend([now, claim_id])
                conn.execute(f"UPDATE knowledge_claims SET {','.join(updates)} WHERE id=?", params)
            if values.get("issue_titles") is not None:
                titles = [str(title).strip() for title in values["issue_titles"] if str(title).strip()]
                if not titles:
                    raise HTTPException(status_code=400, detail="至少保留一个法律问题")
                domain_row = conn.execute(
                    """SELECT i.domain FROM knowledge_issues i
                   JOIN knowledge_claim_issues ci ON ci.issue_id=i.id
                   WHERE ci.claim_id=? ORDER BY ci.is_primary DESC,i.id LIMIT 1""",
                    (claim_id,),
                ).fetchone()
                issue_domain = (domain_row["domain"] if domain_row else "综合法律") or "综合法律"
                conn.execute("DELETE FROM knowledge_claim_issues WHERE claim_id=?", (claim_id,))
                for index, title in enumerate(titles):
                    key = normalize_knowledge_text(title)
                    issue = conn.execute(
                        "SELECT id FROM knowledge_issues WHERE normalized_title=? AND domain=? AND status='active'",
                        (key, issue_domain),
                    ).fetchone()
                    if issue:
                        issue_id = issue["id"]
                    else:
                        cur = conn.execute(
                            """INSERT INTO knowledge_issues
                           (title,normalized_title,domain,status,created_at,updated_at)
                           VALUES (?,?,?,'active',?,?)""", (title[:180], key, issue_domain, now, now)
                        )
                        issue_id = cur.lastrowid
                    conn.execute(
                        "INSERT INTO knowledge_claim_issues(claim_id,issue_id,is_primary) VALUES (?,?,?)",
                        (claim_id, issue_id, int(index == 0)),
                    )
            if values.get("relations") is not None:
                conn.execute("DELETE FROM knowledge_claim_relations WHERE from_claim_id=?", (claim_id,))
                for relation in values["relations"]:
                    relation_type = str(relation.get("relation_type") or "")
                    target_id = int(relation.get("target_id") or 0)
                    if relation_type not in KNOWLEDGE_RELATION_TYPES or not target_id or target_id == claim_id:
                        continue
                    if conn.execute("SELECT id FROM knowledge_claims WHERE id=?", (target_id,)).fetchone():
                        conn.execute(
                            """INSERT OR IGNORE INTO knowledge_claim_relations
                           (from_claim_id,to_claim_id,relation_type,created_at) VALUES (?,?,?,?)""",
                            (claim_id, target_id, relation_type, now),
                        )
            after = dict(_knowledge_claim_row(conn, claim_id))
            audit_knowledge_change(conn, "claim", claim_id, "edit", before, after)
            conn.commit()
            knowledge_search.invalidate(conn)
            result = get_knowledge_claim_detail(conn, claim_id)
        return result


    @router.post("/api/legal-knowledge/claims/{claim_id}/review")
    def review_legal_knowledge_claim(claim_id: int, payload: KnowledgeReviewPayload):
        action_map = {
            "approve": "approved", "reject": "rejected", "return_to_pending": "pending",
            "mark_needs_review": "needs_review",
        }
        target = action_map.get(payload.action)
        if not target:
            raise HTTPException(status_code=400, detail="审核动作无效")
        with get_db() as conn:
            before = dict(_knowledge_claim_row(conn, claim_id))
            if before["review_status"] == "merged":
                raise HTTPException(status_code=400, detail="已合并结论不能直接审核，请先撤销合并")
            if target == "approved":
                count = conn.execute(
                    "SELECT COUNT(*) FROM knowledge_claim_evidence WHERE claim_id=? AND verified=1", (claim_id,)
                ).fetchone()[0]
                if not count:
                    raise HTTPException(status_code=400, detail="至少需要一项经核验的原文依据才能通过")
            now = datetime.datetime.now().isoformat()
            conn.execute(
                """UPDATE knowledge_claims SET review_status=?,reviewer_note=?,reviewed_at=?,updated_at=? WHERE id=?""",
                (target, payload.note.strip()[:500], now if target in {"approved", "rejected"} else None, now, claim_id),
            )
            after = dict(_knowledge_claim_row(conn, claim_id))
            audit_knowledge_change(conn, "claim", claim_id, payload.action, before, after)
            conn.commit()
            knowledge_search.invalidate(conn)
        return {"success": True, "claim": after}


    @router.post("/api/legal-knowledge/claims/{claim_id}/merge")
    def merge_legal_knowledge_claim(claim_id: int, payload: KnowledgeMergePayload):
        with get_db() as conn:
            before = dict(_knowledge_claim_row(conn, claim_id))
            if payload.undo:
                if before["review_status"] != "merged":
                    raise HTTPException(status_code=400, detail="该结论没有处于合并状态")
                now = datetime.datetime.now().isoformat()
                conn.execute(
                    "UPDATE knowledge_claims SET review_status='pending',merged_into_id=NULL,updated_at=? WHERE id=?",
                    (now, claim_id),
                )
                action = "unmerge"
            else:
                target_id = int(payload.target_id or 0)
                if not target_id or target_id == claim_id:
                    raise HTTPException(status_code=400, detail="请选择不同的目标结论")
                target = _knowledge_claim_row(conn, target_id)
                if target["review_status"] == "merged":
                    raise HTTPException(status_code=400, detail="不能合并到另一个已合并结论")
                now = datetime.datetime.now().isoformat()
                conn.execute(
                    "UPDATE knowledge_claims SET review_status='merged',merged_into_id=?,updated_at=? WHERE id=?",
                    (target_id, now, claim_id),
                )
                action = "merge"
            after = dict(_knowledge_claim_row(conn, claim_id))
            audit_knowledge_change(conn, "claim", claim_id, action, before, after)
            conn.commit()
        return {"success": True, "claim": after}


    @router.post("/api/legal-knowledge/issues/{issue_id}/merge")
    def merge_legal_knowledge_issue(issue_id: int, payload: KnowledgeMergePayload):
        with get_db() as conn:
            if payload.undo:
                after = _unmerge_knowledge_issue_records(conn, issue_id)
            else:
                target_id = int(payload.target_id or 0)
                if not target_id:
                    raise HTTPException(status_code=400, detail="请选择不同的目标问题")
                after = _merge_knowledge_issue_records(conn, issue_id, target_id, "merge")
            conn.commit()
        return {"success": True, "issue": after}


    @router.get("/api/articles/{article_id}/knowledge")
    def get_article_knowledge(article_id: int):
        with get_db() as conn:
            if not conn.execute("SELECT id FROM articles WHERE id=?", (article_id,)).fetchone():
                raise HTTPException(status_code=404, detail="文章不存在")
            return article_knowledge(conn, article_id)


    def _run_relation_backfill_job(job_id: int) -> None:
        """Run a resumable local scan and enqueue AI only for non-long articles."""
        with get_db() as conn:
            stamp = datetime.datetime.now().isoformat(timespec="seconds")
            conn.execute(
                """UPDATE relation_backfill_jobs SET status='running',
               started_at=COALESCE(started_at,?),error='',updated_at=? WHERE id=?""",
                (stamp, stamp, job_id),
            )
            conn.commit()
        while True:
            with get_db() as conn:
                job = conn.execute(
                    "SELECT * FROM relation_backfill_jobs WHERE id=?", (job_id,)
                ).fetchone()
                if not job or job["status"] != "running":
                    return
                article = conn.execute(
                    "SELECT id FROM articles WHERE id>? ORDER BY id LIMIT 1",
                    (int(job["cursor_article_id"] or 0),),
                ).fetchone()
                if not article:
                    stamp = datetime.datetime.now().isoformat(timespec="seconds")
                    conn.execute(
                        """UPDATE relation_backfill_jobs SET status='completed',
                       completed_at=?,updated_at=? WHERE id=?""", (stamp, stamp, job_id)
                    )
                    conn.commit()
                    return
                article_id = int(article["id"])
                try:
                    scan_article_relation_rules(conn, article_id)
                    estimate = relation_scan_estimate(conn, article_id)
                    conn.execute(
                        """UPDATE relation_backfill_jobs SET cursor_article_id=?,
                       processed_articles=processed_articles+1,updated_at=? WHERE id=?""",
                        (article_id, datetime.datetime.now().isoformat(timespec="seconds"), job_id),
                    )
                    conn.commit()
                except Exception as exc:
                    stamp = datetime.datetime.now().isoformat(timespec="seconds")
                    conn.execute(
                        """UPDATE relation_backfill_jobs SET status='failed',error=?,
                       updated_at=? WHERE id=?""", (str(exc)[:1200], stamp, job_id)
                    )
                    conn.commit()
                    return
            # The server-side guard is deliberately stricter than the UI: a
            # backfill can never authorize AI for a long article, even if opened.
            if not estimate["long_article"] and not estimate["cached_ai"]:
                try:
                    _job_id, created = knowledge_jobs.enqueue(
                        article_id, "relation_backfill", force=False
                    )
                except HTTPException:
                    created = False
                if created:
                    with get_db() as conn:
                        conn.execute(
                            """UPDATE relation_backfill_jobs SET ai_jobs_created=ai_jobs_created+1,
                           updated_at=? WHERE id=?""",
                            (datetime.datetime.now().isoformat(timespec="seconds"), job_id),
                        )
                        conn.commit()


    @router.get("/api/articles/{article_id}/relations")
    def article_relation_list(article_id: int):
        with get_db() as conn:
            if not conn.execute("SELECT 1 FROM articles WHERE id=?", (article_id,)).fetchone():
                raise HTTPException(status_code=404, detail="文章不存在")
            return get_article_relations(conn, article_id)


    @router.get("/api/articles/{article_id}/relation-scan-estimate")
    def article_relation_scan_estimate(article_id: int):
        with get_db() as conn:
            try:
                return relation_scan_estimate(conn, article_id)
            except LookupError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc


    @router.post("/api/articles/{article_id}/relation-open")
    def article_relation_open(article_id: int):
        with get_db() as conn:
            try:
                result = mark_relation_article_opened(conn, article_id)
                # Unchanged inputs reuse the revision-checked deterministic result.
                with measure_phase('relation-scan'):
                    scan_article_relation_rules(conn, article_id)
                conn.commit()
                return result
            except LookupError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc


    @router.post("/api/articles/{article_id}/relation-scan")
    def article_relation_scan(article_id: int, payload: RelationScanPayload):
        with get_db() as conn:
            try:
                rule_result = scan_article_relation_rules(conn, article_id)
                estimate = relation_scan_estimate(conn, article_id)
                if payload.dismiss_ai_prompt:
                    mark_relation_ai_prompted(conn, article_id, estimate["content_hash"])
                conn.commit()
            except LookupError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc

        ai_job = None
        ai_created = False
        ai_reason = "not_requested"
        if payload.use_ai:
            with get_db() as conn:
                allowed, guard = relation_ai_scan_allowed(
                    conn, article_id, payload.confirmed_long_article_cost
                )
                if guard["long_article"]:
                    if allowed:
                        authorize_relation_ai_scan(conn, article_id, guard["content_hash"])
                    else:
                        mark_relation_ai_prompted(conn, article_id, guard["content_hash"])
                    conn.commit()
            ai_reason = guard["reason"]
            if allowed:
                ai_job, ai_created = knowledge_jobs.enqueue(
                    article_id, "relation_scan", force=False
                )
        return {
            "success": True,
            "rule_scan": rule_result,
            "ai_job_id": ai_job,
            "ai_created": ai_created,
            "ai_reason": ai_reason,
        }


    @router.put("/api/knowledge-mentions/{mention_id}")
    def update_knowledge_mention(mention_id: int, payload: KnowledgeMentionReviewPayload):
        with get_db() as conn:
            try:
                result = review_knowledge_mention(
                    conn, mention_id, status=payload.status,
                    relation_type=payload.relation_type,
                    target_node_id=payload.target_node_id,
                )
                conn.commit()
                return {"success": True, "mention": result}
            except LookupError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc


    @router.get("/api/knowledge-nodes/search")
    def knowledge_node_search(q: str = "", limit: int = 30):
        with get_db() as conn:
            return {"items": search_relation_nodes(conn, q, limit)}


    @router.get("/api/knowledge-nodes/{node_id}")
    def knowledge_node_detail(node_id: int):
        with get_db() as conn:
            result = get_relation_node_detail(conn, node_id)
            if not result:
                raise HTTPException(status_code=404, detail="知识节点不存在")
            result["relation_labels"] = knowledge_relation_labels()
            return result


    @router.get("/api/knowledge-relations/backfill")
    def relation_backfill_status(job_id: int = 0):
        with get_db() as conn:
            return {
                "job": get_relation_backfill_job(conn, job_id or None),
                "long_article_chars": RELATION_LONG_ARTICLE_CHARS,
            }


    @router.post("/api/knowledge-relations/backfill")
    def control_relation_backfill(
        payload: RelationBackfillControlPayload, background_tasks: BackgroundTasks
    ):
        action = (payload.action or "start").strip().lower()
        with get_db() as conn:
            if action == "pause":
                job = get_relation_backfill_job(conn)
                if not job or job["status"] not in {"queued", "running"}:
                    raise HTTPException(status_code=409, detail="当前没有可暂停的关系回扫任务")
                conn.execute(
                    "UPDATE relation_backfill_jobs SET status='paused',updated_at=? WHERE id=?",
                    (datetime.datetime.now().isoformat(timespec="seconds"), job["id"]),
                )
                conn.commit()
                return {"success": True, "job_id": job["id"], "status": "paused"}
            if action not in {"start", "resume"}:
                raise HTTPException(status_code=400, detail="action 仅支持 start、pause、resume")
            job_id = create_relation_backfill_job(conn)
            job = get_relation_backfill_job(conn, job_id)
            if action == "resume" or job["status"] in {"queued", "paused"}:
                conn.execute(
                    "UPDATE relation_backfill_jobs SET status='queued',updated_at=? WHERE id=?",
                    (datetime.datetime.now().isoformat(timespec="seconds"), job_id),
                )
            conn.commit()
        background_tasks.add_task(_run_relation_backfill_job, job_id)
        return {"success": True, "job_id": job_id, "status": "queued"}


    @router.post("/api/articles/{article_id}/knowledge-extract")
    async def extract_article_knowledge(
        article_id: int, force: bool = True, confirmed_long_article_cost: bool = False
    ):
        with get_db() as conn:
            allowed, guard = relation_ai_scan_allowed(
                conn, article_id, confirmed_long_article_cost
            )
            if guard["long_article"] and not guard["cached_ai"]:
                if not allowed:
                    raise HTTPException(
                        status_code=409,
                        detail="超长文章必须在阅读页确认预计批次数后才能启动 AI 扫描",
                    )
                authorize_relation_ai_scan(conn, article_id, guard["content_hash"])
                conn.commit()
        job_id, created = knowledge_jobs.enqueue(article_id, "manual", force=force)
        return {"success": True, "job_id": job_id, "created": created, "status": "queued" if created else "existing"}


    @router.post("/api/legal-knowledge/extractions/batch")
    async def batch_extract_legal_knowledge(payload: KnowledgeBatchPayload):
        jobs, created_count = [], 0
        with get_db() as conn:
            candidates = knowledge_candidate_ids(conn, payload.domain)
        for article_id in candidates:
            with get_db() as conn:
                estimate = relation_scan_estimate(conn, article_id)
            if estimate["long_article"] and not estimate["cached_ai"]:
                jobs.append({
                    "article_id": article_id, "job_id": None, "created": False,
                    "reason": "超长文章需打开后确认费用",
                })
                continue
            job_id, created = knowledge_jobs.enqueue(article_id, "library_batch", force=payload.force)
            jobs.append({"article_id": article_id, "job_id": job_id, "created": created})
            created_count += int(created)
        return {
            "success": True,
            "candidate_count": len(candidates),
            "created_count": created_count,
            "skipped_count": len(candidates) - created_count,
            "jobs": jobs,
        }


    @router.post("/api/legal-knowledge/extractions/cancel")
    def cancel_queued_legal_knowledge_extractions():
        """Cancel work that has not started; let the current article finish safely."""
        with get_db() as conn:
            now = datetime.datetime.now().isoformat()
            queued_count = int(conn.execute(
                "SELECT COUNT(*) FROM knowledge_extraction_jobs WHERE status='queued'"
            ).fetchone()[0])
            running_count = int(conn.execute(
                "SELECT COUNT(*) FROM knowledge_extraction_jobs WHERE status='running'"
            ).fetchone()[0])
            conn.execute(
                """UPDATE knowledge_extraction_jobs
               SET status='cancelled',error='用户停止了剩余处理',completed_at=?,updated_at=?
               WHERE status='queued'""",
                (now, now),
            )
            conn.commit()
        return {
            "success": True,
            "cancelled_count": queued_count,
            "running_count": running_count,
            "message": "正在处理的文章完成后停止" if running_count else "已停止全部等待任务",
        }


    @router.post("/api/legal-knowledge/extractions/skip")
    async def skip_selected_knowledge_articles(payload: KnowledgeArticleSelectionPayload):
        return await knowledge_jobs.stop_selected(payload.article_ids, exclude=True)


    @router.post("/api/legal-knowledge/extractions/stop")
    async def stop_selected_knowledge_articles(payload: KnowledgeArticleSelectionPayload):
        return await knowledge_jobs.stop_selected(payload.article_ids, exclude=False)


    @router.post("/api/legal-knowledge/extractions/resume")
    async def resume_selected_knowledge_articles(payload: KnowledgeArticleSelectionPayload):
        selected = sorted({int(value) for value in payload.article_ids if int(value) > 0})
        if not selected:
            raise HTTPException(status_code=400, detail="请至少选择一篇文章")
        placeholders = ",".join("?" for _ in selected)
        with get_db() as conn:
            conn.execute(
                f"DELETE FROM knowledge_extraction_exclusions WHERE article_id IN ({placeholders})", selected
            )
            conn.commit()
        jobs = []
        for article_id in selected:
            job_id, created = knowledge_jobs.enqueue(article_id, "resume_after_skip", force=False)
            jobs.append({"article_id": article_id, "job_id": job_id, "created": created})
        return {"success": True, "resumed_count": len(selected), "jobs": jobs}


    @router.get("/api/legal-knowledge/extractions")
    def list_legal_knowledge_extractions(status: str = "", limit: int = 200, latest_only: bool = False):
        clauses, params = [], []
        if latest_only:
            clauses.append("j.id IN (SELECT MAX(id) FROM knowledge_extraction_jobs GROUP BY article_id)")
        if status:
            clauses.append("j.status=?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with get_db() as conn:
            rows = conn.execute(
                f"""SELECT j.*,a.title AS article_title,
                CASE WHEN x.article_id IS NULL THEN 0 ELSE 1 END AS excluded
                FROM knowledge_extraction_jobs j
                JOIN articles a ON a.id=j.article_id
                LEFT JOIN knowledge_extraction_exclusions x ON x.article_id=j.article_id {where}
                ORDER BY j.id DESC LIMIT ?""", (*params, max(1, min(limit, 1000)))
            ).fetchall()
            total = int(conn.execute(
                f"SELECT COUNT(*) FROM knowledge_extraction_jobs j {where}", params
            ).fetchone()[0])
            count_clauses = []
            if latest_only:
                count_clauses.append("j.id IN (SELECT MAX(id) FROM knowledge_extraction_jobs GROUP BY article_id)")
            count_where = f"WHERE {' AND '.join(count_clauses)}" if count_clauses else ""
            counts = {
                row["status"]: int(row["n"])
                for row in conn.execute(
                    f"SELECT j.status,COUNT(*) n FROM knowledge_extraction_jobs j {count_where} GROUP BY j.status"
                ).fetchall()
            }
        return {"jobs": [_knowledge_job_dict(row) for row in rows], "total": total, "counts": counts}


    @router.get("/legal-knowledge")
    async def legal_knowledge_page():
        """法律知识中心独立页面。"""
        file_path = frontend_dir / "legal-knowledge.html"
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="法律知识中心页面不存在")
        async with aiofiles.open(str(file_path), mode="r", encoding="utf-8") as file:
            content = await file.read()
        return HTMLResponse(
            content=content,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )

    return KnowledgeCenter(router, _search_local_knowledge_cards)
