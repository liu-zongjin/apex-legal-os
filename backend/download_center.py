"""Unified download metadata and managed staging; never accepts client file paths."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import functools
import hashlib
import os
import re
import shutil
import tempfile
import threading
import time
from contextvars import ContextVar
import uuid
from pathlib import Path
from typing import Any

from fastapi import File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

CATEGORIES = {'mail':'邮箱附件','invoice':'发票','court':'一张网','judicial':'司法短信','document':'文书生成','ai':'AI增强','case':'案件管理','archive':'案卷归档','knowledge':'知识库','calculator':'计算工具','recording':'会议录音','scanner':'扫描件','expenses':'团队费用','filing':'自动化立案','settings':'设置与备份','export':'其他导出'}

MAX_BYTES = 500 * 1024 * 1024
ACTIVE = {'preparing', 'downloading', 'saving', 'queued', 'packing'}
ROOT = Path(os.environ.get('LEGAL_KB_RUNTIME_DIR', str(Path(__file__).resolve().parent.parent))) / 'data' / 'download-center'


async def in_thread(function, *args, **kwargs):
    return await asyncio.get_running_loop().run_in_executor(None, functools.partial(function, *args, **kwargs))


def retry_hint(item):
    page = {'mail':'邮箱','invoice':'发票中心','court':'一张网','judicial':'司法短信',
            'document':'文书生成器','ai':'AI 增强','case':'案件管理','archive':'案卷归档',
            'knowledge':'知识库','calculator':'计算工具','recording':'会议录音',
            'scanner':'扫描件收件箱','expenses':'团队费用','filing':'自动化立案','settings':'设置'}.get(item.get('category'))
    return f'请打开{page}后重新发起下载' if page else '请重新执行导出操作'


def now():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec='seconds')


def filename(value):
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', str(value or '文件')).strip(' .') or '文件'
    suffix = Path(cleaned).suffix.encode('utf-8')[:30].decode('utf-8','ignore')
    stem = Path(cleaned).stem.encode('utf-8')[:200].decode('utf-8','ignore')
    return stem + suffix


class DownloadStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.records = {}
        self.tasks = set()
        try: self.hidden=set(json.loads((self.root/'hidden.json').read_text()))
        except (OSError,ValueError): self.hidden=set()
        state = self.root / 'records.json'
        if state.exists():
            try:
                self.records = {item['id']: item for item in json.loads(state.read_text())}
            except (ValueError, KeyError, TypeError):
                # Preserve damaged history for recovery rather than replacing it silently.
                shutil.copy2(state, self.root / ('records-invalid-' + uuid.uuid4().hex + '.json'))
        for item in self.records.values():
            if item.get('status') in ACTIVE:
                item.update(status='interrupted', error='服务重启，下载已中断。'+retry_hint(item))

    def flush(self):
        fd, temporary = tempfile.mkstemp(dir=self.root, prefix='.records-')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(list(self.records.values()), handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.root / 'records.json')
        finally:
            if Path(temporary).exists():
                Path(temporary).unlink()
        fd,temporary=tempfile.mkstemp(dir=self.root,prefix='.hidden-')
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as handle: json.dump(sorted(self.hidden),handle);handle.flush();os.fsync(handle.fileno())
            os.replace(temporary,self.root/'hidden.json')
        finally:
            if Path(temporary).exists(): Path(temporary).unlink()

    def create(self, **values):
        with self.lock:
            identity = uuid.uuid4().hex
            item = {'id': identity, 'name': '文件', 'source': '其他导出', 'category': 'export',
                    'purpose': 'other', 'status': 'preparing', 'phase': '正在准备文件',
                    'received_bytes': 0, 'total_bytes': 0, 'completed_files': 0, 'total_files': 1,
                    'failed_files': 0, 'case_id': 0, 'case_title': '', 'case_saved':False, 'path': '',
                    'destination': '应用暂存区', 'error': '', 'created_at': now(), 'updated_at': now(), **values}
            self.records[identity] = item
            # Bound metadata; files are never removed while pruning display history.
            if len(self.records) > 2000:
                finished = [key for key, record in self.records.items() if record.get('status') not in ACTIVE and key != identity]
                for key in finished[:len(self.records)-2000]:
                    self.records.pop(key)
            self.flush()
            return dict(item)

    def update(self, identity, **values):
        with self.lock:
            if identity not in self.records:
                raise HTTPException(404, '下载记录不存在')
            self.records[identity].update(values, updated_at=now())
            self.flush()
            return dict(self.records[identity])

    def get(self, identity):
        with self.lock:
            if identity not in self.records:
                raise HTTPException(404, '下载记录不存在')
            return dict(self.records[identity])

    def all(self):
        with self.lock:
            return [dict(item) for item in self.records.values()]


_store = None


def get_store():
    global _store
    if _store is None:
        _store = DownloadStore(ROOT)
    return _store


current_transfer = ContextVar('apex_center_transfer', default=None)


def report_transfer(**values):
    context = current_transfer.get()
    if context:
        if set(values)=={'received_bytes'} and time.monotonic()-context.get('last',0)<.4:
            return
        context['last']=time.monotonic()
        get_store().update(context['id'], **values)


def create_judicial_tracker(get_db, document_id):
    with get_db() as conn:
        row = conn.execute("""SELECT d.original_filename,COALESCE(d.case_id,m.matched_case_id,0) AS case_id,c.title
          FROM case_manager_message_documents d JOIN case_manager_judicial_messages m ON m.id=d.message_id
          LEFT JOIN case_manager_cases c ON c.id=COALESCE(d.case_id,m.matched_case_id) WHERE d.id=?""",(document_id,)).fetchone()
    return get_store().create(name=row[0] or '司法送达文书',source='司法短信',category='judicial',purpose='case',case_id=row[1],case_title=row[2] or '',total_files=0,is_batch=True,batch_title='司法送达文书',destination='获取批次：实际位置见文件明细')['id']


def update_judicial_tracker(identity, progress):
    state = progress.get('status')
    fields = {key:progress[key] for key in ('received_bytes','total_bytes','total_files','completed_files','failed_files','error') if key in progress}
    if progress.get('filename'): fields['name']=progress['filename']
    fields['status'] = {'preparing':'preparing','downloading':'downloading','saving':'saving'}.get(progress.get('phase'),'downloading') if state=='running' else state
    fields['phase'] = {'preparing':'正在读取送达清单','downloading':'正在下载送达文书','saving':'正在校验并保存文书'}.get(progress.get('phase'),'司法短信文书')
    get_store().update(identity,**fields)


def register_download_center_routes(app, get_db):
    from .case_automation import get_folder_binding, store_case_file
    from . import qq_mail_mcp
    store = get_store()

    def case_info(case_id, require_binding=False):
        case_id = int(case_id or 0)
        if not case_id:
            return {'case_id': 0, 'case_title': ''}
        with get_db() as conn:
            row = conn.execute('SELECT title FROM case_manager_cases WHERE id=?', (case_id,)).fetchone()
        if not row:
            raise HTTPException(404, '案件不存在')
        if require_binding:
            binding = get_folder_binding(get_db, case_id, required=True)
            if not binding.get('available'):
                raise HTTPException(409, '案件绑定的本地文件夹不可用，请先检查绑定')
        return {'case_id': case_id, 'case_title': row[0]}

    def history():
        records = []
        with get_db() as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if {'case_manager_message_documents', 'case_manager_judicial_messages', 'case_manager_cases'} <= tables:
                rows = conn.execute('''SELECT d.*,m.matched_case_id,c.title AS case_title
                  FROM case_manager_message_documents d JOIN case_manager_judicial_messages m ON m.id=d.message_id
                  LEFT JOIN case_manager_cases c ON c.id=COALESCE(d.case_id,m.matched_case_id)
                  WHERE m.is_deleted=0 AND (d.staging_path<>'' OR d.status='archived') ORDER BY d.id DESC LIMIT 500''').fetchall()
                for row in rows:
                    r = dict(row)
                    path = r.get('staging_path') or ''
                    if r.get('file_id') and 'case_manager_files' in tables:
                        file = conn.execute('SELECT absolute_path FROM case_manager_files WHERE id=?', (r['file_id'],)).fetchone()
                        if file: path = file[0]
                    records.append({'id': f"judicial-{r['id']}", 'name': r.get('final_filename') or r.get('original_filename'),
                        'category': 'judicial', 'purpose':'case', 'source':'司法短信', 'status':'completed' if r['status'] in ('archived','waiting_confirmation','downloaded','verified') else r['status'],
                        'case_id':r.get('case_id') or r.get('matched_case_id') or 0, 'case_title':r.get('case_title') or '',
                        'path':path, 'destination':'案件文件夹' if r['status']=='archived' else '应用暂存区（待确认）',
                        'case_saved':r['status']=='archived', 'created_at':r['created_at'], 'error':r.get('last_error') or '', 'file_url':f"/api/download-center/records/judicial-{r['id']}/file"})
            if {'case_manager_files','case_manager_cases'} <= tables:
                managed_paths={record.get('path') for record in store.all()}
                sources={'suohan_generator':'文书生成 · 所函','power_attorney_generator':'文书生成 · 授权委托书',
                    'rep_identity_cert_generator':'文书生成 · 法定代表人身份证明','business_approval_generator':'文书生成 · 业务审批表',
                    'document_bundle_generator':'文书生成 · 文书合集','qq_mail':'QQ邮箱','netease_exmail':'网易企业邮箱','qq_exmail':'腾讯企业邮箱'}
                marks=','.join('?' for _ in sources)
                rows=conn.execute(f'SELECT f.*,c.title AS case_title FROM case_manager_files f JOIN case_manager_cases c ON c.id=f.case_id WHERE f.source_type IN ({marks}) ORDER BY f.id DESC LIMIT 500',tuple(sources)).fetchall()
                for row in rows:
                    item=dict(row)
                    if item['absolute_path'] in managed_paths: continue
                    records.append({'id':'casefile-'+str(item['id']),'name':Path(item['absolute_path']).name,'source':sources[item['source_type']],
                        'category':'mail' if item['source_type'] in ('qq_mail','netease_exmail','qq_exmail') else 'document',
                        'purpose':'case','status':'completed','case_id':item['case_id'],'case_title':item['case_title'], 'case_saved':True,
                        'path':item['absolute_path'],'destination':item['absolute_path'],'created_at':item['created_at'],
                        'received_bytes':item['size_bytes'],'total_bytes':item['size_bytes']})
            if {'case_archive_exports','case_manager_folder_bindings','case_manager_cases'} <= tables:
                managed_paths={r.get('path') for r in store.all()}
                rows=conn.execute("""SELECT e.*,c.title AS case_title,b.real_path FROM case_archive_exports e
                    JOIN case_manager_cases c ON c.id=e.case_id
                    JOIN case_manager_folder_bindings b ON b.case_id=e.case_id
                    ORDER BY e.id DESC LIMIT 500""").fetchall()
                for row in rows:
                    r=dict(row)
                    relative=Path(r['relative_directory'])
                    if relative.is_absolute() or '..' in relative.parts: continue
                    for kind,name in {'pdf':'结案材料.pdf','catalog':'卷内目录.docx','summary':'办案小结.docx','manifest':'材料清单.json'}.items():
                        if kind=='summary' and r['category']=='criminal': continue
                        path=str(Path(r['real_path'])/relative/name)
                        if path in managed_paths: continue
                        records.append({'id':f"archive-{r['id']}-{kind}",'name':name,'source':'案卷归档',
                            'category':'archive','purpose':'case','status':'completed','case_id':r['case_id'],
                            'case_title':r['case_title'],'case_saved':True,'path':path,'destination':path,
                            'created_at':r['created_at']})
            if {'court_download_jobs','court_download_files','court_readings'} <= tables:
                rows = conn.execute('''SELECT j.*,r.case_number,r.linked_case_id,c.title AS case_title FROM court_download_jobs j
                  LEFT JOIN court_readings r ON r.id=j.reading_id LEFT JOIN case_manager_cases c ON c.id=r.linked_case_id ORDER BY j.created_at DESC LIMIT 200''').fetchall()
                for row in rows:
                    r = dict(row)
                    files = [dict(f) for f in conn.execute('SELECT * FROM court_download_files WHERE job_id=?', (r['id'],))]
                    records.append({'id':'dossier-'+r['id'], 'name':r.get('case_number') or '在线阅卷卷宗', 'source':'一张网 · 在线阅卷',
                      'category':'court', 'purpose':'case', 'case_id':r.get('linked_case_id') or 0, 'case_title':r.get('case_title') or '',
                      'status':r['state'], 'path':r.get('zip_path') or '', 'destination':r['directory'], 'created_at':r['created_at'], 'error':r['error'],
                      'received_bytes':sum(f['downloaded_bytes'] for f in files), 'total_bytes':sum(f['size_bytes'] or 0 for f in files) if all(f['size_bytes'] is not None for f in files) else 0,
                      'completed_files':sum(f['state']=='completed' for f in files), 'failed_files':sum(f['state']=='failed' for f in files), 'total_files':len(files),
                      'is_batch':True, 'detail_url':'/court-online-downloads?job='+r['id'], 'job_id':r['id']})
        return [r for r in records if r['id'] not in store.hidden]

    def resolve(identity):
        if identity.startswith(('judicial-', 'dossier-', 'casefile-', 'archive-')):
            item = next((r for r in history() if r['id']==identity), None)
            if not item: raise HTTPException(404, '历史文件记录不存在')
            return item
        return store.get(identity)

    def trusted_file(item):
        path = Path(item.get('path') or '')
        if not path.is_file():
            raise HTTPException(404, '文件已不在原保存位置。'+retry_hint(item))
        from .judicial_messages import JUDICIAL_STAGING_DIR
        allowed = [JUDICIAL_STAGING_DIR, store.root, qq_mail_mcp._BASE_DIR / 'uploads' / '邮箱附件', *[c['attachment_root'] for c in qq_mail_mcp.MAILBOX_CONFIGS.values()],
                   Path(__file__).resolve().parent / 'judicial_downloads', Path.home() / 'Downloads']
        with get_db() as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'case_manager_court_online_settings' in tables:
                row = conn.execute('SELECT download_directory FROM case_manager_court_online_settings WHERE id=1').fetchone()
                if row and row[0]: allowed.append(Path(row[0]))
        if item.get('user_saved_directory'): allowed.append(Path(item['user_saved_directory']))
        if item.get('id','').startswith('dossier-') and item.get('destination'): allowed.append(Path(item['destination']))
        if item.get('case_id'):
            binding = get_folder_binding(get_db, int(item['case_id']), required=False)
            if binding.get('available'): allowed.append(Path(binding['real_path']))
        path = path.resolve()
        if not any(path == Path(root).resolve() or Path(root).resolve() in path.parents for root in allowed):
            raise HTTPException(403, '文件已离开授权保存目录')
        return path

    def file_state(item):
        result = dict(item)
        result.update(file_available=False, file_state='unknown', size_bytes=None, file_revision=None)
        if not item.get('path'):
            result['file_state'] = 'batch' if item.get('is_batch') else 'unknown'
            return result
        try:
            path = Path(item['path'])
            stat = path.stat()
            if not path.is_file():
                result['file_state'] = 'unavailable'
                return result
            result.update(file_state='present', size_bytes=stat.st_size)
            try:
                trusted_file(item)
                from .storage_exports import file_revision
                result.update(file_available=True, file_revision=file_revision(path))
            except HTTPException:
                result['file_state'] = 'unavailable'
        except FileNotFoundError:
            # An unavailable volume/directory is not evidence that a file was deleted.
            result['file_state'] = 'missing' if Path(item['path']).parent.is_dir() else 'unavailable'
        except OSError:
            result['file_state'] = 'unavailable'
        if result['file_available']:
            result['file_url'] = '/api/download-center/records/'+item['id']+'/file'
        return result

    def timestamp(value):
        try:
            value = dt.datetime.fromisoformat(str(value or '').replace('Z','+00:00'))
            if value.tzinfo is None: value=value.replace(tzinfo=dt.timezone(dt.timedelta(hours=8)))
            return value.timestamp()
        except (ValueError, TypeError): return 0

    @app.get('/api/download-center/records')
    async def list_records(q: str='', category: str='', status: str='', page: int=1, page_size: int=40,
                           sort: str='newest', min_bytes: int=0, max_bytes: int=-1,
                           date_from: str='', date_to: str='', availability: str=''):
        if sort not in ('newest','oldest','largest','smallest') or min_bytes<0 or max_bytes < -1:
            raise HTTPException(400,'无效排序或大小范围')
        start, end = timestamp(date_from), timestamp(date_to)
        if (date_from and not start) or (date_to and not end): raise HTTPException(400,'无效时间范围')
        if date_to and len(date_to)==10: end += 86400 - .000001
        if start and end and start>end: raise HTTPException(400,'开始时间不能晚于结束时间')
        if max_bytes>=0 and min_bytes>max_bytes: raise HTTPException(400,'最小大小不能超过最大大小')
        rows = store.all() + history()
        summary = {'total':len(rows), 'active':sum(r.get('status') in ACTIVE for r in rows),
                   'failed':sum(r.get('status') in ('failed','partial','interrupted') for r in rows),
                   'unassigned':sum(r.get('purpose')=='case' and not r.get('case_id') for r in rows)}
        rows = [r for r in rows if (not category or r.get('category')==category) and
          (not status or (status=='active' and r.get('status') in ACTIVE) or (status=='issues' and r.get('status') in ('failed','partial','interrupted')) or (status=='unassigned' and r.get('purpose')=='case' and not r.get('case_id')) or r.get('status')==status) and
          (not q or q.casefold() in ' '.join(str(r.get(k) or '') for k in ('name','source','case_title','source_case_title','destination')).casefold()) and
          (not start or timestamp(r.get('created_at'))>=start) and (not end or timestamp(r.get('created_at'))<=end)]
        rows = await in_thread(lambda: [file_state(r) for r in rows])
        rows = [r for r in rows if (not availability or r['file_state']==availability) and
                (not min_bytes or r['size_bytes'] is not None and r['size_bytes']>=min_bytes) and
                (max_bytes<0 or r['size_bytes'] is not None and r['size_bytes']<=max_bytes)]
        if sort in ('largest','smallest'):
            rows.sort(key=lambda r:(r['size_bytes'] is None, -(r['size_bytes'] or 0) if sort=='largest' else r['size_bytes'] or 0, -timestamp(r.get('created_at')), r['id']))
        else: rows.sort(key=lambda r:(timestamp(r.get('created_at')), r['id']), reverse=sort=='newest')
        size, page = max(1,min(100,page_size)), max(1,page)
        return {'items':rows[(page-1)*size:page*size], 'total':len(rows), 'page':page, 'summary':summary, 'categories':CATEGORIES}

    def missing_candidates():
        return [r for r in store.all()+history() if r.get('status') not in ACTIVE and file_state(r)['file_state']=='missing']

    @app.post('/api/download-center/analyze')
    async def analyze():
        items = await in_thread(missing_candidates)
        return {'items':[{'id':r['id'],'name':r.get('name'),'path':r.get('path')} for r in items], 'total':len(items)}

    @app.post('/api/download-center/clean-missing')
    async def clean_missing(request: Request):
        body = await request.json()
        identities = body.get('ids')
        if body.get('confirmed') is not True or not isinstance(identities,list) or len(identities)>2000 or any(not isinstance(identity,str) for identity in identities):
            raise HTTPException(400,'请确认要移除的失效记录')
        removed = 0
        with store.lock:
            eligible={r['id'] for r in missing_candidates()}
            for identity in set(identities)&eligible:
                if identity in store.records: store.records.pop(identity)
                else: store.hidden.add(identity)
                removed += 1
            store.flush()
        return {'removed':removed, 'skipped':len(set(identities))-removed}

    @app.post('/api/download-center/trash')
    async def trash_files(request: Request):
        body = await request.json()
        entries = body.get('items')
        if body.get('confirmed') is not True or not isinstance(entries,list) or not 1<=len(entries)<=100:
            raise HTTPException(400,'每次请选择 1 至 100 个文件并确认移到废纸篓')
        from .storage_exports import file_revision
        import subprocess
from .platform_files import run as run_desktop, has_picker
        moved, errors, paths = [], [], set()
        for entry in entries:
            identity = str(entry.get('id') or '') if isinstance(entry,dict) else ''
            try:
                item=resolve(identity)
                if item.get('status') in ACTIVE: raise HTTPException(409,'文件仍在处理中')
                path=trusted_file(item)
                if Path(item['path']).is_symlink() or file_revision(path)!=entry.get('revision'):
                    raise HTTPException(409,'文件已变化，请刷新后重新选择')
                if path not in paths:
                    await in_thread(run_desktop, ['osascript','-e', 'on run argv\n tell application "Finder" to delete (POSIX file (item 1 of argv))\nend run', str(path)], check=True, capture_output=True, timeout=30)
                    paths.add(path)
                moved.append(identity)
            except (HTTPException,OSError,subprocess.SubprocessError) as exc:
                errors.append({'id':identity,'error':str(getattr(exc,'detail','无法移到废纸篓，请刷新后重试'))})
        return {'moved':moved,'errors':errors}

    @app.post('/api/download-center/import-legacy')
    async def import_legacy(request: Request):
        body=await request.json()
        existing={r.get('legacy_key') for r in store.all()}
        count=0
        for old in (body.get('items') or [])[:200]:
            if not isinstance(old,dict): continue
            key=hashlib.sha256(json.dumps([old.get('id'),old.get('name'),old.get('createdAt')],ensure_ascii=False).encode()).hexdigest()
            if key in existing: continue
            name=filename(old.get('name'))
            candidate=Path.home()/'Downloads'/name
            located=name==old.get('name') and candidate.is_file()
            store.create(name=name,source=str(old.get('source') or '历史下载')[:200],category=str(old.get('category') or 'export')[:40],
              purpose='invoice' if old.get('category')=='invoice' else 'other',status='completed',legacy_key=key,
              created_at=str(old.get('createdAt') or now())[:50],path=str(candidate) if located else '',
              destination=str(candidate) if located else '历史浏览器记录：保存位置未确认')
            existing.add(key);count+=1
        return {'imported':count}

    @app.post('/api/download-center/records')
    async def create_record(request: Request):
        body = await request.json()
        fields = {k:str(body.get(k) or '')[:200] for k in ('name','source','category','purpose')}
        if fields['category'] not in CATEGORIES: raise HTTPException(400,'无效下载来源')
        if fields['purpose'] not in ('case','invoice','other'): raise HTTPException(400,'无效文件用途')
        return store.create(**fields, **case_info(body.get('case_id')),client_owned=True)

    @app.post('/api/download-center/clear-completed')
    async def clear_completed(request: Request):
        body=await request.json()
        if body.get('confirmed') is not True: raise HTTPException(400,'请确认移除已完成记录')
        removed=0
        with store.lock:
            for item in store.all()+history():
                if item.get('status')!='completed' or (item.get('purpose')=='case' and not item.get('case_saved')) or '待确认' in item.get('destination',''): continue
                if item['id'] in store.records: store.records.pop(item['id'])
                else: store.hidden.add(item['id'])
                removed+=1
            store.flush()
        return {'removed':removed}

    @app.post('/api/download-center/records/{identity}/interrupt')
    async def interrupt_client(identity: str):
        item=store.get(identity)
        if item.get('client_owned') and item.get('status') in ACTIVE:
            store.update(identity,status='interrupted',error='下载页面已关闭。'+retry_hint(item))
        return {'ok':True}

    @app.get('/api/download-center/records/{identity}')
    async def get_record(identity: str):
        return resolve(identity)

    @app.patch('/api/download-center/records/{identity}')
    async def patch_record(identity: str, request: Request):
        body = await request.json()
        allowed = {k:body[k] for k in ('status','phase','received_bytes','total_bytes','completed_files','total_files','failed_files','error','name') if k in body}
        for key in ('received_bytes','total_bytes','completed_files','total_files','failed_files'):
            if key in allowed: allowed[key] = max(0,min(1<<50,int(allowed[key] or 0)))
        for key in ('status','phase','error','name'):
            if key in allowed: allowed[key] = str(allowed[key])[:1000]
        if allowed.get('status') and allowed['status'] not in ACTIVE|{'completed','failed','partial','interrupted','needs_action','cancelled'}: raise HTTPException(400,'无效下载状态')
        return store.update(identity, **allowed)

    @app.post('/api/download-center/records/{identity}/file')
    async def upload_result(identity: str, file: UploadFile=File(...)):
        item = store.get(identity)
        directory = store.root / identity
        directory.mkdir(exist_ok=True)
        target = directory / filename(file.filename or item['name'])
        fd, temp = tempfile.mkstemp(dir=directory)
        size = 0
        try:
            with os.fdopen(fd,'wb') as handle:
                while chunk := await file.read(1024*1024):
                    size += len(chunk)
                    if size > MAX_BYTES: raise HTTPException(413,'文件超过 500MB')
                    handle.write(chunk)
                handle.flush(); os.fsync(handle.fileno())
            os.replace(temp,target)
        finally:
            if Path(temp).exists(): Path(temp).unlink()
        return store.update(identity, name=filename(file.filename or item['name']), path=str(target), status='completed', phase='文件已就绪',
                            received_bytes=size,total_bytes=size,completed_files=1,destination='应用暂存区（待确认存入案件）' if item.get('purpose')=='case' else '应用暂存区')

    @app.get('/api/download-center/records/{identity}/file')
    async def download_file(identity: str):
        item = resolve(identity)
        return FileResponse(trusted_file(item), filename=filename(item['name']))

    @app.post('/api/download-center/records/{identity}/open')
    async def open_file(identity: str):
        import subprocess
        item = resolve(identity)
        path = trusted_file(item)
        await in_thread(run_desktop, ['open','-R',str(path)], check=True, timeout=10)
        return {'ok':True}

    @app.post('/api/download-center/records/{identity}/save-case')
    async def save_to_case(identity: str, request: Request):
        body = await request.json()
        if body.get('confirmed') is not True: raise HTTPException(400,'请明确确认保存案件和文件夹')
        item = resolve(identity)
        if item.get('purpose')=='invoice' or item.get('category')=='invoice': raise HTTPException(400,'发票归集与案件材料分开保存')
        info = case_info(body.get('case_id'), require_binding=True)
        if not info['case_id']: raise HTTPException(400,'请选择案件')
        path = trusted_file(item)
        if path.stat().st_size > MAX_BYTES: raise HTTPException(413,'文件超过 500MB')
        result = await in_thread(lambda: store_case_file(get_db, info['case_id'], 'download_material', filename(item['name']), path.read_bytes(),
                                         source_type='download_center', metadata={'download_id':identity,'source':item['source']}))
        values = {**info,'path':result['absolute_path'],'destination':result['absolute_path'],'case_file_id':result['id'],'case_saved':True}
        if identity.startswith(('judicial-','casefile-')):
            return store.create(**{k:item[k] for k in ('name','source','category','purpose')}, **values,status='completed')
        return store.update(identity, **values)

    @app.post('/api/download-center/invoice-results')
    async def register_invoice_results(request: Request):
        body=await request.json()
        identity=str(body.get('identity') or '')
        parent=store.get(identity)
        if parent.get('purpose')!='invoice': raise HTTPException(400,'仅可登记发票归集结果')
        roots=[config['attachment_root'].resolve() for config in qq_mail_mcp.MAILBOX_CONFIGS.values()]
        existing={r.get('path'):r for r in store.all() if r.get('category')=='invoice' and not r.get('is_batch')}
        count,bytes_total=0,0
        for invoice in (body.get('invoices') or []):
            if not isinstance(invoice,dict): continue
            path=Path(str(invoice.get('path') or '')).resolve()
            if not path.is_file() or not any(root in path.parents for root in roots): continue
            if str(path) not in existing:
                owner=next((config.get('label') for config in qq_mail_mcp.MAILBOX_CONFIGS.values() if config['attachment_root'].resolve() in path.parents),None)
                item=store.create(name=path.name,source='发票中心 · '+owner if owner else parent['source'],category='invoice',purpose='invoice',status='completed',
                  path=str(path),destination=str(path),parent_id=identity,total_bytes=path.stat().st_size,received_bytes=path.stat().st_size,completed_files=1)
                existing[str(path)]=item
            count+=1;bytes_total+=path.stat().st_size
        warnings=[str(value) for value in (body.get('warnings') or []) if value]
        incomplete=bool(warnings or body.get('timed_out'))
        return store.update(identity,name='发票检索与归集',is_batch=True,batch_title='发票检索与归集',status='partial' if incomplete else 'completed',phase='发票归集部分完成' if incomplete else '发票归集完成',error='；'.join(warnings),
            total_files=count,completed_files=count,total_bytes=bytes_total,received_bytes=bytes_total,destination='发票文件明细中的实际位置')

    @app.post('/api/download-center/native-ticket')
    async def native_ticket(request: Request):
        import urllib.parse
        body=await request.json()
        parsed=urllib.parse.urlparse(str(body.get('url') or ''))
        if parsed.hostname not in (None,'localhost','127.0.0.1','::1'): raise HTTPException(400,'原生下载来源必须是本机服务')
        path=parsed.path
        match=re.fullmatch(r'/api/case-manager/court-online/downloads/([^/]+)/archive',path)
        if not match: raise HTTPException(400,'该原生下载未对应已知文件')
        from .court_online_service import _active_account_id
        with get_db() as conn:
            owned=conn.execute('SELECT 1 FROM court_download_jobs WHERE id=? AND account_id=?',(match[1],_active_account_id())).fetchone()
        if not owned: raise HTTPException(404,'当前账号中未找到卷宗下载')
        native_id=str(body.get('native_id') or '')[:80]
        existing=next((r for r in store.all() if native_id and r.get('native_id')==native_id and r.get('source_dossier_id')==match[1]),None)
        if existing: return existing
        original=resolve('dossier-'+match[1])
        source=trusted_file(original)
        return store.create(name=source.name,source=original['source'],category='court',purpose='case',
            case_id=original['case_id'],case_title=original['case_title'],path=str(source),destination=str(source),
            status='downloading',total_bytes=source.stat().st_size,phase='正在保存 ZIP 到所选位置',native_id=native_id,source_dossier_id=match[1])

    @app.post('/api/download-center/records/{identity}/native-saved')
    async def native_saved(identity: str, request: Request):
        body=await request.json()
        item=store.get(identity)
        original=trusted_file(item)
        candidate=Path(str(body.get('path') or '')).resolve()
        def verify():
            if not candidate.is_file() or candidate.stat().st_size!=original.stat().st_size:
                raise HTTPException(409,'系统保存的文件尚未完成')
            def digest(path):
                checksum=hashlib.sha256()
                with path.open('rb') as handle:
                    while data:=handle.read(1024*1024): checksum.update(data)
                return checksum.digest()
            if digest(candidate)!=digest(original): raise HTTPException(403,'系统文件与本次下载不一致')
        await in_thread(verify)
        context={}
        with get_db() as conn:
            bindings=conn.execute('SELECT case_id,real_path FROM case_manager_folder_bindings').fetchall()
        owners=[]
        for binding in bindings:
            root=Path(binding[1]).resolve()
            if root in candidate.parents and get_folder_binding(get_db,binding[0],required=False).get('available'):
                owners.append((len(root.parts),binding[0]))
        if owners and item.get('purpose')!='invoice':
            depth=max(depth for depth,_ in owners)
            closest=[case_id for level,case_id in owners if level==depth]
            if len(closest)==1:
                context={**case_info(closest[0]),'case_saved':True}
                if item.get('case_id') and item['case_id']!=context['case_id']:
                    context.update(source_case_id=item['case_id'],source_case_title=item.get('case_title') or '')
        return store.update(identity,path=str(candidate),user_saved_directory=str(candidate.parent),name=candidate.name,
            destination=str(candidate),status='completed',phase='已保存到所选位置',received_bytes=candidate.stat().st_size,completed_files=1,**context)


    @app.post('/api/download-center/case-files/{file_id}/register')
    async def register_case_result(file_id: int, request: Request):
        with get_db() as conn:
            row = conn.execute('SELECT * FROM case_manager_files WHERE id=?', (file_id,)).fetchone()
        if not row: raise HTTPException(404,'案件文件不存在')
        row = dict(row)
        info = case_info(row['case_id'])
        item = {'path':row['absolute_path'],**info}
        path = trusted_file(item)
        body=await request.json()
        values=dict(name=path.name,source='文书生成',category='document',purpose='case',status='completed',phase='已保存到案件文件夹',
            **info,path=str(path),destination=str(path),case_saved=True,received_bytes=path.stat().st_size,total_bytes=path.stat().st_size,completed_files=1)
        if body.get('identity'): return store.update(str(body['identity']),**values)
        return store.create(**values)

    @app.post('/api/download-center/court-jobs')
    async def start_court_job(request: Request):
        body = await request.json()
        all_files = body.get('kind')=='record'
        identity = int(body.get('id') or 0)
        if len(store.tasks)>=3: raise HTTPException(429,'正在下载的任务较多，请稍后重试')
        from .court_online_service import _active_account_id
        with get_db() as conn:
            if all_files:
                row = conn.execute('SELECT linked_case_id,title FROM case_manager_court_online_records WHERE id=? AND account_id=?',(identity,_active_account_id())).fetchone()
                count = conn.execute('SELECT COUNT(*) FROM case_manager_court_online_attachments WHERE record_id=?',(identity,)).fetchone()[0] if row else 0
            else:
                row = conn.execute('SELECT r.linked_case_id,a.filename FROM case_manager_court_online_attachments a JOIN case_manager_court_online_records r ON r.id=a.record_id WHERE a.id=? AND r.account_id=?',(identity,_active_account_id())).fetchone()
                count = 1
        if not row: raise HTTPException(404,'当前一张网账号中未找到该材料')
        info = case_info(row[0])
        item = store.create(name=row[1] or '法院送达材料',source='一张网',category='court',purpose='case',total_files=count,**info,is_batch=True,batch_title=row[1] or '法院送达材料',destination='获取批次：实际位置见文件明细')

        async def run():
            token = current_transfer.set({'id':item['id']})
            try:
                path = '/api/case-manager/court-online/records/{record_id}/download-all' if all_files else '/api/case-manager/court-online/attachments/{attachment_id}/download'
                endpoint = next(route.endpoint for route in app.routes if getattr(route,'path','')==path)
                result = await endpoint(identity)
                results = result.get('results') or [result]
                success, failed = 0, 0
                for file in results:
                    if not file.get('ok'):
                        failed+=1;continue
                    info = case_info(file.get('linked_case_id'))
                    store.create(name=file['filename'],source='一张网',category='court',purpose='case',status='completed',
                        **info,path=file['path'],destination=file['path'],case_saved=bool(file.get('saved_to_case')),parent_id=item['id'],received_bytes=file['size_bytes'],total_bytes=file['size_bytes'],completed_files=1)
                    success+=1
                store.update(item['id'],status='partial' if failed and success else 'completed' if success else 'failed',
                    completed_files=success,failed_files=failed,total_files=len(results),phase='法院材料获取完成',case_saved=bool(results) and all(f.get('saved_to_case') for f in results),
                    error='部分附件未下载，请打开一张网重新下载' if failed else '')
            except Exception as exc:
                store.update(item['id'],status='failed',error=str(exc.detail if isinstance(exc,HTTPException) else exc)[:1000])
            finally:
                current_transfer.reset(token)
        task=asyncio.create_task(run());store.tasks.add(task);task.add_done_callback(store.tasks.discard)
        return item

    @app.post('/api/download-center/mail-jobs')
    async def start_mail_job(request: Request):
        body = await request.json()
        account = str(body.get('account') or 'qq_mail')
        if account not in qq_mail_mcp.MAILBOX_CONFIGS: raise HTTPException(400,'无效邮箱账户')
        purpose = body.get('purpose')
        if purpose not in ('case','invoice','other'): raise HTTPException(400,'请选择附件用途')
        info = case_info(body.get('case_id') if purpose=='case' else 0, require_binding=purpose=='case')
        if purpose=='case' and (not info['case_id'] or body.get('confirmed') is not True): raise HTTPException(400,'请确认目标案件和绑定文件夹')
        if len(store.tasks)>=3: raise HTTPException(429,'正在下载的邮箱任务较多，请稍后重试')
        account_name = qq_mail_mcp.MAILBOX_CONFIGS[account]['label']
        uid = str(body.get('uid') or '')
        if not uid.isdigit(): raise HTTPException(400,'无效邮件编号')
        item = store.create(name=filename(body.get('subject') or '邮件附件'), source=account_name,
            category='invoice' if purpose=='invoice' else 'mail',purpose=purpose, **info, total_files=0,is_batch=True,batch_title=filename(body.get('subject') or '邮件附件'),
            phase='正在连接邮箱并读取附件', destination='发票归集目录' if purpose=='invoice' else '获取批次：实际位置见文件明细' if purpose=='case' else '应用暂存区')
        ids = [str(v) for v in (body.get('attachment_ids') or []) if str(v).isdigit()][:100]

        def run():
            try:
                def progress(**values): store.update(item['id'], **values)
                destination = qq_mail_mcp._collect_month_dir(account) if purpose=='invoice' else store.root / item['id']
                result = qq_mail_mcp.collect_attachments(uid, account=account, attachment_ids=ids,
                    destination_dir=destination, progress=progress, folder=str(body.get("folder") or "inbox"))
                saved_count, failures = 0, []
                for saved in result['saved']:
                    path = saved['path']
                    child_info = info
                    case_write_failed=False
                    if purpose=='case':
                        try:
                            stored = store_case_file(get_db, info['case_id'], 'mail_material', saved['filename'], Path(path).read_bytes(), source_type=account,
                                                     metadata={'mail_uid':uid,'download_id':item['id']})
                            path = stored['absolute_path']
                        except Exception as exc:
                            failures.append(str(exc.detail if isinstance(exc,HTTPException) else exc))
                            case_write_failed=True
                    store.create(name=saved['filename'],source=account_name,category='invoice' if purpose=='invoice' else 'mail',purpose=purpose,
                        **child_info,path=path,status='partial' if case_write_failed else 'completed',received_bytes=saved['size'],total_bytes=saved['size'],completed_files=1,
                        parent_id=item['id'], destination=path,case_saved=purpose=='case' and not case_write_failed, error=failures[-1] if case_write_failed else '')
                    saved_count += 1
                skipped = result.get('skipped') or []
                failed_count = len(failures)+len(skipped)
                store.update(item['id'],status='partial' if failed_count and saved_count else 'completed' if saved_count else 'failed',
                    phase='附件已保存' if saved_count and not failures else '附件已下载，案件保存待完成' if saved_count else '没有可保存的附件',completed_files=max(0,saved_count-len(failures)), failed_files=failed_count,case_saved=purpose=='case' and not failed_count and bool(saved_count),
                    error='；'.join(failures + ([f"{len(skipped)} 个附件未能保存"] if skipped else [])), result=result)
            except Exception as exc:
                store.update(item['id'],status='failed',error=str(exc.detail if isinstance(exc,HTTPException) else exc)[:1000])

        task = asyncio.create_task(in_thread(run))
        store.tasks.add(task); task.add_done_callback(store.tasks.discard)
        return item
