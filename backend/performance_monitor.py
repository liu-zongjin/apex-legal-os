"""Local, privacy-preserving performance telemetry for Stella.

Only aggregate timings and process/page counts are retained in memory. Request
queries, bodies, client names and file paths are deliberately never recorded.
"""

from __future__ import annotations

import os
import resource
import statistics
import subprocess
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


def _process_tree_snapshot() -> dict[str, Any]:
    """Return current aggregate process metrics without retaining arguments.

    ``ru_maxrss`` is a historical high-water mark and therefore cannot show
    whether hibernation actually released memory.  ``ps`` is available on the
    supported macOS runtime and lets diagnostics include helper processes while
    exposing only their short executable names, never command-line arguments.
    """
    try:
        completed = subprocess.run(
            ["ps", "-axo", "pid=,ppid=,rss=,pcpu=,comm="],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
        rows: dict[int, dict[str, Any]] = {}
        children: dict[int, list[int]] = {}
        for line in completed.stdout.splitlines():
            parts = line.strip().split(None, 4)
            if len(parts) < 5:
                continue
            pid, ppid = int(parts[0]), int(parts[1])
            rows[pid] = {
                "pid": pid,
                "ppid": ppid,
                "rssKb": max(0, int(parts[2])),
                "cpuPercent": max(0.0, float(parts[3])),
                "name": os.path.basename(parts[4])[:80],
            }
            children.setdefault(ppid, []).append(pid)
        root = os.getpid()
        descendants: list[int] = []
        pending = list(children.get(root, []))
        while pending:
            pid = pending.pop()
            if pid in descendants:
                continue
            descendants.append(pid)
            pending.extend(children.get(pid, []))
        root_row = rows.get(root, {})
        # The sampling ``ps`` command briefly appears as our own child in its
        # output. Exclude that observer so diagnostics report application
        # helpers rather than the act of measurement itself.
        child_rows = [
            rows[pid] for pid in descendants
            if pid in rows and rows[pid].get("name") not in {"ps"}
        ]
        return {
            "currentRssMb": round(float(root_row.get("rssKb", 0)) / 1024, 1),
            "cpuPercent": round(float(root_row.get("cpuPercent", 0)), 1),
            "childProcessCount": len(child_rows),
            "childRssMb": round(sum(float(row["rssKb"]) for row in child_rows) / 1024, 1),
            "childCpuPercent": round(sum(float(row["cpuPercent"]) for row in child_rows), 1),
            "children": [
                {"pid": row["pid"], "name": row["name"], "rssMb": round(row["rssKb"] / 1024, 1)}
                for row in child_rows[:20]
            ],
        }
    except (OSError, ValueError, subprocess.SubprocessError):
        return {
            "currentRssMb": None,
            "cpuPercent": None,
            "childProcessCount": 0,
            "childRssMb": 0.0,
            "childCpuPercent": 0.0,
            "children": [],
        }


def _clean_frontend_sample(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    integer_fields = ("openTabs", "mountedPages", "iframes", "hibernatedPages", "domNodes", "longTasks")
    clean: dict[str, Any] = {}
    for key in integer_fields:
        value = payload.get(key)
        if isinstance(value, (int, float)):
            clean[key] = max(0, min(int(value), 1_000_000))
    duration = payload.get("longTaskMaxMs")
    if isinstance(duration, (int, float)):
        clean["longTaskMaxMs"] = round(max(0.0, min(float(duration), 600_000.0)), 1)
    startup_ms = payload.get("startupMs")
    if isinstance(startup_ms, (int, float)):
        clean["startupMs"] = round(max(0.0, min(float(startup_ms), 600_000.0)), 1)
    if payload.get("startupPage") == "case-manager":
        clean["startupPage"] = "case-manager"
    startup_outcome = payload.get("startupOutcome")
    if startup_outcome in {
        "online", "offline-cache", "offline-no-cache", "offline-fallback", "startup-error"
    }:
        clean["startupOutcome"] = startup_outcome
    if isinstance(payload.get("startupCacheReady"), bool):
        clean["startupCacheReady"] = payload["startupCacheReady"]
    clean["visible"] = bool(payload.get("visible", True))
    clean["recordedAt"] = int(time.time())
    return clean


def snapshot(active_async_tasks: int | None = None) -> dict[str, Any]:
    with _LOCK:
        requests = list(_REQUESTS)
        frontend = dict(_FRONTEND)
    durations = [float(item["durationMs"]) for item in requests]
    slow = [item for item in requests if float(item["durationMs"]) >= SLOW_REQUEST_MS]
    process = _process_tree_snapshot()
    return {
        "backend": {
            "pid": os.getpid(),
            "rssMb": _rss_mb(),
            **process,
            "threadCount": threading.active_count(),
            "activeAsyncTasks": active_async_tasks,
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
        try:
            import asyncio
            active_tasks = sum(1 for task in asyncio.all_tasks() if not task.done())
        except RuntimeError:
            active_tasks = None
        return snapshot(active_tasks)
