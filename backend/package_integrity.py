"""Verify shipped resources and page routes against the actual frozen service."""
from __future__ import annotations
import ast
import hashlib
import importlib
import io
import json
import re
from pathlib import Path

MANIFEST = 'backend/packaged-resources.json'
RUNTIME_MODULES = ('xlrd', 'pypdf', 'pytesseract', 'psutil', 'docx', 'openpyxl', 'fitz', 'playwright.sync_api')


def verify_runtime_dependencies():
    for name in RUNTIME_MODULES:
        importlib.import_module(name)
    import fitz
    from pypdf import PdfReader
    document = fitz.open()
    page = document.new_page()
    page.insert_text((30, 30), 'Stella PDF dependency check')
    content = document.tobytes()
    document.close()
    if 'Stella PDF' not in PdfReader(io.BytesIO(content)).pages[0].extract_text():
        raise RuntimeError('PDF generation/extraction dependencies failed')
    return list(RUNTIME_MODULES)


def create_manifest(stage, profile):
    routes = {'/fada-wang'}
    for path in (stage / 'backend').glob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not any(isinstance(n, ast.Constant) and isinstance(n.value, str) and
                       '.html' in n.value for n in ast.walk(node)):
                continue
            for decorator in node.decorator_list:
                if not (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                        and decorator.func.attr == 'get' and decorator.args):
                    continue
                route = decorator.args[0]
                if (isinstance(route, ast.Constant) and isinstance(route.value, str) and
                        route.value.startswith('/') and not route.value.startswith('/api/') and
                        '{' not in route.value):
                    routes.add(route.value)
    if profile == 'windows':
        routes.discard('/recording')
    files = {}
    assets = set()
    for directory in ('frontend', 'fada-wang'):
        for path in (stage / directory).rglob('*'):
            if not path.is_file():
                continue
            files[path.relative_to(stage).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
            if path.suffix in ('.html', '.js', '.css'):
                text = path.read_text(encoding='utf-8')
                for asset in re.findall(r'/static/([A-Za-z0-9_./-]+\.(?:js|css|png|svg|ico|woff2?))', text):
                    assets.add('/static/' + asset)
    payload = {'profile': profile, 'pages': sorted(routes), 'assets': sorted(assets), 'files': files}
    (stage / MANIFEST).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return payload


def verify_package(client, resource_root):
    """No skipped missing pages: a bad artifact must fail its build."""
    root = Path(resource_root)
    manifest = json.loads((root / MANIFEST).read_text(encoding='utf-8'))
    for name, expected in manifest['files'].items():
        path = root / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError('Missing or changed packaged resource: ' + name)
    checked = []
    for route in manifest['pages'] + manifest['assets']:
        response = client.get(route)
        if response.status_code != 200:
            raise RuntimeError('Packaged entry failed: ' + route + ' HTTP ' + str(response.status_code))
        if route in manifest['pages'] and 'text/html' not in response.headers.get('content-type', ''):
            raise RuntimeError('Packaged page did not return HTML: ' + route)
        checked.append(route)
    response = client.get('/api/fada-items')
    if response.status_code != 200 or not response.json().get('items'):
        raise RuntimeError('Shipped Fada catalog is empty or unavailable')
    return {'pages': len(manifest['pages']), 'assets': len(manifest['assets']),
            'resources': len(manifest['files']), 'checked': checked}
