"""Exercise the actual model transport in a subprocess with an empty runtime."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class AgentModelPolicyTests(unittest.TestCase):
    def test_transport_limits_fallback_retries_and_context_isolation(self):
        script = r'''
import asyncio,json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock,patch
import httpx
from fastapi import HTTPException
from backend import main,agent_policy

async def run():
    sent=[]
    mode=['fallback']
    async def handler(request):
        model=json.loads(request.content)['model'];sent.append(model)
        if mode[0]=='fallback':return httpx.Response(429)
        if mode[0]=='disconnect':raise httpx.RemoteProtocolError('anonymous disconnect')
        return httpx.Response(200,json={'choices':[{'message':{'content':'anonymous result'},'finish_reason':'stop'}]})
    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as value:yield value
    with patch.object(main,'ai_http_client',client),patch.object(main,'_get_api_config',side_effect=lambda m:('https://fixture.invalid','anonymous-key',m)),patch.object(main,'_ai_fallback_models',return_value=['fixture-other']),patch.object(main.asyncio,'sleep',AsyncMock()):
        consumed=[]
        with agent_policy.task_policy('fixture-primary',lambda:consumed.append(1)):
            try:await main._call_ai_with_fallback('fixture-primary',[{'role':'user','content':'anonymous'}])
            except HTTPException as exc:assert exc.status_code==403
            else:raise AssertionError('unauthorized fallback was allowed')
        assert sent==['fixture-primary'] and len(consumed)==1
        sent.clear();mode[0]='disconnect'
        consumed.clear()
        def consume():
            if consumed:raise HTTPException(429,'anonymous budget exhausted')
            consumed.append(1)
        with agent_policy.task_policy('fixture-primary',consume):
            try:await main._call_ai_with_fallback('fixture-primary',[{'role':'user','content':'anonymous'}])
            except HTTPException as exc:assert exc.status_code==429
            else:raise AssertionError('retry exceeded request budget')
        assert sent==['fixture-primary']
        mode[0]='success';sent.clear()
        counts={'fixture-a':0,'fixture-b':0}
        async def one(model):
            def increment():counts[model]+=1
            with agent_policy.task_policy(model,increment):
                result,actual=await main._call_ai_with_fallback(model,[{'role':'user','content':'anonymous'}])
                assert actual==model
        await asyncio.gather(one('fixture-a'),one('fixture-b'))
        assert counts=={'fixture-a':1,'fixture-b':1}
        assert agent_policy.CURRENT.get() is None
asyncio.run(run())
'''
        with tempfile.TemporaryDirectory(prefix='stella-agent-policy-') as temporary:
            env = os.environ.copy()
            env.update(LEGAL_KB_RUNTIME_DIR=temporary, LEGAL_KB_DB_PATH=str(Path(temporary) / 'anonymous.db'),
                       LEGAL_KB_UPLOAD_DIR=str(Path(temporary) / 'uploads'),
                       LEGAL_KB_ARTICLE_IMAGE_DIR=str(Path(temporary) / 'images'))
            result = subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[1],
                                    env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr[-3000:])
