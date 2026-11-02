"""Use the owner's system web proxy for public case requests, as browsers do."""
from urllib.request import getproxies
from urllib.parse import urlsplit


def case_proxy():
    value = getproxies().get('https') or getproxies().get('http')
    try:
        parsed = urlsplit(value or '')
        if parsed.scheme in {'http', 'https'} and parsed.hostname:
            return value
    except ValueError:
        pass
    return None


class CaseRoutes:
    """Hedge a slow system proxy with direct access; never pin a failed route."""

    def __init__(self, headers=None):
        import httpx
        self.clients = [httpx.AsyncClient(timeout=httpx.Timeout(7, connect=3), trust_env=False,
                                        follow_redirects=False, headers=headers)]
        proxy = case_proxy()
        if proxy:
            self.clients.append(httpx.AsyncClient(proxy=proxy, timeout=httpx.Timeout(7, connect=3),
                                                 trust_env=False, follow_redirects=False, headers=headers))
        self.preferred = 0

    async def request(self, operation, *, deadline=None):
        import asyncio
        import time
        import httpx
        budget = min(10.0, max(0.01, deadline-time.monotonic())) if deadline else 10.0
        async def attempt(index, delay):
            if delay:
                await asyncio.sleep(delay)
            return index, await operation(self.clients[index])
        order = [self.preferred] + [i for i in range(len(self.clients)) if i != self.preferred]
        pending = {asyncio.create_task(attempt(index, position * .4)) for position,index in enumerate(order)}
        all_tasks = set(pending)
        end = time.monotonic() + budget
        last_error, last_response = None, None
        try:
            while pending and time.monotonic() < end:
                done, pending = await asyncio.wait(pending, timeout=max(.001,end-time.monotonic()), return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    try:
                        index, response = task.result()
                        # A real rate limit is authoritative, never evade it with another route.
                        if response.status_code == 429:
                            return response
                        if response.status_code < 400:
                            self.preferred = index
                            return response
                        last_response = response
                    except (httpx.HTTPError, ValueError, OSError) as exc:
                        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
                            raise
                        last_error = exc
            if last_response is not None:
                return last_response
            if last_error is not None:
                raise last_error
            raise httpx.ReadTimeout('公开网页请求达到本次截止时间')
        finally:
            for task in pending:
                task.cancel()
            await asyncio.gather(*all_tasks, return_exceptions=True)

    async def get(self, url, *, params=None, deadline=None):
        return await self.request(lambda client: client.get(url, params=params, follow_redirects=True), deadline=deadline)

    async def public_get(self, url, *, deadline=None):
        from .public_web_search import public_get
        return await self.request(lambda client: public_get(client, url), deadline=deadline)

    async def aclose(self):
        import asyncio
        await asyncio.gather(*(client.aclose() for client in self.clients))
