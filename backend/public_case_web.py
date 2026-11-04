"""公开互联网类案检索：网络公开裁判文书案例数据库裁判文书适配器。

设计边界（与 CASE_PUBLIC_WEB_STUDY.md 一致）：

* 只使用 MediaWiki 公共 API，不抓取登录墙、验证码或反爬页面；
* 说明性 User-Agent、串行请求、≥1 秒间隔、``maxlag`` 上限，失败即放弃；
* 网络公开裁判文书案例数据库是社区存档，不是官方发布，核验级别只能是 ``public_archive``；
* 只有站点 ``zh.wikisource.org``，不接受调用方传 URL，避免变成通用代理。

返回的案例 dict 与 ``case_research.parse_case_search_markdown`` 对齐，
可直接进入既有的争点重排、约束筛选与来源核验流水线。
"""

from __future__ import annotations

import asyncio
import hashlib
import socket
import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from .public_web_search import evidence_excerpt
from .public_case_transport import case_proxy

WIKISOURCE_API = "https://zh.wikisource.org/w/api.php"
WIKISOURCE_HOST = "zh.wikisource.org"
# 说明用途即可，不写个人姓名/联系方式；维基媒体要求可识别的 UA。
USER_AGENT = "StellaLegalKB/1.0 (https://liu-zongjin.github.io/stella-downloads/; public case research)"
SOURCE_LABEL = "网络公开裁判文书案例数据库（公开存档）"
_JUDGMENT_CATEGORY = "中华人民共和国民事判决书"
_MIN_INTERVAL = 2.5
_MAX_RETRIES = 0
_REQUEST_TIMEOUT = 6.0
_REST_SEARCH = f"https://{WIKISOURCE_HOST}/w/rest.php/v1/search/page"
_CACHE_FILE_NAME = "public_case_cache.db"
_CACHE_TTL_SECONDS = 7 * 24 * 3600
_CACHE_STALE_SECONDS = 30 * 24 * 3600
_TITLES_TTL_SECONDS = 24 * 3600
_CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS public_case_cache (
  cache_key TEXT PRIMARY KEY,
  plan_json TEXT NOT NULL,
  cases_json TEXT NOT NULL,
  runs_json TEXT NOT NULL,
  created_at TEXT NOT NULL
)
"""
_PAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS public_page_cache (
  title TEXT PRIMARY KEY,
  wikitext TEXT NOT NULL,
  created_at TEXT NOT NULL
)
"""
_PAGE_TTL_SECONDS = 30 * 24 * 3600
_TITLES_SCHEMA = """
CREATE TABLE IF NOT EXISTS public_search_cache (
  query_key TEXT PRIMARY KEY,
  titles_json TEXT NOT NULL,
  created_at TEXT NOT NULL
)
"""
_cache_ready: set = set()
# 本机常见：IPv4 到维基媒体黑洞、IPv6 可达。一旦证明 IPv6 可用，后续会话直接走 IPv6。
_prefer_ipv6 = False
_ipv6_probed = False


def _probe_ipv6() -> bool:
    """一次性探测本机能否直连维基媒体的 IPv6（IPv4 常被运营商黑洞）。"""
    try:
        infos = socket.getaddrinfo(WIKISOURCE_HOST, 443, socket.AF_INET6, socket.SOCK_STREAM)
    except OSError:
        return False
    for info in infos[:2]:
        try:
            with socket.create_connection((info[4][0], 443), timeout=3.0):
                return True
        except OSError:
            continue
    return False

_HEADER_RE = re.compile(r"\{\{\s*Header/裁判文书\s*\|(.*?)\}\}", re.DOTALL)
_DISAMBIG_MARKER = "裁判文书消歧义页"
_CASE_NUMBER_RE = re.compile(r"[（(]\d{4}[）)][^\s；;，,。]{2,35}?号")
_DATE_CATEGORY_RE = re.compile(r"Category:(\d{4})年(\d{1,2})月(\d{1,2})日")
_COURT_RE = re.compile(r"([\u4e00-\u9fa5]{2,15}?人民法院)")
_HOLDING_START = "本院认为"
_FACT_START = "本院查明"


class PublicCaseError(RuntimeError):
    """网络公开裁判文书案例数据库不可达或返回结构异常。"""


_rate_lock = asyncio.Lock()
_last_request_at = 0.0


async def _throttle() -> None:
    global _last_request_at
    async with _rate_lock:
        wait = _MIN_INTERVAL - (time.monotonic() - _last_request_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_at = time.monotonic()


def _headers() -> Dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
    }


class _WikiSession:
    """Bounded direct/system-proxy routes shared by search and document reads."""
    def __init__(self):
        from .public_case_transport import CaseRoutes
        self.routes = CaseRoutes(_headers())

    async def get(self, params, *, deadline=None):
        await _throttle()
        return await self.routes.get(WIKISOURCE_API, params=params, deadline=deadline)

    async def get_url(self, url, *, deadline=None):
        await _throttle()
        return await self.routes.get(url, deadline=deadline)

    async def aclose(self):
        await self.routes.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.aclose()


def _retry_after(response: httpx.Response, default: float = 5.0, cap: float = 15.0) -> float:
    raw = (response.headers.get("retry-after") or "").strip()
    try:
        return max(1.0, min(float(raw), cap))
    except ValueError:
        return default


async def _api_get(
    session: _WikiSession,
    params: Dict[str, Any],
    *,
    deadline: float | None = None,
    retries: int | None = None,
) -> Dict[str, Any]:
    query = {"action": "query", "format": "json", "formatversion": "2", "maxlag": "5"}
    query.update(params)
    last_error: Exception | None = None
    max_retries = _MAX_RETRIES if retries is None else max(0, int(retries))
    for attempt in range(max_retries + 1):
        if deadline is not None and time.monotonic() >= deadline:
            raise PublicCaseError("公开检索超出本次时间预算，已提前结束")
        if attempt:
            await asyncio.sleep(1.5)
        try:
            response = await session.get(query, deadline=deadline)
        except (httpx.ConnectTimeout, httpx.ConnectError) as exc:
            # 连接层失败重试无意义：IPv6 回退已在会话内尝试过。
            last_error = exc
            break
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
            continue
        if response.status_code == 429:
            wait = _retry_after(response, default=8.0, cap=12.0)
            if wait > 20.0:
                # 站点给的是分钟级封禁窗口，当前请求等待无意义，直接快速失败。
                raise PublicCaseError(f"网络公开裁判文书案例数据库限流（HTTP 429，建议 {int(wait)} 秒后重试）")
            last_error = PublicCaseError(
                f"网络公开裁判文书案例数据库限流（HTTP 429，建议 {int(wait)} 秒后重试）"
            )
            if attempt < max_retries:
                await asyncio.sleep(wait)
            continue
        if response.status_code >= 500:
            last_error = PublicCaseError(f"网络公开裁判文书案例数据库返回 HTTP {response.status_code}")
            continue
        try:
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPStatusError, ValueError) as exc:
            last_error = exc
            continue
        if payload.get("error"):
            error = payload["error"]
            code = str(error.get("code") or "")
            info = str(error.get("info") or "")
            # CirrusSearch 过载时返回 HTTP 200 + error，而不是 429；按可重试处理。
            if "busy" in code.lower() or "too busy" in info.lower():
                last_error = PublicCaseError(f"网络公开裁判文书案例数据库检索排队（{info or code}）")
                if attempt < max_retries:
                    await asyncio.sleep(1.5 * (attempt + 1))
                continue
            raise PublicCaseError(f"网络公开裁判文书案例数据库接口错误：{info or code}")
        return payload
    if isinstance(last_error, PublicCaseError):
        raise last_error
    detail = f"{type(last_error).__name__}：{last_error}" if last_error else "unknown"
    raise PublicCaseError(f"网络公开裁判文书案例数据库暂不可达（{detail}）")


def _compact(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _strip_html(value: str) -> str:
    return BeautifulSoup(str(value or ""), "lxml").get_text(" ").strip()


def _header_params(wikitext: str) -> Dict[str, str]:
    match = _HEADER_RE.search(wikitext or "")
    if not match:
        return {}
    params: Dict[str, str] = {}
    for part in re.split(r"\n?\s*\|", match.group(1)):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        params[key.strip()] = value.strip()
    return params


def _clean_wikitext(wikitext: str) -> str:
    text = str(wikitext or "")
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.DOTALL)
    text = re.sub(r"<ref[^>]*/>", "", text)
    text = text.replace("{{gap}}", " ")
    for _ in range(6):
        stripped = re.sub(r"\{\{[^{}]*\}\}", "", text)
        if stripped == text:
            break
        text = stripped
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"'{2,5}", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"^=+\s*(.*?)\s*=+\s*$", r"\1", text, flags=re.MULTILINE)
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _link_targets(wikitext: str) -> List[str]:
    targets = []
    for match in re.finditer(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]", str(wikitext or "")):
        target = match.group(1).strip()
        if target and "判决书" in target or "裁定书" in target:
            targets.append(target)
    return targets


def _category_date(wikitext: str) -> str:
    match = _DATE_CATEGORY_RE.search(str(wikitext or ""))
    if not match:
        return ""
    year, month, day = match.groups()
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _infer_court(title: str, params: Dict[str, str], body: str) -> str:
    if params.get("court"):
        return params["court"].strip()
    if "最高人民法院" in title:
        return "最高人民法院"
    head = body[:1500] if _HOLDING_START not in body else body.split(_HOLDING_START, 1)[0][:1500]
    match = _COURT_RE.search(head)
    return match.group(1) if match else ""


def _authority_type(court: str) -> str:
    if "最高人民法院" in court:
        return "最高人民法院案例"
    if "高级人民法院" in court:
        return "高级人民法院案例"
    if "中级人民法院" in court:
        return "中级人民法院案例"
    return "其他法院案例"


def _holding(body: str, limit: int = 100000) -> str:
    if _HOLDING_START not in body:
        return ""
    tail = body.rsplit(_HOLDING_START, 1)[1]
    tail = tail.split("判决如下", 1)[0].split("裁定如下", 1)[0]
    return re.sub(r"\s+", "", tail)[:limit]


def judgment_disposition(body):
    parts=re.split(r'判决如下[：:]?|裁定如下[：:]?',body)
    return parts[-1][:1800] if len(parts)>1 else ""


def adjudicated_facts(body, terms=()):
    """Never silently promote a party's pleading into established facts."""
    match=re.search(r'本院(?:经审理)?查明|经审理查明|一审法院(?:认定|查明)(?:的)?事实|一审(?:法院)?查明',body)
    if not match:return ""
    text=body[match.start():]
    text=re.split(r'本院认为|一审法院认为',text,maxsplit=1)[0]
    return text[:100000]


def _factual_summary(body: str, limit: int = 320) -> str:
    if _FACT_START in body:
        summary = body.split(_FACT_START, 1)[1].split(_HOLDING_START, 1)[0]
    else:
        summary = body.split(_HOLDING_START, 1)[0]
    return re.sub(r"\s+", "", summary)[-limit:] if summary else ""


def is_disambiguation(wikitext: str, title: str = "") -> bool:
    text = str(wikitext or "")
    if _DISAMBIG_MARKER in text:
        return True
    return bool(_CASE_NUMBER_RE.search(title)) and len(_clean_wikitext(text)) < 200 and "判决书" in title


def _cache_path() -> Path:
    raw = os.environ.get("LEGAL_KB_DB_PATH", "").strip()
    if raw:
        database = Path(raw).expanduser()
        return database.with_name(f"{database.stem}_{_CACHE_FILE_NAME}")
    try:
        from . import main as _main  # 延迟导入，避免模块级循环依赖
        database = Path(_main.DB_PATH).expanduser()
        return database.with_name(f"{database.stem}_{_CACHE_FILE_NAME}")
    except Exception:
        return Path(tempfile.gettempdir()) / f"stella_{_CACHE_FILE_NAME}"


def _cache_key(plan: Dict[str, Any], limit: int) -> str:
    payload = {
        "version": 9,
        "queries": plan.get("queries", []),
        "paths": plan.get("research_paths", []),
        "context_terms": plan.get("context_terms", []),
        "core": str(plan.get("core_issue") or ""),
        "terms": [str(term) for term in (plan.get("essential_terms") or [])],
        "groups": [list(group) for group in (plan.get("required_term_groups") or [])],
        "limit": int(limit),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _cache_connection():
    path = _cache_path()
    try:
        from .database import connect_database
        connection = connect_database(path)
    except Exception:
        return None
    try:
        if str(path) not in _cache_ready:
            connection.execute(_CACHE_SCHEMA)
            connection.execute(_TITLES_SCHEMA)
            connection.execute(_PAGE_SCHEMA)
            connection.commit()
            _cache_ready.add(str(path))
    except Exception:
        connection.close()
        return None
    return connection


def _cache_load(cache_key: str):
    connection = _cache_connection()
    if connection is None:
        return None
    try:
        row = connection.execute(
            "SELECT cases_json, runs_json, created_at FROM public_case_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
    except Exception:
        row = None
    finally:
        connection.close()
    if not row:
        return None
    try:
        cases = json.loads(row["cases_json"])
        runs = json.loads(row["runs_json"])
        created = datetime.fromisoformat(str(row["created_at"]))
    except (ValueError, TypeError, KeyError):
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - created).total_seconds()
    for case in cases:
        if isinstance(case, dict) and case.get("source_kind") == "wikisource":
            case["source"] = SOURCE_LABEL
    return cases, runs, age, created


def _cache_store(cache_key: str, plan: Dict[str, Any], cases: List[Dict[str, Any]], runs: List[Dict[str, Any]]) -> None:
    connection = _cache_connection()
    if connection is None:
        return
    try:
        connection.execute(
            "INSERT OR REPLACE INTO public_case_cache (cache_key, plan_json, cases_json, runs_json, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                cache_key,
                json.dumps(plan, ensure_ascii=False),
                json.dumps(cases, ensure_ascii=False),
                json.dumps(runs, ensure_ascii=False),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        connection.commit()
    except Exception:
        connection.rollback()
    finally:
        connection.close()


def _titles_key(query: str, limit: int) -> str:
    return hashlib.sha1(f"{query}|{int(limit)}".encode("utf-8")).hexdigest()


def _titles_load(query: str, limit: int) -> List[Dict[str, Any]]:
    connection = _cache_connection()
    if connection is None:
        return []
    try:
        row = connection.execute(
            "SELECT titles_json, created_at FROM public_search_cache WHERE query_key = ?",
            (_titles_key(query, limit),),
        ).fetchone()
    except Exception:
        row = None
    finally:
        connection.close()
    if not row:
        return []
    try:
        hits = json.loads(row["titles_json"])
        created = datetime.fromisoformat(str(row["created_at"]))
    except (ValueError, TypeError):
        return []
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    if (datetime.now(timezone.utc) - created).total_seconds() > _TITLES_TTL_SECONDS:
        return []
    return [hit for hit in hits if isinstance(hit, dict) and hit.get("title")]


def _titles_store(query: str, limit: int, hits: List[Dict[str, Any]]) -> None:
    if not hits:
        return
    connection = _cache_connection()
    if connection is None:
        return
    try:
        connection.execute(
            "INSERT OR REPLACE INTO public_search_cache (query_key, titles_json, created_at) VALUES (?, ?, ?)",
            (_titles_key(query, limit), json.dumps(hits, ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
        )
        connection.commit()
    except Exception:
        connection.rollback()
    finally:
        connection.close()


def build_wikisource_queries(plan: Dict[str, Any]) -> List[Dict[str, str]]:
    """把既有的争点计划转成网络公开裁判文书案例数据库检索式（最多两条 + 可选案号精确查询）。"""
    core = str(plan.get("core_issue") or plan.get("original_query") or "").strip()
    if plan.get("research_paths"):
        from .public_case_planning import recall_query_family
        routes=[]
        families=[(path, recall_query_family(path['queries'], plan.get('context_terms') or [])) for path in plan['research_paths']]
        # Broad first queries discover court vocabulary; all original facts are
        # still mandatory during semantic review, irrespective of query breadth.
        for index in range(4):
            for path, queries in families:
                if len(queries)>index:
                    routes.append({'id':path['id']+f'_{index}', 'viewpoint':'neutral', 'query':queries[index]})
        return routes[:4]
    groups = [group for group in (plan.get("required_term_groups") or []) if group]
    essential = [term for term in (plan.get("essential_terms") or []) if _compact(term)]
    if groups:
        base = " ".join(str(group[0]) for group in groups[:4])
    elif essential:
        base = " ".join(str(term) for term in essential[:5])
    else:
        base = " ".join(re.findall(r"[\u4e00-\u9fff]{2,8}", core)[:5])
    base = base.strip()
    queries: List[Dict[str, str]] = []
    if base:
        queries.append({"id": "neutral", "viewpoint": "neutral", "query": base})
    if essential and groups:
        alternative = " ".join(str(term) for term in essential[:3])
        if alternative and _compact(alternative) != _compact(base):
            queries.append({"id": "terms", "viewpoint": "neutral", "query": alternative})
    number = _CASE_NUMBER_RE.search(core)
    if number:
        tail=re.sub(r"^[（(]\d{4}[）)]|号$", "", number.group(0))
        queries.append({"id":"case_number_body","viewpoint":"neutral","query":'"'+tail+'"'})
        queries.append({
            "id": "case_number",
            "viewpoint": "neutral",
            "query": f'intitle:{number.group(0)}',
        })
    # 词袋相同的检索式在 MediaWiki 上会返回同一批结果；重复发送只会浪费限流配额。
    unique: List[Dict[str, str]] = []
    seen_tokens = set()
    for item in queries:
        tokens = tuple(sorted(set(re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9]+", item["query"].lower()))))
        if tokens in seen_tokens:
            continue
        seen_tokens.add(tokens)
        unique.append(item)
    # Preserve the distinguishing issue and its lexical alternatives on every route.
    if len(groups) >= 2:
        focused = " ".join("(" + " OR ".join('"'+str(t)+'"' for t in g[:4]) + ")" for g in groups[:6])
        unique.insert(0, {"id": "issue_groups", "viewpoint": "neutral", "query": focused})
    exact = [q for q in unique if q["id"] in {"case_number", "case_number_body"}]
    focused = [q for q in unique if q["id"] == "issue_groups"]
    # Actually execute distinct semantic/directional routes; the old adapter
    # silently discarded them and searched the same topic bag twice.
    directional = [q for q in plan.get("queries", []) if q.get("id") != "neutral" and q.get("query")]
    routes, seen = [], set()
    for item in exact + focused + directional + unique:
        key = tuple(sorted(set(re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9]+", item["query"].lower()))))
        if key not in seen:
            seen.add(key)
            routes.append(item)
    return routes[:3]


def parse_judgment_page(
    title: str,
    wikitext: str,
    *,
    required_terms: Iterable[str] = (),
    query_id: str = "neutral",
    remote_score: float = 0.6,
) -> Dict[str, Any]:
    """把网络公开裁判文书案例数据库裁判文书页解析为与法随结果同形的案例 dict。"""
    params = _header_params(wikitext)
    body = _clean_wikitext(wikitext)
    case_number = params.get("案号", "") or (
        _CASE_NUMBER_RE.search(title + "\n" + body[:2500]).group(0) if _CASE_NUMBER_RE.search(title + "\n" + body[:2500]) else ""
    )
    court = _infer_court(title, params, body)
    judgment_date = ""
    if params.get("year"):
        year = params["year"]
        month = str(params.get("month") or "01").zfill(2)
        day = str(params.get("day") or "01").zfill(2)
        judgment_date = f"{int(year):04d}-{month}-{day}"
    judgment_date = judgment_date or _category_date(wikitext)
    trial_type = params.get("type") or ("民事判决书" if "民事判决书" in title else ("民事裁定书" if "裁定书" in title else ""))
    excerpt = evidence_excerpt(body, list(required_terms), max_bytes=1200)
    return {
        "title": title,
        "case_number": case_number,
        "court": court,
        "judgment_date": judgment_date,
        "year": judgment_date[:4],
        "source": SOURCE_LABEL,
        "authority_type": _authority_type(court),
        "citation_value": "",
        "rule_quality": "",
        "factual_summary": _factual_summary(body),
        "facts_text": evidence_excerpt(body.split(_HOLDING_START, 1)[0], list(required_terms), 10000),
        "adjudicated_facts": adjudicated_facts(body, required_terms),
        "matched_excerpt": excerpt,
        "holding": _holding(body),
        "holding_conclusion": _holding(body)[-1800:],
        "disposition": judgment_disposition(body),
        "source_url": f"https://{WIKISOURCE_HOST}/wiki/{quote(title.replace(' ', '_'))}",
        "remote_score": round(remote_score, 3),
        "viewpoint": "neutral",
        "retrieved_by": [query_id],
        "raw_markdown": f"## {title}\n{trial_type}｜{court}｜{case_number}",
        "source_kind": "wikisource",
        "body_fetched": True,
    }


def parse_search_hit(
    title: str,
    snippet: str,
    *,
    required_terms: Iterable[str] = (),
    query_id: str = "neutral",
    remote_score: float = 0.6,
) -> Dict[str, Any]:
    """只用检索命中摘要构造案例卡片：正文取不到时的降级形态。"""
    match = _CASE_NUMBER_RE.search(title)
    case_number = match.group(0) if match else ""
    court = _infer_court(title, {}, "")
    year = ""
    year_match = re.search(r"[（(](\d{4})[）)]", title)
    if year_match:
        year = year_match.group(1)
    excerpt = re.sub(r"\s+", "", snippet or "")[:400]
    return {
        "title": title,
        "case_number": case_number,
        "court": court,
        "judgment_date": "",
        "year": year,
        "source": SOURCE_LABEL,
        "authority_type": _authority_type(court),
        "citation_value": "",
        "rule_quality": "",
        "factual_summary": excerpt[:160],
        "matched_excerpt": excerpt,
        "holding": "",
        "source_url": f"https://{WIKISOURCE_HOST}/wiki/{quote(title.replace(' ', '_'))}",
        "remote_score": round(remote_score, 3),
        "viewpoint": "neutral",
        "retrieved_by": [query_id],
        "raw_markdown": f"## {title}\n{case_number}",
        "source_kind": "wikisource",
        "body_fetched": False,
    }


def _looks_like_judgment(title: str) -> bool:
    return "判决书" in title or "裁定书" in title


async def _api_search(
    session: _WikiSession, query: str, limit: int, *, deadline: float | None = None
) -> List[Dict[str, Any]]:
    payload = await _api_get(session, {
        "list": "search",
        "srsearch": query,
        "srnamespace": "0",
        "srlimit": str(max(1, min(limit, 10))),
        "srprop": "snippet|wordcount|size",
    }, deadline=deadline)
    items = ((payload.get("query") or {}).get("search") or [])
    hits = []
    for item in items:
        title = str(item.get("title") or "").strip()
        if not title or not _looks_like_judgment(title):
            continue
        hits.append({
            "title": title,
            "snippet": _strip_html(item.get("snippet") or ""),
            "wordcount": int(item.get("wordcount") or 0),
        })
    return hits


async def _rest_search(
    session: _WikiSession, query: str, limit: int, *, deadline: float | None = None
) -> List[Dict[str, Any]]:
    """REST 检索是另一条服务路径，主 API 被限流时通常仍可用。"""
    url = f"{_REST_SEARCH}?q={quote(query)}&limit={max(1, min(limit, 10))}"
    response = await session.get_url(url, deadline=deadline)
    if response.status_code == 429:
        await asyncio.sleep(_retry_after(response, default=2.0, cap=3.0))
        response = await session.get_url(url, deadline=deadline)
    if response.status_code == 429:
        raise PublicCaseError(
            f"网络公开裁判文书案例数据库限流（HTTP 429，建议 {int(_retry_after(response, default=5.0, cap=60.0))} 秒后重试）"
        )
    response.raise_for_status()
    payload = response.json()
    hits = []
    for page in payload.get("pages") or []:
        title = str(page.get("title") or "").strip()
        if not title or not _looks_like_judgment(title):
            continue
        hits.append({
            "title": title,
            "snippet": _strip_html(str(page.get("excerpt") or "")),
            "wordcount": 0,
        })
    return hits


async def _html_search(session: _WikiSession, query: str, limit: int, *, deadline=None):
    """The reader-facing search works independently of MediaWiki JSON endpoints."""
    if deadline is not None and time.monotonic() >= deadline:
        raise PublicCaseError("公开网页检索超出时间预算")
    response = await session.get_url(f"https://{WIKISOURCE_HOST}/w/index.php?title=Special:Search&search={quote(query)}&limit={min(limit, 10)}", deadline=deadline)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "lxml")
    hits = []
    for row in soup.select(".mw-search-result")[:min(limit, 10)]:
        link = row.select_one(".mw-search-result-heading a")
        snippet = row.select_one(".searchresult")
        if link:
            title = link.get("title") or link.get_text(" ", strip=True)
            if _looks_like_judgment(title):
                hits.append({"title": title, "snippet": snippet.get_text(" ", strip=True) if snippet else "", "wordcount":0})
    if not soup.select_one(".mw-search-results-container, .mw-search-results, .mw-search-nonefound"):
        raise PublicCaseError("网络公开裁判文书案例数据库网页未返回可识别的搜索结果，可能为访问错误页")
    return hits


async def _html_page(session: _WikiSession, title: str, *, deadline=None):
    if deadline is not None and time.monotonic() >= deadline:
        raise PublicCaseError("公开正文读取超出时间预算")
    response = await session.get_url(f"https://{WIKISOURCE_HOST}/w/index.php?title={quote(title)}&variant=zh-hans", deadline=deadline)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "lxml")
    root = soup.select_one(".mw-parser-output")
    if not root:
        raise PublicCaseError("网络公开裁判文书案例数据库网页未返回裁判正文")
    for node in root.select("script,style,.mw-editsection,.noprint"):
        node.decompose()
    return root.get_text("\n", strip=True)


def _shorten_query(query: str) -> str:
    tokens = [token for token in query.split() if token]
    if len(tokens) <= 2:
        return query
    return " ".join(tokens[:2])


async def _search_titles(
    session: _WikiSession, query: str, limit: int, *, deadline: float | None = None
) -> List[Dict[str, Any]]:
    try:
        hits = await _api_search(session, query, limit, deadline=deadline)
        if hits:
            return hits
    except (PublicCaseError, httpx.HTTPError):
        pass
    try:
        hits = await _rest_search(session, query, limit, deadline=deadline)
        if hits:
            return hits
    except (PublicCaseError, httpx.HTTPError):
        pass
    return await _html_search(session, query, limit, deadline=deadline)


def _page_cache_load(titles: List[str]) -> Dict[str, str]:
    if not titles:
        return {}
    connection = _cache_connection()
    if connection is None:
        return {}
    found: Dict[str, str] = {}
    try:
        placeholders = ",".join("?" for _ in titles)
        rows = connection.execute(
            f"SELECT title, wikitext, created_at FROM public_page_cache WHERE title IN ({placeholders})",
            tuple(titles),
        ).fetchall()
    except Exception:
        rows = []
    finally:
        connection.close()
    now = datetime.now(timezone.utc)
    for row in rows:
        try:
            created = datetime.fromisoformat(str(row["created_at"]))
        except (ValueError, TypeError):
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if (now - created).total_seconds() <= _PAGE_TTL_SECONDS:
            found[str(row["title"])] = str(row["wikitext"])
    return found


def _page_cache_store(pages: Dict[str, str]) -> None:
    if not pages:
        return
    connection = _cache_connection()
    if connection is None:
        return
    now = datetime.now(timezone.utc).isoformat()
    try:
        connection.executemany(
            "INSERT OR REPLACE INTO public_page_cache (title, wikitext, created_at) VALUES (?, ?, ?)",
            [(title, text, now) for title, text in pages.items()],
        )
        connection.commit()
    except Exception:
        connection.rollback()
    finally:
        connection.close()


async def _rest_page(session: _WikiSession, title: str, *, deadline: float | None = None) -> str:
    """REST 单页接口：与 action API 是不同服务路径，用于正文抓取兜底。"""
    if deadline is not None and time.monotonic() >= deadline:
        raise PublicCaseError("公开检索超出本次时间预算，已提前结束")
    url = f"https://{WIKISOURCE_HOST}/w/rest.php/v1/page/{quote(title.replace(' ', '_'))}"
    response = await session.get_url(url, deadline=deadline)
    if response.status_code == 404:
        return ""
    if response.status_code == 429:
        raise PublicCaseError(f"网络公开裁判文书案例数据库限流（HTTP 429，正文暂不可取）")
    response.raise_for_status()
    payload = response.json()
    return str(payload.get("source") or "")


async def _fetch_pages(
    session: _WikiSession, titles: List[str], *, deadline: float | None = None
) -> Dict[str, str]:
    wanted = [title for title in titles if title]
    pages: Dict[str, str] = _page_cache_load(wanted)
    missing = [title for title in wanted if title not in pages]
    if not missing:
        return pages
    last_error: Exception | None = None
    attempted_html = set()
    # 一次批量取正文：网络公开裁判文书案例数据库的阅读接口按 IP 限流，逐页 REST 很容易撞 429，
    # 批量 revisions 只需 1 次请求，命中率也高于逐页。
    try:
        payload = await _api_get(session, {
            "prop": "revisions",
            "rvprop": "content",
            "rvslots": "main",
            "titles": "|".join(missing[:5]),
            "redirects": "1",
        }, deadline=deadline, retries=0)
        fetched: Dict[str, str] = {}
        for page in ((payload.get("query") or {}).get("pages") or []):
            if page.get("missing"):
                continue
            revisions = page.get("revisions") or []
            if not revisions:
                continue
            content = revisions[0].get("slots", {}).get("main", {}).get("content")
            if content:
                fetched[str(page.get("title"))] = content
        _page_cache_store(fetched)
        pages.update(fetched)
    except (PublicCaseError, httpx.HTTPError) as exc:
        last_error = exc
    leftover = [title for title in missing if title not in pages]
    if leftover and last_error is None:
        # 批量接口偶发漏页（重定向/跨命名空间）时，最多补取 1 页，避免再次触发限流。
        title = leftover[0]
        try:
            text = await _rest_page(session, title, deadline=deadline)
        except (PublicCaseError, httpx.HTTPError) as exc:
            last_error = exc
            text = ""
        if text:
            pages[title] = text
            _page_cache_store({title: text})
    # Read the same public page as a browser when the JSON interface is blocked.
    for title in [t for t in wanted if t not in pages and t not in attempted_html][:5]:
        if deadline is not None and time.monotonic() >= deadline:
            break
        try:
            text = await _html_page(session, title, deadline=deadline)
            if text:
                pages[title] = text
                _page_cache_store({title:text})
        except (PublicCaseError, httpx.HTTPError) as exc:
            last_error = exc
    if not pages and last_error is not None:
        raise last_error
    return pages


async def _search_wikisource_cases(plan: Dict[str, Any], *, limit: int = 6, progress=None) -> Dict[str, Any]:
    """按争点计划检索网络公开裁判文书案例数据库，返回 {"cases", "retrieval_runs", "errors"}。"""
    queries = build_wikisource_queries(plan)
    if not queries:
        return {"cases": [], "retrieval_runs": [], "errors": [{"source": "wikisource", "message": "争点为空，未生成检索式"}]}
    cache_key = _cache_key(plan, limit)
    cached = _cache_load(cache_key)
    if cached and cached[0] and cached[2] <= _CACHE_TTL_SECONDS:
        cases_cached, runs_cached, _, created_cached = cached
        for run in runs_cached:
            run["cache"] = "fresh"
            run["fetched_at"] = created_cached.isoformat()
        return {"cases": cases_cached, "retrieval_runs": runs_cached, "errors": []}
    required_terms: List[str] = []
    for group in plan.get("required_term_groups") or []:
        required_terms.extend(str(term) for term in group)
    required_terms.extend(str(term) for term in (plan.get("essential_terms") or []))
    cases: List[Dict[str, Any]] = [] if progress is None else progress["cases"]
    errors: List[Dict[str, str]] = [] if progress is None else progress["errors"]
    runs: List[Dict[str, Any]] = [] if progress is None else progress["retrieval_runs"]
    seen_titles: set[str] = set()
    async with _WikiSession() as session:
        # 网络公开裁判文书案例数据库的检索与正文接口共享严格的按 IP 限流：默认只打 1—2 次检索请求，
        # 命中不足时才追加案号/短词查询，避免一次搜索把配额耗尽。
        deadline = time.monotonic() + 65.0
        for item in queries[:4]:
            if time.monotonic() >= deadline:
                errors.append({"source": "wikisource", "query_id": item["id"], "message": "公开检索超出本次时间预算，已提前结束"})
                break
            hits = _titles_load(item["query"], limit)
            cached_titles = bool(hits)
            if not hits:
                try:
                    hits = await _search_titles(session, item["query"], limit, deadline=deadline)
                except (PublicCaseError, httpx.HTTPError) as exc:
                    errors.append({
                "source": "wikisource",
                "query_id": item["id"],
                "message": f"{str(exc) or type(exc).__name__}（网络公开裁判文书案例数据库请求未完成；已缓存正文仍会复用）",
            })
                    continue
                _titles_store(item["query"], limit, hits)
            runs.append({
                "source": "wikisource", "query_id": item["id"],
                "query": item["query"], "result_count": len(hits),
                "titles_cached": cached_titles,
            })
            fresh = [hit for hit in hits if hit["title"] not in seen_titles][:min(limit, 7)]
            seen_titles.update(hit["title"] for hit in fresh)
            if not fresh:
                continue
            pages: Dict[str, str] = {}
            fetch_error: Exception | None = None
            # 先按摘要成卡：正文接口更容易被限流，摘要至少能给出案号、法院与争点命中句。
            snippet_cases = [
                parse_search_hit(
                    hit["title"],
                    hit.get("snippet") or "",
                    required_terms=required_terms,
                    query_id=item["id"],
                    remote_score=max(0.35, 0.58 - index * 0.04),
                )
                for index, hit in enumerate(fresh)
            ]
            try:
                body_deadline = min(deadline, time.monotonic() + 20.0)
                pages = await _fetch_pages(session, [hit["title"] for hit in fresh], deadline=body_deadline)
            except (PublicCaseError, httpx.HTTPError) as exc:
                fetch_error = exc
            if fetch_error is not None:
                errors.append({"source": "wikisource", "query_id": item["id"], "message": str(fetch_error)})
                cases.extend(snippet_cases)
                continue
            fetched_titles = {case["title"] for case in cases}
            for snippet_case in snippet_cases:
                if snippet_case["title"] not in fetched_titles:
                    cases.append(snippet_case)
            redirects: List[str] = []
            for index, hit in enumerate(fresh):
                wikitext = pages.get(hit["title"])
                if not wikitext:
                    continue
                if is_disambiguation(wikitext, hit["title"]):
                    redirects.extend(_link_targets(wikitext)[:1])
                    continue
                parsed_case = parse_judgment_page(
                    hit["title"], wikitext,
                    required_terms=required_terms,
                    query_id=item["id"],
                    remote_score=max(0.4, 0.66 - index * 0.04),
                )
                parsed_case["body_fetched"] = True
                cases.append(parsed_case)
            if redirects:
                try:
                    target_pages = await _fetch_pages(session, redirects[:3], deadline=deadline)
                except (PublicCaseError, httpx.HTTPError):
                    target_pages = {}
                for title, wikitext in target_pages.items():
                    if title in seen_titles:
                        continue
                    seen_titles.add(title)
                    cases.append(parse_judgment_page(
                        title, wikitext,
                        required_terms=required_terms,
                        query_id=item["id"],
                        remote_score=0.55,
                    ))
    if cases:
        _cache_store(cache_key, plan, cases, runs)
        return {"cases": cases, "retrieval_runs": runs, "errors": errors}
    if cached and cached[2] <= _CACHE_STALE_SECONDS:
        cases_cached, runs_cached, _, created_cached = cached
        for run in runs_cached:
            run["cache"] = "stale"
            run["fetched_at"] = created_cached.isoformat()
        errors.append({
            "source": "wikisource",
            "message": f"网络公开裁判文书案例数据库本次未能检索（限流或不可达），已回退到本机缓存（抓取于 {created_cached.strftime('%Y-%m-%d %H:%M')}）",
        })
        return {"cases": cases_cached, "retrieval_runs": runs_cached, "errors": errors}
    return {"cases": cases, "retrieval_runs": runs, "errors": errors}


async def search_public_cases(plan: Dict[str, Any], *, limit: int = 6) -> Dict[str, Any]:
    """Independent web discovery continues even when the archive API is unavailable."""
    from .public_case_discovery import discover_cases
    async def bounded(call, source, partial):
        try:
            return await asyncio.wait_for(call, max(5,min(70,float(plan.get("source_budget",70)))))
        except (asyncio.TimeoutError, PublicCaseError, httpx.HTTPError, ValueError) as exc:
            partial["errors"].append({"source": source, "message": str(exc) or "部分检索超时，保留已取得资料"})
            return partial
    wiki_partial = {"cases": [], "retrieval_runs": [], "errors": []}
    web_partial = {"cases": [], "retrieval_runs": [], "errors": []}
    results = await asyncio.gather(bounded(_search_wikisource_cases(plan, limit=limit, progress=wiki_partial), "wikisource", wiki_partial),
                                   bounded(discover_cases(plan, limit=limit, progress=web_partial), "public_web", web_partial))
    return {key: [item for result in results for item in result[key]] for key in ("cases", "retrieval_runs", "errors")}
