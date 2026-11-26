"""Resolve the local private configuration without opening runtime data."""

import os
from pathlib import Path


def private_environment_path(project: Path) -> Path:
    explicit = os.environ.get("LEGAL_KB_PRIVATE_ENV_PATH")
    if explicit:
        return Path(explicit)
    locator = project / ".env.private-location"
    if locator.is_file():
        destination = Path(locator.read_text(encoding="utf-8").strip())
        if not destination.is_absolute():
            raise ValueError("Private configuration locator must store an absolute path")
        return destination
    return project / ".env.private"
