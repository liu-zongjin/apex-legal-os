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
                holding=holding, holding_conclusion=holding[-1800:], disposition=judgment_disposition(body), source_url=url, source='网络公开裁判文书案例数据库（公开存档）' if archive else ('法院公开网页' if official else '公开网页转载（待核验）'),
                source_kind='wikisource' if archive else 'public_web', body_fetched=True,
                authority_type=_authority_type(court), remote_score=0.5, viewpoint='neutral',
                retrieved_by=['web_discovery'])


def parse_360_results(html, with_snippets=False):
    """Read ordinary indexed links; never use the engine's AI answer as proof."""
    soup=BeautifulSoup(html, 'lxml')
    found=[]
    for heading in soup.select('.res-list h3')[:12]:
        anchor=heading.find('a',href=True)
        if not anchor:continue
        href=urljoin('https://www.so.com',anchor['href'])
        host=(urlsplit(href).hostname or '').lower()
        if not href.startswith(('https://','http://')) or host in {'ai.so.com','wenku.so.com','image.so.com','video.so.com'}:continue
        if '视频' in heading.get_text():continue
        row=(heading.get_text(' ',strip=True),href)
        if with_snippets:
            block=heading.find_parent('li',class_='res-list') or heading.parent
            row+=(block.get_text(' ',strip=True)[:1000],)
        found.append(row)
    return found


def rank_web_links(found, plan):
    from .case_hybrid import bm25
    query=str(plan.get('core_issue') or plan.get('original_query') or '')
    query+=' '+' '.join(t for group in plan.get('required_term_groups',[]) for t in group)
    scores=bm25(query,[row[0]+' '+(row[2] if len(row)>2 else '') for row in found])
    return [found[i][:2] for i in sorted(range(len(found)),key=lambda i:(-scores[i],i))]


def article_case_leads(html, url, limit=3):
    """A compilation is a source of identifiers, never a combined judgment."""
    from .public_case_web import _CASE_NUMBER_RE
    soup = BeautifulSoup(html, 'lxml')
    for node in soup.select('script,style,nav,footer,header,aside,form'):
        node.decompose()
    body = (soup.find('article') or soup.find('main') or soup.body or soup).get_text(' ', strip=True)
    leads = {}
    for match in _CASE_NUMBER_RE.finditer(body):
        number = match.group(0)
        raw_number = number
        if not re.search(r'[\u4e00-\u9fff]{2}',number):continue
        # Normalize an explicit court prefix, never guess a missing institution.
        prefix=body[max(0,match.start()-12):match.start()]
        if re.search(r'(?:最高院|最高人民法院|最高法)\s*$',prefix) and re.match(r'[（(]\d{4}[）)]民',number):
            number=re.sub(r'^([（(]\d{4}[）)])',r'\1最高法',number)
        key = re.sub(r'[\s（）()]', '', number)
        leads.setdefault(key, {'case_number': number, 'source_url': url,'raw_citation':raw_number,'context':body[max(0,match.start()-180):match.end()+450]})
        if len(leads) >= min(12,max(1,limit)):
            break
    return list(leads.values())


async def discover_cases(plan, *, limit=6, progress=None):
    groups = plan.get('required_term_groups') or []
    terms = [str(t) for g in groups for t in g]
    base = ' '.join(str(g[0]) for g in groups if g) or str(plan.get('core_issue', ''))[:180]
    from .public_case_web import build_wikisource_queries
    path_queries=[r['query'] for r in build_wikisource_queries(plan)]
    queries = list(dict.fromkeys(path_queries + [str(q['query']) for q in plan.get('queries', [])] + [base+' 判决',base+' site:zh.wikisource.org']))[:4]
    runs, errors, candidates = ([], [], {}) if progress is None else (progress["retrieval_runs"], progress["errors"], {})
    completed = [] if progress is None else progress["cases"]
    leads = {}
    lead_jobs=[]
    archive_semaphore=asyncio.Semaphore(1)
    from .public_case_web import _CASE_NUMBER_RE
    docket=_CASE_NUMBER_RE.fullmatch(str(plan.get('core_issue','')).strip())
    def recall(text):
        if docket:
            normalize=lambda value:re.sub(r'[\s（）()]','',value)
            return normalize(docket.group(0)) in normalize(text)
        # Search headings often contain only party names. In semantic mode the
        # executed query supplies recall context; full court text supplies proof.
        if plan.get('semantic_review'):
            return True
        return sum(relevant(text, [g]) for g in required) >= min(2, len(required))
    required = ['|'.join(str(t) for t in g) for g in groups if g]
    semaphore = asyncio.Semaphore(3)
    from .public_case_web import USER_AGENT
    from .public_case_transport import CaseRoutes
    client = CaseRoutes({'Accept-Encoding':'identity','User-Agent':USER_AGENT})
    try:
        async def html_engine(query, exact=False):
            try:
                async with semaphore:
                    response=await client.public_get('https://www.google.com/search?q='+quote_plus(query))
                soup=BeautifulSoup(response.content,'lxml'); found=[]
                if not soup.select('h3') and ('enablejs' in response.text or '/sorry/' in str(response.request.url)):
                    errors.append({'source':'public_web','message':'Google 未返回可读取的搜索结果（需 JavaScript 或人工验证），未将其视为无案例。'})
                for heading in soup.select('h3')[:12]:
                    anchor=heading.find_parent('a',href=True)
                    if not anchor:continue
                    href=anchor['href']
                    if href.startswith('/url?'):href=(parse_qs(urlsplit(href).query).get('q') or [''])[0]
                    if not href.startswith(('https://','http://')):continue
                    parent=anchor.parent
                    description=parent.get_text(' ',strip=True)
                    if exact or recall(description):found.append((heading.get_text(' ',strip=True),href))
                return found
            except (httpx.HTTPError,ValueError) as exc:
                errors.append({'source':'public_web','message':'Google 搜索失败：'+type(exc).__name__})
                return []
        async def search(query, exact=False):
            engines=[]
            try:
                async with semaphore:
                    response=await client.public_get('https://www.so.com/s?q='+quote_plus(query))
                found=parse_360_results(response.content,with_snippets=True)
                engines.append('360')
            except (httpx.HTTPError,ValueError) as exc:
                errors.append({'source':'public_web','message':'360 搜索失败：'+type(exc).__name__})
                found=[]
            if len(found)<3:
                found+=await html_engine(query,exact)
                engines.append('google')
            try:
                if len(found)>=3:
                    runs.append({'source':'public_web','query':query,'result_count':len(found),'engines':engines})
                    return found
                engines.append('bing_rss')
                async with semaphore:
                    response = await client.public_get('https://cn.bing.com/search?format=rss&q='+quote_plus(query))
                root = ElementTree.fromstring(response.content)
                found += [(i.findtext('title') or '', i.findtext('link') or '') for i in root.findall('.//item')[:10]
                         if exact or recall((i.findtext('title') or '')+' '+(i.findtext('description') or ''))]
            except (httpx.HTTPError, ValueError, ElementTree.ParseError) as exc:
                errors.append({'source': 'public_web', 'message': 'Bing 搜索失败：'+type(exc).__name__})
            if len(found) < 2:
                try:
                    async with semaphore:
                        response = await client.public_get('https://www.sogou.com/web?query='+quote_plus(query))
                    soup = BeautifulSoup(response.content, 'lxml')
                    for h in soup.select('h3')[:10]:
                        a = h.find('a', href=True)
                        if a and (exact or recall(h.parent.get_text(' ', strip=True))):
                            found.append((a.get_text(' ', strip=True), urljoin('https://www.sogou.com', a['href'])))
                except (httpx.HTTPError, ValueError) as exc:
                    errors.append({'source': 'public_web', 'message': '搜狗搜索失败：'+type(exc).__name__})
            runs.append({'source': 'public_web', 'query': query, 'result_count': len(found),'engines':engines})
            return found
        async def fetch(url, title, expected_number=None):
            try:
                async with semaphore:
                    response = await client.public_get(url)
                if 'html' not in response.headers.get('content-type', ''):
                    return None
                parsed = parse_page(title, str(response.request.url), response.content, terms)
                if parsed:
                    normalize = lambda n: re.sub(r'[\s（）()]', '', n)
                    if expected_number and normalize(parsed['case_number']) != normalize(expected_number):
                        return None
                    completed.append(parsed)
                elif not expected_number:
                    for lead in article_case_leads(response.content, str(response.request.url),limit=12):
                        key = re.sub(r'[\s（）()]', '', lead['case_number'])
                        if key not in leads and len(leads) < 24:leads[key]=lead
                return parsed
            except (httpx.HTTPError, ValueError) as exc:
                errors.append({'source': 'public_web', 'message': '候选正文未取得：'+type(exc).__name__})
                return None
        # One bounded hop only. Exact matching prevents a similar docket from
        # replacing the cited decision. No model-generated numbers enter here.
        async def follow_web(lead):
            number = lead['case_number']
            found = rank_web_links(await search(number+' 判决书', exact=True),plan)
            for run in runs:
                if run['query'] == number+' 判决书':
                    run.update(lead_source_url=lead['source_url'], lead_case_number=number,lead_context=lead['context'])
            fresh = []
            for title, url in found:
                if not url.startswith(('https://', 'http://')) or url in candidates:
                    continue
                candidates[url] = title
                fresh.append((url, title))
                if len(fresh) >= 4:
                    break
            await asyncio.gather(*(fetch(url, title, number) for url, title in fresh))
        async def follow_archive(lead):
            from .public_case_web import _search_wikisource_cases
            from .public_case_planning import generic_case_plan
            partial={'cases':[],'retrieval_runs':[],'errors':[]}
            try:
                async with archive_semaphore:
                    await _search_wikisource_cases(generic_case_plan(lead['case_number']),limit=4,progress=partial)
            finally:
                normalize=lambda n:re.sub(r'[\s（）()]','',n)
                for case in partial['cases']:
                    if case.get('body_fetched') and normalize(case.get('case_number',''))==normalize(lead['case_number']):completed.append(case)
                for run in partial['retrieval_runs']:
                    run.update(lead_source_url=lead['source_url'],lead_case_number=lead['case_number'])
                runs.extend(partial['retrieval_runs']);errors.extend(partial['errors'])

        async def follow(lead):
            await asyncio.gather(follow_web(lead),follow_archive(lead))
        async def search_and_read(query):
            found=rank_web_links(await search(query),plan)
            fresh=[]
            for title,url in found:
                if not url.startswith(('https://','http://')) or url in candidates:continue
                if len(candidates)>=12 or len(fresh)>=3:break
                candidates[url]=title;fresh.append((url,title))
            await asyncio.gather(*(fetch(url,title) for url,title in fresh))
        await asyncio.gather(*(search_and_read(q) for q in queries))
        if plan.get('semantic_review') and leads:
            values=list(leads.values())
            ranked=rank_web_links([(lead['context'],str(i)) for i,lead in enumerate(values)],plan)
            lead_jobs.extend(asyncio.create_task(follow(values[int(i)])) for _,i in ranked[:3])
            await asyncio.gather(*lead_jobs)
    finally:
        for task in lead_jobs:
            if not task.done():task.cancel()
        if lead_jobs:await asyncio.gather(*lead_jobs,return_exceptions=True)
        await client.aclose()
    return {'cases': completed, 'retrieval_runs': runs, 'errors': errors}
