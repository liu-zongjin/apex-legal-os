"""Case-picker contract checks use anonymous fixtures and disposable databases."""
import ast
import html
import json
import re
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


class CaseLookupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / 'anonymous.sqlite'
        with sqlite3.connect(self.database) as db:
            db.executescript('''
                CREATE TABLE case_manager_cases(id INTEGER PRIMARY KEY,title TEXT,case_kind TEXT DEFAULT 'ordinary',
                    source_status TEXT DEFAULT 'active',parent_series_id INTEGER,series_code TEXT,series_display_name TEXT,
                    series_order INTEGER DEFAULT 0,case_type TEXT,current_stage TEXT,memo TEXT,court_contact TEXT,updated_at TEXT);
                CREATE TABLE case_manager_parties(id INTEGER PRIMARY KEY,case_id INTEGER,party_group TEXT,name TEXT,role TEXT,credit_code TEXT,sort_order INTEGER);
                CREATE TABLE case_manager_case_numbers(id INTEGER PRIMARY KEY,case_id INTEGER,number_type TEXT,case_no TEXT,court TEXT,sort_order INTEGER);
                CREATE TABLE case_manager_hearings(case_id INTEGER,court TEXT);
                CREATE TABLE case_manager_series_profiles(series_case_id INTEGER,table_columns_json TEXT);
                CREATE TABLE case_manager_series_cell_values(id INTEGER,series_case_id INTEGER,child_case_id INTEGER,column_key TEXT,value_text TEXT);
                CREATE TABLE case_manager_folder_bindings(case_id INTEGER PRIMARY KEY,real_path TEXT);
            ''')
            db.executemany('INSERT INTO case_manager_cases(id,title,updated_at) VALUES(?,?,?)', [(i,f'匿名案件{i}','2026-10-01') for i in range(1,206)])
            db.execute("UPDATE case_manager_cases SET case_kind='series' WHERE id=1")
            db.execute("INSERT INTO case_manager_cases(id,title,case_kind,parent_series_id,series_code,series_display_name,updated_at) VALUES(300,'匿名系列案件·匿名自然人甲完整子案名称','series_child',1,'22','22','2026-10-02')")
            db.execute("INSERT INTO case_manager_cases(id,title,source_status,case_kind,parent_series_id) VALUES(301,'已归档子案','archived','series_child',1)")
            db.execute("INSERT INTO case_manager_cases(id,title,source_status) VALUES(302,'已归档案件','archived')")
            db.execute("INSERT INTO case_manager_parties VALUES(1,300,'client','匿名自然人甲','委托人','',0)")
            db.execute("INSERT INTO case_manager_case_numbers VALUES(1,300,'仲裁','（2026）匿名仲案字22号','匿名仲裁委',0)")
            db.execute("INSERT INTO case_manager_folder_bindings VALUES(300,'/anonymous/folder')")
        @contextmanager
        def get_db():
            connection = sqlite3.connect(self.database); connection.row_factory = sqlite3.Row
            try: yield connection
            finally: connection.close()
        # Isolate the real lookup route from unrelated calendar/startup services.
        tree = ast.parse((ROOT/'backend/case_manager.py').read_text())
        register = next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='register_case_manager_routes')
        functions = [node for node in register.body if isinstance(node,ast.FunctionDef) and node.name in {'_parse_lookup_dims','_lookup_cases','case_lookup'}]
        app=FastAPI()
        scope={'app':app,'get_db':get_db,'norm':lambda value:str(value or '').strip(),'row_dict':lambda row:dict(row),'re':re,'json':json,'Any':Any,'Dict':Dict,'List':List}
        exec(compile(ast.Module(body=functions,type_ignores=[]),'case-lookup-route','exec'),scope)
        self.client=TestClient(app)

    def tearDown(self):
        self.temporary.cleanup()

    def test_pagination_reaches_every_active_case_and_keeps_ids(self):
        first=self.client.get('/api/case-manager/case-lookup?limit=200').json()
        self.assertEqual(len(first['items']),200)
        self.assertTrue(first['has_more']); self.assertEqual(first['next_offset'],200)
        last=self.client.get('/api/case-manager/case-lookup?limit=200&offset=200').json()
        self.assertFalse(last['has_more'])
        roots=first['items']+last['items']
        self.assertEqual({item['id'] for item in roots},set(range(1,206)))
        children=next(item for item in roots if item['id']==1)['children']
        self.assertEqual([child['id'] for child in children],[300])
        self.assertEqual(children[0]['title'],'匿名系列案件·匿名自然人甲完整子案名称')
        self.assertTrue(children[0]['folder_bound'])
        self.assertNotIn('real_path',children[0])

    def test_child_party_and_case_number_search_preserve_full_context(self):
        for query in ('匿名自然人甲','案号:（2026）匿名仲案字22号','法院:匿名仲裁委'):
            data=self.client.get('/api/case-manager/case-lookup',params={'q':query}).json()
            self.assertEqual([item['id'] for item in data['items']],[1])
            self.assertEqual(data['items'][0]['children'][0]['clients'][0]['name'],'匿名自然人甲')

    def test_legacy_items_contract_and_bounded_requests(self):
        result=self.client.get('/api/case-manager/case-lookup?limit=1&offset=-5').json()
        self.assertEqual(len(result['items']),1); self.assertEqual(result['next_offset'],1)
        capped=self.client.get('/api/case-manager/case-lookup?limit=10000').json()
        self.assertEqual(len(capped['items']),200)


class CasePickerBrowserTests(unittest.TestCase):
    def test_real_browser_interactions(self):
        chrome='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
        if not Path(chrome).exists():
            chrome=shutil.which('google-chrome') or shutil.which('chromium')
        if not chrome: self.skipTest('Chrome is unavailable')
        with tempfile.TemporaryDirectory() as directory:
            fixture=Path(directory)/'picker.html'
            source=(ROOT/'frontend/apex-case-picker.js').read_text()
            style=(ROOT/'frontend/apex-design-tokens.css').read_text()+(ROOT/'frontend/apex-case-picker.css').read_text()
            harness=(ROOT/'tests/case_picker_browser_harness.js').read_text()
            fixture.write_text(f'<html><head><style>{style}</style></head><body><pre id="result">pending</pre><script>{source}</script><script>{harness}</script></body></html>')
            process=subprocess.run([chrome,'--headless=new','--disable-gpu','--disable-background-networking','--disable-extensions','--no-first-run','--no-default-browser-check',f'--user-data-dir={directory}/profile','--virtual-time-budget=3500','--dump-dom',fixture.as_uri()],capture_output=True,text=True,timeout=45)
            match=re.search(r'<pre id="result">(.*?)</pre>',process.stdout,re.S)
            self.assertIsNotNone(match,process.stderr[-1000:])
            result=json.loads(html.unescape(match.group(1)))
            self.assertTrue(result.get('ok'),result)

    def test_every_registered_menu_loads_the_same_assets(self):
        registry=json.loads((ROOT/'docs/architecture/shared-capabilities.json').read_text())
        capability=next(item for item in registry['capabilities'] if item['id']=='case-picker')
        for name in capability['consumers']:
            if name.endswith('.html'):
                content=(ROOT/name).read_text()
                self.assertIn('/static/apex-case-picker.js',content,name)
                self.assertIn('/static/apex-case-picker.css',content,name)


if __name__=='__main__': unittest.main()
