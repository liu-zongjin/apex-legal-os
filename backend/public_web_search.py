"""Bounded public-web retrieval shared by direct AI and file questions."""
from __future__ import annotations

import asyncio
import datetime as dt
import ipaddress
import re
import socket
import zlib
from urllib.parse import quote_plus, urljoin, urlparse
from xml.etree import ElementTree

import httpx
import jieba
from bs4 import BeautifulSoup


SHANGHAI = dt.timezone(dt.timedelta(hours=8))


def public_host(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        return False
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
        return bool(addresses) and all(ipaddress.ip_address(a[4][0].split('%', 1)[0]).is_global for a in addresses)
    except (OSError, ValueError):
        return False


async def public_get(client, url: str):
    for _ in range(5):
        if not await asyncio.get_running_loop().run_in_executor(None, public_host, url):
            raise ValueError("网页地址不是公开互联网地址")
        async with client.stream('GET', url) as response:
            if response.status_code in {301, 302, 303, 307, 308} and response.headers.get('location'):
                url = urljoin(url, response.headers['location'])
                continue
            response.raise_for_status()
            content = bytearray()
            if response.is_stream_consumed:
                content.extend(response.content)
            else:
                async for chunk in response.aiter_raw():
                    content.extend(chunk)
                    if len(content) > 3_000_000:
                        raise ValueError("网页内容过大")
            raw = bytes(content)
            encoding = response.headers.get('content-encoding', '').lower()
            # Some proxies decompress the body but leave the gzip header behind.
            if encoding == 'gzip' and raw.startswith(b'\x1f\x8b'):
                raw = zlib.decompressobj(31).decompress(raw, 3_000_001)
            elif encoding == 'deflate' and raw.startswith(b'\x78'):
                raw = zlib.decompressobj().decompress(raw, 3_000_001)
            if len(raw) > 3_000_000:
                raise ValueError("网页内容过大")
            if len(raw) < 20_000 and 'html' in response.headers.get('content-type', 'text/html'):
                redirect_page = BeautifulSoup(raw, 'html.parser')
                refresh = redirect_page.find('meta', attrs={'http-equiv': re.compile('^refresh$', re.I)})
                match = re.search(r'url\s*=\s*(.+)', refresh.get('content', ''), re.I) if refresh else None
                if match:
                    url = urljoin(url, match.group(1).strip().strip("\"'"))
                    continue
            response_headers = dict(response.headers)
            response_headers.pop('content-encoding', None)
            response_headers.pop('content-length', None)
            return httpx.Response(response.status_code, headers=response_headers, content=raw, request=response.request)
    raise ValueError("网页跳转次数过多")


def normalise(value):
    return re.sub(r'[^\w\u4e00-\u9fff]', '', value.lower())


def relevant(text: str, required_terms: list[str]) -> bool:
    text = normalise(text)
    return all(any(all(normalise(word) in text for word in re.sub(r'(?<=[A-Za-z])(?=\d)', ' ', term).split()) for term in group.split('|') if normalise(term)) for group in required_terms)


def default_plan(question):
    stop = {'明天', '今天', '现在', '最新', '请问', '多少', '什么', '一下', '帮我', '查询', '搜索', '请', '的', '我', '你', '是', '吗', '了', '给', '介绍'}
    terms = [t.strip() for t in jieba.cut(question) if len(t.strip()) >= 2 and t.strip() not in stop][:6]
    return {'queries': [' '.join('"'+t+'"' for t in terms) or question], 'required_terms': terms[:2]}


def page_excerpt(html, required_terms):
    soup = BeautifulSoup(html, 'html.parser')
    for node in soup.select('script,style,noscript,nav,footer,header'):
        node.decompose()
    root = soup.find('main') or soup.find('article') or soup.body or soup
    lines = [re.sub(r'\s+', ' ', line).strip() for line in root.get_text('\n', strip=True).splitlines()]
    # Preserve opening context and passages around query terms, rather than navigation alone.
    chosen = set(range(min(100, len(lines))))
    for i, line in enumerate(lines):
        if any(normalise(t) in normalise(line) for group in required_terms for t in group.split('|')):
            chosen.update(range(max(0, i-3), min(len(lines), i+30)))
    return '\n'.join(lines[i] for i in sorted(chosen))[:18000]


async def _general_web_context_impl(question: str, limit: int = 5, *, plan=None):
    plan = plan or default_plan(question)
    terms = (plan.get('required_terms') or [])[:2]
    focused = ' '.join('"'+group.split('|')[0].strip('"')+'"' for group in terms)
    def quoted_query(query):
        tokens = re.findall(r'site:[^\s]+|"[^"]+"|[^\s"]+', query)
        return ' '.join(token if token.startswith(('site:', '"')) else '"'+token+'"' for token in tokens)
    domains = re.findall(r'site:([a-zA-Z0-9.-]+)', ' '.join(plan.get('queries') or []))[:2]
    authority_queries = ['"'+terms[-1].split('|')[0]+'" site:'+domain for domain in domains if terms]
    queries = list(dict.fromkeys(authority_queries + [focused] + [quoted_query(q) for q in plan.get('queries') or [question]]))[:3]
    queries = [q for q in queries if q]
    retrieved_at = dt.datetime.now(SHANGHAI).isoformat(timespec='seconds')
    headers = {'Accept-Encoding': 'identity'}
    semaphore = asyncio.Semaphore(3)
    async with httpx.AsyncClient(timeout=10, follow_redirects=False, headers=headers) as client:
        async def search(query):
            try:
                async with semaphore:
                    response = await public_get(client, 'https://cn.bing.com/search?q='+quote_plus(query)+'&format=rss')
                root = ElementTree.fromstring(response.content)
                results = []
                for item in root.findall('.//item')[:15]:
                    title, url = (item.findtext('title') or '').strip(), (item.findtext('link') or '').strip()
                    description = BeautifulSoup(item.findtext('description') or '', 'html.parser').get_text(' ', strip=True)
                    if title and url and relevant(title+' '+url+' '+description, terms[:1]):
                        results.append((title, url, description))
                return results
            except Exception:
                return []
        async def secondary_search(query):
            try:
                async with semaphore:
                    response = await public_get(client, 'https://www.sogou.com/web?query='+quote_plus(query.replace('"', '')))
                soup = BeautifulSoup(response.content, 'html.parser')
                results = []
                for heading in soup.select('h3')[:15]:
                    link = heading.find('a', href=True)
                    if not link:
                        continue
                    title = link.get_text(' ', strip=True)
                    url = urljoin('https://www.sogou.com', link['href'])
                    description = heading.parent.get_text(' ', strip=True)[:2000]
                    if relevant(title+' '+description, terms[:1]):
                        results.append((title, url, description))
                return results
            except Exception:
                return []
        found = await asyncio.gather(*(search(q) for q in queries))
        if sum(relevant(title+' '+url+' '+desc, terms) for group in found for title,url,desc in group) < 2:
            found.extend(await asyncio.gather(*(secondary_search(q) for q in queries)))
        candidates, seen = [], set()
        for group in found:
            for item in group:
                if item[1] not in seen:
                    seen.add(item[1]); candidates.append(item)
        candidates.sort(key=lambda item: (not relevant(item[0]+' '+item[2], terms), not any(urlparse(item[1]).hostname == domain or (urlparse(item[1]).hostname or '').endswith('.'+domain) for domain in domains), not (urlparse(item[1]).hostname or '').endswith('.gov.cn')))
        candidates = candidates[:max(1, min(limit+3, 8))]
        async def fetch(item):
            title, url, description = item
            if not await asyncio.get_running_loop().run_in_executor(None, public_host, url):
                return None
            excerpt = description[:1500]
            try:
                async with semaphore:
                    page = await public_get(client, url)
                if 'html' in page.headers.get('content-type', ''):
                    url = str(page.request.url)
                    parsed_url = urlparse(url)
                    if 'captcha' in parsed_url.path.lower() or (parsed_url.hostname in {'www.sogou.com', 'cn.bing.com', 'www.bing.com'} and parsed_url.path in {'/web', '/search'}):
                        return None
                    text = page_excerpt(page.content, terms)
                    if text and relevant(title+' '+url+' '+text, terms):
                        excerpt = text
            except Exception:
                pass
            if not excerpt or not relevant(title+' '+url+' '+excerpt, terms):
                return None
            return title, url, excerpt
        pages = await asyncio.gather(*(fetch(item) for item in candidates))
    sources, blocks = [], []
    pages.sort(key=lambda item: (item is None, not any(((urlparse(item[1]).hostname or '') == domain or (urlparse(item[1]).hostname or '').endswith('.'+domain)) for domain in domains) if item else True))
    for item in pages:
        if item is None:
            continue
        if len(sources) >= limit:
            break
        title, url, excerpt = item
        index = len(sources)+1
        blocks.append(f'[WEB:{index}] {title}\n网址：{url}\n检索时间：{retrieved_at}\n公开内容节选：{excerpt}')
        sources.append({'id': f'web-{index}', 'title': title, 'source': url, 'url': url,
                        'source_type': 'public_web', 'retrieved_at': retrieved_at})
    return '\n\n'.join(blocks), sources, '' if sources else '联网检索未获得与问题相关的可用资料，无法据此核验实时信息'


async def general_web_context(question: str, limit: int = 5, *, plan=None):
    try:
        return await asyncio.wait_for(_general_web_context_impl(question, limit, plan=plan), timeout=45)
    except asyncio.TimeoutError:
        return "", [], "联网检索超时，无法据此核验实时信息"
