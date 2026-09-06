"""裁判案例统一权威层级识别与排序。"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple


AUTHORITY_ORDER = (
    "指导案例",
    "参考案例",
    "普通最高院案例",
    "广东高院案例",
    "其他高院案例",
    "其他法院案例",
)


def case_authority_level(case: Dict[str, Any]) -> Tuple[int, str]:
    """按产品约定的六级顺序识别案例；数字越小，排列越靠前。"""
    value = " ".join(str(case.get(key) or "") for key in (
        "authority_type", "source", "court", "case_number", "title",
        "citation_value", "database", "db", "cj",
    ))
    if "指导案例" in value or "指导性案例" in value:
        return 0, AUTHORITY_ORDER[0]
    if "参考案例" in value or "典型案例" in value or "公报案例" in value:
        return 1, AUTHORITY_ORDER[1]
    if "最高人民法院" in value or "最高法" in value:
        return 2, AUTHORITY_ORDER[2]
    if "广东省高级人民法院" in value or "广东高院" in value:
        return 3, AUTHORITY_ORDER[3]
    if "高级人民法院" in value or "高院" in value:
        return 4, AUTHORITY_ORDER[4]
    return 5, AUTHORITY_ORDER[5]


def sort_cases_by_authority(
    cases: Iterable[Dict[str, Any]],
    *,
    score_key: str = "final_score",
    constraints: Any = None,
) -> List[Dict[str, Any]]:
    """先按六级权威顺序，再按同层级相关性分数降序排列。

    当用户指定了法院层级/地域等筛选条件（constraints）时，改为“约束命中优先”：
    满足筛选条件的案例整体排在前面，命中组内部再按权威层级与分数排序，
    避免用户只要中级法院案例时最高院/高院案例抢占前列。
    """
    prepared = []
    for original in cases:
        case = original
        rank, label = case_authority_level(case)
        case["authority_rank"] = rank
        case["authority_order_label"] = label
        prepared.append(case)

    def key(case: Dict[str, Any]):
        try:
            score = float(case.get(score_key) or case.get("remote_score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        if constraints:
            constraint_hit = bool(case.get("constraint_hit", True))
            return int(not constraint_hit), int(case.get("authority_rank", 5)), -score
        return int(case.get("authority_rank", 5)), -score

    return sorted(prepared, key=key)
