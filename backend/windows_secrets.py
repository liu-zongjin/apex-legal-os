"""Per-user DPAPI secret storage; existing macOS keychain identities stay intact."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import tempfile


def _path(service, account):
    root = Path(os.environ.get('LEGAL_KB_CONFIG_DIR', Path.home())) / 'credentials'
    return root / (hashlib.sha256((service + '\0' + account).encode()).hexdigest() + '.bin')


def _crypt(data, decrypt=False):
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    source = ctypes.create_string_buffer(data)
    src = Blob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_ubyte)))
    dst = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not function(ctypes.byref(src), None, None, None, None, 1, ctypes.byref(dst)):
        raise OSError('Windows 凭据保护操作失败')
    try:
        return ctypes.string_at(dst.data, dst.size)
    finally:
        kernel.LocalFree(dst.data)


def read(service, account):
    path = _path(service, account)
    if not path.exists():
        return {}
    return json.loads(_crypt(path.read_bytes(), decrypt=True))


def write(service, account, value):
    path = _path(service, account)
    path.parent.mkdir(parents=True, exist_ok=True)
    encrypted = _crypt(json.dumps(value, ensure_ascii=False).encode())
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.credential-')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(encrypted)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def delete(service, account):
    _path(service, account).unlink(missing_ok=True)
