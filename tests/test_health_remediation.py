import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import FastAPI, HTTPException

from backend.runtime_version import SourceMonitor, source_fingerprint, watched_source_files
from backend.health_maintenance import ensure_health_schema, preserve_orphans, restore_record, install_relation_revisions
from backend.search_index import ensure_articles_fts
from backend.ai_transport import ai_http_client, close_ai_transport, streamed_response, DELTA
from backend.ask_stream import register_ask_stream
from backend.database import connect_database, read_snapshot
from backend.case_snapshot import build_details


class RuntimeHealthTests(unittest.TestCase):
    def test_running_browser_and_generated_files_do_not_change_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code = root/'backend/real.py';code.parent.mkdir();code.write_text('value=1')
            baseline = source_fingerprint(root)
            for name in ('browser-profiles/account/session.json','browser-profile/Default/prefs.json'):
                p=root/'backend/court_online_service'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('changed')
            p=root/'backend/contract_previews/preview.html';p.parent.mkdir();p.write_text('preview')
            self.assertEqual(source_fingerprint(root),baseline)
            self.assertEqual(watched_source_files(root),[code.resolve()])
            code.write_text('value=222');self.assertNotEqual(source_fingerprint(root),baseline)

    def test_cached_status_does_no_io_and_fails_closed_when_expired(self):
        monitor=SourceMonitor(Path('/unused'), 'current')
        with patch('backend.runtime_version.source_fingerprint',side_effect=AssertionError('request performed IO')):
            for _ in range(20):self.assertFalse(monitor.status()['restart_required'])
        monitor._checked-=30
        self.assertEqual(monitor.status()['source_status'],'unavailable')
        self.assertTrue(monitor.status()['restart_required'])

    def test_read_snapshot_reuses_connection_and_rejects_writes(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'db.sqlite'
            c=connect_database(path);c.execute('CREATE TABLE x(id PRIMARY KEY)');c.execute('INSERT INTO x VALUES(1)');c.commit();c.close()
            with read_snapshot(lambda:connect_database(path)):
                a=connect_database(path);b=connect_database(path)
                self.assertIs(a,b)
                a.close()
                self.assertEqual(b.execute('SELECT id FROM x').fetchone()[0],1)
                with self.assertRaises(sqlite3.OperationalError):a.execute('DELETE FROM x')


class LosslessRepairTests(unittest.TestCase):
    def setUp(self):
        self.conn=sqlite3.connect(':memory:');self.addCleanup(self.conn.close)
        self.conn.row_factory=sqlite3.Row
        self.conn.executescript('''CREATE TABLE articles(id INTEGER PRIMARY KEY,title TEXT);
            CREATE TABLE notes(id INTEGER PRIMARY KEY,article_id INTEGER,content BLOB,
                FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE);
            CREATE TABLE note_details(id INTEGER PRIMARY KEY,note_id INTEGER,content TEXT,
                FOREIGN KEY(note_id) REFERENCES notes(id) ON DELETE CASCADE);
            INSERT INTO articles VALUES(1,'匿名文章');
            INSERT INTO notes VALUES(10,999,X'00FF');
            INSERT INTO note_details VALUES(20,10,'匿名子记录');''')
        self.conn.execute('PRAGMA foreign_keys=ON')

    def test_preserves_orphan_and_cascading_content_before_removing_invalid_rows(self):
        result=preserve_orphans(self.conn)
        self.assertEqual(result['preserved'],2)
        self.assertEqual(list(self.conn.execute('PRAGMA foreign_key_check')),[])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM integrity_recovery_records').fetchone()[0],2)
        self.assertEqual(preserve_orphans(self.conn)['preserved'],0)
        note=self.conn.execute("SELECT id FROM integrity_recovery_records WHERE source_table='notes'").fetchone()[0]
        restore_record(self.conn,note,1)
        self.assertEqual(self.conn.execute('SELECT content FROM notes WHERE id=10').fetchone()[0],b'\x00\xff')
        self.assertEqual(self.conn.execute('SELECT article_id FROM notes WHERE id=10').fetchone()[0],1)

    def test_bad_parent_and_id_conflict_never_overwrite_user_data(self):
        preserve_orphans(self.conn)
        identity=self.conn.execute("SELECT id FROM integrity_recovery_records WHERE source_table='notes'").fetchone()[0]
        with self.assertRaises(HTTPException):restore_record(self.conn,identity,123456)
        self.conn.execute("INSERT INTO notes VALUES(10,1,'新笔记')");self.conn.commit()
        with self.assertRaises(HTTPException):restore_record(self.conn,identity,1)
        self.assertEqual(self.conn.execute('SELECT content FROM notes WHERE id=10').fetchone()[0],'新笔记')
        self.assertIsNone(self.conn.execute('SELECT restored_at FROM integrity_recovery_records WHERE id=?',(identity,)).fetchone()[0])


class SearchMaintenanceTests(unittest.TestCase):
    def test_unchanged_relation_scan_reuses_result_and_note_edit_invalidates_it(self):
        from tests.test_knowledge_relations import KnowledgeRelationsTests
        from backend import knowledge_relations as kr
        c = KnowledgeRelationsTests().make_conn(); self.addCleanup(c.close)
        ensure_health_schema(c); install_relation_revisions(c)
        c.execute("INSERT INTO articles VALUES(1,'匿名保证责任案例','依据《民法典》第六百八十一条。','摘要')")
        self.assertFalse(kr.scan_article_rules(c,1)['cached'])
        self.assertTrue(kr.scan_article_rules(c,1)['cached'])
        c.execute("INSERT INTO notes VALUES(1,1,'补充《民法典》第六百八十六条')")
        self.assertFalse(kr.scan_article_rules(c,1)['cached'])

    def test_nonsearch_article_updates_do_not_rewrite_fts(self):
        c=sqlite3.connect(':memory:');self.addCleanup(c.close)
        c.execute('CREATE TABLE articles(id INTEGER PRIMARY KEY,title,summary,content,tags,domains,pinned)')
        c.execute("INSERT INTO articles VALUES(1,'建设工程','摘要','履行合同','[]','[]',0)")
        self.assertTrue(ensure_articles_fts(c));c.commit();before=c.total_changes
        c.execute('UPDATE articles SET pinned=1 WHERE id=1')
        self.assertEqual(c.total_changes-before,1)
        c.execute("UPDATE articles SET content='保证责任' WHERE id=1")
        self.assertEqual(c.execute("SELECT rowid FROM articles_fts WHERE articles_fts MATCH '保证责任'").fetchone()[0],1)

    def test_relation_revision_changes_for_notes_and_rules_not_open_state(self):
        c=sqlite3.connect(':memory:');self.addCleanup(c.close)
        c.execute('CREATE TABLE notes(id INTEGER PRIMARY KEY,content TEXT)');ensure_health_schema(c);install_relation_revisions(c)
        c.execute("INSERT INTO notes VALUES(1,'匿名笔记')")
        a=c.execute("SELECT revision FROM health_revisions WHERE key='relations'").fetchone()[0]
        c.execute("UPDATE notes SET content='更正' WHERE id=1")
        self.assertGreater(c.execute("SELECT revision FROM health_revisions WHERE key='relations'").fetchone()[0],a)

    def test_batch_detail_queries_do_not_grow_per_case_and_preserve_series(self):
        c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row;self.addCleanup(c.close)
        c.executescript('''CREATE TABLE case_manager_cases(id INTEGER PRIMARY KEY,title,case_kind,parent_series_id,series_order);
            CREATE TABLE case_manager_parties(id INTEGER PRIMARY KEY,case_id,sort_order,party_group,client_id,credit_code);
            CREATE TABLE case_manager_clients(id INTEGER PRIMARY KEY,name,identity_code,contacts_json);
            CREATE TABLE case_manager_series_profiles(series_case_id INTEGER PRIMARY KEY);
            CREATE TABLE case_manager_case_numbers(id INTEGER PRIMARY KEY,case_id,sort_order,case_no);
            CREATE TABLE case_manager_todos(id INTEGER PRIMARY KEY,case_id,remind_at);
            CREATE TABLE case_manager_hearings(id INTEGER PRIMARY KEY,case_id,hearing_at);
            CREATE TABLE case_manager_preservations(id INTEGER PRIMARY KEY,case_id,deadline_at);
            CREATE TABLE case_manager_appeals(id INTEGER PRIMARY KEY,case_id,deadline_at);
            CREATE TABLE case_manager_claims(id INTEGER PRIMARY KEY,case_id,sort_order);
            CREATE TABLE case_manager_milestones(id INTEGER PRIMARY KEY,case_id,happened_at,sort_order);
            CREATE TABLE case_manager_audit_logs(id INTEGER PRIMARY KEY,case_id,created_at,changes_json,entity_type);
            INSERT INTO case_manager_clients VALUES(1,'匿名委托人','fixture-code','[]');
            INSERT INTO case_manager_parties VALUES(1,1,0,'client',1,'');
            INSERT INTO case_manager_series_profiles VALUES(1);''')
        c.executemany('INSERT INTO case_manager_cases VALUES(?,?,?,?,?)',[(i,'匿名案件','series' if i==1 else 'series_child' if i==201 else 'ordinary',1 if i==201 else None,0) for i in range(1,202)])
        counts=[]
        with patch('backend.case_snapshot.court_rows',return_value={k:[] for k in ('cases','layy','records','hearings')}):
            for size in (5,200):
                queries=[];c.set_trace_callback(queries.append)
                result=build_details(c,list(range(1,size+1)),{})
                counts.append(len(queries));self.assertEqual(len(result[1]['series_children']),1)
                self.assertEqual(result[1]['parties'][0]['credit_code'],'fixture-code')
        self.assertEqual(counts[0],counts[1]);self.assertLess(counts[1],20)


class AsyncHealthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):await close_ai_transport()

    async def test_clients_reuse_transport_without_cross_request_cookies(self):
        cookies=[]
        async def handler(request):
            cookies.append(request.headers.get('cookie'))
            return httpx.Response(200,json={'ok':True},headers={'set-cookie':'account=first; Path=/'})
        transport=httpx.MockTransport(handler)
        with patch('backend.ai_transport.httpx.AsyncHTTPTransport',return_value=transport) as factory:
            for _ in range(2):
                async with ai_http_client(1) as client:await client.post('https://fixture.invalid',json={})
            self.assertEqual(factory.call_count,1)
        self.assertEqual(cookies,[None,None])

    async def test_directory_subscriptions_share_and_release_one_watcher(self):
        from backend.file_watch import changes_for, _LOOPS
        import types
        calls=[]
        async def watch(*args,**kwargs):
            calls.append(1)
            await asyncio.Event().wait()
            yield set()
        with tempfile.TemporaryDirectory() as d, patch.dict('sys.modules',{'watchfiles':types.SimpleNamespace(awatch=watch)}):
            first=changes_for(Path(d));second=changes_for(Path(d))
            await first.__anext__();await second.__anext__();await asyncio.sleep(0)
            self.assertEqual(len(calls),1)
            await first.aclose();self.assertEqual(len(_LOOPS[asyncio.get_running_loop()]),1)
            await second.aclose();self.assertEqual(_LOOPS[asyncio.get_running_loop()],{})

    async def test_deferred_binding_worker_starts_and_stops(self):
        from backend import case_automation as module
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'fixture.db'
            with sqlite3.connect(path) as c:c.execute('CREATE TABLE case_manager_folder_bindings(case_id INTEGER)')
            app=FastAPI()
            with patch.object(module,'ensure_case_automation_schema'),patch.object(module,'TEMPLATE_DIR',Path(d)/'templates'),patch.object(module,'PREVIEW_DIR',Path(d)/'previews'),patch.dict('os.environ',{'CASE_BINDING_VERIFICATION_DISABLED':'0'}):
                module.register_case_automation_routes(app,lambda:sqlite3.connect(path))
                for callback in app.router.on_startup:await callback()
                for callback in app.router.on_shutdown:await callback()

    async def test_stream_emits_partial_text_and_keeps_final_result(self):
        app=FastAPI()
        async def answer(**values):
            await DELTA.get()('delta','匿名片段')
            return {'answer':'匿名完整回答','request_id':values['request_id']}
        register_ask_stream(app,answer)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as client:
            response=await client.post('/api/ask-stream',data={'question':'问题','source_mode':'direct_ai','request_id':'fixture'})
        self.assertIn('event: delta',response.text)
        self.assertIn('匿名片段',response.text)
        self.assertIn('event: result',response.text)
        self.assertIn('匿名完整回答',response.text)

    async def test_stream_rejects_other_scopes(self):
        app=FastAPI();register_ask_stream(app,None)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as client:
            r=await client.post('/api/ask-stream',data={'question':'问题','source_mode':'case_database'})
            self.assertEqual(r.status_code,400)

    async def test_disconnected_stream_cancels_provider(self):
        app = FastAPI()
        disconnected = asyncio.Event(); cancelled = asyncio.Event()
        async def answer(**values):
            try:
                await DELTA.get()('delta', '匿名片段')
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        register_ask_stream(app, answer)
        first = True
        async def receive():
            nonlocal first
            if first:
                first = False
                return {'type':'http.request','body':b'question=fixture&source_mode=direct_ai','more_body':False}
            await disconnected.wait()
            return {'type':'http.disconnect'}
        async def send(message):
            if message['type'] == 'http.response.body' and b'event: delta' in message.get('body',b''):
                disconnected.set()
        scope = {'type':'http','asgi':{'version':'3.0','spec_version':'2.3'},'http_version':'1.1',
                 'method':'POST','scheme':'http','path':'/api/ask-stream','raw_path':b'/api/ask-stream',
                 'query_string':b'','headers':[(b'content-type',b'application/x-www-form-urlencoded')],
                 'client':('127.0.0.1',1),'server':('fixture',80)}
        await asyncio.wait_for(app(scope, receive, send), 2)
        self.assertTrue(cancelled.is_set())

    async def test_direct_answer_enables_only_final_provider_stream(self):
        from backend import main
        from backend.ai_transport import FINAL
        async def provider(*args, **kwargs):
            self.assertTrue(FINAL.get())
            return {'choices':[{'message':{'content':'匿名最终回答'}}]}, 'fixture'
        self.assertFalse(FINAL.get())
        with patch.object(main, '_call_ai_with_fallback', provider), patch.object(main, '_ask_skill_instruction', return_value=''):
            result = await main._ask_direct_ai('匿名问题','fixture',None,None,None)
        self.assertEqual(result['answer'],'匿名最终回答')
        self.assertFalse(FINAL.get())

    async def test_provider_stream_retains_reasoning_and_finish_marker_without_exposing_reasoning(self):
        events=[]
        async def callback(event,text):events.append((event,text))
        lines=[{'choices':[{'index':0,'delta':{'reasoning_content':'内部推理'}}]},
               {'choices':[{'index':0,'delta':{'content':'回答'},'finish_reason':'length'}]}]
        body=''.join('data: '+json.dumps(r)+'\n\n' for r in lines)+'data: [DONE]\n\n'
        async def handler(request):return httpx.Response(200,text=body,headers={'content-type':'text/event-stream'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result=await streamed_response(client,'https://fixture.invalid',{}, {},callback)
        self.assertEqual(result.json()['choices'][0]['finish_reason'],'length')
        self.assertEqual(result.json()['choices'][0]['message']['reasoning_content'],'内部推理')
        self.assertNotIn(('delta','内部推理'),events)
        self.assertIn(('delta','回答'),events)
