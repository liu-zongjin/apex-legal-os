"""Model + transport capabilities, with explicit custom and provider metadata."""
import hashlib
import re
import time
from urllib.parse import urlsplit, urlunsplit

from . import ai_config, ai_custom

_DISCOVERED = {}


def image_input(model):
    model = ai_config.canonical_model_id(model)
    provider, _, name = model.partition(':')
    if provider.startswith('custom_'):
        item = ai_custom.find(provider)
        if item and name in item.get('vision_models', []):
            return True
    name = (name or model).lower()
    # Verified provider/model interfaces, not a blanket “all new models” guess.
    if model == 'deepseek-flash':
        return True
    if provider == 'cc2api':
        return name.startswith(('claude-sonnet-', 'claude-opus-', 'claude-haiku-'))
    if provider == 'doubao' and re.match(r'doubao-seed-2[.-][01]', name):
        return True
    if re.search(r'(?:^|/)(?:pro/)?(?:kimi-k2\.[56]|qwen[^/]*-vl|glm-4\.[15]v)', name, re.I):
        return True
    if provider.startswith('custom_'):
        item = ai_custom.find(provider)
        host = urlsplit(item['api_url']).hostname if item else ''
        if host == 'api.openai.com' and re.match(r'gpt-(?:4o|4\.1|5(?:[.-]|$)|6(?:[.-]|$))', name):
            return True
        if host in {'api.moonshot.cn', 'api.moonshot.ai', 'api.kimi.ai'} and name in {'kimi-k2.5', 'kimi-k2.6'}:
            return True
    return False


async def resolve_image_input(model):
    if image_input(model):
        return True
    # Compatible gateways can advertise a capability even for unknown/new model
    # IDs. Probe metadata only, never send a paid image or business material.
    from .ai_client import api_config
    from .ai_transport import ai_http_client
    import httpx
    try:
        url, key, real = api_config(model)
        if not key or model.startswith('cc2api:'):
            return False
        revision = hashlib.sha256((url + '\0' + key + '\0' + real).encode()).hexdigest()
        cached = _DISCOVERED.get(revision)
        if cached and time.monotonic() - cached[0] < 900:
            return cached[1]
        parsed = urlsplit(url)
        path = re.sub(r'/(?:chat/completions|responses|messages)$', '', parsed.path.rstrip('/')) + '/models'
        async with ai_http_client(timeout=httpx.Timeout(4.0)) as client:
            response = await client.get(urlunsplit((parsed.scheme, parsed.netloc, path, '', '')),
                                        headers={'Authorization': 'Bearer ' + key})
        supported = False
        if response.status_code == 200:
            data = response.json()
            for item in data.get('data', []) if isinstance(data, dict) else []:
                if not isinstance(item, dict) or item.get('id') != real:
                    continue
                architecture = item.get('architecture') or {}
                inputs = item.get('input_modalities') or architecture.get('input_modalities') or []
                modalities = item.get('modalities') or {}
                if isinstance(modalities, dict):
                    inputs = modalities.get('input') or inputs
                supported = 'image' in inputs or (item.get('capabilities') or {}).get('vision') is True
        if len(_DISCOVERED) >= 128:
            _DISCOVERED.clear()
        _DISCOVERED[revision] = (time.monotonic(), supported)
        return supported
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        return False
