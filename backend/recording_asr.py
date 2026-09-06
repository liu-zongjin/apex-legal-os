"""会议/培训录音实时转写与 AI 规整纪要。

- VolcengineRTASR: 火山引擎「豆包流式语音识别大模型」Provider（首选）
  （wss://openspeech.bytedance.com/api/v3/sauc/bigmodel，新版控制台 X-Api-Key 鉴权）
- IflytekRTASR: 讯飞「实时语音转写（标准版）」Provider（备用）
- 音频转换工具：把上传的音频（mp3/m4a/wav/aac 等）转成 16k/16bit/单声道 WAV
- AI 语篇规整与会议纪要：复用 ai_client 的 LLM 配置
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import shutil
import struct
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

import websockets

IFLYTEK_RTASR_URL = "wss://rtasr.xfyun.cn/v1/ws"
VOLCENGINE_ASR_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
VOLCENGINE_DEFAULT_RESOURCE_ID = "volc.bigasr.sauc.duration"

FRAME_BYTES = 1280
FRAME_MS = 40.0
SAMPLE_RATE = 16000

# 火山引擎双向流式建议每包 200ms 音频（性能最优）
VOLCENGINE_PACKET_FRAMES = 5  # 5 × 40ms = 200ms = 6400 字节

# 上传文件转写加速倍率：ASR 计费按音频时长（volc.bigasr.sauc.duration），
# 发送速度不影响免费额度消耗；流式接口服务端稳定上限约为 2 倍速，超过易被限流。
UPLOAD_TRANSCRIBE_SPEEDUP = 2.0
# 单次 WebSocket 发送/连接超时，防止半开连接把转写任务永久卡死
SEND_TIMEOUT = 20.0
CONNECT_TIMEOUT = 30.0
# 转写任务整体看门狗宽限：正常耗时 = 音频时长 / 倍速，另加宽限时间
WATCHDOG_GRACE_SECONDS = 1800.0


# ─────────────────────────────────────────────
# 讯飞配置
# ─────────────────────────────────────────────

def _load_local_secrets():
    try:
        spec_path = Path(__file__).resolve().parent.parent / "local_ai_secrets.py"
        if not spec_path.exists():
            return None
        import importlib.util
        spec = importlib.util.spec_from_file_location("legal_kb_local_ai_secrets_recording", str(spec_path))
        if not spec or not spec.loader:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


def get_iflytek_config() -> Tuple[str, str, str]:
    """返回 (app_id, api_key, api_secret)。"""
    secrets = _load_local_secrets()
    app_id = os.environ.get("IFLYTEK_APP_ID", "") or getattr(secrets, "IFLYTEK_APP_ID", "")
    api_key = os.environ.get("IFLYTEK_API_KEY", "") or getattr(secrets, "IFLYTEK_API_KEY", "")
    api_secret = os.environ.get("IFLYTEK_API_SECRET", "") or getattr(secrets, "IFLYTEK_API_SECRET", "")
    return app_id, api_key, api_secret


def iflytek_configured() -> bool:
    app_id, api_key, _secret = get_iflytek_config()
    return bool(app_id and api_key)


# ─────────────────────────────────────────────
# 火山引擎（豆包流式语音识别大模型）配置
# ─────────────────────────────────────────────

def get_volcengine_config() -> Tuple[str, str, str, str]:
    """返回 (api_key, app_id, access_token, resource_id)。

    - 新版控制台：只需 api_key（X-Api-Key，语音技术控制台的 APP Key）
    - 旧版控制台：需要 app_id（X-Api-App-Key）+ access_token（X-Api-Access-Key）
    """
    secrets = _load_local_secrets()
    api_key = os.environ.get("VOLCENGINE_ASR_API_KEY", "") or getattr(secrets, "VOLCENGINE_ASR_API_KEY", "")
    app_id = os.environ.get("VOLCENGINE_ASR_APP_ID", "") or getattr(secrets, "VOLCENGINE_ASR_APP_ID", "")
    access_token = os.environ.get("VOLCENGINE_ASR_ACCESS_TOKEN", "") or getattr(secrets, "VOLCENGINE_ASR_ACCESS_TOKEN", "")
    resource_id = (
        os.environ.get("VOLCENGINE_ASR_RESOURCE_ID", "")
        or getattr(secrets, "VOLCENGINE_ASR_RESOURCE_ID", "")
        or VOLCENGINE_DEFAULT_RESOURCE_ID
    )
    return api_key, app_id, access_token, resource_id


def volcengine_configured() -> bool:
    api_key, app_id, access_token, _resource = get_volcengine_config()
    return bool(api_key or (app_id and access_token))


def asr_configured() -> bool:
    """任一 ASR 服务已配置即可用。"""
    return volcengine_configured() or iflytek_configured()


def asr_backend_name() -> str:
    """当前生效的转写服务名称。"""
    if volcengine_configured():
        return "火山引擎"
    if iflytek_configured():
        return "讯飞"
    return "未配置"


def create_asr_session(on_segment: Optional[Callable[[Dict[str, Any]], None]] = None,
                       on_error: Optional[Callable[[str], None]] = None) -> "RTASRSession":
    """按配置自动选择火山引擎（优先）或讯飞。"""
    return RTASRSession(on_segment=on_segment, on_error=on_error)


def _build_rtasr_url(app_id: str, api_key: str) -> str:
    """生成讯飞实时语音转写（标准版）WebSocket 鉴权地址。

    该产品使用 HmacSHA1(MD5(appid + ts), api_key)，不同于讯飞流式听写
    接口的 API Secret / HMAC-SHA256 鉴权方式。
    """
    ts = str(int(time.time()))
    base_md5 = hashlib.md5((app_id + ts).encode("utf-8")).hexdigest()
    signa_raw = hmac.new(api_key.encode("utf-8"), base_md5.encode("utf-8"), hashlib.sha1).digest()
    signa = base64.b64encode(signa_raw).decode("utf-8")
    return f"{IFLYTEK_RTASR_URL}?appid={quote(app_id, safe='')}&ts={ts}&signa={quote(signa, safe='')}"


# ─────────────────────────────────────────────
# 讯飞实时语音转写 Provider
# ─────────────────────────────────────────────

class IflytekRTASR:
    """讯飞实时语音转写客户端。

    用法：
        provider = IflytekRTASR(on_segment=callback)
        await provider.start()           # 建立连接并发送业务参数
        await provider.send_pcm(frame)   # 1280 字节 PCM 帧
        await provider.finish()          # 发送空帧结束并等待最终结果

    on_segment(segment) 中的 segment 为 {"start": 秒, "end": 秒, "text": 文本}。
    """

    def __init__(self, on_segment: Optional[Callable[[Dict[str, Any]], None]] = None,
                 on_error: Optional[Callable[[str], None]] = None):
        self._app_id, self._api_key, self._api_secret = get_iflytek_config()
        if not self._app_id or not self._api_key:
            raise RuntimeError("未配置讯飞实时转写凭据（IFLYTEK_APP_ID / IFLYTEK_API_KEY）")
        self._ws = None
        self._on_segment = on_segment
        self._on_error = on_error
        self._stream_offset_ms = 0.0   # 当前会话开始时已累计的音频毫秒数
        self._closed = False
        self.fatal_error: Optional[str] = None
        self._read_task = None

    async def start(self) -> None:
        url = _build_rtasr_url(self._app_id, self._api_key)
        self._ws = await websockets.connect(url, ping_interval=20, ping_timeout=20, max_size=2 ** 24)
        business = {
            "language": "zh_cn",
            "domain": "iat",
            "accent": "mandarin",
            "dwa": "wpgs",
            "ptt": 1,
            "vad_eos": 10000,
            "nbest": 1,
        }
        first_frame = json.dumps({"common": {"app_id": self._app_id}, "business": business})
        await asyncio.wait_for(self._ws.send(first_frame), timeout=SEND_TIMEOUT)

    def _parse_result(self, raw: str) -> List[Dict[str, Any]]:
        """解析讯飞结果帧，返回完成的句子列表。"""
        try:
            payload = json.loads(raw)
        except Exception:
            return []
        if payload.get("action") == "error":
            code = payload.get("code", "")
            message = payload.get("desc", "") or payload.get("message", "")
            if str(code) == "10105":
                self.fatal_error = "讯飞鉴权失败（10105）：请确认 AppID 与 API Key 来自同一应用，并已开通“实时语音转写（标准版）”"
            else:
                self.fatal_error = f"讯飞转写错误 {code}：{message}"
            if self._on_error:
                self._on_error(self.fatal_error)
            return []
        if payload.get("action") != "result":
            return []
        data = payload.get("data")
        if not data:
            return []
        try:
            data_obj = json.loads(data)
        except Exception:
            return []
        st = ((data_obj.get("cn") or {}).get("st")) or {}
        if str(st.get("type")) != "1":
            return []
        words: List[str] = []
        for rt in st.get("rt") or []:
            for ws in rt.get("ws") or []:
                for cw in ws.get("cw") or []:
                    words.append(cw.get("w", ""))
        text = "".join(words).strip()
        if not text:
            return []
        try:
            start_ms = float(st.get("bg", 0))
            end_ms = float(st.get("ed", 0))
        except (TypeError, ValueError):
            return []
        return [{
            "start": round((self._stream_offset_ms + start_ms) / 1000.0, 3),
            "end": round((self._stream_offset_ms + end_ms) / 1000.0, 3),
            "text": text,
        }]

    async def _read_loop(self) -> None:
        """持续读取服务端结果直到连接关闭。"""
        try:
            async for message in self._ws:
                if isinstance(message, (bytes, bytearray)):
                    continue
                for segment in self._parse_result(message):
                    if self._on_segment:
                        self._on_segment(segment)
        except Exception as e:
            if not self._closed and self._on_error:
                self._on_error(f"讯飞连接中断：{e}")

    async def send_pcm(self, frame: bytes) -> None:
        if not self._ws:
            raise RuntimeError("讯飞连接未建立")
        if len(frame) != FRAME_BYTES:
            raise ValueError(f"PCM 帧长度必须为 {FRAME_BYTES} 字节，实际 {len(frame)}")
        await asyncio.wait_for(self._ws.send(frame), timeout=SEND_TIMEOUT)

    async def finish(self) -> None:
        """发送空帧结束音频，等待最终结果后关闭连接。"""
        if not self._ws:
            return
        self._closed = True
        try:
            await asyncio.wait_for(self._ws.send(b"\x00" * FRAME_BYTES), timeout=SEND_TIMEOUT)
            if self._read_task:
                try:
                    await asyncio.wait_for(asyncio.shield(self._read_task), timeout=12)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass
        except Exception:
            pass
        finally:
            await self.close()

    async def close(self) -> None:
        self._closed = True
        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
        self._read_task = None
        if self._ws:
            try:
                await asyncio.wait_for(self._ws.close(), timeout=10)
            except Exception:
                pass
            self._ws = None


# ─────────────────────────────────────────────
# 火山引擎豆包流式语音识别大模型 Provider
# ─────────────────────────────────────────────

class VolcengineRTASR:
    """火山引擎流式语音识别（双向流式，bigmodel 模型）。

    二进制协议：4 字节 header + 4 字节 payload size（大端）+ payload。
    header 布局：[0x11, (type<<4)|flags, (serialization<<4)|compression, 0x00]

    - full client request: type=1, serialization=JSON(1)
    - audio only request:  type=2, serialization=无(0)，每包 200ms
    - 最后一包（负包）:     flags=0b0010
    - 服务端响应:           type=9，flags 含 0b0001 时带 4 字节 sequence
    """

    MSG_FULL_CLIENT = 0b0001
    MSG_AUDIO_ONLY = 0b0010
    MSG_SERVER_RESPONSE = 0b1001
    MSG_SERVER_ERROR = 0b1111
    FLAG_LAST = 0b0010
    FLAG_HAS_SEQ = 0b0001
    SERIALIZATION_JSON = 0b0001
    COMPRESSION_NONE = 0b0000

    def __init__(self, on_segment: Optional[Callable[[Dict[str, Any]], None]] = None,
                 on_error: Optional[Callable[[str], None]] = None):
        self._api_key, self._app_id, self._access_token, self._resource_id = get_volcengine_config()
        if not (self._api_key or (self._app_id and self._access_token)):
            raise RuntimeError("未配置火山引擎流式语音识别凭据（VOLCENGINE_ASR_API_KEY）")
        self._ws = None
        self._on_segment = on_segment
        self._on_error = on_error
        self._stream_offset_ms = 0.0
        self._closed = False
        self.fatal_error: Optional[str] = None
        self._buffer = b""
        self._read_task = None
        self._last_emitted_by_start: Dict[float, Tuple[float, str, bool]] = {}

    def _build_headers(self) -> Dict[str, str]:
        headers = {
            "X-Api-Resource-Id": self._resource_id,
            "X-Api-Request-Id": str(uuid.uuid4()),
            "X-Api-Sequence": "-1",
            "X-Api-Connect-Id": str(uuid.uuid4()),
        }
        if self._api_key:
            headers["X-Api-Key"] = self._api_key
        else:
            headers["X-Api-App-Key"] = self._app_id
            headers["X-Api-Access-Key"] = self._access_token
        return headers

    async def start(self) -> None:
        self._ws = await websockets.connect(
            VOLCENGINE_ASR_URL,
            extra_headers=self._build_headers(),
            ping_interval=20,
            ping_timeout=20,
            max_size=2 ** 24,
            open_timeout=15,
        )
        request = {
            "user": {"uid": "legal-kb-recording"},
            "audio": {"format": "pcm", "rate": SAMPLE_RATE, "bits": 16, "channel": 1, "language": "zh-CN"},
            "request": {
                "model_name": "bigmodel",
                "enable_punc": True,
                "enable_itn": True,
                "show_utterances": True,
            },
        }
        await self._send_frame(self.MSG_FULL_CLIENT, json.dumps(request).encode("utf-8"),
                               flags=0, serialization=self.SERIALIZATION_JSON)
        self._read_task = asyncio.ensure_future(self._read_loop())

    async def _send_frame(self, msg_type: int, payload: bytes, flags: int = 0,
                          serialization: int = 0, compression: int = COMPRESSION_NONE) -> None:
        header = bytes([
            0x11,
            (msg_type << 4) | flags,
            (serialization << 4) | compression,
            0x00,
        ])
        await asyncio.wait_for(self._ws.send(header + struct.pack(">I", len(payload)) + payload),
                               timeout=SEND_TIMEOUT)

    async def send_pcm(self, frame: bytes) -> None:
        if not self._ws:
            raise RuntimeError("火山引擎连接未建立")
        if len(frame) != FRAME_BYTES:
            raise ValueError(f"PCM 帧长度必须为 {FRAME_BYTES} 字节，实际 {len(frame)}")
        self._buffer += frame
        packet_bytes = FRAME_BYTES * VOLCENGINE_PACKET_FRAMES
        while len(self._buffer) >= packet_bytes:
            packet, self._buffer = self._buffer[:packet_bytes], self._buffer[packet_bytes:]
            await self._send_frame(self.MSG_AUDIO_ONLY, packet)

    def _parse_response(self, data: bytes) -> List[Dict[str, Any]]:
        """解析服务端二进制帧，返回完成的句子列表。"""
        if len(data) < 4:
            return []
        msg_type = (data[1] >> 4) & 0x0F
        flags = data[1] & 0x0F
        if msg_type == self.MSG_SERVER_ERROR:
            try:
                code = struct.unpack(">I", data[4:8])[0]
                size = struct.unpack(">I", data[8:12])[0]
                message = data[12:12 + size].decode("utf-8", "ignore")
            except Exception:
                code, message = 0, "未知协议错误"
            self.fatal_error = f"火山引擎转写错误 {code}：{message}"
            if self._on_error:
                self._on_error(self.fatal_error)
            return []
        if msg_type != self.MSG_SERVER_RESPONSE:
            return []
        offset = 4
        if flags & self.FLAG_HAS_SEQ:
            offset += 4  # sequence number
        if len(data) < offset + 4:
            return []
        try:
            size = struct.unpack(">I", data[offset:offset + 4])[0]
            payload = data[offset + 4:offset + 4 + size]
        except Exception:
            return []
        if not payload:
            return []
        try:
            body = json.loads(payload.decode("utf-8"))
        except Exception:
            return []
        result = body.get("result") or {}
        segments: List[Dict[str, Any]] = []
        for utterance in result.get("utterances") or []:
            text = str(utterance.get("text") or "").strip()
            if not text:
                continue
            try:
                start_ms = float(utterance.get("start_time", 0))
                end_ms = float(utterance.get("end_time", 0))
            except (TypeError, ValueError):
                continue
            if end_ms <= start_ms:
                continue
            start = round((self._stream_offset_ms + start_ms) / 1000.0, 3)
            end = round((self._stream_offset_ms + end_ms) / 1000.0, 3)
            definite = bool(utterance.get("definite"))
            # 火山会在每次响应中重复携带尚未变化的 utterance。只转发内容、
            # 结束时间或定稿状态发生变化的版本，避免页面每 200ms 重绘同一句。
            signature = (end, text, definite)
            if self._last_emitted_by_start.get(start) == signature:
                continue
            self._last_emitted_by_start[start] = signature
            segments.append({
                "start": start,
                "end": end,
                "text": text,
                "definite": definite,
            })
        return segments

    async def _read_loop(self) -> None:
        try:
            async for message in self._ws:
                if not isinstance(message, (bytes, bytearray)):
                    continue
                for segment in self._parse_response(bytes(message)):
                    if self._on_segment:
                        self._on_segment(segment)
        except Exception as e:
            if not self._closed and self._on_error and not self.fatal_error:
                self._on_error(f"火山引擎连接中断：{e}")

    async def finish(self) -> None:
        """发送负包结束音频，等待最终结果后关闭连接。"""
        if not self._ws:
            return
        self._closed = True
        try:
            if self._buffer:
                await self._send_frame(self.MSG_AUDIO_ONLY, self._buffer)
                self._buffer = b""
            # 最后一包（负包）：flags=0b0010，空 payload
            await self._send_frame(self.MSG_AUDIO_ONLY, b"", flags=self.FLAG_LAST)
            if self._read_task:
                try:
                    await asyncio.wait_for(asyncio.shield(self._read_task), timeout=12)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass
        except Exception:
            pass
        finally:
            await self.close()

    async def close(self) -> None:
        self._closed = True
        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
        self._read_task = None
        if self._ws:
            try:
                await asyncio.wait_for(self._ws.close(), timeout=10)
            except Exception:
                pass
            self._ws = None


class RTASRSession:
    """带断线自动重连的流式转写会话。

    按配置自动选择火山引擎（优先）或讯飞。在长会议中若连接因网络/静音
    断开，会自动重建连接，句子的时间戳基于本地累计帧数计算，跨会话保持连续。
    """

    def __init__(self, on_segment: Optional[Callable[[Dict[str, Any]], None]] = None,
                 on_error: Optional[Callable[[str], None]] = None):
        self._on_segment = on_segment
        self._on_error = on_error
        self._provider = None
        self._frames_sent = 0
        self._closed = False
        self._reconnects = 0
        self._segments_by_start: Dict[float, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self.fatal_error: Optional[str] = None

    @property
    def elapsed_ms(self) -> float:
        return self._frames_sent * FRAME_MS

    @property
    def segments(self) -> List[Dict[str, Any]]:
        return sorted(self._segments_by_start.values(), key=lambda s: float(s.get("start", 0)))

    def _handle_segment(self, segment: Dict[str, Any]) -> None:
        # 同一起始时间的结果后到覆盖先到（火山引擎分句会多次回传更新）
        self._segments_by_start[round(float(segment.get("start", 0)), 3)] = segment
        if self._on_segment:
            self._on_segment(segment)

    async def _connect(self) -> None:
        if volcengine_configured():
            provider = VolcengineRTASR(on_segment=self._handle_segment, on_error=self._on_error)
        elif iflytek_configured():
            provider = IflytekRTASR(on_segment=self._handle_segment, on_error=self._on_error)
        else:
            raise RuntimeError("未配置语音识别服务（火山引擎或讯飞）")
        # 先挂到 self._provider，start 失败时能通过 close() 释放半开的连接
        self._provider = provider
        provider._stream_offset_ms = self._frames_sent * FRAME_MS
        try:
            await asyncio.wait_for(provider.start(), timeout=CONNECT_TIMEOUT)
        except Exception:
            await provider.close()
            self._provider = None
            raise
        # 后台任务消费服务端消息（火山引擎在 start 内已启动）
        if getattr(provider, "_read_task", None) is None:
            provider._read_task = asyncio.ensure_future(provider._read_loop())

    async def _reconnect(self) -> None:
        self._reconnects += 1
        if self._on_error:
            self._on_error(f"转写连接中断，正在自动重连（第 {self._reconnects} 次）…")
        await asyncio.sleep(1.0)
        await self._connect()

    async def feed(self, pcm_frame: bytes) -> None:
        async with self._lock:
            if self._closed:
                return
            if len(pcm_frame) != FRAME_BYTES:
                raise ValueError(f"PCM 帧长度必须为 {FRAME_BYTES} 字节")
            if self._provider is None:
                await self._connect()
            if getattr(self._provider, "fatal_error", None):
                self.fatal_error = self._provider.fatal_error
                raise RuntimeError(self.fatal_error)
            try:
                await self._provider.send_pcm(pcm_frame)
                self._frames_sent += 1
            except Exception:
                # 发送失败（含 SEND_TIMEOUT 超时）：关闭半开连接后重建并重发
                try:
                    await asyncio.wait_for(self._provider.close(), timeout=10)
                except Exception:
                    pass
                self._provider = None
                await self._reconnect()
                await self._provider.send_pcm(pcm_frame)
                self._frames_sent += 1

    async def finish(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._provider is not None:
                try:
                    await asyncio.wait_for(self._provider.finish(), timeout=60)
                except Exception:
                    pass


# ─────────────────────────────────────────────
# 音频文件转换（16k / 16bit / 单声道 WAV）
# ─────────────────────────────────────────────

def _read_wav_info(path: Path) -> Tuple[int, int, int, int, int]:
    """解析 WAV 头，兼容标准 PCM 与 WAVE_FORMAT_EXTENSIBLE（afconvert 输出）。

    返回 (sample_rate, channels, sampwidth, data_offset, data_size)。
    """
    import struct
    with open(path, "rb") as f:
        head = f.read(12)
        if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            raise ValueError("不是有效的 WAV 文件")
        fmt = None
        data_offset = None
        data_size = 0
        while True:
            chunk_head = f.read(8)
            if len(chunk_head) < 8:
                break
            chunk_id = chunk_head[:4]
            chunk_size = struct.unpack("<I", chunk_head[4:8])[0]
            if chunk_id == b"fmt ":
                fmt_bytes = f.read(chunk_size)
                audio_format, channels, rate = struct.unpack("<HHI", fmt_bytes[:8])
                bits = struct.unpack("<H", fmt_bytes[14:16])[0]
                if audio_format == 0xFFFE:  # WAVE_FORMAT_EXTENSIBLE
                    if chunk_size >= 40:
                        audio_format = struct.unpack("<H", fmt_bytes[24:26])[0]
                if audio_format != 1:
                    raise ValueError(f"不支持的 WAV 编码格式：{audio_format}")
                fmt = (rate, channels, bits // 8)
            elif chunk_id == b"data":
                data_offset = f.tell()
                data_size = chunk_size
                f.seek(chunk_size, 1)
            else:
                f.seek(chunk_size, 1)
        if fmt is None or data_offset is None:
            raise ValueError("WAV 缺少 fmt 或 data 块")
    rate, channels, sampwidth = fmt
    return rate, channels, sampwidth, data_offset, data_size


def _is_plain_wav_16k(path: Path) -> bool:
    try:
        rate, channels, sampwidth, _offset, _size = _read_wav_info(path)
        return rate == SAMPLE_RATE and channels == 1 and sampwidth == 2
    except Exception:
        return False


def convert_audio_to_pcm16k(src: Path, dst: Path) -> None:
    """把任意常见音频转成 16k 单声道 16bit WAV。优先 ffmpeg，其次 macOS afconvert。"""
    if dst.exists() and _is_plain_wav_16k(dst):
        return
    dst.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg = shutil.which("ffmpeg")
    afconvert = shutil.which("afconvert") if os.sys.platform == "darwin" else None

    if ffmpeg:
        result = subprocess.run(
            [ffmpeg, "-y", "-i", str(src), "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "wav", str(dst)],
            capture_output=True, text=True, timeout=1800,
        )
        if result.returncode == 0 and _is_plain_wav_16k(dst):
            return
    if afconvert:
        result = subprocess.run(
            [afconvert, "-f", "WAVE", "-d", f"LEI16@{SAMPLE_RATE}", "-c", "1", str(src), str(dst)],
            capture_output=True, text=True, timeout=1800,
        )
        if result.returncode == 0 and _is_plain_wav_16k(dst):
            return
    if _is_plain_wav_16k(src):
        shutil.copy2(str(src), str(dst))
        return
    raise RuntimeError("无法转换音频文件：需要 ffmpeg 或 macOS afconvert（当前文件格式不受支持）")


def iter_wav_frames(wav_path: Path, frame_bytes: int = FRAME_BYTES):
    """按帧读取 WAV 文件的 PCM 数据，末尾不足一帧时补零（补零帧同时充当结束信号）。"""
    rate, channels, sampwidth, data_offset, data_size = _read_wav_info(wav_path)
    if rate != SAMPLE_RATE or channels != 1 or sampwidth != 2:
        raise RuntimeError("WAV 必须为 16k 单声道 16bit")
    with open(wav_path, "rb") as f:
        f.seek(data_offset)
        remaining = data_size
        while remaining > 0:
            data = f.read(min(frame_bytes, remaining))
            remaining -= len(data)
            if len(data) < frame_bytes:
                data = data + b"\x00" * (frame_bytes - len(data))
                yield data
                return
            yield data


def wav_duration_seconds(wav_path: Path) -> float:
    try:
        rate, channels, sampwidth, _offset, data_size = _read_wav_info(wav_path)
        return round(data_size / (rate * channels * sampwidth), 3)
    except Exception:
        return 0.0


# ─────────────────────────────────────────────
# AI 语篇规整 & 会议纪要
# ─────────────────────────────────────────────

_POLISH_PROMPT = (
    "你是法律会议/培训记录整理助手。请对下面这段语音实时转写的文字进行语篇规整：\n"
    "1. 去除口语中的语气词、重复、自我修正（如“就是说”“然后然后”），使表达流畅；\n"
    "2. 补齐标点，按语义合理分段，每段不超过 6 行；\n"
    "3. 严格保留法律术语、数字、日期、金额、人名、机构名、文件名、法条号的原样，不得改动或臆测；\n"
    "4. 不要添加原文没有的内容，也不要删减实质性信息；\n"
    "5. 只输出规整后的正文，不要任何解释或标题。\n\n"
    "原文如下：\n{text}"
)

_MINUTES_PROMPT = (
    "你是资深法律秘书。请根据以下会议/培训的语音转写内容，生成一份专业、简洁的会议纪要（Markdown 格式），包含：\n"
    "## 一、会议主题\n"
    "## 二、主要议题与要点（分条列出，每条约 1-2 句）\n"
    "## 三、结论与决定\n"
    "## 四、待办事项（每条含事项与负责安排；原文未提及的部分写“原文未提及”）\n"
    "要求：忠于原文，不编造；法律术语、人名、日期、数字必须准确；全文不超过 800 字。\n\n"
    "转写内容如下：\n{text}"
)


def _chunk_text(text: str, chunk_size: int = 3800, overlap: int = 200) -> List[str]:
    if len(text) <= chunk_size:
        return [text]
    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            # 尽量在句号处断开
            cut = text.rfind("。", start + chunk_size // 2, end)
            if cut > start:
                end = cut + 1
        chunks.append(text[start:end])
        start = max(end - overlap, start + 1)
    return chunks


async def polish_transcript(text: str, call_ai: Callable, model: str,
                            progress: Optional[Callable[[str], None]] = None) -> str:
    """语篇规整。call_ai(messages, max_tokens) -> str（AI 输出文本）。"""
    chunks = _chunk_text(text)
    polished_parts: List[str] = []
    for index, chunk in enumerate(chunks):
        if progress:
            progress(f"正在规整第 {index + 1}/{len(chunks)} 段…")
        messages = [{"role": "user", "content": _POLISH_PROMPT.format(text=chunk)}]
        try:
            result = await call_ai(model, messages, max_tokens=3000)
        except Exception as e:
            # 规整失败时回退原文，不阻断流程
            polished_parts.append(chunk)
            if progress:
                progress(f"第 {index + 1} 段规整失败，保留原文：{e}")
            continue
        polished_parts.append((result or "").strip())
    return "\n\n".join(p for p in polished_parts if p).strip()


async def generate_meeting_minutes(text: str, call_ai: Callable, model: str) -> str:
    """生成会议纪要。"""
    excerpt = text[:16000]
    messages = [{"role": "user", "content": _MINUTES_PROMPT.format(text=excerpt)}]
    result = await call_ai(model, messages, max_tokens=2600)
    return (result or "").strip()


async def ai_call_helper(model: str, messages: List[Dict[str, str]], max_tokens: int = 3000) -> str:
    """把 ai_client.call_ai_with_fallback 适配成 call_ai 签名。"""
    from .ai_client import call_ai_with_fallback
    response, _actual = await call_ai_with_fallback(model, messages, max_tokens=max_tokens)
    try:
        return response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"AI 返回格式异常：{json.dumps(response, ensure_ascii=False)[:300]}")
