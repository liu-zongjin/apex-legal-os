"""Anonymous, temporary DB coverage for context boundaries and asynchronous races."""
import asyncio
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from backend import ai_context as ctx, user_memory as memory


class ContextTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from backend import main
        self.main = main
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'context.db'
        self.patch = patch.object(main,'DB_PATH',self.path);self.patch.start()
        main.init_db()
        self.worker = patch.object(ctx,'CALL_AI',None);self.worker.start()
        self.records = {}
        self.clock = int(time.time()*1000)+1000
        with self.db() as c:
            c.execute("INSERT INTO case_manager_cases(id,title,created_at,updated_at) VALUES(901,'匿名甲案','2026-10-15','2026-10-15'),(902,'匿名乙案','2026-10-15','2026-10-15')")
        app = FastAPI(); app.include_router(ctx.create_router(self.db));app.include_router(memory.create_router(self.db))
        self.client = TestClient(app)
    async def asyncTearDown(self):
        self.worker.stop();self.patch.stop();self.temp.cleanup()
    def db(self):
        c=sqlite3.connect(self.path);c.row_factory=sqlite3.Row;return c
    async def save(self,key,text,cid=0,no=False,legacy=False,answer=False):
        self.clock+=10
        records=self.records.setdefault(key,[])
        mid=f'{key}-{len(records)}'
        records.append({'id':mid,'role':'ai' if answer else 'user','content':text,'model':'fixture-model' if answer else '',
                        'ts':self.clock,'contextEligible':not legacy,'noMemory':no})
        scope={'type':'case_database','caseId':cid} if cid else None
        self.main.save_ai_ask_history(self.main.AIAskHistoryPayload(history_key=key,context=scope,records=records))
        return mid
    def prepare(self,key,mid,question,enabled=True,cid=None):
        return ctx.prepare(self.db,key,mid,question,'fixture-model',enabled,cid)

    async def test_legacy_excluded_but_new_messages_in_old_conversation_work(self):
        key='ask_history_legacy'
        await self.save(key,'旧聊天独有标记',legacy=True)
        await self.save(key,'升级后新约定：先给结论')
        mid=await self.save(key,'继续新约定')
        state=self.prepare(key,mid,'继续新约定')
        text=ctx.instruction(state)
        self.assertNotIn('旧聊天独有标记',text)
        self.assertIn('升级后新约定',text)
        with self.db() as c:
            c.execute('UPDATE ai_context_messages SET eligible=0 WHERE message_id=?',(self.records[key][0]['id'],))
        self.records[key][0]['contextEligible']=True
        await self.save(key,'不能升级旧消息资格')
        with self.db() as c:self.assertEqual(c.execute('SELECT eligible FROM ai_context_messages WHERE message_id=?',(self.records[key][0]['id'],)).fetchone()[0],0)

    async def test_case_recall_isolation_and_noncase_default(self):
        await self.save('ask_history_a','合同本金80万元，争议是逾期利息',901)
        await self.save('ask_history_b','合同本金90万元，争议是逾期利息',902)
        await self.save('ask_history_global','合同本金100万元，争议是逾期利息')
        mid=await self.save('ask_history_a2','合同本金与利息是多少',901)
        state=self.prepare('ask_history_a2',mid,'合同本金利息',cid=901)
        recalled=[i['content'] for i in state['items'] if i['type']=='recall']
        self.assertTrue(any('80万元' in x for x in recalled));self.assertFalse(any('90万元' in x or '100万元' in x for x in recalled))
        with self.assertRaises(HTTPException):self.prepare('ask_history_a2',mid,'合同本金',cid=902)
        mid=await self.save('ask_history_global2','合同本金利息')
        self.assertFalse(any('80万元' in i['content'] or '90万元' in i['content'] for i in self.prepare('ask_history_global2',mid,'合同本金利息')['items']))

    async def test_no_memory_keeps_current_context_but_never_cross_recall_or_jobs(self):
        key='ask_history_private'
        await self.save(key,'保密合同金额12345万元',no=True)
        await self.save(key,'收到',no=True,answer=True)
        mid=await self.save(key,'保密合同金额是多少',no=True)
        state=self.prepare(key,mid,'保密合同金额',enabled=False)
        self.assertIn('12345',ctx.instruction(state));self.assertFalse(state['enabled'])
        other=await self.save('ask_history_other','保密合同金额是多少')
        self.assertNotIn('12345',ctx.instruction(self.prepare('ask_history_other',other,'保密合同金额')))
        with self.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM ai_context_jobs WHERE history_key=?',(key,)).fetchone()[0],0)

    async def test_memory_scoping_conflict_and_confirmation(self):
        memory.save(self.db,'我希望你先给结论')
        memory.save(self.db,'甲案用户提供事实',kind='case',case_id=901)
        memory.save(self.db,'乙案用户提供事实',kind='case',case_id=902)
        mid=await self.save('ask_history_mem','分析甲案事实',901)
        text=ctx.instruction(self.prepare('ask_history_mem',mid,'分析甲案事实'))
        self.assertIn('甲案用户提供事实',text);self.assertNotIn('乙案用户提供事实',text)
        with self.db() as c:
            ctx.put_candidate(c,'我叫小甲','personal',0,'ask_history_mem',mid,'称呼',0)
            ctx.put_candidate(c,'我叫小乙','personal',0,'ask_history_mem',mid,'称呼',0)
        items=memory.snapshot(self.db)['items']
        names=[i for i in items if i['subject']=='称呼']
        self.assertEqual({i['status'] for i in names},{'pending','conflict'})
        chosen=next(i for i in names if i['status']=='pending')
        result=self.client.put(f"/api/user-memory/{chosen['id']}/status",json={'status':'active','version':chosen['version']})
        self.assertEqual(result.status_code,200)
        self.assertEqual(sum(i['status']=='active' for i in memory.snapshot(self.db)['items'] if i['subject']=='称呼'),1)

    async def test_summary_and_relevant_original_survive_thirty_rounds(self):
        key='ask_history_long'
        first=await self.save(key,'合同本金为80万元；签订日2026年10月1日。')
        for i in range(62):await self.save(key,'后续无关讨论'+str(i)+'。'*50,answer=bool(i%2))
        async def summarize(model,messages):
            payload=json.loads(messages[-1]['content'])
            return json.dumps({'memories':[],'summary':payload['previous_summary'] or '用户目标：追索本金80万元，签订日2026年10月1日；来源'+first},ensure_ascii=False)
        with self.db() as c:
            c.execute("UPDATE ai_context_jobs SET state='complete' WHERE id<>(SELECT MIN(id) FROM ai_context_jobs)")
        with patch.object(ctx,'CALL_AI',summarize):await ctx.process_jobs(self.db)
        mid=await self.save(key,'最早约定的合同本金与签订日？')
        state=self.prepare(key,mid,'最早合同本金签订日')
        self.assertTrue(any(i['type']=='summary' for i in state['items']))
        self.assertIn('80万元',ctx.instruction(state));self.assertIn('2026年10月1日',ctx.instruction(state))
        self.assertTrue(any(i.get('id')==first for i in state['items']))

    async def test_version_conflict_delete_and_stable_message_ownership(self):
        key='ask_history_version';mid=await self.save(key,'版本检查')
        with self.db() as c:version=ctx.require_conversation(c,key)['version']
        payload=self.main.AIAskHistoryPayload(history_key=key,records=self.records[key],version=version-1)
        with self.assertRaises(HTTPException):self.main.save_ai_ask_history(payload)
        self.main.delete_ai_ask_history(key)
        with self.assertRaises(HTTPException):self.main.save_ai_ask_history(self.main.AIAskHistoryPayload(history_key=key,records=self.records[key]))
        with self.db() as c:self.assertFalse(c.execute('SELECT 1 FROM ai_context_messages WHERE message_id=?',(mid,)).fetchone())

    async def test_async_extraction_summary_failure_retry_and_delete_race(self):
        key='ask_history_job';mid=await self.save(key,'我希望你先给结论')
        await self.save(key,'收到',answer=True)
        async def fake(model,messages):
            self.assertEqual(model,'fixture-model')
            return json.dumps({'memories':[{'content':'我希望你先给结论','kind':'personal','subject':'回答方式'}],'summary':''},ensure_ascii=False)
        with patch.object(ctx,'CALL_AI',fake):await ctx.process_jobs(self.db)
        self.assertTrue(any(i['content']=='我希望你先给结论' for i in memory.snapshot(self.db)['items']))
        saved=memory.snapshot(self.db)['items'][0];memory.remove(self.db,saved['id'])
        with self.db() as c:c.execute("UPDATE ai_context_jobs SET state='pending',memory_revision=(SELECT revision FROM user_memory_settings WHERE id=1)")
        with patch.object(ctx,'CALL_AI',fake):await ctx.process_jobs(self.db)
        self.assertEqual(memory.snapshot(self.db)['items'],[])
        mid=await self.save('ask_history_race','我希望你用中文回复');await self.save('ask_history_race','收到',answer=True)
        async def racing(model,messages):
            memory.remove(self.db)
            return json.dumps({'memories':[{'content':'我希望你用中文回复','kind':'personal','subject':'语言'}]})
        with patch.object(ctx,'CALL_AI',racing):await ctx.process_jobs(self.db)
        self.assertEqual(memory.snapshot(self.db)['items'],[])
        with self.db() as c:c.execute("UPDATE ai_context_jobs SET state='pending',memory_revision=(SELECT revision FROM user_memory_settings WHERE id=1) WHERE history_key='ask_history_race'")
        with patch.object(ctx,'CALL_AI',AsyncMock(side_effect=RuntimeError('匿名失败'))):await ctx.process_jobs(self.db)
        with self.db() as c:self.assertEqual(c.execute("SELECT state FROM ai_context_jobs WHERE history_key='ask_history_race'").fetchone()[0],'failed')

    async def test_managed_ask_uses_backend_history_and_budget_guard(self):
        key='ask_history_direct';await self.save(key,'我正在分析80万元的合同')
        mid=await self.save(key,'继续分析')
        call=AsyncMock(return_value=({'choices':[{'message':{'content':'回答'}}]},'fixture-model'))
        with patch.object(self.main,'_call_ai_with_fallback',call):
            result=await self.main.ask_question(question='继续分析',model='fixture-model',source_mode='direct_ai',
                history_key=key,current_message_id=mid,skill_id=None,request_id=None)
        self.assertIn('context_usage',result)
        self.assertTrue(any('80万元' in m['content'] for m in call.call_args.args[1]))
        self.assertIsNone(ctx.CURRENT.get())
        with self.assertRaises(HTTPException):self.prepare(key,mid,'问'*100000)

    async def test_mixed_cases_never_enter_noncase_recall(self):
        key='ask_history_mixed'
        await self.save(key,'合同金额80万元')
        self.records[key][0]['caseLink']={'caseId':901}
        await self.save(key,'另一合同金额90万元')
        self.records[key][1]['caseLink']={'caseId':902}
        await self.save(key,'区分案件')
        with self.db() as c:self.assertEqual(ctx.require_conversation(c,key)['case_id'],-1)
        mid=await self.save('ask_history_unbound','合同金额是多少')
        text=ctx.instruction(self.prepare('ask_history_unbound',mid,'合同金额'))
        self.assertNotIn('80万元',text);self.assertNotIn('90万元',text)

    async def test_context_exclusions_and_model_switch_recompute_budget(self):
        key='ask_history_controls';mid=await self.save(key,'合同金额80万元')
        ident=memory.save(self.db,'回答时先给结论')
        with self.db() as c:version=ctx.require_conversation(c,key)['version']
        result=self.client.put('/api/ai-context',params={'history_key':key},json={'version':version,'excluded':[f'memory:{ident}','summary'],'recall_enabled':False,'summary':'用户修正的摘要'})
        self.assertEqual(result.status_code,200)
        state=self.prepare(key,mid,'继续')
        self.assertFalse(any(i['type'] in ('memory','summary','recall') for i in state['items']))
        with patch.dict('os.environ',{'STELLA_AI_INPUT_BUDGETS':'{"small-model":12000}'},clear=False):
            small=ctx.prepare(self.db,key,mid,'继续','small-model')
            self.assertEqual(small['budget'],12000)
            token=ctx.CURRENT.set(small)
            try:
                with self.assertRaises(HTTPException):ctx.guard_messages([{'content':'大'*5000}],8000)
            finally:ctx.CURRENT.reset(token)
        self.assertEqual(self.client.put('/api/ai-context',params={'history_key':key},json={'version':version,'excluded':[]}).status_code,409)

    async def test_deleted_memory_source_cannot_return_with_shorter_excerpt(self):
        with self.db() as c:ctx.put_candidate(c,'我希望你先给结论再列依据','personal',0,'ask_history_source','u1','回答方式',0)
        item=memory.snapshot(self.db)['items'][0];memory.remove(self.db,item['id'])
        with self.db() as c:ctx.put_candidate(c,'先给结论再列依据','personal',0,'ask_history_source','u1','回答方式',0)
        self.assertEqual(memory.snapshot(self.db)['items'],[])
