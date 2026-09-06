"""LaunchAgent entry point that keeps macOS TCC attribution on Python.app."""

from __future__ import annotations

import os
import logging
from logging.handlers import RotatingFileHandler
import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_DIR / "logs"
SERVER_LOG = LOG_DIR / "private-server.log"
LOG_PART_BYTES = 5 * 1024 * 1024


class _LoggerWriter:
    """Send print/traceback output through the bounded application logger."""

    def __init__(self, logger: logging.Logger, level: int) -> None:
        self.logger = logger
        self.level = level
        self._pending = ""

    def write(self, message: str) -> int:
        if not message:
            return 0
        self._pending += message
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            if line.strip():
                self.logger.log(self.level, line.rstrip())
        return len(message)

    def flush(self) -> None:
        if self._pending.strip():
            self.logger.log(self.level, self._pending.rstrip())
        self._pending = ""

    def isatty(self) -> bool:
        return False


def _trim_log_tail(path: Path, max_bytes: int) -> None:
    """Keep only the newest complete lines when an existing log is oversized."""
    if not path.exists() or path.stat().st_size <= max_bytes:
        return
    with path.open("rb") as source:
        source.seek(-max_bytes, os.SEEK_END)
        tail = source.read()
    newline = tail.find(b"\n")
    if newline >= 0:
        tail = tail[newline + 1:]
    with path.open("wb") as target:
        target.write(tail)


def configure_bounded_logging() -> None:
    """Keep error/program logs while capping current + one backup at 10 MiB."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _trim_log_tail(SERVER_LOG, LOG_PART_BYTES)
    _trim_log_tail(Path(f"{SERVER_LOG}.1"), LOG_PART_BYTES)

    handler = RotatingFileHandler(
        SERVER_LOG,
        maxBytes=LOG_PART_BYTES,
        backupCount=1,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)
    logging.raiseExceptions = False

    # Third-party clients otherwise emit one INFO line for every successful
    # outbound request (for example Feishu synchronization). Keep only their
    # warnings/errors while preserving this application's own INFO messages.
    for noisy_logger in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    # launchd originally points fd 1/2 at the same unlimited file. Route all
    # Python output through the rotating handler and silence the raw fds so a
    # rollover cannot leave launchd writing into an archived inode.
    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull_fd, 1)
        os.dup2(devnull_fd, 2)
    finally:
        os.close(devnull_fd)
    sys.stdout = _LoggerWriter(logging.getLogger("legal_kb.stdout"), logging.INFO)
    sys.stderr = _LoggerWriter(logging.getLogger("legal_kb.stderr"), logging.ERROR)


def load_private_environment() -> None:
    env_path = PROJECT_DIR / ".env.private"
    if not env_path.exists():
        return
    # The installer writes shell-escaped values with printf %q. Ask bash only
    # to decode that file; the long-running process remains this Python.app.
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            'set -a; . "$1"; env -0',
            "private-server-env",
            str(env_path),
        ],
        check=True,
        stdout=subprocess.PIPE,
    )
    for entry in result.stdout.split(b"\0"):
        if b"=" not in entry:
            continue
        key, value = entry.split(b"=", 1)
        os.environ[key.decode("utf-8")] = value.decode("utf-8")


def main() -> None:
    os.chdir(str(PROJECT_DIR))
    project_text = str(PROJECT_DIR)
    if project_text not in sys.path:
        sys.path.insert(0, project_text)
    load_private_environment()
    os.environ.setdefault("LEGAL_KB_FDA_TARGET", os.path.realpath(sys.executable))
    os.environ.setdefault("LEGAL_KB_PRIVATE_MODE", "1")
    os.environ.setdefault("LEGAL_KB_ALLOW_REMOTE_MANAGEMENT", "0")
    host = os.environ.get("LEGAL_KB_HOST", "").strip()
    if not host or host == "auto":
        host = "0.0.0.0"
    port = int(os.environ.get("PORT", "8000"))

    configure_bounded_logging()

    import uvicorn

    # Successful HTTP requests are intentionally omitted. Startup messages,
    # application warnings and errors continue to use the bounded log above.
    uvicorn.run(
        "backend.main:app",
        host=host,
        port=port,
        access_log=False,
        log_config=None,
    )


if __name__ == "__main__":
    main()
