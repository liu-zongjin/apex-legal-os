"""Shared, data-free branding for desktop and installed mobile shells."""
import base64
import hashlib
import io
import json
import os
import threading
from pathlib import Path
from PIL import Image, UnidentifiedImageError

_lock = threading.Lock()
MAX_BYTES = 1572864


def brand_settings_path(root):
    # Frozen application resources are read-only; each installation owns its preferences.
    runtime = os.environ.get('LEGAL_KB_RUNTIME_DIR')
    return (Path(runtime) if runtime else Path(root)) / 'data/mobile-brand.json'


def read_brand(root):
    try:
        value = json.loads(brand_settings_path(root).read_text())
        if isinstance(value, dict) and isinstance(value.get('logo'), str) and isinstance(value.get('revision'), str) and isinstance(value.get('configured'), bool):
            if value['logo']:
                decode_logo(value['logo'])
            if value['logo'] or not (Path(root) / 'frontend/distribution-brand.png').is_file():
                return value
    except (OSError, ValueError):
        pass
    default = Path(root) / 'frontend/distribution-brand.png'
    if default.is_file():
        logo = 'data:image/png;base64,' + base64.b64encode(default.read_bytes()).decode()
        decode_logo(logo)
        return {'logo': logo, 'revision': hashlib.sha256(logo.encode()).hexdigest()[:20], 'configured': False}
    return {'logo': '', 'revision': 'stella-20261007', 'configured': False}


def decode_logo(logo):
    if not isinstance(logo, str) or len(logo) > MAX_BYTES * 4 // 3 + 100:
        raise ValueError('图片请控制在 1.5 MB 以内')
    prefix, separator, encoded = logo.partition(',')
    if not separator or prefix not in ('data:image/png;base64', 'data:image/webp;base64'):
        raise ValueError('请选择 PNG 或 WebP 品牌标识')
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > MAX_BYTES:
            raise ValueError('图片过大')
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in ('PNG', 'WEBP') or image.width * image.height > 16000000:
                raise ValueError('图片尺寸或格式不支持')
            image.load()
            rgba = image.convert('RGBA')
            if rgba.getextrema()[3][0] == 255:
                raise ValueError('请使用透明背景品牌标识')
            return rgba
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValueError('图片无法打开') from error


def save_brand(root, logo):
    if logo:
        decode_logo(logo)
    elif logo != '':
        raise ValueError('品牌标识格式不正确')
    revision = hashlib.sha256(logo.encode()).hexdigest()[:20] if logo else 'stella-20261007'
    value = {'logo': logo, 'revision': revision, 'configured': True}
    path = brand_settings_path(root)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(value), encoding='utf-8')
        os.replace(temporary, path)
    return value


def logo_bytes(root):
    brand = read_brand(root)
    if not brand['logo']:
        return (Path(root) / 'frontend/stella-brand.png').read_bytes()
    output = io.BytesIO()
    decode_logo(brand['logo']).save(output, format='PNG')
    return output.getvalue()


def icon_bytes(root, size):
    brand = read_brand(root)
    if brand['logo']:
        source = decode_logo(brand['logo'])
        bounds = source.getbbox()
        if bounds:
            source = source.crop(bounds)
        source.thumbnail((int(size * .8), int(size * .8)), Image.Resampling.LANCZOS)
        canvas = Image.new('RGB', (size, size), 'white')
        canvas.paste(source, ((size-source.width)//2, (size-source.height)//2), source)
    else:
        canvas = Image.open(Path(root) / 'frontend/static/app-icon-1024.png').convert('RGB').resize((size, size), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    canvas.save(output, format='PNG')
    return output.getvalue()
