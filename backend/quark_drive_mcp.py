"""夸克网盘本机 MCP 适配器。

通过已安装并授权的夸克网盘官方 Skill 完成文件范围检索与文件问答。
适配器只把问题和命中的网盘文件标识交给夸克官方能力，不下载或复制
网盘文件到法律操作系统。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


class QuarkDriveMCPError(RuntimeError):
    pass


DEFAULT_SKILL_DIR = Path.home() / ".codex" / "skills" / "quarkclouddrive"
MAX_ASSISTANT_FILES = 10_000
FOLDER_SCOPES_ENV = "QUARK_DRIVE_FOLDER_SCOPES"
_USAGE_PATH = Path(
    os.environ.get("LEGAL_KB_DATA_DIR", str(Path(__file__).resolve().parent))
) / "quark_drive_usage.json"
_USAGE_LOCK = threading.Lock()
_TRACKED_ACTIONS = {"search", "summary", "qa"}


_QUARK_CATEGORY_LABELS = {
    0: "文件夹",
    1: "视频",
    2: "音频",
    3: "图片",
    4: "文档",
    5: "种子",
    6: "其他",
    7: "压缩包",
    8: "应用",
}
_NAME_CACHE: Dict[str, str] = {}
_NAME_CACHE_LOCK = threading.Lock()
MAX_BROWSE_ITEMS = 100


def _cache_names(items: Iterable[Dict[str, Any]]) -> None:
    with _NAME_CACHE_LOCK:
        for item in items:
            if not isinstance(item, dict):
                continue
            fid = str(item.get("fid") or "").strip()
            name = str(item.get("filename") or item.get("file_name") or "").strip()
            if fid and name and fid not in _NAME_CACHE:
                _NAME_CACHE[fid] = name[:200]


def _known_name(fid: str) -> Optional[str]:
    with _NAME_CACHE_LOCK:
        return _NAME_CACHE.get(str(fid))


def _item_path_fids(item: Dict[str, Any]) -> List[str]:
    value = item.get("path")
    if isinstance(value, str):
        parts = value.split(",")
    elif isinstance(value, list):
        parts = [str(part) for part in value]
    else:
        return []
    return [part.strip() for part in parts if part.strip() and part.strip() != "0"]


def _format_item(item: Dict[str, Any]) -> Dict[str, Any]:
    fid = str(item.get("fid") or "").strip()
    name = str(item.get("filename") or item.get("file_name") or "").strip()
    category = int(item.get("category") or 0)
    is_folder = category == 0 and not item.get("file", False)
    path_fids = _item_path_fids(item)
    location_parts: List[str] = []
    for ancestor in path_fids:
        resolved = _known_name(ancestor)
        location_parts.append(resolved or "…")
    compact: List[str] = []
    for part in location_parts:
        if part == "…" and compact and compact[-1] == "…":
            continue
        compact.append(part)
    return {
        "fid": fid,
        "parent_fid": str(item.get("parent_fid") or "").strip(),
        "name": name,
        "is_folder": is_folder,
        "category": category,
        "category_label": _QUARK_CATEGORY_LABELS.get(category) or str(item.get("obj_category") or "文件"),
        "item_count": int(item.get("includeItems") or 0),
        "size": int(item.get("size") or 0),
        "updated_at": int(item.get("updated_at") or item.get("created_at") or 0),
        "location": " / ".join(compact),
        "path_fids": path_fids,
        "check_link": str(item.get("check_link") or ""),
    }


def _empty_usage(day: Optional[str] = None) -> Dict[str, Any]:
    return {
        "day": day or time.strftime("%Y-%m-%d", time.localtime()),
        "search_count": 0,
        "assistant_count": 0,
        "assistant_success_count": 0,
        "last_action": "",
        "last_status": "idle",
        "last_message": "尚无调用记录",
        "last_at": "",
    }


def _read_usage_unlocked() -> Dict[str, Any]:
    today = time.strftime("%Y-%m-%d", time.localtime())
    try:
        value = json.loads(_USAGE_PATH.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        value = {}
    if not isinstance(value, dict) or value.get("day") != today:
        return _empty_usage(today)
    clean = _empty_usage(today)
    clean.update({key: value.get(key, default) for key, default in clean.items()})
    for key in ("search_count", "assistant_count", "assistant_success_count"):
        try:
            clean[key] = max(0, int(clean[key]))
        except (TypeError, ValueError):
            clean[key] = 0
    return clean


def _write_usage_unlocked(value: Dict[str, Any]) -> None:
    try:
        _USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = _USAGE_PATH.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        temporary.replace(_USAGE_PATH)
    except OSError:
        # 用量展示不应影响网盘检索和问答本身。
        pass


def _record_usage(command: str, ok: bool, message: str = "") -> None:
    if command not in _TRACKED_ACTIONS:
        return
    with _USAGE_LOCK:
        usage = _read_usage_unlocked()
        if command == "search":
            usage["search_count"] += 1
        else:
            usage["assistant_count"] += 1
            if ok:
                usage["assistant_success_count"] += 1
        usage.update({
            "last_action": command,
            "last_status": "success" if ok else "error",
            "last_message": str(message or ("调用成功" if ok else "调用失败"))[:300],
            "last_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        })
        _write_usage_unlocked(usage)


def usage_status() -> Dict[str, Any]:
    """返回 Stella 可核验的本机调用统计，不虚构服务商剩余额度。"""
    with _USAGE_LOCK:
        usage = _read_usage_unlocked()
    return {
        **usage,
        "searches_per_question": 1,
        "max_files_per_question": MAX_ASSISTANT_FILES,
        "official_remaining_available": False,
        "official_remaining_text": "夸克暂未开放剩余次数查询",
    }


def skill_dir() -> Path:
    configured = os.environ.get("QUARK_DRIVE_SKILL_DIR", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_SKILL_DIR


def _runtime_env() -> Dict[str, str]:
    env = dict(os.environ)
    preferred = [
        "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin",
        "/usr/sbin", "/sbin",
    ]
    current = [item for item in env.get("PATH", "").split(os.pathsep) if item]
    env["PATH"] = os.pathsep.join(dict.fromkeys(preferred + current))
    # LaunchAgent 不继承 Codex 的会话变量；官方 Skill 用该变量识别当前
    # Agent 类型并复用已授权的 Codex 账号配置。仅对子进程补充，不写入系统环境。
    env.setdefault("CODEX_THREAD_ID", "apex-legal-os")
    return env


def _node_binary() -> str:
    node = shutil.which("node", path=_runtime_env()["PATH"])
    if not node:
        raise QuarkDriveMCPError("未找到 Node.js，夸克网盘 MCP 暂不可用")
    return node


def _paths() -> tuple[Path, Path]:
    root = skill_dir()
    installer = root / "scripts" / "install.sh"
    cli = root / "scripts" / "quark-drive.cjs"
    if not installer.is_file() or not cli.is_file():
        raise QuarkDriveMCPError("尚未安装夸克网盘 Skill")
    return installer, cli


async def _run_process(*parts: str, timeout: float) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *parts,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_runtime_env(),
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise QuarkDriveMCPError("夸克网盘响应超时，请稍后重试") from exc
    return (
        int(process.returncode or 0),
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )


def _parse_ndjson(stdout: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in (stdout or "").splitlines():
        try:
            value = json.loads(line.strip())
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _result_row(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    result: Optional[Dict[str, Any]] = None
    for row in rows:
        if row.get("type") == "result":
            result = row
    if result is None:
        raise QuarkDriveMCPError("夸克网盘未返回可识别的结果")
    if int(result.get("code") or 0) != 0:
        raise QuarkDriveMCPError(str(result.get("msg") or "夸克网盘调用失败"))
    return result


async def _run_cli(
    command: str,
    *arguments: str,
    session_id: str,
    session_input: Optional[str] = None,
    timeout: float = 150.0,
) -> List[Dict[str, Any]]:
    installer, cli = _paths()
    install_code, _install_out, install_err = await _run_process(
        "bash", str(installer), timeout=120.0
    )
    if install_code != 0:
        detail = (install_err or "").strip().splitlines()
        raise QuarkDriveMCPError(detail[-1] if detail else "夸克网盘运行环境准备失败")

    parts = [_node_binary(), str(cli), command, *arguments]
    if session_input is not None:
        parts.extend(["--session-input", session_input])
    parts.extend(["--session-id", session_id])
    try:
        code, stdout, stderr = await _run_process(*parts, timeout=timeout)
    except QuarkDriveMCPError as exc:
        _record_usage(command, False, str(exc))
        raise
    rows = _parse_ndjson(stdout)
    if rows:
        try:
            result = _result_row(rows)
        except QuarkDriveMCPError as exc:
            _record_usage(command, False, str(exc))
            raise
        _record_usage(command, True, str(result.get("msg") or "调用成功"))
        return rows
    if code != 0:
        detail = (stderr or "").strip().splitlines()
        message = detail[-1] if detail else "夸克网盘调用失败"
        _record_usage(command, False, message)
        raise QuarkDriveMCPError(message)
    message = "夸克网盘未返回可识别的结果"
    _record_usage(command, False, message)
    raise QuarkDriveMCPError(message)


def _session_id() -> str:
    return f"{int(time.time())}-{secrets.token_hex(3)}"


def _search_keyword(question: str) -> str:
    text = re.sub(r"\s+", " ", str(question or "")).strip()
    prefixes = (
        "请根据夸克网盘中的内容", "请根据夸克网盘里的内容",
        "请基于夸克网盘中的内容", "请基于夸克网盘里的内容",
        "根据夸克网盘中的内容", "根据夸克网盘里的内容",
        "请阅读我的夸克网盘", "请阅读夸克网盘",
    )
    for prefix in prefixes:
        if text.startswith(prefix):
            text = text[len(prefix):].lstrip("，,：:。 ")
            break
    return (text or "网盘文件")[:50]


def _artifact_path(rows: Iterable[Dict[str, Any]]) -> Optional[Path]:
    for row in rows:
        if row.get("type") != "artifact":
            continue
        value = (row.get("data") or {}).get("file_path")
        if value:
            return Path(str(value)).expanduser()
    return None


def _collect_fids(value: Any, output: List[str]) -> None:
    if isinstance(value, dict):
        fid = value.get("fid")
        if isinstance(fid, (str, int)) and str(fid).strip():
            output.append(str(fid).strip())
        for key in ("data", "file_list", "items", "files"):
            if key in value:
                _collect_fids(value[key], output)
    elif isinstance(value, list):
        for item in value:
            _collect_fids(item, output)


def _read_artifact_fids(path: Optional[Path]) -> List[str]:
    if path is None or not path.is_file():
        raise QuarkDriveMCPError("夸克网盘检索结果缺少可用于问答的文件范围")
    fids: List[str] = []
    try:
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                try:
                    value = json.loads(line)
                except (TypeError, ValueError):
                    continue
                _collect_fids(value, fids)
    except OSError as exc:
        raise QuarkDriveMCPError("无法读取夸克网盘检索结果") from exc
    return list(dict.fromkeys(fids))[:MAX_ASSISTANT_FILES]


def _read_artifact_items(path: Optional[Path]) -> List[Dict[str, Any]]:
    if path is None or not path.is_file():
        raise QuarkDriveMCPError("夸克网盘检索结果缺少可用于问答的文件范围")
    items: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                try:
                    value = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if isinstance(value, dict):
                    items.append(value)
    except OSError as exc:
        raise QuarkDriveMCPError("无法读取夸克网盘检索结果") from exc
    return items


def _fids_within_scopes(items: Iterable[Dict[str, Any]], scope_fids: Iterable[str]) -> List[str]:
    allowed = {str(fid).strip() for fid in scope_fids if str(fid).strip()}
    matched: List[str] = []
    for item in items:
        fid = str(item.get("fid") or "").strip()
        parent_fid = str(item.get("parent_fid") or "").strip()
        path_value = item.get("path")
        if isinstance(path_value, str):
            ancestors = {part.strip() for part in path_value.split(",") if part.strip()}
        elif isinstance(path_value, list):
            ancestors = {str(part).strip() for part in path_value if str(part).strip()}
        else:
            ancestors = set()
        if fid and (fid in allowed or parent_fid in allowed or ancestors.intersection(allowed)):
            matched.append(fid)
    return list(dict.fromkeys(matched))[:MAX_ASSISTANT_FILES]


def _assistant_command(question: str) -> str:
    summary_markers = ("总结", "概括", "梳理", "提炼", "主要内容", "核心内容", "讲了什么")
    return "summary" if any(marker in question for marker in summary_markers) else "qa"


def configured_scopes() -> List[Dict[str, str]]:
    raw_value = os.environ.get(FOLDER_SCOPES_ENV) if FOLDER_SCOPES_ENV in os.environ else None
    raw = str(raw_value or "").strip()
    if raw_value is None:
        # Stella 以 LaunchAgent 启动时不会继承页面运行期环境变量；范围配置
        # 同时保存在本机私有配置中，重启后也应能直接恢复。
        try:
            from . import ai_config
            local = getattr(ai_config, "_local_ai_secrets", None)
            raw = str(getattr(local, FOLDER_SCOPES_ENV, "") or "").strip()
        except Exception:
            raw = ""
    if not raw:
        return []
    try:
        values = json.loads(raw)
    except (TypeError, ValueError):
        return []
    scopes: List[Dict[str, str]] = []
    for item in values if isinstance(values, list) else []:
        if not isinstance(item, dict):
            continue
        fid = str(item.get("fid") or "").strip()
        name = str(item.get("name") or "").strip()
        if fid and name and fid not in {scope["fid"] for scope in scopes}:
            scopes.append({"fid": fid, "name": name[:200]})
    return scopes[:100]


async def search_items(keyword: str, category: Optional[int] = None) -> List[Dict[str, Any]]:
    original = str(keyword or "").strip()
    if not original:
        raise QuarkDriveMCPError("请输入要查找的名称或关键词")
    arguments = ["--keyword", original[:50], "--size", "100"]
    rows = await _run_cli(
        "search",
        *arguments,
        session_id=_session_id(),
        session_input=original,
        timeout=90.0,
    )
    items = _full_search_items(rows)
    _cache_names(items)
    formatted = [
        _format_item(item)
        for item in items
        if isinstance(item, dict) and str(item.get("fid") or "").strip()
    ]
    if isinstance(category, int) and 0 <= category <= 8:
        formatted = [
            item for item in formatted
            if (item["category"] == 0 if category == 0 else item["category"] == category)
        ]
    return formatted[:MAX_BROWSE_ITEMS]


def _full_search_items(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result = _result_row(rows)
    items = (result.get("data") or {}).get("file_list") or []
    artifact = _artifact_path(rows)
    if artifact is not None:
        try:
            full_items = _read_artifact_items(artifact)
            if full_items:
                items = full_items
        except QuarkDriveMCPError:
            pass
    return items


async def browse_folder(fid: str, name: str = "") -> Dict[str, Any]:
    """按文件夹名称检索并筛选其内部条目，近似实现目录浏览。

    官方 Skill 暂未开放「列出某文件夹子项」的接口，浏览基于关键词检索：
    以文件夹名称检索整个网盘，再筛出 parent 或路径命中该文件夹的条目。
    同名文件夹过多时检索结果可能被截断，返回 total_matched 供页面提示。
    """
    original_fid = str(fid or "").strip()
    original_name = str(name or "").strip()
    if not original_fid:
        raise QuarkDriveMCPError("缺少要浏览的文件夹")
    keyword = (original_name or "文件夹")[:50]
    rows = await _run_cli(
        "search",
        "--keyword", keyword,
        "--size", "100",
        session_id=_session_id(),
        session_input=original_name,
        timeout=90.0,
    )
    result = _result_row(rows)
    items = _full_search_items(rows)
    _cache_names(items)
    found_self = any(str(item.get("fid") or "") == original_fid for item in items if isinstance(item, dict))
    children: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_fid = str(item.get("fid") or "").strip()
        if not item_fid or item_fid == original_fid:
            continue
        parent_fid = str(item.get("parent_fid") or "").strip()
        ancestors = set(_item_path_fids(item))
        if parent_fid != original_fid and original_fid not in ancestors:
            continue
        children.append(_format_item(item))
    children.sort(key=lambda entry: (not entry["is_folder"], entry["name"]))
    return {
        "folder": {"fid": original_fid, "name": original_name},
        "items": children[:MAX_BROWSE_ITEMS],
        "total_matched": int((result.get("data") or {}).get("total") or 0),
        "folder_seen": found_self,
    }


async def answer_from_drive(question: str) -> Dict[str, Any]:
    original = str(question or "").strip()
    if not original:
        raise QuarkDriveMCPError("问题不能为空")
    session_id = _session_id()
    scopes = configured_scopes()
    if scopes:
        # 官方检索暂不支持限定父文件夹，同名文件和电脑备份副本会造成
        # 跨目录召回。已选范围时直接进行文件夹问答，才能保证其它目录
        # 不参与；首次问答可能由服务端返回“文件仍在分析”的明确状态。
        fids = [scope["fid"] for scope in scopes]
    else:
        search_rows = await _run_cli(
            "search",
            "--keyword", _search_keyword(original),
            "--stdout-only",
            session_id=session_id,
            session_input=original,
            timeout=90.0,
        )
        search_result = _result_row(search_rows)
        total = int((search_result.get("data") or {}).get("total") or 0)
        if total <= 0:
            raise QuarkDriveMCPError("未在夸克网盘中找到与该问题相关的文件，请调整问题中的文件名或主题词后重试")
        artifact = _artifact_path(search_rows)
        fids = _read_artifact_fids(artifact)
        if not fids:
            raise QuarkDriveMCPError("夸克网盘检索到了相关文件，但暂时无法建立问答范围")

    command = _assistant_command(original)
    answer_rows = await _run_cli(
        command,
        "--query", original,
        "--fid-list", ",".join(fids),
        session_id=session_id,
        session_input=original,
        timeout=180.0,
    )
    result = _result_row(answer_rows)
    text_block = (result.get("data") or {}).get("text_block") or {}
    answer = str(text_block.get("text") or "").strip()
    if not answer:
        raise QuarkDriveMCPError(str(result.get("msg") or "夸克网盘未返回可用回答"))
    return {
        "answer": answer,
        "matched_files": 0 if scopes else len(fids),
        "scope_folders": len(scopes),
        "scope_names": [scope["name"] for scope in scopes],
        "title": str(text_block.get("title") or "夸克网盘文件问答"),
    }


async def check_connection() -> Dict[str, Any]:
    rows = await _run_cli(
        "get-user-info",
        session_id=_session_id(),
        session_input=None,
        timeout=60.0,
    )
    result = _result_row(rows)
    user = (result.get("data") or {}).get("userInfo") or {}
    return {"ok": True, "nickname": str(user.get("nickname") or "已授权账号")}
