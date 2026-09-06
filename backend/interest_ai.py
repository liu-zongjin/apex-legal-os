"""AI-assisted extraction for the interest calculator."""

from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any, Dict, List


MAX_DESCRIPTION_LENGTH = 20_000


def extraction_messages(description: str, today: dt.date | None = None) -> List[Dict[str, str]]:
    current_date = (today or dt.date.today()).isoformat()
    schema = {
        "common_principal": 1000000,
        "segments": [{
            "principal": 1000000,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "rate_mode": "lpr",
            "multiplier": 1,
            "spread_bp": 0,
            "fixed_rate": None,
        }],
        "warnings": [],
    }
    return [
        {
            "role": "system",
            "content": (
                "你是利息计算参数抽取器。只提取用户文字明确表达的事实，不补造金额、日期或利率。"
                "金额统一换算为元；日期统一为 YYYY-MM-DD；‘至今/截至今日’按当前日期处理。"
                "日/月利率应换算成年利率（日利率×360，月利率×12）。"
                "LPR、贷款市场报价利率、同期贷款基准利率均使用 rate_mode=lpr，并提取倍数及加减BP；"
                "固定年利率使用 rate_mode=fixed。每个独立计息区间输出一个 segment。"
                "不完整字段使用 null，并在 warnings 中用中文说明。只返回一个 JSON 对象，不要 Markdown。\n"
                f"当前日期：{current_date}\nJSON结构示例：{json.dumps(schema, ensure_ascii=False)}"
            ),
        },
        {"role": "user", "content": description},
    ]


def parse_extraction_content(content: str) -> Dict[str, Any]:
    raw = str(content or "").strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", raw, flags=re.I | re.S)
    if fenced:
        raw = fenced.group(1).strip()
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("AI 未返回可识别的 JSON 参数") from exc
    if not isinstance(data, dict):
        raise ValueError("AI 返回的参数格式不正确")
    return normalize_extraction(data)


def normalize_extraction(data: Dict[str, Any]) -> Dict[str, Any]:
    warnings = [str(item).strip() for item in data.get("warnings", []) if str(item).strip()] if isinstance(data.get("warnings"), list) else []
    common_principal = _positive_number(data.get("common_principal"))
    raw_segments = data.get("segments")
    if not isinstance(raw_segments, list):
        raw_segments = []
    segments = []
    for index, item in enumerate(raw_segments[:50], start=1):
        if not isinstance(item, dict):
            continue
        start_date = _date(item.get("start_date"))
        end_date = _date(item.get("end_date"))
        if not start_date or not end_date:
            warnings.append(f"第{index}段缺少完整起止日期，未自动填充")
            continue
        if start_date > end_date:
            warnings.append(f"第{index}段起算日晚于止算日，未自动填充")
            continue
        mode = str(item.get("rate_mode") or "").lower()
        fixed_rate = _positive_number(item.get("fixed_rate"))
        if mode not in {"lpr", "fixed"}:
            mode = "fixed" if fixed_rate else "lpr"
            warnings.append(f"第{index}段未明确利率方式，已按{'固定利率' if fixed_rate else 'LPR'}填充")
        segment = {
            "principal": _positive_number(item.get("principal")),
            "startDate": start_date,
            "endDate": end_date,
            "mode": mode,
            "multiplier": _number(item.get("multiplier"), 1.0),
            "spreadBp": _number(item.get("spread_bp"), 0.0),
            "fixedRate": fixed_rate or 4.35,
        }
        if mode == "fixed" and not fixed_rate:
            warnings.append(f"第{index}段未识别到固定年利率，已保留默认值供手动调整")
        segments.append(segment)
    return {
        "commonPrincipal": common_principal,
        "segments": segments,
        "warnings": list(dict.fromkeys(warnings)),
    }


def _number(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if -1_000_000 <= number <= 1_000_000 else default


def _positive_number(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(number, 6) if 0 < number <= 1_000_000_000_000_000 else 0.0


def _date(value: Any) -> str:
    text = str(value or "").strip()
    try:
        return dt.date.fromisoformat(text).isoformat()
    except ValueError:
        return ""
