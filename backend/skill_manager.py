from __future__ import annotations

import os
import re
import json
import hashlib
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

from fastapi import FastAPI, HTTPException, Query


_STELLA_APPLIED_SKILLS = {
    "quarkclouddrive": "已接入 Stella 夸克网盘文件检索与问答",
}

_READABLE_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".py", ".js", ".mjs", ".sh"}
_MAX_READABLE_FILE_BYTES = 1024 * 1024
_EXTERNAL_SKILL_REGISTRY_ENV = "APEX_EXTERNAL_SKILL_REGISTRY"


def _skill_roots() -> tuple[Path, Path]:
    """Return the two locations that make up Stella's visible Skill library."""
    codex_root = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex")).expanduser()
    return codex_root / "skills", codex_root / "plugins" / "cache"


def _external_skill_registry_path() -> Path:
    configured = os.environ.get(_EXTERNAL_SKILL_REGISTRY_ENV)
    if configured:
        return Path(configured).expanduser()
    return Path.home() / "Library" / "Application Support" / "APEX" / "external-skill-sources.json"


def _external_skill_roots() -> set[Path]:
    """Load registered external folders, preserving unavailable folders for later scans."""
    registry = _external_skill_registry_path()
    try:
        payload = json.loads(registry.read_text(encoding="utf-8"))
        values = payload.get("paths", []) if isinstance(payload, dict) else []
    except (OSError, UnicodeError, json.JSONDecodeError):
        values = []
    roots: set[Path] = set()
    for value in values:
        try:
            root = Path(str(value)).expanduser().resolve(strict=True)
        except OSError:
            continue
        if root.is_dir() and (root / "SKILL.md").is_file():
            roots.add(root)
    return roots


def _save_external_skill_roots(roots: Iterable[Path]) -> None:
    registry = _external_skill_registry_path()
    try:
        registry.parent.mkdir(parents=True, exist_ok=True)
        payload = {"paths": sorted(str(path) for path in roots)}
        temporary = registry.with_name(f".{registry.name}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, registry)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="无法保存外部 Skill 的本地位置") from exc


def _frontmatter(text: str) -> Dict[str, Any]:
    """Read the small YAML subset commonly used by SKILL.md without adding PyYAML."""
    if not text.startswith("---"):
        return {}
    match = re.match(r"^---\s*\n(.*?)\n---(?:\s*\n|$)", text, re.S)
    if not match:
        return {}
    lines = match.group(1).splitlines()
    result: Dict[str, Any] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        item = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if not item:
            index += 1
            continue
        key, value = item.group(1), item.group(2).strip()
        if value in {">", "|"}:
            parts: List[str] = []
            index += 1
            while index < len(lines) and (not lines[index].strip() or lines[index].startswith((" ", "\t"))):
                if lines[index].strip():
                    parts.append(lines[index].strip())
                index += 1
            result[key] = " ".join(parts)
            continue
        result[key] = value.strip('"\'')
        index += 1
    return result


def _visible_path(path: Path) -> str:
    home = Path.home()
    try:
        return "~/" + str(path.relative_to(home))
    except ValueError:
        return str(path)


def _skill_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    return root.rglob("SKILL.md")


def _plugin_identity(path: Path) -> str:
    parts = path.parts
    try:
        cache_index = parts.index("cache")
        return parts[cache_index + 2]
    except (ValueError, IndexError):
        return "Codex 插件"


def _is_below(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _classify(
    path: Path, personal_root: Path, plugin_root: Path, external_roots: Iterable[Path] = ()
) -> Dict[str, Any]:
    is_external = any(path.parent.resolve() == root for root in external_roots)
    if is_external:
        return {
            "source": "personal",
            "source_label": "外部本地路径",
            "created": False,
            "plugin": "外部本地 Skill",
            "external": True,
        }
    if _is_below(path, personal_root / ".system"):
        return {"source": "system", "source_label": "系统内置", "created": False, "plugin": "Codex", "external": False}
    if _is_below(path, plugin_root):
        plugin = _plugin_identity(path)
        return {"source": "plugin", "source_label": "插件添加", "created": False, "plugin": plugin, "external": False}
    return {"source": "personal", "source_label": "个人 Skill", "created": True, "plugin": "个人创建", "external": False}


def _read_skill(
    path: Path, personal_root: Path, plugin_root: Path, external_roots: Iterable[Path] = ()
) -> Dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8")
        stat = path.stat()
    except (OSError, UnicodeError):
        return None
    meta = _frontmatter(text)
    classification = _classify(path, personal_root, plugin_root, external_roots)
    name = str(meta.get("name") or path.parent.name).strip()
    description = re.sub(r"\s+", " ", str(meta.get("description") or "").strip())
    title_match = re.search(r"^#\s+(.+)$", text, re.M)
    display_name = title_match.group(1).strip() if title_match else name
    headings = [item.strip() for item in re.findall(r"^##\s+(.+)$", text, re.M)[:8]]
    child_files = [item for item in path.parent.rglob("*") if item.is_file()]
    applied_note = _STELLA_APPLIED_SKILLS.get(name, "")
    created = bool(
        classification["created"]
        and not (meta.get("version") and "官方" in description)
    )
    owner_label = classification["plugin"] if classification["external"] else (
        "个人创建" if created
        else "本地安装" if classification["source"] == "personal"
        else classification["plugin"]
    )
    identifier = f"{classification['source']}-{classification['plugin']}-{name}"
    if classification["external"]:
        identifier += "-" + hashlib.sha1(str(path.parent).encode("utf-8")).hexdigest()[:10]
    return {
        "id": re.sub(r"[^a-z0-9_-]+", "-", identifier.lower()).strip("-"),
        "name": name,
        "display_name": display_name,
        "description": description or "该 Skill 暂未提供简介。",
        "version": str(meta.get("version") or "").strip(),
        "argument_hint": str(meta.get("argument-hint") or "").strip(),
        "source": classification["source"],
        "source_label": classification["source_label"],
        "plugin": owner_label,
        "created": created,
        "applied": bool(applied_note),
        "applied_note": applied_note,
        "enabled": True,
        "path": _visible_path(path.parent),
        "updated_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="minutes"),
        "file_count": len(child_files),
        "sections": headings,
    }


def discover_skills() -> Dict[str, Any]:
    personal_root, plugin_root = _skill_roots()
    external_roots = _external_skill_roots()
    paths = (
        list(_skill_files(personal_root))
        + list(_skill_files(plugin_root))
        + [root / "SKILL.md" for root in external_roots]
    )
    skills = []
    seen = set()
    for path in paths:
        skill = _read_skill(path, personal_root, plugin_root, external_roots)
        if not skill or skill["id"] in seen:
            continue
        seen.add(skill["id"])
        skills.append(skill)
    source_order = {"personal": 0, "plugin": 1, "system": 2}
    skills.sort(key=lambda item: (source_order.get(item["source"], 9), item["display_name"].lower()))
    return {
        "skills": skills,
        "summary": {
            "total": len(skills),
            "personal": sum(item["source"] == "personal" for item in skills),
            "created": sum(item["created"] for item in skills),
            "applied": sum(item["applied"] for item in skills),
            "plugins": len({item["plugin"] for item in skills if item["source"] == "plugin"}),
        },
        "scanned_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def _find_skill(skill_id: str) -> tuple[Path, Dict[str, Any]]:
    personal_root, plugin_root = _skill_roots()
    external_roots = _external_skill_roots()
    paths = (
        list(_skill_files(personal_root))
        + list(_skill_files(plugin_root))
        + [root / "SKILL.md" for root in external_roots]
    )
    for path in paths:
        skill = _read_skill(path, personal_root, plugin_root, external_roots)
        if skill and skill["id"] == skill_id:
            return path, skill
    raise HTTPException(status_code=404, detail="Skill 不存在或已被移除")


def _skill_source_directory(value: Any) -> Path:
    """Validate a user-selected local Skill directory without interpreting shell syntax."""
    raw_path = str(value or "").strip()
    if not raw_path:
        raise HTTPException(status_code=400, detail="请填写 Skill 文件夹的位置")
    source = Path(raw_path).expanduser()
    try:
        source = source.resolve(strict=True)
    except OSError as exc:
        raise HTTPException(status_code=404, detail="找不到该本地位置") from exc
    if source.is_file() and source.name.lower() == "skill.md":
        source = source.parent
    if not source.is_dir():
        raise HTTPException(status_code=400, detail="请选择包含 SKILL.md 的文件夹")
    if not (source / "SKILL.md").is_file():
        raise HTTPException(status_code=400, detail="该文件夹中没有找到 SKILL.md")
    return source


def import_local_skill(source_value: Any) -> Dict[str, Any]:
    """Register an external Skill directory and always read it in place.

    Only the folder path is stored in Stella's settings. The Skill files remain owned
    by their original tool, so future edits are visible on the next scan.
    """
    source = _skill_source_directory(source_value)
    personal_root, plugin_root = _skill_roots()
    if _is_below(source, personal_root.resolve()):
        raise HTTPException(status_code=409, detail="该 Skill 已在 Stella 的个人 Skill 目录中，无需重复添加")
    external_roots = _external_skill_roots()
    already_registered = source in external_roots
    external_roots.add(source)
    _save_external_skill_roots(external_roots)
    skill = _read_skill(source / "SKILL.md", personal_root, plugin_root, external_roots)
    if not skill:
        raise HTTPException(status_code=500, detail="已登记本地位置，但无法读取其 SKILL.md")
    message = (
        f"{skill['display_name']} 已在 Stella 中登记，将直接同步原路径的更新"
        if not already_registered
        else f"{skill['display_name']} 已在 Stella 中登记"
    )
    return {"success": True, "skill": skill, "message": message, "already_registered": already_registered}


def open_skill_location(skill_id: str) -> Dict[str, Any]:
    """Open the exact on-disk Skill folder for an already-discovered Skill."""
    skill_file, skill = _find_skill(skill_id)
    folder = skill_file.parent
    try:
        if os.name == "posix" and Path("/System/Library/CoreServices/Finder.app").exists():
            subprocess.run(["open", str(folder)], check=True, timeout=10)
        elif os.name == "nt":
            os.startfile(str(folder))  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", str(folder)], check=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise HTTPException(status_code=500, detail="无法打开 Skill 的本地文件夹") from exc
    return {"success": True, "path": _visible_path(folder), "message": f"已打开 {skill['display_name']} 的本地文件夹"}


def delete_skill(skill_id: str, confirmed: bool) -> Dict[str, Any]:
    """Remove a user-managed Skill after the UI has received explicit confirmation."""
    if not confirmed:
        raise HTTPException(status_code=400, detail="请先确认删除 Skill")
    skill_file, skill = _find_skill(skill_id)
    personal_root, _ = _skill_roots()
    external_roots = _external_skill_roots()
    folder = skill_file.parent.resolve()

    if folder in external_roots:
        external_roots.remove(folder)
        _save_external_skill_roots(external_roots)
        return {
            "success": True,
            "mode": "unregistered",
            "message": f"已从 Stella 移除 {skill['display_name']}；原始本地文件未删除",
        }

    managed_root = personal_root.resolve()
    system_root = (personal_root / ".system").resolve()
    if not _is_below(folder, managed_root) or _is_below(folder, system_root):
        raise HTTPException(status_code=403, detail="插件和系统内置 Skill 不能在此删除")
    try:
        shutil.rmtree(folder)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="无法删除该 Skill 的本地文件") from exc
    return {"success": True, "mode": "deleted", "message": f"已删除 {skill['display_name']}"}


def _document_title(path: Path, text: str) -> str:
    match = re.search(r"^#\s+(.+)$", text, re.M)
    if match:
        return match.group(1).strip()
    if path.name == "SKILL.md":
        return "核心指令"
    return path.stem.replace("-", " ").replace("_", " ").strip()


def _document_kind(relative: Path) -> str:
    if relative.as_posix() == "SKILL.md":
        return "核心指令"
    if relative.parts and relative.parts[0] == "references":
        return "规则与参考"
    if relative.parts and relative.parts[0] == "scripts":
        return "执行脚本"
    return "附属文件"


def _skill_documents(skill_file: Path) -> List[Dict[str, Any]]:
    root = skill_file.parent
    documents: List[Dict[str, Any]] = []
    candidates = [skill_file] + sorted(
        (
            path for path in root.rglob("*")
            if path.is_file()
            and path != skill_file
            and path.suffix.lower() in _READABLE_SUFFIXES
            and path.stat().st_size <= _MAX_READABLE_FILE_BYTES
            and not any(part.startswith(".") or part == "node_modules" for part in path.relative_to(root).parts)
        ),
        key=lambda path: (
            0 if path.relative_to(root).parts[0] == "references" else 1,
            path.relative_to(root).as_posix().lower(),
        ),
    )
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8")
            relative = path.relative_to(root)
        except (OSError, UnicodeError, ValueError):
            continue
        documents.append({
            "path": relative.as_posix(),
            "title": _document_title(path, text),
            "kind": _document_kind(relative),
            "size": path.stat().st_size,
            "line_count": len(text.splitlines()),
        })
    return documents


def _read_skill_document(skill_file: Path, relative_path: str) -> str:
    root = skill_file.parent.resolve()
    if not relative_path or Path(relative_path).is_absolute():
        raise HTTPException(status_code=400, detail="文件路径无效")
    target = (root / relative_path).resolve()
    if not _is_below(target, root) or not target.is_file():
        raise HTTPException(status_code=404, detail="规则文件不存在")
    if target.suffix.lower() not in _READABLE_SUFFIXES or target.stat().st_size > _MAX_READABLE_FILE_BYTES:
        raise HTTPException(status_code=400, detail="该文件不支持在线预览")
    try:
        return target.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise HTTPException(status_code=500, detail="无法读取规则文件") from exc


_SKILL_INSTRUCTION_MAX_CHARS = 30000
_SKILL_SKILLMD_MAX_CHARS = 20000
_SKILL_REFERENCE_MAX_CHARS = 10000


def load_skill_instruction(skill_id: str) -> str:
    """构建用户所选个人 Skill 的注入指令。

    仅允许“个人 Skill”（source == personal）参与问答。读取 SKILL.md
    核心指令与 references 参考文件，超长内容截断，防止挤占证据窗口。
    返回空字符串表示未选择、不可用或读取失败。
    """
    if not skill_id:
        return ""
    try:
        skill_file, skill = _find_skill(skill_id)
    except HTTPException:
        return ""
    if skill.get("source") != "personal":
        return ""
    parts: List[str] = []
    total = 0
    candidates = [skill_file] + sorted(
        (
            path for path in skill_file.parent.rglob("*")
            if path.is_file()
            and path != skill_file
            and path.suffix.lower() in _READABLE_SUFFIXES
            and path.stat().st_size <= _MAX_READABLE_FILE_BYTES
            and not any(part.startswith(".") or part == "node_modules" for part in path.relative_to(skill_file.parent).parts)
        ),
        key=lambda path: path.relative_to(skill_file.parent).as_posix().lower(),
    )
    for path in candidates:
        relative = path.relative_to(skill_file.parent)
        kind = _document_kind(relative)
        limit = (
            _SKILL_SKILLMD_MAX_CHARS
            if relative.as_posix() == "SKILL.md"
            else _SKILL_REFERENCE_MAX_CHARS
        )
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if len(text) > limit:
            text = text[:limit] + "\n…（内容过长，已截断）"
        remaining = _SKILL_INSTRUCTION_MAX_CHARS - total
        if remaining <= 0:
            break
        if len(text) > remaining:
            text = text[:remaining] + "\n…（内容过长，已截断）"
        total += len(text)
        if relative.as_posix() == "SKILL.md":
            parts.append(f"【Skill 核心指令 · {skill.get('display_name') or skill.get('name') or skill_id}】\n{text}")
        else:
            parts.append(f"【Skill 参考文件 · {relative.as_posix()}】\n{text}")
    if not parts:
        return ""
    return (
        "【用户启用的个人 Skill】本次回答前，你必须先完整阅读下方 Skill 的全部内容，"
        "并严格按其规定的方式处理用户的问题；Skill 要求与系统通用规则冲突时，"
        "优先执行 Skill 的明确要求（但不得编造 Skill 未提供的规范）。\n\n"
        + "\n\n".join(parts)
        + "\n\n【Skill 阅读完毕】请遵循上述 Skill 的流程与要求，结合用户的具体问题作答。\n"
    )


def register_skill_manager_routes(app: FastAPI) -> None:
    @app.get("/api/skills")
    async def list_skills():
        return discover_skills()

    @app.post("/api/skills/import")
    async def import_skill(payload: Dict[str, Any]):
        """Register a local Skill folder while leaving its files in place."""
        return import_local_skill(payload.get("path"))

    @app.get("/api/skills/{skill_id}")
    async def skill_detail(skill_id: str):
        skill_file, skill = _find_skill(skill_id)
        return {
            "skill": skill,
            "documents": _skill_documents(skill_file),
            "content": _read_skill_document(skill_file, "SKILL.md"),
            "active_document": "SKILL.md",
        }

    @app.post("/api/skills/{skill_id}/open-location")
    async def open_location(skill_id: str):
        return open_skill_location(skill_id)

    @app.delete("/api/skills/{skill_id}")
    async def remove_skill(skill_id: str, payload: Dict[str, Any]):
        return delete_skill(skill_id, bool(payload.get("confirmed")))

    @app.get("/api/skills/{skill_id}/content")
    async def skill_document(skill_id: str, file: str = Query(..., min_length=1, max_length=500)):
        skill_file, _ = _find_skill(skill_id)
        return {"path": file, "content": _read_skill_document(skill_file, file)}
