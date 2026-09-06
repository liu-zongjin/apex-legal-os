"""Minimal FinChina MCP client for verified company-profile imports."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List

import httpx

from .ai_config import FINCHINA_API_KEY, FINCHINA_MCP_URL
from .mcp_tool_router import discover_streamable_http_tools, plan_mcp_tool_calls


COMPANY_PROFILE_INDICATORS = [
    "企业名称", "统一社会信用代码", "法定代表人", "注册资本", "成立日期",
    "注册地址", "通信地址", "经营范围", "登记状态", "企业性质", "行业", "地区",
]


class FinChinaError(RuntimeError):
    pass


async def _call_finchina_mcp(rpc_payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    """Execute a JSON-RPC request in a fresh, properly initialized MCP session.

    财汇的 Streamable HTTP endpoint validates the MCP session before accepting
    ``tools/call``.  Posting a tool call directly used to work with an older
    gateway, but its current protocol layer rejects that shape with
    “协议层异常，请求参数不符合规范”.
    """
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "x-api-key": FINCHINA_API_KEY,
    }
    initialize_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "legal-knowledge-base", "version": "1.0.0"},
        },
    }
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            initialized = await client.post(FINCHINA_MCP_URL, json=initialize_payload, headers=headers)
            _decode_mcp_envelope(initialized)
            session_headers = dict(headers)
            session_id = initialized.headers.get("mcp-session-id")
            if session_id:
                session_headers["mcp-session-id"] = session_id
            await client.post(
                FINCHINA_MCP_URL,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers=session_headers,
            )
            response = await client.post(FINCHINA_MCP_URL, json=rpc_payload, headers=session_headers)
        return _decode_mcp_response(response)
    except httpx.TimeoutException as exc:
        raise FinChinaError("财汇查询超时，请稍后重试") from exc
    except httpx.HTTPStatusError as exc:
        raise FinChinaError(f"财汇服务连接失败（HTTP {exc.response.status_code}）") from exc
    except httpx.RequestError as exc:
        raise FinChinaError("当前无法连接财汇服务") from exc


def _decode_mcp_envelope(response: httpx.Response) -> Dict[str, Any]:
    """Decode a JSON-RPC/SSE envelope, including replies with no tool content."""
    response.raise_for_status()
    raw = response.text.strip()
    values = [line[5:].strip() for line in raw.splitlines() if line.startswith("data:")]
    for value in reversed(values or [raw]):
        try:
            envelope = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(envelope, dict):
            continue
        if envelope.get("error"):
            message = (envelope.get("error") or {}).get("message") or "财汇 MCP 调用失败"
            raise FinChinaError(str(message))
        return envelope
    raise FinChinaError("财汇服务返回了无法识别的数据")


async def _execute_tool(tool_name: str, arguments: Dict[str, Any], timeout: float = 35.0) -> Dict[str, Any]:
    """Call one FinChina second-level tool and return its decoded payload."""
    if not FINCHINA_API_KEY:
        raise FinChinaError("尚未配置财汇 MCP 密钥")
    rpc_payload = {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {
            "name": "execute_tool",
            "arguments": {"tool_name": tool_name, "arguments": arguments},
        },
    }
    payload = await _call_finchina_mcp(rpc_payload, timeout)
    status = payload.get("status") or {}
    if status.get("code") not in (0, 1, "0", "1"):
        detail = status.get("info") or status.get("message") or "财汇查询失败"
        raise FinChinaError(str(detail))
    return payload


def _decode_mcp_response(response: httpx.Response) -> Dict[str, Any]:
    response.raise_for_status()
    raw = response.text.strip()
    if raw.startswith("event:") or raw.startswith("data:"):
        raw = "\n".join(line[6:] for line in raw.splitlines() if line.startswith("data: ")).strip()
    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FinChinaError("财汇服务返回了无法识别的数据") from exc
    if envelope.get("error"):
        message = (envelope.get("error") or {}).get("message") or "财汇 MCP 调用失败"
        raise FinChinaError(str(message))
    content = (envelope.get("result") or {}).get("content") or []
    text = "".join(
        str(item.get("text") or "")
        for item in content
        if isinstance(item, dict) and item.get("type") == "text"
    )
    if not text:
        raise FinChinaError("财汇服务未返回企业信息")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise FinChinaError("财汇企业信息格式异常") from exc


def _profile_rows(payload: Dict[str, Any]) -> Dict[str, str]:
    """Convert 财汇's indicator rows into a ``指标名 -> 指标值`` mapping.

    ``get_company_basic_info`` returns three columns (企业名称、指标名、指标值),
    rather than the two columns this client originally expected.  The old
    positional parser consequently treated the company name as the key and
    the indicator name as its value, dropping every actual profile field.
    Keep compatibility with a two-column response while preferring the
    column names supplied by the MCP response.
    """
    records = ((payload.get("data") or {}).get("records") or {})
    result: Dict[str, str] = {}
    heads = records.get("headInfo") or []
    key_index = value_index = None
    for index, head in enumerate(heads):
        if not isinstance(head, dict):
            continue
        field = str(head.get("field") or "").strip()
        name = str(head.get("name") or "").strip()
        if field in {"index_name", "indicator_name"} or name in {"指标名", "指标名称"}:
            key_index = index
        elif field in {"index_value", "indicator_value"} or name in {"指标值", "指标内容"}:
            value_index = index

    for row in records.get("data") or []:
        if not isinstance(row, list) or len(row) < 2:
            continue
        if key_index is not None and value_index is not None:
            if len(row) <= max(key_index, value_index):
                continue
            key = str(row[key_index] or "").strip()
            value = str(row[value_index] or "").strip()
        elif len(row) >= 3:
            # Current 财汇 schema without headInfo: 企业名称、指标名、指标值。
            key = str(row[1] or "").strip()
            value = str(row[2] or "").strip()
        else:
            # Legacy two-column schema: 指标名、指标值。
            key = str(row[0] or "").strip()
            value = str(row[1] or "").strip()
        if key and value and key not in result:
            result[key] = value
    return result


async def lookup_company_profile(company_name: str) -> Dict[str, Any]:
    name = str(company_name or "").strip()
    if not FINCHINA_API_KEY:
        raise FinChinaError("尚未配置财汇 MCP 密钥")
    if not name:
        raise FinChinaError("请先输入法人客户名称")
    if len(name) > 120:
        raise FinChinaError("法人客户名称过长")

    rpc_payload = {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {
            "name": "execute_tool",
            "arguments": {
                "tool_name": "get_company_basic_info",
                "arguments": {"target_company": [name], "indicator_name": COMPANY_PROFILE_INDICATORS},
            },
        },
    }
    payload = await _call_finchina_mcp(rpc_payload, 25.0)

    status = payload.get("status") or {}
    if status.get("code") not in (0, 1, "0", "1"):
        detail = status.get("info") or status.get("message") or "财汇企业查询失败"
        raise FinChinaError(str(detail))
    rows = _profile_rows(payload)
    if not rows:
        raise FinChinaError("未找到匹配的法人客户，请核对企业全称")

    target_detail = ((status.get("paramDetails") or {}).get("target_company") or {})
    matched_name = str(target_detail.get("standardized") or rows.get("企业名称") or name).strip()
    capital = rows.get("注册资本(万元)") or rows.get("注册资本") or ""
    currency = rows.get("注册资本币种") or ""
    registered_capital = f"{capital}万元{currency}" if capital and "万" not in capital else capital
    industry = (
        rows.get("国标行业小类") or rows.get("国标行业中类")
        or rows.get("国标行业大类") or rows.get("国标行业门类") or ""
    )
    region_parts = [rows.get("所属省", ""), rows.get("所属市", ""), rows.get("所属区县", "")]
    region = " / ".join(dict.fromkeys(part for part in region_parts if part))
    return {
        "name": matched_name,
        "matched_name": matched_name,
        "identity_code": rows.get("统一社会信用代码", ""),
        "legal_representative": rows.get("法定代表人", ""),
        "address": rows.get("注册地址") or rows.get("通信地址") or "",
        "registered_capital": registered_capital,
        "establishment_date": rows.get("成立日期", ""),
        "registration_status": rows.get("登记状态", ""),
        "business_scope": rows.get("经营范围", ""),
        "enterprise_nature": rows.get("企业性质", ""),
        "industry": industry,
        "region": region,
        "data_source": "财汇企业预警通",
        "source_checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "match_message": str(target_detail.get("message") or "").strip(),
    }


async def lookup_company_profile_with_legal_representative_title(company_name: str) -> Dict[str, Any]:
    """Retrieve the company profile and the legal representative's current executive title.

    The basic-profile tool identifies the legal representative; the executive tool
    is then queried for the same standardized company and matched by name.  A
    missing executive match is valid (for example, a sole proprietor) and leaves
    the optional title blank.
    """
    profile = await lookup_company_profile(company_name)
    representative = str(profile.get("legal_representative") or "").strip()
    target_company = str(profile.get("matched_name") or profile.get("name") or company_name).strip()
    profile["legal_representative_title"] = ""
    if not representative or not target_company:
        return profile
    try:
        payload = await _execute_tool(
            "get_company_executives", {"target_company": [target_company], "limit": 100}
        )
        titles: List[str] = []
        for row in _record_dicts(payload):
            executive_name = _first(row, "senior_management_name", "高管名称", "姓名")
            if executive_name != representative:
                continue
            title = _first(row, "senior_management_position", "高管职位", "职务")
            if title and title not in titles:
                titles.append(title)
        profile["legal_representative_title"] = "、".join(titles)
    except FinChinaError:
        # Basic profile remains useful when executive data is temporarily absent.
        pass
    return profile


def _readable_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        values = [_readable_value(item) for item in value.values()]
        return "、".join(dict.fromkeys(item for item in values if item))
    if isinstance(value, (list, tuple)):
        values = [_readable_value(item) for item in value]
        return "、".join(dict.fromkeys(item for item in values if item))
    text = str(value).strip()
    return "" if text in ("-", "None", "null") else text


def _record_dicts(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    records = (payload.get("data") or {}).get("records") or {}
    heads = records.get("headInfo") or []
    result: List[Dict[str, str]] = []
    for raw_row in records.get("data") or []:
        if not isinstance(raw_row, list):
            continue
        row: Dict[str, str] = {}
        for index, head in enumerate(heads):
            if index >= len(raw_row) or not isinstance(head, dict):
                continue
            value = _readable_value(raw_row[index])
            field = str(head.get("field") or "").strip()
            name = str(head.get("name") or "").strip()
            if field:
                row[field] = value
            if name:
                row[name] = value
        result.append(row)
    return result


def _first(row: Dict[str, str], *keys: str) -> str:
    return next((str(row.get(key) or "").strip() for key in keys if str(row.get(key) or "").strip()), "")


def _event_body(row: Dict[str, str], fields: Iterable[str]) -> str:
    lines, seen = [], set()
    for field in fields:
        value = str(row.get(field) or "").strip()
        if value and value not in seen:
            seen.add(value)
            lines.append(f"{field}：{value}")
    return "\n".join(lines)


def _event_url(category: str, row: Dict[str, str], title: str, published_at: str) -> str:
    original = _first(row, "original_url", "外部原文链接")
    if original.startswith(("http://", "https://")):
        return original
    raw = json.dumps(row, ensure_ascii=False, sort_keys=True) or f"{title}|{published_at}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"finchina://{category}/{digest}"


def _normalize_enterprise_event(category: str, row: Dict[str, str]) -> Dict[str, Any]:
    if category == "judicial":
        company = _first(row, "litigant_name", "当事人名称")
        cause = _first(row, "cause_of_action", "案由")
        title = _first(row, "case_name", "案件名称") or f"{company} · {cause or '司法案件'}"
        published = _first(row, "publish_date", "案件更新日期", "latest_proceeding_date", "最新进程时间")
        fields = ("当事人名称", "案件身份", "案由", "案件类型", "涉案金额", "案号", "最新进程", "最新进程时间", "法院", "案件更新日期")
        domain = "企业诉讼"
    elif category == "penalty":
        company = _first(row, "penalized_party", "企业名称")
        penalty_type = _first(row, "penalty_type", "处罚类型", "credit_type", "信用类型")
        agency = _first(row, "regulatory_agency", "处理机构")
        title = f"{company} · {penalty_type or '监管处罚'}" + (f"（{agency}）" if agency else "")
        published = _first(row, "disclosure_date", "披露日期")
        fields = ("企业名称", "披露日期", "信用类型", "处罚类型", "罚没金额", "违规类型", "违规事项", "文号", "处理机构", "法规依据", "关联主体", "关联类型")
        domain = "监管合规"
    elif category == "news":
        company = _first(row, "企业全称", "target_company")
        title = _first(row, "title", "资讯标题") or f"{company or '企业'} · 舆情动态"
        published = _first(row, "date", "发布日期")
        related = _first(row, "related_companies", "关联企业集合")
        if not company and related:
            company = related.split("、", 1)[0]
        fields = ("资讯标题", "发布日期", "来源", "资讯摘要", "关联企业集合")
        domain = "企业舆情"
    elif category == "dishonest":
        company = _first(row, "失信被执行人", "企业名称", "dishonest_debtor")
        case_number = _first(row, "案号", "case_number")
        performance = _first(row, "履行情况", "performance_status")
        title = f"{company or '目标企业'} · 失信被执行人" + (f"（{performance}）" if performance else "")
        published = _first(row, "发布日期", "立案时间", "publish_date")
        fields = ("失信被执行人", "案号", "履行情况", "失信行为具体情形", "执行依据文号", "执行法院", "申请执行人", "发布日期")
        domain = "失信执行"
    elif category == "changes":
        company = _first(row, "企业名称", "公司名称", "target_company")
        change_item = _first(row, "变更项目", "change_item")
        title = f"{company or '目标企业'} · {change_item or '工商变更'}"
        published = _first(row, "变更时间", "核准日期", "change_time")
        fields = ("企业名称", "变更时间", "变更项目", "变更前内容", "变更后内容")
        domain = "工商变更"
    elif category == "ownership":
        company = _first(row, "企业名称", "公司名称", "目标企业", "target_company")
        controller = _first(row, "实际控制人", "受益所有人", "名称", "股东名称")
        title = f"{company or '目标企业'} · {_first(row, '_subtype') or '控制关系'}"
        if controller:
            title += f"：{controller}"
        published = _first(row, "更新日期", "报告期", "date")
        fields = ("企业名称", "实际控制人", "实际控制人性质", "受益所有人", "最终受益比例", "控制比例", "控制路径", "更新日期")
        domain = "股权关系"
    elif category == "encumbrance":
        company = _first(row, "企业名称", "出质标的企业", "抵押人", "target_company")
        subtype = _first(row, "_subtype") or "质押抵押"
        counterparty = _first(row, "质权人", "抵押权人", "抵押权人企业")
        title = f"{company or '目标企业'} · {subtype}" + (f"（权利人：{counterparty}）" if counterparty else "")
        published = _first(row, "公告日期", "登记日期", "noticedate", "perfection_date")
        fields = ("企业名称", "出质人", "质权人", "出质标的企业", "出质股权数额", "公告日期", "登记编号", "登记日期", "抵押人", "抵押权人", "抵押财产描述", "财产价值", "被担保债权数额", "最新登记状态")
        domain = "资产受限"
    elif category == "guarantee":
        company = _first(row, "企业名称", "担保方", "target_company")
        guaranteed = _first(row, "被担保方", "被担保企业")
        status = _first(row, "担保状态", "guarantee_status")
        title = f"{company or '目标企业'} · 担保事项" + (f"（{guaranteed}）" if guaranteed else "")
        published = _first(row, "报告期", "公告日期", "reporting_date")
        fields = ("担保方", "被担保方", "担保金额", "担保起始日", "担保到期日", "担保状态", "担保类型", "报告期")
        domain = "或有负债"
    elif category == "overdue":
        company = _first(row, "票据逾期企业", "违约企业", "发行人", "企业名称", "target_company")
        subtype = _first(row, "_subtype") or "债务风险"
        status = _first(row, "是否结清", "违约状态", "兑付情况", "是否在持续逾期名单")
        title = f"{company or '目标企业'} · {subtype}" + (f"（{status}）" if status else "")
        published = _first(row, "截至月份", "最新违约日期", "首次展期日期", "披露日期", "as_of_month")
        fields = ("票据逾期企业", "截至月份", "逾期余额", "累计逾期发生额", "是否在承兑人逾期名单", "是否在持续逾期名单", "是否结清", "违约企业", "债券简称", "最新违约金额", "最新违约日期", "违约原因", "展期余额", "首次展期日期", "兑付情况")
        domain = "债务风险"
    elif category == "rating":
        company = _first(row, "企业名称", "被评级主体", "主体名称", "target_company")
        rating = _first(row, "主体评级", "信用等级", "最新评级")
        direction = _first(row, "评级变动方向", "评级展望")
        title = f"{company or '目标企业'} · 主体评级 {rating or '更新'}" + (f"（{direction}）" if direction else "")
        published = _first(row, "评级日期", "rating_date")
        fields = ("企业名称", "主体评级", "评级展望", "评级变动方向", "评级机构", "评级日期")
        domain = "信用评级"
    elif category == "finance":
        company = _first(row, "企业名称", "公司名称", "target_company")
        period = _first(row, "报告期", "日期", "date")
        title = f"{company or '目标企业'} · 财务体检" + (f"（{period}）" if period else "")
        published = period
        fields = ("企业名称", "报告期", "营业总收入", "净利润", "资产负债率", "经营活动现金流净额", "总资产", "所有者权益")
        domain = "财务健康"
    else:
        company = _first(row, "企业名称", "公司名称", "target_company")
        title = f"{company or '目标企业'} · 企业动态"
        published = _first(row, "发布日期", "日期", "date")
        fields = tuple(key for key in row.keys() if not key.startswith("_"))
        domain = "企业情报"
    body = _event_body(row, fields)
    summary = _first(row, "summary", "资讯摘要") or "；".join(body.splitlines()[1:5])
    risk_score = _enterprise_risk_score(category, row)
    risk_level = "critical" if risk_score >= 85 else "high" if risk_score >= 65 else "medium" if risk_score >= 40 else "low"
    return {
        "title": title,
        "url": _event_url(category, row, title, published),
        "source_name": "财汇企业预警通",
        "date": published,
        "published_at": published,
        "summary": summary[:1000],
        "search_proof": summary[:500],
        "body_text": body[:12000],
        "domain": domain,
        "category": category,
        "company": company,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "subtype": _first(row, "_subtype"),
        "verification_level": "structured_data",
    }


def _enterprise_risk_score(category: str, row: Dict[str, str]) -> int:
    """Apply a transparent triage score for UI prioritisation, not a legal conclusion."""
    base = {
        "dishonest": 96, "overdue": 88, "penalty": 76, "judicial": 58,
        "rating": 55, "encumbrance": 52, "guarantee": 46, "news": 38,
        "changes": 28, "finance": 24, "ownership": 16,
    }.get(category, 20)
    text = " ".join(str(value or "") for value in row.values())
    high_words = ("全部未履行", "未结清", "持续逾期", "违约", "评级调低", "展望负面", "被执行人", "被告", "逾期")
    medium_words = ("部分未履行", "部分结清", "展期", "处罚", "注销登记", "负面")
    positive_words = ("已结清", "评级调高", "展望正面", "原告", "申请执行人")
    if any(word in text for word in high_words):
        base += 12
    elif any(word in text for word in medium_words):
        base += 7
    if any(word in text for word in positive_words):
        base -= 8
    return max(5, min(base, 100))


async def query_company_intelligence(
    companies: List[str], categories: List[str], days: int = 7, limit_per_category: int = 50,
) -> Dict[str, Any]:
    """Query the selected FinChina due-diligence dimensions for Explore/Radar."""
    normalized_companies = list(dict.fromkeys(str(name or "").strip() for name in companies if str(name or "").strip()))
    if not normalized_companies:
        raise FinChinaError("请至少选择一家法人客户")
    if len(normalized_companies) > 20:
        raise FinChinaError("单次最多查询20家法人客户")
    supported = {
        "judicial", "dishonest", "penalty", "changes", "ownership", "encumbrance",
        "guarantee", "overdue", "rating", "finance", "news",
    }
    allowed = [value for value in dict.fromkeys(categories or []) if value in supported]
    if not allowed:
        raise FinChinaError("请至少选择一类企业情报")
    safe_days = max(1, min(int(days or 7), 3650))
    safe_limit = max(1, min(int(limit_per_category or 50), 100))
    date_text = f"近{safe_days}天"
    specs = {
        "judicial": [("get_company_judicial_case_list", {"target_company": normalized_companies, "publish_date": date_text, "sort_field": "publish_date:desc", "limit": safe_limit}, "司法案件")],
        "dishonest": [("get_company_dishonest_debtor_details", {"dishonest_debtor": normalized_companies, "publish_year": date_text, "limit": safe_limit}, "失信被执行人")],
        "penalty": [("get_company_regulatory_penalty_details", {"target_company": normalized_companies, "disclosure_date": date_text, "sort_field": "disclosure_date:desc", "limit": safe_limit}, "监管处罚")],
        "changes": [("get_company_business_registration_changes", {"target_company": normalized_companies, "change_time": date_text, "sort_field": "change_time:desc", "limit": safe_limit}, "工商变更")],
        "ownership": [
            ("get_company_actual_controller", {"target_company": normalized_companies[:10]}, "实际控制人"),
            ("get_company_beneficial_owners", {"target_company": normalized_companies}, "受益所有人"),
        ],
        "encumbrance": [
            ("get_company_equity_pledge_details", {"target_company": normalized_companies, "sort_field": "noticedate:desc", "limit": safe_limit}, "股权出质"),
            ("get_company_chattel_mortgage_details", {"target_company": normalized_companies, "sort_field": "perfection_date:desc", "limit": safe_limit}, "动产抵押"),
        ],
        "guarantee": [("get_guarantee_event_details", {"target_company": normalized_companies, "reporting_date": date_text, "sort_field": "reporting_date:desc", "limit": safe_limit}, "担保事项")],
        "overdue": [
            ("get_company_bill_overdue_details", {"target_company": normalized_companies, "as_of_month": date_text, "sort_field": "as_of_month:desc", "limit": safe_limit}, "票据逾期"),
            ("get_company_bond_default_details", {"target_company": normalized_companies, "latest_default_start_date": date_text, "sort_field": "latest_default_start_date:desc", "limit": safe_limit}, "债券违约"),
            ("get_company_bond_extension_details", {"target_company": normalized_companies, "sort_field": "company_first_extension_date:desc", "limit": safe_limit}, "债券展期"),
        ],
        "rating": [("get_corporate_credit_ratings", {"target_company": normalized_companies, "rating_date": date_text, "sort_field": "rating_date:desc", "limit": safe_limit}, "主体评级")],
        "finance": [("get_company_financial_metrics", {"target_company": normalized_companies, "indicator_name": ["营业总收入", "净利润", "资产负债率", "经营活动现金流净额"], "date": "近三年年报"}, "财务指标")],
        "news": [("search_news", {"target_company": normalized_companies, "publish_date": date_text, "limit": min(safe_limit, 50)}, "企业舆情")],
    }

    async def run(category: str) -> tuple[str, Dict[str, Any] | Exception]:
        payloads = []
        for tool_name, arguments, subtype in specs[category]:
            try:
                payloads.append((subtype, await _execute_tool(tool_name, arguments)))
            except Exception as exc:
                payloads.append((subtype, exc))
        return category, payloads

    responses = await asyncio.gather(*(run(category) for category in allowed))
    results, errors, totals = [], {}, {}
    for category, payloads in responses:
        totals[category] = 0
        category_errors = []
        for subtype, payload in payloads:
            if isinstance(payload, Exception):
                category_errors.append(f"{subtype}：{payload}")
                continue
            rows = _record_dicts(payload)
            totals[category] += int((((payload.get("data") or {}).get("summary") or {}).get("total_records")) or len(rows))
            for row in rows:
                row["_subtype"] = subtype
                results.append(_normalize_enterprise_event(category, row))
        if category_errors:
            errors[category] = "；".join(category_errors)
    results.sort(key=lambda item: str(item.get("published_at") or ""), reverse=True)
    risk_counts = {
        level: sum(1 for item in results if item.get("risk_level") == level)
        for level in ("critical", "high", "medium", "low")
    }
    return {
        "results": results,
        "total_returned": len(results),
        "total_matches": sum(totals.values()),
        "totals": totals,
        "errors": errors,
        "companies": normalized_companies,
        "categories": allowed,
        "days": safe_days,
        "risk_counts": risk_counts,
        "risk_score": max((int(item.get("risk_score") or 0) for item in results), default=0),
        "data_source": "财汇企业预警通",
    }


async def search_company_candidates(company_keyword: str, limit: int = 1000) -> Dict[str, Any]:
    """Resolve the entered enterprise name for the import picker.

    财汇已将旧版 ``filter_companies_by_basic_info`` 二级工具下线；继续
    调用它会被协议层拒绝。企业基本信息工具本身接受全称、简称及别名，
    因此先解析并返回标准企业名称，随后仍沿用原有的“点选后导入”流程。
    """
    keyword = str(company_keyword or "").strip()
    if not FINCHINA_API_KEY:
        raise FinChinaError("尚未配置财汇 MCP 密钥")
    if not keyword:
        raise FinChinaError("请先输入法人客户名称")
    if len(keyword) > 120:
        raise FinChinaError("法人客户名称过长")
    try:
        profile = await lookup_company_profile(keyword)
    except FinChinaError as exc:
        message = str(exc)
        if "查询超时" in message:
            raise FinChinaError("财汇候选企业查询超时，请稍后重试") from exc
        raise
    matched_name = str(profile.get("matched_name") or profile.get("name") or keyword).strip()
    return {
        "query": keyword,
        "candidates": [{"name": matched_name}],
        "returned": 1,
        "total": 1,
        "truncated": False,
        "data_source": "财汇企业预警通",
    }


# ──────────────────────────────────────────────────────────
# AI增强 · 基于 MCP 搜索：万得财汇
# ──────────────────────────────────────────────────────────

_ASK_INTELLIGENCE_CATEGORIES = [
    "judicial", "dishonest", "penalty", "changes", "ownership",
    "encumbrance", "guarantee", "overdue", "rating", "finance", "news",
]

_ASK_INTELLIGENCE_LIMIT = 8

_FINCHINA_TOOL_CATEGORY_MAP = {
    "query_enterprise_profile": ("changes",),
    "query_enterprise_equity_and_investments": ("ownership",),
    "query_enterprise_financial_data": ("finance",),
    "query_enterprise_guarantee_and_collateral": ("encumbrance", "guarantee"),
    "query_enterprise_credit_and_rating": ("overdue", "rating"),
    "query_enterprise_judicial_litigation": ("judicial", "dishonest"),
    "query_regulatory_penalties_data": ("penalty",),
    "query_enterprise_business_and_bidding": ("news",),
}


async def plan_finchina_intelligence_categories(query: str) -> List[str]:
    """依据财汇实时公布的一级能力，选择需要执行的二级专项工具组。"""
    text = str(query or "").strip()
    if any(marker in text for marker in ("全面尽调", "全部风险", "全面风险", "综合风险", "所有风险", "多维风险")):
        return list(_ASK_INTELLIGENCE_CATEGORIES)
    try:
        tools = await discover_streamable_http_tools(
            FINCHINA_MCP_URL,
            {"x-api-key": FINCHINA_API_KEY},
            cache_key=f"finchina:{FINCHINA_MCP_URL}",
        )
        enterprise_tools = [
            tool for tool in tools
            if str(tool.get("name") or "") in _FINCHINA_TOOL_CATEGORY_MAP
        ]
        calls = await plan_mcp_tool_calls(
            text,
            enterprise_tools,
            source_name="万得财汇 MCP",
            max_calls=4,
        )
        categories = []
        for call in calls:
            categories.extend(_FINCHINA_TOOL_CATEGORY_MAP.get(call["name"], ()))
        # “企业基础档案”由 lookup_company_profile 固定承担；只有用户明确查询
        # 变更时才附加工商变更明细，避免把普通基本信息问题误扩成历史扫描。
        if "changes" in categories and not any(marker in text for marker in ("变更", "更名", "曾用名", "历史")):
            categories.remove("changes")
        return list(dict.fromkeys(categories))
    except Exception:
        pass

    # 规划服务不可用时保留轻量、可审计的语义兜底，不再无条件扫描全部维度。
    fallback = {
        "judicial": ("诉讼", "案件", "司法", "裁判", "立案", "开庭"),
        "dishonest": ("失信", "被执行", "限高", "终本"),
        "penalty": ("处罚", "监管", "经营异常", "税务违法"),
        "changes": ("变更", "更名", "曾用名"),
        "ownership": ("实控人", "实际控制人", "受益所有人", "股权", "股东"),
        "encumbrance": ("抵押", "质押", "出质", "资产受限"),
        "guarantee": ("担保", "互保"),
        "overdue": ("逾期", "违约", "展期"),
        "rating": ("评级", "信用等级"),
        "finance": ("财务", "营收", "利润", "资产负债率", "现金流"),
        "news": ("舆情", "新闻", "经营动态"),
    }
    return [category for category, markers in fallback.items() if any(marker in text for marker in markers)]

_COMPANY_SUFFIX = (
    "有限公司|有限责任公司|股份有限公司|集团有限公司|集团股份有限公司|"
    "普通合伙企业|有限合伙企业|特殊普通合伙|个人独资企业|律师事务所|农民专业合作社|集团"
)


def _normalise(value: str) -> str:
    return re.sub(r"[\s（）()]+", "", value or "")


def _searchable_name(value: str) -> str:
    """生成可命中财汇企业库的关键词变体：全名(半角)、括号前主干、去括号全名。"""
    name = (value or "").strip()
    name = name.replace("（", "(").replace("）", ")")
    stripped = re.sub(r"\([^()]*\)", "", name)
    variants = [name]
    if "(" in name:
        prefix = name.split("(", 1)[0].strip()
        if prefix and prefix != name:
            variants.append(prefix)
    if stripped and stripped != name and stripped != variants[1] if len(variants) > 1 else True:
        variants.append(stripped)
    return variants


def _extract_company_name(query: str) -> str:
    """从自然语言问题中提取完整企业名称：优先书名号/引号包裹，其次按组织后缀截取。"""
    text = str(query or "").strip()
    if not text:
        return ""
    quoted = re.search(
        rf"[《“\"「]([^》”\"」]{{2,120}}?(?:{_COMPANY_SUFFIX}))[》”\"」]?",
        text,
    )
    if quoted:
        return quoted.group(1).strip()
    pattern = re.compile(rf"[\u4e00-\u9fffA-Za-z0-9（）()·&]{{2,80}}?(?:{_COMPANY_SUFFIX})")
    match = pattern.search(text)
    if not match:
        return ""
    name = match.group(0).strip()
    name = re.sub(
        r"^(?:请|麻烦|帮我|查找|检索|查询|搜索|查看|核实|确认|介绍一下|了解|查一下|问一下|分析|调查|尽调"
        r"|该家|这家|那家|此家)+",
        "",
        name,
    )
    return name.strip("的：" + "，")


def _compact_events(events: List[Dict[str, Any]], per_category: int) -> List[Dict[str, Any]]:
    """压缩尽调事件：保留标题/日期/风险分级/摘要，丢弃超长正文，单类最多保留指定条数。"""
    compact: List[Dict[str, Any]] = []
    for event in events:
        compact.append({
            "标题": event.get("title") or "",
            "日期": event.get("date") or "",
            "领域": event.get("domain") or "",
            "类别": event.get("category") or "",
            "风险分级": event.get("risk_level") or "",
            "风险评分": event.get("risk_score") or 0,
            "摘要": str(event.get("summary") or "")[:400],
        })
        if len(compact) >= per_category:
            break
    return compact


async def _resolve_company_candidates(
    company_name: str,
) -> Tuple[str, List[Dict[str, str]]]:
    """用多个关键词变体在财汇企业库中检索候选，返回命中关键词与候选清单。"""
    last_error = ""
    for keyword in _searchable_name(company_name):
        try:
            result = await search_company_candidates(keyword, limit=50)
        except FinChinaError as exc:
            last_error = str(exc)
            continue
        candidates = result.get("candidates") or []
        if candidates:
            return keyword, candidates
    raise FinChinaError(f"财汇未找到与「{company_name}」匹配的企业，请核对完整企业名称（{last_error}）" if last_error else f"财汇未找到与「{company_name}」匹配的企业，请核对完整企业名称")


def _pick_best_candidate(candidates: List[Dict[str, str]], company_name: str) -> Dict[str, str]:
    """按归一化名称相似度选取最接近查询主体的候选，避免把“XX腾讯科技有限公司”当作腾讯主体。"""
    import difflib

    norm = _normalise(company_name)
    scored = sorted(
        (
            (difflib.SequenceMatcher(None, norm, _normalise(item.get("name") or "")).ratio(), item)
            for item in candidates
        ),
        key=lambda pair: (-pair[0], len(pair[1].get("name") or "")),
    )
    best_score, best = scored[0]
    if best_score >= 0.5:
        return best
    return candidates[0]


async def search_company(query: str) -> str:
    """AI增强专用：从问题中解析企业主体，核验工商画像并并行扫描多维风险。

    返回紧凑 JSON：主体信息、候选说明、画像字段、各维度命中数与代表性事件。
    """
    company_name = _extract_company_name(query)
    if not company_name:
        raise FinChinaError("未能在问题中识别企业名称，请使用完整企业名称提问")
    resolved_keyword, candidates = await _resolve_company_candidates(company_name)
    chosen = _pick_best_candidate(candidates, company_name)
    matched = (
        _normalise(chosen.get("name") or "") == _normalise(company_name)
        or _normalise(chosen.get("name") or "") == _normalise(resolved_keyword)
    )
    name = chosen.get("name") or company_name
    note = ""
    if len(candidates) > 1 and not matched:
        others = "、".join(item.get("name", "") for item in candidates[1:6])
        note = (
            f"按关键词「{resolved_keyword}」检索到多个候选主体，已自动选取「{name}」。"
            f"其他候选：{others}。如需精确核验请使用完整企业名称提问。"
        )

    profile = await lookup_company_profile(name)
    selected_categories = await plan_finchina_intelligence_categories(query)
    intelligence = (
        await query_company_intelligence(
            [name],
            categories=selected_categories,
            days=3650,
            limit_per_category=_ASK_INTELLIGENCE_LIMIT,
        )
        if selected_categories else {
            "results": [], "totals": {}, "errors": {},
            "total_matches": 0, "total_returned": 0,
        }
    )

    per_category_events: Dict[str, List[Dict[str, Any]]] = {}
    for event in intelligence.get("results") or []:
        category = str(event.get("category") or "")
        per_category_events.setdefault(category, [])
        if len(per_category_events[category]) < _ASK_INTELLIGENCE_LIMIT:
            per_category_events[category].append(event)
    compact_categories = {
        category: {
            "命中数": intelligence.get("totals", {}).get(category, 0),
            "返回数": len(events),
            "事件": _compact_events(events, _ASK_INTELLIGENCE_LIMIT),
        }
        for category, events in per_category_events.items()
        if events
    }
    return json.dumps({
        "数据源": "财汇企业预警通",
        "主体": {"企业名称": name, "候选说明": note},
        "工商画像": profile,
        "风险扫描": {
            "按用户诉求选择的维度": selected_categories,
            "扫描维度数": len(selected_categories),
            "总命中数": intelligence.get("total_matches", 0),
            "返回事件数": intelligence.get("total_returned", 0),
            "各维度": compact_categories,
            "维度错误": intelligence.get("errors") or None,
        },
    }, ensure_ascii=False)
