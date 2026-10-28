"""Selected-model visual document reading. Page rendering is local, never OCR."""
from __future__ import annotations
import asyncio
import base64
import io
from pathlib import Path
from fastapi import HTTPException

VISUAL_SUFFIXES = {'.pdf', '.png', '.jpg', '.jpeg', '.webp', '.gif'}


def profile(path, question=''):
    """Cheap local inspection; use native PDF text before allocating image work."""
    import re
    if Path(path).suffix.lower() != '.pdf':
        return {'text': '', 'visual_pages': list(range(page_count(path)))}
    import fitz
    force_visual = bool(re.search(r'图像|图片|图表|印章|签名|手写|版式|布局|涂改|真伪|骑缝|视觉', question))
    texts, visual = [], []
    with fitz.open(path) as document:
        for index, page in enumerate(document):
            text = page.get_text(sort=True) or ''
            if text.strip():
                texts.append(f'【第 {index + 1} 页】\n{text}')
            pictures = page.get_images()
            # Large non-text graphics can carry tables even when a caption has
            # a text layer. Small logos/decorations do not trigger visual work.
            picture_area = sum(rect.get_area() for item in pictures for rect in page.get_image_rects(item[0]))
            scanned = len(text.strip()) < 50 and (bool(pictures) or bool(page.get_drawings()))
            graphic_content = len(text.strip()) < 300 and picture_area > page.rect.get_area() * .25
            if scanned or graphic_content or (force_visual and (pictures or page.get_drawings())):
                visual.append(index)
    return {'text': '\n\n'.join(texts), 'visual_pages': visual}


def page_count(path):
    if Path(path).suffix.lower() == '.pdf':
        import fitz
        with fitz.open(path) as document:
            return len(document)
    from PIL import Image
    with Image.open(path) as image:
        return getattr(image, 'n_frames', 1)


def render_page(path, page):
    from PIL import Image, ImageOps
    if Path(path).suffix.lower() == '.pdf':
        import fitz
        with fitz.open(path) as document:
            item = document[page]
            scale = min(3.0, 2200 / max(item.rect.width, item.rect.height))
            pixmap = item.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            image = Image.open(io.BytesIO(pixmap.tobytes('png')))
    else:
        with Image.open(path) as source:
            source.seek(page)
            image = ImageOps.exif_transpose(source).convert('RGB')
    try:
        image.thumbnail((2200, 2200))
        buffer = io.BytesIO()
        image.convert('RGB').save(buffer, format='JPEG', quality=92)
        return 'data:image/jpeg;base64,' + base64.b64encode(buffer.getvalue()).decode('ascii')
    finally:
        image.close()


async def answer(question, rows, files, model, skill, call_ai, extra='', progress=None, repeat_text=False):
    from . import ai_input, ai_context
    from .case_files import _file_question_messages, _answer_complete_files
    loop = asyncio.get_running_loop()
    pages, fingerprints = [], {}
    native_rows = list(rows)
    for item in files:
        path = Path(item['path'])
        stat = path.stat(); fingerprints[str(path)] = (stat.st_size, stat.st_mtime_ns)
        inspection = ({'text': '', 'visual_pages': item['visual_pages']} if 'visual_pages' in item
                      else await loop.run_in_executor(None, profile, path, question))
        if inspection['text']:
            from .case_files import _located_chunks
            native_rows.extend({'relative_path': item.get('relative_path', item['name']), 'display_name': item['name'],
                                'chunk_index': index, 'chunk_text': text, 'locator': locator}
                               for index, (text, locator) in enumerate(_located_chunks(inspection['text'])))
        for index in inspection['visual_pages']:
            pages.append({**item, 'page': index, 'chunk_index': index,
                          'relative_path': item.get('relative_path', item['name']),
                          'display_name': item['name'], 'locator': f'第 {index + 1} 页（直接视觉分析）',
                          'chunk_text': '', 'vision': True})
    rows = native_rows
    if not pages:
        if not rows:
            raise HTTPException(400, '所选文件没有可读取的文字或视觉页面')
        return await _answer_complete_files(question, rows, model, skill, call_ai, extra, progress)
    ceiling = ai_context.model_budget(model) - 9000
    scope = ai_input.SCOPE.get() or {}
    usage = scope.get('usage')
    # Check a lower bound before the first paid read. Never start hundreds of
    # pages only to spend the whole request budget and leave an incomplete job.
    if usage:
        import math
        base_cost = ai_input.size(_file_question_messages(question, [], [], False, skill))
        capacity = max(1, (ceiling - base_cost) // 4200)
        reads = math.ceil(len(pages) / capacity)
        remaining = usage['limit'] - usage['model_requests'] - 2
        if reads + int(reads > 1) > remaining:
            raise HTTPException(413, '完整读取这些扫描页所需调用超过本轮预算，尚未发送图像。请分组提问或选择容量更大的模型；系统不会只读部分页面后假称已读完。')
    # Textual files stay complete too. If they alone exceed a request, read them
    # first through the same complete batching path and label the resulting notes.
    text_messages = _file_question_messages(question, rows, rows, False, skill, extra)
    if ai_input.size(text_messages) + 4096 > ceiling and rows:
        notes, _, _, rows, _ = await _answer_complete_files(question, rows, model, skill, call_ai, extra, progress)
        text_messages = [{'role': 'system', 'content': skill},
                         {'role': 'user', 'content': f'任务：{question}\n以下为已完整分批阅读文字文件的分析：\n{notes}\n{extra}'}]
    all_rows = [*rows, *pages]
    for index, page in enumerate(pages, len(rows) + 1):
        page['_file_index'] = index
    current, encoded_size, answers, actual = [], 0, [], model
    later_messages = _file_question_messages(question, [], [], False, skill) if not repeat_text else text_messages
    async def flush(blocks):
        nonlocal actual
        if progress:
            progress(f'所选模型正在直接分析扫描原页（第 {len(answers) + 1} 批）')
        messages = [dict(message) for message in (text_messages if repeat_text or not answers else later_messages)]
        messages[0]['content'] += ('\n本次直接提供全部选定视觉页面，未经过 OCR。严格按真实文件名、页码和 [FILE:n] 引用。'
                                  '先完整阅读每页再处理任务，保留表格对应关系、数值、否定与例外。看不清的内容标明页码和无法辨认，禁止猜读。'
                                  '必须同时核对本批所附的全部文字原文，记录与问题相关的事实、数值、条件及例外，供最终合并。'
                                  '多批时只分析当前批，不把本批未出现的信息说成整份文件没有；前批文字不重复发送，最终结合各批分析作答。')
        messages.append({'role': 'user', 'content': blocks})
        value, _, actual = await call_ai(model, messages)
        answers.append(value)
    for page in pages:
        path = Path(page['path']); stat = path.stat()
        if fingerprints[str(path)] != (stat.st_size, stat.st_mtime_ns):
            raise HTTPException(409, '文件在读取期间已修改，请重新发送问题')
        url = await loop.run_in_executor(None, render_page, path, page['page'])
        label = f"[FILE:{page['_file_index']}] 《{page['name']}》第 {page['page'] + 1} 页，以下图像为原页。"
        blocks = [{'type': 'text', 'text': label}, {'type': 'image_url', 'image_url': {'url': url, 'detail': 'high'}}]
        if current and (encoded_size + len(url) > 24 * 1024 * 1024
                        or ai_input.size(text_messages if repeat_text or not answers else later_messages) + ((len(current) // 2) + 1) * 4200 > ceiling):
            await flush(current)
            current, encoded_size = [], 0
        current.extend(blocks); encoded_size += len(url)
    if current:
        await flush(current)
    answer_text = '\n\n'.join(answers)
    if len(answers) > 1:
        synthesis = [{'role': 'system', 'content': skill + '\n以下各批均已实际读取视觉页面。按当前任务合并，保留不同文件、各页重要事实、差异与 [FILE:n] 页码引用；不得添加新事实。'},
                     {'role': 'user', 'content': f'任务：{question}\n\n逐批分析：\n{answer_text}'}]
        if ai_input.size(synthesis) <= ceiling:
            answer_text, _, actual = await call_ai(model, synthesis)
        else:
            answer_text = '已完整读取全部视觉页面；以下为逐批分析，尚未形成跨批次统一结论。\n\n' + answer_text
    return answer_text, '', actual, all_rows, len(answers)
