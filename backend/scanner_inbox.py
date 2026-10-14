"""Read-only integration for a fixed Fuji Xerox CentreWare scan mailbox.

The printer is a legacy HTTP Basic-auth appliance.  Keep its protocol at this
boundary: browser code never sees the credentials or talks to the printer.
"""
from __future__ import annotations

import asyncio
import ast
import datetime as dt
import io
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import quote, urljoin

import httpx
from bs4 import BeautifulSoup
from fastapi import HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from .case_automation import get_folder_binding, store_case_file
from .case_files import prepare_ai_attachment_paths


PRINTER_BASE_URL = "http://192.168.20.253/"
MAILBOX_ID = "001"
KEYCHAIN_SERVICE = "APEX 扫描收件箱 · 001"
KEYCHAIN_ACCOUNT = "centreware-mailbox-001"
MAX_DOCUMENTS = 500
MAX_DOWNLOADS = 20
PREVIEW_CACHE_SECONDS = 300
PREVIEW_CACHE_MAX_ITEMS = 5
PREVIEW_CACHE_MAX_BYTES = 60 * 1024 * 1024
TEMP_DOWNLOAD_SECONDS = 30 * 60


class ScannerInboxError(RuntimeError):
    status_code = 502


class ScannerNotConfigured(ScannerInboxError):
    status_code = 409


class ScannerAuthenticationError(ScannerInboxError):
    status_code = 401


class ScannerProtocolError(ScannerInboxError):
    status_code = 502


class ScannerUnavailable(ScannerInboxError):
    status_code = 503


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _safe_name(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", str(value or "")).strip(" .")
    return cleaned[:120] or fallback


def _attachment_header(filename: str) -> str:
    """Content-Disposition with a latin-1 ASCII fallback and RFC 5987 UTF-8 name."""
    ascii_fallback = _safe_name(filename.encode("ascii", "ignore").decode() or "APEX-scan", "APEX-scan.pdf")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}"


def _keychain_read() -> dict[str, str] | None:
    completed = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w"],
        capture_output=True, text=True, timeout=8,
    )
    if completed.returncode != 0:
        return None
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict) or not value.get("username") or "password" not in value:
        return None
    return {"username": str(value["username"]), "password": str(value["password"])}


def _keychain_write(username: str, password: str) -> None:
    payload = json.dumps({"username": username, "password": password}, ensure_ascii=False)
    completed = subprocess.run(
        ["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w", payload],
        capture_output=True, text=True, timeout=8,
    )
    if completed.returncode != 0:
        raise ScannerInboxError("无法写入 macOS 钥匙串")


def _keychain_delete() -> None:
    subprocess.run(
        ["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT],
        capture_output=True, text=True, timeout=8,
    )


@dataclass(frozen=True)
class ScanDocument:
    source_id: str
    name: str
    scanned_at: str
    compression: str
    pages: int | None
    document_type: str
    selection_name: str
    selection_value: str

    def public(self, imports: dict[str, list[str]], notes: dict[str, str] | None = None, status: str | None = None) -> dict[str, Any]:
        data = {
            "source_id": self.source_id,
            "name": self.name,
            "scanned_at": self.scanned_at,
            "compression": self.compression,
            "pages": self.pages,
            "document_type": self.document_type,
            "imported_to": imports.get(self.source_id, []),
            "note": (notes or {}).get(self.source_id, ""),
        }
        if status:
            data["status"] = status
        return data


class CentreWareClient:
    """Small adapter for the pages exposed by CentreWare Internet Services."""

    def __init__(self, credentials: dict[str, str], *, transport: httpx.AsyncBaseTransport | None = None):
        self._credentials = credentials
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=PRINTER_BASE_URL,
            auth=httpx.BasicAuth(self._credentials["username"], self._credentials["password"]),
            follow_redirects=True,
            timeout=httpx.Timeout(15.0, connect=5.0),
            transport=self._transport,
        )

    @staticmethod
    def _check(response: httpx.Response) -> None:
        if response.status_code == 401:
            raise ScannerAuthenticationError("扫描盘账号或密码不正确")
        if response.status_code >= 400:
            raise ScannerProtocolError(f"扫描盘返回异常状态：{response.status_code}")

    async def _mailbox_page(self) -> tuple[httpx.AsyncClient, httpx.Response]:
        client = self._client()
        try:
            # The device establishes its legacy scan context through scan.htm.
            response = await client.get("scan.htm")
            self._check(response)
            response = await client.get("scpblst.htm")
            self._check(response)
            # CentreWare's own PBLST page submits these fields from doLst(1)
            # when opening mailbox 001.  This creates an APEX-only session;
            # it has no dependency on Safari tabs, cookies, or saved state.
            response = await client.post("PBDOCLST.cmd", data={
                "BOX": str(int(MAILBOX_ID)), "ORD": "DD", "SET": "1",
                "LTOP": "1", "LNUM": "100", "PAGE": "1",
            })
            self._check(response)
            return client, response
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
            await client.aclose()
            raise ScannerUnavailable("无法连接局域网扫描盘，请确认当前 Mac 已接入办公网络") from exc
        except Exception:
            await client.aclose()
            raise

    @staticmethod
    def _documents_from_html(content: str) -> tuple[list[ScanDocument], BeautifulSoup]:
        soup = BeautifulSoup(content, "html.parser")
        if "Login failed" in soup.get_text(" ", strip=True):
            raise ScannerAuthenticationError("扫描盘账号或密码不正确")
        # CentreWare 1.8 keeps the file rows in a JavaScript `lst` array and
        # renders them client-side.  HTTP clients therefore must parse this
        # source data instead of looking for an already-built HTML table.
        script_text = "\n".join(script.get_text() for script in soup.select("script"))
        match = re.search(r"\bvar\s+lst\s*=\s*(\[[\s\S]*?\]);", script_text)
        if match:
            try:
                rows = ast.literal_eval(match.group(1))
            except (SyntaxError, ValueError) as exc:
                raise ScannerProtocolError("无法解析扫描盘文件列表") from exc
            compression_labels = ["-", "MH", "MR", "MMR", "JBIG", "JPEG", "未压缩"]
            type_labels = {1: "打印", 2: "扫描", 3: "传真", 4: "邮件"}
            documents = []
            for row in rows:
                if not isinstance(row, (list, tuple)) or len(row) < 6:
                    continue
                source_id = str(row[0])
                pages = int(row[3]) if str(row[3]).isdigit() else None
                compression_index = int(row[2]) if str(row[2]).isdigit() else 0
                type_index = int(row[4]) if str(row[4]).isdigit() else 0
                documents.append(ScanDocument(
                    source_id=source_id,
                    name=_safe_name(str(row[5]), source_id),
                    scanned_at=str(row[1]),
                    compression=compression_labels[compression_index] if 0 <= compression_index < len(compression_labels) else "",
                    pages=pages,
                    document_type=type_labels.get(type_index, "扫描"),
                    selection_name="DOC",
                    selection_value=source_id,
                ))
            return documents, soup
        documents: list[ScanDocument] = []
        for row in soup.select("tr"):
            checkbox = row.select_one('input[type="checkbox"]')
            cells = [cell.get_text(" ", strip=True) for cell in row.select("td")]
            if not checkbox or len(cells) < 4:
                continue
            # CentreWare 1.8 renders the table as: checkbox, document number,
            # filename, timestamp, compression, pages, type, … .  Prefer these
            # positions over generic number matching because filenames are often
            # digit-only timestamps as well.
            numeric = cells[1] if len(cells) > 1 and re.fullmatch(r"\d{1,8}", cells[1] or "") else next((value for value in cells if re.fullmatch(r"\d{1,8}", value or "")), "")
            if not numeric:
                continue
            timestamp = cells[3] if len(cells) > 3 and re.fullmatch(r"\d{4}/\d{2}/\d{2}\s+\d{1,2}:\d{2}", cells[3] or "") else next((value for value in cells if re.fullmatch(r"\d{4}/\d{2}/\d{2}\s+\d{1,2}:\d{2}", value or "")), "")
            compression = cells[4] if len(cells) > 4 else next((value for value in cells if value.upper() in {"JPEG", "TIFF", "PDF", "XPS"}), "")
            page_text = cells[5] if len(cells) > 5 else ""
            name = cells[2] if len(cells) > 2 else numeric
            document_type = cells[6] if len(cells) > 6 else "扫描"
            documents.append(ScanDocument(
                source_id=numeric,
                name=_safe_name(name, numeric),
                scanned_at=timestamp,
                compression=compression,
                pages=int(page_text) if page_text.isdigit() else None,
                document_type=document_type or "扫描",
                selection_name=str(checkbox.get("name") or ""),
                selection_value=str(checkbox.get("value") or numeric),
            ))
        if not documents and "信箱文件列表" not in soup.get_text(" ", strip=True):
            raise ScannerProtocolError("无法识别扫描盘返回的文件列表")
        return documents, soup

    async def list_documents(self) -> list[ScanDocument]:
        client, response = await self._mailbox_page()
        try:
            documents, _ = self._documents_from_html(response.text)
            return documents[:MAX_DOCUMENTS]
        finally:
            await client.aclose()

    async def download_pdf(self, source_id: str) -> tuple[str, bytes]:
        client, response = await self._mailbox_page()
        try:
            documents, soup = self._documents_from_html(response.text)
            document = next((item for item in documents if item.source_id == str(source_id)), None)
            if not document:
                raise HTTPException(status_code=404, detail="扫描文件已不在信箱中")
            script_text = "\n".join(script.get_text() for script in soup.select("script"))
            legacy_box = re.search(r"\bvar\s+box\s*=\s*(\[[\s\S]*?\]);", script_text)
            if legacy_box:
                try:
                    box = ast.literal_eval(legacy_box.group(1))
                except (SyntaxError, ValueError) as exc:
                    raise ScannerProtocolError("无法解析扫描盘信箱参数") from exc
                if not isinstance(box, (list, tuple)) or len(box) < 3:
                    raise ScannerProtocolError("扫描盘未提供信箱参数")
                extracted = await client.get("PBDOCLNK.cmd", params={
                    "BOX": str(box[0]), "PWD": str(box[1]), "ORD": str(box[2]),
                    "DGACNT": "", "GACNT": "", "ACNTUID": "",
                    "DOC": f"{document.source_id}/", "FORM": "PDF", "PAGE": "",
                    "SMNL": "0", "HCMP": "0", "ICMP": str(box[5] if len(box) > 5 else 0), "NCOLOR": "false",
                })
                self._check(extracted)
                if extracted.content.startswith(b"%PDF-"):
                    return f"扫描_{document.source_id}_{document.name}.pdf", extracted.content
                # This CentreWare generation returns an HTML relay page first.
                # Its JavaScript `info` array contains a short-lived, same-device
                # PDF link.  Follow it using the same APEX-owned HTTP session.
                relay_scripts = "\n".join(script.get_text() for script in BeautifulSoup(extracted.text, "html.parser").select("script"))
                relay_info = re.search(r"\bvar\s+info\s*=\s*(\[[\s\S]*?\]);", relay_scripts)
                if not relay_info:
                    raise ScannerProtocolError("扫描盘未返回 PDF；请在设备页面确认该文件仍可取出")
                try:
                    links = ast.literal_eval(relay_info.group(1))
                    link = next((str(row[4]) for row in links if isinstance(row, (list, tuple)) and len(row) >= 5 and str(row[1]) == document.source_id), "")
                except (SyntaxError, ValueError, TypeError) as exc:
                    raise ScannerProtocolError("无法解析扫描盘 PDF 取件链接") from exc
                if not link or not link.startswith("/") or link.startswith("//"):
                    raise ScannerProtocolError("扫描盘返回了无效的 PDF 取件链接")
                pdf_response = await client.get(link)
                self._check(pdf_response)
                if not pdf_response.content.startswith(b"%PDF-"):
                    raise ScannerProtocolError("扫描盘未返回 PDF；请在设备页面确认该文件仍可取出")
                return f"扫描_{document.source_id}_{document.name}.pdf", pdf_response.content
            form = next((item for item in soup.select("form") if item.select_one('input[type="checkbox"]')), None)
            if not form:
                raise ScannerProtocolError("扫描盘未提供文件取出表单")
            payload: dict[str, str] = {}
            for field in form.select("input[type=hidden]"):
                if field.get("name"):
                    payload[str(field["name"])] = str(field.get("value") or "")
            if not document.selection_name:
                raise ScannerProtocolError("扫描盘未提供文件选择参数")
            payload[document.selection_name] = document.selection_value
            pdf_select = next((select for select in form.select("select") if "PDF" in select.get_text(" ", strip=True).upper()), None)
            if pdf_select and pdf_select.get("name"):
                option = next((item for item in pdf_select.select("option") if "PDF" in item.get_text(" ", strip=True).upper()), None)
                if option:
                    payload[str(pdf_select["name"])] = str(option.get("value") or option.get_text(" ", strip=True))
            submit = next((item for item in form.select('input[type="submit"],button') if "文件取出" in item.get_text(" ", strip=True) or "文件取出" in str(item.get("value") or "")), None)
            if submit and submit.get("name"):
                payload[str(submit["name"])] = str(submit.get("value") or "1")
            action = str(form.get("action") or response.request.url.path)
            target = urljoin(str(response.url), action)
            method = str(form.get("method") or "get").strip().lower()
            extracted = await (client.post(target, data=payload) if method == "post" else client.get(target, params=payload))
            self._check(extracted)
            content = extracted.content
            if not content.startswith(b"%PDF-"):
                raise ScannerProtocolError("扫描盘未返回 PDF；请在设备页面确认该文件仍可取出")
            return f"扫描_{document.source_id}_{document.name}.pdf", content
        finally:
            await client.aclose()


def _merge_with_snapshot(
    latest: list[ScanDocument],
    snapshot: list[ScanDocument],
    labels: dict[str, list[str]],
    notes: dict[str, str],
) -> tuple[list[dict[str, Any]], int, int]:
    """Compare a live mailbox list against the persisted snapshot.

    Files that only exist on the device are marked "new"; files that existed
    in the snapshot but are gone from the device stay listed and are marked
    "deleted" so the user can see what changed while APEX was closed.
    Snapshot order is preserved for the deleted tail.
    """
    snapshot_ids = {item.source_id for item in snapshot}
    snapshot_by_id = {item.source_id: item for item in snapshot}
    latest_ids = {item.source_id for item in latest}
    items: list[dict[str, Any]] = [
        item.public(labels, notes, status=None if item.source_id in snapshot_ids else "new")
        for item in latest
    ]
    deleted = [snapshot_by_id[item.source_id] for item in snapshot if item.source_id not in latest_ids]
    for item in deleted:
        items.append(item.public(labels, notes, status="deleted"))
    new_count = len(latest) - len(snapshot_ids & latest_ids)
    return items, new_count, len(deleted)


def register_scanner_inbox_routes(
    app: Any,
    get_db: Callable[[], Any],
    frontend_dir: Path,
    *,
    parse_file: Callable[[Path, bool], Any],
    require_action: Callable[[Request], None] | None = None,
    client_factory: Callable[[dict[str, str]], CentreWareClient] = CentreWareClient,
) -> None:
    def guard(request: Request) -> None:
        if require_action:
            require_action(request)

    def ensure_schema() -> None:
        with get_db() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS scanner_inbox_imports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mailbox_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                destination_key TEXT NOT NULL,
                destination_label TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                UNIQUE(mailbox_id, source_id, destination_key)
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_scanner_inbox_source ON scanner_inbox_imports(mailbox_id, source_id)")
            conn.execute("""CREATE TABLE IF NOT EXISTS scanner_inbox_notes (
                mailbox_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                PRIMARY KEY(mailbox_id, source_id)
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS scanner_inbox_snapshot (
                mailbox_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                name TEXT NOT NULL,
                scanned_at TEXT NOT NULL DEFAULT '',
                compression TEXT NOT NULL DEFAULT '',
                pages INTEGER,
                document_type TEXT NOT NULL DEFAULT '',
                selection_name TEXT NOT NULL DEFAULT '',
                selection_value TEXT NOT NULL DEFAULT '',
                position INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(mailbox_id, source_id)
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS scanner_inbox_snapshot_meta (
                mailbox_id TEXT PRIMARY KEY,
                fetched_at TEXT NOT NULL
            )""")
            conn.commit()

    ensure_schema()

    # These caches live only in the APEX process: no files, database rows, or
    # device changes are created.  They make repeatedly viewing the same PDF
    # responsive without background polling.  The mailbox file list itself is
    # persisted in the database as a snapshot so that reopening this tool shows
    # the last known list before the printer is reachable again.
    preview_cache: dict[str, tuple[float, bytes]] = {}
    # Staged files handed out as one-time downloads when the user picks the
    # "individual files" mode for multiple scans.
    temp_downloads: dict[str, dict[str, Any]] = {}

    def clear_ephemeral_cache() -> None:
        preview_cache.clear()
        for token in list(temp_downloads):
            entry = temp_downloads.pop(token, None)
            if entry:
                Path(entry["path"]).unlink(missing_ok=True)
        with get_db() as conn:
            conn.execute("DELETE FROM scanner_inbox_snapshot WHERE mailbox_id=?", (MAILBOX_ID,))
            conn.execute("DELETE FROM scanner_inbox_snapshot_meta WHERE mailbox_id=?", (MAILBOX_ID,))
            conn.commit()

    def save_snapshot(documents: list[ScanDocument]) -> str:
        fetched_at = _now()
        with get_db() as conn:
            conn.execute("DELETE FROM scanner_inbox_snapshot WHERE mailbox_id=?", (MAILBOX_ID,))
            conn.execute("DELETE FROM scanner_inbox_snapshot_meta WHERE mailbox_id=?", (MAILBOX_ID,))
            conn.executemany(
                """INSERT INTO scanner_inbox_snapshot(
                    mailbox_id,source_id,name,scanned_at,compression,pages,
                    document_type,selection_name,selection_value,position
                ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                [
                    (MAILBOX_ID, doc.source_id, doc.name, doc.scanned_at, doc.compression, doc.pages,
                     doc.document_type, doc.selection_name, doc.selection_value, index)
                    for index, doc in enumerate(documents)
                ],
            )
            conn.execute("INSERT INTO scanner_inbox_snapshot_meta(mailbox_id,fetched_at) VALUES(?,?)", (MAILBOX_ID, fetched_at))
            conn.commit()
        return fetched_at

    def load_snapshot() -> tuple[list[ScanDocument], str | None]:
        with get_db() as conn:
            meta = conn.execute("SELECT fetched_at FROM scanner_inbox_snapshot_meta WHERE mailbox_id=?", (MAILBOX_ID,)).fetchone()
            rows = conn.execute(
                "SELECT source_id,name,scanned_at,compression,pages,document_type,selection_name,selection_value FROM scanner_inbox_snapshot WHERE mailbox_id=? ORDER BY position",
                (MAILBOX_ID,),
            ).fetchall()
        documents = [
            ScanDocument(
                source_id=str(row["source_id"]),
                name=str(row["name"]),
                scanned_at=str(row["scanned_at"]),
                compression=str(row["compression"]),
                pages=row["pages"],
                document_type=str(row["document_type"]),
                selection_name=str(row["selection_name"]),
                selection_value=str(row["selection_value"]),
            )
            for row in rows
        ]
        return documents, (str(meta["fetched_at"]) if meta else None)

    async def preview_content(source_id: str) -> bytes:
        now = time.monotonic()
        cached = preview_cache.get(source_id)
        if cached and cached[0] > now:
            return cached[1]
        for cached_id, (expires_at, _) in list(preview_cache.items()):
            if expires_at <= now:
                preview_cache.pop(cached_id, None)
        _, content = await client_factory(credentials()).download_pdf(source_id)
        if len(content) <= PREVIEW_CACHE_MAX_BYTES:
            while len(preview_cache) >= PREVIEW_CACHE_MAX_ITEMS:
                oldest_id = min(preview_cache, key=lambda item: preview_cache[item][0])
                preview_cache.pop(oldest_id, None)
            preview_cache[source_id] = (time.monotonic() + PREVIEW_CACHE_SECONDS, content)
        return content

    def credentials() -> dict[str, str]:
        value = _keychain_read()
        if not value:
            raise ScannerNotConfigured("请先在打印机扫描盘中配置 001 信箱凭据")
        return value

    def import_labels() -> dict[str, list[str]]:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT source_id,destination_label FROM scanner_inbox_imports WHERE mailbox_id=? ORDER BY id DESC", (MAILBOX_ID,)
            ).fetchall()
        result: dict[str, list[str]] = {}
        for row in rows:
            result.setdefault(str(row["source_id"]), []).append(str(row["destination_label"]))
        return result

    def document_notes() -> dict[str, str]:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT source_id,note FROM scanner_inbox_notes WHERE mailbox_id=? AND TRIM(note)<>''", (MAILBOX_ID,)
            ).fetchall()
        return {str(row["source_id"]): str(row["note"]) for row in rows}

    def record_import(source_id: str, destination_key: str, destination_label: str, *, ignore_duplicate: bool = False) -> None:
        with get_db() as conn:
            try:
                conn.execute(
                    "INSERT INTO scanner_inbox_imports(mailbox_id,source_id,destination_key,destination_label,imported_at) VALUES(?,?,?,?,?)",
                    (MAILBOX_ID, source_id, destination_key, destination_label, _now()),
                )
                conn.commit()
            except Exception as exc:
                if "UNIQUE constraint failed" in str(exc):
                    if ignore_duplicate:
                        return
                    raise HTTPException(status_code=409, detail="该扫描件已导入到相同目标") from exc
                raise

    async def files_for(source_ids: list[str]) -> list[tuple[str, Path]]:
        values = list(dict.fromkeys(str(item) for item in source_ids if str(item).strip()))
        if not values or len(values) > MAX_DOWNLOADS:
            raise HTTPException(status_code=400, detail=f"请选择 1 至 {MAX_DOWNLOADS} 个扫描文件")
        client = client_factory(credentials())
        root = Path(tempfile.mkdtemp(prefix="apex-scanner-inbox-"))
        try:
            results: list[tuple[str, Path]] = []
            for index, source_id in enumerate(values):
                filename, content = await client.download_pdf(source_id)
                target = root / f"{index:02d}_{_safe_name(filename, source_id + '.pdf')}"
                target.write_bytes(content)
                os.chmod(target, 0o600)
                results.append((source_id, target))
            return results
        except Exception:
            shutil.rmtree(root, ignore_errors=True)
            raise

    def cleanup_files(items: list[tuple[str, Path]]) -> None:
        if items:
            shutil.rmtree(items[0][1].parent, ignore_errors=True)

    def prune_temp_downloads() -> None:
        now = time.monotonic()
        for token in [token for token, entry in temp_downloads.items() if entry["expires_at"] <= now]:
            entry = temp_downloads.pop(token, None)
            if entry:
                path = Path(entry["path"])
                path.unlink(missing_ok=True)
                try:
                    path.parent.rmdir()
                except OSError:
                    pass

    @app.get("/scanner-inbox")
    async def scanner_inbox_page():
        page = frontend_dir / "scanner-inbox.html"
        if not page.is_file():
            raise HTTPException(status_code=404, detail="打印机扫描盘页面不存在")
        return StreamingResponse(io.BytesIO(page.read_bytes()), media_type="text/html", headers={"Cache-Control": "no-store"})

    @app.get("/api/scanner-inbox/status")
    async def scanner_status(request: Request):
        guard(request)
        return {"configured": bool(_keychain_read()), "printer": "ApeosPort-V C5575 T2", "mailbox_id": MAILBOX_ID, "address": "192.168.20.253"}

    @app.put("/api/scanner-inbox/settings")
    async def scanner_settings(request: Request):
        guard(request)
        body = await request.json()
        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        if not username:
            raise HTTPException(status_code=400, detail="请填写扫描盘账号")
        # Verify first.  A mistyped replacement must not overwrite the last
        # working Keychain record or leave the user stranded in a bad state.
        try:
            documents = await client_factory({"username": username, "password": password}).list_documents()
        except ScannerInboxError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        _keychain_write(username, password)
        save_snapshot(documents)
        preview_cache.clear()
        return {"ok": True, "configured": True, "document_count": len(documents)}

    @app.delete("/api/scanner-inbox/settings")
    async def scanner_settings_delete(request: Request):
        guard(request)
        _keychain_delete()
        clear_ephemeral_cache()
        return {"ok": True, "configured": False}

    @app.get("/api/scanner-inbox/documents")
    async def scanner_documents(request: Request, refresh: bool = False, snapshot: bool = False):
        guard(request)
        labels = import_labels()
        notes = document_notes()
        try:
            if snapshot:
                # Fast path used on page open: show the last known list
                # immediately, before the printer is contacted.
                documents, fetched_at = load_snapshot()
                return {
                    "items": [item.public(labels, notes) for item in documents],
                    "mailbox_id": MAILBOX_ID,
                    "fetched_at": fetched_at,
                    "from_snapshot": True,
                    "new_count": 0,
                    "deleted_count": 0,
                }
            # Sync path: compare the live mailbox against the persisted
            # snapshot so new scans are flagged and files removed on the
            # device stay listed with a "deleted" status.
            snapshot_documents, snapshot_fetched_at = load_snapshot()
            documents = await client_factory(credentials()).list_documents()
            fetched_at = save_snapshot(documents)
            items, new_count, deleted_count = _merge_with_snapshot(documents, snapshot_documents, labels, notes)
            return {
                "items": items,
                "mailbox_id": MAILBOX_ID,
                "fetched_at": fetched_at,
                "cached": False,
                "from_snapshot": False,
                "new_count": new_count,
                "deleted_count": deleted_count,
            }
        except ScannerNotConfigured as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        except ScannerInboxError as exc:
            # Printer unreachable: keep showing the last known snapshot and
            # report the reason through sync_error so the page does not go
            # blank just because the appliance is offline.
            documents, fetched_at = load_snapshot()
            return {
                "items": [item.public(labels, notes) for item in documents],
                "mailbox_id": MAILBOX_ID,
                "fetched_at": fetched_at or snapshot_fetched_at,
                "cached": True,
                "from_snapshot": True,
                "new_count": 0,
                "deleted_count": 0,
                "sync_error": str(exc),
            }

    @app.get("/api/scanner-inbox/preview/{source_id}")
    async def scanner_preview(source_id: str, request: Request):
        """Stream a printer file for in-app viewing without persisting it."""
        guard(request)
        if not re.fullmatch(r"\d{1,8}", source_id):
            raise HTTPException(status_code=400, detail="扫描文件编号无效")
        try:
            content = await preview_content(source_id)
            return Response(
                content=content,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": "inline; filename=APEX-scan-preview.pdf",
                    "Cache-Control": "no-store",
                },
            )
        except ScannerInboxError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @app.put("/api/scanner-inbox/notes")
    async def scanner_note(request: Request):
        guard(request)
        body = await request.json()
        source_id = str(body.get("source_id") or "").strip()
        note = str(body.get("note") or "").strip()
        if not source_id or len(source_id) > 80:
            raise HTTPException(status_code=400, detail="扫描文件编号无效")
        if len(note) > 2000:
            raise HTTPException(status_code=400, detail="备注不能超过 2000 个字符")
        with get_db() as conn:
            if note:
                conn.execute(
                    """INSERT INTO scanner_inbox_notes(mailbox_id,source_id,note,updated_at) VALUES(?,?,?,?)
                       ON CONFLICT(mailbox_id,source_id) DO UPDATE SET note=excluded.note,updated_at=excluded.updated_at""",
                    (MAILBOX_ID, source_id, note, _now()),
                )
            else:
                conn.execute("DELETE FROM scanner_inbox_notes WHERE mailbox_id=? AND source_id=?", (MAILBOX_ID, source_id))
            conn.commit()
        return {"ok": True, "source_id": source_id, "note": note}

    @app.post("/api/scanner-inbox/download")
    async def scanner_download(request: Request):
        guard(request)
        body = await request.json()
        source_ids = body.get("source_ids") if isinstance(body.get("source_ids"), list) else []
        mode = str(body.get("mode") or "zip").strip().lower()
        if mode not in {"zip", "files"}:
            mode = "zip"
        try:
            items = await files_for(source_ids)
            if mode == "files":
                # 不直接把单个 PDF 的 POST 响应转成 blob：WKWebView 会把 blob
                # 当作可预览页面打开，而不会进入其原生下载流程。无论数量多少，
                # 都先给出带 ``attachment`` 响应头的一次性 GET 链接。
                prune_temp_downloads()
                entries: list[dict[str, str]] = []
                for source_id, path in items:
                    token = secrets.token_urlsafe(24)
                    temp_downloads[token] = {"expires_at": time.monotonic() + TEMP_DOWNLOAD_SECONDS, "path": str(path)}
                    entries.append({"name": re.sub(r"^\d+_", "", path.name), "url": f"/api/scanner-inbox/download-file/{token}"})
                    record_import(source_id, "download", "已下载到本机", ignore_duplicate=True)
                return {"mode": "files", "files": entries}
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
                for _, path in items:
                    package.write(path, arcname=re.sub(r"^\d+_", "", path.name))
            archive.seek(0)
            for source_id, _ in items:
                record_import(source_id, "download", "已下载到本机", ignore_duplicate=True)
            return StreamingResponse(
                archive,
                media_type="application/zip",
                headers={
                    # HTTP response headers are latin-1 only.  Keep the ASCII
                    # fallback and provide the preferred Chinese filename using
                    # RFC 5987 percent encoding.
                    "Content-Disposition": "attachment; filename=APEX-scans.zip; filename*=UTF-8''APEX%E6%89%AB%E6%8F%8F%E4%BB%B6.zip",
                    "Cache-Control": "no-store",
                },
            )
        except ScannerInboxError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        finally:
            if "items" in locals():
                if mode != "files":
                    cleanup_files(items)

    @app.get("/api/scanner-inbox/download-file/{token}")
    async def scanner_download_file(token: str, request: Request):
        """Stream a single file staged by the download endpoint, then delete it."""
        guard(request)
        prune_temp_downloads()
        entry = temp_downloads.pop(token, None)
        if not entry:
            raise HTTPException(status_code=404, detail="下载链接已失效，请重新选择文件")
        try:
            path = Path(entry["path"])
            content = path.read_bytes()
            return Response(
                content=content,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": _attachment_header(re.sub(r"^\d+_", "", path.name)),
                    "Cache-Control": "no-store",
                },
            )
        finally:
            path.unlink(missing_ok=True)
            try:
                path.parent.rmdir()
            except OSError:
                pass

    @app.post("/api/scanner-inbox/import")
    async def scanner_import(request: Request):
        guard(request)
        body = await request.json()
        source_ids = body.get("source_ids") if isinstance(body.get("source_ids"), list) else []
        destination = str(body.get("destination") or "")
        try:
            if destination == "case":
                case_id = int(body.get("case_id") or 0)
                if not case_id:
                    raise HTTPException(status_code=400, detail="请选择案件")
                binding = get_folder_binding(get_db, case_id, required=True)
                root = Path(binding["real_path"]).resolve(strict=True)
                if not os.access(root, os.W_OK | os.X_OK):
                    raise HTTPException(status_code=409, detail="案件文件夹当前不可写")
                key = f"case:{case_id}"
                with get_db() as conn:
                    duplicates = [
                        str(source_id) for source_id in source_ids
                        if conn.execute(
                            "SELECT 1 FROM scanner_inbox_imports WHERE mailbox_id=? AND source_id=? AND destination_key=?",
                            (MAILBOX_ID, source_id, key),
                        ).fetchone()
                    ]
                if duplicates:
                    raise HTTPException(status_code=409, detail="选中的扫描件中包含已导入该案件的文件")
                items = await files_for(source_ids)
                stored: list[dict[str, str]] = []
                for source_id, path in items:
                    filename = re.sub(r"^\d+_", "", path.name)
                    file_item = store_case_file(
                        get_db, case_id, "download_material", filename, path.read_bytes(),
                        mime_type="application/pdf", source_type="scanner_inbox",
                        original_filename=filename,
                        metadata={"mailbox_id": MAILBOX_ID, "scanner_source_id": source_id},
                    )
                    record_import(source_id, key, f"已归入案件 {case_id}")
                    stored.append({"source_id": source_id, "path": file_item["absolute_path"]})
                return {"ok": True, "destination": "case", "items": stored}
            if destination == "ai":
                items = await files_for(source_ids)
                with get_db() as conn:
                    already_sent = [
                        source_id for source_id in source_ids
                        if conn.execute(
                            "SELECT 1 FROM scanner_inbox_imports WHERE mailbox_id=? AND source_id=? AND destination_key='ai'",
                            (MAILBOX_ID, str(source_id)),
                        ).fetchone()
                    ]
                if already_sent:
                    raise HTTPException(status_code=409, detail="选中的扫描件中包含已发送至 AI 的文件")
                result = await prepare_ai_attachment_paths([path for _, path in items], parse_file=parse_file, allow_cloud_ocr=bool(body.get("allow_cloud_ocr")))
                for source_id, _ in items:
                    record_import(source_id, "ai", "已发送至 AI 增强")
                return {"ok": True, "destination": "ai", **result}
            raise HTTPException(status_code=400, detail="不支持的导入目标")
        except ScannerInboxError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        finally:
            if "items" in locals():
                cleanup_files(items)
