"""人民法院在线服务的本地 APEX 集成。

协议实现与浏览器扩展相互独立：浏览器只用于取得/续期法院会话，所有
业务数据都由本机后端保存并通过本地 API 交给案件管理页。

安全边界（必须持续遵守）：
1. 只读取当前已登录账号自身权限范围内、官网页面正常展示的数据。
2. 只采用被动方式发现接口：监听用户在浏览器中的正常页面操作产生的
    XHR，不主动构造请求、不枚举、不爆破、不模拟未发生的用户行为。
3. 不绕过或弱化任何认证/验证码机制，不使用登录接口之外的认证途径。
4. 默认只读取官网数据。经律师在“自动化立案”页面逐项确认的民商事
   一审草稿，可使用当前律师账号的 Token API 写入该账号自己的官网草稿；
   不调用最终提交、验证码、身份核验或电子签名接口。
5. 请求频率沿用用户配置的同步间隔，不做激进抓取；对监听发现的路由
   先人工审查确认属于本账号可读范围后再封装，禁止自动批量调用。
6. 记录落库时过滤敏感参数（证件号、手机号等），只保留业务路由形态。
"""
from __future__ import annotations

import asyncio
import base64
import datetime as dt
import hashlib
import io
import json
import mimetypes
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Any, Callable, Dict

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response

from .case_automation import COURT_DOCUMENT_SUBDIR, get_folder_binding, store_case_file

COURT_ORIGIN = "https://zxfw.court.gov.cn"
# 官网 API 使用 /yzw 作为网关前缀，后续服务名同样以 /yzw- 开头。
COURT_API = f"{COURT_ORIGIN}/yzw"
BAIDU_TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
BAIDU_OCR_URL = "https://aip.baidubce.com/rest/2.0/ocr/v1/accurate_basic"
KEYCHAIN_SERVICE = "APEX · 法院在线服务"
KEYCHAIN_ACCOUNT = "court-online-service-v1"
MODULE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("LEGAL_KB_DATA_DIR", str(MODULE_DIR))) / "court_online_service"
PROFILE_DIR = DATA_DIR / "browser-profile"
PROFILE_ACCOUNTS_DIR = DATA_DIR / "browser-profiles"
DOWNLOAD_DIR = DATA_DIR / "法院文书"
RETENTION_DAYS = 90
MAX_BYTES = 50 * 1024 * 1024
ALLOWED_KINDS = {"todo", "message", "delivery"}
# The court-service browser is a dedicated profile. It needs cookies and
# localStorage for the court session, but it does not need Chrome's background
# component updater or an unbounded HTTP disk cache. Keep these limits scoped
# to this profile so the user's normal Chrome installation is unaffected.
COURT_BROWSER_DISK_CACHE_BYTES = 32 * 1024 * 1024
# The native shell is the owner of the login flow. Keeping this explicit lets
# the backend restore APEX even when the controlled Chrome window was already
# visible before the user clicked the login button.
APEX_APP_BUNDLE_ID = "com.liuzongjin.legalkb.native"


class CourtOnlineError(HTTPException):
    def __init__(self, detail: str, status_code: int = 502):
        super().__init__(status_code=status_code, detail=detail)


async def _arm_login_feedback(page: Any) -> None:
    """在提交前监听新出现的验证码错误，保留短暂提示且忽略上次残留提示。"""
    await page.evaluate(r"""() => {
        window.__courtLoginFeedback?.observer.disconnect();
        const captchaError = /验证码.{0,20}(错误|不正确|有误|失效|过期|不匹配|失败)|请.{0,8}(重新|正确)输入验证码/;
        // 官网新版把“验证码输入错误”直接渲染成登录表单中的行内文本，
        // 不一定使用 toast/alert 等提示节点；扫描可见的短文本可兼容两种页面。
        const visibleErrors = () => Array.from(document.body?.querySelectorAll('*') || [])
            .filter(el => {
                const style = getComputedStyle(el);
                return el.getClientRects().length && style.display !== 'none'
                    && style.visibility !== 'hidden' && style.opacity !== '0';
            })
            .filter(el => {
                const text = String(el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
                return text && text.length <= 180 && captchaError.test(text);
            });
        let previous = new Set(visibleErrors());
        const state = {error: false};
        state.scan = () => {
            const current = new Set(visibleErrors());
            if ([...current].some(el => !previous.has(el))) state.error = true;
            previous = current;
        };
        state.observer = new MutationObserver(state.scan);
        state.observer.observe(document.body, {subtree: true, childList: true,
            characterData: true, attributes: true});
        window.__courtLoginFeedback = state;
    }""")


async def _wait_login_result(page: Any) -> str:
    """每 100ms 检查登录状态；验证码报错立即返回，不再等满 8 秒。"""
    try:
        result = await page.wait_for_function(r"""() => {
            const state = window.__courtLoginFeedback;
            state?.scan();
            const token = (localStorage.getItem('zxfwtoken') || '').replace(/^"|"$/g, '');
            if (token && !location.hash.includes('/pagesGrxx/pc/login/index')) return 'success';
            if (state?.error) return 'captcha_error';
            return false;
        }""", polling=100, timeout=8000)
        try:
            return str(await result.json_value())
        finally:
            await result.dispose()
    except Exception as exc:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        if isinstance(exc, PlaywrightTimeoutError):
            return "timeout"
        raise
    finally:
        try:
            await page.evaluate("() => window.__courtLoginFeedback?.observer.disconnect()")
        except Exception:
            pass


async def _refresh_captcha_image(
    page: Any,
    captcha_locator: Any,
    previous_image_url: str,
    image_reader: Callable[[], Any],
    timeout: float = 0.85,
) -> str:
    """点击验证码并在短窗口内取得新图；部分官网会自动换图，需避免重复点击。"""
    deadline = time.monotonic() + max(0.1, float(timeout))

    def absolute(value: Any) -> str:
        return urllib.parse.urljoin(page.url, str(value or ""))

    try:
        current = absolute(await image_reader())
    except Exception:
        current = ""
    if current and current != previous_image_url:
        return current

    clicked = False
    for selector in (".fd-images-code img", ".fd-images-code [style*='background-image']", ".fd-images-code"):
        remaining_ms = int(max(0, (deadline - time.monotonic()) * 1000))
        if remaining_ms <= 0:
            break
        try:
            await page.locator(selector).first.click(timeout=min(250, remaining_ms))
            clicked = True
            break
        except Exception:
            continue
    if not clicked:
        try:
            remaining_ms = int(max(0, (deadline - time.monotonic()) * 1000))
            if remaining_ms > 0:
                await captcha_locator.click(timeout=min(250, remaining_ms))
        except Exception:
            pass

    while time.monotonic() < deadline:
        try:
            current = absolute(await image_reader())
        except Exception:
            current = ""
        if current and current != previous_image_url:
            return current
        await page.wait_for_timeout(50)
    # 下一轮仍会重新读取并识别当前图片；即使官网复用了 URL，也不让刷新流程
    # 把自动登录阻塞数秒，避免错误提示出现后窗口看起来像“卡死”。
    return current or previous_image_url


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _parse_hearing_at(value: Any) -> str:
    """把官网返回的开庭时间转换为本地时间字符串（YYYY-MM-DD HH:MM）。

    兼容 ISO 8601 带时区/不带时区、以及常见的“2026年4月23日 15:30”等中文格式；
    无法识别时返回空字符串，由调用方决定是否落库。
    """
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone()
        return parsed.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        pass
    match = re.search(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})(?:日)?(?:\s+(\d{1,2})[:点时](\d{1,2})?)?", text)
    if match:
        year, month, day = int(match[1]), int(match[2]), int(match[3])
        hour = int(match[4] or 0)
        minute = int(match[5] or 0)
        try:
            return dt.datetime(year, month, day, hour, minute).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return ""
    return ""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _safe_filename(value: Any, fallback: str = "法院文书") -> str:
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", str(value or "")).strip(" .")
    return (name[:180] or fallback)


def _safe_extension(value: Any) -> str:
    extension = re.sub(r"[^A-Za-z0-9]+", "", str(value or "").lower())[:12]
    return f".{extension}" if extension else ""


def _document_filename(filename: Any, extension: Any = "", content_type: str = "") -> str:
    """保留官网文书名，并在缺失时补齐可被 macOS 识别的扩展名。"""
    name = _safe_filename(filename)
    suffix = _safe_extension(extension)
    if not suffix:
        mime_map = {
            "application/pdf": ".pdf", "application/msword": ".doc",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
            "image/jpeg": ".jpg", "image/png": ".png",
        }
        suffix = mime_map.get(content_type.split(";", 1)[0].strip().lower(), "")
    return name if not suffix or name.lower().endswith(suffix) else f"{name}{suffix}"


def _redact_account(value: str) -> str:
    if len(value) <= 3:
        return "*" * len(value)
    return f"{value[:2]}{'*' * max(2, len(value) - 4)}{value[-2:]}"


def _display_account(value: str) -> str:
    """Account number shown in the status card and account switcher."""
    return str(value or "").strip()


def _account_id(value: str) -> str:
    """Return a stable, non-sensitive local identifier for a court account."""
    account = str(value or "").strip()
    if not account:
        return "legacy"
    return "acct_" + hashlib.sha256(account.encode("utf-8")).hexdigest()[:16]


PROBE_ROUTE_LIMIT = 3000
# 记录网关路由时仅保留业务筛选参数，丢弃分页与可能含账号、证号等敏感信息的其余参数。
PROBE_QUERY_WHITELIST = {"xxlb", "sdzt", "tzfs", "status", "type", "kind"}
PROBE_STATIC_SUFFIXES = (".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2", ".ttf", ".map", ".html")


def _probe_route_target(url: str) -> str:
    """把监听到的响应地址收敛为可聚合的业务路由，仅保留白名单查询参数。"""
    parsed = urllib.parse.urlsplit(str(url or ""))
    if parsed.hostname != "zxfw.court.gov.cn":
        return ""
    path = parsed.path
    if not (path.startswith("/yzw") or path.startswith("/portal-chat")):
        return ""
    if path.lower().endswith(PROBE_STATIC_SUFFIXES):
        return ""
    kept = [(k, v) for k, v in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True) if k in PROBE_QUERY_WHITELIST]
    target = f"https://{parsed.netloc}{path}"
    query = "&".join(f"{k}={v}" for k, v in kept)
    return f"{target}?{query}" if query else target


def _request_body_keys(request: Any) -> str:
    """从监听请求中提取 JSON/表单体的键名，只存键名不存值。"""
    try:
        post = request.post_data or ""
    except Exception:
        return ""
    if not post or len(post) > 4096:
        return ""
    try:
        data = json.loads(post)
    except (ValueError, TypeError):
        return ""
    if isinstance(data, dict):
        return ",".join(str(key) for key in data.keys())[:300]
    if isinstance(data, list):
        return f"<list x{len(data)}>"
    return ""


def _record_probe_route(conn: Any, method: str, url: str, status: int, post_data: str = "") -> None:
    target = _probe_route_target(url)
    if not target:
        return
    now = _now()
    body_keys = _request_body_keys(type("R", (), {"post_data": post_data})())
    conn.execute("""INSERT INTO case_manager_court_online_probe_routes(method,url,status,hit_count,first_seen,last_seen,body_keys)
                    VALUES(?,?,?,1,?,?,?)
                    ON CONFLICT(method,url) DO UPDATE SET status=excluded.status,hit_count=hit_count+1,last_seen=excluded.last_seen,body_keys=excluded.body_keys""",
                 (method.upper(), target[:500], int(status), now, now, body_keys[:300]))
    conn.execute("DELETE FROM case_manager_court_online_probe_routes WHERE id NOT IN (SELECT id FROM case_manager_court_online_probe_routes ORDER BY last_seen DESC LIMIT ?)", (PROBE_ROUTE_LIMIT,))


def _read_secret_store() -> dict[str, Any]:
    """Read the multi-account keychain payload, upgrading the old single account shape.

    Account names, passwords and tokens remain in the macOS Keychain.  SQLite only
    receives a one-way account id, so the two data sets can never overwrite one
    another while the account number itself is not copied into the application DB.
    """
    try:
        done = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w"],
            capture_output=True, text=True, timeout=8,
        )
        if done.returncode != 0:
            return {}
        data = json.loads(done.stdout)
        if not isinstance(data, dict):
            return {"version": 2, "active_account_id": "legacy", "accounts": {}, "shared": {}}
        if int(data.get("version") or 0) >= 2 and isinstance(data.get("accounts"), dict):
            accounts = {
                str(key): {str(k): str(v) for k, v in value.items()}
                for key, value in data["accounts"].items() if isinstance(value, dict)
            }
            return {
                "version": 2,
                "active_account_id": str(data.get("active_account_id") or "legacy"),
                "accounts": accounts,
                "shared": {str(k): str(v) for k, v in (data.get("shared") or {}).items()},
                "legacy_profile_account_id": str(data.get("legacy_profile_account_id") or ""),
            }
        # Compatibility with the original single-account keychain record.
        account = str(data.get("account") or "").strip()
        active = _account_id(account)
        personal = {key: str(data.get(key) or "") for key in ("account", "password", "session_token")}
        shared = {key: str(data.get(key) or "") for key in ("baidu_api_key", "baidu_secret_key")}
        return {"version": 2, "active_account_id": active, "accounts": {active: personal} if account else {},
                "shared": shared, "legacy_profile_account_id": active if account else ""}
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return {"version": 2, "active_account_id": "legacy", "accounts": {}, "shared": {}}


def _write_secret_store(value: dict[str, Any]) -> None:
    safe = {
        "version": 2,
        "active_account_id": str(value.get("active_account_id") or "legacy"),
        "accounts": value.get("accounts") or {},
        "shared": value.get("shared") or {},
        "legacy_profile_account_id": str(value.get("legacy_profile_account_id") or ""),
    }
    _write_keychain_payload(safe)


def _write_keychain_payload(value: dict[str, Any]) -> None:
    try:
        done = subprocess.run(
            ["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT,
             "-w", _json(value)], capture_output=True, text=True, timeout=8,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CourtOnlineError("无法写入 macOS 钥匙串") from exc
    if done.returncode != 0:
        raise CourtOnlineError("无法写入 macOS 钥匙串")


def _read_secret() -> dict[str, str]:
    store = _read_secret_store()
    active = str(store.get("active_account_id") or "legacy")
    account = dict((store.get("accounts") or {}).get(active) or {})
    secret = {str(k): str(v) for k, v in (store.get("shared") or {}).items()}
    secret.update({str(k): str(v) for k, v in account.items()})
    secret["_account_id"] = active
    return secret


def _write_secret(value: dict[str, str]) -> None:
    """Persist fields for the active account without touching other accounts."""
    store = _read_secret_store()
    active = str(value.get("_account_id") or store.get("active_account_id") or "legacy")
    accounts = store.setdefault("accounts", {})
    personal = dict(accounts.get(active) or {})
    for key in ("account", "password", "session_token"):
        if key in value:
            personal[key] = str(value[key] or "")
    if personal.get("account"):
        accounts[active] = personal
    shared = store.setdefault("shared", {})
    for key in ("baidu_api_key", "baidu_secret_key"):
        if key in value:
            shared[key] = str(value[key] or "")
    store["active_account_id"] = active
    _write_secret_store(store)


def _active_account_id() -> str:
    return _read_secret().get("_account_id") or "legacy"


def _scoped_remote_id(account_id: str, remote_id: Any) -> str:
    """Namespace a remote identifier because different accounts can share it."""
    return f"{account_id}:{str(remote_id)}"


def _profile_dir_for_active_account() -> Path:
    store = _read_secret_store()
    active = str(store.get("active_account_id") or "legacy")
    # Keep the original persistent browser profile for the first account so its
    # existing logged-in session is retained during the upgrade.
    if active and active == str(store.get("legacy_profile_account_id") or ""):
        return PROFILE_DIR
    return PROFILE_ACCOUNTS_DIR / active


def _canonical_hearing_remote_id(account_id: str, source: str, raw_json: str, fallback: str) -> str:
    """Build one stable local id for a hearing regardless of its import path."""
    try:
        raw = json.loads(raw_json or "{}")
    except (TypeError, ValueError):
        raw = {}
    def raw_value(*keys: str) -> str:
        for key in keys:
            value = raw.get(key) if isinstance(raw, dict) else None
            if value not in (None, ""):
                return str(value)
        return ""
    source = str(source or "")
    if source.startswith("case"):
        category = source.rsplit("_", 1)[-1] if "_" in source else "sp"
        if category not in {"sp", "zx", "pc"}:
            category = "sp"
        remote = raw_value("cbh", "cajbh", "id")
        if remote:
            return _scoped_remote_id(account_id, f"case:{category}:{remote}")
    if source == "kqtbaj":
        remote = raw_value("id", "cbh", "cajbh", "ahdm", "uuid")
        if remote:
            return _scoped_remote_id(account_id, f"kqtbaj:{remote}")
    return _scoped_remote_id(account_id, fallback)


def _merge_duplicate_court_hearings(conn: Any) -> int:
    """Collapse historic duplicate hearings while preserving the useful link/data.

    Older versions formed a hearing id from an already-prefixed case id.  Each
    account switch could add another prefix, making one court event appear two
    or three times.  Equal account/case/time/court rows are the same event.
    """
    groups = conn.execute(
        """SELECT account_id,case_number,case_name,court_name,hearing_at
           FROM case_manager_court_online_hearings
           GROUP BY account_id,case_number,case_name,court_name,hearing_at
           HAVING COUNT(*) > 1"""
    ).fetchall()
    if not groups:
        return 0
    hearing_table_exists = bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='case_manager_hearings'"
    ).fetchone())
    removed = 0
    for group in groups:
        rows = conn.execute(
            """SELECT * FROM case_manager_court_online_hearings
               WHERE account_id=? AND case_number=? AND case_name=? AND court_name=? AND hearing_at=?
               ORDER BY CASE WHEN linked_case_id IS NULL OR linked_case_id=0 THEN 0 ELSE 1 END DESC,
                        datetime(updated_at) DESC,id DESC""",
            tuple(group),
        ).fetchall()
        survivor = dict(rows[0])
        survivor_id = int(survivor["id"])
        linked = next((row["linked_case_id"] for row in rows if row["linked_case_id"]), None)
        canonical = _canonical_hearing_remote_id(
            str(survivor["account_id"]), str(survivor["source"]), str(survivor["raw_json"]), str(survivor["remote_id"]),
        )
        duplicate_ids = [int(row["id"]) for row in rows[1:]]
        if duplicate_ids:
            if hearing_table_exists:
                for duplicate_id in duplicate_ids:
                    conn.execute(
                        "UPDATE case_manager_hearings SET source_key=? WHERE source_key=?",
                        (f"court-hearing:{survivor_id}", f"court-hearing:{duplicate_id}"),
                    )
            conn.execute(
                f"DELETE FROM case_manager_court_online_hearings WHERE id IN ({','.join('?' for _ in duplicate_ids)})",
                duplicate_ids,
            )
            removed += len(duplicate_ids)
        conn.execute(
            "UPDATE case_manager_court_online_hearings SET remote_id=?,linked_case_id=COALESCE(?,linked_case_id),updated_at=? WHERE id=?",
            (canonical, linked, _now(), survivor_id),
        )
    return removed


def _normalize_court_remote_ids(conn: Any) -> int:
    """Finish the account-id migration without displaying duplicate records.

    Court record ids used to be stored as the raw id returned by the website.
    They are now namespaced by account so that two court accounts can safely
    contain the same remote id.  A service update could run in between those
    two conventions, leaving both ``id`` and ``account:id`` for one item.
    Normalize the historic rows on startup and retain the newer scoped row
    where both exist.
    """
    def canonical_id(table: str, account_id: str, remote_id: str, category: Any = "") -> str:
        source = str(remote_id or "")
        account_prefix = f"{account_id}:"
        # A transitional migration prefixed some ids more than once.  Strip
        # only this account's own prefix, never another account's namespace.
        while source.startswith(account_prefix):
            source = source[len(account_prefix):]
        if table == "case_manager_court_online_cases":
            category = str(category or "sp")
            if category not in {"sp", "zx", "pc"}:
                category = "sp"
            while True:
                if source.startswith(account_prefix):
                    source = source[len(account_prefix):]
                    continue
                if source.startswith(("sp:", "zx:", "pc:")):
                    source = source[3:]
                    continue
                break
            source = f"{category}:{source}"
        return _scoped_remote_id(account_id, source)

    tables = (
        ("case_manager_court_online_records", "case_manager_court_online_attachments", "record_id", "kind"),
        ("case_manager_court_online_cases", "", "", ""),
        ("case_manager_court_online_layy", "case_manager_court_online_layy_audits", "layy_id", ""),
        ("case_manager_court_online_hearings", "", "", ""),
    )
    merged = 0
    for table, child_table, child_fk, type_column in tables:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if not {"id", "remote_id", "account_id"}.issubset(columns):
            continue
        rows = conn.execute(
            f"SELECT * FROM {table} WHERE COALESCE(account_id,'')<>'' AND COALESCE(remote_id,'')<>''"
        ).fetchall()
        for source_row in rows:
            source = dict(source_row)
            account_id = str(source["account_id"])
            remote_id = str(source["remote_id"])
            scoped_id = canonical_id(table, account_id, remote_id, source.get("ajlb"))
            if remote_id == scoped_id:
                continue
            target_sql = f"SELECT * FROM {table} WHERE remote_id=?"
            target_params: list[Any] = [scoped_id]
            if type_column:
                target_sql += f" AND {type_column}=?"
                target_params.append(source[type_column])
            target_row = conn.execute(target_sql, target_params).fetchone()
            if not target_row:
                conn.execute(f"UPDATE {table} SET remote_id=? WHERE id=?", (scoped_id, source["id"]))
                continue

            target = dict(target_row)
            if int(target["id"]) == int(source["id"]):
                continue
            # Preserve child rows whenever they do not already exist on the
            # scoped item.  Conflicting child rows are equivalent snapshots and
            # are safely removed with the old parent below.
            if child_table:
                conn.execute(
                    f"UPDATE OR IGNORE {child_table} SET {child_fk}=? WHERE {child_fk}=?",
                    (target["id"], source["id"]),
                )
            updates = ["linked_case_id=COALESCE(linked_case_id, ?)"]
            params: list[Any] = [source.get("linked_case_id")]
            if "first_seen" in columns:
                updates.append(
                    "first_seen=CASE WHEN COALESCE(NULLIF(first_seen,''),'')='' THEN ? "
                    "WHEN ?<>'' AND ?<first_seen THEN ? ELSE first_seen END"
                )
                first_seen = str(source.get("first_seen") or "")
                params.extend([first_seen, first_seen, first_seen, first_seen])
            if table == "case_manager_court_online_layy":
                # Detail calls are deliberately throttled.  Keep an existing
                # legacy detail snapshot if the newly namespaced row has not
                # fetched it yet.
                updates.append(
                    "detail_json=CASE WHEN COALESCE(NULLIF(detail_json,''),'{}')='{}' "
                    "AND COALESCE(NULLIF(?,''),'{}')<>'{}' THEN ? ELSE detail_json END"
                )
                detail_json = str(source.get("detail_json") or "{}")
                params.extend([detail_json, detail_json])
                for field in ("apply_time", "judge", "filing_method", "claim_amount", "lawsuit_request", "case_number"):
                    updates.append(f"{field}=COALESCE(NULLIF({field},''), ?)")
                    params.append(source.get(field) or "")
            params.append(target["id"])
            conn.execute(f"UPDATE {table} SET {', '.join(updates)} WHERE id=?", params)
            conn.execute(f"DELETE FROM {table} WHERE id=?", (source["id"],))
            merged += 1
    return merged


def _merge_duplicate_court_layy(conn: Any) -> int:
    """Merge indistinguishable filing appointments returned under different ids.

    The court service can occasionally return an identical appointment more
    than once with different internal ids.  Keep those ids internally only
    when their business data differs; otherwise one card is enough for the
    user and avoids inflated tab counts.
    """
    rows = [dict(row) for row in conn.execute("SELECT * FROM case_manager_court_online_layy").fetchall()]
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    identity_fields = (
        "account_id", "category", "court_name", "case_type", "parties", "case_name", "status",
        "cause", "review_comment", "filed_date", "update_date", "applicant", "submit_time",
        "withdraw_time", "material_count", "material_time", "cause_code", "filing_method", "case_number",
    )
    for row in rows:
        key = tuple(str(row.get(field) or "").strip() for field in identity_fields)
        # Do not merge incomplete placeholders that have no meaningful party
        # or case information to establish a business identity.
        if not any(key[index] for index in (3, 4, 5, 10)):
            continue
        groups.setdefault(key, []).append(row)

    removed = 0
    for group in groups.values():
        if len(group) < 2:
            continue
        group.sort(
            key=lambda row: (
                str(row.get("detail_json") or "{}") not in ("", "{}"),
                bool(row.get("linked_case_id")),
                str(row.get("updated_at") or ""),
                int(row["id"]),
            ),
            reverse=True,
        )
        survivor = group[0]
        for duplicate in group[1:]:
            conn.execute(
                "UPDATE OR IGNORE case_manager_court_online_layy_audits SET layy_id=? WHERE layy_id=?",
                (survivor["id"], duplicate["id"]),
            )
            detail_json = str(duplicate.get("detail_json") or "{}")
            conn.execute(
                """UPDATE case_manager_court_online_layy SET
                     linked_case_id=COALESCE(linked_case_id, ?),
                     detail_json=CASE WHEN COALESCE(NULLIF(detail_json,''),'{}')='{}'
                                      AND COALESCE(NULLIF(?,''),'{}')<>'{}' THEN ? ELSE detail_json END,
                     first_seen=CASE WHEN COALESCE(NULLIF(first_seen,''),'')='' THEN ?
                                     WHEN ?<>'' AND ?<first_seen THEN ? ELSE first_seen END
                   WHERE id=?""",
                (
                    duplicate.get("linked_case_id"), detail_json, detail_json,
                    duplicate.get("first_seen") or "", duplicate.get("first_seen") or "",
                    duplicate.get("first_seen") or "", duplicate.get("first_seen") or "", survivor["id"],
                ),
            )
            conn.execute("DELETE FROM case_manager_court_online_layy WHERE id=?", (duplicate["id"],))
            removed += 1
    return removed


def _reconcile_layy_snapshot(
    conn: Any,
    account_id: str,
    remote_ids_by_category: dict[str, set[str]],
) -> int:
    """Remove appointments absent from successfully refreshed official categories.

    The official ``layy`` endpoint is the source of truth for the active
    "我的立案" view. Earlier versions retained every local appointment unless
    the endpoint explicitly returned ``isDel=1``. The site commonly omits
    withdrawn, expired, or otherwise closed appointments from that list
    without returning a tombstone, causing the local view to grow indefinitely.

    Only categories whose request completed successfully are reconciled. That
    means a transient failure for, say, execution cases can never erase their
    cached rows while the successfully returned trial list still mirrors the
    official page.
    """
    categories = [category for category in remote_ids_by_category if category in {"sp", "zx", "pc"}]
    removed = 0
    for category in categories:
        remote_ids = remote_ids_by_category[category]
        clauses = ["account_id=?", "category=?"]
        params: list[Any] = [account_id, category]
        if remote_ids:
            placeholders = ",".join("?" for _ in remote_ids)
            clauses.append(f"remote_id NOT IN ({placeholders})")
            params.extend(sorted(remote_ids))
        where = " AND ".join(clauses)
        stale = conn.execute(
            f"SELECT id FROM case_manager_court_online_layy WHERE {where}", params
        ).fetchall()
        if not stale:
            continue
        stale_ids = [int(row["id"]) for row in stale]
        placeholders = ",".join("?" for _ in stale_ids)
        conn.execute(
            f"DELETE FROM case_manager_court_online_layy_audits WHERE layy_id IN ({placeholders})",
            stale_ids,
        )
        conn.execute(
            f"DELETE FROM case_manager_court_online_layy WHERE id IN ({placeholders})",
            stale_ids,
        )
        removed += len(stale_ids)
    return removed


def _delete_secret() -> None:
    try:
        subprocess.run(["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT],
                       capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.SubprocessError):
        pass


def _validate_court_url(url: str) -> str:
    parsed = urllib.parse.urlparse(str(url or ""))
    if parsed.scheme != "https" or parsed.hostname != "zxfw.court.gov.cn":
        raise HTTPException(status_code=400, detail="仅允许访问人民法院在线服务的 HTTPS 地址")
    return parsed.geturl()


async def automated_filing_api_call(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    """Call one approved filing-draft API using the active lawyer's Token.

    This helper deliberately has no route exposed to the browser.  The only
    caller is the local automated-filing workflow, which never calls the final
    filing-submit, verification, signature, or captcha APIs.
    """
    verb = str(method or "").upper()
    if verb not in {"GET", "POST", "PATCH", "DELETE"}:
        raise CourtOnlineError("不支持的一张网立案接口方法", 422)
    clean_path = str(path or "")
    # The public filing page removes a party through this one narrow endpoint.
    # Do not turn DELETE into a general capability: it is allowed only for a
    # single party row, never for a draft, material, agent, or final filing.
    if verb == "DELETE" and not re.fullmatch(r"/yzw-zxfw-lafw/api/v3/layy/dsr/[^/]+/[^/]+", clean_path):
        raise CourtOnlineError("仅允许删除已确认的单张重复当事人卡", 422)
    approved_auxiliary_paths = {
        "/yzw-zxfw-ajfw/api/v1/file/upload/signature",
        "/yzw-zxfw-ajfw/api/v1/dzqm/dzqmList",
        "/yzw-zxfw-yhfw/api/v1/grxx/yjsd/list",
        "/yzw-zxfw-ajfw/api/v1/isMakeSddzqrs",
        "/yzw-zxfw-ajfw/api/v1/sddzqrsMake",
        "/yzw-zxfw-ajfw/api/v1/saveSddzFile",
        "/yzw-zxfw-lafw/api/v3/ysla/ay/pz",
    }
    allowed_upload_signature = clean_path == "/yzw-zxfw-ajfw/api/v1/file/upload/signature"
    if not clean_path.startswith("/yzw-zxfw-lafw/api/v3/layy") and clean_path not in approved_auxiliary_paths:
        raise CourtOnlineError("不允许调用该一张网接口", 422)
    # 最终提交及所有认证相关接口永远不进入自动化白名单。
    if not allowed_upload_signature and any(token in clean_path.lower() for token in ("submit", "commit", "captcha", "sign", "verify", "auth")):
        raise CourtOnlineError("自动化立案不调用最终提交或认证接口", 422)
    secret = _read_secret()
    token = str(secret.get("session_token") or "")
    if not token:
        raise CourtOnlineError("请先登录人民法院在线服务", 401)
    headers = {
        "Authorization": token,
        "Accept": "application/json",
        "Origin": COURT_ORIGIN,
        "Referer": f"{COURT_ORIGIN}/zxfw/",
    }
    url = _validate_court_url(f"{COURT_API}{clean_path}")
    client = httpx.AsyncClient(timeout=90 if clean_path == "/yzw-zxfw-lafw/api/v3/layy/ocr" else 60,
                               headers=headers, follow_redirects=False)
    try:
        # OCR uses GET but appends parties. A timeout is an unknown write
        # outcome, never permission to replay it. Ordinary detail GETs retry.
        retryable = verb in {"GET", "PATCH", "DELETE"} and clean_path != "/yzw-zxfw-lafw/api/v3/layy/ocr"
        response = None
        for attempt in range(4):
            try:
                if verb == "GET":
                    response = await client.get(url, params=payload or None)
                elif verb == "POST":
                    response = await client.post(url, json=payload or {})
                elif verb == "PATCH":
                    response = await client.patch(url, json=payload or {})
                else:
                    # The court's party-delete route carries both identifiers in
                    # the path and accepts no body.  ``httpx`` versions bundled
                    # with the desktop app do not expose ``json=`` on ``delete()``.
                    response = await client.delete(url)
                break
            except httpx.TimeoutException as exc:
                if not retryable or attempt == 3:
                    raise CourtOnlineError("一张网接口请求超时，请稍后重试或检查官网是否处理中", 504) from exc
                await asyncio.sleep(1.0 * (attempt + 1))
            except httpx.TransportError as exc:
                if not retryable or attempt == 3:
                    raise CourtOnlineError("连接人民法院在线服务失败，请检查网络与登录状态", 502) from exc
                await asyncio.sleep(1.0 * (attempt + 1))
    except httpx.HTTPError as exc:
        raise CourtOnlineError("一张网接口请求异常，请稍后重试", 502) from exc
    finally:
        await client.aclose()
    if response.status_code == 401:
        raise CourtOnlineError("法院官网 Token 已过期，请重新登录后继续", 401)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        # The filing workbench needs an actionable error without retaining or
        # exposing a complete court response (which may contain personal data).
        message = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                message = str(body.get("message") or body.get("msg") or body.get("error") or "").strip()
        except ValueError:
            pass
        suffix = f"：{message[:180]}" if message else ""
        raise CourtOnlineError(f"一张网接口响应异常（HTTP {response.status_code}）{suffix}") from exc
    try:
        data = response.json()
    except ValueError as exc:
        raise CourtOnlineError(f"一张网接口响应异常（HTTP {response.status_code}，未返回 JSON 数据）") from exc
    if isinstance(data, dict) and data.get("success") is False:
        raise CourtOnlineError(str(data.get("message") or "一张网接口拒绝了本次写入"), 422)
    return data.get("data", data) if isinstance(data, dict) else data


async def automated_filing_upload_file(file_path: Path, court_id: str, material_type: str) -> str:
    """Upload one local filing file through the court-issued, short-lived OSS signature.

    Only the active lawyer's selected local file is sent.  The returned object
    path is not a public URL and is subsequently registered on the same draft.
    """
    source = Path(file_path)
    if not source.is_file() or source.stat().st_size <= 0:
        raise CourtOnlineError("待上传材料不可读取", 422)
    extension = source.suffix.lower() or ".pdf"
    signature = await automated_filing_api_call("POST", "/yzw-zxfw-ajfw/api/v1/file/upload/signature", {
        "path": "layy", "ext": extension, "fydm": str(court_id), "cllx": str(material_type),
    })
    if not isinstance(signature, dict) or not all(signature.get(key) for key in ("ossPath", "storeAs", "token", "policy", "ossaccessKeyId", "signature")):
        raise CourtOnlineError("一张网未返回可用的材料上传凭证")
    form = {
        "key": str(signature["storeAs"]), "x-oss-security-token": str(signature["token"]),
        "policy": str(signature["policy"]), "OSSAccessKeyId": str(signature["ossaccessKeyId"]),
        "success_action_status": "200", "signature": str(signature["signature"]),
    }
    upload_url = _validate_download_url(str(signature["ossPath"]))
    try:
        mime_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        # macOS/Python 对 .docx 的识别并非所有安装环境都完整，显式兜底。
        if source.suffix.lower() == ".docx":
            mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        with source.open("rb") as handle:
            async with httpx.AsyncClient(timeout=120, follow_redirects=False) as client:
                response = await client.post(upload_url, data=form, files={"file": (source.name, handle, mime_type)})
        response.raise_for_status()
    except (OSError, httpx.HTTPError) as exc:
        raise CourtOnlineError("材料上传到一张网文件服务失败") from exc
    return str(signature["storeAs"])


def _validate_download_url(url: str) -> str:
    """法院接口会返回短时有效的 OSS HTTPS 文书地址。"""
    parsed = urllib.parse.urlparse(str(url or ""))
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not (host == "zxfw.court.gov.cn" or host.endswith(".aliyuncs.com")):
        raise HTTPException(status_code=400, detail="附件地址不受人民法院在线服务信任")
    return parsed.geturl()


def _browser_executable() -> str:
    choices = [
        os.environ.get("LEGAL_KB_BROWSER_EXECUTABLE", ""),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        str(Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    ]
    return next((item for item in choices if item and Path(item).is_file()), "")


def _browser_profile_is_frontmost(profile_dir: Path, executable: str) -> bool:
    """Verify that Chrome's visible foreground process uses our dedicated profile."""
    if not executable:
        return False
    try:
        matches = subprocess.run(
            ["pgrep", "-f", ".*" + re.escape(f"--user-data-dir={profile_dir}")],
            capture_output=True, text=True, timeout=8,
        )
        if matches.returncode != 0:
            return False
        expected_executable = Path(executable).resolve()
        profile_arg = f"--user-data-dir={profile_dir}"
        for raw_pid in matches.stdout.splitlines():
            if not raw_pid.isdigit():
                continue
            pid = int(raw_pid)
            command = subprocess.run(
                ["ps", "-p", str(pid), "-o", "comm="],
                capture_output=True, text=True, timeout=8,
            )
            if command.returncode != 0 or Path(command.stdout.strip()).resolve() != expected_executable:
                continue
            arguments = subprocess.run(
                ["ps", "-p", str(pid), "-o", "args="],
                capture_output=True, text=True, timeout=8,
            )
            if arguments.returncode != 0 or not re.search(
                r"(?:^|\s)" + re.escape(profile_arg) + r"(?=\s|$)", arguments.stdout
            ):
                continue
            front = subprocess.run(["lsappinfo", "front"], capture_output=True, text=True, timeout=8)
            if front.returncode != 0 or not front.stdout.strip():
                return False
            info = subprocess.run(
                ["lsappinfo", "info", "-only", "pid", front.stdout.strip()],
                capture_output=True, text=True, timeout=8,
            )
            return info.returncode == 0 and bool(re.search(rf"\bpid\s*=\s*{pid}\b", info.stdout))
    except Exception:
        return False
    return False


def _court_browser_launch_args(*, background: bool) -> list[str]:
    """Return conservative flags for the dedicated court-service browser.

    Component updates are independent of the normal Chrome application update
    and can download large optional models. The court integration uses its own
    OCR path and does not need those background downloads to keep a login
    session alive. The cache-size limit only bounds ordinary HTTP cache data;
    cookies, localStorage, downloads, and the persistent profile remain intact.
    """
    args = [
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-component-update",
        # Start the dedicated browser minimized. CDP restores a normal,
        # centered window only when the user explicitly requests manual input.
        # This avoids a visible frame while Chrome is still starting up.
        "--start-minimized",
        f"--disk-cache-size={COURT_BROWSER_DISK_CACHE_BYTES}",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-background-timer-throttling",
    ]
    if background:
        args.append("--hide-crash-restore-bubble")
    else:
        # Keep the legacy fallback position as a last-resort guard for Chrome
        # builds that ignore --start-minimized during first-window creation.
        # CDP immediately minimizes the window, and reveal explicitly replaces
        # these coordinates with a normal centered window.
        args.append("--window-position=-32000,-32000")
    return args


def _trim_uniform_border(image_bytes: bytes, tolerance: int = 10) -> bytes:
    """把整屏截图四周的纯色窗口背景裁掉，只保留官网页面内容。

    受控 Chrome 的窗口尺寸与渲染视口在某些操作序列下会短暂不同步，
    截图右下方可能出现大面积白底；按右下角底色裁剪后，浮窗画面始终
    紧凑贴合官网内容。裁剪失败或裁不动时原样返回。
    """
    try:
        from PIL import Image, ImageChops
    except ImportError:
        return image_bytes
    try:
        im = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        width, height = im.size
        if width * height > 6_500_000 or width < 40 or height < 40:
            return image_bytes
        background = Image.new("RGB", im.size, im.getpixel((width - 4, height - 4)))
        diff = ImageChops.difference(im, background).convert("L")
        bbox = diff.point(lambda p: 255 if p > tolerance else 0).getbbox()
        if not bbox:
            return image_bytes
        x0, y0, x1, y1 = bbox
        # 内容占比不足一半视为异常，保留原图；四周已无空白也直接返回。
        if (x1 - x0 < width * 0.5 and y1 - y0 < height * 0.5) or (
            width - (x1 - x0) < 16 and height - (y1 - y0) < 16
        ):
            return image_bytes
        cropped = im.crop(bbox)
        out = io.BytesIO()
        cropped.save(out, format="PNG")
        return out.getvalue()
    except Exception:
        return image_bytes


def _ensure_schema(get_db: Callable[[], Any]) -> None:
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS case_manager_court_online_settings (
          id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL DEFAULT 1,
          sync_interval_minutes INTEGER NOT NULL DEFAULT 5,
          auto_login_enabled INTEGER NOT NULL DEFAULT 1, ocr_enabled INTEGER NOT NULL DEFAULT 1,
          session_logged_in_at TEXT DEFAULT '', last_sync_at TEXT DEFAULT '', last_error TEXT DEFAULT '',
          download_directory TEXT DEFAULT '',
          updated_at TEXT NOT NULL
        );
        INSERT OR IGNORE INTO case_manager_court_online_settings(id,updated_at) VALUES(1,datetime('now'));
        CREATE TABLE IF NOT EXISTS case_manager_court_online_records (
          id INTEGER PRIMARY KEY AUTOINCREMENT, remote_id TEXT NOT NULL, kind TEXT NOT NULL,
          title TEXT DEFAULT '', content TEXT DEFAULT '', published_at TEXT DEFAULT '', unread INTEGER NOT NULL DEFAULT 1,
          delivery_status TEXT DEFAULT '', case_number TEXT DEFAULT '', case_name TEXT DEFAULT '', court_name TEXT DEFAULT '',
          case_space_url TEXT DEFAULT '', chat_context_json TEXT DEFAULT '{}', raw_json TEXT DEFAULT '{}',
          linked_case_id INTEGER, stored_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          UNIQUE(kind,remote_id), FOREIGN KEY(linked_case_id) REFERENCES case_manager_cases(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_court_online_records_kind_date ON case_manager_court_online_records(kind,published_at DESC);
        CREATE TABLE IF NOT EXISTS case_manager_court_online_attachments (
          id INTEGER PRIMARY KEY AUTOINCREMENT, record_id INTEGER NOT NULL, remote_id TEXT NOT NULL,
          filename TEXT NOT NULL, extension TEXT DEFAULT '', source_url TEXT DEFAULT '', staging_path TEXT DEFAULT '',
          size_bytes INTEGER DEFAULT 0, status TEXT NOT NULL DEFAULT 'available', downloaded_at TEXT DEFAULT '', last_error TEXT DEFAULT '',
          UNIQUE(record_id,remote_id), FOREIGN KEY(record_id) REFERENCES case_manager_court_online_records(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS case_manager_court_online_logs (
          id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, level TEXT NOT NULL, message TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS case_manager_court_online_probe_routes (
          id INTEGER PRIMARY KEY AUTOINCREMENT, method TEXT NOT NULL, url TEXT NOT NULL,
          status INTEGER DEFAULT 0, hit_count INTEGER NOT NULL DEFAULT 1,
          first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, body_keys TEXT DEFAULT '',
          UNIQUE(method,url)
        );
        CREATE TABLE IF NOT EXISTS case_manager_court_online_cases (
          id INTEGER PRIMARY KEY AUTOINCREMENT, remote_id TEXT NOT NULL,
          ajlb TEXT NOT NULL DEFAULT 'sp', case_number TEXT DEFAULT '', case_name TEXT DEFAULT '', cause TEXT DEFAULT '',
          business_type TEXT DEFAULT '', court_name TEXT DEFAULT '', judge TEXT DEFAULT '',
          department TEXT DEFAULT '', stage TEXT DEFAULT '', adjudication TEXT DEFAULT '',
          status INTEGER DEFAULT 0, parties TEXT DEFAULT '', filing_date TEXT DEFAULT '',
          judgment_date TEXT DEFAULT '', update_date TEXT DEFAULT '', raw_json TEXT DEFAULT '{}',
          linked_case_id INTEGER, first_seen TEXT NOT NULL, updated_at TEXT NOT NULL,
          UNIQUE(remote_id), FOREIGN KEY(linked_case_id) REFERENCES case_manager_cases(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS case_manager_court_online_layy (
          id INTEGER PRIMARY KEY AUTOINCREMENT, remote_id TEXT NOT NULL,
          court_name TEXT DEFAULT '', case_type TEXT DEFAULT '', parties TEXT DEFAULT '',
          case_name TEXT DEFAULT '', status TEXT DEFAULT '', cause TEXT DEFAULT '',
          category TEXT DEFAULT '', review_comment TEXT DEFAULT '', filed_date TEXT DEFAULT '',
          update_date TEXT DEFAULT '', raw_json TEXT DEFAULT '{}',
          linked_case_id INTEGER, first_seen TEXT NOT NULL, updated_at TEXT NOT NULL,
          UNIQUE(remote_id), FOREIGN KEY(linked_case_id) REFERENCES case_manager_cases(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS case_manager_court_online_layy_audits (
          id INTEGER PRIMARY KEY AUTOINCREMENT, layy_id INTEGER NOT NULL, remote_id TEXT NOT NULL DEFAULT '',
          shjg TEXT DEFAULT '', shjg_text TEXT DEFAULT '', review_comment TEXT DEFAULT '',
          review_time TEXT DEFAULT '', reviewer TEXT DEFAULT '', reviewer_id TEXT DEFAULT '',
          remark_term TEXT DEFAULT '', reject_reason TEXT DEFAULT '', raw_json TEXT DEFAULT '{}',
          created_at TEXT NOT NULL,
          UNIQUE(layy_id, remote_id),
          FOREIGN KEY(layy_id) REFERENCES case_manager_court_online_layy(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS case_manager_court_online_hearings (
          id INTEGER PRIMARY KEY AUTOINCREMENT, remote_id TEXT NOT NULL,
          source TEXT NOT NULL DEFAULT 'case_list', case_number TEXT DEFAULT '',
          case_name TEXT DEFAULT '', court_name TEXT DEFAULT '', hearing_type TEXT DEFAULT '',
          hearing_at TEXT DEFAULT '', location TEXT DEFAULT '', judge TEXT DEFAULT '',
          status TEXT DEFAULT '', raw_json TEXT DEFAULT '{}',
          linked_case_id INTEGER, first_seen TEXT NOT NULL, updated_at TEXT NOT NULL,
          UNIQUE(remote_id), FOREIGN KEY(linked_case_id) REFERENCES case_manager_cases(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_court_online_hearings_at ON case_manager_court_online_hearings(hearing_at);
        """)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(case_manager_court_online_probe_routes)").fetchall()}
        if "body_keys" not in columns:
            conn.execute("ALTER TABLE case_manager_court_online_probe_routes ADD COLUMN body_keys TEXT DEFAULT ''")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(case_manager_court_online_settings)").fetchall()}
        if "download_directory" not in columns:
            conn.execute("ALTER TABLE case_manager_court_online_settings ADD COLUMN download_directory TEXT DEFAULT ''")
        # Separate every account's local records. Existing records are assigned
        # to the account that was already configured before this upgrade.
        legacy_account_id = _active_account_id()
        for table in (
            "case_manager_court_online_records", "case_manager_court_online_cases",
            "case_manager_court_online_layy", "case_manager_court_online_hearings",
        ):
            table_columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if "account_id" not in table_columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN account_id TEXT NOT NULL DEFAULT 'legacy'")
            conn.execute(f"UPDATE {table} SET account_id=? WHERE account_id='' OR account_id='legacy'", (legacy_account_id,))
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_account ON {table}(account_id)")
        # “我的案件”在官网区分审判/执行/破产三类：ajlb 列记录类别
        # （sp=审判、zx=执行、pc=破产），remote_id 加类别前缀防止跨类别冲突。
        case_columns = {row[1] for row in conn.execute("PRAGMA table_info(case_manager_court_online_cases)").fetchall()}
        if "ajlb" not in case_columns:
            conn.execute("ALTER TABLE case_manager_court_online_cases ADD COLUMN ajlb TEXT NOT NULL DEFAULT 'sp'")
        # 兼容旧格式数据：官网记录无类别前缀时补上 'sp:' 前缀并标记为审判案件。
        # 若同一条记录已存在带前缀版本（例如运行中的旧服务刚写入的无前缀行），
        # 先删除无前缀副本避免 UNIQUE 冲突，保留带前缀版本。
        conn.execute(
            """DELETE FROM case_manager_court_online_cases
               WHERE ajlb='sp' AND remote_id NOT LIKE 'sp:%' AND remote_id NOT LIKE 'zx:%' AND remote_id NOT LIKE 'pc:%'
                 AND EXISTS (SELECT 1 FROM case_manager_court_online_cases t WHERE t.remote_id='sp:'||case_manager_court_online_cases.remote_id)"""
        )
        conn.execute(
            """UPDATE case_manager_court_online_cases SET remote_id='sp:'||remote_id, ajlb='sp'
               WHERE ajlb='sp' AND remote_id NOT LIKE 'sp:%' AND remote_id NOT LIKE 'zx:%' AND remote_id NOT LIKE 'pc:%'"""
        )
        # 立案预约详情字段：官网列表接口之外，详情接口（layyxq）还返回申请人、
        # 申请/提交时间、承办人、立案方式、标的额、案号等，审核记录单独存子表。
        layy_columns = {row[1] for row in conn.execute("PRAGMA table_info(case_manager_court_online_layy)").fetchall()}
        for name, ddl in {
            "applicant": "TEXT DEFAULT ''",
            "apply_time": "TEXT DEFAULT ''",
            "submit_time": "TEXT DEFAULT ''",
            "judge": "TEXT DEFAULT ''",
            "filing_method": "TEXT DEFAULT ''",
            "claim_amount": "TEXT DEFAULT ''",
            "lawsuit_request": "TEXT DEFAULT ''",
            "case_number": "TEXT DEFAULT ''",
            "cause_code": "TEXT DEFAULT ''",
            "material_count": "INTEGER DEFAULT 0",
            "material_time": "TEXT DEFAULT ''",
            "withdraw_time": "TEXT DEFAULT ''",
            "detail_json": "TEXT DEFAULT '{}'",
        }.items():
            if name not in layy_columns:
                conn.execute(f"ALTER TABLE case_manager_court_online_layy ADD COLUMN {name} {ddl}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_court_online_layy_category ON case_manager_court_online_layy(category)")
        _normalize_court_remote_ids(conn)
        _merge_duplicate_court_layy(conn)
        _merge_duplicate_court_hearings(conn)
        conn.commit()


def register_court_online_service_routes(app: Any, get_db: Callable[[], Any]) -> None:
    _ensure_schema(get_db)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
    # 浏览器档案必须在本服务的生命周期内保持打开。法院的 zxfwtoken 与
    # Cookie 会在页面内续期；每次同步都从这个页面读取最新 token。
    scheduler: dict[str, Any] = {
        "task": None, "login_task": None, "keepalive_task": None, "sync_lock": asyncio.Lock(),
        "sync_job": None, "sync_result": None, "sync_started_at": "", "sync_finished_at": "", "sync_stage": "",
        "playwright": None, "browser_context": None, "browser_page": None,
        "probe_attached": set(), "browser_on_screen": False, "apex_focus_requested": False,
        "browser_connected": False, "browser_cdp_port": "",
        "last_login_launch_at": 0.0, "last_login_cooldown_notice_at": 0.0,
    }

    def log(level: str, message: str) -> None:
        with get_db() as conn:
            conn.execute("INSERT INTO case_manager_court_online_logs(created_at,level,message) VALUES(?,?,?)", (_now(), level, message[:500]))
            conn.execute("DELETE FROM case_manager_court_online_logs WHERE id NOT IN (SELECT id FROM case_manager_court_online_logs ORDER BY id DESC LIMIT 100)")
            conn.commit()

    def account_summaries() -> list[dict[str, Any]]:
        store = _read_secret_store()
        active = str(store.get("active_account_id") or "legacy")
        active_profile = _profile_dir_for_active_account()
        return [{
            "id": account_id,
            "label": _display_account(str(secret.get("account") or "")) or "未命名账号",
            "active": account_id == active,
            "credentials_configured": bool(secret.get("account") and secret.get("password")),
        } for account_id, secret in (store.get("accounts") or {}).items()]

    def repair_staged_download_names() -> None:
        """修复早期版本漏写扩展名的本地文书，不重新下载也不触碰用户其他文件。"""
        with get_db() as conn:
            rows = conn.execute("SELECT id,filename,extension,staging_path FROM case_manager_court_online_attachments WHERE staging_path<>''").fetchall()
            for row in rows:
                source = Path(row[3])
                if not source.is_file() or source.suffix:
                    continue
                target = source.with_name(_document_filename(source.name, row[2]))
                if target == source or target.exists():
                    continue
                try:
                    source.replace(target)
                    conn.execute("UPDATE case_manager_court_online_attachments SET staging_path=? WHERE id=?", (str(target), row[0]))
                except OSError:
                    continue
            conn.commit()

    repair_staged_download_names()

    def settings() -> dict[str, Any]:
        with get_db() as conn:
            row = dict(conn.execute("SELECT * FROM case_manager_court_online_settings WHERE id=1").fetchone())
        secret = _read_secret()
        # 同步失败不等于登录失败；保留有效会话，让登录浮窗按登录结果关闭。
        # 旧 token 或近期同步记录仍不能把停在登录页的窗口判为登录成功。
        page = scheduler.get("browser_page")
        page_open = bool(page and not page.is_closed())
        page_on_login = page_open and "/pagesGrxx/pc/login/index" in str(page.url or "")
        login_error = bool(row.get("last_error") and not str(row["last_error"]).startswith("同步失败："))
        session_active = bool(secret.get("session_token") and page_open and not page_on_login
                              and not login_error)
        if not session_active and secret.get("session_token") and not page_open and not login_error:
            try:
                last_sync = str(row.get("last_sync_at") or "")
                if last_sync and time.time() - dt.datetime.fromisoformat(last_sync.replace("Z", "+00:00")).timestamp() < 1800:
                    session_active = True
            except (ValueError, TypeError):
                pass
        return {
            **row, "enabled": bool(row["enabled"]), "auto_login_enabled": bool(row["auto_login_enabled"]),
            "ocr_enabled": bool(row["ocr_enabled"]), "account": _display_account(secret.get("account", "")),
            "credentials_configured": bool(secret.get("account") and secret.get("password")),
            "ocr_configured": _ddddocr_ready() or bool(secret.get("baidu_api_key") and secret.get("baidu_secret_key")),
            # 仅保存的 token 不能代表会话可用：官网还校验浏览器 Cookie。
            "session_active": session_active, "login_in_progress": bool(scheduler["login_task"] and not scheduler["login_task"].done()),
            "active_account_id": secret.get("_account_id") or "legacy", "accounts": account_summaries(),
        }

    async def backend_session_probe(secret: dict[str, str] | None = None) -> int:
        """纯后端会话探测：仅凭钥匙串 token 请求官网鉴权接口，不依赖浏览器窗口。

        返回 HTTP 状态码；token 缺失或网络异常返回 -1。
        """
        if secret is None:
            secret = _read_secret()
        token = str(secret.get("session_token") or "")
        if not token:
            return -1
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
                response = await client.get(
                    _validate_court_url(f"{COURT_API}/yzw-zxfw-ajfw/api/v1/ajListByUserId"),
                    headers={"Authorization": token, "Accept": "application/json"},
                )
            return response.status_code
        except Exception:
            return -1

    def download_directory() -> Path:
        with get_db() as conn:
            row = conn.execute("SELECT download_directory FROM case_manager_court_online_settings WHERE id=1").fetchone()
        configured = str(row[0] or "").strip() if row else ""
        target = Path(configured).expanduser() if configured else DOWNLOAD_DIR
        if not target.is_absolute():
            target = DOWNLOAD_DIR
        target.mkdir(parents=True, exist_ok=True)
        return target

    def save_settings(body: dict[str, Any]) -> dict[str, Any]:
        interval = int(body.get("sync_interval_minutes", 5) or 5)
        if not 1 <= interval <= 1440:
            raise HTTPException(status_code=422, detail="同步间隔必须介于 1 到 1440 分钟")
        with get_db() as conn:
            current = conn.execute("SELECT download_directory FROM case_manager_court_online_settings WHERE id=1").fetchone()
            directory = str(body["download_directory"]).strip() if "download_directory" in body else str(current[0] or "")
            conn.execute("""UPDATE case_manager_court_online_settings SET enabled=?,sync_interval_minutes=?,auto_login_enabled=?,ocr_enabled=?,download_directory=?,updated_at=? WHERE id=1""", (
                int(bool(body.get("enabled", True))), interval, int(bool(body.get("auto_login_enabled", True))),
                int(bool(body.get("ocr_enabled", True))), directory, _now()))
            conn.commit()
        old = _read_secret()
        supplied_account = str(body.get("account") or "").strip()
        if supplied_account and supplied_account != old.get("account"):
            store = _read_secret_store()
            next_id = _account_id(supplied_account)
            entry = dict((store.get("accounts") or {}).get(next_id) or {})
            entry["account"] = supplied_account
            if str(body.get("password") or "").strip():
                entry["password"] = str(body["password"]).strip()
            store.setdefault("accounts", {})[next_id] = entry
            store["active_account_id"] = next_id
            _write_secret_store(store)
            old = _read_secret()
        for key in ("account", "password", "baidu_api_key", "baidu_secret_key"):
            if key in body and str(body[key]).strip() and not (key == "account" and supplied_account): old[key] = str(body[key]).strip()
        _write_secret(old)
        return settings()

    def set_error(message: str) -> None:
        with get_db() as conn:
            conn.execute("UPDATE case_manager_court_online_settings SET last_error=?,updated_at=? WHERE id=1", (message[:500], _now()))
            conn.commit()

    def _enhance_captcha_image(image_bytes: bytes) -> bytes:
        """放大并增强验证码图片，提高百度 OCR 识别率；异常时原样返回。"""
        try:
            import io
            from PIL import Image, ImageFilter
            img = Image.open(io.BytesIO(image_bytes)).convert("L")
            width, height = img.size
            scale = 3 if width * height < 40000 else 2
            img = img.resize((width * scale, height * scale), Image.LANCZOS)
            img = img.filter(ImageFilter.SHARPEN)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        except Exception:
            return image_bytes

    _baidu_token_cache: dict[str, Any] = {"token": "", "expires_at": 0.0}
    _ddddocr_engine: Any = None
    _ddddocr_error: str = ""

    def _ddddocr_ready() -> bool:
        """本机 ddddocr 验证码识别引擎（免费、不联网）懒加载单例。"""
        nonlocal _ddddocr_engine, _ddddocr_error
        if _ddddocr_engine is not None:
            return True
        try:
            import ddddocr
            _ddddocr_engine = ddddocr.DdddOcr(show_ad=False)
            return True
        except Exception as exc:
            _ddddocr_error = str(exc)[:200]
            return False

    def _local_captcha_value(image_bytes: bytes) -> str:
        """用本机 ddddocr 识别验证码，失败返回空串。"""
        try:
            if not _ddddocr_ready():
                return ""
            result = _ddddocr_engine.classification(image_bytes)
            value = re.sub(r"[^0-9A-Za-z]", "", str(result or ""))
            return value
        except Exception:
            return ""

    async def ocr_captcha(image_url: str, secret: dict[str, str]) -> str:
        if image_url.startswith("data:image"):
            _, _, base64_data = image_url.partition(",")
            try:
                image_bytes = base64.b64decode(base64_data)
            except (ValueError, TypeError) as exc:
                raise CourtOnlineError("验证码图片数据无效") from exc
        else:
            _validate_court_url(image_url)
            async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
                image = await client.get(image_url)
                image.raise_for_status()
                image_bytes = image.content
        enhanced = _enhance_captcha_image(image_bytes)
        # 首选本机 ddddocr（免费、不联网），避免百度 OCR 按量计费。
        value = _local_captcha_value(enhanced)
        if value:
            return value
        # 兜底：配置了百度密钥时才调用云端，未配置则报错转人工。
        if not (secret.get("baidu_api_key") and secret.get("baidu_secret_key")):
            if not _ddddocr_ready():
                raise CourtOnlineError(f"本机 OCR 引擎不可用：{_ddddocr_error or 'ddddocr 未安装'}")
            raise CourtOnlineError("未能识别验证码，请手动输入")
        access_token = _baidu_token_cache["token"]
        if not access_token or time.time() > _baidu_token_cache["expires_at"] - 60:
            async with httpx.AsyncClient(timeout=20) as client:
                token_response = await client.post(BAIDU_TOKEN_URL, data={"grant_type": "client_credentials", "client_id": secret["baidu_api_key"], "client_secret": secret["baidu_secret_key"]})
                token_response.raise_for_status()
                access_token = str(token_response.json().get("access_token") or "")
                if not access_token:
                    raise CourtOnlineError("百度 OCR 密钥无效")
                _baidu_token_cache["token"] = access_token
                _baidu_token_cache["expires_at"] = time.time() + 2592000
        async with httpx.AsyncClient(timeout=20) as client:
            result = await client.post(f"{BAIDU_OCR_URL}?access_token={urllib.parse.quote(access_token)}", data={"image": base64.b64encode(enhanced).decode()})
            result.raise_for_status()
        words = "".join(str(item.get("words", "")) for item in (result.json().get("words_result") or []))
        value = re.sub(r"[^0-9A-Za-z]", "", words)
        if not value:
            raise CourtOnlineError("未能识别验证码")
        return value

    async def current_browser_token() -> str:
        """读取仍在运行的法院页面会话；页面被用户关闭时安全降级。"""
        page = scheduler.get("browser_page")
        if not page:
            return ""
        try:
            if page.is_closed():
                return ""
            token = await page.evaluate("""() => {
                const value = localStorage.getItem('zxfwtoken') || '';
                return String(value).replace(/^\\\"|\\\"$/g, '');
            }""")
            return str(token or "").strip()
        except Exception:
            return ""

    async def persist_browser_token() -> str:
        token = await current_browser_token()
        if token:
            secret = _read_secret()
            if secret.get("session_token") != token:
                secret["session_token"] = token
                _write_secret(secret)
        return token

    async def browser_cookie_header() -> str:
        """把持久浏览器档案的官网 Cookie 安全用于本机后端请求。"""
        context = scheduler.get("browser_context")
        if not context:
            return ""
        try:
            cookies = await context.cookies([COURT_ORIGIN])
            return "; ".join(f"{item['name']}={item['value']}" for item in cookies if item.get("name"))
        except Exception:
            return ""

    async def _clear_emulation_override(context: Any, page: Any) -> None:
        """清除可能残留的设备模拟（Emulation 覆盖会导致官网页面只渲染
        在窗口左上角、右下角留出大面积白底）。"""
        try:
            cdp = await context.new_cdp_session(page)
            await cdp.send("Emulation.clearDeviceMetricsOverride")
            await cdp.detach()
        except Exception as exc:
            log("warning", f"清除官网页面设备模拟失败：{exc}")

    async def _set_browser_window_visibility(page: Any, on_screen: bool) -> bool:
        """用 CDP 把受控官网 Chrome 窗口移入/移出屏幕。

        一张网的自动登录默认全程在后台最小化完成：不弹出原生窗口、不抢焦点，
        用户在应用内浮窗里看实时画面（/browser/frame）。需要人工输入
        验证码时，由浮窗按钮调用 on_screen=True 把原生窗口唤回屏幕。
        """
        if not page or page.is_closed():
            return False
        context = scheduler.get("browser_context")
        if not context:
            return False
        try:
            cdp = await context.new_cdp_session(page)
            window_id = int((await cdp.send("Browser.getWindowForTarget"))["windowId"])
            if on_screen:
                bounds: dict[str, Any] = {
                    "windowState": "normal", "left": 80, "top": 80,
                    "width": 1400, "height": 940,
                }
            else:
                # macOS clamps negative window coordinates to the nearest
                # visible edge, which leaves a strip of Chrome on the desktop.
                # Minimize the controlled window instead; it remains attached
                # to the CDP page and can still be restored for manual CAPTCHA.
                bounds = {"windowState": "minimized"}
            await cdp.send("Browser.setWindowBounds", {"windowId": window_id, "bounds": bounds})
            await cdp.detach()
            scheduler["browser_on_screen"] = on_screen
            return True
        except Exception as exc:
            log("warning", f"调整官网浏览器窗口位置失败：{exc}")
            return False

    async def _hide_controlled_browser_windows(context: Any) -> None:
        """Hide every page window in the dedicated profile before login.

        Chrome can retain a second tab/window after a manual CAPTCHA handoff.
        Moving only the scheduler's current page would leave that stale window
        visible and still able to take focus.
        """
        for candidate in list(getattr(context, "pages", []) or []):
            try:
                await _set_browser_window_visibility(candidate, on_screen=False)
            except Exception:
                pass

    def _frontmost_app_bundle_id() -> str:
        """记录当前前台应用的 bundle id，供浏览器启动后还原焦点。

        用 lsappinfo 而不是 System Events：后者需要辅助功能权限，
        launchd 服务里会静默失败；lsappinfo/open 无需任何授权。
        """
        try:
            front = subprocess.run(["lsappinfo", "front"], text=True, capture_output=True, timeout=8)
            asn = front.stdout.strip() if front.returncode == 0 else ""
            if not asn:
                return ""
            info = subprocess.run(["lsappinfo", "info", "-only", "bundleid", asn], text=True, capture_output=True, timeout=8)
            if info.returncode != 0:
                return ""
            return info.stdout.split("=", 1)[-1].strip().strip('"')
        except Exception:
            return ""

    def _activate_app_by_bundle(bundle_id: str) -> None:
        if not bundle_id:
            return
        # `open -b` may only launch an already-running app without making its
        # window frontmost when the caller is a background service. AppleScript
        # asks LaunchServices to activate the exact bundle and reliably brings
        # the existing APEX window back to the active Space. Keep `open -b` as
        # a fallback for systems where Apple Events permission is unavailable.
        escaped = str(bundle_id).replace("\\", "\\\\").replace('"', '\\"')
        try:
            if shutil.which("osascript"):
                result = subprocess.run(
                    ["osascript", "-e", f'tell application id "{escaped}" to activate'],
                    capture_output=True, text=True, timeout=8,
                )
                if result.returncode == 0:
                    return
            subprocess.run(["open", "-b", bundle_id], capture_output=True, timeout=8)
        except Exception:
            pass

    async def _frontmost_bundle_async() -> str:
        return await asyncio.get_running_loop().run_in_executor(None, _frontmost_app_bundle_id)

    async def _activate_apex_async() -> None:
        await asyncio.get_running_loop().run_in_executor(None, _activate_app_by_bundle, APEX_APP_BUNDLE_ID)

    def _chrome_bundle_path() -> str:
        """从 Chrome 可执行文件路径推出 .app 包路径，仅 macOS 有意义。"""
        executable = _browser_executable()
        if not executable:
            return ""
        path = Path(executable).resolve()
        if path.parent.name == "MacOS" and path.parent.parent.name == "Contents":
            bundle = path.parent.parent.parent
            if bundle.name.endswith(".app") and bundle.is_dir():
                return str(bundle)
        return ""

    def _browser_proc_pattern(profile_dir: Path) -> str:
        """匹配本应用受控 Chrome 的进程模式。

        注意：pkill/pgrep 的模式若以“-”开头会被当成选项报错
        （“pkill: illegal option”），所以用 .* 前缀绕开。
        """
        return f".*--user-data-dir={profile_dir}"

    async def _launch_browser_background(playwright: Any, profile_dir: Path):
        """macOS：用 `open -g` 后台启动 Chrome 并经 CDP 连接受控。

        `open -g` 以后台方式启动应用，Chrome 进程不会主动激活自己；
        Playwright 只通过 CDP
        连接该实例。返回 (context, page)，失败返回 None 走常规启动。
        """
        bundle = _chrome_bundle_path()
        if not bundle:
            return None
        try:
            # 清理同档案的残留进程；单例锁会让新实例拿不到调试端口，
            # 所以必须等到旧进程完全退出再启动。
            pattern = _browser_proc_pattern(profile_dir)
            for _ in range(16):
                alive = subprocess.run(["pgrep", "-f", pattern], text=True, capture_output=True, timeout=10)
                if alive.returncode != 0 or not alive.stdout.strip():
                    break
                subprocess.run(["pkill", "-f", pattern], capture_output=True, timeout=10)
                await asyncio.sleep(0.5)
            await asyncio.sleep(0.3)
            port_file = profile_dir / "DevToolsActivePort"
            try:
                port_file.unlink()
            except OSError:
                pass
            result = subprocess.run(
                ["open", "-g", "-n", "-a", bundle, "--args",
                 f"--user-data-dir={profile_dir}", "--remote-debugging-port=0",
                 *_court_browser_launch_args(background=True)],
                text=True, capture_output=True, timeout=20)
            if result.returncode != 0:
                log("warning", f"后台方式启动 Chrome 失败：{result.stderr.strip()[:160]}")
                return None
            port = ""
            for _ in range(60):
                try:
                    port = port_file.read_text().splitlines()[0].strip()
                    if port:
                        break
                except (OSError, IndexError, ValueError):
                    pass
                await asyncio.sleep(0.5)
            if not port:
                log("warning", "未取得受控 Chrome 调试端口，改用常规方式启动")
                return None
            browser = await playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=20000)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = context.pages[0] if context.pages else await context.new_page()
            scheduler.update({"browser_connected": True, "browser_cdp_port": port})
            log("info", "已通过后台方式启动受控 Chrome，窗口不会激活或抢占前台")
            return context, page
        except Exception as exc:
            log("warning", f"后台方式启动受控浏览器失败：{exc}")
            return None

    async def _terminate_background_browser(connected: bool) -> None:
        """退出经 `open -g` 启动的受控 Chrome（Playwright 连接关闭不会杀进程）。"""
        if not connected:
            return
        profile_dir = _profile_dir_for_active_account()
        try:
            subprocess.run(["pkill", "-f", _browser_proc_pattern(profile_dir)], capture_output=True, timeout=10)
        except Exception:
            pass

    async def start_login(existing_session_only: bool = False) -> None:
        secret = _read_secret()
        if not (secret.get("account") and secret.get("password")):
            raise CourtOnlineError("请先保存法院官网登录账号和密码")
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise CourtOnlineError("当前环境缺少浏览器自动化组件") from exc
        profile_dir = _profile_dir_for_active_account()
        profile_dir.mkdir(parents=True, exist_ok=True)
        log("info", "已在浮窗模式启动人民法院在线服务自动登录")
        async def keep_apex_front() -> None:
            """受控窗口隐藏时保持 APEX 前台，包括 Chrome 最小化后的桌面。"""
            while True:
                if (scheduler.get("apex_focus_requested", False)
                        and not scheduler.get("browser_on_screen", False)
                        and await _frontmost_bundle_async() != APEX_APP_BUNDLE_ID):
                    context = scheduler.get("browser_context")
                    if context:
                        await _hide_controlled_browser_windows(context)
                    await _activate_apex_async()
                await asyncio.sleep(0.25)

        front_guard_task = asyncio.create_task(keep_apex_front())
        login_succeeded = False
        try:
            # 不使用 async with：退出上下文会立即关闭浏览器，造成保存的
            # token 无法随网页续期，随后被后台同步误判为反复会话过期。
            context = scheduler.get("browser_context")
            page = scheduler.get("browser_page")
            if not context or not page or page.is_closed():
                playwright = await async_playwright().start()
                # macOS：优先用 `open -g` 后台方式 + CDP 连接，Chrome 进程
                # 从头到尾不激活自己、不抢占前台，全屏页面不会被切走。
                launched = await _launch_browser_background(playwright, profile_dir)
                if launched:
                    context, page = launched
                    scheduler.update({"playwright": playwright, "browser_context": context,
                                      "browser_page": page, "browser_on_screen": False})
                    await _clear_emulation_override(context, page)
                else:
                    # 兜底：常规拉起有头 Chrome，从启动时最小化，并在启动后
                    # 把焦点还原给原前台应用。认证与验证码流程不作任何绕过。
                    options: dict[str, Any] = {"headless": False, "accept_downloads": True,
                                                "args": _court_browser_launch_args(background=False)}
                    executable = _browser_executable()
                    if executable: options["executable_path"] = executable
                    context = await playwright.chromium.launch_persistent_context(str(profile_dir), **options)
                    page = context.pages[0] if context.pages else await context.new_page()
                    scheduler.update({"playwright": playwright, "browser_context": context, "browser_page": page, "browser_on_screen": False})
            # 每次从 APEX 发起登录都强制收起受控窗口。此前人工点过
            # “打开原生窗口”时 browser_on_screen 会保持为 True，旧逻辑
            # 会把这个可见窗口带入下一次登录，从而再次抢走前台焦点。
            # `open -g` 也不能保证所有 Chrome 版本都不激活窗口；CDP 隐藏
            # 后再恢复 APEX，覆盖新建和复用两种路径。
            await _hide_controlled_browser_windows(context)
            if scheduler.get("apex_focus_requested", False):
                await _activate_apex_async()
            if id(context) not in scheduler.get("probe_attached", set()):
                from .court_filing_ocr import FILING_ROUTE, make_ocr_handler
                await context.route(FILING_ROUTE, make_ocr_handler(get_db, automated_filing_api_call, log))
                scheduler.setdefault("probe_attached", set()).add(id(context))

                async def on_response(response: Any) -> None:
                    try:
                        request = response.request
                        if request.resource_type not in {"xhr", "fetch"}:
                            return
                        target = _probe_route_target(response.url)
                        if target:
                            with get_db() as conn:
                                _record_probe_route(conn, request.method, target, response.status, request.post_data or "")
                                conn.commit()
                    except Exception:
                        pass

                context.on("response", on_response)
                log("info", "已开启法院网关路由监听")

            async def login_page_ready() -> bool:
                """确认登录页已实际挂载，避免空白页被误当成可操作页面。

                官网登录页为 uni-app H5 时挂载在 <uni-app>，旧版 Vue 挂载在
                <#app>；两种都按“出现可操作登录控件”判定就绪。
                """
                try:
                    await page.wait_for_function("""() => {
                        const root = document.querySelector('uni-app') || document.querySelector('#app');
                        return Boolean(root && (root.querySelector('input, button, [role="button"], .fd-login-btn') || root.innerText.trim()));
                    }""", timeout=15000)
                    return True
                except Exception:
                    try:
                        state = await page.evaluate("""() => ({
                            readyState: document.readyState,
                            appChildren: document.querySelector('#app')?.childElementCount || 0,
                            appTextLength: document.querySelector('#app')?.innerText.length || 0,
                        })""")
                        log("warning", f"法院登录页未渲染：{state}")
                    except Exception:
                        log("warning", "法院登录页未渲染，且无法读取页面状态")
                    return False

            async def captcha_image_url() -> str:
                """新版登录页验证码渲染在 uni-image 内 div 的 background-image，
                旧版是 img 标签；两者都兼容，返回可下载/解码的 URL。"""
                return str(await page.evaluate("""() => {
                    const imgEl = document.querySelector('.fd-images-code img');
                    if (imgEl && imgEl.src) return imgEl.src;
                    const bg = document.querySelector('.fd-images-code [style*="background-image"]');
                    if (bg) {
                        const m = (bg.style.backgroundImage || '').match(/url\\(["']?([^"')]+)["']?\\)/);
                        if (m) return m[1];
                    }
                    const dataImg = document.querySelector('img[src^="data:image"]');
                    return dataImg ? dataImg.src : '';
                }""") or "")

            async def open_login_page() -> None:
                login_url = f"{COURT_ORIGIN}/zxfw/#/pagesGrxx/pc/login/index"
                # 偶发的缓存或首屏脚本加载失败会留下一个只有 #app 的空白页。
                # 重载一次即可恢复时不打断用户；第二次仍未挂载则立即报出明确原因。
                for attempt in range(2):
                    if attempt:
                        log("warning", "法院登录页为空白，正在自动重新加载")
                        await page.reload(wait_until="domcontentloaded", timeout=30000)
                    else:
                        await page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
                    await _set_browser_window_visibility(page, on_screen=False)
                    if scheduler.get("apex_focus_requested", False):
                        await _activate_apex_async()
                    if await login_page_ready():
                        return
                raise CourtOnlineError("法院登录页未能加载，请检查网络后重新登录")
            # 扩展实际使用的是 pagesGrxx 这一路由；旧路由会留下旧 token，
            # 但并不会进入可提交的密码登录页，因而会造成“登录成功”的假象。
            # 已登录会话检测：一张网能正常同步说明会话有效，此时点击“登录官网”
            # 应直接打开工作台，而不是重新导航到登录页要求再次登录。
            cached_token = await current_browser_token()
            if not cached_token:
                cached_token = secret.get("session_token", "")
            session_valid = False
            if cached_token:
                try:
                    probe_headers = {"Authorization": cached_token, "Accept": "application/json"}
                    probe_cookie = await browser_cookie_header()
                    if probe_cookie: probe_headers["Cookie"] = probe_cookie
                    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
                        probe = await client.get(_validate_court_url(f"{COURT_API}/yzw-zxfw-ajfw/api/v1/ajListByUserId"), headers=probe_headers)
                        session_valid = probe.status_code == 200
                except Exception:
                    session_valid = False
            if session_valid:
                try:
                    await page.goto(f"{COURT_ORIGIN}/zxfw/#/pagesGrxx", wait_until="domcontentloaded", timeout=30000)
                except Exception:
                    pass
                await _set_browser_window_visibility(page, on_screen=False)
                if scheduler.get("apex_focus_requested", False):
                    await _activate_apex_async()
                secret["session_token"] = cached_token
                _write_secret(secret)
                with get_db() as conn:
                    conn.execute("UPDATE case_manager_court_online_settings SET session_logged_in_at=?,last_error='',updated_at=? WHERE id=1", (_now(), _now()))
                    conn.commit()
                log("info", "法院官网会话已有效，跳过登录页直接打开工作台")
                start_sync_job(manual=True)
                login_succeeded = True
                return
            if existing_session_only:
                raise CourtOnlineError("法院官网会话已失效，请重新登录")
            await open_login_page()
            # 登录页有 个人用户 / 律师用户 / 法人用户 三种角色；本应用面向
            # 律师账号，必须先切换到“律师用户”，否则会一直停在登录页。
            # 优先点精确文字节点，避免 .fd-tab 是整个选项组时误点个人用户。
            # 旧版才退回按选项类名查找；两种都失败则停止，不能继续用错身份。
            try:
                await page.get_by_text("律师用户", exact=True).click(timeout=8000)
            except Exception:
                try:
                    tab = page.locator(".fd-tab").filter(has_text="律师用户").first
                    await tab.click(timeout=8000)
                except Exception as exc:
                    raise CourtOnlineError("登录页未能切换到“律师用户”，请检查官网页面后重试") from exc
            # 页面前端经常变动，按扩展中的 CSS 和通用控件双路径填充。
            try: await page.get_by_text("密码登录", exact=False).click(timeout=8000)
            except Exception: pass
            for selector in (".fd-input-loginid input", "input[type='text']", ".fd-input-account input", "input[placeholder*='账号']"):
                try:
                    await page.locator(selector).first.fill(secret["account"], timeout=4000); break
                except Exception: continue
            for selector in (".fd-input-pwd input[type='password']", "input[type='password']", ".fd-input-password input"):
                try:
                    await page.locator(selector).first.fill(secret["password"], timeout=4000); break
                except Exception: continue
            config = settings()
            if config["ocr_enabled"] and config["ocr_configured"]:
                for attempt in range(3):
                    try:
                        # 登录页验证码图片为 base64 data URI（uni-app H5），新版渲染在
                        # uni-image 的 background-image 里，旧版是 img 标签。
                        captcha = page.locator(".fd-images-code").first
                        await captcha.wait_for(timeout=8000)
                        raw_image_url = await captcha_image_url()
                        if not raw_image_url:
                            raise CourtOnlineError("未获取到验证码图片")
                        image_url = urllib.parse.urljoin(page.url, raw_image_url)
                        value = await ocr_captcha(image_url, secret)
                        field = page.locator(".fd-input-code input, input[placeholder*='验证码']").first
                        if await field.count() == 0:
                            field = page.locator("input[type='text']").nth(1)
                        await field.fill(value)
                        await _arm_login_feedback(page)
                        # 新版登录页登录按钮是 uni-view（class=fd-login-btn），旧版是 button。
                        try: await page.locator(".fd-login-btn").click(timeout=3000)
                        except Exception:
                            try: await page.get_by_role("button", name=re.compile("登录")).click(timeout=3000)
                            except Exception:
                                try: await page.locator("button").filter(has_text="登录").first.click(timeout=3000)
                                except Exception: await page.get_by_text("登录", exact=True).first.click(timeout=3000)
                        outcome = await _wait_login_result(page)
                        if outcome == "success":
                            break
                        if outcome == "timeout":
                            log("warning", "法院登录尚未返回明确结果，保留窗口等待，避免重复提交")
                            break
                        if attempt == 2:
                            log("warning", "验证码自动识别连续三次未被接受，请在浮窗点击“打开原生窗口”手动输入")
                            break
                        log("warning", f"验证码识别第 {attempt + 1} 次未被接受，立即刷新验证码重试")
                        # 官网可能已自动换图；仍为原图时才点击，避免双重刷新。
                        await _refresh_captcha_image(page, captcha, image_url, captcha_image_url)
                    except Exception as exc:
                        try:
                            await page.evaluate("() => window.__courtLoginFeedback?.observer.disconnect()")
                        except Exception:
                            pass
                        log("warning", f"验证码自动识别未完成：{exc}")
                        log("warning", "验证码自动登录已暂停，请在浮窗点击“打开原生窗口”完成验证")
                        break
            # 等待人工接管或自动登录完成；读取 localStorage 中的 token，不向网页 API 暴露。
            for _ in range(300):
                token = await current_browser_token()
                still_on_login = await page.evaluate("() => location.hash.includes('/pagesGrxx/pc/login/index')")
                if token and not still_on_login:
                    secret["session_token"] = str(token)
                    _write_secret(secret)
                    with get_db() as conn:
                        conn.execute("UPDATE case_manager_court_online_settings SET session_logged_in_at=?,last_error='',updated_at=? WHERE id=1", (_now(), _now()))
                        conn.commit()
                    log("info", "法院官网登录成功")
                    # 登录完成立即用刚续期的 token 与 Cookie 同步一次，避免再等一个同步周期。
                    start_sync_job(manual=True)
                    login_succeeded = True
                    return
                await page.wait_for_timeout(500)
            raise CourtOnlineError("登录等待超时，请在浮窗中重试或打开原生窗口手动登录")
        except Exception as exc:
            set_error(str(exc))
            log("error", f"登录失败：{exc}")
            raise
        finally:
            front_guard_task.cancel()
            await asyncio.gather(front_guard_task, return_exceptions=True)
            apex_focus_requested = scheduler.get("apex_focus_requested", False)
            if login_succeeded and apex_focus_requested:
                # The APEX page may stop polling while Chrome is frontmost.
                # Complete the handoff here instead of waiting for /browser/hide.
                context = scheduler.get("browser_context")
                if context:
                    await _hide_controlled_browser_windows(context)
            if apex_focus_requested and (login_succeeded or not scheduler.get("browser_on_screen", False)):
                await _activate_apex_async()
            scheduler["apex_focus_requested"] = False

    def launch_login(force: bool = False, keep_apex_front: bool = False) -> bool:
        if keep_apex_front:
            scheduler["apex_focus_requested"] = True
        task = scheduler.get("login_task")
        if task and not task.done():
            return False
        now = time.monotonic()
        # 定时同步遇到连续 401 时，只保留一次人工登录窗口，不再每五分钟打断用户。
        if not force and now - float(scheduler.get("last_login_launch_at") or 0) < 600:
            if now - float(scheduler.get("last_login_cooldown_notice_at") or 0) > 600:
                scheduler["last_login_cooldown_notice_at"] = now
                log("warning", "法院会话待恢复，已保留登录窗口，10 分钟内不重复发起登录")
            return False
        scheduler["last_login_launch_at"] = now
        login_task = asyncio.create_task(start_login())
        scheduler["login_task"] = login_task
        def clear_focus_request(completed: asyncio.Task) -> None:
            # start_login can fail before its guarded try/finally (for example,
            # when no credentials are configured).
            if scheduler.get("login_task") is completed:
                scheduler["apex_focus_requested"] = False
        login_task.add_done_callback(clear_focus_request)
        return True

    async def court_json(client: httpx.AsyncClient, path: str, payload: dict[str, Any] | None = None, method: str = "POST") -> Any:
        url = _validate_court_url(f"{COURT_API}{path}")
        request = (lambda: client.post(url, json=payload or {}) if method == "POST" else client.get(url, params=payload or None))
        response = await request()
        if response.status_code == 401:
            # 先从持久浏览器页面取一次刚续期的 zxfwtoken 并仅重试一次。
            # 不在这里立即清除钥匙串，以免偶发 401 让用户被强制重新登录。
            fresh_token = await persist_browser_token()
            if fresh_token and fresh_token != client.headers.get("Authorization", ""):
                client.headers["Authorization"] = fresh_token
                cookie_header = await browser_cookie_header()
                if cookie_header: client.headers["Cookie"] = cookie_header
                response = await request()
        if response.status_code == 401:
            raise HTTPException(status_code=401, detail="法院官网会话已过期")
        response.raise_for_status()
        data = response.json()
        return data.get("data", data) if isinstance(data, dict) else data

    def pick(value: dict[str, Any], *keys: str) -> str:
        for key in keys:
            item = value.get(key)
            if item not in (None, ""): return str(item)
        return ""

    def human_case_number(value: dict[str, Any]) -> str:
        """官网的 ahdm 有时是内部 UUID，展示时只采用可读的法定案号。"""
        for candidate in (pick(value, "ah", "caseNo", "case_number"), pick(value, "xxxq", "content", "xxnr")):
            match = re.search(r"[（(]\d{4}[）)][^\n，。；;]{2,100}?号", candidate)
            if match:
                return match.group(0)
        return ""

    def result_rows(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            rows = value.get("records", value.get("list", value.get("data", [])))
            return [item for item in rows if isinstance(item, dict)] if isinstance(rows, list) else []
        return []

    async def paged_rows(client: httpx.AsyncClient, path: str, payload: dict[str, Any], *,
                         page_key: str, size_key: str, method: str = "POST") -> tuple[list[dict[str, Any]], bool]:
        """Read every page without treating a truncated or repeated page as a full snapshot."""
        all_rows: list[dict[str, Any]] = []
        first_keys: set[str] = set()
        page_size = int(payload[size_key])
        for page in range(1, 21):
            rows = result_rows(await court_json(client, path, {**payload, page_key: page}, method=method))
            if rows:
                fingerprint = _json(rows[0])
                if fingerprint in first_keys:
                    log("warning", f"官网分页重复，已停止读取：{path}")
                    return all_rows, False
                first_keys.add(fingerprint)
            all_rows.extend(rows)
            if len(rows) < page_size:
                return all_rows, True
        log("warning", f"官网分页超过 20 页，已保留现有缓存：{path}")
        return all_rows, False

    def _auto_match_case(conn: Any, case_number: str, case_name: str = "") -> Any:
        """按法定案号自动匹配案件管理系统中的案件。

        优先在规范化案号表（case_manager_case_numbers）中做去空格、
        全半角括号归一后精确比对；未命中再回退到案件标题包含完整案号，
        最后尝试当事人名称近似匹配。
        """
        candidates = [case_number, case_name]
        for raw in candidates:
            compact = re.sub(r"[\s（）()《》〈〉·.]", "", raw or "")
            if not compact or not re.search(r"\d", compact):
                continue
            row = conn.execute(
                """SELECT n.case_id FROM case_manager_case_numbers n
                   JOIN case_manager_cases c ON c.id=n.case_id
                   WHERE c.source_status='active'
                     AND COALESCE(c.case_kind,'ordinary')<>'series_child'
                     AND REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(n.case_no,' ',''),'　',''),'（',''),'）',''),'(',''),')','') = ?
                   ORDER BY n.id DESC LIMIT 1""",
                (compact,),
            ).fetchone()
            if row:
                return int(row[0])
            row = conn.execute(
                """SELECT id FROM case_manager_cases c
                   WHERE c.source_status='active'
                     AND COALESCE(c.case_kind,'ordinary')<>'series_child'
                     AND c.title LIKE ?
                   ORDER BY c.id DESC LIMIT 1""",
                (f"%{compact}%",),
            ).fetchone()
            if row:
                return int(row[0])
        return None

    def auto_link_pending_records(conn: Any, account_id: str | None = None) -> int:
        """为所有尚未关联案件的官网记录执行一次案号自动匹配。

        覆盖三类实体：通知记录（case_manager_court_online_records）、
        我的案件（case_manager_court_online_cases）、开庭扫描
        （case_manager_court_online_hearings）。
        """
        targets = (
            "case_manager_court_online_records",
            "case_manager_court_online_cases",
            "case_manager_court_online_hearings",
        )
        linked = 0
        for table in targets:
            rows = conn.execute(
                f"""SELECT id,case_number,case_name FROM {table}
                    WHERE linked_case_id IS NULL AND COALESCE(case_number,'')<>''
                    {"AND account_id=?" if account_id else ""} ORDER BY id""",
                [account_id] if account_id else [],
            ).fetchall()
            for row in rows:
                matched = _auto_match_case(conn, row["case_number"], row["case_name"])
                if matched:
                    conn.execute(
                        f"UPDATE {table} SET linked_case_id=?,updated_at=? WHERE id=?",
                        (matched, _now(), row["id"]),
                    )
                    linked += 1
        return linked

    def upsert_court_hearing(conn: Any, remote_id: str, source: str, raw: dict[str, Any],
                             case_number: str = "", case_name: str = "", court_name: str = "",
                             hearing_type: str = "", hearing_at: str = "", location: str = "",
                             judge: str = "", status: str = "", account_id: str | None = None) -> None:
        """把一张网读取到的开庭时间写入开庭扫描表，并按案号智能关联本地案件。"""
        local_at = _parse_hearing_at(hearing_at)
        if not local_at:
            return
        account_id = account_id or _active_account_id()
        if not str(remote_id).startswith(f"{account_id}:"):
            remote_id = _scoped_remote_id(account_id, remote_id)
        linked = _auto_match_case(conn, case_number, case_name)
        stamp = _now()
        conn.execute(
            """INSERT INTO case_manager_court_online_hearings
               (remote_id,source,case_number,case_name,court_name,hearing_type,hearing_at,location,judge,status,raw_json,linked_case_id,first_seen,updated_at,account_id)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(remote_id) DO UPDATE SET
                 case_number=excluded.case_number, case_name=excluded.case_name,
                 court_name=excluded.court_name, hearing_type=excluded.hearing_type,
                 hearing_at=excluded.hearing_at, location=excluded.location,
                 judge=excluded.judge, status=excluded.status, raw_json=excluded.raw_json,
                 linked_case_id=COALESCE(linked_case_id,excluded.linked_case_id),
                 updated_at=excluded.updated_at""",
            (remote_id, source, case_number, case_name, court_name, hearing_type,
             local_at, location, judge, status, _json(raw), linked or None, stamp, stamp, account_id),
        )

    async def sync_once(manual: bool = False) -> dict[str, Any]:
        async with scheduler["sync_lock"]:
            scheduler["sync_stage"] = "正在连接人民法院在线服务"
            config = settings()
            account_id = str(config.get("active_account_id") or "legacy")
            if not config["enabled"] and not manual: return {"ok": True, "skipped": True}
            secret = _read_secret()
            token = await persist_browser_token() or secret.get("session_token", "")
            # 服务重启后只有钥匙串 token、没有浏览器 Cookie，先恢复持久档案，
            # 不再发送必然失败的请求并误报“会话过期”。
            # 无浏览器窗口时先做纯后端探测：会话仍有效则静默同步，
            # 不自动拉起可见窗口打扰用户；只有窗口存在且会话过期时才重登。
            if not scheduler.get("browser_context"):
                if await backend_session_probe(secret) != 200:
                    if config["auto_login_enabled"] and config["credentials_configured"] and scheduler.get("browser_page") and not scheduler["browser_page"].is_closed():
                        launch_login()
                    return {"ok": False, "needs_login": True, "message": "法院浏览器窗口未打开，已静默跳过本次同步"}
            if not token:
                if config["auto_login_enabled"] and config["credentials_configured"] and scheduler.get("browser_page") and not scheduler["browser_page"].is_closed():
                    launch_login()
                return {"ok": False, "needs_login": True}
            headers = {"Authorization": token, "Accept": "application/json"}
            cookie_header = await browser_cookie_header()
            if cookie_header: headers["Cookie"] = cookie_header
            incoming: list[tuple[str, dict[str, Any]]] = []
            complete_record_snapshots: set[str] = set()
            try:
                async with httpx.AsyncClient(timeout=25, headers=headers, follow_redirects=False) as client:
                    for kind, message_type in (("todo", "1"), ("message", "2")):
                        rows, complete = await paged_rows(client, "/yzw-zxfw-xxfw/api/v1/znxx/list", {"xxlb": message_type, "pageSize": 100, "sfyx": 1, "xxxq": "", "fbsjKsrq": "", "fbsjJsrq": ""}, page_key="pageNo", size_key="pageSize")
                        incoming.extend((kind, item) for item in rows)
                        if complete: complete_record_snapshots.add(kind)
                    deliveries: list[dict[str, Any]] = []
                    delivery_pages_complete = True
                    for status in ("1", "2"):
                        rows, complete = await paged_rows(client, "/yzw-zxfw-sdfw/api/v1/sdfw/getSdListByZjhmAndAhdmNew", {"pageSize": 100, "ajbh": "", "sdzt": status, "tzfs": "16"}, page_key="pageNum", size_key="pageSize")
                        if not complete: delivery_pages_complete = False
                        for item in rows:
                            delivery = {**item, "_delivery_status": status}
                            deliveries.append(delivery)
                    if delivery_pages_complete: complete_record_snapshots.add("delivery")
                    scheduler["sync_stage"] = f"正在读取 {len(deliveries)} 条电子送达的文书"
                    attachment_limit = asyncio.Semaphore(4)
                    async def load_delivery_attachments(delivery: dict[str, Any]) -> None:
                        sdbh = pick(delivery, "sdbh", "id", "bh")
                        if not sdbh: return
                        async with attachment_limit:
                            try:
                                docs = await court_json(client, "/yzw-zxfw-sdfw/api/v1/sdfw/getWsListBySdbhNew", {"sdbh": sdbh, "qdbh": pick(delivery, "qdbh")})
                                delivery["attachments"] = result_rows(docs)
                                delivery["_attachments_loaded"] = True
                            except Exception as exc:
                                log("warning", f"未能读取电子送达附件：{exc}")
                    await asyncio.gather(*(load_delivery_attachments(item) for item in deliveries))
                    incoming.extend(("delivery", item) for item in deliveries)
                    scheduler["sync_stage"] = "正在读取案件、立案预约与开庭信息"
                    cases: list[dict[str, Any]] = []
                    try:
                        cases = result_rows(await court_json(client, "/yzw-zxfw-ajfw/api/v1/ajListByUserId", {}, method="GET"))
                    except Exception as exc:
                        log("warning", f"未能同步法院案件列表：{exc}")
                    # “我的案件”官网按类别分页返回，ajlb 参数区分案件类别：
                    # 审判案件走默认列表接口；执行/破产走案件列表接口，ajlb 取官网
                    # 页面 myCase.field 配置值（执行 1501_000001-1000、破产 1501_000001-1100）。
                    # 任一类同步失败只记警告，不影响其余类别。
                    case_groups: list[tuple[str, list[dict[str, Any]]]] = [("sp", cases)]
                    for ajlb, label, code in (("zx", "执行", "1501_000001-1000"), ("pc", "破产", "1501_000001-1100")):
                        try:
                            rows, _ = await paged_rows(client, "/yzw-zxfw-ajfw/api/v1/ajlist", {"pageSize": 100, "ajlb": code, "searchtext": "", "ajzt": "", "sfid": "", "sort": ""}, page_key="pageNum", size_key="pageSize")
                        except Exception as exc:
                            log("warning", f"未能同步{label}案件列表：{exc}")
                            continue
                        case_groups.append((ajlb, rows))
                    layy_items: list[dict[str, Any]] = []
                    # Keep successful categories separate. A successful empty
                    # result is meaningful; a failed request must retain its
                    # local cache until a later successful refresh.
                    layy_snapshot_categories: set[str] = set()
                    # 立案预约官网按审判（sp）/执行（zx）/破产（pc）分类返回，
                    # 且分页上限较小，逐类拉取并合并，避免只同步到第一页。
                    layy_categories = (("sp", "审判"), ("zx", "执行"), ("pc", "破产"))
                    for ajlb, label in layy_categories:
                        try:
                            rows, complete = await paged_rows(client, "/yzw-zxfw-lafw/api/v3/layy", {"limit": 100, "ajlb": ajlb}, page_key="page", size_key="limit", method="GET")
                            # Some court deployments omit ``ajlb`` in a
                            # category-filtered response. Preserve the request
                            # scope with the row so it can still be upserted
                            # and reconciled accurately.
                            layy_items.extend({**row, "_sync_category": ajlb} for row in rows)
                            if complete: layy_snapshot_categories.add(ajlb)
                        except Exception as exc:
                            log("warning", f"未能同步{label}立案预约列表：{exc}")
                    if not layy_items:
                        try:
                            fallback_rows, complete = await paged_rows(client, "/yzw-zxfw-lafw/api/v3/layy", {"limit": 100}, page_key="page", size_key="limit", method="GET")
                            layy_items = fallback_rows
                            # The unfiltered fallback can represent all
                            # categories only when its rows identify their
                            # own category. Otherwise it remains useful for
                            # display/upsert but is not a safe delete snapshot.
                            if complete and all(pick(row, "ajlb") in {"sp", "zx", "pc"} for row in fallback_rows):
                                layy_snapshot_categories.update(("sp", "zx", "pc"))
                            else:
                                log("warning", "未按官网立案预约快照清理：回退列表缺少案件类别")
                        except Exception as exc:
                            log("warning", f"未能同步立案预约列表：{exc}")
                    hearing_items: list[dict[str, Any]] = []
                    try:
                        kqtbaj = await court_json(client, "/yzw-zxfw-ajfw/api/v1/kqtbaj", None, method="GET")
                        hearing_items = result_rows(kqtbaj)
                        if not hearing_items and isinstance(kqtbaj, dict):
                            hearing_items = result_rows(kqtbaj.get("data"))
                    except Exception as exc:
                        log("warning", f"未能同步开庭通知：{exc}")
            except HTTPException as exc:
                if exc.status_code == 401 and config["auto_login_enabled"] and config["credentials_configured"]:
                    launch_login()
                raise
            except (httpx.HTTPError, ValueError) as exc:
                set_error(f"同步失败：{exc}"); log("error", f"同步失败：{exc}"); raise CourtOnlineError("人民法院在线服务暂时无法访问") from exc
            added = 0
            merged_hearings = 0
            merged_layy = 0
            with get_db() as conn:
                for kind, raw in incoming:
                    remote_id = pick(raw, "id", "xxid", "sdbh", "bh", "messageId", "uuid")
                    if not remote_id: remote_id = f"{kind}:{hash(_json(raw))}"
                    remote_id = _scoped_remote_id(account_id, remote_id)
                    content = pick(raw, "content", "xxnr", "xxxq", "nr", "message")
                    title = pick(raw, "title", "xxbt", "wsMc", "wsmc", "ajmc", "name") or pick(raw, "xxlxmc") or ("电子送达" if kind == "delivery" else "法院通知")
                    case_number = human_case_number(raw)
                    linked = _auto_match_case(conn, case_number, pick(raw, "ajmc", "caseName"))
                    previous = conn.execute("SELECT id FROM case_manager_court_online_records WHERE kind=? AND remote_id=? AND account_id=?", (kind, remote_id, account_id)).fetchone()
                    values = (title, content, pick(raw, "createTime", "fbsj", "fbsjS", "sendTime", "sdsj", "fssj"), pick(raw, "_delivery_status", "status", "sdzt"), case_number, pick(raw, "ajmc", "caseName"), pick(raw, "fyMc", "fymc", "fsfy", "fsfymc", "courtName"), pick(raw, "caseSpaceUrl", "ajkjUrl"), _json(raw.get("chatContext") or {}), _json(raw), linked if linked else None, _now())
                    if previous:
                        conn.execute("""UPDATE case_manager_court_online_records SET title=?,content=?,published_at=?,delivery_status=?,case_number=?,case_name=?,court_name=?,case_space_url=?,chat_context_json=?,raw_json=?,linked_case_id=COALESCE(linked_case_id,?),updated_at=? WHERE id=?""", (*values, previous[0]))
                        record_id = int(previous[0])
                    else:
                        conn.execute("""INSERT INTO case_manager_court_online_records(remote_id,kind,title,content,published_at,delivery_status,case_number,case_name,court_name,case_space_url,chat_context_json,raw_json,linked_case_id,stored_at,updated_at,account_id) VALUES(?,?,?, ?,?,?,?,?,?,?,?,?,?,?,?,?)""", (remote_id, kind, *values, _now(), account_id))
                        record_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0]); added += 1
                    attachments = raw.get("attachments") or raw.get("wsList") or raw.get("wslist") or raw.get("files") or []
                    # Keep stable attachment rows (including local download/archive state).
                    # A failed document-list request must not erase the previous snapshot.
                    attachment_ids: list[str] = []
                    for index, attachment in enumerate(attachments if isinstance(attachments, list) else []):
                        if not isinstance(attachment, dict): continue
                        attachment_id = pick(attachment, "id", "bh", "wjbh", "fileId", "c_wsbh", "c_stbh") or str(index)
                        attachment_ids.append(attachment_id)
                        source_url = pick(attachment, "url", "downloadUrl", "previewUrl", "wjlj")
                        conn.execute("""INSERT INTO case_manager_court_online_attachments(record_id,remote_id,filename,extension,source_url) VALUES(?,?,?,?,?) ON CONFLICT(record_id,remote_id) DO UPDATE SET filename=excluded.filename,extension=excluded.extension,source_url=excluded.source_url""", (record_id, attachment_id, _safe_filename(pick(attachment, "name", "wjmc", "filename", "c_wsmc"), f"法院文书-{index+1}"), pick(attachment, "extension", "suffix", "c_wjgs"), source_url))
                    if kind == "delivery" and raw.get("_attachments_loaded"):
                        if attachment_ids:
                            placeholders = ",".join("?" for _ in attachment_ids)
                            conn.execute(f"DELETE FROM case_manager_court_online_attachments WHERE record_id=? AND remote_id NOT IN ({placeholders}) AND COALESCE(staging_path,'')='' AND status='available'", (record_id, *attachment_ids))
                        else:
                            conn.execute("DELETE FROM case_manager_court_online_attachments WHERE record_id=? AND COALESCE(staging_path,'')='' AND status='available'", (record_id,))
                for ajlb, group in case_groups:
                    for raw in group:
                        source_case_id = pick(raw, "cbh", "cajbh", "id")
                        if not source_case_id:
                            continue
                        remote_id = _scoped_remote_id(account_id, f"{ajlb}:{source_case_id}")
                        case_number = pick(raw, "cah")
                        linked = _auto_match_case(conn, case_number, pick(raw, "cajmc"))
                        conn.execute("""INSERT INTO case_manager_court_online_cases(remote_id,ajlb,case_number,case_name,cause,business_type,court_name,judge,department,stage,adjudication,status,parties,filing_date,judgment_date,update_date,raw_json,linked_case_id,first_seen,updated_at,account_id)
                            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                            ON CONFLICT(remote_id) DO UPDATE SET ajlb=excluded.ajlb,case_number=excluded.case_number,case_name=excluded.case_name,cause=excluded.cause,business_type=excluded.business_type,court_name=excluded.court_name,judge=excluded.judge,department=excluded.department,stage=excluded.stage,adjudication=excluded.adjudication,status=excluded.status,parties=excluded.parties,filing_date=excluded.filing_date,judgment_date=excluded.judgment_date,update_date=excluded.update_date,raw_json=excluded.raw_json,linked_case_id=COALESCE(linked_case_id,excluded.linked_case_id),updated_at=excluded.updated_at""",
                            (remote_id, ajlb, case_number, pick(raw, "cajmc"), pick(raw, "claay"), pick(raw, "cywlxTranslateText"), pick(raw, "cysfyTranslateText"), pick(raw, "ccbrTranslateText"), pick(raw, "ccbsptTranslateText"), pick(raw, "cajjzjdTranslateText"), pick(raw, "cjafsTranslateText"), int(pick(raw, "najzt") or 0), pick(raw, "ccyr"), pick(raw, "dlarq"), pick(raw, "djarq"), pick(raw, "dzhgxsj"), _json(raw), linked or None, _now(), _now(), account_id))
                        if hearing_at_raw := pick(raw, "dktsj", "ktsj"):
                            upsert_court_hearing(
                                conn, f"case:{ajlb}:{source_case_id}", f"case_{ajlb}", raw,
                                case_number=case_number, case_name=pick(raw, "cajmc"),
                                court_name=pick(raw, "cysfyTranslateText", "cfydmTranslateText"),
                                judge=pick(raw, "ccbrTranslateText"),
                                status=pick(raw, "cajjzjdTranslateText", "najzt"),
                                hearing_at=hearing_at_raw, account_id=account_id,
                            )
                layy_detail_targets: list[tuple[int, str]] = []
                removed_layy = 0
                layy_remote_ids_by_category: dict[str, set[str]] = {
                    category: set() for category in layy_snapshot_categories
                }
                for raw in layy_items:
                    source_remote_id = pick(raw, "id")
                    if not source_remote_id:
                        continue
                    remote_id = _scoped_remote_id(account_id, source_remote_id)
                    # 官网对已删除的立案预约返回 isDel=1（软删除），此时不应保留本地记录。
                    if str(pick(raw, "isDel")).lower() in ("1", "true", "yes"):
                        stale = conn.execute("SELECT id FROM case_manager_court_online_layy WHERE remote_id=?", (remote_id,)).fetchone()
                        if stale:
                            conn.execute("DELETE FROM case_manager_court_online_layy_audits WHERE layy_id=?", (stale[0],))
                            conn.execute("DELETE FROM case_manager_court_online_layy WHERE id=?", (stale[0],))
                            removed_layy += 1
                        continue
                    raw_category = pick(raw, "_sync_category", "ajlb")
                    category = raw_category if raw_category in {"sp", "zx", "pc"} else ""
                    # A category-scoped endpoint should identify each row's
                    # category. If it does not, preserve the cached row until
                    # a later response can establish that identity.
                    if category:
                        layy_remote_ids_by_category.setdefault(category, set()).add(remote_id)
                    linked = _auto_match_case(conn, "", pick(raw, "ajmc"))
                    layy_status = pick(raw, "zt") or pick(raw, "ztmc", "ztText", "ztName", "ztTranslateText")
                    applicant = pick(raw, "sqrmc", "dsrMc")
                    cause = pick(raw, "laay")
                    cause_code = pick(raw, "laayMz")
                    material_count = pick(raw, "bcclCs")
                    previous = conn.execute("SELECT id, COALESCE(NULLIF(update_date,''),''), COALESCE(NULLIF(detail_json,''),'{}') FROM case_manager_court_online_layy WHERE remote_id=?", (remote_id,)).fetchone()
                    conn.execute("""INSERT INTO case_manager_court_online_layy(remote_id,court_name,case_type,parties,case_name,status,cause,category,review_comment,filed_date,update_date,applicant,submit_time,withdraw_time,material_count,material_time,cause_code,filing_method,raw_json,linked_case_id,first_seen,updated_at,account_id)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(remote_id) DO UPDATE SET court_name=COALESCE(NULLIF(excluded.court_name,''),court_name),case_type=COALESCE(NULLIF(excluded.case_type,''),case_type),parties=COALESCE(NULLIF(excluded.parties,''),parties),case_name=COALESCE(NULLIF(excluded.case_name,''),case_name),status=COALESCE(NULLIF(excluded.status,''),status),cause=COALESCE(NULLIF(excluded.cause,''),cause),category=COALESCE(NULLIF(excluded.category,''),category),review_comment=COALESCE(NULLIF(excluded.review_comment,''),review_comment),filed_date=COALESCE(NULLIF(excluded.filed_date,''),filed_date),update_date=COALESCE(NULLIF(excluded.update_date,''),update_date),applicant=COALESCE(NULLIF(excluded.applicant,''),applicant),submit_time=COALESCE(NULLIF(excluded.submit_time,''),submit_time),withdraw_time=COALESCE(NULLIF(excluded.withdraw_time,''),withdraw_time),material_count=excluded.material_count,material_time=COALESCE(NULLIF(excluded.material_time,''),material_time),cause_code=COALESCE(NULLIF(excluded.cause_code,''),cause_code),filing_method=COALESCE(NULLIF(excluded.filing_method,''),filing_method),raw_json=excluded.raw_json,linked_case_id=COALESCE(linked_case_id,excluded.linked_case_id),updated_at=excluded.updated_at""",
                        (remote_id, pick(raw, "fymc"), pick(raw, "cajlx"), pick(raw, "dsrMc"), pick(raw, "ajmc"), layy_status, cause, raw_category, pick(raw, "shyj"), pick(raw, "createTime"), pick(raw, "updateTime"), applicant, pick(raw, "tjsj"), pick(raw, "chsj"), int(material_count or 0) if str(material_count or "").isdigit() else 0, pick(raw, "bcclSj"), cause_code, pick(raw, "lafs"), _json(raw), linked or None, _now(), _now(), account_id))
                    current = conn.execute("SELECT id FROM case_manager_court_online_layy WHERE remote_id=?", (remote_id,)).fetchone()
                    row_id = int(current[0])
                    # 仅当官网更新时间变化或本地尚无详情时才拉取详情与审核记录，
                    # 避免每次同步都对官网发起大量详情请求。
                    changed = not previous or previous[1] != pick(raw, "updateTime") or previous[2] in ("", "{}", None)
                    if changed:
                        layy_detail_targets.append((row_id, source_remote_id))
                # 清理本账号遗留的官网已删除立案预约（isDel=1）。这些记录可能因
                # 已不在官网列表中而不再被本轮遍历到，但仍残留在本地列表里。
                for stale_layy in conn.execute(
                    "SELECT id FROM case_manager_court_online_layy WHERE account_id=? AND CAST(COALESCE(json_extract(raw_json,'$.isDel'),0) AS TEXT)='1'",
                    (account_id,),
                ).fetchall():
                    conn.execute("DELETE FROM case_manager_court_online_layy_audits WHERE layy_id=?", (stale_layy[0],))
                    conn.execute("DELETE FROM case_manager_court_online_layy WHERE id=?", (stale_layy[0],))
                    removed_layy += 1
                # Mirror every successfully refreshed category, including
                # appointments the official list omits without an ``isDel``
                # tombstone.
                removed_layy += _reconcile_layy_snapshot(
                    conn, account_id, layy_remote_ids_by_category,
                )
                for raw in hearing_items:
                    remote_id = pick(raw, "id", "cbh", "cajbh", "ahdm", "uuid") or f"kqtbaj:{hash(_json(raw))}"
                    upsert_court_hearing(
                        conn, f"kqtbaj:{remote_id}", "kqtbaj", raw,
                        case_number=human_case_number(raw) or pick(raw, "ah", "cah", "caseNo", "case_number"),
                        case_name=pick(raw, "ajmc", "caseName", "cajmc", "name"),
                        court_name=pick(raw, "fymc", "fyMc", "courtName", "cysfyTranslateText"),
                        hearing_type=pick(raw, "ktsx", "kclx", "ktlx", "cajlbTranslateText"),
                        judge=pick(raw, "ccbr", "cbr", "judge"),
                        status=pick(raw, "status", "ktzt"),
                        location=pick(raw, "ktsd", "ktdd", "address", "location"),
                        hearing_at=pick(raw, "ktsj", "dktsj", "ktSj", "hearingAt", "hearingTime"), account_id=account_id,
                    )
                cutoff = (dt.datetime.now().astimezone() - dt.timedelta(days=RETENTION_DAYS)).isoformat(timespec="seconds")
                conn.execute("DELETE FROM case_manager_court_online_records WHERE account_id=? AND stored_at<?", (account_id, cutoff))
                # 差分删除：官网本次返回列表（按类别）中已不存在的近期记录一并
                # 移除，避免官网已删除的通知一直滞留在本地列表。仅当本次返回
                # 非空时执行，且只清理 30 天窗口内的记录，防止官网分页截断
                # 导致误删较早的历史记录。cases/layy/hearings 不做差分删除：
                # 官网按分页或状态返回，不返回不等于已删除。
                removed = 0
                for kind in ("todo", "message", "delivery"):
                    seen = [
                        _scoped_remote_id(account_id, pick(raw, "id", "xxid", "sdbh", "bh", "messageId", "uuid") or f"{kind}:{hash(_json(raw))}")
                        for item_kind, raw in incoming if item_kind == kind
                    ]
                    if not seen or kind not in complete_record_snapshots:
                        continue
                    placeholders = ",".join("?" for _ in seen)
                    recent = (dt.datetime.now().astimezone() - dt.timedelta(days=30)).isoformat(timespec="seconds")
                    stale = conn.execute(
                        f"""SELECT id FROM case_manager_court_online_records
                            WHERE account_id=? AND kind=? AND remote_id NOT IN ({placeholders})
                              AND COALESCE(NULLIF(published_at, ''), stored_at) >= ?""",
                        (account_id, kind, *seen, recent),
                    ).fetchall()
                    if stale:
                        for stale_row in stale:
                            conn.execute("DELETE FROM case_manager_court_online_attachments WHERE record_id=?", (stale_row["id"],))
                        conn.execute(
                            f"""DELETE FROM case_manager_court_online_records
                                WHERE account_id=? AND kind=? AND remote_id NOT IN ({placeholders})
                                  AND COALESCE(NULLIF(published_at, ''), stored_at) >= ?""",
                            (account_id, kind, *seen, recent),
                        )
                        removed += len(stale)
                # 同一官网开庭记录可能同时来自“我的案件”与历史回填；无论
                # 切换账号多少次，都以账号内的案号、时间、法院作为最终业务键。
                # 在提交同步事务前合并，前端永远不会读到中间重复状态。
                merged_hearings = _merge_duplicate_court_hearings(conn)
                conn.execute("UPDATE case_manager_court_online_settings SET last_sync_at=?,last_error='',updated_at=? WHERE id=1", (_now(), _now()))
                conn.commit()
            if merged_hearings:
                log("info", f"同步时合并 {merged_hearings} 条重复开庭记录")
            # 立案预约详情与审核记录：列表接口不返回审核时间/审核人/承办人等，
            # 对本次有变化的记录调用官网详情接口补齐（事务外发起网络请求）。
            if layy_detail_targets:
                scheduler["sync_stage"] = f"正在补齐 {len(layy_detail_targets)} 条立案预约详情"
                # 主同步用的 AsyncClient 已在上方列表请求完成后关闭；此处必须使用
                # 新客户端，否则详情请求会因 "client has been closed" 全部失败。
                detail_rows: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
                async with httpx.AsyncClient(timeout=25, headers=headers, follow_redirects=False) as detail_client:
                    detail_limit = asyncio.Semaphore(4)
                    async def load_layy_detail(row_id: int, remote_id: str) -> tuple[int, dict[str, Any], dict[str, Any]] | None:
                        detail: dict[str, Any] = {}
                        basic: dict[str, Any] = {}
                        async with detail_limit:
                            try:
                                response = await court_json(detail_client, f"/yzw-zxfw-lafw/api/v3/layy/layyxq/{remote_id}/0", None, method="GET")
                                if isinstance(response, dict):
                                    detail = response
                            except Exception as exc:
                                log("warning", f"未能读取立案预约审核详情 {remote_id}：{exc}")
                            # 列表缺少案件名称或案由时再补读基础信息。
                            detail_layy = detail.get("layy") if isinstance(detail.get("layy"), dict) else detail
                            if not pick(detail_layy, "ajmc", "cajmc", "caseName", "laay"):
                                try:
                                    response = await court_json(detail_client, f"/yzw-zxfw-lafw/api/v3/layy/jbxx/{remote_id}", None, method="GET")
                                    if isinstance(response, dict):
                                        basic = response
                                except Exception as exc:
                                    log("warning", f"未能读取立案预约基础信息 {remote_id}：{exc}")
                        return (row_id, detail, basic) if detail or basic else None
                    detail_rows = [row for row in await asyncio.gather(*(load_layy_detail(row_id, remote_id) for row_id, remote_id in layy_detail_targets)) if row]
                if detail_rows:
                    stamp = _now()
                    with get_db() as conn:
                        for row_id, detail, basic in detail_rows:
                            detail_layy = detail.get("layy") if isinstance(detail.get("layy"), dict) else detail
                            basic_layy = basic.get("layy") if isinstance(basic.get("layy"), dict) else basic

                            def detail_pick(*keys: str) -> str:
                                return pick(basic_layy, *keys) or pick(detail_layy, *keys)

                            conn.execute("""UPDATE case_manager_court_online_layy SET
                                court_name=COALESCE(NULLIF(?,''),court_name), case_type=COALESCE(NULLIF(?,''),case_type),
                                parties=COALESCE(NULLIF(?,''),parties), case_name=COALESCE(NULLIF(?,''),case_name),
                                status=COALESCE(NULLIF(?,''),status), cause=COALESCE(NULLIF(?,''),cause),
                                review_comment=COALESCE(NULLIF(?,''),review_comment), applicant=COALESCE(NULLIF(?,''),applicant),
                                apply_time=COALESCE(NULLIF(?,''),apply_time), submit_time=COALESCE(NULLIF(?,''),submit_time),
                                judge=COALESCE(NULLIF(?,''),judge), filing_method=COALESCE(NULLIF(?,''),filing_method),
                                claim_amount=COALESCE(NULLIF(?,''),claim_amount), lawsuit_request=COALESCE(NULLIF(?,''),lawsuit_request),
                                case_number=COALESCE(NULLIF(?,''),case_number), cause_code=COALESCE(NULLIF(?,''),cause_code),
                                material_count=CASE WHEN ? > 0 THEN ? ELSE material_count END,
                                material_time=COALESCE(NULLIF(?,''),material_time), withdraw_time=COALESCE(NULLIF(?,''),withdraw_time),
                                detail_json=?, updated_at=?
                                WHERE id=?""",
                                (detail_pick("fymc", "fyMc", "courtName"), detail_pick("cajlx", "ajlx", "caseType"),
                                 detail_pick("dsrMc", "sqrmc", "parties"), detail_pick("ajmc", "cajmc", "caseName", "name"),
                                 detail_pick("zt", "ztmc", "ztText", "ztName", "ztTranslateText"), detail_pick("laay", "cause"),
                                 detail_pick("shyj", "reviewComment"), detail_pick("sqrmc", "dsrMc"), detail_pick("createTime"),
                                 detail_pick("tjsj"), detail_pick("cbrmc"), detail_pick("lafs"), detail_pick("sqbdje"),
                                 detail_pick("ssqq"), detail_pick("ah", "caseNumber"), detail_pick("laayMz"),
                                 int(detail_pick("bcclCs") or 0) if detail_pick("bcclCs").isdigit() else 0,
                                 int(detail_pick("bcclCs") or 0) if detail_pick("bcclCs").isdigit() else 0,
                                 detail_pick("bcclSj"), detail_pick("chsj"), _json({"layyxq": detail, "jbxx": basic}), stamp, row_id))
                            for audit in detail.get("shjgs") or []:
                                if not isinstance(audit, dict):
                                    continue
                                audit_id = pick(audit, "id") or f"{pick(audit, 'shsj')}:{pick(audit, 'shrxm')}"
                                conn.execute("""INSERT INTO case_manager_court_online_layy_audits(layy_id,remote_id,shjg,shjg_text,review_comment,review_time,reviewer,reviewer_id,remark_term,reject_reason,raw_json,created_at)
                                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                                    ON CONFLICT(layy_id,remote_id) DO UPDATE SET shjg=excluded.shjg,shjg_text=excluded.shjg_text,review_comment=excluded.review_comment,review_time=excluded.review_time,reviewer=excluded.reviewer,reviewer_id=excluded.reviewer_id,remark_term=excluded.remark_term,reject_reason=excluded.reject_reason,raw_json=excluded.raw_json,created_at=excluded.created_at""",
                                    (row_id, audit_id, pick(audit, "shjg"), pick(audit, "cshjg"), pick(audit, "shyj"), pick(audit, "shsj"), pick(audit, "shrxm"), pick(audit, "shrid"), pick(audit, "bzqx"), pick(audit, "bhyy"), _json(audit), stamp))
                        conn.commit()
                    log("info", f"已同步 {len(detail_rows)} 条立案预约详情与审核记录")
            # 官网偶尔会用不同内部编号返回完全相同的预约；详情补齐后再合并，
            # 可同时保留完整的审核记录并保证列表/计数不重复。
            with get_db() as conn:
                merged_layy = _merge_duplicate_court_layy(conn)
                conn.commit()
            if merged_layy:
                log("info", f"同步时合并 {merged_layy} 条重复立案预约")
            if removed_layy:
                log("info", f"同步时移除 {removed_layy} 条官网已删除的立案预约")
            # 预立案工作台只消费本轮已落库的“我的立案”结果；不向官网写入任何数据。
            try:
                from .filing_workspace import reconcile_filing_drafts
                reconciled = reconcile_filing_drafts(get_db)
                if reconciled:
                    log("info", f"已回写 {reconciled} 条预立案草稿状态")
            except Exception as exc:
                log("warning", f"预立案状态回写失败：{exc}")
            if added: log("info", f"同步完成，发现 {added} 条新法院在线服务记录")
            if removed: log("info", f"同步完成，移除 {removed} 条官网已删除的法院在线服务记录")
            return {"ok": True, "added": added, "removed": removed, "count": len(incoming)}

    def record_dict(row: Any, conn: Any) -> dict[str, Any]:
        item = dict(row)
        item["unread"] = bool(item["unread"])
        item["attachments"] = [dict(entry) for entry in conn.execute("SELECT * FROM case_manager_court_online_attachments WHERE record_id=? ORDER BY id", (item["id"],)).fetchall()]
        try: raw = json.loads(item.get("raw_json") or "{}")
        except json.JSONDecodeError: raw = {}
        item["chat_available"] = bool(isinstance(raw, dict) and any(raw.get(key) not in (None, "") for key in ("fyId", "ajbh", "ahdm", "caseId")))
        return item

    @app.get("/api/case-manager/court-online/status")
    def court_status():
        account_id = _active_account_id()
        with get_db() as conn:
            pending = conn.execute("SELECT COUNT(*) FROM case_manager_court_online_records WHERE account_id=? AND (unread=1 OR (kind='delivery' AND delivery_status='1'))", (account_id,)).fetchone()[0]
            record_counts = {
                row["kind"]: int(row["n"])
                for row in conn.execute("SELECT kind, COUNT(*) AS n FROM case_manager_court_online_records WHERE account_id=? GROUP BY kind", (account_id,)).fetchall()
            }
            case_count = int(conn.execute("SELECT COUNT(*) FROM case_manager_court_online_cases WHERE account_id=?", (account_id,)).fetchone()[0])
            trial_count = int(conn.execute("SELECT COUNT(*) FROM case_manager_court_online_cases WHERE account_id=? AND ajlb='sp'", (account_id,)).fetchone()[0])
            execute_count = int(conn.execute("SELECT COUNT(*) FROM case_manager_court_online_cases WHERE account_id=? AND ajlb='zx'", (account_id,)).fetchone()[0])
            bankruptcy_count = int(conn.execute("SELECT COUNT(*) FROM case_manager_court_online_cases WHERE account_id=? AND ajlb='pc'", (account_id,)).fetchone()[0])
            layy_count = int(conn.execute("SELECT COUNT(*) FROM case_manager_court_online_layy WHERE account_id=? AND CAST(COALESCE(json_extract(raw_json,'$.isDel'),0) AS TEXT)<>'1'", (account_id,)).fetchone()[0])
            layy_trial = int(conn.execute("SELECT COUNT(*) FROM case_manager_court_online_layy WHERE account_id=? AND category='sp' AND CAST(COALESCE(json_extract(raw_json,'$.isDel'),0) AS TEXT)<>'1'", (account_id,)).fetchone()[0])
            layy_execute = int(conn.execute("SELECT COUNT(*) FROM case_manager_court_online_layy WHERE account_id=? AND category='zx' AND CAST(COALESCE(json_extract(raw_json,'$.isDel'),0) AS TEXT)<>'1'", (account_id,)).fetchone()[0])
            layy_bankruptcy = int(conn.execute("SELECT COUNT(*) FROM case_manager_court_online_layy WHERE account_id=? AND category='pc' AND CAST(COALESCE(json_extract(raw_json,'$.isDel'),0) AS TEXT)<>'1'", (account_id,)).fetchone()[0])
            hearing_count = int(conn.execute("SELECT COUNT(*) FROM case_manager_court_online_hearings WHERE account_id=?", (account_id,)).fetchone()[0])
        return {**settings(), "unread_count": int(pending),
                "record_count": sum(record_counts.values()),
                "todo_count": record_counts.get("todo", 0),
                "message_count": record_counts.get("message", 0),
                "delivery_count": record_counts.get("delivery", 0),
                "case_count": case_count, "case_trial_count": trial_count,
                "execute_case_count": execute_count, "bankruptcy_case_count": bankruptcy_count,
                "layy_count": layy_count, "layy_trial_count": layy_trial,
                "layy_execute_count": layy_execute, "layy_bankruptcy_count": layy_bankruptcy,
                "hearing_count": hearing_count}

    @app.get("/api/case-manager/court-online/settings")
    def get_settings(): return settings()

    @app.put("/api/case-manager/court-online/settings")
    def put_settings(body: Dict[str, Any]): return save_settings(body)

    async def close_active_browser_session() -> None:
        connected = bool(scheduler.get("browser_connected"))
        context = scheduler.get("browser_context")
        playwright = scheduler.get("playwright")
        scheduler.update({"browser_context": None, "browser_page": None, "playwright": None, "probe_attached": set(),
                          "browser_on_screen": False, "browser_connected": False, "browser_cdp_port": ""})
        if context:
            try: await context.close()
            except Exception: pass
        if playwright:
            try: await playwright.stop()
            except Exception: pass
        if connected:
            # `open -g` 启动的 Chrome 进程独立于 Playwright，需按档案目录定向退出。
            await _terminate_background_browser(connected)

    async def prepare_browser_runtime_cache_cleanup() -> None:
        """Stop the controlled browser before its regenerable caches are removed.

        The storage endpoint lives in ``main.py`` while the browser scheduler
        owns the persistent Playwright/CDP session. Expose a narrow app-state
        hook instead of coupling the storage module to scheduler internals.
        Login data is stored in the profile and is not removed by this step.
        """
        async with scheduler["sync_lock"]:
            login_task = scheduler.get("login_task")
            if login_task and not login_task.done():
                login_task.cancel()
                await asyncio.gather(login_task, return_exceptions=True)
                scheduler["login_task"] = None
            await close_active_browser_session()

    # Storage management uses this hook before deleting cache directories.
    # Keeping it on app.state avoids a reverse import from the browser service
    # into the large main module and keeps the hook optional for isolated tests.
    app_state = getattr(app, "state", None)
    if app_state is not None:
        app_state.prepare_court_browser_runtime_cache_cleanup = prepare_browser_runtime_cache_cleanup

    @app.post("/api/case-manager/court-online/accounts/switch")
    async def switch_account(body: Dict[str, Any]):
        target = str(body.get("account_id") or "")
        store = _read_secret_store()
        if target not in (store.get("accounts") or {}):
            raise HTTPException(status_code=404, detail="法院账号不存在")
        if scheduler["sync_lock"].locked() or (scheduler.get("login_task") and not scheduler["login_task"].done()):
            raise HTTPException(status_code=409, detail="当前账号正在登录或同步，请稍后再切换")
        if target != str(store.get("active_account_id") or "legacy"):
            await close_active_browser_session()
            store["active_account_id"] = target
            _write_secret_store(store)
            log("info", f"已切换法院账号：{_redact_account(str(store['accounts'][target].get('account') or ''))}")
        return {"ok": True, **settings()}

    @app.post("/api/case-manager/court-online/download-directory/select")
    def select_download_directory():
        if shutil.which("osascript") is None:
            raise HTTPException(status_code=501, detail="当前系统不支持系统文件夹选择器")
        result = subprocess.run(["osascript", "-e", 'POSIX path of (choose folder with prompt "选择法院文书下载目录")'], text=True, capture_output=True, timeout=120)
        if result.returncode != 0:
            if "-128" in result.stderr:
                return {"ok": False, "cancelled": True}
            raise HTTPException(status_code=500, detail=result.stderr.strip() or "选择文件夹失败")
        path = Path(result.stdout.strip().rstrip("/"))
        if not path.is_absolute() or not path.is_dir():
            raise HTTPException(status_code=400, detail="所选下载目录不可用")
        with get_db() as conn:
            conn.execute("UPDATE case_manager_court_online_settings SET download_directory=?,updated_at=? WHERE id=1", (str(path), _now()))
            conn.commit()
        return {"ok": True, "download_directory": str(path)}

    @app.post("/api/case-manager/court-online/download-directory/open")
    def open_download_directory():
        path = download_directory()
        try:
            subprocess.run(["open", str(path)], check=True, timeout=10)
        except (OSError, subprocess.SubprocessError) as exc:
            raise HTTPException(status_code=500, detail=f"无法打开本地文件夹：{exc}")
        return {"ok": True, "download_directory": str(path)}

    @app.delete("/api/case-manager/court-online/credentials")
    def delete_credentials():
        store = _read_secret_store()
        active = str(store.get("active_account_id") or "legacy")
        accounts = store.get("accounts") or {}
        accounts.pop(active, None)
        if accounts:
            store["accounts"] = accounts
            store["active_account_id"] = next(iter(accounts))
            _write_secret_store(store)
        else:
            _delete_secret()
        shutil.rmtree(active_profile, ignore_errors=True)
        log("info", "已清除当前法院账号的凭据和会话")
        return {"ok": True}

    @app.post("/api/case-manager/court-online/login")
    async def login():
        # A prior manual login can leave Chrome frontmost. Hide it and activate
        # APEX in this request so minimizing Chrome cannot leave an empty desk.
        context = scheduler.get("browser_context")
        if context:
            await _hide_controlled_browser_windows(context)
        launch_login(force=True, keep_apex_front=True)
        await _activate_apex_async()
        return {"ok": True, "message": "正在页面浮窗中自动登录官网，不会弹出其他窗口"}

    @app.post("/api/case-manager/court-online/logout")
    async def logout():
        """退出当前法院账号的登录会话。

        只结束会话并关闭受控浏览器，不清除已保存的账号密码、
        文书目录和已同步数据；重新点击登录即可自动登录回来。
        """
        secret = _read_secret()
        had_token = secret.get("session_token", "")
        secret["session_token"] = ""
        _write_secret(secret)
        await close_active_browser_session()
        with get_db() as conn:
            conn.execute("UPDATE case_manager_court_online_settings SET session_logged_in_at='',last_error='',updated_at=? WHERE id=1", (_now(),))
            conn.commit()
        log("info", "已退出法院官网登录会话" + ("（原会话有效）" if had_token else ""))
        return {"ok": True, **settings()}

    @app.post("/api/case-manager/court-online/browser/reveal")
    async def browser_reveal():
        """把受控官网窗口唤回屏幕，供人工登录或查看已登录工作台。

        该接口只移动本应用自己启动的受控浏览器窗口，不操作任何
        其他进程的窗口，也不触碰任何法院页面内容。
        """
        page = scheduler.get("browser_page")
        if not page or page.is_closed():
            if not settings()["session_active"]:
                raise HTTPException(status_code=409, detail="一张网浏览器未打开，请先重新发起登录")
            try:
                await start_login(existing_session_only=True)
            except Exception as exc:
                log("warning", f"恢复一张网专用浏览器失败：{exc}")
                raise HTTPException(status_code=409, detail="一张网会话未能恢复，请重新登录") from exc
            page = scheduler.get("browser_page")
            if not page or page.is_closed():
                raise HTTPException(status_code=409, detail="一张网浏览器未能恢复，请重新登录")
        moved = await _set_browser_window_visibility(page, on_screen=True)
        if moved:
            try:
                await page.bring_to_front()
            except Exception:
                pass
            if settings()["session_active"]:
                try:
                    await page.goto(f"{COURT_ORIGIN}/zxfw/#/pagesGrxx", wait_until="domcontentloaded", timeout=30000)
                except Exception as exc:
                    log("warning", f"打开法院官网工作台失败，已保留可见窗口：{exc}")
            try:
                await page.bring_to_front()
            except Exception:
                pass
            frontmost = await asyncio.get_running_loop().run_in_executor(
                None, _browser_profile_is_frontmost, _profile_dir_for_active_account(), _browser_executable()
            )
            if frontmost:
                log("info", "已在前台打开一张网专用 Chrome 窗口")
            else:
                log("warning", "一张网窗口已恢复，但专用 Chrome 未进入前台")
            return {"ok": frontmost}
        return {"ok": False}

    @app.post("/api/case-manager/court-online/browser/hide")
    async def browser_hide():
        """把受控官网窗口重新最小化（登录完成后由浮窗自动调用）。"""
        context = scheduler.get("browser_context")
        page = scheduler.get("browser_page")
        if not context or not page or page.is_closed():
            return {"ok": False}
        await _hide_controlled_browser_windows(context)
        await _activate_apex_async()
        return {"ok": True}

    @app.get("/api/case-manager/court-online/browser/frame")
    async def browser_frame(request: Request):
        """返回当前受控官网页面的画面，供页内浮窗与自动化立案实时展示。

        支持 ?clip=root：只裁剪页面主内容区（uni-app 根节点/#app），
        去掉整屏截图四周的空白，浮窗里显示更紧凑。
        """
        page = scheduler.get("browser_page")
        if not page or page.is_closed():
            raise HTTPException(status_code=409, detail="一张网浏览器未打开，请先在一张网完成登录")
        clip_root = str(request.query_params.get("clip") or "") == "root"
        try:
            image = None
            if clip_root:
                locator = page.locator("uni-app, #app").first
                try:
                    image = await locator.screenshot(type="png", timeout=6000)
                except Exception:
                    image = None
            if image is None:
                image = await page.screenshot(type="png")
            image = _trim_uniform_border(image)
            return Response(content=image, media_type="image/png", headers={"Cache-Control": "no-store"})
        except Exception as exc:
            raise HTTPException(status_code=502, detail="无法读取官网实时画面") from exc

    @app.post("/api/case-manager/court-online/browser/open-filing")
    async def open_filing_browser():
        """通过官网可见导航打开在线立案入口，不填写、不上传、不提交任何法院侧数据。"""
        page = scheduler.get("browser_page")
        if not page or page.is_closed():
            launch_login(force=True)
            raise HTTPException(status_code=409, detail="一张网浏览器未打开，已在浮窗中自动启动登录；登录完成后请重试")
        try:
            await page.goto(f"{COURT_ORIGIN}/zxfw/#/pagesGrxx", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(1200)
            entry = page.get_by_text("在线立案", exact=True).first
            await entry.click(timeout=10000)
            await page.wait_for_timeout(1200)
            return {"ok": True, "message": "已打开官网在线立案入口"}
        except Exception as exc:
            raise HTTPException(status_code=502, detail="无法打开官网在线立案入口") from exc

    @app.post("/api/case-manager/court-online/browser/show-filing-stage")
    async def show_filing_stage(request: Request):
        """Navigate the visible Court Online Service page for the current API stage.

        This route is deliberately visual-only.  It never fills a field,
        uploads a file, creates a draft, or submits anything.  The Token API
        remains the sole writer; the browser merely gives the lawyer a stable
        view of the corresponding official surface.
        """
        body = await request.json()
        stage = str(body.get("stage") or "api_create_draft")
        draft_id = str(body.get("draft_id") or "").strip()
        court_id = str(body.get("court_id") or "").strip()
        case_type = str(body.get("case_type") or "1501_000001-0301").strip()
        page = scheduler.get("browser_page")
        if not page or page.is_closed():
            raise HTTPException(status_code=409, detail="一张网浏览器未打开，请先在一张网完成登录")
        try:
            if stage == "api_create_draft" or not draft_id:
                await page.goto(f"{COURT_ORIGIN}/zxfw/#/pagesWsla/pc/zxla/pick-case-type/index", wait_until="domcontentloaded", timeout=30000)
                label = "官网“选择案件类型”页面"
            else:
                # The official pages read their current draft from this
                # browser-tab session.  Seed only that local page context,
                # then open the existing API-created draft in read-only
                # visual mode.  No official field is filled or saved here.
                await page.goto(f"{COURT_ORIGIN}/zxfw/#/pagesGrxx", wait_until="domcontentloaded", timeout=30000)
                page_context = {"id": draft_id, "fyid": court_id, "ajlx": case_type, "lafs": "1"}
                # The uni-app router continues hydrating briefly after
                # ``goto``. Retry the local storage hand-off if that router
                # replaces the execution context during the first attempt.
                for attempt in range(3):
                    try:
                        await page.evaluate("""param => sessionStorage.setItem('layyParam', JSON.stringify(param))""", page_context)
                        break
                    except Exception:
                        if attempt == 2:
                            raise
                        await page.wait_for_timeout(500)
                # Every non-create step is shown on the read-only draft-detail
                # page.  The wizard's upload component
                # (/pagesWsla/common/wsla/components/file-upload/index) loads
                # the draft into the court wizard, which materialises an extra
                # “非法人组织” placeholder party card per role; the detail page
                # renders the same stored case, parties, agent and attachments
                # without performing any court-side write, so it reintroduces
                # none of those duplicate cards.
                target = "/pagesWsla/common/wsla/detail/index"
                query = f"fyid={urllib.parse.quote(court_id)}&layyid={urllib.parse.quote(draft_id)}&ajlx={urllib.parse.quote(case_type)}"
                label = "官网“案件空间”草稿详情页面"
                await page.goto(f"{COURT_ORIGIN}/zxfw/#{target}?{query}", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(650)
            anchor = {
                "api_basic_info": "基本信息",
                "api_parties": "原告信息",
                "api_agent": "代理人信息",
                "api_materials": "材料信息",
                "api_service_address": "送达地址确认书",
            }.get(stage)
            if anchor:
                try:
                    target_text = page.get_by_text(anchor, exact=stage != "api_service_address").first
                    if await target_text.count():
                        await target_text.scroll_into_view_if_needed(timeout=4000)
                except Exception:
                    # Some courts omit the delivery-address row from the
                    # visible template. The real page remains useful even
                    # when that optional visual anchor is absent.
                    pass
            return {"ok": True, "stage": stage, "label": label, "url": str(page.url)}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"无法切换官网实时展示页面：{str(exc)[:180]}") from exc

    @app.post("/api/case-manager/court-online/browser/refresh-filing-materials")
    async def refresh_filing_materials(request: Request):
        """Refresh the visible read-only draft-detail page after one upload.

        This endpoint performs no upload or form write.  It only reloads the
        currently visible official draft-detail page when it is already the
        same draft, so the APEX canvas can show each newly registered
        attachment as the court site renders it.  It never opens the court
        wizard, which would materialise an extra placeholder party card.
        """
        body = await request.json()
        draft_id = str(body.get("draft_id") or "").strip()
        page = scheduler.get("browser_page")
        if not page or page.is_closed():
            raise HTTPException(status_code=409, detail="一张网浏览器未打开")
        current_url = str(page.url)
        if not draft_id or "detail/index" not in current_url or draft_id not in current_url:
            raise HTTPException(status_code=409, detail="官网实时画面当前不是本草稿的只读详情页")
        try:
            # The registration API can take a short moment to become visible
            # to the official page's material-list query.
            await page.wait_for_timeout(320)
            await page.reload(wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(850)
            return {"ok": True, "draft_id": draft_id, "url": str(page.url)}
        except Exception as exc:
            raise HTTPException(status_code=502, detail="无法刷新官网材料页面") from exc

    @app.get("/api/case-manager/court-online/browser/visible-controls")
    async def browser_visible_controls():
        """只读取当前官网可见控件，供立案适配器建立字段映射。"""
        page = scheduler.get("browser_page")
        if not page or page.is_closed():
            raise HTTPException(status_code=409, detail="一张网浏览器未打开")
        try:
            controls = await page.evaluate("""() => Array.from(document.querySelectorAll('button,input,textarea,select,[role="button"],uni-view'))
              .filter(el => { const style = getComputedStyle(el); const rect = el.getBoundingClientRect(); return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0; })
              .map(el => ({tag:el.tagName.toLowerCase(), text:(el.innerText || el.getAttribute('aria-label') || el.getAttribute('placeholder') || '').trim().slice(0,120), type:el.getAttribute('type') || '', name:el.getAttribute('name') || '', placeholder:el.getAttribute('placeholder') || '', cls:(el.className || '').toString().slice(0,160)}))
              .filter(item => item.text || item.name || item.placeholder).slice(0,250)""")
            return {"url": str(page.url), "controls": controls}
        except Exception as exc:
            raise HTTPException(status_code=502, detail="无法读取官网页面结构") from exc

    @app.post("/api/case-manager/court-online/browser/filing-step/civil-first-instance")
    async def map_civil_first_instance_step():
        """仅进入民事一审的下一页以验证页面字段；不录入、不上传、不提交。"""
        page = scheduler.get("browser_page")
        if not page or page.is_closed():
            raise HTTPException(status_code=409, detail="一张网浏览器未打开")
        try:
            entry = page.locator(".fd-children-item.fd-children-blue").filter(has_text="民事一审").first
            await entry.click(timeout=10000)
            await page.wait_for_timeout(1200)
            return {"ok": True, "message": "已进入民事一审的下一步（仅页面验证）"}
        except Exception as exc:
            raise HTTPException(status_code=502, detail="无法进入民事一审页面") from exc

    def sync_job_status() -> dict[str, Any]:
        job = scheduler.get("sync_job")
        running = bool(job and not job.done())
        return {"running": running, "stage": scheduler.get("sync_stage") if running else "",
                "started_at": scheduler.get("sync_started_at") or "",
                "finished_at": scheduler.get("sync_finished_at") or "",
                "result": scheduler.get("sync_result") if not running else None}

    def start_sync_job(manual: bool = False) -> dict[str, Any]:
        job = scheduler.get("sync_job")
        if job and not job.done():
            return sync_job_status()
        scheduler["sync_started_at"] = _now()
        scheduler["sync_finished_at"] = ""
        scheduler["sync_stage"] = "正在连接人民法院在线服务"
        scheduler["sync_result"] = None
        async def run() -> None:
            try:
                scheduler["sync_result"] = await sync_once(manual)
            except Exception as exc:
                scheduler["sync_result"] = {"ok": False, "message": str(getattr(exc, "detail", exc))}
                log("error", f"同步失败：{getattr(exc, 'detail', exc)}")
            finally:
                scheduler["sync_finished_at"] = _now()
                scheduler["sync_stage"] = ""
        scheduler["sync_job"] = asyncio.create_task(run())
        return sync_job_status()

    @app.post("/api/case-manager/court-online/sync/start")
    async def sync_start(): return start_sync_job(True)

    @app.get("/api/case-manager/court-online/sync/status")
    async def sync_status(): return sync_job_status()

    @app.post("/api/case-manager/court-online/sync")
    async def sync(): return await sync_once(True)

    @app.get("/api/case-manager/court-online/search-options")
    def search_options():
        """高级搜索下拉候选值：聚合一张网记录、我的案件、立案预约、开庭扫描与本地案件库中
        可选的案号、法院、当事人，按最近更新时间优先、数量受限。"""
        with get_db() as conn:
            case_no_rows = conn.execute(
                """SELECT v FROM (
                       SELECT case_number AS v, MAX(updated_at) AS t FROM case_manager_court_online_records WHERE case_number<>'' GROUP BY case_number
                       UNION ALL SELECT case_number, MAX(updated_at) FROM case_manager_court_online_cases WHERE case_number<>'' GROUP BY case_number
                       UNION ALL SELECT case_number, MAX(updated_at) FROM case_manager_court_online_hearings WHERE case_number<>'' GROUP BY case_number
                   ) ORDER BY t DESC LIMIT 300"""
            ).fetchall()
            court_rows = conn.execute(
                """SELECT v FROM (
                       SELECT court_name AS v, MAX(updated_at) AS t FROM case_manager_court_online_records WHERE court_name<>'' GROUP BY court_name
                       UNION ALL SELECT court_name, MAX(updated_at) FROM case_manager_court_online_cases WHERE court_name<>'' GROUP BY court_name
                       UNION ALL SELECT court_name, MAX(updated_at) FROM case_manager_court_online_layy WHERE court_name<>'' GROUP BY court_name
                       UNION ALL SELECT court_name, MAX(updated_at) FROM case_manager_court_online_hearings WHERE court_name<>'' GROUP BY court_name
                   ) ORDER BY t DESC LIMIT 200"""
            ).fetchall()
            party_rows = conn.execute(
                """SELECT v, n FROM (
                       SELECT parties AS v, 1 AS n FROM case_manager_court_online_cases WHERE parties<>''
                       UNION ALL SELECT parties, 1 FROM case_manager_court_online_layy WHERE parties<>''
                       UNION ALL SELECT name AS v, COUNT(*) AS n FROM case_manager_parties GROUP BY name
                   )"""
            ).fetchall()
        party_count: Dict[str, int] = {}
        for row in party_rows:
            for name in re.split(r"[,，、;；]+", str(row[0])):
                name = name.strip()
                if not name:
                    continue
                party_count[name] = party_count.get(name, 0) + (int(row[1]) if row[1] else 1)
        return {
            "case_no": [row[0] for row in case_no_rows],
            "court": [row[0] for row in court_rows],
            "party": [k for k, _ in sorted(party_count.items(), key=lambda kv: (-kv[1], kv[0]))][:400],
        }

    @app.get("/api/case-manager/court-online/records")
    def list_records(kind: str = "", q: str = "", unread: bool = False, page: int = 1, page_size: int = 50, case_no: str = "", court: str = "", party: str = ""):
        if kind and kind not in ALLOWED_KINDS: raise HTTPException(status_code=422, detail="无效的记录类型")
        page, page_size = max(1, page), min(max(1, page_size), 100)
        clauses, params = ["r.account_id=?"], [_active_account_id()]
        if kind: clauses.append("r.kind=?"); params.append(kind)
        if q.strip(): clauses.append("(r.title LIKE ? OR r.content LIKE ? OR r.case_number LIKE ? OR r.case_name LIKE ? OR r.court_name LIKE ? OR COALESCE(c.title,'') LIKE ?)"); params.extend([f"%{q.strip()}%"] * 6)
        if unread: clauses.append("r.unread=1")
        if case_no.strip():
            compact = re.sub(r"[\s（）()《》〈〉·.]", "", case_no.strip())
            if compact:
                clauses.append(
                    "REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(r.case_number,' ',''),'　',''),'（',''),'）',''),'(',''),')','') LIKE ?"
                )
                params.append(f"%{compact}%")
        if court.strip():
            clauses.append("r.court_name LIKE ?")
            params.append(f"%{court.strip()}%")
        if party.strip():
            pattern = f"%{party.strip()}%"
            clauses.append(
                """(r.case_name LIKE ?
                   OR EXISTS (
                       SELECT 1 FROM case_manager_parties p
                       JOIN case_manager_cases cc ON cc.id=p.case_id
                       WHERE cc.id=r.linked_case_id AND (p.name LIKE ? OR p.role LIKE ?)
                   ))"""
            )
            params.extend([pattern, pattern, pattern])
        where = " AND ".join(clauses)
        with get_db() as conn:
            source = "case_manager_court_online_records r LEFT JOIN case_manager_cases c ON c.id=r.linked_case_id"
            total = int(conn.execute(f"SELECT COUNT(*) FROM {source} WHERE {where}", params).fetchone()[0])
            rows = conn.execute(f"SELECT r.*, c.title AS linked_case_title FROM {source} WHERE {where} ORDER BY r.unread DESC,datetime(r.published_at) DESC,r.id DESC LIMIT ? OFFSET ?", [*params, page_size, (page-1)*page_size]).fetchall()
            counts = conn.execute("SELECT kind, COUNT(*) AS n FROM case_manager_court_online_records WHERE account_id=? GROUP BY kind", (_active_account_id(),)).fetchall()
            kind_counts: Dict[str, int] = {row["kind"]: int(row["n"]) for row in counts}
            kind_counts["total"] = sum(kind_counts.values())
            return {"items": [record_dict(row, conn) for row in rows], "total": total, "page": page, "page_size": page_size, "kind_counts": kind_counts}

    @app.post("/api/case-manager/court-online/auto-link")
    def auto_link_all():
        """按案号自动匹配案件管理系统数据库，批量关联尚未关联的官网记录。"""
        with get_db() as conn:
            linked = auto_link_pending_records(conn, _active_account_id())
            conn.commit()
        if linked:
            log("info", f"自动关联完成，按案号匹配 {linked} 条法院记录")
        return {"ok": True, "linked": linked}

    @app.get("/api/case-manager/court-online/cases")
    def list_court_cases(q: str = "", case_no: str = "", court: str = "", party: str = "", ajlb: str = "", page: int = 1, page_size: int = 50):
        page, page_size = max(1, page), min(max(1, page_size), 100)
        clauses, params = ["account_id=?"], [_active_account_id()]
        if ajlb.strip():
            if ajlb.strip() not in ("sp", "zx", "pc"):
                raise HTTPException(status_code=422, detail="无效的案件类别")
            clauses.append("ajlb=?")
            params.append(ajlb.strip())
        if q.strip():
            pattern = f"%{q.strip()}%"
            clauses.append("(case_number LIKE ? OR case_name LIKE ? OR cause LIKE ? OR court_name LIKE ? OR judge LIKE ? OR parties LIKE ?)")
            params.extend([pattern] * 6)
        if case_no.strip():
            compact = re.sub(r"[\s（）()《》〈〉·.]", "", case_no.strip())
            if compact:
                clauses.append(
                    "REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(case_number,' ',''),'　',''),'（',''),'）',''),'(',''),')','') LIKE ?"
                )
                params.append(f"%{compact}%")
        if court.strip():
            clauses.append("court_name LIKE ?")
            params.append(f"%{court.strip()}%")
        if party.strip():
            pattern = f"%{party.strip()}%"
            clauses.append("(case_name LIKE ? OR parties LIKE ?)")
            params.extend([pattern, pattern])
        where = " AND ".join(clauses)
        with get_db() as conn:
            total = int(conn.execute(f"SELECT COUNT(*) FROM case_manager_court_online_cases WHERE {where}", params).fetchone()[0])
            rows = conn.execute(f"""SELECT * FROM case_manager_court_online_cases WHERE {where}
                ORDER BY
                  CASE WHEN linked_case_id IS NULL OR linked_case_id = 0 THEN 1 ELSE 0 END,
                  CASE WHEN COALESCE(stage,'') LIKE '%结案%' OR COALESCE(stage,'') LIKE '%归档%' THEN 1 ELSE 0 END,
                  datetime(COALESCE(NULLIF(filing_date,''), update_date)) DESC,
                  datetime(update_date) DESC, id DESC
                LIMIT ? OFFSET ?""", [*params, page_size, (page - 1) * page_size]).fetchall()
            return {"items": [dict(row) for row in rows], "total": total, "page": page, "page_size": page_size}

    def _court_case_payload(conn: Any, row: Any) -> dict[str, Any]:
        """把一条“我的案件”官网记录解析为统一的详情字典。

        详情展示（court_case_detail）与“同步到案件”（sync-plan / sync）共用，
        保证同一官网记录解析出的字段一致。
        """
        item = dict(row)
        linked_title = ""
        if item.get("linked_case_id"):
            hit = conn.execute("SELECT title FROM case_manager_cases WHERE id=?", (item["linked_case_id"],)).fetchone()
            linked_title = str(hit[0] or "") if hit else ""
        try:
            raw = json.loads(item.get("raw_json") or "{}")
        except json.JSONDecodeError:
            raw = {}

        def local_date(value: Any) -> str:
            text = str(value or "").strip()
            if not text:
                return ""
            try:
                parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
                if parsed.tzinfo is not None:
                    parsed = parsed.astimezone()
                return parsed.strftime("%Y-%m-%d")
            except ValueError:
                return text[:10]

        def plain(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, (dict, list)):
                return _json(value)
            text = str(value).strip()
            return "" if text in ("None", "null", "0") and value not in (0, 0.0) else text

        case_number = plain(raw.get("cah"))
        court_current = plain(raw.get("cfydmTranslateText"))
        court_from = plain(raw.get("cysfyTranslateText"))
        case_identifier = plain(raw.get("cajbh"))
        case_mark = plain(raw.get("cajbs"))
        if case_mark == case_identifier:
            case_mark = ""
        amount = ""
        try:
            raw_amount = float(raw.get("dlabdje") or 0)
        except (TypeError, ValueError):
            raw_amount = 0.0
        if raw_amount > 0:
            amount_text = f"{raw_amount:,.2f}".rstrip("0").rstrip(".")
            amount = f"¥ {amount_text}"
        hearing_at = plain(raw.get("dktsj") or raw.get("cktsj"))
        if hearing_at:
            hearing_at = _parse_hearing_at(hearing_at)

        mapped_keys = {
            "cah", "cajmc", "claay", "cywlx", "cywlxTranslateText", "cajlb", "cajlbTranslateText",
            "cfydm", "cfydmTranslateText", "cysfy", "cysfyTranslateText", "ccbr", "ccbrTranslateText",
            "ccbspt", "ccbsptTranslateText", "cajjzjd", "cajjzjdTranslateText", "cjafs", "cjafsTranslateText",
            "ccyr", "dlarq", "djarq", "dzhgxsj", "cusername", "dlabdje", "cajbh", "cajbs",
            "cysah", "dktsj", "cktsj", "dsxrq", "dcjsj", "csycx", "csycxTranslateText",
        }
        raw_fields: list[dict[str, str]] = []
        for key in sorted(raw):
            if key in mapped_keys:
                continue
            value = raw[key]
            if isinstance(value, (dict, list)):
                continue
            if value is None or str(value).strip() in ("", "None", "null"):
                continue
            raw_fields.append({"key": key, "value": plain(value)})

        return {
            "id": item["id"],
            "ajlb": item.get("ajlb") or "",
            "case_number": case_number or "",
            "case_name": plain(item.get("case_name") or raw.get("cajmc")) or "",
            "cause": plain(item.get("cause") or raw.get("claay")) or "",
            "business_type": plain(item.get("business_type") or raw.get("cywlxTranslateText")) or "",
            "stage": plain(item.get("stage") or raw.get("cajjzjdTranslateText")) or "",
            "adjudication": plain(item.get("adjudication") or raw.get("cjafsTranslateText")) or "",
            "department": plain(item.get("department") or raw.get("ccbsptTranslateText")) or "",
            "judge": plain(item.get("judge") or raw.get("ccbrTranslateText")) or "",
            "parties": plain(item.get("parties") or raw.get("ccyr")) or "",
            "filing_date": local_date(item.get("filing_date") or raw.get("dlarq")),
            "judgment_date": local_date(item.get("judgment_date") or raw.get("djarq")),
            "update_date": local_date(item.get("update_date") or raw.get("dzhgxsj")),
            "first_seen": local_date(item.get("first_seen")),
            "linked_case_id": item.get("linked_case_id") or 0,
            "linked_case_title": linked_title,
            "case_identifier": case_identifier,
            "case_mark": case_mark,
            "case_category": plain(raw.get("cajlbTranslateText")),
            "procedure": plain(raw.get("csycxTranslateText")),
            "original_number": plain(raw.get("cysah")),
            "current_court": court_current,
            "transfer_court": court_from if court_from != court_current else "",
            "hearing_at": hearing_at,
            "served_date": local_date(raw.get("dsxrq")),
            "amount": amount,
            "account": plain(raw.get("cusername")),
            "record_time": local_date(raw.get("dcjsj")),
            "raw_fields": raw_fields,
        }

    @app.get("/api/case-manager/court-online/cases/{case_row_id}/detail")
    def court_case_detail(case_row_id: int):
        """我的案件详情：返回已提取的表字段，并从官网原始数据中解析出
        全部已知语义字段与未识别字段，供前端弹窗分门别类展示。"""
        with get_db() as conn:
            row = conn.execute("SELECT * FROM case_manager_court_online_cases WHERE id=? AND account_id=?", (case_row_id, _active_account_id())).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="官网案件记录不存在")
            return _court_case_payload(conn, row)

    def _compact_case_no(value: Any) -> str:
        return re.sub(r"[\s（）()《》〈〉·.]", "", str(value or ""))

    def _infer_instance(procedure: str, case_number: str) -> str:
        """按官网审理程序与案号判断本案属于一审还是二审。

        本地案号记录只区分一审/二审两列日期，再审、执行等审理程序
        归入二审列，并在计划中向用户说明判定理由。
        """
        text = f"{procedure or ''} {case_number or ''}"
        if re.search(r"二审|第二审|终审|再审|(?:民|刑|行|知)(?:辖)?终", text):
            return "second"
        if re.search(r"一审|(?:民|刑|行|知)(?:辖)?初", text):
            return "first"
        return "first"

    def _instance_label(instance: str) -> str:
        return "二审" if instance == "second" else "一审"

    def _build_sync_plan(conn: Any, payload: dict[str, Any], local: dict[str, Any]) -> dict[str, Any]:
        """智能检测官网案件可同步到本地案件的字段，生成待确认计划。

        审级判定：官网“审理程序”或案号中包含二审/终审/再审判为二审，
        其余按一审处理。案号记录定位：优先匹配规范化案号完全一致的本地
        案号记录；没有则回退到本地第一条案号记录；本地没有任何案号记录
        时提示将按审级新建一条案号记录。
        """
        case_id = int(local.get("id") or 0)
        court_no = _compact_case_no(payload.get("case_number"))
        numbers = [dict(r) for r in conn.execute(
            "SELECT * FROM case_manager_case_numbers WHERE case_id=? ORDER BY sort_order,id",
            (case_id,),
        ).fetchall()] if case_id else []
        instance = _infer_instance(payload.get("procedure"), payload.get("case_number"))
        matched = False
        target = None
        if court_no and re.search(r"\d", court_no):
            for item in numbers:
                if _compact_case_no(item.get("case_no")) == court_no:
                    target, matched = item, True
                    break
        if target is None and numbers:
            want = _instance_label(instance)
            for item in numbers:
                if want in str(item.get("number_type") or ""):
                    target = item
                    break

        fields: list[dict[str, Any]] = []

        def add_field(key: str, label: str, source_label: str, source_value: str,
                      target_label: str, current_value: str, reason: str,
                      action: str = "") -> None:
            if not source_value:
                return
            if not action:
                if str(current_value or "").strip() == source_value:
                    action = "same"
                elif str(current_value or "").strip():
                    action = "overwrite"
                else:
                    action = "new"
            fields.append({
                "key": key,
                "label": label,
                "source_label": source_label,
                "source_value": source_value,
                "target_label": target_label,
                "current_value": str(current_value or ""),
                "action": action,
                "reason": reason,
            })

        filing_key = "second_filing_at" if instance == "second" else "first_filing_at"
        judgment_key = "second_judgment_effective_at" if instance == "second" else "first_judgment_served_at"
        judgment_label = "生效" if instance == "second" else "送达"
        procedure_text = payload.get("procedure") or "未标注"
        add_field(
            "filing_at", f"{_instance_label(instance)}立案时间", "立案日期",
            payload.get("filing_date"), f"案号记录·{_instance_label(instance)}立案时间",
            (target or {}).get(filing_key),
            f"官网审理程序“{procedure_text}”判定为{_instance_label(instance)}案件",
        )
        judgment_source = payload.get("judgment_date") or payload.get("served_date")
        add_field(
            "judgment_at", f"{_instance_label(instance)}判决{judgment_label}时间",
            "结案日期" if payload.get("judgment_date") else "送达日期",
            judgment_source, f"案号记录·{_instance_label(instance)}判决{judgment_label}时间",
            (target or {}).get(judgment_key),
            f"官网记录的案件结案/送达日期，对应{_instance_label(instance)}判决{judgment_label}时间",
        )
        add_field(
            "court", "承办法院", "承办法院",
            payload.get("current_court"), "案号记录·受理机构",
            (target or {}).get("court"), "官网记录的承办法院",
        )
        judge = payload.get("judge")
        if judge:
            current_contact = str(local.get("court_contact") or "")
            if f"姓名：{judge}" in current_contact:
                add_field("judge", "承办法官", "承办法官", judge,
                          "案件信息·裁判机关经办人（联系与备忘）", judge,
                          "官网记录的承办法官，已存在", action="same")
            else:
                add_field("judge", "承办法官", "承办法官", judge,
                          "案件信息·裁判机关经办人（联系与备忘）", current_contact or "（空）",
                          "官网记录的承办法官，追加到案件联系与备忘", action="append")

        return {
            "court_case": {
                "id": payload.get("id"),
                "case_number": payload.get("case_number") or "",
                "case_name": payload.get("case_name") or "",
                "procedure": payload.get("procedure") or "",
                "instance": instance,
                "instance_label": _instance_label(instance),
                "filing_date": payload.get("filing_date") or "",
                "judgment_date": payload.get("judgment_date") or "",
                "served_date": payload.get("served_date") or "",
                "current_court": payload.get("current_court") or "",
                "judge": judge or "",
            },
            "target": {
                "case_id": case_id,
                "case_title": local.get("title") or "",
                "number_row_id": (target or {}).get("id") or 0,
                "number_type": (target or {}).get("number_type") or "",
                "case_no": (target or {}).get("case_no") or "",
                "create_new": not bool(target),
                "matched_case_no": matched,
            },
            "fields": fields,
        }

    @app.get("/api/case-manager/court-online/cases/{case_row_id}/sync-plan")
    def court_case_sync_plan(case_row_id: int, case_id: int = 0):
        """同步前智能检测：给出官网案件可同步到本地案件的字段计划。"""
        if case_id <= 0:
            raise HTTPException(status_code=400, detail="缺少本地案件参数")
        with get_db() as conn:
            row = conn.execute("SELECT * FROM case_manager_court_online_cases WHERE id=?", (case_row_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="官网案件记录不存在")
            local = conn.execute(
                "SELECT * FROM case_manager_cases WHERE id=? AND COALESCE(source_status,'active')='active'",
                (case_id,),
            ).fetchone()
            if not local:
                raise HTTPException(status_code=404, detail="本地案件不存在")
            return _build_sync_plan(conn, _court_case_payload(conn, row), dict(local))

    @app.post("/api/case-manager/court-online/cases/{case_row_id}/sync")
    async def court_case_sync(case_row_id: int, request: Request):
        """把用户在确认界面勾选的一张网字段写入本地案件对应字段。

        只写入选中的字段；字段取值以同步计划（sync-plan）为准，避免
        前端传值与官网数据不一致。写入后记录审计日志。
        """
        body = await request.json()
        case_id = int(body.get("case_id") or 0)
        selected = {str(key).strip() for key in (body.get("fields") or []) if str(key).strip()}
        ALLOWED_SYNC_KEYS = {"filing_at", "judgment_at", "court", "judge"}
        selected &= ALLOWED_SYNC_KEYS
        if not selected:
            raise HTTPException(status_code=400, detail="未选择任何可同步字段")
        if case_id <= 0:
            raise HTTPException(status_code=400, detail="缺少本地案件参数")
        stamp = _now()
        with get_db() as conn:
            row = conn.execute("SELECT * FROM case_manager_court_online_cases WHERE id=?", (case_row_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="官网案件记录不存在")
            local = conn.execute(
                "SELECT * FROM case_manager_cases WHERE id=? AND COALESCE(source_status,'active')='active'",
                (case_id,),
            ).fetchone()
            if not local:
                raise HTTPException(status_code=404, detail="本地案件不存在")
            local = dict(local)
            plan = _build_sync_plan(conn, _court_case_payload(conn, row), local)
            target = plan["target"]
            changes: list[dict[str, str]] = []
            synced: list[str] = []

            number_updates: dict[str, Any] = {}
            if target["number_row_id"]:
                number_updates["number_row_id"] = target["number_row_id"]
            else:
                number_updates["number_row_id"] = 0
                number_updates["number_type"] = "一审" if plan["court_case"]["instance"] == "first" else "二审"
                number_updates["case_no"] = plan["court_case"]["case_number"]
            for field in plan["fields"]:
                if field["key"] not in selected or field["action"] == "same":
                    continue
                source_value = field["source_value"]
                if field["key"] == "filing_at":
                    column = "second_filing_at" if plan["court_case"]["instance"] == "second" else "first_filing_at"
                elif field["key"] == "judgment_at":
                    column = "second_judgment_effective_at" if plan["court_case"]["instance"] == "second" else "first_judgment_served_at"
                elif field["key"] == "court":
                    column = "court"
                else:
                    column = ""
                if column:
                    number_updates[column] = source_value
                changes.append({
                    "field": field["key"],
                    "label": field["label"],
                    "before": field["current_value"],
                    "after": source_value,
                })
                synced.append(field["key"])
            if number_updates.get("number_row_id"):
                row_id = number_updates["number_row_id"]
                current = conn.execute("SELECT * FROM case_manager_case_numbers WHERE id=?", (row_id,)).fetchone()
                if not current:
                    raise HTTPException(status_code=404, detail="本地案号记录不存在")
                conn.execute(
                    """UPDATE case_manager_case_numbers
                       SET court=COALESCE(?,court), first_filing_at=COALESCE(?,first_filing_at),
                           first_judgment_served_at=COALESCE(?,first_judgment_served_at),
                           second_filing_at=COALESCE(?,second_filing_at),
                           second_judgment_effective_at=COALESCE(?,second_judgment_effective_at),
                           updated_at=?
                       WHERE id=?""",
                    (
                        number_updates.get("court", ""),
                        number_updates.get("first_filing_at", ""),
                        number_updates.get("first_judgment_served_at", ""),
                        number_updates.get("second_filing_at", ""),
                        number_updates.get("second_judgment_effective_at", ""),
                        stamp, row_id,
                    ),
                )
            elif column_writes := {k: v for k, v in number_updates.items() if k not in ("number_row_id", "number_type", "case_no")}:
                row_id = int(conn.execute(
                    """INSERT INTO case_manager_case_numbers
                       (case_id, number_type, case_no, court,
                        first_filing_at, first_judgment_served_at, second_filing_at, second_judgment_effective_at,
                        sort_order, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
                    (
                        case_id, number_updates.get("number_type", ""), number_updates.get("case_no", ""),
                        number_updates.get("court", ""), number_updates.get("first_filing_at", ""),
                        number_updates.get("first_judgment_served_at", ""), number_updates.get("second_filing_at", ""),
                        number_updates.get("second_judgment_effective_at", ""), stamp, stamp,
                    ),
                ).lastrowid)
                number_updates["number_row_id"] = row_id
            if "judge" in selected:
                judge = plan["court_case"].get("judge") or ""
                judge_field = next((f for f in plan["fields"] if f["key"] == "judge"), None)
                if judge and judge_field and judge_field["action"] != "same":
                    current_contact = str(local.get("court_contact") or "")
                    block = (
                        "【联调/诉讼/仲裁阶段】\n"
                        "【联系人组】\n"
                        "身份：承办法官\n"
                        f"姓名：{judge}\n"
                    )
                    if f"姓名：{judge}" not in current_contact:
                        next_contact = f"{current_contact}\n\n{block}".strip() if current_contact.strip() else block.strip()
                        conn.execute(
                            "UPDATE case_manager_cases SET court_contact=?, updated_at=? WHERE id=?",
                            (next_contact, stamp, case_id),
                        )
            if synced:
                conn.execute(
                    "UPDATE case_manager_cases SET updated_at=? WHERE id=?",
                    (stamp, case_id),
                )
                conn.execute(
                    """INSERT INTO case_manager_audit_logs
                       (case_id, entity_type, entity_id, action, summary, changes_json, actor, created_at)
                       VALUES (?, 'case', ?, 'synced', ?, ?, '本机用户', ?)""",
                    (
                        case_id, case_id,
                        "从一张网同步官网案件信息到本地案件",
                        _json(changes), stamp,
                    ),
                )
                conn.execute(
                    "INSERT INTO case_manager_court_online_logs(created_at,level,message) VALUES(?,?,?)",
                    (stamp, "info", f"案件 {case_id} 从官网案件 {case_row_id} 同步字段：{','.join(synced)}"),
                )
                conn.commit()
            return {
                "ok": True,
                "synced": synced,
                "changes": changes,
                "target": {"number_row_id": number_updates.get("number_row_id") or 0},
            }

    @app.get("/api/case-manager/court-online/layy")
    def list_layy(q: str = "", case_no: str = "", court: str = "", party: str = "", ajlb: str = "", page: int = 1, page_size: int = 50):
        page, page_size = max(1, page), min(max(1, page_size), 100)
        clauses, params = ["account_id=?"], [_active_account_id()]
        clauses.append("CAST(COALESCE(json_extract(raw_json,'$.isDel'),0) AS TEXT)<>'1'")
        if ajlb.strip():
            if ajlb.strip() not in ("sp", "zx", "pc"):
                raise HTTPException(status_code=422, detail="无效的案件类别")
            clauses.append("category=?")
            params.append(ajlb.strip())
        if q.strip():
            pattern = f"%{q.strip()}%"
            clauses.append("(court_name LIKE ? OR case_type LIKE ? OR parties LIKE ? OR case_name LIKE ? OR cause LIKE ? OR review_comment LIKE ?)")
            params.extend([pattern] * 6)
        if case_no.strip():
            pattern = f"%{case_no.strip()}%"
            clauses.append("(case_name LIKE ? OR parties LIKE ?)")
            params.extend([pattern, pattern])
        if court.strip():
            clauses.append("court_name LIKE ?")
            params.append(f"%{court.strip()}%")
        if party.strip():
            pattern = f"%{party.strip()}%"
            clauses.append("(parties LIKE ? OR case_name LIKE ?)")
            params.extend([pattern, pattern])
        where = " AND ".join(clauses)
        with get_db() as conn:
            total = int(conn.execute(f"SELECT COUNT(*) FROM case_manager_court_online_layy WHERE {where}", params).fetchone()[0])
            rows = conn.execute(f"SELECT * FROM case_manager_court_online_layy WHERE {where} ORDER BY datetime(update_date) DESC,id DESC LIMIT ? OFFSET ?", [*params, page_size, (page - 1) * page_size]).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                try:
                    detail = json.loads(item.get("detail_json") or "{}")
                    layy = (detail.get("layy") or {}) if isinstance(detail, dict) else {}
                    item["judge"] = item.get("judge") or pick(layy, "cbrmc")
                    item["filing_method"] = item.get("filing_method") or pick(layy, "lafs")
                    item["claim_amount"] = item.get("claim_amount") or pick(layy, "sqbdje")
                    item["lawsuit_request"] = item.get("lawsuit_request") or pick(layy, "ssqq")
                    item["case_number"] = item.get("case_number") or pick(layy, "ah")
                    item["material_count"] = item.get("material_count") or (int(pick(layy, "bcclCs") or 0) if str(pick(layy, "bcclCs") or "").isdigit() else 0)
                    item["material_time"] = item.get("material_time") or pick(layy, "bcclSj")
                except (json.JSONDecodeError, TypeError):
                    pass
                item["audits"] = [dict(a) for a in conn.execute(
                    "SELECT shjg,shjg_text,review_comment,review_time,reviewer,reviewer_id,remark_term,reject_reason FROM case_manager_court_online_layy_audits WHERE layy_id=? ORDER BY datetime(COALESCE(NULLIF(review_time,''),'1970-01-01')) ASC,id ASC",
                    (item["id"],)).fetchall()]
                items.append(item)
            return {"items": items, "total": total, "page": page, "page_size": page_size}

    def backfill_hearings_from_cases(conn: Any, account_id: str | None = None) -> int:
        """把历史同步的“我的案件”数据中带开庭时间的记录补入开庭扫描表。"""
        rows = conn.execute(
            """SELECT raw_json, ajlb FROM case_manager_court_online_cases
               WHERE account_id=? AND json_extract(raw_json,'$.dktsj') IS NOT NULL
                 AND json_extract(raw_json,'$.dktsj')<>'null'"""
        , (account_id or _active_account_id(),)).fetchall()
        filled = 0
        for row in rows:
            try:
                raw = json.loads(row["raw_json"] or "{}")
            except json.JSONDecodeError:
                continue
            hearing_at_raw = pick(raw, "dktsj", "ktsj")
            if not hearing_at_raw:
                continue
            remote_id = pick(raw, "cbh", "cajbh", "id")
            if not remote_id:
                continue
            ajlb = str(row["ajlb"] or "sp") if "ajlb" in row.keys() else "sp"
            upsert_court_hearing(
                conn, f"case:{ajlb}:{remote_id}", f"case_{ajlb}", raw,
                case_number=pick(raw, "cah"),
                case_name=pick(raw, "cajmc"),
                court_name=pick(raw, "cysfyTranslateText", "cfydmTranslateText"),
                judge=pick(raw, "ccbrTranslateText"),
                status=pick(raw, "cajjzjdTranslateText"),
                hearing_at=hearing_at_raw, account_id=account_id or _active_account_id(),
            )
            filled += 1
        return filled

    @app.get("/api/case-manager/court-online/hearings")
    def list_court_hearings(q: str = "", case_no: str = "", court: str = "", party: str = "", future_only: bool = False, page: int = 1, page_size: int = 50):
        """开庭扫描列表：一张网读取到的开庭时间，按时间从新到旧展示。

        附带 linked_case_title（已关联的本地案件名）与 added（是否已加入开庭提醒）。
        首次打开时回填历史案件数据中的开庭时间。
        """
        page, page_size = max(1, page), min(max(1, page_size), 100)
        clauses, params = ["h.account_id=?"], [_active_account_id()]
        if q.strip():
            pattern = f"%{q.strip()}%"
            clauses.append("(case_number LIKE ? OR case_name LIKE ? OR court_name LIKE ? OR hearing_type LIKE ? OR location LIKE ? OR judge LIKE ?)")
            params.extend([pattern] * 6)
        if case_no.strip():
            compact = re.sub(r"[\s（）()《》〈〉·.]", "", case_no.strip())
            if compact:
                clauses.append(
                    "REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(h.case_number,' ',''),'　',''),'（',''),'）',''),'(',''),')','') LIKE ?"
                )
                params.append(f"%{compact}%")
        if court.strip():
            clauses.append("h.court_name LIKE ?")
            params.append(f"%{court.strip()}%")
        if party.strip():
            clauses.append("h.case_name LIKE ?")
            params.append(f"%{party.strip()}%")
        if future_only:
            clauses.append("datetime(h.hearing_at)>=datetime('now','localtime')")
        where = " AND ".join(clauses)
        source = (
            "case_manager_court_online_hearings h "
            "LEFT JOIN case_manager_cases c ON c.id=h.linked_case_id"
        )
        with get_db() as conn:
            if int(conn.execute("SELECT COUNT(*) FROM case_manager_court_online_hearings WHERE account_id=?", (_active_account_id(),)).fetchone()[0]) == 0:
                backfill_hearings_from_cases(conn, _active_account_id())
                conn.commit()
            total = int(conn.execute(f"SELECT COUNT(*) FROM {source} WHERE {where}", params).fetchone()[0])
            rows = conn.execute(
                f"""SELECT h.*, c.title AS linked_case_title,
                       EXISTS(SELECT 1 FROM case_manager_hearings ch WHERE ch.source_key='court-hearing:'||h.id) AS added
                    FROM {source} WHERE {where}
                    ORDER BY datetime(h.hearing_at) DESC, h.id DESC LIMIT ? OFFSET ?""",
                [*params, page_size, (page - 1) * page_size],
            ).fetchall()
            return {
                "items": [{**dict(row), "added": bool(row["added"])} for row in rows],
                "total": total, "page": page, "page_size": page_size,
            }

    @app.post("/api/case-manager/court-online/cases/{case_row_id}/case")
    def link_court_case(case_row_id: int, body: Dict[str, Any]):
        """手动把一张网“我的案件”关联到本地案件，case_id 传 0 时解除关联。"""
        case_id = int(body.get("case_id") or 0)
        with get_db() as conn:
            row = conn.execute("SELECT id FROM case_manager_court_online_cases WHERE id=? AND account_id=?", (case_row_id, _active_account_id())).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="官网案件记录不存在")
            if case_id and not conn.execute("SELECT 1 FROM case_manager_cases WHERE id=?", (case_id,)).fetchone():
                raise HTTPException(status_code=404, detail="案件不存在")
            conn.execute("UPDATE case_manager_court_online_cases SET linked_case_id=?,updated_at=? WHERE id=?", (case_id or None, _now(), case_row_id)); conn.commit()
        return {"ok": True}

    @app.post("/api/case-manager/court-online/hearings/{hearing_id}/case")
    def link_court_hearing(hearing_id: int, body: Dict[str, Any]):
        """手动把开庭扫描记录关联到本地案件，case_id 传 0 时解除关联。"""
        case_id = int(body.get("case_id") or 0)
        with get_db() as conn:
            row = conn.execute("SELECT id FROM case_manager_court_online_hearings WHERE id=? AND account_id=?", (hearing_id, _active_account_id())).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="开庭扫描记录不存在")
            if case_id and not conn.execute("SELECT 1 FROM case_manager_cases WHERE id=?", (case_id,)).fetchone():
                raise HTTPException(status_code=404, detail="案件不存在")
            conn.execute("UPDATE case_manager_court_online_hearings SET linked_case_id=?,updated_at=? WHERE id=?", (case_id or None, _now(), hearing_id)); conn.commit()
        return {"ok": True}

    @app.post("/api/case-manager/court-online/records/{record_id}/read")
    def mark_read(record_id: int):
        with get_db() as conn:
            conn.execute("UPDATE case_manager_court_online_records SET unread=0,updated_at=? WHERE id=? AND account_id=?", (_now(), record_id, _active_account_id())); conn.commit()
        return {"ok": True}

    @app.post("/api/case-manager/court-online/records/{record_id}/case")
    def link_case(record_id: int, body: Dict[str, Any]):
        case_id = int(body.get("case_id") or 0)
        with get_db() as conn:
            if case_id and not conn.execute("SELECT 1 FROM case_manager_cases WHERE id=?", (case_id,)).fetchone(): raise HTTPException(status_code=404, detail="案件不存在")
            conn.execute("UPDATE case_manager_court_online_records SET linked_case_id=?,updated_at=? WHERE id=? AND account_id=?", (case_id or None, _now(), record_id, _active_account_id())); conn.commit()
        return {"ok": True}

    @app.post("/api/case-manager/court-online/records/{record_id}/chat")
    async def get_chat(record_id: int):
        """按需拉取法院私信全文，避免每轮同步读取全部聊天记录。"""
        with get_db() as conn:
            row = conn.execute("SELECT raw_json,chat_context_json FROM case_manager_court_online_records WHERE id=? AND account_id=?", (record_id, _active_account_id())).fetchone()
        if not row: raise HTTPException(status_code=404, detail="法院记录不存在")
        try: raw = json.loads(row[0] or "{}")
        except json.JSONDecodeError: raw = {}
        token = _read_secret().get("session_token", "")
        if not token: raise HTTPException(status_code=401, detail="请先登录人民法院在线服务")
        payload = {key: raw[key] for key in ("fyId", "ajbh", "ahdm", "caseId") if raw.get(key) not in (None, "")}
        if not payload: return {"items": [], "message": "此通知未包含可读取的私信上下文"}
        headers = {"Authorization": token}
        if cookie_header := await browser_cookie_header(): headers["Cookie"] = cookie_header
        async with httpx.AsyncClient(timeout=25, headers=headers, follow_redirects=False) as client:
            bind = await court_json(client, "/yzw-zxfw-ajfw/api/v1/bind", payload)
            sid = str(bind.get("sid") or "") if isinstance(bind, dict) else ""
            if not sid: return {"items": [], "message": "法院官网未返回私信会话"}
            response = await client.post(_validate_court_url(f"{COURT_ORIGIN}/portal-chat/api/v1/chat/msgs?limit=100"), json={"sid": sid})
            response.raise_for_status()
            data = response.json()
        return {"items": data.get("data", data) if isinstance(data, dict) else data}

    @app.get("/api/case-manager/court-online/chat-file-preview")
    async def preview_chat_file(url: str):
        """以本地代理预览私信中的文件，网页不直接取得法院会话令牌。"""
        source = _validate_court_url(url)
        token = _read_secret().get("session_token", "")
        if not token: raise HTTPException(status_code=401, detail="请先登录人民法院在线服务")
        headers = {"Authorization": token}
        if cookie_header := await browser_cookie_header(): headers["Cookie"] = cookie_header
        async with httpx.AsyncClient(timeout=60, follow_redirects=False, headers=headers) as client:
            response = await client.get(source); response.raise_for_status()
        if len(response.content) > MAX_BYTES: raise HTTPException(status_code=413, detail="附件超过 50MB 限制")
        filename = _safe_filename(Path(urllib.parse.urlparse(source).path).name, "法院私信附件")
        target = download_directory() / f"chat-preview-{uuid.uuid4().hex}-{filename}"
        target.write_bytes(response.content)
        return FileResponse(target, filename=filename)

    async def download_attachment(attachment_id: int) -> dict[str, Any]:
        with get_db() as conn:
            row = conn.execute("""SELECT a.*,r.kind,r.remote_id AS record_remote_id,r.linked_case_id
                                  FROM case_manager_court_online_attachments a
                                  JOIN case_manager_court_online_records r ON r.id=a.record_id
                                  WHERE a.id=? AND r.account_id=?""", (attachment_id, _active_account_id())).fetchone()
        if not row: raise HTTPException(status_code=404, detail="附件不存在")
        item = dict(row)
        if not item["source_url"]: raise HTTPException(status_code=409, detail="该附件尚未提供可下载地址，请在官网案件空间中查看")
        url = _validate_download_url(item["source_url"])
        token = _read_secret().get("session_token", "")
        headers = {"Authorization": token}
        if cookie_header := await browser_cookie_header(): headers["Cookie"] = cookie_header
        async with httpx.AsyncClient(timeout=60, follow_redirects=False, headers=headers) as client:
            response = await client.get(url); response.raise_for_status()
        if len(response.content) > MAX_BYTES: raise HTTPException(status_code=413, detail="附件超过 50MB 限制")
        content_type = response.headers.get("content-type", "")
        content_head = response.content.lstrip()[:64].lower()
        if "text/html" in content_type.lower() or content_head.startswith((b"<!doctype html", b"<html", b"<head")):
            raise HTTPException(status_code=502, detail="法院官网返回了网页而非文书，请重新登录后再下载")
        name = _document_filename(item["filename"], item["extension"], content_type)
        linked_case_id = int(item.get("linked_case_id") or 0)
        saved_to_case = False
        case_file_id = None
        target: Path
        if linked_case_id:
            # 已关联案件时，下载本身就是归档动作。这样“下载”和“下载全部”
            # 共享同一条路径选择规则，不会再落入一张网的默认目录。
            try:
                binding = get_folder_binding(get_db, linked_case_id, required=False)
                if binding.get("available"):
                    case_file = store_case_file(
                        get_db,
                        linked_case_id,
                        "court_document",
                        name,
                        response.content,
                        mime_type=content_type,
                        source_type="court_online_attachment",
                        source_id=attachment_id,
                        original_filename=str(item.get("filename") or name),
                        metadata={
                            "court_online_record_id": int(item.get("record_id") or 0),
                            "court_online_attachment_id": attachment_id,
                            "remote_id": str(item.get("remote_id") or ""),
                        },
                    )
                    target = Path(case_file["absolute_path"])
                    saved_to_case = True
                    case_file_id = int(case_file["id"])
                else:
                    log("warning", f"附件 #{attachment_id} 的关联案件文件夹不可用，已保存到一张网默认目录")
            except Exception as exc:
                # 下载不能因为已失效的案件绑定而丢失；保留既有的默认目录作为安全回退。
                log("warning", f"附件 #{attachment_id} 未能保存至关联案件文件夹：{getattr(exc, 'detail', exc)}")
        if not saved_to_case:
            target = download_directory() / f"{attachment_id}-{name}"
            target.write_bytes(response.content)
        with get_db() as conn:
            conn.execute("UPDATE case_manager_court_online_attachments SET staging_path=?,size_bytes=?,status='downloaded',downloaded_at=?,last_error='' WHERE id=?", (str(target), len(response.content), _now(), attachment_id)); conn.commit()
        return {
            "ok": True,
            "attachment_id": attachment_id,
            "filename": name,
            "size_bytes": len(response.content),
            "path": str(target),
            "linked_case_id": linked_case_id or None,
            "saved_to_case": saved_to_case,
            "case_file_id": case_file_id,
        }

    @app.post("/api/case-manager/court-online/attachments/{attachment_id}/download")
    async def download_one(attachment_id: int): return await download_attachment(attachment_id)

    @app.get("/api/case-manager/court-online/attachments/{attachment_id}/preview")
    async def preview_attachment(attachment_id: int):
        with get_db() as conn: row = conn.execute("SELECT a.staging_path FROM case_manager_court_online_attachments a JOIN case_manager_court_online_records r ON r.id=a.record_id WHERE a.id=? AND r.account_id=?", (attachment_id, _active_account_id())).fetchone()
        if not row: raise HTTPException(status_code=404, detail="附件不存在")
        if not row[0] or not Path(row[0]).is_file(): await download_attachment(attachment_id)
        with get_db() as conn: path = Path(conn.execute("SELECT a.staging_path FROM case_manager_court_online_attachments a JOIN case_manager_court_online_records r ON r.id=a.record_id WHERE a.id=? AND r.account_id=?", (attachment_id, _active_account_id())).fetchone()[0])
        return FileResponse(path, filename=path.name)

    @app.post("/api/case-manager/court-online/records/{record_id}/download-all")
    async def download_all(record_id: int):
        with get_db() as conn: ids = [int(row[0]) for row in conn.execute("SELECT a.id FROM case_manager_court_online_attachments a JOIN case_manager_court_online_records r ON r.id=a.record_id WHERE a.record_id=? AND r.account_id=?", (record_id, _active_account_id())).fetchall()]
        results = []
        for attachment_id in ids:
            try: results.append(await download_attachment(attachment_id))
            except Exception as exc: results.append({"attachment_id": attachment_id, "ok": False, "error": str(getattr(exc, "detail", exc))})
        return {"ok": all(item.get("ok") for item in results), "results": results}

    @app.post("/api/case-manager/court-online/attachments/{attachment_id}/archive")
    def archive_attachment(attachment_id: int, body: Dict[str, Any]):
        case_id = int(body.get("case_id") or 0)
        if not case_id: raise HTTPException(status_code=422, detail="请选择要归档的案件")
        with get_db() as conn:
            row = conn.execute("SELECT a.staging_path,a.filename FROM case_manager_court_online_attachments a JOIN case_manager_court_online_records r ON r.id=a.record_id WHERE a.id=? AND r.account_id=?", (attachment_id, _active_account_id())).fetchone()
        if not row or not row[0] or not Path(row[0]).is_file(): raise HTTPException(status_code=409, detail="请先下载附件")
        try: root = get_folder_binding(get_db, case_id, required=True)["real_path"]
        except HTTPException: raise HTTPException(status_code=409, detail="该案件尚未绑定本地文件夹")
        destination = Path(root) / COURT_DOCUMENT_SUBDIR; destination.mkdir(parents=False, exist_ok=True)
        source = Path(row[0])
        try:
            if source.resolve().parent == destination.resolve():
                return {"ok": True, "path": str(source), "already_archived": True}
        except OSError:
            pass
        target = destination / _safe_filename(row[1]); shutil.copy2(row[0], target)
        return {"ok": True, "path": str(target)}

    @app.get("/api/case-manager/court-online/logs")
    def get_logs():
        with get_db() as conn: return {"items": [dict(row) for row in conn.execute("SELECT * FROM case_manager_court_online_logs ORDER BY id DESC LIMIT 100").fetchall()]}

    @app.get("/api/case-manager/court-online/probe/routes")
    def list_probe_routes(q: str = "", limit: int = 200):
        limit = min(max(1, limit), 1000)
        clauses, params = ["1=1"], []
        if q.strip():
            clauses.append("url LIKE ?"); params.append(f"%{q.strip()}%")
        where = " AND ".join(clauses)
        with get_db() as conn:
            rows = conn.execute(f"SELECT method,url,status,hit_count,first_seen,last_seen,body_keys FROM case_manager_court_online_probe_routes WHERE {where} ORDER BY last_seen DESC LIMIT ?", [*params, limit]).fetchall()
            return {"items": [dict(row) for row in rows], "total": len(rows)}

    # 验证用只读白名单：参数在代码中固定，调用方不可传入任意参数，避免越权访问。
    PROBE_CALL_ROUTES: dict[str, tuple[str, str, dict[str, Any] | None]] = {
        "ajlist": ("POST", "/yzw-zxfw-ajfw/api/v1/ajlist", {"pageNum": 1, "pageSize": 100, "ajlb": "1501_000001-1000", "searchtext": "", "ajzt": "", "sfid": "", "sort": ""}),
        "kqtbaj": ("GET", "/yzw-zxfw-ajfw/api/v1/kqtbaj", None),
        "layy": ("GET", "/yzw-zxfw-lafw/api/v3/layy", {"limit": 10, "page": 1, "ajlb": "sp"}),
        "sxsq/page": ("GET", "/yzw-zxfw-sxfw/api/v3/sxsq/page", None),
        "user/info": ("GET", "/yzw-zxfw-sxfw/api/v1/user/info", None),
        "zhrl/list": ("POST", "/yzw-zxfw-xxfw/api/v1/zhrl/list", {"anyday": "", "isRc": "", "option": ""}),
    }
    probe_call_calls: list[float] = []

    @app.post("/api/case-manager/court-online/probe/call")
    async def probe_call(body: Dict[str, Any]):
        route = str(body.get("route") or "")
        if route not in PROBE_CALL_ROUTES:
            raise HTTPException(status_code=422, detail="未知的验证路由")
        now = time.monotonic()
        probe_call_calls[:] = [t for t in probe_call_calls if now - t < 60]
        if len(probe_call_calls) >= 10:
            raise HTTPException(status_code=429, detail="验证调用过于频繁，请稍后再试")
        probe_call_calls.append(now)
        method, path, payload = PROBE_CALL_ROUTES[route]
        token = _read_secret().get("session_token", "")
        if not token:
            raise HTTPException(status_code=401, detail="请先登录人民法院在线服务")
        headers = {"Authorization": token, "Accept": "application/json",
                   "Origin": COURT_ORIGIN, "Referer": f"{COURT_ORIGIN}/zxfw/"}
        if cookie_header := await browser_cookie_header():
            headers["Cookie"] = cookie_header
        async with httpx.AsyncClient(timeout=25, headers=headers, follow_redirects=False) as client:
            data = await court_json(client, path, payload or {}, method=method)
        return {"route": route, "data": data}

    @app.post("/api/case-manager/court-online/probe/browser")
    async def probe_browser(body: Dict[str, Any]):
        """在已登录的官网页面内同源复刻一个只读请求，用于参数验证。

        支持两种形态：path（GET，只读网关路径）或 route（白名单内
        接口，POST 参数由代码固定）。频率受限。
        """
        page = scheduler.get("browser_page")
        if not page or page.is_closed():
            raise HTTPException(status_code=409, detail="法院浏览器会话未打开，请先登录")
        now = time.monotonic()
        probe_call_calls[:] = [t for t in probe_call_calls if now - t < 60]
        if len(probe_call_calls) >= 10:
            raise HTTPException(status_code=429, detail="验证调用过于频繁，请稍后再试")
        probe_call_calls.append(now)
        route = str(body.get("route") or "")
        method, payload = "GET", None
        if route:
            if route not in PROBE_CALL_ROUTES:
                raise HTTPException(status_code=422, detail="未知的验证路由")
            method, path, payload = PROBE_CALL_ROUTES[route]
            method = "POST" if method == "POST" else "GET"
            path = f"/yzw{path}"
        else:
            path = str(body.get("path") or "")
            if not path.startswith("/yzw/"):
                raise HTTPException(status_code=422, detail="仅允许网关只读路径")
            if any(str(key).startswith(("sdbh", "ajbh", "qdbh")) for key, _ in urllib.parse.parse_qsl(urllib.parse.urlsplit(path).query)):
                raise HTTPException(status_code=422, detail="不允许携带业务编号参数")
        try:
            result = await page.evaluate(
                """async (opts) => {
                    const raw = localStorage.getItem('zxfwtoken') || '';
                    const token = String(raw).replace(/^\\"|\\"$/g, '');
                    const options = {method: opts.method, headers: {
                        Authorization: token, Accept: 'application/json', 'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest',
                    }};
                    if (opts.method === 'POST') options.body = JSON.stringify(opts.payload || {});
                    const response = await fetch(new URL(opts.path, location.origin).href, options);
                    const text = await response.text();
                    return {status: response.status, body: text.slice(0, 200000)};
                }""",
                {"method": method, "path": path, "payload": payload},
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"页面内请求失败：{exc}")
        return result

    async def keepalive_once() -> None:
        """保活探测：以低频轻量请求维持官网会话活跃，避免闲置被强制退出。

        优先在浏览器页面内发起请求——既验证会话有效性，也向官网传递页面
        活跃信号；页面内失败再回退到后端直接请求。会话过期时自动触发重新登录。
        """
        config = settings()
        if not config["enabled"]:
            return
        with get_db() as conn:
            last_sync_row = conn.execute("SELECT last_sync_at FROM case_manager_court_online_settings WHERE id=1").fetchone()
        last_sync_at = str(last_sync_row[0] or "") if last_sync_row else ""
        if last_sync_at:
            try:
                if time.time() - dt.datetime.fromisoformat(last_sync_at.replace("Z", "+00:00")).timestamp() < 240:
                    return
            except (ValueError, TypeError):
                pass
        secret = _read_secret()
        token = await persist_browser_token() or secret.get("session_token", "")
        page = scheduler.get("browser_page")
        context = scheduler.get("browser_context")
        if not context or not page or page.is_closed():
            # 浏览器窗口未打开：纯后端静默保活，不拉起可见窗口。
            # 会话有效则静默完成；失效时不打扰，由前端状态提示用户手动登录。
            status = await backend_session_probe(secret)
            if status == 200:
                return
            if status == 401:
                log("warning", "保活：官网会话已过期，请点击“登录官网”恢复")
            return
        if not token:
            if config["auto_login_enabled"] and config["credentials_configured"]:
                launch_login()
                log("warning", "保活：会话 token 缺失，已触发恢复登录")
            return
        try:
            page_status = await page.evaluate(
                """async () => {
                    const raw = localStorage.getItem('zxfwtoken') || '';
                    const token = String(raw).replace(/^\\"|\\"$/g, '');
                    try {
                        const response = await fetch('/yzw/yzw-zxfw-ajfw/api/v1/ajListByUserId', {
                            method: 'GET',
                            headers: {Authorization: token, Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
                        });
                        return response.status;
                    } catch (e) { return -1; }
                }"""
            )
            if page_status == 200:
                await persist_browser_token()
                return
            if page_status == 401:
                raise HTTPException(status_code=401, detail="会话已过期")
            headers = {"Authorization": token, "Accept": "application/json"}
            cookie_header = await browser_cookie_header()
            if cookie_header: headers["Cookie"] = cookie_header
            async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
                probe = await client.get(_validate_court_url(f"{COURT_API}/yzw-zxfw-ajfw/api/v1/ajListByUserId"), headers=headers)
            if probe.status_code == 200:
                await persist_browser_token()
                return
            if probe.status_code == 401:
                raise HTTPException(status_code=401, detail="会话已过期")
            log("warning", f"保活探测返回非预期状态：{probe.status_code}")
        except HTTPException as exc:
            if exc.status_code == 401 and config["auto_login_enabled"] and config["credentials_configured"]:
                launch_login()
                log("warning", "保活：官网会话已过期，已触发自动重新登录")
        except Exception as exc:
            log("warning", f"保活探测失败：{exc}")

    async def scheduler_loop() -> None:
        await asyncio.sleep(8)
        while True:
            if not (scheduler.get("sync_job") and not scheduler["sync_job"].done()) and not scheduler["sync_lock"].locked():
                start_sync_job(False)
            interval = int(settings().get("sync_interval_minutes") or 5)
            await asyncio.sleep(max(60, min(interval * 60, 86400)))

    async def keepalive_loop() -> None:
        await asyncio.sleep(60)
        while True:
            try: await keepalive_once()
            except Exception as exc: log("error", f"保活任务失败：{exc}")
            await asyncio.sleep(300)

    @app.on_event("startup")
    async def start_court_scheduler():
        if os.environ.get("COURT_ONLINE_SCHEDULER_DISABLED") != "1":
            if scheduler["task"] is None or scheduler["task"].done(): scheduler["task"] = asyncio.create_task(scheduler_loop())
            if scheduler.get("keepalive_task") is None or scheduler["keepalive_task"].done(): scheduler["keepalive_task"] = asyncio.create_task(keepalive_loop())

    @app.on_event("shutdown")
    async def stop_court_scheduler():
        for key in ("task", "login_task", "keepalive_task", "sync_job"):
            if scheduler.get(key): scheduler[key].cancel(); scheduler[key] = None
        connected = bool(scheduler.get("browser_connected"))
        context = scheduler.get("browser_context")
        if context:
            try: await context.close()
            except Exception: pass
        playwright = scheduler.get("playwright")
        if playwright:
            try: await playwright.stop()
            except Exception: pass
        scheduler.update({"browser_context": None, "browser_page": None, "playwright": None,
                          "browser_on_screen": False, "browser_connected": False, "browser_cdp_port": ""})
        await _terminate_background_browser(connected)
