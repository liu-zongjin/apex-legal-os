"""Exercise calendar settings and alarm construction against isolated SQLite."""
import ast
import contextlib
import datetime as dt
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import case_manager as module
from backend.migrations import _add_todo_calendar_rules, migrate_database

ROOT = Path(__file__).resolve().parents[1]


class CalendarReminderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'calendar.db'
        # Start with the legacy schema to exercise migration compatibility.
        with sqlite3.connect(self.path) as db:
            db.execute('''CREATE TABLE case_manager_calendar_settings (
                id INTEGER PRIMARY KEY, enabled INTEGER, calendar_name TEXT,
                hearing_reminder_days TEXT, hearing_reminder_time TEXT,
                preservation_reminder_days TEXT, preservation_reminder_time TEXT,
                appeal_reminder_days TEXT, appeal_reminder_time TEXT, updated_at TEXT)''')
            db.execute("INSERT INTO case_manager_calendar_settings VALUES(1,0,'匿名-iCloud','[5]','08:00','[15]','10:00','[10]','11:00','old')")
        migrate_database(self.path, Path(self.tmp.name) / 'backups')
        @contextlib.contextmanager
        def get_db():
            db = sqlite3.connect(self.path)
            db.row_factory = sqlite3.Row
            try:
                yield db
            finally:
                db.close()
        app = FastAPI()
        tree = ast.parse((ROOT / 'backend/case_manager.py').read_text())
        register = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'register_case_manager_routes')
        names = {'to_iso', 'norm', 'now_iso', 'row_dict', 'parse_date', 'parse_datetime',
                 'normalize_todo_recurrence', 'parse_reminder_days', 'parse_reminder_time',
                 'calendar_rule', 'default_calendar_settings', 'calendar_settings',
                 'save_calendar_settings', 'calendar_event_spec', 'applescript_date',
                 'script_quote', 'calendar_prelude', 'create_calendar_event_via_applescript'}
        functions = [n for n in register.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
        self.scope = {**vars(module), 'get_db': get_db, 'app': app}
        exec(compile(ast.Module(body=functions, type_ignores=[]), '<calendar-routes>', 'exec'), self.scope)
        self.client = TestClient(app)
        self.start = (dt.datetime.now() + dt.timedelta(days=40)).replace(hour=14, minute=25, second=0, microsecond=0)
        self.item = {'id': 1, 'todo_title': '匿名待办', 'remind_at': self.start.isoformat(), 'recurrence': 'weekly'}

    def test_upgrade_preserves_old_rules_and_has_backup(self):
        settings = self.scope['calendar_settings']()
        self.assertEqual(settings['todo_reminder_days'], '[0]')
        self.assertEqual(settings['todo_reminder_time'], '')
        self.assertEqual(settings['hearing_reminder_time'], '08:00')
        self.assertEqual(settings['preservation_reminder_days'], '[15]')
        self.assertEqual(len(list((Path(self.tmp.name) / 'backups').glob('*.db'))), 1)
        with sqlite3.connect(self.path) as db:
            _add_todo_calendar_rules(db)
        self.assertEqual(migrate_database(self.path), [])

    def save(self, **patch):
        settings = self.scope['calendar_settings']()
        result = self.client.post('/api/case-manager/calendar/settings', json={**settings, **patch})
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()['settings']

    def test_defaults_preserve_original_time_and_recurrence(self):
        spec = self.scope['calendar_event_spec']('todo', self.item)
        self.assertEqual(spec['alarms'], [self.start])
        self.assertEqual(spec['start'], self.start)
        self.assertEqual(spec['recurrence'], 'weekly')
        with sqlite3.connect(self.path) as db:
            db.execute('DELETE FROM case_manager_calendar_settings')
            db.commit()
        self.assertEqual(self.scope['calendar_settings']()['todo_reminder_time'], '')
        self.assertEqual(self.scope['calendar_event_spec']('todo', self.item)['alarms'], [self.start])

    def test_save_reload_custom_rules_and_calendar_alarm_output(self):
        saved = self.save(todo_reminder_days='7，3,0,3,-1,400', todo_reminder_time='08:45')
        self.assertEqual(json.loads(saved['todo_reminder_days']), [7, 3, 0])
        self.assertEqual(saved['todo_reminder_time'], '08:45')
        spec = self.scope['calendar_event_spec']('todo', self.item)
        expected = [(self.start - dt.timedelta(days=d)).replace(hour=8, minute=45) for d in [7, 3, 0]]
        self.assertEqual(spec['alarms'], expected)
        self.assertEqual(spec['start'], self.start)
        scripts = []
        self.scope['run_osascript'] = lambda script: scripts.append(script) or 'anonymous-uid'
        self.scope['create_calendar_event_via_applescript']('匿名-iCloud', spec)
        self.assertEqual(scripts[0].count('make new display alarm'), 3)
        self.assertIn('set time of alarmDate1 to 31500', scripts[0])

    def test_empty_time_reset_and_old_clients_preserve_todo_rule(self):
        saved = self.save(todo_reminder_days='3,0', todo_reminder_time='08:45')
        old_body = {k: v for k, v in saved.items() if not k.startswith('todo_')}
        self.assertEqual(self.client.post('/api/case-manager/calendar/settings', json=old_body).json()['settings']['todo_reminder_time'], '08:45')
        self.save(todo_reminder_time='')
        spec = self.scope['calendar_event_spec']('todo', self.item)
        self.assertEqual(spec['alarms'], [self.start - dt.timedelta(days=3), self.start])

    def test_expired_alarms_filtered_and_other_types_unchanged(self):
        self.save(todo_reminder_days='365,0', todo_reminder_time='')
        self.assertEqual(self.scope['calendar_event_spec']('todo', self.item)['alarms'], [self.start])
        self.assertIsNone(self.scope['calendar_event_spec']('todo', {}))
        hearing = self.scope['calendar_event_spec']('hearing', {'id': 2, 'hearing_at': self.start.isoformat()})
        self.assertEqual(hearing['alarms'], [(self.start - dt.timedelta(days=5)).replace(hour=8, minute=0)])

    def test_single_day_setting_is_not_replaced_by_default(self):
        saved = self.save(todo_reminder_days='3')
        self.assertEqual(json.loads(saved['todo_reminder_days']), [3])
        self.assertEqual(self.scope['calendar_event_spec']('todo', self.item)['alarms'], [self.start - dt.timedelta(days=3)])
