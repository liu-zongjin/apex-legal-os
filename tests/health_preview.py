"""Anonymous, disposable full-app runtime for browser/debug verification."""
import asyncio
import datetime
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    with tempfile.TemporaryDirectory(prefix='stella-anonymous-health-') as directory:
        for key in ('LEGAL_KB_RUNTIME_DIR','LEGAL_KB_DATA_DIR'):
            os.environ[key]=directory
        os.environ['LEGAL_KB_DB_PATH']=str(Path(directory)/'anonymous.db')
        for key in ('RADAR_SCHEDULER_DISABLED','COURT_ONLINE_SCHEDULER_DISABLED',
                    'JUDICIAL_MESSAGES_SCHEDULER_DISABLED','INVOICE_AUTOMATION_SCHEDULER_DISABLED',
                    'DOMAIN_CLASSIFICATION_DISABLED','CASE_BINDING_VERIFICATION_DISABLED'):
            os.environ[key]='1'
        os.environ['LEGAL_KB_PRIVATE_MODE']='0'
        os.environ['OPENCODE_API_KEY']='anonymous-fixture'
        os.environ['OPENCODE_API_URL']='https://anonymous.invalid/chat/completions'
        for key in ('LEGAL_KB_ACCESS_USER','LEGAL_KB_ACCESS_PASSWORD'):
            os.environ.pop(key,None)
        from backend import main as app_main
        from backend.health_maintenance import preserve_orphans
        stamp=datetime.datetime.now().isoformat()
        for index in range(1,13):
            app_main.save_article(title=f'匿名知识 {index}',content=f'<p>建设工程合同履行与保证责任。匿名演示正文 {index}。</p>',summary='匿名知识摘要',domains=['建设工程'],source_type='manual',tags=[],check_duplicate=False)
        with app_main.get_db() as conn:
            for index in range(1,164):
                kind='series' if index==1 else 'series_child' if index>151 else 'ordinary'
                conn.execute('''INSERT INTO case_manager_cases(id,title,case_type,case_kind,parent_series_id,source_status,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?)''',(index,f'匿名案件 {index}','建设工程',kind,1 if index>151 else None,'archived' if 60<=index<=151 else 'active',stamp,stamp))
            conn.execute("INSERT INTO case_manager_series_profiles(series_case_id,created_at,updated_at) VALUES(1,?,?)",(stamp,stamp))
            conn.execute('INSERT INTO notes(article_id,content,created_at) VALUES(?,?,?)',(1,'匿名文章笔记',stamp))
            conn.commit()
            conn.execute('PRAGMA foreign_keys=OFF')
            conn.execute('INSERT INTO notes(article_id,content,created_at) VALUES(?,?,?)',(9999,'需要恢复的匿名笔记',stamp))
            conn.commit();conn.execute('PRAGMA foreign_keys=ON')
            preserve_orphans(conn)
        # No real account, key, browser session or user files enter this process.
        app_main.OPENCODE_API_KEY='anonymous-fixture'
        app_main.ai_config_module.OPENCODE_API_KEY='anonymous-fixture'
        app_main.OPENCODE_API_URL='https://anonymous.invalid/chat/completions'
        app_main.ai_config_module.OPENCODE_API_URL=app_main.OPENCODE_API_URL
        import httpx
        from backend import ai_transport
        class FixtureStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                for text in ('这是一段','匿名流式','回答。'):
                    await asyncio.sleep(.08)
                    yield ('data: '+json.dumps({'choices':[{'index':0,'delta':{'content':text}}]},ensure_ascii=False)+'\n\n').encode()
                yield b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
        async def provider(request):
            body=json.loads(request.content)
            if body.get('stream'):
                return httpx.Response(200,stream=FixtureStream(),headers={'content-type':'text/event-stream'})
            return httpx.Response(200,json={'choices':[{'message':{'content':'匿名模型回答。'},'finish_reason':'stop'}]})
        ai_transport.httpx.AsyncHTTPTransport=lambda **kw:httpx.MockTransport(provider)
        import uvicorn
        uvicorn.run(app_main.app,host='127.0.0.1',port=int(os.environ.get('HEALTH_PREVIEW_PORT','18016')),access_log=False)


if __name__=='__main__':main()
