"""Create content-indexed signed component catalog; no publication side effects."""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import time
import zipfile
from pathlib import Path


def pack_component(name, root, output, base_url):
    files = {}
    size = 0
    archive = output / (name + '.zip')
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=7) as z:
        for path in sorted(root.rglob('*')):
            if path.is_symlink():
                raise ValueError('Symlink in component')
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
            size += path.stat().st_size
            z.write(path, relative)
    return {'id': name, 'url': base_url.rstrip('/') + '/' + name + '.zip',
            'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'bytes': archive.stat().st_size,
            'expanded_bytes': size, 'files': files}


def sign(payload, key):
    raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':'), sort_keys=True).encode()
    return {'payload': base64.b64encode(raw).decode(), 'signature': base64.b64encode(key.sign(raw)).decode()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--components', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--build', type=int, required=True)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--mirror-base-url', action='append', default=[],
                        help='Optional publisher-controlled HTTPS mirror base (up to three)')
    parser.add_argument('--private-key', type=Path)
    parser.add_argument('--development-key', action='store_true')
    args = parser.parse_args()
    from urllib.parse import urlsplit
    if len(args.mirror_base_url) > 3:
        parser.error('At most three mirror bases are supported')
    for url in [args.base_url, *args.mirror_base_url]:
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.port not in (None, 443)):
            parser.error('Download bases must be HTTPS without credentials, queries or fragments')
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    if bool(args.private_key) == bool(args.development_key):
        parser.error('Choose an existing private key or an ephemeral development key')
    key = Ed25519PrivateKey.generate() if args.development_key else Ed25519PrivateKey.from_private_bytes(args.private_key.read_bytes())
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    components = [pack_component(p.name, p, output, args.base_url) for p in sorted(args.components.iterdir()) if p.is_dir()]
    for component in components:
        if args.mirror_base_url:
            component['mirrors'] = [base.rstrip('/') + '/' + component['id'] + '.zip' for base in args.mirror_base_url]
    envelope = sign({'schema': 1, 'target': 'windows-x86_64', 'version': args.version,
                     'build': args.build, 'expires_at': int(time.time()) + 30 * 86400, 'components': components}, key)
    (output / 'catalog.json').write_text(json.dumps(envelope), encoding='utf-8')
    config = {'public_key': base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode(),
              'catalog_url': '', 'allowed_hosts': list(dict.fromkeys(urlsplit(url).hostname for url in [args.base_url, *args.mirror_base_url]))}
    (output / 'bootstrap-config.json').write_text(json.dumps(config), encoding='utf-8')
    print('Created signed development catalog' if args.development_key else 'Created signed catalog; not published')


if __name__ == '__main__':
    main()
