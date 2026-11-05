"""Opt-in metrics for source runtimes. No business data or account identifiers."""
import asyncio
import os
import platform
import sys
from pathlib import Path

from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, StrictBool


class Consent(BaseModel):
    allowed: StrictBool


def install_source_statistics(app):
    sender = None
    task = None
    wake = None

    def current():
        nonlocal sender
        # Only launchers that prepare an isolated source profile enable this.
        if os.environ.get('STELLA_SOURCE_STATISTICS') != '1':
            return None
        if sender is None:
            from scripts.windows.bootstrap_engine import atomic_json, exclusive_lock
            from scripts.windows.windows_telemetry import Statistics, post_event, windows_version
            def version():
                return windows_version() if sys.platform == 'win32' else platform.mac_ver()[0] or '0.0.0'
            def post(payload):
                return post_event({**payload, 'channel': 'source'})
            sender = Statistics(Path(os.environ['LEGAL_KB_RUNTIME_DIR']), '2026110501',
                                exclusive_lock, atomic_json, post=post, version=version)
        return sender

    @app.get('/api/source-statistics')
    async def status():
        metrics = current()
        return {'enabled': metrics is not None, **(metrics.status() if metrics else {'allowed': None})}

    @app.put('/api/source-statistics')
    async def consent(body: Consent, request: Request):
        # Browser writes must originate at this exact loopback app, not another site.
        if request.headers.get('origin') != str(request.base_url).rstrip('/'):
            raise HTTPException(403, 'invalid_origin')
        metrics = current()
        if metrics is None:
            raise HTTPException(404, 'source_statistics_disabled')
        result = await run_in_threadpool(metrics.consent, body.allowed)
        if wake is not None:
            wake.set()
        return {'enabled': True, **result}

    async def run():
        while True:
            wake.clear()
            try:
                delay = await run_in_threadpool(current().run_due)
            except Exception:
                delay = 300
            try:
                await asyncio.wait_for(wake.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    @app.on_event('startup')
    async def start():
        nonlocal task, wake
        wake = asyncio.Event()
        if current() is not None:
            task = asyncio.create_task(run())

    @app.on_event('shutdown')
    async def stop():
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
