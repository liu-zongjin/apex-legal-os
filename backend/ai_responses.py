"""Stateless Responses transport normalized to Stella's existing choices contract."""
from __future__ import annotations

import json
import httpx


def normalize_response(data, streamed_text=''):
    if not isinstance(data, dict) or data.get('error') or data.get('status') not in {'completed', 'incomplete'}:
        raise httpx.RemoteProtocolError('模型未返回完整的 Responses 结果')
    if data['status'] == 'incomplete' and (data.get('incomplete_details') or {}).get('reason') != 'max_output_tokens':
        raise httpx.RemoteProtocolError('模型未能完成回答')
    parts = []
    for item in data.get('output') or []:
        if item.get('type') != 'message' or item.get('role', 'assistant') != 'assistant':
            continue
        for block in item.get('content') or []:
            if block.get('type') == 'output_text':
                parts.append(block.get('text') or '')
            elif block.get('type') == 'refusal':
                parts.append(block.get('refusal') or '')
    content = ''.join(parts) or streamed_text
    usage = data.get('usage') or {}
    normalized_usage = {
        'prompt_tokens': usage.get('input_tokens', 0),
        'completion_tokens': usage.get('output_tokens', 0),
        'total_tokens': usage.get('total_tokens', usage.get('input_tokens', 0)+usage.get('output_tokens', 0)),
    }
    if usage.get('input_tokens_details'):
        normalized_usage['prompt_tokens_details'] = usage['input_tokens_details']
    return httpx.Response(200, json={
        'choices': [{'message': {'role': 'assistant', 'content': content, 'reasoning_content': ''},
                     'finish_reason': 'length' if data['status'] == 'incomplete' else 'stop'}],
        'usage': normalized_usage,
    })


async def call_responses(client, url, model, messages, max_tokens, headers, callback=None):
    # Replay local history explicitly. Never store a remote conversation or use
    # previous_response_id; tools and unrelated vendor settings are not enabled.
    def content_parts(content):
        if not isinstance(content, list):
            return content
        result = []
        for block in content:
            if block.get('type') == 'text':
                result.append({'type': 'input_text', 'text': block.get('text', '')})
            elif block.get('type') == 'image_url':
                image = block['image_url']
                result.append({'type': 'input_image', 'image_url': image['url'], 'detail': image.get('detail', 'high')})
            else:
                raise ValueError('Unsupported multimodal content block')
        return result
    payload = {'model': model, 'input': [{'role': m['role'], 'content': content_parts(m.get('content', ''))} for m in messages],
               'max_output_tokens': max_tokens, 'store': False, 'stream': callback is not None}
    if callback is None:
        response = await client.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            return response
        try:
            return normalize_response(response.json())
        except (ValueError, TypeError, AttributeError) as exc:
            raise httpx.RemoteProtocolError('模型返回的 Responses 数据无效') from exc

    await callback('reset', '')
    async with client.stream('POST', url, json=payload, headers=headers) as response:
        if response.status_code != 200:
            await response.aread()
            return httpx.Response(response.status_code, content=response.content)
        if 'text/event-stream' not in response.headers.get('content-type', ''):
            await response.aread()
            try:
                return normalize_response(response.json())
            except (ValueError, TypeError, AttributeError) as exc:
                raise httpx.RemoteProtocolError('模型返回的 Responses 数据无效') from exc
        content, size, frame = [], 0, []
        async for line in response.aiter_lines():
            if line:
                if line.startswith('data:'):
                    frame.append(line[5:].lstrip())
                continue
            if not frame:
                continue
            raw = '\n'.join(frame); frame = []
            if raw == '[DONE]':
                break
            try:
                event = json.loads(raw)
                kind = event.get('type')
                if kind in {'response.failed', 'error'}:
                    raise httpx.RemoteProtocolError('Responses 服务在生成过程中返回错误')
                if kind == 'response.output_text.delta':
                    text = event.get('delta') or ''
                    if not isinstance(text, str):
                        raise ValueError('invalid delta')
                    size += len(text)
                    if size > 1000000:
                        raise ValueError('answer exceeds display limit')
                    content.append(text)
                    await callback('delta', text)
                elif kind in {'response.completed', 'response.incomplete'}:
                    return normalize_response(event.get('response'), ''.join(content))
            except (ValueError, TypeError, AttributeError) as exc:
                raise httpx.RemoteProtocolError('Responses 流式数据无效') from exc
        raise httpx.RemoteProtocolError('Responses 连接已中断，回答尚未完成')
