"""Public-distribution-only document branding and customization boundaries.

Copied into the isolated build snapshot. Never imported by the private app.
"""
from __future__ import annotations
import base64
import hashlib
import io
import json
import os
import threading
from pathlib import Path
from fastapi import Body, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from PIL import Image, UnidentifiedImageError

CONTACT_URL = 'https://github.com/liu-zongjin/stella-downloads/issues/new'
MAX_LOGO_BYTES = 2 * 1024 * 1024
_LOCK = threading.RLock()


def profile_path():
    return Path(os.environ['LEGAL_KB_RUNTIME_DIR']) / 'data/public-document-brand.json'


def profile():
    with _LOCK:
        try:
            value = json.loads(profile_path().read_text())
            if not isinstance(value, dict): raise ValueError()
            return {'firm_name': str(value.get('firm_name') or '律师事务所')[:80], 'logo': str(value.get('logo') or '')}
        except (OSError, ValueError, TypeError):
            return {'firm_name': '律师事务所', 'logo': ''}


def public_firm_name():
    return profile()['firm_name']


def decode_logo(value):
    if not isinstance(value, str) or len(value) > MAX_LOGO_BYTES * 4 // 3 + 100:
        raise ValueError('Logo 请控制在 2 MB 以内')
    prefix, separator, encoded = value.partition(',')
    if not separator or prefix not in {'data:image/png;base64','data:image/jpeg;base64','data:image/webp;base64'}:
        raise ValueError('请选择 PNG、JPG 或 WebP 图片')
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > MAX_LOGO_BYTES: raise ValueError('Logo 请控制在 2 MB 以内')
        with Image.open(io.BytesIO(raw)) as image:
            if image.width * image.height > 16_000_000: raise ValueError('图片尺寸过大')
            image.load()
            output = io.BytesIO()
            # Re-encode pixels only; uploaded EXIF and ancillary metadata are not retained.
            image.convert('RGBA').save(output, format='PNG')
            return output.getvalue()
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ValueError('图片无法读取') from exc


def save_profile(payload):
    if not isinstance(payload, dict): raise ValueError('设置格式不正确')
    name = payload.get('firm_name', '律师事务所')
    if not isinstance(name, str) or len(name.strip()) > 80 or any(ord(c) < 32 for c in name):
        raise ValueError('律所名称请控制在 80 字以内')
    value = {'firm_name': name.strip() or '律师事务所', 'logo': ''}
    if payload.get('logo'):
        raw = decode_logo(payload['logo'])
        value['logo'] = 'data:image/png;base64,' + base64.b64encode(raw).decode()
    with _LOCK:
        path = profile_path(); path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp'); temporary.write_text(json.dumps(value, ensure_ascii=False))
        os.replace(temporary, path)
    return value


def document_logo_bytes():
    value = profile()['logo']
    return base64.b64decode(value.partition(',')[2]) if value else None


def add_public_firm_logo(doc):
    raw = document_logo_bytes()
    if not raw: return
    from docx.shared import Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    with Image.open(io.BytesIO(raw)) as image:
        width = min(4.8, .75 * image.width / image.height)
    paragraph = doc.add_paragraph(); paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.add_run().add_picture(io.BytesIO(raw), width=Inches(width))
    paragraph.paragraph_format.space_after = Inches(.12)


def public_docx_logo(raw):
    """Add the selected firm logo to non-letter exports, preserving their standard titles."""
    from docx import Document
    from docx.oxml import OxmlElement
    if not document_logo_bytes(): return raw
    doc = Document(io.BytesIO(raw))
    add_public_firm_logo(doc)
    last = doc.paragraphs[-1]._p
    doc._element.body.insert(0, last)
    out = io.BytesIO();doc.save(out);return out.getvalue()


def register_public_edition(app, frontend_dir):
    @app.middleware('http')
    async def customization_boundary(request, call_next):
        if request.url.path.startswith(('/api/mingsi-chapters', '/api/mingsi-meetings', '/api/scanner-inbox')):
            return JSONResponse({'detail':'此功能需定制化开发，详情请联系作者。', 'code':'customization_required','contact_url':CONTACT_URL},status_code=501)
        return await call_next(request)

    @app.get('/api/public-edition/document-brand')
    def get_document_brand():
        return profile()

    @app.put('/api/public-edition/document-brand')
    def put_document_brand(payload: dict = Body(...)):
        try: return save_profile(payload)
        except ValueError as exc: raise HTTPException(400, str(exc))

    @app.get('/public-firm-logo.png')
    def logo_image():
        raw = document_logo_bytes()
        if not raw:
            out=io.BytesIO();Image.new('RGBA',(1,1),(0,0,0,0)).save(out,format='PNG');raw=out.getvalue()
        return Response(raw,media_type='image/png',headers={'Cache-Control':'no-store'})

    @app.get('/scanner-inbox')
    @app.get('/public-customization')
    def customization_page():
        return HTMLResponse((frontend_dir/'public-customization.html').read_text(),headers={'Cache-Control':'no-store'})
