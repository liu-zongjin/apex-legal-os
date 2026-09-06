"""会议/培训录音：实时转写、上传转写、回放、AI 规整纪要、知识库入库。"""

from __future__ import annotations

import asyncio
import datetime
import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import BackgroundTasks, File, HTTPException, Request, UploadFile, WebSocket
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from . import recording_asr as rasr
from .ai_config import DEFAULT_AI_MODEL
from .security import check_basic_auth_header, check_session_cookie, is_loopback_client

RECORDING_DIR_NAME = "recordings"
_RECORDING_LOCK = asyncio.Lock()


def _now() -> str:
    return datetime.datetime.now().isoformat()


def ensure_recording_schema(get_db: Callable[[], Any]) -> None:
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS recordings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                audio_path TEXT NOT NULL DEFAULT '',
                duration REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'draft',
                processed_ms INTEGER NOT NULL DEFAULT 0,
                transcript_json TEXT NOT NULL DEFAULT '[]',
                polished_text TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                article_id INTEGER,
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_recordings_created ON recordings(created_at)")
        conn.commit()


def _update_recording(get_db, recording_id: int, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = _now()
    columns = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [recording_id]
    with get_db() as conn:
        conn.execute(f"UPDATE recordings SET {columns} WHERE id=?", values)
        conn.commit()


def _get_recording(get_db, recording_id: int) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM recordings WHERE id=?", (recording_id,)).fetchone()
    return dict(row) if row else None


def _recording_to_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    try:
        segments = json.loads(row.get("transcript_json") or "[]")
    except Exception:
        segments = []
    return {
        "id": row["id"],
        "title": row["title"],
        "audio_path": row.get("audio_path", ""),
        "duration": row.get("duration", 0),
        "status": row.get("status", "draft"),
        "processed_ms": row.get("processed_ms", 0),
        "segments": segments,
        "polished_text": row.get("polished_text", ""),
        "summary": row.get("summary", ""),
        "article_id": row.get("article_id"),
        "error": row.get("error", ""),
        "created_at": row.get("created_at", ""),
        "updated_at": row.get("updated_at", ""),
    }


def _segments_to_text(segments: List[Dict[str, Any]]) -> str:
    return "\n".join(seg.get("text", "") for seg in segments if seg.get("text"))


# ─────────────────────────────────────────────
# 后台任务：上传文件转写（2 倍速送帧；ASR 按音频时长计费，速度不影响免费额度）
# ─────────────────────────────────────────────

async def _transcribe_recording_file(get_db, recording_id: int, wav_path: Path) -> None:
    try:
        duration = rasr.wav_duration_seconds(wav_path)
        await run_in_threadpool(_update_recording, get_db, recording_id, status="transcribing",
                                processed_ms=0, duration=duration, error="")
        sentences: List[Dict[str, Any]] = []

        def on_segment(segment: Dict[str, Any]) -> None:
            sentences.append(segment)

        session = rasr.RTASRSession(on_segment=on_segment,
                                    on_error=lambda msg: print(f"[recording {recording_id}] {msg}"))

        async def update_progress() -> None:
            await run_in_threadpool(_update_recording, get_db, recording_id,
                                    processed_ms=int(session.elapsed_ms))

        frame_index = 0
        start = time.monotonic()
        last_cancel_check = start
        # 整体看门狗：正常耗时 = 音频时长 / 倍速；超过宽限时间仍未完成则中止，
        # 让状态落为 failed（可重新转写），而不是永远停在「转写中」。
        expected = (duration if duration > 0 else 8 * 3600) / rasr.UPLOAD_TRANSCRIBE_SPEEDUP
        deadline = start + expected + rasr.WATCHDOG_GRACE_SECONDS
        for frame in rasr.iter_wav_frames(wav_path):
            now = time.monotonic()
            if now > deadline:
                raise RuntimeError("转写看门狗超时：任务运行时间已超过音频时长与宽限时间之和，已中止")
            # 每 10 秒检查一次任务是否被取消（录音被删除）
            if frame_index == 0 or now - last_cancel_check >= 10.0:
                last_cancel_check = now
                rec = await run_in_threadpool(_get_recording, get_db, recording_id)
                if rec is None or rec.get("status") == "cancelled":
                    return
            await session.feed(frame)
            frame_index += 1
            # 按 UPLOAD_TRANSCRIBE_SPEEDUP 倍速节奏发送（计费按音频时长，不受发送速度影响）
            target = start + frame_index * (rasr.FRAME_MS / 1000.0) / rasr.UPLOAD_TRANSCRIBE_SPEEDUP
            delay = target - time.monotonic()
            if delay > 0:
                await asyncio.sleep(min(delay, 1.0))
            if frame_index % 125 == 0:
                await update_progress()
        await session.finish()
        # finish 后可能仍有结果回调，稍等片刻再落库
        await asyncio.sleep(0.6)
        await update_progress()
        await run_in_threadpool(_update_recording, get_db, recording_id,
                                transcript_json=json.dumps(sentences, ensure_ascii=False))
        await _run_ai_processing(get_db, recording_id)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"[recording {recording_id}] 转写失败：{e}")
        await run_in_threadpool(_update_recording, get_db, recording_id, status="failed", error=str(e)[:500])


async def _run_ai_processing(get_db, recording_id: int) -> None:
    """对已转写的文本做语篇规整与纪要总结。"""
    rec = _get_recording(get_db, recording_id)
    if rec is None:
        return
    raw_text = _segments_to_text(json.loads(rec.get("transcript_json") or "[]"))
    if not raw_text.strip():
        _update_recording(get_db, recording_id, status="completed")
        return
    _update_recording(get_db, recording_id, status="ai_processing", error="")

    def progress_note(msg: str) -> None:
        _update_recording(get_db, recording_id, error=msg)

    polished = raw_text
    try:
        polished = await rasr.polish_transcript(raw_text, rasr.ai_call_helper, DEFAULT_AI_MODEL,
                                                progress=progress_note)
    except Exception as e:
        print(f"[recording {recording_id}] 规整失败：{e}")
    _update_recording(get_db, recording_id, polished_text=polished)

    summary = ""
    try:
        summary = await rasr.generate_meeting_minutes(raw_text, rasr.ai_call_helper, DEFAULT_AI_MODEL)
    except Exception as e:
        print(f"[recording {recording_id}] 纪要失败：{e}")
    _update_recording(get_db, recording_id, summary=summary, status="completed", error="")


def _spawn_ai_processing(get_db, recording_id: int) -> None:
    async def _runner() -> None:
        async with _RECORDING_LOCK:
            try:
                await _run_ai_processing(get_db, recording_id)
            except Exception as e:
                print(f"[recording {recording_id}] AI 处理异常：{e}")
                _update_recording(get_db, recording_id, status="completed", error=str(e)[:300])

    asyncio.create_task(_runner())


# ─────────────────────────────────────────────
# 路由注册
# ─────────────────────────────────────────────

def register_recording_routes(app: Any, get_db: Callable[[], Any],
                              save_article_fn: Callable, upload_dir: Path) -> None:
    ensure_recording_schema(get_db)
    recordings_dir = upload_dir / RECORDING_DIR_NAME
    recordings_dir.mkdir(parents=True, exist_ok=True)
    cancelled_recording_ids: set[int] = set()

    @app.get("/api/recordings/asr-config")
    async def get_asr_config_status():
        volc_key, volc_appid, volc_token, resource_id = rasr.get_volcengine_config()
        ifly_app_id, _ifly_key, ifly_secret = rasr.get_iflytek_config()
        def mask(value: str) -> str:
            if not value:
                return ""
            return (value[:4] + "••••••" + value[-4:]) if len(value) > 8 else "••••••"
        return {
            "ok": True,
            "configured": rasr.asr_configured(),
            "backend": rasr.asr_backend_name(),
            "volcengine": {
                "configured": rasr.volcengine_configured(),
                "api_key_masked": mask(volc_key),
                "app_id_masked": mask(volc_appid),
                "access_token_masked": mask(volc_token),
                "resource_id": resource_id,
            },
            "iflytek": {
                "configured": rasr.iflytek_configured(),
                "app_id_masked": mask(ifly_app_id),
                "api_secret_masked": mask(ifly_secret),
            },
        }

    @app.put("/api/recordings/asr-config")
    async def update_asr_config(request: Request):
        from .main import _write_local_ai_settings
        try:
            body = await request.json()
        except Exception:
            body = {}
        values: Dict[str, str] = {}
        for key in ("VOLCENGINE_ASR_API_KEY", "VOLCENGINE_ASR_APP_ID",
                    "VOLCENGINE_ASR_ACCESS_TOKEN", "VOLCENGINE_ASR_RESOURCE_ID",
                    "IFLYTEK_APP_ID", "IFLYTEK_API_KEY", "IFLYTEK_API_SECRET"):
            value = str(body.get(key) or "").strip()
            if value:
                values[key] = value
        if values:
            _write_local_ai_settings(values)
        return {"ok": True, "configured": rasr.asr_configured(), "backend": rasr.asr_backend_name()}

    @app.post("/api/recordings/live/start")
    async def start_live_recording(request: Request):
        body = await request.json()
        title = str(body.get("title") or "").strip() or "未命名会议录音"
        if not rasr.asr_configured():
            raise HTTPException(status_code=400, detail="未配置语音识别服务：请在「会议录音」页面填写火山引擎（或讯飞）凭据")
        with get_db() as conn:
            cur = conn.execute(
                "INSERT INTO recordings (title, audio_path, status, created_at, updated_at) VALUES (?, '', 'recording', ?, ?)",
                (title, _now(), _now()),
            )
            conn.commit()
            recording_id = cur.lastrowid
        return {"ok": True, "id": recording_id}

    @app.websocket("/ws/recordings/live/{recording_id}")
    async def live_recording_ws(websocket: WebSocket, recording_id: int):
        token = websocket.cookies.get("legal_kb_session")
        client_host = websocket.client.host if websocket.client else ""
        authorized = (
            is_loopback_client(client_host)
            or check_session_cookie(token)
            or check_basic_auth_header(websocket.headers.get("authorization"))
        )
        if not authorized:
            await websocket.close(code=4401)
            return
        rec = _get_recording(get_db, recording_id)
        if rec is None:
            await websocket.accept()
            await websocket.send_json({"type": "error", "message": "录音不存在"})
            await websocket.close(code=4404)
            return
        await websocket.accept()

        raw_path = recordings_dir / f"{recording_id}.raw"
        wav_path = recordings_dir / f"{recording_id}.wav"
        audio_file = open(raw_path, "wb")
        segments: List[Dict[str, Any]] = []
        segment_queue: asyncio.Queue = asyncio.Queue()
        session: Optional[rasr.RTASRSession] = None
        provider_error = ""
        finished = False

        def on_segment(segment: Dict[str, Any]) -> None:
            # 火山会持续回传同一句的临时修订稿。临时稿只用于页面实时预览，
            # 正式录音记录仅保存 definite=true 的最终分句。
            if segment.get("definite"):
                segments.append(segment)
            try:
                segment_queue.put_nowait(segment)
            except Exception:
                pass

        def on_error(msg: str) -> None:
            nonlocal provider_error
            provider_error = msg

        session = rasr.RTASRSession(on_segment=on_segment, on_error=on_error)
        buffer = b""
        asr_failed = False

        async def relay_segments_to_page() -> None:
            """将识别线程产生的片段实时推送给会议录音页面。"""
            while True:
                segment = await segment_queue.get()
                try:
                    if segment is None:
                        return
                    await websocket.send_json({
                        "type": "segment",
                        "start": segment.get("start", 0),
                        "end": segment.get("end", 0),
                        "text": segment.get("text", ""),
                        "definite": bool(segment.get("definite")),
                    })
                except Exception:
                    return
                finally:
                    segment_queue.task_done()

        segment_relay_task = asyncio.create_task(relay_segments_to_page())

        async def relay_pending() -> None:
            nonlocal buffer
            while len(buffer) >= rasr.FRAME_BYTES:
                frame, buffer = buffer[:rasr.FRAME_BYTES], buffer[rasr.FRAME_BYTES:]
                await session.feed(frame)

        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if message.get("text") == "end":
                    finished = True
                    break
                data = message.get("bytes")
                if not data:
                    continue
                audio_file.write(data)
                buffer += data
                if asr_failed:
                    continue
                try:
                    await relay_pending()
                except RuntimeError as e:
                    asr_failed = True
                    await websocket.send_json({"type": "error", "message": str(e)[:300]})
                except Exception:
                    pass
                if provider_error:
                    await websocket.send_json({"type": "status", "message": provider_error})
                    provider_error = ""
        except Exception as e:
            print(f"[recording {recording_id}] 实时转写中断：{e}")
        finally:
            audio_file.close()
            try:
                if session is not None:
                    await session.finish()
                    await asyncio.sleep(0.5)
            except Exception:
                pass
            try:
                segment_queue.put_nowait(None)
                await asyncio.wait_for(segment_relay_task, timeout=2)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                segment_relay_task.cancel()
            except Exception:
                pass

        # 删除请求可能发生在录音 WebSocket 尚未完全退出时。此时不再生成 WAV、
        # 更新数据库或启动 AI 处理，并清理仍可能由打开文件句柄留下的临时文件。
        if recording_id in cancelled_recording_ids:
            for path in (raw_path, wav_path):
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass
            cancelled_recording_ids.discard(recording_id)
            try:
                await websocket.close(code=1000)
            except Exception:
                pass
            return

        # 原始 PCM 转 WAV（含 44 字节头）
        raw_bytes = raw_path.stat().st_size if raw_path.exists() else 0
        try:
            import wave as _wave
            with _wave.open(str(wav_path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(rasr.SAMPLE_RATE)
                with open(raw_path, "rb") as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk:
                            break
                        w.writeframes(chunk)
            duration = round(raw_bytes / (rasr.SAMPLE_RATE * 2), 3) if raw_bytes else 0
        except Exception as e:
            print(f"[recording {recording_id}] WAV 写入失败：{e}")
            duration = 0
        try:
            raw_path.unlink(missing_ok=True)
        except Exception:
            pass

        unique_segments = _dedupe_segments(segments)
        _update_recording(get_db, recording_id,
                          audio_path=str(wav_path),
                          duration=duration,
                          processed_ms=int(duration * 1000),
                          transcript_json=json.dumps(unique_segments, ensure_ascii=False),
                          status="ai_processing")
        try:
            await websocket.send_json({"type": "done", "segments_count": len(unique_segments)})
            await websocket.close(code=1000)
        except Exception:
            pass
        _spawn_ai_processing(get_db, recording_id)

    @app.post("/api/recordings")
    async def upload_recording(request: Request, background_tasks: BackgroundTasks, file: UploadFile = File(...)):
        if not rasr.asr_configured():
            raise HTTPException(status_code=400, detail="未配置语音识别服务：请在「会议录音」页面填写火山引擎（或讯飞）凭据")
        original = file.filename or "recording"
        suffix = Path(original).suffix.lower() or ".wav"
        if suffix not in {".mp3", ".wav", ".m4a", ".aac", ".amr", ".mp4", ".mov", ".caf", ".flac"}:
            suffix = ".wav"
        with get_db() as conn:
            title = Path(original).stem or "未命名会议录音"
            cur = conn.execute(
                "INSERT INTO recordings (title, audio_path, status, created_at, updated_at) VALUES (?, '', 'uploading', ?, ?)",
                (title, _now(), _now()),
            )
            conn.commit()
            recording_id = cur.lastrowid

        raw_path = recordings_dir / f"{recording_id}{suffix}"
        wav_path = recordings_dir / f"{recording_id}.wav"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        with open(raw_path, "wb") as out:
            while True:
                chunk = await file.read(1024 * 256)
                if not chunk:
                    break
                out.write(chunk)

        async def convert_and_start() -> None:
            try:
                _update_recording(get_db, recording_id, status="converting")
                await run_in_threadpool(rasr.convert_audio_to_pcm16k, raw_path, wav_path)
                if recording_id in cancelled_recording_ids:
                    for path in (raw_path, wav_path):
                        try:
                            path.unlink(missing_ok=True)
                        except Exception:
                            pass
                    cancelled_recording_ids.discard(recording_id)
                    return
                _update_recording(get_db, recording_id, audio_path=str(wav_path))
                await _transcribe_recording_file(get_db, recording_id, wav_path)
            except Exception as e:
                print(f"[recording {recording_id}] 上传转写失败：{e}")
                _update_recording(get_db, recording_id, status="failed", error=str(e)[:500])

        background_tasks.add_task(convert_and_start)
        return {"ok": True, "id": recording_id}

    @app.get("/api/recordings")
    async def list_recordings():
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM recordings ORDER BY created_at DESC LIMIT 60"
            ).fetchall()
        return {"ok": True, "recordings": [_recording_to_dict(dict(r)) for r in rows]}

    @app.get("/api/recordings/{recording_id}")
    async def get_recording(recording_id: int):
        rec = _get_recording(get_db, recording_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="录音不存在")
        return {"ok": True, "recording": _recording_to_dict(rec)}

    @app.get("/api/recordings/{recording_id}/audio")
    async def get_recording_audio(recording_id: int):
        rec = _get_recording(get_db, recording_id)
        if rec is None or not rec.get("audio_path"):
            raise HTTPException(status_code=404, detail="音频文件不存在")
        path = Path(rec["audio_path"])
        if not path.exists():
            raise HTTPException(status_code=404, detail="音频文件不存在")
        return FileResponse(str(path), media_type="audio/wav", filename=f"{rec['title']}.wav")

    @app.delete("/api/recordings/{recording_id}")
    async def delete_recording(recording_id: int):
        rec = _get_recording(get_db, recording_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="录音不存在")
        if rec.get("status") in {"recording", "uploading", "converting", "transcribing", "ai_processing"}:
            cancelled_recording_ids.add(recording_id)
            _update_recording(get_db, recording_id, status="cancelled")
        for path in recordings_dir.glob(f"{recording_id}.*"):
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass
        with get_db() as conn:
            conn.execute("DELETE FROM recordings WHERE id=?", (recording_id,))
            conn.commit()
        return {"ok": True}

    @app.post("/api/recordings/{recording_id}/transcribe")
    async def retranscribe_recording(recording_id: int, background_tasks: BackgroundTasks):
        rec = _get_recording(get_db, recording_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="录音不存在")
        if rec.get("status") in {"recording", "transcribing", "ai_processing"}:
            raise HTTPException(status_code=400, detail="录音正在处理中")
        wav_path = Path(rec.get("audio_path") or "")
        if not wav_path.exists():
            raise HTTPException(status_code=404, detail="音频文件不存在")
        _update_recording(get_db, recording_id, transcript_json="[]", polished_text="", summary="",
                          status="transcribing", error="")

        async def start_transcribe() -> None:
            await _transcribe_recording_file(get_db, recording_id, wav_path)

        background_tasks.add_task(start_transcribe)
        return {"ok": True}

    @app.post("/api/recordings/{recording_id}/ai-process")
    async def reprocess_recording_ai(recording_id: int):
        rec = _get_recording(get_db, recording_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="录音不存在")
        _spawn_ai_processing(get_db, recording_id)
        return {"ok": True}

    @app.post("/api/recordings/{recording_id}/save-to-kb")
    async def save_recording_to_kb(recording_id: int):
        rec = _get_recording(get_db, recording_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="录音不存在")
        segments = json.loads(rec.get("transcript_json") or "[]")
        content = (rec.get("polished_text") or "").strip() or _segments_to_text(segments)
        if not content.strip():
            raise HTTPException(status_code=400, detail="还没有转写内容，无法入库")
        existing_article = rec.get("article_id")
        article_id = existing_article
        if not article_id:
            try:
                article_id = save_article_fn(
                    title=rec["title"],
                    content=content,
                    summary=(rec.get("summary") or "").strip(),
                    domains=[],
                    source_type="recording",
                    source_filename=Path(rec.get("audio_path") or "").name or "",
                    check_duplicate=False,
                )
            except ValueError as e:
                raise HTTPException(status_code=409, detail=str(e))
            _update_recording(get_db, recording_id, article_id=article_id)
        return {"ok": True, "article_id": article_id}


def _dedupe_segments(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """去掉分段结果中重复的句子（同一起始时间只保留最后一条，不含 definite 元信息）。"""
    by_start: Dict[float, Dict[str, Any]] = {}
    for seg in segments:
        key = round(float(seg.get("start", 0)), 3)
        clean = {k: v for k, v in seg.items() if k in {"start", "end", "text"}}
        by_start[key] = clean
    return sorted(by_start.values(), key=lambda s: float(s.get("start", 0)))
