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
from backend.agent_tasks import add_schema, register_agent_task_routes
from backend.agent_policy import before_request


def create_preview_app(runtime=None):
    temporary = None
    if runtime is None:
        temporary = tempfile.TemporaryDirectory(prefix='stella-workflow-preview-')
        runtime = Path(temporary.name)
    runtime = Path(runtime); runtime.mkdir(exist_ok=True, parents=True)
    root = runtime / '匿名材料';root.mkdir(exist_ok=True)
    db = runtime / 'fixture.db'
    with sqlite3.connect(db) as conn:
        add_schema(conn)
        conn.execute('CREATE TABLE IF NOT EXISTS research_projects(id INTEGER PRIMARY KEY,case_id INTEGER,name TEXT)')
        conn.execute("INSERT OR REPLACE INTO research_projects VALUES(1,1,'匿名研究项目')")
        conn.execute('CREATE TABLE IF NOT EXISTS articles(id INTEGER PRIMARY KEY,title TEXT,summary TEXT,content TEXT)')
        conn.execute('INSERT OR REPLACE INTO articles VALUES(1,?,?,?)', ('合同履行与付款抗辩研究', '匿名夹具',
                     '合同价款与实际付款应结合合同约定及付款凭证核对，不能将请求直接当作已证明事实。' * 5))
        conn.execute('CREATE TABLE IF NOT EXISTS research_project_articles(case_id INTEGER,article_id INTEGER, UNIQUE(case_id,article_id))')
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
        before_request(model)
        data=json.loads(messages[-1]['content']);rows=[]
        if 'goal' in data:
            source=data['sources'][0]
            return json.dumps({'items':[{'title':'匿名演示：核对付款情况','type':'issue',
                'analysis':'材料显示合同约定及履行信息，需结合完整凭证核对；此处为匿名测试夹具。',
                'evidence':[{'source_id':source['id'],'quote':source['text'].strip()[:1000]}],
                'follow_up':'核对凭证对应关系与原文。'}]}), '', model
        if '案件关联知识助手' in messages[0]['content']:
            if 'article' not in data:
                source=data['sources'][0]
                return json.dumps({'topics':[{'question':'合同价款与付款履行如何核对','terms':['合同','付款','价款'],
                    'evidence':[{'source_id':source['id'],'quote':source['text'].strip()[:700]}]}]}),'','匿名演示模型'
            article=data['article'];fragment=article['fragments'][0];source=data['sources'][0]
            return json.dumps({'article_id':article['id'],'applicability':'direct','types':['support','risk'],
                'topic_ids':[data['topics'][0]['id']],
                'reason':'匿名演示：文章讨论合同价款与实际付款的对应关系，可用于核查本案合同约定和付款凭证，并提醒不能将尚未核实的请求当作已证明事实。此处为测试夹具，不代表真实模型分析。',
                'limits':'须核对实际付款对应关系，文章所引法源未作现行效力核验。',
                'article_evidence':[{'fragment_id':fragment['id'],'quote':fragment['text'][:100]}],
                'case_evidence':[{'source_id':source['id'],'quote':source['text'].strip()[:700]}]}),'','匿名演示模型'
        if 'claims' not in data and 'document_items' not in data:
            rows=[]
            for source in data['sources']:
                dates=re.findall(r'2026年\s*1月\s*1日',source['text'])
                date=dates[0] if dates else ''
                rows.append({'source_id':source['id'],'date_text':date,'actors':'','description':'匿名事件：'+source['text'].strip()[:200],'topic':'付款','quote':source['text'].strip()})
            return json.dumps({'events':rows}), '', '匿名演示模型'
        if 'document_items' in data:
            source=data['sources'][0]
            return json.dumps({'title':Path(data['path']).stem,'summary':'匿名夹具：'+source['text'].strip(),'purpose':'证明文书中对应的合同约定或付款情况','quotes':[{'source_id':source['id'],'quote':source['text'].strip()}]}), '', '匿名演示模型'
        for claim in data['claims']:
            source=next((s for s in data['sources'] if re.sub(r'\s+','',claim['claim']) in re.sub(r'\s+','',s['text'])),None)
            quote = source['text'].strip() if source else ''
            rows.append({'id':claim['id'],'status':'supported' if source else 'not_found','reason':'匿名演示：逐字匹配；不代表真实AI能力。','evidence':[{'source_id':source['id'],'quote':quote}] if source else []})
        return json.dumps({'results':rows}), '', '匿名演示模型'
    frontend=Path(__file__).resolve().parents[1]/'frontend'
    app=FastAPI();app.state.preview_temp=temporary;app.state.preview_root=root
    register_case_file_routes(app,get_db,frontend,parse_file=parse,call_ai=ai)
    workflows=register_case_workflow_routes(app,get_db,frontend,parse_file=parse,call_ai=ai,require_action=lambda request:None)
    register_agent_task_routes(app,get_db,workflows,require_action=lambda request:None,
        models=lambda:{'items':[{'value':'fixture-model','label':'匿名演示模型'}],'default_model':'fixture-model'})
    app.mount('/static',StaticFiles(directory=frontend),name='static')
    @app.post('/api/case-research/cases/{case_id}/articles/{article_id}')
    def link_article(case_id:int,article_id:int):
        with get_db() as conn:
            conn.execute('INSERT OR IGNORE INTO research_project_articles VALUES(?,?)',(case_id,article_id));conn.commit()
        return {'success':True}
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
            body=body.replace('STELLA · 办案工作台','匿名调试预览 · AI响应为测试夹具，未调用真实模型')
            from fastapi.responses import HTMLResponse
            return HTMLResponse(body,headers={'Cache-Control':'no-store'})
        return response
    return app

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8769);parser.add_argument('--runtime',type=Path)
    args=parser.parse_args()
    import uvicorn
    uvicorn.run(create_preview_app(args.runtime),host='127.0.0.1',port=args.port,log_level='warning')
