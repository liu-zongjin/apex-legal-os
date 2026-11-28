#!/usr/bin/env python3
"""Read-only source-app discovery and update diagnostics; optional patch export."""
import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys
from urllib.parse import unquote, urlparse

BUNDLE_ID = 'com.stella.source.native'


def run(args, timeout=15):
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, timeout=timeout, check=True).stdout


def app_info(path):
    try:
        with (path / 'Contents' / 'Info.plist').open('rb') as stream:
            info = plistlib.load(stream)
        if info.get('CFBundleIdentifier') == BUNDLE_ID:
            return info.get('StellaSourceRoot', '(未设置)')
    except (OSError, ValueError, plistlib.InvalidFileException):
        pass
    return None


def dock_apps():
    path = Path.home() / 'Library/Preferences/com.apple.dock.plist'
    try:
        with path.open('rb') as stream:
            dock = plistlib.load(stream)
        for tile in dock.get('persistent-apps', []):
            url = tile.get('tile-data', {}).get('file-data', {}).get('_CFURLString', '')
            parsed = urlparse(url)
            if parsed.scheme == 'file':
                yield Path(unquote(parsed.path))
    except (OSError, ValueError, plistlib.InvalidFileException):
        return


def main():
    parser = argparse.ArgumentParser(description='发现源码客户端并检查端口；不停止进程或更改应用。')
    parser.add_argument('--app', type=Path, help='检查指定应用对应的源码')
    parser.add_argument('--patch-dir', type=Path, help='新建私有目录，导出已跟踪文件的差异与状态清单')
    args = parser.parse_args()
    if args.patch_dir and not args.app:
        parser.error('--patch-dir 需要 --app')
    dock = list(dock_apps())
    try:
        indexed = [Path(p) for p in run(['mdfind', "kMDItemCFBundleIdentifier == 'com.stella.source.native'"]).splitlines()]
    except (OSError, subprocess.SubprocessError):
        indexed = []
        print('无法读取 Spotlight 索引；请结合 Dock 和运行中的应用手动确认。')
    candidates = dock + indexed + [Path.home() / 'Applications/Stella Source.app']
    if args.app:
        candidates.insert(0, args.app.expanduser())
    print('发现的 Stella Source 应用（Spotlight 可能不完整）：')
    seen = set()
    for candidate in candidates:
        key = os.path.normpath(str(candidate))
        if key in seen:
            continue
        seen.add(key)
        root = app_info(candidate)
        if root is not None:
            print(f'  {candidate}  源码：{root}' + ('  [Dock]' if candidate in dock else ''))
    print('\n18866 端口监听者（PID、父 PID、启动时间、完整命令行）：')
    try:
        result = subprocess.run(['lsof', '-nP', '-iTCP:18866', '-sTCP:LISTEN', '-t'],
                                capture_output=True, text=True, timeout=15)
        if result.returncode not in (0, 1):
            print('  无法检查监听者：', result.stderr.strip())
        elif not result.stdout.strip():
            print('  未发现监听者（权限限制可能影响结果）。')
        for pid in sorted(set(result.stdout.split())):
            if pid.isdigit():
                print(run(['ps', '-ww', '-p', pid, '-o', 'pid=,ppid=,lstart=,command=']).rstrip())
    except (OSError, subprocess.SubprocessError) as exc:
        print(f'  检查失败：{exc}')
    if not args.app:
        print('\n明确用户实际启动的应用后，用 --app "应用路径" 检查其源码。')
        return 0
    root = app_info(args.app.expanduser())
    if not root or root == '(未设置)':
        print('指定应用不是有效的 Stella Source 应用，或未设置源码目录。', file=sys.stderr)
        return 1
    try:
        root = str(Path(root).expanduser().resolve(strict=True))
        status = run(['git', '-C', root, 'status', '--porcelain', '--untracked-files=all'])
        revision = run(['git', '-C', root, 'rev-parse', '--verify', 'HEAD']).strip()
        print(f'\n指定应用源码：{root}\n当前提交：{revision}\n未提交变更：')
        print(status if status else '  无', end='\n' if not status else '')
        if args.patch_dir:
            # Do not create an apparently successful export if Git fails.
            def git_diff(*args):
                return subprocess.run(['git', '-C', root, 'diff', '--binary', *args, '--'],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, check=True).stdout
            diff = git_diff('HEAD')
            staged = git_diff('--cached', 'HEAD')
            unstaged = git_diff()
            dest = args.patch_dir.expanduser()
            dest.mkdir(mode=0o700, parents=False, exist_ok=False)
            for name, content in [('tracked-changes.patch', diff), ('staged.patch', staged),
                                  ('unstaged.patch', unstaged), ('status.txt', status.encode('utf-8')),
                                  ('source-root.txt', (root + '\n').encode('utf-8'))]:
                fd = os.open(str(dest / name), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(content)
            print(f'已导出补丁及清单至 {dest}。未跟踪和被忽略的文件未包含在补丁中；请保留旧源码。')
    except (OSError, subprocess.SubprocessError) as exc:
        print(f'源码检查或导出失败：{exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
