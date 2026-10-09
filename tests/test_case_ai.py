import asyncio
import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from backend.case_ai import answer_case_database, database_schema, run_query


def fixture(path):
    conn = sqlite3.connect(path)
    conn.executescript('''
        CREATE TABLE case_manager_cases(id INTEGER PRIMARY KEY,title TEXT,source_status TEXT,case_kind TEXT,memo TEXT);
        CREATE TABLE case_manager_parties(id INTEGER PRIMARY KEY,case_id INTEGER,name TEXT,FOREIGN KEY(case_id) REFERENCES case_manager_cases(id));
        CREATE TABLE case_manager_court_online_layy(id INTEGER PRIMARY KEY,linked_case_id INTEGER,status TEXT,review_comment TEXT,updated_at TEXT,raw_json TEXT);
        CREATE TABLE case_manager_court_online_settings(auth_token TEXT);
        CREATE TABLE case_manager_contract_profiles(case_id INTEGER,fee_json TEXT,api_key TEXT);
        CREATE TABLE case_manager_message_documents(id INTEGER,case_id INTEGER,content TEXT);
        CREATE TABLE related_records(id INTEGER,case_id INTEGER,FOREIGN KEY(case_id) REFERENCES case_manager_cases(id));
        CREATE TABLE articles(id INTEGER,content TEXT);
    ''')
    conn.executemany('INSERT INTO case_manager_cases VALUES(?,?,?,?,?)',
        [(i,f'匿名案件{i}', 'archived' if i%2 else 'active', 'ordinary', '联系记录：第二次联系未接通') for i in range(1,252)])
    conn.execute("INSERT INTO case_manager_parties VALUES(1,251,'匿名示丆某')")
    conn.execute("INSERT INTO case_manager_court_online_layy VALUES(1,251,'待补正','补充授权委托书','2026-10-10','{}')")
    conn.execute("INSERT INTO case_manager_contract_profiles VALUES(251,'{\"fee\":5000}','private')")
    conn.execute("INSERT INTO articles VALUES(1,'知识库')")
    conn.commit(); conn.close()


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'fixture.db'
        fixture(self.path)
        self.conn = sqlite3.connect(self.path)
        self.schema = database_schema(self.conn)

    def tearDown(self):
        self.conn.close(); self.temp.cleanup()

    def test_full_counts_and_paging(self):
        self.assertEqual(run_query(self.conn,self.schema,'SELECT count(*) AS n FROM case_manager_cases')['rows'],[{'n':251}])
        first = run_query(self.conn,self.schema,'SELECT * FROM case_manager_cases ORDER BY id')
        self.assertEqual(len(first['rows']),200); self.assertTrue(first['has_more'])
        last = run_query(self.conn,self.schema,'SELECT * FROM case_manager_cases ORDER BY id LIMIT 200 OFFSET 200')
        self.assertEqual(len(last['rows']),51); self.assertFalse(last['has_more'])

    def test_one_web_join_and_detail_json(self):
        result = run_query(self.conn,self.schema,'''SELECT c.title,p.name,l.review_comment,l.updated_at,
            json_extract(f.fee_json,'$.fee') AS fee FROM case_manager_cases c JOIN case_manager_parties p ON p.case_id=c.id
            JOIN case_manager_court_online_layy l ON l.linked_case_id=c.id JOIN case_manager_contract_profiles f ON f.case_id=c.id''')
        self.assertEqual(result['rows'][0]['review_comment'],'补充授权委托书')
        self.assertEqual(result['rows'][0]['fee'],5000)
        from backend.case_ai import _case_links
        links = _case_links(self.conn,[{'id':777,'case_id':251}])
        self.assertEqual(links,[{'case_id':251,'case_title':'匿名案件251'}])
        self.assertIn('related_records',self.schema)
        self.assertEqual(self.schema['case_manager_parties']['foreign_keys'][0]['table'],'case_manager_cases')

    def test_writes_secrets_and_unrelated_data_denied(self):
        self.assertNotIn('case_manager_court_online_settings',self.schema)
        for sql in ["DELETE FROM case_manager_cases", "WITH t AS (SELECT 1) DELETE FROM case_manager_cases",
                "SELECT * FROM articles", "SELECT api_key FROM case_manager_contract_profiles", "SELECT * FROM sqlite_master",
                "SELECT load_extension('x')", "PRAGMA table_info(case_manager_cases)", "ATTACH DATABASE ':memory:' AS x",
                "SELECT * FROM case_manager_cases; DELETE FROM case_manager_cases"]:
            with self.subTest(sql=sql): self.assertIn('error',run_query(self.conn,self.schema,sql))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM case_manager_cases').fetchone()[0],251)
        self.assertEqual(self.conn.execute('SELECT api_key FROM case_manager_contract_profiles').fetchone()[0],'private')

    def test_expensive_recursive_query_is_interrupted(self):
        moments = iter([0,100])
        with patch('backend.case_ai.time.monotonic',side_effect=lambda: next(moments,100)):
            result = run_query(self.conn,self.schema,'WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<10000000) SELECT SUM(x) FROM n')
        self.assertIn('interrupted',result['error'])

    def test_long_value_is_explicitly_incomplete(self):
        result = run_query(self.conn,self.schema,"SELECT printf('%050000d',1) AS long_text FROM case_manager_cases LIMIT 1")
        self.assertTrue(result['has_more']); self.assertTrue(result['note'])


class AnswerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.path = Path(self.temp.name)/'fixture.db'; fixture(self.path)
    async def asyncTearDown(self): self.temp.cleanup()
    def get_db(self): return sqlite3.connect(self.path)
    def response(self,obj): return ({'choices':[{'message':{'content':json.dumps(obj,ensure_ascii=False)}}]},'deepseek-chat')

    def mock_call(self, plans):
        return AsyncMock(side_effect=plans+[plans[-1]])

    async def test_roundtrip_and_followup_based_only_on_database(self):
        call = self.mock_call([self.response({'queries':[{'label':'案件总数','sql':'SELECT count(*) AS total FROM case_manager_cases'}]}),
            self.response({'answer':'全部251个案件。[citation:1]'})])
        result = await answer_case_database(self.get_db,call,'一共有多少案件','deepseek-chat',[{'role':'user','content':'含归档'}])
        self.assertIn('251',result['answer']); self.assertEqual(result['source_mode'],'case_database')
        self.assertEqual(result['cited_sources'][0]['source_type'],'case_database')
        self.assertIn('251',result['cited_sources'][0]['excerpt'])
        self.assertEqual(result['sources'],[])
        self.assertIn('含归档',call.call_args.args[1][1]['content'])
        self.assertFalse(self.get_db().in_transaction)

    async def test_malformed_plan_and_forbidden_query_are_retried(self):
        call = self.mock_call([self.response([]),self.response({'queries':[{'sql':'SELECT * FROM articles'}]}),
            self.response({'queries':[{'label':'立案审核','sql':'SELECT review_comment,updated_at FROM case_manager_court_online_layy'}]}),
            self.response({'answer':'需补充授权委托书。[citation:1]'})])
        result = await answer_case_database(self.get_db,call,'一张网有什么待处理事项','deepseek-chat')
        self.assertEqual(len(result['cited_sources']),1)
        self.assertEqual(result['cited_sources'][0]['target'],'court_online')
        self.assertEqual(call.await_count,5)

    async def test_cancellation_closes_read_snapshot(self):
        connection = self.get_db()
        call = AsyncMock(side_effect=asyncio.CancelledError)
        with self.assertRaises(asyncio.CancelledError):
            await answer_case_database(lambda:connection,call,'全部案件','deepseek-chat')
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute('SELECT 1')

    async def test_request_route_bypasses_knowledge_and_mcp(self):
        from backend import main
        call = self.mock_call([self.response({'queries':[{'label':'案件总数','sql':'SELECT count(*) AS total FROM case_manager_cases'}]}),self.response({'answer':'251'})])
        with patch.object(main,'get_db',self.get_db),patch.object(main,'_call_ai_with_fallback',call),patch.object(
                main,'_resolve_follow_up_question',side_effect=AssertionError('KB route')):
            result = await main.ask_question(question='总共多少案件',model='deepseek-chat',source_mode='case_database',
                skill_id=None,request_id=None,conversation_context=None)
        self.assertEqual(result['answer'],'251')


class UIContractTests(unittest.TestCase):
    def test_old_sources_and_identifiers_render_in_readable_form(self):
        root = Path(__file__).resolve().parent.parent
        subprocess.run(['node','tests/case_ai_ui_harness.js'],cwd=str(root),check=True,capture_output=True)


    def test_case_entry_and_isolated_scope(self):
        root = Path(__file__).resolve().parent.parent
        js = (root/'frontend/app.js').read_text()
        self.assertIn("CASE_AI: 'case_ai'",js)
        self.assertIn("return 'ask_history_case_database'",js)
        self.assertIn("requestContext?.type === 'case_database' ? 'case_database'",js)
        self.assertIn('mountAskPanelInTab(switchingTab, targetPage)',js)
        self.assertIn("normalized.indexOf('ai_ask') + 1",js)
        self.assertIn("if (askContext?.type === 'case_database') return;",js)
        self.assertIn('全部案件及一张网已同步资料',js)
