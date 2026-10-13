"""Disposable anonymous workbench demo. Never imports backend.main or live data.

Run: python3 scripts/case_workflow_preview.py --port 8769
Model/OCR responses are clearly labeled fixtures; PDF/Office output is real.
"""
from __future__ import annotations
import argparse
import json
import re
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fitz
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from backend.case_workflows import register_case_workflow_routes
from backend.case_files import register_case_file_routes
from backend.case_automation import get_folder_binding


def create_preview_app(runtime=None):
    temporary = None
    if runtime is None:
        temporary = tempfile.TemporaryDirectory(prefix='stella-workflow-preview-')
        runtime = Path(temporary.name)
    runtime = Path(runtime); runtime.mkdir(exist_ok=True, parents=True)
    root = runtime / '匿名材料';root.mkdir(exist_ok=True)
    db = runtime / 'fixture.db'
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS case_manager_cases(id INTEGER PRIMARY KEY,title TEXT,case_type TEXT,source_status TEXT)')
        conn.execute('INSERT OR IGNORE INTO case_manager_cases VALUES(1,?,?,?)',('匿名合同纠纷','民事','active'))
        conn.execute('CREATE TABLE IF NOT EXISTS case_manager_folder_bindings(case_id INTEGER PRIMARY KEY,real_path TEXT,inode INTEGER,device_id INTEGER)')
        conn.execute('INSERT OR REPLACE INTO case_manager_folder_bindings VALUES(1,?,?,?)',(str(root),root.stat().st_ino,root.stat().st_dev))
    @contextmanager
    def get_db():
        conn=sqlite3.connect(db);conn.row_factory=sqlite3.Row
        try:yield conn
        finally:conn.close()
    for name,lines in [('01_合同.pdf',['匿名合同','价款为10000元。','付款日期为2026年1月1日。']),('02_付款凭证.pdf',['匿名付款凭证','2026年1月1日付款10000元。'])]:
        if not (root/name).exists():
            with fitz.open() as document:
                page=document.new_page()
                for i,line in enumerate(lines):page.insert_text((60,90+i*32),line,fontname='china-s',fontsize=14)
                document.save(root/name)
    (root/'03_草稿.txt').write_text('价款为10000元。付款日期为2026年1月1日。已支付全部价款。',encoding='utf-8')
    def parse(path,consent):
        if path.suffix=='.pdf':
            with fitz.open(path) as document:return {'content':'\n'.join(page.get_text() for page in document)}
        return {'content':path.read_text(encoding='utf-8')}
    async def ai(model,messages):
        data=json.loads(messages[-1]['content']);rows=[]
        for claim in data['claims']:
            source=next((s for s in data['sources'] if re.sub(r'\s+','',claim['claim']) in re.sub(r'\s+','',s['text'])),None)
            quote = source['text'].strip() if source else ''
            rows.append({'id':claim['id'],'status':'supported' if source else 'not_found','reason':'匿名演示：逐字匹配；不代表真实AI能力。','evidence':[{'source_id':source['id'],'quote':quote}] if source else []})
        return json.dumps({'results':rows}), '', '匿名演示模型'
    frontend=Path(__file__).resolve().parents[1]/'frontend'
    app=FastAPI();app.state.preview_temp=temporary;app.state.preview_root=root
    register_case_file_routes(app,get_db,frontend,parse_file=parse,call_ai=ai)
    register_case_workflow_routes(app,get_db,frontend,parse_file=parse,call_ai=ai,require_action=lambda request:None)
    app.mount('/static',StaticFiles(directory=frontend),name='static')
    @app.get('/api/case-manager/case-lookup')
    def lookup():return {'items':[{'id':1,'title':'匿名合同纠纷','case_type':'民事'}],'has_more':False}
    @app.get('/api/case-manager/cases/{case_id}/folder-binding')
    def binding(case_id:int):return get_folder_binding(get_db,case_id,required=True)
    @app.middleware('http')
    async def fixture_banner(request,call_next):
        response=await call_next(request)
        # Display a clear fixture banner in the workbench, without editing product code.
        if request.url.path=='/case-workflows':
            body=b''.join([chunk async for chunk in response.body_iterator]).decode('utf-8')
            body=body.replace('案件 / 办案工作台','匿名调试预览 / AI响应为测试夹具，未调用真实模型')
            from fastapi.responses import HTMLResponse
            return HTMLResponse(body,headers={'Cache-Control':'no-store'})
        return response
    return app

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8769);parser.add_argument('--runtime',type=Path)
    args=parser.parse_args()
    import uvicorn
    uvicorn.run(create_preview_app(args.runtime),host='127.0.0.1',port=args.port,log_level='warning')
