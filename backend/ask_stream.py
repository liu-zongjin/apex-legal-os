"""Additive direct-answer transport; final result remains authoritative."""
import asyncio
import json
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from .ai_transport import DELTA


def register_ask_stream(app, answer):
    @app.post('/api/ask-stream')
    async def ask_stream(request: Request):
        form = await request.form()
        if form.get('source_mode') != 'direct_ai':
            raise HTTPException(400, '当前流式入口只支持直接 AI 问答')
        values = {k:form.get(k) for k in ('question','focus_case_id','model','article_ids','source_mode',
            'request_id','skill_id','conversation_context','history_key','current_message_id')}
        values['model'] = values['model'] or ''
        values['case_search'] = False
        values['memory_enabled'] = str(form.get('memory_enabled','true')).lower() in {'1','true','yes','on'}
        if values['focus_case_id']:
            try: values['focus_case_id'] = int(values['focus_case_id'])
            except ValueError: raise HTTPException(422, '无效的案件编号')
        else:
            values['focus_case_id'] = None
        queue = asyncio.Queue(maxsize=32)
        async def emit(event, text):
            await queue.put((event, {'text':text}))
        async def produce():
            token = DELTA.set(emit)
            try:
                result = await answer(**values)
                if hasattr(result, 'body'):
                    result = json.loads(result.body)
                await queue.put(('result', result))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                detail = exc.detail if isinstance(exc, HTTPException) else '生成中断，可检查原任务状态后重试'
                await queue.put(('error', {'message':detail}))
            finally:
                DELTA.reset(token)
        async def events():
            task = asyncio.create_task(produce())
            try:
                while True:
                    try:
                        event, payload = await asyncio.wait_for(queue.get(), 10)
                    except asyncio.TimeoutError:
                        yield ': heartbeat\n\n'
                        continue
                    yield 'event: ' + event + '\ndata: ' + json.dumps(payload,ensure_ascii=False) + '\n\n'
                    if event in {'result','error'}: break
            finally:
                if not task.done(): task.cancel()
                try: await task
                except asyncio.CancelledError: pass
        return StreamingResponse(events(), media_type='text/event-stream',
            headers={'Cache-Control':'no-store','X-Accel-Buffering':'no','Content-Encoding':'identity'})
