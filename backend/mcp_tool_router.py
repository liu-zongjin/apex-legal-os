"""Runtime MCP capability discovery and AI-assisted tool-call planning.

Adapters keep responsibility for entity resolution and result normalization. This
module removes the assumption that an MCP server has a fixed, hand-coded tool set:
it reads ``tools/list``, asks the configured lightweight model to select relevant
tools from the user's original request, then validates every proposed call against
the advertised JSON schema before execution.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import httpx

from .ai_client import call_ai_with_fallback
from .ai_config import effective_default_model


class MCPToolRouterError(RuntimeError):
    pass


_TOOL_CACHE: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
_TOOL_CACHE_SECONDS = 600.0


def _decode_envelope(response: httpx.Response) -> Dict[str, Any]:
    response.raise_for_status()
    raw = response.text.strip()
    payloads = [line[5:].strip() for line in raw.splitlines() if line.startswith("data:")]
    if not payloads:
        payloads = [raw]
    for value in reversed(payloads):
        try:
            envelope = json.loads(value)
        except (TypeError, ValueError):
            continue
        if isinstance(envelope, dict):
            if envelope.get("error"):
                message = (envelope.get("error") or {}).get("message") or "MCP 请求失败"
                raise MCPToolRouterError(str(message))
            return envelope
    raise MCPToolRouterError("MCP 返回了无法识别的数据")


async def discover_streamable_http_tools(
    url: str,
    headers: Mapping[str, str],
    *,
    cache_key: str = "",
    timeout: float = 35.0,
) -> List[Dict[str, Any]]:
    """Read and briefly cache a Streamable HTTP server's advertised tools."""
    key = cache_key or url
    cached = _TOOL_CACHE.get(key)
    if cached and time.monotonic() - cached[0] < _TOOL_CACHE_SECONDS:
        return cached[1]
    request_headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        **dict(headers),
    }
    initialize = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "legal-knowledge-base-tool-router", "version": "1.0.0"},
        },
    }
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            init_response = await client.post(url, json=initialize, headers=request_headers)
            _decode_envelope(init_response)
            session_headers = dict(request_headers)
            session_id = init_response.headers.get("mcp-session-id")
            if session_id:
                session_headers["mcp-session-id"] = session_id
            await client.post(
                url,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers=session_headers,
            )
            response = await client.post(
                url,
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                headers=session_headers,
            )
            envelope = _decode_envelope(response)
    except httpx.TimeoutException as exc:
        raise MCPToolRouterError("读取 MCP 工具清单超时") from exc
    except httpx.RequestError as exc:
        raise MCPToolRouterError("当前无法读取 MCP 工具清单") from exc
    tools = (envelope.get("result") or {}).get("tools") or []
    normalized = [tool for tool in tools if isinstance(tool, dict) and tool.get("name")]
    if not normalized:
        raise MCPToolRouterError("MCP 未公布可用工具")
    _TOOL_CACHE[key] = (time.monotonic(), normalized)
    return normalized


def _json_from_model(text: str) -> Dict[str, Any]:
    value = str(text or "").strip()
    value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.IGNORECASE)
    try:
        parsed = json.loads(value)
    except ValueError:
        match = re.search(r"\{.*\}", value, flags=re.DOTALL)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
        except ValueError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


def _compact_tool(tool: Dict[str, Any]) -> Dict[str, Any]:
    schema = tool.get("inputSchema") or {}
    properties = schema.get("properties") or {}
    return {
        "name": tool.get("name"),
        "title": tool.get("title") or "",
        "description": re.sub(r"\s+", " ", str(tool.get("description") or ""))[:500],
        "parameters": {
            name: {
                "type": (detail or {}).get("type"),
                "description": re.sub(r"\s+", " ", str((detail or {}).get("description") or ""))[:240],
                **({"enum": (detail or {}).get("enum")} if (detail or {}).get("enum") else {}),
            }
            for name, detail in properties.items()
            if isinstance(detail, dict)
        },
        "required": schema.get("required") or [],
    }


def validate_tool_calls(
    proposed: Iterable[Dict[str, Any]],
    tools: Iterable[Dict[str, Any]],
    *,
    max_calls: int = 4,
    argument_overrides: Optional[Mapping[str, Any]] = None,
    excluded_tools: Iterable[str] = (),
) -> List[Dict[str, Any]]:
    """Allowlist names/arguments and enforce advertised required parameters."""
    catalog = {str(tool.get("name")): tool for tool in tools if isinstance(tool, dict)}
    excluded = set(excluded_tools)
    overrides = dict(argument_overrides or {})
    result, seen = [], set()
    for item in proposed:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        if not name or name in excluded or name in seen or name not in catalog:
            continue
        schema = catalog[name].get("inputSchema") or {}
        properties = schema.get("properties") or {}
        raw_arguments = item.get("arguments") if isinstance(item.get("arguments"), dict) else {}
        arguments = {
            key: value for key, value in raw_arguments.items()
            if key in properties and value is not None
        }
        for key, value in overrides.items():
            if key in properties:
                arguments[key] = value
        if any(key not in arguments or arguments[key] in (None, "") for key in schema.get("required") or []):
            continue
        result.append({"name": name, "arguments": arguments})
        seen.add(name)
        if len(result) >= max(1, min(int(max_calls or 4), 8)):
            break
    return result


async def plan_mcp_tool_calls(
    question: str,
    tools: List[Dict[str, Any]],
    *,
    source_name: str,
    max_calls: int = 4,
    argument_overrides: Optional[Mapping[str, Any]] = None,
    excluded_tools: Iterable[str] = (),
) -> List[Dict[str, Any]]:
    """Use the configured model to select relevant advertised tools and arguments."""
    usable = [tool for tool in tools if str(tool.get("name") or "") not in set(excluded_tools)]
    prompt = {
        "source": source_name,
        "user_question": str(question or "").strip(),
        "max_calls": max_calls,
        "tools": [_compact_tool(tool) for tool in usable],
    }
    messages = [
        {
            "role": "system",
            "content": (
                "你是MCP工具调用规划器。根据用户原话选择能够直接提供所需字段的专用工具；"
                "不要因为常用就调用无关的通用工具。多维问题可选择多个互补工具，禁止虚构工具名或参数。"
                "只输出JSON：{\"calls\":[{\"name\":\"工具名\",\"arguments\":{}}]}。"
            ),
        },
        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
    ]
    response, _ = await asyncio.wait_for(
        call_ai_with_fallback(
            effective_default_model(), messages, temperature=0.0, max_tokens=900
        ),
        timeout=12.0,
    )
    choice = ((response.get("choices") or [{}])[0] or {}).get("message") or {}
    parsed = _json_from_model(choice.get("content") or "")
    return validate_tool_calls(
        parsed.get("calls") or [], tools, max_calls=max_calls,
        argument_overrides=argument_overrides, excluded_tools=excluded_tools,
    )
