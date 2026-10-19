"""Bundled server entry: independent runtime, no inherited provider credentials."""
from __future__ import annotations
import argparse
import os
import secrets
import sys
from pathlib import Path


def configure(runtime: Path):
    for name in list(os.environ):
        if name.endswith(('_API_KEY','_API_SECRET','_AUTH_CODE','_ACCESS_TOKEN','_AUTHORIZATION','_WEB_COOKIE')):
            os.environ.pop(name, None)
    runtime = runtime.expanduser().resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    os.environ.update({
        'LEGAL_KB_RUNTIME_DIR':str(runtime), 'LEGAL_KB_DB_PATH':str(runtime/'legal_kb.db'),
        'LEGAL_KB_UPLOAD_DIR':str(runtime/'uploads'), 'LEGAL_KB_ARTICLE_IMAGE_DIR':str(runtime/'article_images'),
        'LEGAL_KB_DATA_DIR':str(runtime/'data'), 'LEGAL_KB_CONFIG_DIR':str(runtime),
        'LEGAL_KB_PRIVATE_MODE':'0','LEGAL_KB_HOST':'127.0.0.1','PORT':'18865',
        'CODEX_HOME':str(runtime/'skills-home'), 'FEISHU_LISTENER_ENABLED':'0',
    })
    for name in ('LEGAL_KB_ACCESS_PASSWORD','LEGAL_KB_SESSION_SECRET','APEX_ANONYMOUS_PILOT'):
        os.environ.pop(name, None)
    os.environ['LEGAL_KB_SESSION_SECRET'] = secrets.token_hex(32)
    return runtime


def backup_for_build(runtime, build):
    """Online SQLite backup before importing backend code that may migrate it."""
    import datetime
    import json
    import re
    import sqlite3
    if not re.fullmatch(r'[1-9][0-9]{0,17}', build):
        raise ValueError('app build must be a positive integer')
    marker = runtime / 'app-build.json'
    previous = json.loads(marker.read_text()) if marker.exists() else {}
    if previous.get('build') == build:
        return marker
    database = runtime / 'legal_kb.db'
    if database.exists() and database.stat().st_size:
        backups = runtime / 'data/history_backups'
        backups.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        target = backups / ('before-app-' + build + '-' + stamp + '.db')
        with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as source:
            with sqlite3.connect(target) as destination:
                source.backup(destination)
                if destination.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Database backup verification failed')
    return marker


EXAMPLE_ARTICLES = (
    ('合同履行检查清单（示例）', ['合同纠纷'], '体验示例：了解文章、摘要、标签与笔记的组织方式。',
     '<h2>示例用途</h2><p>本文为体验版全新编写的虚构示例，不来源于真实案件或原用户知识库。</p>'
     '<h2>整理顺序</h2><p>先核对合同主体、签订日期与履行节点，再整理交付记录、对账资料和沟通记录。</p>'
     '<h2>材料清单</h2><ul><li>合同及补充协议</li><li>履行与交付记录</li><li>往来邮件和确认记录</li></ul>'
     '<p>可选中文本添加笔记，或者在文章问答中体验提问。本文不提供具体法律结论。</p>'),
    ('建设工程资料整理方法（示例）', ['建设工程合同纠纷'], '体验示例：使用目录和标签整理一个虚构项目的材料。',
     '<h2>虚构项目</h2><p>星港示例项目仅用于展示资料分类，不对应任何实际工程。</p>'
     '<h2>建议分组</h2><ul><li>招投标和合同材料</li><li>施工过程记录</li><li>验收与结算资料</li></ul>'
     '<p>每份材料注明形成日期、提供者与待核对事项。可尝试搜索“验收”或“结算”。</p>'
     '<p>以上为软件操作样例，不是实际案件意见。</p>'),
    ('Stella 体验版使用指南（示例）', [], '从文章阅读、案件管理到自行配置 AI，快速体验 Stella。',
     '<h2>开始体验</h2><p>左侧文章列表有三篇示例；效率中心中有两个虚构案件，可打开案件管理查看。</p>'
     '<h2>配置自己的服务</h2><p>打开设置或 AI、MCP、Skills 管理页，填写自己的服务信息。安装包不含分享者的密钥与登录会话。</p>'
     '<h2>本地数据</h2><p>新建的数据只保存在本机的 StellaPublic 独立目录。个人财务与长期记忆初始为空。</p>'
     '<p>请勿将示例材料用于真实提交或对外出具。</p>'),
)


def seed_preview_articles(get_db):
    import datetime
    import hashlib
    import json
    from backend.main import rebuild_article_paragraphs
    marker = 'stella.preview.articles.v1'
    with get_db() as conn:
        if conn.execute('SELECT 1 FROM app_preferences WHERE preference_key=?', (marker,)).fetchone():
            return False
        stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        for title, domains, summary, content in EXAMPLE_ARTICLES:
            digest = hashlib.sha256(('stella-preview:' + title).encode()).hexdigest()
            row = conn.execute('SELECT id FROM articles WHERE source_hash=?', (digest,)).fetchone()
            if not row:
                cursor = conn.execute('''INSERT INTO articles(title,content,summary,domains,source_type,source_hash,created_at,tags)
                    VALUES (?,?,?,?,?,?,?,?)''', (title,content,summary,json.dumps(domains,ensure_ascii=False),
                    'manual',digest,stamp,json.dumps(['体验示例','虚构数据'],ensure_ascii=False)))
                rebuild_article_paragraphs(conn,cursor.lastrowid,content)
        conn.execute('INSERT INTO app_preferences(preference_key,value_json,updated_at) VALUES (?,?,?)',(marker,'true',stamp))
        conn.commit()
    return True


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--runtime',type=Path,default=Path.home()/'Library/Application Support/StellaPublic')
    parser.add_argument('--self-test',action='store_true')
    parser.add_argument('--port',type=int,default=18865)
    parser.add_argument('--app-build',default='1')
    args=parser.parse_args()
    runtime=configure(args.runtime)
    # Hold the lock for the lifetime of the process, including migrations.
    import fcntl
    lock = open(runtime / 'server.lock', 'a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    marker = backup_for_build(runtime, args.app_build)
    os.environ['PORT'] = str(args.port)
    from backend.main import app,get_db
    from backend.anonymous_pilot import seed_anonymous_pilot_data
    with get_db() as conn:
        seeded=seed_anonymous_pilot_data(conn)
        if seeded:
            # A preview never starts importing the recipient's Messages history automatically.
            conn.execute('UPDATE case_manager_message_settings SET enabled=0 WHERE id=1')
            conn.commit()
    seed_preview_articles(get_db)
    import json
    pending = marker.with_suffix('.tmp')
    pending.write_text(json.dumps({'build': args.app_build}))
    pending.replace(marker)
    if args.self_test:
        from backend import ai_config
        from backend.user_memory import snapshot
        from fastapi.testclient import TestClient
        with get_db() as conn:
            assert conn.execute('SELECT count(*) FROM case_manager_cases').fetchone()[0] == 2
            assert conn.execute('SELECT count(*) FROM articles').fetchone()[0] == 3
            for table in ('pc_income_records','pc_deposit_records','user_memories','case_manager_court_online_records'):
                exists=conn.execute('SELECT 1 FROM sqlite_master WHERE type="table" AND name=?',(table,)).fetchone()
                if exists: assert conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0, table
            assert not conn.execute('SELECT enabled FROM case_manager_message_settings WHERE id=1').fetchone()[0]
        for name,value in vars(ai_config).items():
            if name.endswith(('_API_KEY','_AUTH_CODE','_AUTHORIZATION','_WEB_COOKIE')):
                assert not value, name
        assert snapshot(get_db)['items']==[]
        with TestClient(app) as client:
            for path in ('/','/ai-api-manager','/mcp-manager','/skill-manager','/api/ai-providers','/api/mcp-manager/status','/api/user-memory'):
                response=client.get(path)
                if path == '/api/mcp-manager/status' and response.status_code==404: continue
                assert response.status_code==200, (path,response.status_code)
        import ddddocr
        ddddocr.DdddOcr(show_ad=False)
        from playwright.sync_api import sync_playwright
        assert not any('/personal-center' in getattr(route, 'path', '') for route in app.routes)
        print('PREVIEW_SELF_TEST_OK: 2 fictional cases; 3 original demo articles; no personal finances, saved memory or provider credentials')
        return
    import uvicorn
    ready = runtime / ('server-ready-' + str(os.getpid()))
    class PublicServer(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            if self.started:
                ready.touch()
    try:
        PublicServer(uvicorn.Config(app, host='127.0.0.1', port=args.port,
                                   access_log=False, log_level='warning')).run()
    finally:
        ready.unlink(missing_ok=True)


if __name__=='__main__':
    main()
