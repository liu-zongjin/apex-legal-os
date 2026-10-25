"""Real reminder API/SQLite operations on an anonymous database, no desktop sync."""
import ast
import contextlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import case_manager as module
from backend.migrations import _allow_standalone_todos
from tests.test_series_manager import BASE_SCHEMA

ROOT = Path(__file__).resolve().parents[1]


class TodoFixture:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='stella-ordinary-todos-')
        self.path = Path(self.tmp.name) / 'fixture.db'
        with sqlite3.connect(self.path) as db:
            db.executescript(BASE_SCHEMA)
            db.execute("ALTER TABLE case_manager_todos ADD COLUMN recurrence TEXT DEFAULT ''")
            db.execute("ALTER TABLE case_manager_todos ADD COLUMN completed_at TEXT DEFAULT ''")
            db.execute("ALTER TABLE case_manager_todos ADD COLUMN completed_ledger_id INTEGER")
            db.execute("INSERT INTO case_manager_cases(id,title,source_status,created_at,updated_at) VALUES(1,'匿名案件','active','old','old')")
            _allow_standalone_todos(db)
        @contextlib.contextmanager
        def get_db():
            db = sqlite3.connect(self.path)
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA foreign_keys=ON')
            try:
                yield db
            finally:
                db.close()
        self.get_db = get_db
        app = FastAPI()
        self.syncs = []
        tree = ast.parse((ROOT / 'backend/case_manager.py').read_text())
        register = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'register_case_manager_routes')
        names = {'now_iso','norm','row_dict','normalize_todo_recurrence','to_iso','source_key','merge_text_values','merge_record_text',
                 'upsert_todo','audit_row','add_audit_log','audit_text','save_reminder','create_todo','update_todo','get_todos',
                 'list_table','case_status_where','complete_todo','delete_todo','calendar_item','parse_date','parse_datetime',
                 'todo_occurrences_between','advance_todo_occurrence','add_months','case_manager_events'}
        functions = [node for node in register.body if isinstance(node,(ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
        self.scope = {**vars(module), 'app': app, 'get_db': get_db, 'ENTITY_AUDIT_NAMES': {'todo':'待办'}, 'ENTITY_AUDIT_FIELDS': {'todo':{}},
                      'annotate_series_reminders': lambda items: items, 'annotate_message_sources': lambda db,items,*kind: items,
                      'auto_sync_if_enabled': lambda *a,**k: self.syncs.append(a), 'delete_calendar_sync_record': lambda *a: None,
                      'move_matter_local_links': lambda *a: None}
        exec(compile(ast.Module(body=functions,type_ignores=[]), '<real-todo-routes>', 'exec'), self.scope)
        self.client = TestClient(app)

    def close(self):
        self.tmp.cleanup()


class StandaloneTodoTests(unittest.TestCase):
    def setUp(self):
        self.fx = TodoFixture()
        self.client = self.fx.client
        self.body = {'case_id':'','title':'','todo_title':'提交匿名会议材料','remind_at':'2026-10-26T10:00','notes':'请核对签字页','recurrence':'weekly'}
    def tearDown(self):
        self.fx.close()
    def create(self, patch=None):
        r = self.client.post('/api/case-manager/todos', json={**self.body, **(patch or {})})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()['id']
    def test_unlinked_save_list_search_calendar_and_no_phantom_case(self):
        item_id = self.create()
        item = self.client.get('/api/case-manager/todos?q=会议').json()['items'][0]
        self.assertEqual(item['id'], item_id)
        self.assertIsNone(item['case_id'])
        self.assertEqual(item['title'], '')
        self.assertEqual(item['recurrence'], 'weekly')
        self.assertEqual(self.fx.scope['calendar_item']('todo', item_id)['id'], item_id)
        events = self.client.get('/api/case-manager/events?types=todo&start=2026-10-26&end=2026-11-03').json()['items']
        self.assertEqual(len(events), 2)
        with self.fx.get_db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM case_manager_cases').fetchone()[0], 1)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
    def test_associate_detach_edit_and_complete_without_case_ledger(self):
        item_id = self.create({'case_id':1, 'title':'任意显示文字'})
        self.assertEqual(self.client.get('/api/case-manager/todos').json()['items'][0]['title'], '匿名案件')
        r = self.client.put(f'/api/case-manager/todos/{item_id}', json={**self.body, 'notes':'修改后的备注'})
        self.assertEqual(r.status_code,200,r.text)
        new_id = r.json()['id']
        self.assertIsNone(self.client.get('/api/case-manager/todos').json()['items'][0]['case_id'])
        for _ in range(2):
            r = self.client.post(f'/api/case-manager/todos/{new_id}/complete', json={'completed_at':'2026-10-26'})
            self.assertEqual(r.status_code,200,r.text)
            self.assertIsNone(r.json()['ledger_id'])
        self.assertEqual(self.client.get('/api/case-manager/todos').json()['items'], [])
        self.assertIsNone(self.fx.scope['calendar_item']('todo', new_id))
    def test_invalid_case_and_empty_task_are_rejected_without_new_case(self):
        for patch in ({'case_id':999}, {'todo_title':''}, {'case_id':'invalid'}):
            r = self.client.post('/api/case-manager/todos', json={**self.body, **patch})
            self.assertEqual(r.status_code,400,r.text)
        self.create({'title':'AI提取的文字不应创建案件'})
        with self.fx.get_db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM case_manager_cases').fetchone()[0], 1)
    def test_case_linked_completion_keeps_ledger_behavior(self):
        with self.fx.get_db() as db:
            db.executescript("""CREATE TABLE research_projects(id INTEGER PRIMARY KEY,case_id,name,client,case_info,issues,status,notes,created_at,updated_at);
                CREATE TABLE research_case_ledgers(id INTEGER PRIMARY KEY,project_id,title,content,happened_at,created_at,updated_at);""")
        item_id = self.create({'case_id':1})
        for _ in range(2):
            r = self.client.post(f'/api/case-manager/todos/{item_id}/complete',json={'completed_at':'2026-10-26'})
            self.assertEqual(r.status_code,200,r.text)
            self.assertIsNotNone(r.json()['ledger_id'])
        with self.fx.get_db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM research_case_ledgers').fetchone()[0],1)

    def test_home_reminder_cache_includes_ordinary_todos(self):
        import datetime, hashlib, json
        tree = ast.parse((ROOT / 'backend/main.py').read_text())
        names = {'_home_reminder_local_signature','_home_reminder_item'}
        nodes = [node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in names]
        env = {**vars(module), 'get_db':self.fx.get_db, 'datetime':datetime, 'hashlib':hashlib, 'json':json,'sqlite3':sqlite3}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'<home-reminders>', 'exec'),env)
        before = env['_home_reminder_local_signature']()
        today = datetime.date.today().isoformat()
        item_id = self.create({'remind_at':today+'T10:00'})
        self.assertNotEqual(before,env['_home_reminder_local_signature']())
        with self.fx.get_db() as db:
            row = db.execute('SELECT id,title,todo_title AS reminder_type,remind_at,notes FROM case_manager_todos WHERE id=?',(item_id,)).fetchone()
            self.assertEqual(env['_home_reminder_item'](row,'todos','remind_at','待办','notes')['title'], self.body['todo_title'])

    def test_empty_migration_retains_deleted_id_high_water(self):
        db = sqlite3.connect(':memory:')
        db.executescript(BASE_SCHEMA)
        db.execute("INSERT INTO case_manager_todos(id,case_id,title,created_at,updated_at) VALUES(99,1,'匿名','old','old')")
        db.execute('DELETE FROM case_manager_todos')
        _allow_standalone_todos(db)
        new = db.execute("INSERT INTO case_manager_todos(case_id,title,created_at,updated_at) VALUES(NULL,'','now','now')").lastrowid
        self.assertGreater(new,99)
        db.close()

    def test_migration_preserves_existing_rows_shortcuts_indexes_and_sequence(self):
        from backend.matter_local_links import add_schema
        db = sqlite3.connect(':memory:')
        db.executescript(BASE_SCHEMA)
        db.execute("INSERT INTO case_manager_cases(id,title,created_at,updated_at) VALUES(1,'匿名案件','old','old')")
        db.execute("INSERT INTO case_manager_todos(id,case_id,title,todo_title,created_at,updated_at) VALUES(41,1,'匿名案件','旧待办','old','old')")
        db.execute("INSERT INTO case_manager_todos(id,case_id,title,created_at,updated_at) VALUES(99,1,'匿名案件','old','old')")
        db.execute('DELETE FROM case_manager_todos WHERE id=99')
        add_schema(db)
        db.execute("INSERT INTO case_manager_matter_local_links(todo_id,path,name,kind) VALUES(41,'/anonymous/file.txt','file.txt','file')")
        db.execute('CREATE INDEX custom_todo_index ON case_manager_todos(todo_title)')
        before = db.execute('SELECT * FROM case_manager_todos').fetchall()
        _allow_standalone_todos(db)
        self.assertEqual(db.execute('SELECT * FROM case_manager_todos').fetchall(), before)
        self.assertEqual(db.execute('SELECT todo_id FROM case_manager_matter_local_links').fetchone()[0],41)
        self.assertIsNotNone(db.execute("SELECT name FROM sqlite_master WHERE name='custom_todo_index'").fetchone())
        self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
        new = db.execute("INSERT INTO case_manager_todos(case_id,title,created_at,updated_at) VALUES(NULL,'','now','now')").lastrowid
        self.assertGreater(new,99)
        _allow_standalone_todos(db)
        db.commit()
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('DELETE FROM case_manager_cases WHERE id=1')
        self.assertEqual(db.execute('SELECT id FROM case_manager_todos').fetchall(),[(new,)])
        self.assertEqual(db.execute('SELECT * FROM case_manager_matter_local_links').fetchall(),[])
        db.close()

    def test_unlinked_delete_and_repeated_save(self):
        item_id = self.create()
        self.assertEqual(self.create(),item_id)
        r = self.client.delete(f'/api/case-manager/todos/{item_id}')
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.client.get('/api/case-manager/todos').json()['items'],[])


if __name__ == '__main__':
    unittest.main()
