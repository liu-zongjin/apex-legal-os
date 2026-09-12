"""明思智慧律所会议室预定的本地 APEX 适配器。

账号密码与明思访问令牌只保存在 macOS 钥匙串；浏览器只访问本地 APEX
接口，绝不直接得到凭据或明思 token。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Callable, Dict

from fastapi import HTTPException

from .mingsi_client import (
    KEYCHAIN_ACCOUNT,
    KEYCHAIN_SERVICE,
    MINGSI_API,
    MINGSI_HOST,
    MingsiClient,
    MingsiError,
    _account_id,
    _code_error,
    _delete_secret,
    _json,
    _now,
    _read_secret,
    _redact_account,
    _response_code,
    _validate_date,
    _validate_time,
    _write_secret,
)


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

    # Pass the module aliases explicitly so existing meeting-service tests or
    # embedders that patch the keychain helpers retain their seam.
    client = MingsiClient(read_secret=_read_secret, write_secret=_write_secret, delete_secret=_delete_secret)
    call_remote = client.call_remote
    login = client.login
    authenticated = client.authenticated
    profile = client.profile
    status = client.status

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
        client.clear_credentials()
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
