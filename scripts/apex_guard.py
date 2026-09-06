#!/usr/bin/env python3
"""Repository guardrails for safe, continuous APEX development."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Sequence


ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "docs" / "architecture" / "shared-capabilities.json"
API_SNAPSHOT = ROOT / "docs" / "architecture" / "api-contract.json"

TEXT_SUFFIXES = {".py", ".js", ".css", ".html", ".md", ".json", ".yml", ".yaml", ".swift", ".sh"}
SKIP_SECRET_CONTENT = {
    "scripts/apex_guard.py",
    "feishu_config_template.py",
}
SECRET_PATTERNS = (
    ("OpenAI-compatible key", re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}")),
    ("Ark key", re.compile(r"(?<![A-Za-z0-9])ark-[A-Za-z0-9_-]{20,}")),
    ("GitHub token", re.compile(r"(?<![A-Za-z0-9])(?:ghp|gho|ghu|ghs|github_pat)_[A-Za-z0-9_]{20,}")),
    ("Slack token", re.compile(r"(?<![A-Za-z0-9])xox[baprs]-[A-Za-z0-9-]{20,}")),
    ("AWS access key", re.compile(r"(?<![A-Z0-9])AKIA[A-Z0-9]{16}(?![A-Z0-9])")),
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
)
ROUTE_PATTERN = re.compile(
    r"@(?P<owner>app|router)\.(?P<method>get|post|put|patch|delete|options|head)"
    r"\(\s*[rubfRUBF]*(?P<quote>['\"])(?P<path>/[^'\"]*)(?P=quote)",
    re.MULTILINE,
)


class GuardFailure(RuntimeError):
    pass


def run(command: Sequence[str], *, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(command), cwd=str(ROOT), text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        check=False,
    )


def repo_files() -> List[str]:
    proc = run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        capture=True,
    )
    if proc.returncode:
        raise GuardFailure("无法读取 Git 文件清单。")
    return sorted(item for item in proc.stdout.split("\0") if item)


def changed_files(base: str | None = None) -> List[str]:
    commands = []
    if base:
        commands.append(["git", "diff", "--name-only", f"{base}...HEAD"])
    commands.extend([
        ["git", "diff", "--name-only"],
        ["git", "diff", "--cached", "--name-only"],
    ])
    found = set()
    for command in commands:
        proc = run(command, capture=True)
        if proc.returncode == 0:
            found.update(line.strip() for line in proc.stdout.splitlines() if line.strip())
    return sorted(found)


def load_registry() -> dict:
    try:
        return json.loads(REGISTRY.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GuardFailure(f"共享能力登记表无法读取：{exc}") from exc


def registry_check() -> None:
    payload = load_registry()
    capabilities = payload.get("capabilities")
    if payload.get("schema_version") != 1 or not isinstance(capabilities, list):
        raise GuardFailure("共享能力登记表格式无效。")
    ids = set()
    missing = []
    for item in capabilities:
        capability_id = item.get("id")
        if not capability_id or capability_id in ids:
            raise GuardFailure(f"共享能力 id 缺失或重复：{capability_id!r}")
        ids.add(capability_id)
        for key in ("source", "consumers", "tests"):
            if not isinstance(item.get(key), list):
                raise GuardFailure(f"{capability_id}.{key} 必须是数组。")
        for pattern in item["source"] + item["consumers"] + item["tests"]:
            if "*" not in pattern and not (ROOT / pattern).exists():
                missing.append(f"{capability_id}: {pattern}")
    if missing:
        raise GuardFailure("登记表引用不存在：\n  " + "\n  ".join(missing))
    print(f"共享能力登记表：{len(capabilities)} 项，结构有效")


def matching_capabilities(paths: Iterable[str]) -> List[dict]:
    normalized = list(paths)
    matches = []
    for item in load_registry()["capabilities"]:
        patterns = item["source"] + item["consumers"] + item.get("tests", [])
        if any(fnmatch.fnmatch(path, pattern) for path in normalized for pattern in patterns):
            matches.append(item)
    return matches


def impact_report(paths: Sequence[str]) -> None:
    paths = list(paths) or changed_files()
    print("变更文件：")
    if not paths:
        print("  （当前没有已跟踪的修改）")
    for path in paths:
        print(f"  - {path}")
    matches = matching_capabilities(paths)
    print("受影响的共享能力：")
    if not matches:
        print("  （未匹配登记项；仍需搜索符号和接口引用）")
    for item in matches:
        print(f"  - {item['id']} [{item['kind']}]")
        print("    消费方：" + ", ".join(item["consumers"]))
        print("    检查：" + ", ".join(item["tests"]))
    cross_module_markers = ("backend/main.py", "native-shell/", "frontend/style.css", "frontend/color-theme", "frontend/apex-")
    cross_module = bool(matches) or any(path.startswith(cross_module_markers) for path in paths)
    print("变更级别：" + ("跨模块" if cross_module else "局部"))


def secret_check() -> None:
    failures = []
    banned_names = (
        ".env", "legal_kb.db", "pending_tasks.db", "local_ai_secrets.py",
        "local_ai_prefs.json", "local_feishu_expense_config.json",
    )
    for relative in repo_files():
        path = Path(relative)
        if path.name in banned_names or any(part in {"uploads", "article_images", "browser-profile", "browser-profiles"} for part in path.parts):
            failures.append(f"禁止跟踪的运行数据：{relative}")
            continue
        if relative in SKIP_SECRET_CONTENT or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = (ROOT / relative).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for label, pattern in SECRET_PATTERNS:
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                failures.append(f"疑似 {label}：{relative}:{line}")
    if failures:
        raise GuardFailure("敏感信息检查失败（不会显示密钥内容）：\n  " + "\n  ".join(failures))
    print("敏感信息检查：通过")


def discover_routes() -> List[dict]:
    routes = []
    for path in sorted((ROOT / "backend").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        relative = str(path.relative_to(ROOT))
        for match in ROUTE_PATTERN.finditer(text):
            routes.append({
                "method": match.group("method").upper(),
                "path": match.group("path"),
                "source": relative,
            })
    return sorted(routes, key=lambda item: (item["path"], item["method"], item["source"]))


def api_snapshot(write: bool = False) -> None:
    payload = {"schema_version": 1, "routes": discover_routes()}
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if write:
        API_SNAPSHOT.write_text(rendered, encoding="utf-8")
        print(f"API 契约已更新：{len(payload['routes'])} 条路由")
        return
    if not API_SNAPSHOT.exists():
        raise GuardFailure("缺少 API 契约快照；运行 apex_guard.py api-update。")
    if API_SNAPSHOT.read_text(encoding="utf-8") != rendered:
        raise GuardFailure("API 路由契约发生变化；核对调用方后运行 apex_guard.py api-update。")
    print(f"API 契约：{len(payload['routes'])} 条路由，无意外变化")


def syntax_check() -> None:
    python_files = [str(ROOT / path) for path in repo_files() if path.endswith(".py")]
    proc = run([sys.executable, "-m", "py_compile", *python_files])
    if proc.returncode:
        raise GuardFailure("Python 语法检查失败。")
    js_files = [path for path in repo_files() if path.endswith(".js") and not path.startswith("node_modules/")]
    if js_files:
        node = run(["node", "--version"], capture=True)
        if node.returncode == 0:
            for path in js_files:
                checked = run(["node", "--check", path])
                if checked.returncode:
                    raise GuardFailure(f"JavaScript 语法检查失败：{path}")
        else:
            print("JavaScript 语法检查：跳过（未安装 Node.js）")
    print(f"语法检查：{len(python_files)} 个 Python 文件，{len(js_files)} 个 JavaScript 文件")


def unit_tests(extended: bool) -> None:
    if extended:
        command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]
    else:
        command = [
            sys.executable, "-m", "unittest",
            "tests.test_shared_capabilities",
            "tests.test_client_picker_contract",
            "tests.test_database_migrations",
            "tests.test_performance_monitor",
            "tests.test_native_shell_contract",
        ]
    proc = run(command)
    if proc.returncode:
        raise GuardFailure("自动测试失败。")


def guard(level: str) -> None:
    registry_check()
    secret_check()
    syntax_check()
    api_snapshot()
    unit_tests(extended=level == "extended")
    impact_report([])
    print(f"APEX {level} 检查：通过")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("preflight")
    impact = sub.add_parser("impact")
    impact.add_argument("paths", nargs="*")
    sub.add_parser("secrets")
    sub.add_parser("registry")
    sub.add_parser("api-check")
    sub.add_parser("api-update")
    sub.add_parser("fast")
    sub.add_parser("extended")
    args = parser.parse_args()
    try:
        if args.command == "preflight":
            registry_check(); secret_check(); impact_report([])
        elif args.command == "impact":
            impact_report(args.paths)
        elif args.command == "secrets":
            secret_check()
        elif args.command == "registry":
            registry_check()
        elif args.command == "api-check":
            api_snapshot()
        elif args.command == "api-update":
            api_snapshot(write=True)
        else:
            guard(args.command)
    except GuardFailure as exc:
        print(f"失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
