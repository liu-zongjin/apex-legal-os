"""QQ, Tencent enterprise, and NetEase enterprise mailbox HTTP routes."""

from __future__ import annotations

import asyncio
import datetime
import functools
import os
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, NamedTuple, Optional
from urllib.parse import quote

import aiofiles
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from . import qq_mail_mcp
from .mail_invoices import (
    InvoiceService, _INVOICE_AUTOMATION_EXTENSIONS, _invoice_export_key, _normalize_invoice_automation_task,
)


class QQMailInvoiceScanRequest(BaseModel):
    account: str = "qq_mail"
    since_days: int = 30
    start_date: str = ""
    end_date: str = ""
    extensions: List[str] = []
    keyword: str = ""
    limit: int = 2000


class QQMailInvoiceDownloadRequest(BaseModel):
    account: str = "qq_mail"
    paths: List[str] = []
    invoices: List[Dict[str, Any]] = []


class QQMailInvoiceAutomationTaskRequest(BaseModel):
    id: str = ""
    account: str = "qq_mail"
    name: str = "月度发票归集"
    day: int = 1
    hour: int = 9
    minute: int = 0
    extensions: List[str] = []
    keyword: str = ""
    enabled: bool = True


class QQMailOpenFolderRequest(BaseModel):
    account: str = "qq_mail"


class QQMailEnglishClassifyRequest(BaseModel):
    account: str = "qq_mail"
    uids: List[str] = []


class QQMailReadStateRequest(BaseModel):
    account: str = "qq_mail"
    folder: str = "inbox"
    read: bool = True


class QQMailDeleteRequest(BaseModel):
    account: str = "qq_mail"
    folder: str = "inbox"


class QQMailInvoiceCollectRequest(BaseModel):
    limit: int = 30
    keyword: str = ""
    since_days: int = 7
    account: str = "qq_mail"


class MailRoutes(NamedTuple):
    router: APIRouter
    start_invoice_scheduler: Callable[[], Awaitable[None]]
    stop_invoice_scheduler: Callable[[], Awaitable[None]]


def create_router(runtime_dir: Path, *, frontend_dir: Path) -> MailRoutes:
    router = APIRouter()
    invoices = InvoiceService(runtime_dir)

    @router.get("/qq-mail")
    async def qq_mail_page():
        """QQ 邮箱邮件管理页面"""
        file_path = frontend_dir / "qq-mail.html"
        if file_path.exists():
            async with aiofiles.open(str(file_path), mode='r', encoding='utf-8') as f:
                content = await f.read()
            headers = {
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
            return HTMLResponse(content=content, headers=headers)
        else:
            raise HTTPException(status_code=404, detail="QQ 邮箱管理页面不存在")

    @router.post("/api/qq-mail/send")
    async def qq_mail_send(
        account: str = Form("qq_mail"),
        to: str = Form(""),
        cc: str = Form(""),
        bcc: str = Form(""),
        subject: str = Form(""),
        body: str = Form(""),
        body_html: str = Form(""),
        use_cloud_attachments: str = Form("0"),
        use_large_attachments: str = Form("0"),
        attachments: Optional[List[UploadFile]] = File(None),
    ):
        """SMTP 发信：普通附件；网易和 QQ 分别使用各自官方的大附件通道。"""
        loop = asyncio.get_running_loop()
        attachment_items = []
        for item in (attachments or [])[:10]:
            try:
                data = await item.read()
            except Exception:
                continue
            if data:
                attachment_items.append({"filename": item.filename or "attachment", "content": data})
        try:
            result = await loop.run_in_executor(
                None,
                functools.partial(
                    qq_mail_mcp.send_mail,
                    account=account,
                    to=to, cc=cc, bcc=bcc, subject=subject, body=body, body_html=body_html,
                    attachments=attachment_items,
                    use_cloud_attachments=str(use_cloud_attachments or "").strip().lower() in {"1", "true", "yes", "on"},
                    use_large_attachments=str(use_large_attachments or "").strip().lower() in {"1", "true", "yes", "on"},
                ),
            )
        except qq_mail_mcp.QQMailMCPError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return result

    @router.post("/api/qq-mail/drafts")
    async def qq_mail_save_draft(
        account: str = Form("qq_mail"), to: str = Form(""), cc: str = Form(""),
        bcc: str = Form(""), subject: str = Form(""), body: str = Form(""), body_html: str = Form(""),
    ):
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, functools.partial(
                qq_mail_mcp.save_draft, account=account, to=to, cc=cc, bcc=bcc, subject=subject, body=body, body_html=body_html,
            ))
        except qq_mail_mcp.QQMailMCPError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.post("/api/qq-mail/invoices")
    async def qq_mail_invoices(payload: QQMailInvoiceScanRequest):
        """扫描邮件附件中的发票文件并解析开票人、金额、开票时间。"""
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                None,
                functools.partial(
                    qq_mail_mcp.scan_invoices,
                    account=str(payload.account or "qq_mail").strip(),
                    since_days=max(1, min(int(payload.since_days or 30), 365)),
                    extensions=payload.extensions or [],
                    keyword=str(payload.keyword or "").strip(),
                    limit=max(10, min(int(payload.limit or 2000), 5000)),
                    start_date=str(payload.start_date or "").strip(),
                    end_date=str(payload.end_date or "").strip(),
                ),
            )
        except qq_mail_mcp.QQMailMCPError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        for invoice in result.get("invoices") or []:
            if isinstance(invoice, dict) and invoice.get("path"):
                invoice["export_key"] = _invoice_export_key(invoice, Path(str(invoice["path"])))
        return result

    @router.post("/api/qq-mail/invoices/download")
    async def qq_mail_invoice_download(payload: QQMailInvoiceDownloadRequest):
        """Build every selected file and its export history off the API event loop."""
        archive = await asyncio.get_running_loop().run_in_executor(None, functools.partial(invoices._prepare_invoice_export, payload))
        filename = f"邮箱发票_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        from fastapi.responses import StreamingResponse
        return StreamingResponse(archive, media_type="application/zip", headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})

    @router.get("/api/qq-mail/invoices/history")
    async def qq_mail_invoice_export_history(account: str = "qq_mail"):
        return await asyncio.get_running_loop().run_in_executor(None, functools.partial(invoices._invoice_history_payload, account))

    @router.get("/api/qq-mail/invoice-automation")
    async def qq_mail_invoice_automation(account: str = "qq_mail"):
        store = invoices._invoice_automation_store()
        return {
            "tasks": [item for item in store["tasks"] if item.get("account") == account],
            "collections": [item for item in store["collections"] if item.get("account") == account],
        }

    @router.post("/api/qq-mail/invoice-automation")
    async def save_qq_mail_invoice_automation(payload: QQMailInvoiceAutomationTaskRequest):
        with invoices._automation_lock:
            store = invoices._invoice_automation_store()
            existing = next((item for item in store["tasks"] if item.get("id") == payload.id), None) if payload.id else None
            task = _normalize_invoice_automation_task(payload.model_dump(), existing)
            if existing:
                store["tasks"] = [task if item.get("id") == task["id"] else item for item in store["tasks"]]
            else:
                store["tasks"] = [task] + store["tasks"]
            invoices._save_invoice_automation_store(store)
        return {"task": task}

    @router.delete("/api/qq-mail/invoice-automation/{task_id}")
    async def delete_qq_mail_invoice_automation(task_id: str):
        with invoices._automation_lock:
            store = invoices._invoice_automation_store()
            before = len(store["tasks"])
            store["tasks"] = [item for item in store["tasks"] if item.get("id") != task_id]
            if before == len(store["tasks"]):
                raise HTTPException(status_code=404, detail="自动归集任务不存在")
            invoices._save_invoice_automation_store(store)
        return {"success": True}

    @router.post("/api/qq-mail/invoice-automation/{task_id}/run")
    async def run_qq_mail_invoice_automation(task_id: str):
        loop = asyncio.get_running_loop()
        return {"collection": await loop.run_in_executor(None, functools.partial(invoices._run_invoice_automation_task, task_id, True))}

    @router.get("/api/qq-mail/invoice-automation/collections/{collection_id}/download")
    async def download_qq_mail_invoice_automation_archive(collection_id: str):
        collection = next((item for item in invoices._invoice_automation_store()["collections"] if item.get("id") == collection_id), None)
        archive = Path(str((collection or {}).get("archive_path") or "")).resolve()
        try:
            allowed = os.path.commonpath((str(archive), str(invoices._automation_archive_dir.resolve()))) == str(invoices._automation_archive_dir.resolve())
        except ValueError:
            allowed = False
        if not collection or not allowed or not archive.is_file():
            raise HTTPException(status_code=404, detail="本地归集压缩包不存在")
        return FileResponse(str(archive), media_type="application/zip", filename=archive.name)

    @router.post("/api/qq-mail/open-folder")
    async def qq_mail_open_folder(payload: QQMailOpenFolderRequest):
        """在访达中打开附件保存目录。"""
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                None, qq_mail_mcp.open_attachment_folder, str(payload.account or "qq_mail").strip()
            )
        except qq_mail_mcp.QQMailMCPError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return result

    @router.get("/api/qq-mail/file")
    async def qq_mail_file(path: str = ""):
        """预览已下载的邮箱附件。仅允许读取邮箱附件目录内的文件。"""
        if not path:
            raise HTTPException(status_code=400, detail="缺少文件路径")
        requested = Path(path).resolve()
        allowed_roots = tuple(
            config["attachment_root"].resolve()
            for config in qq_mail_mcp.MAILBOX_CONFIGS.values()
        ) + ((qq_mail_mcp._BASE_DIR / "uploads" / "邮箱附件").resolve(),)
        if not any(requested == root or root in requested.parents for root in allowed_roots):
            raise HTTPException(status_code=403, detail="仅允许预览邮箱附件目录内的文件")
        if not requested.is_file():
            raise HTTPException(status_code=404, detail="文件不存在")
        content_types = {
            ".pdf": "application/pdf",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
        }
        media_type = content_types.get(requested.suffix.lower())
        if media_type is None:
            raise HTTPException(status_code=415, detail="该文件类型不支持在线预览")
        return FileResponse(str(requested), media_type=media_type, filename=requested.name)

    @router.get("/api/qq-mail/status")
    async def qq_mail_status(account: str = "qq_mail"):
        """邮箱连接状态与收件箱统计（支持 QQ、腾讯企业和网易企业邮箱）。"""
        loop = asyncio.get_running_loop()
        try:
            status = await loop.run_in_executor(None, qq_mail_mcp.check_connection, account)
        except qq_mail_mcp.QQMailMCPError as exc:
            return {"ok": False, "message": str(exc), "total": 0}
        return {"ok": True, "total": int(status.get("total") or 0), "latency_ms": int(status.get("latency_ms") or 0)}

    @router.get("/api/qq-mail/mails")
    async def qq_mail_mails(limit: int = 30, unread_only: bool = False, keyword: str = "", account: str = "qq_mail", folder: str = "inbox"):
        """收件箱、已发送或草稿箱邮件列表（最新在前）。"""
        limit = max(1, min(int(limit or 30), 100))
        loop = asyncio.get_running_loop()
        try:
            mails = await loop.run_in_executor(
                None,
                functools.partial(
                    qq_mail_mcp.list_mails,
                    limit=limit, unread_only=bool(unread_only), keyword=str(keyword or "").strip(),
                    account=account, folder=folder,
                ),
            )
        except qq_mail_mcp.QQMailMCPError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"mails": mails, "count": len(mails)}

    @router.post("/api/qq-mail/mails/classify-english")
    async def qq_mail_classify_english(payload: QQMailEnglishClassifyRequest):
        """按标题和正文识别全英文收件箱邮件；结果写入邮件摘要缓存。"""
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, functools.partial(
                qq_mail_mcp.classify_inbox_english, payload.uids, str(payload.account or "qq_mail"),
            ))
        except qq_mail_mcp.QQMailMCPError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"mostly_english": result}

    @router.get("/api/qq-mail/mails/{uid}")
    async def qq_mail_detail(uid: str, account: str = "qq_mail", folder: str = "inbox"):
        """指定邮件正文与附件清单。"""
        loop = asyncio.get_running_loop()
        try:
            detail = await loop.run_in_executor(None, functools.partial(qq_mail_mcp.read_mail, uid, account=account, folder=folder))
        except qq_mail_mcp.QQMailMCPError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return detail

    @router.get("/api/qq-mail/contacts")
    async def qq_mail_contacts(account: str = "qq_mail", query: str = ""):
        loop = asyncio.get_running_loop()
        try:
            contacts = await loop.run_in_executor(None, functools.partial(qq_mail_mcp.list_contacts, account, query))
        except qq_mail_mcp.QQMailMCPError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"contacts": contacts}

    @router.post("/api/qq-mail/mails/{uid}/read-state")
    async def qq_mail_read_state(uid: str, payload: QQMailReadStateRequest):
        """设置收件箱邮件的已读/未读状态。"""
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, functools.partial(
                qq_mail_mcp.set_mail_read, uid, bool(payload.read),
                account=str(payload.account or "qq_mail"), folder=str(payload.folder or "inbox"),
            ))
        except qq_mail_mcp.QQMailMCPError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.post("/api/qq-mail/mails/{uid}/collect")
    async def qq_mail_collect(uid: str, account: str = Form("qq_mail"), attachment_ids: Optional[List[str]] = Form(None)):
        """下载指定邮件的全部附件到本机。"""
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, functools.partial(
                qq_mail_mcp.collect_attachments, uid, account=account, attachment_ids=attachment_ids,
            ))
        except qq_mail_mcp.QQMailMCPError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return result

    @router.delete("/api/qq-mail/mails/{uid}")
    async def qq_mail_delete(uid: str, payload: QQMailDeleteRequest):
        """删除当前文件夹中的一封邮件。"""
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, functools.partial(
                qq_mail_mcp.delete_mail, uid, account=payload.account, folder=payload.folder,
            ))
        except qq_mail_mcp.QQMailMCPError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.post("/api/qq-mail/collect-invoices")
    async def qq_mail_collect_invoices(payload: QQMailInvoiceCollectRequest):
        """批量收集近期邮件中的发票、账单、回执等附件。"""
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                None,
                functools.partial(
                    qq_mail_mcp.collect_invoice_attachments,
                    limit=max(1, min(int(payload.limit or 30), 100)),
                    keyword=str(payload.keyword or "").strip(),
                    since_days=max(1, min(int(payload.since_days or 7), 90)),
                    account=str(payload.account or "qq_mail").strip(),
                ),
            )
        except qq_mail_mcp.QQMailMCPError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return result

    return MailRoutes(router, invoices.start_invoice_automation_scheduler, invoices.stop_invoice_automation_scheduler)
