"""Pre-case material selection and AI suggestions; no case or party writes."""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path

from fastapi import HTTPException, Request

from .case_automation import validate_case_folder
from .case_files import (_answer_complete_files, _located_chunks, _parse_ai_file,
                         _plain_text, _resolve_inside, _run_in_thread, SUPPORTED_AI_SUFFIXES)
from .ai_config import effective_purpose_model
from .ai_capabilities import resolve_image_input
from .file_vision import VISUAL_SUFFIXES, profile as visual_profile
from .platform_files import has_picker, run as run_desktop

_SESSIONS = {}
_MAX_FILES = 100


def _session(token):
    now = time.monotonic()
    for key, value in list(_SESSIONS.items()):
        if now - value[1] > 12 * 3600:
            _SESSIONS.pop(key, None)
    entry = _SESSIONS.get(str(token or ''))
    if not entry:
        raise HTTPException(404, '文件夹选择已失效，请重新选择')
    root, _ = entry
    validate_case_folder(str(root))
    return root


def _files(root):
    items = []
    for current, dirs, names in os.walk(root, followlinks=False):
        folder = Path(current)
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and not (folder / d).is_symlink())
        for name in sorted(names):
            path = folder / name
            if name.startswith('.') or path.is_symlink() or path.suffix.lower() not in SUPPORTED_AI_SUFFIXES:
                continue
            if path.is_file():
                items.append(path.relative_to(root).as_posix())
                if len(items) > 1000:
                    raise HTTPException(413, '文件夹中可识别文件超过 1000 个，请选择更具体的文件夹')
    return items


def _parse_result(answer):
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', str(answer or '').strip(), flags=re.I)
    try:
        data = json.loads(text)
    except ValueError:
        start, end = text.find('{'), text.rfind('}')
        try:
            data = json.loads(text[start:end + 1]) if start >= 0 and end > start else None
        except ValueError:
            data = None
    if not isinstance(data, dict):
        raise HTTPException(502, 'AI 未返回完整的识别结果，请重试或改用手动立案')
    return data


def _split_case_numbers(value):
    """Split a legacy combined case-number value into one number per entry.

    New recognition returns a structured list; this guards older prompts and
    models that still put several numbers into one string. A value is only
    split when every resulting part contains a number marker, so genuine
    single numbers with punctuation stay intact.
    """
    text = str(value or '').strip()
    if not text:
        return []
    found = re.findall(r'[（(]\s*\d{4}\s*[）)][^、，,;；\n]{0,80}?号', text)
    if len(found) >= 2:
        rest = text
        for part in found:
            rest = rest.replace(part, '', 1)
        if not re.sub(r'[\s、，,;；。]', '', rest):
            return [part.strip() for part in found]
    parts = [part.strip() for part in re.split(r'[、，,;；\n]+', text) if part.strip()]
    if len(parts) >= 2 and all('号' in part for part in parts):
        return parts
    return [text]


def register_case_intake_routes(app, *, parse_file, call_ai, require_management):
    @app.post('/api/case-manager/intake/folder')
    def select_folder(request: Request):
        require_management(request)
        if not has_picker():
            raise HTTPException(501, '当前系统不支持文件夹选择')
        result = run_desktop(['osascript', '-e', 'POSIX path of (choose folder with prompt "选择案件文件夹")'],
                             text=True, capture_output=True, timeout=120)
        if result.returncode:
            if '-128' in result.stderr:
                return {'cancelled': True}
            raise HTTPException(500, result.stderr.strip() or '选择文件夹失败')
        root, _ = validate_case_folder(result.stdout.strip())
        token = uuid.uuid4().hex
        if len(_SESSIONS) >= 100:
            _SESSIONS.pop(min(_SESSIONS, key=lambda key: _SESSIONS[key][1]), None)
        _SESSIONS[token] = (root, time.monotonic())
        return {'session': token, 'folder_path': str(root), 'files': _files(root)}

    @app.post('/api/case-manager/intake/recognize')
    async def recognize(request: Request):
        require_management(request)
        body = await request.json()
        root = _session(body.get('session'))
        paths = body.get('paths')
        if not isinstance(paths, list) or not paths:
            raise HTTPException(400, '请选择案件材料')
        if len(paths) > _MAX_FILES:
            raise HTTPException(400, f'一次最多识别 {_MAX_FILES} 个文件，请缩小选择范围')
        allowed = set(_files(root))
        if any(not isinstance(p, str) or p not in allowed for p in paths):
            raise HTTPException(400, '所选文件已变更或不在案件文件夹中，请重新选择')
        selected_model = effective_purpose_model('case_intake')
        selected = [(relative, _resolve_inside(root, relative, allow_root=False)) for relative in dict.fromkeys(paths)]
        inspections, fingerprints = {}, {}
        for relative, path in selected:
            stat = path.stat()
            if stat.st_size > 100 * 1024 * 1024:
                raise HTTPException(413, f'文件超过 100 MB：{relative}')
            fingerprints[relative] = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
            if path.suffix.lower() == '.pdf':
                inspections[relative] = await _run_in_thread(visual_profile, path, '')
        needs_vision = any(path.suffix.lower() in VISUAL_SUFFIXES and
                           (path.suffix.lower() != '.pdf' or inspections[relative].get('visual_pages'))
                           for relative, path in selected)
        can_see = await resolve_image_input(selected_model) if needs_vision else False
        rows, visual_files, needs_ocr, source_texts, visual_pages, text_modes = [], [], [], {}, {}, {}
        for relative, path in selected:
            native_pdf = path.suffix.lower() == '.pdf' and not inspections[relative].get('visual_pages')
            text_modes[relative] = 'text'
            if native_pdf or (can_see and path.suffix.lower() in VISUAL_SUFFIXES):
                inspection = inspections.get(relative) or await _run_in_thread(visual_profile, path, '')
                content = _plain_text(str(inspection.get('text') or ''))
                pages = inspection.get('visual_pages') or []
                if pages:
                    visual_files.append({'name': relative, 'path': path, 'relative_path': relative, 'visual_pages': pages})
                    visual_pages[relative] = {page + 1 for page in pages}
            else:
                parsed = await _parse_ai_file(parse_file, path, body.get('allow_cloud_ocr') is True)
                if parsed.get('needs_ocr'):
                    needs_ocr.append(relative)
                    continue
                content = _plain_text(str(parsed.get('content') or ''))
                if parsed.get('ocr_used'):
                    text_modes[relative] = 'ocr'
                pages = []
            source_texts[relative] = re.sub(r'\s+', '', content)
            chunks = _located_chunks(content)
            if not chunks and not pages:
                raise HTTPException(400, f'文件无法提取文字：{relative}')
            rows.extend({'relative_path': relative, 'display_name': relative, 'chunk_index': i,
                         'chunk_text': text, 'locator': locator} for i, (text, locator) in enumerate(chunks))
        if needs_ocr:
            return {'consent_required': needs_ocr}
        question = '''完整阅读材料，提取用于新建案件的信息，只依据材料，不猜测。返回一个完整 JSON 对象，不要 Markdown：
{"parties":[{"name":"名称","role":"材料中的诉讼地位或空","type":"单位或个人","file":"材料相对路径","page":1,"source":"原文逐字摘录"}],
 "case_numbers":[{"case_no":"完整案号","court":"受理机构，不确定时为空","number_type":"一审/二审/再审/执行/仲裁等，不确定时为空","file":"材料相对路径","page":1,"source":"原文逐字摘录"}],
 "questions":[{"field":"case_type/current_stage/court_contact/party_contact/memo 中之一","question":"根据材料提出的确认问题","value":"材料支持的候选值","file":"材料相对路径","page":1,"source":"原文逐字摘录"}]}。
file 必须是所选材料的完整相对路径，source 必须是该文件中连续的原文逐字摘录。
视觉页面必须准确提供 page 页码，文字文件没有页码时 page 可以为空。识别不清的内容不得猜测。
当事人仅列确实出现的主体，不判断委托关系。案号一律放入 case_numbers：识别到几个案号就输出几条，每条只写一个完整案号，禁止把多个案号合并进一个字符串或一条记录；受理机构和审级能对应时逐条填写。每个非空字段最多一题（案号除外），缺少依据的字段不要出题。联系方式仅在有明确原文时提出，不要推断。'''
        from . import ai_context, ai_input
        context_token = ai_context.CURRENT.set(None)
        input_token = ai_input.SCOPE.set(ai_input.new_scope(question))
        try:
            answer, _, model, _, _ = await _answer_complete_files(question, rows, selected_model, '', call_ai, visual_files=visual_files, visual_repeat_text=False)
        finally:
            ai_input.SCOPE.reset(input_token)
            ai_context.CURRENT.reset(context_token)
        for relative, path in selected:
            try:
                stat = path.stat()
                unchanged = fingerprints[relative] == (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
            except OSError:
                unchanged = False
            if not unchanged:
                raise HTTPException(409, f'材料在识别期间发生变化，请重新识别：{relative}')
        data = _parse_result(answer)
        parties = data.get('parties') if isinstance(data.get('parties'), list) else []
        questions = data.get('questions') if isinstance(data.get('questions'), list) else []
        suggested_numbers = data.get('case_numbers') if isinstance(data.get('case_numbers'), list) else []
        fields = {'case_type', 'current_stage', 'case_no', 'court', 'court_contact', 'party_contact', 'memo'}
        def evidence(item):
            file = str(item.get('file') or '').strip()
            quote = re.sub(r'\s+', '', str(item.get('source') or ''))
            if file not in source_texts or len(quote) < 2:
                return None
            if quote in source_texts[file]:
                return {'mode': text_modes[file], 'file': file, 'quote': quote}
            try:
                page = int(item.get('page'))
            except (TypeError, ValueError, OverflowError):
                return None
            if page not in visual_pages.get(file, set()):
                return None
            return {'mode': 'vision', 'file': file, 'quote': quote, 'page': page}

        def source_label(item, proof):
            suffix = (f"第 {proof['page']} 页，模型视觉识别，请核对原件" if proof['mode'] == 'vision'
                      else ('OCR识别文字，请核对原件' if proof['mode'] == 'ocr' else '文字层核对'))
            return f"{proof['file']}（{suffix}）：{str(item['source']).strip()}"[:700]

        def reference(proof):
            return proof['quote'] if proof['mode'] == 'vision' else source_texts[proof['file']]

        clean_numbers = []
        seen_numbers = set()
        def add_number(item, proof, case_no, court='', number_type=''):
            case_no = str(case_no or '').strip()
            key = re.sub(r'\s+', '', case_no)
            if not key or key in seen_numbers:
                return
            seen_numbers.add(key)
            clean_numbers.append({'case_no': case_no[:200], 'court': str(court or '').strip()[:200],
                                  'number_type': str(number_type or '').strip()[:50],
                                  'source': source_label(item, proof), 'source_mode': proof['mode']})

        for item in suggested_numbers[:50]:
            if not isinstance(item, dict):
                continue
            case_no = str(item.get('case_no') or '').strip()
            proof = evidence(item)
            if not case_no or not proof or re.sub(r'\s+', '', case_no) not in reference(proof):
                continue
            add_number(item, proof, case_no, item.get('court'), item.get('number_type'))

        seen = set()
        clean_questions = []
        pending_numbers = []
        pending_court = None
        for item in questions:
            if not isinstance(item, dict):
                continue
            field = str(item.get('field') or '')
            value, source = str(item.get('value') or '').strip(), str(item.get('source') or '').strip()
            proof = evidence(item)
            if field not in fields or field in seen or not value or not source or not proof:
                continue
            if field == 'case_no':
                parts = _split_case_numbers(value)
                if not all(re.sub(r'\s+', '', part) in reference(proof) for part in parts):
                    continue
                seen.add(field)
                pending_numbers.append((item, proof, parts))
                continue
            if field == 'court':
                seen.add(field)
                pending_court = (item, proof)
                continue
            seen.add(field)
            clean_questions.append({'field': field, 'question': str(item.get('question') or field)[:300],
                                    'value': value[:2000], 'source': source_label(item, proof), 'source_mode': proof['mode']})
        total_parts = sum(len(parts) for _, _, parts in pending_numbers)
        for item, proof, parts in pending_numbers:
            for part in parts:
                court = str(pending_court[0].get('value') or '').strip() if total_parts == 1 and pending_court else ''
                add_number(item, proof, part, court, item.get('number_type'))
        # A court suggestion that cannot be tied to one number is dropped rather
        # than becoming a number-less row; the new prompt asks for court per number.
        if pending_court:
            court_value = str(pending_court[0].get('value') or '').strip()
            if len(clean_numbers) == 1 and not clean_numbers[0]['court'] and court_value:
                clean_numbers[0]['court'] = court_value[:200]
            elif not clean_numbers:
                item, proof = pending_court
                clean_questions.append({'field': 'court', 'question': str(item.get('question') or '受理机构')[:300],
                                        'value': court_value[:2000], 'source': source_label(item, proof),
                                        'source_mode': proof['mode']})
        clean_parties = []
        for item in parties[:50]:
            if not isinstance(item, dict) or not str(item.get('name') or '').strip():
                continue
            proof = evidence(item)
            if not proof or re.sub(r'\s+', '', str(item['name'])) not in (proof['quote'] if proof['mode'] == 'vision' else source_texts[proof['file']]):
                continue
            party = {k: str(item.get(k) or '').strip()[:500] for k in ('name', 'role', 'type')}
            party['source'] = source_label(item, proof)
            party['source_mode'] = proof['mode']
            clean_parties.append(party)
        return {'parties': clean_parties, 'case_numbers': clean_numbers, 'questions': clean_questions,
                'model': model, 'files': list(dict.fromkeys(paths))}
