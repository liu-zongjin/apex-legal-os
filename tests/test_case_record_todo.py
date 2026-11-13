"""Record-to-todo integration uses a disposable database and anonymous records."""
import ast
import asyncio
import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.case_manager import case_record_plain_text

ROOT = Path(__file__).resolve().parents[1]


def test_record_sync_is_distinct_idempotent_and_preserves_text(tmp_path):
    db_path = tmp_path / 'test.db'
    with sqlite3.connect(db_path) as db:
        db.executescript('''
            CREATE TABLE case_manager_cases(id INTEGER PRIMARY KEY,title TEXT);
            CREATE TABLE research_projects(id INTEGER PRIMARY KEY,case_id INTEGER);
            CREATE TABLE research_case_ledgers(id INTEGER PRIMARY KEY,project_id INTEGER,title TEXT,content TEXT);
            CREATE TABLE research_case_memo_entries(id INTEGER PRIMARY KEY,project_id INTEGER,title TEXT,content TEXT);
            CREATE TABLE case_manager_todos(id INTEGER PRIMARY KEY,case_id INTEGER,title TEXT,todo_title TEXT,
                remind_at TEXT,recurrence TEXT,notes TEXT,status TEXT,created_at TEXT,updated_at TEXT,source_key TEXT UNIQUE);
            INSERT INTO case_manager_cases VALUES(1,'匿名案件'),(2,'另一案件');
            INSERT INTO research_projects VALUES(1,1);
            INSERT INTO research_case_ledgers VALUES(1,1,'相同标题','<p>第一段</p><p>第二段 &amp; 原文</p>');
            INSERT INTO research_case_memo_entries VALUES(1,1,'相同标题','备忘录原文');
        ''')
    @contextmanager
    def get_db():
        conn = sqlite3.connect(db_path); conn.row_factory = sqlite3.Row
        try: yield conn
        finally: conn.close()
    async def ai(*args, **kwargs):
        return {'choices':[{'message':{'content':'核对案件材料'}}]}, 'fixture'
    tree = ast.parse((ROOT/'backend/case_manager.py').read_text())
    register = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'register_case_manager_routes')
    route = next(n for n in register.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'record_to_todo')
    app = FastAPI()
    scope = dict(app=app,get_db=get_db,HTTPException=HTTPException,re=re,json=json,asyncio=asyncio,
                 ai_call=ai,DEFAULT_AI_MODEL='fixture',case_record_plain_text=case_record_plain_text,now_iso=lambda:'2026-01-01',
                 add_audit_log=lambda *args: None, audit_row=lambda *args: {}, ENTITY_AUDIT_FIELDS={'todo': {}})
    exec(compile(ast.Module(body=[route],type_ignores=[]),'record-todo','exec'),scope)
    client = TestClient(app)
    url = '/api/case-manager/cases/1/records/ledger/1/todo'
    first = client.post(url).json()
    assert first['existing'] is False and first['title'] == '核对案件材料'
    with sqlite3.connect(db_path) as db:
        row = db.execute('SELECT notes,remind_at FROM case_manager_todos').fetchone()
        assert row == ('第一段\n第二段 & 原文','')
        db.execute("UPDATE case_manager_todos SET notes='用户修改' WHERE id=?",(first['id'],))
    second = client.post(url).json()
    assert second['existing'] and second['id'] == first['id']
    other = client.post('/api/case-manager/cases/1/records/memo/1/todo').json()
    assert other['id'] != first['id']
    assert client.post('/api/case-manager/cases/2/records/ledger/1/todo').status_code == 404
    with sqlite3.connect(db_path) as db:
        assert db.execute('SELECT notes FROM case_manager_todos WHERE id=?',(first['id'],)).fetchone()[0] == '用户修改'
        assert db.execute('SELECT COUNT(*) FROM case_manager_todos').fetchone()[0] == 2
    async def failing_ai(*args, **kwargs): raise RuntimeError('unavailable')
    scope['ai_call'] = failing_ai
    with sqlite3.connect(db_path) as db:
        db.execute("INSERT INTO research_case_ledgers VALUES(2,1,'备用标题','完整内容')")
    fallback = client.post('/api/case-manager/cases/1/records/ledger/2/todo').json()
    assert fallback['fallback'] and fallback['title'] == '备用标题'
