"""元典普通案例/权威案例语义检索的可选适配器。

只有同时显式启用并提供 API Key 时才调用，避免在用户不知情时消耗积分。
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List

import httpx

from .ai_config import YUANDIAN_API_KEY, YUANDIAN_CASES_ENABLED, YUANDIAN_CASE_SEARCH_URL


class YuandianCaseError(RuntimeError):
    pass


def is_enabled() -> bool:
    return bool(YUANDIAN_CASES_ENABLED and YUANDIAN_API_KEY)


def source_status() -> Dict[str, Any]:
    return {
        "name": "元典开放平台案例库",
        "configured": bool(YUANDIAN_API_KEY),
        "enabled": is_enabled(),
        "requires_api_key": True,
        "usage_may_consume_credits": True,
    }


def _date(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) != 8:
        return ""
    try:
        return datetime.datetime.strptime(digits, "%Y%m%d").date().isoformat()
    except ValueError:
        return ""


def parse_yuandian_cases(payload: Dict[str, Any], query_id: str) -> List[Dict[str, Any]]:
    rows = ((payload.get("extra") or {}).get("wenshu") or [])
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        content = str(row.get("content") or "").strip()
        authority = str(row.get("authority") or "").strip()
        database = str(row.get("db") or "").strip()
        score = row.get("score") or 0
        try:
            remote_score = max(0.0, min(float(score), 1.0))
        except (TypeError, ValueError):
            remote_score = 0.0
        year = str(row.get("jand") or "")
        result.append({
            "title": str(row.get("title") or "").strip(),
            "case_number": str(row.get("ah") or "").strip(),
            "court": str(row.get("jbdw") or "").strip(),
            "judgment_date": _date(row.get("jaDate")),
            "year": year,
            "source": "元典开放平台",
            "authority_type": authority or database or "普通裁判案例",
            "citation_value": "候选案例，须核验原文",
            "rule_quality": "待核验",
            "factual_summary": content,
            "matched_excerpt": content,
            # 语义接口文档明确 content 是整理内容而非逐字原文，不能直接标成裁判规则。
            "holding": "",
            "source_url": "",
            "remote_score": remote_score,
            "viewpoint": "neutral",
            "retrieved_by": [query_id],
            "provider_case_id": str(row.get("scid") or ""),
            "provider_case_type": row.get("type"),
        })
    return [case for case in result if case["title"] or case["case_number"]]


async def search_yuandian_cases(query: str, top_k: int, query_id: str) -> List[Dict[str, Any]]:
    if not is_enabled():
        return []
    headers = {
        "X-API-Key": YUANDIAN_API_KEY,
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
    }
    body = {
        "query": str(query or "")[:1000],
        "rewrite_flag": False,
        "wenshu_filter": {"dianxing": False},
        "return_num": max(1, min(int(top_k or 6), 10)),
    }
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.post(YUANDIAN_CASE_SEARCH_URL, headers=headers, json=body)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise YuandianCaseError("元典案例检索暂时不可用") from exc
    if int(payload.get("code") or 0) not in {200, 201}:
        raise YuandianCaseError(str(payload.get("msg") or "元典案例检索失败"))
    return parse_yuandian_cases(payload, query_id)
