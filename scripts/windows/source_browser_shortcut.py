"""Read and write the browser shortcut through the Unicode Windows Shell API."""
import argparse
import json
import os
from pathlib import Path
import subprocess

import pythoncom
from win32com.shell import shell


def read_shortcut(shortcut):
    # IShellLink.GetPath also returns a WIN32_FIND_DATA tuple.
    target, _ = shortcut.GetPath(0)
    return {
        'target': target,
        'arguments': shortcut.GetArguments(),
        'root': shortcut.GetWorkingDirectory(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('create', 'verify', 'read'))
    parser.add_argument('link', type=Path)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = args.root.resolve()
    runtime = Path(os.environ['LOCALAPPDATA']) / 'StellaSource'
    target = root / '.venv' / 'Scripts' / 'python.exe'
    arguments = subprocess.list2cmdline([
        str(root / 'scripts' / 'windows' / 'source_server.py'),
        '--runtime', str(runtime), '--open-browser',
    ])
    shortcut = pythoncom.CoCreateInstance(
        shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink,
    )
    persist = shortcut.QueryInterface(pythoncom.IID_IPersistFile)
    if args.link.exists() or args.action != 'create':
        persist.Load(str(args.link))
        existing = read_shortcut(shortcut)
        if args.action == 'read':
            print(json.dumps(existing))
        elif (Path(existing['target']) != target or Path(existing['root']) != root
              or existing['arguments'] != arguments):
            parser.exit(1, '桌面快捷方式属于其他安装，请先核对原有入口。\n')
        return
    shortcut.SetPath(str(target))
    shortcut.SetArguments(arguments)
    shortcut.SetWorkingDirectory(str(root))
    shortcut.SetIconLocation(str(root / 'windows-installer' / 'src-tauri' / 'icons' / 'icon.ico'), 0)
    shortcut.SetDescription('Stella 源码工作空间（浏览器）')
    persist.Save(str(args.link), True)


if __name__ == '__main__':
    main()
