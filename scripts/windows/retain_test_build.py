"""Private CI transport for an owner-requested test; never signs or publishes releases."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def git(*args, data=None):
    return subprocess.check_output(['git', *args], cwd=ROOT, input=data).decode().strip()


def retain(branch, items):
    entries = []
    for name, data in items:
        sha = git('hash-object', '-w', '--stdin', data=data)
        entries.append(f'100644 blob {sha}\t{name}')
    tree = git('mktree', data=('\n'.join(sorted(entries))+'\n').encode())
    ref = 'refs/stella-test/' + branch.rsplit('/', 1)[-1]
    previous = subprocess.run(['git', 'rev-parse', '--verify', ref], cwd=ROOT, capture_output=True, text=True)
    parent = ['-p', previous.stdout.strip()] if previous.returncode == 0 else []
    commit = git('-c', 'user.name=Stella CI', '-c', 'user.email=ci@example.invalid',
                 'commit-tree', tree, *parent, data=b'Private Windows test build\n')
    git('update-ref', ref, commit)
    subprocess.run(['git', '-c', 'pack.window=0', '-c', 'pack.compression=0', 'push', 'origin',
                    commit+':refs/heads/'+branch], cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase')
    args = parser.parse_args()
    run = os.environ['GITHUB_RUN_ID']
    info = {'source': os.environ['GITHUB_SHA'], 'run': run, 'phase': args.phase,
            'test_only': True, 'public_release': False}
    if args.phase == 'complete':
        from make_catalog import pack_component
        output = ROOT / 'build/test-setup'
        output.mkdir(parents=True, exist_ok=True)
        server = pack_component('server', ROOT / 'build/windows-components/server', output,
                                'https://liu-zongjin.github.io/stella-downloads/windows/private-test')
        (output / 'server-component.json').write_text(json.dumps(server), encoding='utf-8')
        import shutil
        installers = list((ROOT/'windows-installer/src-tauri/target/release/bundle/nsis').glob('*.exe'))
        assert len(installers) == 1 and installers[0].stat().st_size < 50_000_000
        shutil.copyfile(installers[0], output/'Stella-Windows-1.1.7-test.1-setup.exe')
        shutil.copyfile(ROOT/'windows-installer/src-tauri/resources/bootstrap-engine.exe', output/'bootstrap-engine.exe')
        for name in ('windows-build.log', 'windows-smoke-result.json', 'windows-smoke.log'):
            shutil.copyfile(ROOT/'build'/name, output/name)
        (output/'BUILD-INFO.json').write_text(json.dumps(info), encoding='utf-8')
        with tempfile.TemporaryDirectory(prefix='stella-test-transport-') as directory:
            archive = Path(directory)/'test-build.tar'
            with tarfile.open(archive, 'w') as target:
                for path in sorted(output.iterdir()):
                    target.add(path, arcname=path.name, recursive=False)
            parts, items = [], []
            with archive.open('rb') as stream:
                while True:
                    data = stream.read(40 * 1024 * 1024)
                    if not data:
                        break
                    name = f'part-{len(parts):03}'
                    parts.append({'name': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
                    items.append((name, data))
            manifest = dict(info, parts=parts, archive_bytes=archive.stat().st_size,
                            archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
            items.append(('manifest.json', json.dumps(manifest).encode()))
            retain('ci/windows-startup-test-'+run, items)
    logs = [('BUILD-STATUS.json', json.dumps(info).encode())]
    for path in (ROOT/'build').glob('windows-*.log'):
        logs.append((path.name, '\n'.join(path.read_text(encoding='utf-8', errors='replace').splitlines()[-100:]).encode()))
    retain('ci/windows-test-status-'+run, logs)


if __name__ == '__main__':
    main()
