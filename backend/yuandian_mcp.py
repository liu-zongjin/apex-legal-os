"""元典案例与法律法规 Streamable HTTP MCP 客户端。"""

from __future__ import annotations

import json
import os
import re
import asyncio
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import httpx

from .case_authority import sort_cases_by_authority
from .case_issue import (
    build_fact_fingerprint,
    build_search_constraints,
    constraint_hit,
    detect_court_level,
    evaluate_case_fit,
    match_tier_order,
)
from .mcp_tool_router import discover_streamable_http_tools, plan_mcp_tool_calls


class YuandianMCPError(RuntimeError):
    pass


_DEFAULT_URLS = {
    "case": "https://open.chineselaw.com/mcp/case/stream",
    "law": "https://open.chineselaw.com/mcp/law/stream",
}


def _codex_server_config(server_name: str) -> Tuple[str, str]:
    """读取用户已授权的本机 Codex MCP 配置，不复制或记录凭据。"""
    config_path = Path(os.environ.get("CODEX_CONFIG_PATH", Path.home() / ".codex" / "config.toml"))
    try:
        raw = config_path.read_text(encoding="utf-8")
    except OSError:
        return "", ""
    match = re.search(
        rf"^\[mcp_servers\.{re.escape(server_name)}\]\s*$\n(.*?)(?=^\[|\Z)",
        raw,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not match:
        return "", ""
    section = match.group(1)
    url_match = re.search(r'^url\s*=\s*"([^"\n]+)"', section, flags=re.MULTILINE)
    auth_match = re.search(r'Authorization\s*=\s*"([^"\n]+)"', section)
    return (
        url_match.group(1).strip() if url_match else "",
        auth_match.group(1).strip() if auth_match else "",
    )


def server_config(kind: str) -> Tuple[str, str]:
    if kind not in _DEFAULT_URLS:
        raise ValueError("不支持的元典 MCP 类型")
    prefix = f"YUANDIAN_{kind.upper()}_MCP"
    url = os.environ.get(f"{prefix}_URL", "").strip()
    authorization = os.environ.get("YUANDIAN_MCP_AUTHORIZATION", "").strip()
    if not url or not authorization:
        configured_url, configured_authorization = _codex_server_config(f"yuandian-{kind}")
        url = url or configured_url
        authorization = authorization or configured_authorization
    return url or _DEFAULT_URLS[kind], authorization


def source_status(kind: str) -> Dict[str, Any]:
    url, authorization = server_config(kind)
    return {
        "name": "元典·案例库 MCP" if kind == "case" else "元典·法律法规 MCP",
        "url": url,
        "configured": bool(url and authorization),
        "enabled": bool(url and authorization),
    }


def _decode_response(response: httpx.Response) -> Dict[str, Any]:
    response.raise_for_status()
    raw = response.text.strip()
    if not raw:
        return {}
    payloads = []
    if raw.startswith("event:") or raw.startswith("data:"):
        payloads = [line[5:].strip() for line in raw.splitlines() if line.startswith("data:")]
    else:
        payloads = [raw]
    for value in reversed(payloads):
        if not value:
            continue
        try:
            envelope = json.loads(value)
        except json.JSONDecodeError:
            continue
        if envelope.get("error"):
            message = (envelope.get("error") or {}).get("message") or "元典 MCP 调用失败"
            raise YuandianMCPError(str(message))
        return envelope
    raise YuandianMCPError("元典 MCP 返回了无法识别的数据")


async def call_yuandian_tool(
    kind: str,
    tool_name: str,
    arguments: Dict[str, Any],
    timeout: float = 35.0,
) -> str:
    url, authorization = server_config(kind)
    if not authorization:
        raise YuandianMCPError(f"元典·{'案例库' if kind == 'case' else '法律法规'} MCP 尚未配置")
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
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            init_response = await client.post(url, json=initialize, headers=headers)
            _decode_response(init_response)
            session_id = init_response.headers.get("mcp-session-id")
            session_headers = dict(headers)
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
    except httpx.TimeoutException as exc:
        raise YuandianMCPError("元典 MCP 连接超时，请稍后重试") from exc
    except httpx.HTTPStatusError as exc:
        raise YuandianMCPError(f"元典 MCP 连接失败（HTTP {exc.response.status_code}）") from exc
    except httpx.RequestError as exc:
        raise YuandianMCPError("当前无法连接元典 MCP") from exc

    result = envelope.get("result") or {}
    content = result.get("content") or []
    text = "\n".join(
        str(item.get("text") or "").strip()
        for item in content
        if isinstance(item, dict) and item.get("type") == "text" and item.get("text")
    ).strip()
    if result.get("isError"):
        raise YuandianMCPError(text or "元典 MCP 工具执行失败")
    if not text:
        raise YuandianMCPError("元典 MCP 未返回结果")
    return text


async def search_cases(query: str, top_k: int = 6) -> str:
    return await call_yuandian_tool(
        "case",
        "yuandian_case_vector_search",
        {
            "query": str(query or "").strip()[:1000],
            "rewrite_flag": True,
            "wenshu_filter": {"dianxing": False},
            "return_num": max(1, min(int(top_k or 6), 10)),
        },
    )


def _json_payload(raw: str) -> Dict[str, Any]:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _case_rows(raw: str) -> list:
    """兼容关键词接口与语义接口的两种返回结构。"""
    payload = _json_payload(raw)
    data = payload.get("data") or {}
    rows = data.get("lst") if isinstance(data, dict) else None
    if rows is None:
        rows = (payload.get("extra") or {}).get("wenshu") or []
    return [row for row in (rows or []) if isinstance(row, dict)]


_QUERY_NOISE = {
    "检索", "查询", "搜索", "支持", "观点", "裁判", "案例", "真实案例", "相关案例",
    "找一些", "给我", "总结", "归纳", "说明", "问题", "责任", "承担责任", "应当",
    "是否", "能否", "可以", "不能", "不得", "不予", "要求", "这一", "一个", "相关",
    "以及", "对于", "如果", "因为", "什么", "怎么", "如何", "哪些", "分别", "结果",
    "房子", "二楼", "一层", "赠送", "没有", "计入", "产权证", "只有", "业主", "上到",
    "流到", "积水", "杂草", "灰尘", "泥土", "平时", "基本", "任何", "改造", "罕见",
    # 筛选与交付类噪声词：法院层级、地域、程序词由 build_search_constraints 解析，
    # 不进入 AND 检索式；以下词用于 jieba 分词后的过滤兜底。
    "广东省", "其他省", "中级人民法院", "高级人民法院", "基层人民法院", "最高人民法院",
    "中级", "高级", "基层", "最高", "中院", "高院", "人民法院", "法院", "省内",
    "以下", "案件", "收费", "如何", "收取", "就此", "提起", "针对", "围绕",
    "有关", "这类", "此类", "以下案件", "诉讼费如何",
}

_LEGAL_PHRASES = (
    "预约合同", "本约合同", "强制履行", "继续履行", "强制缔约", "违约责任",
    "商品房预约合同", "意思自治", "非金钱债务", "合同成立", "实际履行",
    "露台", "排水口", "排水堵塞", "漏水", "渗漏", "倒灌", "烟道", "暴雨",
    "不可抗力", "物业服务", "物业公司", "共有部分", "专有部分", "实际控制人",
    "设计缺陷", "施工缺陷", "财产损害赔偿", "物件损害责任", "过错责任",
    "建设工程价款", "优先受偿权", "债权转让", "执行异议", "表见代理", "诉讼时效",
    # 债权人撤销权与诉讼费争点
    "债权人撤销权", "放弃到期债权", "无偿放弃", "放弃债权", "免除债务", "无偿处分",
    "撤销权", "撤销债务人", "债务人无偿", "恶意延长",
    "诉讼费", "案件受理费", "受理费", "按件收费", "非财产案件", "财产案件",
    "诉讼标的", "标的额", "简易程序",
)

_TERM_EXPANSIONS = {
    "预约合同": ("本约合同", "强制缔约", "继续履行", "违约责任"),
    "露台": ("排水口", "物业公司", "共有部分", "漏水"),
    "排水口": ("堵塞", "倒灌", "暴雨"),
    "物业公司": ("物业服务", "维修养护", "共有部分"),
    "撤销权": ("债权人撤销权", "放弃债权", "免除债务", "无偿转让"),
    "放弃债权": ("放弃到期债权", "免除债务", "无偿处分", "恶意延长"),
    "债权人撤销权": ("放弃债权", "无偿处分", "撤销债务人"),
    "诉讼费": ("案件受理费", "按件收费", "非财产案件", "诉讼标的"),
    "案件受理费": ("受理费", "诉讼费", "按件收费", "非财产案件"),
}


def _clean_issue_query(query: str) -> str:
    text = re.sub(r"\s+", " ", str(query or "")).strip()
    text = re.sub(r"^(?:请|麻烦|帮我)?(?:检索|查询|搜索|找(?:一些|几件)?)", "", text)
    text = re.sub(r"(?:并)?(?:给我)?(?:总结|归纳|列出).*$", "", text)
    return text.strip(" ，。；：:？?‘’“”\"'")[:600]


def _query_terms(query: str, constraints: Dict[str, Any]) -> List[str]:
    """抽取能区分争点的词；通用交付词与法院层级/地域等筛选词不进入案例检索。"""
    core = _clean_issue_query(query)
    # 剥离约束词：法院层级、地域、程序等筛选条件由 build_search_constraints 解析，
    # 不应占据关键词名额，也不能被 AND 进检索式造成零召回。
    for word in sorted((constraints or {}).get("constraint_words") or [], key=len, reverse=True):
        core = core.replace(word, " ")
    positioned = []
    for phrase in _LEGAL_PHRASES:
        pos = core.find(phrase)
        if pos >= 0:
            positioned.append((pos, -len(phrase), phrase))
    terms: List[str] = []
    for _, _, phrase in sorted(positioned):
        if not any(phrase in existing and phrase != existing for existing in terms):
            terms.append(phrase)
    # 先加入争点同义词，再接收通用分词，避免长事实描述把真正用于类案召回的
    # “物业/共有部分/漏水”等法律概念挤出词表。
    for term in list(terms):
        for expansion in _TERM_EXPANSIONS.get(term, ()):
            if expansion not in terms:
                terms.append(expansion)
    try:
        import jieba
        segmented = jieba.cut(re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]+", " ", core), cut_all=False)
    except Exception:
        segmented = re.findall(r"[\u4e00-\u9fff]{2,10}|[A-Za-z][A-Za-z0-9.-]+", core)
    for word in segmented:
        word = str(word).strip()
        if len(word) < 2 or word in _QUERY_NOISE or word.isdigit():
            continue
        if any(word in existing for existing in terms):
            continue
        terms.append(word)
    return terms[:12]


def build_case_query_plan(query: str) -> Dict[str, Any]:
    core = _clean_issue_query(query)
    constraints = build_search_constraints(core)
    terms = _query_terms(query, constraints)
    fingerprint = build_fact_fingerprint(core)
    if fingerprint.get("kind") == "sequential_guarantee_claims":
        terms = ["连带保证人", "保证责任", "主债务人", "重复起诉", "可分之诉", "分别起诉", "重复受偿"]
    if not terms:
        terms = [core[:24]] if core else []

    routes: List[str] = []

    def add_route(values: Iterable[str]) -> None:
        value = " ".join(dict.fromkeys(item for item in values if item)).strip()
        if value and value not in routes:
            routes.append(value)

    # 有先后顺序的争点必须保留角色方向，并加入裁判原句/执行处理等司法语言。
    for route in fingerprint.get("query_routes") or []:
        add_route(route.split())
    # 撤销权诉讼费争点：构造“事实 + 收费”双焦点路由，避免“放弃债权”与“受理费”
    # 被同一查询长句稀释；层级/地域约束不在查询式中表达，改由结果过滤执行。
    if any(term in core for term in ("放弃债权", "放弃到期债权", "无偿放弃", "免除债务")) and (
        "撤销权" in core or "撤销" in core
    ):
        issue_routes = [
            ["债权人撤销权", "放弃到期债权"],
            ["放弃债权", "撤销债务人", "无偿"],
            ["债权人撤销权", "免除债务"],
        ]
        if any(term in core for term in ("诉讼费", "受理费", "收费", "交纳")):
            issue_routes = [
                ["债权人撤销权", "放弃到期债权", "案件受理费"],
                ["债权人撤销权", "诉讼费", "非财产案件"],
                ["撤销权", "受理费", "按件收费"],
            ]
        for route in issue_routes:
            add_route(route)
    # 通用问题仍按法律关系、裁判结果与关键事实分组，避免长事实全量 AND 导致零召回。
    if not any("撤销" in route for route in routes):
        add_route(terms[:3])
        add_route([terms[0], *terms[3:5]] if terms else [])
        add_route([*terms[1:3], *terms[5:6]])
    if len(routes) < 2:
        add_route(terms[:2])
    return {
        "original_query": str(query or "").strip(),
        "core_issue": core,
        "essential_terms": terms,
        "keyword_queries": routes[:5] if fingerprint.get("strict_direction") else routes[:3],
        "semantic_query": core or str(query or "").strip(),
        "semantic_queries": fingerprint.get("semantic_queries") or [core or str(query or "").strip()],
        "fact_fingerprint": fingerprint,
        "search_constraints": constraints,
    }


def _normalise_case(row: Dict[str, Any], source_kind: str, query_id: str) -> Dict[str, Any]:
    return {
        **row,
        "title": row.get("title") or "",
        "ah": row.get("ah") or "",
        "jbdw": row.get("jbdw") or "",
        "jaDate": row.get("jaDate") or row.get("cprq") or "",
        "source": row.get("source") or row.get("type") or row.get("db") or "",
        "content": row.get("content") or row.get("llm_content") or "",
        "url": row.get("url") or "",
        "scid": row.get("scid") or row.get("id") or "",
        "_source_kind": source_kind,
        "_retrieved_by": [query_id],
    }


def _case_key(row: Dict[str, Any]) -> str:
    return re.sub(r"\s+", "", str(row.get("ah") or row.get("scid") or row.get("title") or "")).lower()


def _deduplicate_case_rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        key = _case_key(row)
        if not key:
            continue
        if key not in merged:
            merged[key] = dict(row)
            continue
        current = merged[key]
        current["_retrieved_by"] = sorted(set(
            current.get("_retrieved_by", []) + row.get("_retrieved_by", [])
        ))
        # 权威库、详情更长的记录优先作为展示底稿。
        if row.get("_source_kind") == "qwal" and current.get("_source_kind") != "qwal":
            preserved = current["_retrieved_by"]
            current.update(row)
            current["_retrieved_by"] = preserved
        elif len(str(row.get("content") or "")) > len(str(current.get("content") or "")):
            current["content"] = row.get("content") or current.get("content")
    return list(merged.values())


def _case_relevance(row: Dict[str, Any], terms: List[str]) -> Tuple[float, List[str]]:
    text = re.sub(r"\s+", "", "\n".join(str(row.get(key) or "") for key in (
        "title", "content", "fxgc", "pjjg", "ay"
    )))
    matched = [term for term in terms if re.sub(r"\s+", "", term) in text]
    core_terms = terms[:6] or terms
    denominator = max(2, min(4, len(core_terms)))
    score = min(len(matched) / denominator, 1.0)
    if row.get("title") and any(term in str(row.get("title")) for term in core_terms):
        score += 0.08
    if row.get("_source_kind") == "qwal":
        score += 0.05
    return min(round(score, 4), 1.0), matched


def _apply_fact_fit(row: Dict[str, Any], fingerprint: Dict[str, Any]) -> None:
    fit = evaluate_case_fit((
        row.get("title"), row.get("content"), row.get("fxgc"), row.get("pjjg"), row.get("ay")
    ), fingerprint)
    if fingerprint.get("kind") == "generic":
        fit.update({"match_tier": "related", "direction_match": "not_applicable"})
    row.update({
        "_fit_score": fit["fit_score"],
        "_match_tier": fit["match_tier"],
        "_detected_direction": fit["detected_direction"],
        "_direction_match": fit["direction_match"],
    })


def _apply_constraints(row: Dict[str, Any], constraints: Dict[str, Any]) -> None:
    """把用户筛选条件（法院层级/地域/程序）写入案例行，供排序与报告分组使用。"""
    result = constraint_hit(
        str(row.get("jbdw") or ""),
        constraints,
        procedure_text=str(row.get("spcx") or ""),
        region_extra=str(row.get("cj") or ""),
    )
    row["constraint_match"] = result["constraint_match"]
    row["constraint_hit"] = result["constraint_hit"]
    row["constraint_notes"] = result["notes"]
    if result.get("constraint_level"):
        row["constraint_level"] = result["constraint_level"]


def _case_rank_score(row: Dict[str, Any], constraints: Dict[str, Any] = None) -> float:
    """同一权威层级内优先终审/再审、较高法院及字段完备的案例。"""
    score = float(row.get("_relevance") or 0) * 0.55 + float(row.get("_fit_score") or 0) * 0.45
    court = str(row.get("jbdw") or "")
    level = str(row.get("cj") or "")
    procedure = str(row.get("spcx") or "")
    if "最高" in level or "最高人民法院" in court:
        score += 0.20
    elif "高级" in level or "高级人民法院" in court:
        score += 0.16
    elif "中级" in level or "中级人民法院" in court or court.endswith("中级人民法院"):
        score += 0.10
    if "再审" in procedure:
        score += 0.12
    elif "二审" in procedure:
        score += 0.10
    elif "一审" in procedure:
        score -= 0.02
    if row.get("ah"):
        score += 0.02
    if row.get("url"):
        score += 0.01
    # 用户指定法院层级/地域时，命中约束显著加分，不命中降权；层级无法识别的中性处理。
    if constraints and (constraints.get("court_levels") or constraints.get("strict_regions")):
        hit = row.get("constraint_hit")
        if hit is True:
            score += 0.22
        elif hit is False:
            score -= 0.30
    return round(score, 4)


def _select_diverse_cases(rows: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    """第一轮每个法院取一件，避免同一批量判决占满代表性样本。"""
    if any(row.get("_match_tier") for row in rows):
        quotas = {
            "highly_similar": max(2, limit - 4),
            "analogical": 2,
            "related": 1,
            "reverse_direction": 1,
        }
        selected: List[Dict[str, Any]] = []
        selected_keys = set()
        courts = set()
        for tier in ("highly_similar", "analogical", "related", "reverse_direction"):
            tier_rows = [row for row in rows if row.get("_match_tier") == tier]
            added = 0
            for row in tier_rows:
                key = _case_key(row)
                court = str(row.get("jbdw") or row.get("source") or row.get("title") or "")
                if key in selected_keys or (court and court in courts and len(tier_rows) > 1):
                    continue
                selected.append(row)
                selected_keys.add(key)
                if court:
                    courts.add(court)
                added += 1
                if added >= quotas[tier] or len(selected) >= limit:
                    break
        for row in rows:
            key = _case_key(row)
            if key in selected_keys:
                continue
            selected.append(row)
            selected_keys.add(key)
            if len(selected) >= limit:
                break
        return selected

    selected: List[Dict[str, Any]] = []
    deferred: List[Dict[str, Any]] = []
    courts = set()
    for row in rows:
        court = str(row.get("jbdw") or row.get("source") or row.get("title") or "")
        if court and court in courts:
            deferred.append(row)
            continue
        selected.append(row)
        if court:
            courts.add(court)
        if len(selected) >= limit:
            return selected
    for row in deferred:
        selected.append(row)
        if len(selected) >= limit:
            break
    return selected


def _extract_evidence(text: str, terms: List[str], max_chars: int = 1800) -> str:
    value = re.sub(r"\n{3,}", "\n\n", str(text or "")).strip()
    if len(value) <= max_chars:
        return value
    positions = [value.find(term) for term in terms if term and value.find(term) >= 0]
    center = min(positions) if positions else 0
    start = max(0, center - 350)
    end = min(len(value), start + max_chars)
    if start:
        boundary = max(value.rfind("。", 0, start), value.rfind("\n", 0, start))
        if boundary >= max(0, start - 250):
            start = boundary + 1
    if end < len(value):
        boundary = value.find("。", end)
        if 0 < boundary <= end + 180:
            end = boundary + 1
    return ("…" if start else "") + value[start:end].strip() + ("…" if end < len(value) else "")


def _detail_rows(raw: str) -> List[Dict[str, Any]]:
    payload = _json_payload(raw)
    data = payload.get("data") or []
    if isinstance(data, dict):
        data = data.get("lst") or data.get("data") or []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


async def _verify_case_detail(row: Dict[str, Any], terms: List[str]) -> Dict[str, Any]:
    detail = None
    error = ""
    try:
        raw = await call_yuandian_tool(
            "case",
            "yuandian_rh_case_details",
            {
                "type": row.get("_source_kind") or "ptal",
                **({"id": row.get("scid")} if row.get("scid") else {"ah": row.get("ah")}),
            },
        )
        candidates = _detail_rows(raw)
        detail = next((item for item in candidates if item.get("ah") == row.get("ah")), None)
        detail = detail or (candidates[0] if candidates else None)
    except Exception as exc:  # 单案详情失败不应使整批检索报废
        error = str(exc)

    merged = {**row, **(detail or {})}
    verified = bool(detail)
    analysis = merged.get("fxgc") or ""
    if analysis:
        evidence_type = "裁判文书分析过程字段（详情接口）"
        evidence = _extract_evidence(analysis, terms)
    elif verified and row.get("_source_kind") == "ptal":
        evidence_type = "普通案例全文片段（详情接口）"
        evidence = _extract_evidence(merged.get("content") or "", terms)
    elif verified:
        evidence_type = "权威案例详情/裁判摘要字段（非逐字全文）"
        evidence = _extract_evidence(merged.get("content") or "", terms)
    else:
        evidence_type = "检索命中摘要（尚未取得详情）"
        evidence = _extract_evidence(row.get("content") or "", terms)
    score, matched = _case_relevance(merged, terms)
    merged.update({
        "_detail_verified": verified,
        "_detail_error": error,
        "_evidence_type": evidence_type,
        "_evidence": evidence,
        "_relevance": score,
        "_matched_terms": matched,
    })
    return merged


def _compact_case_result(rows: list, max_cases: int = 10, constraints: Dict[str, Any] = None) -> str:
    compact = []
    seen = set()
    prepared = []
    for row in rows:
        key = str(row.get("scid") or row.get("ah") or row.get("title") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        prepared.append({
            **row,
            "title": row.get("title") or "",
            "case_number": row.get("ah") or "",
            "court": row.get("jbdw") or "",
            "authority_type": row.get("authority") or row.get("source") or row.get("db") or "",
            "remote_score": row.get("_rank_score") or row.get("_relevance") or row.get("score") or 0,
        })
    if any(row.get("_direction_match") not in {None, "not_applicable"} for row in prepared):
        ordered = sorted(prepared, key=lambda row: (
            match_tier_order(row.get("_match_tier", "weak")),
            int(row.get("authority_rank", 5)),
            -float(row.get("remote_score") or 0),
        ))
    else:
        ordered = sort_cases_by_authority(prepared, score_key="remote_score", constraints=constraints)
    for row in ordered:
        compact.append({
            "案名": row.get("title") or "",
            "案号": row.get("ah") or "",
            "法院": row.get("jbdw") or "",
            "法院层级": row.get("cj") or "",
            "裁判日期": row.get("jaDate") or "",
            "案件类型": row.get("ajlb") or "",
            "审判程序": row.get("spcx") or "",
            "案例来源": row.get("source") or row.get("db") or row.get("type") or "",
            "权威顺序": row.get("authority_order_label") or "其他法院案例",
            "案例标识": row.get("scid") or "",
            "原文链接": row.get("url") or "",
            "详情核验状态": "已调用详情接口核验" if row.get("_detail_verified") else "仅检索命中，详情未核验",
            "证据类型": row.get("_evidence_type") or "检索命中摘要",
            "裁判依据片段": row.get("_evidence") or "",
            "判决结果": _extract_evidence(row.get("pjjg") or "", [], 500),
            "检索相关性": row.get("_relevance") or 0,
            "命中争点词": row.get("_matched_terms") or [],
            "召回路径": row.get("_retrieved_by") or [],
            "类案层级": row.get("_match_tier") or "related",
            "事实方向": row.get("_detected_direction") or "unknown",
            "方向匹配": row.get("_direction_match") or "not_applicable",
            "筛选条件命中": "是" if row.get("constraint_hit") is True else ("否" if row.get("constraint_hit") is False else "不适用"),
            "筛选条件说明": "、".join(row.get("constraint_notes") or []),
        })
        if len(compact) >= max_cases:
            break
    return json.dumps({"案例数量": len(compact), "案例": compact}, ensure_ascii=False)


async def research_cases(query: str, top_k: int = 10) -> Dict[str, Any]:
    """权威优先、关键词为主、语义补漏，并对入选案例逐案调详情核验。"""
    plan = build_case_query_plan(query)
    routes = plan["keyword_queries"]
    terms = plan["essential_terms"]
    fingerprint = plan.get("fact_fingerprint") or {}
    constraints = plan.get("search_constraints") or {}
    if not routes:
        raise YuandianMCPError("无法从问题中提取有效案例检索词")

    constraint_desc = constraints.get("description") or ""
    steps = [
        f"提炼核心争点与检索词：{'、'.join(terms[:8])}"
        + (f"；筛选条件：{constraint_desc}" if constraints.get("present") else "")
    ]
    errors: List[str] = []
    candidates: List[Dict[str, Any]] = []

    # 第一层：权威案例。只用最能代表争点的一条 AND 查询，避免 OR 查询把无关
    # 的高权威案例挤到结果前列。
    try:
        raw = await call_yuandian_tool(
            "case", "yuandian_rh_qwal_search",
            {"qw": routes[0], "search_mode": "and", "ajlb": "民事案件", "top_k": 15},
        )
        rows = [_normalise_case(row, "qwal", "权威案例关键词") for row in _case_rows(raw)]
        candidates.extend(rows)
        steps.append(f"权威案例关键词检索完成，召回 {len(rows)} 件")
    except Exception as exc:
        errors.append(f"权威案例关键词检索：{exc}")
        steps.append("权威案例关键词检索未完成")

    # 第二层：普通案例。多组 AND 查询覆盖法律关系、裁判结论与关键事实。
    async def search_ptal(index: int, route: str):
        reasoning_route = any(marker in route for marker in (
            "责任各自独立", "可分之诉", "判项", "仍可", "不构成重复起诉"
        ))
        raw = await call_yuandian_tool(
            "case", "yuandian_rh_ptal_search",
            {
                ("fxgc" if reasoning_route else "qw"): route,
                "search_mode": "and", "ajlb": "民事案件",
                "wszl": ["判决书", "裁定书"], "top_k": 30,
            },
        )
        return [_normalise_case(row, "ptal", f"普通案例关键词{index + 1}") for row in _case_rows(raw)]

    gathered = await asyncio.gather(
        *(search_ptal(index, route) for index, route in enumerate(routes)),
        return_exceptions=True,
    )
    ptal_count = 0
    for index, result in enumerate(gathered):
        if isinstance(result, Exception):
            errors.append(f"普通案例关键词{index + 1}：{result}")
            continue
        candidates.extend(result)
        ptal_count += len(result)
    steps.append(f"普通案例分组关键词检索完成，累计召回 {ptal_count} 件")

    deduped = _deduplicate_case_rows(candidates)
    scored = []
    for row in deduped:
        score, matched = _case_relevance(row, terms)
        row["_relevance"] = score
        row["_matched_terms"] = matched
        _apply_fact_fit(row, fingerprint)
        _apply_constraints(row, constraints)
        if score >= 0.42 or row.get("_match_tier") == "highly_similar":
            scored.append(row)

    # 第三层：只有关键词检索的直接相关候选不足时才启用语义检索补漏。
    if len(scored) < 5 or fingerprint.get("strict_direction"):
        try:
            semantic_raw = await asyncio.gather(*(
                call_yuandian_tool(
                    "case", "yuandian_case_vector_search",
                    {
                        "query": semantic_query, "rewrite_flag": True,
                        "wenshu_filter": {"dianxing": False, "wenshu_type": "民事案件"},
                        "return_num": 30 if fingerprint.get("strict_direction") else 12,
                    },
                )
                for semantic_query in plan.get("semantic_queries") or [plan["semantic_query"]]
            ), return_exceptions=True)
            vector_rows = []
            for index, raw in enumerate(semantic_raw):
                if isinstance(raw, Exception):
                    errors.append(f"语义补充{index + 1}：{raw}")
                    continue
                vector_rows.extend(
                    _normalise_case(row, "ptal", f"语义补充{index + 1}") for row in _case_rows(raw)
                )
            candidates.extend(vector_rows)
            steps.append(f"关键词直接相关候选不足，语义补充召回 {len(vector_rows)} 件")
            deduped = _deduplicate_case_rows(candidates)
            scored = []
            for row in deduped:
                score, matched = _case_relevance(row, terms)
                row["_relevance"] = score
                row["_matched_terms"] = matched
                _apply_fact_fit(row, fingerprint)
                _apply_constraints(row, constraints)
                if score >= 0.42 or row.get("_match_tier") == "highly_similar":
                    scored.append(row)
        except Exception as exc:
            errors.append(f"语义补充：{exc}")
            steps.append("语义补充检索未完成")

    # 先按权威层级、再按争点相关性选取；逐案详情核验后再做最终排序。
    # 用户指定法院层级/地域时，约束命中的案例优先进入候选前列。
    for row in scored:
        row["_rank_score"] = _case_rank_score(row, constraints)
    ranked = sort_cases_by_authority(scored, score_key="_rank_score", constraints=constraints)
    if fingerprint.get("strict_direction"):
        ranked = sorted(ranked, key=lambda row: (
            match_tier_order(row.get("_match_tier", "weak")),
            int(row.get("authority_rank", 5)),
            -float(row.get("_rank_score") or 0),
        ))
    detail_limit = max(5, min(int(top_k or 10), 12))
    selected = _select_diverse_cases(ranked, detail_limit)
    verified = await asyncio.gather(*(_verify_case_detail(row, terms) for row in selected))
    for row in verified:
        _apply_fact_fit(row, fingerprint)
        _apply_constraints(row, constraints)
        row["_rank_score"] = _case_rank_score(row, constraints)
    verified = sort_cases_by_authority(verified, score_key="_rank_score", constraints=constraints)
    if fingerprint.get("strict_direction"):
        verified = sorted(verified, key=lambda row: (
            match_tier_order(row.get("_match_tier", "weak")),
            int(row.get("authority_rank", 5)),
            -float(row.get("_rank_score") or 0),
        ))
    verified_count = sum(bool(row.get("_detail_verified")) for row in verified)
    if constraints.get("present"):
        hit_count = sum(bool(row.get("constraint_hit")) for row in verified)
        steps.append(f"筛选条件核验：{len(verified)} 件入选案例中 {hit_count} 件命中法院层级/地域/程序要求")
    steps.extend([
        f"按案号与案例标识去重并过滤弱相关结果，保留 {len(scored)} 件候选",
        f"对入选的 {len(verified)} 件案例调用详情接口，成功核验 {verified_count} 件",
        "按权威层级与争点相关性排序，并区分详情原文字段与检索摘要",
    ])

    compact = _compact_case_result(verified, max_cases=detail_limit, constraints=constraints)
    unique_count = (json.loads(compact) or {}).get("案例数量", 0)
    if not unique_count:
        raise YuandianMCPError("元典案例 MCP 未检得与当前争点直接相关的可用案例")
    return {
        "result": compact,
        "steps": steps,
        "errors": errors,
        "case_count": unique_count,
        "verified_count": verified_count,
        "query_plan": plan,
    }


async def search_laws(query: str, top_k: int = 6) -> str:
    safe_query = str(query or "").strip()
    if not safe_query:
        raise YuandianMCPError("检索问题不能为空")
    try:
        url, authorization = server_config("law")
        tools = await discover_streamable_http_tools(
            url,
            {"Authorization": authorization},
            cache_key=f"yuandian:law:{url}",
        )
        calls = await plan_mcp_tool_calls(
            safe_query,
            tools,
            source_name="元典·法律法规 MCP",
            max_calls=3,
            excluded_tools=(
                "yuandian_list_apis", "yuandian_get_api_doc", "yuandian_get_user_balance",
            ),
        )
        titles = {
            str(tool.get("name")): str(tool.get("title") or tool.get("name") or "")
            for tool in tools
        }
    except Exception:
        calls, titles = [], {}
    if calls:
        gathered = await asyncio.gather(
            *(call_yuandian_tool("law", call["name"], call["arguments"]) for call in calls),
            return_exceptions=True,
        )
        parts = [
            f"【{titles.get(call['name'], call['name'])}】\n{result}"
            for call, result in zip(calls, gathered)
            if not isinstance(result, Exception) and str(result).strip()
        ]
        if parts:
            return "\n\n---\n\n".join(parts)

    # 动态能力发现或规划失败时，保留既有语义检索作为稳定兜底。
    return await call_yuandian_tool(
        "law",
        "yuandian_law_vector_search",
        {
            "query": safe_query[:1000],
            "rewrite_flag": True,
            "fatiao_filter": {"sxx": ["现行有效", "尚未生效"]},
            "return_num": max(1, min(int(top_k or 6), 10)),
        },
    )


async def get_balance() -> Dict[str, Any]:
    raw = await call_yuandian_tool("case", "yuandian_get_user_balance", {})
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise YuandianMCPError("元典余额返回格式无法识别") from exc
    data = payload.get("data") or {}
    return {
        "point_balance": data.get("pointBalance"),
        "count_balance": data.get("countBalance"),
    }
