"""Frozen Windows backend entry; empty per-user runtime, graceful pipe-owner shutdown."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import sys
import threading
import time
import uuid
from pathlib import Path

# This helper is frozen into the application, not a second business implementation.
from bootstrap_engine import exclusive_lock, InstallError
from preview_entry import backup_for_build


def configure(runtime):
    runtime = runtime.expanduser().resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    for key in list(os.environ):
        if key.endswith(("_API_KEY", "_API_SECRET", "_ACCESS_TOKEN", "_AUTH_CODE", "_AUTHORIZATION", "_WEB_COOKIE")):
            os.environ.pop(key, None)
    os.environ.update({
        "LEGAL_KB_RUNTIME_DIR": str(runtime), "LEGAL_KB_CONFIG_DIR": str(runtime),
        "LEGAL_KB_DB_PATH": str(runtime / "legal_kb.db"), "LEGAL_KB_UPLOAD_DIR": str(runtime / "uploads"),
        "LEGAL_KB_ARTICLE_IMAGE_DIR": str(runtime / "article_images"), "LEGAL_KB_DATA_DIR": str(runtime / "data"),
        "LEGAL_KB_HOST": "127.0.0.1", "PORT": "18865", "LEGAL_KB_PRIVATE_MODE": "0",
        "LEGAL_KB_SESSION_SECRET": secrets.token_hex(32), "FEISHU_LISTENER_ENABLED": "0",
        "JUDICIAL_SMS_SCHEDULER_DISABLED": "1", "CODEX_HOME": str(runtime / "skills-home"),
    })
    for key in ("LEGAL_KB_ACCESS_PASSWORD", "APEX_ANONYMOUS_PILOT"):
        os.environ.pop(key, None)
    return runtime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--app-build", required=True)
    parser.add_argument("--ready-token", required=True)
    parser.add_argument("--shutdown-file", required=True, type=Path)
    args = parser.parse_args()
    runtime = configure(args.runtime)
    token = uuid.UUID(args.ready_token).hex
    ready = runtime / ("server-ready-" + token)
    shutdown = args.shutdown_file.resolve()
    if shutdown.parent != runtime or shutdown.name != "stop-" + token:
        raise InstallError("关闭标记无效")
    shutdown.unlink(missing_ok=True)
    with exclusive_lock(runtime / "server.lock"):
        marker = backup_for_build(runtime, args.app_build)
        from backend.main import app, get_db
        # Keep anonymous first launch genuinely empty; existing records are untouched.
        with get_db() as conn:
            conn.execute("UPDATE case_manager_message_settings SET enabled=0 WHERE id=1")
            conn.commit()
        import uvicorn
        class Server(uvicorn.Server):
            async def startup(self, sockets=None):
                await super().startup(sockets=sockets)
                if self.started:
                    from bootstrap_engine import atomic_json
                    atomic_json(marker, {"build": args.app_build})
                    ready.touch()
        server = Server(uvicorn.Config(app, host="127.0.0.1", port=18865, loop="asyncio",
                                       workers=1, access_log=False, log_level="warning"))
        def monitor():
            while not shutdown.exists():
                time.sleep(0.25)
            server.should_exit = True
        threading.Thread(target=monitor, daemon=True).start()
        try:
            server.run()
        finally:
            ready.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
