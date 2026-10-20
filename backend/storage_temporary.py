"""Explain development temporary artifacts; delete only explicit, unchanged selections."""
from pathlib import Path
import hashlib
import os
import re
import shutil
import subprocess

_BUILD = re.compile(r"public-update-package-\d{8}(?:-(?:r\d+|final))?$")
_PROTECTED_SUFFIXES = {'.db', '.sqlite', '.sqlite3', '.sql', '.bak', '.pem', '.key', '.p12', '.pfx'}


def _snapshot(path):
    """No symlink traversal; fingerprint names and metadata, never private contents."""
    nodes = [path]
    if path.is_dir() and not path.is_symlink():
        for parent, dirs, files in os.walk(path, followlinks=False):
            nodes.extend(Path(parent) / name for name in dirs + files)
    digest = hashlib.sha256()
    size = count = 0
    protected = False
    for node in sorted(nodes):
        st = node.lstat()
        rel = node.relative_to(path).as_posix()
        digest.update(repr((rel, st.st_mode, st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_ino)).encode())
        if node.is_symlink():
            # Framework symlinks are normal, but never follow an external target.
            try:
                node.resolve().relative_to(path.resolve())
            except (ValueError, RuntimeError):
                protected = True
        elif node.is_file():
            size += st.st_size
            count += 1
            if ((node.suffix.lower() in _PROTECTED_SUFFIXES and not rel.endswith('Stella.app/Contents/Resources/Server/_internal/certifi/cacert.pem')) or node.name.startswith('.env')
                    or any(word in node.name.lower() for word in ('credential', 'secret', 'backup'))
                    or any(part in {'uploads', 'article_images', 'history_backups', 'schema_backups'} for part in Path(rel).parts)
                    or node.name.endswith(('-wal', '-shm', '-journal'))):
                protected = True
    return digest.hexdigest(), size, count, protected


def inventory(root, counted_files):
    """Rows sum exactly to the existing temp_files category, not other categories."""
    tmp = root / '.tmp'
    if tmp.is_symlink() or not tmp.is_dir():
        return []
    grouped = {}
    for record in counted_files:
        parts = Path(record['name']).parts
        if len(parts) >= 2 and parts[0] == '.tmp':
            group = grouped.setdefault(parts[1], {'size': 0, 'count': 0})
            group['size'] += record['size']
            group['count'] += 1
    builds = [name for name in grouped if _BUILD.fullmatch(name)]
    latest = max(builds, key=lambda name: (re.search(r'\d{8}', name).group(), name.endswith('-final'), (tmp/name).stat().st_mtime_ns), default='')
    rows = []
    for name, totals in grouped.items():
        path = tmp / name
        try:
            revision, disk_size, disk_count, protected = _snapshot(path)
            updated = path.stat().st_mtime
        except OSError:
            continue
        group, title, advice, impact, level = (
            'unconfirmed', '用途待确认', '建议保留：用途尚未确认，不提供直接删除。',
            '仅放在临时目录不能证明可安全删除；先确认文件来源。', 'keep')
        if _BUILD.fullmatch(name) and path.is_dir() and (path/'Stella.app').is_dir():
            group, title = 'build', '应用打包副本'
            level = 'optional' if name == latest else 'priority'
            advice = ('建议暂留：这是当前目录中最新的候选包，完成发布或验收后再清理。' if name == latest
                      else '优先清理：旧轮次打包副本；确认无需测试或分发该版本后可删除。')
            impact = '删除本地应用副本和压缩包；不删除当前运行的 dist/Stella.app。再次使用需要重新打包。'
        elif re.fullmatch(r'(?:sparkle-[\d.]+|Sparkle-[\d.]+\.tar\.xz|sparkle-integration(?:-final)?)', name):
            group, title, level = 'update_tools', '自动更新工具与测试', 'optional'
            advice = '按需清理：近期不做打包或更新测试时可以删除。'
            impact = '后续打包需重新下载、校验或生成；不会删除钥匙串中的发布签名私钥。'
        elif (path.is_dir() and (name in {'document-branding-ui', 'system-messages-ui', 'unified-settings-ui', 'public-native-compile', 'native-private-check', 'filing-duplicate-fix'})
              or re.fullmatch(r'(?:admin|login)-(?:1024|1440)-(?:light|dark)\.png', name)):
            group, title, level = 'verification', '界面验收与编译测试', 'optional'
            advice = '按需清理：已验收且无需保留排障记录后可删除。'
            impact = '会丢失该项截图或测试产物；需要时重新运行验收或编译。'
        if protected:
            group, title, level = 'protected', '回滚、数据或敏感文件', 'keep'
            advice = '建议保留：发现数据库、SQL、备份或敏感文件，需单独核对。'
            impact = '可能用于恢复数据或保留配置，不纳入临时文件清理。'
        rows.append(dict(name='.tmp/' + name, title=title, group=group, recommendation=advice,
                         impact=impact, level=level, cleanable=level != 'keep', revision=revision,
                         modified_at=updated, disk_size=disk_size, disk_count=disk_count, **totals))
    return sorted(rows, key=lambda row: (-row['size'], row['name']))


def delete_selected(root, selections, current_rows):
    if not isinstance(selections, list) or not selections or len(selections) > 200:
        raise ValueError('请选择要清理的具体项目；不支持整目录清空')
    tmp = root / '.tmp'
    if tmp.is_symlink() or not tmp.is_dir():
        raise ValueError('临时目录已变化，请刷新后重试')
    allowed = {row['name']: row for row in current_rows}
    chosen = {}
    for selection in selections:
        if not isinstance(selection, dict):
            raise ValueError('清理项目格式不正确')
        name = selection.get('name')
        row = allowed.get(name) if isinstance(name, str) else None
        if not row or not row['cleanable'] or selection.get('revision') != row['revision']:
            raise ValueError('所选项目已变化或需保留，请刷新明细后重试')
        path = root / name
        if path.parent != tmp or path.is_symlink():
            raise ValueError('不能清理链接或临时目录以外的文件')
        chosen[name] = (path, row)
    # Fail closed if open-file inspection is unavailable. Never stop user tasks.
    try:
        probe = subprocess.run(['lsof', '-nP', '-Fn', '+D', str(tmp)], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError('无法确认临时文件是否正在使用，请稍后重试') from exc
    if probe.returncode not in (0, 1) or probe.stderr.strip():
        raise ValueError('无法完整确认文件使用情况，请稍后重试')
    opened = [Path(line[1:]) for line in probe.stdout.splitlines() if line.startswith('n')]
    for path, row in chosen.values():
        if any(p == path or path in p.parents for p in opened):
            raise ValueError('所选项目正在被程序使用，请结束相关任务后重试')
        revision, _, _, protected = _snapshot(path)
        if revision != row['revision'] or protected:
            raise ValueError('所选项目已变化，请刷新后重试')
    freed = 0
    errors = []
    for path, row in chosen.values():
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            freed += row['disk_size']
        except OSError:
            errors.append(row['name'])
    return freed, errors
