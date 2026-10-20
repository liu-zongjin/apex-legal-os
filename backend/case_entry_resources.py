"""Attachments saved atomically with case ledger/memo text; local sources stay in place."""
import json
import logging
import re
import shutil
import subprocess
from .platform_files import run as run_desktop, has_picker
import uuid
from pathlib import Path
from contextlib import closing

from fastapi import HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from .matter_local_links import local, path_info

TABLES = {'ledgers': 'research_case_ledgers', 'memo-entries': 'research_case_memo_entries'}
MAX_FILE = 50 * 1024 * 1024
MAX_TOTAL = 100 * 1024 * 1024
MAX_ITEMS = 40


def table_for(kind):
    if kind not in TABLES:
        raise HTTPException(404, '记录类型不存在')
    return TABLES[kind]


def entry(conn, kind, entry_id):
    row = conn.execute(f'SELECT * FROM {table_for(kind)} WHERE id=?', (entry_id,)).fetchone()
    if not row:
        raise HTTPException(404, '记录不存在')
    return dict(row)


def resources(row):
    return json.loads(row.get('resources_json') or '[]')


def upload_path(root, resource):
    identifier = str(resource.get('id', ''))
    if not re.fullmatch(r'[a-f0-9]{32}', identifier):
        raise HTTPException(400, '附件标识无效')
    return root / identifier


def discard_uploads(root, items):
    for item in items:
        if item['kind'] == 'upload':
            try:
                upload_path(root, item).unlink(missing_ok=True)
            except OSError:
                logging.getLogger(__name__).warning('Could not remove detached case-entry upload %s', item['id'])


def register_routes(app, get_db, root, save_entry, payload_class):
    root = Path(root)

    @app.get('/api/case-research/{entry_kind}/{entry_id}/resources')
    def list_resources(entry_kind: str, entry_id: int, request: Request):
        with closing(get_db()) as conn:
            items = resources(entry(conn, entry_kind, entry_id))
        try:
            local(request)
            desktop = True
        except HTTPException:
            desktop = False
        result = []
        for value in items:
            item = dict(value)
            if item['kind'] == 'upload':
                item['exists'] = upload_path(root, item).is_file()
            elif desktop:
                path = Path(item['path'])
                item['exists'] = path.is_dir() if item['kind'] == 'folder' else path.is_file()
            else:
                item.pop('path', None)
                item['exists'] = False
            result.append(item)
        return {'items': result, 'local_available': desktop}

    @app.post('/api/case-research/projects/{project_id}/resources/select')
    def select_resource(project_id: int, request: Request, kind: str = 'file'):
        local(request)
        with closing(get_db()) as conn:
            if not conn.execute('SELECT 1 FROM research_projects WHERE id=?', (project_id,)).fetchone():
                raise HTTPException(404, '案件研究不存在')
        if kind not in ('file', 'folder'):
            raise HTTPException(400, '请选择文件或文件夹')
        if not has_picker():
            raise HTTPException(501, '当前系统不支持本地选择器')
        try:
            result = run_desktop(['osascript', '-e', f'POSIX path of (choose {kind} with prompt "选择记录关联的文件或文件夹")'],
                                    capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            raise HTTPException(408, '选择超时，请重试')
        if result.returncode:
            if '-128' in result.stderr:
                return {'cancelled': True}
            raise HTTPException(400, '选择失败，请重试')
        path = path_info(result.stdout)
        return {'path': str(path), 'name': path.name, 'kind': 'folder' if path.is_dir() else 'file'}

    async def save(project_id, entry_kind, entry_id, request):
        table = table_for(entry_kind)
        with closing(get_db()) as conn:
            if entry_id:
                old_row = entry(conn, entry_kind, entry_id)
                project_id = old_row['project_id']
            else:
                old_row = {'resources_json': '[]'}
            if not conn.execute('SELECT 1 FROM research_projects WHERE id=?', (project_id,)).fetchone():
                raise HTTPException(404, '案件研究不存在')
        old = resources(old_row)
        added = []
        try:
            async with request.form(max_files=MAX_ITEMS, max_fields=10) as form:
                try:
                    data = json.loads(form.get('payload', '{}'))
                    payload = payload_class(**data)
                    keep = data.get('keep_resource_ids', [])
                    paths = data.get('local_paths', [])
                    if (not isinstance(keep, list) or any(not isinstance(value, str) for value in keep)
                            or not isinstance(paths, list) or any(not isinstance(value, str) for value in paths)):
                        raise ValueError()
                    files = form.getlist('files')
                    if any(not isinstance(file, UploadFile) and not hasattr(file, 'filename') for file in files):
                        raise ValueError()
                except (ValueError, TypeError):
                    raise HTTPException(400, '记录或附件数据无效')
                if entry_id and data.get('base_updated_at') is not None and data['base_updated_at'] != old_row['updated_at']:
                    raise HTTPException(409, '记录已被修改，请重新打开后编辑')
                old_by_id = {item['id']: item for item in old}
                if any(identifier not in old_by_id for identifier in keep):
                    raise HTTPException(409, '附件已变化，请重新打开记录')
                kept = [item for item in old if item['id'] in keep]
                if len(kept) + len(paths) + len(files) > MAX_ITEMS:
                    raise HTTPException(400, '每条记录最多添加 40 个文件或文件夹')
                # Removing local metadata also requires a local session.
                if paths or any(item['kind'] != 'upload' and item['id'] not in keep for item in old):
                    local(request)
                known_paths = {item.get('path') for item in kept}
                for value in paths:
                    path = path_info(value)
                    if str(path) in known_paths:
                        continue
                    known_paths.add(str(path))
                    added.append({'id': uuid.uuid4().hex, 'kind': 'folder' if path.is_dir() else 'file',
                                  'path': str(path), 'name': path.name or str(path)})
                total = 0
                for file in files:
                    item = {'id': uuid.uuid4().hex, 'kind': 'upload',
                            'name': str(file.filename or '未命名附件').replace('\\', '/').split('/')[-1][:255], 'size': 0}
                    root.mkdir(parents=True, exist_ok=True)
                    added.append(item)
                    with upload_path(root, item).open('xb') as target:
                        while chunk := await file.read(1024 * 1024):
                            item['size'] += len(chunk)
                            total += len(chunk)
                            if item['size'] > MAX_FILE or total > MAX_TOTAL:
                                raise HTTPException(413, '单个文件最多 50 MB，本次上传总计最多 100 MB')
                            target.write(chunk)
                updated = kept + added
                saved = save_entry(table, project_id, payload, entry_id,
                                   resource_edit=(json.dumps(updated, ensure_ascii=False), old_row.get('updated_at')))
        except Exception:
            discard_uploads(root, added)
            raise
        discard_uploads(root, [item for item in old if item['id'] not in keep])
        return saved

    @app.post('/api/case-research/projects/{project_id}/{entry_kind}/with-resources')
    async def create_with_resources(project_id: int, entry_kind: str, request: Request):
        return await save(project_id, entry_kind, 0, request)

    @app.put('/api/case-research/{entry_kind}/{entry_id}/with-resources')
    async def update_with_resources(entry_kind: str, entry_id: int, request: Request):
        return await save(0, entry_kind, entry_id, request)

    def owned_resource(entry_kind, entry_id, resource_id):
        with closing(get_db()) as conn:
            items = resources(entry(conn, entry_kind, entry_id))
        item = next((item for item in items if item['id'] == resource_id), None)
        if not item:
            raise HTTPException(404, '附件或绑定不存在')
        return item

    @app.get('/api/case-research/{entry_kind}/{entry_id}/resources/{resource_id}/download')
    def download_resource(entry_kind: str, entry_id: int, resource_id: str):
        item = owned_resource(entry_kind, entry_id, resource_id)
        if item['kind'] != 'upload':
            raise HTTPException(400, '本地绑定请在本机打开')
        path = upload_path(root, item)
        if not path.is_file():
            raise HTTPException(404, '附件已不存在')
        return FileResponse(path, filename=item['name'], media_type='application/octet-stream')

    @app.post('/api/case-research/{entry_kind}/{entry_id}/resources/{resource_id}/open')
    def open_resource(entry_kind: str, entry_id: int, resource_id: str, request: Request):
        local(request)
        item = owned_resource(entry_kind, entry_id, resource_id)
        if item['kind'] == 'upload':
            raise HTTPException(400, '请使用附件下载入口')
        path = path_info(item['path'])
        if ('folder' if path.is_dir() else 'file') != item['kind']:
            raise HTTPException(409, '原位置类型已改变，请重新绑定')
        if not shutil.which('open'):
            raise HTTPException(501, '当前系统不支持打开本地文件')
        try:
            run_desktop(['open', '--', str(path)], check=True, capture_output=True, timeout=15)
        except (subprocess.SubprocessError, OSError):
            raise HTTPException(500, '打开失败，请检查文件权限或默认应用')
        return {'ok': True}
