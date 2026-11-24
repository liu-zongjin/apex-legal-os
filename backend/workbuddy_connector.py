"""Stella's opt-in, same-machine, read-only WorkBuddy connector."""

from datetime import date
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
from threading import Lock
from typing import Literal, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, StrictBool, conint, constr

from .database import read_snapshot
from .workbuddy_stdio import MAX_MESSAGE, RECORD_KINDS, TOOLS
from .workbuddy_data import read_user_data, readable_data


CONNECTOR_ID = "stella-local"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
SCOPES = ("knowledge", "cases", "schedule", *dict.fromkeys(scope for scope, _ in RECORD_KINDS.values()))
REQUIRED = {
    "stella_search_knowledge": ("knowledge",),
    "stella_find_cases": ("cases", "schedule", "contacts", "case_records", "case_materials", "deadlines", "documents"),
    "stella_get_case": ("cases",),
    "stella_list_schedule": ("schedule",),
}
ACTIVE_CASES = "COALESCE(c.source_status, 'active') IN ('active', 'archived')"
CASE_COLUMNS = "c.id,c.title,c.case_type,c.current_stage,c.source_status,c.case_kind,c.series_code,c.series_display_name"


class Permissions(BaseModel):
    knowledge: StrictBool = True
    cases: StrictBool = False
    schedule: StrictBool = False
    article_details: StrictBool = False
    contacts: StrictBool = False
    case_records: StrictBool = False
    case_materials: StrictBool = False
    deadlines: StrictBool = False
    business_finance: StrictBool = False
    documents: StrictBool = False
    saved_memories: StrictBool = False


class Query(BaseModel):
    query: constr(strict=True, strip_whitespace=True, min_length=1, max_length=160)


class CaseQuery(BaseModel):
    case_id: conint(strict=True, ge=1, le=9223372036854775807)


class ScheduleQuery(BaseModel):
    case_id: Optional[conint(strict=True, ge=1, le=9223372036854775807)] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    kind: Literal["all", "hearing", "todo"] = "all"
    sort: Literal["earliest", "latest"] = "earliest"
    count_only: StrictBool = False
    group_by: Literal["type", "month"] = "type"


class RecordFilters(BaseModel):
    case_id: Optional[conint(strict=True, ge=1, le=9223372036854775807)] = None
    article_id: Optional[conint(strict=True, ge=1, le=9223372036854775807)] = None
    record_id: Optional[conint(strict=True, ge=1, le=9223372036854775807)] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    query: Optional[constr(strict=True, strip_whitespace=True, min_length=1, max_length=160)] = None
    offset: conint(strict=True, ge=0, le=100000) = 0
    limit: conint(strict=True, ge=1, le=12) = 8
    char_offset: Optional[conint(strict=True, ge=0, le=2147483647)] = None


def _local_port(request, browser=False):
    host = urlsplit(str(request.base_url))
    if (not request.client or request.client.host not in LOCAL_HOSTS
            or host.hostname not in LOCAL_HOSTS
            or any(header in request.headers for header in ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto"))):
        raise HTTPException(403, "请在同一台电脑上使用 Stella 连接器。")
    origin = request.headers.get("origin")
    if browser and request.method != "GET" and origin != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "请从 Stella 的设置页面操作。")
    if not browser and (origin is not None or request.headers.get("sec-fetch-site")):
        raise HTTPException(403, "该入口仅供本机 WorkBuddy 连接器调用。")
    return request.scope["server"][1]


def _atomic_write(target, data, original=None):
    prior_mode = target.stat().st_mode & 0o777 if original else 0o600
    fd, temporary = tempfile.mkstemp(prefix=".stella-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            if hasattr(os, "fchmod"):
                os.fchmod(handle.fileno(), prior_mode)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if original is not None and (target.read_bytes() if target.exists() else b"") != original:
            raise ValueError("WorkBuddy 配置刚被修改，请重试。")
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _installation_launcher():
    configured = os.environ.get("STELLA_WORKBUDDY_LAUNCHER")
    if configured and Path(configured).is_absolute() and Path(configured).exists():
        if sys.platform == "darwin":
            return ["/usr/bin/open", "-g", configured]
        if sys.platform == "win32":
            return [configured]
    if sys.platform == "darwin" and os.environ.get("STELLA_WORKBUDDY_PRIVATE_AGENT") == "1":
        return ["/bin/launchctl", "kickstart", "gui/%d/com.liuzongjin.legalkb.private" % os.getuid()]
    return []


def _open_workbuddy():
    if sys.platform == "darwin":
        subprocess.run(
            ["/usr/bin/open", "-b", "com.tencent.workbuddy.mac"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=5, check=True,
        )
    elif sys.platform == "win32":
        os.startfile("workbuddy://")
    else:
        raise OSError("WorkBuddy desktop launcher unavailable")


def _case_link(origin, case_id):
    return f"{origin}/case-manager?case_id={case_id}"


def _case_fields(row, origin, detail=False):
    item = {
        "case_id": row["id"],
        "title": (row["series_display_name"] or row["title"])[:160],
        "internal_code": (row["series_code"] or "")[:50],
        "open_in_stella": _case_link(origin, row["id"]),
    }
    if detail:
        item.update({
            "case_type": (row["case_type"] or "")[:80],
            "stage": (row["current_stage"] or "")[:80],
            "status": row["source_status"] or "active",
            "kind": row["case_kind"] or "ordinary",
        })
    return item


def _find_cases(conn, query, origin):
    compact_query = re.sub(r"[\s（）()]", "", query)
    literal = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    compact = compact_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = conn.execute(
        f"""SELECT {CASE_COLUMNS}
        FROM case_manager_cases c
        WHERE {ACTIVE_CASES}
          AND (c.title LIKE ? ESCAPE '\\' OR c.series_display_name LIKE ? ESCAPE '\\'
               OR c.series_code LIKE ? ESCAPE '\\' OR CAST(c.id AS TEXT)=?
               OR EXISTS (SELECT 1 FROM case_manager_case_numbers n WHERE n.case_id=c.id
                    AND (n.case_no LIKE ? ESCAPE '\\'
                         OR (? <> '' AND REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
                             n.case_no,' ',''),'　',''),'（',''),'）',''),'(',''),')','') LIKE ? ESCAPE '\\'))))
        ORDER BY (c.series_code=? OR c.title=? OR c.series_display_name=? OR CAST(c.id AS TEXT)=?) DESC, c.id DESC
        LIMIT 9""",
        (f"%{literal}%", f"%{literal}%", f"%{literal}%", query, f"%{literal}%",
         compact, f"%{compact}%", query, query, query, query),
    ).fetchall()
    return {"items": [_case_fields(row, origin) for row in rows[:8]], "more_results": len(rows) > 8}


def _read_case(conn, case_id, origin):
    row = conn.execute(
        f"SELECT {CASE_COLUMNS} FROM case_manager_cases c WHERE {ACTIVE_CASES} AND c.id=?", (case_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Stella 中没有找到可读取的该案件。")
    item = _case_fields(row, origin, detail=True)
    item["case_numbers"] = [
        {"number": (number[0] or "")[:100], "court": (number[1] or "")[:100]}
        for number in conn.execute(
            "SELECT case_no,court FROM case_manager_case_numbers WHERE case_id=? ORDER BY sort_order,id LIMIT 8",
            (case_id,),
        )
    ]
    return item


def _read_schedule(conn, filters, origin):
    if filters.start_date and filters.end_date and filters.start_date > filters.end_date:
        raise HTTPException(422, "开始日期必须早于或等于结束日期。")
    kind_sources = (
        ("hearing", "case_manager_hearings", "COALESCE(NULLIF(r.reminder_type,''),'开庭')", "hearing_at"),
        ("todo", "case_manager_todos", "COALESCE(NULLIF(r.todo_title,''),r.title)", "remind_at"),
    )
    sql_parts, params = [], []
    for kind, table, label, date_col in kind_sources:
        if filters.kind not in ("all", kind):
            continue
        scope = [f"(r.case_id IS NULL OR ({ACTIVE_CASES}))" if kind == "todo" else ACTIVE_CASES]
        if kind == "todo":
            scope.append("COALESCE(r.status,'pending')<>'completed'")
        if filters.case_id is not None:
            scope.append("(r.case_id=? OR (c.case_kind='series_child' AND c.parent_series_id=?))")
            params.extend((filters.case_id, filters.case_id))
        for date_filter, operator in ((filters.start_date, ">="), (filters.end_date, "<=")):
            if date_filter:
                scope.append(f"date(r.{date_col}) {operator} ?")
                params.append(date_filter.isoformat())
        where = " AND ".join(scope)
        sql_parts.append(
            f"SELECT '{kind}' AS kind,r.id,r.case_id,{label} AS label,"
            f"r.{date_col} AS recorded_at,datetime(r.{date_col}) AS sort_date "
            f"FROM {table} r LEFT JOIN case_manager_cases c ON c.id=r.case_id WHERE {where}"
        )
        # A missing joined case is not eligible; standalone todos have a NULL case_id.
        sql_parts[-1] += " AND (r.case_id IS NULL OR c.id IS NOT NULL)"
    if filters.count_only:
        grouped_month = filters.group_by == "month"
        month = "strftime('%Y-%m', sort_date)" if grouped_month else "NULL"
        rows = conn.execute(
            f"SELECT {month} AS month,kind,label,COUNT(*) AS count FROM (" + " UNION ALL ".join(sql_parts) + ") "
            "GROUP BY month,kind,CASE WHEN kind='hearing' THEN label ELSE '' END ORDER BY month,kind,label LIMIT 151",
            params,
        ).fetchall()
        if len(rows) > 150:
            raise HTTPException(422, "统计分组过多，请缩短日期范围。")
        groups = [
            {"kind": row["kind"], "label": row["label"][:80] if row["kind"] == "hearing" else "未完成待办",
             "count": row["count"], **({"month": row["month"]} if grouped_month else {})}
            for row in rows
        ]
        return {"total": sum(group["count"] for group in groups), "by_type": groups,
                "open_in_stella": _case_link(origin, filters.case_id) if filters.case_id else f"{origin}/case-manager?tab=hearings"}
    order = "DESC" if filters.sort == "latest" else "ASC"
    rows = conn.execute(
        "SELECT * FROM (" + " UNION ALL ".join(sql_parts) + ") "
        f"ORDER BY sort_date IS NULL,sort_date {order},kind,id LIMIT 13", params,
    ).fetchall()
    items = [
        {
            "kind": row["kind"], "case_id": row["case_id"],
            "title": (row["label"] or "")[:160], "recorded_at": row["recorded_at"] if row["sort_date"] else None,
            "open_in_stella": (_case_link(origin, row["case_id"]) if row["case_id"]
                               else f"{origin}/case-manager?tab=todos"),
        }
        for row in rows[:12]
    ]
    return {"items": items, "more_results": len(rows) > 12}


def create_router(runtime, get_db, list_articles, plain_text, search_cards=None, workbuddy_config=None):
    router = APIRouter()
    defaults = Permissions()
    directory = runtime / "data" / "workbuddy-connector"
    settings_path = directory / "connection.json"
    launcher_path = directory / "stdio.py"
    config_path = workbuddy_config if workbuddy_config is not None else Path.home() / ".workbuddy" / "mcp.json"
    lock = Lock()

    def current():
        try:
            return json.loads(settings_path.read_bytes())
        except (OSError, ValueError):
            return {}

    def definition():
        return {"type": "stdio", "command": sys._base_executable, "args": ["-I", "-B", str(launcher_path)]}

    def register():
        entry = definition()
        if not config_path.parent.is_dir():
            return "请先启动 WorkBuddy 桌面版，再回到 Stella 连接。"
        try:
            original = config_path.read_bytes() if config_path.exists() else b""
            content = json.loads(original.decode("utf-8-sig")) if original.strip() else {}
            servers = content.setdefault("mcpServers", {})
            if CONNECTOR_ID in servers and servers[CONNECTOR_ID] != entry:
                existing = servers[CONNECTOR_ID]
                if not isinstance(existing, dict) or existing.get("args", [])[-1:] != [str(launcher_path)]:
                    return "WorkBuddy 已连接另一套 Stella。解除原连接后，再连接当前安装。"
            if servers.get(CONNECTOR_ID) != entry:
                servers[CONNECTOR_ID] = entry
                _atomic_write(config_path, _json_bytes(content), original)
        except (OSError, ValueError, AttributeError, TypeError):
            return "无法自动合并 WorkBuddy 配置。请在 WorkBuddy 自定义连接器中添加下方配置。"
        return ""

    @router.get("/api/workbuddy/settings")
    def get_settings(request: Request):
        _local_port(request, browser=True)
        with lock:
            settings = current()
        return {
            "enabled": bool(settings.get("token")),
            "permissions": {
                scope: settings.get("permissions", {}).get(scope, getattr(defaults, scope)) is True
                for scope in SCOPES
            },
        }

    @router.put("/api/workbuddy/settings")
    def enable(request: Request, permissions: Permissions):
        port = _local_port(request, browser=True)
        selected = {scope: getattr(permissions, scope) for scope in SCOPES}
        if not any(selected.values()):
            raise HTTPException(422, "请至少选择一项读取权限。")
        if getattr(sys, "frozen", False):
            raise HTTPException(409, "请使用支持本机连接器的 Stella 源码客户端。")
        with lock:
            record = current()
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            _atomic_write(launcher_path, Path(__file__).with_name("workbuddy_stdio.py").read_bytes())
            _atomic_write(settings_path, _json_bytes({
                "port": port, "token": record.get("token") or secrets.token_urlsafe(32),
                "permissions": selected, "launch": _installation_launcher(),
            }))
            fallback = register()
        return {
            "enabled": True, "permissions": selected, "registered": not fallback, "message": fallback,
            "configuration": {"mcpServers": {CONNECTOR_ID: definition()}} if fallback else None,
        }

    @router.delete("/api/workbuddy/settings")
    def revoke(request: Request):
        _local_port(request, browser=True)
        with lock:
            settings_path.unlink(missing_ok=True)
        return {"enabled": False}

    @router.post("/api/workbuddy/open")
    def open_workbuddy(request: Request):
        _local_port(request, browser=True)
        try:
            _open_workbuddy()
        except (OSError, subprocess.SubprocessError):
            raise HTTPException(409, "未能打开 WorkBuddy。请从系统应用列表打开桌面版。") from None
        return {"opened": True}

    @router.post("/api/workbuddy/call")
    async def call(request: Request):
        from starlette.concurrency import run_in_threadpool

        port = _local_port(request)
        authorization = request.headers.get("authorization", "")
        with lock:
            record = current()
        expected = "Bearer " + record.get("token", "")
        if not record.get("token") or record.get("port") != port or not hmac.compare_digest(authorization.encode(), expected.encode()):
            raise HTTPException(401, "WorkBuddy 尚未获得此 Stella 安装的授权，请在 Stella 设置中连接。")
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_MESSAGE:
                raise HTTPException(413, "Stella 查询参数过长。")
            body.extend(chunk)
        try:
            payload = json.loads(body)
            name = payload["name"]
            arguments = payload.get("arguments", {})
            if (not isinstance(name, str) or name not in TOOLS or not isinstance(arguments, dict)
                    or set(arguments) - set(TOOLS[name][1])):
                raise ValueError
        except (ValueError, KeyError, TypeError, RecursionError):
            raise HTTPException(422, "无法识别 Stella 查询参数。") from None
        permissions = record["permissions"]
        if name == "stella_list_readable_data":
            return readable_data(permissions)
        if name == "stella_read_records":
            kind = arguments.pop("type", None)
            if not isinstance(kind, str) or kind not in RECORD_KINDS:
                raise HTTPException(422, "请选择已支持的 Stella 资料类型。")
            required = (RECORD_KINDS[kind][0],)
        else:
            kind = None
            required = REQUIRED[name]
        if not any(permissions.get(scope) is True for scope in required):
            raise HTTPException(403, "请在 Stella 设置中启用这项读取权限。")
        origin = f"http://127.0.0.1:{port}"
        try:
            return await run_in_threadpool(read_tool, name, arguments, origin, kind)
        except ValueError:
            raise HTTPException(422, "请检查查询词、案件 ID 或日期格式。") from None

    def read_tool(name, arguments, origin, kind):
        with read_snapshot(get_db):
            conn = get_db()
            if name == "stella_search_knowledge":
                query = Query(**arguments).query
                articles = list_articles(q=query, page=1, page_size=5)["articles"]
                items = [
                    {
                        "type": "article", "title": (article["title"] or "")[:200],
                        "excerpt": plain_text(
                            (article.get("content_snippets") or [{}])[0].get("text")
                            or (article.get("summary") or "")[:1600]
                        )[:500],
                        "open_in_stella": f"{origin}/?open_article={article['id']}",
                    }
                    for article in articles
                ]
                if search_cards:
                    items.extend({
                        "type": "knowledge_card", "title": (card.get("statement") or "")[:260],
                        "conditions": (card.get("conditions_text") or "")[:250],
                        "exceptions": (card.get("exceptions_text") or "")[:250],
                        "sources": (card.get("source_titles") or "")[:400],
                        "open_in_stella": f"{origin}/legal-knowledge?claim_id={card['id']}",
                    } for card in search_cards(query)["results"])
                return {"items": items}
            if name == "stella_find_cases":
                return _find_cases(conn, Query(**arguments).query, origin)
            if name == "stella_get_case":
                return _read_case(conn, CaseQuery(**arguments).case_id, origin)
            for key in ("start_date", "end_date"):
                if key in arguments and not isinstance(arguments[key], str):
                    raise ValueError
            if kind is not None:
                model = RecordFilters(**arguments)
                filters = model.model_dump(exclude_none=True) if hasattr(model, "model_dump") else model.dict(exclude_none=True)
                for key in ("start_date", "end_date"):
                    if key in filters:
                        filters[key] = filters[key].isoformat()
                return read_user_data(conn, runtime, kind, filters, origin, plain_text)
            return _read_schedule(conn, ScheduleQuery(**arguments), origin)

    return router
