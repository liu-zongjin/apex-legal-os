"""Manage the private Mac backup schedule and its generated archives."""

from __future__ import annotations

import json
import os
import plistlib
import re
import stat
import sys
import threading
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, StrictBool, StrictInt

from .security import allow_remote_management, is_loopback_client


router = APIRouter()
BACKUP_LABEL = "com.liuzongjin.legalkb.private.backup"
_SCHEDULE_LOCK = threading.Lock()
DEFAULTS = {"enabled": True, "frequency": "daily", "hour": 3, "minute": 20, "weekday": 0, "retention_days": 14}
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
    if not isinstance(data, dict):
        raise ValueError("备份计划格式无效")
    result = {key: data.get(key, default) for key, default in DEFAULTS.items()}
    if not isinstance(result["enabled"], bool):
        raise ValueError("自动备份状态无效")
    if result["frequency"] not in ("daily", "weekdays", "weekly"):
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
    enabled: StrictBool = True
    frequency: str
    hour: StrictInt
    minute: StrictInt
    weekday: StrictInt = 0
    retention_days: StrictInt


def scheduled_backup_files(root: Path):
    for category, pattern in FILE_PATTERNS.items():
        directory = root / category
        if directory.is_symlink() or not directory.is_dir():
            continue
        for path in directory.iterdir():
            if not pattern.fullmatch(path.name):
                continue
            try:
                info = path.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISREG(info.st_mode):
                yield category, path, info


def backup_revision(info: os.stat_result) -> str:
    return f"{info.st_dev}:{info.st_ino}:{info.st_size}:{info.st_mtime_ns}"


def backup_timestamp(name: str, info: os.stat_result) -> dict:
    modified = datetime.fromtimestamp(info.st_mtime)
    utc_stamp = re.search(r"(?<![0-9])[0-9]{8}T[0-9]{6,12}Z", name)
    if utc_stamp:
        try:
            created = datetime.strptime(utc_stamp.group()[:15], "%Y%m%dT%H%M%S")
            created = created.replace(tzinfo=timezone.utc).astimezone()
            return {"created_at": created.strftime("%Y-%m-%d %H:%M:%S"),
                    "modified_at": modified.isoformat(" ", timespec="seconds")}
        except ValueError:
            pass
    for match in reversed(list(re.finditer(r"(?<![0-9])20[0-9]{6}(?:-[0-9]{6}|-[0-9]{4}|[0-9]{6})?(?![0-9])", name))):
        stamp = match.group().replace("-", "")
        pattern = {8: "%Y%m%d", 12: "%Y%m%d%H%M", 14: "%Y%m%d%H%M%S"}[len(stamp)]
        try:
            created = datetime.strptime(stamp, pattern)
        except ValueError:
            continue
        return {"created_at": created.isoformat(" ", timespec="seconds") if len(stamp) > 8 else created.date().isoformat(),
                "modified_at": modified.isoformat(" ", timespec="seconds")}
    return {"created_at": None, "modified_at": modified.isoformat(" ", timespec="seconds")}


def backup_retention_note(size: int, newest: bool, kind: str) -> str:
    if not size:
        return "文件为空，无法用于恢复。请先确认另有可用备份。"
    if newest:
        return "建议保留。这是此类备份中最近的一个恢复点。"
    if kind == "rollback":
        return "确认对应更新或维护已稳定运行，并且不再需要回到此时间点后，可考虑清理。"
    return "确认有较新的可用备份，并且不再需要此时间点的数据后，可考虑清理。"


@router.get("/api/backup-management")
def get_backup_management():
    root = backup_root()
    schedule_error = None
    try:
        settings = read_settings()
    except HTTPException as exc:
        settings = DEFAULTS.copy()
        schedule_error = exc.detail
    files = []
    for category, path, info in scheduled_backup_files(root):
        is_db = category == "databases"
        files.append({
            "name": path.name, "category": category, "size": info.st_size,
            "display_name": "定时数据库备份" if is_db else "定时上传文件备份",
            "file_type": "SQLite 数据库" if is_db else "压缩存档（tar.gz）",
            "backup_reason": "恢复备份时的知识库数据。" if is_db else "恢复备份时的上传原件。",
            "revision": backup_revision(info),
            **backup_timestamp(path.name, info),
        })
    files.sort(key=lambda item: (item["created_at"] or item["modified_at"], item["name"]), reverse=True)
    seen = set()
    for file in files:
        newest = file["category"] not in seen and file["size"] > 0
        file["retention_note"] = backup_retention_note(file["size"], newest, "scheduled")
        if newest:
            seen.add(file["category"])
    return {
        "settings": settings, "schedule_available": sys.platform == "darwin" and launch_agent_path().is_file(),
        "schedule_error": schedule_error, "platform": sys.platform,
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
    with _SCHEDULE_LOCK:
        return _persist_schedule(settings)


def _persist_schedule(settings: dict) -> dict:
    plist_path = launch_agent_path()
    if sys.platform != "darwin" or not plist_path.is_file():
        raise HTTPException(409, "这台 Mac 尚未安装自动备份任务，请先安装私有服务")
    config_path = settings_path()
    try:
        old_plist = plist_path.read_bytes()
        plist = plistlib.loads(old_plist)
        if plist.get("Label") != BACKUP_LABEL:
            raise ValueError("自动备份任务标识不匹配")
        old_config = config_path.read_bytes() if config_path.exists() else None
        if settings["enabled"]:
            plist["StartCalendarInterval"] = calendar_interval(settings)
        else:
            plist.pop("StartCalendarInterval", None)
        plist["RunAtLoad"] = False
        new_plist = plistlib.dumps(plist)
        new_config = (json.dumps(settings, ensure_ascii=False, indent=2) + "\n").encode()
        _atomic_write(config_path, new_config)
        plist_written = False
        try:
            _atomic_write(plist_path, new_plist)
            plist_written = True
            _reload_agent(plist_path)
        except Exception:
            if plist_written:
                _atomic_write(plist_path, old_plist)
            if old_config is None:
                config_path.unlink(missing_ok=True)
            else:
                _atomic_write(config_path, old_config)
            if plist_written:
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
        info = path.lstat()
        revision = getattr(request, "query_params", {}).get("revision")
        if not stat.S_ISREG(info.st_mode) or (revision is not None and revision != backup_revision(info)):
            raise HTTPException(409, "备份文件已变化，请刷新列表后重试")
        configured_db = Path(os.environ.get("LEGAL_KB_DB_PATH") or "").resolve()
        if path.resolve() == configured_db:
            raise HTTPException(409, "当前运行的数据库不能删除")
        size = info.st_size
        path.unlink()
    except OSError as exc:
        raise HTTPException(500, f"删除备份失败：{exc}") from exc
    return {"ok": True, "freed_bytes": size}
