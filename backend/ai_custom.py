"""Private, runtime-only OpenAI-compatible provider records."""
import json
import os
import re
import tempfile
import threading
import uuid
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit

PATH=Path(os.environ.get('LEGAL_KB_CONFIG_DIR',str(Path(__file__).resolve().parent.parent)))/'local_ai_custom_providers.json'
LOCK=threading.RLock()


def ensure_same_origin(request):
    from fastapi import HTTPException
    if request.headers.get('origin') not in (None,str(request.base_url).rstrip('/')):
        raise HTTPException(403,'请从 Stella AI API 管理页面操作')


def providers():
    if not PATH.exists():return []
    value=json.loads(PATH.read_text())
    if not isinstance(value,list):raise ValueError('自定义 API 配置无法读取')
    return value


def find(identifier):return next((item for item in providers() if item['id']==identifier),None)


def resolve(model):
    identifier,sep,name=str(model).partition(':')
    if not identifier.startswith('custom_'):return None
    provider=find(identifier)
    if not provider or name not in provider['models']:raise ValueError('自定义模型不存在，请在 AI API 管理中重新选择')
    return provider['api_url'],provider['api_key'],name


def is_responses(model):
    identifier=str(model).partition(':')[0]
    if not identifier.startswith('custom_'):return False
    provider=find(identifier)
    return bool(provider and provider['protocol']=='responses')


def chat_options(model,max_tokens,temperature):
    """Reasoning APIs may reject sampling controls or reserve tiny budgets for thought."""
    real=str(model).partition(':')[2]
    if real.startswith(('kimi-','o1','o3','o4','gpt-5','gpt-6')):
        result={'max_completion_tokens':max_tokens} if real.startswith(('o1','o3','o4','gpt-5','gpt-6')) else {'max_tokens':max_tokens,'thinking':{'type':'disabled'}}
        if real.startswith('kimi-'):result['temperature']=1.0
        return result
    return {'max_tokens':max_tokens,'temperature':temperature}


def save(value,identifier=None):
    if not isinstance(value,dict) or any(key not in {'name','api_url','api_key','clear_key','protocol','models'} for key in value):raise ValueError('API 配置格式不正确')
    with LOCK:
        items=providers();existing=next((item for item in items if item['id']==identifier),None)
        if identifier and not existing:raise ValueError('未找到该自定义 API')
        if not existing and len(items)>=20:raise ValueError('最多添加 20 个自定义 API')
        record={**(existing or {}),**value,'id':identifier or 'custom_'+uuid.uuid4().hex[:16]}
        name=record.get('name','');protocol=record.get('protocol','chat')
        if not isinstance(name,str) or not name.strip() or len(name)>60:raise ValueError('请填写服务名称（最多 60 字）')
        url=urlsplit(str(record.get('api_url','')).strip())
        if url.scheme!='https' or not url.hostname or url.username or url.password or url.query or url.fragment:raise ValueError('请填写不含密钥或查询参数的 HTTPS API 地址')
        if protocol not in ('chat','responses'):raise ValueError('不支持的 API 协议')
        api_path=url.path.rstrip('/')
        suffix='/responses' if protocol=='responses' else '/chat/completions'
        for existing_suffix in ('/responses','/chat/completions'):
            if api_path.endswith(existing_suffix):
                api_path=api_path[:-len(existing_suffix)];break
        api_path+=suffix
        record['api_url']=urlunsplit((url.scheme,url.netloc,api_path,'',''));record['name']=name.strip();record['protocol']=protocol
        models=record.get('models')
        if not isinstance(models,list) or not 1<=len(models)<=50 or any(not isinstance(m,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}',m) for m in models):raise ValueError('请填写 1–50 个有效模型 ID（每行一个）')
        record['models']=list(dict.fromkeys(models))
        key=record.get('api_key','')
        if not isinstance(key,str) or len(key)>4096 or any(ord(c)<33 for c in key):raise ValueError('API 密钥格式不正确')
        record['api_key']=key or (existing['api_key'] if existing else '')
        if record.pop('clear_key',False):record['api_key']=''
        if not existing:items.append(record)
        else:items=[record if item['id']==identifier else item for item in items]
        _write(items)
    return record


def remove(identifier):
    with LOCK:_write([item for item in providers() if item['id']!=identifier])


def _write(items):
    PATH.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.local_ai_custom.',dir=str(PATH.parent))
    try:
        with os.fdopen(fd,'w') as file:json.dump(items,file,ensure_ascii=False,indent=2);file.flush();os.fsync(file.fileno())
        os.chmod(name,0o600);os.replace(name,PATH)
    finally:
        if os.path.exists(name):os.unlink(name)
