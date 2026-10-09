from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Tuple

import httpx

from .ai_config import (
    CC2API_API_KEY,
    CC2API_API_URL,
    ARK_API_KEY,
    ARK_API_URL,
    DEEPSEEK_API_KEY,
    DEEPSEEK_API_URL,
    OPENCODE_API_KEY,
    OPENCODE_API_URL,
    SCNET_API_KEY,
    SCNET_API_URL,
    SILICONFLOW_API_KEY,
    SILICONFLOW_API_URL,
    canonical_model_id,
    effective_temperature,
    opencode_request_headers,
)

FALLBACK_STATUS_CODES = {402, 429}


def fallback_model() -> str:
    """降级备用模型（可在 AI API 管理页修改）。"""
    from .ai_config import effective_purpose_model
    return effective_purpose_model("fallback")


def api_config(model: str) -> Tuple[str, str, str]:
    model = canonical_model_id(model)
    if model.startswith("cc2api:"):
        return CC2API_API_URL, CC2API_API_KEY, model[len("cc2api:"):]
    if model.startswith("doubao:"):
        mapping = {
            "Doubao-Seed-2.0-pro": "ep-20260505135746-4798d",
            "Doubao-Seed-2.0-lite": "ep-20260505155909-kzbtw",
            "Doubao-Seed-2.0-mini": "ep-20260505141255-h5dfb",
        }
        name = model[len("doubao:"):]
        return ARK_API_URL, ARK_API_KEY, mapping.get(name, name)
    if model.startswith("scnet:"):
        return SCNET_API_URL, SCNET_API_KEY, model[len("scnet:"):]
    if model.startswith("opencode:"):
        return OPENCODE_API_URL, OPENCODE_API_KEY, model[len("opencode:"):]
    if "/" in model:
        return SILICONFLOW_API_URL, SILICONFLOW_API_KEY, model
    return DEEPSEEK_API_URL, DEEPSEEK_API_KEY, model


def prepare_cc2api_request(api_key: str, payload: Dict[str, Any]):
    """Translate text conversations into Anthropic Messages without client spoofing."""
    body = dict(payload)
    system = []
    messages = []
    for message in payload.get("messages", []):
        if message.get("role") == "system":
            content = message.get("content", "")
            system.extend(content if isinstance(content, list) else [{"type": "text", "text": content}])
        else:
            messages.append(dict(message))
    body["messages"] = messages
    if system:
        body["system"] = system
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
        "User-Agent": "Stella/1.0",
    }
    return headers, body


def normalize_cc2api_response(response: httpx.Response) -> httpx.Response:
    """Keep existing callers on the shared Chat Completions response contract."""
    if response.status_code != 200:
        return response
    data = response.json()
    if data.get("type") != "message":
        return httpx.Response(502, json={"error": {"message": "Invalid Messages response"}})
    blocks = data.get("content") or []
    usage = data.get("usage") or {}
    result = {
        "id": data.get("id"), "model": data.get("model"),
        "choices": [{"index": 0, "message": {
            "role": "assistant",
            "content": "".join(block.get("text", "") for block in blocks if block.get("type") == "text"),
            "reasoning_content": "".join(block.get("thinking", "") for block in blocks if block.get("type") == "thinking"),
        }, "finish_reason": "length" if data.get("stop_reason") == "max_tokens" else "stop"}],
        "usage": {"prompt_tokens": usage.get("input_tokens", 0),
                  "completion_tokens": usage.get("output_tokens", 0)},
    }
    return httpx.Response(200, json=result)


def model_available(model: str) -> bool:
    return bool(api_config(model)[1])


async def call_ai_with_fallback(
    model: str,
    messages: List[Dict[str, str]],
    temperature: float = 0.1,
    max_tokens: int = 1200,
) -> Tuple[Dict[str, Any], str]:
    async def request(selected: str) -> httpx.Response:
        url, key, real_model = api_config(selected)
        if not key:
            raise RuntimeError(f"AI 服务未配置密钥：{selected}")
        timeout = 120.0 if selected in {"deepseek-reasoner", "deepseek-ai/DeepSeek-R1"} else 60.0
        payload = {
            "model": real_model,
            "messages": messages,
            "temperature": effective_temperature(real_model, temperature),
            "max_tokens": max_tokens,
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        if selected.startswith("opencode:"):
            headers = opencode_request_headers(key)
        if selected.startswith("cc2api:"):
            headers, payload = prepare_cc2api_request(key, payload)
        # 工具规划只需很短的 JSON。网关在响应前断开时重试一次即可；
        # 不把超时重试留给这里，避免占满问答总时长。
        for attempt, delay in enumerate((0.0, 0.8)):
            if delay:
                await asyncio.sleep(delay)
            try:
                timeout_config = httpx.Timeout(
                    timeout,
                    connect=min(15.0, timeout),
                    write=min(30.0, timeout),
                    pool=15.0,
                )
                async with httpx.AsyncClient(timeout=timeout_config) as client:
                    response = await client.post(
                        url,
                        headers=headers,
                        json=payload,
                    )
                    return normalize_cc2api_response(response) if selected.startswith("cc2api:") else response
            except (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError):
                if attempt == 1:
                    raise
        raise RuntimeError("AI 请求未返回结果")

    response = await request(model)
    actual_model = model
    fallback = fallback_model()
    if response.status_code in FALLBACK_STATUS_CODES and model != fallback:
        response = await request(fallback)
        actual_model = fallback
    if response.status_code != 200:
        raise RuntimeError(f"AI 服务错误（{response.status_code}）：{response.text[:500]}")
    return response.json(), actual_model
