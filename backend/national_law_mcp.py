"""国家法律法规数据库访问适配器。

集中封装 flk.npc.gov.cn 当前公开页面所使用的 JSON 接口。上层只依赖本模块
返回的稳定字段，避免国家库前端接口调整时影响知识库其他功能。
"""

from __future__ import annotations

import asyncio
import html
import os
import re
import time
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlencode

import httpx


NPC_LAW_DB_URL = os.environ.get("NPC_LAW_DB_URL", "https://flk.npc.gov.cn").rstrip("/")

STATUS_LABELS = {
    1: "已废止",
    2: "已修改",
    3: "有效",
    4: "尚未生效",
}
DEFAULT_STATUS_CODES = (3, 4)
_REQUEST_LOCK = asyncio.Lock()
_LAST_REQUEST_AT = 0.0
_MIN_REQUEST_INTERVAL = max(0.0, float(os.environ.get("NPC_LAW_DB_MIN_INTERVAL", "0.25")))
_RETRY_DELAYS = (0.0, 0.6, 1.8)


class NationalLawError(RuntimeError):
    pass


def _clean_highlight(value: Any) -> str:
    text = re.sub(r"<[^>]+>", "", str(value or ""))
    return html.unescape(text).replace("\u3000", " ").strip()


def normalize_title(value: Any) -> str:
    text = _clean_highlight(value)
    text = re.sub(r"[《》〈〉\s]", "", text)
    text = re.sub(r"[（(](?:失效|废止|已修改|\d{4}年修(?:正|订)(?:文本)?)[）)]$", "", text)
    return text.strip()


def detail_url(bbbs: str) -> str:
    return f"{NPC_LAW_DB_URL}/detail?bbbs={bbbs}"


def _status_codes(values: Optional[Iterable[int]]) -> List[int]:
    raw = list(values or DEFAULT_STATUS_CODES)
    result = []
    for value in raw:
        try:
            code = int(value)
        except (TypeError, ValueError):
            continue
        if code in STATUS_LABELS and code not in result:
            result.append(code)
    return result or list(DEFAULT_STATUS_CODES)


def _headers() -> Dict[str, str]:
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": NPC_LAW_DB_URL,
        "Referer": NPC_LAW_DB_URL + "/",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        ),
    }


async def _request_json(
    method: str,
    path: str,
    *,
    json_body: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: float = 20.0,
) -> Dict[str, Any]:
    global _LAST_REQUEST_AT
    last_error: Optional[NationalLawError] = None
    for attempt, retry_delay in enumerate(_RETRY_DELAYS):
        if retry_delay:
            await asyncio.sleep(retry_delay)
        try:
            # 国家库在短时间并发访问详情、下载地址时偶尔返回 HTML；串行限速可显著
            # 降低该概率，也避免批量收录影响其他知识库功能。
            async with _REQUEST_LOCK:
                remaining = _MIN_REQUEST_INTERVAL - (time.monotonic() - _LAST_REQUEST_AT)
                if remaining > 0:
                    await asyncio.sleep(remaining)
                async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                    response = await client.request(
                        method,
                        NPC_LAW_DB_URL + path,
                        json=json_body,
                        params=params,
                        headers=_headers(),
                    )
                _LAST_REQUEST_AT = time.monotonic()
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("response is not an object")
            if int(data.get("code") or 0) != 200:
                raise NationalLawError(str(data.get("msg") or "国家法律法规数据库返回异常"))
            return data
        except httpx.TimeoutException as exc:
            last_error = NationalLawError("国家法律法规数据库连接超时，请稍后重试")
            last_error.__cause__ = exc
        except httpx.HTTPStatusError as exc:
            last_error = NationalLawError(
                f"国家法律法规数据库连接失败（HTTP {exc.response.status_code}），请稍后重试"
            )
            last_error.__cause__ = exc
        except (httpx.RequestError, ValueError) as exc:
            last_error = NationalLawError("国家法律法规数据库暂时未返回有效数据，请稍后重试")
            last_error.__cause__ = exc
        except NationalLawError as exc:
            last_error = exc
        if attempt == len(_RETRY_DELAYS) - 1:
            break
    raise last_error or NationalLawError("国家法律法规数据库暂时不可用，请稍后重试")


def _law_row(row: Dict[str, Any]) -> Dict[str, Any]:
    code = row.get("sxx")
    try:
        code = int(code) if code is not None else None
    except (TypeError, ValueError):
        code = None
    bbbs = str(row.get("bbbs") or "").strip()
    return {
        "bbbs": bbbs,
        "title": _clean_highlight(row.get("title")),
        "normalized_title": normalize_title(row.get("title")),
        "status_code": code,
        "status_label": STATUS_LABELS.get(code, "未知"),
        "category": str(row.get("flxz") or "").strip(),
        "issuer": str(row.get("zdjgName") or "").strip(),
        "published_at": str(row.get("gbrq") or "").strip(),
        "effective_at": str(row.get("sxrq") or "").strip(),
        "score": float(row.get("score") or 0),
        "source_url": detail_url(bbbs) if bbbs else NPC_LAW_DB_URL,
    }


async def search_national_laws(
    query: str,
    *,
    search_scope: str = "title",
    exact: bool = False,
    statuses: Optional[Iterable[int]] = None,
    limit: int = 10,
) -> Dict[str, Any]:
    safe_query = str(query or "").strip()[:200]
    if not safe_query:
        raise NationalLawError("检索内容不能为空")
    safe_limit = max(1, min(int(limit or 10), 30))
    payload = {
        "searchRange": 2 if search_scope == "fulltext" else 1,
        "sxrq": [],
        "gbrq": [],
        "sxx": _status_codes(statuses),
        "searchType": 1 if exact else 2,
        "xgzlSearch": False,
        "searchContent": safe_query,
        "pageNum": 1,
        "pageSize": safe_limit,
    }
    data = await _request_json("POST", "/law-search/search/list", json_body=payload)
    rows = [_law_row(row) for row in (data.get("rows") or []) if row.get("bbbs")]
    # 国家库的模糊排序偶尔会把弱相关项排在前面；标题完全一致时始终前置。
    normalized_query = normalize_title(safe_query)
    rows.sort(
        key=lambda row: (
            0 if row["normalized_title"] == normalized_query else 1,
            0 if row["status_code"] == 3 else 1,
            -row["score"],
        )
    )
    return {"query": safe_query, "total": int(data.get("total") or 0), "results": rows[:safe_limit]}


async def get_national_law_hits(
    bbbs: str,
    query: str,
    *,
    exact: bool = True,
) -> List[str]:
    safe_bbbs = str(bbbs or "").strip()
    safe_query = str(query or "").strip()[:200]
    if not safe_bbbs or not safe_query:
        raise NationalLawError("法规标识和检索内容不能为空")
    data = await _request_json(
        "POST",
        "/law-search/search/hitDisplay",
        json_body={
            "bbbs": safe_bbbs,
            "searchContent": safe_query,
            "searchRange": 2,
            "searchType": 1 if exact else 2,
        },
    )
    payload = data.get("data") or {}
    return [
        _clean_highlight(item)
        for item in (payload.get("contentHitDisplay") or [])
        if _clean_highlight(item)
    ]


async def get_national_law_detail(bbbs: str) -> Dict[str, Any]:
    safe_bbbs = str(bbbs or "").strip()
    if not safe_bbbs:
        raise NationalLawError("法规标识不能为空")
    data = await _request_json(
        "GET", "/law-search/search/flfgDetails", params={"bbbs": safe_bbbs}
    )
    raw = data.get("data") or {}
    row = _law_row({**raw, "bbbs": safe_bbbs})
    files = raw.get("ossFile") or {}
    row.update(
        {
            "toc": raw.get("content") or {},
            "word_path": str(files.get("ossWordPath") or ""),
            "pdf_path": str(files.get("ossPdfPath") or ""),
            "related_materials": raw.get("xgzl") or [],
            "history": raw.get("lsyg"),
        }
    )
    return row


async def get_national_law_download_url(bbbs: str, fmt: str = "docx") -> str:
    safe_format = "pdf" if fmt == "pdf" else "docx"
    data = await _request_json(
        "GET",
        "/law-search/download/pc",
        params={"bbbs": str(bbbs or "").strip(), "format": safe_format},
    )
    url = str((data.get("data") or {}).get("url") or "").strip()
    if not url.startswith("https://"):
        raise NationalLawError("国家法律法规数据库未返回可下载的官方文件")
    return url


async def download_national_law_docx(bbbs: str, timeout: float = 45.0) -> bytes:
    url = await get_national_law_download_url(bbbs, "docx")
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": _headers()["User-Agent"]})
        response.raise_for_status()
        content = response.content
    except httpx.HTTPError as exc:
        raise NationalLawError("下载国家库官方 Word 文件失败") from exc
    # 国家库的“Word”下载接口既会返回 OOXML .docx，也会为部分较早法规
    # 返回 OLE 复合文档格式的 .doc。两者都是有效的官方 Word 文件。
    is_docx = content.startswith(b"PK")
    is_legacy_doc = content.startswith(bytes.fromhex("d0cf11e0a1b11ae1"))
    if len(content) < 100 or not (is_docx or is_legacy_doc):
        raise NationalLawError("国家库官方 Word 文件格式异常")
    return content


async def check_national_law_update(
    bbbs: str,
    title: str,
    *,
    known_status: Optional[int] = None,
) -> Dict[str, Any]:
    detail = await get_national_law_detail(bbbs)
    search = await search_national_laws(title, search_scope="title", exact=True, limit=20)
    same_title = [
        row for row in search["results"]
        if row["normalized_title"] == normalize_title(title)
    ]
    preferred = next((row for row in same_title if row["status_code"] == 3), None)
    if preferred is None:
        preferred = next((row for row in same_title if row["status_code"] == 4), None)
    return {
        "current": detail,
        "preferred": preferred,
        "same_title_versions": same_title,
        "status_changed": known_status is not None and detail.get("status_code") != int(known_status),
        "new_version_available": bool(preferred and preferred.get("bbbs") != bbbs),
    }


def client_status() -> Dict[str, Any]:
    return {
        "name": "国家法律法规数据库 MCP",
        "url": NPC_LAW_DB_URL,
        "default_statuses": [STATUS_LABELS[c] for c in DEFAULT_STATUS_CODES],
    }
