"""Request-local evidence allocation. Instructions and questions are never clipped."""
from __future__ import annotations

import contextvars
import re
import os
from fastapi import HTTPException

SCOPE = contextvars.ContextVar('stella_ai_input', default=None)
PARTIAL = ('【资料覆盖限制】以下仅为本次来源的部分原文；未提供部分不能视为不存在。'
           '不得声称已穷尽全部资料，引用只限实际展示的完整字段或段落。\n')


def new_scope(question):
    parent = SCOPE.get()
    try:
        limit = max(4, min(64, int(os.environ.get('STELLA_AI_MAX_FOREGROUND_REQUESTS', '24'))))
    except ValueError:
        limit = 24
    usage = parent.get('usage') if parent else None
    return {'question': question, 'sections': [], 'audit': [],
            'usage': usage if usage is not None else {'model_requests': 0, 'limit': limit}}


def before_request():
    scope = SCOPE.get()
    if scope is None:
        return
    from .ai_transport import FINAL
    usage = scope.setdefault('usage', {'model_requests': 0, 'limit': 24})
    # Reserve two final-answer attempts; optional planning/research cannot consume
    # the entire question budget and leave no capacity to deliver its result.
    ceiling = usage['limit'] if FINAL.get() else usage['limit'] - 2
    if usage['model_requests'] >= ceiling:
        raise HTTPException(429, f"本次已达到自动模型请求预算（{usage['model_requests']} 次），已停止追加调用。请分步处理剩余任务。")
    usage['model_requests'] += 1


def register(question, sections):
    scope = SCOPE.get()
    if scope is None:
        return
    scope['question'] = question
    scope['sections'] = [(label, text) for label, text in sections if text]


def size(messages):
    from .ai_context import tokens
    def cost(content):
        if isinstance(content, list):
            return sum(tokens(block.get('text', '')) if block.get('type') in {'text', 'input_text'} else 4096
                       for block in content)
        return tokens(content)
    return sum(cost(m.get('content', '')) + 32 for m in messages)


def excerpt(text, budget, question):
    """Keep complete source records, or a visibly partial prefix of one record.

    Never join unlabelled middle paragraphs from different judgments: this could
    attribute one court's reasoning to another case. Unrecognised formats retain
    source order and stop at a complete line/paragraph boundary.
    """
    from .ai_context import tokens, relevance
    if tokens(text) <= budget:
        return text
    allowance = budget - tokens(PARTIAL)
    if allowance <= 0:
        return ''
    # Stable paragraph IDs and explicit record headings are safe selection units.
    records = re.split(r'(?m)(?=^\[REF:\d+:\d+\]|^【相关文章\d+】|^#{1,4} \d+[.、 ]|^\d+[.、] [《【])', text)
    records = [r for r in records if r.strip()]
    if len(records) > 1:
        chosen, remaining = [], allowance
        # Keep original locators/headings with each entire record; prefer relevant
        # records but restore source order before sending them to the model.
        for index in sorted(range(len(records)), key=lambda i: (-relevance(question, records[i]), i)):
            cost = tokens(records[index])
            if cost <= remaining:
                chosen.append(index)
                remaining -= cost
        if chosen:
            return PARTIAL + ''.join(records[i] for i in sorted(chosen))
    # Unknown MCP formats may mix metadata and quotes. Preserve the prefix rather
    # than inventing a record parser or cutting a quote halfway through a line.
    lines, used = [], 0
    for line in text.splitlines(keepends=True):
        cost = tokens(line)
        if used + cost > allowance:
            break
        lines.append(line)
        used += cost
    return PARTIAL + ''.join(lines) if lines else ''


def fit(messages, limit):
    """Allocate one shared estimated-token ceiling across retrieved sources."""
    scope = SCOPE.get()
    if not scope:
        return
    scope['selected_sections'] = {label: text for label, text in scope.get('sections', [])
                                  if any(text in str(message.get('content', '')) for message in messages)}
    scope['audit'] = []
    if size(messages) <= limit:
        return
    # Count every occurrence; remove longer enclosing sections first to avoid
    # double counting nested snippets and retain all non-evidence instructions.
    skeleton = [dict(m) for m in messages]
    found = []
    for label, text in sorted(scope.get('sections', []), key=lambda item: -len(item[1])):
        count = sum(str(m.get('content', '')).count(text) for m in skeleton)
        if not count:
            continue
        found.append((label, text, count))
        for message in skeleton:
            message['content'] = str(message.get('content', '')).replace(text, '')
    available = limit - size(skeleton)
    if not found or available <= 0:
        return  # The mandatory-input guard supplies an actionable error.
    # Water filling gives short sources their full allocation and distributes the
    # rest fairly. One large provider cannot consume the entire shared window.
    from .ai_context import tokens
    allocations = [0] * len(found)
    pending = set(range(len(found)))
    while pending:
        share = max(0, available // sum(found[i][2] for i in pending))
        small = [i for i in pending if tokens(found[i][1]) <= share]
        if not small:
            for i in pending:
                allocations[i] = share
            break
        for i in small:
            allocations[i] = tokens(found[i][1])
            available -= allocations[i] * found[i][2]
            pending.remove(i)
    audit, selected_sections = [], {}
    for (label, text, count), allocation in zip(found, allocations):
        selected = excerpt(text, allocation, scope.get('question', ''))
        selected_sections[label] = selected
        for message in messages:
            message['content'] = str(message.get('content', '')).replace(text, selected)
        if selected != text:
            audit.append({'source': label, 'original_bytes': len(text.encode('utf-8')),
                          'selected_bytes': len(selected.encode('utf-8'))})
    scope['audit'] = audit
    scope['selected_sections'] = selected_sections
