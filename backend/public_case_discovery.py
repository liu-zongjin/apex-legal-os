"""Bounded open-web judgment discovery; snippets are leads, never evidence."""
from __future__ import annotations

import asyncio
import re
import time
from urllib.parse import quote_plus, urljoin, urlsplit, parse_qs
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from .public_web_search import evidence_excerpt, relevant


# Search targets are discovery hints. Publication on any of these hosts does
# not establish that a page is a judgment, nor that it supports the proposition.
SOURCE_GROUPS = (
    ('court', ('court.gov.cn', 'gzcourt.gov.cn', 'sdcourt.gov.cn', 'chinacourt.org')),
    ('archive', ('zh.wikisource.org', 'cn.govopendata.com', 'songer.datasn.com')),
    ('practice', ('szlawyers.com', 'sfj.yueyang.gov.cn', 'yzwqw.com', 'diaoshanghai.com')),
    ('media', ('thepaper.cn', 'news.ifeng.com', 'minghui.org')),
)
INDEXED_ARCHIVES = ('wenshu.nlaw.org', 'chinalawyer.co')


def _site_matches(url, sites):
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or '').lower().rstrip('.')
    except ValueError:
        return False
    return parsed.scheme in {'https', 'http'} and any(host == site or host.endswith('.' + site) for site in sites)


def _source_group(url):
    if _site_matches(url, INDEXED_ARCHIVES):
        return 'archive'
    return next((group for group, sites in SOURCE_GROUPS if _site_matches(url, sites)), '')


def _docket_key(number):
    return re.sub(r'[\s（）()]', '', number)


def supplied_document_urls(question):
    """Only URLs present in the original request may enter the direct-read lane."""
    links = []
    for value in re.findall(r'https?://[^\s<>"`、。，；！？（）【】]+', question):
        url = value.rstrip('.,;!?)]')
        try:
            target = urlsplit(url)
            if target.username is not None or target.port not in (None, 80, 443) or not target.hostname:
                continue
        except ValueError:
            continue
        if len(url) <= 2048 and url not in links:
            links.append(url)
            if len(links) == 3:
                break
    return links


def parse_page(title, url, html, terms, *, require_caption=False):
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
    # Prefer the document's own caption. A search title or article heading
    # can name a different decision than the page actually reproduces.
    caption = re.search(r'([\u4e00-\u9fff]{2,30}人民法院)\s*(?:[民刑行]\s*[事政]\s*)?(?:判\s*决|裁\s*定)\s*书\s*', body[:2200])
    number = _CASE_NUMBER_RE.match(body, caption.end()) if caption else None
    group = _source_group(url)
    disposition = judgment_disposition(body)
    if (group or require_caption) and (not number or not disposition):
        # Official case digests, commentary and quotes still contribute leads.
        # Require the court/document caption and its own docket on these lanes.
        return None
    number = number or _CASE_NUMBER_RE.search(body[:2500])
    holding = _holding(body)
    if not number or not holding:
        return None
    court_match = re.search(r'最高人民法院|[\u4e00-\u9fff]{2,12}(?:高级|中级)人民法院', body[:2500])
    court = caption.group(1) if caption else court_match.group(0) if court_match else _infer_court(title, {}, body)
    host = (urlsplit(url).hostname or '').lower()
    archive = host == 'zh.wikisource.org'
    official = group == 'court' and not _site_matches(url, ('chinacourt.org',))
    source = ('网络公开裁判文书案例数据库（公开存档）' if archive else '法院公开裁判文书' if official
              else '裁判文书公开存档（转载）' if group == 'archive' else '公开网页转载（待核验）')
    return dict(title=title, case_number=number.group(0), court=court, year='',
                factual_summary='', adjudicated_facts=adjudicated_facts(body,terms), facts_text=evidence_excerpt(body.split('本院认为',1)[0],terms,10000), matched_excerpt=evidence_excerpt(holding, terms, 5000),
                holding=holding, holding_conclusion=holding[-1800:], disposition=disposition, source_url=url, source=source,
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
        # Normal results expose the destination separately from 360's opaque
        # click-tracking URL. Domain filtering must see the destination.
        direct = anchor.get('data-mdurl', '')
        href=urljoin('https://www.so.com', direct if direct.startswith(('https://', 'http://')) else anchor['href'])
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
    soup = BeautifulSoup(html, 'lxml')
    for node in soup.select('script,style,nav,footer,header,aside,form'):
        node.decompose()
    root = soup.find('article') or soup.find('main') or soup.body or soup
    leads = _text_case_leads(root.get_text(' ', strip=True), url, limit)
    for anchor in root.find_all('a', href=True):
        label = anchor.get_text(' ', strip=True)
        if not re.search(r'判决书|裁定书|裁判文书|查看原文|全文', label):
            continue
        destination = urljoin(url, anchor['href'])
        if destination == url or _source_group(destination) not in {'court', 'archive'}:
            continue
        for lead in leads:
            if len(leads) == 1 or _docket_key(lead['case_number']) in _docket_key(label):
                links = lead.setdefault('document_links', [])
                if len(links) < 2 and destination not in links:
                    links.append(destination)
    return leads


def _text_case_leads(body, url, limit):
    from .public_case_web import _CASE_NUMBER_RE
    leads = {}
    for match in _CASE_NUMBER_RE.finditer(body):
        number = match.group(0)
        raw_number = number
        if not re.search(r'[\u4e00-\u9fff]{2}',number):continue
        # Normalize an explicit court prefix, never guess a missing institution.
        prefix=body[max(0,match.start()-12):match.start()]
        if re.search(r'(?:最高院|最高人民法院|最高法)\s*$',prefix) and re.match(r'[（(]\d{4}[）)]民',number):
            number=re.sub(r'^([（(]\d{4}[）)])',r'\1最高法',number)
        key = _docket_key(number)
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
    deadline = time.monotonic() + max(5, min(70, float(plan.get('source_budget', 70))))
    leads = {}
    lead_jobs=[]
    discovery = None
    broad_reads = 0
    archive_semaphore=asyncio.Semaphore(1)
    from .public_case_web import _CASE_NUMBER_RE
    docket=_CASE_NUMBER_RE.fullmatch(str(plan.get('core_issue','')).strip())
    def recall(text):
        if docket:
            return _docket_key(docket.group(0)) in _docket_key(text)
        # Search headings often contain only party names. In semantic mode the
        # executed query supplies recall context; full court text supplies proof.
        if plan.get('semantic_review'):
            return True
        return sum(relevant(text, [g]) for g in required) >= min(2, len(required))
    required = ['|'.join(str(t) for t in g) for g in groups if g]
    semaphore = asyncio.Semaphore(3)
    scoped_semaphore = asyncio.Semaphore(2)
    document_semaphore = asyncio.Semaphore(4)
    linked_document_semaphore = asyncio.Semaphore(2)
    from .public_case_web import USER_AGENT
    from .public_case_transport import CaseRoutes
    client = CaseRoutes({'Accept-Encoding':'identity','User-Agent':USER_AGENT})
    try:
        async def request(url, gate, search_deadline):
            async def perform():
                async with gate:
                    if gate is scoped_semaphore:
                        return await asyncio.wait_for(client.public_get(url), timeout=5)
                    return await client.public_get(url)
            return await asyncio.wait_for(perform(), timeout=max(0, search_deadline - time.monotonic()))

        async def html_engine(query, exact, gate, search_deadline):
            try:
                response=await request('https://www.google.com/search?q='+quote_plus(query), gate, search_deadline)
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
                    if exact or recall(description):found.append((heading.get_text(' ',strip=True),href,description[:1000]))
                return found
            except (asyncio.TimeoutError,httpx.HTTPError,ValueError) as exc:
                errors.append({'source':'public_web','message':'Google 搜索失败：'+type(exc).__name__})
                return []
        async def search(query, exact=False, *, sites=(), gate=semaphore):
            engines=[]
            search_deadline = min(deadline, time.monotonic() + 26)
            def in_scope(rows):
                return [row for row in rows if not sites or _site_matches(row[1], sites)]

            def record(found):
                run = {'source':'public_web','query':query,'result_count':len(found),'engines':engines}
                if sites:
                    run['target_sites'] = list(sites)
                    run['returned_sites'] = sorted({urlsplit(row[1]).hostname for row in found})
                runs.append(run)
                return found

            try:
                response=await request('https://www.so.com/s?q='+quote_plus(query), gate, search_deadline)
                found=in_scope(parse_360_results(response.content,with_snippets=True))
                engines.append('360')
            except (asyncio.TimeoutError,httpx.HTTPError,ValueError) as exc:
                errors.append({'source':'public_web','message':'360 搜索失败：'+type(exc).__name__})
                found=[]
            if len(found)<3:
                found+=in_scope(await html_engine(query,exact,gate,search_deadline))
                engines.append('google')
            try:
                if len(found)>=3 and (not sites or len({urlsplit(row[1]).hostname for row in found}) >= 2):
                    return record(found)
                engines.append('bing_rss')
                response = await request('https://cn.bing.com/search?format=rss&q='+quote_plus(query), gate, search_deadline)
                root = ElementTree.fromstring(response.content)
                found += in_scope([(i.findtext('title') or '', i.findtext('link') or '', i.findtext('description') or '') for i in root.findall('.//item')[:10]
                         if exact or recall((i.findtext('title') or '')+' '+(i.findtext('description') or ''))])
            except (asyncio.TimeoutError, httpx.HTTPError, ValueError, ElementTree.ParseError) as exc:
                errors.append({'source': 'public_web', 'message': 'Bing 搜索失败：'+type(exc).__name__})
            if len(found) < 2 and not sites:
                try:
                    response = await request('https://www.sogou.com/web?query='+quote_plus(query), gate, search_deadline)
                    soup = BeautifulSoup(response.content, 'lxml')
                    for h in soup.select('h3')[:10]:
                        a = h.find('a', href=True)
                        if a and (exact or recall(h.parent.get_text(' ', strip=True))):
                            found.append((a.get_text(' ', strip=True), urljoin('https://www.sogou.com', a['href'])))
                except (asyncio.TimeoutError, httpx.HTTPError, ValueError) as exc:
                    errors.append({'source': 'public_web', 'message': '搜狗搜索失败：'+type(exc).__name__})
            return record(found)
        def remember(lead):
            key = _docket_key(lead['case_number'])
            prior = leads.get(key)
            if (not prior and len(leads) < 24) or (prior and prior.get('from_snippet') and not lead.get('from_snippet')):
                leads[key] = lead

        async def fetch(url, title, expected_number=None, *, explicit=False, strict_source=False):
            def unread(reason, retryable=False):
                errors.append({'source':'public_web', 'message':'候选正文未取得：'+reason,
                               'document_url':url, 'document_title':title,
                               'document_number':expected_number, 'retryable':retryable,
                               'document_explicit':explicit, 'document_strict':strict_source})

            try:
                async with (linked_document_semaphore if expected_number else document_semaphore):
                    response = await client.public_get(url, deadline=deadline, document=True)
                if 'html' not in response.headers.get('content-type', ''):
                    if explicit:unread('当前仅能读取 HTML 裁判正文')
                    return None
                parsed = parse_page(title, str(response.request.url), response.content, terms,
                                    require_caption=explicit or strict_source or expected_number is not None)
                if parsed:
                    if expected_number and _docket_key(parsed['case_number']) != _docket_key(expected_number):
                        unread('页面案号与引用案号不一致')
                        return None
                    completed.append(parsed)
                elif not expected_number:
                    for lead in article_case_leads(response.content, str(response.request.url),limit=12):
                        remember(lead)
                if not parsed and (explicit or expected_number):
                    unread('页面未识别到完整裁判正文')
                return parsed
            except (asyncio.CancelledError, asyncio.TimeoutError, httpx.HTTPError, ValueError) as exc:
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                transient = isinstance(exc, (asyncio.CancelledError, TimeoutError, httpx.TransportError)) or status in (408, 500, 502, 503, 504)
                unread(f'HTTP {status}' if status else type(exc).__name__, transient)
                if isinstance(exc, asyncio.CancelledError):
                    raise
                return None

        def remember_snippets(rows, urls):
            for row in rows:
                if row[1] in urls:
                    for lead in _text_case_leads(' '.join((row[0], row[2] if len(row) > 2 else '')), row[1], 2):
                        remember(dict(lead, from_snippet=True))
        # One bounded hop only. Exact matching prevents a similar docket from
        # replacing the cited decision. No model-generated numbers enter here.
        async def follow_web(lead):
            number = lead['case_number']
            direct = [url for url in lead.get('document_links', []) if url not in candidates]
            if direct:
                candidates.update((url, number) for url in direct)
                read = await asyncio.gather(*(fetch(url, number, number) for url in direct))
                runs.append({'source':'public_web', 'query':number, 'result_count':sum(bool(case) for case in read),
                             'lead_source_url':lead['source_url'], 'lead_case_number':number, 'engines':['linked_document']})
                if any(read):
                    return
            found = rank_web_links(await search(number+' 判决书', exact=True),plan)
            for run in runs:
                if run['query'] == number+' 判决书':
                    run.update(lead_source_url=lead['source_url'], lead_case_number=number,lead_context=lead['context'],
                               lead_from_snippet=bool(lead.get('from_snippet')))
            fresh = []
            for title, url in found:
                if not url.startswith(('https://', 'http://')) or url in candidates:
                    continue
                candidates[url] = title
                fresh.append((url, title))
                if len(fresh) >= 4 - len(direct):
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
                for case in partial['cases']:
                    if case.get('body_fetched') and _docket_key(case.get('case_number',''))==_docket_key(lead['case_number']):completed.append(case)
                for run in partial['retrieval_runs']:
                    run.update(lead_source_url=lead['source_url'],lead_case_number=lead['case_number'],
                               lead_from_snippet=bool(lead.get('from_snippet')))
                runs.extend(partial['retrieval_runs']);errors.extend(partial['errors'])

        async def follow(lead):
            await asyncio.gather(follow_web(lead),follow_archive(lead))
        async def search_and_read(query):
            nonlocal broad_reads
            results = await search(query)
            found=rank_web_links(results,plan)
            fresh=[]
            for title,url in found:
                if not url.startswith(('https://','http://')) or url in candidates:continue
                if broad_reads>=12 or len(fresh)>=3:break
                broad_reads += 1
                candidates[url]=title;fresh.append((url,title))
            remember_snippets(results, {url for url, _ in fresh})
            await asyncio.gather(*(fetch(url,title,docket.group(0) if docket else None) for url,title in fresh))
        async def read_source_group(group, sites, index):
            # Use different angles across groups without adding more requests.
            seed = re.sub(r'\bsite:\S+', '', queries[index % len(queries)] if queries else base).strip() or base
            site_terms = ' OR '.join('site:' + site for site in sites)
            query = seed + (' (' + site_terms + ')' if len(sites) > 1 else ' ' + site_terms)
            results = await search(query, exact=True, sites=sites, gate=scoped_semaphore)
            fresh = []
            hosts = set()
            for title, url in rank_web_links(results, plan):
                host = re.sub(r'^(www|m)\.', '', urlsplit(url).hostname.lower().rstrip('.'))
                if url in candidates or (len(sites) > 1 and host in hosts):
                    continue
                candidates[url] = title
                hosts.add(host)
                fresh.append((url, title))
                if len(fresh) == (1 if len(sites) == 1 else 2):
                    break
            remember_snippets(results, {url for url, _ in fresh})
            await asyncio.gather(*(fetch(url, title, docket.group(0) if docket else None) for url, title in fresh))

        async def read_seed(url, title, number, origin, *, strict_source=False):
            parsed = await fetch(url, title, number, explicit=origin == 'supplied_document', strict_source=strict_source)
            runs.append({'source':'public_web', 'query':number or title, 'result_count':int(bool(parsed)),
                         'engines':[origin], 'document_url':url})

        async def read_index(rows, engine, query, sites=()):
            results = [(title, url, snippet) for title, url, snippet in rows
                       if not sites or _site_matches(url, sites)]
            ranked = rank_web_links(results, plan)
            snippets = {url: snippet for _, url, snippet in results}
            runs.append({'source': 'public_web', 'query': query, 'engines': [engine],
                         'target_sites': list(sites), 'result_count': len(results),
                         'returned_sites': sorted({urlsplit(row[1]).hostname for row in results}),
                         'search_hints': [{'title': title[:140], 'snippet': snippets[url][:220]}
                                          for title, url in ranked[:3]]})
            # Preserve the best citation leads independently of the document
            # slots, and prefer apparent judgment pages over search commentary.
            remember_snippets(results, {url for _, url in ranked[:8]})
            ranked.sort(key=lambda row: not (_CASE_NUMBER_RE.search(row[0]) or '判决书' in row[0] or '裁定书' in row[0]))
            fresh = []
            for title, url in ranked:
                if url in candidates:
                    continue
                candidates[url] = title
                fresh.append((url, title))
                if len(fresh) == 4:
                    break
            await asyncio.gather(*(fetch(url, title, docket.group(0) if docket else None, strict_source=True) for url, title in fresh))

        async def search_indexes():
            from .public_case_indexes import search_exa

            issue = str(plan.get('core_issue') or '')
            # A semantic index can use the whole proposition as an anchor.
            # The short engine queries are alternative ways to discover it.
            # On follow-up, put the new vocabulary before the repeated issue.
            indexed_queries = [*queries, issue] if plan.get('indexed_follow_up') else [issue, *queries]
            clean_queries = list(dict.fromkeys(query for query in
                (re.sub(r'\bsite:\S+|https?://\S+', '', q).strip()[:220] for q in indexed_queries) if query))
            if not clean_queries:
                return
            sites = tuple(site for group, hosts in SOURCE_GROUPS if group in {'court', 'archive'} for site in hosts) + INDEXED_ARCHIVES
            try:
                rows = await asyncio.wait_for(search_exa(clean_queries, sites), timeout=min(16, max(0.01, deadline - time.monotonic())))
            except (httpx.HTTPError, ValueError, asyncio.TimeoutError) as exc:
                status = f'HTTP {exc.response.status_code}' if isinstance(exc, httpx.HTTPStatusError) else str(exc) if isinstance(exc, ValueError) and str(exc).startswith('Exa ') else type(exc).__name__
                errors.append({'source':'public_web', 'message':f'公开索引搜索未完成（{status}）'})
                return
            await read_index(rows, 'Exa', clean_queries[0], sites)

        seeds = []
        for url in plan.get('document_urls', [])[:3]:
            candidates[url] = '用户提供的文书链接'
            seeds.append(read_seed(url, candidates[url], docket.group(0) if docket else None, 'supplied_document'))
        for item in plan.get('retry_documents', [])[:3]:
            url = item['document_url']
            if url in candidates:
                continue
            candidates[url] = item['document_title']
            seeds.append(read_seed(url, candidates[url], item.get('document_number'), 'retry_document',
                                   strict_source=item.get('document_strict', False)))
        # Wikisource already has a native discovery lane. Query the other
        # archives individually; some engines apply only one site: operator.
        scopes = [(group, scope) for group, sites in SOURCE_GROUPS
                  for scope in ([(site,) for site in sites if site != 'zh.wikisource.org'] if group == 'archive' else [sites])]
        indexes = [search_indexes()] if plan.get('indexed_web_discovery') else []
        discovery = asyncio.gather(*seeds, *indexes, *(search_and_read(q) for q in queries),
                                   *(read_source_group(group, sites, i) for i, (group, sites) in enumerate(scopes)))
        # Begin exact-docket recovery while slower pages are still being read.
        # The source budget remains shared, but pending body reads cannot
        # consume the entire window for following already discovered leads.
        await asyncio.wait({discovery}, timeout=max(0, min(26, deadline - time.monotonic())))
        if plan.get('semantic_review') and leads:
            values=list(leads.values())
            ranked=rank_web_links([(lead['context'],str(i)) for i,lead in enumerate(values)],plan)
            lead_jobs.extend(asyncio.create_task(follow(values[int(i)])) for _,i in ranked[:3])
        await asyncio.gather(discovery, *lead_jobs)
    finally:
        tasks = lead_jobs if discovery is None else [discovery, *lead_jobs]
        for task in tasks:
            if not task.done():task.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
        await client.aclose()
    return {'cases': completed, 'retrieval_runs': runs, 'errors': errors}
