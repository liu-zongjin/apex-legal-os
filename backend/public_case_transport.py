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
        self.proxy_client = None
        self.dns_cache = {}
        proxy = case_proxy()
        if proxy:
            self.clients.append(httpx.AsyncClient(proxy=proxy, timeout=httpx.Timeout(7, connect=3),
                                                 trust_env=False, follow_redirects=False, headers=headers))
            self.proxy_client = self.clients[-1]
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
        async def operation(client):
            validator = (lambda target: self.proxy_public_host(client, target)) if client is self.proxy_client else None
            return await public_get(client, url, host_validator=validator)
        return await self.request(operation, deadline=deadline)

    async def proxy_public_host(self, client, url):
        """Validate remote DNS when a configured proxy owns hostname resolution.

        Literal/private URLs stay blocked. A poisoned or synthetic local DNS
        answer must not disable every public search behind the owner's proxy.
        Every redirect still goes through this validator and TLS verification.
        """
        import asyncio
        import ipaddress
        import time
        import httpx
        from .public_web_search import public_host
        parsed = urlsplit(url)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            return False
        try:
            if parsed.port not in (None, 80, 443):return False
        except ValueError:return False
        try:
            ipaddress.ip_address(parsed.hostname)
        except ValueError:
            pass
        else:
            return await asyncio.get_running_loop().run_in_executor(None, public_host, url)
        if parsed.hostname.lower() in {'localhost', 'localhost.localdomain'} or parsed.hostname.lower().endswith(('.local', '.localhost', '.internal')) or '.' not in parsed.hostname:
            return False
        if await asyncio.get_running_loop().run_in_executor(None, public_host, url):
            return True
        key = parsed.hostname.lower()
        # Only fixed search endpoints may use remote validation. Arbitrary
        # document links retain the original local public-address requirement.
        if key not in {'www.google.com','cn.bing.com','www.bing.com','www.so.com','www.sogou.com'}:
            return False
        cached = self.dns_cache.get(key)
        if cached and cached[1] > time.monotonic():
            return cached[0]
        async def lookup(kind):
            response = await client.get('https://dns.google/resolve', params={'name':key, 'type':kind},
                                        headers={'Accept':'application/dns-json'}, follow_redirects=False, timeout=4)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data,dict) or not isinstance(data.get('Answer',[]),list) or any(not isinstance(row,dict) for row in data.get('Answer',[])):
                raise ValueError('公开 DNS 响应无效')
            if response.status_code != 200 or data.get('Status') != 0:
                raise ValueError('公开 DNS 查询未成功')
            return [ipaddress.ip_address(row['data']) for row in data.get('Answer', []) if row.get('type') in (1,28)]
        try:
            answers = await asyncio.gather(lookup('A'), lookup('AAAA'))
            addresses = [ip for rows in answers for ip in rows]
            allowed = bool(addresses) and all(ip.is_global for ip in addresses)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            allowed = False
        if len(self.dns_cache) >= 128:
            self.dns_cache.pop(next(iter(self.dns_cache)))
        self.dns_cache[key] = (allowed, time.monotonic()+60)
        return allowed

    async def aclose(self):
        import asyncio
        await asyncio.gather(*(client.aclose() for client in self.clients))
