import sqlite3
from io import BytesIO

import openpyxl

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.article_notes import create_router


def test_note_links_round_trip_and_validation(tmp_path):
    path = tmp_path / 'test.sqlite'
    def db():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        return conn
    with db() as conn:
        conn.executescript('''
            CREATE TABLE articles(id INTEGER PRIMARY KEY, title TEXT);
            CREATE TABLE notes(id INTEGER PRIMARY KEY, article_id INTEGER, content TEXT, selected_text TEXT, created_at TEXT);
            CREATE TABLE case_manager_cases(id INTEGER PRIMARY KEY, deleted_at TEXT, title TEXT);
            CREATE TABLE case_reading_notes(note_id INTEGER REFERENCES notes(id) ON DELETE CASCADE, case_id INTEGER REFERENCES case_manager_cases(id) ON DELETE CASCADE, PRIMARY KEY(note_id,case_id));
            INSERT INTO articles VALUES(1,'文章');
            INSERT INTO notes VALUES(1,1,'笔记','原文','2026-01-01');
            INSERT INTO case_manager_cases VALUES(1,'','案件一'),(2,'','案件二'),(3,'deleted','已删除');
        ''')
    app = FastAPI()
    app.include_router(create_router(
        db, load_fada_notes=lambda: [],
        safe_export_filename=lambda name, fallback: name or fallback,
    ))
    client = TestClient(app)
    assert client.put('/api/reading-note-links/1', json={'case_ids':[1,2]}).status_code == 200
    assert set(client.get('/api/reading-note-links/1').json()) == {1,2}
    assert client.get('/api/case-reading-notes/2').json()[0]['content'] == '笔记'
    with db() as conn:
        conn.execute("UPDATE notes SET content='=1+1' WHERE id=1")
    response = client.get('/api/case-reading-notes/1/export')
    assert response.status_code == 200
    sheet = openpyxl.load_workbook(BytesIO(response.content)).active
    assert [cell.value for cell in sheet[2]] == [1, '案件一', '文章', '=1+1', '原文', '2026-01-01']
    assert sheet['D2'].data_type == 's'
    assert client.delete('/api/case-reading-notes/1/1').status_code == 200
    assert client.get('/api/reading-note-links/1').json() == [2]
    assert client.get('/api/case-reading-notes/2').json()[0]['content'] == '=1+1'
    assert client.delete('/api/case-reading-notes/1/1').status_code == 404
    assert client.put('/api/reading-note-links/1', json={'case_ids':[1,2]}).status_code == 200
    assert client.put('/api/reading-note-links/1', json={'case_ids':[3]}).status_code == 400
    assert set(client.get('/api/reading-note-links/1').json()) == {1,2}
    assert client.put('/api/reading-note-links/1', json={'case_ids':[]}).status_code == 200
    assert client.get('/api/case-reading-notes/1').json() == []
