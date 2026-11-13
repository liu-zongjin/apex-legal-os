"""Structured general web indexes used only to discover candidate URLs."""
from __future__ import annotations

import json
from urllib.parse import urlsplit

import httpx

from .public_case_transport import case_proxy


def _rows(value, link_key, text_key):
    if not isinstance(value, list):
        raise ValueError('搜索索引响应缺少结果列表')
    rows = []
    for row in value[:30]:
        if not isinstance(row, dict):
            continue
        title, url, text = row.get('title'), row.get(link_key), row.get(text_key, '')
        if not isinstance(title, str) or not isinstance(url, str) or not url.startswith(('https://', 'http://')):
            continue
        try:
            parsed = urlsplit(url)
            if len(url) > 2048 or not parsed.hostname or parsed.username is not None or parsed.port not in (None, 80, 443):
                continue
        except ValueError:
            continue
        rows.append((title[:300], url, text[:650] if isinstance(text, str) else ''))
    return rows


async def _post(endpoint, payload, headers):
    async with httpx.AsyncClient(proxy=case_proxy(), trust_env=False, timeout=httpx.Timeout(14, connect=5)) as client:
        async with client.stream('POST', endpoint, json=payload, headers=headers) as response:
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 512_000:
                    raise ValueError('搜索索引响应过大')
    return body.decode('utf-8')


async def search_exa(queries, sites):
    arguments = {'query': '中国大陆法院公开裁判文书：' + queries[0],
                 'additionalQueries': queries[1:4], 'includeDomains': list(sites),
                 'numResults': 20, 'type': 'auto', 'textMaxCharacters': 650}
    headers = {'Accept': 'application/json, text/event-stream'}
    raw = await _post('https://mcp.exa.ai/mcp?tools=web_search_advanced_exa',
                      {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                       'params': {'name': 'web_search_advanced_exa', 'arguments': arguments}}, headers)
    frames = [line[5:].strip() for line in raw.splitlines() if line.startswith('data:') and line[5:].strip()]
    for frame in frames or [raw]:
        data = json.loads(frame)
        if not isinstance(data, dict) or data.get('id') != 1:
            continue
        result = data.get('result')
        if not isinstance(result, dict) or result.get('isError'):
            # Do not echo remote messages, which may include setup instructions.
            raise ValueError('Exa 公开搜索不可用或达到请求上限')
        for part in result.get('content', []):
            if isinstance(part, dict) and part.get('type') == 'text':
                payload = json.loads(part.get('text', ''))
                if isinstance(payload, dict) and 'results' in payload:
                    return _rows(payload['results'], 'url', 'text')
    raise ValueError('Exa 公开搜索响应缺少结果')
