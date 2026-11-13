import asyncio
import json
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import httpx
from backend import ai_input, ai_reasoning, main
from backend.ai_transport import FINAL
from backend.public_case_answer import answer_public_cases


class PublicCaseReasoningTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_level_reaches_research_model_only(self):
        calls=[]
        class Client:
            async def post(self, url, json, headers):
                calls.append(json.copy())
                return httpx.Response(200,json={'choices':[{'message':{'content':'{}'},'finish_reason':'stop'}]})
        @asynccontextmanager
        async def client(timeout): yield Client()
        scope=ai_input.SCOPE.set(ai_input.new_scope('匿名问题'))
        token=ai_reasoning.RESEARCH_STAGE.set(True)
        try:
            for effort in ('fast','low','high','max'):
                ai_input.SCOPE.get()['reasoning_effort']=effort
                with patch.object(main,'_get_api_config',return_value=('https://example.test','key','deepseek-flash')), patch.object(main,'ai_http_client',client):
                    await main._call_ai_with_fallback('deepseek-flash',[{'role':'user','content':'匿名材料'}],max_tokens=1600)
                sent=calls[-1]
                self.assertEqual(sent['thinking']['type'], 'disabled' if effort=='fast' else 'enabled')
                self.assertEqual(sent.get('reasoning_effort'), None if effort=='fast' else effort)
                self.assertEqual(sent['max_tokens'], max(1600, ai_reasoning.RESEARCH_BUDGETS.get(effort,0)))
                self.assertFalse(FINAL.get())
        finally:
            ai_reasoning.RESEARCH_STAGE.reset(token);ai_input.SCOPE.reset(scope)

    async def test_route_scopes_setting_to_public_research_calls(self):
        seen=[]
        async def fake_call(*args,**kwargs):
            seen.append((ai_reasoning.RESEARCH_STAGE.get(),(ai_input.SCOPE.get() or {}).get('reasoning_effort'),FINAL.get()))
            return ({'choices':[{'message':{'content':'{}'}}]},'deepseek-flash')
        async def fake_answer(*args,**kwargs):
            self.assertEqual(kwargs['reasoning_effort'],'high')
            await kwargs['call_plan']('deepseek-flash',[{'role':'user','content':'匿名'}])
            self.assertFalse(ai_reasoning.RESEARCH_STAGE.get())
            return {'answer':'完成。','sources':[]}
        with patch('backend.user_memory.snapshot',return_value={'enabled':False,'auto_save':False,'revision':0,'items':[]}), patch.object(main,'get_db',side_effect=AssertionError('local KB accessed')), patch.object(main,'_call_ai_with_fallback',side_effect=fake_call), patch('backend.public_case_answer.answer_public_cases',side_effect=fake_answer):
            result=await main.ask_question(question='测试',model='deepseek-flash',source_mode='public_web_cases',reasoning_effort='high',memory_enabled=False)
        self.assertEqual(result['answer'],'完成。')
        self.assertEqual(seen,[(True,'high',False)])
        self.assertFalse(ai_reasoning.RESEARCH_STAGE.get())

    async def test_research_fallback_keeps_selected_effort(self):
        calls=[]
        class Client:
            async def post(self, url, json, headers):
                calls.append(json.copy())
                if json['model']=='deepseek-flash': raise httpx.ReadTimeout('timeout')
                return httpx.Response(200,json={'choices':[{'message':{'content':'{}'},'finish_reason':'stop'}]})
        @asynccontextmanager
        async def client(timeout): yield Client()
        scope=ai_input.SCOPE.set(ai_input.new_scope('匿名问题'))
        ai_input.SCOPE.get()['reasoning_effort']='max'
        token=ai_reasoning.RESEARCH_STAGE.set(True)
        try:
            with patch.object(main,'_get_api_config',side_effect=lambda model:('https://example.test','key',model)), patch.object(main,'ai_http_client',client), patch.object(main,'_ai_fallback_models',return_value=['deepseek-v4-pro','opencode:deepseek-flash']):
                _, actual=await main._call_ai_with_fallback('deepseek-flash',[{'role':'user','content':'匿名材料'}],max_tokens=1600)
            self.assertEqual(actual,'deepseek-v4-pro')
            self.assertEqual([item['model'] for item in calls],['deepseek-flash','deepseek-v4-pro'])
            self.assertTrue(all(item.get('reasoning_effort')=='max' for item in calls))
        finally:
            ai_reasoning.RESEARCH_STAGE.reset(token);ai_input.SCOPE.reset(scope)

    async def test_timeout_budgets_and_grounded_review_are_preserved(self):
        court='本院认为，已经通知保证人，应承担保证责任。'
        case=dict(title='匿名判决',case_number='（2024）示民初8号',source_url='https://example.org/8',source='公开存档',holding=court,adjudicated_facts='',source_kind='public_web',retrieved_by=[],remote_score=.5)
        replies=[{'groups':[['保证']], 'queries':['保证 通知'], 'paths':[{'required_facts':['已通知保证人'],'queries':['保证 通知']}]}, {'cases':[{'index':0,'path_id':'p0','stance':'support','quote':court,'fact_checks':[{'fact_index':0,'status':'established','proof_kind':'court_finding','quote':'已经通知保证人'}]}]}, {'reviews':[{'index':0,'verdict':'supported'}]}]
        async def model(*a,**kw): return {'text':json.dumps(replies.pop(0),ensure_ascii=False)},'deepseek-flash'
        search=AsyncMock(return_value=dict(cases=[case],coverage={},metrics={},retrieval_runs=[],errors=[]))
        original=asyncio.wait_for; timeouts=[]
        async def record(coro, timeout):
            timeouts.append(timeout)
            return await original(coro,timeout)
        with patch('backend.public_case_answer.search_cases_structured',search),patch('backend.public_case_answer.asyncio.wait_for',record):
            result=await answer_public_cases('保证通知事实测试','deepseek-flash',None,None,resolve=AsyncMock(return_value='保证通知事实测试'),call_plan=model,extract=lambda d:(d['text'],'',''),call_answer=AsyncMock(),progress=lambda *a,**kw:None,reasoning_effort='high')
        self.assertEqual(result['case_research']['coverage']['counts']['support'],1)
        self.assertIn(court,result['answer'])
        self.assertTrue(any(179 <= t <= 180 for t in timeouts),timeouts)
        self.assertTrue(any(t>105 for t in timeouts),timeouts)
        self.assertEqual(replies,[])

    async def test_incomplete_batch_retries_with_larger_output_budget(self):
        court='本院认为，已经通知保证人，应承担保证责任。'
        case=dict(title='匿名判决',case_number='（2024）示民初8号',source_url='https://example.org/8',source='公开存档',holding=court,adjudicated_facts='',source_kind='public_web',retrieved_by=[],remote_score=.5)
        plan={'groups':[['保证']], 'queries':['保证 通知'], 'paths':[{'required_facts':['已通知保证人'],'queries':['保证 通知']}]}
        good={'cases':[{'index':0,'path_id':'p0','stance':'support','quote':court,'fact_checks':[{'fact_index':0,'status':'established','proof_kind':'court_finding','quote':'已经通知保证人'}]}]}
        replies=[plan, {'cases':[]}, good, {'reviews':[{'index':0,'verdict':'supported'}]}]
        budgets=[]
        async def model(*args,**kwargs):
            budgets.append(kwargs['max_tokens'])
            return {'text':json.dumps(replies.pop(0),ensure_ascii=False)},'deepseek-flash'
        search=AsyncMock(return_value=dict(cases=[case],coverage={},metrics={},retrieval_runs=[],errors=[]))
        with patch('backend.public_case_answer.search_cases_structured',search):
            result=await answer_public_cases('保证通知事实测试','deepseek-flash',None,None,resolve=AsyncMock(return_value='保证通知事实测试'),call_plan=model,extract=lambda d:(d['text'],'',''),call_answer=AsyncMock(),progress=lambda *a,**kw:None,reasoning_effort='high')
        self.assertEqual(budgets,[1600,4500,24000,2200])
        self.assertEqual(result['case_research']['coverage']['counts']['support'],1)

    async def test_cancel_interrupts_deep_research(self):
        started=asyncio.Event()
        async def model(*args,**kwargs):
            started.set()
            await asyncio.Event().wait()
        task=asyncio.create_task(answer_public_cases('匿名问题','deepseek-flash',None,None,resolve=AsyncMock(return_value='匿名问题'),call_plan=model,extract=lambda d:(d['text'],'',''),call_answer=AsyncMock(),progress=lambda *a,**kw:None,reasoning_effort='max'))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
