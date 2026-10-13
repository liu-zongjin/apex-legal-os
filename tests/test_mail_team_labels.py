import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.mail_team_labels import create_router


class MailTeamLabelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.dbpath = self.root / 'fixture.db'
        with self.db() as conn:
            conn.execute('CREATE TABLE suohan_lawyers(id INTEGER PRIMARY KEY, name TEXT)')
            conn.executemany('INSERT INTO suohan_lawyers VALUES (?,?)', [(1,'成员甲'),(2,'成员乙')])
        self.summaries = {'10':dict(date='2026-10-13',subject='测试一',**{'from':'anonymous@example.test'}),
                          '11':dict(date='2026-10-12',subject='测试二',**{'from':'other@example.test'})}
        self.mail = SimpleNamespace(MAILBOX_CONFIGS={'netease_exmail':{},'qq_mail':{}},
            _load_summary_cache=lambda *args: {'mails':self.summaries})
        self.client = self.make_client()

    def tearDown(self):
        self.temp.cleanup()

    def db(self):
        return sqlite3.connect(self.dbpath)

    def make_client(self):
        app = FastAPI()
        app.include_router(create_router(self.db, self.mail, self.root/'labels'))
        return TestClient(app)

    def snapshot(self, **params):
        return self.client.get('/api/qq-mail/team-labels',params=params).json()

    def assign(self, **kwargs):
        body = dict(uids=['10','11'],member_id=1)
        body.update(kwargs)
        return self.client.put('/api/qq-mail/team-labels',json=body)

    def test_bulk_persistence_reassign_clear_and_isolation(self):
        result = self.assign().json()
        self.assertEqual(result['updated_count'],2)
        self.assertEqual(result['assignments']['10']['identity'],self.summaries['10'])
        self.client = self.make_client()
        self.assertEqual(len(self.snapshot()['assignments']),2)
        self.assertEqual(self.snapshot(folder='sent')['assignments'],{})
        self.assertEqual(self.snapshot(account='qq_mail')['assignments'],{})
        self.assertEqual(self.assign(uids=['10'],member_id=2).json()['assignments']['10']['member_name'],'成员乙')
        self.assertEqual(self.assign(uids=['10'],member_id=None).json()['assignments'].keys(), {'11'})

    def test_member_library_rename_delete_and_atomic_validation(self):
        self.assign()
        with self.db() as conn:
            conn.execute("UPDATE suohan_lawyers SET name='新名称' WHERE id=1")
            conn.execute('DELETE FROM suohan_lawyers WHERE id=2')
        self.assertEqual(self.snapshot()['members'],[{'id':1,'name':'新名称'}])
        before = self.snapshot()['assignments']
        self.assertEqual(self.assign(member_id=2).status_code,400)
        self.assertEqual(self.assign(uids=['10','999']).status_code,409)
        self.assertEqual(self.snapshot()['assignments'],before)
        self.summaries.clear()
        self.assertEqual(self.snapshot()['assignments'],before)
        self.assertEqual(self.assign(member_id=None).status_code,200)

    def test_invalid_inputs_and_corruption_never_overwrite(self):
        for data in ({'account':'../escape'},{'folder':'../../escape'},{'uids':['../10']},{'uids':[]}):
            self.assertIn(self.assign(**data).status_code, (400,422))
        self.assign()
        path=self.root/'labels'/'netease_exmail-inbox.json'
        path.write_text('{invalid')
        self.assertEqual(self.client.get('/api/qq-mail/team-labels').status_code,500)
        self.assertEqual(self.assign().status_code,500)
        self.assertEqual(path.read_text(),'{invalid')

    def test_failed_atomic_replace_keeps_previous_labels(self):
        self.assign()
        before=self.snapshot()['assignments']
        with patch('backend.mail_team_labels.os.replace',side_effect=OSError('disk full')):
            self.assertEqual(self.assign(member_id=2).status_code,500)
        self.assertEqual(self.snapshot()['assignments'],before)
        self.assertFalse(list((self.root/'labels').glob('.labels-*')))
