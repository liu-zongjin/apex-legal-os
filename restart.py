#!/usr/bin/env python3
"""Restart the legal knowledge base on port 8000.

This helper is intended to be run by the desktop user in Terminal. It stops
existing Python processes listening on the configured port, then starts the app.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import shutil
import json
import urllib.error
import urllib.request
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
PORT = os.environ.get("PORT", "8000")
HOST = os.environ.get("LEGAL_KB_HOST", "127.0.0.1")
LAUNCH_AGENT_LABEL = "com.liuzongjin.legalkb"
LAUNCH_AGENT_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"
PRIVATE_LAUNCH_AGENT_LABEL = "com.liuzongjin.legalkb.private"
PRIVATE_LAUNCH_AGENT_PATH = (
    Path.home() / "Library" / "LaunchAgents" / f"{PRIVATE_LAUNCH_AGENT_LABEL}.plist"
)


def launch_agent_is_loaded(label: str = LAUNCH_AGENT_LABEL) -> bool:
    """配置文件存在不代表服务已经加载到当前用户的 launchd 域。"""
    service = f"gui/{os.getuid()}/{label}"
    completed = subprocess.run(
        ["launchctl", "print", service],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return completed.returncode == 0


def listening_pids() -> list[int]:
    try:
        output = subprocess.check_output(
            ["lsof", "-nP", f"-iTCP:{PORT}", "-sTCP:LISTEN", "-t"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return []
    pids = []
    for line in output.splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return sorted(set(pids))


def access_credentials() -> tuple[str, str] | None:
    """Read the local Basic Auth pair without printing or persisting it."""
    username = os.environ.get("LEGAL_KB_ACCESS_USER", "")
    password = os.environ.get("LEGAL_KB_ACCESS_PASSWORD", "")
    env_path = BASE_DIR / ".env.private"
    if password or not env_path.is_file():
        return (username or "lawyer", password) if password else None

    # .env.private uses shell-escaped assignments written by the installer.
    # Decode it the same way as the LaunchAgent, but keep its contents in memory.
    completed = subprocess.run(
        [
            "/bin/bash",
            "-c",
            'set -a; . "$1" >/dev/null || exit; env -0',
            "restart-env",
            str(env_path),
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=5,
    )
    if completed.returncode != 0:
        return None
    values = {}
    for entry in completed.stdout.split(b"\0"):
        if b"=" not in entry:
            continue
        key, value = entry.split(b"=", 1)
        if key in {b"LEGAL_KB_ACCESS_USER", b"LEGAL_KB_ACCESS_PASSWORD"}:
            values[key.decode("ascii")] = value.decode("utf-8")
    password = values.get("LEGAL_KB_ACCESS_PASSWORD", "")
    if not password:
        return None
    return values.get("LEGAL_KB_ACCESS_USER", "lawyer") or "lawyer", password


def status_opener() -> urllib.request.OpenerDirector:
    """Build a local status client that can pass the configured login."""
    credentials = access_credentials()
    if not credentials:
        return urllib.request.build_opener()
    username, password = credentials
    password_manager = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    password_manager.add_password(
        None, f"http://127.0.0.1:{PORT}/", username, password
    )
    return urllib.request.build_opener(
        urllib.request.HTTPBasicAuthHandler(password_manager)
    )


def stop_listeners() -> bool:
    """Stop standalone servers before handing the port back to launchd."""
    pids = listening_pids()
    for pid in pids:
        print(f"停止旧服务进程 {pid}...")
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        except PermissionError:
            print(f"无权限停止进程 {pid}，请在活动监视器中强制退出它。")
            return False

    deadline = time.time() + 5
    while listening_pids() and time.time() < deadline:
        time.sleep(0.2)

    remaining = listening_pids()
    if remaining:
        print("旧服务未退出，请先强制退出这些进程：", ", ".join(map(str, remaining)))
        return False
    return True


def wait_for_verified_server(previous_pids: set[int] | None = None, timeout: float = 30.0) -> bool:
    """Wait until a new process is serving the current disk source version."""
    previous_pids = previous_pids or set()
    deadline = time.monotonic() + timeout
    last_state = ""
    try:
        opener = status_opener()
    except (OSError, UnicodeError, subprocess.SubprocessError):
        print("重启校验失败：无法读取本地登录配置，请检查 .env.private。")
        return False
    while time.monotonic() < deadline:
        try:
            with opener.open(
                f"http://127.0.0.1:{PORT}/api/server-status?_=restart-check",
                timeout=1.5,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Invalid status response")
            pid = int(payload.get("pid") or 0)
            source_status = payload.get("source_status")
            if pid and pid not in previous_pids and source_status == "current":
                print(
                    f"已确认新服务进程 {pid} 正在运行，源码版本 {payload.get('runtime_source_version')} 与磁盘一致。"
                )
                return True
            last_state = f"pid={pid}, source_status={source_status}"
        except urllib.error.HTTPError as exc:
            last_state = f"HTTP {exc.code}"
        except (OSError, ValueError, TypeError, urllib.error.URLError):
            last_state = "连接失败"
        time.sleep(0.5)
    print(f"重启校验失败：服务未在 {timeout:.0f} 秒内加载当前源码（{last_state or '尚未响应'}）。")
    return False


def bootstrap_launch_agent(label: str, plist_path: Path) -> bool:
    """Load an installed-but-unloaded LaunchAgent and start it."""
    previous_pids = set(listening_pids())
    domain = f"gui/{os.getuid()}"
    service = f"{domain}/{label}"
    completed = subprocess.run(
        ["launchctl", "bootstrap", domain, str(plist_path)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if completed.returncode != 0 and not launch_agent_is_loaded(label):
        print(f"自动启动服务加载失败：{(completed.stdout or '').strip()}")
        return False
    completed = subprocess.run(
        ["launchctl", "kickstart", "-k", service],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if completed.returncode != 0:
        print(f"自动启动服务启动失败：{(completed.stdout or '').strip()}")
        return False
    print(f"已恢复自动启动服务 {label}：http://localhost:{PORT}")
    return wait_for_verified_server(previous_pids)


def main() -> int:
    disable_autostart = "--disable-autostart" in sys.argv
    delay_seconds = 0.0
    if "--delay" in sys.argv:
        try:
            delay_seconds = max(0.0, float(sys.argv[sys.argv.index("--delay") + 1]))
        except (ValueError, IndexError):
            print("--delay 参数需要填写有效秒数。")
            return 2
    if delay_seconds:
        time.sleep(delay_seconds)

    # 私有部署使用单独的 LaunchAgent 标签和入口脚本。优先重启当前真正
    # 已加载的服务，不能仅凭某个历史 plist 文件是否存在来判断。
    if not disable_autostart:
        for loaded_label in (PRIVATE_LAUNCH_AGENT_LABEL, LAUNCH_AGENT_LABEL):
            if not launch_agent_is_loaded(loaded_label):
                continue
            service = f"gui/{os.getuid()}/{loaded_label}"
            previous_pids = set(listening_pids())
            completed = subprocess.run(
                ["launchctl", "kickstart", "-k", service], check=False,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            if completed.returncode != 0:
                print(f"自动启动服务重启失败：{(completed.stdout or '').strip()}")
                return 1
            print(f"已通过自动启动服务 {loaded_label} 重启：http://localhost:{PORT}")
            return 0 if wait_for_verified_server(previous_pids) else 1

        # 私有部署的 plist 可能因迁移、注销或手工 bootout 留在磁盘上，
        # 但没有加载到当前用户的 launchd 域。旧逻辑会在此启动一个孤立
        # 的 uvicorn 进程，令完全磁盘访问权限的责任进程发生漂移。
        # 先释放端口，再恢复正式 LaunchAgent，确保后续重启始终走同一路径。
        if PRIVATE_LAUNCH_AGENT_PATH.exists():
            if not stop_listeners():
                return 1
            return 0 if bootstrap_launch_agent(
                PRIVATE_LAUNCH_AGENT_LABEL, PRIVATE_LAUNCH_AGENT_PATH
            ) else 1

    if LAUNCH_AGENT_PATH.exists():
        print(f"检测到自动启动项：{LAUNCH_AGENT_PATH}")
        if disable_autostart:
            uid = os.getuid()
            subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LAUNCH_AGENT_LABEL}"], check=False)
            disabled_path = LAUNCH_AGENT_PATH.with_suffix(".plist.disabled")
            try:
                shutil.move(str(LAUNCH_AGENT_PATH), str(disabled_path))
                print(f"已停用自动启动项：{disabled_path}")
            except PermissionError:
                print("无权限移动自动启动项，请手动删除或改名该 plist 文件。")
                return 1
        elif launch_agent_is_loaded():
            # 由 launchd 管理时必须让同一个 LaunchAgent 完成重启；若继续在此
            # 启动独立 uvicorn，会与 KeepAlive 进程争用端口并形成反复拉起循环。
            service = f"gui/{os.getuid()}/{LAUNCH_AGENT_LABEL}"
            previous_pids = set(listening_pids())
            completed = subprocess.run(
                ["launchctl", "kickstart", "-k", service], check=False,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            if completed.returncode != 0:
                print(f"自动启动服务重启失败：{(completed.stdout or '').strip()}")
                return 1
            print(f"已通过自动启动服务重启：http://localhost:{PORT}")
            return 0 if wait_for_verified_server(previous_pids) else 1
        else:
            # 常见于配置文件遗留、LaunchAgent 被手动 bootout 的情况。
            # 此时 kickstart 必然报 "Could not find service"；继续走下方的
            # 普通停止/启动流程，确保网页上的重启按钮仍然可用。
            print("自动启动配置存在但服务未加载，改用普通进程方式重启。")

    previous_pids = set(listening_pids())
    if not stop_listeners():
        return 1

    log_path = BASE_DIR / "server.log"
    pid_path = BASE_DIR / "server.pid"
    env = os.environ.copy()
    env["PORT"] = PORT
    env["LEGAL_KB_HOST"] = HOST
    with log_path.open("a", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", HOST, "--port", PORT],
            cwd=BASE_DIR,
            stdout=log,
            stderr=log,
            start_new_session=True,
            env=env,
        )
    pid_path.write_text(str(proc.pid), encoding="utf-8")
    print(f"新版法律操作系统已启动：http://localhost:{PORT}（PID {proc.pid}）")
    return 0 if wait_for_verified_server(previous_pids) else 1


if __name__ == "__main__":
    raise SystemExit(main())
