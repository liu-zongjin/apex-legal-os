"""Per-question reasoning settings for the official DeepSeek API."""
import contextvars
from fastapi import HTTPException

MODELS = {'deepseek-flash', 'deepseek-v4-pro'}
LEVELS = {'fast', 'low', 'high', 'max'}
BUDGETS = {'low': 16000, 'high': 32000, 'max': 48000}
TIMEOUTS = {'low': 300.0, 'high': 480.0, 'max': 600.0}
# Case research makes multiple structured calls, so its per-call output caps
# and wall-clock budgets are separate from those for a single final answer.
RESEARCH_STAGE = contextvars.ContextVar('stella_public_case_reasoning', default=False)
RESEARCH_BUDGETS = {'low': 8000, 'high': 16000, 'max': 24000}
RESEARCH_STAGE_TIMEOUTS = {'low': 90, 'high': 180, 'max': 300}
RESEARCH_TOTAL_TIMEOUTS = {'low': 900, 'high': 1500, 'max': 2400}


def validate(model, value):
    value = str(value or '').strip()
    if not value:
        return ''  # Existing callers retain their current behavior.
    if value not in LEVELS:
        raise HTTPException(422, '无效的思考深度')
    if model not in MODELS:
        raise HTTPException(400, '当前模型暂不支持思考深度调节')
    return value
