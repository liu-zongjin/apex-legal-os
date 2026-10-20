"""Locate shipped Mac helpers without requiring recipient developer tools."""
from pathlib import Path
import sys


def macos_helper(name):
    if name not in {'APEXCalendarBridge', 'APEXContactsBridge', 'APEXVisionOCR'}:
        raise ValueError('Unknown Mac helper')
    if sys.platform != 'darwin':
        return None
    if getattr(sys, 'frozen', False):
        candidate = Path(sys.executable).resolve().parents[2] / 'MacOS' / name
    else:
        candidate = Path(__file__).resolve().parent.parent / 'dist/Stella.app/Contents/MacOS' / name
    return candidate if candidate.is_file() else None
