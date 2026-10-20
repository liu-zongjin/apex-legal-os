"""Local, privacy-preserving performance telemetry for APEX.

Only aggregate timings and process/page counts are retained in memory. Request
queries, bodies, client names and file paths are deliberately never recorded.
"""

from __future__ import annotations

import os
try:
    import resource
except ImportError:  # Windows has no Unix resource module.
    resource = None
import sys
import statistics
import subprocess
import threading
import time
from collections import deque
from contextlib import contextmanager
from starlette.concurrency import run_in_threadpool
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


SLOW_REQUEST_MS = 500.0
_REQUESTS: deque[dict[str, Any]] = deque(maxlen=500)
_FRONTEND: dict[str, Any] = {}
_LOCK = threading.Lock()
_PHASES = {}
_LOOP_LAG = deque(maxlen=120)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return round(ordered[index], 1)


def _rss_mb() -> float:
    if resource is None:
        try:
            import psutil
            return round(psutil.Process().memory_info().rss / 1024 / 1024, 1)
        except (ImportError, OSError):
            return 0.0
    # macOS reports bytes; Linux reports KiB.
    raw = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform == "darwin":
        return round(raw / 1024 / 1024, 1)
    return round(raw / 1024, 1)


def _process_tree_snapshot() -> dict[str, Any]:
    """Return current aggregate process metrics without retaining arguments.

    ``ru_maxrss`` is a historical high-water mark and therefore cannot show
    whether hibernation actually released memory.  ``ps`` is available on the
    supported macOS runtime and lets diagnostics include helper processes while
    exposing only their short executable names, never command-line arguments.
    """
    if sys.platform == "win32":
        try:
            import psutil
            root = psutil.Process()
            children = root.children(recursive=True)
            rows = []
            for child in children:
                try:
                    rows.append({"pid": child.pid, "name": child.name()[:80],
                                 "rssMb": round(child.memory_info().rss / 1024**2, 1)})
                except psutil.Error:
                    continue
            return {"currentRssMb": round(root.memory_info().rss / 1024**2, 1),
                    "cpuPercent": None, "childProcessCount": len(rows),
                    "childRssMb": round(sum(r["rssMb"] for r in rows), 1),
                    "childCpuPercent": None, "children": rows[:20]}
        except (ImportError, OSError):
            return {"currentRssMb": None, "cpuPercent": None, "childProcessCount": None,
                    "childRssMb": None, "childCpuPercent": None, "children": []}
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
    if isinstance(payload.get("longTaskSupported"), bool):
        clean["longTaskSupported"] = payload["longTaskSupported"]
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
        phases = {k:list(v) for k,v in _PHASES.items()}
        loop_lag = list(_LOOP_LAG)
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
            "categories": {category: {'sampleSize': len([r for r in requests if r.get('category') == category]),
                'p95Ms': _percentile([r['durationMs'] for r in requests if r.get('category') == category], .95)}
                for category in ('local','static','external','heavy','ai','stream')},
            "eventLoopLagP95Ms": _percentile(loop_lag, .95),
            "memoryScope": "python-and-direct-descendants; native-WebKit-not-included",
            "phases": {k: {'samples': len(v), 'p95Ms': _percentile(list(v), .95)} for k,v in phases.items()},
            "recentSlowRequests": slow[-10:],
        },
        "frontend": frontend or None,
        "budgets": {"localApiP95Ms": int(SLOW_REQUEST_MS), "memoryTrend": "no-sustained-growth"},
    }


def install_performance_monitor(app: Any) -> None:
    app.add_middleware(RequestMetrics)
    lag_state = {'task': None}
    @app.on_event('startup')
    async def start_lag_monitor():
        import asyncio
        async def monitor():
            loop = asyncio.get_running_loop()
            while True:
                expected = loop.time() + 1
                await asyncio.sleep(1)
                with _LOCK:
                    _LOOP_LAG.append(max(0.0, (loop.time() - expected) * 1000))
        lag_state['task'] = asyncio.create_task(monitor())
    @app.on_event('shutdown')
    async def stop_lag_monitor():
        if lag_state['task'] is not None:
            lag_state['task'].cancel()

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
        return await run_in_threadpool(snapshot, active_tasks)


@contextmanager
def measure_phase(name):
    if name not in {'ai-provider', 'ai-pool-wait', 'ai-background', 'case-snapshot', 'relation-scan'}:
        raise ValueError('Unknown aggregate phase')
    start = time.perf_counter()
    try:
        yield
    finally:
        with _LOCK:
            _PHASES.setdefault(name, deque(maxlen=120)).append(round((time.perf_counter()-start)*1000, 1))


def request_category(path, streaming=False):
    if streaming: return 'stream'
    if path.startswith('/static'): return 'static'
    # These endpoints await remote mail servers, including the home aggregate.
    if path.startswith(('/proxy', '/api/qq-mail/')) or path == '/api/home/reminder-center': return 'external'
    if '/ask' in path: return 'ai'
    if any(x in path for x in ('offline-snapshot','export','download','preview','scan','sync')): return 'heavy'
    return 'local'


class RequestMetrics:
    """Outermost ASGI observer includes middleware, response bytes and errors."""
    def __init__(self, app):
        self.app = app
    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        start = time.perf_counter(); status = 500; headers_ms = 0.0; streaming = False
        async def observe(message):
            nonlocal status, headers_ms, streaming
            if message['type'] == 'http.response.start':
                status = message['status']; headers_ms = (time.perf_counter()-start)*1000
                streaming = any(k.lower()==b'content-type' and b'text/event-stream' in v for k,v in message.get('headers', []))
            await send(message)
        try:
            await self.app(scope, receive, observe)
        finally:
            route = scope.get('route')
            path = getattr(route, 'path', '/unmatched')
            if scope.get('path', '').startswith('/static/'):
                path = '/static/{asset}'  # Mounts may not expose a route object.
            if path not in {'/api/diagnostics/frontend', '/api/diagnostics/performance'}:
                category = request_category(path, streaming)
                with _LOCK:
                    _REQUESTS.append({'method':scope['method'], 'path':path[:160], 'status':status,
                        'durationMs':round((time.perf_counter()-start)*1000,1),
                        'headersMs':round(headers_ms,1), 'category':category, 'recordedAt':int(time.time())})
