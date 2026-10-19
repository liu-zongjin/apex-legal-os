"""User-managed generated outputs; no business sources outside outputs are eligible."""
import datetime
import hashlib
import os
from pathlib import Path


def export_path(root, name):
    root = Path(root)
    if root.is_symlink():
        raise ValueError('不能操作符号链接目录')
    root = root.resolve()
    value = Path(name)
    if value.is_absolute() or not value.parts or any(p in {'.', '..'} for p in value.parts):
        raise ValueError('无效的导出文件路径')
    path = root / value
    if any(root.joinpath(*value.parts[:i]).is_symlink() for i in range(len(value.parts) + 1)):
        raise ValueError('不能操作符号链接')
    if not path.is_file() or path.resolve() != path.absolute():
        raise ValueError('文件已不存在或路径已改变，请刷新')
    return path


def file_revision(path):
    s = path.stat()
    return hashlib.sha256(f'{s.st_dev}:{s.st_ino}:{s.st_size}:{s.st_mtime_ns}:{s.st_ctime_ns}'.encode()).hexdigest()


def export_inventory(root):
    root = Path(root)
    if root.is_symlink():
        return []
    root = root.resolve()
    files = []
    for base, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(base) / d).is_symlink())
        for name in names:
            try:
                path = export_path(root, (Path(base) / name).relative_to(root).as_posix())
                # Match the storage overview, which excludes OS metadata.
                if name in {'.DS_Store', 'Thumbs.db', 'desktop.ini'}:
                    continue
                stat = path.stat()
                relative = path.relative_to(root).as_posix()
                first = relative.split('/')[0]
                if first.startswith(('public-', 'previous-public')):
                    purpose = '公开版打包、发布与验证产物'
                elif 'series-export' in first:
                    purpose = '系列案件导出产物'
                elif path.suffix.lower() in {'.log', '.png', '.jpg', '.json', '.cjs', '.py'} or 'style' in first:
                    purpose = '开发验收、截图与检查记录'
                else:
                    purpose = '其它生成文件（请核对后清理）'
                files.append({'name': relative, 'group': first if '/' in relative else '根目录文件',
                              'purpose': purpose, 'size': stat.st_size,
                              'modified': datetime.datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                              'revision': file_revision(path)})
            except (OSError, ValueError):
                continue
    return sorted(files, key=lambda f: (-f['size'], f['name']))


def delete_exports(root, entries):
    root = Path(root)
    if root.is_symlink():
        raise ValueError('不能操作符号链接目录')
    root = root.resolve()
    if not isinstance(entries, list) or not entries or len(entries) > 200:
        raise ValueError('每次请选择 1 至 200 个文件')
    selected = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get('name'), str):
            raise ValueError('文件选择格式不正确')
        path = export_path(root, entry['name'])
        if file_revision(path) != entry.get('revision'):
            raise ValueError('文件已更新，请刷新列表后重新选择')
        selected[path] = entry['revision']
    freed, errors = 0, []
    for path, revision in selected.items():
        try:
            path = export_path(root, path.relative_to(root).as_posix())
            if file_revision(path) != revision:
                raise ValueError('文件已更新')
            size = path.stat().st_size
            path.unlink()
            freed += size
        except (OSError, ValueError):
            errors.append(path.name)
    return freed, errors
