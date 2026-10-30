"""Conservatively reclaim unchanged, retired source-update virtual environments."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import uuid

NAME = re.compile(r'candidate-[0-9a-f]{32}\Z')
REPARSE_POINT = 0x400


def ordinary(path):
    info = path.lstat()
    return not (stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & REPARSE_POINT)


def candidate_path(versions, name):
    if not NAME.fullmatch(name) or not ordinary(versions):
        raise ValueError('invalid versions directory or candidate')
    candidate = versions / name
    if not ordinary(candidate) or not candidate.is_dir():
        raise ValueError('candidate is not an ordinary directory')
    return candidate


def inventory(directory):
    if not ordinary(directory) or not directory.is_dir():
        raise ValueError('environment is not an ordinary directory')
    items = {}
    def visit(folder):
        with os.scandir(folder) as entries:
            paths = [Path(item.path) for item in entries]
        for path in paths:
            info = path.lstat()
            if not ordinary(path):
                raise ValueError('environment contains a link or reparse point')
            relative = path.relative_to(directory).as_posix()
            if stat.S_ISDIR(info.st_mode):
                items[relative] = 'directory'
                visit(path)
            elif stat.S_ISREG(info.st_mode):
                digest = hashlib.sha256()
                with path.open('rb') as source:
                    for block in iter(lambda: source.read(1024 * 1024), b''):
                        digest.update(block)
                items[relative] = digest.hexdigest()
            else:
                raise ValueError('environment contains a special file')
    visit(directory)
    return items


def record(versions, runtime, name):
    env = candidate_path(versions, name) / '.venv'
    files = inventory(env)
    manifests = runtime / 'source-environment-inventories'
    manifests.mkdir(parents=True, exist_ok=True)
    if not ordinary(manifests):
        raise ValueError('inventory directory is a link')
    destination = manifests / (name + '.json')
    if destination.exists() or destination.is_symlink():
        raise ValueError('inventory already exists')
    temporary = manifests / (uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps({'version': 1, 'candidate': name, 'files': files},
                                        ensure_ascii=True, sort_keys=True), encoding='utf-8')
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def prune(versions, runtime, current, previous):
    manifests = runtime / 'source-environment-inventories'
    if not manifests.exists() or not ordinary(manifests):
        return []
    removed = []
    for manifest in manifests.glob('candidate-*.json'):
        name = manifest.stem
        if name in (current, previous) or not NAME.fullmatch(name):
            continue
        try:
            if not ordinary(manifest) or not manifest.is_file():
                continue
            data = json.loads(manifest.read_text(encoding='utf-8'))
            if data.get('version') != 1 or data.get('candidate') != name or not isinstance(data.get('files'), dict):
                continue
            env = candidate_path(versions, name) / '.venv'
            if inventory(env) != data['files']:
                continue
            shutil.rmtree(env)
            manifest.unlink()
            removed.append(name)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            # Unknown or modified files always win over reclaiming space.
            continue
    return removed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('record', 'prune'))
    parser.add_argument('--versions', type=Path, required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--current', required=True)
    parser.add_argument('--previous', default='')
    args = parser.parse_args()
    if args.action == 'record':
        record(args.versions, args.runtime, args.current)
    else:
        print('Retired unchanged environments removed: ' + str(len(prune(
            args.versions, args.runtime, args.current, args.previous))))


if __name__ == '__main__':
    main()
