"""Narrow Windows replacements for existing macOS desktop file actions.

Only known choose/open/trash operations are translated. Arbitrary AppleScript
is never interpreted or executed on Windows. Callers retain ownership checks.
"""
from __future__ import annotations
import base64
import os
from pathlib import Path
import subprocess
import sys


def has_picker():
    import shutil
    return sys.platform == 'win32' or bool(shutil.which('osascript'))


def has_opener():
    import shutil
    return sys.platform == 'win32' or bool(shutil.which('open'))


def run(command, **kwargs):
    if sys.platform != 'win32' or not command or command[0] not in ('open', 'osascript'):
        return subprocess.run(command, **kwargs)
    if command[0] == 'open':
        args = [p for p in command[1:] if p not in ('--', '-R')]
        if len(args) != 1:
            raise OSError('不支持的文件操作')
        path = str(Path(args[0]).resolve(strict=True))
        if '-R' in command:
            return subprocess.run(['explorer.exe', '/select,' + path], creationflags=0x08000000, **kwargs)
        os.startfile(path)
        return subprocess.CompletedProcess(command, 0, stdout='', stderr='')
    script_index = command.index('-e') + 1
    script = command[script_index]
    if 'choose folder' in script or 'choose file' in script:
        kind = 'folder' if 'choose folder' in script else 'file'
        body = ('Add-Type -AssemblyName System.Windows.Forms;'
                '[Console]::OutputEncoding=[Text.UTF8Encoding]::new();')
        if kind == 'folder':
            body += '$d=New-Object System.Windows.Forms.FolderBrowserDialog;'
            result = '$d.SelectedPath'
        else:
            body += '$d=New-Object System.Windows.Forms.OpenFileDialog;'
            result = '$d.FileName'
        body += f'if($d.ShowDialog() -eq "OK"){{[Console]::Write({result})}}else{{exit 128}}'
        encoded = base64.b64encode(body.encode('utf-16le')).decode()
        kwargs.pop('text', None)
        kwargs.pop('encoding', None)
        kwargs.pop('capture_output', None)
        result = subprocess.run(['powershell.exe', '-NoProfile', '-STA', '-EncodedCommand', encoded],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=0x08000000, **kwargs)
        return subprocess.CompletedProcess(command, result.returncode, result.stdout.decode('utf-8-sig').strip(),
                                           '-128' if result.returncode == 128 else result.stderr.decode('utf-8-sig', errors='replace'))
    if 'Finder' in script and 'delete' in script:
        paths = command[script_index + 1:]
        if paths and paths[0] == '--':
            paths = paths[1:]
        if not paths:
            raise OSError('缺少回收站文件')
        trash(paths)
        return subprocess.CompletedProcess(command, 0, stdout='', stderr='')
    raise OSError('此系统操作不适用于 Windows')


def trash(paths):
    # Require the modern IFileOperation implementation and its recycle-only sink.
    # Never fall back to legacy SHFileOperation or unlink for unsupported volumes.
    resolved = [str(Path(p).resolve(strict=True)) for p in paths]
    if any(p.startswith('\\\\') for p in resolved):
        raise OSError('共享文件夹不支持此回收站操作，请在资源管理器中处理')
    try:
        from send2trash.win.modern import send2trash
    except ImportError as exc:
        raise OSError('回收站组件不可用，请修复安装') from exc
    send2trash(resolved)
