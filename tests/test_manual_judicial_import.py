import asyncio
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from backend import judicial_messages as jm
from tests import test_judicial_messages as existing_tests


class Request:
    def __init__(self, data): self.data = data
    async def json(self): return self.data
    async def form(self): return self.data


class Upload:
    def __init__(self, name, data): self.filename, self.data = name, data
    async def read(self, size): return self.data[:size]
    async def close(self): pass


class ManualImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = Path(self.temp.name) / 'anonymous.db'
        connections=[]
        self.addCleanup(lambda: [conn.close() for conn in connections])
        def db():
            conn = sqlite3.connect(path)
            connections.append(conn)
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA foreign_keys=ON')
            return conn
        self.db = db
        with db() as conn:
            conn.executescript('''
              CREATE TABLE case_manager_cases(id INTEGER PRIMARY KEY,title TEXT,case_type TEXT,current_stage TEXT,source_status TEXT);
              CREATE TABLE case_manager_case_numbers(case_id INTEGER,case_no TEXT,court TEXT);
              CREATE TABLE case_manager_parties(case_id INTEGER,name TEXT);
              CREATE TABLE case_manager_files(id INTEGER PRIMARY KEY,relative_path TEXT,absolute_path TEXT);
              INSERT INTO case_manager_cases VALUES(1,'示例合同纠纷','民事','一审','active');
              INSERT INTO case_manager_case_numbers VALUES(1,'（2026）粤0101民初123号','示例法院');
            ''')
        jm._ensure_schema(db)
        with db() as conn:
            conn.execute('UPDATE case_manager_message_settings SET ai_enabled=0')
        app = existing_tests.JudicialMessageStorageTests._route_app()
        jm.register_judicial_message_routes(app, db, {})
        self.preview = app.routes[('POST','/api/case-manager/judicial-messages/import-preview')]
        self.commit = app.routes[('POST','/api/case-manager/judicial-messages/import')]

    def count(self):
        with self.db() as conn:
            return conn.execute('SELECT count(*) FROM case_manager_judicial_messages').fetchone()[0]

    def test_preview_never_writes_and_utf8_text_is_editable(self):
        result = asyncio.run(self.preview(Request({'file':Upload('短信.txt','请核对送达材料'.encode())})))
        self.assertEqual(result['text'],'请核对送达材料')
        self.assertTrue(result['requires_confirmation'])
        self.assertEqual(self.count(),0)

    def test_import_keeps_case_suggestion_but_does_not_automatically_write_outputs(self):
        body = {'confirmed':True,'text':'【示例法院】（2026）粤0101民初123号定于2026年11月2日9时开庭。'}
        result = asyncio.run(self.commit(Request(body)))
        with self.db() as conn:
            row = conn.execute('SELECT * FROM case_manager_judicial_messages').fetchone()
            self.assertEqual(row['suggested_case_id'],1)
            self.assertEqual(row['workflow_status'],'suggested')
            self.assertIsNone(row['matched_case_id'])
            self.assertEqual(row['received_at'],'')
            self.assertEqual(conn.execute('SELECT count(*) FROM case_manager_message_links').fetchone()[0],0)
        duplicate = asyncio.run(self.commit(Request(body)))
        self.assertTrue(duplicate['duplicate'])
        self.assertEqual(result['id'], duplicate['id'])
        self.assertEqual(self.count(),1)

    def test_confirmation_and_received_time_are_required_to_be_valid(self):
        for data in ({'text':'通知'}, {'text':'通知','confirmed':True,'received_at':'昨天'}):
            with self.assertRaises(jm.HTTPException):
                asyncio.run(self.commit(Request(data)))
        self.assertEqual(self.count(),0)

    def test_screenshot_ocr_stays_a_preview(self):
        from PIL import Image
        image = BytesIO()
        Image.new('RGB',(50,50),'white').save(image, format='PNG')
        with patch('backend.court_directory.ocr_image_bytes',return_value='请核对 OCR 文字'):
            result = asyncio.run(self.preview(Request({'file':Upload('短信.png',image.getvalue())})))
        self.assertEqual(result['source'],'manual-image')
        self.assertEqual(self.count(),0)

    def test_unrecognized_and_oversized_uploads_are_rejected_without_writes(self):
        for file in (Upload('短信.exe',b'not text'),Upload('短信.txt',b'a'*(8*1024*1024+1))):
            with self.assertRaises(jm.HTTPException):
                asyncio.run(self.preview(Request({'file':file})))
        self.assertEqual(self.count(),0)


if __name__ == '__main__': unittest.main()
