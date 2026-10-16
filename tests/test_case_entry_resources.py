"""Exercise actual timeline persistence against anonymous, disposable SQLite data."""
import ast
import datetime
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel
from backend import case_entry_resources as module
from backend.migrations import _add_case_entry_resources

SOURCE = Path(__file__).resolve().parents[1] / 'backend/main.py'
TREE = ast.parse(SOURCE.read_text())


class EntryResourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = self.root / 'uploads'
        with self.db() as conn:
            conn.execute('CREATE TABLE research_projects(id INTEGER PRIMARY KEY, updated_at TEXT)')
            conn.execute("INSERT INTO research_projects VALUES(1,'old')")
            for table in module.TABLES.values():
                conn.execute(f'''CREATE TABLE {table}(id INTEGER PRIMARY KEY, project_id INTEGER,
                    title TEXT,content TEXT,happened_at TEXT,created_at TEXT,updated_at TEXT)''')
                conn.execute(f"INSERT INTO {table} VALUES(1,1,'旧标题','旧内容','','old','old')")
                conn.execute(f"INSERT INTO {table} VALUES(2,1,'第二条','旧内容','','old','old')")
            _add_case_entry_resources(conn)
            _add_case_entry_resources(conn)
        names = {'CaseTimelineEntryPayload', '_save_timeline_entry', '_require_project', '_delete_timeline_entry', '_timeline_public_entry'}
        extracted = ast.Module(body=[node for node in TREE.body if isinstance(node,(ast.FunctionDef,ast.ClassDef)) and node.name in names], type_ignores=[])
        env = dict(get_db=self.db, BaseModel=BaseModel, HTTPException=HTTPException, datetime=datetime)
        exec(compile(extracted, str(SOURCE), 'exec'),env)
        self.legacy_save = env['_save_timeline_entry']
        self.payload = env['CaseTimelineEntryPayload']
        self.public_entry = env['_timeline_public_entry']
        self.app = FastAPI()
        module.register_routes(self.app,self.db,self.store,self.legacy_save,self.payload)
        self.client = TestClient(self.app,base_url='http://localhost',client=('127.0.0.1',12345))
        self.local_file = self.root / "匿名材料 'quote'.txt"
        self.local_file.write_text('original')

    def tearDown(self):
        self.temp.cleanup()

    def db(self):
        conn = sqlite3.connect(self.root/'fixture.db')
        conn.row_factory = sqlite3.Row
        return conn

    def save(self,kind='memo-entries',entry_id=1,**changes):
        data = dict(title='新标题',content='新内容',happened_at='2026-10-16',keep_resource_ids=[],local_paths=[])
        data.update(changes.pop('data',{}))
        url = f'/api/case-research/{kind}/{entry_id}/with-resources' if entry_id else f'/api/case-research/projects/1/{kind}/with-resources'
        return self.client.request('PUT' if entry_id else 'POST',url,data={'payload':json.dumps(data)},**changes)

    def items(self,kind='memo-entries',entry_id=1):
        return self.client.get(f'/api/case-research/{kind}/{entry_id}/resources').json()['items']

    def test_new_and_existing_both_types_persist_download_and_unbind(self):
        for kind in module.TABLES:
            for entry_id in (0,1):
                response = self.save(kind,entry_id,data={'local_paths':[str(self.local_file),str(self.root)]},files=[('files',('匿名文件.txt',b'uploaded','text/plain'))])
                self.assertEqual(response.status_code,200,response.text)
                saved_id=response.json()['id']
                items=self.items(kind,saved_id)
                self.assertEqual([item['kind'] for item in items],['file','folder','upload'])
                upload=items[-1]
                url=f"/api/case-research/{kind}/{saved_id}/resources/{upload['id']}/download"
                self.assertEqual(self.client.get(url).content,b'uploaded')
                self.assertEqual(self.client.get(url.replace(f'/{saved_id}/resources', '/999/resources')).status_code,404)
                self.assertEqual(self.save(kind,saved_id).status_code,200)
                self.assertEqual(self.items(kind,saved_id),[])
                self.assertTrue(self.local_file.exists())
                self.assertFalse((self.store/upload['id']).exists())

    def test_legacy_save_preserves_resources_and_invalid_kept_id_is_rejected(self):
        self.save(data={'local_paths':[str(self.local_file)]})
        original=self.items()
        self.legacy_save('research_case_memo_entries',1,self.payload(content='兼容旧入口'),1)
        self.assertEqual(self.items(),original)
        response=self.save(data={'keep_resource_ids':['foreign-resource']})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.items(),original)

    def test_upload_failure_and_invalid_text_roll_back_files_and_record(self):
        with patch.object(module,'MAX_FILE',3):
            response=self.save(files=[('files',('too-big.txt',b'1234','text/plain'))])
        self.assertEqual(response.status_code,413)
        self.assertEqual(list(self.store.iterdir()),[])
        response=self.save(data={'content':''},files=[('files',('small.txt',b'123','text/plain'))])
        self.assertEqual(response.status_code,400)
        self.assertEqual(list(self.store.iterdir()),[])
        with self.db() as conn:
            self.assertEqual(conn.execute('SELECT content FROM research_case_memo_entries WHERE id=1').fetchone()[0],'旧内容')

    def test_local_open_missing_and_type_changed_never_launch(self):
        self.save(data={'local_paths':[str(self.local_file)]})
        item=self.items()[0]
        url=f"/api/case-research/memo-entries/1/resources/{item['id']}/open"
        with patch.object(module.subprocess,'run') as run:
            self.assertEqual(self.client.post(url).status_code,200)
            self.assertEqual(run.call_args.args[0],['open','--',str(self.local_file.resolve())])
            run.reset_mock()
            self.local_file.unlink()
            self.assertFalse(self.items()[0]['exists'])
            self.assertEqual(self.client.post(url).status_code,400)
            self.local_file.mkdir()
            self.assertEqual(self.client.post(url).status_code,409)
            run.assert_not_called()

    def test_remote_and_proxy_cannot_add_remove_or_open_local_paths(self):
        self.save(data={'local_paths':[str(self.local_file)]})
        item=self.items()[0]
        for headers in ({'X-Forwarded-For':'203.0.113.1'},{'Origin':'https://remote.example'}):
            response=self.client.put('/api/case-research/memo-entries/1/with-resources',headers=headers,
                data={'payload':json.dumps(dict(content='changed',keep_resource_ids=[],local_paths=[]))})
            self.assertEqual(response.status_code,403)
            listing=self.client.get('/api/case-research/memo-entries/1/resources',headers=headers).json()
            self.assertNotIn('path',listing['items'][0])
            self.assertFalse(listing['local_available'])
            self.assertEqual(self.client.post(f"/api/case-research/memo-entries/1/resources/{item['id']}/open",headers=headers).status_code,403)

    def test_picker_cancel_invalid_type_and_missing_owner(self):
        from types import SimpleNamespace
        with patch.object(module.subprocess,'run',return_value=SimpleNamespace(returncode=1,stderr='(-128)')):
            response=self.client.post('/api/case-research/projects/1/resources/select?kind=file')
            self.assertEqual(response.json(),{'cancelled':True})
        self.assertEqual(self.client.post('/api/case-research/projects/1/resources/select?kind=invalid').status_code,400)
        self.assertEqual(self.client.post('/api/case-research/projects/999/resources/select').status_code,404)
        self.assertEqual(self.items(),[])

    def test_concurrent_change_during_upload_preserves_other_edit(self):
        # The real persistence callback must reject a stale row version atomically.
        with self.assertRaises(HTTPException) as error:
            self.legacy_save('research_case_memo_entries',1,self.payload(content='new'),1,resource_edit=('[]','stale'))
        self.assertEqual(error.exception.status_code,409)
        with self.db() as conn:
            self.assertEqual(conn.execute('SELECT content FROM research_case_memo_entries WHERE id=1').fetchone()[0],'旧内容')

    def test_general_research_serialization_does_not_expose_local_metadata(self):
        self.save(data={'local_paths':[str(self.local_file)]})
        with self.db() as conn:
            row=conn.execute('SELECT * FROM research_case_memo_entries WHERE id=1').fetchone()
        public=self.public_entry(row)
        self.assertNotIn('resources_json',public)
        self.assertEqual(public['content'],'新内容')
        self.assertEqual(self.save(data={'base_updated_at':'stale'}).status_code,409)

    def test_invalid_form_and_limits_do_not_modify_data(self):
        for data in ({'keep_resource_ids':[{}]}, {'local_paths':['relative.txt']}, {'local_paths':[str(self.root)]*41}):
            self.assertEqual(self.save(data=data).status_code,400)
        self.assertEqual(self.items(),[])
