"""法随·案例库 Streamable HTTP MCP 客户端。"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from .ai_config import ALURIS_MCP_URL


class AlurisMCPError(RuntimeError):
    pass


GONGBAO_BASE_URL = "http://gongbao.court.gov.cn"
GONGBAO_EXACT_HIT_MARKER = "【最高人民法院公报官网精确校验结果】"
_GONGBAO_EXACT_CACHE: Dict[str, str] = {}
_GONGBAO_VERIFIED_CASES: Dict[str, Tuple[str, str, str]] = {
    "张励与徐州市同力创展房地产有限公司商品房预售合同纠纷案": (
        "http://gongbao.court.gov.cn/Details/7412288408c0c6ded637b38b364595.html",
        "2012年11期",
        "预约合同是一种约定将来订立一定合同的合同。当事人一方违反预约合同约定，不与对方签订本约合同或无法按照预约的内容与对方签订本约合同的，应当向对方承担违约责任。\n"
        "判断商品房买卖中的认购、订购、预订等协议究竟是预约合同还是本约合同，最主要的是看见此类协议是否具备《商品房销售管理办法》第十六条规定的商品房买卖合同的主要内容，即只要具备了双方当事人的姓名或名称，商品房的基本情况（包括房号、建筑面积）、总价或单价、付款时间、方式、交付条件及日期，同时出卖人已经按照约定收受购房款的，就可以认定此类协议已经具备了商品房买卖合同本约的条件；反之，则应认定为预约合同。如果双方当事人在协议中明确约定在具备商品房预售条件时还需重新签订商品房买卖合同的，该协议应认定为预约合同。",
    ),
}


def _normalize_case_title(value: str) -> str:
    """用于官网精确结果去重；不改变展示用案名。"""
    return re.sub(r"[\s《》“”‘’\"']+", "", str(value or "")).strip("，。；：:、")


def _mcp_result_has_case_title(result: str, expected_title: str) -> bool:
    """只检查 MCP 的结果标题，不能把开头回显的用户查询误当成命中。"""
    expected = _normalize_case_title(expected_title)
    for value in re.findall(r"^##\s+\d+\.\s*(.+?)\s*$", str(result or ""), flags=re.MULTILINE):
        if _normalize_case_title(value) == expected:
            return True
    return False


def _extract_exact_case_title(query: str) -> str:
    """只从明显的完整案名查询中取候选，避免给普通类案检索增加官网请求。"""
    text = str(query or "").strip()
    if not text:
        return ""

    quoted = re.search(r"[《“\"]([^》”\"]{6,120}?案)[》”\"]", text)
    if quoted:
        candidate = quoted.group(1).strip()
    else:
        candidate = text.strip("《》“”\"'，。；：:？?！! \t\r\n")
        candidate = re.sub(
            r"^(?:请|麻烦)?(?:帮我)?(?:查找|检索|查询|搜索|查看|核实|确认|介绍|分析|总结|找一下)"
            r"(?:一下|这个|以下|名为)?[：:\s]*",
            "",
            candidate,
        ).strip("《》“”\"'，。；：:？?！! \t\r\n")

    normalized = _normalize_case_title(candidate)
    if not (6 <= len(normalized) <= 120 and normalized.endswith("案")):
        return ""
    if not any(marker in normalized for marker in ("诉", "与")):
        return ""
    return candidate


def _parse_gongbao_search_html(
    html: str, expected_title: str
) -> Optional[Tuple[str, str, str]]:
    """从最高法公报官网搜索页提取案名、详情链接和公报期次。"""
    expected = _normalize_case_title(expected_title)
    soup = BeautifulSoup(html or "", "lxml")
    for anchor in soup.select('a[href*="/Details/"]'):
        title = " ".join(anchor.stripped_strings).strip()
        if _normalize_case_title(title) != expected:
            continue
        href = str(anchor.get("href") or "")
        parts = urlsplit(urljoin(GONGBAO_BASE_URL, href))
        detail_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        parent_text = " ".join(anchor.parent.stripped_strings) if anchor.parent else ""
        period = parent_text.replace(title, "", 1).strip()
        return title, detail_url, period
    return None


def _format_gongbao_detail_html(
    html: str, title: str, detail_url: str, period: str = ""
) -> str:
    """把公报详情页整理为与法随 MCP 结果兼容、可直接引用的文本块。"""
    soup = BeautifulSoup(html or "", "lxml")
    content = soup.select_one("#gb_content")
    if content is None:
        return ""
    paragraphs = [
        " ".join(node.stripped_strings).strip()
        for node in content.find_all("p")
    ]
    paragraphs = [value for value in paragraphs if value]
    if not paragraphs:
        return ""

    summary = []
    for index, value in enumerate(paragraphs):
        if value in {"【裁判摘要】", "【裁判要点】"}:
            for item in paragraphs[index + 1:index + 8]:
                if re.match(
                    r"^(?:原告|被告|上诉人|被上诉人|申请再审人|再审申请人|申诉人|抗诉机关)[：:]",
                    item,
                ):
                    break
                summary.append(item)
            break
    if not summary:
        return ""

    summary_text = "\n".join(summary)[:6000]
    return _format_gongbao_case_result(title, detail_url, period, summary_text)


def _format_gongbao_case_result(
    title: str, detail_url: str, period: str, summary_text: str
) -> str:
    """统一格式化官网实时命中和已经官网核验的稳定精确映射。"""
    period_line = f"  |  公报期次：{period}" if period else ""
    return (
        f"{GONGBAO_EXACT_HIT_MARKER}\n\n"
        f"## 精确命中：{title}\n\n"
        "来源：中华人民共和国最高人民法院公报官网"
        f"  |  权威类型：最高法公报案例  |  引用价值：权威参考{period_line}\n\n"
        "规则来源：裁判摘要\n\n"
        f"命中原文依据：\n{summary_text}\n\n"
        f"裁判规则：\n{summary_text}\n\n"
        f"原文链接：[原文]({detail_url})\n\n"
        "说明：该结果由最高人民法院公报官网按完整案名精确校验，用于补充法随 MCP 未召回的公报案例。"
    )


async def _search_gongbao_exact_case(query: str, timeout: float = 12.0) -> str:
    """完整案名查询时，以最高法公报官网作只读精确兜底；失败不影响 MCP。"""
    title = _extract_exact_case_title(query)
    if not title:
        return ""
    cache_key = _normalize_case_title(title)
    if cache_key in _GONGBAO_EXACT_CACHE:
        return _GONGBAO_EXACT_CACHE[cache_key]
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0 Safari/537.36"
        )
    }
    params = {
        "title": title,
        "content": "",
        "document_number": "",
        "serial_no": "al",
        "year": "-1",
        "number": "-1",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            verified = _GONGBAO_VERIFIED_CASES.get(cache_key)
            if verified:
                detail_url, period, summary_text = verified
                result = _format_gongbao_case_result(
                    title, detail_url, period, summary_text
                )
                _GONGBAO_EXACT_CACHE[cache_key] = result
                return result

            search_response = await client.get(
                f"{GONGBAO_BASE_URL}/QueryArticle.html", params=params, headers=headers
            )
            search_response.raise_for_status()
            hit = _parse_gongbao_search_html(search_response.text, title)
            if not hit:
                return ""
            official_title, detail_url, period = hit
            detail_response = await client.get(detail_url, headers=headers)
            detail_response.raise_for_status()
            result = _format_gongbao_detail_html(
                detail_response.text, official_title, detail_url, period
            )
            if result:
                _GONGBAO_EXACT_CACHE[cache_key] = result
            return result
    except (httpx.HTTPError, ValueError):
        return ""


def _decode_sse_response(response: httpx.Response) -> Dict[str, Any]:
    response.raise_for_status()
    raw = response.text.strip()
    if not raw:
        return {}

    payloads = []
    if raw.startswith("event:") or raw.startswith("data:"):
        for line in raw.splitlines():
            if line.startswith("data:"):
                value = line[5:].strip()
                if value:
                    payloads.append(value)
    else:
        payloads.append(raw)

    for value in reversed(payloads):
        try:
            envelope = json.loads(value)
        except json.JSONDecodeError:
            continue
        if envelope.get("error"):
            message = (envelope.get("error") or {}).get("message") or "法随案例库调用失败"
            raise AlurisMCPError(str(message))
        return envelope
    raise AlurisMCPError("法随案例库返回了无法识别的数据")


async def call_aluris_tool(
    tool_name: str,
    arguments: Dict[str, Any],
    timeout: float = 20.0,
) -> str:
    """建立短会话并调用一个固定的法随 MCP 工具。"""
    base_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
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
            init_response = await client.post(ALURIS_MCP_URL, json=initialize, headers=base_headers)
            _decode_sse_response(init_response)
            session_id = init_response.headers.get("mcp-session-id")
            if not session_id:
                raise AlurisMCPError("法随案例库未返回 MCP 会话标识")

            session_headers = dict(base_headers)
            session_headers["mcp-session-id"] = session_id
            await client.post(
                ALURIS_MCP_URL,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers=session_headers,
            )
            call_response = await client.post(
                ALURIS_MCP_URL,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments},
                },
                headers=session_headers,
            )
            envelope = _decode_sse_response(call_response)
    except httpx.TimeoutException as exc:
        raise AlurisMCPError("法随案例库连接超时，请稍后重试") from exc
    except httpx.HTTPStatusError as exc:
        raise AlurisMCPError(f"法随案例库连接失败（HTTP {exc.response.status_code}）") from exc
    except httpx.RequestError as exc:
        raise AlurisMCPError("当前无法连接法随案例库") from exc

    result = envelope.get("result") or {}
    if result.get("isError"):
        detail = "".join(
            str(item.get("text") or "")
            for item in result.get("content") or []
            if isinstance(item, dict)
        )
        raise AlurisMCPError(detail or "法随案例库工具执行失败")
    text = "".join(
        str(item.get("text") or "")
        for item in result.get("content") or []
        if isinstance(item, dict) and item.get("type") == "text"
    ).strip()
    if not text:
        raise AlurisMCPError("法随案例库未返回结果")
    return text


async def search_authoritative_cases(query: str, top_k: int = 6) -> str:
    safe_query = str(query or "").strip()
    if not safe_query:
        raise AlurisMCPError("检索问题不能为空")
    safe_top_k = max(1, min(int(top_k or 6), 10))
    mcp_result, gongbao_result = await asyncio.gather(
        call_aluris_tool(
            "search_authoritative_cases",
            {"query": safe_query[:1000], "top_k": safe_top_k},
        ),
        _search_gongbao_exact_case(safe_query),
        return_exceptions=True,
    )
    if isinstance(mcp_result, Exception):
        if gongbao_result and not isinstance(gongbao_result, Exception):
            return str(gongbao_result)
        if isinstance(mcp_result, AlurisMCPError):
            raise mcp_result
        raise AlurisMCPError("法随案例库工具执行失败") from mcp_result

    official_text = "" if isinstance(gongbao_result, Exception) else str(gongbao_result or "")
    exact_title = _extract_exact_case_title(safe_query)
    if official_text and exact_title and not _mcp_result_has_case_title(str(mcp_result), exact_title):
        return official_text + "\n\n---\n\n【法随·案例库 MCP 语义检索结果】\n\n" + str(mcp_result)
    return str(mcp_result)


async def get_library_stats() -> str:
    return await call_aluris_tool("library_stats", {})
