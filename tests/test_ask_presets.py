import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.ask_presets import register_ask_presets


class AskPresetsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        path = str(Path(self.temp.name) / 'test.sqlite')
        def db():
            c=sqlite3.connect(path); c.row_factory=sqlite3.Row; return c
        conn=db(); conn.execute('CREATE TABLE app_preferences (preference_key TEXT PRIMARY KEY, value_json TEXT, updated_at TEXT)'); conn.commit(); conn.close()
        app=FastAPI(); register_ask_presets(app,db,{'deepseek-flash','fixture-model'})
        self.client=TestClient(app)
        self.payload={'name':'案例研究','source_mode':'mcp:aluris,national_law','model':'deepseek-flash','skill_id':'personal---test','reasoning_effort':'max','case_source':'both'}
    def tearDown(self): self.temp.cleanup()
    def test_round_trip_persist_distinct_options_and_delete(self):
        created=self.client.post('/api/ai-ask/presets',json=self.payload)
        self.assertEqual(created.status_code,200)
        first=created.json()['preset']; self.assertEqual({k:first[k] for k in self.payload},self.payload)
        empty={**self.payload,'name':'不使用 Skill','skill_id':'','reasoning_effort':'fast','case_source':'mcp','source_mode':'local_only'}
        self.assertEqual(self.client.post('/api/ai-ask/presets',json=empty).status_code,200)
        self.assertEqual(len(self.client.get('/api/ai-ask/presets').json()['presets']),2)
        self.assertEqual(self.client.post('/api/ai-ask/presets',json=self.payload).status_code,409)
        self.assertEqual(self.client.delete('/api/ai-ask/presets/'+first['id']).status_code,200)
        self.assertEqual(self.client.get('/api/ai-ask/presets').json()['presets'][0]['skill_id'],'')
    def test_invalid_options_cannot_be_saved(self):
        for key,value in [('name',''),('model','missing'),('model',[]),('source_mode','mcp:a;bad'),('reasoning_effort','wrong'),('case_source','unknown')]:
            with self.subTest(key=key,value=value): self.assertEqual(self.client.post('/api/ai-ask/presets',json={**self.payload,key:value}).status_code,400)
        self.assertEqual(self.client.get('/api/ai-ask/presets').json()['presets'],[])
