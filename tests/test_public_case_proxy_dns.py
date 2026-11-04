"""Proxy DNS recovery must keep every private-address boundary intact."""
import unittest
from unittest.mock import AsyncMock, patch
import httpx
from backend.public_case_transport import CaseRoutes
from backend.public_web_search import public_get


class ProxyDnsTests(unittest.IsolatedAsyncioTestCase):
    async def check(self,url,answers=None,fail=False):
        routes=CaseRoutes()
        async def get(endpoint,**kw):
            if fail:raise httpx.ConnectError('unavailable')
            return httpx.Response(200,json={'Status':0,'Answer':answers or []},request=httpx.Request('GET',endpoint))
        client=AsyncMock();client.get.side_effect=get
        try:
            with patch('backend.public_web_search.public_host',return_value=False):
                allowed=await routes.proxy_public_host(client,url)
            return allowed,client
        finally:await routes.aclose()

    async def test_remote_public_dns_recovers_poisoned_local_dns(self):
        allowed,client=await self.check('https://www.google.com/search',[{'type':1,'data':'8.8.8.8'}])
        self.assertTrue(allowed)
        self.assertEqual(client.get.await_count,2)
        self.assertTrue(all(c.args[0]=='https://dns.google/resolve' for c in client.get.await_args_list))

    async def test_private_literal_and_local_names_never_reach_resolver(self):
        for url in ('http://127.0.0.1/a','http://[::1]/a','http://192.168.1.2/a','http://localhost/a','http://printer.local/a','http://host.internal/a','http://2130706433/a','https://user:pass@public.example/a','http://public.example:8080/a','https://public.example:invalid/a','https://@public.example/a'):
            allowed,client=await self.check(url,[{'type':1,'data':'8.8.8.8'}])
            self.assertFalse(allowed,url)
            client.get.assert_not_awaited()

    async def test_mixed_or_private_remote_answers_are_rejected(self):
        for data in ('127.0.0.1','192.168.0.1','169.254.169.254','::1','fc00::1','198.18.0.1'):
            allowed,_=await self.check('https://www.google.com',[{'type':1,'data':'8.8.8.8'},{'type':1,'data':data}])
            self.assertFalse(allowed,data)

    async def test_arbitrary_document_host_cannot_override_local_private_dns(self):
        allowed,client=await self.check('https://untrusted.example/document',[{'type':1,'data':'8.8.8.8'}])
        self.assertFalse(allowed)
        client.get.assert_not_awaited()

    async def test_no_answers_or_resolver_failure_fail_closed(self):
        self.assertFalse((await self.check('https://www.google.com'))[0])
        self.assertFalse((await self.check('https://www.google.com',fail=True))[0])

    async def test_redirect_to_private_host_is_revalidated(self):
        seen=[]
        async def validate(url):
            seen.append(url);return '127.0.0.1' not in url
        def handler(request):return httpx.Response(302,headers={'location':'http://127.0.0.1/private'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(ValueError):await public_get(client,'https://www.google.com',host_validator=validate)
        self.assertEqual(seen,['https://www.google.com','http://127.0.0.1/private'])

    async def test_successful_dns_result_is_cached_for_route_lifetime(self):
        routes=CaseRoutes();client=AsyncMock()
        client.get.return_value=httpx.Response(200,json={'Status':0,'Answer':[{'type':1,'data':'8.8.8.8'}]},request=httpx.Request('GET','https://dns.google/resolve'))
        try:
            with patch('backend.public_web_search.public_host',return_value=False):
                self.assertTrue(await routes.proxy_public_host(client,'https://www.google.com/a'))
                self.assertTrue(await routes.proxy_public_host(client,'https://www.google.com/b'))
            self.assertEqual(client.get.await_count,2)
        finally:await routes.aclose()
