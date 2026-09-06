"""类案检索的事实指纹、方向识别与相关度评分。

本模块只做确定性的查询规划和候选重排，不生成或补写案例事实。
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


_GUARANTOR = ("连带责任保证人", "连带保证人", "保证人", "担保人", "保证责任")
_DEBTOR = ("主债务人", "债务人", "主债务", "主合同债务")
_SEQUENCE_MARKERS = ("先", "后", "此前", "此后", "前案", "后案", "另案", "另行", "再", "又", "仍可", "已经", "已")


def _compact(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _first_position(text: str, aliases: Sequence[str]) -> int:
    positions = [text.find(alias) for alias in aliases if text.find(alias) >= 0]
    return min(positions) if positions else -1


def _has_directional_context(text: str) -> bool:
    return any(marker in text for marker in _SEQUENCE_MARKERS)


def _sequence_hit(text: str, first: Sequence[str], second: Sequence[str]) -> bool:
    """识别同一事实段中的先后主张，避免把法条中的“可以A也可以B”误判为时序。"""
    aliases1 = "|".join(re.escape(item) for item in first)
    aliases2 = "|".join(re.escape(item) for item in second)
    patterns = (
        rf"(?:先|此前|前案|已|已经|曾|另案)[^。；]{{0,180}}(?:{aliases1})[^。；]{{0,120}}(?:后|此后|现|又|再|仍可|另行)[^。；]{{0,180}}(?:{aliases2})",
        rf"(?:{aliases1})[^。；]{{0,100}}(?:后|此后|又|再|仍可|另行)[^。；]{{0,180}}(?:{aliases2})",
        rf"(?:起诉|主张|请求)[^。；]{{0,100}}(?:{aliases1})[^。；]{{0,100}}(?:另行|再|又|仍可)[^。；]{{0,140}}(?:{aliases2})",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def infer_claim_direction(text: str) -> str:
    """返回 guarantor_to_debtor、debtor_to_guarantor 或 unknown。"""
    value = _compact(text)
    if not value or not _has_directional_context(value):
        return "unknown"
    # 裁判文书摘要经常同时包含一审观点、当事人主张和二审纠正意见。若存在
    # “本院认为”，优先使用最后一段终审说理，避免把被纠正的下级法院观点当结论。
    holding = value.rsplit("本院认为", 1)[-1] if "本院认为" in value else value
    guarantor_aliases = "|".join(re.escape(item) for item in _GUARANTOR)
    debtor_aliases = "|".join(re.escape(item) for item in _DEBTOR)
    explicit_guarantee_first = re.search(
        rf"(?:向|起诉|请求)[^。；]{{0,100}}(?:{guarantor_aliases})[^。；]{{0,80}}"
        rf"(?:主张|承担)[^。；]{{0,40}}后[^。；]{{0,100}}(?:另行|仍可|再)[^。；]{{0,80}}(?:{debtor_aliases})",
        holding,
    )
    explicit_debtor_first = re.search(
        rf"(?:向|起诉|请求)[^。；]{{0,100}}(?:{debtor_aliases})[^。；]{{0,80}}"
        rf"(?:主张|履行)[^。；]{{0,40}}后[^。；]{{0,100}}(?:另行|仍可|再)[^。；]{{0,80}}(?:{guarantor_aliases})",
        holding,
    )
    if explicit_guarantee_first and not explicit_debtor_first:
        return "guarantor_to_debtor"
    if explicit_debtor_first and not explicit_guarantee_first:
        return "debtor_to_guarantor"
    guarantee_first = _sequence_hit(holding, _GUARANTOR, _DEBTOR)
    debtor_first = _sequence_hit(holding, _DEBTOR, _GUARANTOR)
    if not guarantee_first and not debtor_first and holding != value:
        guarantee_first = _sequence_hit(value, _GUARANTOR, _DEBTOR)
        debtor_first = _sequence_hit(value, _DEBTOR, _GUARANTOR)
    if guarantee_first and not debtor_first:
        return "guarantor_to_debtor"
    if debtor_first and not guarantee_first:
        return "debtor_to_guarantor"
    return "unknown"


_COURT_LEVEL_ALIASES = {
    "supreme": ("最高人民法院", "最高法"),
    "high": ("高级人民法院", "高级法院", "高院"),
    "intermediate": ("中级人民法院", "中级法院", "中院"),
    "basic": ("基层人民法院", "基层法院"),
}

_COURT_LEVEL_LABELS = {
    "supreme": "最高人民法院",
    "high": "高级人民法院",
    "intermediate": "中级人民法院",
    "basic": "基层人民法院",
}

# 省市简称，用于法院地域匹配；直辖市同时具有省级与市级身份。
_REGION_NAMES = (
    "广东", "广西", "海南", "福建", "浙江", "江苏", "山东", "河北", "湖北", "湖南",
    "河南", "安徽", "江西", "四川", "贵州", "云南", "陕西", "甘肃", "青海", "宁夏",
    "新疆", "西藏", "内蒙古", "辽宁", "吉林", "黑龙江", "山西",
    "北京", "上海", "天津", "重庆",
)

_REGION_OPEN_MARKERS = ("其他省", "其他省份", "各省", "全国", "不限", "其他地区")

_PROCEDURE_ALIASES = (
    ("first", ("一审", "第一审")),
    ("second", ("二审", "第二审", "上诉")),
    ("retrial", ("再审", "审判监督")),
)


def detect_court_level(text: str) -> str:
    """从法院/层级文本识别法院层级；返回 supreme/high/intermediate/basic/空。"""
    value = str(text or "")
    for level in ("supreme", "high", "intermediate", "basic"):
        if any(alias in value for alias in _COURT_LEVEL_ALIASES[level]):
            return level
    # 区/县/县级市人民法院通常为基层法院，但字段未必带“基层”字样。
    if re.search(r"(?:区|县)人民法院", value) or re.search(r"市人民法院(?!中级)", value):
        return "basic"
    return ""


def _region_hits(text: str) -> List[str]:
    value = str(text or "")
    hits = []
    for region in _REGION_NAMES:
        if region not in value:
            continue
        if region in ("广西", "新疆", "西藏", "内蒙古", "宁夏") and region + "自治" not in value:
            continue
        hits.append(region)
    return hits


def build_search_constraints(query: str) -> Dict[str, Any]:
    """从用户问题中解析法院层级、地域、程序等硬筛选条件。

    筛选条件与检索关键词分开处理：层级/地域词不进入 AND 检索式，而是作为
    召回结果的过滤与排序依据，避免噪声词挤占争点词位置。
    """
    text = _compact(query)
    levels = [level for level in _COURT_LEVEL_ALIASES if any(alias in text for alias in _COURT_LEVEL_ALIASES[level])]
    regions = _region_hits(text)
    if any(marker in text for marker in _REGION_OPEN_MARKERS):
        # “或其他省”“各省”等表述取消地域限制，只保留层级约束。
        regions_open = True
        strict_regions: List[str] = []
    else:
        regions_open = False
        strict_regions = regions
    procedures = [key for key, aliases in _PROCEDURE_ALIASES if any(alias in text for alias in aliases)]
    # 层级/地域/程序词清单，用于从检索关键词中剥离。
    constraint_words = []
    for level in levels:
        constraint_words.extend(_COURT_LEVEL_ALIASES[level])
    for region in _REGION_NAMES:
        if region in text:
            constraint_words.append(region)
    for _, aliases in _PROCEDURE_ALIASES:
        for alias in aliases:
            if alias in text:
                constraint_words.append(alias)
    descriptions = []
    if levels:
        descriptions.append("、".join(_COURT_LEVEL_LABELS[level] for level in levels))
    if strict_regions:
        descriptions.append("地域：" + "、".join(strict_regions))
    elif regions and regions_open:
        descriptions.append("地域不限（" + "、".join(regions) + "等）")
    if procedures:
        labels = {"first": "一审", "second": "二审", "retrial": "再审"}
        descriptions.append("程序：" + "、".join(labels[item] for item in procedures))
    return {
        "court_levels": levels,
        "regions": regions,
        "strict_regions": strict_regions,
        "procedures": procedures,
        "constraint_words": sorted(set(constraint_words), key=len, reverse=True),
        "present": bool(levels or regions or procedures),
        "description": "；".join(descriptions) if descriptions else "未识别到明确筛选条件",
    }


def constraint_hit(
    court_text: str,
    constraints: Optional[Dict[str, Any]] = None,
    *,
    procedure_text: str = "",
    region_extra: str = "",
) -> Dict[str, Any]:
    """判断案例是否命中用户筛选条件；返回命中状态、得分调整与说明。"""
    constraints = constraints or {}
    level_text = f"{court_text} {region_extra}".strip()
    detected_level = detect_court_level(level_text)
    notes: List[str] = []
    if constraints.get("court_levels"):
        if detected_level in constraints["court_levels"]:
            level_hit = True
        elif detected_level:
            level_hit = False
            notes.append(f"法院层级为{_COURT_LEVEL_LABELS.get(detected_level, detected_level)}，不符合筛选要求")
        else:
            level_hit = False
            notes.append("无法识别法院层级，不满足层级筛选")
    else:
        level_hit = None
    if constraints.get("strict_regions"):
        region_value = f"{court_text} {region_extra}"
        region_hit = any(region in region_value for region in constraints["strict_regions"])
        if not region_hit:
            notes.append("法院地域不在指定范围内")
    else:
        region_hit = None
    procedure_hit = None
    if constraints.get("procedures"):
        procedure_value = str(procedure_text or "")
        procedure_hit = any(
            alias in procedure_value
            for key in constraints["procedures"]
            for alias in dict(_PROCEDURE_ALIASES)[key]
        )
        if not procedure_hit:
            notes.append("审判程序不在指定范围内")
    checks = [value for value in (level_hit, region_hit, procedure_hit) if value is not None]
    if not checks:
        return {"constraint_match": "not_applicable", "constraint_hit": True, "notes": []}
    matched = all(checks)
    return {
        "constraint_match": "met" if matched else "violated",
        "constraint_hit": matched,
        "constraint_level": detected_level,
        "notes": notes,
    }


def build_fact_fingerprint(query: str) -> Dict[str, Any]:
    """从用户问题提取可用于硬约束和查询扩展的类案事实指纹。"""
    text = _compact(query)
    direction = infer_claim_direction(text)
    if direction == "unknown" and _has_directional_context(text):
        guarantor_pos = _first_position(text, _GUARANTOR)
        debtor_pos = _first_position(text, _DEBTOR)
        if guarantor_pos >= 0 and debtor_pos >= 0:
            direction = "guarantor_to_debtor" if guarantor_pos < debtor_pos else "debtor_to_guarantor"

    guarantee_issue = (
        any(alias in text for alias in _GUARANTOR)
        and any(alias in text for alias in _DEBTOR)
        and any(marker in text for marker in ("重复起诉", "一事不再理", "分别起诉", "另行起诉", "可分之诉", "重复受偿"))
    )
    if not guarantee_issue:
        return {
            "kind": "generic",
            "direction": "unknown",
            "strict_direction": False,
            "required_groups": [],
            "query_routes": [],
            "semantic_queries": [],
        }

    required_groups = [
        list(_GUARANTOR[:3]),
        list(_DEBTOR[:2]),
        ["重复起诉", "一事不再理", "重复诉讼", "重复受偿", "重复获益"],
    ]
    if direction == "guarantor_to_debtor":
        routes = [
            "先诉保证人 后诉主债务人 重复起诉",
            "保证责任 后 仍可 主债务人",
            "主债务人 连带保证人 责任各自独立",
            "可分之诉 分别起诉",
            "重复受偿 判项 执行",
        ]
        semantic = [
            "债权人先向连带责任保证人主张保证责任，后又另行起诉主债务人履行主合同债务，是否构成重复起诉",
            "主债务人与连带保证人责任各自独立，基于主合同和保证合同的诉讼属于可分之诉，重复受偿由判项或执行处理",
        ]
    else:
        routes = [
            "先诉主债务人 后诉保证人 重复起诉",
            "主债务人 后 仍可 保证责任",
            "借贷关系 保证关系 当事人 诉讼标的 不同",
            "可分之诉 分别起诉",
            "重复受偿 未清偿部分",
        ]
        semantic = [
            "债权人先起诉主债务人，后又另行起诉连带责任保证人承担保证责任，是否构成重复起诉",
            "主债务人与连带保证人的诉讼是否属于不同法律关系和可分之诉，重复受偿如何处理",
        ]
    return {
        "kind": "sequential_guarantee_claims",
        "direction": direction,
        "strict_direction": direction != "unknown",
        "first_defendant": "连带责任保证人" if direction == "guarantor_to_debtor" else "主债务人",
        "later_defendant": "主债务人" if direction == "guarantor_to_debtor" else "连带责任保证人",
        "required_groups": required_groups,
        "query_routes": routes,
        "semantic_queries": semantic,
    }


def evaluate_case_fit(texts: Iterable[Any], fingerprint: Dict[str, Any]) -> Dict[str, Any]:
    """对候选案例进行可解释的事实方向与争点匹配评分。"""
    text = _compact("\n".join(str(item or "") for item in texts))
    groups: List[List[str]] = fingerprint.get("required_groups") or []
    group_hits = [any(_compact(term) in text for term in group) for group in groups]
    issue_ratio = sum(group_hits) / len(group_hits) if group_hits else 0.0
    detected = infer_claim_direction(text)
    expected = fingerprint.get("direction") or "unknown"
    if not fingerprint.get("strict_direction"):
        direction_match = "not_applicable"
        direction_score = 0.0
    elif detected == expected:
        direction_match = "aligned"
        direction_score = 0.42
    elif detected != "unknown":
        direction_match = "reversed"
        direction_score = -0.42
    else:
        direction_match = "unknown"
        direction_score = -0.08

    rule_hits = sum(marker in text for marker in (
        "责任各自独立", "不同法律关系", "可分之诉", "分别起诉",
        "不构成重复起诉", "不属于重复起诉", "判项", "执行问题",
    ))
    score = max(0.0, min(1.0, issue_ratio * 0.48 + direction_score + min(rule_hits, 3) * 0.06 + 0.18))
    if direction_match == "aligned" and issue_ratio >= 2 / 3 and "代位权" in text:
        tier = "analogical"
        score = max(0.0, score - 0.08)
    elif direction_match == "aligned" and issue_ratio >= 2 / 3:
        tier = "highly_similar"
    elif direction_match == "reversed":
        tier = "reverse_direction"
    elif issue_ratio >= 2 / 3:
        tier = "related"
    else:
        tier = "weak"
    return {
        "fit_score": round(score, 4),
        "match_tier": tier,
        "detected_direction": detected,
        "direction_match": direction_match,
        "required_group_hits": group_hits,
    }


def match_tier_order(value: str) -> int:
    return {
        "highly_similar": 0, "analogical": 1, "related": 2,
        "reverse_direction": 3, "weak": 4,
    }.get(value, 4)
