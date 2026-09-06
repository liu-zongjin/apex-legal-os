"""北大法宝 Streamable HTTP MCP 适配器。

本模块只把北大法宝 MCP 实际返回的案例、法规字段交给问答层；授权信息仅从
``PKULAW_MCP_AUTHORIZATION`` 读取，绝不写入检索结果、日志或前端响应。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

import httpx

from .ai_config import PKULAW_MCP_AUTHORIZATION
from .case_authority import case_authority_level
from .case_issue import build_fact_fingerprint, build_search_constraints, constraint_hit, evaluate_case_fit, match_tier_order


class PkuLawMCPError(RuntimeError):
    pass


_DEFAULT_URLS = {
    "law_search": "https://apim-gateway.pkulaw.com/mcp-law-search-service",
    "law_keyword": "https://apim-gateway.pkulaw.com/mcp-law",
    "case_semantic": "https://apim-gateway.pkulaw.com/mcp-case-search-service",
    "case_keyword": "https://apim-gateway.pkulaw.com/mcp-case",
    "law_item": "https://apim-gateway.pkulaw.com/mcp-fatiao",
    "law_recognition": "https://apim-gateway.pkulaw.com/law_recognition",
    "case_number_recognition": "https://apim-gateway.pkulaw.com/case_number_recognition",
    "citation_validator": "https://apim-gateway.pkulaw.com/pku_citation_validator",
    "doc_link": "https://apim-gateway.pkulaw.com/add-doc-link",
}

_CASE_GRADE_SCORE = {
    "指导性案例": 100, "参考案例": 95, "公报案例": 90, "典型案例": 85,
    "参阅案例": 80, "经典案例": 75, "优秀案例": 70, "应用案例": 65,
    "法宝推荐": 60, "评析案例": 45, "普通案例": 20,
}


def server_config(kind: str) -> Tuple[str, str]:
    if kind not in _DEFAULT_URLS:
        raise ValueError("不支持的北大法宝 MCP 类型")
    env_name = f"PKULAW_{kind.upper()}_URL"
    return os.environ.get(env_name, _DEFAULT_URLS[kind]).strip(), PKULAW_MCP_AUTHORIZATION


def source_status(kind: str) -> Dict[str, Any]:
    url, authorization = server_config(kind)
    source_name = "北大法宝·案例库 MCP" if kind.startswith("case") else "北大法宝·法律法规 MCP"
    return {"name": source_name, "url": url, "configured": bool(url and authorization), "enabled": bool(url and authorization)}


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
            message = (envelope.get("error") or {}).get("message") or "北大法宝 MCP 调用失败"
            raise PkuLawMCPError(str(message))
        return envelope
    raise PkuLawMCPError("北大法宝 MCP 返回了无法识别的数据")


async def call_pkulaw_tool(kind: str, tool_name: str, arguments: Dict[str, Any], timeout: float = 35.0) -> str:
    url, authorization = server_config(kind)
    if not authorization:
        raise PkuLawMCPError("北大法宝 MCP 尚未配置")
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "Authorization": authorization,
    }
    initialize = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "legal-knowledge-base", "version": "1.0.0"}},
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
                await client.post(url, json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=session_headers)
                response = await client.post(
                    url,
                    json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": tool_name, "arguments": arguments}},
                    headers=session_headers,
                )
                envelope = _decode_response(response)
            break
        except httpx.TimeoutException as exc:
            last_error = PkuLawMCPError("北大法宝 MCP 连接超时，请稍后重试")
            last_error.__cause__ = exc
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            last_error = PkuLawMCPError(f"北大法宝 MCP 连接失败（HTTP {status_code}）")
            last_error.__cause__ = exc
            if status_code not in {429, 502, 503, 504}:
                raise last_error
        except httpx.RequestError as exc:
            last_error = PkuLawMCPError("当前无法连接北大法宝 MCP")
            last_error.__cause__ = exc
        if attempt == len(retry_delays) - 1:
            raise last_error or PkuLawMCPError("当前无法连接北大法宝 MCP")

    result = envelope.get("result") or {}
    content = result.get("content") or []
    text = "\n".join(str(item.get("text") or "").strip() for item in content if isinstance(item, dict) and item.get("type") == "text").strip()
    if result.get("isError"):
        raise PkuLawMCPError(text or "北大法宝 MCP 工具执行失败")
    if not text:
        raise PkuLawMCPError("北大法宝 MCP 未返回结果")
    return text


def _json_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return []


def _value(row: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, list):
            value = "、".join(str(item) for item in value if item)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _case_key(row: Dict[str, Any]) -> str:
    return re.sub(r"[\s()（）]", "", _value(row, "案号", "case_number", "CaseFlag")) or re.sub(r"\s+", "", _value(row, "案名", "title", "Title"))


def _normalise_case(row: Dict[str, Any], mode: str, query_id: str = "") -> Dict[str, Any]:
    grade = _value(row, "case_grade", "CaseGrade")
    return {
        "案名": _value(row, "title", "Title") or "检索结果未提供",
        "案号": _value(row, "case_number", "CaseFlag") or "检索结果未提供",
        "法院": _value(row, "courthouse_name", "Court") or "检索结果未提供",
        "裁判日期": _value(row, "decision_date", "LastInstanceDate") or "检索结果未提供",
        "案件类型": _value(row, "case_type", "CaseClassName", "Category") or "检索结果未提供",
        "文书类型": _value(row, "doc_type", "DocumentAttr") or "检索结果未提供",
        "案由": _value(row, "cause_of_action") or "检索结果未提供",
        "权威类型": grade or "普通案例",
        "关键事实": _value(row, "ascertain", "Ascertain"),
        "裁判观点": _value(row, "identified", "Identified", "CaseGist", "Core"),
        "裁判结果": _value(row, "referee_result", "RefereeResult"),
        "原文链接": _value(row, "url", "Url"),
        "来源": "北大法宝·案例库 MCP",
        "检索方式": mode,
        "证据类型": "北大法宝 MCP 返回的案例字段",
        "_retrieved_by": [query_id] if query_id else [mode],
        "_rank": max((_CASE_GRADE_SCORE.get(part, 0) for part in re.split(r"[、,，]", grade)), default=0),
    }


def _compact_case(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: (str(value)[:5000] if key in {"关键事实", "裁判观点", "裁判结果"} else value)
        for key, value in item.items() if not key.startswith("_")
    }


def _case_query(query: str, constraints: Dict[str, Any] = None) -> str:
    text = re.sub(r"[“”\"'《》]", " ", str(query or ""))
    for word in sorted((constraints or {}).get("constraint_words") or [], key=len, reverse=True):
        text = text.replace(word, " ")
    text = re.sub(r"(?:请|帮我|检索|查询|搜索|查找|相关|案例|裁判|判决|观点|能否|是否|如何|什么|以下|案件|收费|收取|的)", " ", text)
    terms = re.findall(r"[\u4e00-\u9fff]{2,12}", text)
    return " ".join(dict.fromkeys(terms[:4])) or str(query or "").strip()


def _case_type_for_query(query: str) -> Optional[str]:
    text = str(query or "")
    if any(marker in text for marker in ("刑事", "犯罪", "刑法", "被告人", "公诉", "罪", "量刑")):
        return "刑事案件"
    if any(marker in text for marker in ("行政", "行政处罚", "行政许可", "行政复议")):
        return "行政案件"
    if any(marker in text for marker in ("执行", "终本", "执行异议", "执行复议")):
        return "执行案件"
    return "民事案件"


async def search_cases(query: str, top_k: int = 10) -> Dict[str, Any]:
    safe_query = str(query or "").strip()
    if not safe_query:
        raise PkuLawMCPError("检索问题不能为空")
    size = max(1, min(int(top_k or 10), 20))
    fingerprint = build_fact_fingerprint(safe_query)
    constraints = build_search_constraints(safe_query)
    keyword_queries = list(fingerprint.get("query_routes") or [])[:5] or [_case_query(safe_query, constraints)]
    semantic_queries = list(fingerprint.get("semantic_queries") or [])[:2] or [safe_query]
    calls = [
        ("语义检索", f"semantic_{index + 1}", call_pkulaw_tool(
            "case_semantic", "search_case",
            {"text": value[:1000], "case_type": _case_type_for_query(safe_query), "size": max(size, 15)},
        ))
        for index, value in enumerate(semantic_queries)
    ]
    calls.extend(
        ("关键词检索", f"keyword_{index + 1}", call_pkulaw_tool(
            "case_keyword", "get_case_list", {"fulltext": value[:160]}
        ))
        for index, value in enumerate(keyword_queries)
    )
    results = await asyncio.gather(*(item[2] for item in calls), return_exceptions=True)
    errors, candidates = [], []
    retrieval_runs = []
    for (mode, query_id, _), raw in zip(calls, results):
        if isinstance(raw, Exception):
            errors.append(str(raw))
            continue
        value = _json_value(raw)
        rows = value if mode == "语义检索" and isinstance(value, list) else (
            value.get("Data") if isinstance(value, dict) else []
        )
        normalised = [_normalise_case(row, mode, query_id) for row in (rows or []) if isinstance(row, dict)]
        candidates.extend(normalised)
        retrieval_runs.append({"query_id": query_id, "mode": mode, "result_count": len(normalised)})
    if not candidates:
        raise PkuLawMCPError(errors[0] if errors else "北大法宝案例库未返回可用案例")
    deduped = {}
    for item in candidates:
        key = _case_key(item)
        if not key:
            continue
        if key not in deduped:
            deduped[key] = item
            continue
        # 关键词检索往往有更好的案例等级标签，语义检索通常才含裁判理由和结果。
        # 同一案件合并真实返回字段，不能为了等级而丢失可引用的裁判内容。
        existing = deduped[key]
        existing["_retrieved_by"] = sorted(set(existing.get("_retrieved_by", []) + item.get("_retrieved_by", [])))
        for field in ("案名", "案号", "法院", "裁判日期", "案件类型", "文书类型", "案由", "关键事实", "裁判观点", "裁判结果", "原文链接"):
            if existing.get(field) in {"", "检索结果未提供"} and item.get(field) not in {"", "检索结果未提供"}:
                existing[field] = item[field]
        if item["_rank"] > existing["_rank"]:
            existing["_rank"] = item["_rank"]
            existing["权威类型"] = item["权威类型"]
    for item in deduped.values():
        fit = evaluate_case_fit((
            item.get("案名"), item.get("关键事实"), item.get("裁判观点"), item.get("裁判结果")
        ), fingerprint)
        if fingerprint.get("kind") == "generic":
            fit.update({"match_tier": "related", "direction_match": "not_applicable"})
        item.update(fit)
        constraint_result = constraint_hit(
            str(item.get("法院") or ""), constraints, region_extra=str(item.get("案名") or "")
        )
        item["constraint_hit"] = constraint_result["constraint_hit"]
        item["constraint_notes"] = constraint_result["notes"]
        authority_rank, _ = case_authority_level({
            "title": item.get("案名"), "case_number": item.get("案号"),
            "court": item.get("法院"), "authority_type": item.get("权威类型"),
        })
        item["_authority_rank"] = authority_rank
        item["_fit_rank"] = float(item.get("fit_score") or 0) + min(len(item.get("_retrieved_by", [])), 4) * 0.03
    constraint_active = bool(constraints.get("court_levels") or constraints.get("strict_regions"))
    selected = sorted(deduped.values(), key=lambda item: (
        0 if item.get("constraint_hit") else 1,
        match_tier_order(item.get("match_tier", "related")) if fingerprint.get("strict_direction") else 0,
        item.get("_authority_rank", 5),
        -item.get("_fit_rank", 0),
        -item["_rank"],
    ))[:size]
    for item in selected:
        item["事实方向"] = item.get("detected_direction", "unknown")
        item["方向匹配"] = item.get("direction_match", "not_applicable")
        item["类案层级"] = item.get("match_tier", "related")
        item["召回路径"] = item.get("_retrieved_by", [])
        item["筛选条件命中"] = "是" if item.get("constraint_hit") is True else ("否" if item.get("constraint_hit") is False else "不适用")
        item["筛选条件说明"] = "、".join(item.get("constraint_notes") or []) if not item.get("constraint_hit") else ""
    payload = {"检索问题": safe_query, "数据源": "北大法宝·案例库 MCP", "筛选条件": constraints.get("description") or "", "案例": [_compact_case(item) for item in selected]}
    return {
        "result": json.dumps(payload, ensure_ascii=False, indent=2),
        "case_count": len(selected), "errors": errors,
        "query_plan": {
            "fact_fingerprint": fingerprint,
            "retrieval_runs": retrieval_runs,
            "search_constraints": constraints,
        },
        "constraint_active": constraint_active,
    }


def _normalise_law(row: Dict[str, Any], mode: str) -> Dict[str, Any]:
    return {
        "法规名称": _value(row, "title", "Title") or "检索结果未提供",
        "条文内容": _value(row, "article"),
        "文号": _value(row, "doc_no", "DocumentNO"),
        "时效状态": _value(row, "timeliness", "TimelinessDic") or "检索结果未提供",
        "效力位阶": _value(row, "effectiveness", "EffectivenessDic") or "检索结果未提供",
        "制定机关": _value(row, "issue_department", "IssueDepartment") or "检索结果未提供",
        "公布日期": _value(row, "issue_date", "IssueDate"),
        "施行日期": _value(row, "implementation_date", "ImplementDate"),
        "原文链接": _value(row, "url", "Url"),
        "来源": "北大法宝·法律法规 MCP",
        "检索方式": mode,
        "证据类型": "北大法宝 MCP 返回的法规字段",
    }


_ARTICLE_NUMBER_RE = re.compile(r"第?(?P<number>[一二三四五六七八九十百千万零〇]{1,10}|\d{1,4})条")
_LAW_TITLE_BRACKETS_RE = re.compile(r"[《》〈〉<>\"'“”\s]")
_LAW_TITLE_SUFFIX_RE = re.compile(r"[（(](?:19|20)\d{2}年?(?:修正|修订)(?:文本)?[）)]$")
_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}


def _normalise_law_title(value: str) -> str:
    """法规名称归一化：去书名号/空白/引号，去掉尾部"（2023修正）"等版本后缀，用于跨版本合并。"""
    title = _LAW_TITLE_BRACKETS_RE.sub("", value or "")
    return _LAW_TITLE_SUFFIX_RE.sub("", title)


def _article_number_value(text: str) -> Optional[int]:
    """把条号转成阿拉伯数字，如 "五百七十七" -> 577、"509" -> 509；无法解析返回 None。"""
    text = str(text or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if not re.fullmatch(r"[零〇一二三四五六七八九十百千万]+", text):
        return None
    total, section, digit = 0, 0, 0
    for ch in text:
        if ch in _CN_DIGITS:
            digit = _CN_DIGITS[ch]
        elif ch == "万":
            section = (section + digit) * 10000
            total += section
            section, digit = 0, 0
        else:
            section += (digit or 1) * _CN_UNITS[ch]
            digit = 0
    return total + section + digit


def _find_title_spans(text: str) -> List[Tuple[int, int]]:
    """按配对的《》扫描法规名称区间，支持名称内嵌套书名号（如《关于适用《民诉法》的解释》）。"""
    spans: List[Tuple[int, int]] = []
    depth, start = 0, -1
    for index, ch in enumerate(text):
        if ch == "《":
            if depth == 0:
                start = index
            depth += 1
        elif ch == "》" and depth:
            depth -= 1
            if depth == 0 and start != -1:
                spans.append((start, index + 1))
                start = -1
    return spans


def _article_hints(query: str) -> List[Tuple[str, str]]:
    """提取查询中所有的 (法规名称, 条号) 组合，支持一个法规多个条文、多个法规并存。

    条号兼容"第五百零九条""154条""第135条"等中英文/带不带"第"的写法。
    """
    text = str(query or "")
    hints: List[Tuple[str, str]] = []
    spans = _find_title_spans(text)
    for index, (start, end) in enumerate(spans):
        title = text[start + 1:end - 1].strip()
        title = title.replace("<", "《").replace(">", "》").replace("〈", "《").replace("〉", "》")
        next_start = spans[index + 1][0] if index + 1 < len(spans) else len(text)
        for number in _ARTICLE_NUMBER_RE.finditer(text, end, next_start):
            hints.append((title, number.group("number")))
    if hints:
        return hints
    # 兜底：无书名号时，把第一条"第X条"前的连续汉字当作法规名，绑定后续所有条号。
    first = _ARTICLE_NUMBER_RE.search(text)
    if first:
        head_match = re.search(r"[\u4e00-\u9fff]{2,50}$", text[: first.start()])
        if head_match:
            title = head_match.group(0)
            hints = [(title, number.group("number")) for number in _ARTICLE_NUMBER_RE.finditer(text)]
    return hints


async def search_laws(query: str, top_k: int = 8) -> Dict[str, Any]:
    safe_query = str(query or "").strip()
    if not safe_query:
        raise PkuLawMCPError("检索问题不能为空")
    size = max(1, min(int(top_k or 8), 20))
    hints = _article_hints(safe_query)
    unique_titles = list(dict.fromkeys(title for title, _ in hints))[:5]
    calls = [
        ("full", lambda: call_pkulaw_tool("law_search", "search_article", {"text": safe_query[:1000], "timeliness": "现行有效", "size": size})),
        ("keyword", lambda: call_pkulaw_tool("law_keyword", "get_law_list", {"fulltext": _case_query(safe_query)[:160], "timeliness": ["现行有效"]})),
    ]
    # 按法规名单独语义检索，主要作为元数据（文号/制定机关/公布日期）的可靠来源。
    for title in unique_titles:
        calls.append(("law_semantic", lambda t=title: call_pkulaw_tool("law_search", "search_article", {"text": t, "timeliness": "现行有效", "size": 5})))
    for title, number in hints[:15]:
        calls.append(("precise", lambda t=title, n=number: call_pkulaw_tool("law_search", "get_article", {"title": t, "number": f"第{n}条"})))
    responses = await asyncio.gather(*(call() for _, call in calls), return_exceptions=True)
    errors, laws = [], []
    for (kind, _), raw in zip(calls, responses):
        if isinstance(raw, Exception):
            errors.append(str(raw)); continue
        value = _json_value(raw)
        if kind == "full":
            laws.extend(_normalise_law(row, "语义检索") for row in value if isinstance(row, dict))
        elif kind == "keyword":
            rows = value.get("Data") if isinstance(value, dict) else []
            laws.extend(_normalise_law(row, "关键词检索") for row in (rows or []) if isinstance(row, dict))
        elif kind == "law_semantic":
            rows = value if isinstance(value, list) else [value]
            laws.extend(_normalise_law(row, "语义检索") for row in rows if isinstance(row, dict))
        else:
            rows = value if isinstance(value, list) else [value]
            laws.extend(_normalise_law(row, "指定条文查询") for row in rows if isinstance(row, dict))
    if not laws:
        raise PkuLawMCPError(errors[0] if errors else "北大法宝法律法规库未返回可用结果")
    if hints:
        # 精确指定了条文时：空条文的行只保留"命中请求法规"的（作为元数据来源），
        # 其余噪音行（司法解释、通知等）剔除。
        requested_titles = {_normalise_law_title(title) for title, _ in hints}
        laws = [
            item for item in laws
            if item["条文内容"] or _normalise_law_title(item["法规名称"]) in requested_titles
        ]
    # 指定条文查询的正文优先，同法规（含不同修正版本名称）条目互相补齐元数据空字段。
    order_rank = {"指定条文查询": 0, "语义检索": 1, "关键词检索": 2}
    merged: Dict[str, Dict[str, Any]] = {}
    for item in sorted(laws, key=lambda law: order_rank.get(law["检索方式"], 9)):
        key = _normalise_law_title(item["法规名称"]) + "\n" + item["条文内容"]
        if key not in merged:
            merged[key] = item
    for item in merged.values():
        item_title = _normalise_law_title(item["法规名称"])
        for other in laws:
            if _normalise_law_title(other["法规名称"]) != item_title:
                continue
            for field in ("文号", "时效状态", "效力位阶", "制定机关", "公布日期", "施行日期", "原文链接"):
                if item.get(field) in {"", "检索结果未提供"} and other.get(field) not in {"", "检索结果未提供"}:
                    item[field] = other[field]
    # 精确查询的返回必须命中请求的条号，防止张冠李戴；指定了条文时其余检索
    # 方式返回的非请求条文也一并剔除，保证只输出用户点名的条文。
    requested = {_article_number_value(number) for _, number in hints}
    selected = []
    for item in sorted(merged.values(), key=lambda law: order_rank.get(law["检索方式"], 9)):
        if not item["条文内容"]:
            continue
        leading = _ARTICLE_NUMBER_RE.match(item["条文内容"])
        if item["检索方式"] == "指定条文查询":
            if not leading or _article_number_value(leading.group("number")) not in requested:
                errors.append(f"指定条文查询未命中：{item['法规名称']} {leading.group(0) if leading else '无法识别条号'}")
                continue
        elif hints and (not leading or _article_number_value(leading.group("number")) not in requested):
            continue
        selected.append(item)
    selected = selected[:size]
    if not selected:
        raise PkuLawMCPError(errors[0] if errors else "北大法宝法律法规库未返回可用结果")
    payload = {"检索问题": safe_query, "数据源": "北大法宝·法律法规 MCP", "法规": selected}
    return {"result": json.dumps(payload, ensure_ascii=False, indent=2), "law_count": len(selected), "errors": errors}


async def status() -> Dict[str, Any]:
    """轻量连通性探测；仅列工具，不调用检索。"""
    probe_kinds = {"case": "case_semantic", "law": "law_search"}
    result: Dict[str, Any] = {"configured": bool(PKULAW_MCP_AUTHORIZATION), "sources": []}
    for label, kind in probe_kinds.items():
        url, authorization = server_config(kind)
        result["sources"].append({"kind": label, "url": url, "configured": bool(url and authorization)})
    return result
