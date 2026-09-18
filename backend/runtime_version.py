"""Runtime/source version checks shared by the backend and its supervisor.

The private macOS service is long-lived, so a changed file must never silently
leave an older Python process serving requests.  Keep this module dependency
free: it is imported by both ``backend.main`` and the LaunchAgent entrypoint.
The supervisor intentionally watches this module too.
"""

from __future__ import annotations

import hashlib
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
    "article_images", "browser-profile", "browser_profiles", "data", "legal_kb.db", "logs", "uploads",
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
        for path in root.rglob("*"):
            if _is_watched(path):
                paths.add(path.resolve())
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
