import asyncio
import ast
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException
from backend.mingsi_chapter_service import _load_metadata

from backend.business_profile import KEY, chapter_approver, firm_defaults
from backend.automated_filing import _ensure_schema


class BusinessProfileTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'anonymous.db'

    def tearDown(self):
        self.directory.cleanup()

    def get_db(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def test_unconfigured_installation_has_no_business_identity(self):
        with self.get_db() as conn:
            self.assertTrue(all(not value for value in firm_defaults(conn).values()))
        self.assertEqual(chapter_approver(self.get_db), '')

    def test_identity_and_bank_are_read_from_database(self):
        with self.get_db() as conn:
            conn.execute('CREATE TABLE app_preferences(preference_key TEXT PRIMARY KEY,value_json TEXT,updated_at TEXT)')
            conn.execute('INSERT INTO app_preferences VALUES(?,?,?)',
                         (KEY, json.dumps({'firm': {'name': '匿名测试律所', 'account': 'TEST-ACCOUNT'},
                                           'chapter_approver': '匿名审批人'}), 'fixture'))
        with self.get_db() as conn:
            self.assertEqual(firm_defaults(conn)['account'], 'TEST-ACCOUNT')
            self.assertEqual(firm_defaults(conn)['address'], '')
        self.assertEqual(chapter_approver(self.get_db), '匿名审批人')
        other = sqlite3.connect(':memory:')
        self.assertEqual(firm_defaults(other)['account'], '')
        other.close()

    def test_filing_initialization_never_seeds_people_or_contacts(self):
        _ensure_schema(self.get_db)
        with self.get_db() as conn:
            for table in ('automated_filing_agent_profiles', 'automated_filing_service_contacts',
                          'automated_filing_legal_rep_phones'):
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0], 0)
            conn.execute('INSERT INTO automated_filing_agent_profiles(name,updated_at) VALUES(?,?)',
                         ('匿名律师', 'fixture'))
        _ensure_schema(self.get_db)
        with self.get_db() as conn:
            self.assertEqual(conn.execute('SELECT name FROM automated_filing_agent_profiles').fetchone()[0], '匿名律师')

    def test_missing_approver_stops_before_external_requests(self):
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(_load_metadata(object(), ''))
        self.assertEqual(raised.exception.status_code, 422)

    def test_document_initialization_preserves_only_public_taxonomies(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'backend/main.py').read_text())
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name in ('_init_suohan_tables', '_init_suohan_defaults')]
        namespace = {'sqlite3': sqlite3}
        exec(compile(ast.Module(body=functions, type_ignores=[]), '<initialization>', 'exec'), namespace)
        with self.get_db() as conn:
            namespace['_init_suohan_tables'](conn)
            namespace['_init_suohan_defaults'](conn)
            for table in ('suohan_lawyers', 'suohan_clients', 'suohan_parties'):
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0], 0)
            self.assertGreater(conn.execute('SELECT COUNT(*) FROM suohan_case_types').fetchone()[0], 0)
            self.assertGreater(conn.execute('SELECT COUNT(*) FROM suohan_stages').fetchone()[0], 0)
