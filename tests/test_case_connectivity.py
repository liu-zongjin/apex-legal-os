import asyncio
import time
import unittest
from unittest.mock import AsyncMock, patch
import httpx
from backend.public_case_transport import CaseRoutes
from backend.case_research import build_case_query_plan
from backend import public_case_web as wiki

class RouteTests(unittest.IsolatedAsyncioTestCase):
    def routes(self):
        value=object.__new__(CaseRoutes)
        value.clients=['direct','proxy']; value.preferred=0
        return value

    async def test_slow_proxy_cannot_hold_fast_direct(self):
        value=self.routes(); value.preferred=1; cancelled=[]
        async def request(client):
            if client=='proxy':
                try: await asyncio.sleep(10)
                finally: cancelled.append(client)
            return httpx.Response(200)
        start=time.monotonic()
        result=await value.request(request)
        self.assertEqual(result.status_code,200)
        self.assertLess(time.monotonic()-start,1)
        self.assertEqual(cancelled,['proxy'])

    async def test_previously_successful_route_is_not_pinned_after_failure(self):
        value=self.routes()
        async def request(client):
            if client=='direct': raise httpx.ConnectTimeout('offline')
            return httpx.Response(200)
        result=await value.request(request)
        self.assertEqual(result.status_code,200)
        self.assertEqual(value.preferred,1)

    async def test_total_deadline_cancels_all_routes(self):
        value=self.routes()
        async def request(client): await asyncio.sleep(10)
        start=time.monotonic()
        with self.assertRaises(httpx.ReadTimeout):
            await value.request(request,deadline=time.monotonic()+.05)
        self.assertLess(time.monotonic()-start,.2)

    async def test_one_failed_source_retains_partial_cases(self):
        async def archive(plan,limit,progress):
            progress['cases'].append({'title':'已取得正文'})
            raise httpx.ReadTimeout('later stage failed')
        with patch.object(wiki,'_search_wikisource_cases',archive), patch('backend.public_case_discovery.discover_cases',AsyncMock(return_value={'cases':[],'errors':[],'retrieval_runs':[]})):
            result=await wiki.search_public_cases({'core_issue':'匿名争点'})
        self.assertEqual(result['cases'],[{'title':'已取得正文'}])
        self.assertTrue(result['errors'])

    def test_unplanned_question_is_not_replaced_by_topic_template(self):
        from backend.public_case_planning import generic_case_plan
        question='甲行为或乙行为之后是否存在丙法律效果'
        plan=generic_case_plan(question)
        self.assertEqual(plan['core_issue'],question)
        self.assertEqual(plan['required_term_groups'],[])
        self.assertEqual(plan['fact_fingerprint'],{})
