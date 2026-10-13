import subprocess
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.matter_local_links import add_schema, register_routes, move_links, KINDS


class MatterLocalLinksTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / 'test.db'
        def get_db():
            conn = sqlite3.connect(self.db)
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA foreign_keys=ON')
            return conn
        self.get_db = get_db
        with get_db() as conn:
            for table, _ in KINDS.values():
                conn.execute(f'CREATE TABLE {table}(id INTEGER PRIMARY KEY,case_id INTEGER)')
                conn.executemany(f'INSERT INTO {table} VALUES (?,1)', [(1,), (2,)])
            add_schema(conn)
            conn.commit()
        app = FastAPI()
        register_routes(app, get_db)
        self.client = TestClient(app, base_url='http://localhost', client=('127.0.0.1', 12345))
        self.file = self.root / "材料 '含引号'.pdf"
        self.file.write_bytes(b'test')
        self.url = '/api/case-manager/matters/todos/1/local-links'

    def tearDown(self):
        self.temp.cleanup()

    def test_persistence_isolation_duplicates_and_unbind_preserves_file(self):
        for kind in KINDS:
            url = f'/api/case-manager/matters/{kind}/1/local-links'
            self.assertEqual(self.client.post(url, json={'path': str(self.file)}).status_code, 200)
            self.client.post(url, json={'path': str(self.file)})
            self.assertEqual(len(self.client.get(url).json()['items']), 1)
            self.assertEqual(self.client.get(url.replace('/1/', '/2/')).json()['items'], [])
        link = self.client.get(self.url).json()['items'][0]
        self.client.delete(self.url + '/' + str(link['id']))
        self.assertTrue(self.file.exists())
        self.assertEqual(self.client.get(self.url).json()['items'], [])
        self.assertEqual(len(self.client.get(self.url.replace('todos', 'hearings')).json()['items']), 1)

    def test_open_uses_bound_path_and_rejects_other_owner_missing_file(self):
        self.client.post(self.url, json={'path': str(self.file)})
        link = self.client.get(self.url).json()['items'][0]
        endpoint = self.url + '/' + str(link['id']) + '/open'
        with patch('backend.matter_local_links.shutil.which', return_value='/usr/bin/open'), patch('backend.matter_local_links.subprocess.run') as run:
            self.assertEqual(self.client.post(endpoint).status_code, 200)
            self.assertEqual(run.call_args.args[0], ['open', '--', str(self.file.resolve())])
            run.reset_mock()
            self.assertEqual(self.client.post(endpoint.replace('/1/', '/2/')).status_code, 404)
            run.assert_not_called()
            self.file.unlink()
            self.assertFalse(self.client.get(self.url).json()['items'][0]['exists'])
            self.assertEqual(self.client.post(endpoint).status_code, 400)
            run.assert_not_called()

    def test_folder_path_validation_owner_validation_and_cascade(self):
        self.assertEqual(self.client.post(self.url, json={'path': 'relative'}).status_code, 400)
        self.assertEqual(self.client.post(self.url, json={'path': 'https://example.com'}).status_code, 400)
        self.assertEqual(self.client.post(self.url.replace('/1/', '/999/'), json={'path': str(self.root)}).status_code, 404)
        self.client.post(self.url, json={'path': str(self.root)})
        self.assertEqual(self.client.get(self.url).json()['items'][0]['kind'], 'folder')
        with self.get_db() as conn:
            conn.execute('DELETE FROM case_manager_todos WHERE id=1')
            conn.commit()
            self.assertEqual(conn.execute('SELECT count(*) FROM case_manager_matter_local_links').fetchone()[0], 0)
        self.assertTrue(self.root.is_dir())

    def test_edit_replacing_record_retains_shortcuts(self):
        self.client.post(self.url, json={'path': str(self.file)})
        with self.get_db() as conn:
            move_links(conn, 'todos', 1, 2)
            conn.execute('DELETE FROM case_manager_todos WHERE id=1')
            conn.commit()
        items = self.client.get(self.url.replace('/1/', '/2/')).json()['items']
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]['exists'])

    def test_picker_cancel_timeout_and_remote_rejection(self):
        with patch('backend.matter_local_links.shutil.which', return_value='/usr/bin/osascript'), patch('backend.matter_local_links.subprocess.run') as run:
            run.return_value.returncode = 1
            run.return_value.stderr = 'User cancelled (-128)'
            self.assertTrue(self.client.post(self.url+'/select').json()['cancelled'])
            self.assertEqual(self.client.get(self.url).json()['items'], [])
            run.side_effect = subprocess.TimeoutExpired('osascript', 120)
            self.assertEqual(self.client.post(self.url+'/select').status_code, 408)
        for headers in [{'host':'stella.example.com'}, {'x-forwarded-for':'127.0.0.1'}, {'origin':'https://stella.example.com'}, {'origin':'null'}]:
            self.assertEqual(self.client.get(self.url, headers=headers).status_code, 403)
            self.assertEqual(self.client.post(self.url, json={'path': str(self.file)}, headers=headers).status_code, 403)

    def test_authenticated_desktop_is_allowed_in_private_mode(self):
        with patch.dict('os.environ', {'LEGAL_KB_PRIVATE_MODE':'1'}):
            self.assertEqual(self.client.get(self.url, headers={'origin':'http://localhost:8000'}).status_code, 200)
            self.assertEqual(self.client.post(self.url, json={'path': str(self.file)}).status_code, 200)
        remote = TestClient(self.client.app, base_url='http://localhost', client=('192.0.2.1', 12345))
        self.assertEqual(remote.get(self.url).status_code, 403)
