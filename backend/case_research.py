"""争点感知的权威案例检索、结构化与来源核验。"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, Iterable, List
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

from .aluris_mcp import AlurisMCPError, search_authoritative_cases
from .case_authority import case_authority_level, sort_cases_by_authority
from .case_issue import (
    build_fact_fingerprint,
    build_search_constraints,
    constraint_hit,
    evaluate_case_fit,
    match_tier_order,
)
from .yuandian_cases import is_enabled as yuandian_enabled, search_yuandian_cases


_OUTPUT_INSTRUCTION_MARKERS = (
    "请检索", "请查询", "请搜索", "请列出", "分别列出", "每案给出", "并说明",
    "整理成", "按权威", "仅保留", "删除无法", "原文链接",
)
_LEGAL_TERMS = (
    "建设工程价款", "优先受偿权", "债权转让", "受让人", "承包人", "实际施工人",
    "执行异议", "破产", "抵押权", "担保", "合同效力", "违约责任", "侵权责任",
    "股权转让", "劳动关系", "竞业限制", "公司人格否认", "诉讼时效", "除斥期间",
    "善意取得", "表见代理", "代位权", "撤销权", "从权利", "专属性",
    "放弃债权", "无偿转让", "免除债务", "诉讼费", "案件受理费", "按件收费",
)
_OFFICIAL_HOST_SUFFIXES = (
    "court.gov.cn", "chinacourt.org", "npc.gov.cn", "gov.cn", "spp.gov.cn",
)
_SECTION_LABELS = (
    "适用场景", "规则来源", "案例详情摘要", "命中原文依据", "来源位置",
    "裁判规则", "引用摘要", "原文链接", "案例编号", "说明",
)


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _strip_output_instructions(query: str) -> str:
    text = re.sub(r"\s+", " ", str(query or "")).strip()
    cut = len(text)
    for marker in _OUTPUT_INSTRUCTION_MARKERS:
        pos = text.find(marker)
        if pos > 3:
            cut = min(cut, pos)
    core = text[:cut].strip(" ，。；：:？?")
    return core or text[:500]


def _essential_terms(core_issue: str) -> List[str]:
    terms = [term for term in _LEGAL_TERMS if term in core_issue]
    if "建设工程" in core_issue and "建设工程价款" not in terms:
        terms.append("建设工程")
    return terms[:8]


def build_case_query_plan(query: str) -> Dict[str, Any]:
    """去掉交付格式噪声，生成中性、支持、反对三路召回计划。

    用户指定的法院层级/地域等筛选条件单独解析为 search_constraints，
    不进入召回查询式；召回后按约束命中优先排序。
    """
    original = str(query or "").strip()
    if not original:
        raise AlurisMCPError("检索问题不能为空")
    core = _strip_output_instructions(original)
    constraints = build_search_constraints(core)
    for word in constraints.get("constraint_words") or []:
        core = core.replace(word, " ")
    terms = _essential_terms(core)
    fingerprint = build_fact_fingerprint(core)

    if fingerprint.get("kind") == "sequential_guarantee_claims":
        required_groups = fingerprint["required_groups"]
        strict_issue_match = True
        queries = [
            {"id": f"directional_{index + 1}", "viewpoint": "neutral", "query": route}
            for index, route in enumerate(fingerprint["query_routes"])
        ]
        queries.extend([
            {"id": "support", "viewpoint": "support", "query": fingerprint["semantic_queries"][1]},
            {"id": "oppose", "viewpoint": "oppose", "query": f"{fingerprint['semantic_queries'][0]} 构成重复起诉 不得另行起诉"},
        ])
        terms = ["连带保证人", "主债务人", "重复起诉", "可分之诉", "分别起诉", "重复受偿"]
        neutral = support = oppose = ""
    elif all(marker in core for marker in ("建设工程", "债权转让", "优先受偿")):
        neutral = "建设工程价款债权转让 受让人 优先受偿权"
        support = "建设工程价款债权转让 从权利随主债权转让 受让人承继优先受偿权"
        oppose = "建设工程价款优先受偿权 专属于承包人 不随债权转让 受让人不享有"
        required_groups = [
            ["建设工程价款", "工程价款"],
            ["债权转让", "受让人", "转让债权"],
            ["优先受偿权", "优先受偿"],
        ]
        strict_issue_match = True
    elif ("撤销" in core and any(marker in core for marker in ("放弃债权", "放弃到期债权", "无偿", "免除债务"))) \
            or "撤销权" in core:
        # 债权人撤销权诉讼费争点：三路分别对应中性召回、按件/非财产口径、按标的额/财产口径，
        # 与实践中并存的两种收费做法对应，避免“予以支持/不予支持”式扩展答非所问。
        issue_terms = " ".join(
            term for term in ("债权人撤销权", "放弃到期债权", "撤销债务人", "无偿转让", "免除债务")
            if term in core or term in terms
        ) or "债权人撤销权 放弃到期债权"
        if any(marker in core for marker in ("诉讼费", "受理费", "收费", "交纳")):
            neutral = f"{issue_terms} 案件受理费"
            support = f"{issue_terms} 按件收费 非财产案件"
            oppose = f"{issue_terms} 按诉讼标的额 分段累计交纳 财产案件"
        else:
            neutral = issue_terms
            support = f"{issue_terms} 予以支持 可以撤销"
            oppose = f"{issue_terms} 不予支持 不得撤销"
        required_groups = [
            ["撤销权", "撤销债务人"],
            ["放弃债权", "放弃到期债权", "免除债务", "无偿转让", "无偿处分"],
        ]
        if any(marker in core for marker in ("诉讼费", "受理费", "收费", "交纳")):
            required_groups.append(["案件受理费", "诉讼费", "按件收费", "非财产案件", "标的额"])
        strict_issue_match = True
    else:
        neutral = core
        support = f"{core} 予以支持 可以 认可 构成"
        oppose = f"{core} 不予支持 不得 不能 不构成"
        required_groups = [[term] for term in terms[:4]]
        strict_issue_match = False

    if fingerprint.get("kind") != "sequential_guarantee_claims":
        queries = [
            {"id": "neutral", "viewpoint": "neutral", "query": neutral},
            {"id": "support", "viewpoint": "support", "query": support},
            {"id": "oppose", "viewpoint": "oppose", "query": oppose},
        ]
    seen = set()
    queries = [item for item in queries if not (item["query"] in seen or seen.add(item["query"]))]
    return {
        "original_query": original,
        "core_issue": core,
        "essential_terms": terms,
        "required_term_groups": required_groups,
        "strict_issue_match": strict_issue_match,
        "fact_fingerprint": fingerprint,
        "queries": queries,
        "search_constraints": constraints,
    }


def _field(block: str, label: str) -> str:
    labels = "|".join(re.escape(item) for item in _SECTION_LABELS)
    match = re.search(
        rf"^{re.escape(label)}[：:]\s*(.*?)(?=^(?:{labels})[：:]|\Z)",
        block,
        flags=re.MULTILINE | re.DOTALL,
    )
    return re.sub(r"\n{2,}", "\n", match.group(1)).strip() if match else ""


def _metadata(block: str) -> Dict[str, str]:
    line = next((line for line in block.splitlines() if line.startswith("来源：")), "")
    result: Dict[str, str] = {}
    for part in re.split(r"\s*\|\s*", line):
        if "：" in part:
            key, value = part.split("：", 1)
            result[key.strip()] = value.strip()
    return result


def _infer_court(detail: str, authority_type: str) -> str:
    match = re.search(r"法院\s+([^；;\n]+)", detail)
    if match:
        return match.group(1).strip()
    if "最高法" in authority_type:
        return "最高人民法院"
    return ""


def _infer_viewpoint(text: str) -> str:
    compact = _compact(text)
    oppose = ("不予支持", "不享有", "不得主张", "不能主张", "不随", "专属于", "优先权消灭")
    support = ("予以支持", "应予支持", "可以主张", "一并转让", "随主债权", "受让人取得")
    oppose_hits = sum(marker in compact for marker in oppose)
    support_hits = sum(marker in compact for marker in support)
    if oppose_hits > support_hits:
        return "oppose"
    if support_hits > oppose_hits:
        return "support"
    return "neutral"


def parse_case_search_markdown(markdown: str, query_id: str = "neutral") -> List[Dict[str, Any]]:
    """把法随 Markdown 卡片解析成稳定字段；缺失字段保持空值，不让模型补写。"""
    text = str(markdown or "")
    matches = list(re.finditer(r"^##\s+(?:\d+\.\s*|精确命中：)(.+?)\s*$", text, re.MULTILINE))
    cases: List[Dict[str, Any]] = []
    for index, match in enumerate(matches):
        title = match.group(1).strip()
        block = text[match.end(): matches[index + 1].start() if index + 1 < len(matches) else len(text)]
        meta = _metadata(block)
        detail = _field(block, "案例详情摘要")
        holding = _field(block, "裁判规则")
        excerpt = _field(block, "命中原文依据")
        link_value = _field(block, "原文链接")
        link_match = re.search(r"\[[^\]]+\]\((https?://[^)]+)\)", link_value)
        case_number = meta.get("案号", "")
        if not case_number:
            number_match = re.search(r"[（(]\d{4}[）)][^\s；;，,。]{2,35}?号", detail + "\n" + block)
            case_number = number_match.group(0) if number_match else ""
        score_text = meta.get("综合分", "0")
        try:
            remote_score = float(score_text)
        except ValueError:
            remote_score = 0.0
        combined = "\n".join((title, detail, excerpt, holding))
        cases.append({
            "title": title,
            "case_number": case_number,
            "court": _infer_court(detail, meta.get("权威类型", "")),
            "judgment_date": "",
            "year": meta.get("年份", ""),
            "source": meta.get("来源", ""),
            "authority_type": meta.get("权威类型", ""),
            "citation_value": meta.get("引用价值", ""),
            "rule_quality": meta.get("规则质量", ""),
            "factual_summary": detail,
            "matched_excerpt": excerpt,
            "holding": holding,
            "source_url": link_match.group(1) if link_match else "",
            "remote_score": remote_score,
            "viewpoint": _infer_viewpoint(combined),
            "retrieved_by": [query_id],
            "raw_markdown": f"## {title}\n{block.strip()}",
        })
    return cases


def _dedupe_key(case: Dict[str, Any]) -> str:
    if case.get("case_number"):
        return "number:" + _compact(case["case_number"]).lower()
    if case.get("source_url"):
        parts = urlsplit(case["source_url"])
        return "url:" + (parts.netloc + parts.path).lower().rstrip("/")
    return "title:" + re.sub(r"[^\w\u4e00-\u9fff]", "", case.get("title", "")).lower()


def deduplicate_cases(cases: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for case in cases:
        key = _dedupe_key(case)
        if key not in merged:
            merged[key] = dict(case)
            continue
        current = merged[key]
        current["retrieved_by"] = sorted(set(current["retrieved_by"] + case["retrieved_by"]))
        if case.get("remote_score", 0) > current.get("remote_score", 0):
            preserved_queries = current["retrieved_by"]
            current.update(case)
            current["retrieved_by"] = preserved_queries
    return list(merged.values())


def _authority_score(case: Dict[str, Any]) -> float:
    rank, _ = case_authority_level(case)
    return (1.0, 0.92, 0.84, 0.76, 0.68, 0.5)[rank]


def _issue_score(case: Dict[str, Any], plan: Dict[str, Any]) -> tuple[float, str, List[str]]:
    text = _compact("\n".join(str(case.get(key, "")) for key in (
        "title", "factual_summary", "matched_excerpt", "holding"
    )))
    groups = plan.get("required_term_groups") or []
    group_hits = [any(_compact(term) in text for term in group) for group in groups]
    matched = [term for term in plan.get("essential_terms", []) if _compact(term) in text]
    if not groups:
        return 0.5, "related", matched
    ratio = sum(group_hits) / len(group_hits)
    if ratio == 1:
        return 1.0, "direct", matched
    if ratio >= 0.5:
        return 0.55 + ratio * 0.2, "related", matched
    return ratio * 0.5, "weak", matched


def rank_cases(cases: List[Dict[str, Any]], plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    constraints = plan.get("search_constraints") or {}
    for case in cases:
        issue_score, issue_match, matched = _issue_score(case, plan)
        case["issue_score"] = round(issue_score, 4)
        case["issue_match"] = issue_match
        case["matched_issue_terms"] = matched
        case["authority_score"] = _authority_score(case)
        constraint_result = constraint_hit(
            str(case.get("court") or ""),
            constraints,
            region_extra=str(case.get("title") or ""),
        )
        case["constraint_match"] = constraint_result["constraint_match"]
        case["constraint_hit"] = constraint_result["constraint_hit"]
        case["constraint_notes"] = constraint_result["notes"]
        retrieval_bonus = min(len(case.get("retrieved_by", [])) * 0.03, 0.09)
        fit = evaluate_case_fit((
            case.get("title"), case.get("factual_summary"), case.get("matched_excerpt"), case.get("holding")
        ), plan.get("fact_fingerprint") or {})
        case.update(fit)
        if (plan.get("fact_fingerprint") or {}).get("kind") != "sequential_guarantee_claims":
            case["match_tier"] = "related" if issue_match != "weak" else "weak"
            case["fit_score"] = issue_score
        constraint_bonus = 0.0
        if case.get("constraint_hit") is True:
            constraint_bonus = 0.18
        elif case.get("constraint_hit") is False:
            constraint_bonus = -0.15
        case["final_score"] = round(
            issue_score * 0.30
            + case["fit_score"] * 0.35
            + float(case.get("remote_score", 0)) * 0.25
            + case["authority_score"] * 0.07
            + retrieval_bonus
            + constraint_bonus,
            4,
        )
    if (plan.get("fact_fingerprint") or {}).get("strict_direction"):
        prepared = sort_cases_by_authority(cases)
        return sorted(prepared, key=lambda case: (
            match_tier_order(case.get("match_tier", "weak")),
            int(case.get("authority_rank", 5)),
            -float(case.get("final_score") or 0),
        ))
    return sort_cases_by_authority(cases, constraints=constraints)


def _is_official_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == suffix or host.endswith("." + suffix) for suffix in _OFFICIAL_HOST_SUFFIXES)


async def verify_case_source(case: Dict[str, Any], timeout: float = 6.0) -> Dict[str, Any]:
    url = str(case.get("source_url") or "")
    verification = {
        "authority_status": "official" if _is_official_url(url) else ("secondary" if url else "missing"),
        "link_status": "missing" if not url else "not_checked",
        "identifier_match": False,
        "holding_match": False,
        "status": "unverified",
        "notes": [],
    }
    if not url:
        verification["notes"].append("结果未提供原文链接")
        return verification
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": "legal-kb-source-verifier/1.0"})
            response.raise_for_status()
        verification["link_status"] = "reachable"
        visible = _compact(BeautifulSoup(response.text[:2_000_000], "lxml").get_text(" "))
        title = _compact(case.get("title", ""))
        number = _compact(case.get("case_number", ""))
        verification["identifier_match"] = bool(
            (number and number in visible) or (title and len(title) >= 6 and title in visible)
        )
        excerpt = _compact(case.get("matched_excerpt", ""))
        probes = [excerpt[:30], excerpt[30:60]] if len(excerpt) >= 30 else [excerpt]
        verification["holding_match"] = bool(excerpt and any(probe and probe in visible for probe in probes))
        if verification["authority_status"] == "official" and verification["identifier_match"] and verification["holding_match"]:
            verification["status"] = "verified"
        elif verification["identifier_match"] or verification["holding_match"]:
            verification["status"] = "partial"
            verification["notes"].append("页面可打开，但案号/案名与裁判依据尚未全部匹配")
        else:
            verification["notes"].append("页面可打开，但正文未匹配案号、案名或裁判依据")
    except (httpx.HTTPError, ValueError) as exc:
        verification["link_status"] = "unreachable"
        verification["notes"].append(f"原文链接暂不可核验：{type(exc).__name__}")
    return verification


def format_structured_case_markdown(cases: List[Dict[str, Any]], coverage: Dict[str, Any]) -> str:
    if not cases:
        return "未检得符合当前争点约束的可用案例。"
    lines = ["【争点感知、多路召回与来源核验结果】", ""]
    for index, case in enumerate(cases, 1):
        verification = case.get("verification") or {}
        constraint_label = {
            True: "筛选条件：命中",
            False: "筛选条件：未命中（" + "、".join(case.get("constraint_notes") or ["不符合指定层级/地域"]) + "）",
        }.get(case.get("constraint_hit"), "")
        lines.extend([
            f"## {index}. {case['title']}", "",
            f"权威顺序：{case.get('authority_order_label') or case_authority_level(case)[1]}  |  观点：{case['viewpoint']}  |  争点匹配：{case['issue_match']}  |  核验状态：{verification.get('status', 'unverified')}",
            f"类案层级：{case.get('match_tier', 'related')}  |  事实方向：{case.get('detected_direction', 'unknown')}  |  方向匹配：{case.get('direction_match', 'not_applicable')}",
            f"来源：{case.get('source') or '结果未提供'}  |  权威类型：{case.get('authority_type') or '结果未提供'}  |  案号：{case.get('case_number') or '结果未提供'}  |  法院：{case.get('court') or '结果未提供'}  |  年份：{case.get('year') or '结果未提供'}",
        ])
        if constraint_label:
            lines.append(constraint_label)
        lines.extend([
            "", "命中原文依据：", case.get("matched_excerpt") or "结果未提供", "",
            "裁判规则：", case.get("holding") or "结果未提供", "",
            f"原文链接：{case.get('source_url') or '结果未提供'}", "",
        ])
    missing = coverage.get("missing_viewpoints") or []
    if missing:
        lines.append("覆盖提示：未检得可识别的" + "、".join(missing) + "观点案例，不以一般性案例填充。")
    return "\n".join(lines).strip()


async def search_cases_structured(
    query: str,
    top_k: int = 6,
    *,
    verify_sources: bool = True,
) -> Dict[str, Any]:
    """执行三路召回，返回兼容 Markdown 和结构化案例。"""
    plan = build_case_query_plan(query)
    per_query_k = max(2, min(int(top_k or 6), 6))
    results = await asyncio.gather(
        *(search_authoritative_cases(item["query"], per_query_k) for item in plan["queries"]),
        return_exceptions=True,
    )
    parsed: List[Dict[str, Any]] = []
    errors = []
    retrieval_runs = []
    for item, result in zip(plan["queries"], results):
        if isinstance(result, Exception):
            errors.append({"query_id": item["id"], "message": str(result)})
            continue
        query_cases = parse_case_search_markdown(result, item["id"])
        retrieval_runs.append({
            "source": "aluris", "query_id": item["id"],
            "query": item["query"], "result_count": len(query_cases)
        })
        parsed.extend(query_cases)
    if yuandian_enabled():
        # 元典可能按积分计费，只有用户同时配置 Key 和显式开关后才执行；每路最多10条。
        yuandian_results = await asyncio.gather(
            *(search_yuandian_cases(item["query"], per_query_k, item["id"]) for item in plan["queries"]),
            return_exceptions=True,
        )
        for item, result in zip(plan["queries"], yuandian_results):
            if isinstance(result, Exception):
                errors.append({"query_id": item["id"], "source": "yuandian", "message": str(result)})
                continue
            retrieval_runs.append({
                "source": "yuandian", "query_id": item["id"],
                "query": item["query"], "result_count": len(result),
            })
            for case in result:
                combined = "\n".join((case.get("title", ""), case.get("factual_summary", "")))
                case["viewpoint"] = _infer_viewpoint(combined)
            parsed.extend(result)
    if not parsed and errors:
        raise AlurisMCPError(errors[0]["message"] or "法随案例库检索失败")

    ranked = rank_cases(deduplicate_cases(parsed), plan)
    # 弱相关结果不进入最终卡片；若全弱则返回空数组，避免用一般案例填充争点。
    allowed_matches = {"direct"} if plan.get("strict_issue_match") else {"direct", "related"}
    eligible = [case for case in ranked if case["issue_match"] in allowed_matches]
    constraints = plan.get("search_constraints") or {}
    limit = max(1, min(int(top_k or 6), 10))
    if constraints.get("court_levels") or constraints.get("strict_regions"):
        # 用户指定法院层级/地域时，命中筛选条件的案例整体优先，未命中者置后并保留标注，
        # 保证既不错失同型案例，也不让层级不符的案例静默充当直接依据。
        hit_cases = [case for case in eligible if case.get("constraint_hit")]
        miss_cases = [case for case in eligible if not case.get("constraint_hit")]
        selected = (hit_cases + miss_cases)[:limit]
    else:
        selected = eligible[:limit]
    if verify_sources and selected:
        verified = await asyncio.gather(*(verify_case_source(case) for case in selected))
        for case, verification in zip(selected, verified):
            case["verification"] = verification
    else:
        for case in selected:
            case["verification"] = {
                "authority_status": "official" if _is_official_url(case.get("source_url", "")) else "unknown",
                "link_status": "not_checked",
                "identifier_match": False,
                "holding_match": False,
                "status": "unverified",
                "notes": ["本次请求未执行链接核验"],
            }

    counts = {"support": 0, "oppose": 0, "neutral": 0}
    for case in selected:
        counts[case["viewpoint"]] = counts.get(case["viewpoint"], 0) + 1
    coverage = {
        "counts": counts,
        "missing_viewpoints": [label for key, label in (("support", "支持"), ("oppose", "反对")) if counts.get(key, 0) == 0],
        "candidate_count": len(ranked),
        "selected_count": len(selected),
        "constraint_eligible": bool(constraints.get("court_levels") or constraints.get("strict_regions")),
        "constraint_hit_count": sum(bool(case.get("constraint_hit")) for case in selected),
    }
    metrics = {
        "direct_issue_rate": round(
            sum(case["issue_match"] == "direct" for case in selected) / len(selected), 4
        ) if selected else 0.0,
        "official_source_rate": round(
            sum((case.get("verification") or {}).get("authority_status") == "official" for case in selected) / len(selected), 4
        ) if selected else 0.0,
        "verified_source_rate": round(
            sum((case.get("verification") or {}).get("status") == "verified" for case in selected) / len(selected), 4
        ) if selected else 0.0,
        "opposing_viewpoint_covered": bool(counts.get("support") and counts.get("oppose")),
        "constraint_hit_rate": round(
            sum(bool(case.get("constraint_hit")) for case in selected) / len(selected), 4
        ) if selected else 0.0,
    }
    for case in selected:
        case.pop("raw_markdown", None)
    return {
        "query_plan": plan,
        "cases": selected,
        "coverage": coverage,
        "metrics": metrics,
        "errors": errors,
        "result": format_structured_case_markdown(selected, coverage),
        "retrieval_runs": retrieval_runs,
    }
