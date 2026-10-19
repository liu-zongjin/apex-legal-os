"""Pinned official Sparkle binary tools. Cache contains no application/user data."""
from pathlib import Path
import hashlib
import subprocess
import tarfile
import urllib.request

VERSION = '2.10.0'
SHA256 = 'c2bf58aa8387266ac179357b1415d6f2635f044da8be41042af32425dae6da0c'
URL = f'https://github.com/sparkle-project/Sparkle/releases/download/{VERSION}/Sparkle-{VERSION}.tar.xz'
ROOT = Path(__file__).resolve().parents[2]


def tools():
    cache = ROOT / '.tmp' / ('sparkle-' + VERSION)
    archive = ROOT / '.tmp' / ('Sparkle-' + VERSION + '.tar.xz')
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        pending = archive.with_suffix('.download')
        urllib.request.urlretrieve(URL, pending)
        pending.replace(archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise RuntimeError('Sparkle checksum mismatch; refusing SDK')
    # Always re-extract verified bytes; do not trust a mutated cached framework.
    import shutil
    if cache.exists():
        shutil.rmtree(cache)
    cache.mkdir()
    # Official checksum pins a trusted archive, including its framework symlinks.
    with tarfile.open(archive) as source:
        source.extractall(cache)
    return cache


def public_key(sdk):
    result = subprocess.check_output([str(sdk/'bin/generate_keys'), '--account', 'stella-public', '-p'], text=True).strip()
    import base64
    if len(base64.b64decode(result, validate=True)) != 32:
        raise RuntimeError('Generate the Stella public release key in Keychain first')
    return result


def swift_annotation_flags():
    """Only fill annotations absent from the build SDK; never edit SDK headers."""
    result = subprocess.run(['xcrun', 'clang', '-dM', '-E', '-x', 'objective-c', '-'],
                            input='#import <Foundation/Foundation.h>\n',
                            text=True, capture_output=True, check=True)
    flags = []
    for name in ('NS_SWIFT_SENDABLE', 'NS_SWIFT_UI_ACTOR', 'NS_SWIFT_ASYNC'):
        if not any(line.startswith('#define ' + name + ' ') or line.startswith('#define ' + name + '(')
                   for line in result.stdout.splitlines()):
            flags.extend(['-Xcc', '-D' + name + ('(x)' if name == 'NS_SWIFT_ASYNC' else '') + '='])
    return flags
