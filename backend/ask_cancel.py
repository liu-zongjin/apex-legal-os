"""AI 增强任务取消注册表。

main.py 与 case_files.py 共用：请求开始把当前 asyncio 任务登记进来，
“停止生成”时 /api/ask-cancel/{request_id} 通过 task.cancel() 真正中断
检索、MCP 调用和大模型生成等所有未完成的 await。
"""

import asyncio
import re
from typing import Dict, Optional
from fastapi import HTTPException

_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9_-]{8,80}")

_AI_ASK_TASKS: Dict[str, "asyncio.Task"] = {}


def normalize_request_id(value: Optional[str]) -> str:
    candidate = str(value or "").strip()
    return candidate if _REQUEST_ID_RE.fullmatch(candidate) else ""


def register_current_task(request_id: Optional[str], task: Optional["asyncio.Task"] = None) -> str:
    """登记当前任务的取消句柄，返回规范化后的 request_id（无效时为空串）。

    任务无论正常结束、抛异常还是被取消，都由 done_callback 自动清理注册表，
    调用方无需自行 try/finally。
    """
    key = normalize_request_id(request_id)
    if not key:
        return ""
    task = task or asyncio.current_task()
    previous = _AI_ASK_TASKS.get(key)
    if previous is not None and previous is not task and not previous.done():
        raise HTTPException(409, '同一问答任务仍在执行，请读取原任务状态')
    _AI_ASK_TASKS[key] = task
    def clear(completed):
        if _AI_ASK_TASKS.get(key) is completed:
            _AI_ASK_TASKS.pop(key, None)
    task.add_done_callback(clear)
    return key


def unregister_task(key: str) -> None:
    if _AI_ASK_TASKS.get(key) is asyncio.current_task():
        _AI_ASK_TASKS.pop(key, None)


def cancel_task(request_id: Optional[str]) -> bool:
    """取消指定任务；返回是否真的中断了仍在运行的任务。"""
    key = normalize_request_id(request_id)
    task = _AI_ASK_TASKS.get(key)
    if task and not task.done():
        task.cancel()
        return True
    return False
