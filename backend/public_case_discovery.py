"""Bounded open-web judgment discovery; snippets are leads, never evidence."""
from __future__ import annotations

import asyncio
import re
from urllib.parse import quote_plus, urljoin, urlsplit, parse_qs
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from .public_web_search import public_get, evidence_excerpt, relevant
from .public_case_transport import case_proxy


def parse_page(title, url, html, terms):
    from .public_case_web import _CASE_NUMBER_RE, _holding, _infer_court, _authority_type, adjudicated_facts, judgment_disposition
    soup = BeautifulSoup(html, 'lxml')
    for node in soup.select('script,style,nav,footer,header,aside,form'):
        node.decompose()
    root = soup.select_one('.mw-parser-output') or soup.find('article') or soup.find('main') or soup.body or soup
    body = root.get_text('\n', strip=True)
    # Wikisource spaces headings as separate nodes; normalize only whitespace.
    body = re.sub(r'[ \t\u3000]+', ' ', body)
    # Compilation articles contain different cases; never attach the first
    # number to all subsequent court quotations.
    if len(set(_CASE_NUMBER_RE.findall(body))) > 1 and (len(re.findall(r'案例[一二三四五六七八九十0-9]+', body)) > 1 or body.count('案件来源') > 1):
        return None
    heading = soup.find('h1')
    if heading and heading.get_text(strip=True):
        title = heading.get_text(' ', strip=True)
    number = _CASE_NUMBER_RE.search(title) or _CASE_NUMBER_RE.search(body[:5000])
    holding = _holding(body)
    if not number or not holding:
        return None
    court_match = re.search(r'最高人民法院|[\u4e00-\u9fff]{2,12}(?:高级|中级)人民法院', body[:2500])
    court = court_match.group(0) if court_match else _infer_court(title, {}, body)
    host = (urlsplit(url).hostname or '').lower()
    archive = host == 'zh.wikisource.org'
    official = host.endswith(('.court.gov.cn', '.chinacourt.org')) or host in {'court.gov.cn', 'chinacourt.org'}
    return dict(title=title, case_number=number.group(0), court=court, year='',
                factual_summary='', adjudicated_facts=adjudicated_facts(body,terms), facts_text=evidence_excerpt(body.split('本院认为',1)[0],terms,10000), matched_excerpt=evidence_excerpt(holding, terms, 5000),
                holding=holding, holding_conclusion=holding[-1800:], disposition=judgment_disposition(body), source_url=url, source='维基文库（公开存档）' if archive else ('法院公开网页' if official else '公开网页转载（待核验）'),
                source_kind='wikisource' if archive else 'public_web', body_fetched=True,
                authority_type=_authority_type(court), remote_score=0.5, viewpoint='neutral',
                retrieved_by=['web_discovery'])


async def discover_cases(plan, *, limit=6, progress=None):
    groups = plan.get('required_term_groups') or []
    terms = [str(t) for g in groups for t in g]
    base = ' '.join(str(g[0]) for g in groups if g) or str(plan.get('core_issue', ''))[:180]
    path_queries=[q for p in plan.get('research_paths',[]) for q in p['queries']]
    queries = list(dict.fromkeys(path_queries + [str(q['query']) for q in plan.get('queries', [])] + [base+' 判决',base+' site:zh.wikisource.org']))[:4]
    runs, errors, candidates = ([], [], {}) if progress is None else (progress["retrieval_runs"], progress["errors"], {})
    completed = [] if progress is None else progress["cases"]
    from .public_case_web import _CASE_NUMBER_RE
    docket=_CASE_NUMBER_RE.fullmatch(str(plan.get('core_issue','')).strip())
    def recall(text):
        if docket:
            normalize=lambda value:re.sub(r'[\s（）()]','',value)
            return normalize(docket.group(0)) in normalize(text)
        return sum(relevant(text, [g]) for g in required) >= min(2, len(required))
    required = ['|'.join(str(t) for t in g) for g in groups if g]
    semaphore = asyncio.Semaphore(3)
    from .public_case_web import USER_AGENT
    from .public_case_transport import CaseRoutes
    client = CaseRoutes({'Accept-Encoding':'identity','User-Agent':USER_AGENT})
    try:
        async def html_engine(query):
            try:
                async with semaphore:
                    response=await client.public_get('https://www.google.com/search?q='+quote_plus(query))
                soup=BeautifulSoup(response.content,'lxml'); found=[]
                for heading in soup.select('h3')[:12]:
                    anchor=heading.find_parent('a',href=True)
                    if not anchor:continue
                    href=anchor['href']
                    if href.startswith('/url?'):href=(parse_qs(urlsplit(href).query).get('q') or [''])[0]
                    if not href.startswith(('https://','http://')):continue
                    parent=anchor.parent
                    description=parent.get_text(' ',strip=True)
                    if recall(description):found.append((heading.get_text(' ',strip=True),href))
                return found
            except (httpx.HTTPError,ValueError):return []
        async def search(query):
            found = await html_engine(query)
            try:
                async with semaphore:
                    response = await client.public_get('https://cn.bing.com/search?format=rss&q='+quote_plus(query))
                root = ElementTree.fromstring(response.content)
                found += [(i.findtext('title') or '', i.findtext('link') or '') for i in root.findall('.//item')[:10]
                         if recall((i.findtext('title') or '')+' '+(i.findtext('description') or ''))]
            except (httpx.HTTPError, ValueError, ElementTree.ParseError) as exc:
                errors.append({'source': 'public_web', 'message': 'Bing 搜索失败：'+type(exc).__name__})
            if len(found) < 2:
                try:
                    async with semaphore:
                        response = await client.public_get('https://www.sogou.com/web?query='+quote_plus(query))
                    soup = BeautifulSoup(response.content, 'lxml')
                    for h in soup.select('h3')[:10]:
                        a = h.find('a', href=True)
                        if a and recall(h.parent.get_text(' ', strip=True)):
                            found.append((a.get_text(' ', strip=True), urljoin('https://www.sogou.com', a['href'])))
                except (httpx.HTTPError, ValueError) as exc:
                    errors.append({'source': 'public_web', 'message': '搜狗搜索失败：'+type(exc).__name__})
            runs.append({'source': 'public_web', 'query': query, 'result_count': len(found)})
            return found
        found = await asyncio.gather(*(search(q) for q in queries))
        for batch in found:
            for title, url in batch:
                if url.startswith(('https://', 'http://')):
                    candidates.setdefault(url, title)
        async def fetch(url, title):
            try:
                async with semaphore:
                    response = await client.public_get(url)
                if 'html' not in response.headers.get('content-type', ''):
                    return None
                parsed = parse_page(title, str(response.request.url), response.content, terms)
                if parsed:
                    completed.append(parsed)
                return parsed
            except (httpx.HTTPError, ValueError) as exc:
                errors.append({'source': 'public_web', 'message': '候选正文未取得：'+type(exc).__name__})
                return None
        pages = await asyncio.gather(*(fetch(url, title) for url, title in list(candidates.items())[:12]))
    finally:
        await client.aclose()
    return {'cases': completed, 'retrieval_runs': runs, 'errors': errors}
