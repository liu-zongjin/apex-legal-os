"""Run repository tests with a disposable runtime before importing the app."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory


_runtime = TemporaryDirectory(prefix="stella-tests-")
_root = Path(_runtime.name).resolve()

# Remove explicit paths inherited from a developer's running installation.
for _name in (
    "LEGAL_KB_DB_PATH",
    "LEGAL_KB_UPLOAD_DIR",
    "LEGAL_KB_ARTICLE_IMAGE_DIR",
    "LEGAL_KB_PRIVATE_MODE",
    "LEGAL_KB_ACCESS_USER",
    "LEGAL_KB_ACCESS_PASSWORD",
    "LEGAL_KB_SESSION_SECRET",
):
    os.environ.pop(_name, None)

os.environ.update({
    "LEGAL_KB_RUNTIME_DIR": str(_root),
    "LEGAL_KB_CONFIG_DIR": str(_root / "config"),
    "LEGAL_KB_PRIVATE_ENV_PATH": str(_root / ".env.private"),
    "LEGAL_KB_DATA_DIR": str(_root / "data"),
    "LEGAL_KB_BACKUP_DIR": str(_root / "backups"),
})
