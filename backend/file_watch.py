"""Reference-counted directory subscriptions, shared per event loop/root."""
from __future__ import annotations
import asyncio
import json
import weakref
from fastapi import HTTPException

_LOOPS = weakref.WeakKeyDictionary()


async def changes_for(root):
    loop = asyncio.get_running_loop()
    roots = _LOOPS.setdefault(loop, {})
    key = str(root)
    if key not in roots:
        if len(roots) >= 32:
            raise HTTPException(429, '已达到同时监控目录上限，请关闭闲置文件页')
        entry = {'queues': set(), 'task': None}
        roots[key] = entry
        async def watch():
            try:
                from watchfiles import awatch
                async for changes in awatch(root, debounce=350, step=120, recursive=True, rust_timeout=15000):
                    paths = []
                    for _, changed in changes:
                        try:
                            paths.append(__import__('pathlib').Path(changed).resolve().relative_to(root).as_posix())
                        except (OSError, ValueError):
                            pass
                    event = 'event: change\ndata: ' + json.dumps({'changed_paths':sorted(set(paths))}) + '\n\n'
                    for queue in list(entry['queues']):
                        if queue.full():
                            queue.get_nowait()  # Coalesce; the page refreshes full columns.
                        queue.put_nowait(event)
            except asyncio.CancelledError:
                raise
            except Exception:
                for queue in list(entry['queues']):
                    if queue.full(): queue.get_nowait()
                    queue.put_nowait('event: error\ndata: {"message":"目录监听中断，请重新连接"}\n\n')
            finally:
                for queue in list(entry['queues']):
                    if queue.full(): queue.get_nowait()
                    queue.put_nowait(None)
        entry['task'] = asyncio.create_task(watch())
    entry = roots[key]
    queue = asyncio.Queue(maxsize=4)
    if len(entry['queues']) >= 32:
        raise HTTPException(429, '该目录的订阅过多')
    entry['queues'].add(queue)
    try:
        yield 'event: ready\ndata: {}\n\n'
        while True:
            event = await queue.get()
            if event is None:
                break
            yield event
    finally:
        entry['queues'].discard(queue)
        if not entry['queues']:
            roots.pop(key, None)
            entry['task'].cancel()
            try: await entry['task']
            except asyncio.CancelledError: pass
