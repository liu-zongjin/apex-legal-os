"""Run Claude Code-only gateway requests through the official headless client."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx

ROOT = Path(__file__).resolve().parent.parent
CLAUDE_CODE_VERSION = "2.1.295"


def client_path() -> str:
    bundled = ROOT / "data/cc2api-runtime/node_modules/.bin/claude"
    if bundled.is_file():
        return str(bundled.resolve())
    installed = shutil.which("claude")
    if installed:
        return installed
    raise RuntimeError("CC2API 需要官方 Claude Code 客户端，请运行 scripts/install_cc2api_runtime.py")


def base_url(api_url: str) -> str:
    parsed = urlsplit(api_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("CC2API 地址必须是有效的 HTTPS 地址")
    path = parsed.path.rstrip("/")
    if path.endswith("/v1/messages"):
        path = path[:-len("/v1/messages")]
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list) and all(block.get("type") == "text" for block in content):
        return "\n".join(block.get("text", "") for block in content)
    raise ValueError("CC2API 当前支持文本问答，请先将附件提取为文本")


def conversation_prompt(messages: list) -> tuple[str, str]:
    system = []
    turns = []
    for message in messages:
        role = message.get("role")
        text = _text(message.get("content", ""))
        if role == "system":
            system.append(text)
        elif role in {"user", "assistant"}:
            turns.append({"role": role, "content": text})
        else:
            raise ValueError("CC2API 仅接受文本 user/assistant/system 消息")
    if not turns:
        raise ValueError("CC2API 请求缺少对话内容")
    if len(turns) == 1 and turns[0]["role"] == "user":
        prompt = turns[0]["content"]
    else:
        prompt = ("以下 JSON 是当前应用的对话历史。assistant 内容是历史回答，"
                  "请结合全部上下文，仅回答最后一个 user 的问题，不重复历史内容。\n"
                  + json.dumps(turns, ensure_ascii=False))
    return prompt, "\n\n".join(system)


def result_response(data: dict, model: str) -> httpx.Response:
    if data.get("is_error") or data.get("subtype") != "success":
        status = data.get("api_error_status")
        status = status if isinstance(status, int) and 400 <= status <= 599 else 502
        # CLI diagnostics may contain prompts/paths; do not expose them to callers.
        return httpx.Response(status, json={"error": {"message": f"CC2API 客户端调用失败（{status}）"}})
    usage = data.get("usage") or {}
    answer = data.get("result")
    if not isinstance(answer, str) or not answer.strip():
        return httpx.Response(502, json={"error": {"message": "CC2API 未返回回答正文"}})
    return httpx.Response(200, json={
        "model": model, "choices": [{"index": 0, "message": {
            "role": "assistant", "content": answer, "reasoning_content": "",
        }, "finish_reason": "length" if data.get("stop_reason") == "max_tokens" else "stop"}],
        "usage": {"prompt_tokens": usage.get("input_tokens", 0),
                  "completion_tokens": usage.get("output_tokens", 0)},
    })


async def call_cc2api(api_url: str, api_key: str, model: str, messages: list,
                     max_tokens: int = 1500, timeout: float = 180.0) -> httpx.Response:
    executable = client_path()
    endpoint = base_url(api_url)
    prompt, system = conversation_prompt(messages)
    # Never inherit another provider's auth, integrations, or custom settings.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("ANTHROPIC_", "CLAUDE_"))}
    env.update({"ANTHROPIC_BASE_URL": endpoint, "ANTHROPIC_AUTH_TOKEN": api_key,
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                "CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(max(256, int(max_tokens))),
                "CLAUDE_CODE_SKIP_PROMPT_HISTORY": "1"})
    with tempfile.TemporaryDirectory(prefix="stella-cc2api-") as temporary:
        env["CLAUDE_CONFIG_DIR"] = temporary
        args = [executable, "--bare", "-p", "--output-format", "json", "--model", model,
                "--tools", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                "--no-session-persistence", "--max-turns", "1"]
        if system:
            system_path = Path(temporary) / "instructions.txt"
            system_path.write_text(system, encoding="utf-8")
            args.extend(["--append-system-prompt-file", str(system_path)])
        process = await asyncio.create_subprocess_exec(
            *args, cwd=temporary, env=env, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, _stderr = await asyncio.wait_for(
                process.communicate(prompt.encode("utf-8")), timeout=timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
            if process.returncode is None:
                process.kill()
            await process.communicate()
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise httpx.ReadTimeout("CC2API 模型响应超时") from exc
        try:
            data = json.loads(stdout)
        except (ValueError, UnicodeDecodeError):
            return httpx.Response(502, json={"error": {"message": "CC2API 客户端未返回有效结果"}})
        if not isinstance(data, dict):
            return httpx.Response(502, json={"error": {"message": "CC2API 客户端结果格式无效"}})
        if process.returncode and not data.get("is_error"):
            data = {"is_error": True}
        return result_response(data, model)
