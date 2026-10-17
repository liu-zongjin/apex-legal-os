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
    stop = {'明天', '今天', '现在', '最新', '请问', '多少', '什么', '一下', '帮我', '查询', '搜索', '检索', '官方', '文档', '原始', '链接', '作用', '一句话', '只给', '请', '的', '我', '你', '是', '吗', '了', '给', '介绍'}
    domains = re.findall(r'\b(?:[A-Za-z0-9-]+\.)+(?:com|org|net|cn|edu|io|dev)\b', question, re.I)[:2]
    text = question
    for domain in domains:
        text = text.replace(domain, '')
    # Preserve API identifiers instead of treating dots/domains as separate topics.
    identifiers = re.findall(r'\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+\b', text)
    terms = list(dict.fromkeys(identifiers + [t.strip() for t in jieba.cut(text)
        if len(t.strip()) >= 2 and t.strip() not in stop and t.strip() not in {part for name in identifiers for part in name.split('.')}]))[:6]
    query = ' '.join('"'+t+'"' for t in terms) or text
    if domains:
        query += ' site:'+domains[0]
    return {'queries': [query], 'required_terms': terms[:2]}


def evidence_budget(question, plan):
    if re.search(r'全面|逐项|对比|完整|全部|所有|详细|逐条', question) or len(plan.get('required_terms') or []) >= 3:
        return 12000
    return 7000 if len(plan.get('required_terms') or []) >= 2 else 4000


def evidence_excerpt(text, required_terms, max_bytes=2400, seen=None):
    """Select verbatim passages by topic coverage, with a UTF-8 byte ceiling.

    No model call: numbers, qualifiers and negation remain in their original
    sentences. Selection considers the entire page rather than its opening.
    """
    seen = seen if seen is not None else set()
    candidates, local_seen = [], set()
    # Keep qualifications with the statement they qualify, rather than selecting
    # a positive sentence while silently dropping its immediately following limit.
    lines = re.split(r'\n+|(?<=[。！？])', text)
    for index in range(len(lines)-1):
        if re.match(r'\s*(?:但是|但|除外|除非|不过|其中|仅限|不适用|不得)', lines[index+1]):
            lines[index] += lines[index+1]
            lines[index+1] = ''
    for line in lines:
        line = re.sub(r'\s+', ' ', line).strip()
        # Bound individual passages even on pages with no sentence punctuation.
        for start in range(0, len(line), 360):
            passage = line[start:start+360]
            key = normalise(passage)
            if not key or key in seen or key in local_seen:
                continue
            local_seen.add(key)
            coverage = {i for i, group in enumerate(required_terms)
                        if any(normalise(term) in key for term in group.split('|') if normalise(term))}
            candidates.append((len(candidates), passage, key, coverage))
    selected, covered, remaining = [], set(), max(0, int(max_bytes))
    while candidates and remaining > 0:
        best = max(candidates, key=lambda item: (
            len(item[3] - covered), len(item[3]),
            bool(re.search(r'\d|不得|除外|但是|不适用', item[1])), -item[0]))
        candidates.remove(best)
        if selected and required_terms and not best[3]:
            break
        cost = len(best[1].encode('utf-8')) + (1 if selected else 0)
        if cost > remaining:
            continue
        selected.append(best)
        covered.update(best[3]); remaining -= cost; seen.add(best[2])
    return '\n'.join(item[1] for item in sorted(selected))


def page_excerpt(html, required_terms):
    soup = BeautifulSoup(html, 'html.parser')
    dates = [node.get('content', '') for node in soup.select(
        'meta[property="article:published_time"],meta[name="pubdate"],meta[name="lastmod"]')]
    for node in soup.select('script,style,noscript,nav,footer,header,aside,form'):
        node.decompose()
    root = soup.find('main') or soup.find('article') or soup.body or soup
    # Keep table cells together so values retain their row labels and units.
    for row in root.select('tr'):
        row.replace_with(soup.new_string(' | '.join(row.stripped_strings)+'\n'))
    text = root.get_text('\n', strip=True)
    date_text = '\n'.join('页面日期字段：'+date[:100] for date in dates[:2] if date)
    return date_text + ('\n' if date_text else '') + evidence_excerpt(text, required_terms, 4000)


def pack_web_context(pages, required_terms, retrieved_at, max_bytes=7000, limit=5):
    """Share a bounded evidence budget across distinct sources and topic groups."""
    sources, blocks, seen_urls, seen_passages = [], [], set(), set()
    remaining = max(0, min(int(max_bytes), 12000))
    pages = [item for item in pages if item]
    for position, (title, url, excerpt) in enumerate(pages):
        if len(sources) >= limit or url in seen_urls:
            continue
        seen_urls.add(url)
        dates = re.findall(r'^页面日期字段：[^\n]{1,100}', excerpt, re.M)[:2]
        date_text = '\n'.join(dates)
        header = (f'[WEB:{len(sources)+1}] {title[:240]}\n网址：{url}\n检索时间：{retrieved_at}\n'
                  + (date_text+'\n' if date_text else '') + '公开内容节选：')
        excerpt = re.sub(r'^页面日期字段：[^\n]*\n?', '', excerpt, flags=re.M)
        overhead = len(header.encode('utf-8')) + (2 if blocks else 0)
        share = min(4000, max(900, (remaining-overhead)//max(1, min(limit-len(sources), len(pages)-position))))
        passage = evidence_excerpt(excerpt, required_terms, min(share, remaining-overhead), seen_passages)
        if not passage:
            continue
        block = header + passage
        remaining -= len(block.encode('utf-8')) + (2 if blocks else 0)
        blocks.append(block)
        sources.append({'id': f'web-{len(sources)+1}', 'title': title, 'source': url, 'url': url,
                        'source_type': 'public_web', 'retrieved_at': retrieved_at})
    return '\n\n'.join(blocks), sources


async def _general_web_context_impl(question: str, limit: int = 5, *, plan=None, max_bytes=None):
    plan = plan or default_plan(question)
    if max_bytes is None:
        max_bytes = evidence_budget(question, plan)
    terms = (plan.get('required_terms') or [])[:3]
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
    pages.sort(key=lambda item: (item is None, not any(((urlparse(item[1]).hostname or '') == domain or (urlparse(item[1]).hostname or '').endswith('.'+domain)) for domain in domains) if item else True))
    text, sources = pack_web_context(pages, terms, retrieved_at, max_bytes, limit)
    warning = '' if sources else '联网检索未获得与问题相关的可用资料，无法据此核验实时信息'
    if sources and not relevant(text, terms):
        warning = '当前资料节选未覆盖全部检索要点，请补充来源或缩小单次问题范围'
    return text, sources, warning


async def general_web_context(question: str, limit: int = 5, *, plan=None, max_bytes=None):
    try:
        return await asyncio.wait_for(_general_web_context_impl(question, limit, plan=plan, max_bytes=max_bytes), timeout=45)
    except asyncio.TimeoutError:
        return "", [], "联网检索超时，无法据此核验实时信息"
