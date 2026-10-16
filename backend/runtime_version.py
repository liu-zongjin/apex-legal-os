"""Runtime/source version checks shared by the backend and its supervisor.

The private macOS service is long-lived, so a changed file must never silently
leave an older Python process serving requests.  Keep this module dependency
free: it is imported by both ``backend.main`` and the LaunchAgent entrypoint.
The supervisor intentionally watches this module too.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from pathlib import Path


WATCHED_SUFFIXES = frozenset({
    ".command", ".css", ".html", ".js", ".json", ".plist", ".py", ".sh", ".swift",
})
WATCHED_ROOTS = ("backend", "frontend", "native-shell", "scripts")
WATCHED_FILES = (
    "app_entry.py",
    "restart.py",
    "start.py",
    "package.json",
    "package-lock.json",
    "requirements-private.txt",
    ".env.private",
)
IGNORED_PARTS = frozenset({
    ".git", ".mypy_cache", ".pytest_cache", ".venv", "__pycache__", "node_modules",
    "article_images", "browser-profile", "browser_profiles", "browser-profiles",
    "court_online_service", "contract_previews", "contract_templates", "judicial_downloads",
    "build", "data", "legal_kb.db", "logs", "uploads",
})


def _is_watched(path: Path) -> bool:
    if not path.is_file() or (
        path.name != ".env.private" and path.suffix.lower() not in WATCHED_SUFFIXES
    ):
        return False
    return not any(part in IGNORED_PARTS for part in path.parts)


def watched_source_files(base_dir: Path) -> list[Path]:
    """Return deterministic source/config files that require a reload."""
    base_dir = Path(base_dir).resolve()
    paths: set[Path] = set()
    for relative_root in WATCHED_ROOTS:
        root = base_dir / relative_root
        if not root.is_dir():
            continue
        for directory, children, filenames in os.walk(root, followlinks=False):
            children[:] = [name for name in children if name not in IGNORED_PARTS
                           and not name.startswith('.')
                           and not Path(directory, name).is_symlink()]
            for name in filenames:
                path = Path(directory, name)
                if not path.is_symlink() and _is_watched(path):
                    paths.add(path)
    for relative_path in WATCHED_FILES:
        path = base_dir / relative_path
        if _is_watched(path):
            paths.add(path.resolve())
    return sorted(paths, key=lambda path: str(path))


def source_fingerprint(base_dir: Path) -> str:
    """Fingerprint source metadata without reading runtime/user data."""
    base_dir = Path(base_dir).resolve()
    digest = hashlib.sha256()
    for path in watched_source_files(base_dir):
        try:
            stat = path.stat()
        except OSError:
            continue
        try:
            relative = path.relative_to(base_dir).as_posix()
        except ValueError:
            relative = str(path)
        digest.update(relative.encode("utf-8", "replace"))
        digest.update(b"\0")
        digest.update(str(stat.st_mtime_ns).encode("ascii"))
        digest.update(b":")
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def source_status(base_dir: Path, runtime_version: str) -> dict[str, object]:
    """Return the additive status fields exposed by ``/api/server-status``."""
    disk_version = source_fingerprint(base_dir)
    current = bool(runtime_version) and runtime_version == disk_version
    return {
        "runtime_source_version": runtime_version,
        "disk_source_version": disk_version,
        "source_status": "current" if current else "stale",
        "restart_required": not current,
    }


class SourceMonitor:
    """One background sampler; request handlers never walk the filesystem.

    Status fails closed if sampling stops. The supervisor still restarts a
    changed process; the bounded detection window is one sampling interval.
    """
    def __init__(self, base_dir: Path, runtime_version: str, interval: float = 1.5):
        self.base_dir = Path(base_dir)
        self.runtime_version = runtime_version
        self.interval = interval
        self._disk_version = runtime_version
        self._checked = time.monotonic()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name='stella-source-monitor', daemon=True)
            self._thread.start()

    def refresh(self):
        version = source_fingerprint(self.base_dir)
        with self._lock:
            self._disk_version = version
            self._checked = time.monotonic()

    def _run(self):
        while not self._stop.is_set():
            try:
                self.refresh()
            except OSError:
                pass  # Expired samples become unavailable, never silently current.
            self._stop.wait(self.interval)

    def status(self, runtime_version=None):
        with self._lock:
            runtime = self.runtime_version if runtime_version is None else runtime_version
            fresh = time.monotonic() - self._checked < max(10.0, self.interval * 4)
            disk = self._disk_version
        current = fresh and bool(runtime) and runtime == disk
        return {'runtime_source_version': runtime, 'disk_source_version': disk,
                'source_status': ('current' if current else 'stale') if fresh else 'unavailable',
                'restart_required': not current}

    def close(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
