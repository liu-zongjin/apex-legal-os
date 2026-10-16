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

    async def test_context_changes_cannot_hide_stale_history_save(self):
        key='ask_history_revision_audit';await self.save(key,'窗口甲保存的内容')
        with self.db() as c:original=ctx.require_conversation(c,key)
        stale=list(self.records[key])
        await self.save(key,'窗口乙新增内容')
        inspected=self.client.get('/api/ai-context',params={'history_key':key}).json()
        response=self.client.put('/api/ai-context',params={'history_key':key},json={'version':inspected['version'],'recall_enabled':False,'excluded':[]})
        self.assertEqual(response.status_code,200)
        with self.assertRaises(HTTPException):
            self.main.save_ai_ask_history(self.main.AIAskHistoryPayload(history_key=key,records=stale,version=original['history_version']))
        with self.db() as c:current=ctx.require_conversation(c,key)
        self.main.save_ai_ask_history(self.main.AIAskHistoryPayload(history_key=key,records=self.records[key],version=current['history_version']))
        self.assertEqual(len(self.main.get_ai_ask_history()['conversations'][0]['records']),2)

    async def test_private_context_taints_derived_answer_and_never_cross_recalls(self):
        key='ask_history_taint';await self.save(key,'保密金额777777元',no=True)
        mid=await self.save(key,'重复上一条金额')
        usage=self.prepare(key,mid,'重复上一条金额')
        self.assertTrue(usage['private_context'])
        aid=await self.save(key,'上一条金额为777777元',answer=True)
        self.records[key][-1]['contextUsage']=usage
        self.main.save_ai_ask_history(self.main.AIAskHistoryPayload(history_key=key,records=self.records[key]))
        with self.db() as c:self.assertEqual(c.execute('SELECT no_memory FROM ai_context_messages WHERE message_id=?',(aid,)).fetchone()[0],1)
        other=await self.save('ask_history_taint_other','保密金额是多少')
        self.assertNotIn('777777',ctx.instruction(self.prepare('ask_history_taint_other',other,'保密金额')))

    async def test_memory_changes_preserve_other_conversations_manual_summary(self):
        key='ask_history_manual_summary';await self.save(key,'案件目标')
        with self.db() as c:
            c.execute("UPDATE ai_context_conversations SET summary='用户修正：需核验合同',summary_manual=1,summary_version=3 WHERE history_key=?",(key,))
        ident=memory.save(self.db,'我希望你用简洁语言回答')
        memory.remove(self.db,ident)
        with self.db() as c:
            row=ctx.require_conversation(c,key)
            self.assertEqual(row['summary'],'用户修正：需核验合同');self.assertEqual(row['summary_version'],3)

    async def test_auto_save_disabled_still_summarizes_without_capturing_memory(self):
        key='ask_history_summary_only'
        with self.db() as c:c.execute('UPDATE user_memory_settings SET auto_save=0')
        for i in range(10):await self.save(key,('用户事实' if i%2==0 else '回答')+str(i),answer=bool(i%2))
        async def summarizer(model,messages):
            payload=json.loads(messages[-1]['content'])
            self.assertFalse(payload['capture_memories'])
            return json.dumps({'memories':[{'content':'用户事实0','kind':'case','subject':'事实'}],'summary':'用户事实0，来源已保留'})
        with patch.object(ctx,'CALL_AI',summarizer):await ctx.process_jobs(self.db)
        self.assertEqual(memory.snapshot(self.db)['items'],[])
        with self.db() as c:self.assertIn('用户事实0',ctx.require_conversation(c,key)['summary'])

    async def test_malformed_background_response_is_failed_not_fake_success(self):
        key='ask_history_invalid_json';await self.save(key,'我希望你用中文回答');await self.save(key,'收到',answer=True)
        with patch.object(ctx,'CALL_AI',AsyncMock(return_value='{"memories":[],"summary":123}')):await ctx.process_jobs(self.db)
        with self.db() as c:self.assertEqual(c.execute('SELECT state FROM ai_context_jobs WHERE history_key=?',(key,)).fetchone()[0],'failed')

    async def test_recent_originals_remain_chronological_after_relevance_selection(self):
        key='ask_history_order'
        for i in range(12):await self.save(key,('早期合同本金80万元' if i==0 else '后续内容'+str(i)),answer=bool(i%2))
        mid=await self.save(key,'合同本金')
        selected=[m['id'] for m in self.prepare(key,mid,'合同本金')['items'] if m['type']=='recent']
        expected=[r['id'] for r in self.records[key][:-1] if r['id'] in selected]
        self.assertEqual(selected,expected)

    async def test_rebuild_retries_failed_and_latest_job_without_remining_all_completed_turns(self):
        key='ask_history_retry_scope'
        for i in range(8):await self.save(key,('用户' if i%2==0 else '回答')+str(i),answer=bool(i%2))
        with self.db() as c:c.execute("UPDATE ai_context_jobs SET state='complete' WHERE history_key=?",(key,))
        response=self.client.post('/api/ai-context/rebuild',params={'history_key':key})
        self.assertEqual(response.status_code,200)
        with self.db() as c:self.assertEqual(c.execute("SELECT count(*) FROM ai_context_jobs WHERE state='pending' AND history_key=?",(key,)).fetchone()[0],1)

    async def test_upgrade_repairs_old_derived_privacy_and_preserves_history_revision(self):
        path=Path(self.temp.name)/'legacy-context.db'
        with sqlite3.connect(path) as c:
            c.executescript('''CREATE TABLE ai_context_conversations(history_key TEXT PRIMARY KEY,version INTEGER,summary TEXT,summary_ids TEXT,summary_version INTEGER,summary_manual INTEGER);
                CREATE TABLE ai_context_messages(message_id TEXT PRIMARY KEY,no_memory INTEGER,usage_json TEXT);
                CREATE TABLE ai_context_jobs(id INTEGER PRIMARY KEY,message_id TEXT,state TEXT);
                INSERT INTO ai_context_conversations VALUES('legacy',7,'不应保留的衍生摘要','["a2"]',3,0);
                INSERT INTO ai_context_messages VALUES('private',1,'null');
                INSERT INTO ai_context_jobs VALUES(1,'a2','pending');''')
            c.execute('INSERT INTO ai_context_messages VALUES(?,?,?)',('a1',0,json.dumps({'items':[{'type':'recent','id':'private'}]})))
            c.execute('INSERT INTO ai_context_messages VALUES(?,?,?)',('a2',0,json.dumps({'items':[{'type':'recent','id':'a1'}]})))
            ctx.upgrade_audit_schema(c)
            self.assertEqual(c.execute('SELECT history_version,summary FROM ai_context_conversations').fetchone(),(7,''))
            self.assertEqual(c.execute("SELECT no_memory FROM ai_context_messages WHERE message_id='a2'").fetchone()[0],1)
            self.assertEqual(c.execute('SELECT state,capture_allowed FROM ai_context_jobs').fetchone(),('cancelled',0))
            ctx.upgrade_audit_schema(c)
            self.assertEqual(c.execute('SELECT history_version FROM ai_context_conversations').fetchone()[0],7)

    async def test_rebuild_while_worker_running_keeps_replacement_job(self):
        key='ask_history_running_rebuild';await self.save(key,'我希望你用中文回答');await self.save(key,'收到',answer=True)
        started=asyncio.Event();release=asyncio.Event();calls=[]
        async def model_call(model,messages):
            calls.append(1)
            if len(calls)==1:
                started.set();await release.wait()
            return json.dumps({'memories':[],'summary':''})
        with patch.object(ctx,'CALL_AI',model_call):
            worker=asyncio.create_task(ctx.process_jobs(self.db))
            await started.wait()
            response=self.client.post('/api/ai-context/rebuild',params={'history_key':key})
            self.assertEqual(response.status_code,200)
            release.set();await worker
        self.assertEqual(len(calls),2)
        with self.db() as c:self.assertEqual(c.execute('SELECT state FROM ai_context_jobs WHERE history_key=?',(key,)).fetchone()[0],'complete')
