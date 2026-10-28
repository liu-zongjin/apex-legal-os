"""Series edits must affect top-level order before LIMIT and offline export."""
import ast
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import case_manager
from tests import test_series_manager as series_fixture


class SeriesActivityOrderTests(unittest.TestCase):
    setUp = series_fixture.SeriesManagerTests.setUp
    tearDown = series_fixture.SeriesManagerTests.tearDown
    create_series = series_fixture.SeriesManagerTests.create_series

    def listing_scope(self):
        app = FastAPI()
        tree = ast.parse(Path(case_manager.__file__).read_text())
        register = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'register_case_manager_routes')
        names = {'list_table', 'case_status_where', 'row_dict', 'norm', 'get_cases', 'build_case_manager_offline_snapshot', 'now_iso'}
        functions = [n for n in register.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
        scope = {**vars(case_manager), 'app':app, 'get_db':self.get_db, 'ENTITY_AUDIT_NAMES':{},
                 'case_manager_events':lambda **kw:{'items':[]}, 'dashboard_data':lambda:{},
                 'prepaid_expense_offline_snapshot':lambda db:{},
                 'court_online_offline_snapshot':lambda:{}}
        for name in ['get_case_types','get_case_stages','party_roles','case_number_types','preservation_types','court_options']:
            scope[name] = lambda **kw:{'items':[]}
        exec(compile(ast.Module(body=functions, type_ignores=[]), '<case-list-and-snapshot>', 'exec'), scope)
        return scope, TestClient(app)

    def old_records(self):
        series = self.create_series()
        with self.get_db() as db:
            db.execute('DELETE FROM case_manager_audit_logs')
            db.execute("UPDATE case_manager_cases SET updated_at='2026-01-01T09:00:00'")
            db.execute("UPDATE case_manager_cases SET updated_at='2026-02-01T09:00:00',pinned=1 WHERE id=1")
            db.execute("UPDATE case_manager_cases SET pinned=1 WHERE id=?",(series['id'],))
            db.commit()
        return series

    def test_each_edit_updates_child_and_parent_and_orders_within_pinned_group(self):
        series = self.old_records()
        child = series['children'][0]
        scope, client = self.listing_scope()
        base = f"/api/case-manager/series/{series['id']}/children/{child['id']}"
        for path, body in [('/cell',{'field':'case_no','value':'示例案号'}),
                           ('/cell-format',{'field':'memo','format':{'align':'right'}}),
                           ('/cell',{'field':'memo','value':'新的匿名备忘'})]:
            with self.subTest(path=path, body=body):
                with patch('backend.series_manager._now',return_value='2026-03-01T10:30:00'):
                    result = self.client.patch(base+path,json=body)
                self.assertEqual(result.status_code,200,result.text)
                with self.get_db() as db:
                    stamps = [r[0] for r in db.execute('SELECT updated_at FROM case_manager_cases WHERE id IN (?,?)',(series['id'],child['id']))]
                self.assertEqual(stamps,['2026-03-01T10:30:00']*2)
                items = client.get('/api/case-manager/cases?limit=1').json()['items']
                self.assertEqual(items[0]['id'],series['id'])
                self.assertEqual(items[0]['updated_at'],'2026-03-01T10:30:00')
        with self.get_db() as db:
            db.execute('UPDATE case_manager_cases SET pinned=0 WHERE id=?',(series['id'],));db.commit()
        self.assertEqual(client.get('/api/case-manager/cases?limit=1').json()['items'][0]['id'],1)

    def test_historical_child_edits_and_audits_are_read_without_rewriting_records(self):
        series=self.old_records(); child=series['children'][0]
        scope, client=self.listing_scope()
        with self.get_db() as db:
            db.execute("UPDATE case_manager_cases SET updated_at='2026-03-01T08:00:00' WHERE id=?",(child['id'],))
            db.commit()
        self.assertEqual(client.get('/api/case-manager/cases?limit=1').json()['items'][0]['updated_at'],'2026-03-01T08:00:00')
        with self.get_db() as db:
            db.execute("INSERT INTO case_manager_audit_logs(case_id,entity_type,action,created_at) VALUES (?,'series','updated','2026-03-02T08:00:00')",(child['id'],));db.commit()
        snapshot=scope['build_case_manager_offline_snapshot']()
        self.assertEqual(snapshot['cases']['active'][0]['id'],series['id'])
        self.assertEqual(snapshot['cases']['active'][0]['updated_at'],'2026-03-02T08:00:00')
        self.assertEqual(client.get('/api/case-manager/cases?limit=1').json()['items'][0]['updated_at'],'2026-03-02T08:00:00')
        with self.get_db() as db:
            self.assertEqual(db.execute('SELECT updated_at FROM case_manager_cases WHERE id=?',(series['id'],)).fetchone()[0],'2026-01-01T09:00:00')

    def test_failed_edit_does_not_touch_case_or_parent(self):
        series=self.old_records();child=series['children'][0]
        result=self.client.patch(f"/api/case-manager/series/{series['id']}/children/{child['id']}/cell",json={'field':'nonexistent','value':'invalid'})
        self.assertEqual(result.status_code,400)
        with self.get_db() as db:
            self.assertEqual([r[0] for r in db.execute('SELECT updated_at FROM case_manager_cases WHERE id IN (?,?)',(series['id'],child['id']))],['2026-01-01T09:00:00']*2)

if __name__=='__main__':unittest.main()
