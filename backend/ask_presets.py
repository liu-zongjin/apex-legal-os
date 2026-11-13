"""Named, installation-local AI workspace settings."""
import datetime
import json
import re
import uuid
from fastapi import HTTPException, Request

KEY = 'ai_ask_presets_v1'
MODES = {'hybrid', 'local_only', 'direct_ai', 'direct_ai_web', 'public_web_cases', 'aluris_only', 'national_law_only', 'mcp_both'}


def _read(conn):
    row = conn.execute('SELECT value_json FROM app_preferences WHERE preference_key=?', (KEY,)).fetchone()
    if not row:
        return []
    try:
        value = json.loads(row['value_json'])
    except (ValueError, TypeError):
        raise HTTPException(500, '固定搭配数据无法读取，请先恢复设置备份')
    if not isinstance(value, list):
        raise HTTPException(500, '固定搭配数据格式不正确，请先恢复设置备份')
    return value


def _save(conn, items):
    conn.execute('''INSERT INTO app_preferences (preference_key,value_json,updated_at) VALUES (?,?,?)
        ON CONFLICT(preference_key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at''',
        (KEY, json.dumps(items, ensure_ascii=False), datetime.datetime.now().isoformat()))


def register_ask_presets(app, get_db, allowed_models):
    @app.get('/api/ai-ask/presets')
    def list_presets():
        conn = get_db()
        try: return {'presets': _read(conn)}
        finally: conn.close()

    @app.post('/api/ai-ask/presets')
    async def create_preset(request: Request):
        body = await request.json()
        if not isinstance(body, dict): raise HTTPException(400, '固定搭配格式不正确')
        name, mode, model = body.get('name'), body.get('source_mode'), body.get('model')
        skill, effort, case_source = body.get('skill_id'), body.get('reasoning_effort'), body.get('case_source')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40: raise HTTPException(400, '请输入 1 至 40 字的搭配名称')
        if not isinstance(mode, str) or not (mode in MODES or re.fullmatch(r'mcp:[a-z0-9_]+(?:,[a-z0-9_]+)*', mode)): raise HTTPException(400, '回答范围无效')
        if not isinstance(model, str) or model not in allowed_models: raise HTTPException(400, '所选模型不可用')
        if not isinstance(skill, str) or len(skill) > 200: raise HTTPException(400, 'Skill 设置无效')
        if effort not in ('', 'fast', 'low', 'high', 'max') or (effort and model not in ('deepseek-flash', 'deepseek-v4-pro')): raise HTTPException(400, '思考深度设置无效')
        if case_source not in ('mcp', 'public_web', 'both'): raise HTTPException(400, '案例来源无效')
        item = {'id': uuid.uuid4().hex, 'name': name.strip(), 'source_mode': mode, 'model': model, 'skill_id': skill, 'reasoning_effort': effort, 'case_source': case_source}
        conn = get_db()
        try:
            conn.execute('BEGIN IMMEDIATE')
            items = _read(conn)
            if len(items) >= 40: raise HTTPException(400, '最多保存 40 个固定搭配')
            if any(x.get('name') == item['name'] for x in items if isinstance(x, dict)): raise HTTPException(409, '已有同名搭配，请使用其他名称')
            items.append(item); _save(conn, items); conn.commit()
        except Exception:
            conn.rollback(); raise
        finally: conn.close()
        return {'preset': item}

    @app.delete('/api/ai-ask/presets/{preset_id}')
    def delete_preset(preset_id: str):
        if not re.fullmatch(r'[a-f0-9]{32}', preset_id): raise HTTPException(400, '固定搭配编号无效')
        conn = get_db()
        try:
            conn.execute('BEGIN IMMEDIATE')
            items = _read(conn)
            kept = [item for item in items if item.get('id') != preset_id]
            if len(kept) == len(items): raise HTTPException(404, '固定搭配不存在')
            _save(conn, kept); conn.commit()
        except Exception:
            conn.rollback(); raise
        finally: conn.close()
        return {'success': True}
