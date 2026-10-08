"""Account-scoped online reading and durable, streaming court download jobs."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import re
import subprocess
import threading
import time
import uuid
import zipfile
from functools import partial
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from fastapi.responses import FileResponse, HTMLResponse

PREFIX = '/api/case-manager/court-online'
REMOTE = '/yzw-zxfw-sxfw/api/v3/wsyj'
TERMINAL = {'completed', 'partial', 'failed', 'cancelled'}


def add_schema(conn):
    # Called only by the numbered migration, not by route registration.
    conn.execute('''CREATE TABLE IF NOT EXISTS court_readings (
      id INTEGER PRIMARY KEY, account_id TEXT NOT NULL, remote_id TEXT NOT NULL,
      case_number TEXT NOT NULL, court_name TEXT NOT NULL, status TEXT NOT NULL,
      valid_from TEXT, valid_until TEXT, case_remote_id TEXT, case_type TEXT,
      online INTEGER NOT NULL DEFAULT 0, linked_case_id INTEGER,
      updated_at TEXT NOT NULL, UNIQUE(account_id, remote_id))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS court_download_jobs (
      id TEXT PRIMARY KEY, account_id TEXT NOT NULL, reading_id INTEGER NOT NULL,
      title TEXT NOT NULL, source TEXT NOT NULL, state TEXT NOT NULL,
      directory TEXT NOT NULL, zip_path TEXT, error TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS court_download_files (
      id INTEGER PRIMARY KEY, job_id TEXT NOT NULL, remote_id TEXT NOT NULL,
      name TEXT NOT NULL, relative_path TEXT NOT NULL, size_bytes INTEGER,
      downloaded_bytes INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'queued',
      validator TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
      UNIQUE(job_id, relative_path))''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_court_jobs_account ON court_download_jobs(account_id, created_at)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_court_files_job ON court_download_files(job_id)')


def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def safe_name(value):
    value = re.sub(r'[\x00-\x1f/\\:*?"<>|]', '_', str(value or '')).strip(' .')
    return value[:160] or '未命名'


def is_open(row):
    if row['status'] != '11800006-3' or not row['online']:
        return False
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    try:
        start = dt.datetime.fromisoformat(str(row['valid_from'])).replace(tzinfo=now.tzinfo)
        end = dt.datetime.fromisoformat(str(row['valid_until'])).replace(tzinfo=now.tzinfo)
        return start <= now <= end
    except (ValueError, TypeError):
        return False


def flatten_directory(tree):
    """Normalize the official directory tree; never use application attachments."""
    result = []
    def visit(node, parents):
        if isinstance(node, list):
            for child in node: visit(child, parents)
            return
        if not isinstance(node, dict): return
        children = node.get('children')
        name = safe_name(node.get('name') or node.get('wjmc'))
        if children:
            visit(children, parents + [name])
            return
        url = node.get('url') or node.get('downloadUrl')
        denied = any(node.get(k) in (False, 0, '0', 'false') for k in ('canDownload', 'downloadable', 'allowDownload') if k in node)
        if not url or denied: return
        identity = str(node.get('id') or node.get('clbh') or node.get('path') or '/'.join(parents + [name]))
        result.append({'remote_id': identity, 'name': name, 'relative_path': '/'.join(parents + [name]),
                       'size_bytes': positive_size(node.get('size') or node.get('sizeBytes') or node.get('wjdx')), 'url': str(url)})
    visit(tree, [])
    return result


def positive_size(value):
    try: return int(value) if int(value) >= 0 else None
    except (TypeError, ValueError): return None


def unique_paths(files):
    seen = set()
    for index, file in enumerate(files, 1):
        parts = [safe_name(x) for x in file['relative_path'].split('/') if x]
        path = Path(*parts)
        candidate = str(path)
        if candidate.casefold() in seen:
            candidate = str(path.with_name(f'{path.stem}-{index:04d}{path.suffix}'))
        while candidate.casefold() in seen:
            path = Path(candidate)
            candidate = str(path.with_name(f'{path.stem}-{index:04d}{path.suffix}'))
        seen.add(candidate.casefold())
        file['relative_path'] = candidate
    return files


def build_zip(directory, files, title, source, stop):
    directory = Path(directory)
    target = directory / (safe_name(title) + '.zip')
    temporary = target.with_suffix('.zip.part')
    manifest = [{'文件名称': f['name'], '目录': f['relative_path'], '大小': f['size_bytes'],
                 '状态': f['state'], '原因': f['error']} for f in files]
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            for file in files:
                if stop.is_set(): raise InterruptedError()
                if file['state'] != 'completed': continue
                with (directory / '原始文件' / file['relative_path']).open('rb') as src:
                    with archive.open('原始文件/' + file['relative_path'], 'w', force_zip64=True) as dst:
                        while chunk := src.read(1024 * 1024):
                            if stop.is_set(): raise InterruptedError()
                            dst.write(chunk)
            archive.writestr('文件清单.json', json.dumps({'来源': '申请材料打包测试' if source == 'application-test' else '法院开放卷宗', '文件': manifest}, ensure_ascii=False, indent=2))
        if stop.is_set(): raise InterruptedError()
        temporary.replace(target)
        return str(target)
    finally:
        temporary.unlink(missing_ok=True)


def register_dossier_routes(app, get_db, *, account_id, session_headers, download_directory, validate_url, court_origin, frontend_dir):
    tasks = {}
    stops = {}
    rates = {}
    speed_samples = {}
    job_lock = [None]
    refresh_lock = [None]
    refreshed = {}

    def query(sql, args=()):
        with get_db() as conn: return [dict(x) for x in conn.execute(sql, args).fetchall()]

    def write(sql, args=()):
        with get_db() as conn:
            conn.execute(sql, args)
            conn.commit()

    def reading(identity):
        rows = query('SELECT * FROM court_readings WHERE id=? AND account_id=?', (identity, account_id()))
        if not rows: raise HTTPException(404, '阅卷记录不存在')
        return rows[0]

    def job(identity):
        rows = query('SELECT * FROM court_download_jobs WHERE id=? AND account_id=?', (identity, account_id()))
        if not rows: raise HTTPException(404, '下载任务不存在')
        return rows[0]

    async def remote(path, params=None):
        async with httpx.AsyncClient(timeout=40, follow_redirects=False) as client:
            response = await client.get(court_origin + '/yzw' + path, params=params, headers=await session_headers())
        if response.status_code in (401, 403): raise HTTPException(response.status_code, '官网登录失效或无访问权限，请登录官网后继续')
        response.raise_for_status()
        body = response.json()
        if str(body.get('code')) != '200':
            raise HTTPException(502, str(body.get('message') or '法院服务返回异常'))
        return body.get('data')

    async def refresh_readings():
        owner = account_id()
        found = set()
        page = 1
        while True:
            data = await remote(REMOTE, {'fydm': '', 'ah': '', 'search': '', 'page': page, 'limit': 50, 'zt': '', 'ajbh': ''}) or {}
            rows = data.get('records') or []
            if account_id() != owner: raise HTTPException(409, '账号已切换，请刷新')
            fresh = [r for r in rows if str(r.get('id')) not in found]
            if rows and not fresh: raise HTTPException(502, '官网分页重复，未能完整同步')
            for r in fresh:
                found.add(str(r['id']))
                write('''INSERT INTO court_readings(account_id,remote_id,case_number,court_name,status,valid_from,valid_until,case_remote_id,case_type,online,updated_at)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(account_id,remote_id) DO UPDATE SET
                  case_number=excluded.case_number,court_name=excluded.court_name,status=excluded.status,
                  valid_from=excluded.valid_from,valid_until=excluded.valid_until,case_remote_id=excluded.case_remote_id,
                  case_type=excluded.case_type,online=excluded.online,updated_at=excluded.updated_at''',
                  (owner, str(r['id']), r.get('ah') or '', r.get('fyMc') or '', r.get('zt') or '', r.get('yjyxqKssj'), r.get('yjyxqJssj'), r.get('ajbs'), r.get('ajlx'), int(str(r.get('yjfs')) == '1'), stamp()))
            if not rows or len(found) >= int(data.get('total') or len(found)): break
            page += 1
            if page > 200: raise HTTPException(502, '官网阅卷记录过多，请缩小同步范围')
        return len(found)

    async def source_files(row, source):
        if source == 'application-test':
            data = await remote(REMOTE + '/wsyjxq/' + row['remote_id']) or {}
            return unique_paths([{'remote_id': str(f.get('id') or f.get('clbh')), 'name': safe_name(f.get('name') or f.get('wjmc')),
                   'relative_path': '申请材料/' + safe_name(f.get('name') or f.get('wjmc')), 'size_bytes': None,
                   'url': f['url']} for f in data.get('wsyjCls', []) if f.get('url')])
        # Verify current permissions, not just the cached approved state.
        data = await remote(REMOTE + '/wsyjxq/' + row['remote_id']) or {}
        current = {**row, 'status': data.get('zt'), 'online': int(str(data.get('yjfs')) == '1'),
                   'valid_from': data.get('yjyxqKssj'), 'valid_until': data.get('yjyxqJssj')}
        if not is_open(current): raise HTTPException(403, '卷宗尚未开放或阅卷有效期已结束')
        directory = await remote(REMOTE + '/aj/jzml', {'ajbh': row['case_remote_id'], 'id': row['remote_id'], 'ajcx': row['case_type']})
        return unique_paths(flatten_directory(directory))

    def snapshot(identity, owner=None):
        if owner is None:
            item = job(identity)
        else:
            rows = query('SELECT * FROM court_download_jobs WHERE id=? AND account_id=?', (identity, owner))
            if not rows: raise HTTPException(404, '下载任务不存在')
            item = rows[0]
        files = query('SELECT * FROM court_download_files WHERE job_id=? ORDER BY id', (identity,))
        total = sum(f['size_bytes'] or 0 for f in files) if all(f['size_bytes'] is not None for f in files) else None
        transferred = sum(f['downloaded_bytes'] for f in files)
        complete = sum(f['state'] == 'completed' for f in files)
        failed = sum(f['state'] == 'failed' for f in files)
        speed = 0
        if item['state'] == 'downloading' and identity in rates:
            now = time.monotonic()
            samples = speed_samples.setdefault(identity, [(rates[identity][0], rates[identity][1])])
            samples.append((now, transferred))
            while len(samples) > 2 and samples[1][0] < now - 5: samples.pop(0)
            elapsed = now - samples[0][0]
            speed = max(0, transferred - samples[0][1]) / max(.1, elapsed)
        item.update(files=files, file_count=len(files), completed_count=complete, failed_count=failed,
                    total_bytes=total, downloaded_bytes=transferred, speed_bytes=speed,
                    download_percent=min(100, 100 * transferred / total) if total else None,
                    file_percent=100 * complete / len(files) if files else 0,
                    eta_seconds=max(0, (total - transferred) / speed) if total is not None and speed > 0 else None,
                    zip_size_bytes=Path(item['zip_path']).stat().st_size if item['zip_path'] and Path(item['zip_path']).is_file() else None)
        return item

    def update_file(identity, **values):
        write('UPDATE court_download_files SET ' + ','.join(k + '=?' for k in values) + ' WHERE id=?', (*values.values(), identity))

    async def transfer(item, file, resolve, stop):
        destination = Path(item['directory']) / '原始文件' / file['relative_path']
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(destination.name + '.part')
        last_account_check = [float('-inf')]
        def check():
            if stop.is_set(): raise asyncio.CancelledError()
            if time.monotonic() - last_account_check[0] >= 1:
                last_account_check[0] = time.monotonic()
                if account_id() != item['account_id']: raise HTTPException(409, '账号已切换，任务已暂停')
        update_file(file['id'], state='downloading', error='')
        for attempt in range(2):
            check()
            available = await resolve(force=attempt > 0)
            descriptor = available.get(file['remote_id'])
            if not descriptor: raise HTTPException(403, '文件已不在开放下载清单中')
            url = validate_url(descriptor['url'])
            offset = partial.stat().st_size if partial.exists() and file['validator'] else 0
            headers = await session_headers() if urlsplit(url).hostname == urlsplit(court_origin).hostname else {}
            if offset: headers.update({'Range': f'bytes={offset}-', 'If-Range': file['validator']})
            headers['Accept-Encoding'] = 'identity'
            async with httpx.AsyncClient(timeout=httpx.Timeout(60, read=120), follow_redirects=False) as client:
                async with client.stream('GET', url, headers=headers) as response:
                    if response.status_code in (401, 403) and attempt == 0: continue
                    if response.status_code in (401, 403): raise HTTPException(response.status_code, '下载权限或登录会话已失效，请刷新后继续')
                    if response.status_code == 416 and attempt == 0:
                        partial.unlink(missing_ok=True); file['validator'] = ''; continue
                    response.raise_for_status()
                    content_type = response.headers.get('content-type', '').lower()
                    if any(t in content_type for t in ('text/html', 'application/json', 'text/plain')):
                        raise ValueError('官网返回错误页面，未保存为文件')
                    validator = response.headers.get('etag') or response.headers.get('last-modified') or ''
                    if response.status_code == 206:
                        match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('content-range', ''))
                        if not offset or not match or int(match[1]) != offset or (validator and validator != file['validator']):
                            raise ValueError('断点续传响应不匹配，请重新下载')
                        total = int(match[3])
                    else:
                        offset = 0
                        total = positive_size(response.headers.get('content-length'))
                    count = offset
                    updated = time.monotonic()
                    update_file(file['id'], downloaded_bytes=count, size_bytes=total, validator=validator)
                    with partial.open('ab' if offset else 'wb') as output:
                        async for chunk in response.aiter_bytes(256 * 1024):
                            check()
                            output.write(chunk)
                            count += len(chunk)
                            if time.monotonic() - updated > .25:
                                update_file(file['id'], downloaded_bytes=count)
                                updated = time.monotonic()
                    check()
                    if total is not None and count != total: raise ValueError('文件大小不符，下载未完整结束')
                    if destination.suffix.lower() == '.pdf':
                        with partial.open('rb') as stream:
                            if b'%PDF-' not in stream.read(1024): raise ValueError('返回内容不是有效PDF')
                    partial.replace(destination)
                    update_file(file['id'], state='completed', downloaded_bytes=count, size_bytes=count, error='')
                    return
        raise ValueError('下载链接刷新后仍不可用')

    async def run(identity):
        stop = stops[identity]
        try:
            if job_lock[0] is None: job_lock[0] = asyncio.Lock()
            async with job_lock[0]:
                item = job(identity)
                if item['state'] != 'queued': return
                row = reading(item['reading_id'])
                files = query('SELECT * FROM court_download_files WHERE job_id=? ORDER BY id', (identity,))
                for file in files:
                    local = Path(item['directory']) / '原始文件' / file['relative_path']
                    if file['state'] == 'completed' and (not local.is_file() or local.stat().st_size != file['size_bytes']):
                        file.update(state='queued', downloaded_bytes=0, validator='')
                        update_file(file['id'], state='queued', downloaded_bytes=0, validator='')
                write("UPDATE court_download_jobs SET state='downloading',error='',updated_at=? WHERE id=?", (stamp(), identity))
                rates[identity] = (time.monotonic(), sum(f['downloaded_bytes'] for f in files))
                limiter = asyncio.Semaphore(3)
                resolve_lock = asyncio.Lock()
                cache = {'time': float('-inf'), 'files': {}}
                async def resolve(force=False):
                    async with resolve_lock:
                        # Short-lived URLs are never persisted. Refresh again on retry.
                        if item['source'] == 'dossier' and not is_open(row): raise HTTPException(403, '阅卷有效期已结束')
                        if force or time.monotonic() - cache['time'] > 60:
                            cache['files'] = {f['remote_id']: f for f in await source_files(row, item['source'])}
                            cache['time'] = time.monotonic()
                        return cache['files']
                async def one(file):
                    if file['state'] == 'completed': return
                    async with limiter:
                        try: await transfer(item, file, resolve, stop)
                        except HTTPException:
                            stop.set()
                            raise
                        except asyncio.CancelledError: raise
                        except Exception as exc:
                            update_file(file['id'], state='failed', error=re.sub(r'https?://[^\s]+', '[下载地址]', str(exc))[:250])
                children = [asyncio.create_task(one(f)) for f in files]
                try: await asyncio.gather(*children)
                finally:
                    for child in children:
                        if not child.done(): child.cancel()
                    await asyncio.gather(*children, return_exceptions=True)
                files = query('SELECT * FROM court_download_files WHERE job_id=? ORDER BY id', (identity,))
                if not any(f['state'] == 'completed' for f in files):
                    write("UPDATE court_download_jobs SET state='failed',error='全部文件下载失败',updated_at=? WHERE id=?", (stamp(), identity)); return
                write("UPDATE court_download_jobs SET state='packing',updated_at=? WHERE id=?", (stamp(), identity))
                archive = await asyncio.get_running_loop().run_in_executor(None, partial(build_zip, item['directory'], files, item['title'], item['source'], stop))
                if stop.is_set(): return
                state = 'completed' if all(f['state'] == 'completed' for f in files) else 'partial'
                write('UPDATE court_download_jobs SET state=?,zip_path=?,updated_at=? WHERE id=?', (state, archive, stamp(), identity))
        except HTTPException as exc:
            write("UPDATE court_download_jobs SET state='paused',error=?,updated_at=? WHERE id=? AND state NOT IN ('cancelled','completed')", (str(exc.detail), stamp(), identity))
        except (asyncio.CancelledError, InterruptedError):
            write("UPDATE court_download_jobs SET state='paused',updated_at=? WHERE id=? AND state IN ('queued','downloading','packing')", (stamp(), identity))
        except Exception as exc:
            write("UPDATE court_download_jobs SET state='failed',error=?,updated_at=? WHERE id=?", (re.sub(r'https?://[^\s]+', '[下载地址]', str(exc))[:250], stamp(), identity))
        finally:
            rates.pop(identity, None)
            speed_samples.pop(identity, None)
            for file in query("SELECT f.*,j.directory FROM court_download_files f JOIN court_download_jobs j ON j.id=f.job_id WHERE f.job_id=? AND f.state!='completed'", (identity,)):
                part = Path(file['directory']) / '原始文件' / (file['relative_path'] + '.part')
                if part.is_file(): update_file(file['id'], downloaded_bytes=part.stat().st_size)
            write("UPDATE court_download_files SET state='queued' WHERE job_id=? AND state='downloading'", (identity,))

    def launch(identity):
        stops[identity] = threading.Event()
        tasks[identity] = asyncio.create_task(run(identity))
        def finished(done):
            # A resume may start before the old done callback runs. Never clear
            # the replacement task's cancellation event or task reference.
            if tasks.get(identity) is done:
                tasks.pop(identity, None)
                stops.pop(identity, None)
        tasks[identity].add_done_callback(finished)

    @app.get('/court-online-downloads')
    async def page():
        return HTMLResponse((Path(frontend_dir) / 'court-online-downloads.html').read_text(), headers={'Cache-Control': 'no-store'})

    @app.get('/api/case-manager/court-online/readings')
    async def list_readings(q: str = '', status: str = '', page: int = 1, page_size: int = 50, refresh: bool = False):
        warning = ''
        owner = account_id()
        if refresh_lock[0] is None: refresh_lock[0] = asyncio.Lock()
        try:
            async with refresh_lock[0]:
                if refresh or time.monotonic() - refreshed.get(owner, float('-inf')) > 60:
                    await refresh_readings()
                    refreshed[owner] = time.monotonic()
        except Exception as exc: warning = str(getattr(exc, 'detail', '官网同步失败，显示最近缓存'))
        rows = query('''SELECT r.*,c.title AS linked_case_title FROM court_readings r LEFT JOIN case_manager_cases c ON c.id=r.linked_case_id WHERE r.account_id=? ORDER BY r.id DESC''', (account_id(),))
        statuses = {'11800006-2': '待审查', '11800006-3': '已开放', '11800006-4': '未通过', '11800006-5': '已失效'}
        for row in rows:
            row['can_download'] = is_open(row)
            row['status_label'] = statuses.get(row['status'], '其他状态')
            if row['status'] == '11800006-3' and not row['can_download']: row['status_label'] = '未开放或已过期'
        rows = [r for r in rows if (not q or q.casefold() in (r['case_number'] + r['court_name']).casefold()) and (not status or r['status'] == status)]
        start = (max(1, page) - 1) * min(100, max(1, page_size))
        return {'items': rows[start:start + min(100, max(1, page_size))], 'total': len(rows), 'warning': warning}

    @app.get('/api/case-manager/court-online/readings/{reading_id}/detail')
    async def detail(reading_id: int):
        row = reading(reading_id)
        data = await remote(REMOTE + '/wsyjxq/' + row['remote_id']) or {}
        # Never send identity numbers, contact details or signed URLs to the UI.
        return {'item': row, 'purpose': data.get('cSqyt') or '', 'requested_content': data.get('xcynr') or '',
                'review_comment': data.get('scyj') or '', 'materials': [{'name': f.get('name') or f.get('wjmc')} for f in data.get('wsyjCls', [])]}

    @app.get('/api/case-manager/court-online/readings/{reading_id}/directory')
    async def directory(reading_id: int):
        row = reading(reading_id)
        files = await source_files(row, 'dossier')
        return {'files': [{k: v for k, v in f.items() if k != 'url'} for f in files],
                'notice': '' if files else '官网目录未返回可下载文件。如使用独立阅卷服务，请在官网查看；该路径待有效卷宗样本进一步验证。'}

    @app.post('/api/case-manager/court-online/readings/{reading_id}/case')
    async def link(reading_id: int, body: dict):
        reading(reading_id)
        case = body.get('case_id')
        if not query('SELECT id FROM case_manager_cases WHERE id=?', (case,)): raise HTTPException(404, '案件不存在')
        write('UPDATE court_readings SET linked_case_id=? WHERE id=?', (case, reading_id))
        return {'ok': True}

    @app.post('/api/case-manager/court-online/readings/{reading_id}/downloads')
    async def create(reading_id: int, body: dict):
        row = reading(reading_id)
        owner = account_id()
        source = body.get('source', 'dossier')
        if source not in ('dossier', 'application-test'): raise HTTPException(422, '未知文件来源')
        files = await source_files(row, source)
        selected = body.get('file_ids')
        if selected is not None:
            if not isinstance(selected, list) or not all(isinstance(x, str) for x in selected): raise HTTPException(422, '文件选择无效')
            files = [f for f in files if f['remote_id'] in selected]
        if not files: raise HTTPException(409, '暂无开放下载的文件')
        if account_id() != owner: raise HTTPException(409, '账号已切换，请重试')
        for file in files: validate_url(file['url'])
        # Repeated clicks reuse an active batch instead of downloading twice.
        active = query("SELECT id FROM court_download_jobs WHERE account_id=? AND reading_id=? AND source=? AND state IN ('queued','downloading','packing')", (owner, reading_id, source))
        wanted = sorted(f['remote_id'] for f in files)
        for candidate in active:
            if sorted(f['remote_id'] for f in query('SELECT remote_id FROM court_download_files WHERE job_id=?', (candidate['id'],))) == wanted: return snapshot(candidate['id'])
        if query("SELECT COUNT(*) AS count FROM court_download_jobs WHERE state IN ('queued','downloading','packing')")[0]['count'] >= 20:
            raise HTTPException(429, '下载队列已满，请等待当前任务结束')
        identity = uuid.uuid4().hex
        title = row['case_number'] + ('—申请材料打包测试' if source == 'application-test' else '—开放卷宗') + dt.datetime.now().strftime('-%Y%m%d-%H%M%S')
        root = Path(download_directory()) / (safe_name(title) + '-' + identity[:8])
        root.mkdir(parents=True)
        with get_db() as conn:
            conn.execute('INSERT INTO court_download_jobs(id,account_id,reading_id,title,source,state,directory,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)', (identity, owner, reading_id, title, source, 'queued', str(root), stamp(), stamp()))
            conn.executemany('INSERT INTO court_download_files(job_id,remote_id,name,relative_path,size_bytes) VALUES(?,?,?,?,?)', [(identity, f['remote_id'], f['name'], f['relative_path'], f['size_bytes']) for f in files])
            conn.commit()
        launch(identity)
        return snapshot(identity)

    @app.get('/api/case-manager/court-online/downloads')
    async def list_jobs(page: int = 1):
        owner = account_id()
        rows = query('SELECT id FROM court_download_jobs WHERE account_id=? ORDER BY created_at DESC LIMIT 50 OFFSET ?', (owner, (max(1, page)-1)*50))
        return {'items': [{k: v for k, v in snapshot(r['id'], owner).items() if k != 'files'} for r in rows]}

    @app.get('/api/case-manager/court-online/downloads/{job_id}')
    async def get_job(job_id: str): return snapshot(job_id)

    @app.post('/api/case-manager/court-online/downloads/{job_id}/{action}')
    async def control(job_id: str, action: str):
        item = job(job_id)
        if action in ('pause', 'cancel'):
            if item['state'] in TERMINAL: return snapshot(job_id)
            if job_id in stops: stops[job_id].set()
            if job_id in tasks:
                if item['state'] != 'packing': tasks[job_id].cancel()
                await asyncio.gather(tasks[job_id], return_exceptions=True)
            write('UPDATE court_download_jobs SET state=?,updated_at=? WHERE id=?', ('paused' if action == 'pause' else 'cancelled', stamp(), job_id))
        elif action in ('resume', 'retry'):
            if job_id in tasks and not tasks[job_id].done(): return snapshot(job_id)
            if item['state'] == 'completed': return snapshot(job_id)
            write("UPDATE court_download_files SET state='queued',error='' WHERE job_id=? AND state != 'completed'", (job_id,))
            write("UPDATE court_download_jobs SET state='queued',error='',zip_path=NULL,updated_at=? WHERE id=?", (stamp(), job_id))
            launch(job_id)
        elif action in ('open-folder', 'open-zip'):
            path = Path(item['zip_path']) if action == 'open-zip' and item['zip_path'] else Path(item['directory'])
            if action == 'open-zip' and not item['zip_path']: raise HTTPException(409, '压缩包尚未完成')
            if not path.exists(): raise HTTPException(404, '本地文件不存在')
            subprocess.run(['open', str(path)], check=True, timeout=10)
        else: raise HTTPException(422, '未知操作')
        return snapshot(job_id)

    @app.get('/api/case-manager/court-online/downloads/{job_id}/archive')
    async def archive(job_id: str):
        item = job(job_id)
        if not item['zip_path'] or not Path(item['zip_path']).is_file(): raise HTTPException(404, '压缩包尚未完成')
        return FileResponse(item['zip_path'], filename=Path(item['zip_path']).name, media_type='application/zip')

    @app.on_event('startup')
    async def recover():
        write("UPDATE court_download_jobs SET state='paused',error='服务重启，请点击继续下载' WHERE state IN ('queued','downloading','packing')")
        write("UPDATE court_download_files SET state='queued' WHERE state='downloading'")

    async def stop_jobs():
        pending = list(tasks.items())
        for event in stops.values(): event.set()
        for identity, task in pending:
            rows = query('SELECT state FROM court_download_jobs WHERE id=?', (identity,))
            if not rows or rows[0]['state'] != 'packing': task.cancel()
        await asyncio.gather(*(task for _, task in pending), return_exceptions=True)

    state = getattr(app, 'state', None)
    if state is not None: state.pause_court_dossier_jobs = stop_jobs

    @app.on_event('shutdown')
    async def shutdown():
        await stop_jobs()
