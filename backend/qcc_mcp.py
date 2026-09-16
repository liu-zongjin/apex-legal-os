"""企查查（QCC）Streamable HTTP MCP 客户端。

企查查开放 MCP 提供 4 大能力域、10 个对外 Server：企业数据（企业基座 /
风控 / 知产 / 经营 / 历史 / 董监高）、法律数据（法律法规 / 司法案例）、
标讯数据、智能文档解析。本模块按 Server 分类发起标准 MCP 会话调用，
授权信息仅从 ``QCC_MCP_AUTHORIZATION`` 读取（Bearer 头，含前缀）。

实体锚定遵循企查查规则：能唯一精确匹配时直接锁定；多候选时优先按
查询词与候选企业名称匹配，仍不唯一时自动选取首个候选并在结果中显式
标注，提示用户可用完整企业名称重新提问。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .ai_config import QCC_MCP_AUTHORIZATION
from .mcp_tool_router import (
    MCPToolRouterError,
    discover_streamable_http_tools,
    plan_mcp_tool_calls,
    validate_tool_calls,
)


class QccMCPError(RuntimeError):
    pass


_DEFAULT_URLS = {
    "company": "https://agent.qcc.com/mcp/company/stream",
    "risk": "https://agent.qcc.com/mcp/risk/stream",
    "ipr": "https://agent.qcc.com/mcp/ipr/stream",
    "operation": "https://agent.qcc.com/mcp/operation/stream",
    "history": "https://agent.qcc.com/mcp/history/stream",
    "executive": "https://agent.qcc.com/mcp/executive/stream",
    "regulation": "https://agent.qcc.com/mcp/regulation/stream",
    "case": "https://agent.qcc.com/mcp/case/stream",
    "tender": "https://agent.qcc.com/mcp/tender/stream",
    "document": "https://agent.qcc.com/mcp/document/stream",
}

_SOURCE_NAMES = {
    "company": "企查查·企业信息",
    "risk": "企查查·司法风险",
    "ipr": "企查查·知识产权",
    "operation": "企查查·经营信息",
    "history": "企查查·历史信息",
    "executive": "企查查·董监高画像",
    "regulation": "企查查·法律法规",
    "case": "企查查·司法案例",
    "tender": "企查查·招投标",
    "document": "企查查·智能文档",
}


def server_config(category: str) -> Tuple[str, str]:
    if category not in _DEFAULT_URLS:
        raise ValueError("不支持的企查查 MCP 类型")
    env_name = f"QCC_{category.upper()}_MCP_URL"
    return os.environ.get(env_name, _DEFAULT_URLS[category]).strip(), QCC_MCP_AUTHORIZATION


def source_status(category: str) -> Dict[str, Any]:
    url, authorization = server_config(category)
    return {
        "name": _SOURCE_NAMES.get(category, "企查查 MCP"),
        "url": url,
        "configured": bool(url and authorization),
        "enabled": bool(url and authorization),
    }


async def discover_qcc_tools(category: str) -> List[Dict[str, Any]]:
    """读取企查查当前实际公布的工具清单，避免能力更新后本地仍使用旧清单。"""
    url, authorization = server_config(category)
    if not authorization:
        raise QccMCPError(
            f"{_SOURCE_NAMES.get(category, '企查查 MCP')} 尚未配置授权（QCC_MCP_AUTHORIZATION）"
        )
    try:
        return await discover_streamable_http_tools(
            url,
            {"Authorization": authorization},
            cache_key=f"qcc:{category}:{url}",
        )
    except MCPToolRouterError as exc:
        raise QccMCPError(str(exc)) from exc


async def plan_qcc_tool_calls(
    category: str,
    query: str,
    *,
    argument_overrides: Optional[Dict[str, Any]] = None,
    excluded_tools: Tuple[str, ...] = (),
    max_calls: int = 4,
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """根据用户原话和实时工具说明选择企查查专用工具。"""
    tools = await discover_qcc_tools(category)
    calls = await plan_mcp_tool_calls(
        query,
        tools,
        source_name=_SOURCE_NAMES.get(category, "企查查 MCP"),
        max_calls=max_calls,
        argument_overrides=argument_overrides,
        excluded_tools=excluded_tools,
    )
    titles = {
        str(tool.get("name")): str(tool.get("title") or tool.get("name") or "")
        for tool in tools
    }
    return calls, titles


def _decode_response(response: httpx.Response) -> Dict[str, Any]:
    response.raise_for_status()
    raw = response.text.strip()
    if not raw:
        return {}
    payloads = [line[5:].strip() for line in raw.splitlines() if line.startswith("data:")]
    if not payloads:
        payloads = [raw]
    for value in reversed(payloads):
        try:
            envelope = json.loads(value)
        except json.JSONDecodeError:
            continue
        if envelope.get("error"):
            message = (envelope.get("error") or {}).get("message") or "企查查 MCP 调用失败"
            raise QccMCPError(str(message))
        return envelope
    raise QccMCPError("企查查 MCP 返回了无法识别的数据")


async def call_qcc_tool(
    category: str,
    tool_name: str,
    arguments: Dict[str, Any],
    timeout: float = 35.0,
) -> str:
    """建立短会话并调用一个企查查 MCP 工具，失败时按退避策略重试。"""
    url, authorization = server_config(category)
    if not authorization:
        raise QccMCPError(
            f"{_SOURCE_NAMES.get(category, '企查查 MCP')} 尚未配置授权（QCC_MCP_AUTHORIZATION）"
        )
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "Authorization": authorization,
    }
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "legal-knowledge-base", "version": "1.0.0"},
        },
    }
    retry_delays = (0.0, 0.8, 2.0)
    envelope: Dict[str, Any] = {}
    last_error: Optional[Exception] = None
    for attempt, delay in enumerate(retry_delays):
        if delay:
            await asyncio.sleep(delay)
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                init_response = await client.post(url, json=initialize, headers=headers)
                _decode_response(init_response)
                session_headers = dict(headers)
                session_id = init_response.headers.get("mcp-session-id")
                if session_id:
                    session_headers["mcp-session-id"] = session_id
                await client.post(
                    url,
                    json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                    headers=session_headers,
                )
                response = await client.post(
                    url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {"name": tool_name, "arguments": arguments},
                    },
                    headers=session_headers,
                )
                envelope = _decode_response(response)
            break
        except httpx.TimeoutException as exc:
            last_error = QccMCPError("企查查 MCP 连接超时，请稍后重试")
            last_error.__cause__ = exc
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            last_error = QccMCPError(f"企查查 MCP 连接失败（HTTP {status_code}）")
            last_error.__cause__ = exc
            if status_code not in {429, 502, 503, 504}:
                raise last_error
        except httpx.RequestError as exc:
            last_error = QccMCPError("当前无法连接企查查 MCP")
            last_error.__cause__ = exc
        if attempt == len(retry_delays) - 1:
            raise last_error or QccMCPError("当前无法连接企查查 MCP")

    result = envelope.get("result") or {}
    content = result.get("content") or []
    text = "\n".join(
        str(item.get("text") or "").strip()
        for item in content
        if isinstance(item, dict) and item.get("type") == "text"
    ).strip()
    if result.get("isError"):
        raise QccMCPError(text or "企查查 MCP 工具执行失败")
    if not text:
        raise QccMCPError("企查查 MCP 未返回结果")
    return text


def _json_value(raw: str) -> Dict[str, Any]:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


_PERSON_EVIDENCE_KEY_MARKERS = (
    "主要人员", "关键人员", "高管", "董监高", "任职", "负责人", "法定代表人",
    "变更记录", "高级管理人员备案", "历史任职",
)
_PERSON_ROLE_WORDS = (
    "变更前", "变更后", "股东变更", "股东发生变更", "无", "章程", "有限公司",
)


def _person_name_from_value(value: Any) -> List[str]:
    """从企查查人员字段中提取姓名，不把职务或企业名称当成人名。"""
    if not isinstance(value, str):
        return []
    text = value.strip()
    if not text:
        return []
    candidates = []
    if re.fullmatch(r"[\u4e00-\u9fff]{2,4}", text):
        candidates.append(text)
    candidates.extend(re.findall(r"[\"“]([\u4e00-\u9fff]{2,4})[\"”]", text))
    candidates.extend(re.findall(r"([\u4e00-\u9fff]{2,4})(?=[（(])", text))
    result = []
    for candidate in candidates:
        if candidate in _PERSON_ROLE_WORDS or any(word in candidate for word in _PERSON_ROLE_WORDS):
            continue
        if candidate not in result:
            result.append(candidate)
    return result


def extract_company_people(raw: str) -> Dict[str, List[str]]:
    """从多企业工商证据中提取各主体的当前/历史人员姓名。

    企查查董监高 Server 的工具要求企业名与人员名双锚定，因此不能把整句
    “对比 A、B 的任职”直接交给它。此函数只读取企业信息 MCP 已返回的人员、
    法定代表人和高管变更字段，供后续对交集候选人做专项核验。
    """
    payload = _json_value(raw)
    rows = payload.get("各企业结果") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        rows = [payload] if isinstance(payload, dict) and payload else []
    result: Dict[str, List[str]] = {}

    def walk(value: Any, key_hint: str, names: List[str]) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                key_text = str(key or "")
                relevant = any(marker in key_text or marker in key_hint for marker in _PERSON_EVIDENCE_KEY_MARKERS)
                if isinstance(item, str) and relevant:
                    for name in _person_name_from_value(item):
                        if name not in names:
                            names.append(name)
                if isinstance(item, (dict, list)) and (relevant or not key_hint):
                    walk(item, key_text if relevant else key_hint, names)
        elif isinstance(value, list):
            for item in value:
                walk(item, key_hint, names)
        elif isinstance(value, str) and key_hint:
            for name in _person_name_from_value(value):
                if name not in names:
                    names.append(name)

    for row in rows:
        if not isinstance(row, dict):
            continue
        company_name = str(row.get("企业名称") or row.get("公司名称") or "").strip()
        if not company_name:
            continue
        evidence = row.get("结果")
        if isinstance(evidence, str):
            evidence = _json_value(evidence)
        names: List[str] = []
        walk(evidence, "", names)
        result[company_name] = names
    return result


def company_response_covers_fields(raw: str, markers: Tuple[str, ...]) -> bool:
    """判断企业信息响应是否为每个已返回主体提供了可用专项字段。

    不能只搜索字段名：企查查会在字段值中返回 ``_error``，或者在多主体
    响应中一家公司成功、另一家公司失败。只有所有主体都成功返回目标字段，
    才能跳过历史/董监高依赖调用。
    """
    payload = _json_value(raw)

    def has_usable_field(value: Any) -> bool:
        if isinstance(value, dict):
            return not bool(value.get("_error")) and bool(value)
        if isinstance(value, str):
            text = value.strip()
            return bool(text) and not any(
                marker in text for marker in ("未返回", "调用失败", "接口不可用")
            )
        return value is not None

    def has_marked_field(value: Any) -> bool:
        if isinstance(value, dict):
            for key, item in value.items():
                key_text = str(key or "")
                if any(marker in key_text for marker in markers):
                    if key_text.startswith("本次调用"):
                        continue
                    if has_usable_field(item):
                        return True
                if isinstance(item, (dict, list)) and has_marked_field(item):
                    return True
        elif isinstance(value, list):
            return any(has_marked_field(item) for item in value)
        return False

    rows = payload.get("各企业结果") if isinstance(payload, dict) else None
    if isinstance(rows, list):
        successful_results = []
        for row in rows:
            if not isinstance(row, dict) or row.get("查询状态") != "成功":
                return False
            result = row.get("结果")
            if isinstance(result, str):
                result = _json_value(result)
            if not isinstance(result, dict):
                return False
            successful_results.append(result)
        return bool(successful_results) and all(
            has_marked_field(result) for result in successful_results
        )

    return bool(payload) and has_marked_field(payload)


def _normalise_keyword(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


_COMPANY_NAME_PATTERN = re.compile(
    r"[【\[（(\s]*"
    r"([\u4e00-\u9fffA-Za-z0-9·（）()]{2,80}?(?:"
    r"股份有限公司|有限责任公司|有限公司|合伙企业|个人独资企业|个体工商户|"
    r"便利店|超市|商店|店|集体经济组织|经济合作社|村民委员会|居民委员会))"
)
_PERSON_IN_COMPANY_PATTERN = re.compile(
    r"(?:负责人|法定代表人|法人代表|经营者|店主|老板)\s*(?:是|为|：|:)?\s*"
    r"([\u4e00-\u9fff]{2,4}?)(?=[，,。；;、\s]|$)"
)
_RELATED_COMPANY_INTENT_PATTERN = re.compile(
    r"还(?:经营|开设|开了|有)|(?:经营|任职|关联|控制|投资|名下).*?(?:哪些|什么)|"
    r"(?:哪些|什么).*?(?:企业|公司|超市|便利店|店铺)|关联企业"
)

_COMPANY_COMPARISON_PATTERN = re.compile(
    r"对比|比较|比对|交叉任职|交叉任用|共同任职|共同人员|重合人员|"
    r"两家(?:公司|企业)|多家(?:公司|企业)|分别(?:查询|核对|比对)|各自(?:的|是否)"
)
_COMPANY_LEADING_FILLER_PATTERN = re.compile(
    r"^(?:对比|比较|比对|查询|检索|查找|分析|核对|结合|关于|请|帮我|分别|明确|判断)+"
)

def extract_company_name(query: str) -> str:
    """从自然语言问题中提取企业名称，避免把整句交给实体锚定接口。"""
    names = extract_company_names(query)
    return names[0] if names else str(query or "").strip()


def extract_company_names(query: str) -> List[str]:
    """提取问题中的全部企业名称，并保持出现顺序。

    旧实现使用 ``search`` 只取第一个主体，导致“对比 A、B”在进入 MCP
    前就丢失 B。这里保留原有单主体行为，同时为多主体任务提供稳定的
    去重实体列表。
    """
    text = str(query or "").strip()
    matches = _COMPANY_NAME_PATTERN.finditer(text)
    names: List[str] = []
    seen = set()
    for match in matches:
        name = match.group(1).strip("【】[]（）() \t\r\n")
        name = _COMPANY_LEADING_FILLER_PATTERN.sub("", name)
        key = _normalise_keyword(name)
        if name and key not in seen:
            names.append(name)
            seen.add(key)
    return names


def extract_person_name(query: str) -> str:
    """提取“某企业负责人示七某”这类表达中的自然人姓名。"""
    match = _PERSON_IN_COMPANY_PATTERN.search(str(query or ""))
    return match.group(1) if match else ""


def asks_for_related_companies(query: str) -> bool:
    return bool(_RELATED_COMPANY_INTENT_PATTERN.search(str(query or "")))


def asks_for_company_comparison(query: str) -> bool:
    """判断是否是需要保留多个主体并进行集合比对的企业问题。"""
    return len(extract_company_names(query)) > 1 or bool(
        _COMPANY_COMPARISON_PATTERN.search(str(query or ""))
    )


# 企查查企业信息 Server 提供多种专项工具。此前企业查询无论用户问什么，
# 都只调用工商登记、企业简介和股东信息，导致开票、联系方式、年报等明确
# 存在的字段从未进入回答上下文。这里按用户原始诉求选择专项工具；一个问题
# 命中多个维度时会合并调用，未命中时才回退到通用企业画像。
_COMPANY_TOOL_INTENTS: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    ("get_tax_invoice_info", "税号开票信息", (
        "发票", "开票", "税号", "纳税人识别号", "开户行", "银行账号", "开票资料",
    )),
    ("verify_company_accuracy", "企业准确性验证", (
        "二要素", "名称与信用代码", "名称和信用代码", "企业名称与统一社会信用代码",
        "企业名称和统一社会信用代码", "名称是否一致", "代码是否匹配",
    )),
    ("get_contact_info", "联系方式", (
        "联系方式", "联系电话", "电话号码", "电话", "邮箱", "电子邮箱", "官网", "网站",
    )),
    ("get_annual_reports", "企业年报", (
        "企业年报", "工商年报", "年度报告", "年报", "从业人数", "社保人数",
    )),
    ("get_branches", "分支机构", (
        "分支机构", "分公司", "分店", "分支", "办事处",
    )),
    ("get_change_records", "变更记录", (
        "变更记录", "工商变更", "变更历史", "历史工商", "历史登记", "历史信息",
        "历史沿革", "什么时候改", "曾用名", "更名前", "更名记录",
    )),
    ("get_external_investments", "对外投资", (
        "对外投资", "投资了哪些", "投资企业", "被投资企业", "投资布局",
    )),
    ("get_financial_data", "财务数据", (
        "财务数据", "财务状况", "营业收入", "营收", "净利润", "毛利率", "净利率",
        "资产负债率", "流动比率", "总资产", "总负债", "偿债能力", "盈利能力",
    )),
    ("get_key_personnel", "主要人员", (
        "主要人员", "关键人员", "高管", "董事", "监事", "经理", "管理团队",
        "任职", "交叉任职", "共同人员", "人员交叉",
    )),
    ("get_listing_info", "上市信息", (
        "上市信息", "上市公司", "是否上市", "股票代码", "股票简称", "证券代码", "交易所", "市值",
    )),
    ("get_beneficial_owners", "受益所有人", (
        "受益所有人", "最终受益人", "最终受益自然人", "ubo", "反洗钱", "aml",
    )),
    ("get_actual_controller", "实际控制人", (
        "实际控制人", "实控人", "谁控制", "最终控制人",
    )),
    ("get_shareholder_info", "股东信息", (
        "股东", "直接持股", "一层持股", "出资人", "投资人", "股权结构", "持股比例",
    )),
    ("get_company_profile", "企业简介", (
        "企业简介", "公司简介", "是做什么", "做什么的", "主营业务", "业务模式", "行业分类",
    )),
    ("get_company_registration_info", "企业工商信息", (
        "工商信息", "登记信息", "基本信息", "法定代表人", "法人", "注册资本", "成立日期",
        "注册地址", "经营范围", "经营状态", "登记状态", "统一社会信用代码", "纳税人资质",
    )),
)

_DEFAULT_COMPANY_TOOLS: Tuple[Tuple[str, str], ...] = (
    ("get_company_registration_info", "企业工商信息"),
    ("get_company_profile", "企业简介"),
    ("get_shareholder_info", "股东信息"),
)


def select_company_tools(query: str) -> List[Tuple[str, str, Dict[str, Any]]]:
    """按自然语言诉求选择企业信息工具，并生成其调用参数。"""
    text = str(query or "")
    lowered = text.lower()
    selected: List[Tuple[str, str, Dict[str, Any]]] = []
    seen = set()
    for tool_name, title, keywords in _COMPANY_TOOL_INTENTS:
        if any(keyword.lower() in lowered for keyword in keywords):
            if tool_name not in seen:
                selected.append((tool_name, title, {}))
                seen.add(tool_name)
    if selected:
        return selected
    return [(tool_name, title, {}) for tool_name, title in _DEFAULT_COMPANY_TOOLS]


async def resolve_company(query: str) -> Dict[str, Any]:
    """按企查查实体锚定规则解析企业主体，返回锁定主体与候选清单。"""
    company_query = extract_company_name(query)
    raw = await call_qcc_tool("company", "get_company_by_query", {"searchKey": company_query})
    payload = _json_value(raw)
    match_type = str(payload.get("匹配结果") or "")
    raw_info = payload.get("企业信息") or {}

    def entity_of(item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": item.get("企业名称") or company_query,
            "credit_code": item.get("统一社会信用代码") or "",
        }

    if match_type == "唯一精确匹配":
        info = raw_info if isinstance(raw_info, dict) else (
            raw_info[0] if isinstance(raw_info, list) and raw_info and isinstance(raw_info[0], dict) else {}
        )
        return {**entity_of(info), "candidates": []}

    candidates = raw_info if isinstance(raw_info, list) else []
    if candidates:
        keyword = _normalise_keyword(company_query)
        matched = [
            item for item in candidates
            if isinstance(item, dict) and keyword and keyword in _normalise_keyword(str(item.get("企业名称") or ""))
        ]
        if len(matched) == 1:
            return {**entity_of(matched[0]), "candidates": candidates}
        return {**entity_of(candidates[0]), "candidates": candidates}
    raise QccMCPError(f"企查查未能识别企业主体「{company_query}」，请检查企业名称或统一社会信用代码后重试")


def _first_qcc_value(payload: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


async def resolve_company_candidates(company_keyword: str, limit: int = 30) -> Dict[str, Any]:
    """企查查企业候选搜索，供“导入企业信息”在万得财汇查不到时自动降级。

    返回结构与财汇 ``search_company_candidates`` 保持一致，前端候选选择器可复用。
    """
    keyword = str(company_keyword or "").strip()
    if not keyword:
        raise QccMCPError("请先输入企业名称")
    if len(keyword) > 120:
        raise QccMCPError("企业名称过长")
    try:
        entity = await resolve_company(keyword)
    except QccMCPError as exc:
        raise QccMCPError(f"企查查未找到匹配企业，请尝试更完整的名称（{exc}）") from exc
    candidates: List[Dict[str, str]] = []
    for item in entity.get("candidates") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("企业名称") or "").strip()
        if not name:
            continue
        candidates.append({
            "name": name,
            "credit_code": str(item.get("统一社会信用代码") or "").strip(),
        })
    if not candidates:
        candidates = [{
            "name": str(entity.get("name") or keyword).strip(),
            "credit_code": str(entity.get("credit_code") or "").strip(),
        }]
    safe_limit = max(1, min(int(limit or 30), 100))
    picked = candidates[:safe_limit]
    return {
        "query": keyword,
        "candidates": picked,
        "returned": len(picked),
        "total": len(candidates),
        "truncated": len(candidates) > safe_limit,
        "data_source": "企查查·企业信息",
    }


async def lookup_company_profile(company_name: str) -> Dict[str, Any]:
    """企查查工商档案查询，供“导入企业信息”在万得财汇查不到时自动降级。

    字段结构与财汇 ``lookup_company_profile`` 保持一致，前端表单填充逻辑可复用；
    数据来源标记为“企查查·企业信息”。
    """
    name = str(company_name or "").strip()
    if not name:
        raise QccMCPError("请先输入企业名称")
    if len(name) > 120:
        raise QccMCPError("企业名称过长")
    try:
        raw = await call_qcc_tool("company", "get_company_registration_info", {"searchKey": name})
    except QccMCPError as exc:
        raise QccMCPError(f"企查查工商信息查询失败：{exc}") from exc
    payload = _json_value(raw)
    if not payload:
        raise QccMCPError("企查查未返回工商登记信息")
    matched_name = _first_qcc_value(payload, "企业名称", "公司名称", "名称") or name
    region_parts = [
        part for part in (
            _first_qcc_value(payload, "注册地址所在省", "省份"),
            _first_qcc_value(payload, "注册地址所在市", "城市", "市"),
            _first_qcc_value(payload, "注册地址所在区县", "区县"),
        ) if part
    ]
    return {
        "name": matched_name,
        "matched_name": matched_name,
        "identity_code": _first_qcc_value(payload, "统一社会信用代码", "信用代码"),
        "legal_representative": _first_qcc_value(payload, "法定代表人", "法人代表"),
        "address": _first_qcc_value(payload, "注册地址", "住所", "地址"),
        "registered_capital": _first_qcc_value(payload, "注册资本", "注册资金"),
        "establishment_date": _first_qcc_value(payload, "成立日期", "开业日期"),
        "registration_status": _first_qcc_value(payload, "登记状态", "经营状态", "企业状态"),
        "business_scope": _first_qcc_value(payload, "经营范围"),
        "enterprise_nature": _first_qcc_value(payload, "企业类型", "企业性质", "市场主体类型"),
        "industry": _first_qcc_value(payload, "所属行业", "行业", "行业分类"),
        "region": " / ".join(dict.fromkeys(region_parts)),
        "data_source": "企查查·企业信息",
        "source_checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "match_message": "",
    }


async def search_company(query: str, *, _single: bool = False) -> str:
    """按用户诉求查询企业专项信息；人员关联问题使用“企业+姓名”双锚。"""
    if not _single and len(extract_company_names(query)) > 1:
        return await search_companies(query)
    entity = await resolve_company(query)
    search_key = entity["name"]
    if entity["candidates"]:
        entity["_note"] = (
            "企查查返回多个候选主体，已自动选取「{name}」。如需查询其他主体，"
            "请以完整企业名称重新提问。".format(name=entity["name"])
        )
    results: Dict[str, Any] = {"主体": entity}
    try:
        planned_calls, tool_titles = await plan_qcc_tool_calls(
            "company",
            query,
            argument_overrides={"searchKey": search_key, "name": entity["name"]},
            excluded_tools=("get_company_by_query",),
            max_calls=5,
        )
    except Exception:
        # 能力发现或轻量规划器暂不可用时，仍用本地意图表完成可预测的降级。
        planned_calls, tool_titles = [], {}
    if planned_calls:
        tasks = [
            (call["name"], tool_titles.get(call["name"], call["name"]), call["arguments"])
            for call in planned_calls
        ]
        # 动态规划器可能只选中“企业工商信息”这一项。对历史、主要人员、
        # 股东等用户明确点名的维度，确定性意图表必须补齐已知专项工具，
        # 否则模型一次规划漏项就会制造“数据源没有返回”的假象。
        planned_names = {item[0] for item in tasks}
        for tool_name, title, arguments in select_company_tools(query):
            if tool_name not in planned_names:
                tasks.append((tool_name, title, arguments))
                planned_names.add(tool_name)
    else:
        tasks = select_company_tools(query)
    successful_tools: List[str] = []
    requested_tools: List[str] = []
    for tool_name, title, extra_arguments in tasks:
        requested_tools.append(title)
        arguments = {"searchKey": search_key, **extra_arguments}
        if tool_name == "verify_company_accuracy":
            if not entity.get("credit_code"):
                results[title] = {"_error": "未取得统一社会信用代码，无法执行企业二要素验证"}
                continue
            arguments = {"searchKey": entity["credit_code"], "name": entity["name"]}
        elif tool_name == "get_contact_info" and any(
            marker in str(query or "") for marker in ("过滤无效", "排除无效", "只要有效", "去掉错误")
        ):
            arguments["excludeInvalidPhone"] = True
        try:
            raw = await call_qcc_tool("company", tool_name, arguments)
            payload = _json_value(raw)
            if payload:
                for key, value in payload.items():
                    if key not in results:
                        results[key] = value
            else:
                results[title] = raw
            successful_tools.append(title)
        except QccMCPError as exc:
            results[title] = {"_error": str(exc)}
    person_name = extract_person_name(query)
    if person_name and asks_for_related_companies(query):
        # 企查查的董监高接口要求企业与人员双锚；先由上面的实体解析锁定
        # 企业，再查该人员当前全部关联企业，避免把自然语言整句误作企业名称。
        try:
            related_raw = await call_qcc_tool(
                "executive",
                "get_executive_related_companies",
                {"searchKey": search_key, "personName": person_name},
            )
            related_payload = _json_value(related_raw)
            results["人员关联企业查询"] = {
                "查询人员": person_name,
                "查询范围": "当前以股东、法定代表人或高管等角色关联的企业",
                "结果": related_payload or related_raw,
            }
        except QccMCPError as exc:
            results["人员关联企业查询"] = {
                "查询人员": person_name,
                "_error": str(exc),
            }
    if not successful_tools and not results.get("人员关联企业查询"):
        raise QccMCPError(
            "企查查未能返回所请求的专项信息（{tools}）".format(
                tools="、".join(requested_tools)
            )
        )
    results["本次调用的企查查能力"] = successful_tools
    return json.dumps(results, ensure_ascii=False)


async def search_companies(query: str) -> str:
    """并行查询问题中出现的全部企业，并保留可供模型比对的分组证据。

    企业信息 MCP 的单主体接口仍然是事实查询的最小单元；多主体问题由
    这里拆分后分别调用，再以稳定的 ``各企业结果`` 结构合并，避免模型只
    看到第一个企业就误判“另一主体没有返回”。
    """
    names = extract_company_names(query)
    if len(names) < 2:
        return await search_company(query, _single=True)

    async def fetch_one(name: str) -> Dict[str, Any]:
        single_query = f"{name}；用户原始问题：{query}"
        try:
            raw = await search_company(single_query, _single=True)
            payload = _json_value(raw)
            return {
                "企业名称": name,
                "查询状态": "成功",
                "结果": payload or raw,
            }
        except QccMCPError as exc:
            return {"企业名称": name, "查询状态": "失败", "错误": str(exc)}

    rows = await asyncio.gather(*(fetch_one(name) for name in names))
    successful = [row for row in rows if row.get("查询状态") == "成功"]
    if not successful:
        errors = "；".join(
            f"{row['企业名称']}：{row.get('错误') or '未返回数据'}" for row in rows
        )
        raise QccMCPError(f"企查查未返回任何目标企业的企业信息（{errors}）")
    return json.dumps({
        "查询类型": "多企业工商信息对比",
        "主体名称列表": names,
        "主体数量": len(names),
        "各企业结果": rows,
        "比对要求": "必须逐一核对每个主体的实际返回字段，再对股东、法定代表人、董事、监事、经理及历史人员集合求交集；未返回字段不得推断。",
        "成功主体数量": len(successful),
    }, ensure_ascii=False)


def _entity_arguments(tool: Dict[str, Any], company_name: str, query: str) -> Dict[str, Any]:
    """为动态发现的企业工具填充常见实体参数，供规划器失败时兜底。"""
    schema = tool.get("inputSchema") or {}
    properties = schema.get("properties") or {}
    arguments: Dict[str, Any] = {}
    aliases = {
        "searchKey": company_name,
        "companyName": company_name,
        "company_name": company_name,
        "targetCompany": company_name,
        "target_company": company_name,
        "name": company_name,
        "keyword": company_name,
        "query": query,
    }
    for key, value in aliases.items():
        if key in properties:
            arguments[key] = value
    return arguments


def _fallback_category_calls(
    tools: List[Dict[str, Any]],
    category: str,
    company_name: str,
    query: str,
    max_calls: int,
) -> List[Dict[str, Any]]:
    """模型规划失败时，按工具描述选择历史/高管能力并校验必填参数。"""
    if category == "history":
        keywords = ("历史", "变更", "登记", "任职", "投资", "沿革")
    else:
        keywords = ("董", "监", "高管", "任职", "在外任职", "历史任职", "人员")
    proposed: List[Dict[str, Any]] = []
    for tool in tools:
        haystack = " ".join([
            str(tool.get("name") or ""),
            str(tool.get("title") or ""),
            str(tool.get("description") or ""),
        ])
        if not any(keyword in haystack for keyword in keywords):
            continue
        proposed.append({
            "name": tool.get("name"),
            "arguments": _entity_arguments(tool, company_name, query),
        })
    return validate_tool_calls(proposed, tools, max_calls=max_calls)


async def _search_qcc_category_for_companies(
    category: str,
    query: str,
    *,
    max_calls: int = 4,
) -> str:
    """按企业拆分调用企查查历史或董监高 Server。"""
    names = extract_company_names(query)
    if not names:
        name = extract_company_name(query)
        names = [name] if name else []
    if not names:
        raise QccMCPError("未识别到企业名称，无法查询企查查专项信息")

    async def fetch_one(company_name: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {"企业名称": company_name, "调用结果": {}, "调用错误": {}}
        try:
            tools = await discover_qcc_tools(category)
            try:
                calls, titles = await plan_qcc_tool_calls(
                    category,
                    query,
                    argument_overrides={"searchKey": company_name, "companyName": company_name},
                    max_calls=max_calls,
                )
            except Exception:
                calls = _fallback_category_calls(
                    tools, category, company_name, query, max_calls
                )
                titles = {
                    str(tool.get("name")): str(tool.get("title") or tool.get("name") or "")
                    for tool in tools
                }
            if not calls:
                calls = _fallback_category_calls(
                    tools, category, company_name, query, max_calls
                )
            gathered = await asyncio.gather(
                *(
                    call_qcc_tool(category, call["name"], call["arguments"])
                    for call in calls
                ),
                return_exceptions=True,
            )
            for call, raw in zip(calls, gathered):
                title = titles.get(call["name"], call["name"])
                if isinstance(raw, Exception):
                    result["调用错误"][title] = str(raw)
                    continue
                payload = _json_value(str(raw))
                result["调用结果"][title] = payload or raw
        except Exception as exc:
            result["调用错误"]["工具发现或规划"] = str(exc)
        return result

    rows = await asyncio.gather(*(fetch_one(name) for name in names))
    if not any(row.get("调用结果") for row in rows):
        raise QccMCPError(
            f"企查查{_SOURCE_NAMES.get(category, category)}未返回可用专项信息"
        )
    label = "企查查·历史信息" if category == "history" else "企查查·董监高画像"
    return json.dumps({
        "查询类型": label,
        "主体名称列表": names,
        "各企业结果": rows,
        "比对要求": "历史或任职信息必须按企业分组展示，再按自然人姓名、职务和变更时间进行交叉核验；同名人员不得直接认定为同一人。",
    }, ensure_ascii=False)


async def search_history(query: str) -> str:
    return await _search_qcc_category_for_companies("history", query)


async def _search_executive_intersections(query: str, company_evidence: str) -> str:
    people_by_company = extract_company_people(company_evidence)
    if len(people_by_company) < 2:
        return json.dumps({
            "查询类型": "企查查·董监高画像",
            "主体名称列表": list(people_by_company),
            "交集候选人员": [],
            "说明": "企业信息 MCP 返回的主体不足两个，未执行董监高交集专项核验。",
        }, ensure_ascii=False)
    common_people = sorted(
        set.intersection(*(set(names) for names in people_by_company.values()))
    )
    if not common_people:
        return json.dumps({
            "查询类型": "企查查·董监高画像",
            "主体名称列表": list(people_by_company),
            "各企业人员集合": people_by_company,
            "交集候选人员": [],
            "说明": "企业信息 MCP 已返回的当前/历史人员字段中未发现姓名交集，未执行董监高专项核验。",
        }, ensure_ascii=False)

    tools = await discover_qcc_tools("executive")
    catalog = {str(tool.get("name")): tool for tool in tools}
    preferred_names = (
        "get_executive_historical_positions",
        "get_executive_historical_related_companies",
        "get_executive_positions",
        "get_executive_related_companies",
    )
    tool_name = next((name for name in preferred_names if name in catalog), "")
    if not tool_name:
        raise QccMCPError("企查查董监高画像未公布可用于历史任职核验的工具")
    title = str(catalog[tool_name].get("title") or tool_name)
    calls = []
    for person_name in common_people:
        for company_name in people_by_company:
            calls.append({
                "企业名称": company_name,
                "人员姓名": person_name,
                "工具名称": tool_name,
                "工具标题": title,
            })
    gathered = await asyncio.gather(
        *(
            call_qcc_tool(
                "executive",
                item["工具名称"],
                {"searchKey": item["企业名称"], "personName": item["人员姓名"]},
            )
            for item in calls
        ),
        return_exceptions=True,
    )
    rows = []
    for item, raw in zip(calls, gathered):
        row = {**item}
        if isinstance(raw, Exception):
            row["错误"] = str(raw)
        else:
            payload = _json_value(str(raw))
            row["结果"] = payload or raw
        rows.append(row)
    return json.dumps({
        "查询类型": "企查查·董监高画像",
        "主体名称列表": list(people_by_company),
        "各企业人员集合": people_by_company,
        "交集候选人员": common_people,
        "专项核验结果": rows,
        "比对要求": "只有企业名、人员姓名及任职时间/职务能够对应时，才可确认交叉任职；同名不得直接认定为同一人。",
    }, ensure_ascii=False)


async def search_executive(query: str, *, company_evidence: str = "") -> str:
    if company_evidence:
        return await _search_executive_intersections(query, company_evidence)
    return await _search_qcc_category_for_companies("executive", query)


async def search_risk(query: str) -> str:
    """企业司法风险查询：根据诉求选专项维度，宽泛尽调才执行全量扫描。"""
    entity = await resolve_company(query)
    try:
        planned_calls, tool_titles = await plan_qcc_tool_calls(
            "risk",
            query,
            argument_overrides={"searchKey": entity["name"]},
            # 详情工具需要先从列表接口获得 documentId，不允许规划器臆造。
            excluded_tools=("get_judicial_document_detail",),
            max_calls=5,
        )
    except Exception:
        planned_calls, tool_titles = [], {}
    if not planned_calls:
        planned_calls = [{
            "name": "get_company_risk_scan", "arguments": {"searchKey": entity["name"]},
        }]
        tool_titles = {"get_company_risk_scan": "企业风险扫描"}
    payload: Dict[str, Any] = {"主体": entity}
    succeeded = []
    errors = {}
    for call in planned_calls:
        title = tool_titles.get(call["name"], call["name"])
        try:
            raw = await call_qcc_tool("risk", call["name"], call["arguments"])
            value = _json_value(raw)
            payload[title] = value or raw
            if isinstance(value, dict):
                # 保留旧版企业风险扫描的顶层字段，避免现有回答和导出逻辑因
                # 引入“专项工具标题”这一层后丢失计数等结构化数据。
                for key, item in value.items():
                    if key not in payload:
                        payload[key] = item
            succeeded.append(title)
        except QccMCPError as exc:
            errors[title] = str(exc)
    if not succeeded:
        raise QccMCPError(
            "企查查未能返回所请求的司法风险专项信息（{tools}）".format(
                tools="、".join(tool_titles.get(call["name"], call["name"]) for call in planned_calls)
            )
        )
    payload["本次调用的企查查能力"] = succeeded
    if errors:
        payload["未完成的能力"] = errors
    return json.dumps(payload, ensure_ascii=False)


async def search_cases(query: str, top_k: int = 8) -> str:
    """司法案例查询：按实时能力选择检索/溯源工具，失败时双路召回。"""
    safe_query = str(query or "").strip()
    if not safe_query:
        raise QccMCPError("检索问题不能为空")
    safe_top_k = max(1, min(int(top_k or 8), 20))
    try:
        planned_calls, tool_titles = await plan_qcc_tool_calls(
            "case",
            safe_query,
            excluded_tools=("get_judicial_case_detail",),
            max_calls=3,
        )
    except Exception:
        planned_calls, tool_titles = [], {}
    if planned_calls:
        gathered = await asyncio.gather(
            *(call_qcc_tool("case", call["name"], call["arguments"]) for call in planned_calls),
            return_exceptions=True,
        )
        planned_parts = []
        for call, result in zip(planned_calls, gathered):
            title = tool_titles.get(call["name"], call["name"])
            if isinstance(result, Exception):
                continue
            text = str(result).strip()
            payload = _json_value(text)
            rows = payload.get("案例列表") if payload else None
            if isinstance(rows, list) and len(rows) > safe_top_k:
                payload["案例列表"] = rows[:safe_top_k]
                text = json.dumps(payload, ensure_ascii=False)
            if text:
                planned_parts.append(f"【{title}】\n{text}")
        if planned_parts:
            return "\n\n---\n\n".join(planned_parts)

    # 规划器或动态工具调用不可用时，保留原有的普通案例 + 权威案例双路兜底。
    gathered = await asyncio.gather(
        call_qcc_tool(
            "case",
            "get_judicial_case_search",
            {"keyword": safe_query[:200]},
        ),
        call_qcc_tool(
            "case",
            "get_judicial_authoritative_case_search",
            {"keyword": safe_query[:200]},
        ),
        return_exceptions=True,
    )
    parts: List[str] = []
    labels = ("普通案例检索", "权威案例检索")
    for index, result in enumerate(gathered):
        if isinstance(result, Exception):
            if isinstance(result, QccMCPError):
                parts.append(f"{labels[index]}：{result}")
            else:
                parts.append(f"{labels[index]}：调用失败")
            continue
        text = str(result).strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except ValueError:
            payload = None
        if isinstance(payload, dict) and payload.get("案例列表"):
            rows = payload["案例列表"]
            if isinstance(rows, list) and len(rows) > safe_top_k:
                payload["案例列表"] = rows[:safe_top_k]
            text = json.dumps(payload, ensure_ascii=False)
        parts.append(text)
    if not parts:
        raise QccMCPError("企查查司法案例 MCP 未检得可用案例")
    return "\n\n---\n\n".join(parts)


async def search_laws(query: str, top_k: int = 6) -> str:
    """法律法规查询：按实时能力选择检索/溯源工具，失败时双路召回。"""
    safe_query = str(query or "").strip()
    if not safe_query:
        raise QccMCPError("检索问题不能为空")
    safe_top_k = max(1, min(int(top_k or 6), 20))
    try:
        planned_calls, tool_titles = await plan_qcc_tool_calls(
            "regulation",
            safe_query,
            excluded_tools=("get_legal_article_detail", "get_legal_regulation_detail"),
            max_calls=3,
        )
    except Exception:
        planned_calls, tool_titles = [], {}
    if planned_calls:
        gathered = await asyncio.gather(
            *(call_qcc_tool("regulation", call["name"], call["arguments"]) for call in planned_calls),
            return_exceptions=True,
        )
        planned_parts = []
        for call, result in zip(planned_calls, gathered):
            title = tool_titles.get(call["name"], call["name"])
            if isinstance(result, Exception):
                continue
            text = str(result).strip()
            payload = _json_value(text)
            rows = payload.get("法条列表") if payload else None
            if isinstance(rows, list) and len(rows) > safe_top_k:
                payload["法条列表"] = rows[:safe_top_k]
                text = json.dumps(payload, ensure_ascii=False)
            if text:
                planned_parts.append(f"【{title}】\n{text}")
        if planned_parts:
            return "\n\n---\n\n".join(planned_parts)

    gathered = await asyncio.gather(
        call_qcc_tool(
            "regulation",
            "get_legal_article_semantic_search",
            {"query": safe_query[:500]},
        ),
        call_qcc_tool(
            "regulation",
            "get_legal_article_search",
            {"keyword": safe_query[:160]},
        ),
        return_exceptions=True,
    )
    parts: List[str] = []
    labels = ("法条语义检索", "法条关键词检索")
    for index, result in enumerate(gathered):
        if isinstance(result, Exception):
            if isinstance(result, QccMCPError):
                parts.append(f"{labels[index]}：{result}")
            else:
                parts.append(f"{labels[index]}：调用失败")
            continue
        text = str(result).strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except ValueError:
            payload = None
        if isinstance(payload, dict) and payload.get("法条列表"):
            rows = payload["法条列表"]
            if isinstance(rows, list) and len(rows) > safe_top_k:
                payload["法条列表"] = rows[:safe_top_k]
            text = json.dumps(payload, ensure_ascii=False)
        parts.append(text)
    if not parts:
        raise QccMCPError("企查查法律法规 MCP 未检得可用法条")
    return "\n\n---\n\n".join(parts)
