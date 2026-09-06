"""Search public, authoritative Chinese legal websites.

This adapter deliberately accepts no caller-supplied URL.  It queries a fixed search
endpoint and only returns links whose final host is on the authority allow-list, so
the knowledge-base fallback cannot be used as a general-purpose web proxy.
"""

from __future__ import annotations

import html
import re
from typing import Any, Dict, List
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx
from bs4 import BeautifulSoup


SEARCH_ENDPOINT = "https://www.bing.com/search"
AUTHORITY_SITE_QUERY = (
    "(site:gov.cn OR site:npc.gov.cn OR site:court.gov.cn OR site:spp.gov.cn "
    "OR site:shiac.org OR site:bjac.org.cn OR site:gzac.org)"
)
INSTITUTION_HOSTS = {
    "npc.gov.cn": "全国人大网",
    "court.gov.cn": "最高人民法院",
    "gongbao.court.gov.cn": "最高人民法院公报",
    "spp.gov.cn": "最高人民检察院",
    "shiac.org": "上海国际经济贸易仲裁委员会（上海国际仲裁中心）",
    "bjac.org.cn": "北京仲裁委员会",
    "gzac.org": "广州仲裁委员会",
}


class AuthoritativeSearchError(RuntimeError):
    pass


def _normalized_host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().strip(".")


def is_authoritative_url(url: str) -> bool:
    host = _normalized_host(url)
    if not host:
        return False
    if host == "gov.cn" or host.endswith(".gov.cn"):
        return True
    return any(host == allowed or host.endswith("." + allowed) for allowed in INSTITUTION_HOSTS)


def authority_name(url: str) -> str:
    host = _normalized_host(url)
    for allowed, label in sorted(INSTITUTION_HOSTS.items(), key=lambda item: len(item[0]), reverse=True):
        if host == allowed or host.endswith("." + allowed):
            return label
    if host == "gov.cn" or host.endswith(".gov.cn"):
        return host[4:] if host.startswith("www.") else host
    return host


def _unwrap_bing_url(url: str) -> str:
    """Keep normal result links and safely unwrap common Bing redirect links."""
    parsed = urlparse(url)
    if not parsed.hostname or "bing.com" not in parsed.hostname:
        return url
    params = parse_qs(parsed.query)
    for key in ("url", "u", "r"):
        value = (params.get(key) or [""])[0]
        if value.startswith(("http://", "https://")):
            return unquote(value)
    return url


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def parse_search_results(page_html: str, limit: int = 10) -> List[Dict[str, str]]:
    soup = BeautifulSoup(page_html or "", "html.parser")
    results: List[Dict[str, str]] = []
    seen = set()
    for item in soup.select("li.b_algo"):
        link = item.select_one("h2 a[href]")
        if not link:
            continue
        url = _unwrap_bing_url(str(link.get("href") or "")).split("#", 1)[0]
        if not is_authoritative_url(url):
            continue
        canonical = url.rstrip("/")
        if canonical in seen:
            continue
        title = _clean_text(link.get_text(" ", strip=True))
        if len(title) < 4:
            continue
        snippet_node = item.select_one(".b_caption p") or item.select_one("p")
        seen.add(canonical)
        results.append({
            "title": title[:240],
            "url": url,
            "source": authority_name(url),
            "host": _normalized_host(url),
            "snippet": _clean_text(snippet_node.get_text(" ", strip=True) if snippet_node else "")[:500],
            "verification_level": "official_domain",
        })
        if len(results) >= max(1, min(int(limit or 10), 20)):
            break
    downloadable_by_source: Dict[str, str] = {}
    for result in results:
        path = urlparse(result["url"]).path.lower()
        if path.endswith((".pdf", ".doc", ".docx")) or "/download/" in path:
            downloadable_by_source.setdefault(result["source"], result["url"])
    for result in results:
        # Keep the original page URL for browsing/citation, but use an official
        # downloadable document from the same issuer when the page is JS-only.
        result["import_url"] = downloadable_by_source.get(result["source"], result["url"])
    return results


async def search_authoritative_legal_web(query: str, limit: int = 10) -> Dict[str, Any]:
    safe_query = _clean_text(query)[:200]
    if not safe_query:
        raise AuthoritativeSearchError("检索内容不能为空")
    safe_limit = max(1, min(int(limit or 10), 20))
    params = {"q": f'"{safe_query}" {AUTHORITY_SITE_QUERY}', "count": str(max(12, safe_limit * 2))}
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(SEARCH_ENDPOINT, params=params, headers=headers)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise AuthoritativeSearchError("权威官网检索暂时不可用，请稍后重试") from exc
    return {
        "query": safe_query,
        "search_url": SEARCH_ENDPOINT + "?q=" + quote_plus(params["q"]),
        "results": parse_search_results(response.text, safe_limit),
    }
