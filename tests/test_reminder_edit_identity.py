"""Exercise reminder saves against anonymous SQLite records through real routes."""
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
KINDS = {
    'todo': ('todos', {'todo_title': '核对材料', 'remind_at': '2026-11-20T09:00', 'recurrence': 'weekly'}, 'remind_at'),
    'hearing': ('hearings', {'reminder_type': '开庭', 'hearing_at': '2026-11-20T09:00', 'location': '第一法庭'}, 'hearing_at'),
    'preservation': ('preservations', {'preservation_type': '冻结', 'asset_content': '匿名资产', 'start_at': '2026-11-01', 'deadline_at': '2026-11-20', 'period_years': 1}, 'deadline_at'),
    'appeal': ('appeals', {'appeal_type': '上诉', 'start_at': '2026-11-01', 'deadline_at': '2026-11-20', 'period_days': 15}, 'deadline_at'),
}


class ReminderEditIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='stella-reminder-edits-')
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'fixture.db'
        with sqlite3.connect(self.path) as db:
            db.executescript(BASE_SCHEMA)
            db.executescript("""
                ALTER TABLE case_manager_todos ADD COLUMN recurrence TEXT DEFAULT '';
                ALTER TABLE case_manager_todos ADD COLUMN completed_at TEXT DEFAULT '';
                ALTER TABLE case_manager_todos ADD COLUMN completed_ledger_id INTEGER;
                INSERT INTO case_manager_cases(id,title,created_at,updated_at) VALUES(1,'匿名案件','old','old');
                INSERT INTO case_manager_cases(id,title,created_at,updated_at) VALUES(2,'另一匿名案件','old','old');
                CREATE TABLE research_projects(id INTEGER PRIMARY KEY,case_id,name,client,case_info,issues,status,notes,created_at,updated_at);
                CREATE TABLE research_case_ledgers(id INTEGER PRIMARY KEY,project_id,title,content,happened_at,source_type,source_id,created_at,updated_at);
            """)
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
        register = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'register_case_manager_routes')
        names = {'now_iso', 'norm', 'row_dict', 'normalize_todo_recurrence', 'to_iso', 'source_key',
                 'merge_text_values', 'merge_record_text', 'audit_row', 'audit_text', 'add_audit_log',
                 'save_reminder', 'ensure_case_research_project', 'sync_hearing_to_case_ledger', 'delete_hearing_case_ledger'}
        names.update(f'{action}_{kind}' for kind in KINDS for action in ('upsert', 'create', 'update'))
        functions = [n for n in register.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
        scope = {**vars(module), 'app': app, 'get_db': get_db,
                 'ENTITY_AUDIT_NAMES': dict.fromkeys(KINDS, '提醒'),
                 'ENTITY_AUDIT_FIELDS': {kind: {} for kind in KINDS},
                 'auto_sync_if_enabled': lambda *a, **k: self.syncs.append(a),
                 'delete_calendar_sync_record': lambda *a: None,
                 'move_matter_local_links': lambda *a: None}
        exec(compile(ast.Module(body=functions, type_ignores=[]), '<real-reminder-routes>', 'exec'), scope)
        self.scope = scope
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def body(self, kind):
        return {'case_id': 1, 'title': '匿名案件', 'notes': '原始备注', **KINDS[kind][1]}

    def create(self, kind, body):
        response = self.client.post(f'/api/case-manager/{KINDS[kind][0]}', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['id']

    def rows(self, kind):
        with self.get_db() as db:
            return [dict(row) for row in db.execute(f'SELECT * FROM case_manager_{KINDS[kind][0]} ORDER BY id')]

    def test_date_edits_keep_identity_source_and_hearing_ledger(self):
        for kind, (plural, _, date_field) in KINDS.items():
            with self.subTest(kind=kind):
                body = self.body(kind)
                item_id = self.create(kind, body)
                before = self.rows(kind)[0]
                response = self.client.put(f'/api/case-manager/{plural}/{item_id}', json={**body, date_field: '2026-11-25T10:00'})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()['id'], item_id)
                after = self.rows(kind)[0]
                self.assertEqual((after['source_key'], after['created_at']), (before['source_key'], before['created_at']))
                if kind == 'hearing':
                    with self.get_db() as db:
                        ledgers = db.execute('SELECT source_id,happened_at FROM research_case_ledgers').fetchall()
                        self.assertEqual(len(ledgers), 1)
                        self.assertEqual(ledgers[0]['source_id'], item_id)
                        self.assertIn('2026-11-25', ledgers[0]['happened_at'])

    def test_clear_notes_and_contacts_replaces_old_text(self):
        for kind, (plural, _, _) in KINDS.items():
            with self.subTest(kind=kind):
                body = {**self.body(kind), 'court_contact': '原联系人', 'party_contact': '原当事人联系人'}
                item_id = self.create(kind, body)
                response = self.client.put(f'/api/case-manager/{plural}/{item_id}', json={**body, 'notes': '', 'court_contact': '', 'party_contact': ''})
                self.assertEqual(response.status_code, 200, response.text)
                row = self.rows(kind)[0]
                self.assertEqual(row['notes'], '')
                if kind in ('hearing', 'appeal'):
                    self.assertEqual(row['court_contact'], '')
                    self.assertEqual(row['party_contact'], '')

    def test_recreating_pre_edit_values_cannot_overwrite_the_edited_record(self):
        for kind, (plural, _, date_field) in KINDS.items():
            with self.subTest(kind=kind):
                body = self.body(kind)
                item_id = self.create(kind, body)
                # Simulate an older installation's content-derived source key.
                before = self.rows(kind)[0]
                fields = {
                    'todo': ['case_id', 'title', 'todo_title', 'remind_at', 'recurrence'],
                    'hearing': ['case_id', 'title', 'reminder_type', 'hearing_at', 'location'],
                    'preservation': ['case_id', 'title', 'preservation_type', 'asset_content', 'start_at', 'deadline_at', 'period_years'],
                    'appeal': ['case_id', 'title', 'appeal_type', 'start_at', 'period_days', 'deadline_at'],
                }[kind]
                legacy_key = self.scope['source_key'](kind, *(before[field] for field in fields))
                with self.get_db() as db:
                    db.execute(f"UPDATE case_manager_{plural} SET source_key=? WHERE id=?", (legacy_key, item_id))
                    db.commit()
                response = self.client.put(f'/api/case-manager/{plural}/{item_id}', json={**body, date_field: '2026-12-01'})
                self.assertEqual(response.status_code, 200, response.text)
                second_id = self.create(kind, body)
                self.assertNotEqual(item_id, second_id)
                rows = self.rows(kind)
                self.assertIn('2026-12-01', rows[0][date_field])
                self.assertEqual(rows[0]['source_key'], legacy_key)

    def test_edit_matching_another_record_does_not_merge_or_delete(self):
        for kind, (plural, _, date_field) in KINDS.items():
            with self.subTest(kind=kind):
                body = self.body(kind)
                first_id = self.create(kind, body)
                second_id = self.create(kind, {**body, date_field: '2026-12-01', 'notes': '第二条'})
                first = self.rows(kind)[0]
                response = self.client.put(f'/api/case-manager/{plural}/{second_id}', json={**body, 'notes': '修改第二条'})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()['id'], second_id)
                rows = self.rows(kind)
                self.assertEqual([r['id'] for r in rows], [first_id, second_id])
                self.assertEqual(rows[0], first)

    def test_missing_update_is_rejected_without_inserting(self):
        for kind, (plural, _, _) in KINDS.items():
            with self.subTest(kind=kind):
                response = self.client.put(f'/api/case-manager/{plural}/999', json=self.body(kind))
                self.assertEqual(response.status_code, 404, response.text)
                self.assertEqual(self.rows(kind), [])
        self.assertEqual(self.syncs, [])

    def test_case_reassignment_preserves_incoming_links_and_hearing_ledger_id(self):
        for kind, (plural, _, _) in KINDS.items():
            with self.subTest(kind=kind):
                body = self.body(kind)
                item_id = self.create(kind, body)
                with self.get_db() as db:
                    db.execute(f'CREATE TABLE fixture_{plural}_links(item_id REFERENCES case_manager_{plural}(id) ON DELETE CASCADE)')
                    db.execute(f'INSERT INTO fixture_{plural}_links VALUES(?)', (item_id,))
                    ledger = db.execute('SELECT id FROM research_case_ledgers WHERE source_id=?', (item_id,)).fetchone() if kind == 'hearing' else None
                    db.commit()
                response = self.client.put(f'/api/case-manager/{plural}/{item_id}', json={**body, 'case_id': 2})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()['id'], item_id)
                row = self.rows(kind)[0]
                self.assertEqual((row['case_id'], row['title']), (2, '另一匿名案件'))
                with self.get_db() as db:
                    self.assertEqual(db.execute(f'SELECT item_id FROM fixture_{plural}_links').fetchone()[0], item_id)
                    self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
                    if kind == 'hearing':
                        moved = db.execute('SELECT l.id,p.case_id FROM research_case_ledgers l JOIN research_projects p ON p.id=l.project_id').fetchone()
                        self.assertEqual(tuple(moved), (ledger['id'], 2))

    def test_explicit_case_id_is_validated_and_owns_display_title(self):
        for kind, (plural, _, _) in KINDS.items():
            with self.subTest(kind=kind):
                for case_id in (999, 'invalid'):
                    response = self.client.post(f'/api/case-manager/{plural}', json={**self.body(kind), 'case_id': case_id})
                    self.assertEqual(response.status_code, 400, response.text)
                self.create(kind, {**self.body(kind), 'title': '过时的案件名'})
                self.assertEqual(self.rows(kind)[0]['title'], '匿名案件')

    def test_different_todo_recurrences_remain_separate(self):
        first = self.create('todo', self.body('todo'))
        second = self.create('todo', {**self.body('todo'), 'recurrence': 'monthly'})
        self.assertNotEqual(first, second)
        self.assertEqual([r['recurrence'] for r in self.rows('todo')], ['weekly', 'monthly'])

    def test_edit_preserves_completion_fields(self):
        body = self.body('todo')
        item_id = self.create('todo', body)
        with self.get_db() as db:
            db.execute("UPDATE case_manager_todos SET status='completed',completed_at='2026-11-16',completed_ledger_id=7 WHERE id=?", (item_id,))
            db.commit()
        response = self.client.put(f'/api/case-manager/todos/{item_id}', json={**body, 'remind_at': '2026-12-01'})
        self.assertEqual(response.status_code, 200, response.text)
        row = self.rows('todo')[0]
        self.assertEqual((row['id'], row['status'], row['completed_at'], row['completed_ledger_id']), (item_id, 'completed', '2026-11-16', 7))


if __name__ == '__main__':
    unittest.main()
