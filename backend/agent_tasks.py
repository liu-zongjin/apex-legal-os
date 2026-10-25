"""Durable, single-process material-task coordination over the existing workflows."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from contextlib import contextmanager

from fastapi import HTTPException, Request

from .agent_policy import task_policy
from .case_files import _run_in_thread, _resolve_inside
from .case_workflows import MAX_FILES, stamp, plain

VERSION = 1
ACTIVE = {'queued', 'running'}
RESUMABLE = {'failed', 'paused', 'cancelled', 'interrupted'}
STEPS = [('inventory', '材料清点与解析'), ('timeline', '事实时间线'), ('analysis', '事项、争点与缺口'), ('delivery', '来源检查与草稿交付')]


def add_schema(conn):
    statements = [
        '''CREATE TABLE IF NOT EXISTS agent_tasks (
            id TEXT PRIMARY KEY, case_id INTEGER NOT NULL, project_id INTEGER,
            request_key TEXT NOT NULL, request_json TEXT NOT NULL, request_hash TEXT NOT NULL,
            input_json TEXT NOT NULL, child_id TEXT NOT NULL UNIQUE,
            version INTEGER NOT NULL DEFAULT 1, generation INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL, delivery_status TEXT NOT NULL DEFAULT 'none',
            review_status TEXT NOT NULL DEFAULT 'unreviewed', calls_used INTEGER NOT NULL DEFAULT 0,
            message TEXT NOT NULL, error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(case_id,request_key))''',
        '''CREATE INDEX IF NOT EXISTS idx_agent_tasks_case ON agent_tasks(case_id,created_at DESC)''',
        '''CREATE TABLE IF NOT EXISTS agent_steps (
            task_id TEXT NOT NULL REFERENCES agent_tasks(id) ON DELETE CASCADE,
            name TEXT NOT NULL, position INTEGER NOT NULL, status TEXT NOT NULL,
            PRIMARY KEY(task_id,name))''',
        '''CREATE TABLE IF NOT EXISTS agent_commands (
            task_id TEXT PRIMARY KEY REFERENCES agent_tasks(id) ON DELETE CASCADE,
            child_id TEXT NOT NULL UNIQUE, status TEXT NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS agent_events (
            task_id TEXT NOT NULL REFERENCES agent_tasks(id) ON DELETE CASCADE,
            sequence INTEGER NOT NULL, status TEXT NOT NULL, message TEXT NOT NULL, at TEXT NOT NULL,
            PRIMARY KEY(task_id,sequence))''',
    ]
    for statement in statements:
        conn.execute(statement)


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def fingerprint(value):
    return hashlib.sha256(packed(value).encode()).hexdigest()


class MaterialTaskService:
    def __init__(self, get_db, workflows, models):
        self.get_db, self.workflows, self.models = get_db, workflows, models
        self.running = {}
        self.slots = None
        self.stopping = False

    @contextmanager
    def db(self):
        resource = self.get_db()
        try:
            with resource as conn:
                yield conn
        finally:
            if hasattr(resource, 'close'):
                resource.close()

    def scope(self, conn, case_id, project_id=None):
        if not conn.execute('SELECT 1 FROM case_manager_cases WHERE id=?', (case_id,)).fetchone():
            raise HTTPException(404, '案件不存在')
        if project_id:
            row = conn.execute('SELECT case_id FROM research_projects WHERE id=?', (project_id,)).fetchone()
            if row is None or row['case_id'] != case_id:
                raise HTTPException(409, '研究项目未关联本案；未扩大材料范围')

    def row(self, conn, case_id, task_id):
        row = conn.execute('SELECT * FROM agent_tasks WHERE case_id=? AND id=?', (case_id, task_id)).fetchone()
        if row is None:
            raise HTTPException(404, '材料分析任务不存在或不属于本案')
        self.scope(conn, case_id, row['project_id'])
        return dict(row)

    def event(self, conn, task_id, status, message):
        seq = conn.execute('SELECT COALESCE(MAX(sequence),0)+1 FROM agent_events WHERE task_id=?', (task_id,)).fetchone()[0]
        conn.execute('INSERT INTO agent_events VALUES(?,?,?,?,?)', (task_id, seq, status, message, stamp()))

    def create(self, case_id, body):
        if not isinstance(body, dict) or set(body) - {'request_key', 'paths', 'goal', 'model', 'max_calls', 'allow_cloud_ocr', 'draft', 'project_id'}:
            raise HTTPException(422, '任务参数无效')
        key = body.get('request_key')
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}', key):
            raise HTTPException(422, '缺少有效请求标识，请重新交办')
        model = plain(body.get('model', ''), 150)
        model_info = next((item for item in self.models()['items'] if item['value'] == model), None)
        if model_info is None:
            raise HTTPException(422, '请选择已配置且可用于任务的模型')
        calls = body.get('max_calls', 40)
        if type(calls) is not int or not 1 <= calls <= 120:
            raise HTTPException(422, '请求上限须为1至120次')
        draft = plain(body.get('draft', ''), 40000)
        paths = body.get('paths')
        if not isinstance(paths, list) or not (0 if draft else 1) <= len(paths) <= MAX_FILES or not all(isinstance(p, str) for p in paths):
            raise HTTPException(422, '请选择1至40份材料')
        if type(body.get('allow_cloud_ocr', False)) is not bool:
            raise HTTPException(422, 'OCR授权参数无效')
        project_id = body.get('project_id') or None
        if project_id is not None and (type(project_id) is not int or project_id <= 0):
            raise HTTPException(422, '研究项目标识无效')
        config = {'kind': 'material_analysis', 'paths': sorted(paths),
                  'goal': plain(body.get('goal', ''), 2000) or '梳理材料陈述、时间线、待研究争点、矛盾候选与补证建议。',
                  'draft': draft, 'model': model,
                  'model_revision': model_info.get('revision'),
                  'allow_cloud_ocr': body.get('allow_cloud_ocr', False)}
        request = {**config, 'project_id': project_id, 'max_calls': calls}
        request_hash = fingerprint(request)
        # Internal execution semantics are pinned for new tasks, but are not a
        # user parameter: old idempotency keys must still return the old task.
        request['material_input_version'] = 1
        # Check idempotency before reading current files: a retry returns the original task,
        # even if files have since changed. A different request cannot reuse the key.
        with self.db() as conn:
            self.scope(conn, case_id, project_id)
            existing = conn.execute('SELECT id,request_hash FROM agent_tasks WHERE case_id=? AND request_key=?', (case_id, key)).fetchone()
            if existing:
                if existing['request_hash'] != request_hash:
                    raise HTTPException(409, '请求标识已用于另一组参数，请重新交办')
                return existing['id']
        root = self.workflows.root(case_id, writable=True)
        sources = []
        for path in config['paths']:
            resolved, source = self.workflows.source(root, path)
            info = resolved.stat()
            sources.append({**source, 'size': info.st_size, 'mtime_ns': info.st_mtime_ns})
        if len({row['path'] for row in sources}) != len(paths):
            raise HTTPException(422, '材料不能重复')
        task_id, child_id = uuid.uuid4().hex, uuid.uuid4().hex
        with self.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            existing = conn.execute('SELECT id,request_hash FROM agent_tasks WHERE case_id=? AND request_key=?', (case_id, key)).fetchone()
            if existing:
                if existing['request_hash'] != request_hash:
                    raise HTTPException(409, '请求标识已用于另一组参数')
                return existing['id']
            conn.execute('''INSERT INTO agent_tasks
                (id,case_id,project_id,request_key,request_json,request_hash,input_json,child_id,status,message,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                (task_id, case_id, project_id, key, packed(request), request_hash,
                 packed(sources), child_id, 'queued', '等待分析材料', stamp(), stamp()))
            conn.executemany('INSERT INTO agent_steps VALUES(?,?,?,?)',
                             [(task_id, name, index, 'pending') for index, (name, _) in enumerate(STEPS)])
            conn.execute('INSERT INTO agent_commands VALUES(?,?,?)', (task_id, child_id, 'prepared'))
            self.event(conn, task_id, 'queued', '已固定材料范围、所选模型和请求上限')
            conn.commit()
        return task_id

    def get(self, case_id, task_id):
        with self.db() as conn:
            row = self.row(conn, case_id, task_id)
            steps = [dict(r) for r in conn.execute('SELECT * FROM agent_steps WHERE task_id=? ORDER BY position', (task_id,))]
        config = json.loads(row.pop('request_json'))
        row['sources'] = json.loads(row.pop('input_json'))
        row.pop('request_hash')
        row['config'] = config
        row['steps'] = [{**step, 'label': dict(STEPS)[step['name']]} for step in steps]
        row['child'] = None
        row['source_warning'] = ''
        try:
            root = self.workflows.root(case_id)
            for source in row['sources']:
                path = _resolve_inside(root, source['path'], allow_root=False)
                info = path.stat()
                if info.st_size != source['size'] or info.st_mtime_ns != source['mtime_ns']:
                    row['source_warning'] = '材料可能已变化；继续办理与下载成果时将核对完整版本'
        except (HTTPException, OSError):
            row['source_warning'] = '材料或案件文件夹当前不可用，请检查后继续'
        try:
            _, child = self.workflows.load(case_id, row['child_id'])
            if child.get('owner_task') != task_id:
                raise HTTPException(409, '子任务关联异常')
            row['child'] = child
            if row['status'] in ACTIVE:
                row['message'] = child['message']
            if child.get('coverage'):
                row['steps'][0]['status'] = 'completed'
            if child.get('timeline_coverage'):
                row['steps'][1]['status'] = 'completed'
            if child.get('analysis_complete'):
                row['steps'][2]['status'] = 'completed'
        except HTTPException as exc:
            if exc.status_code != 404:
                row['source_warning'] = str(exc.detail)
        return row

    def launch(self, case_id, task_id):
        if task_id in self.running:
            return
        if self.stopping:
            raise HTTPException(503, '服务正在退出，请稍后继续任务')
        task = asyncio.create_task(self.run(case_id, task_id))
        self.running[task_id] = task
        def finished(done):
            if self.running.get(task_id) is done:
                self.running.pop(task_id, None)
            if not done.cancelled():
                done.exception()
        task.add_done_callback(finished)

    def consume(self, case_id, task_id, generation):
        with self.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = self.row(conn, case_id, task_id)
            config = json.loads(row['request_json'])
            if row['generation'] != generation or row['status'] != 'running':
                raise HTTPException(409, '任务已停止或版本已变化')
            current = next((item for item in self.models()['items'] if item['value'] == config['model']), None)
            if current is None or current.get('revision') != config.get('model_revision'):
                raise HTTPException(409, '模型服务配置已变化；未发送材料，请建立后继任务重新确认')
            if row['calls_used'] >= config['max_calls']:
                raise HTTPException(429, '任务请求上限已达到；进度已保存，可新建后继任务调整上限')
            conn.execute('UPDATE agent_tasks SET calls_used=calls_used+1,updated_at=? WHERE id=?', (stamp(), task_id))
            conn.commit()

    def finish(self, case_id, task_id, generation, status, message, error='', child=None):
        with self.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            # Persist failure even if the case/project was unlinked during execution.
            row = conn.execute('SELECT * FROM agent_tasks WHERE case_id=? AND id=?', (case_id, task_id)).fetchone()
            if row is None:
                return
            if row['generation'] != generation or row['status'] not in ACTIVE:
                return
            delivery = 'complete' if status == 'succeeded' else ('partial' if child and child.get('coverage') else 'none')
            conn.execute('UPDATE agent_tasks SET status=?,delivery_status=?,message=?,error=?,updated_at=? WHERE id=?',
                         (status, delivery, message, error, stamp(), task_id))
            conn.execute('UPDATE agent_commands SET status=? WHERE task_id=?', (status, task_id))
            if status == 'succeeded':
                conn.execute("UPDATE agent_steps SET status='completed' WHERE task_id=?", (task_id,))
            self.event(conn, task_id, status, message)
            conn.commit()

    async def run(self, case_id, task_id):
        generation, child = None, None
        try:
            if self.slots is None:
                self.slots = asyncio.Semaphore(1)
            async with self.slots:
                with self.db() as conn:
                    conn.execute('BEGIN IMMEDIATE')
                    row = self.row(conn, case_id, task_id)
                    if row['status'] != 'queued':
                        return
                    if row['version'] != VERSION:
                        raise HTTPException(409, '任务执行版本不兼容，请建立后继任务')
                    generation = row['generation']
                    conn.execute("UPDATE agent_tasks SET status='running',message='核对材料版本',updated_at=? WHERE id=?", (stamp(), task_id))
                    conn.execute("UPDATE agent_steps SET status='running' WHERE task_id=? AND name='inventory'", (task_id,))
                    self.event(conn, task_id, 'running', '核对材料并继续有效检查点')
                    conn.commit()
                config = json.loads(row['request_json'])
                child_body = {k: v for k, v in config.items() if k not in {'project_id', 'max_calls', 'model_revision'}}
                sources = json.loads(row['input_json'])
                with task_policy(config['model'], lambda: self.consume(case_id, task_id, generation)):
                    root, child = await _run_in_thread(self.workflows.create_owned, case_id, child_body, task_id,
                                                     row['child_id'], [(s['path'], s['sha256']) for s in sources])
                    for source in sources:
                        await _run_in_thread(self.workflows.source, root, source['path'], source['sha256'])
                    if child['status'] != 'completed':
                        self.workflows.launch(root, child, owner_task=task_id)
                        await self.workflows.jobs[child['id']]
                    _, child = self.workflows.load(case_id, row['child_id'])
                    if child['status'] == 'cancelled':
                        self.finish(case_id, task_id, generation, 'interrupted', '办理中断，已保存进度，请核对后继续', child=child)
                        return
                    if child['status'] != 'completed':
                        raise HTTPException(422, child.get('error') or '材料分析中断，已保留进度')
                self.finish(case_id, task_id, generation, 'succeeded', '分析草稿已交付，时间线与分析事项待复核', child=child)
        except asyncio.CancelledError:
            if generation is not None:
                self.finish(case_id, task_id, generation, 'interrupted', '服务中断，进度已保存，可继续办理', child=child)
            raise
        except Exception as exc:
            message = str(exc.detail)[:400] if isinstance(exc, HTTPException) else '任务未完成，请检查材料、模型配置或转换组件后继续'
            if generation is None:
                with self.db() as conn:
                    row = conn.execute('SELECT generation FROM agent_tasks WHERE id=? AND case_id=?', (task_id, case_id)).fetchone()
                    generation = row['generation'] if row else None
            if generation is not None:
                self.finish(case_id, task_id, generation, 'failed', message, error=message, child=child)

    async def control(self, case_id, task_id, action, generation):
        with self.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = self.row(conn, case_id, task_id)
            if type(generation) is not int or row['generation'] != generation:
                raise HTTPException(409, '任务状态已变化，请刷新后操作')
            if row['version'] != VERSION:
                raise HTTPException(409, '任务版本不兼容，请建立后继任务')
            if action == 'resume':
                if row['status'] not in RESUMABLE or task_id in self.running:
                    raise HTTPException(409, '任务正在办理或无需继续')
                root = self.workflows.root(case_id)
                for source in json.loads(row['input_json']):
                    self.workflows.source(root, source['path'], source['sha256'])
                config = json.loads(row['request_json'])
                current = next((item for item in self.models()['items'] if item['value'] == config['model']), None)
                if current is None or current.get('revision') != config.get('model_revision'):
                    raise HTTPException(409, '原模型已不可用，请建立后继任务选择模型')
                if row['calls_used'] >= config['max_calls']:
                    try:
                        _, child = self.workflows.load(case_id, row['child_id'])
                    except HTTPException:
                        child = {}
                    if not child.get('analysis_complete'):
                        raise HTTPException(409, '原请求上限已用尽，请建立后继任务调整上限')
                status, message = 'queued', '等待继续分析'
            elif action in {'pause', 'cancel'}:
                if row['status'] not in ACTIVE:
                    raise HTTPException(409, '当前任务未在办理')
                status, message = ('paused', '任务已暂停，可继续') if action == 'pause' else ('cancelled', '任务已停止，已受理请求可能仍产生费用')
            else:
                raise HTTPException(404, '任务操作不存在')
            conn.execute('UPDATE agent_tasks SET status=?,generation=generation+1,message=?,updated_at=? WHERE id=?',
                         (status, message, stamp(), task_id))
            self.event(conn, task_id, status, message)
            conn.commit()
        if action == 'resume':
            self.launch(case_id, task_id)
        else:
            task = self.running.get(task_id)
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        return self.get(case_id, task_id)

    def recover(self):
        with self.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            rows = conn.execute("SELECT id FROM agent_tasks WHERE status IN ('queued','running')").fetchall()
            for row in rows:
                conn.execute("UPDATE agent_tasks SET status='interrupted',generation=generation+1,message=?,updated_at=? WHERE id=?",
                             ('服务已重启，请核对后继续任务', stamp(), row['id']))
                self.event(conn, row['id'], 'interrupted', '服务已重启，未自动再次发起付费请求')
            conn.commit()


def register_agent_task_routes(app, get_db, workflows, *, require_action, models):
    service = MaterialTaskService(get_db, workflows, models)
    app.state.agent_tasks = service

    @app.get('/api/agent-tasks/models')
    def model_options():
        return models()

    @app.get('/api/agent-tasks/cases/{case_id}/projects')
    def projects(case_id: int):
        with service.db() as conn:
            service.scope(conn, case_id)
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name='research_projects'").fetchone()
            return {'items': [dict(r) for r in conn.execute('SELECT id,name FROM research_projects WHERE case_id=? ORDER BY id DESC LIMIT 100', (case_id,))] if exists else []}

    @app.get('/api/agent-tasks/cases/{case_id}/tasks')
    def tasks(case_id: int, offset: int = 0):
        if not 0 <= offset <= 100000:
            raise HTTPException(422, '任务列表页码无效')
        with service.db() as conn:
            service.scope(conn, case_id)
            rows = conn.execute('''SELECT id,project_id,status,delivery_status,review_status,
                message,error,calls_used,created_at,updated_at,request_json FROM agent_tasks
                WHERE case_id=? ORDER BY created_at DESC,id DESC LIMIT 61 OFFSET ?''', (case_id, offset)).fetchall()
        items = []
        for row in rows[:60]:
            item = dict(row)
            item['goal'] = json.loads(item.pop('request_json')).get('goal', '')[:200]
            items.append(item)
        return {'items': items, 'has_more': len(rows) > 60,
                'next_offset': offset + 60 if len(rows) > 60 else None}

    @app.post('/api/agent-tasks/cases/{case_id}/tasks')
    async def create(case_id: int, request: Request):
        require_action(request)
        task_id = await _run_in_thread(service.create, case_id, await request.json())
        result = service.get(case_id, task_id)
        if result['status'] == 'queued':
            service.launch(case_id, task_id)
        return result

    @app.get('/api/agent-tasks/cases/{case_id}/tasks/{task_id}')
    def detail(case_id: int, task_id: str):
        return service.get(case_id, task_id)

    @app.get('/api/agent-tasks/cases/{case_id}/tasks/{task_id}/events')
    def events(case_id: int, task_id: str, after: int = 0):
        if after < 0:
            raise HTTPException(422, '事件游标无效')
        with service.db() as conn:
            service.row(conn, case_id, task_id)
            rows = [dict(r) for r in conn.execute('SELECT * FROM agent_events WHERE task_id=? AND sequence>? ORDER BY sequence LIMIT 100', (task_id, after))]
        return {'items': rows, 'cursor': rows[-1]['sequence'] if rows else after}

    @app.post('/api/agent-tasks/cases/{case_id}/tasks/{task_id}/{action}')
    async def control(case_id: int, task_id: str, action: str, request: Request):
        require_action(request)
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {'generation'}:
            raise HTTPException(422, '请提交当前任务版本')
        return await service.control(case_id, task_id, action, body['generation'])

    @app.on_event('startup')
    async def recover():
        service.recover()

    @app.on_event('shutdown')
    async def shutdown():
        service.stopping = True
        running = list(service.running.values())
        for task in running:
            task.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)

    return service
