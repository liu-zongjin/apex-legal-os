"""Local, privacy-preserving performance telemetry for APEX.

Only aggregate timings and process/page counts are retained in memory. Request
queries, bodies, client names and file paths are deliberately never recorded.
"""

from __future__ import annotations

import os
import resource
import statistics
import threading
import time
from collections import deque
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


SLOW_REQUEST_MS = 500.0
_REQUESTS: deque[dict[str, Any]] = deque(maxlen=500)
_FRONTEND: dict[str, Any] = {}
_LOCK = threading.Lock()


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return round(ordered[index], 1)


def _rss_mb() -> float:
    # macOS reports bytes; Linux reports KiB.
    raw = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if os.uname().sysname == "Darwin":
        return round(raw / 1024 / 1024, 1)
    return round(raw / 1024, 1)


def _clean_frontend_sample(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    integer_fields = ("openTabs", "mountedPages", "iframes", "domNodes", "longTasks")
    clean: dict[str, Any] = {}
    for key in integer_fields:
        value = payload.get(key)
        if isinstance(value, (int, float)):
            clean[key] = max(0, min(int(value), 1_000_000))
    duration = payload.get("longTaskMaxMs")
    if isinstance(duration, (int, float)):
        clean["longTaskMaxMs"] = round(max(0.0, min(float(duration), 600_000.0)), 1)
    clean["visible"] = bool(payload.get("visible", True))
    clean["recordedAt"] = int(time.time())
    return clean


def snapshot() -> dict[str, Any]:
    with _LOCK:
        requests = list(_REQUESTS)
        frontend = dict(_FRONTEND)
    durations = [float(item["durationMs"]) for item in requests]
    slow = [item for item in requests if float(item["durationMs"]) >= SLOW_REQUEST_MS]
    return {
        "backend": {
            "pid": os.getpid(),
            "rssMb": _rss_mb(),
            "sampleSize": len(requests),
            "medianMs": round(statistics.median(durations), 1) if durations else 0.0,
            "p95Ms": _percentile(durations, 0.95),
            "slowCount": len(slow),
            "recentSlowRequests": slow[-10:],
        },
        "frontend": frontend or None,
        "budgets": {"localApiP95Ms": int(SLOW_REQUEST_MS), "memoryTrend": "no-sustained-growth"},
    }


def install_performance_monitor(app: Any) -> None:
    @app.middleware("http")
    async def record_request_timing(request: Request, call_next):
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration = round((time.perf_counter() - start) * 1000, 1)
            path = request.scope.get("route").path if request.scope.get("route") else request.url.path
            if path not in {"/api/diagnostics/frontend", "/api/diagnostics/performance"}:
                with _LOCK:
                    _REQUESTS.append({
                        "method": request.method,
                        "path": str(path)[:160],
                        "status": status_code,
                        "durationMs": duration,
                        "recordedAt": int(time.time()),
                    })

    @app.post("/api/diagnostics/frontend", include_in_schema=False)
    async def record_frontend_diagnostics(request: Request):
        try:
            sample = _clean_frontend_sample(await request.json())
        except Exception:
            return JSONResponse({"ok": False, "error": "invalid_payload"}, status_code=400)
        with _LOCK:
            _FRONTEND.clear()
            _FRONTEND.update(sample)
        return {"ok": True}

    @app.get("/api/diagnostics/performance")
    async def get_performance_diagnostics():
        return snapshot()
