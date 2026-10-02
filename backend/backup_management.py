"""Manage the private Mac backup schedule and its generated archives."""

from __future__ import annotations

import json
import os
import plistlib
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .security import allow_remote_management, is_loopback_client


router = APIRouter()
BACKUP_LABEL = "com.liuzongjin.legalkb.private.backup"
DEFAULTS = {"frequency": "daily", "hour": 3, "minute": 20, "weekday": 0, "retention_days": 14}
FILE_PATTERNS = {
    "databases": re.compile(r"^legal_kb-\d{8}-\d{6}\.db$"),
    "uploads": re.compile(r"^uploads-\d{8}-\d{6}\.tar\.gz$"),
}


def backup_root() -> Path:
    return Path(os.environ.get("LEGAL_KB_BACKUP_DIR") or Path.home() / "LegalKBBackups").expanduser().resolve()


def settings_path() -> Path:
    return backup_root() / "backup-settings.json"


def launch_agent_path() -> Path:
    return Path.home() / "Library/LaunchAgents" / f"{BACKUP_LABEL}.plist"


def _validate(data: dict) -> dict:
    result = {key: data.get(key, default) for key, default in DEFAULTS.items()}
    if result["frequency"] not in {"daily", "weekdays", "weekly"}:
        raise ValueError("备份周期无效")
    for key, low, high in (("hour", 0, 23), ("minute", 0, 59), ("weekday", 0, 6), ("retention_days", 1, 365)):
        value = result[key]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError(f"{key} 超出允许范围")
    return result


def read_settings() -> dict:
    path = settings_path()
    if not path.exists():
        defaults = DEFAULTS.copy()
        try:
            defaults["retention_days"] = int(os.environ.get("LEGAL_KB_BACKUP_RETENTION_DAYS", "14"))
            return _validate(defaults)
        except ValueError:
            return DEFAULTS.copy()
    try:
        return _validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError) as exc:
        raise HTTPException(500, f"备份设置无法读取：{exc}") from exc


def calendar_interval(settings: dict) -> dict | list[dict]:
    timing = {"Hour": settings["hour"], "Minute": settings["minute"]}
    if settings["frequency"] == "daily":
        return timing
    if settings["frequency"] == "weekly":
        return {**timing, "Weekday": settings["weekday"]}
    return [{**timing, "Weekday": day} for day in range(1, 6)]


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_name, path)
    finally:
        Path(temp_name).unlink(missing_ok=True)


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, timeout=15, check=False)


def _reload_agent(plist_path: Path) -> None:
    domain = f"gui/{os.getuid()}"
    # bootout can report an error when the agent is not loaded. Bootstrap is
    # the operation whose success determines whether the new schedule is live.
    _launchctl("bootout", domain, str(plist_path))
    result = _launchctl("bootstrap", domain, str(plist_path))
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "launchctl bootstrap 失败")


def _require_management(request: Request) -> None:
    client_host = request.client.host if request.client else ""
    if not is_loopback_client(client_host) and not allow_remote_management():
        raise HTTPException(403, "私有部署模式已禁用远程管理功能")


class BackupSettingsInput(BaseModel):
    frequency: str
    hour: int
    minute: int
    weekday: int = 0
    retention_days: int


@router.get("/api/backup-management")
def get_backup_management():
    root = backup_root()
    files = []
    for category, pattern in FILE_PATTERNS.items():
        directory = root / category
        if directory.is_symlink() or not directory.is_dir():
            continue
        for path in directory.iterdir():
            if not pattern.fullmatch(path.name) or path.is_symlink() or not path.is_file():
                continue
            stat = path.stat()
            files.append({
                "name": path.name, "category": category, "size": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            })
    files.sort(key=lambda item: item["name"], reverse=True)
    return {
        "settings": read_settings(), "schedule_available": launch_agent_path().is_file(),
        "backup_dir": str(root), "files": files,
        "total_size": sum(item["size"] for item in files),
    }


@router.put("/api/backup-management/settings")
def save_backup_settings(payload: BackupSettingsInput, request: Request):
    _require_management(request)
    try:
        settings = _validate(payload.model_dump() if hasattr(payload, "model_dump") else payload.dict())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    plist_path = launch_agent_path()
    if not plist_path.is_file():
        raise HTTPException(409, "这台 Mac 尚未安装自动备份任务，请先安装私有服务")
    config_path = settings_path()
    try:
        old_plist = plist_path.read_bytes()
        plist = plistlib.loads(old_plist)
        if plist.get("Label") != BACKUP_LABEL:
            raise ValueError("自动备份任务标识不匹配")
        old_config = config_path.read_bytes() if config_path.exists() else None
        plist["StartCalendarInterval"] = calendar_interval(settings)
        plist["RunAtLoad"] = False
        new_plist = plistlib.dumps(plist)
        new_config = (json.dumps(settings, ensure_ascii=False, indent=2) + "\n").encode()
        _atomic_write(config_path, new_config)
        _atomic_write(plist_path, new_plist)
        try:
            _reload_agent(plist_path)
        except Exception:
            _atomic_write(plist_path, old_plist)
            if old_config is None:
                config_path.unlink(missing_ok=True)
            else:
                _atomic_write(config_path, old_config)
            _reload_agent(plist_path)
            raise
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(500, f"保存备份计划失败：{exc}") from exc
    return {"ok": True, "settings": settings}


@router.delete("/api/backup-management/files/{category}/{name}")
def delete_backup_file(category: str, name: str, request: Request):
    _require_management(request)
    pattern = FILE_PATTERNS.get(category)
    if pattern is None or not pattern.fullmatch(name):
        raise HTTPException(400, "备份文件名无效")
    directory = backup_root() / category
    path = directory / name
    if directory.is_symlink() or path.is_symlink() or not path.is_file() or path.parent.resolve() != directory.resolve():
        raise HTTPException(404, "备份文件不存在")
    try:
        size = path.stat().st_size
        path.unlink()
    except OSError as exc:
        raise HTTPException(500, f"删除备份失败：{exc}") from exc
    return {"ok": True, "freed_bytes": size}
