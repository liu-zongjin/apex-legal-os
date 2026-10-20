"""Local shortcuts owned by individual case reminders; never copy source files."""
from pathlib import Path
from urllib.parse import urlsplit
import shutil
import subprocess
from .platform_files import run as run_desktop, has_picker, has_opener

from fastapi import HTTPException, Request
from .security import is_loopback_client

KINDS = {kind: ('case_manager_' + kind, column) for kind, column in (
    ('todos', 'todo_id'), ('hearings', 'hearing_id'),
    ('preservations', 'preservation_id'), ('appeals', 'appeal_id'))}


def add_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS case_manager_matter_local_links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        todo_id INTEGER REFERENCES case_manager_todos(id) ON DELETE CASCADE,
        hearing_id INTEGER REFERENCES case_manager_hearings(id) ON DELETE CASCADE,
        preservation_id INTEGER REFERENCES case_manager_preservations(id) ON DELETE CASCADE,
        appeal_id INTEGER REFERENCES case_manager_appeals(id) ON DELETE CASCADE,
        path TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('file','folder')),
        CHECK((todo_id IS NOT NULL)+(hearing_id IS NOT NULL)+
              (preservation_id IS NOT NULL)+(appeal_id IS NOT NULL)=1))''')
    for _, column in KINDS.values():
        conn.execute(f'CREATE UNIQUE INDEX IF NOT EXISTS idx_matter_links_{column} '
                     f'ON case_manager_matter_local_links({column},path)')


def move_links(conn, matter_kind, old_id, new_id):
    """Reminder edits can replace their row ID; retain shortcuts atomically."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='case_manager_matter_local_links'").fetchone():
        return
    column = KINDS[matter_kind][1]
    conn.execute(f'INSERT OR IGNORE INTO case_manager_matter_local_links ({column},path,name,kind) '
                 f'SELECT ?,path,name,kind FROM case_manager_matter_local_links WHERE {column}=?',
                 (new_id, old_id))


def local(request):
    # Authentication remains owned by middleware, including private mode.
    # A reverse proxy also connects from loopback, so check its target and
    # forwarding headers before permitting desktop filesystem actions.
    peer = request.client.host if request.client else None
    forwarded = any(name in request.headers for name in
                    ('forwarded', 'x-forwarded-for', 'x-forwarded-host', 'x-forwarded-proto'))
    origin = request.headers.get('origin')
    local_origin = not origin or is_loopback_client(urlsplit(origin).hostname)
    if not (is_loopback_client(peer) and is_loopback_client(request.url.hostname)
            and local_origin and not forwarded):
        raise HTTPException(403, '请在本机 Stella 中管理和打开本地文件')

def path_info(value):
    raw = str(value or '').strip()
    if not raw or '\x00' in raw or len(raw) > 4096:
        raise HTTPException(400, '请填写有效的本地绝对路径')
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise HTTPException(400, '请填写本地绝对路径')
    try:
        path = path.resolve(strict=True)
    except (OSError, RuntimeError):
        raise HTTPException(400, '文件或文件夹不存在，请重新绑定')
    if not (path.is_file() or path.is_dir()):
        raise HTTPException(400, '请选择普通文件或文件夹')
    return path


def register_routes(app, get_db):
    def owner(conn, matter_kind, item_id):
        if matter_kind not in KINDS:
            raise HTTPException(404, '事项类型不存在')
        table, column = KINDS[matter_kind]
        if not conn.execute(f'SELECT 1 FROM {table} WHERE id=?', (item_id,)).fetchone():
            raise HTTPException(404, '事项不存在')
        return column

    @app.get('/api/case-manager/matters/{matter_kind}/{item_id}/local-links')
    def list_links(matter_kind: str, item_id: int, request: Request):
        local(request)
        with get_db() as conn:
            column = owner(conn, matter_kind, item_id)
            rows = conn.execute(f'SELECT id,path,name,kind FROM case_manager_matter_local_links '
                                f'WHERE {column}=? ORDER BY id', (item_id,)).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            path = Path(item['path'])
            item['exists'] = path.is_dir() if item['kind'] == 'folder' else path.is_file()
            items.append(item)
        return {'items': items}

    @app.post('/api/case-manager/matters/{matter_kind}/{item_id}/local-links/select')
    def select_link(matter_kind: str, item_id: int, request: Request, kind: str = 'file'):
        local(request)
        with get_db() as conn:
            owner(conn, matter_kind, item_id)
        if kind not in ('file', 'folder'):
            raise HTTPException(400, '请选择文件或文件夹')
        if not has_picker():
            raise HTTPException(501, '当前系统不支持选择器，请粘贴路径')
        script = f'POSIX path of (choose {kind} with prompt "选择事项关联的本地文件或文件夹")'
        try:
            result = run_desktop(['osascript', '-e', script], capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            raise HTTPException(408, '选择超时，请重试')
        if result.returncode:
            if '-128' in result.stderr:
                return {'cancelled': True}
            raise HTTPException(500, '选择失败，请粘贴路径重试')
        return {'path': str(path_info(result.stdout))}

    @app.post('/api/case-manager/matters/{matter_kind}/{item_id}/local-links')
    async def save_link(matter_kind: str, item_id: int, request: Request):
        local(request)
        body = await request.json()
        path = path_info(body.get('path'))
        with get_db() as conn:
            column = owner(conn, matter_kind, item_id)
            conn.execute(f'INSERT OR IGNORE INTO case_manager_matter_local_links '
                         f'({column},path,name,kind) VALUES (?,?,?,?)',
                         (item_id, str(path), path.name or str(path), 'folder' if path.is_dir() else 'file'))
            conn.commit()
        return {'ok': True}

    @app.post('/api/case-manager/matters/{matter_kind}/{item_id}/local-links/{link_id}/open')
    def open_link(matter_kind: str, item_id: int, link_id: int, request: Request):
        local(request)
        with get_db() as conn:
            column = owner(conn, matter_kind, item_id)
            row = conn.execute(f'SELECT path,kind FROM case_manager_matter_local_links '
                               f'WHERE {column}=? AND id=?', (item_id, link_id)).fetchone()
        if not row:
            raise HTTPException(404, '绑定不存在')
        path = path_info(row['path'])
        if ('folder' if path.is_dir() else 'file') != row['kind']:
            raise HTTPException(409, '绑定的文件类型已改变，请重新绑定')
        if not has_opener():
            raise HTTPException(501, '当前系统不支持打开本地文件')
        try:
            run_desktop(['open', '--', str(path)], check=True, capture_output=True, timeout=15)
        except (subprocess.SubprocessError, OSError):
            raise HTTPException(500, '打开失败，请检查文件权限或默认应用')
        return {'ok': True}

    @app.delete('/api/case-manager/matters/{matter_kind}/{item_id}/local-links/{link_id}')
    def remove_link(matter_kind: str, item_id: int, link_id: int, request: Request):
        local(request)
        with get_db() as conn:
            column = owner(conn, matter_kind, item_id)
            conn.execute(f'DELETE FROM case_manager_matter_local_links WHERE {column}=? AND id=?',
                         (item_id, link_id))
            conn.commit()
        return {'ok': True}
