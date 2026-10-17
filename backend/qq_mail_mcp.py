"""邮箱本机 MCP 适配器（QQ 邮箱 + 腾讯企业邮箱 + 网易企业邮箱）。

通过标准 IMAP over SSL 直连邮箱服务器，实现查收邮件、读取邮件详情
与附件下载（发票收集）。凭据从本机私有配置读取：QQ 邮箱使用
``QQ_MAIL_ADDRESS``/``QQ_MAIL_AUTH_CODE``（开启 IMAP/SMTP 服务后生成
的授权码）；腾讯企业邮箱使用 ``EXMAIL_ADDRESS``/``EXMAIL_AUTH_CODE``
（在网页邮箱「邮箱绑定 → 客户端专用密码」生成）；网易企业邮箱使用
``NETEASE_EXMAIL_ADDRESS``/``NETEASE_EXMAIL_AUTH_CODE``（在网页版邮箱
设置中开启 IMAP/SMTP 并生成客户端授权码）。附件按账号分别落盘到
``uploads/邮箱发票/``、``uploads/企业邮箱发票/``和
``uploads/网易企业邮箱发票/``，按月份分目录，避免重复下载。
"""
from __future__ import annotations

import datetime as _datetime
import ast
import email
import hashlib
import html as _html
import imaplib
import ipaddress
import json
import os
import re
import socket
import threading
import time as _time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen
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
# 网易企业邮箱通过 IMAP LIST 返回中文特殊文件夹名（Modified UTF-7 编码），
# 与 QQ/腾讯企业邮箱的英文目录不同。目录名按账号隔离，避免影响已有邮箱。
ACCOUNT_MAIL_FOLDERS = {
    "netease_exmail": {
        **MAIL_FOLDERS,
        "sent": "&XfJT0ZAB-",   # 已发送
        "drafts": "&g0l6P3ux-", # 草稿箱
    },
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
        "login_env": "EXMAIL_LOGIN",
        "code_env": "EXMAIL_AUTH_CODE",
        "attachment_root": _BASE_DIR / "uploads" / "企业邮箱发票",
        "portal_url": "https://exmail.qq.com",
        "credential_hint": "在网页版企业邮箱「设置 → 邮箱绑定 → 客户端专用密码」生成专用密码",
    },
    "netease_exmail": {
        "label": "网易企业邮箱",
        "host": "imap.qiye.163.com",
        "address_env": "NETEASE_EXMAIL_ADDRESS",
        "code_env": "NETEASE_EXMAIL_AUTH_CODE",
        # 网易 SMTP 已经会把成功发出的邮件保存到“已发送”；再次 IMAP APPEND
        # 会在“已发送”中产生第二份副本，但不会带来额外的投递保障。
        "smtp_server_saves_sent": True,
        "attachment_root": _BASE_DIR / "uploads" / "网易企业邮箱发票",
        "portal_url": "https://mail.qiye.163.com/static/sirius-web/?version=1789102496212/#mailbox",
        "credential_hint": "在网易企业邮箱网页版「设置 → 客户端设置」中开启 IMAP/SMTP 并生成客户端授权码；需要真正云附件时另配置网页版会话 Cookie",
    },
}

_DOWNLOAD_LOCK = threading.Lock()
_INVOICE_SCAN_LOCKS = {account: threading.RLock() for account in MAILBOX_CONFIGS}
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


def _login_address(account: str) -> str:
    """返回 IMAP/SMTP 认证用账号，兼容企业邮箱内部账号与自定义域别名。"""
    config = _account_config(account)
    env_name = config.get("login_env")
    if env_name:
        value = os.environ.get(env_name) or str(getattr(ai_config, env_name, "") or "")
        if str(value or "").strip():
            return str(value).strip()
    return _address(account)


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


def _login_credentials(account: str) -> Tuple[str, str]:
    label = _account_config(account)["label"]
    address = _address(account)
    login_address = _login_address(account)
    code = _auth_code(account)
    if not address or not login_address or not code:
        raise QQMailMCPError(f"尚未配置{label}地址或授权码，请先到设置 → 管理 → MCP 服务中配置")
    return login_address, code


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
    login_address, code = _login_credentials(account)
    try:
        client = imaplib.IMAP4_SSL(host, IMAP_PORT)
        client.sock.settimeout(20)
    except OSError as exc:
        raise QQMailMCPError(f"无法连接{label}服务器：{exc}") from exc
    try:
        status, detail = client.login(login_address, code)
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


def _folder_name(folder: str, account: str = "qq_mail") -> str:
    value = str(folder or "inbox").strip().lower()
    folders = ACCOUNT_MAIL_FOLDERS.get(account, MAIL_FOLDERS)
    if value not in folders:
        raise QQMailMCPError("未知的邮件文件夹")
    return folders[value]


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


def _fetch_message(
    client: imaplib.IMAP4_SSL,
    uid: str,
    folder: str = "inbox",
    account: str = "qq_mail",
    _mailbox: str = "",
    _peek: bool = False,
) -> Tuple[email.message.Message, bytes]:
    mailbox = _mailbox or _folder_name(folder, account)
    status, _ = client.select(mailbox, readonly=True)
    if status != "OK":
        raise QQMailMCPError(f"无法打开邮件文件夹：{mailbox}")
    try:
        status, data = client.uid("fetch", uid, "(BODY.PEEK[])" if _peek else "(RFC822)")
    except imaplib.IMAP4.error as exc:
        raise QQMailMCPError(f"读取邮件失败：{exc}") from exc
    if status != "OK" or not data or not data[0]:
        raise QQMailMCPError(f"未找到邮件 {uid}")
    raw = data[0]
    if isinstance(raw, tuple):
        raw = raw[1]
    message = email.message_from_bytes(raw)
    return message, raw


def _uid_set(
    client: imaplib.IMAP4_SSL,
    limit: int,
    unread_only: bool,
    keyword: str,
    folder: str = "inbox",
    account: str = "qq_mail",
) -> List[str]:
    mailbox = _folder_name(folder, account)
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
    mailbox: str = DEFAULT_FOLDER,
) -> List[str]:
    """在 IMAP 服务器端先按日期筛选，避免下载无关邮件后再判断日期。"""
    status, _ = client.select(mailbox, readonly=True)
    if status != "OK":
        raise QQMailMCPError(f"无法打开邮件文件夹：{mailbox}")
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
    if status != "OK":
        raise QQMailMCPError("邮箱拒绝日期检索，不能将扫描结果视为空邮箱")
    if not data or not data[0]:
        return []
    ids = data[0].split()
    selected = ids if limit == 0 else ids[-max(1, min(int(limit or 2000), 5000)):]
    return [item.decode("ascii", errors="replace") for item in selected][::-1]


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
                if folder == "inbox" and cache.get("version") != 2:
                    # Earlier invoice scans replaced original ZIP attachment names
                    # with generated member names in the shared mailbox summary.
                    cache["mails"] = {uid: row for uid, row in cache["mails"].items()
                                      if not any(re.match(r"^[0-9a-f]{12}_|^__unnamed_attachment", str(name))
                                                 for name in row.get("attachments", []))}
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
                json.dump({"version": 2, "mails": mails}, file, ensure_ascii=False)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, path)
        except OSError:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _all_unread_uids(
    client: imaplib.IMAP4_SSL,
    folder: str = "inbox",
    account: str = "qq_mail",
) -> set:
    try:
        status, _ = client.select(_folder_name(folder, account), readonly=True)
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
    _folder_name(folder, account)
    client = _connect(account)
    try:
        uids = _uid_set(client, limit, unread_only, keyword, folder, account)
        if not uids:
            return []
        cache = _load_summary_cache(account, folder)
        unread_uids = _all_unread_uids(client, folder, account) if folder == "inbox" else set()
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
                    message, raw = _fetch_message(client, uid, folder, account)
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


def _set_mail_read_on_client(
    client: imaplib.IMAP4_SSL,
    uid: str,
    is_read: bool,
    folder: str = "inbox",
    account: str = "qq_mail",
) -> None:
    if folder != "inbox":
        raise QQMailMCPError("只有收件箱邮件可以变更已读状态")
    mailbox = _folder_name(folder, account)
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
        _set_mail_read_on_client(client, uid, is_read, folder, account)
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
                    message, raw = _fetch_message(client, uid, "inbox", account)
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
            _set_mail_read_on_client(client, uid, True, folder, account)
        message, raw = _fetch_message(client, uid, folder, account)
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
            # 让前端淘汰旧版纯文本/云附件正文缓存，重新读取新版云附件卡片。
            "body_render_version": 2,
            "attachments": _attachments(message),
        }
    finally:
        _safe_logout(client)
    if folder == "inbox":
        _update_cached_read_state(account, uid, True, folder)
    return detail


def collect_attachments(
    uid: str, account: str = "qq_mail", attachment_ids: Optional[List[str]] = None,
    destination_dir: Optional[Path] = None, progress=None, folder: str = "inbox",
) -> Dict[str, Any]:
    """下载指定邮件的全部附件（发票/文档/压缩包）到本机目录。"""
    client = _connect(account)
    try:
        message, _ = _fetch_message(client, uid, account=account, folder=folder)
    finally:
        _safe_logout(client)
    saved: List[Dict[str, Any]] = []
    skipped: List[str] = []
    folder = Path(destination_dir) if destination_dir is not None else (_BASE_DIR / "uploads" / "邮箱附件" / account / _datetime.datetime.now().strftime("%Y-%m"))
    folder.mkdir(parents=True, exist_ok=True)
    wanted_ids = {str(item) for item in (attachment_ids or []) if str(item).isdigit()}
    if progress: progress(status="saving", phase="正在保存邮箱附件", total_files=sum(not wanted_ids or item["id"] in wanted_ids for item in _attachments(message)))
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
            if progress: progress(name=filename, phase="正在保存附件", total_bytes=len(payload), received_bytes=0)
            with target.open("wb") as output:
                for start in range(0,len(payload),1024*1024):
                    output.write(payload[start:start+1024*1024])
                    if progress: progress(received_bytes=min(len(payload),start+1024*1024))
            if progress: progress(completed_files=len(saved)+1)
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
        mailbox = _folder_name(folder, account)
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
        uids = _uid_set(client, limit, unread_only=False, keyword=keyword, account=account)
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
                    message, _ = _fetch_message(client, uid, account=account)
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
    "netease_exmail": ("smtp.qiye.163.com", 465),
}

MAX_ATTACHMENTS = 10
# 普通 SMTP 邮件的大小是 MIME 编码后的整封邮件大小，不是附件在磁盘上的
# 原始大小。附件会经过 base64 编码，且收件方通常比发件方设置更低的上限；
# 以 25 MiB 作为分卷阈值，避免邮件先进入网易队列、随后因 DATA_TRANS
# 的 552 mailsize limit 异步退信。阈值按 MIME 编码后的整封邮件计算；
# 25 MiB 也为含有超大单页对象的 PDF 留出可投递空间，更大的文件优先走云附件。
MAX_SMTP_MESSAGE_BYTES = 25 * 1024 * 1024
# 网易企业邮箱网页端的云附件 API 与登录网页使用同一主机；旧的
# maild.qiye.163.com 已无法解析，会被 Python 表现为 TLS EOF。
NETEASE_CLOUD_API_HOST = "https://mail.qiye.163.com"
NETEASE_CLOUD_TOKEN_PATH = "/biz/api/biz/attachment/getUploadToken"
NETEASE_CLOUD_FINISH_PATH = "/biz/api/biz/attachment/finishUpload"
NETEASE_CLOUD_UPLOAD_TIMEOUT = 15 * 60

# QQ 邮箱网页端的“文件中转站/超大附件”接口。它不是 SMTP/IMAP 协议，
# 需要同一账号的网页登录 Cookie；上传成功后邮件正文携带官方下载链接。
QQ_FTN_API_HOST = "https://mail.qq.com"
QQ_FTN_WEB_HOST = "https://wx.mail.qq.com"
QQ_FTN_LOGIN_PATH = "/cgi-bin/login"
QQ_FTN_CREATE_PATH = "/cgi-bin/ftnCreatefile"
QQ_FTN_LIST_PATH = "/cgi-bin/ftnExs_files"
QQ_FTN_CURRENT_USERINFO_PATH = "/ftn/userinfo"
QQ_FTN_CURRENT_CREATE_PATH = "/ftn/create"
QQ_FTN_CURRENT_LIST_PATH = "/ftn/list"
QQ_FTN_UPLOAD_TIMEOUT = 15 * 60
QQ_FTN_MAX_FILE_BYTES = 3 * 1024 * 1024 * 1024


def _netease_web_cookie() -> str:
    """Return an optional official-web session cookie without exposing it to the UI."""
    return str(
        os.environ.get("NETEASE_EXMAIL_WEB_COOKIE")
        or getattr(ai_config, "NETEASE_EXMAIL_WEB_COOKIE", "")
        or ""
    ).strip()


def _qq_web_cookie() -> str:
    """Return the optional QQ web session cookie without exposing it to the UI."""
    return str(
        os.environ.get("QQ_MAIL_WEB_COOKIE")
        or getattr(ai_config, "QQ_MAIL_WEB_COOKIE", "")
        or ""
    ).strip()


def _parse_qq_json_payload(content: bytes) -> Dict[str, Any]:
    """Parse QQ's JSON and legacy JavaScript-object response variants."""
    text = content.decode("utf-8-sig", errors="replace").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        pass
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    candidate = text[start:end + 1]
    candidate = re.sub(r"([{,]\s*)([A-Za-z_$][\w$]*)(\s*:)", r'\1"\2"\3', candidate)
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        pass
    try:
        candidate = re.sub(r"\btrue\b", "True", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\bfalse\b", "False", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\bnull\b", "None", candidate, flags=re.IGNORECASE)
        parsed = ast.literal_eval(candidate)
        return parsed if isinstance(parsed, dict) else {}
    except (SyntaxError, ValueError, TypeError):
        return {}


def _qq_web_request(
    method: str,
    path: str,
    *,
    query: Optional[Dict[str, Any]] = None,
    raw: Optional[bytes] = None,
    headers: Optional[Dict[str, str]] = None,
    parse_json: bool = True,
) -> Any:
    cookie = _qq_web_cookie()
    if not cookie:
        raise QQMailMCPError(
            "未配置 QQ 邮箱网页版会话，暂不能使用超大附件；"
            "请先在官方网页端登录后配置 QQ_MAIL_WEB_COOKIE"
        )
    url = path if path.startswith(("http://", "https://")) else QQ_FTN_API_HOST.rstrip("/") + path
    if query:
        url += "?" + urlencode(query)
    request_headers = {
        "Accept": "application/json, text/plain, */*",
        "Cookie": cookie,
        "Origin": "https://mail.qq.com",
        "Referer": "https://mail.qq.com/",
        "User-Agent": "APEX-Legal-Knowledge-Base/1.0",
    }
    if headers:
        request_headers.update(headers)
    request = Request(url, data=raw, headers=request_headers, method=method.upper())
    try:
        with urlopen(request, timeout=QQ_FTN_UPLOAD_TIMEOUT) as response:
            content = response.read()
    except HTTPError as exc:
        detail = exc.read(512).decode("utf-8", errors="replace")
        raise QQMailMCPError(f"QQ邮箱超大附件接口失败：HTTP {exc.code} {detail[:180]}") from exc
    except (URLError, OSError) as exc:
        raise QQMailMCPError(f"无法连接 QQ 邮箱超大附件接口：{exc}") from exc
    if not parse_json:
        return content
    payload = _parse_qq_json_payload(content)
    if not payload:
        raise QQMailMCPError("QQ邮箱超大附件接口返回了无法解析的响应")
    return payload


def _qq_current_web_request(path: str, *, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Call the current wx.mail.qq.com form API used by the QQ web client."""
    cookie = _qq_web_cookie()
    if not cookie:
        raise QQMailMCPError(
            "未配置 QQ 邮箱网页版会话，暂不能使用超大附件；"
            "请先在官方网页端登录后配置 QQ_MAIL_WEB_COOKIE"
        )
    sid = _qq_sid()
    form = {
        "sid": sid,
        # QQ 网页端用“毫秒时间戳 + 5 位随机数”作为每次请求的防重放参数。
        "r": str(int(_time.time() * 1000)) + str(int((_time.time() * 100000) % 100000)).zfill(5),
        "language": "zh",
    }
    if params:
        form.update(params)
    request = Request(
        QQ_FTN_WEB_HOST.rstrip("/") + path,
        data=urlencode(form).encode("utf-8"),
        headers={
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": cookie,
            "Origin": QQ_FTN_WEB_HOST,
            "Referer": QQ_FTN_WEB_HOST + "/home/index?sid=" + quote(sid, safe=""),
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=QQ_FTN_UPLOAD_TIMEOUT) as response:
            payload = _parse_qq_json_payload(response.read())
    except HTTPError as exc:
        detail = exc.read(512).decode("utf-8", errors="replace")
        raise QQMailMCPError(f"QQ邮箱超大附件接口失败：HTTP {exc.code} {detail[:180]}") from exc
    except (URLError, OSError) as exc:
        raise QQMailMCPError(f"无法连接 QQ 邮箱超大附件接口：{exc}") from exc
    if not payload:
        raise QQMailMCPError("QQ邮箱超大附件接口返回了无法解析的响应")
    error = _qq_payload_error(payload)
    if error:
        raise QQMailMCPError(f"QQ邮箱超大附件会话无效：{error}")
    return payload


def _qq_sid() -> str:
    """Resolve the current web session id from the cookie or a harmless login probe."""
    cookie = _qq_web_cookie()
    # 新版 QQ 邮箱使用 wx.mail.qq.com，并把可用于 /ftn/* 的会话放在 xm_sid；
    # 旧版页面才常见 sid/qm_sid。优先使用 xm_sid，避免把旧 sid 当成当前会话。
    for name in ("xm_sid", "xm_muti_sid", "sid", "qm_sid", "qm_sid2"):
        match = re.search(r"(?:^|;\s*)" + re.escape(name) + r"=([^;]+)", cookie)
        if match and match.group(1).strip():
            return unquote(match.group(1).strip())
    # 新版登录页会把当前 sid 放在 wx.mail.qq.com 首页的最终 URL 中。
    # 这一步比直接请求旧版 /cgi-bin/login 稳定，且不会上传文件。
    for probe_url in (QQ_FTN_WEB_HOST + "/", QQ_FTN_API_HOST + QQ_FTN_LOGIN_PATH + "?" + urlencode({
        "fun": "psaread", "rand": "", "delegate_url": "", "target": "",
    })):
        request = Request(
            probe_url,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Cookie": cookie,
                "Referer": QQ_FTN_WEB_HOST + "/",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                final_url = response.geturl()
                body = response.read(64 * 1024).decode("utf-8", errors="replace")
        except (HTTPError, URLError, OSError):
            continue
        sid = parse_qs(urlparse(final_url).query).get("sid", [""])[0]
        if not sid:
            match = re.search(r"(?:[?&]|\b)sid=([^&\"'\s]+)", body)
            sid = unquote(match.group(1)) if match else ""
        if sid:
            return sid
    raise QQMailMCPError("QQ邮箱网页版会话无效或已过期，请重新登录并更新 Cookie")


def _qq_payload_error(payload: Dict[str, Any]) -> str:
    head = payload.get("head") if isinstance(payload.get("head"), dict) else {}
    if head and head.get("ret") not in (None, 0, "0", "200", 200, ""):
        return str(head.get("msg") or head.get("errmsg") or f"ret={head.get('ret')}")
    for key in ("errcode", "ret", "code"):
        if key not in payload:
            continue
        value = payload.get(key)
        if value in (None, 0, "0", "200", 200, ""):
            continue
        return str(payload.get("errmsg") or payload.get("errinfo") or payload.get("message") or f"ret={value}")
    return ""


def _qq_nested_value(value: Any, names: Tuple[str, ...]) -> Any:
    wanted = {name.lower() for name in names}
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in wanted and item not in (None, ""):
                return item
        for item in value.values():
            found = _qq_nested_value(item, names)
            if found not in (None, ""):
                return found
    elif isinstance(value, list):
        for item in value:
            found = _qq_nested_value(item, names)
            if found not in (None, ""):
                return found
    return None


def _qq_file_items(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    for key in ("oFiles", "files", "fileList", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _qq_expire_at_ms(value: Any, now_ms: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None
    if number >= 10_000_000_000:
        return int(number)
    if number >= 1_000_000_000:
        return int(number * 1000)
    return int(now_ms or int(_time.time() * 1000)) + int(number * 1000)


def _format_qq_expire_time(value: Any) -> str:
    expire_ms = _qq_expire_at_ms(value)
    if expire_ms is None:
        return "无限期"
    return _datetime.datetime.fromtimestamp(expire_ms / 1000, tz=_NETEASE_CLOUD_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _format_qq_remaining(value: Any, now_ms: Optional[int] = None) -> str:
    expire_ms = _qq_expire_at_ms(value, now_ms=now_ms)
    if expire_ms is None:
        return "剩余有效期：无限期"
    remaining_seconds = max(0, int((expire_ms - (now_ms or int(_time.time() * 1000))) / 1000))
    if remaining_seconds <= 0:
        return "剩余有效期：已过期"
    days, remainder = divmod(remaining_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    if days:
        return f"剩余有效期：{days}天{hours}小时"
    if hours:
        return f"剩余有效期：{hours}小时{minutes}分钟"
    if minutes:
        return f"剩余有效期：{minutes}分钟"
    return "剩余有效期：不到1分钟"


def _qq_file_metadata(item: Dict[str, Any], sid: str, filename: str, size: int) -> Dict[str, Any]:
    file_id = _qq_nested_value(item, ("sFileId", "fileId", "fid"))
    fetch_code = _qq_nested_value(item, ("sFetchCode", "fetchCode", "code"))
    file_key = _qq_nested_value(item, ("sKey", "key"))
    if not file_id or not fetch_code or not file_key:
        return {}
    expire_value = _qq_nested_value(item, ("nExpireTime", "expireTime", "expire_time", "expireAt"))
    return {
        "filename": str(_qq_nested_value(item, ("sName", "name", "filename")) or filename),
        "size": int(_qq_nested_value(item, ("nSize", "size")) or size),
        "download_url": (
            f"{QQ_FTN_API_HOST}{'/cgi-bin/ftnDownload302'}?"
            + urlencode({"sid": sid, "fid": file_id, "code": fetch_code, "k": file_key})
        ),
        "expire_time": expire_value,
    }


def _qq_upload_bytes(upload_url: str, content: bytes) -> Dict[str, Any]:
    if not upload_url.startswith("https://"):
        raise QQMailMCPError("QQ邮箱返回了不安全的超大附件上传地址")
    request = Request(
        upload_url,
        data=content,
        headers={
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(content)),
            "Cookie": _qq_web_cookie(),
            "Origin": "https://mail.qq.com",
            "Referer": "https://mail.qq.com/",
            "User-Agent": "APEX-Legal-Knowledge-Base/1.0",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=QQ_FTN_UPLOAD_TIMEOUT) as response:
            return _parse_qq_json_payload(response.read())
    except HTTPError as exc:
        detail = exc.read(512).decode("utf-8", errors="replace")
        raise QQMailMCPError(f"QQ邮箱超大附件上传失败：HTTP {exc.code} {detail[:180]}") from exc
    except (URLError, OSError) as exc:
        raise QQMailMCPError(f"QQ邮箱超大附件上传失败：{exc}") from exc


def check_qq_large_attachment_session() -> Dict[str, Any]:
    """Validate QQ's official file-transfer session without uploading a file."""
    started = _time.monotonic()
    payload = _qq_current_web_request(QQ_FTN_CURRENT_USERINFO_PATH, params={"bizid": 2})
    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
    return {
        "ok": True,
        "message": "QQ邮箱超大附件网页会话有效",
        "latency_ms": int((_time.monotonic() - started) * 1000),
        "available_bytes": body.get("space_limited"),
        "used_bytes": body.get("used_space"),
    }


def _upload_qq_large_attachments(attachments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Upload files to QQ's official transfer station and return download links."""
    sid = _qq_sid()
    results: List[Dict[str, Any]] = []
    for item in attachments[:MAX_ATTACHMENTS]:
        filename = str(item.get("filename") or "attachment").strip() or "attachment"
        content = item.get("content") or b""
        if not content:
            continue
        if len(content) > QQ_FTN_MAX_FILE_BYTES:
            raise QQMailMCPError(f"附件 {filename} 超过 QQ 邮箱官方超大附件单文件上限")
        sha = hashlib.sha1(content).hexdigest()
        payload = _qq_web_request(
            "GET", QQ_FTN_CREATE_PATH,
            query={"uin": "", "ef": "js", "resp_charset": "UTF8", "s": "ftnCreate", "sid": sid,
                   "dirid": "", "path": filename, "size": len(content), "sha": sha, "sha3": "",
                   "appid": 2, "loc": "ftnCreatefile,ftnCreatefile,ftnCreate,ftn2"},
        )
        error = _qq_payload_error(payload)
        if error:
            raise QQMailMCPError(f"QQ邮箱超大附件创建失败：{filename}：{error}")
        upload_url = _qq_nested_value(payload, ("sUploadUrl", "uploadUrl", "upload_url", "uploadUrlV2"))
        if not upload_url:
            host = _qq_nested_value(payload, ("sUploadHost", "uploadHost", "upload_host", "host"))
            path = _qq_nested_value(payload, ("sUploadPath", "uploadPath", "upload_path", "path"))
            ukey = _qq_nested_value(payload, ("sUKey", "ukey", "uKey", "uploadKey", "token"))
            if host and path:
                upload_url = "https://" + str(host).rstrip("/") + "/" + str(path).lstrip("/")
                if ukey and "ukey=" not in upload_url:
                    upload_url += ("&" if "?" in upload_url else "?") + urlencode({"ukey": ukey})
        if upload_url:
            _qq_upload_bytes(str(upload_url), content)
            payload = _qq_web_request(
                "GET", QQ_FTN_LIST_PATH,
                query={"t": "ftn.json", "s": "list", "ef": "js", "listtype": "self", "up": "down",
                       "sorttype": "createtime", "sid": sid, "page": 0, "pagesize": 100},
            )
        candidates = _qq_file_items(payload)
        if not candidates and isinstance(payload, dict):
            candidates = [payload]
        selected = next(
            (candidate for candidate in candidates
             if str(_qq_nested_value(candidate, ("sName", "name", "filename")) or "") == filename
             and int(_qq_nested_value(candidate, ("nSize", "size")) or len(content)) == len(content)),
            None,
        )
        metadata = _qq_file_metadata(selected or {}, sid, filename, len(content))
        if not metadata:
            raise QQMailMCPError(f"QQ邮箱超大附件上传完成但未返回可下载信息：{filename}")
        results.append(metadata)
    return results


def _cloud_response_data(payload: Any) -> Dict[str, Any]:
    """Normalize the several response envelopes used by the Sirius web API."""
    if not isinstance(payload, dict):
        raise QQMailMCPError("网易云附件接口返回了无效响应")
    code = payload.get("code")
    if code not in (None, 0, "0", 200, "200"):
        message = payload.get("message") or payload.get("msg") or payload.get("errMsg") or str(code)
        raise QQMailMCPError(f"网易云附件接口拒绝请求：{message}")
    data = payload.get("data", payload)
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]
    if not isinstance(data, dict):
        raise QQMailMCPError("网易云附件接口返回了无效数据")
    return data


def _netease_cloud_request(
    method: str,
    path: str,
    *,
    query: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
    form_body: bool = False,
    raw: Optional[bytes] = None,
    headers: Optional[Dict[str, str]] = None,
    parse_json: bool = True,
) -> Any:
    cookie = _netease_web_cookie()
    if not cookie:
        raise QQMailMCPError(
            "未配置网易企业邮箱网页版会话，暂不能调用云附件；"
            "请先在官方网页端登录后配置 NETEASE_EXMAIL_WEB_COOKIE"
        )
    url = path if path.startswith(("http://", "https://")) else NETEASE_CLOUD_API_HOST.rstrip("/") + path
    if query:
        url += "?" + urlencode(query)
    request_headers = {
        "Accept": "application/json, text/plain, */*",
        "Cookie": cookie,
        "Origin": "https://mail.qiye.163.com",
        "Referer": "https://mail.qiye.163.com/",
        "User-Agent": "APEX-Legal-Knowledge-Base/1.0",
    }
    if headers:
        request_headers.update(headers)
    payload = raw
    if body is not None:
        if form_body:
            payload = urlencode(body).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/x-www-form-urlencoded;charset=UTF-8")
        else:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json;charset=UTF-8")
    request = Request(url, data=payload, headers=request_headers, method=method.upper())
    try:
        with urlopen(request, timeout=NETEASE_CLOUD_UPLOAD_TIMEOUT) as response:
            content = response.read()
    except HTTPError as exc:
        detail = exc.read(512).decode("utf-8", errors="replace")
        raise QQMailMCPError(f"网易云附件接口失败：HTTP {exc.code} {detail[:180]}") from exc
    except (URLError, OSError) as exc:
        raise QQMailMCPError(f"无法连接网易云附件接口：{exc}") from exc
    if not content or not parse_json:
        return {}
    try:
        # 网易云附件完成接口偶尔以 UTF-8 BOM 开头；utf-8-sig 同时兼容
        # 带 BOM 与不带 BOM 的 JSON 响应。
        return json.loads(content.decode("utf-8-sig", errors="replace"))
    except (TypeError, ValueError) as exc:
        raise QQMailMCPError("网易云附件接口返回了无法解析的响应") from exc


def check_netease_cloud_session() -> Dict[str, Any]:
    """Validate the saved official-web session without uploading a user file."""
    started = _time.monotonic()
    marker = b"apex-cloud-session-check"
    token_payload = _cloud_response_data(_netease_cloud_request(
        "GET",
        NETEASE_CLOUD_TOKEN_PATH,
        query={
            "fileName": "apex-cloud-session-check.txt",
            "fileSize": len(marker),
            "md5": hashlib.md5(marker).hexdigest(),
        },
    ))
    if not all(str(token_payload.get(name) or "").strip() for name in ("bucketName", "nosKey", "token")):
        raise QQMailMCPError("网易云附件会话无效或已过期，请重新登录官方网页端并更新 Cookie")
    return {
        "ok": True,
        "message": "网易云附件网页会话有效",
        "latency_ms": int((_time.monotonic() - started) * 1000),
    }


def _upload_netease_cloud_attachments(attachments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Upload files to 网易云附件 and return link metadata for the outgoing mail.

    The official web client stores the binary outside the SMTP MIME message.  The
    SMTP adapter cannot manufacture the proprietary native attachment envelope, so
    the returned download URL is placed in the message body as a cloud-attachment
    link.  This still avoids encoding the original bytes into SMTP and keeps the
    link backed by 网易's cloud attachment service.
    """
    results: List[Dict[str, Any]] = []
    for item in attachments[:MAX_ATTACHMENTS]:
        filename = str(item.get("filename") or "attachment").strip() or "attachment"
        content = item.get("content") or b""
        if not content:
            continue
        token_payload = _cloud_response_data(_netease_cloud_request(
            "GET",
            NETEASE_CLOUD_TOKEN_PATH,
            query={
                "fileName": filename,
                "fileSize": len(content),
                "md5": hashlib.md5(content).hexdigest(),
            },
        ))
        bucket = str(token_payload.get("bucketName") or "").strip()
        object_key = str(token_payload.get("nosKey") or "").strip()
        upload_token = str(token_payload.get("token") or "").strip()
        if not bucket or not object_key or not upload_token:
            raise QQMailMCPError(f"网易云附件未返回有效上传令牌：{filename}")
        upload_host = str(token_payload.get("uploadHost") or NETEASE_CLOUD_API_HOST).rstrip("/")
        upload_url = f"{upload_host}/{quote(bucket, safe='')}/{quote(object_key, safe='/')}"
        _netease_cloud_request(
            "PUT",
            upload_url,
            raw=content,
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Length": str(len(content)),
                "x-nos-token": upload_token,
            },
            parse_json=False,
        )
        finished = _cloud_response_data(_netease_cloud_request(
            "POST",
            NETEASE_CLOUD_FINISH_PATH,
            body={
                "fileId": token_payload.get("fileId"),
                "nosKey": object_key,
                "fileSize": len(content),
            },
            form_body=True,
        ))
        download_url = str(finished.get("downloadUrl") or finished.get("fileUrl") or "").strip()
        identity = str(finished.get("identity") or "").strip()
        if not download_url and not identity:
            raise QQMailMCPError(f"网易云附件上传完成但未返回下载地址：{filename}")
        results.append({
            "filename": filename,
            "size": len(content),
            "download_url": download_url,
            "identity": identity,
            "expire_time": finished.get("expireTime"),
        })
    return results


_NETEASE_CLOUD_TZ = _datetime.timezone(_datetime.timedelta(hours=8))


def _netease_cloud_expire_ms(value: Any) -> Optional[int]:
    """Normalize the cloud API's expiry value to epoch milliseconds."""
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    # The web API currently returns milliseconds; accept seconds for fixtures
    # and future protocol variants as well.
    if number < 10_000_000_000:
        number *= 1000
    return int(number)


def _format_netease_cloud_expire_time(value: Any) -> str:
    expire_ms = _netease_cloud_expire_ms(value)
    if expire_ms is None:
        return "—"
    date = _datetime.datetime.fromtimestamp(expire_ms / 1000, tz=_NETEASE_CLOUD_TZ)
    return date.strftime("%Y-%m-%d %H:%M:%S")


def _format_netease_cloud_size(size: Any) -> str:
    try:
        megabytes = max(0, int(size or 0)) / (1024 * 1024)
    except (TypeError, ValueError):
        megabytes = 0
    return f"{megabytes:.2f}M"


def _format_netease_cloud_remaining(value: Any, now_ms: Optional[int] = None) -> str:
    expire_ms = _netease_cloud_expire_ms(value)
    if expire_ms is None:
        return "剩余有效期：以网易企业邮箱为准"
    remaining_seconds = max(0, int((expire_ms - (now_ms or int(_time.time() * 1000))) / 1000))
    if remaining_seconds <= 0:
        return "剩余有效期：已过期"
    days, remainder = divmod(remaining_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    if days:
        return f"剩余有效期：{days}天{hours}小时"
    if hours:
        return f"剩余有效期：{hours}小时{minutes}分钟"
    if minutes:
        return f"剩余有效期：{minutes}分钟"
    return "剩余有效期：不到1分钟"


def _append_cloud_attachment_links(
    body: str,
    body_html: str,
    cloud_items: List[Dict[str, Any]],
) -> Tuple[str, str]:
    if not cloud_items:
        return body, body_html
    lines = ["", "企业邮箱云附件："]
    html_lines = []
    html_lines.append(
        '<div data-apex-cloud-attachment="1" style="max-width:760px;margin:18px 0;'
        'border:1px solid #e4e7ec;border-radius:14px;background:#fff;overflow:hidden;'
        'font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',\'PingFang SC\','
        '\'Microsoft YaHei\',sans-serif;color:#252a34;box-shadow:0 3px 14px rgba(31,41,55,.08);">'
        '<div style="padding:15px 18px;border-bottom:1px solid #e9ebef;font-size:18px;'
        'font-weight:700;line-height:1.4;">网易企业邮箱云附件</div>'
    )
    for item in cloud_items:
        name = str(item.get("filename") or "附件")
        url = str(item.get("download_url") or "").strip()
        expire_value = item.get("expire_time")
        expire_ms = _netease_cloud_expire_ms(expire_value)
        expire_text = _format_netease_cloud_expire_time(expire_value)
        remaining_text = _format_netease_cloud_remaining(expire_value)
        size_text = _format_netease_cloud_size(item.get("size"))
        if expire_ms is not None:
            lines.append(
                f"- {name}  {size_text} | 过期时间：{expire_text} | {remaining_text}"
            )
        else:
            lines.append(f"- {name}  {size_text} | {remaining_text}")
        if url:
            lines.append(f"  下载：{url}")
            html_lines.append(
                '<div style="display:flex;align-items:center;gap:14px;padding:18px 20px;">'
                '<div aria-hidden="true" style="flex:0 0 auto;width:54px;height:54px;display:flex;'
                'align-items:center;justify-content:center;border-radius:7px;background:#72a8f5;'
                'color:#fff;font-size:31px;line-height:1;">☁</div>'
                '<div style="min-width:0;flex:1;">'
                f'<div style="font-size:19px;line-height:1.45;word-break:break-all;">{_html.escape(name)}</div>'
                f'<div style="margin-top:5px;color:#a1a4aa;font-size:16px;line-height:1.5;">'
                f'{_html.escape(size_text)}'
                f' <span style="padding:0 5px;">|</span> 过期时间：{_html.escape(expire_text)}'
                f' <span style="padding:0 5px;">|</span> '
                f'<span data-cloud-expire-at="{_html.escape(str(expire_ms or ""), quote=True)}">{_html.escape(remaining_text)}</span>'
                '</div></div>'
                f'<a href="{_html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer" '
                'style="flex:0 0 auto;color:#4f86c9;font-size:19px;text-decoration:none;">下载</a></div>'
            )
        else:
            lines.append("  请在网易企业邮箱网页端打开此邮件查看云附件")
            html_lines.append(
                '<div style="display:flex;align-items:center;gap:14px;padding:18px 20px;">'
                '<div aria-hidden="true" style="flex:0 0 auto;width:54px;height:54px;display:flex;'
                'align-items:center;justify-content:center;border-radius:7px;background:#72a8f5;'
                'color:#fff;font-size:31px;line-height:1;">☁</div>'
                '<div style="min-width:0;flex:1;">'
                f'<div style="font-size:19px;line-height:1.45;word-break:break-all;">{_html.escape(name)}</div>'
                f'<div style="margin-top:5px;color:#a1a4aa;font-size:16px;line-height:1.5;">'
                f'{_html.escape(size_text)} <span style="padding:0 5px;">|</span> 过期时间：{_html.escape(expire_text)}'
                f' <span style="padding:0 5px;">|</span> '
                f'<span data-cloud-expire-at="{_html.escape(str(expire_ms or ""), quote=True)}">{_html.escape(remaining_text)}</span>'
                '</div></div>'
                '<span style="flex:0 0 auto;color:#9aa0aa;font-size:15px;">请在网页版查看</span></div>'
            )
    html_lines.append("</div>")
    return (body or "") + "\n".join(lines), (body_html or "") + "".join(html_lines)


def _append_qq_large_attachment_links(
    body: str,
    body_html: str,
    items: List[Dict[str, Any]],
) -> Tuple[str, str]:
    """Render QQ official-transfer links in the same readable card style."""
    if not items:
        return body, body_html
    lines = ["", "QQ邮箱超大附件："]
    html_lines = [
        '<div data-apex-qq-large-attachment="1" style="max-width:760px;margin:18px 0;'
        'border:1px solid #e4e7ec;border-radius:14px;background:#fff;overflow:hidden;'
        'font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',\'PingFang SC\','
        '\'Microsoft YaHei\',sans-serif;color:#252a34;box-shadow:0 3px 14px rgba(31,41,55,.08);">'
        '<div style="padding:15px 18px;border-bottom:1px solid #e9ebef;font-size:18px;'
        'font-weight:700;line-height:1.4;">QQ邮箱超大附件</div>'
    ]
    for item in items:
        name = str(item.get("filename") or "附件")
        url = str(item.get("download_url") or "").strip()
        size_text = _format_netease_cloud_size(item.get("size"))
        expire_value = item.get("expire_time")
        expire_ms = _qq_expire_at_ms(expire_value)
        expire_text = _format_qq_expire_time(expire_value)
        remaining_text = _format_qq_remaining(expire_value)
        lines.append(f"- {name}  {size_text} | 过期时间：{expire_text} | {remaining_text}")
        if url:
            lines.append(f"  下载：{url}")
        html_lines.append(
            '<div style="display:flex;align-items:center;gap:14px;padding:18px 20px;">'
            '<div aria-hidden="true" style="flex:0 0 auto;width:54px;height:54px;display:flex;'
            'align-items:center;justify-content:center;border-radius:7px;background:#72a8f5;'
            'color:#fff;font-size:31px;line-height:1;">☁</div>'
            '<div style="min-width:0;flex:1;">'
            f'<div style="font-size:19px;line-height:1.45;word-break:break-all;">{_html.escape(name)}</div>'
            f'<div style="margin-top:5px;color:#a1a4aa;font-size:16px;line-height:1.5;">'
            f'{_html.escape(size_text)} <span style="padding:0 5px;">|</span> 过期时间：{_html.escape(expire_text)}'
            f' <span style="padding:0 5px;">|</span> '
            f'<span data-qq-expire-at="{_html.escape(str(expire_ms or ""), quote=True)}">{_html.escape(remaining_text)}</span>'
            '</div></div>'
            + (f'<a href="{_html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer" '
               'style="flex:0 0 auto;color:#4f86c9;font-size:19px;text-decoration:none;">下载</a>'
               if url else '<span style="flex:0 0 auto;color:#9aa0aa;font-size:15px;">请在网页版查看</span>')
            + '</div>'
        )
    html_lines.append("</div>")
    return (body or "") + "\n".join(lines), (body_html or "") + "".join(html_lines)


def _build_smtp_message(
    address: str,
    label: str,
    to: str,
    subject: str,
    body: str,
    body_html: str,
    cc: str,
    attachments: List[Dict[str, Any]],
) -> Any:
    """构造一封普通 MIME 邮件，返回 email.message.Message。"""
    from email.header import Header
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.utils import formataddr

    message = MIMEMultipart()
    message["From"] = formataddr((str(Header(label, "utf-8")), address))
    message["To"] = to
    message["Subject"] = subject or "（无主题）"
    if cc.strip():
        message["Cc"] = cc
    if body_html.strip():
        alternative = MIMEMultipart("alternative")
        alternative.attach(MIMEText(body or "", "plain", "utf-8"))
        alternative.attach(MIMEText(body_html, "html", "utf-8"))
        message.attach(alternative)
    else:
        message.attach(MIMEText(body or "", "plain", "utf-8"))
    for item in attachments[:MAX_ATTACHMENTS]:
        filename = str(item.get("filename") or "attachment").strip()
        data = item.get("content") or b""
        if not filename or not data:
            continue
        part = MIMEApplication(data, _subtype="octet-stream")
        part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", filename))
        message.attach(part)
    return message


def _render_pdf_pages(reader: Any, start: int, end: int) -> bytes:
    """将 [start, end) 页复制成一个新的 PDF。"""
    from io import BytesIO
    from PyPDF2 import PdfWriter

    output = BytesIO()
    writer = PdfWriter()
    for index in range(start, end):
        writer.add_page(reader.pages[index])
    writer.write(output)
    return output.getvalue()


def _split_large_pdf_attachment(
    pdf_item: Dict[str, Any],
    other_attachments: List[Dict[str, Any]],
    address: str,
    label: str,
    to: str,
    subject: str,
    body: str,
    body_html: str,
    cc: str,
) -> List[Dict[str, Any]]:
    """按页拆分一个大 PDF，使每个分卷都能放入普通 SMTP 邮件。"""
    from io import BytesIO
    from pathlib import PurePath

    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(BytesIO(pdf_item.get("content") or b""))
    except Exception as exc:
        raise QQMailMCPError(
            f"附件 {pdf_item.get('filename') or 'PDF'} 无法自动分卷，请改用超大附件或链接发送"
        ) from exc
    page_count = len(reader.pages)
    if page_count < 2:
        raise QQMailMCPError(
            f"附件 {pdf_item.get('filename') or 'PDF'} 只有一页且超过普通 SMTP 大小，"
            "请改用当前邮箱的超大附件或链接发送"
        )

    original_name = str(pdf_item.get("filename") or "attachment.pdf")
    path = PurePath(original_name)
    stem = path.stem or "attachment"
    suffix = path.suffix or ".pdf"
    # 预留足够长的分卷后缀，避免实际的“第 n/m 卷”标题使邮件越过阈值。
    probe_filename = f"{stem}-第999卷-共999卷{suffix}"
    split_body = (body or "") + "\n\n（原附件已自动按页分卷发送，请按邮件主题中的卷号查收。）"
    split_body_html = body_html
    if split_body_html.strip():
        split_body_html += "<p>（原附件已自动按页分卷发送，请按邮件主题中的卷号查收。）</p>"

    parts: List[Dict[str, Any]] = []
    start = 0
    while start < page_count:
        extras = other_attachments if start == 0 else []
        low, high = start + 1, page_count
        best_end = None
        best_bytes = None
        while low <= high:
            end = (low + high) // 2
            candidate = {"filename": probe_filename, "content": _render_pdf_pages(reader, start, end)}
            message = _build_smtp_message(
                address, label, to, f"{subject or '（无主题）'} [第 999/999 卷]",
                split_body, split_body_html, cc, [candidate] + extras,
            )
            if len(message.as_bytes()) <= MAX_SMTP_MESSAGE_BYTES:
                best_end, best_bytes = end, candidate["content"]
                low = end + 1
            else:
                high = end - 1
        if best_end is None or best_bytes is None:
            raise QQMailMCPError(
                f"附件 {original_name} 存在单页超过普通 SMTP 安全上限，"
                "请改用当前邮箱的超大附件或链接发送"
            )
        parts.append({"filename": "", "content": best_bytes})
        start = best_end

    total = len(parts)
    for index, item in enumerate(parts, start=1):
        item["filename"] = f"{stem}-第{index}卷-共{total}卷{suffix}"
    return parts


def _send_smtp_message(
    account: str,
    address: str,
    login_address: str,
    auth_code: str,
    recipients: List[str],
    message_bytes: bytes,
) -> None:
    """提交一封 SMTP 邮件，并保留服务器直接拒收的收件人信息。"""
    import smtplib

    label = _account_config(account)["label"]
    host, port = SMTP_HOSTS[account]
    client = None
    try:
        client = smtplib.SMTP_SSL(host, port, timeout=30)
        client.login(login_address, auth_code)
        refused = client.sendmail(address, recipients, message_bytes)
        if isinstance(refused, dict) and refused:
            details = []
            for recipient, error in refused.items():
                if isinstance(error, tuple) and len(error) >= 2:
                    reason = error[1]
                    if isinstance(reason, bytes):
                        reason = reason.decode("utf-8", errors="replace")
                    details.append(f"{recipient}：{error[0]} {reason}")
                else:
                    details.append(f"{recipient}：{error}")
            raise QQMailMCPError(f"{label}拒收收件人，邮件未完成提交：" + "；".join(details))
    except smtplib.SMTPAuthenticationError as exc:
        raise QQMailMCPError(f"{label}发信认证失败，请检查授权码") from exc
    except smtplib.SMTPDataError as exc:
        reason = exc.smtp_error
        if isinstance(reason, bytes):
            reason = reason.decode("utf-8", errors="replace")
        if exc.smtp_code == 552 or "size" in str(reason).lower():
            raise QQMailMCPError(
                f"{label}拒绝发送：邮件大小超过 SMTP 或收件方上限。"
                "请拆分附件，或改用当前邮箱超大附件/网盘链接后再发送"
            ) from exc
        raise QQMailMCPError(f"发送失败：{exc.smtp_code} {reason}") from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise QQMailMCPError(f"发送失败：{exc}") from exc
    finally:
        if client is not None:
            try:
                client.quit()
            except (smtplib.SMTPException, OSError):
                pass


def send_mail(
    account: str,
    to: str,
    subject: str,
    body: str,
    body_html: str = "",
    cc: str = "",
    bcc: str = "",
    attachments: Optional[List[Dict[str, Any]]] = None,
    use_cloud_attachments: bool = False,
    use_large_attachments: bool = False,
) -> Dict[str, Any]:
    """通过 SMTP 发送邮件；网易云附件和 QQ 超大附件分别走官方网页通道。"""
    config = _account_config(account)
    label = config["label"]
    address, auth_code = _credentials(account)
    if use_cloud_attachments and account != "netease_exmail":
        raise QQMailMCPError("云附件目前仅支持网易企业邮箱，请切换发件账号")
    if use_large_attachments and account != "qq_mail":
        raise QQMailMCPError("QQ超大附件目前仅支持 QQ邮箱，请切换发件账号")
    login_address = _login_address(account)
    if not to or not to.strip():
        raise QQMailMCPError("收件人不能为空")
    recipients = [item.strip() for item in re.split(r"[,;，；]", to) if item.strip()]
    if not recipients:
        raise QQMailMCPError("收件人地址无效")

    all_recipients = list(recipients)
    if cc.strip():
        all_recipients.extend(item.strip() for item in re.split(r"[,;，；]", cc) if item.strip())
    if bcc.strip():
        all_recipients.extend(item.strip() for item in re.split(r"[,;，；]", bcc) if item.strip())

    original_attachments = list((attachments or [])[:MAX_ATTACHMENTS])
    outgoing_body = body
    outgoing_body_html = body_html
    cloud_items: List[Dict[str, Any]] = []
    cloud_fallback_reason = ""
    cloud_attempted = False
    large_items: List[Dict[str, Any]] = []
    large_fallback_reason = ""
    large_attempted = False
    # 明确勾选云附件时，全部附件转云；网易大邮件即使没有勾选，也自动尝试
    # 云附件，避免再次把 80MB 级文件送进 SMTP MIME 编码流程。
    cloud_should_attempt = bool(
        account == "netease_exmail"
        and original_attachments
        and (use_cloud_attachments or len(
            _build_smtp_message(address, label, to, subject, body, body_html, cc, original_attachments
            ).as_bytes()
        ) > MAX_SMTP_MESSAGE_BYTES)
    )
    if cloud_should_attempt:
        cloud_attempted = True
        try:
            cloud_items = _upload_netease_cloud_attachments(original_attachments)
            if len(cloud_items) != len([item for item in original_attachments if item.get("content")]):
                raise QQMailMCPError("网易云附件未完成全部文件上传")
            outgoing_body, outgoing_body_html = _append_cloud_attachment_links(
                body, body_html, cloud_items,
            )
            original_attachments = []
        except QQMailMCPError as exc:
            cloud_fallback_reason = str(exc)
            cloud_items = []

    large_should_attempt = bool(
        account == "qq_mail"
        and original_attachments
        and (use_large_attachments or len(
            _build_smtp_message(address, label, to, subject, body, body_html, cc, original_attachments
            ).as_bytes()
        ) > MAX_SMTP_MESSAGE_BYTES)
    )
    if large_should_attempt:
        large_attempted = True
        try:
            large_items = _upload_qq_large_attachments(original_attachments)
            if len(large_items) != len([item for item in original_attachments if item.get("content")]):
                raise QQMailMCPError("QQ邮箱超大附件未完成全部文件上传")
            outgoing_body, outgoing_body_html = _append_qq_large_attachment_links(
                outgoing_body, outgoing_body_html, large_items,
            )
            original_attachments = []
        except QQMailMCPError as exc:
            large_fallback_reason = str(exc)
            large_items = []

    message = _build_smtp_message(
        address, label, to, subject, outgoing_body, outgoing_body_html, cc, original_attachments,
    )
    message_bytes = message.as_bytes()
    submitted_messages = 0
    split = False
    if len(message_bytes) <= MAX_SMTP_MESSAGE_BYTES:
        deliveries = [(
            subject or "（无主题）", outgoing_body, outgoing_body_html, original_attachments, message_bytes,
        )]
    else:
        pdf_indexes = [
            index for index, item in enumerate(original_attachments)
            if str(item.get("filename") or "").lower().endswith(".pdf") and item.get("content")
        ]
        if not pdf_indexes:
            size_mib = len(message_bytes) / (1024 * 1024)
            limit_mib = MAX_SMTP_MESSAGE_BYTES / (1024 * 1024)
            raise QQMailMCPError(
                f"邮件总大小约 {size_mib:.1f}MB，超过普通 SMTP 安全上限 {limit_mib:.0f}MB。"
                + (f"QQ超大附件上传失败：{large_fallback_reason}" if account == "qq_mail" and large_fallback_reason else "当前仅支持自动拆分多页 PDF；请将其他大附件改用对应邮箱的超大附件或链接发送")
            )
        split_index = max(pdf_indexes, key=lambda index: len(original_attachments[index].get("content") or b""))
        pdf_item = original_attachments[split_index]
        other_attachments = original_attachments[:split_index] + original_attachments[split_index + 1:]
        split_parts = _split_large_pdf_attachment(
            pdf_item, other_attachments, address, label, to, subject,
            outgoing_body, outgoing_body_html, cc,
        )
        split = True
        deliveries = []
        total = len(split_parts)
        split_body = (outgoing_body or "") + "\n\n（原附件已自动按页分卷发送，请按邮件主题中的卷号查收。）"
        split_body_html = outgoing_body_html
        if split_body_html.strip():
            split_body_html += "<p>（原附件已自动按页分卷发送，请按邮件主题中的卷号查收。）</p>"
        for index, part in enumerate(split_parts, start=1):
            part_subject = f"{subject or '（无主题）'} [第 {index}/{total} 卷]"
            part_attachments = [part]
            if index == 1:
                part_attachments = other_attachments + part_attachments
            part_message = _build_smtp_message(
                address, label, to, part_subject, split_body, split_body_html, cc, part_attachments,
            )
            part_bytes = part_message.as_bytes()
            if len(part_bytes) > MAX_SMTP_MESSAGE_BYTES:
                raise QQMailMCPError(
                    f"自动分卷后的第 {index}/{total} 卷仍超过普通 SMTP 大小，"
                    "请改用当前邮箱的超大附件或链接发送"
                )
            deliveries.append((part_subject, split_body, split_body_html, part_attachments, part_bytes))

    for part_subject, _, _, part_attachments, part_bytes in deliveries:
        _send_smtp_message(account, address, login_address, auth_code, all_recipients, part_bytes)
        # QQ/腾讯企业邮箱不会稳定地替 SMTP 发信保存“已发送”，因此由本地补写一份；
        # 网易会自动保存，不能再 APPEND，否则会在“已发送”中出现两个相同副本。
        if config.get("smtp_server_saves_sent"):
            saved_to_sent = True
        else:
            saved_to_sent = _append_message(account, "sent", part_bytes, "(\\Seen)")
        submitted_messages += 1

    _record_contacts(account, to, cc)
    return {
        "success": True,
        "submitted_to_smtp": True,
        "submitted_messages": submitted_messages,
        "split_into_parts": split,
        "to": recipients,
        "cc": bool(cc.strip()),
        "bcc": bool(bcc.strip()),
        "saved_to_sent": bool(saved_to_sent),
        "cloud_attachment_count": len(cloud_items),
        "cloud_attachment_mode": "netease_cloud_link" if cloud_items else "normal_mime",
        "cloud_attempted": cloud_attempted,
        "cloud_fallback_reason": cloud_fallback_reason,
        "large_attachment_count": len(large_items),
        "large_attachment_mode": "qq_ftn_link" if large_items else "normal_mime",
        "large_attachment_attempted": large_attempted,
        "large_attachment_fallback_reason": large_fallback_reason,
    }


def _append_message(account: str, folder: str, message_bytes: bytes, flags: str = "") -> bool:
    client = None
    try:
        client = _connect(account)
        status, _ = client.append(_folder_name(folder, account), flags, None, message_bytes)
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
    wanted = str(name or "").lower()
    for element in root.iter():
        if _xml_local(element.tag).lower() == wanted:
            return str(element.text or "").strip()
    return ""


def _clean_amount(value: str) -> str:
    from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
    if value is None or str(value).strip() == "":
        return ""
    text = str(value).replace("−", "-").replace("－", "-")
    cleaned = re.sub(r"[¥￥,\s]", "", text)
    match = re.search(r"[-+]?\d+(?:\.\d+)?", cleaned)
    if not match:
        return ""
    try:
        amount = Decimal(match.group(0))
        if cleaned.startswith("(") and cleaned.endswith(")"):
            amount = -abs(amount)
        return str(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except InvalidOperation:
        return ""


def _capital_invoice_amount(value):
    """Decode the labelled RMB capital total when OCR loses the numeric total."""
    from decimal import Decimal
    match = re.fullmatch(r"(负?)([零壹贰叁肆伍陆柒捌玖拾佰仟万亿]+)[元圆]([零壹贰叁肆伍陆柒捌玖角分整正]*)", value)
    if not match:
        return ""
    digits = {character: index for index, character in enumerate("零壹贰叁肆伍陆柒捌玖")}
    small = {"拾": 10, "佰": 100, "仟": 1000}
    total = section = number = 0
    for character in match.group(2):
        if character in digits:
            number = digits[character]
        elif character in small:
            section += (number or 1) * small[character]
            number = 0
        else:
            section += number
            if character == "万":
                total += section * 10000
            else:
                total = (total + section) * 100000000
            section = number = 0
    amount = Decimal(total + section + number)
    fraction = match.group(3)
    for unit, divisor in (("角", 10), ("分", 100)):
        part = re.search(r"([零壹贰叁肆伍陆柒捌玖])" + unit, fraction)
        if part:
            amount += Decimal(digits[part.group(1)]) / divisor
    if match.group(1):
        amount = -amount
    return f"{amount:.2f}"


def _clean_issue_time(value: str) -> str:
    if not value:
        return ""
    text = str(value).strip()
    match = re.search(r"(\d{4})\s*[年./-]\s*(\d{1,2})\s*[月./-]\s*(\d{1,2})(?:\s*日)?", text)
    if not match:
        match = re.search(r"(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)", text)
    if not match:
        return ""
    try:
        date = _datetime.date(*(int(part) for part in match.groups()))
        return f"{date.year:04d}年{date.month:02d}月{date.day:02d}日"
    except ValueError:
        return ""


def _parse_xml_invoice_root(root: Any) -> Dict[str, str]:
    seller = (
        _xml_text(root, "SellerName")
        or _xml_text(root, "Seller")
        or _xml_text(root, "SellerEnterpriseName")
    )
    issue_time = (
        _xml_text(root, "IssueTime")
        or _xml_text(root, "InvoiceDate")
        or _xml_text(root, "IssueDate")
        or _xml_text(root, "RequestTime")
    )
    amount = (
        _xml_text(root, "TotalTax-includedAmount")
        or _xml_text(root, "TaxIncludedAmount")
        or _xml_text(root, "TotaltaxIncludedAmount")
        or _xml_text(root, "TotalTaxIncludedAmount")
        or _xml_text(root, "TotalAmount")
        or _xml_text(root, "TotalTaxAndFee")
        or _xml_text(root, "AmountInFiguers")
    )
    if not amount and _xml_text(root, "TotalAmWithoutTax"):
        from decimal import Decimal
        subtotal = _clean_amount(_xml_text(root, "TotalAmWithoutTax"))
        tax = _clean_amount(_xml_text(root, "TotalTaxAmount") or _xml_text(root, "TotalTaxAm") or "0")
        if subtotal and tax:
            amount = str(Decimal(subtotal) + Decimal(tax))
    amount = amount or _xml_text(root, "Amount")
    return {
        "issuer": seller[:120],
        "amount": _clean_amount(amount),
        "issue_time": _clean_issue_time(issue_time),
        "invoice_number": (_xml_text(root, "InvoiceNumber") or _xml_text(root, "InvoiceNo") or _xml_text(root, "Fphm")),
        "invoice_code": _xml_text(root, "InvoiceCode") or _xml_text(root, "Fpdm"),
    }


def _invoice_archive_members(archive):
    entries = archive.infolist()
    if len(entries) > 500 or sum(item.file_size for item in entries) > 50 * 1024 * 1024:
        raise QQMailMCPError("发票压缩包超过安全读取上限")
    return entries


def _parse_xml_invoice(path: Path) -> Dict[str, str]:
    import xml.etree.ElementTree as ET
    import zipfile
    try:
        raw = path.read_bytes()
    except OSError:
        return {}
    candidates = [raw]
    # 广东数电发票的 XML 下载接口有时返回“带一层 ZIP 容器的 XML”，
    # 文件扩展名仍然是 .xml。先解容器再走同一套字段解析。
    if zipfile.is_zipfile(path):
        try:
            with zipfile.ZipFile(path) as archive:
                candidates = [
                    archive.read(item) for item in _invoice_archive_members(archive)
                    if not item.is_dir() and item.filename.lower().endswith(".xml")
                ] or candidates
        except (OSError, zipfile.BadZipFile, QQMailMCPError):
            return {}
    for candidate in candidates:
        try:
            root = ET.fromstring(candidate)
        except ET.ParseError:
            continue
        meta = _parse_xml_invoice_root(root)
        if any(meta.values()):
            return meta
    return {}


_OFD_COMPANY_PATTERN = re.compile(
    r"([\u4e00-\u9fa5（）()·]{4,60}(?:公司|集团|店|工作室|事务所|中心|服务部|商行|经营部))[^¥\u4e00-\u9fa5]*?¥"
)
_OFD_CAPITAL_AMOUNT_PATTERN = re.compile(
    r"[零壹贰叁肆伍陆柒捌玖拾佰仟万亿圆整角分]+((?:[-−－]\s*)?[¥￥]\s*[-−－]?[0-9,]+\.\d{2})"
)
_OFD_AMOUNT_PATTERN = re.compile(r"((?:[-−－]\s*)?[¥￥]\s*[-−－]?[0-9,]+\.\d{2})")
_OFD_DATE_PATTERN = re.compile(r"(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)")


def _parse_ofd_invoice(path: Path) -> Dict[str, str]:
    import zipfile
    import xml.etree.ElementTree as ET
    try:
        with zipfile.ZipFile(str(path)) as archive:
            content_names = [
                item.filename for item in _invoice_archive_members(archive)
                for name in [item.filename] if "/Pages/" in name and name.endswith("Content.xml")
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
    except (zipfile.BadZipFile, OSError, RuntimeError, QQMailMCPError):
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
    return {"issuer": issuer, "amount": amount, "issue_time": issue_time, "invoice_number": _invoice_number_from_text(text), "invoice_code": _invoice_code_from_text(text)}


_PDF_SELLER_PATTERNS = (
    re.compile(r"销售方名称[:：]?\s*([^\n\r]{2,80})"),
    re.compile(r"名称[:：]\s*([^\n\r]{2,80})"),
)
_PDF_AMOUNT_PATTERNS = (
    re.compile(r"(?:价税合计|小写)[\s\S]{0,100}?((?:[-−－]\s*)?[¥￥]\s*[-−－]?[0-9,]+\.\d{2})"),
    re.compile(r"[（(]小写[)）]\s*((?:[-−－]\s*)?[¥￥]?\s*[-−－]?[0-9,]+\.\d{2})"),
    re.compile(r"((?:[-−－]\s*)?[¥￥]\s*[-−－]?[0-9,]+\.\d{2})"),
)
_PDF_DATE_PATTERNS = (
    re.compile(r"开票日期[:：]\s*(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)"),
    re.compile(r"(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)"),
)


_PDF_COMPANY_PATTERN = re.compile(
    r"([\u4e00-\u9fa5（）()·]{3,60}(?:公司|集团|店|工作室|事务所|中心|服务部|商行|经营部|餐厅|酒店|饭店|食府|学院|学校|医院|银行|支行|分公司|分店))"
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
    meta = _parse_invoice_text(text)
    # Scanned invoice PDFs have no usable text layer. OCR only likely invoices,
    # with a page bound so ordinary case bundles never trigger unbounded work.
    if not meta.get("amount") and _is_invoice_attachment_name(path.name):
        try:
            from .court_directory import _vision_ocr_image
            with fitz.open(str(path)) as document:
                if len(document) == 1:
                    ocr_text = "\n".join(_vision_ocr_image(page.get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes("png")) for page in document)
                    recovered = _parse_invoice_text(ocr_text)
                    for key, value in recovered.items():
                        if value and not meta.get(key):
                            meta[key] = value
        except Exception:
            pass
    return meta


def _parse_invoice_text(text):
    text = text.replace("\u3000", " ")
    header = re.sub(r"\s+", "", text)[:160]
    if not re.search(r"发\s*票\s*(?:号\s*码|代\s*码)|价\s*税\s*合\s*计|tax\s+invoice|receipt", text, re.I) and not ("收据" in header and "合同" not in header):
        return {}
    issuer = ""
    # 数电票的 PDF 文本层经常把“名称：”标签和值分离到不同列，
    # 不能用跨行的 `\s*` 贪婪匹配，否则会把“下载次数：1”误当成开票人。
    companies = list(_PDF_COMPANY_PATTERN.finditer(text))
    if companies:
        # 文本层通常按购买方 → 销售方排列，最后一个企业名是销售方；
        # 对“销售方名称：xxx”仍优先取标签附近的值。
        seller_block = text.find("销售方信息")
        candidates = [
            match for match in companies
            if (seller_block < 0 or match.start() >= seller_block)
            and not re.search(r"开户银行|银行|支行", match.group(1))
        ]
        if candidates:
            issuer = candidates[-1].group(1)[:120]
        else:
            issuer = companies[-1].group(1)[:120]
    for pattern in _PDF_SELLER_PATTERNS:
        if issuer:
            break
        match = pattern.search(text)
        if match:
            candidate = re.sub(r"[\s:：]", "", match.group(1))
            if (
                candidate and candidate not in ("名称", "开票人", "下载次数1")
                and not re.fullmatch(r"下载次数\d+", candidate)
            ):
                issuer = candidate[:120]
                break
    amount = ""
    total_match = re.search(r"价税合计[\s\S]{0,260}", text)
    # PDF streams frequently place the printed total before subtotal/tax values.
    # A labelled capital total is independent of that drawing order.
    capital = re.search(r"负?[零壹贰叁肆伍陆柒捌玖拾佰仟万亿]+[元圆][零壹贰叁肆伍陆柒捌玖角分整正]*", text)
    if total_match and capital:
        amount = _capital_invoice_amount(capital.group(0))
    if not amount and total_match:
        # 文本层常按列顺序输出“金额、税额、价税合计”，所以“价税合计”
        # 后的最后一个货币值才是含税总额，不能取遇到的第一个金额。
        total_values = re.findall(r"((?:[-−－]\s*)?[¥￥]\s*[-−－]?[0-9,]+\.\d{2})", total_match.group(0))
        if total_values:
            amount = _clean_amount(total_values[-1])
    if not amount and total_match:
        values = re.findall(r"(?<![\d.])[-−－]?[0-9,]{1,16}\.\d{2}(?![\d.])", total_match.group(0))
        if values:
            amount = _clean_amount(values[-1])
    if not amount and total_match:
        capital = re.search(r"负?[零壹贰叁肆伍陆柒捌玖拾佰仟万亿]+[元圆][零壹贰叁肆伍陆柒捌玖角分整正]*", total_match.group(0))
        if capital:
            amount = _capital_invoice_amount(capital.group(0))
    for pattern in _PDF_AMOUNT_PATTERNS:
        if amount:
            break
        match = pattern.search(text)
        if match:
            amount = _clean_amount(match.group(1))
            if amount:
                break
    # 如果 PDF 文本层没有“年/月/日”分隔符，也接受税务平台常见的
    # YYYYMMDD 开票日期。
    issue_time = ""
    for pattern in _PDF_DATE_PATTERNS:
        match = pattern.search(text)
        if match:
            raw = re.sub(r"\s", "", match.group(1))
            issue_time = _clean_issue_time(raw)
            if issue_time:
                break
    return {"issuer": issuer, "amount": amount, "issue_time": issue_time, "invoice_number": _invoice_number_from_text(text), "invoice_code": _invoice_code_from_text(text)}


def _parse_csv_invoice(path: Path) -> Dict[str, str]:
    try:
        raw = path.read_bytes()
    except OSError:
        return {}
    text = ""
    for encoding in ("utf-8-sig", "gb18030", "utf-8"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if not text:
        return {}
    import csv
    import io
    try:
        table = list(csv.reader(io.StringIO(text)))
    except csv.Error:
        table = []
    table = [row for row in table if any(cell.strip() for cell in row)]
    if len(table) >= 2 and len(table[0]) >= 3:
        headers = [re.sub(r"[\s（）()]", "", cell).lower() for cell in table[0]]
        def column(*aliases):
            return next((i for alias in aliases for i, name in enumerate(headers) if name.startswith(alias.lower())), None)
        amount_column = column("发票金额", "价税合计", "含税金额", "totalamount")
        issuer_column = column("销售方名称", "销方名称", "销售方", "开票人", "收款方", "sellername")
        date_column = column("开票时间", "开票日期", "发票日期", "invoicedate")
        number_column = column("发票号码", "invoicenumber")
        code_column = column("发票代码", "invoicecode")
        if amount_column is not None and number_column is not None:
            def cell(row, index):
                value = row[index].strip() if index is not None and index < len(row) else ""
                return value[2:-1].replace('""', '"') if value.startswith('="') and value.endswith('"') else value
            entries = [{"issuer": cell(row, issuer_column)[:120], "amount": _clean_amount(cell(row, amount_column)),
                        "issue_time": _clean_issue_time(cell(row, date_column)),
                        "invoice_number": cell(row, number_column), "invoice_code": cell(row, code_column)} for row in table[1:]]
            # This metadata contract describes one invoice per file, not a ledger total.
            unique = {(entry["invoice_code"], entry["invoice_number"], entry["amount"]): entry for entry in entries}
            return next(iter(unique.values())) if len(unique) == 1 else {}
    compact = re.sub(r"[ \t\u3000]+", "", text)
    issuer = ""
    issuer_match = re.search(
        r"(?:销售方|开票方|开票人|商户|供应商)[：:,，]?([^,，;；\r\n]{2,100})",
        compact,
        flags=re.IGNORECASE,
    )
    if issuer_match:
        issuer = issuer_match.group(1).strip(" \t\"'")[:120]
    amount = ""
    amount_matches = re.findall(
        r"(?:价税合计|含税金额|发票金额|总金额|合计金额|金额)[：:,，]?¥?\s*([-−－]?[0-9,]+(?:\.\d{1,2})?)",
        compact,
        flags=re.IGNORECASE,
    )
    if amount_matches:
        amount = _clean_amount(amount_matches[-1])
    issue_time = ""
    date_match = re.search(
        r"(?:开票日期|开票时间|发票日期|日期)[：:,，]?([^,，;；\r\n]{6,30})",
        compact,
        flags=re.IGNORECASE,
    )
    if date_match:
        issue_time = _clean_issue_time(date_match.group(1))
    if not issue_time:
        issue_match = re.search(r"\b\d{4}(?:[-/.]\d{1,2}){2}\b|\b\d{8}\b", compact)
        if issue_match:
            issue_time = _clean_issue_time(issue_match.group(0))
    return {"issuer": issuer, "amount": amount, "issue_time": issue_time, "invoice_number": _invoice_number_from_text(text), "invoice_code": _invoice_code_from_text(text)}


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
    elif suffix == ".csv":
        meta = _parse_csv_invoice(path)
        method = "csv"
    elif suffix in {".jpg", ".jpeg", ".png"} and _is_invoice_attachment_name(path.name):
        from .court_directory import _vision_ocr_image
        meta = _parse_invoice_text(_vision_ocr_image(path.read_bytes()))
        method = "image-ocr"
    else:
        meta, method = {}, "unsupported"
    parsed = bool(meta.get("amount")) or (
        bool(meta.get("issuer")) and bool(meta.get("issue_time"))
    )
    return {"issuer": meta.get("issuer", ""), "amount": meta.get("amount", ""),
            "issue_time": meta.get("issue_time", ""), "parsed": parsed, "method": method,
            "invoice_number": meta.get("invoice_number") or invoice_number_from_values(path.name), "invoice_code": meta.get("invoice_code") or ""}


_INVOICE_FILENAME_MARKERS = ("发票", "invoice", "receipt", "收据", "dzfp", "fp_")


def _scan_cache_path(account: str, folder: Path) -> Path:
    data_folder = _BASE_DIR / "data"
    data_folder.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\u4e00-\u9fa5-]", "_", f"{folder.parent.name}_{folder.name}" if folder.name.startswith("invoice_") else folder.name)
    return data_folder / f"invoice_meta_{account}_{safe}.json"


_SCAN_CACHE_VERSION = 8

_INVOICE_LINK_CONTEXT_MARKERS = (
    "发票", "下载发票", "查看发票", "电子票", "数电", "开票", "invoice", "receipt", "票据",
)
_INVOICE_MAIL_TEXT_MARKERS = (
    "发票", "电子票", "数电", "开票", "发票号码", "发票金额", "电子凭证",
    "invoice", "receipt", "receipt no", "tax invoice", "税务发票",
)
_INVOICE_SENDER_MARKERS = (
    "invoice@", "invoice.", "gdfapiao.com", "nuonuo.com", "chinatax.gov.cn",
    "crestv.cn", "crestv.com", "vpiaotong.com", "hellotax.top", "fapiao",
)
_KNOWN_INVOICE_LINK_HOSTS = (
    "nnfp.jss.com.cn", "of1.cn", "inv.jss.com.cn", "storage.nuonuo.com",
    "fp.nuonuo.com", "nnfp.nuonuo.com", "gdfapiao.com", "crestv.com",
    "vpiaotong.com", "hellotax.top",
)
_INVOICE_ALT_PORT_HOST_SUFFIXES = ("chinatax.gov.cn",)
_MAX_LINK_RESPONSE_BYTES = 25 * 1024 * 1024
_INVOICE_SCAN_MAX_SECONDS = 30.0
_INVOICE_LINK_TIMEOUT = (3.0, 6.0)
_INVOICE_LINK_RESOLVER_VERSION = 2
_INVOICE_SCAN_VERSION = 3
_INVOICE_PARSER_VERSION = 6


def _normalize_invoice_extensions(extensions):
    allowed = [str(ext).lower() for ext in (extensions or []) if str(ext).lower() in INVOICE_EXTENSIONS]
    if not allowed:
        return list(INVOICE_EXTENSIONS)
    if ".jpg" in allowed or ".jpeg" in allowed:
        allowed.extend([".jpg", ".jpeg"])
    return list(dict.fromkeys(allowed))


def _invoice_number_from_text(text):
    match = re.search(r"(?:发\s*票\s*号\s*码|发\s*票\s*编\s*号|invoice\s*(?:number|no\.?))[\s:：#]*([0-9]{8,24})(?![0-9])", text, re.I)
    return match.group(1) if match else invoice_number_from_values(text)


def _invoice_code_from_text(text):
    match = re.search(r"发\s*票\s*代\s*码[\s:：]*([0-9]{10,12})(?![0-9])", text)
    return match.group(1) if match else ""


def invoice_number_from_values(*values: Any) -> str:
    for value in values:
        text = unquote(str(value or ""))
        match = re.search(r"(?<!\d)\d{20}(?!\d)", text)
        if match:
            return match.group(0)
    return ""


def _contains_invoice_marker(*values: Any) -> bool:
    haystack = " ".join(str(value or "") for value in values).lower()
    return any(marker.lower() in haystack for marker in _INVOICE_MAIL_TEXT_MARKERS)


def _is_invoice_attachment_name(filename: str) -> bool:
    lowered = str(filename or "").lower()
    if any(marker.lower() in lowered for marker in _INVOICE_FILENAME_MARKERS):
        return True
    # 一些税务平台把附件直接命名为 20 位发票号码或“号码_日期”，
    # 文件名没有“发票/dzfp”字样，也应进入实际文件解析阶段。
    return bool(re.search(r"(?<!\d)\d{16,24}(?!\d)", lowered))


def _is_invoice_mail_hint(subject: str = "", sender: str = "", filenames: Optional[List[str]] = None) -> bool:
    return (
        _contains_invoice_marker(subject)
        or any(_is_invoice_attachment_name(name) for name in (filenames or []))
        or any(marker in str(sender or "").lower() for marker in _INVOICE_SENDER_MARKERS)
    )


def _canonical_invoice_link(url: str) -> str:
    """Unwrap invoice QR generators instead of downloading the QR image."""
    value = _html.unescape(str(url or "")).strip()
    for _ in range(3):
        try:
            parsed = urlparse(value)
        except ValueError:
            return ""
        if parsed.hostname not in {"nnfp.jss.com.cn", "nnfp.nuonuo.com"} or not parsed.path.endswith("/getEwmImg.do"):
            break
        nested = (parse_qs(parsed.query).get("content") or [""])[0]
        if not nested.startswith(("https://", "http://")):
            return ""
        value = nested
    return value


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
    # 部分税务平台使用无扩展名的统一导出接口，发票格式和号码只放在查询参数中，
    # 例如广东数电发票的 exportDzfpwjEwm?Wjgs=PDF&Fphm=... 链接。
    query_keys = {str(key).lower() for key in parse_qs(parsed.query)}
    path = unquote(parsed.path).lower()
    if "exportdzfp" in path and "wjgs" in query_keys:
        return True
    if "wjgs" in query_keys and query_keys.intersection({"fphm", "fpdm", "kprq", "czsj"}):
        return True
    if host.endswith(".chinatax.gov.cn") and query_keys.intersection({"fphm", "fpdm"}):
        return True
    haystack = f"{context} {url}".lower()
    return any(marker in haystack for marker in _INVOICE_LINK_CONTEXT_MARKERS)


def _extract_invoice_links(message: email.message.Message) -> List[str]:
    """从纯文本和 HTML 正文提取疑似发票领取/下载链接。"""
    links: List[str] = []
    url_pattern = re.compile(r"https?://[^\s<>\"']+", flags=re.IGNORECASE)

    def add(url: str, context: str = "") -> None:
        value = _html.unescape(str(url or "")).strip().strip("<>\"'")
        value = value.rstrip("。；，、,;)")
        value = _canonical_invoice_link(value)
        if value and _is_invoice_link_candidate(value, context) and value not in links:
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
            # 除标准 <a href> 外，税务平台邮件还常把地址放在 data-url、
            # onclick 或无引号属性里；逐标签提取比只匹配完整闭合的 a 标签更稳。
            for tag_match in re.finditer(r"<[^>]+>", text, flags=re.IGNORECASE | re.DOTALL):
                tag = tag_match.group(0)
                context = tag
                for attr_match in re.finditer(
                    r"(?:href|data-(?:url|href|download)|onclick)\s*=\s*(?:([\"'])(.*?)\1|([^\s>]+))",
                    tag, flags=re.IGNORECASE | re.DOTALL,
                ):
                    raw_value = attr_match.group(2) or attr_match.group(3) or ""
                    for url_match in url_pattern.finditer(_html.unescape(raw_value)):
                        add(url_match.group(0), context)
            # 有些模板把跳转地址直接拼进 script 或 JSON，而不是属性。
            for match in url_pattern.finditer(text):
                # 只取地址之后的短上下文，避免相邻的退订链接继承前一个
                # “发票”锚点的语义。
                nearby = text[match.start():match.end() + 80]
                # 邮件 HTML 中的 logo、二维码和装饰图也会带公网 URL；只有
                # 明确带发票语义时才把 PNG/JPG 当作下载链接，避免把网页素材
                # 展开成“需人工查看”的发票行。
                if Path(urlparse(match.group(0)).path).suffix.lower() in {".png", ".jpg", ".jpeg"} \
                        and not _contains_invoice_marker(nearby):
                    continue
                add(match.group(0), nearby)
        else:
            for match in url_pattern.finditer(text):
                nearby = text[max(0, match.start() - 120):match.end() + 120]
                add(match.group(0), nearby)
    return links


def _validate_public_http_url(url: str) -> None:
    """阻止邮件链接访问本机、局域网或云元数据地址。"""
    try:
        parsed = urlparse(url)
        if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
            raise QQMailMCPError("发票链接不是有效的 HTTP 地址")
        port = parsed.port
        host = parsed.hostname.lower().rstrip(".")
        allowed_alt_port = (
            port == 8443
            and any(
                host == suffix or host.endswith("." + suffix)
                for suffix in _INVOICE_ALT_PORT_HOST_SUFFIXES
            )
        )
        if port not in (None, 80, 443) and not allowed_alt_port:
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
    timeout: Optional[Tuple[float, float]] = None,
    deadline: Optional[float] = None,
) -> Tuple[str, Dict[str, str], bytes]:
    """受限请求公网发票链接，逐跳校验重定向并限制响应大小。"""
    import requests

    current = str(url or "").strip()
    session = requests.Session()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,application/octet-stream,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    request_method = method.upper()
    request_data = data
    request_timeout = timeout or (8.0, 20.0)
    for _ in range(6):
        if deadline is not None and _time.monotonic() >= deadline:
            raise QQMailMCPError("发票链接下载超时，已跳过该链接")
        _validate_public_http_url(current)
        effective_timeout = request_timeout
        if deadline is not None:
            remaining = deadline - _time.monotonic()
            if remaining <= 0:
                raise QQMailMCPError("发票链接下载超时，已跳过该链接")
            effective_timeout = (
                min(request_timeout[0], max(0.2, remaining)),
                min(request_timeout[1], max(0.2, remaining)),
            )
        try:
            response = session.request(
                request_method, current, data=request_data, headers=headers,
                timeout=effective_timeout, allow_redirects=False, stream=True,
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
        try:
            for chunk in response.iter_content(64 * 1024):
                if deadline is not None and _time.monotonic() >= deadline:
                    response.close()
                    raise QQMailMCPError("发票链接下载超时，已跳过该链接")
                if not chunk:
                    continue
                size += len(chunk)
                if size > _MAX_LINK_RESPONSE_BYTES:
                    response.close()
                    raise QQMailMCPError("发票链接响应超过 25MB，已停止下载")
                chunks.append(chunk)
        except requests.RequestException as exc:
            response.close()
            raise QQMailMCPError("发票文件传输中断，可重新扫描自动重试") from exc
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
    probe = content.lstrip(b"\xef\xbb\xbf \t\r\n")
    if content.startswith(b"%PDF") or "application/pdf" in content_type:
        return ".pdf"
    if probe.startswith(b"<?xml") or "application/xml" in content_type or "text/xml" in content_type:
        return ".xml"
    # 统一导出接口通常返回 application/octet-stream，格式只能从 Wjgs 参数判断。
    # 明显的 HTML 错误页不能按参数伪装成可用发票文件。
    query = parse_qs(urlparse(url).query)
    format_hint = next(
        (values[0] for key, values in query.items() if key.lower() in {"wjgs", "filetype"} and values),
        "",
    ).upper()
    hinted_extension = {"PDF": ".pdf", "OFD": ".ofd", "XML": ".xml"}.get(format_hint, "")
    if hinted_extension and content and "text/html" not in content_type and not re.search(
        rb"<\s*html\b|<\s*body\b", probe[:2048], re.IGNORECASE
    ):
        return hinted_extension
    return ""


def _resolve_nuonuowang_link(
    final_url: str,
    allowed: List[str],
    timeout: Optional[Tuple[float, float]] = None,
    deadline: Optional[float] = None,
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
        timeout=timeout,
        deadline=deadline,
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


def _resolve_vpiaotong_link(final_url: str, allowed: List[str], timeout=None, deadline=None):
    """Use the public receipt page's read-only invoice API and electronic-file endpoint."""
    parsed = urlparse(final_url)
    if parsed.hostname != "scan.vpiaotong.com":
        return None
    route = parsed.fragment.split("?", 1)[0]
    match = re.fullmatch(r"/invoiceStatus/([^/]+)", route)
    if not match:
        return None
    extension = next((ext for ext in (".pdf", ".ofd", ".xml") if ext in allowed), "")
    if not extension:
        return None
    params = urlencode({"lsh": unquote(match.group(1))})
    origin = f"{parsed.scheme}://{parsed.netloc}"
    _, _, raw = _safe_http_request(
        f"{origin}/Aloe/tp/scan-invoice/getInvInfo.pt?{params}",
        referer=final_url, timeout=timeout, deadline=deadline,
    )
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        return None
    info = payload["data"]
    if str(payload.get("code")) != "200" or info.get("kpzt") != "MAKEINVOICESUCCESS":
        return None
    number = info.get("qdFpHm") or info.get("fpHm") or "下载"
    return {
        "download_url": f"{origin}/Aloe/tp/scan-invoice/getElectronicInvoice.pt?{params}&fileType={extension[1:].upper()}",
        "extension": extension,
        "filename": f"电子发票_{number}_{info.get('xsfMc') or ''}{extension}",
        "meta": {"issuer": str(info.get("xsfMc") or "")[:120],
                 "amount": _clean_amount(str(info.get("jshj") or "")),
                 "issue_time": _clean_issue_time(str(info.get("kprq") or ""))},
    }


def _linked_archive_invoices(url, headers, content, allowed):
    """Reuse bounded ZIP parsing and return every selected invoice in the archive."""
    if not content.startswith(b"PK\x03\x04") or not (
        Path(urlparse(url).path).suffix.lower() == ".zip" or "zip" in headers.get("content-type", "").lower()
    ):
        return None
    message = email.message.EmailMessage()
    message.set_content("")
    message.add_attachment(content, maintype="application", subtype="zip", filename="发票.zip")
    files = [{"filename": name, "content": data, "source_url": url, "meta_hint": {}}
             for name, data in _invoice_parts(message) if Path(name).suffix.lower() in allowed]
    if not files:
        return None
    return {**files[0], "additional_files": files[1:]}


def _invoice_urls_from_download_page(url: str, headers: Dict[str, str], content: bytes) -> List[str]:
    """从税务平台中转页提取下一跳下载地址。"""
    content_type = str(headers.get("content-type") or "").lower()
    probe = content.lstrip(b"\xef\xbb\xbf \t\r\n")
    if "html" not in content_type and not re.match(rb"<(?:!doctype|html|body|head)\b", probe[:256], re.I):
        return []
    text = content.decode("utf-8", errors="replace")
    urls: List[str] = []
    for match in re.finditer(r"https?://[^\s<>\"']+", _html.unescape(text), flags=re.IGNORECASE):
        candidate = match.group(0).rstrip("。；，、,;)")
        if candidate == url or candidate in urls:
            continue
        context = text[max(0, match.start() - 180):match.end() + 180]
        if _is_invoice_link_candidate(candidate, context):
            urls.append(candidate)
    return urls[:5]


def _download_invoice_link(
    url: str,
    allowed: List[str],
    timeout: Optional[Tuple[float, float]] = None,
    deadline: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """解析领取链接，普通页面下载首选格式，ZIP 保留全部选中格式成员。"""
    url = _canonical_invoice_link(url)
    if not url:
        return None
    final_url, headers, content = _safe_http_request(
        url, timeout=timeout, deadline=deadline,
    )
    archived = _linked_archive_invoices(final_url, headers, content, allowed)
    if archived:
        return archived
    extension = _linked_file_extension(final_url, headers, content)
    meta_hint: Dict[str, str] = {}
    filename = Path(urlparse(final_url).path).name
    if not extension:
        resolved = _resolve_nuonuowang_link(
            final_url, allowed, timeout=timeout, deadline=deadline,
        ) or _resolve_vpiaotong_link(final_url, allowed, timeout=timeout, deadline=deadline)
        if resolved:
            final_url, headers, content = _safe_http_request(
                resolved["download_url"], referer=final_url,
                timeout=timeout, deadline=deadline,
            )
            extension = _linked_file_extension(final_url, headers, content) or resolved["extension"]
            filename = resolved["filename"]
            meta_hint = resolved["meta"]
    if not extension:
        # 百旺/数电平台和部分第三方开票平台先返回一个 HTML 中转页，
        # 下一跳才是真正的 PDF/OFD/XML。只跟随同页显式公网链接，且继续沿用
        # 每跳 URL 校验和总超时，避免把普通邮件中的外链当成下载目标。
        for next_url in _invoice_urls_from_download_page(final_url, headers, content):
            try:
                next_final, next_headers, next_content = _safe_http_request(
                    next_url, referer=final_url, timeout=timeout, deadline=deadline,
                )
            except QQMailMCPError:
                continue
            next_extension = _linked_file_extension(next_final, next_headers, next_content)
            if next_extension:
                final_url, headers, content, extension = (
                    next_final, next_headers, next_content, next_extension,
                )
                filename = Path(urlparse(final_url).path).name
                break
    if not extension or extension not in allowed or not content:
        return None
    # A successful HTTP response may still be an expired-link/error page.
    probe = content.lstrip(b"\xef\xbb\xbf \t\r\n")
    if extension == ".pdf" and not probe.startswith(b"%PDF"):
        return None
    if extension == ".ofd" and not content.startswith(b"PK\x03\x04"):
        return None
    if extension == ".xml" and not (probe.startswith(b"<") or content.startswith(b"PK\x03\x04")):
        return None
    if extension in {".xml", ".ofd"} and re.search(rb"<\s*(?:html|body)\b", probe[:2048], re.I):
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
            for record in (cache.get("linked_uids") or {}).values():
                record["links"] = list(dict.fromkeys(
                    target for url in record.get("links", []) if (target := _canonical_invoice_link(url))
                ))
                for item in record.get("files", []):
                    item["source_url"] = _canonical_invoice_link(item.get("source_url") or "")
            return cache
    except (OSError, ValueError):
        pass
    return {"version": _SCAN_CACHE_VERSION, "by_uid": {}}


def _save_scan_cache(account: str, folder: Path, cache: Dict[str, Dict[str, Any]]) -> None:
    path = _scan_cache_path(account, folder)
    temporary = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with open(temporary, "w", encoding="utf-8") as file:
            json.dump(cache, file, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _meta_for_file(target: Path, scan_cache: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """解析发票元数据，同一文件（大小+修改时间未变）复用缓存结果。"""
    try:
        stat = target.stat()
        key = f"invoice-parser-v{_INVOICE_PARSER_VERSION}:{target.name}:{stat.st_size}:{stat.st_mtime_ns}"
    except OSError:
        key = f"invoice-parser-v{_INVOICE_PARSER_VERSION}:{target.name}"
    cached = scan_cache.get(key)
    meta = dict(cached) if cached else parse_invoice_metadata(target)
    sibling = target.with_suffix(".xml")
    if target.suffix.lower() in {".pdf", ".ofd"} and sibling.is_file():
        hint = _meta_for_file(sibling, scan_cache)
        if hint.get("invoice_number") and (not meta.get("invoice_number") or meta.get("invoice_number") == hint["invoice_number"]):
            for field in ("issuer", "amount", "issue_time", "invoice_number", "invoice_code"):
                if hint.get(field):
                    meta[field] = hint[field]
            meta["parsed"] = bool(meta.get("amount")) or bool(meta.get("issuer") and meta.get("issue_time"))
    scan_cache[key] = dict(meta)
    return meta


def _looks_like_invoice(filename: str, meta: Dict[str, Any]) -> bool:
    """Keep named/numeric invoices or files with recognizable invoice fields."""
    if meta.get("amount"):
        return True
    return _is_invoice_attachment_name(filename) or bool(meta.get("issuer") and meta.get("issue_time"))


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
    candidates += re.findall(r'"(?:name|filename)\*?"\s+"([^"]+)"', text, flags=re.IGNORECASE)
    # RFC2231 may split percent-encoded names across numbered parameters.
    segments = re.findall(r'"(?:name|filename)\*(\d+)\*?"\s+(?:"([^"\r\n]*)"|\{\d+\}\s*([^\s()]+))', text, re.I)
    joined = ""
    for index, quoted, literal in segments:
        if index == "0" and joined:
            candidates.append(joined)
            joined = ""
        joined += quoted or literal
    if joined:
        candidates.append(joined)
    names = []
    for value in candidates:
        charset = "utf-8"
        if "''" in value:
            prefix, value = value.split("''", 1)
            charset = prefix or charset
        try:
            decoded = _decode_text(unquote(value, encoding=charset))
        except LookupError:
            decoded = _decode_text(unquote(value))
        if decoded and decoded not in names:
            names.append(decoded)
    return names


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


def _bodystructure_records(data):
    """Reassemble imaplib's split literal tuples and trailing response fragments."""
    records, current = [], ""
    for item in data or []:
        if isinstance(item, tuple):
            head = item[0].decode("utf-8", errors="replace") if item[0] else ""
            literal = item[1].decode("utf-8", errors="replace") if item[1] else ""
            # Replace the literal size marker with a quoted value so all parameter
            # variants go through the same filename decoder.
            fragment = re.sub(r"\{\d+\}$", lambda _: '"' + literal.replace('"', '') + '"', head)
        elif isinstance(item, bytes):
            fragment = item.decode("utf-8", errors="replace")
        else:
            continue
        if re.match(r"^\d+\s+\(", fragment) and current:
            records.append(current)
            current = ""
        current += fragment
    if current:
        records.append(current)
    return records


def _mail_attachment_names_map(client: imaplib.IMAP4_SSL, uids: List[str], deadline=None, infer_unnamed=False) -> Dict[str, List[str]]:
    """批量获取多封邮件的 BODYSTRUCTURE 附件名（一次往返）。"""
    result: Dict[str, List[str]] = {}
    if not uids:
        return result
    # 大时间段可能包含上千封邮件；分块防止命令行和单次响应过大。
    for offset in range(0, len(uids), 20):
        if deadline is not None and _time.monotonic() >= deadline:
            break
        uid_list = ",".join(uids[offset:offset + 20])
        try:
            status, data = client.uid("fetch", uid_list, "(UID BODYSTRUCTURE)")
        except imaplib.IMAP4.error:
            continue
        if status != "OK" or not data:
            continue
        for text in _bodystructure_records(data):
            match = re.search(r"UID (\d+)", text)
            if not match:
                continue
            uid = match.group(1)
            names = _extract_attachment_names_text(text)
            for mime, extension in (("PDF", ".pdf"), ("OFD", ".ofd"), ("XML", ".xml")):
                if infer_unnamed and re.search(r'"(?:APPLICATION|TEXT)"\s+"' + mime + '"', text, re.I) and not any(Path(name).suffix.lower() == extension for name in names):
                    names.append("__unnamed_attachment" + extension)
            result[uid] = names
    return result


def _mail_subjects_map(client: imaplib.IMAP4_SSL, uids: List[str], summaries=None, deadline=None) -> Dict[str, str]:
    """批量获取邮件主题（轻量 HEADER 请求）。"""
    result: Dict[str, str] = {}
    if not uids:
        return result
    for offset in range(0, len(uids), 20):
        if deadline is not None and _time.monotonic() >= deadline:
            break
        uid_list = ",".join(uids[offset:offset + 20])
        try:
            status, data = client.uid("fetch", uid_list, "(UID BODY.PEEK[HEADER.FIELDS (SUBJECT DATE FROM)])")
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
            uid = match.group(1)
            result[uid] = _decode_text(message.get("Subject"))
            if summaries is not None:
                summary = summaries.setdefault(uid, {"uid": uid})
                summary.update(subject=result[uid], **{"from": _decode_text(message.get("From")), "date": _message_date(message)})
    return result


def _invoice_attachment_file(folder, uid, filename, payload, cache, invoice_hint, metadata_hint=None):
    """Parse new generic documents in staging; retain only invoice candidates."""
    import uuid
    target = folder / _safe_filename(uid, filename)
    if target.is_file():
        meta = _meta_for_file(target, cache)
        if metadata_hint and (not meta.get("invoice_number") or meta.get("invoice_number") == metadata_hint.get("invoice_number")):
            meta.update({key: value for key, value in metadata_hint.items() if value})
            meta["parsed"] = bool(meta.get("amount"))
            stat = target.stat()
            cache[f"invoice-parser-v{_INVOICE_PARSER_VERSION}:{target.name}:{stat.st_size}:{stat.st_mtime_ns}"] = dict(meta)
        return target, meta
    if not payload:
        return None, {}
    temporary = target.with_name(".pending_" + uuid.uuid4().hex[:12] + "_" + target.name)
    try:
        temporary.write_bytes(payload)
        meta = _meta_for_file(temporary, {})
        if metadata_hint and (not meta.get("invoice_number") or meta.get("invoice_number") == metadata_hint.get("invoice_number")):
            meta.update({key: value for key, value in metadata_hint.items() if value})
            meta["parsed"] = bool(meta.get("amount"))
        keep = _looks_like_invoice(filename, meta) or (invoice_hint and Path(filename).suffix.lower() in {".pdf", ".ofd", ".xml", ".csv"})
        if not keep:
            return None, meta
        os.replace(temporary, target)
        stat = target.stat()
        cache[f"invoice-parser-v{_INVOICE_PARSER_VERSION}:{target.name}:{stat.st_size}:{stat.st_mtime_ns}"] = dict(meta)
        return target, meta
    finally:
        temporary.unlink(missing_ok=True)


def _invoice_part_filename(part, index):
    filename = _decode_text(part.get_filename()).strip()
    if filename:
        return filename
    extension = {"application/pdf": ".pdf", "application/ofd": ".ofd", "application/xml": ".xml",
                 "text/xml": ".xml", "image/jpeg": ".jpeg", "image/png": ".png"}.get(part.get_content_type())
    if extension and (part.get_content_disposition() == "attachment" or extension in {".pdf", ".ofd", ".xml"}):
        return f"附件_{index}{extension}"
    return ""


def _invoice_parts(message: email.message.Message, errors=None):
    """Read named MIME files and bounded ZIP entries without extracting archive paths."""
    import io
    import zipfile
    for index, part in enumerate(message.walk()):
        if part.get_content_maintype() == "multipart":
            continue
        filename = _invoice_part_filename(part, index)
        if not filename:
            continue
        payload = part.get_payload(decode=True) or b""
        if Path(filename).suffix.lower() != ".zip":
            yield filename, payload
            continue
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                entries = _invoice_archive_members(archive)
                for item in entries:
                    if item.is_dir() or Path(item.filename).suffix.lower() not in INVOICE_EXTENSIONS:
                        continue
                    key = hashlib.sha256((filename + ":" + item.filename).encode()).hexdigest()[:12]
                    name = Path(item.filename).name
                    yield f"{key}_{name}", archive.read(item)
        except (zipfile.BadZipFile, RuntimeError, OSError, QQMailMCPError) as exc:
            if errors is None:
                raise QQMailMCPError("发票压缩包无法读取") from exc
            errors.append({"filename": filename, "error": str(exc)})


def _invoice_mailboxes(client: imaplib.IMAP4_SSL) -> List[str]:
    """Include custom folders, preserving the server's modified UTF-7 names."""
    status, data = client.list()
    if status != "OK":
        raise QQMailMCPError("无法读取邮箱文件夹列表，扫描范围不完整")
    mailboxes = [DEFAULT_FOLDER]
    for raw in data or []:
        if isinstance(raw, tuple) and len(raw) == 2:
            head, literal = raw
            raw = re.sub(rb"\{\d+\}$", lambda _: b'"' + literal.replace(b'"', b'\\"') + b'"', head)
        if not isinstance(raw, bytes):
            continue
        match = re.match(rb'\((.*?)\)\s+(?:"[^"\r\n]*"|NIL)\s+(.+)$', raw)
        if not match or b"\\noselect" in match.group(1).lower():
            continue
        mailbox = match.group(2).decode("ascii")
        if not mailbox.startswith('"') and " " in mailbox:
            mailbox = '"' + mailbox.replace('"', '\\"') + '"'
        if mailbox.strip('"').upper() != DEFAULT_FOLDER and mailbox not in mailboxes:
            mailboxes.append(mailbox)
    return mailboxes


def _complete_invoice_metadata(rows):
    """Use the exact same invoice's structured version, never a mail-wide guess."""
    groups = {}
    by_file = {}
    for row in rows:
        if "行程单" in str(row.get("filename") or ""):
            row["document_role"] = "supporting"
            row["amount"] = ""
            continue
        number = row.get("invoice_number") or invoice_number_from_values(row.get("filename"))
        if number:
            row["invoice_number"] = number
        key = (row.get("mailbox", DEFAULT_FOLDER), str(row.get("uid")), Path(row.get("filename", "")).stem)
        by_file.setdefault(key, []).append(row)
    # Outlined OFDs have no extractable characters, but their matching PDF/XML
    # in the very same message and with the exact same basename identifies them.
    for siblings in by_file.values():
        numbers = {r.get("invoice_number") for r in siblings if r.get("invoice_number")}
        if len(numbers) == 1:
            for row in siblings:
                row["invoice_number"] = next(iter(numbers))
    for row in rows:
        number = row.get("invoice_number")
        if not number or row.get("document_role") == "supporting":
            continue
        identity = (number, row.get("invoice_code") or row.get("issuer") or "") if len(number) < 16 else (number, "")
        groups.setdefault(identity, []).append(row)
    for siblings in groups.values():
        for field in ("amount", "issuer", "issue_time", "invoice_code"):
            candidates = [r for r in siblings if r.get(field)]
            structured = [r for r in candidates if r.get("ext") == ".xml"]
            preferred = structured or candidates
            values = {str(r[field]) for r in preferred}
            if len(values) != 1:
                continue
            value = next(iter(values))
            for row in siblings:
                if not row.get(field) or structured:
                    if row.get(field) != value:
                        row.setdefault("metadata_sources", {})[field] = preferred[0].get("filename", "")
                    row[field] = value
        for row in siblings:
            row["parsed"] = bool(row.get("amount")) or bool(row.get("issuer") and row.get("issue_time"))
    return rows


def _restore_local_invoices(account, rows, allowed, start_date, end_date, keyword, *, deadline=None, state=None):
    """Recover downloaded inbox invoices hidden by the server's IMAP time window.

    Only cached mail receipt dates define the range; invoice dates and file mtimes
    must never be substituted. Files and original mail remain untouched.
    """
    summaries = dict(_load_summary_cache(account).get("mails") or {})
    summaries.update(_load_summary_cache(account, folder="invoice_inbox").get("mails") or {})
    root = Path(_account_config(account)["attachment_root"])
    known = {(r.get("invoice_number"), r.get("ext")) for r in rows if r.get("invoice_number")}
    paths = {r["path"] for r in rows}
    local_contents = set()
    for folder in sorted(root.glob("????-??"), reverse=True):
        cache = None
        changed = False
        for target in sorted(folder.glob("*")):
            if deadline is not None and _time.monotonic() >= deadline:
                if state is not None:
                    state["pending"] = True
                break
            if not target.is_file() or target.suffix.lower() not in allowed or str(target) in paths:
                continue
            uid, separator, filename = target.name.partition("_")
            summary = summaries.get(uid) if separator and uid.isdigit() else None
            if not summary:
                continue
            date = str(summary.get("date") or "")[:10]
            if not (start_date <= date <= end_date) or (keyword and keyword not in str(summary.get("subject") or "").lower()):
                continue
            if not _is_invoice_attachment_name(filename):
                continue
            content_key = hashlib.sha256(target.read_bytes()).hexdigest()
            if content_key in local_contents:
                continue
            local_contents.add(content_key)
            if cache is None:
                cache = _load_scan_cache(account, folder)
            meta = _meta_for_file(target, cache)
            changed = True
            identity = (meta.get("invoice_number"), target.suffix.lower())
            if identity[0] and identity in known:
                continue
            rows.append({"uid": uid, "mailbox": DEFAULT_FOLDER, "filename": filename,
                         "path": str(target), "mail_date": summary.get("date", ""),
                         "subject": summary.get("subject", ""), "from": summary.get("from", ""),
                         "ext": target.suffix.lower(), "size": target.stat().st_size,
                         "source_type": "local", **meta})
            paths.add(str(target))
            if identity[0]:
                known.add(identity)
        if changed:
            _save_scan_cache(account, folder, cache)
        if state and state.get("pending"):
            break
    return rows


def scan_invoices(account: str, since_days: int = 30, extensions=None, keyword: str = "",
                  limit: int = 2000, start_date: str = "", end_date: str = ""):
    _account_config(account)
    lock = _INVOICE_SCAN_LOCKS[account]
    if not lock.acquire(timeout=5):
        raise QQMailMCPError("该邮箱仍有扫描正在保存结果，请稍后重试")
    try:
        return _scan_invoices(account, since_days, extensions, keyword, limit, start_date, end_date)
    finally:
        lock.release()


def _scan_invoices(
    account: str, since_days: int = 30, extensions: Optional[List[str]] = None,
    keyword: str = "", limit: int = 2000, start_date: str = "", end_date: str = "",
) -> Dict[str, Any]:
    client = _connect(account)
    deadline = _time.monotonic() + _INVOICE_SCAN_MAX_SECONDS
    results, warnings = [], []
    client_ref = [client]
    scope_folder = _collect_month_dir(account) / "invoice_scope"
    scope_cache = _load_scan_cache(account, scope_folder)
    selection = [since_days, start_date, end_date, sorted(_normalize_invoice_extensions(extensions)), keyword.strip().lower(), limit, _INVOICE_LINK_RESOLVER_VERSION, _INVOICE_SCAN_VERSION, _INVOICE_PARSER_VERSION]
    continuing = scope_cache.get("selection") == selection and bool(scope_cache.get("remaining_mailboxes"))
    prior_results = (scope_cache.get("mailbox_results") or {}) if continuing else {}
    try:
        try:
            mailboxes = _invoice_mailboxes(client)
        except (QQMailMCPError, imaplib.IMAP4.error, OSError) as exc:
            mailboxes = [DEFAULT_FOLDER]
            warnings.append(str(exc))
        scan_order = [mailbox for mailbox in mailboxes if not continuing or mailbox in scope_cache["remaining_mailboxes"]]
        current_results = dict(prior_results)
        for mailbox in scan_order:
            if _time.monotonic() >= deadline:
                warnings.append("扫描达到时间上限，部分文件夹未扫描；请再次扫描继续")
                break
            try:
                result = _scan_invoice_mailbox(
                    account, since_days, extensions, keyword, limit, start_date, end_date,
                    _client=client_ref[0], _mailbox=mailbox, _deadline=deadline, _client_ref=client_ref,
                )
            except (QQMailMCPError, imaplib.IMAP4.error, OSError) as exc:
                warnings.append(f"文件夹 {mailbox} 扫描失败：{exc}")
                continue
            current_results[mailbox] = result
        remaining_mailboxes = [mailbox for mailbox in mailboxes if mailbox not in current_results or current_results[mailbox].get("timed_out")]
        scope_cache.update(selection=selection, remaining_mailboxes=remaining_mailboxes, mailbox_results=current_results)
        _save_scan_cache(account, scope_folder, scope_cache)
        results = [current_results[mailbox] for mailbox in mailboxes if mailbox in current_results]
        for result in results:
            warnings.extend(result.get("warnings") or [])
    finally:
        _safe_logout(client_ref[0])
    rows = [{**row, "mailbox": result.get("mailbox") or DEFAULT_FOLDER} for result in results for row in result["invoices"]]
    for row in rows:
        row["invoice_number"] = row.get("invoice_number") or invoice_number_from_values(row.get("filename"), row.get("subject"), row.get("source_url"))
    date_result = results[0] if results else {}
    local_state = {}
    if date_result.get("start_date") and date_result.get("end_date"):
        rows = _restore_local_invoices(account, rows, _normalize_invoice_extensions(extensions),
                                       date_result["start_date"], date_result["end_date"], keyword.strip().lower(),
                                       deadline=_time.monotonic() + 15, state=local_state)
    if local_state.get("pending"):
        warnings.append("本机历史发票正在分批识别，将继续扫描")
    rows = _complete_invoice_metadata(rows)
    rows.sort(key=lambda row: row.get("mail_date") or "", reverse=True)
    return {
        **(results[0] if results else {}),
        "folder": str(_collect_month_dir(account)), "invoices": rows, "total": len(rows),
        "parsed_count": sum(bool(row.get("parsed")) for row in rows),
        "scanned_mails": sum(result["scanned_mails"] for result in results),
        "scanned_folders": len(results), "total_folders": len(mailboxes),
        "timed_out": bool(local_state.get("pending")) or any(result.get("timed_out") for result in results) or len(results) < len(mailboxes),
        "warnings": list(dict.fromkeys(warnings)),
    }


def _scan_invoice_mailbox(
    account: str,
    since_days: int = 30,
    extensions: Optional[List[str]] = None,
    keyword: str = "",
    limit: int = 2000,
    start_date: str = "",
    end_date: str = "",
    *, _client=None, _mailbox: str = DEFAULT_FOLDER, _deadline=None, _client_ref=None,
) -> Dict[str, Any]:
    """扫描邮件附件中的发票文件：下载、解析开票人/金额/开票时间，形成列表。"""
    allowed = _normalize_invoice_extensions(extensions)
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
    scan_deadline = _deadline if _deadline is not None else _time.monotonic() + _INVOICE_SCAN_MAX_SECONDS
    link_failures = 0
    scan_timed_out = False
    attempted_link_urls = set()
    client = _client or _connect(account)
    mail_failures = 0
    archive_failures = 0
    visited_uids = []
    failed_uids = set()

    def fetch_invoice_message(uid):
        nonlocal client
        options = {"_mailbox": _mailbox} if _mailbox != DEFAULT_FOLDER else {}
        try:
            return _fetch_message(client, uid, account=account, _peek=True, **options)
        except (OSError, imaplib.IMAP4.abort) as exc:
            # A socket timeout poisons imaplib's buffered reader. Reconnect once,
            # preserving already parsed rows and the remaining-message cursor.
            _safe_logout(client)
            if _time.monotonic() >= scan_deadline:
                raise QQMailMCPError("邮件读取超时，请再次扫描继续") from exc
            client = _connect(account)
            if _client_ref is not None:
                _client_ref[0] = client
            try:
                return _fetch_message(client, uid, account=account, _peek=True, **options)
            except (OSError, imaplib.IMAP4.abort) as retry_exc:
                raise QQMailMCPError("邮件重试读取失败，请再次扫描继续") from retry_exc

    try:
        # 日期条件直接交给 IMAP，避免先取最新 N 封再逐封下载判断，且不会漏掉
        # 时间段内较早、但不在“最新 100 封”里的发票邮件。
        uids = _uid_set_between(client, range_start, range_end, limit=0, **({"mailbox": _mailbox} if _mailbox != DEFAULT_FOLDER else {}))
        if not uids:
            return {"invoices": [], "total": 0, "folder": "", "scanned_mails": 0,
                    "timed_out": False, "warnings": [],
                    "start_date": range_start.isoformat(), "end_date": range_end.isoformat()}
        folder = _collect_month_dir(account)
        cache_scope = "invoice_inbox"
        if _mailbox != DEFAULT_FOLDER:
            cache_scope = "invoice_" + hashlib.sha256(_mailbox.encode()).hexdigest()[:16]
            folder = folder / cache_scope
            folder.mkdir(parents=True, exist_ok=True)
        cache = _load_summary_cache(account, **({"folder": cache_scope} if cache_scope != "inbox" else {}))
        scan_cache = _load_scan_cache(account, folder)
        validity_response = client.response("UIDVALIDITY")
        validity = ""
        if isinstance(validity_response, tuple) and len(validity_response) == 2:
            for item in validity_response[1] or []:
                if isinstance(item, bytes) and item.isdigit():
                    validity = item.decode("ascii")
                    break
        if validity and scan_cache.get("uidvalidity") and scan_cache["uidvalidity"] != validity:
            scan_cache = {"version": _SCAN_CACHE_VERSION, "by_uid": {}, "storage_epoch": validity}
            cache = {"mails": {}}
        if validity:
            scan_cache["uidvalidity"] = validity
        cache_folder = folder
        if scan_cache.get("storage_epoch"):
            folder = folder / ("uidvalidity_" + str(scan_cache["storage_epoch"]))
            folder.mkdir(parents=True, exist_ok=True)
        checked_uids = scan_cache.get("by_uid") or {}
        linked_uids = scan_cache.get("linked_uids") or {}
        signature = [range_start.isoformat(), range_end.isoformat(), sorted(allowed), normalized_keyword, _INVOICE_SCAN_VERSION, _INVOICE_PARSER_VERSION]
        resume = scan_cache.get("signature") == signature
        remaining_uids = (scan_cache.get("remaining_uids") or []) if resume else []
        all_uids = list(uids)
        completed_uids = set(scan_cache.get("completed_uids") or []) if resume and remaining_uids else set()
        remaining_set = set(remaining_uids)
        pending_uids = [uid for uid in uids if uid not in completed_uids]
        if remaining_uids:
            pending_uids = [uid for uid in pending_uids if uid in remaining_set] + [uid for uid in pending_uids if uid not in remaining_set]
        uids = pending_uids[:max(1, min(int(limit or 2000), 5000))]
        rows: List[Dict[str, Any]] = [
            row for row in (scan_cache.get("rows") or [])
            if resume and remaining_uids and str(row.get("uid")) in all_uids and Path(str(row.get("path") or "")).is_file()
        ]
        # 只对未检查过的邮件批量获取 BODYSTRUCTURE 附件名（其余复用缓存）。
        new_uids = [uid for uid in uids[:20] if uid not in checked_uids]
        if new_uids:
            # Reserve most of the batch for parsing messages. Preflighting the
            # entire date range can consume every deadline before visiting a UID.
            fresh_map = _mail_attachment_names_map(client, new_uids[:20], deadline=scan_deadline, infer_unnamed=True)
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
        missing_subject_uids = [
            uid for uid in uids
            if not str((cache["mails"].get(uid) or {}).get("subject") or "") or not (cache["mails"].get(uid) or {}).get("from")
        ]
        # 不能只给“有扩展名附件”的邮件取主题：正文链接型发票在
        # BODYSTRUCTURE 中没有附件名，正是最容易被漏掉的一类。已有摘要直接复用，
        # 只有缺少主题的邮件才补一次轻量 HEADER 请求，避免每次扫描重复往返。
        subject_uids = [uid for uid in uids[:20] if uid in missing_subject_uids]
        subject_map = _mail_subjects_map(client, subject_uids, summaries=cache["mails"], deadline=scan_deadline) if subject_uids else {}
        for uid, subject in subject_map.items():
            cached_summary = cache["mails"].setdefault(uid, {"uid": uid})
            cached_summary["subject"] = subject or "（无主题）"
        with _DOWNLOAD_LOCK:
            for position, uid in enumerate(uids):
                if _time.monotonic() >= scan_deadline:
                    scan_timed_out = True
                    break
                if uid not in checked_uids and uid not in fresh_map:
                    chunk = [item for item in uids[position:position + 20] if item not in checked_uids and item not in fresh_map]
                    discovered = _mail_attachment_names_map(client, chunk, deadline=scan_deadline, infer_unnamed=True)
                    fresh_map.update(discovered)
                    attachment_map.update(discovered)
                if uid not in subject_map and not (cache["mails"].get(uid) or {}).get("subject"):
                    chunk = [item for item in uids[position:position + 20] if not (cache["mails"].get(item) or {}).get("subject")]
                    subject_map.update(_mail_subjects_map(client, chunk, summaries=cache["mails"], deadline=scan_deadline))
                if _time.monotonic() >= scan_deadline:
                    scan_timed_out = True
                    break
                visited_uids.append(uid)
                # 复用摘要缓存：该邮件附件已全部落盘时跳过完整邮件下载。
                cached = cache["mails"].get(uid)
                known_subject = str((cached or {}).get("subject") or subject_map.get(uid) or "")
                if normalized_keyword and known_subject and normalized_keyword not in known_subject.lower():
                    continue
                full_message: Optional[email.message.Message] = None
                if uid not in subject_map and not (cached or {}).get("subject"):
                    try:
                        full_message, _ = fetch_invoice_message(uid)
                    except QQMailMCPError:
                        mail_failures += 1
                        failed_uids.add(uid)
                        continue
                    cache["mails"][uid] = _summary_from_message(uid, full_message, read=bool((cached or {}).get("read", True)))
                    cached = cache["mails"][uid]
                    known_subject = str(cached.get("subject") or "")
                    if normalized_keyword and normalized_keyword not in known_subject.lower():
                        continue
                known_attachment_names = list(
                    (cached or {}).get("attachments") or attachment_map.get(uid) or []
                )
                is_invoice_subject = _is_invoice_mail_hint(
                    known_subject,
                    str((cached or {}).get("from") or ""),
                    known_attachment_names,
                )

                # 无附件发票：从正文领取/下载链接解析真实 PDF/OFD/XML。
                link_record = linked_uids.get(uid)
                stored_link_files = (link_record or {}).get("files") or []
                matching_stored_files = [
                    item for item in stored_link_files
                    if Path(str(item.get("filename") or "")).suffix.lower() in allowed
                ]
                recently_checked_empty = False
                if (
                    link_record
                    and not stored_link_files
                    and not (link_record.get("links") or [])
                    and link_record.get("checked_at")
                ):
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
                if restored_link_count:
                    attempted_link_urls.update(
                        str(item.get("source_url")) for item in matching_stored_files if item.get("source_url") and (folder / _safe_filename(uid, str(item.get("filename") or ""))).is_file()
                    )

                should_resolve_links = (
                    is_invoice_subject
                    and (
                        not link_record
                        or not stored_link_files and not (link_record.get("links") or [])
                        or restored_link_count < len(matching_stored_files)
                        or any(url not in {item.get("source_url") for item in matching_stored_files} for url in link_record.get("links", []))
                    )
                    and not recently_checked_empty
                )
                if should_resolve_links:
                    links = list((link_record or {}).get("links") or [])
                    if not links:
                        try:
                            if full_message is None:
                                full_message, _ = fetch_invoice_message(uid)
                        except QQMailMCPError:
                            mail_failures += 1
                            failed_uids.add(uid)
                            full_message = None
                        if full_message is not None:
                            links = _extract_invoice_links(full_message)
                            cache["mails"][uid] = _summary_from_message(
                                uid, full_message, read=bool((cached or {}).get("read", True))
                            )
                            cached = cache["mails"][uid]
                    downloaded_files = list(stored_link_files)
                    links_to_download = [
                        source_url for source_url in links
                        if source_url not in attempted_link_urls
                    ]
                    for source_url in links_to_download:
                        attempted_link_urls.add(source_url)
                        if _time.monotonic() >= scan_deadline:
                            scan_timed_out = True
                            break
                        remaining = max(0.2, scan_deadline - _time.monotonic())
                        try:
                            downloaded = _download_invoice_link(
                                source_url,
                                allowed,
                                timeout=(
                                    min(_INVOICE_LINK_TIMEOUT[0], remaining),
                                    min(_INVOICE_LINK_TIMEOUT[1], remaining),
                                ),
                                deadline=scan_deadline,
                            )
                        except QQMailMCPError:
                            link_failures += 1
                            failed_uids.add(uid)
                            attempted_link_urls.discard(source_url)
                            continue
                        if not downloaded:
                            link_failures += 1
                            failed_uids.add(uid)
                            attempted_link_urls.discard(source_url)
                            continue
                        for downloaded_file in [downloaded] + list(downloaded.get("additional_files") or []):
                            filename = str(downloaded_file["filename"])
                            # One message can contain several downloads with identical generic names.
                            filename = f"{hashlib.sha256(source_url.encode()).hexdigest()[:12]}_{filename}"
                            target = folder / _safe_filename(uid, filename)
                            if not target.exists():
                                target.write_bytes(downloaded_file["content"])
                            meta = _meta_for_file(target, scan_cache)
                            hint = downloaded_file.get("meta_hint") or {}
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
                        "checked_at": _datetime.datetime.now().isoformat(timespec="seconds") if full_message is not None or links else "",
                        "links": links,
                        "files": downloaded_files,
                    }
                if cached and cached.get("attachments"):
                    disk_attachments = []
                    all_present = not any(Path(name).suffix.lower() == ".zip" for name in cached["attachments"])
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
                            if not (_looks_like_invoice(filename, meta) or (is_invoice_subject and Path(filename).suffix.lower() in {".pdf", ".ofd", ".xml", ".csv"})):
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
                # A missing server response is unknown, not proof of no attachments.
                if uid not in checked_uids and uid not in fresh_map and full_message is None:
                    try:
                        full_message, _ = fetch_invoice_message(uid)
                    except QQMailMCPError:
                        mail_failures += 1
                        failed_uids.add(uid)
                        continue
                # BODYSTRUCTURE 预筛：没有目标扩展名附件的邮件不下载完整内容。
                attachment_names = attachment_map.get(uid) or []
                if not attachment_names and full_message is not None:
                    attachment_names = [name for index, part in enumerate(full_message.walk()) if (name := _invoice_part_filename(part, index))]
                    attachment_map[uid] = list(attachment_names)
                wanted_names = [
                    name for name in attachment_names
                    if Path(name).suffix.lower() in allowed or Path(name).suffix.lower() == ".zip"
                ]
                if not wanted_names:
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
                        if not (_looks_like_invoice(filename, meta) or (is_invoice_subject and Path(filename).suffix.lower() in {".pdf", ".ofd", ".xml", ".csv"})):
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
                        message, _ = fetch_invoice_message(uid)
                    except QQMailMCPError:
                        mail_failures += 1
                        failed_uids.add(uid)
                        continue
                mail_date = _message_date(message)
                try:
                    part_errors = []
                    invoice_parts = list(_invoice_parts(message, errors=part_errors))
                    archive_failures += len(part_errors)
                    if part_errors:
                        failed_uids.add(uid)
                except QQMailMCPError:
                    mail_failures += 1
                    failed_uids.add(uid)
                    continue
                cache["mails"][uid] = _summary_from_message(
                    uid, message, read=bool((cached or {}).get("read", True))
                )
                # BODYSTRUCTURE 的文件名编码不完整时，以完整 MIME 解析结果
                # 回写缓存；下次扫描不再沿用旧的空/乱码附件名。
                checked_uids[uid] = [item[0] for item in invoice_parts] + [item["filename"] for item in part_errors]
                cache["mails"][uid]["attachments"] = list(checked_uids[uid])
                attachment_map[uid] = list(checked_uids[uid])
                # XML is already inside the fetched MIME payload even when the
                # user selected only OFD/PDF. Read its fields without adding an
                # unselected format to the result or requiring another request.
                import xml.etree.ElementTree as ET
                sibling_metadata = {}
                for part_name, part_payload in invoice_parts:
                    if Path(part_name).suffix.lower() == ".xml":
                        try:
                            hint = _parse_xml_invoice_root(ET.fromstring(part_payload))
                        except (ET.ParseError, ValueError):
                            continue
                        if hint.get("invoice_number"):
                            sibling_metadata[Path(part_name).stem] = hint
                for filename, payload in invoice_parts:
                    suffix = Path(filename).suffix.lower()
                    if suffix not in allowed:
                        continue
                    target, meta = _invoice_attachment_file(folder, uid, filename, payload, scan_cache, is_invoice_subject,
                                                            sibling_metadata.get(Path(filename).stem))
                    if target is None:
                        continue
                    if not (_looks_like_invoice(filename, meta) or (is_invoice_subject and Path(filename).suffix.lower() in {".pdf", ".ofd", ".xml", ".csv"})):
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
        if _client is None:
            _safe_logout(client)
    # 记录已检查过的 uid 及其附件名，避免下次重复 BODYSTRUCTURE。
    for uid, names in fresh_map.items():
        checked_uids.setdefault(uid, names)
    # Failed BODYSTRUCTURE requests must remain retryable, never cache them as empty.
    scan_cache["by_uid"] = checked_uids
    scan_cache["linked_uids"] = linked_uids
    scan_cache["signature"] = signature
    visited_set = set(visited_uids[:-1] if scan_timed_out else visited_uids)
    completed_uids.update(visited_set - failed_uids)
    scan_cache["completed_uids"] = list(completed_uids)
    scan_cache["remaining_uids"] = [uid for uid in all_uids if uid not in completed_uids]
    scan_timed_out = scan_timed_out or bool(scan_cache["remaining_uids"])
    scan_cache["rows"] = list({row["path"]: row for row in rows}.values())
    _save_scan_cache(account, cache_folder, scan_cache)
    _save_summary_cache(account, cache, **({"folder": cache_scope} if cache_scope != "inbox" else {}))
    # 同一文件可能同时被转发正文和附件路径发现，最终列表按落盘路径去重。
    unique_rows: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        unique_rows[str(row.get("path") or f"{row.get('uid')}:{row.get('filename')}")] = row
    rows = list(unique_rows.values())
    rows.sort(key=lambda item: item.get("mail_date") or "", reverse=True)
    warnings: List[str] = []
    if archive_failures:
        warnings.append(f"{archive_failures} 个压缩附件读取失败，其他发票已保留")
    if mail_failures:
        warnings.append(f"{mail_failures} 封邮件读取失败，请重试")
    if link_failures:
        warnings.append(f"{link_failures} 个发票下载链接失败或超时，已跳过")
    if scan_timed_out:
        warnings.append("扫描达到时间上限，剩余邮件将在下次扫描时继续")
    return {
        "invoices": rows,
        "total": len(rows),
        "folder": str(folder),
        "parsed_count": sum(1 for row in rows if row.get("parsed")),
        "scanned_mails": len(completed_uids.intersection(all_uids)),
        "mailbox": _mailbox,
        "timed_out": scan_timed_out,
        "warnings": warnings,
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
