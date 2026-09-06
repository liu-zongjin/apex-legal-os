"""Import article links submitted through a Feishu Bitable form.

The form is deliberately pull-based: Feishu keeps submissions while the local
legal system is offline, and this module imports them on the next startup.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import HTTPException, Request


CONFIG_PATH = Path(__file__).resolve().parent.parent / "local_feishu_article_config.json"
FEISHU_FIELDS = {
    "url": "文章链接",
    "status": "同步状态",
    "article_id": "本地文章编号",
    "synced_at": "同步时间",
    "note": "同步说明",
}
REQUIRED_FIELDS = set(FEISHU_FIELDS.values())


def _sync_interval_seconds() -> float:
    """Keep mobile form submissions responsive without over-polling Feishu."""
    try:
        return max(15.0, min(float(os.environ.get("FEISHU_ARTICLE_SYNC_INTERVAL_SECONDS", "30")), 300.0))
    except ValueError:
        return 30.0


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "".join(_text(item) for item in value).strip()
    if isinstance(value, dict):
        for key in ("text", "link", "url", "value", "name"):
            if key in value:
                return _text(value[key])
        return "".join(_text(item) for item in value.values()).strip()
    return str(value).strip()


def _field_url(value: Any) -> str:
    if isinstance(value, list):
        for item in value:
            url = _field_url(item)
            if url:
                return url
        return ""
    if isinstance(value, dict):
        for key in ("link", "url", "text", "value"):
            url = _field_url(value.get(key))
            if url:
                return url
        return ""
    value = _text(value)
    return value if value.startswith(("https://", "http://")) else ""


def _read_config() -> Dict[str, str]:
    try:
        return {str(k): _text(v) for k, v in json.loads(CONFIG_PATH.read_text(encoding="utf-8")).items()}
    except Exception:
        return {}


def _write_config(config: Dict[str, str]) -> None:
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _parse_base_url(value: str) -> Tuple[str, str]:
    parsed = urlparse(value if "://" in value else f"https://{value}")
    parts = [part for part in parsed.path.split("/") if part]
    try:
        app_token = parts[parts.index("base") + 1]
    except (ValueError, IndexError):
        app_token = ""
    table_id = (parse_qs(parsed.query).get("table") or [""])[0]
    if not app_token or not table_id:
        raise HTTPException(status_code=400, detail="请填写多维表格编辑页链接，链接中须同时包含 /base/ 和 table=tbl…")
    return app_token, table_id


def _settings(config: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    config = config or _read_config()
    secret = config.get("app_secret", "")
    return {
        "configured": bool(config.get("app_id") and secret and config.get("app_token") and config.get("table_id")),
        "app_id": config.get("app_id", ""),
        "app_secret_configured": bool(secret),
        "app_secret_masked": f"{secret[:3]}••••••{secret[-3:]}" if len(secret) > 6 else ("••••••••" if secret else ""),
        "base_url": config.get("base_url", ""),
        "form_url": config.get("form_url", ""),
    }


def ensure_schema(get_db: Callable[[], Any]) -> None:
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS feishu_article_imports (
                source_record_id TEXT PRIMARY KEY,
                article_id INTEGER,
                source_url TEXT NOT NULL,
                source_payload_hash TEXT NOT NULL,
                imported_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS feishu_article_sync_issues (
                source_record_id TEXT PRIMARY KEY,
                source_payload_hash TEXT NOT NULL,
                error_message TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS feishu_article_sync_state (
                id INTEGER PRIMARY KEY CHECK(id=1),
                last_attempt_at TEXT DEFAULT '', last_success_at TEXT DEFAULT '',
                last_result_json TEXT DEFAULT '{}', last_error TEXT DEFAULT '', updated_at TEXT NOT NULL
            );
        """)
        conn.execute("""INSERT OR IGNORE INTO feishu_article_sync_state
            (id,last_attempt_at,last_success_at,last_result_json,last_error,updated_at)
            VALUES (1,'','','{}','',?)""", (_now(),))
        conn.commit()


class FeishuArticleSync:
    def __init__(self, get_db: Callable[[], Any], import_url: Callable[[str], Awaitable[Dict[str, Any]]]):
        self.get_db, self.import_url = get_db, import_url
        self.lock: Optional[asyncio.Lock] = None
        self._token, self._token_expires_at = "", 0.0

    async def _token_for(self, client: httpx.AsyncClient, config: Dict[str, str]) -> str:
        now = asyncio.get_running_loop().time()
        if self._token and now < self._token_expires_at - 300:
            return self._token
        response = await client.post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal", json={"app_id": config["app_id"], "app_secret": config["app_secret"]})
        payload = self._response(response, "飞书身份验证失败")
        self._token = _text(payload.get("tenant_access_token"))
        if not self._token:
            raise RuntimeError("飞书未返回访问凭证")
        self._token_expires_at = now + int(payload.get("expire") or 7200)
        return self._token

    @staticmethod
    def _response(response: httpx.Response, fallback: str) -> Dict[str, Any]:
        try:
            payload = response.json()
        except Exception:
            payload = {}
        if response.status_code >= 400 or payload.get("code") not in (None, 0):
            raise RuntimeError(_text(payload.get("msg")) or fallback)
        return payload

    async def _records(self, client: httpx.AsyncClient, token: str, config: Dict[str, str]) -> List[Dict[str, Any]]:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{config['app_token']}/tables/{config['table_id']}/records/search"
        records: List[Dict[str, Any]] = []
        page_token = ""
        while True:
            params: Dict[str, Any] = {"page_size": 500}
            if page_token:
                params["page_token"] = page_token
            data = self._response(await client.post(url, headers={"Authorization": f"Bearer {token}"}, params=params, json={"automatic_fields": True}), "无法读取飞书表单记录").get("data", {})
            records.extend(data.get("items") or [])
            if not data.get("has_more"):
                return records
            page_token = _text(data.get("page_token"))
            if not page_token:
                return records

    async def verify(self, config: Dict[str, str]) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=20.0) as client:
            token = await self._token_for(client, config)
            url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{config['app_token']}/tables/{config['table_id']}/fields"
            items = self._response(await client.get(url, headers={"Authorization": f"Bearer {token}"}), "无法读取多维表格字段").get("data", {}).get("items", [])
        missing = sorted(REQUIRED_FIELDS - {item.get("field_name") for item in items})
        if missing:
            raise HTTPException(status_code=400, detail=f"多维表格缺少字段：{'、'.join(missing)}")
        return {"ok": True, "message": "连接成功，表单字段与读取权限检查通过"}

    async def _writeback(self, client: httpx.AsyncClient, token: str, config: Dict[str, str], updates: List[Dict[str, Any]]) -> None:
        if not updates:
            return
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{config['app_token']}/tables/{config['table_id']}/records/batch_update"
        for index in range(0, len(updates), 500):
            self._response(await client.post(url, headers={"Authorization": f"Bearer {token}"}, json={"records": updates[index:index + 500]}), "无法回写飞书同步状态")

    async def sync(self) -> Dict[str, Any]:
        if self.lock is None:
            self.lock = asyncio.Lock()
        if self.lock.locked():
            return {"ok": True, "busy": True, "message": "飞书文章正在同步"}
        async with self.lock:
            config = _read_config()
            if not _settings(config)["configured"]:
                return {"ok": False, "configured": False, "message": "尚未配置飞书文章表单"}
            result = {"imported": 0, "duplicate": 0, "existing": 0, "invalid": 0, "writeback": 0}
            with self.get_db() as conn:
                conn.execute("UPDATE feishu_article_sync_state SET last_attempt_at=?,updated_at=? WHERE id=1", (_now(), _now()))
                conn.commit()
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    token = await self._token_for(client, config)
                    updates = []
                    for record in await self._records(client, token, config):
                        record_id, fields = _text(record.get("record_id")), record.get("fields") or {}
                        if not record_id:
                            continue
                        url = _field_url(fields.get(FEISHU_FIELDS["url"]))
                        fingerprint = hashlib.sha256(url.encode("utf-8")).hexdigest()
                        if not url:
                            result["invalid"] += 1
                            message = "请填写有效的 http:// 或 https:// 文章链接"
                            self._save_issue(record_id, fingerprint, message)
                            updates.append(self._update(record_id, "需修正", "", message))
                            continue
                        with self.get_db() as conn:
                            imported = conn.execute("SELECT article_id FROM feishu_article_imports WHERE source_record_id=?", (record_id,)).fetchone()
                            issue = conn.execute("SELECT source_payload_hash,error_message FROM feishu_article_sync_issues WHERE source_record_id=?", (record_id,)).fetchone()
                        if imported:
                            result["existing"] += 1
                            updates.append(self._update(record_id, "已同步", str(imported["article_id"] or ""), "已收录"))
                            continue
                        if issue and issue["source_payload_hash"] == fingerprint:
                            result["invalid"] += 1
                            updates.append(self._update(record_id, "需修正", "", issue["error_message"]))
                            continue
                        try:
                            saved = await self.import_url(url)
                            article_id = saved.get("id")
                            duplicate = bool(saved.get("duplicate"))
                            if saved.get("ai_summary_pending"):
                                # 正文已经安全入库，但 AI 摘要尚未成功。不要写入
                                # imported 表，否则以后会被 existing 分支永久跳过。
                                result["invalid"] += 1
                                updates.append(self._update(
                                    record_id,
                                    "摘要待重试",
                                    str(article_id or ""),
                                    "正文已收录，AI 摘要将在下一轮自动重试",
                                ))
                                continue
                            if duplicate:
                                result["duplicate"] += 1
                            else:
                                result["imported"] += 1
                            self._save_import(record_id, article_id, url, fingerprint)
                            updates.append(self._update(record_id, "已同步", str(article_id or ""), "已存在" if duplicate else "已收录"))
                        except Exception as exc:
                            result["invalid"] += 1
                            message = str(getattr(exc, "detail", exc))[:500] or "文章解析失败"
                            self._save_issue(record_id, fingerprint, message)
                            updates.append(self._update(record_id, "需修正", "", message))
                    await self._writeback(client, token, config, updates)
                    result["writeback"] = len(updates)
                stamp = _now()
                with self.get_db() as conn:
                    conn.execute("UPDATE feishu_article_sync_state SET last_success_at=?,last_result_json=?,last_error='',updated_at=? WHERE id=1", (stamp, json.dumps(result, ensure_ascii=False), stamp))
                    conn.commit()
                return {"ok": True, **result, "last_success_at": stamp}
            except Exception as exc:
                message = str(exc)[:500] or "飞书文章同步失败"
                with self.get_db() as conn:
                    conn.execute("UPDATE feishu_article_sync_state SET last_result_json=?,last_error=?,updated_at=? WHERE id=1", (json.dumps(result, ensure_ascii=False), message, _now()))
                    conn.commit()
                return {"ok": False, **result, "message": message}

    def _save_import(self, record_id: str, article_id: Any, url: str, fingerprint: str) -> None:
        with self.get_db() as conn:
            conn.execute("INSERT OR REPLACE INTO feishu_article_imports(source_record_id,article_id,source_url,source_payload_hash,imported_at) VALUES (?,?,?,?,?)", (record_id, article_id, url, fingerprint, _now()))
            conn.execute("DELETE FROM feishu_article_sync_issues WHERE source_record_id=?", (record_id,))
            conn.commit()

    def _save_issue(self, record_id: str, fingerprint: str, message: str) -> None:
        with self.get_db() as conn:
            conn.execute("INSERT INTO feishu_article_sync_issues(source_record_id,source_payload_hash,error_message,updated_at) VALUES (?,?,?,?) ON CONFLICT(source_record_id) DO UPDATE SET source_payload_hash=excluded.source_payload_hash,error_message=excluded.error_message,updated_at=excluded.updated_at", (record_id, fingerprint, message, _now()))
            conn.commit()

    @staticmethod
    def _update(record_id: str, status: str, article_id: str, note: str) -> Dict[str, Any]:
        # The provisioned Bitable uses text fields so it works without any
        # extra field-type setup in Feishu; dates must therefore be text too.
        return {"record_id": record_id, "fields": {FEISHU_FIELDS["status"]: status, FEISHU_FIELDS["article_id"]: article_id, FEISHU_FIELDS["synced_at"]: _now(), FEISHU_FIELDS["note"]: note}}


def register_feishu_article_routes(app: Any, get_db: Callable[[], Any], import_url: Callable[[str], Awaitable[Dict[str, Any]]]) -> None:
    ensure_schema(get_db)
    syncer, scheduler_task = FeishuArticleSync(get_db, import_url), None

    @app.get("/api/articles/feishu-settings")
    def get_settings():
        return _settings()

    @app.put("/api/articles/feishu-settings")
    async def put_settings(request: Request):
        body, previous = await request.json(), _read_config()
        base_url = _text(body.get("base_url"))
        app_token, table_id = _parse_base_url(base_url)
        secret = _text(body.get("app_secret"))
        if not secret or "•" in secret:
            secret = previous.get("app_secret", "")
        config = {"app_id": _text(body.get("app_id")), "app_secret": secret, "base_url": base_url, "form_url": _text(body.get("form_url")), "app_token": app_token, "table_id": table_id}
        if not config["app_id"] or not config["app_secret"]:
            raise HTTPException(status_code=400, detail="请填写飞书 App ID 和 App Secret")
        syncer._token = ""
        verified = await syncer.verify(config) if body.get("verify", True) else {"ok": True, "message": "设置已保存"}
        # Keep the working configuration intact when users accidentally paste
        # another Bitable's link or the Feishu validation fails.
        _write_config(config)
        return {**_settings(config), "verification": verified}

    @app.post("/api/articles/feishu-sync")
    async def sync_articles():
        return await syncer.sync()

    async def scheduler_loop() -> None:
        # The first run makes submissions made while the Mac was powered off
        # available as soon as the legal system starts.  Subsequent short polls
        # cover links submitted while it stays open.
        await asyncio.sleep(1)
        while True:
            try:
                if _settings()["configured"]:
                    await syncer.sync()
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            await asyncio.sleep(_sync_interval_seconds())

    @app.on_event("startup")
    async def start_scheduler():
        nonlocal scheduler_task
        if scheduler_task is None or scheduler_task.done():
            scheduler_task = asyncio.create_task(scheduler_loop())

    @app.on_event("shutdown")
    async def stop_scheduler():
        nonlocal scheduler_task
        if scheduler_task:
            scheduler_task.cancel()
            try:
                await scheduler_task
            except asyncio.CancelledError:
                pass
            scheduler_task = None
