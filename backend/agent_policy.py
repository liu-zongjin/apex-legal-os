"""Request-local limits for durable material tasks; ordinary AI calls are unchanged."""
from contextlib import contextmanager
from contextvars import ContextVar

from fastapi import HTTPException

CURRENT = ContextVar('stella_agent_policy', default=None)


@contextmanager
def task_policy(model, consume):
    token = CURRENT.set((model, consume))
    try:
        yield
    finally:
        CURRENT.reset(token)


def check_model(model):
    policy = CURRENT.get()
    if policy is not None and model != policy[0]:
        raise HTTPException(403, '任务仅授权所选模型；未向其他模型发送材料')


def before_request(model):
    """Called immediately before each upstream request, including retries."""
    check_model(model)
    policy = CURRENT.get()
    if policy is not None:
        policy[1]()
