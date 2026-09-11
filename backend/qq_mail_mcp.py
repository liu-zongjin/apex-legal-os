"""邮箱本机 MCP 适配器（QQ 邮箱 + 腾讯企业邮箱）。

通过标准 IMAP over SSL 直连邮箱服务器，实现查收邮件、读取邮件详情
与附件下载（发票收集）。凭据从本机私有配置读取：QQ 邮箱使用
``QQ_MAIL_ADDRESS``/``QQ_MAIL_AUTH_CODE``（开启 IMAP/SMTP 服务后生成
的授权码）；腾讯企业邮箱使用 ``EXMAIL_ADDRESS``/``EXMAIL_AUTH_CODE``
（在网页邮箱「邮箱绑定 → 客户端专用密码」生成）。附件落盘到
``uploads/邮箱发票/``（企业邮箱为 ``uploads/企业邮箱发票/``），
按月份分目录，避免重复下载。
"""
from __future__ import annotations

import datetime as _datetime
import email
import html as _html
import imaplib
import ipaddress
import json
import os
import re
import socket
import threading
from urllib.parse import parse_qs, unquote, urljoin, urlparse
from email.header import decode_header, make_header
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import ai_config
from .ai_client import call_ai_with_fallback
from .ai_config import effective_default_model


class QQMailMCPError(RuntimeError):
    pass


IMAP_PORT = 993
DEFAULT_FOLDER = "INBOX"
MAIL_FOLDERS = {
    "inbox": "INBOX",
    # imaplib 不会替带空格的邮箱名自动加引号，QQ/企业邮箱均使用该名称。
    "sent": '"Sent Messages"',
    "drafts": "Drafts",
}
MAX_LIST_MAILS = 100
MAX_COLLECT_UIDS = 20

ATTACHMENT_EXTENSIONS = (
    ".pdf", ".jpg", ".jpeg", ".png", ".ofd", ".doc", ".docx",
    ".xls", ".xlsx", ".zip", ".rar", ".et", ".wps",
)

_BASE_DIR = Path(__file__).resolve().parent.parent

# 支持接入的邮箱账号。address_env / code_env 为本机私有配置的凭据变量名，
# 附件按账号分目录落盘，互不干扰。
MAILBOX_CONFIGS: Dict[str, Dict[str, Any]] = {
    "qq_mail": {
        "label": "QQ邮箱",
        "host": "imap.qq.com",
        "address_env": "QQ_MAIL_ADDRESS",
        "code_env": "QQ_MAIL_AUTH_CODE",
        "attachment_root": _BASE_DIR / "uploads" / "邮箱发票",
        "portal_url": "https://mail.qq.com",
        "credential_hint": "在 QQ 邮箱网页版「设置 → 应用 → 应用管理 → IMAP/SMTP服务」生成授权码",
    },
    "qq_exmail": {
        "label": "腾讯企业邮箱",
        "host": "imap.exmail.qq.com",
        "address_env": "EXMAIL_ADDRESS",
        "code_env": "EXMAIL_AUTH_CODE",
        "attachment_root": _BASE_DIR / "uploads" / "企业邮箱发票",
        "portal_url": "https://exmail.qq.com",
        "credential_hint": "在网页版企业邮箱「设置 → 邮箱绑定 → 客户端专用密码」生成专用密码",
    },
}

_DOWNLOAD_LOCK = threading.Lock()
_CACHE_LOCK = threading.RLock()


def _account_config(account: str) -> Dict[str, Any]:
    config = MAILBOX_CONFIGS.get(str(account or "qq_mail").strip())
    if config is None:
        raise QQMailMCPError(f"未知的邮箱账号：{account}")
    return config


def _address(account: str) -> str:
    env_name = _account_config(account)["address_env"]
    value = os.environ.get(env_name) or str(getattr(ai_config, env_name, "") or "")
    return str(value or "").strip()


def _auth_code(account: str) -> str:
    env_name = _account_config(account)["code_env"]
    value = os.environ.get(env_name) or str(getattr(ai_config, env_name, "") or "")
    return str(value or "").strip()


def _credentials(account: str) -> Tuple[str, str]:
    label = _account_config(account)["label"]
    address = _address(account)
    code = _auth_code(account)
    if not address or not code:
        raise QQMailMCPError(f"尚未配置{label}地址或授权码，请先到设置 → 管理 → MCP 服务中配置")
    return address, code


def _safe_logout(client: imaplib.IMAP4_SSL) -> None:
    """关闭 IMAP 会话；服务器断开/超时不应覆盖已经成功的业务结果。"""
    try:
        client.logout()
    except (imaplib.IMAP4.error, OSError):
        try:
            client.shutdown()
        except (imaplib.IMAP4.error, OSError):
            pass


def _connect(account: str) -> imaplib.IMAP4_SSL:
    label = _account_config(account)["label"]
    host = _account_config(account)["host"]
    address, code = _credentials(account)
    try:
        try:
            # timeout 约束 TCP 连接 + TLS 握手阶段（Python 3.9+）；
            # 旧版本回退为连接后手动设置，避免连接阶段无限挂起拖垮调用方。
            client = imaplib.IMAP4_SSL(host, IMAP_PORT, timeout=20)
        except TypeError:
            client = imaplib.IMAP4_SSL(host, IMAP_PORT)
        client.sock.settimeout(20)
    except OSError as exc:
        raise QQMailMCPError(f"无法连接{label}服务器：{exc}") from exc
    try:
        status, detail = client.login(address, code)
    except imaplib.IMAP4.error as exc:
        _safe_logout(client)
        raise QQMailMCPError(f"{label}登录失败，请检查授权码：{exc}") from exc
    if status != "OK":
        _safe_logout(client)
        raise QQMailMCPError(f"{label}登录被拒绝，请重新生成授权码后更新配置")
    return client


def _select(client: imaplib.IMAP4_SSL, folder: str) -> int:
    status, data = client.select(folder, readonly=True)
    if status != "OK":
        raise QQMailMCPError(f"无法打开邮件文件夹：{folder}")
    return int(data[0])


def _decode_text(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return str(value)


def _raw_header(raw: bytes, name: str) -> bytes:
    """读取原始头部，修复部分企业邮箱把 UTF-8 直接写进头部造成的替换乱码。"""
    if not raw:
        return b""
    header_block = raw.split(b"\r\n\r\n", 1)[0].split(b"\n\n", 1)[0]
    pattern = re.compile(rb"(?:^|\n)" + re.escape(name.encode("ascii")) + rb"[ \t]*:[ \t]*(.*(?:\n[ \t].*)*)", re.I)
    match = pattern.search(header_block)
    return match.group(1).replace(b"\r\n", b" ").replace(b"\n", b" ").strip() if match else b""


def _decode_header(raw_value: bytes, fallback: Optional[str] = None) -> str:
    """先使用 RFC 2047，再兼容未编码的 UTF-8/GBK 邮件头。"""
    if raw_value:
        try:
            ascii_value = raw_value.decode("ascii")
            decoded = _decode_text(ascii_value)
            if decoded and "�" not in decoded:
                return decoded
        except UnicodeDecodeError:
            pass
        for charset in ("utf-8", "gb18030", "gbk", "big5", "latin-1"):
            try:
                return raw_value.decode(charset)
            except UnicodeDecodeError:
                continue
    return _decode_text(fallback)


def _message_header(message: email.message.Message, raw: bytes, name: str) -> str:
    return _decode_header(_raw_header(raw, name), message.get(name))


def _folder_name(folder: str) -> str:
    value = str(folder or "inbox").strip().lower()
    if value not in MAIL_FOLDERS:
        raise QQMailMCPError("未知的邮件文件夹")
    return MAIL_FOLDERS[value]


def _mailbox_size(client: imaplib.IMAP4_SSL) -> int:
    status, data = client.select(DEFAULT_FOLDER, readonly=True)
    if status != "OK":
        return 0
    return int(data[0])


def _parse_date(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(_datetime.datetime.now().astimezone().tzinfo)
        return parsed.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(value)


def _message_date(message: email.message.Message) -> str:
    """优先取 Date 头，缺失时回退到 Received 头中的时间（QQ 邮箱不发 Date 头）。"""
    date = _parse_date(message.get("Date"))
    if date:
        return date
    received = message.get_all("Received") or []
    for item in received:
        match = re.search(
            r"\b\w{3}, \d{1,2} \w{3} \d{4} \d{2}:\d{2}:\d{2} [+-]\d{4}",
            str(item),
        )
        if match:
            date = _parse_date(match.group(0))
            if date:
                return date
    return ""


def _body_text(message: email.message.Message) -> str:
    plain_parts: List[str] = []
    html_parts: List[str] = []
    for part in message.walk():
        content_type = part.get_content_type()
        disposition = str(part.get("Content-Disposition") or "")
        if "attachment" in disposition:
            continue
        if content_type == "text/plain":
            payload = part.get_payload(decode=True)
            if payload:
                plain_parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
        elif content_type == "text/html":
            payload = part.get_payload(decode=True)
            if payload:
                html_parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
    if plain_parts:
        return "\n".join(plain_parts)
    if html_parts:
        html = "\n".join(html_parts)
        # 去除样式与脚本块，避免 CSS/JS 源码混入正文。
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.IGNORECASE | re.DOTALL)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.IGNORECASE | re.DOTALL)
        html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
        html = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
        html = re.sub(r"</p>", "\n", html, flags=re.IGNORECASE)
        html = re.sub(r"<div[^>]*>", "\n", html, flags=re.IGNORECASE)
        html = re.sub(r"</tr>", "\n", html, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", html)
        text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<") \
            .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
    return ""


def _body_html(message: email.message.Message) -> str:
    """返回可在隔离 iframe 中显示的邮件 HTML。

    邮件正文不能直接插入 APEX 页面：邮件自带的 CSS 会污染界面，且 HTML
    邮件可能含有脚本或伪装链接。这里保留排版所需的表格、样式和图片，同时
    清除可执行/可导航的危险内容；前端再以无脚本的 sandbox iframe 呈现。
    """
    html_parts: List[str] = []
    for part in message.walk():
        if part.get_content_type() != "text/html":
            continue
        if "attachment" in str(part.get("Content-Disposition") or "").lower():
            continue
        payload = part.get_payload(decode=True)
        if payload:
            html_parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
    if not html_parts:
        return ""

    from bs4 import BeautifulSoup

    soup = BeautifulSoup("\n".join(html_parts), "html.parser")
    # 邮件中的脚本、嵌入页、表单和 base 标签都不属于正文视觉呈现，且会带来
    # 执行、跳转或相对链接劫持风险。
    for tag in soup.find_all(["script", "iframe", "object", "embed", "form", "base"]):
        tag.decompose()
    for tag in soup.find_all("meta"):
        if tag.get("http-equiv"):
            tag.decompose()
    for tag in soup.find_all(True):
        for attr, value in list(tag.attrs.items()):
            name = str(attr).lower()
            text = " ".join(value) if isinstance(value, list) else str(value)
            scheme = text.strip().lower()
            if name.startswith("on") or name in {"srcdoc", "formaction"}:
                del tag.attrs[attr]
            elif name in {"href", "src", "xlink:href"} and scheme.startswith(
                ("javascript:", "vbscript:", "data:text/html")
            ):
                del tag.attrs[attr]
        if tag.name == "a" and tag.get("href"):
            tag["target"] = "_blank"
            tag["rel"] = "noopener noreferrer"
    return str(soup)


def _attachments(message: email.message.Message) -> List[Dict[str, Any]]:
    result = []
    for part_index, part in enumerate(message.walk()):
        if part.get_content_maintype() == "multipart":
            continue
        filename = part.get_filename()
        if not filename:
            continue
        filename = _decode_text(filename).strip()
        if not filename:
            continue
        result.append({
            "id": str(part_index),
            "filename": filename,
            "size": len(part.get_payload(decode=True) or b""),
            "content_type": part.get_content_type(),
        })
    return result


def _fetch_message(client: imaplib.IMAP4_SSL, uid: str, folder: str = "inbox") -> Tuple[email.message.Message, bytes]:
    mailbox = _folder_name(folder)
    status, _ = client.select(mailbox, readonly=True)
    if status != "OK":
        raise QQMailMCPError(f"无法打开邮件文件夹：{mailbox}")
    try:
        status, data = client.uid("fetch", uid, "(RFC822)")
    except imaplib.IMAP4.error as exc:
        raise QQMailMCPError(f"读取邮件失败：{exc}") from exc
    if status != "OK" or not data or not data[0]:
        raise QQMailMCPError(f"未找到邮件 {uid}")
    raw = data[0]
    if isinstance(raw, tuple):
        raw = raw[1]
    message = email.message_from_bytes(raw)
    return message, raw


def _uid_set(client: imaplib.IMAP4_SSL, limit: int, unread_only: bool, keyword: str, folder: str = "inbox") -> List[str]:
    mailbox = _folder_name(folder)
    status, _ = client.select(mailbox, readonly=True)
    if status != "OK":
        raise QQMailMCPError(f"无法打开邮件文件夹：{mailbox}")
    criteria: List[str] = []
    if unread_only:
        criteria.append("UNSEEN")
    if keyword:
        escaped = keyword.replace("\\", "").replace('"', "").replace("'", "")
        if escaped:
            criteria.append(f'SUBJECT "{escaped}"')
    if criteria:
        search_criteria = " ".join(criteria)
    else:
        search_criteria = "ALL"
    try:
        # IMAP 搜索条件必须按 UTF-8 编码，否则中文关键词会以 ascii 编码失败。
        status, data = client.uid("search", None, search_criteria.encode("utf-8"))
    except imaplib.IMAP4.error as exc:
        raise QQMailMCPError(f"邮件搜索失败：{exc}") from exc
    if status != "OK":
        return []
    ids = data[0].split() if data and data[0] else []
    # 返回最新在前、最多 limit 条。
    return [item.decode("ascii", errors="replace") for item in ids[-max(1, min(limit, MAX_LIST_MAILS)):]][::-1]


def _uid_set_between(
    client: imaplib.IMAP4_SSL,
    start_date: _datetime.date,
    end_date: _datetime.date,
    limit: int = 2000,
) -> List[str]:
    """在 IMAP 服务器端先按日期筛选，避免下载无关邮件后再判断日期。"""
    status, _ = client.select(DEFAULT_FOLDER, readonly=True)
    if status != "OK":
        raise QQMailMCPError(f"无法打开邮件文件夹：{DEFAULT_FOLDER}")
    if end_date < start_date:
        start_date, end_date = end_date, start_date
    month_names = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

    def imap_date(value: _datetime.date) -> str:
        return f"{value.day:02d}-{month_names[value.month - 1]}-{value.year:04d}"

    # BEFORE 不含指定日，因此使用结束日期的下一天来覆盖完整结束日。
    criteria = f"SINCE {imap_date(start_date)} BEFORE {imap_date(end_date + _datetime.timedelta(days=1))}"
    try:
        status, data = client.uid("search", None, criteria)
    except imaplib.IMAP4.error as exc:
        raise QQMailMCPError(f"邮件日期搜索失败：{exc}") from exc
    if status != "OK" or not data or not data[0]:
        return []
    ids = data[0].split()
    safe_limit = max(1, min(int(limit or 2000), 5000))
    return [item.decode("ascii", errors="replace") for item in ids[-safe_limit:]][::-1]


def _collect_month_dir(account: str) -> Path:
    root = _account_config(account)["attachment_root"]
    month = _datetime.datetime.now().strftime("%Y-%m")
    folder = root / month
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _safe_filename(uid: str, filename: str) -> str:
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    cleaned = re.sub(r'[\\/:*?"<>|\s]+', "_", stem)[:80]
    return f"{uid}_{cleaned}{suffix}"


def check_connection(account: str = "qq_mail") -> Dict[str, Any]:
    """IMAP 登录并读取收件箱邮件总数，作为 MCP 服务页的连接测试。"""
    started = _datetime.datetime.now()
    client = _connect(account)
    try:
        total = _mailbox_size(client)
    finally:
        _safe_logout(client)
    latency = int((_datetime.datetime.now() - started).total_seconds() * 1000)
    return {"ok": True, "total": total, "latency_ms": latency}


# ── 摘要缓存：已加载邮件不重复下载 ──────────────────────────
_MAX_SUMMARY_CACHE = 500


def _summary_cache_path(account: str, folder: str = "inbox") -> Path:
    data_folder = _BASE_DIR / "data"
    data_folder.mkdir(parents=True, exist_ok=True)
    suffix = "" if folder == "inbox" else f"_{folder}"
    return data_folder / f"mail_summary_{account}{suffix}.json"


def _load_summary_cache(account: str, folder: str = "inbox") -> Dict[str, Any]:
    with _CACHE_LOCK:
        try:
            with open(_summary_cache_path(account, folder), encoding="utf-8") as file:
                cache = json.load(file)
            if isinstance(cache, dict) and isinstance(cache.get("mails"), dict):
                return cache
        except (OSError, ValueError):
            pass
    return {"mails": {}}


def _save_summary_cache(account: str, cache: Dict[str, Any], folder: str = "inbox") -> None:
    mails = cache.get("mails") or {}
    if len(mails) > _MAX_SUMMARY_CACHE:
        # 保留 uid 数值最大的（最新）一批。
        keep = sorted(mails, key=lambda uid: (uid.isdigit(), int(uid) if uid.isdigit() else 0), reverse=True)[:_MAX_SUMMARY_CACHE]
        mails = {uid: mails[uid] for uid in keep}
        cache["mails"] = mails
    path = _summary_cache_path(account, folder)
    temporary = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    with _CACHE_LOCK:
        try:
            with open(temporary, "w", encoding="utf-8") as file:
                json.dump({"mails": mails}, file, ensure_ascii=False)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, path)
        except OSError:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _all_unread_uids(client: imaplib.IMAP4_SSL, folder: str = "inbox") -> set:
    try:
        status, _ = client.select(_folder_name(folder), readonly=True)
        if status != "OK":
            return set()
        status, data = client.uid("search", None, b"UNSEEN")
    except imaplib.IMAP4.error:
        return set()
    if status != "OK" or not data or not data[0]:
        return set()
    return {item.decode("ascii", errors="replace") for item in data[0].split()}


def _summary_from_message(uid: str, message: email.message.Message, read: bool, raw: bytes = b"") -> Dict[str, Any]:
    attachments = _attachments(message)
    return {
        "uid": uid,
        "date": _message_date(message),
        "from": _message_header(message, raw, "From"),
        "to": _message_header(message, raw, "To"),
        "subject": _message_header(message, raw, "Subject") or "（无主题）",
        "attachments": [item["filename"] for item in attachments],
        "attachment_count": len(attachments),
        "read": read,
    }


def _fetch_summaries(
    client: imaplib.IMAP4_SSL,
    uids: List[str],
    unread_uids: set,
) -> Dict[str, Dict[str, Any]]:
    """批量拉取轻量邮件头和 BODYSTRUCTURE；不下载正文和附件内容。"""
    result: Dict[str, Dict[str, Any]] = {}
    for offset in range(0, len(uids), 50):
        batch = uids[offset:offset + 50]
        try:
            status, data = client.uid(
                "fetch",
                ",".join(batch),
                "(BODY.PEEK[HEADER.FIELDS (DATE FROM TO SUBJECT)])",
            )
        except imaplib.IMAP4.error:
            continue
        if status != "OK" or not data:
            continue
        for item in data:
            if not isinstance(item, tuple):
                continue
            descriptor = item[0].decode("utf-8", errors="replace") if item[0] else ""
            match = re.search(r"\bUID (\d+)\b", descriptor)
            if not match:
                continue
            uid = match.group(1)
            raw_header = item[1] if isinstance(item[1], bytes) else b""
            message = email.message_from_bytes(raw_header)
            result[uid] = {
                "uid": uid,
                "date": _message_date(message),
                "from": _message_header(message, raw_header, "From"),
                "to": _message_header(message, raw_header, "To"),
                "subject": _message_header(message, raw_header, "Subject") or "（无主题）",
                "attachments": [],
                "attachment_count": 0,
                "read": uid not in unread_uids,
            }
    # 部分 IMAP 服务器会把组合 FETCH 的 BODYSTRUCTURE 拆成无 UID 的尾部响应，
    # 因而单独批量请求附件结构，仍然只有两次轻量往返而不是逐封下载。
    attachment_names = _mail_attachment_names_map(client, uids)
    for uid, names in attachment_names.items():
        if uid in result:
            result[uid]["attachments"] = names
            result[uid]["attachment_count"] = len(names)
    return result


def list_mails(limit: int = 20, unread_only: bool = False, keyword: str = "", account: str = "qq_mail", folder: str = "inbox") -> List[Dict[str, Any]]:
    """邮件摘要：按文件夹增量加载，已缓存的邮件不再重复下载。"""
    _folder_name(folder)
    client = _connect(account)
    try:
        uids = _uid_set(client, limit, unread_only, keyword, folder)
        if not uids:
            return []
        cache = _load_summary_cache(account, folder)
        unread_uids = _all_unread_uids(client, folder) if folder == "inbox" else set()
        # 筛选条件只决定 UID 集合，不影响摘要内容；任何模式都应复用 UID 缓存。
        missing_uids = [
            uid for uid in uids
            if not cache["mails"].get(uid)
            or not cache["mails"][uid].get("subject")
            or not cache["mails"][uid].get("date")
            or str(cache["mails"][uid].get("subject") or "").startswith(("Date:", "Subject:"))
            or "�" in str(cache["mails"][uid].get("subject") or "")
            or "�" in str(cache["mails"][uid].get("from") or "")
        ]
        if missing_uids:
            summaries = _fetch_summaries(client, missing_uids, unread_uids)
            # 极少数服务器不返回可解析的 BODYSTRUCTURE 时，逐封回退以保证结果完整。
            for uid in missing_uids:
                if uid in summaries:
                    continue
                try:
                    message, raw = _fetch_message(client, uid, folder)
                except QQMailMCPError:
                    continue
                summaries[uid] = _summary_from_message(uid, message, uid not in unread_uids, raw)
            cache["mails"].update(summaries)
            _save_summary_cache(account, cache, folder)
        result: List[Dict[str, Any]] = []
        for uid in uids:
            summary = cache["mails"].get(uid)
            if not summary:
                continue
            item = dict(summary)
            item["read"] = True if folder != "inbox" else uid not in unread_uids
            item["folder"] = folder
            if folder in ("sent", "drafts"):
                item["counterparty"] = item.get("to") or item.get("from")
            result.append(item)
        if folder == "sent":
            _record_contacts(account, *(str(item.get("to") or "") for item in result))
        return result
    finally:
        _safe_logout(client)


def _update_cached_read_state(account: str, uid: str, is_read: bool, folder: str = "inbox") -> None:
    cache = _load_summary_cache(account, folder)
    item = (cache.get("mails") or {}).get(uid)
    if item is None:
        return
    item["read"] = bool(is_read)
    _save_summary_cache(account, cache, folder)


def _set_mail_read_on_client(client: imaplib.IMAP4_SSL, uid: str, is_read: bool, folder: str = "inbox") -> None:
    if folder != "inbox":
        raise QQMailMCPError("只有收件箱邮件可以变更已读状态")
    mailbox = _folder_name(folder)
    try:
        status, _ = client.select(mailbox, readonly=False)
        if status != "OK":
            raise QQMailMCPError(f"无法打开邮件文件夹：{mailbox}")
        operation = "+FLAGS.SILENT" if is_read else "-FLAGS.SILENT"
        status, _ = client.uid("store", str(uid), operation, r"(\Seen)")
    except imaplib.IMAP4.error as exc:
        raise QQMailMCPError(f"更新邮件已读状态失败：{exc}") from exc
    if status != "OK":
        raise QQMailMCPError("更新邮件已读状态失败")


def set_mail_read(uid: str, is_read: bool, account: str = "qq_mail", folder: str = "inbox") -> Dict[str, Any]:
    """同步 IMAP 的 Seen 标记，并更新本机邮件摘要缓存。"""
    client = _connect(account)
    try:
        _set_mail_read_on_client(client, uid, is_read, folder)
    finally:
        _safe_logout(client)
    _update_cached_read_state(account, uid, is_read, folder)
    return {"uid": str(uid), "read": bool(is_read)}


def _mostly_english(text: str) -> bool:
    """按标题与正文合并后的可见文字判定语言，兼容短英文验证码邮件。"""
    content = re.sub(r"https?://\S+|[\w.+-]+@[\w.-]+", " ", str(text or ""))
    latin = len(re.findall(r"[A-Za-z]", content))
    cjk = len(re.findall(r"[\u4e00-\u9fff]", content))
    return latin >= 12 and (cjk == 0 or latin >= cjk * 3)


_ENGLISH_CLASSIFIER_VERSION = 2


def classify_inbox_english(uids: List[str], account: str = "qq_mail") -> Dict[str, bool]:
    """显式启用过滤时才读取正文并缓存“绝大部分英文”判定。"""
    safe_uids = list(dict.fromkeys(str(uid) for uid in uids if str(uid)))[:100]
    cache = _load_summary_cache(account, "inbox")
    pending = [
        uid for uid in safe_uids
        if (cache.get("mails") or {}).get(uid, {}).get("english_classifier_version") != _ENGLISH_CLASSIFIER_VERSION
    ]
    if pending:
        client = _connect(account)
        try:
            for uid in pending:
                try:
                    message, raw = _fetch_message(client, uid, "inbox")
                except QQMailMCPError:
                    continue
                item = cache.setdefault("mails", {}).setdefault(uid, _summary_from_message(uid, message, True, raw))
                # 合并标题与正文；既能识别短英文验证码，也避免只看品牌名误伤中文正文。
                item["mostly_english"] = _mostly_english(
                    _message_header(message, raw, "Subject") + "\n" + _body_text(message)[:12000]
                )
                item["english_classifier_version"] = _ENGLISH_CLASSIFIER_VERSION
        finally:
            _safe_logout(client)
        _save_summary_cache(account, cache, "inbox")
    return {uid: bool((cache.get("mails") or {}).get(uid, {}).get("mostly_english")) for uid in safe_uids}


def read_mail(uid: str, account: str = "qq_mail", folder: str = "inbox") -> Dict[str, Any]:
    """读取指定邮件的完整详情，含正文与附件信息。"""
    client = _connect(account)
    try:
        # 打开收件箱邮件即视为已读，与网页端交互保持一致。
        if folder == "inbox":
            _set_mail_read_on_client(client, uid, True, folder)
        message, raw = _fetch_message(client, uid, folder)
        detail = {
            "uid": uid,
            "date": _message_date(message),
            "from": _message_header(message, raw, "From"),
            "to": _message_header(message, raw, "To"),
            "cc": _message_header(message, raw, "Cc"),
            "subject": _message_header(message, raw, "Subject") or "（无主题）",
            "folder": folder,
            "body": _body_text(message)[:6000],
            "body_html": _body_html(message),
            # 让前端淘汰仅保存纯文本正文的旧详情缓存。
            "body_render_version": 1,
            "attachments": _attachments(message),
        }
    finally:
        _safe_logout(client)
    if folder == "inbox":
        _update_cached_read_state(account, uid, True, folder)
    return detail


def collect_attachments(
    uid: str, account: str = "qq_mail", attachment_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """下载指定邮件的全部附件（发票/文档/压缩包）到本机目录。"""
    client = _connect(account)
    try:
        message, _ = _fetch_message(client, uid)
    finally:
        _safe_logout(client)
    saved: List[Dict[str, Any]] = []
    skipped: List[str] = []
    folder = _collect_month_dir(account)
    wanted_ids = {str(item) for item in (attachment_ids or []) if str(item).isdigit()}
    with _DOWNLOAD_LOCK:
        for part_index, part in enumerate(message.walk()):
            if part.get_content_maintype() == "multipart":
                continue
            if wanted_ids and str(part_index) not in wanted_ids:
                continue
            filename = part.get_filename()
            if not filename:
                continue
            filename = _decode_text(filename).strip()
            if not filename:
                continue
            suffix = Path(filename).suffix.lower()
            if suffix not in ATTACHMENT_EXTENSIONS:
                skipped.append(filename)
                continue
            target = folder / _safe_filename(uid, filename)
            payload = part.get_payload(decode=True)
            if not payload:
                skipped.append(filename)
                continue
            target.write_bytes(payload)
            saved.append({
                "filename": filename,
                "path": str(target),
                "size": len(payload),
            })
    return {
        "uid": uid,
        "folder": str(folder),
        "saved": saved,
        "skipped": skipped,
    }


def delete_mail(uid: str, account: str = "qq_mail", folder: str = "inbox") -> Dict[str, Any]:
    """删除一封邮件并立刻从当前 IMAP 文件夹移除。"""
    client = _connect(account)
    try:
        mailbox = _folder_name(folder)
        status, _ = client.select(mailbox, readonly=False)
        if status != "OK":
            raise QQMailMCPError(f"无法打开邮件文件夹：{mailbox}")
        status, _ = client.uid("store", str(uid), "+FLAGS.SILENT", "(\\Deleted)")
        if status != "OK":
            raise QQMailMCPError("删除邮件失败")
        # 当前连接只操作用户主动删除的邮件；服务端不支持 UID EXPUNGE 时回退。
        status, _ = client.uid("expunge", str(uid))
        if status != "OK":
            status, _ = client.expunge()
        if status != "OK":
            raise QQMailMCPError("删除邮件失败")
    except imaplib.IMAP4.error as exc:
        raise QQMailMCPError(f"删除邮件失败：{exc}") from exc
    finally:
        _safe_logout(client)
    cache = _load_summary_cache(account, folder)
    if str(uid) in (cache.get("mails") or {}):
        cache["mails"].pop(str(uid), None)
        _save_summary_cache(account, cache, folder)
    return {"success": True, "uid": str(uid), "folder": folder}


def collect_invoice_attachments(
    limit: int = 30,
    keyword: str = "",
    since_days: int = 7,
    account: str = "qq_mail",
) -> Dict[str, Any]:
    """批量收集近期邮件的发票类附件（主题或附件名含发票/账单/回执等）。"""
    client = _connect(account)
    try:
        uids = _uid_set(client, limit, unread_only=False, keyword=keyword)
        if not uids:
            return {"total_scanned": 0, "total_saved": 0, "saved": [], "scanned": []}
        invoice_markers = ("发票", "invoice", "账单", "回执", "receipt", "票据", "报销")
        cutoff = _datetime.datetime.now() - _datetime.timedelta(days=since_days)
        scanned: List[Dict[str, Any]] = []
        saved: List[Dict[str, Any]] = []
        folder = _collect_month_dir(account)
        with _DOWNLOAD_LOCK:
            for uid in uids:
                try:
                    message, _ = _fetch_message(client, uid)
                except QQMailMCPError:
                    continue
                subject = _decode_text(message.get("Subject")) or ""
                attachments = _attachments(message)
                if not attachments:
                    continue
                mail_date = _message_date(message)
                try:
                    parsed_date = _datetime.datetime.strptime(mail_date, "%Y-%m-%d %H:%M")
                except ValueError:
                    parsed_date = cutoff
                if parsed_date < cutoff:
                    continue
                matched = any(
                    marker.lower() in (subject + " " + " ".join(
                        item["filename"] for item in attachments
                    )).lower()
                    for marker in invoice_markers
                )
                if not matched:
                    continue
                scanned.append({
                    "uid": uid, "date": mail_date, "from": _decode_text(message.get("From")),
                    "subject": subject, "attachments": [item["filename"] for item in attachments],
                })
                for part in message.walk():
                    if part.get_content_maintype() == "multipart":
                        continue
                    filename = part.get_filename()
                    if not filename:
                        continue
                    filename = _decode_text(filename).strip()
                    if not filename:
                        continue
                    suffix = Path(filename).suffix.lower()
                    if suffix not in ATTACHMENT_EXTENSIONS:
                        continue
                    target = folder / _safe_filename(uid, filename)
                    payload = part.get_payload(decode=True)
                    if not payload:
                        continue
                    target.write_bytes(payload)
                    saved.append({
                        "uid": uid, "filename": filename, "path": str(target), "size": len(payload),
                    })
        return {
            "total_scanned": len(scanned),
            "total_saved": len(saved),
            "folder": str(folder),
            "scanned": scanned,
            "saved": saved,
        }
    finally:
        _safe_logout(client)


_MAIL_TOOLS = [
    {
        "name": "list_mails",
        "description": "查收收件箱最新邮件列表。适合用户问'有什么新邮件'、'查收邮件'或按主题找邮件。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "最多返回多少封，默认 20"},
                "unread_only": {"type": "boolean", "description": "只看未读邮件"},
                "keyword": {"type": "string", "description": "按主题关键词过滤，例如 发票"},
            },
        },
    },
    {
        "name": "read_mail",
        "description": "读取指定邮件的正文与附件清单。适合用户问某封邮件的内容。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "uid": {"type": "string", "description": "邮件 uid（来自 list_mails）"},
            },
            "required": ["uid"],
        },
    },
    {
        "name": "collect_invoice_attachments",
        "description": "批量收集近期邮件里的发票、账单、回执等附件并保存到本机。适合用户要收集发票附件。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "最多扫描多少封，默认 30"},
                "keyword": {"type": "string", "description": "主题关键词过滤，例如 发票"},
                "since_days": {"type": "integer", "description": "只收集最近 N 天，默认 7"},
            },
        },
    },
    {
        "name": "collect_attachments",
        "description": "下载某一封邮件的全部附件。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "uid": {"type": "string", "description": "邮件 uid"},
            },
            "required": ["uid"],
        },
    },
]


def _json_from_model(text: str) -> Dict[str, Any]:
    value = str(text or "").strip()
    value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.IGNORECASE)
    try:
        parsed = json.loads(value)
    except ValueError:
        match = re.search(r"\{.*\}", value, flags=re.DOTALL)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
        except ValueError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


def _execute_mail_call(call: Dict[str, Any], account: str) -> Dict[str, Any]:
    name = str(call.get("name") or "")
    arguments = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
    if name == "list_mails":
        rows = list_mails(
            limit=int(arguments.get("limit") or 20),
            unread_only=bool(arguments.get("unread_only")),
            keyword=str(arguments.get("keyword") or ""),
            account=account,
        )
        return {"mails": rows, "count": len(rows)}
    if name == "read_mail":
        return read_mail(str(arguments.get("uid") or ""), account=account)
    if name == "collect_invoice_attachments":
        return collect_invoice_attachments(
            limit=int(arguments.get("limit") or 30),
            keyword=str(arguments.get("keyword") or ""),
            since_days=int(arguments.get("since_days") or 7),
            account=account,
        )
    if name == "collect_attachments":
        return collect_attachments(str(arguments.get("uid") or ""), account=account)
    raise QQMailMCPError(f"未知的邮箱工具：{name}")


async def answer_from_mail(question: str, account: str = "qq_mail") -> Dict[str, Any]:
    """邮箱任务入口：先列近期邮件摘要，再由模型规划工具调用并执行。

    返回 ``answer`` 文本供 AI 问答流程直接展示或作为上下文注入。
    """
    label = _account_config(account)["label"]
    recent = list_mails(limit=30, account=account)
    recent_summary = []
    for item in recent:
        attachments = "、".join(item["attachments"][:3]) or "无附件"
        recent_summary.append(
            f"[{item['uid']}] {item['date']} · {item['from']} · 《{item['subject']}》 · 附件：{attachments}"
        )
    tools_text = json.dumps(_MAIL_TOOLS, ensure_ascii=False)
    messages = [
        {
            "role": "system",
            "content": (
                f"你是{label}助手。根据用户要求和最近邮件摘要，选择最合适的邮箱工具完成任务："
                "查收邮件用 list_mails，读具体邮件用 read_mail，收集发票附件用 "
                "collect_invoice_attachments，下载某封邮件全部附件用 collect_attachments。"
                "uid 必须取自邮件摘要中给出的编号。只输出JSON："
                '{"calls":[{"name":"工具名","arguments":{}}],"reply":"给用户的一句话说明"}。'
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {"question": question, "recent_mails": recent_summary, "tools": tools_text},
                ensure_ascii=False,
            ),
        },
    ]
    response, _ = await call_ai_with_fallback(
        effective_default_model(), messages, temperature=0.0, max_tokens=900
    )
    choice = ((response.get("choices") or [{}])[0] or {}).get("message") or {}
    planned = _json_from_model(choice.get("content") or "")
    calls = [item for item in (planned.get("calls") or []) if isinstance(item, dict)]
    results: List[Dict[str, Any]] = []
    executed: List[str] = []
    for item in calls[:4]:
        name = str(item.get("name") or "")
        try:
            result = _execute_mail_call(item, account)
        except QQMailMCPError as exc:
            results.append({"tool": name, "error": str(exc)})
            continue
        executed.append(name)
        results.append({"tool": name, "result": result})
    if not results:
        return {
            "answer": f"未能从{label}中处理该请求。您可以先问我“查收我的邮件”，再指定要读取或收集的邮件。",
            "executed_tools": [],
            "mail_summary": recent_summary[:20],
        }
    summary_messages = [
        {"role": "system", "content": f"你是{label}助手。根据工具执行结果，用中文简洁回答用户。"},
        {"role": "user", "content": json.dumps(
            {"question": question, "results": results}, ensure_ascii=False, default=str
        )},
    ]
    answer_response, _ = await call_ai_with_fallback(
        effective_default_model(), summary_messages, temperature=0.0, max_tokens=900
    )
    answer_choice = ((answer_response.get("choices") or [{}])[0] or {}).get("message") or {}
    answer = str(answer_choice.get("content") or "").strip() or str(planned.get("reply") or "")
    return {
        "answer": answer,
        "executed_tools": executed,
        "results": results,
        "mail_summary": recent_summary[:20],
    }


# ──────────────────────────────────────────────────────────
# SMTP 发信（写信功能）
# ──────────────────────────────────────────────────────────

SMTP_HOSTS = {
    "qq_mail": ("smtp.qq.com", 465),
    "qq_exmail": ("smtp.exmail.qq.com", 465),
}

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024


def send_mail(
    account: str,
    to: str,
    subject: str,
    body: str,
    body_html: str = "",
    cc: str = "",
    bcc: str = "",
    attachments: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """通过 SMTP 发送邮件。attachments 为 [{filename, content_bytes}]。"""
    import smtplib
    from email.header import Header
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.utils import formataddr

    config = _account_config(account)
    label = config["label"]
    address, code = _credentials(account)
    host, port = SMTP_HOSTS[account]
    if not to or not to.strip():
        raise QQMailMCPError("收件人不能为空")
    recipients = [item.strip() for item in re.split(r"[,;，；]", to) if item.strip()]
    if not recipients:
        raise QQMailMCPError("收件人地址无效")

    message = MIMEMultipart()
    message["From"] = formataddr((str(Header(label, "utf-8")), address))
    message["To"] = to
    message["Subject"] = subject or "（无主题）"
    all_recipients = list(recipients)
    if cc.strip():
        message["Cc"] = cc
        all_recipients.extend(item.strip() for item in re.split(r"[,;，；]", cc) if item.strip())
    if bcc.strip():
        all_recipients.extend(item.strip() for item in re.split(r"[,;，；]", bcc) if item.strip())
    if body_html.strip():
        alternative = MIMEMultipart("alternative")
        alternative.attach(MIMEText(body or "", "plain", "utf-8"))
        alternative.attach(MIMEText(body_html, "html", "utf-8"))
        message.attach(alternative)
    else:
        message.attach(MIMEText(body or "", "plain", "utf-8"))
    for item in (attachments or [])[:10]:
        filename = str(item.get("filename") or "attachment").strip()
        data = item.get("content") or b""
        if not filename or not data:
            continue
        if len(data) > MAX_ATTACHMENT_BYTES:
            raise QQMailMCPError(f"附件 {filename} 超过 20MB 限制")
        part = MIMEApplication(data, _subtype="octet-stream")
        part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", filename))
        message.attach(part)
    try:
        client = smtplib.SMTP_SSL(host, port, timeout=30)
        client.login(address, code)
        client.sendmail(address, all_recipients, message.as_string())
        client.quit()
    except smtplib.SMTPAuthenticationError as exc:
        raise QQMailMCPError(f"{label}发信认证失败，请检查授权码") from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise QQMailMCPError(f"发送失败：{exc}") from exc
    # SMTP 成功后再写入“已发送”，使 IMAP 列表即时可见；部分服务端也会自动
    # 保存，重复副本不影响发信结果，因此此处失败只作为状态返回。
    saved_to_sent = _append_message(account, "sent", message.as_bytes(), "(\\Seen)")
    _record_contacts(account, to, cc)
    return {"success": True, "to": recipients, "cc": bool(cc.strip()), "bcc": bool(bcc.strip()), "saved_to_sent": saved_to_sent}


def _append_message(account: str, folder: str, message_bytes: bytes, flags: str = "") -> bool:
    client = None
    try:
        client = _connect(account)
        status, _ = client.append(_folder_name(folder), flags, None, message_bytes)
        return status == "OK"
    except (QQMailMCPError, imaplib.IMAP4.error, OSError):
        return False
    finally:
        if client is not None:
            _safe_logout(client)


def _contacts_path(account: str) -> Path:
    folder = _BASE_DIR / "data"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"mail_contacts_{account}.json"


def _record_contacts(account: str, *values: str) -> None:
    found = {}
    with _CACHE_LOCK:
        try:
            stored = json.loads(_contacts_path(account).read_text(encoding="utf-8"))
            found = {str(item.get("email", "")).lower(): item for item in stored if item.get("email")}
        except (OSError, ValueError, TypeError):
            pass
        for name, address in getaddresses(values):
            address = address.strip().lower()
            if "@" not in address:
                continue
            found[address] = {"email": address, "name": name.strip(), "last_used": _datetime.datetime.now().isoformat(timespec="seconds")}
        try:
            _contacts_path(account).write_text(json.dumps(list(found.values()), ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass


def list_contacts(account: str = "qq_mail", query: str = "") -> List[Dict[str, str]]:
    _account_config(account)
    try:
        items = json.loads(_contacts_path(account).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        items = []
    needle = str(query or "").strip().lower()
    filtered = [item for item in items if not needle or needle in str(item.get("email", "")).lower() or needle in str(item.get("name", "")).lower()]
    return sorted(filtered, key=lambda item: str(item.get("last_used", "")), reverse=True)[:50]


def save_draft(
    account: str, to: str, subject: str, body: str, cc: str = "", bcc: str = "", body_html: str = "",
) -> Dict[str, Any]:
    """将当前编辑内容写入 IMAP 草稿箱；附件可在发送前再次添加。"""
    from email.header import Header
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.utils import formataddr
    label = _account_config(account)["label"]
    address, _ = _credentials(account)
    message = MIMEMultipart()
    message["From"] = formataddr((str(Header(label, "utf-8")), address))
    message["To"] = to
    if cc: message["Cc"] = cc
    message["Subject"] = subject or "（无主题）"
    if body_html.strip():
        alternative = MIMEMultipart("alternative")
        alternative.attach(MIMEText(body or "", "plain", "utf-8"))
        alternative.attach(MIMEText(body_html, "html", "utf-8"))
        message.attach(alternative)
    else:
        message.attach(MIMEText(body or "", "plain", "utf-8"))
    if not _append_message(account, "drafts", message.as_bytes(), "(\\Draft)"):
        raise QQMailMCPError("保存草稿失败，请稍后重试")
    return {"success": True}


# ──────────────────────────────────────────────────────────
# 发票附件扫描与元数据解析
# ──────────────────────────────────────────────────────────

INVOICE_EXTENSIONS = (
    ".pdf", ".ofd", ".xml", ".png", ".jpg", ".jpeg", ".csv",
)

_XML_NS_PATTERN = re.compile(r"\{[^}]+\}(.+)")


def _xml_local(tag: str) -> str:
    match = _XML_NS_PATTERN.match(str(tag or ""))
    return match.group(1) if match else str(tag or "")


def _xml_text(root: Any, name: str) -> str:
    for element in root.iter():
        if _xml_local(element.tag) == name:
            return str(element.text or "").strip()
    return ""


def _clean_amount(value: str) -> str:
    if not value:
        return ""
    cleaned = re.sub(r"[^\d.]", "", str(value))
    try:
        return f"{float(cleaned):.2f}"
    except ValueError:
        return ""


def _clean_issue_time(value: str) -> str:
    if not value:
        return ""
    text = str(value).strip()
    # 日期字段可能附带 UTC/本地时间；开票日期只保留完整的日，绝不能按字符
    # 截断成“2026-08-1123:20”之类的伪日期。
    match = re.search(r"(\d{4})\s*[年./-]\s*(\d{1,2})\s*[月./-]\s*(\d{1,2})(?:\s*日)?", text)
    if match:
        return f"{match.group(1)}年{int(match.group(2)):02d}月{int(match.group(3)):02d}日"
    return ""


def _parse_xml_invoice(path: Path) -> Dict[str, str]:
    import xml.etree.ElementTree as ET
    try:
        tree = ET.parse(str(path))
    except ET.ParseError:
        return {}
    root = tree.getroot()
    seller = _xml_text(root, "SellerName") or _xml_text(root, "Seller")
    issue_time = _xml_text(root, "IssueTime") or _xml_text(root, "InvoiceDate") \
        or _xml_text(root, "IssueDate")
    amount = (
        _xml_text(root, "TotalTax-includedAmount")
        or _xml_text(root, "TaxIncludedAmount")
        or _xml_text(root, "TotaltaxIncludedAmount")
        or _xml_text(root, "TotalAmount")
        or _xml_text(root, "TotalTaxAndFee")
        or _xml_text(root, "AmountInFiguers")
        or _xml_text(root, "TotalAmWithoutTax")
        or _xml_text(root, "Amount")
    )
    return {
        "issuer": seller[:120],
        "amount": _clean_amount(amount),
        "issue_time": _clean_issue_time(issue_time),
    }


_OFD_COMPANY_PATTERN = re.compile(
    r"([\u4e00-\u9fa5（）()·]{4,60}(?:公司|集团|店|工作室|事务所|中心|服务部|商行|经营部))[^¥\u4e00-\u9fa5]*?¥"
)
_OFD_CAPITAL_AMOUNT_PATTERN = re.compile(
    r"[零壹贰叁肆伍陆柒捌玖拾佰仟万亿圆整角分]+[¥￥]\s*([0-9,]+\.\d{2})"
)
_OFD_AMOUNT_PATTERN = re.compile(r"[¥￥]\s*([0-9,]+\.\d{2})")
_OFD_DATE_PATTERN = re.compile(r"(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)")


def _parse_ofd_invoice(path: Path) -> Dict[str, str]:
    import zipfile
    import xml.etree.ElementTree as ET
    try:
        with zipfile.ZipFile(str(path)) as archive:
            content_names = [
                name for name in archive.namelist()
                if "/Pages/" in name and name.endswith("Content.xml")
            ]
            text_parts: List[str] = []
            for name in content_names:
                try:
                    root = ET.parse(archive.open(name)).getroot()
                except ET.ParseError:
                    continue
                for element in root.iter():
                    if element.tag.endswith("TextCode") and element.text:
                        text_parts.append(str(element.text))
            text = "".join(text_parts).replace(" ", "").replace("\u3000", "")
    except (zipfile.BadZipFile, OSError):
        return {}
    issuer = ""
    companies = list(_OFD_COMPANY_PATTERN.finditer(text))
    if companies:
        # OFD 文本顺序为 购买方 → 销售方 → 金额，销售方是金额前最后一个公司名。
        issuer = companies[-1].group(1)[:120]
    amount = ""
    match = _OFD_CAPITAL_AMOUNT_PATTERN.search(text)
    if match:
        amount = _clean_amount(match.group(1))
    if not amount:
        amounts = _OFD_AMOUNT_PATTERN.findall(text)
        if amounts:
            amount = _clean_amount(amounts[-1])
    issue_time = ""
    match = _OFD_DATE_PATTERN.search(text)
    if match:
        issue_time = _clean_issue_time(re.sub(r"\s", "", match.group(1)))
    return {"issuer": issuer, "amount": amount, "issue_time": issue_time}


_PDF_SELLER_PATTERNS = (
    re.compile(r"销售方名称[:：]?\s*([^\n\r]{2,80})"),
    re.compile(r"名称[:：]\s*([^\n\r]{2,80})"),
)
_PDF_AMOUNT_PATTERNS = (
    re.compile(r"价税合计[（(]?[大小写)）]*[¥￥]?\s*([0-9,]+\.\d{2})"),
    re.compile(r"[（(]小写[)）]\s*[¥￥]?\s*([0-9,]+\.\d{2})"),
    re.compile(r"[¥￥]\s*([0-9,]+\.\d{2})"),
)
_PDF_DATE_PATTERNS = (
    re.compile(r"开票日期[:：]\s*(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)"),
    re.compile(r"(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)"),
)


_PDF_COMPANY_PATTERN = re.compile(
    r"([\u4e00-\u9fa5（）()·]{4,60}(?:公司|集团|店|工作室|事务所|中心|服务部|商行|经营部))"
)


def _parse_pdf_invoice(path: Path) -> Dict[str, str]:
    try:
        import fitz
        document = fitz.open(str(path))
    except Exception:
        return {}
    text = ""
    try:
        for page in document:
            text += page.get_text("text") + "\n"
    finally:
        document.close()
    text = text.replace("\u3000", " ")
    issuer = ""
    for pattern in _PDF_SELLER_PATTERNS:
        match = pattern.search(text)
        if match:
            candidate = re.sub(r"[\s:：]", "", match.group(1))
            if candidate and candidate not in ("名称", "开票人"):
                issuer = candidate[:120]
                break
    if not issuer:
        # 表格式发票：数据列按“购买方 → 销售方 → 金额”排列，
        # 金额之前的最后一个公司名即销售方。
        companies = list(_PDF_COMPANY_PATTERN.finditer(text))
        amount_index = text.find("¥")
        if amount_index < 0:
            amount_index = len(text)
        for match in reversed(companies):
            if match.start() < amount_index:
                issuer = match.group(1)[:120]
                break
    amount = ""
    for pattern in _PDF_AMOUNT_PATTERNS:
        match = pattern.search(text)
        if match:
            amount = _clean_amount(match.group(1))
            if amount:
                break
    issue_time = ""
    for pattern in _PDF_DATE_PATTERNS:
        match = pattern.search(text)
        if match:
            raw = re.sub(r"\s", "", match.group(1))
            issue_time = _clean_issue_time(raw)
            if issue_time:
                break
    return {"issuer": issuer, "amount": amount, "issue_time": issue_time}


def parse_invoice_metadata(path: Path) -> Dict[str, Any]:
    """解析单个发票附件，返回 {issuer, amount, issue_time, parsed, method}。"""
    suffix = str(path.suffix or "").lower()
    if suffix == ".xml":
        meta = _parse_xml_invoice(path)
        method = "xml"
    elif suffix == ".ofd":
        meta = _parse_ofd_invoice(path)
        method = "ofd"
    elif suffix == ".pdf":
        meta = _parse_pdf_invoice(path)
        method = "pdf"
    else:
        meta, method = {}, "unsupported"
    parsed = bool(meta.get("amount")) or (
        bool(meta.get("issuer")) and bool(meta.get("issue_time"))
    )
    return {"issuer": meta.get("issuer", ""), "amount": meta.get("amount", ""),
            "issue_time": meta.get("issue_time", ""), "parsed": parsed, "method": method}


_INVOICE_FILENAME_MARKERS = ("发票", "invoice", "receipt", "收据", "dzfp", "fp_")


def _scan_cache_path(account: str, folder: Path) -> Path:
    data_folder = _BASE_DIR / "data"
    data_folder.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\u4e00-\u9fa5-]", "_", folder.name)
    return data_folder / f"invoice_meta_{account}_{safe}.json"


_SCAN_CACHE_VERSION = 5

_INVOICE_LINK_CONTEXT_MARKERS = (
    "发票", "下载发票", "查看发票", "电子票", "invoice", "receipt", "票据",
)
_KNOWN_INVOICE_LINK_HOSTS = (
    "nnfp.jss.com.cn", "of1.cn", "inv.jss.com.cn", "storage.nuonuo.com",
    "fp.nuonuo.com", "nnfp.nuonuo.com",
)
_MAX_LINK_RESPONSE_BYTES = 25 * 1024 * 1024


def _is_invoice_link_candidate(url: str, context: str = "") -> bool:
    try:
        parsed = urlparse(str(url or "").strip())
    except ValueError:
        return False
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname.lower().rstrip(".")
    suffix = Path(parsed.path).suffix.lower()
    if suffix in INVOICE_EXTENSIONS:
        return True
    if parsed.path in ("", "/"):
        return False
    if any(host == known or host.endswith("." + known) for known in _KNOWN_INVOICE_LINK_HOSTS):
        return True
    haystack = f"{context} {url}".lower()
    return any(marker in haystack for marker in _INVOICE_LINK_CONTEXT_MARKERS)


def _extract_invoice_links(message: email.message.Message) -> List[str]:
    """从纯文本和 HTML 正文提取疑似发票领取/下载链接。"""
    links: List[str] = []

    def add(url: str, context: str = "") -> None:
        value = _html.unescape(str(url or "")).strip().strip("<>\"'")
        value = value.rstrip("。；，、,;)")
        if _is_invoice_link_candidate(value, context) and value not in links:
            links.append(value)

    for part in message.walk():
        if part.get_content_type() not in ("text/plain", "text/html"):
            continue
        disposition = str(part.get("Content-Disposition") or "").lower()
        if "attachment" in disposition:
            continue
        payload = part.get_payload(decode=True) or b""
        text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        if part.get_content_type() == "text/html":
            for match in re.finditer(
                r"<a\b[^>]*?href\s*=\s*([\"'])(.*?)\1[^>]*>(.*?)</a\s*>",
                text, flags=re.IGNORECASE | re.DOTALL,
            ):
                anchor_text = re.sub(r"<[^>]+>", " ", match.group(3))
                add(match.group(2), anchor_text)
        if part.get_content_type() == "text/plain":
            for match in re.finditer(r"https?://[^\s<>\"']+", text, flags=re.IGNORECASE):
                nearby = text[max(0, match.start() - 100):match.end() + 100]
                add(match.group(0), nearby)
    return links[:10]


def _validate_public_http_url(url: str) -> None:
    """阻止邮件链接访问本机、局域网或云元数据地址。"""
    try:
        parsed = urlparse(url)
        if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
            raise QQMailMCPError("发票链接不是有效的 HTTP 地址")
        if parsed.port not in (None, 80, 443):
            raise QQMailMCPError("发票链接使用了不允许的端口")
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except (ValueError, OSError) as exc:
        raise QQMailMCPError(f"无法解析发票下载地址：{exc}") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise QQMailMCPError("发票链接指向非公网地址，已阻止访问")


def _safe_http_request(
    url: str,
    method: str = "GET",
    data: Optional[Dict[str, Any]] = None,
    referer: str = "",
) -> Tuple[str, Dict[str, str], bytes]:
    """受限请求公网发票链接，逐跳校验重定向并限制响应大小。"""
    import requests

    current = str(url or "").strip()
    session = requests.Session()
    headers = {"User-Agent": "Mozilla/5.0 LegalKB-InvoiceScanner/1.0"}
    if referer:
        headers["Referer"] = referer
    request_method = method.upper()
    request_data = data
    for _ in range(6):
        _validate_public_http_url(current)
        try:
            response = session.request(
                request_method, current, data=request_data, headers=headers,
                timeout=(8, 20), allow_redirects=False, stream=True,
            )
        except requests.RequestException as exc:
            raise QQMailMCPError(f"访问发票链接失败：{exc}") from exc
        if response.status_code in (301, 302, 303, 307, 308):
            target = response.headers.get("Location")
            response.close()
            if not target:
                raise QQMailMCPError("发票链接重定向缺少目标地址")
            current = urljoin(current, target)
            if response.status_code in (301, 302, 303):
                request_method, request_data = "GET", None
            headers["Referer"] = url
            continue
        if response.status_code < 200 or response.status_code >= 300:
            response.close()
            raise QQMailMCPError(f"发票链接返回 HTTP {response.status_code}")
        chunks: List[bytes] = []
        size = 0
        for chunk in response.iter_content(64 * 1024):
            if not chunk:
                continue
            size += len(chunk)
            if size > _MAX_LINK_RESPONSE_BYTES:
                response.close()
                raise QQMailMCPError("发票链接响应超过 25MB，已停止下载")
            chunks.append(chunk)
        response_headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
        response.close()
        return current, response_headers, b"".join(chunks)
    raise QQMailMCPError("发票链接重定向次数过多")


def _linked_file_extension(url: str, headers: Dict[str, str], content: bytes) -> str:
    disposition = headers.get("content-disposition", "")
    filename_match = re.search(r"filename\*?=(?:UTF-8''|\")?([^\";]+)", disposition, re.IGNORECASE)
    if filename_match:
        suffix = Path(unquote(filename_match.group(1).strip())).suffix.lower()
        if suffix in INVOICE_EXTENSIONS:
            return suffix
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in INVOICE_EXTENSIONS:
        return suffix
    content_type = headers.get("content-type", "").lower()
    if content.startswith(b"%PDF") or "application/pdf" in content_type:
        return ".pdf"
    if content.lstrip().startswith(b"<?xml") or "application/xml" in content_type or "text/xml" in content_type:
        return ".xml"
    return ""


def _resolve_nuonuowang_link(
    final_url: str,
    allowed: List[str],
) -> Optional[Dict[str, Any]]:
    parsed = urlparse(final_url)
    if "printQrcode" not in parsed.path:
        return None
    query = parse_qs(parsed.query)
    param_list = (query.get("paramList") or [""])[0]
    if not param_list:
        return None
    middle_uri = parsed.path.rsplit("/", 1)[-1]
    if parsed.query:
        middle_uri += "?" + parsed.query
    api_url = f"{parsed.scheme}://{parsed.netloc}/sapi/scan2/getIvcDetailShow.do"
    _, _, raw = _safe_http_request(
        api_url,
        method="POST",
        data={
            "paramList": param_list,
            "code": (query.get("code") or [""])[0],
            "aliView": (query.get("aliView") or [""])[0],
            "invoiceDetailMiddleUri": middle_uri,
            "shortLinkSource": (query.get("shortLinkSource") or [""])[0],
            "_timestamp": int(_datetime.datetime.now().timestamp() * 1000),
        },
        referer=final_url,
    )
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        return None
    invoice = (((payload.get("data") or {}).get("invoiceSimpleVo")) or {})
    choices = {
        ".pdf": invoice.get("url") or invoice.get("medicalInvociePdfUrl"),
        ".ofd": invoice.get("ofdDownloadUrl"),
        ".xml": invoice.get("xmlUrl"),
    }
    for extension in (".pdf", ".ofd", ".xml"):
        if extension not in allowed or not choices.get(extension):
            continue
        return {
            "download_url": str(choices[extension]),
            "extension": extension,
            "filename": f"电子发票_{invoice.get('fphm') or invoice.get('id') or '下载'}_{invoice.get('saleName') or ''}{extension}",
            "meta": {
                "issuer": str(invoice.get("saleName") or "")[:120],
                "amount": _clean_amount(str(invoice.get("orderTotal") or "")),
                "issue_time": _clean_issue_time(str(invoice.get("invoiceDate") or "")),
            },
        }
    return None


def _download_invoice_link(url: str, allowed: List[str]) -> Optional[Dict[str, Any]]:
    """解析正文领取链接并下载一个首选格式（PDF > OFD > XML）。"""
    final_url, headers, content = _safe_http_request(url)
    extension = _linked_file_extension(final_url, headers, content)
    meta_hint: Dict[str, str] = {}
    filename = Path(urlparse(final_url).path).name
    if not extension:
        resolved = _resolve_nuonuowang_link(final_url, allowed)
        if resolved:
            final_url, headers, content = _safe_http_request(
                resolved["download_url"], referer=final_url
            )
            extension = _linked_file_extension(final_url, headers, content) or resolved["extension"]
            filename = resolved["filename"]
            meta_hint = resolved["meta"]
    if not extension or extension not in allowed or not content:
        return None
    if not filename or Path(filename).suffix.lower() != extension:
        filename = f"链接发票{extension}"
    return {
        "filename": _decode_text(unquote(filename))[:180],
        "content": content,
        "source_url": url,
        "meta_hint": meta_hint,
    }


def _load_scan_cache(account: str, folder: Path) -> Dict[str, Dict[str, Any]]:
    try:
        with open(_scan_cache_path(account, folder), encoding="utf-8") as file:
            cache = json.load(file)
        if isinstance(cache, dict) and cache.get("version") == _SCAN_CACHE_VERSION:
            return cache
    except (OSError, ValueError):
        pass
    return {"version": _SCAN_CACHE_VERSION, "by_uid": {}}


def _save_scan_cache(account: str, folder: Path, cache: Dict[str, Dict[str, Any]]) -> None:
    try:
        with open(_scan_cache_path(account, folder), "w", encoding="utf-8") as file:
            json.dump(cache, file, ensure_ascii=False)
    except OSError:
        pass


def _meta_for_file(target: Path, scan_cache: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """解析发票元数据，同一文件（大小+修改时间未变）复用缓存结果。"""
    try:
        stat = target.stat()
        key = f"{target.name}:{stat.st_size}:{int(stat.st_mtime)}"
    except OSError:
        key = f"{target.name}"
    cached = scan_cache.get(key)
    if cached:
        return dict(cached)
    meta = parse_invoice_metadata(target)
    scan_cache[key] = dict(meta)
    return meta


def _looks_like_invoice(filename: str, meta: Dict[str, Any]) -> bool:
    """没有金额时，仅当文件名含发票关键词才视为发票。"""
    if meta.get("amount"):
        return True
    lowered = str(filename or "").lower()
    return any(marker in lowered for marker in _INVOICE_FILENAME_MARKERS)


def _extract_attachment_names_text(text: str) -> List[str]:
    candidates = []
    # RFC2231 连续编码：filename* {N} utf-8''名字.pdf
    candidates += re.findall(r'"filename\*"\s*\{\d+\}\s*([^\s"()]+)', text, flags=re.IGNORECASE)
    # 普通编码：("name"|"filename") {N} =?charset?B/Q?...?= （QQ 邮箱跨元素 RFC2047 编码）
    candidates += re.findall(
        r'"(?:name|filename)"\s*\{\d+\}\s*((?:=\?[^?\s]+\?[BQbq]\?[^?]*\?=\s*)+)',
        text,
        flags=re.IGNORECASE,
    )
    # 普通引号包裹：("name"|"filename") "名字.pdf"
    candidates += re.findall(r'"(?:name|filename)"\s+"([^"]+)"', text, flags=re.IGNORECASE)
    names = []
    for value in candidates:
        if "''" in value:
            value = value.split("''", 1)[1]
        decoded = _decode_text(value)
        if decoded and decoded not in names:
            names.append(decoded)
    return names[:20]


def _mail_attachment_names(client: imaplib.IMAP4_SSL, uid: str) -> List[str]:
    """用 BODYSTRUCTURE 轻量获取单封邮件附件文件名。"""
    try:
        status, data = client.uid("fetch", uid, "(BODYSTRUCTURE)")
    except imaplib.IMAP4.error:
        return []
    if status != "OK" or not data:
        return []
    text = ""
    for item in data:
        if isinstance(item, tuple):
            for sub in item:
                if isinstance(sub, bytes):
                    text += sub.decode("utf-8", errors="replace")
        elif isinstance(item, bytes):
            text += item.decode("utf-8", errors="replace")
    return _extract_attachment_names_text(text)


def _mail_attachment_names_map(client: imaplib.IMAP4_SSL, uids: List[str]) -> Dict[str, List[str]]:
    """批量获取多封邮件的 BODYSTRUCTURE 附件名（一次往返）。"""
    result: Dict[str, List[str]] = {}
    if not uids:
        return result
    # 大时间段可能包含上千封邮件；分块防止命令行和单次响应过大。
    for offset in range(0, len(uids), 100):
        uid_list = ",".join(uids[offset:offset + 100])
        try:
            status, data = client.uid("fetch", uid_list, "(BODYSTRUCTURE)")
        except imaplib.IMAP4.error:
            continue
        if status != "OK" or not data:
            continue
        for item in data:
            if isinstance(item, tuple):
                head = item[0].decode("utf-8", errors="replace") if item[0] else ""
                text = head + (item[1].decode("utf-8", errors="replace") if item[1] else "")
            elif isinstance(item, bytes):
                text = item.decode("utf-8", errors="replace")
            else:
                continue
            match = re.search(r"UID (\d+)", text)
            if not match:
                continue
            uid = match.group(1)
            names = _extract_attachment_names_text(text)
            if names:
                result[uid] = names
    return result


def _mail_subjects_map(client: imaplib.IMAP4_SSL, uids: List[str]) -> Dict[str, str]:
    """批量获取邮件主题（轻量 HEADER 请求）。"""
    result: Dict[str, str] = {}
    if not uids:
        return result
    for offset in range(0, len(uids), 100):
        uid_list = ",".join(uids[offset:offset + 100])
        try:
            status, data = client.uid("fetch", uid_list, "(BODY.PEEK[HEADER.FIELDS (SUBJECT DATE)])")
        except imaplib.IMAP4.error:
            continue
        if status != "OK" or not data:
            continue
        for item in data:
            if not isinstance(item, tuple):
                continue
            head = item[0].decode("utf-8", errors="replace") if item[0] else ""
            match = re.search(r"UID (\d+)", head)
            if not match:
                continue
            raw_header = item[1] if isinstance(item[1], bytes) else b""
            message = email.message_from_bytes(raw_header)
            result[match.group(1)] = _decode_text(message.get("Subject"))
    return result


def scan_invoices(
    account: str,
    since_days: int = 30,
    extensions: Optional[List[str]] = None,
    keyword: str = "",
    limit: int = 2000,
    start_date: str = "",
    end_date: str = "",
) -> Dict[str, Any]:
    """扫描邮件附件中的发票文件：下载、解析开票人/金额/开票时间，形成列表。"""
    allowed = [ext.lower() for ext in (extensions or []) if ext.lower() in INVOICE_EXTENSIONS] \
        or list(INVOICE_EXTENSIONS)
    today = _datetime.date.today()
    try:
        range_start = _datetime.date.fromisoformat(str(start_date or ""))
    except ValueError:
        range_start = today - _datetime.timedelta(days=max(1, since_days) - 1)
    try:
        range_end = _datetime.date.fromisoformat(str(end_date or ""))
    except ValueError:
        range_end = today
    if range_end < range_start:
        range_start, range_end = range_end, range_start
    normalized_keyword = str(keyword or "").strip().lower()
    client = _connect(account)
    try:
        # 日期条件直接交给 IMAP，避免先取最新 N 封再逐封下载判断，且不会漏掉
        # 时间段内较早、但不在“最新 100 封”里的发票邮件。
        uids = _uid_set_between(client, range_start, range_end, limit=limit)
        if not uids:
            return {"invoices": [], "total": 0, "folder": "", "scanned_mails": 0,
                    "start_date": range_start.isoformat(), "end_date": range_end.isoformat()}
        folder = _collect_month_dir(account)
        cache = _load_summary_cache(account)
        scan_cache = _load_scan_cache(account, folder)
        checked_uids = scan_cache.get("by_uid") or {}
        linked_uids = scan_cache.get("linked_uids") or {}
        rows: List[Dict[str, Any]] = []
        # 只对未检查过的邮件批量获取 BODYSTRUCTURE 附件名（其余复用缓存）。
        new_uids = [uid for uid in uids if uid not in checked_uids]
        if new_uids:
            fresh_map = _mail_attachment_names_map(client, new_uids)
        else:
            fresh_map = {}
        attachment_map = {}
        for uid in uids:
            if uid in checked_uids:
                stored = checked_uids[uid]
                if stored:
                    attachment_map[uid] = stored
            elif uid in fresh_map:
                attachment_map[uid] = fresh_map[uid]
        # 附件名无发票关键词、但扩展名匹配的邮件，用主题判断是否发票类邮件，
        # 避免为仲裁文书等普通 PDF 下载完整邮件。
        invoice_markers = ("发票", "invoice", "收据", "receipt", "账单", "票据")
        need_subject = [
            uid for uid in uids
            if not any(
                marker in name.lower()
                for name in (attachment_map.get(uid) or [])
                for marker in invoice_markers
            )
            and any(
                Path(name).suffix.lower() in allowed
                for name in (attachment_map.get(uid) or [])
            )
        ]
        missing_subject_uids = [
            uid for uid in uids
            if not str((cache["mails"].get(uid) or {}).get("subject") or "")
        ]
        subject_uids = list(dict.fromkeys(need_subject + missing_subject_uids))
        subject_map = _mail_subjects_map(client, subject_uids) if subject_uids else {}
        for uid, subject in subject_map.items():
            cached_summary = cache["mails"].setdefault(uid, {"uid": uid})
            cached_summary["subject"] = subject or "（无主题）"
        subject_filtered = {
            uid for uid in need_subject
            if any(
                marker in str(
                    (cache["mails"].get(uid) or {}).get("subject") or subject_map.get(uid) or ""
                ).lower()
                for marker in invoice_markers
            )
        }
        with _DOWNLOAD_LOCK:
            for uid in uids:
                # 复用摘要缓存：该邮件附件已全部落盘时跳过完整邮件下载。
                cached = cache["mails"].get(uid)
                known_subject = str((cached or {}).get("subject") or subject_map.get(uid) or "")
                if normalized_keyword and normalized_keyword not in known_subject.lower():
                    continue
                full_message: Optional[email.message.Message] = None
                is_invoice_subject = any(marker in known_subject.lower() for marker in invoice_markers)
                known_attachment_names = list(
                    (cached or {}).get("attachments") or attachment_map.get(uid) or []
                )
                has_explicit_invoice_attachment = any(
                    marker in name.lower()
                    for name in known_attachment_names
                    for marker in invoice_markers
                )

                # 无附件发票：从正文领取/下载链接解析真实 PDF/OFD/XML。
                link_record = linked_uids.get(uid)
                stored_link_files = (link_record or {}).get("files") or []
                matching_stored_files = [
                    item for item in stored_link_files
                    if Path(str(item.get("filename") or "")).suffix.lower() in allowed
                ]
                recently_checked_empty = False
                if link_record and not stored_link_files and link_record.get("checked_at"):
                    try:
                        checked_at = _datetime.datetime.fromisoformat(str(link_record["checked_at"]))
                        recently_checked_empty = (
                            _datetime.datetime.now() - checked_at < _datetime.timedelta(hours=6)
                        )
                    except ValueError:
                        recently_checked_empty = False
                restored_link_count = 0
                for stored in matching_stored_files:
                    filename = str(stored.get("filename") or "")
                    target = folder / _safe_filename(uid, filename)
                    if not target.is_file():
                        continue
                    meta = _meta_for_file(target, scan_cache)
                    hint = stored.get("meta_hint") if isinstance(stored.get("meta_hint"), dict) else {}
                    for field in ("issuer", "amount", "issue_time"):
                        # 发票文件内的结构化字段优先；链接页接口仅作 PDF/OFD
                        # 无法解析时的兜底，避免接口时间戳覆盖真正开票日期。
                        if not meta.get(field) and hint.get(field):
                            meta[field] = hint[field]
                    meta["parsed"] = bool(meta.get("amount")) or (
                        bool(meta.get("issuer")) and bool(meta.get("issue_time"))
                    )
                    meta["method"] = f"link+{meta.get('method') or Path(filename).suffix.lstrip('.')}"
                    rows.append({
                        "uid": uid,
                        "mail_date": (cached or {}).get("date") or "",
                        "from": (cached or {}).get("from") or "",
                        "subject": known_subject,
                        "filename": filename,
                        "path": str(target),
                        "ext": Path(filename).suffix.lower(),
                        "size": target.stat().st_size,
                        "source_type": "link",
                        "source_url": str(stored.get("source_url") or ""),
                        **meta,
                    })
                    restored_link_count += 1

                should_resolve_links = (
                    is_invoice_subject
                    and restored_link_count == 0
                    and not has_explicit_invoice_attachment
                    and not recently_checked_empty
                )
                if should_resolve_links:
                    links = list((link_record or {}).get("links") or [])
                    if not links:
                        try:
                            full_message, _ = _fetch_message(client, uid)
                        except QQMailMCPError:
                            full_message = None
                        if full_message is not None:
                            links = _extract_invoice_links(full_message)
                            cache["mails"][uid] = _summary_from_message(
                                uid, full_message, read=bool((cached or {}).get("read", True))
                            )
                            cached = cache["mails"][uid]
                    downloaded_files = list(stored_link_files)
                    for source_url in links[:5]:
                        try:
                            downloaded = _download_invoice_link(source_url, allowed)
                        except QQMailMCPError:
                            continue
                        if not downloaded:
                            continue
                        filename = str(downloaded["filename"])
                        target = folder / _safe_filename(uid, filename)
                        if not target.exists():
                            target.write_bytes(downloaded["content"])
                        meta = _meta_for_file(target, scan_cache)
                        hint = downloaded.get("meta_hint") or {}
                        for field in ("issuer", "amount", "issue_time"):
                            if not meta.get(field) and hint.get(field):
                                meta[field] = hint[field]
                        meta["parsed"] = bool(meta.get("amount")) or (
                            bool(meta.get("issuer")) and bool(meta.get("issue_time"))
                        )
                        meta["method"] = f"link+{meta.get('method') or Path(filename).suffix.lstrip('.')}"
                        stored_item = {
                            "filename": filename,
                            "source_url": source_url,
                            "meta_hint": hint,
                        }
                        if not any(item.get("filename") == filename for item in downloaded_files):
                            downloaded_files.append(stored_item)
                        rows.append({
                            "uid": uid,
                            "mail_date": _message_date(full_message) if full_message else (cached or {}).get("date") or "",
                            "from": _decode_text(full_message.get("From")) if full_message else (cached or {}).get("from") or "",
                            "subject": _decode_text(full_message.get("Subject")) if full_message else known_subject,
                            "filename": filename,
                            "path": str(target),
                            "ext": Path(filename).suffix.lower(),
                            "size": target.stat().st_size,
                            "source_type": "link",
                            "source_url": source_url,
                            **meta,
                        })
                    linked_uids[uid] = {
                        "checked_at": _datetime.datetime.now().isoformat(timespec="seconds"),
                        "links": links,
                        "files": downloaded_files,
                    }
                if cached and cached.get("attachments"):
                    disk_attachments = []
                    all_present = True
                    for filename in cached["attachments"]:
                        if Path(filename).suffix.lower() not in allowed:
                            continue
                        target = folder / _safe_filename(uid, filename)
                        if not target.exists():
                            all_present = False
                            break
                        disk_attachments.append((filename, target))
                    if all_present and disk_attachments:
                        for filename, target in disk_attachments:
                            meta = _meta_for_file(target, scan_cache)
                            if not _looks_like_invoice(filename, meta):
                                continue
                            rows.append({
                                "uid": uid,
                                "mail_date": cached.get("date") or "",
                                "from": cached.get("from") or "",
                                "subject": cached.get("subject") or "",
                                "filename": filename,
                                "path": str(target),
                                "ext": Path(filename).suffix.lower(),
                                "size": target.stat().st_size if target.exists() else 0,
                                **meta,
                            })
                        continue
                # BODYSTRUCTURE 预筛：没有目标扩展名附件的邮件不下载完整内容。
                attachment_names = attachment_map.get(uid) or []
                wanted_names = [
                    name for name in attachment_names
                    if Path(name).suffix.lower() in allowed
                ]
                if not wanted_names:
                    continue
                # 无发票关键词且主题也无发票特征 → 视为普通文档，跳过。
                has_invoice_word = any(
                    marker in name.lower()
                    for name in wanted_names
                    for marker in invoice_markers
                )
                if not has_invoice_word and uid not in subject_filtered:
                    continue
                # 目标附件已全部落盘：直接从磁盘解析，跳过完整邮件下载。
                pending_names = [
                    name for name in wanted_names
                    if not (folder / _safe_filename(uid, name)).exists()
                ]
                if not pending_names:
                    for filename in wanted_names:
                        target = folder / _safe_filename(uid, filename)
                        if not target.is_file():
                            continue
                        meta = _meta_for_file(target, scan_cache)
                        if not _looks_like_invoice(filename, meta):
                            continue
                        rows.append({
                            "uid": uid,
                            "mail_date": cached.get("date") if cached else "",
                            "from": cached.get("from") if cached else "",
                            "subject": cached.get("subject") if cached else "",
                            "filename": filename,
                            "path": str(target),
                            "ext": Path(filename).suffix.lower(),
                            "size": target.stat().st_size,
                            **meta,
                        })
                    continue
                message = full_message
                if message is None:
                    try:
                        message, _ = _fetch_message(client, uid)
                    except QQMailMCPError:
                        continue
                mail_date = _message_date(message)
                attachments = _attachments(message)
                cache["mails"][uid] = _summary_from_message(
                    uid, message, read=bool((cached or {}).get("read", True))
                )
                for part in message.walk():
                    if part.get_content_maintype() == "multipart":
                        continue
                    filename = part.get_filename()
                    if not filename:
                        continue
                    filename = _decode_text(filename).strip()
                    if not filename:
                        continue
                    suffix = Path(filename).suffix.lower()
                    if suffix not in allowed:
                        continue
                    target = folder / _safe_filename(uid, filename)
                    if not target.exists():
                        payload = part.get_payload(decode=True)
                        if payload:
                            target.write_bytes(payload)
                    meta = _meta_for_file(target, scan_cache)
                    if not _looks_like_invoice(filename, meta):
                        continue
                    rows.append({
                        "uid": uid,
                        "mail_date": mail_date,
                        "from": _decode_text(message.get("From")),
                        "subject": _decode_text(message.get("Subject")) or "（无主题）",
                        "filename": filename,
                        "path": str(target),
                        "ext": suffix,
                        "size": target.stat().st_size if target.exists() else 0,
                        **meta,
                    })
    finally:
        _safe_logout(client)
    # 记录已检查过的 uid 及其附件名，避免下次重复 BODYSTRUCTURE。
    checked_uids.update({uid: names for uid, names in fresh_map.items()})
    checked_uids.update({uid: [] for uid in new_uids if uid not in fresh_map})
    scan_cache["by_uid"] = checked_uids
    scan_cache["linked_uids"] = linked_uids
    _save_scan_cache(account, folder, scan_cache)
    _save_summary_cache(account, cache)
    # 同一文件可能同时被转发正文和附件路径发现，最终列表按落盘路径去重。
    unique_rows: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        unique_rows[str(row.get("path") or f"{row.get('uid')}:{row.get('filename')}")] = row
    rows = list(unique_rows.values())
    rows.sort(key=lambda item: item.get("mail_date") or "", reverse=True)
    return {
        "invoices": rows,
        "total": len(rows),
        "folder": str(folder),
        "parsed_count": sum(1 for row in rows if row.get("parsed")),
        "scanned_mails": len(uids),
        "start_date": range_start.isoformat(),
        "end_date": range_end.isoformat(),
    }


def open_attachment_folder(account: str) -> Dict[str, Any]:
    """在访达中打开当前月份的附件保存目录。"""
    import subprocess
    folder = _collect_month_dir(account)
    folder.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.Popen(["open", str(folder)])
    except OSError as exc:
        raise QQMailMCPError(f"无法打开文件夹：{exc}") from exc
    return {"success": True, "folder": str(folder)}
