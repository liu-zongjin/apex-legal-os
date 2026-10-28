"""Pooled transports with request-local headers/cookies and background capacity."""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
import contextvars
import time
import weakref
import functools
import httpx
from .performance_monitor import measure_phase

_BACKGROUND = contextvars.ContextVar('stella_background_ai', default=False)
_POOLS = weakref.WeakKeyDictionary()
DELTA = contextvars.ContextVar('stella_answer_delta', default=None)
FINAL = contextvars.ContextVar('stella_final_answer', default=False)


def final_answer(function):
    @functools.wraps(function)
    async def wrapped(*args, **kwargs):
        token = FINAL.set(True)
        try: return await function(*args, **kwargs)
        finally: FINAL.reset(token)
    return wrapped


class BorrowedTransport(httpx.AsyncBaseTransport):
    def __init__(self, transport): self.transport = transport
    async def handle_async_request(self, request):
        return await self.transport.handle_async_request(request)
    async def aclose(self): pass  # Shutdown owns the pooled sockets.


@asynccontextmanager
async def background_ai():
    from .ai_input import SCOPE
    input_token = SCOPE.set(None)
    token = _BACKGROUND.set(True)
    delta_token = DELTA.set(None)
    try:
        yield
    finally:
        SCOPE.reset(input_token)
        _BACKGROUND.reset(token)
        DELTA.reset(delta_token)


@asynccontextmanager
async def ai_http_client(timeout):
    loop = asyncio.get_running_loop()
    pools = _POOLS.setdefault(loop, {'active': 0})
    background = _BACKGROUND.get()
    key = 'background' if background else 'foreground'
    with measure_phase('ai-pool-wait'):
        deadline = loop.time() + 5
        while background and pools['active'] and loop.time() < deadline:
            await asyncio.sleep(.1)
    if key not in pools:
        pools[key] = httpx.AsyncHTTPTransport(limits=httpx.Limits(
            max_connections=1 if background else 8, max_keepalive_connections=1 if background else 4,
            keepalive_expiry=30), trust_env=False)
    if not background:
        pools['active'] += 1
    try:
        # A fresh client isolates credentials and Set-Cookie across accounts,
        # while the borrowed transport reuses authenticated-request sockets.
        async with httpx.AsyncClient(timeout=timeout, transport=BorrowedTransport(pools[key]), trust_env=False) as client:
            with measure_phase('ai-background' if background else 'ai-provider'):
                yield client
    finally:
        if not background:
            pools['active'] -= 1


async def close_ai_transport():
    pools = _POOLS.pop(asyncio.get_running_loop(), {})
    for key in ('foreground', 'background'):
        if key in pools:
            await pools[key].aclose()


async def streamed_response(client, url, payload, headers, callback):
    """Normalize an opt-in direct-answer stream to the existing choices shape."""
    content = []; reasoning = []; finish = 'stop'; usage = {}; complete = False
    await callback('reset', '')
    async with client.stream('POST', url, json={**payload, 'stream':True}, headers=headers) as response:
        if response.status_code != 200:
            await response.aread()
            return httpx.Response(response.status_code, content=response.content, headers=response.headers)
        import json
        if 'text/event-stream' not in response.headers.get('content-type', ''):
            await response.aread()
            return httpx.Response(200, content=response.content, headers=response.headers)
        size = 0
        async for line in response.aiter_lines():
            if not line.startswith('data:'): continue
            raw = line[5:].strip()
            if raw == '[DONE]':
                complete = True
                break
            try:
                data = json.loads(raw)
                if not isinstance(data, dict) or not isinstance(data.get('choices', []), list):
                    raise ValueError('invalid stream event')
            except (ValueError, TypeError) as exc:
                raise httpx.RemoteProtocolError('AI 服务返回了无效的流式数据') from exc
            if data.get('error'):
                raise httpx.RemoteProtocolError('AI 服务在生成过程中返回错误')
            usage = data.get('usage') or usage
            for choice in data.get('choices') or []:
                if not isinstance(choice, dict):
                    raise httpx.RemoteProtocolError('AI 服务返回了无效的回答数据')
                if choice.get('index',0) != 0: continue
                delta = choice.get('delta') or {}
                if not isinstance(delta, dict):
                    raise httpx.RemoteProtocolError('AI 服务返回了无效的回答片段')
                text = delta.get('content') or ''
                if not isinstance(text, str): raise httpx.RemoteProtocolError('Invalid streamed answer')
                if text:
                    size += len(text)
                    if size > 1000000: raise ValueError('Streamed answer exceeds the display limit')
                    content.append(text); await callback('delta', text)
                reasoning_text = delta.get('reasoning_content')
                if isinstance(reasoning_text, str):
                    reasoning.append(reasoning_text)
                finish = choice.get('finish_reason') or finish
                if choice.get('finish_reason'):
                    complete = True
        if not complete:
            raise httpx.RemoteProtocolError('AI 生成连接中断，回答尚未完成')
    return httpx.Response(200, json={'choices':[{'message':{'content':''.join(content),
        'reasoning_content':''.join(reasoning)},'finish_reason':finish}], 'usage':usage})
