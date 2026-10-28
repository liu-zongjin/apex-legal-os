"""Exercise the actual opponent creation route against a disposable database."""
import ast
import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient


class OpponentCreationTests(unittest.TestCase):
    def test_create_company_and_person(self):
        source = Path(__file__).resolve().parents[1] / 'backend/case_manager.py'
        tree = ast.parse(source.read_text())
        register = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'register_case_manager_routes')
        functions = [n for n in register.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and n.name in {'normalized_opponent_body', 'create_opponent'}]
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'test.sqlite'
            fields = ('opponent_type name document_type nationality gender identity_code address legal_representative '
                      'legal_representative_document_type legal_representative_document_number legal_representative_mobile '
                      'registered_capital establishment_date registration_status business_scope enterprise_nature industry region '
                      'data_source source_checked_at contact_person phone notes contacts_json created_at updated_at').split()
            with sqlite3.connect(database) as conn:
                conn.execute('CREATE TABLE case_manager_opponents (id INTEGER PRIMARY KEY, ' + ', '.join(f + ' TEXT' for f in fields) + ')')
            @contextmanager
            def get_db():
                conn = sqlite3.connect(database)
                conn.row_factory = sqlite3.Row
                try:
                    yield conn
                finally:
                    conn.close()
            def detail(identifier):
                with get_db() as conn:
                    return dict(conn.execute('SELECT * FROM case_manager_opponents WHERE id=?', (identifier,)).fetchone())
            app = FastAPI()
            env = {'app': app, 'Request': Request, 'HTTPException': HTTPException, 'Dict': Dict, 'Any': Any,
                   'json': json, 'norm': lambda x: str(x or '').strip(), 'get_db': get_db,
                   'now_iso': lambda: '2026-01-01', 'set_managed_option_hidden': lambda *args: None,
                   'get_opponent_detail': detail}
            exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), 'exec'), env)
            client = TestClient(app)
            for name, kind in [('匿名公司', '单位'), ('匿名个人', '个人')]:
                response = client.post('/api/case-manager/opponents', json={'name': name, 'opponent_type': kind, 'contacts': [{'name': '联系人', 'phone': '123'}]})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()['name'], name)
                self.assertEqual(response.json()['contact_person'], '联系人')
                self.assertEqual(client.post('/api/case-manager/opponents', json={'name': name}).status_code, 409)


if __name__ == '__main__':
    unittest.main()
