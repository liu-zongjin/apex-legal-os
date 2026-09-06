"""明思智慧律所会议室预定的本地 APEX 适配器。

账号密码与明思访问令牌只保存在 macOS 钥匙串；浏览器只访问本地 APEX
接口，绝不直接得到凭据或明思 token。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
from typing import Any, Callable, Dict

import httpx
from fastapi import HTTPException


MINGSI_API = "https://epmswebsvr.elawoffice.net/Elawoffice/"
MINGSI_HOST = "mingsi.elawoffice.net"
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
            capture_output=True, text=True, timeout=8,
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
            capture_output=True, text=True, timeout=8,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise MingsiError("无法写入 macOS 钥匙串") from exc
    if result.returncode:
        raise MingsiError("无法写入 macOS 钥匙串")


def _delete_secret() -> None:
    try:
        subprocess.run(["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT], capture_output=True, text=True, timeout=8)
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


def _meeting_list(data: Any) -> dict[str, Any]:
    payload = data.get("data") if isinstance(data, dict) else {}
    item = data.get("meetinglist") if isinstance(data, dict) else None
    if not isinstance(item, dict) and isinstance(payload, dict):
        item = payload.get("meetinglist")
    return item if isinstance(item, dict) else {"records": [], "total": 0, "current": 1}


def _time_part(value: Any) -> str:
    """将明思返回的纯时间或日期时间统一成 HH:MM。"""
    text = str(value or "").strip()
    if " " in text:
        text = text.rsplit(" ", 1)[-1]
    if "T" in text:
        text = text.rsplit("T", 1)[-1]
    return _validate_time(text, "会议时间") if text else ""


def register_mingsi_meeting_routes(app: Any, get_db: Callable[[], Any]) -> None:
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS mingsi_meeting_audit (
          id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
          account_id TEXT NOT NULL, meeting_id TEXT DEFAULT '', room_id TEXT DEFAULT '',
          meeting_date TEXT DEFAULT '', begin_time TEXT DEFAULT '', end_time TEXT DEFAULT '',
          outcome TEXT NOT NULL, message TEXT DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_mingsi_meeting_audit_account_time
          ON mingsi_meeting_audit(account_id, created_at DESC);
        """)
        conn.commit()

    async def call_remote(path: str, *, token: str = "", data: Any = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = token
        try:
            async with httpx.AsyncClient(base_url=MINGSI_API, timeout=15, headers=headers) as client:
                response = await client.post(path.lstrip("/"), json=data, params=params)
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException as exc:
            raise MingsiError("明思系统响应超时，请稍后重试", 504) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise MingsiError("无法连接明思系统") from exc
        if not isinstance(payload, dict):
            raise MingsiError("明思系统返回了无法识别的数据")
        return payload

    async def login(secret: dict[str, str]) -> dict[str, Any]:
        account, password = secret.get("account", ""), secret.get("password", "")
        if not account or not password:
            raise HTTPException(status_code=409, detail="请先在本页连接明思账号")
        response = await call_remote("/sys/login", data={
            "personname": account, "password": password, "corpId": secret.get("corp_id", ""),
            "openId": "", "appType": "web", "hostname": MINGSI_HOST,
        })
        code = _response_code(response)
        if code == -2:
            nested = response.get("data") if isinstance(response.get("data"), dict) else {}
            corps = response.get("corpList") or nested.get("corpList") or []
            return {"needs_corp": True, "corporations": corps, "message": "请选择所属机构后继续"}
        if code != 0:
            raise HTTPException(status_code=401, detail=_code_error(response))
        # 明思网页在登录成功后直接从响应根对象读取 token；data 仅承载
        # 用户/机构等业务数据。兼容少数部署将 token 放入 data 的情况。
        nested = response.get("data") if isinstance(response.get("data"), dict) else {}
        token = str(response.get("token") or nested.get("token") or "")
        if not token:
            raise MingsiError("明思登录成功但未返回访问令牌")
        secret["token"] = token
        _write_secret(secret)
        return {"ok": True}

    async def authenticated(path: str, *, data: Any = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
        secret = _read_secret()
        if not secret.get("token"):
            outcome = await login(secret)
            if outcome.get("needs_corp"):
                raise HTTPException(status_code=409, detail=outcome)
            secret = _read_secret()
        response = await call_remote(path, token=secret.get("token", ""), data=data, params=params)
        if _response_code(response) == 401:
            secret["token"] = ""
            _write_secret(secret)
            outcome = await login(secret)
            if outcome.get("needs_corp"):
                raise HTTPException(status_code=409, detail=outcome)
            response = await call_remote(path, token=_read_secret().get("token", ""), data=data, params=params)
        if _response_code(response) != 0:
            raise HTTPException(status_code=502, detail=_code_error(response))
        return response

    async def profile() -> dict[str, Any]:
        response = await authenticated("/sys/epmsperson/getLoginPerson")
        data = response.get("data") if isinstance(response.get("data"), dict) else {}
        person = response.get("person") if isinstance(response, dict) else None
        if not isinstance(person, dict) and isinstance(data, dict):
            person = data.get("person")
        return person if isinstance(person, dict) else {}

    def status() -> dict[str, Any]:
        secret = _read_secret()
        return {
            "configured": bool(secret.get("account") and secret.get("password")),
            "connected": bool(secret.get("token")),
            "account": _redact_account(secret.get("account", "")),
            "account_id": _account_id(secret.get("account", "")) if secret.get("account") else "",
        }

    @app.get("/api/mingsi-meetings/status")
    def get_status():
        return status()

    @app.post("/api/mingsi-meetings/credentials")
    async def save_credentials(body: Dict[str, Any]):
        account, password = str(body.get("account") or "").strip(), str(body.get("password") or "")
        corp_id = str(body.get("corp_id") or "").strip()
        if not account or not password:
            raise HTTPException(status_code=422, detail="请输入明思账号和密码")
        _write_secret({"account": account, "password": password, "corp_id": corp_id, "token": ""})
        outcome = await login(_read_secret())
        return {**status(), **outcome}

    @app.delete("/api/mingsi-meetings/credentials")
    def clear_credentials():
        _delete_secret()
        return {"ok": True}

    @app.get("/api/mingsi-meetings/bootstrap")
    async def bootstrap():
        person = await profile()
        rooms = await authenticated("/case/meeting/getMeetingRoomList", params={"roomstate": 1})
        person_id = person.get("personid") or person.get("id") or ""
        approvers: list[Any] = []
        if person_id:
            result = await authenticated("/case/meeting/getAuditor", params={"personid": person_id})
            payload = result.get("data", {}) if isinstance(result.get("data"), dict) else {}
            listing = result.get("list") if isinstance(result, dict) else None
            if not isinstance(listing, (list, dict)) and isinstance(payload, dict):
                listing = payload.get("list", [])
            if isinstance(listing, dict):
                listing = listing.get("epmsPersonEntityList", [])
            approvers = listing if isinstance(listing, list) else []
        room_data = rooms.get("data", {}) if isinstance(rooms.get("data"), dict) else {}
        room_list = rooms.get("meetingroomlist") if isinstance(rooms, dict) else None
        if not isinstance(room_list, list) and isinstance(room_data, dict):
            room_list = room_data.get("meetingroomlist", [])
        return {"status": status(), "person": person, "rooms": room_list if isinstance(room_list, list) else [], "approvers": approvers}

    @app.get("/api/mingsi-meetings/meetings")
    async def meetings(page: int = 1, limit: int = 20):
        # 与明思原网页 /MyMeeting 保持相同的查询参数。
        result = await authenticated("/case/meeting/getMeetingFlowList", data={
            "page": max(1, page), "limit": min(max(1, limit), 100),
            "querytype": "apply",
        })
        return _meeting_list(result)

    @app.get("/api/mingsi-meetings/schedule")
    async def schedule(meeting_date: str):
        """返回指定日期全部会议室的占用时段，不向页面暴露申请人信息。"""
        day = _validate_date(meeting_date)
        result = await authenticated("/case/meeting/getMeetingFlowList", data={
            "page": 1, "limit": 200, "querytype": "calendar",
            "applydatestart": f"{day} 00:00", "applydateend": f"{day} 23:59",
        })
        records = _meeting_list(result).get("records", [])
        events = []
        for item in records if isinstance(records, list) else []:
            if not isinstance(item, dict):
                continue
            room_id = str(item.get("meetingroomid") or "")
            begin = _time_part(item.get("meetingbegintime"))
            end = _time_part(item.get("meetingendtime"))
            if room_id and begin and end:
                events.append({"room_id": room_id, "begin_time": begin, "end_time": end})
        return {"meeting_date": day, "events": events}

    @app.post("/api/mingsi-meetings/availability")
    async def availability(body: Dict[str, Any]):
        meeting_date = _validate_date(body.get("meeting_date"))
        begin = _validate_time(body.get("begin_time"), "开始时间")
        end = _validate_time(body.get("end_time"), "结束时间")
        if begin >= end:
            raise HTTPException(status_code=422, detail="结束时间必须晚于开始时间")
        room_id = str(body.get("room_id") or "").strip()
        if not room_id:
            raise HTTPException(status_code=422, detail="请选择会议室")
        result = await authenticated("/case/meeting/checkMeetingCanBook", params={
            "meetingid": int(body.get("meeting_id") or 0), "meetingroomid": room_id,
            "meetingbookdate": meeting_date, "begintime": begin, "endtime": end,
        })
        payload = result.get("data", {}) if isinstance(result.get("data"), dict) else {}
        available = result.get("result") if isinstance(result, dict) else None
        if available is None and isinstance(payload, dict):
            available = payload.get("result")
        return {"available": bool(available), "message": "可预定" if available else "该时段已被预定"}

    @app.post("/api/mingsi-meetings/meetings")
    async def create_meeting(body: Dict[str, Any]):
        meeting_date = _validate_date(body.get("meeting_date"))
        begin, end = _validate_time(body.get("begin_time"), "开始时间"), _validate_time(body.get("end_time"), "结束时间")
        room_id, room_name = str(body.get("room_id") or "").strip(), str(body.get("room_name") or "").strip()
        subject = str(body.get("subject") or "").strip()
        if not room_id or not subject or begin >= end:
            raise HTTPException(status_code=422, detail="请完整填写会议事宜、会议室和有效使用时段")
        checked = await availability({"meeting_date": meeting_date, "begin_time": begin, "end_time": end, "room_id": room_id})
        if not checked["available"]:
            raise HTTPException(status_code=409, detail=checked["message"])
        person = await profile()
        approver_ids = body.get("approver_ids") if isinstance(body.get("approver_ids"), list) else []
        entity = {
            "meetingid": None, "meetingmetter": subject, "meetingbookdate": meeting_date,
            "meetingmembers": str(body.get("members") or "").strip(), "meetingbegintime": begin, "meetingendtime": end,
            "remark": str(body.get("remark") or "").strip(), "meetingroomid": room_id, "meetingroomname": room_name,
            "applypsnid": person.get("personid") or person.get("id"), "applypsnname": person.get("personname") or person.get("name"),
            "nowauditor": None, "nowauditorname": "", "approveperson": approver_ids, "approvalstatus": 0,
            "tempmeetingmettertype": [str(body.get("meeting_type") or "其他")], "meetingmettertype": str(body.get("meeting_type") or "其他"), "meetingTimeStr": "",
        }
        account_id = _account_id(_read_secret().get("account", ""))
        try:
            result = await authenticated("/case/meeting/saveMeeting", data={"meetingEntity": entity, "auditorlist": approver_ids, "attachfilesEntities": [], "redoflag": 0})
            raw = result.get("data", {}) if isinstance(result.get("data"), dict) else result
            meeting_id = str(raw.get("meetingid") or raw.get("id") or "")
            outcome, message = "success", _code_error(result) if result.get("msg") else "提交成功"
        except HTTPException as exc:
            outcome, message = "failed", str(exc.detail)
            with get_db() as conn:
                conn.execute("INSERT INTO mingsi_meeting_audit(created_at,account_id,room_id,meeting_date,begin_time,end_time,outcome,message) VALUES(?,?,?,?,?,?,?,?)", (_now(), account_id, room_id, meeting_date, begin, end, outcome, message[:500]))
                conn.commit()
            raise
        with get_db() as conn:
            conn.execute("INSERT INTO mingsi_meeting_audit(created_at,account_id,meeting_id,room_id,meeting_date,begin_time,end_time,outcome,message) VALUES(?,?,?,?,?,?,?,?,?)", (_now(), account_id, meeting_id, room_id, meeting_date, begin, end, outcome, message[:500]))
            conn.commit()
        return {"ok": True, "meeting_id": meeting_id, "message": message}

    @app.get("/api/mingsi-meetings/audit")
    def audit(limit: int = 30):
        account_id = _account_id(_read_secret().get("account", ""))
        with get_db() as conn:
            rows = conn.execute("SELECT created_at,meeting_id,room_id,meeting_date,begin_time,end_time,outcome,message FROM mingsi_meeting_audit WHERE account_id=? ORDER BY id DESC LIMIT ?", (account_id, min(max(1, limit), 100))).fetchall()
        return {"records": [dict(row) for row in rows]}
