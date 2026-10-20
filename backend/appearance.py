"""One runtime profile shared by local/public UI and document generation."""
import base64
import datetime
import io
import json
import re

from fastapi import HTTPException, Request
from fastapi.responses import Response

KEY = 'stella.appearance.v1'
DEFAULTS = {'user_name':'新用户', 'firm_name':'', 'firm_logo':'', 'firm_code':'', 'firm_address':'', 'firm_phone':''}


def get_appearance(get_db):
    with get_db() as conn:
        row=conn.execute('SELECT value_json FROM app_preferences WHERE preference_key=?',(KEY,)).fetchone()
    value=json.loads(row[0]) if row else {}
    profile={**DEFAULTS, **{k:v for k,v in value.items() if k in DEFAULTS}}
    profile['firm_code']=re.sub(r'(?:函|律)\s*字\s*第\s*$','',profile['firm_code'])
    return profile


def normalize_logo(value):
    from PIL import Image
    if value == '': return ''
    if not isinstance(value,str) or len(value)>2200000 or not value.startswith(('data:image/png;base64,','data:image/webp;base64,')):
        raise ValueError('请上传不超过 1.5 MB 的 PNG 或 WebP 图片')
    try:
        content=base64.b64decode(value.split(',',1)[1],validate=True)
        if len(content)>1572864: raise ValueError()
        image=Image.open(io.BytesIO(content))
        if image.format not in ('PNG','WEBP') or image.width>4096 or image.height>4096: raise ValueError()
        image.load();output=io.BytesIO();image.convert('RGBA').save(output,format='PNG')
        if len(output.getvalue())>1572864: raise ValueError()
        return 'data:image/png;base64,'+base64.b64encode(output.getvalue()).decode()
    except Exception:
        raise ValueError('图片无法读取或尺寸过大，请使用不超过 4096 像素的 PNG 或 WebP')


def validate_update(value):
    if not isinstance(value,dict) or not value or any(k not in DEFAULTS for k in value): raise ValueError('设置内容不正确')
    result={}
    for key,item in value.items():
        if key=='firm_logo':result[key]=normalize_logo(item);continue
        if not isinstance(item,str) or len(item)> (300 if key=='firm_address' else 80) or any(ord(c)<32 for c in item):raise ValueError('请检查姓名或律所资料的长度与格式')
        result[key]=item.strip()
        if key=='firm_code':result[key]=re.sub(r'(?:函|律)\s*字\s*第\s*$','',result[key])
        if key=='user_name' and not result[key]:result[key]='新用户'
    return result


def logo_stream(profile):
    return io.BytesIO(base64.b64decode(profile['firm_logo'].split(',',1)[1])) if profile.get('firm_logo') else None


def register_appearance_routes(app,get_db):
    @app.get('/api/appearance')
    def read_appearance():return get_appearance(get_db)

    @app.put('/api/appearance')
    async def write_appearance(request: Request):
        if request.headers.get('origin') not in (None,str(request.base_url).rstrip('/')):
            raise HTTPException(403,'请从 Stella 页面保存设置')
        if not request.headers.get('content-type','').startswith('application/json'):
            raise HTTPException(415,'请使用 JSON 保存设置')
        chunks=[];length=0
        async for part in request.stream():
            length+=len(part)
            if length>2300000:raise HTTPException(413,'设置内容过大')
            chunks.append(part)
        try:changes=validate_update(json.loads(b''.join(chunks)))
        except (ValueError,TypeError) as exc:raise HTTPException(400,str(exc))
        with get_db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('SELECT value_json FROM app_preferences WHERE preference_key=?',(KEY,)).fetchone()
            value={**DEFAULTS,**(json.loads(row[0]) if row else {}),**changes}
            conn.execute('INSERT INTO app_preferences(preference_key,value_json,updated_at) VALUES(?,?,?) ON CONFLICT(preference_key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at',
                (KEY,json.dumps(value,ensure_ascii=False),datetime.datetime.now().isoformat()))
            conn.commit()
        return value

    @app.get('/api/appearance/logo')
    def read_logo():
        stream=logo_stream(get_appearance(get_db))
        if stream is None:return Response(status_code=404,headers={'Cache-Control':'no-store'})
        return Response(stream.getvalue(),media_type='image/png',headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
