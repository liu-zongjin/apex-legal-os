"""Verify a staged environment is still eligible for future safe cleanup."""
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.windows.source_storage import clean_source, inventory

root, manifest = map(Path, sys.argv[1:])
if not clean_source(root):
    for args in (['rev-parse', '--show-toplevel'], ['status', '--porcelain', '--untracked-files=all']):
        result = subprocess.run(['git', '--no-optional-locks', '-C', str(root), *args],
                                text=True, capture_output=True, timeout=30)
        print('git', args[0], 'exit:', result.returncode, 'output:', result.stdout, 'error:', result.stderr, flush=True)
    raise RuntimeError('Normal client use changed the source checkout')
expected = json.loads(manifest.read_text(encoding='utf-8'))['files']
actual = inventory(root / '.venv')
if actual != expected:
    changed = sorted(key for key in set(actual) | set(expected) if actual.get(key) != expected.get(key))
    raise RuntimeError('Normal client use changed the recorded environment: ' + repr(changed[:20]))
print('Source and environment remain eligible for future cleanup.')
