"""Windows common-item dialog on its own COM apartment, without PowerShell.

The backend owns filesystem selection so both the native shell and a loopback
browser can use the same routes. This module has no import-time Windows calls.
"""
from __future__ import annotations

import ctypes
import queue
import threading
import uuid

_selection_lock = threading.Lock()
_CANCELLED = 0x800704C7


def _check(code):
    value = int(code) & 0xFFFFFFFF
    if value & 0x80000000:
        raise OSError(f'Windows 选择窗口不可用（0x{value:08X}），请重试或粘贴文件夹路径')


def _method(pointer, index, *types):
    table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, *types)(table[index])


def _dialog(kind, *, show=True):
    ole = ctypes.OleDLL('ole32')
    user = ctypes.WinDLL('user32')
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    ole.CoInitializeEx.restype = ctypes.c_int32
    ole.CoCreateInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
                                   ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    ole.CoCreateInstance.restype = ctypes.c_int32
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole.CoTaskMemFree.restype = None
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None
    user.GetForegroundWindow.argtypes = []
    user.GetForegroundWindow.restype = ctypes.c_void_p
    # STA + disable OLE1 DDE. Always balance successful initialization, including S_FALSE.
    _check(ole.CoInitializeEx(None, 0x2 | 0x4))
    dialog, item, name = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    try:
        clsid = ctypes.create_string_buffer(uuid.UUID('DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7').bytes_le)
        iid = ctypes.create_string_buffer(uuid.UUID('D57C7288-D4AD-4768-BE02-9D969532D960').bytes_le)
        _check(ole.CoCreateInstance(clsid, None, 1, iid, ctypes.byref(dialog)))
        options = ctypes.c_uint32()
        _check(_method(dialog, 10, ctypes.POINTER(ctypes.c_uint32))(dialog, ctypes.byref(options)))
        flags = options.value | 0x40 | 0x800 | 0x8  # filesystem, existing path, preserve cwd
        flags &= ~0x200  # single selection
        if kind == 'folder':
            flags = (flags | 0x20) & ~0x1000
        else:
            flags |= 0x1000
        _check(_method(dialog, 9, ctypes.c_uint32)(dialog, flags))
        _check(_method(dialog, 17, ctypes.c_wchar_p)(dialog, '选择本地文件夹' if kind == 'folder' else '选择本地文件'))
        if not show:
            return None  # CI verifies native creation/configuration without an unattended modal.
        code = _method(dialog, 3, ctypes.c_void_p)(dialog, user.GetForegroundWindow())
        if int(code) & 0xFFFFFFFF == _CANCELLED:
            return None
        _check(code)
        _check(_method(dialog, 20, ctypes.POINTER(ctypes.c_void_p))(dialog, ctypes.byref(item)))
        # SIGDN_FILESYSPATH returns a Unicode path, including drive roots and UNC shares.
        _check(_method(item, 5, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p))(
            item, 0x80058000, ctypes.byref(name)))
        value = ctypes.wstring_at(name)
        if not value:
            raise OSError('未取得所选路径，请重新选择')
        return value
    finally:
        if name.value:
            ole.CoTaskMemFree(name)
        if item.value:
            _method(item, 2)(item)
        if dialog.value:
            _method(dialog, 2)(dialog)
        ole.CoUninitialize()


def select_path(kind, *, show=True):
    if kind not in ('file', 'folder'):
        raise ValueError('请选择文件或文件夹')
    if not _selection_lock.acquire(blocking=False):
        raise OSError('已有文件选择窗口，请先完成或取消当前选择')
    result = queue.Queue(maxsize=1)
    def choose():
        try:
            result.put((True, _dialog(kind, show=show)))
        except Exception as exc:
            result.put((False, exc))
    try:
        # Do not attach COM/Tk state to Uvicorn's loop or reused request workers.
        thread = threading.Thread(target=choose, name='stella-windows-picker', daemon=True)
        thread.start()
        success, value = result.get()
        thread.join()
        if not success:
            raise value
        return value
    finally:
        _selection_lock.release()
