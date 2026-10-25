"""SCNet OCR transport and private configuration, shared by tests and material parsing."""
import hashlib
import os
import re
import threading
import time
from io import BytesIO

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

OCR_URL = "https://api.scnet.cn/api/llm/v1/ocr/recognize"


class OcrError(RuntimeError):
    pass


def _failure(code, request_id=""):
    hints = {
        "401": "密钥无效或已失效，请检查当前 OCR 密钥",
        "402": "账户余额不足，请在 SCNet 控制台检查余额与 OCR 额度",
        "422": "请求参数被服务拒绝，请核对接口要求",
        "429": "请求过于频繁，请稍后重试",
        "430": "当前密钥没有服务授权，请在 SCNet 控制台检查权限",
        "431": "账户已停用，请联系 SCNet 客服",
        "433": "团队消费限额已达到上限，请联系账户管理员",
        "434": "免费额度已用尽或过期，请检查额度与付费设置",
        "435": "SCNet OCR 处理异常，请稍后重试；持续失败时请携请求编号联系平台客服",
        "436": "服务未能下载图片，请稍后重试",
        "437": "图片格式不受支持",
        "438": "图片超过 10 MB，请缩小图片后重试",
        "439": "服务未找到上传的图片，请重试",
        "440": "OCR 识别类型错误，请使用通用文字识别 GENERAL",
        "441": "上传文件超过 10 MB，请缩小后重试",
        "500": "OCR 服务内部异常，请稍后重试",
        "503": "OCR 服务繁忙，请稍后重试",
    }
    safe_code = str(code) if re.fullmatch(r"[A-Za-z0-9_-]{1,32}", str(code)) else "未知"
    hint = hints.get(str(code), "服务未返回有效识别结果，请稍后重试或联系平台客服")
    # Never echo a remote body, credential, uploaded filename or document text.
    identifier = str(request_id)
    suffix = f"；请求编号 {identifier}" if re.fullmatch(r"[A-Za-z0-9_-]{1,120}", identifier) else ""
    return OcrError(f"OCR 服务返回 {safe_code}：{hint}{suffix}")


def recognize(image_bytes, *, api_key, filename="page.png", retry_count=3):
    if not api_key:
        raise OcrError("尚未配置 OCR 密钥，请到设置 → OCR 配置与测试中配置")
    for attempt in range(max(1, min(retry_count, 3))):
        if attempt:
            time.sleep(3 * attempt)
        try:
            response = httpx.post(
                OCR_URL, headers={"Authorization": f"Bearer {api_key}"},
                data={"ocrType": "GENERAL"},
                files={"file": (filename, image_bytes, "image/png")}, timeout=60,
            )
            try:
                result = response.json()
            except ValueError:
                result = {}
            if response.status_code != 200:
                error = _failure(response.status_code, result.get("request_id", "") if isinstance(result, dict) else "")
                if response.status_code in {429, 435, 500, 503} and attempt + 1 < retry_count:
                    continue
                raise error
            if not isinstance(result, dict):
                raise OcrError("OCR 返回格式异常，请稍后重试")
            if str(result.get("code")) != "0":
                raise _failure(result.get("code", "未知"), result.get("request_id", ""))
            items = result.get("data", [])
            if isinstance(items, dict):
                items = items.get("result", [items])
            if not isinstance(items, list):
                raise OcrError("OCR 返回格式异常，请稍后重试")
            lines = []
            for item in items or []:
                rows = item.get("result", [item] if "elements" in item else []) if isinstance(item, dict) else []
                if not isinstance(rows, list):
                    raise OcrError("OCR 返回格式异常，请稍后重试")
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    if row.get("status", 200) != 200:
                        raise _failure(row["status"], result.get("request_id", ""))
                    elements = row.get("elements") or {}
                    if not isinstance(elements, dict):
                        raise OcrError("OCR 返回格式异常，请稍后重试")
                    texts = elements.get("text") or elements.get("words_result") or []
                    if not isinstance(texts, list) or any(not isinstance(text, dict) for text in texts):
                        raise OcrError("OCR 返回格式异常，请稍后重试")
                    for text in texts:
                        word = str(text.get("text") or text.get("words") or "").strip()
                        if word:
                            lines.append(word)
            return "\n".join(lines)
        except httpx.RequestError:
            if attempt + 1 >= retry_count:
                raise OcrError("无法连接 OCR 服务或请求超时，请检查网络后重试") from None
    raise OcrError("OCR 服务暂时不可用，请稍后重试")


class OcrUpdate(BaseModel):
    key_mode: str
    api_key: str = Field(default="", max_length=4096)

    class Config:
        extra = "forbid"


class OcrSettings:
    def __init__(self, read_secret, save_secrets):
        self.read_secret = read_secret
        self.save_secrets = save_secrets
        self.last_test = None
        self.test_lock = threading.Lock()

    def mode(self):
        return self.read_secret("SCNET_OCR_KEY_MODE", "shared")

    def key(self):
        name = "SCNET_OCR_API_KEY" if self.mode() == "dedicated" else "SCNET_API_KEY"
        return self.read_secret(name, "")

    def revision(self):
        return hashlib.sha256((self.mode() + "\0" + self.key()).encode()).hexdigest()

    def payload(self):
        key = self.key()
        dedicated = self.read_secret("SCNET_OCR_API_KEY", "")
        last = self.last_test
        return {
            "provider": "SCNet · 超算互联网", "api_url": OCR_URL, "ocr_type": "GENERAL",
            "key_mode": self.mode(), "configured": bool(key),
            "key_masked": "••••••••" + key[-4:] if len(key) > 4 else "已设置" if key else "未配置",
            "has_dedicated_key": bool(dedicated),
            "managed_mode": "SCNET_OCR_KEY_MODE" in os.environ,
            "managed_key": "SCNET_OCR_API_KEY" in os.environ,
            "test": last[1] if last and last[0] == self.revision() else None,
        }

    def update(self, body):
        if body.key_mode not in {"shared", "dedicated"}:
            raise HTTPException(400, "请选择复用 SCNet 密钥或使用 OCR 专用密钥")
        if "SCNET_OCR_KEY_MODE" in os.environ and body.key_mode != self.mode():
            raise HTTPException(409, "密钥方式由系统环境变量管理，请在部署配置中修改并重启")
        values = {}
        if "SCNET_OCR_KEY_MODE" not in os.environ:
            values["SCNET_OCR_KEY_MODE"] = body.key_mode
        key = body.api_key.strip()
        if key and body.key_mode != "dedicated":
            raise HTTPException(400, "请先选择使用 OCR 专用密钥；共用密钥请在 AI API 管理中修改")
        if key:
            if "SCNET_OCR_API_KEY" in os.environ:
                raise HTTPException(409, "OCR 专用密钥由系统环境变量管理，页面无法修改")
            if any(char.isspace() for char in key):
                raise HTTPException(400, "密钥不能包含空格或换行")
            values["SCNET_OCR_API_KEY"] = key
        if body.key_mode == "dedicated" and not (key or self.read_secret("SCNET_OCR_API_KEY", "")):
            raise HTTPException(400, "请填写 OCR 专用密钥")
        self.save_secrets(values)
        self.last_test = None
        return self.payload()

    def test(self):
        if not self.test_lock.acquire(blocking=False):
            raise HTTPException(409, "OCR 测试正在进行，请等待本次结果")
        try:
            revision, key = self.revision(), self.key()
            from PIL import Image, ImageDraw
            image = Image.new("RGB", (360, 100), "white")
            ImageDraw.Draw(image).text((15, 30), "STELLA OCR TEST 123456", fill="black")
            image = image.resize((1080, 300))
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            started = time.monotonic()
            try:
                text = recognize(buffer.getvalue(), api_key=key, filename="stella_ocr_test.png", retry_count=1)
                ok = "123456" in text
                result = {"ok": ok, "message": "OCR 识别正常" if ok else "服务已响应，但未完整识别测试数字，请重试",
                          "text": text[:1000], "latency_ms": round((time.monotonic() - started) * 1000)}
            except OcrError as error:
                result = {"ok": False, "message": str(error), "text": "",
                          "latency_ms": round((time.monotonic() - started) * 1000)}
            if key:
                for field in ("message", "text"):
                    result[field] = result[field].replace(key, "[密钥已隐藏]")
            result["tested_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self.last_test = (revision, result)
            return result
        finally:
            self.test_lock.release()


def register_ocr_routes(app, settings, guard, frontend_dir):
    def authorize(request):
        guard(request)
        origin = request.headers.get("origin")
        if origin is not None and origin != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "请从 Stella 的 OCR 设置页面操作")

    @app.get("/ocr-settings")
    def ocr_settings_page():
        return FileResponse(frontend_dir / "ocr-settings.html", headers={"Cache-Control": "no-store"})

    @app.get("/api/ocr-settings")
    def get_ocr_settings(request: Request):
        authorize(request)
        return JSONResponse(settings.payload(), headers={"Cache-Control": "no-store"})

    @app.put("/api/ocr-settings")
    def save_ocr_settings(body: OcrUpdate, request: Request):
        authorize(request)
        return JSONResponse(settings.update(body), headers={"Cache-Control": "no-store"})

    @app.post("/api/ocr-settings/test")
    async def test_ocr_settings(request: Request):
        authorize(request)
        return JSONResponse(await run_in_threadpool(settings.test), headers={"Cache-Control": "no-store"})
