"""Invoice export history, local archives and monthly collection scheduler."""

from __future__ import annotations

import asyncio
import datetime
import functools
import hashlib
import json
import os
import re
import threading
import uuid
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from . import qq_mail_mcp


_INVOICE_AUTOMATION_EXTENSIONS = (".pdf", ".ofd", ".xml", ".png", ".jpg", ".csv")


def _invoice_export_key(invoice: Dict[str, Any], path: Path) -> str:
    """Identify invoice format across copies; unknown files use their actual content."""
    number = str(invoice.get("invoice_number") or "") or qq_mail_mcp.invoice_number_from_values(
        invoice.get("filename"), path.name, invoice.get("subject"))
    if number:
        owner = str(invoice.get("invoice_code") or invoice.get("issuer") or "") if len(number) < 16 else ""
        identity = f"invoice:{owner}:{number}:{path.suffix.lower()}".encode("utf-8")
        return hashlib.sha256(identity).hexdigest()
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repair_invoice_export_history(account: str, records: List[Dict[str, Any]]) -> bool:
    """一次性修复旧版链接发票遗留的截断日期，并保持筛除已导出的匹配键一致。"""
    root = qq_mail_mcp.MAILBOX_CONFIGS[account]["attachment_root"].resolve()
    changed = False
    for record in records:
        if record.get("key_version") == 3:
            continue
        path = Path(str(record.get("path") or "")).resolve()
        if root not in path.parents or not path.is_file():
            continue
        parsed = qq_mail_mcp.parse_invoice_metadata(path)
        for field in ("issue_time", "issuer", "amount"):
            if parsed.get(field):
                record[field] = parsed[field]
        record["invoice_code"] = str(parsed.get("invoice_code") or "")
        record["invoice_number"] = parsed.get("invoice_number") or qq_mail_mcp.invoice_number_from_values(record.get("filename"), record.get("subject"))
        previous = record.get("export_key")
        record["export_key"] = _invoice_export_key(record, path)
        if previous and previous != record["export_key"]:
            record["legacy_export_keys"] = list(dict.fromkeys((record.get("legacy_export_keys") or []) + [key for key in (record.get("legacy_export_key"), previous) if key]))
            record["legacy_export_key"] = previous
        record["key_version"] = 3
        changed = True
    return changed


def _normalize_invoice_automation_task(raw: Dict[str, Any], existing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    account = str(raw.get("account") or (existing or {}).get("account") or "qq_mail").strip()
    if account not in qq_mail_mcp.MAILBOX_CONFIGS:
        raise HTTPException(status_code=400, detail="未知的邮箱账号")
    try:
        day = int(raw.get("day", (existing or {}).get("day", 1)))
        hour = int(raw.get("hour", (existing or {}).get("hour", 9)))
        minute = int(raw.get("minute", (existing or {}).get("minute", 0)))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="归集时间格式不正确") from exc
    if not 1 <= day <= 28 or not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise HTTPException(status_code=400, detail="归集日期应为每月 1–28 日，时间应为有效的小时和分钟")
    extensions = raw.get("extensions", (existing or {}).get("extensions", list(_INVOICE_AUTOMATION_EXTENSIONS)))
    extensions = [str(ext).lower() for ext in (extensions or []) if str(ext).lower() in _INVOICE_AUTOMATION_EXTENSIONS]
    return {
        "id": str((existing or {}).get("id") or uuid.uuid4().hex),
        "account": account,
        "name": str(raw.get("name") or (existing or {}).get("name") or "月度发票归集").strip()[:60] or "月度发票归集",
        "day": day,
        "hour": hour,
        "minute": minute,
        "extensions": extensions or list(_INVOICE_AUTOMATION_EXTENSIONS),
        "keyword": str(raw.get("keyword", (existing or {}).get("keyword") or "")).strip()[:100],
        "enabled": bool(raw.get("enabled", (existing or {}).get("enabled", True))),
        "created_at": str((existing or {}).get("created_at") or datetime.datetime.now().isoformat(timespec="seconds")),
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "last_period": str((existing or {}).get("last_period") or ""),
        "last_attempt_period": str((existing or {}).get("last_attempt_period") or ""),
        "last_attempt_at": str((existing or {}).get("last_attempt_at") or ""),
    }


def _invoice_previous_month_range(now: Optional[datetime.datetime] = None) -> tuple[datetime.date, datetime.date, str]:
    today = (now or datetime.datetime.now()).date()
    first_this_month = today.replace(day=1)
    end = first_this_month - datetime.timedelta(days=1)
    start = end.replace(day=1)
    return start, end, start.strftime("%Y-%m")


def _invoice_automation_due(item, now, period):
    if not item.get("enabled", True) or item.get("last_period") == period:
        return False
    due = now.replace(day=int(item.get("day") or 1), hour=int(item.get("hour") or 0), minute=int(item.get("minute") or 0), second=0, microsecond=0)
    if now < due:
        return False
    # A partial or failed run requires an explicit manual retry; repeated scans can
    # otherwise create unbounded snapshots when a mailbox persistently times out.
    if item.get("last_attempt_period") == period:
        return False
    return True


class InvoiceService:
    def __init__(self, runtime_dir: Path):
        self.runtime_dir = runtime_dir
        self._export_lock = threading.RLock()
        self._automation_lock = threading.RLock()
        self._automation_file = runtime_dir / "data" / "invoice_automation.json"
        self._automation_archive_dir = runtime_dir / "data" / "invoice_auto_collections"
        self._scheduler_task: Optional[asyncio.Task] = None

    def _invoice_export_history_path(self, account: str) -> Path:
        if account not in qq_mail_mcp.MAILBOX_CONFIGS:
            raise HTTPException(status_code=400, detail="未知的邮箱账号")
        folder = self.runtime_dir / "data"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"invoice_export_history_{account}.json"

    def _load_invoice_export_history(self, account: str) -> List[Dict[str, Any]]:
        try:
            records = json.loads(self._invoice_export_history_path(account).read_text(encoding="utf-8"))
            return records if isinstance(records, list) else []
        except (OSError, ValueError):
            return []

    def _save_invoice_export_history(self, account: str, records: List[Dict[str, Any]]) -> None:
        path = self._invoice_export_history_path(account)
        temporary = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            temporary.write_text(json.dumps(records[:1000], ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _prepare_invoice_export(self, payload):
        if payload.account not in qq_mail_mcp.MAILBOX_CONFIGS:
            raise HTTPException(status_code=400, detail="未知的邮箱账号")
        root = qq_mail_mcp.MAILBOX_CONFIGS[payload.account]["attachment_root"].resolve()
        paths = payload.paths or []
        if len(paths) > 5000:
            raise HTTPException(status_code=400, detail="单次最多打包 5000 个文件")
        selected = []
        for raw in paths:
            path = Path(str(raw or "")).resolve()
            if root not in path.parents or not path.is_file():
                raise HTTPException(status_code=400, detail="所选文件已不存在或不属于当前邮箱，请重新扫描")
            if path not in selected:
                selected.append(path)
        if not selected:
            raise HTTPException(status_code=400, detail="请至少选择一个可下载的发票文件")
        if sum(path.stat().st_size for path in selected) > 250 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="所选文件超过 250MB，请分批下载")
        archive = BytesIO()
        used_names = set()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for path in selected:
                name, index = path.name, 1
                while name in used_names:
                    index += 1
                    name = f"{path.stem}_{index}{path.suffix}"
                used_names.add(name)
                bundle.write(path, arcname=name)
        archive.seek(0)
        provided = {str(Path(str(item.get("path") or "")).resolve()): item for item in payload.invoices or [] if isinstance(item, dict)}
        exported_at = datetime.datetime.now().isoformat(timespec="seconds")
        with self._export_lock:
            history = self._load_invoice_export_history(payload.account)
            _repair_invoice_export_history(payload.account, history)
            by_key = {str(item.get("export_key") or ""): item for item in history}
            for path in selected:
                invoice = provided.get(str(path), {})
                key = _invoice_export_key(invoice, path)
                by_key[key] = {
                    **by_key.get(key, {}),
                    "export_key": key, "key_version": 3, "exported_at": exported_at,
                    "filename": path.name, "invoice_code": str(invoice.get("invoice_code") or ""), "invoice_number": str(invoice.get("invoice_number") or qq_mail_mcp.invoice_number_from_values(path.name)),
                    "issuer": str(invoice.get("issuer") or "")[:120], "amount": str(invoice.get("amount") or "")[:40],
                    "issue_time": str(invoice.get("issue_time") or "")[:60], "subject": str(invoice.get("subject") or "")[:200], "path": str(path),
                }
            history = sorted(by_key.values(), key=lambda item: str(item.get("exported_at") or ""), reverse=True)
            self._save_invoice_export_history(payload.account, history)
        return archive

    def _invoice_history_payload(self, account):
        with self._export_lock:
            records = self._load_invoice_export_history(account)
            if _repair_invoice_export_history(account, records):
                records.sort(key=lambda item: str(item.get("exported_at") or ""), reverse=True)
                self._save_invoice_export_history(account, records)
            keys = [key for item in records for key in (item.get("export_key"), item.get("legacy_export_key"), *(item.get("legacy_export_keys") or [])) if key]
            return {"records": records, "count": len(records), "export_keys": keys}

    def _invoice_automation_store(self) -> Dict[str, Any]:
        """读取本地任务库；配置和记录均只保存在当前电脑的数据目录。"""
        with self._automation_lock:
            try:
                payload = json.loads(self._automation_file.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    payload.setdefault("tasks", [])
                    payload.setdefault("collections", [])
                    return payload
            except (OSError, ValueError):
                pass
        return {"version": 1, "tasks": [], "collections": []}

    def _save_invoice_automation_store(self, payload: Dict[str, Any]) -> None:
        with self._automation_lock:
            self._automation_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._automation_file.with_suffix(f".{os.getpid()}.tmp")
            try:
                temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                os.replace(temporary, self._automation_file)
            finally:
                temporary.unlink(missing_ok=True)

    def _invoice_automation_archive_path(self, account: str, period: str, collection_id: str) -> Path:
        safe_period = re.sub(r"[^0-9-]", "", period) or "unknown"
        root = (self._automation_archive_dir / account / safe_period).resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root / f"发票自动归集_{safe_period.replace('-', '')}_{collection_id[:8]}.zip"

    def _run_invoice_automation_task(self, task_id: str, manual: bool = False) -> Dict[str, Any]:
        """扫描上一个自然月，写入持久 ZIP，并把结果快照存入归集历史。"""
        with self._automation_lock:
            store = self._invoice_automation_store()
            task = next((item for item in store["tasks"] if item.get("id") == task_id), None)
            if not task:
                raise HTTPException(status_code=404, detail="自动归集任务不存在")
            task = dict(task)
        start, end, period = _invoice_previous_month_range()
        collection_id = uuid.uuid4().hex
        started_at = datetime.datetime.now().isoformat(timespec="seconds")
        try:
            collected = {}
            with qq_mail_mcp._INVOICE_SCAN_LOCKS[task["account"]]:
                for attempt in range(12):
                    result = qq_mail_mcp.scan_invoices(
                        account=task["account"], since_days=31, extensions=task["extensions"], keyword=task["keyword"],
                        limit=5000, start_date=start.isoformat(), end_date=end.isoformat(),
                    )
                    for row in result.get("invoices") or []:
                        collected[row["path"]] = row
                    if not result.get("timed_out"):
                        break
            result["invoices"] = list(collected.values())
            invoices = result.get("invoices") or []
            archive_path = self._invoice_automation_archive_path(task["account"], period, collection_id)
            used_names: set[str] = set()
            archived_invoices = []
            skipped_invoices = 0
            with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as bundle:
                for row in invoices:
                    path = Path(str(row.get("path") or "")).resolve()
                    root = qq_mail_mcp.MAILBOX_CONFIGS[task["account"]]["attachment_root"].resolve()
                    try:
                        allowed = os.path.commonpath((str(path), str(root))) == str(root)
                    except ValueError:
                        allowed = False
                    if not allowed or not path.is_file():
                        skipped_invoices += 1
                        continue
                    name = path.name
                    if name in used_names:
                        name = f"{path.stem}_{len(used_names) + 1}{path.suffix}"
                    used_names.add(name)
                    bundle.write(path, arcname=name)
                    archived_invoices.append(row)
            invoices = archived_invoices
            # Reuse an existing archive only when every named member has identical bytes.
            def archive_fingerprint(candidate):
                with zipfile.ZipFile(candidate) as source:
                    return sorted((entry.filename, entry.file_size, hashlib.sha256(source.read(entry)).hexdigest())
                                  for entry in source.infolist())
            fingerprint = archive_fingerprint(archive_path)
            for candidate in archive_path.parent.glob("*.zip"):
                if candidate == archive_path:
                    continue
                try:
                    if archive_fingerprint(candidate) == fingerprint:
                        archive_path.unlink()
                        archive_path = candidate
                        break
                except (OSError, zipfile.BadZipFile, RuntimeError):
                    continue
            if skipped_invoices:
                result["warnings"] = list(result.get("warnings") or []) + [f"{skipped_invoices} 个文件已不存在，归集将自动重试"]
            collection = {
                "id": collection_id, "task_id": task_id, "task_name": task["name"], "account": task["account"],
                "period": period, "status": "partial" if result.get("warnings") or result.get("timed_out") else "completed", "manual": manual, "started_at": started_at,
                "completed_at": datetime.datetime.now().isoformat(timespec="seconds"), "archive_path": str(archive_path),
                "archive_name": archive_path.name, "invoice_count": len(invoices), "scanned_mails": int(result.get("scanned_mails") or 0),
                "invoices": [{**row, "export_key": _invoice_export_key(row, Path(str(row.get("path") or "")))} for row in invoices[:500]],
                "error": "；".join(result.get("warnings") or []),
            }
        except Exception as exc:
            collection = {
                "id": collection_id, "task_id": task_id, "task_name": task["name"], "account": task["account"],
                "period": period, "status": "failed", "manual": manual, "started_at": started_at,
                "completed_at": datetime.datetime.now().isoformat(timespec="seconds"), "archive_path": "", "archive_name": "",
                "invoice_count": 0, "scanned_mails": 0, "invoices": [], "error": str(exc)[:600],
            }
        with self._automation_lock:
            store = self._invoice_automation_store()
            store["collections"] = [collection] + [item for item in store["collections"] if item.get("id") != collection_id]
            store["collections"] = store["collections"][:100]
            for item in store["tasks"]:
                if item.get("id") == task_id:
                    if collection["status"] == "completed":
                        item["last_period"] = period
                    # 同一月份的定时任务只尝试一次，避免邮箱不可用时每分钟反复连接。
                    item["last_attempt_period"] = period
                    item["last_attempt_at"] = datetime.datetime.now().isoformat(timespec="seconds")
                    item["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
            self._save_invoice_automation_store(store)
        return collection

    async def _invoice_automation_scheduler_loop(self):
        """每分钟检查一次到期任务；实际扫描在工作线程中执行，避免阻塞 API。"""
        await asyncio.sleep(8)
        while True:
            try:
                now = datetime.datetime.now()
                _, _, period = _invoice_previous_month_range(now)
                store = self._invoice_automation_store()
                due = [
                    item for item in store["tasks"]
                    if _invoice_automation_due(item, now, period)
                ]
                for task in due:
                    try:
                        await asyncio.get_running_loop().run_in_executor(
                            None, functools.partial(self._run_invoice_automation_task, str(task.get("id") or ""), False)
                        )
                    except Exception as exc:
                        print(f"[invoice-automation] task {task.get('id')} failed: {exc}")
            except Exception as exc:
                print(f"[invoice-automation] scheduler failed: {exc}")
            await asyncio.sleep(60)

    async def start_invoice_automation_scheduler(self):
        if os.environ.get("INVOICE_AUTOMATION_SCHEDULER_DISABLED") == "1":
            return
        if self._scheduler_task is None or self._scheduler_task.done():
            self._scheduler_task = asyncio.create_task(self._invoice_automation_scheduler_loop())

    async def stop_invoice_automation_scheduler(self):
        if self._scheduler_task:
            self._scheduler_task.cancel()
            self._scheduler_task = None
