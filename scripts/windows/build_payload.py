"""Freeze Windows payload from the same audited Git snapshot as Mac packaging.

Development builds only. This never uploads assets or edits a live runtime.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'win32':
        raise SystemExit('Windows payloads must be built on Windows')
    spec = importlib.util.spec_from_file_location('shared_public_snapshot', ROOT / 'scripts/build_private_preview.py')
    shared = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shared)
    output = args.output.resolve()
    if output.exists():
        raise SystemExit('Use a fresh isolated output directory')
    with tempfile.TemporaryDirectory(prefix='stella-windows-source-') as directory:
        stage = Path(directory) / 'source'
        stage.mkdir()
        shared.isolated_source(ROOT, stage, profile='windows')
        for name in ('server_entry.py', 'bootstrap_engine.py'):
            shutil.copyfile(ROOT / 'scripts/windows' / name, stage / name)
        shutil.copyfile(ROOT / 'scripts/distribution/preview_entry.py', stage / 'preview_entry.py')
        command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
                   '--name', 'StellaServer', '--distpath', str(Path(directory) / 'dist'),
                   '--workpath', str(Path(directory) / 'build'), '--specpath', directory,
                   '--paths', str(stage), '--add-data', f'{stage / "frontend"};frontend',
                   '--add-data', f'{stage / "backend"};backend', '--collect-submodules', 'backend',
                   '--collect-all', 'jieba', '--collect-all', 'ddddocr', '--collect-all', 'onnxruntime',
                   '--collect-all', 'psutil', '--collect-all', 'playwright',
                   '--hidden-import', 'uvicorn.logging', '--hidden-import', 'uvicorn.loops.asyncio',
                   '--hidden-import', 'uvicorn.protocols.http.h11_impl', '--hidden-import', 'uvicorn.lifespan.on']
        for module in ('torch', 'tensorflow', 'matplotlib', 'scipy', 'backend.recording_routes',
                       'backend.recording_asr', 'backend.feishu_article_sync', 'backend.feishu_family_finance_sync'):
            command.extend(['--exclude-module', module])
        env = dict(os.environ)
        env.pop('PYTHONPATH', None)
        for key in list(env):
            if key.endswith(('_API_KEY', '_API_SECRET', '_ACCESS_TOKEN', '_AUTH_CODE', '_AUTHORIZATION', '_WEB_COOKIE')):
                env.pop(key, None)
        subprocess.run([*command, str(stage / 'server_entry.py')], cwd=stage, env=env, check=True)
        payload = Path(directory) / 'dist/StellaServer'
        for source in (payload / '_internal/backend').rglob('*.py'):
            source.unlink()
        for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md'):
            shutil.copyfile(ROOT / name, payload / name)
        shutil.copytree(ROOT / 'third_party', payload / 'third_party')
        shared.audit_bundle(payload)
        shutil.copytree(payload, output)


if __name__ == '__main__':
    main()
