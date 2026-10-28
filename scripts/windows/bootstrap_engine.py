"""Small frozen installer worker. No business modules or user data in this binary.

The Tauri host talks newline-delimited JSON on stdout/stdin. Installation plans
are authenticated before any payload is downloaded. No server-supplied command
line is executed. The same worker supports a signed adjacent offline catalog.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import ctypes
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable
from urllib.parse import urljoin, urlsplit

import requests

MAX_CATALOG = 4 * 1024 * 1024
IDS = {"server", "browser", "ocr", "converter", "node"}
REQUIRED = {"server", "browser", "ocr", "converter"}
HEX = re.compile(r"^[0-9a-f]{64}$")
RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", re.I)
SLOW_WINDOW = 30
MIN_DOWNLOAD_RATE = 64 * 1024


class InstallError(RuntimeError):
    pass


class SlowDownload(requests.RequestException):
    pass


def emit(kind: str, **data):
    print(json.dumps({"event": kind, **data}, ensure_ascii=False), flush=True)


def digest(path: Path, progress=None) -> str:
    value = hashlib.sha256()
    received = 0
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(part)
            received += len(part)
            if progress:
                progress(received)
    return value.hexdigest()


def wait_for_server(child, ready, stop, notify, timeout=120):
    """Report failure before cooperative shutdown, which may itself need to wait."""
    began = time.monotonic()
    next_report = began
    while True:
        code = child.poll()
        if code is not None:
            raise InstallError(f"本地服务启动失败（退出码 {code}）。请查看 %LOCALAPPDATA%\\Stella\\userdata\\server.log")
        if stop.is_set():
            raise InstallError("启动已取消，正在等待后台安全结束")
        if ready.exists():
            return
        now = time.monotonic()
        if now - began >= timeout:
            raise InstallError("本地服务启动超过两分钟。请查看 %LOCALAPPDATA%\\Stella\\userdata\\server.log；后台安全结束前无法再次启动")
        if now >= next_report:
            notify("startup_wait", elapsed_seconds=int(now - began), timeout_seconds=timeout)
            next_report = now + 2
        stop.wait(0.2)


def safe_path(raw: str) -> PurePosixPath:
    if not isinstance(raw, str) or not raw or "\\" in raw or ":" in raw:
        raise InstallError("组件中包含非法路径")
    value = PurePosixPath(raw)
    if value.is_absolute() or any(p in {".", ".."} for p in raw.split("/")):
        raise InstallError("组件路径越界")
    if any(not p or p[-1:] in {".", " "} or RESERVED.match(p) or
           any(ord(c) < 32 or c in '<>"|?*' for c in p) for p in raw.split("/")):
        raise InstallError("组件路径不适用于 Windows")
    return value


def atomic_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextlib.contextmanager
def exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            try:
                stream.seek(0, os.SEEK_END)
                if stream.tell() == 0:
                    stream.write(b"0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise InstallError("Stella 正在运行或另一个安装正在进行，请先退出后重试") from exc
        else:
            import fcntl
            try:
                stream.seek(0)
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise InstallError("另一个 Stella 进程正在使用此目录") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def architecture() -> str:
    if os.name == "nt":
        process, native = ctypes.c_ushort(), ctypes.c_ushort()
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        kernel.IsWow64Process2.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ushort), ctypes.POINTER(ctypes.c_ushort)]
        if not kernel.IsWow64Process2(kernel.GetCurrentProcess(), ctypes.byref(process), ctypes.byref(native)):
            raise InstallError("无法识别系统架构")
        return {0x8664: "x86_64", 0xAA64: "arm64", 0x014c: "x86"}.get(native.value, "unknown")
    return platform.machine().lower()


def office_executable(component):
    console = component / 'program/soffice.com'
    return console if console.is_file() else component / 'program/soffice.exe'


def supported_windows(arch, version):
    """Windows 10 1809+ x64 workstations across Home, Pro and Enterprise."""
    return (arch == "x86_64" and version.major == 10 and
            version.build >= 17763 and version.product_type == 1)


def probe(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile(dir=root):
        pass
    arch = architecture()
    version = sys.getwindowsversion() if os.name == "nt" else None
    build = version.build if version else 0
    return {"os": sys.platform, "architecture": arch, "windows_build": build,
            "supported": version is not None and supported_windows(arch, version),
            "free_bytes": shutil.disk_usage(root).free,
            "installed": (root / "active.json").is_file()}


class Installer:
    def __init__(self, root: Path, config: dict, notify: Callable = emit):
        self.root = root
        self.config = config
        self.notify = notify
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Stella-Windows-Installer/1", "Accept-Encoding": "identity"})

    def validate_url(self, raw: str):
        url = urlsplit(raw)
        if url.scheme != "https" or url.username or url.password or url.fragment or url.port not in (None, 443):
            raise InstallError("下载地址必须是可信 HTTPS 地址")
        if url.hostname not in self.config["allowed_hosts"]:
            raise InstallError("下载地址不在已授权的组件服务器中")

    def get(self, url: str, headers=None):
        for _ in range(6):
            self.validate_url(url)
            response = self.session.get(url, headers=headers or {}, stream=True,
                                        timeout=(10, 30), allow_redirects=False)
            if response.status_code not in (301, 302, 303, 307, 308):
                return response
            target = response.headers.get("Location", "")
            response.close()
            if not target:
                raise InstallError("下载服务器返回无效跳转")
            url = urljoin(url, target)
        raise InstallError("下载跳转次数过多")

    def read_catalog(self, path: Path | None = None):
        if path:
            if path.stat().st_size > MAX_CATALOG:
                raise InstallError("组件清单过大")
            envelope = json.loads(path.read_bytes())
        else:
            endpoint = self.config.get("catalog_url")
            if not endpoint:
                raise InstallError("Windows 下载通道尚未配置；此版本仅供开发验证")
            with self.get(endpoint) as response:
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_content(65536):
                    body.extend(chunk)
                    if len(body) > MAX_CATALOG:
                        raise InstallError("组件清单过大")
            envelope = json.loads(body)
        return envelope, self.verify(envelope)

    def verify(self, envelope, *, installing=True):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        try:
            payload = base64.b64decode(envelope["payload"], validate=True)
            if len(payload) > MAX_CATALOG:
                raise ValueError("size")
            key = Ed25519PublicKey.from_public_bytes(base64.b64decode(self.config["public_key"], validate=True))
            key.verify(base64.b64decode(envelope["signature"], validate=True), payload)
            data = json.loads(payload)
        except Exception as exc:
            raise InstallError("组件清单签名无效，请重新获取官方安装程序") from exc
        if data.get("schema") != 1 or data.get("target") != "windows-x86_64":
            raise InstallError("组件清单不适用于此安装器")
        if type(data.get("build")) is not int or data["build"] <= 0:
            raise InstallError("版本编号无效")
        if not re.fullmatch(r"\d+\.\d+\.\d+", data.get("version", "")):
            raise InstallError("版本信息无效")
        if type(data.get("expires_at")) is not int or installing and data["expires_at"] <= time.time():
            raise InstallError("安装清单已过期，请联网重新检查")
        components = data.get("components")
        if not isinstance(components, list) or not 4 <= len(components) <= 5:
            raise InstallError("组件清单不完整")
        seen = set()
        for c in components:
            name = c.get("id")
            if name not in IDS or name in seen:
                raise InstallError("组件编号无效")
            seen.add(name)
            if not HEX.fullmatch(c.get("sha256", "")):
                raise InstallError("组件校验值无效")
            for field in ("bytes", "expanded_bytes"):
                if type(c.get(field)) is not int or not 0 < c[field] <= 8 * 1024**3:
                    raise InstallError("组件大小无效")
            files = c.get("files")
            if not isinstance(files, dict) or not 1 <= len(files) <= 30000:
                raise InstallError("组件文件清单无效")
            folded = set()
            for name, checksum in files.items():
                safe_path(name)
                if name.casefold() in folded or not HEX.fullmatch(checksum):
                    raise InstallError("组件存在重复文件或无效校验值")
                folded.add(name.casefold())
            self.validate_url(c["url"])
            mirrors = c.get("mirrors", [])
            if not isinstance(mirrors, list) or len(mirrors) > 3 or any(not isinstance(url, str) for url in mirrors):
                raise InstallError("组件备用下载地址无效")
            for url in mirrors:
                self.validate_url(url)
        if not REQUIRED <= seen:
            raise InstallError("缺少运行所需组件")
        # Entrypoints are fixed by the client, never executable commands from the feed.
        expected = {"server": "StellaServer.exe", "browser": "chrome.exe",
                    "ocr": "tesseract.exe", "converter": "program/soffice.exe"}
        for c in components:
            if c["id"] in expected and expected[c["id"]] not in c["files"]:
                raise InstallError("缺少组件启动文件")
        return data

    def component_dir(self, c):
        return self.root / "components" / c["id"] / c["sha256"]

    def intact(self, c, phase=None):
        root = self.component_dir(c)
        if not root.is_dir() or root.is_symlink():
            return False
        actual = set()
        checked, tick, processed = 0, 0.0, 0
        began = time.monotonic()
        def report(file_bytes=0, force=False):
            nonlocal tick
            now = time.monotonic()
            if phase and (force or now - tick >= 0.5):
                elapsed = now - began
                received = processed + file_bytes
                self.notify("verification", component=c["id"], phase=phase,
                            checked=checked, total=len(c["files"]), received=received,
                            expanded_bytes=c["expanded_bytes"], elapsed_seconds=round(elapsed, 1),
                            eta_seconds=round(max(0, c["expanded_bytes"] - received) * elapsed / received) if received and elapsed >= 3 else None)
                tick = now
        for path in root.rglob("*"):
            if path.is_symlink():
                return False
            if path.is_file():
                name = path.relative_to(root).as_posix()
                actual.add(name)
                if name not in c["files"] or digest(path, report if phase else None) != c["files"][name]:
                    return False
                checked += 1
                processed += path.stat().st_size
                report(force=checked == len(c["files"]))
        return actual == set(c["files"])

    def plan(self, data, phase="plan_verify"):
        result = [{"id": c["id"], "bytes": c["bytes"], "expanded_bytes": c["expanded_bytes"],
                   "file_count": len(c["files"]), "reuse": self.intact(c, phase)} for c in data["components"]]
        needed = sum(c["bytes"] + 2 * c["expanded_bytes"] for c, state in zip(data["components"], result) if not state["reuse"])
        return {"version": data["version"], "build": data["build"], "components": result,
                "download_bytes": sum(c["bytes"] for c in result if not c["reuse"]),
                "required_free_bytes": needed + 256 * 1024**2}

    def download(self, c, offline: Path | None):
        cache = self.root / "cache"
        cache.mkdir(parents=True, exist_ok=True)
        target = cache / (c["sha256"] + ".zip")
        part = target.with_suffix(".part")
        if target.is_symlink() or part.is_symlink():
            raise InstallError("组件缓存不允许包含链接")
        self.notify("phase", component=c["id"], phase="verify_archive")
        if target.is_file() and target.stat().st_size == c["bytes"] and digest(target) == c["sha256"]:
            self.notify("download_complete", component=c["id"], total=c["bytes"], cached=True)
            return target
        target.unlink(missing_ok=True)
        local = offline / (c["id"] + ".zip") if offline else None
        if local and local.is_file():
            if local.is_symlink() or local.stat().st_size != c["bytes"]:
                raise InstallError("离线组件校验失败：" + c["id"])
            checksum = hashlib.sha256()
            with local.open("rb") as src, part.open("wb") as dst:
                for chunk in iter(lambda: src.read(1024 * 1024), b""):
                    checksum.update(chunk)
                    dst.write(chunk)
            if checksum.hexdigest() != c["sha256"]:
                part.unlink(missing_ok=True)
                raise InstallError("离线组件校验失败：" + c["id"])
        else:
            sources = list(dict.fromkeys([c["url"], *c.get("mirrors", [])]))
            # Every source was authenticated by verify(), and redirects remain allowlisted.
            for url in sources:
                self.validate_url(url)
            attempts = max(3, len(sources))
            for attempt in range(attempts):
                source = sources[attempt % len(sources)]
                start = part.stat().st_size if part.exists() else 0
                if start >= c["bytes"]:
                    part.unlink(missing_ok=True)
                    start = 0
                try:
                    checksum = hashlib.sha256()
                    if start:
                        self.notify("phase", component=c["id"], phase="verify_resume")
                        with part.open("rb") as prefix:
                            for chunk in iter(lambda: prefix.read(1024 * 1024), b""):
                                checksum.update(chunk)
                    self.notify("phase", component=c["id"], phase="download",
                                source=urlsplit(source).hostname, attempt=attempt + 1)
                    with self.get(source, {"Range": f"bytes={start}-"} if start else {}) as response:
                        response.raise_for_status()
                        if response.status_code == 206:
                            expected = f"bytes {start}-{c['bytes']-1}/{c['bytes']}"
                            if response.headers.get("Content-Range") != expected:
                                raise InstallError("下载续传范围不一致")
                        elif response.status_code == 200:
                            start = 0
                            checksum = hashlib.sha256()
                        else:
                            raise InstallError("下载服务器响应无效")
                        self.notify("phase", component=c["id"], phase="download",
                                    source=urlsplit(source).hostname, attempt=attempt + 1)
                        received = start
                        began = tick = window_at = time.monotonic()
                        window_bytes = 0
                        self.notify("progress", component=c["id"], received=received, total=c["bytes"],
                                    speed_bytes_per_second=0, eta_seconds=None, source=urlsplit(source).hostname)
                        with part.open("ab" if start else "wb") as out:
                            for chunk in response.iter_content(16384):
                                received += len(chunk)
                                if received > c["bytes"]:
                                    raise InstallError("下载组件超出预期大小")
                                out.write(chunk)
                                checksum.update(chunk)
                                window_bytes += len(chunk)
                                now = time.monotonic()
                                rate = (received - start) / max(now - began, 0.001)
                                if now - tick >= 0.5 or received == c["bytes"]:
                                    self.notify("progress", component=c["id"], received=received, total=c["bytes"],
                                                speed_bytes_per_second=round(rate),
                                                elapsed_seconds=round(now - began, 1),
                                                eta_seconds=round((c["bytes"] - received) / rate) if rate > 0 else None,
                                                source=urlsplit(source).hostname)
                                    tick = now
                                if now - window_at >= SLOW_WINDOW:
                                    if window_bytes / (now - window_at) < MIN_DOWNLOAD_RATE and received < c["bytes"]:
                                        raise SlowDownload()
                                    window_at, window_bytes = now, 0
                    self.notify("phase", component=c["id"], phase="verify_archive")
                    if received == c["bytes"] and checksum.hexdigest() == c["sha256"]:
                        break
                    part.unlink(missing_ok=True)
                    self.notify("download_reset", component=c["id"])
                    reason = "checksum"
                except requests.RequestException as exc:
                    reason = "slow" if isinstance(exc, SlowDownload) else "network"
                if attempt + 1 < attempts:
                    self.notify("retry", component=c["id"], reason=reason, attempt=attempt + 2,
                                switching_source=len(sources) > 1)
                elif reason != "checksum":
                    raise InstallError("组件下载持续缓慢或中断，已保留进度，可切换网络后重试") from None
            else:
                raise InstallError("组件校验失败，请重试")
        if part.stat().st_size != c["bytes"]:
            raise InstallError("组件文件校验失败")
        os.replace(part, target)
        self.notify("download_complete", component=c["id"], total=c["bytes"], cached=bool(local and local.is_file()))
        return target

    def extract(self, c, archive: Path):
        target = self.component_dir(c)
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=".staging-", dir=target.parent))
        try:
            count, total, seen, tick, written = 0, 0, set(), 0.0, 0
            began = time.monotonic()
            def report(checked):
                elapsed = time.monotonic() - began
                self.notify("verification", component=c["id"], phase="verify_extract",
                            checked=checked, total=len(c["files"]), received=written,
                            expanded_bytes=c["expanded_bytes"], elapsed_seconds=round(elapsed, 1),
                            eta_seconds=round(max(0, c["expanded_bytes"] - written) * elapsed / written) if written and elapsed >= 3 else None)
            with zipfile.ZipFile(archive) as z:
                if len(z.infolist()) > 60000:
                    raise InstallError("组件文件过多")
                for item in z.infolist():
                    name = item.filename.rstrip("/")
                    path = safe_path(name)
                    kind = (item.external_attr >> 16) & 0o170000
                    if kind not in (0, 0o100000, 0o040000):
                        raise InstallError("组件不允许包含链接或特殊文件")
                    if item.is_dir():
                        continue
                    if name not in c["files"] or name.casefold() in seen:
                        raise InstallError("组件文件与签名清单不一致")
                    seen.add(name.casefold())
                    total += item.file_size
                    count += 1
                    if total > c["expanded_bytes"]:
                        raise InstallError("组件解压大小超过限制")
                    dest = stage.joinpath(*path.parts)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    checksum = hashlib.sha256()
                    with z.open(item) as src, dest.open("xb") as dst:
                        for chunk in iter(lambda: src.read(1024 * 1024), b""):
                            checksum.update(chunk)
                            dst.write(chunk)
                            written += len(chunk)
                            if time.monotonic() - tick >= 0.5:
                                report(count - 1)
                                tick = time.monotonic()
                    if checksum.hexdigest() != c["files"][name]:
                        raise InstallError("组件内文件校验失败")
                    if time.monotonic() - tick >= 0.5 or count == len(c["files"]):
                        report(count)
                        tick = time.monotonic()
            if count != len(c["files"]) or total != c["expanded_bytes"]:
                raise InstallError("组件内容不完整")
            if target.exists():
                shutil.rmtree(target)
            os.replace(stage, target)
        finally:
            if stage.exists():
                shutil.rmtree(stage)

    def install(self, envelope, offline: Path | None = None):
        data = self.verify(envelope)
        self.root.mkdir(parents=True, exist_ok=True)
        with exclusive_lock(self.root / "lifecycle.lock"):
            active = self.root / "active.json"
            if active.exists():
                old = self.verify(json.loads(active.read_bytes()), installing=False)
                if data["build"] < old["build"]:
                    raise InstallError("不能安装低于当前版本的组件")
                if data["build"] == old["build"] and data != old:
                    raise InstallError("同一版本的组件清单发生变化")
            self.notify("phase", phase="plan_verify")
            plan = self.plan(data)
            self.notify("plan", **plan)
            if shutil.disk_usage(self.root).free < plan["required_free_bytes"]:
                raise InstallError("磁盘空间不足，请清理空间后重试")
            for c, state in zip(data["components"], plan["components"]):
                if not state["reuse"]:
                    self.notify("phase", component=c["id"], phase="download")
                    archive = self.download(c, offline)
                    self.notify("phase", component=c["id"], phase="verify_extract")
                    self.extract(c, archive)
                    self.notify("component_extracted", component=c["id"])
            # Existing components passed plan(); new files passed streaming extraction hashes.
            # Keep the full post-health disk read before switching the active pointer.
            self.notify('phase', component='server', phase='self_test')
            self.health_check(data)
            self.notify('phase', phase='final_verify')
            for component in data['components']:
                if not self.intact(component, 'final_verify'):
                    raise InstallError('组件自检改写了安装文件，原有版本保持不变')
            if active.exists():
                atomic_json(self.root / "previous.json", json.loads(active.read_bytes()))
            atomic_json(active, envelope)
        self.notify("installed", version=data["version"], build=data["build"])
        return data

    def health_check(self, data):
        """Run fixed, offline smoke checks before declaring a component set usable."""
        components = {c['id']: self.component_dir(c) for c in data['components']}
        flags = {'creationflags': 0x08000000} if os.name == 'nt' else {}
        with tempfile.TemporaryDirectory(prefix='stella-component-check-') as directory:
            folder = Path(directory)
            def run(args, timeout=45):
                try:
                    result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                            stderr=subprocess.PIPE, timeout=timeout,
                                            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}, **flags)
                except (OSError, subprocess.SubprocessError):
                    raise InstallError('组件无法在当前电脑启动，请修复安装或检查系统限制') from None
                if result.returncode:
                    raise InstallError('组件运行自检未通过，原有版本保持不变')
                return result.stdout
            run([str(components['server'] / 'StellaServer.exe'), '--self-test-components'], 90)
            self.notify('self_test_progress', checked=1, total=4)
            languages = run([str(components['ocr'] / 'tesseract.exe'), '--list-langs',
                             '--tessdata-dir', str(components['ocr'] / 'tessdata')]).decode('utf-8', errors='replace')
            if 'chi_sim' not in languages or 'eng' not in languages:
                raise InstallError('缺少中文或英文文字识别语言数据')
            self.notify('self_test_progress', checked=2, total=4)
            html = folder / 'check.html'
            html.write_text('<html><body>stella-component-ready</body></html>')
            rendered = run([str(components['browser'] / 'chrome.exe'), '--headless', '--disable-gpu',
                            '--no-first-run', '--no-default-browser-check', '--disable-breakpad', '--disable-crash-reporter',
                            '--enable-logging=stderr',
                            '--user-data-dir=' + str(folder / 'browser'), '--dump-dom', html.as_uri()])
            if b'stella-component-ready' not in rendered:
                raise InstallError('浏览器组件未能完成页面渲染')
            self.notify('self_test_progress', checked=3, total=4)
            document = folder / 'check.txt'
            document.write_text('Stella document conversion check', encoding='utf-8')
            run([str(office_executable(components['converter'])),
                 '-env:UserInstallation=' + (folder / 'office').as_uri(), '--headless',
                 '--convert-to', 'pdf', '--outdir', str(folder), str(document)], 90)
            pdf = folder / 'check.pdf'
            if not pdf.is_file() or not pdf.read_bytes().startswith(b'%PDF-'):
                raise InstallError('文档转换组件未能生成有效 PDF')
            self.notify('self_test_progress', checked=4, total=4)

    def launch(self):
        self.notify("phase", phase="launch_verify")
        envelope = json.loads((self.root / "active.json").read_bytes())
        data = self.verify(envelope, installing=False)
        with exclusive_lock(self.root / "lifecycle.lock"):
            components = {c["id"]: self.component_dir(c) for c in data["components"]}
            entrypoints = {"server": "StellaServer.exe", "browser": "chrome.exe",
                           "ocr": "tesseract.exe", "converter": "program/soffice.exe"}
            if not all(self.component_dir(c).is_dir() and
                       (c["id"] not in entrypoints or
                        (self.component_dir(c) / entrypoints[c["id"]]).is_file())
                       for c in data["components"]):
                raise InstallError("已安装组件损坏，请在安装界面修复")
            runtime = self.root / "userdata"
            runtime.mkdir(parents=True, exist_ok=True)
            token = uuid.uuid4().hex
            ready = runtime / ("server-ready-" + token)
            env = dict(os.environ)
            env['PYTHONDONTWRITEBYTECODE'] = '1'
            env.update({"LEGAL_KB_BROWSER_EXECUTABLE": str(components["browser"] / "chrome.exe"),
                        "LEGAL_KB_SOFFICE": str(office_executable(components["converter"])),
                        "TESSERACT_CMD": str(components["ocr"] / "tesseract.exe"),
                        "TESSDATA_PREFIX": str(components["ocr"] / "tessdata"),
                        "STELLA_COMPONENT_ROOT": str(self.root / "components")})
            env["PATH"] = os.pathsep.join([str(components["ocr"]), str(components["converter"] / "program"), str(components.get("node", components["server"])), env.get("PATH", "")])
            stop = threading.Event()
            metrics_wake = threading.Event()
            def listen():
                for line in sys.stdin:
                    if line.strip() == "metrics-wake":
                        metrics_wake.set()
                    if line.strip() == "stop":
                        break
                stop.set()  # Parent pipe closing is also an orderly exit request.
                metrics_wake.set()
            threading.Thread(target=listen, daemon=True).start()
            with (runtime / "server.log").open("a", encoding="utf-8") as log:
                self.notify("phase", phase="launch_service")
                child = subprocess.Popen([str(components["server"] / "StellaServer.exe"),
                    "--runtime", str(runtime), "--app-build", str(data["build"]), "--ready-token", token,
                    "--shutdown-file", str(runtime / ("stop-" + token))], env=env, stdout=log, stderr=log,
                    creationflags=0x08000000 if os.name == "nt" else 0)
                try:
                    try:
                        wait_for_server(child, ready, stop, self.notify)
                    except InstallError as exc:
                        # The host cannot finish its command until shutdown completes.
                        # Deliver the reason now so a stuck import never hides it.
                        self.notify("launch_failed", message=str(exc), cleanup_pending=child.poll() is None)
                        raise
                    ready.unlink(missing_ok=True)
                    self.notify("ready", url="http://127.0.0.1:18865/", build=data["build"])
                    from windows_telemetry import Statistics
                    statistics = Statistics(self.root, data["build"], exclusive_lock, atomic_json)
                    def report_statistics():
                        while not stop.is_set():
                            metrics_wake.wait(statistics.run_due())
                            metrics_wake.clear()
                    threading.Thread(target=report_statistics, daemon=True).start()
                    while not stop.wait(0.5):
                        if child.poll() is not None:
                            raise InstallError("本地服务已停止，请重新启动 Stella")
                finally:
                    stop.set()
                    metrics_wake.set()
                    shutdown = runtime / ("stop-" + token)
                    shutdown.touch()
                    try:
                        child.wait(timeout=40)
                    except subprocess.TimeoutExpired:
                        # Never kill a potentially writing database to make an update succeed.
                        self.notify("shutdown_wait", message="仍在保存工作，等待后台安全结束")
                        child.wait()
                    shutdown.unlink(missing_ok=True)


def load_config():
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return json.loads((base / "bootstrap-config.json").read_bytes())


def main():
    if sys.stdout is not None and hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("probe", "plan", "install", "launch", "check", "metrics-status", "metrics-allow", "metrics-deny"))
    parser.add_argument("--catalog", type=Path)
    args = parser.parse_args()
    root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Stella"
    try:
        if args.action == "probe":
            emit("probe", **probe(root))
            return
        engine = Installer(root, load_config())
        if args.action.startswith("metrics-"):
            from windows_telemetry import Statistics
            data = engine.verify(json.loads((root / "active.json").read_bytes()), installing=False)
            statistics = Statistics(root, data["build"], exclusive_lock, atomic_json)
            if args.action != "metrics-status":
                statistics.consent(args.action == "metrics-allow")
            emit("statistics", **statistics.status())
            return
        if args.action == "launch":
            engine.launch()
            return
        if not probe(root)["supported"]:
            raise InstallError("支持 Windows 10 1809（17763）及更新版本、Windows 11 的 Intel/AMD 64 位电脑；不支持 Windows Server 或 ARM 设备")
        envelope, data = engine.read_catalog(args.catalog)
        if args.action == "install":
            engine.install(envelope, args.catalog.parent if args.catalog else None)
        elif args.action == "check":
            active = root / "active.json"
            old = engine.verify(json.loads(active.read_bytes()), installing=False) if active.exists() else {"build": 0}
            emit("update", available=data["build"] > old["build"], version=data["version"], build=data["build"])
        else:
            emit("plan", **engine.plan(data))
    except Exception as exc:
        # Do not print requests URLs, cookies, proxy credentials or raw exception text.
        emit("error", message=str(exc) if isinstance(exc, InstallError) else "操作未完成，请检查网络或修复安装后重试")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
