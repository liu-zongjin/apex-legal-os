"""Shared local client for the MingSi (明思) web API.

The browser only talks to the local APEX server.  MingSi credentials and its
short-lived access token stay in the macOS keychain, which lets meeting-room
booking and chapter/seal applications share login and token-refresh behavior.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
from typing import Any

import httpx
from fastapi import HTTPException


MINGSI_API = "https://epmswebsvr.elawoffice.net/Elawoffice/"
MINGSI_HOST = "mingsi.elawoffice.net"
# Keep this service/account pair stable: existing meeting-room credentials
# must remain usable after the client is shared with other MingSi features.
KEYCHAIN_SERVICE = "APEX · 明思会议室预定"
KEYCHAIN_ACCOUNT = "mingsi-meeting-v1"


class MingsiError(HTTPException):
    def __init__(self, detail: str, status_code: int = 502):
        super().__init__(status_code=status_code, detail=detail)


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _redact_account(account: str) -> str:
    value = str(account or "").strip()
    if len(value) <= 3:
        return "*" * len(value)
    return f"{value[:2]}{'*' * max(2, len(value) - 4)}{value[-2:]}"


def _read_secret() -> dict[str, str]:
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if result.returncode:
            return {}
        value = json.loads(result.stdout)
        return {str(key): str(item or "") for key, item in value.items()} if isinstance(value, dict) else {}
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return {}


def _write_secret(value: dict[str, str]) -> None:
    payload = {key: str(value.get(key) or "") for key in ("account", "password", "token", "corp_id")}
    try:
        result = subprocess.run(
            ["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w", _json(payload)],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise MingsiError("无法写入 macOS 钥匙串") from exc
    if result.returncode:
        raise MingsiError("无法写入 macOS 钥匙串")


def _delete_secret() -> None:
    try:
        subprocess.run(
            ["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def _account_id(account: str) -> str:
    return "acct_" + hashlib.sha256(str(account).encode("utf-8")).hexdigest()[:16]


def _validate_date(value: Any) -> str:
    text = str(value or "").strip()
    try:
        return dt.date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="预定日期格式应为 YYYY-MM-DD") from exc


def _validate_time(value: Any, field: str) -> str:
    text = str(value or "").strip()
    try:
        dt.time.fromisoformat(text)
        return text[:5]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{field}格式应为 HH:MM") from exc


def _code_error(data: Any) -> str:
    if isinstance(data, dict):
        return str(data.get("msg") or data.get("message") or "明思系统返回异常")
    return "明思系统返回异常"


def _response_code(data: dict[str, Any]) -> int:
    value = data.get("code", -1)
    try:
        return int(-1 if value is None else value)
    except (TypeError, ValueError):
        return -1


class MingsiClient:
    """A small authenticated API adapter shared by local APEX routes."""

    def __init__(self, *, read_secret=_read_secret, write_secret=_write_secret, delete_secret=_delete_secret):
        # Dependency injection also keeps all remote calls deterministic in
        # service tests, without ever putting real credentials in fixtures.
        self._read_secret = read_secret
        self._write_secret = write_secret
        self._delete_secret = delete_secret

    async def call_remote(
        self,
        path: str,
        *,
        token: str = "",
        data: Any = None,
        params: dict[str, Any] | None = None,
        files: Any = None,
    ) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if files is None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = token
        try:
            async with httpx.AsyncClient(base_url=MINGSI_API, timeout=15, headers=headers) as client:
                if files is None:
                    response = await client.post(path.lstrip("/"), json=data, params=params)
                else:
                    response = await client.post(path.lstrip("/"), data=data or {}, files=files, params=params)
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException as exc:
            raise MingsiError("明思系统响应超时，请稍后重试", 504) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise MingsiError("无法连接明思系统") from exc
        if not isinstance(payload, dict):
            raise MingsiError("明思系统返回了无法识别的数据")
        return payload

    async def login(self, secret: dict[str, str]) -> dict[str, Any]:
        account, password = secret.get("account", ""), secret.get("password", "")
        if not account or not password:
            raise HTTPException(status_code=409, detail="请先在本页连接明思账号")
        response = await self.call_remote("/sys/login", data={
            "personname": account,
            "password": password,
            "corpId": secret.get("corp_id", ""),
            "openId": "",
            "appType": "web",
            "hostname": MINGSI_HOST,
        })
        code = _response_code(response)
        if code == -2:
            nested = response.get("data") if isinstance(response.get("data"), dict) else {}
            corps = response.get("corpList") or nested.get("corpList") or []
            return {"needs_corp": True, "corporations": corps, "message": "请选择所属机构后继续"}
        if code != 0:
            raise HTTPException(status_code=401, detail=_code_error(response))
        nested = response.get("data") if isinstance(response.get("data"), dict) else {}
        token = str(response.get("token") or nested.get("token") or "")
        if not token:
            raise MingsiError("明思登录成功但未返回访问令牌")
        secret["token"] = token
        self._write_secret(secret)
        return {"ok": True}

    async def authenticated(
        self,
        path: str,
        *,
        data: Any = None,
        params: dict[str, Any] | None = None,
        files: Any = None,
    ) -> dict[str, Any]:
        secret = self._read_secret()
        if not secret.get("token"):
            outcome = await self.login(secret)
            if outcome.get("needs_corp"):
                raise HTTPException(status_code=409, detail=outcome)
            secret = self._read_secret()
        response = await self.call_remote(path, token=secret.get("token", ""), data=data, params=params, files=files)
        if _response_code(response) == 401:
            secret["token"] = ""
            self._write_secret(secret)
            outcome = await self.login(secret)
            if outcome.get("needs_corp"):
                raise HTTPException(status_code=409, detail=outcome)
            response = await self.call_remote(
                path,
                token=self._read_secret().get("token", ""),
                data=data,
                params=params,
                files=files,
            )
        if _response_code(response) != 0:
            raise HTTPException(status_code=502, detail=_code_error(response))
        return response

    async def profile(self) -> dict[str, Any]:
        response = await self.authenticated("/sys/epmsperson/getLoginPerson")
        data = response.get("data") if isinstance(response.get("data"), dict) else {}
        person = response.get("person") if isinstance(response, dict) else None
        if not isinstance(person, dict) and isinstance(data, dict):
            person = data.get("person")
        return person if isinstance(person, dict) else {}

    def status(self) -> dict[str, Any]:
        secret = self._read_secret()
        return {
            "configured": bool(secret.get("account") and secret.get("password")),
            "connected": bool(secret.get("token")),
            "account": _redact_account(secret.get("account", "")),
            "account_id": _account_id(secret.get("account", "")) if secret.get("account") else "",
        }

    def clear_credentials(self) -> None:
        self._delete_secret()
