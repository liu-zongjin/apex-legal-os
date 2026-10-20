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


class InstallError(RuntimeError):
    pass


def emit(kind: str, **data):
    print(json.dumps({"event": kind, **data}, ensure_ascii=False), flush=True)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(part)
    return value.hexdigest()


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
        stream.seek(0)
        stream.write(b"0")
        stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise InstallError("Stella 正在运行或另一个安装正在进行，请先退出后重试") from exc
        else:
            import fcntl
            try:
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


def probe(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile(dir=root):
        pass
    arch = architecture()
    build = sys.getwindowsversion().build if os.name == "nt" else 0
    return {"os": sys.platform, "architecture": arch, "windows_build": build,
            "supported": os.name == "nt" and arch == "x86_64" and build >= 22000 and sys.getwindowsversion().product_type == 1,
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

    def intact(self, c):
        root = self.component_dir(c)
        if not root.is_dir() or root.is_symlink():
            return False
        actual = set()
        for path in root.rglob("*"):
            if path.is_symlink():
                return False
            if path.is_file():
                name = path.relative_to(root).as_posix()
                actual.add(name)
                if name not in c["files"] or digest(path) != c["files"][name]:
                    return False
        return actual == set(c["files"])

    def plan(self, data):
        result = [{"id": c["id"], "bytes": c["bytes"], "reuse": self.intact(c)} for c in data["components"]]
        needed = sum(c["bytes"] + 2 * c["expanded_bytes"] for c, state in zip(data["components"], result) if not state["reuse"])
        return {"version": data["version"], "build": data["build"], "components": result,
                "download_bytes": sum(c["bytes"] for c in result if not c["reuse"]),
                "required_free_bytes": needed + 256 * 1024**2}

    def download(self, c, offline: Path | None):
        cache = self.root / "cache"
        cache.mkdir(parents=True, exist_ok=True)
        target = cache / (c["sha256"] + ".zip")
        if target.is_file() and target.stat().st_size == c["bytes"] and digest(target) == c["sha256"]:
            return target
        target.unlink(missing_ok=True)
        part = target.with_suffix(".part")
        local = offline / (c["id"] + ".zip") if offline else None
        if local and local.is_file():
            if local.is_symlink() or local.stat().st_size != c["bytes"] or digest(local) != c["sha256"]:
                raise InstallError("离线组件校验失败：" + c["id"])
            shutil.copyfile(local, part)
        else:
            for attempt in range(3):
                start = part.stat().st_size if part.exists() else 0
                if start >= c["bytes"]:
                    part.unlink(missing_ok=True)
                    start = 0
                try:
                    with self.get(c["url"], {"Range": f"bytes={start}-"} if start else {}) as response:
                        response.raise_for_status()
                        if response.status_code == 206:
                            expected = f"bytes {start}-{c['bytes']-1}/{c['bytes']}"
                            if response.headers.get("Content-Range") != expected:
                                raise InstallError("下载续传范围不一致")
                        elif response.status_code == 200:
                            start = 0
                        else:
                            raise InstallError("下载服务器响应无效")
                        received = start
                        tick = 0.0
                        with part.open("ab" if start else "wb") as out:
                            for chunk in response.iter_content(262144):
                                received += len(chunk)
                                if received > c["bytes"]:
                                    raise InstallError("下载组件超出预期大小")
                                out.write(chunk)
                                if time.monotonic() - tick > 0.2:
                                    self.notify("progress", component=c["id"], received=received, total=c["bytes"])
                                    tick = time.monotonic()
                    if received == c["bytes"] and digest(part) == c["sha256"]:
                        break
                    part.unlink(missing_ok=True)
                except requests.RequestException:
                    if attempt == 2:
                        raise InstallError("组件下载中断，可保留进度后重试") from None
            else:
                raise InstallError("组件校验失败，请重试")
        if part.stat().st_size != c["bytes"] or digest(part) != c["sha256"]:
            raise InstallError("组件文件校验失败")
        os.replace(part, target)
        return target

    def extract(self, c, archive: Path):
        target = self.component_dir(c)
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=".staging-", dir=target.parent))
        try:
            count, total, seen = 0, 0, set()
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
                    with z.open(item) as src, dest.open("xb") as dst:
                        shutil.copyfileobj(src, dst)
                    if digest(dest) != c["files"][name]:
                        raise InstallError("组件内文件校验失败")
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
            plan = self.plan(data)
            if shutil.disk_usage(self.root).free < plan["required_free_bytes"]:
                raise InstallError("磁盘空间不足，请清理空间后重试")
            for c in data["components"]:
                if not self.intact(c):
                    self.notify("phase", component=c["id"], phase="download")
                    archive = self.download(c, offline)
                    self.notify("phase", component=c["id"], phase="verify_extract")
                    self.extract(c, archive)
            # Only switch after every component is intact. The old pointer survives failures.
            for c in data["components"]:
                if not self.intact(c):
                    raise InstallError("组件安装后校验未通过")
            self.notify('phase', component='server', phase='self_test')
            self.health_check(data)
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
                                            stderr=subprocess.PIPE, timeout=timeout, **flags)
                except (OSError, subprocess.SubprocessError):
                    raise InstallError('组件无法在当前电脑启动，请修复安装或检查系统限制') from None
                if result.returncode:
                    raise InstallError('组件运行自检未通过，原有版本保持不变')
                return result.stdout
            run([str(components['server'] / 'StellaServer.exe'), '--self-test-components'], 90)
            languages = run([str(components['ocr'] / 'tesseract.exe'), '--list-langs',
                             '--tessdata-dir', str(components['ocr'] / 'tessdata')]).decode('utf-8', errors='replace')
            if 'chi_sim' not in languages or 'eng' not in languages:
                raise InstallError('缺少中文或英文文字识别语言数据')
            html = folder / 'check.html'
            html.write_text('<html><body>stella-component-ready</body></html>')
            rendered = run([str(components['browser'] / 'chrome.exe'), '--headless', '--disable-gpu',
                            '--no-first-run', '--no-default-browser-check',
                            '--user-data-dir=' + str(folder / 'browser'), '--dump-dom', html.as_uri()])
            if b'stella-component-ready' not in rendered:
                raise InstallError('浏览器组件未能完成页面渲染')
            document = folder / 'check.txt'
            document.write_text('Stella document conversion check', encoding='utf-8')
            run([str(components['converter'] / 'program/soffice.exe'),
                 '-env:UserInstallation=' + (folder / 'office').as_uri(), '--headless',
                 '--convert-to', 'pdf', '--outdir', str(folder), str(document)], 90)
            pdf = folder / 'check.pdf'
            if not pdf.is_file() or not pdf.read_bytes().startswith(b'%PDF-'):
                raise InstallError('文档转换组件未能生成有效 PDF')

    def launch(self):
        envelope = json.loads((self.root / "active.json").read_bytes())
        data = self.verify(envelope, installing=False)
        with exclusive_lock(self.root / "lifecycle.lock"):
            components = {c["id"]: self.component_dir(c) for c in data["components"]}
            if not all(self.intact(c) for c in data["components"]):
                raise InstallError("已安装组件损坏，请在安装界面修复")
            runtime = self.root / "userdata"
            runtime.mkdir(parents=True, exist_ok=True)
            token = uuid.uuid4().hex
            ready = runtime / ("server-ready-" + token)
            env = dict(os.environ)
            env.update({"LEGAL_KB_BROWSER_EXECUTABLE": str(components["browser"] / "chrome.exe"),
                        "LEGAL_KB_SOFFICE": str(components["converter"] / "program/soffice.exe"),
                        "TESSERACT_CMD": str(components["ocr"] / "tesseract.exe"),
                        "TESSDATA_PREFIX": str(components["ocr"] / "tessdata"),
                        "STELLA_COMPONENT_ROOT": str(self.root / "components")})
            env["PATH"] = os.pathsep.join([str(components["ocr"]), str(components.get("node", components["server"])), env.get("PATH", "")])
            stop = threading.Event()
            def listen():
                for line in sys.stdin:
                    if line.strip() == "stop":
                        break
                stop.set()  # Parent pipe closing is also an orderly exit request.
            threading.Thread(target=listen, daemon=True).start()
            with (runtime / "server.log").open("a", encoding="utf-8") as log:
                child = subprocess.Popen([str(components["server"] / "StellaServer.exe"),
                    "--runtime", str(runtime), "--app-build", str(data["build"]), "--ready-token", token,
                    "--shutdown-file", str(runtime / ("stop-" + token))], env=env, stdout=log, stderr=log,
                    creationflags=0x08000000 if os.name == "nt" else 0)
                try:
                    deadline = time.monotonic() + 120
                    while not ready.exists():
                        if stop.wait(0.2) or child.poll() is not None or time.monotonic() > deadline:
                            raise InstallError("本地服务未能启动，请查看本机诊断日志或修复安装")
                    ready.unlink(missing_ok=True)
                    self.notify("ready", url="http://127.0.0.1:18865/", build=data["build"])
                    while not stop.wait(0.5):
                        if child.poll() is not None:
                            raise InstallError("本地服务已停止，请重新启动 Stella")
                finally:
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
    parser.add_argument("action", choices=("probe", "plan", "install", "launch", "check"))
    parser.add_argument("--catalog", type=Path)
    args = parser.parse_args()
    root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Stella"
    try:
        if args.action == "probe":
            emit("probe", **probe(root))
            return
        engine = Installer(root, load_config())
        if args.action == "launch":
            engine.launch()
            return
        if not probe(root)["supported"]:
            raise InstallError("首版仅支持 Windows 11 的 Intel/AMD 64 位电脑")
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
