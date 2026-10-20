"""Read shipped public answers separately from the recipient's notes and updates."""
from __future__ import annotations
import json


def embedded_answers(page):
    marker = 'const qaData = '
    start = page.find(marker)
    if start < 0:
        raise ValueError('Missing public Fada answer catalog')
    value, _ = json.JSONDecoder().raw_decode(page[start + len(marker):])
    if not isinstance(value, list):
        raise ValueError('Invalid public Fada catalog')
    return value


def batches_from_page(page):
    batches = {}
    for item in embedded_answers(page):
        title = item['batch']
        batch = batches.setdefault(title, {'title': title, 'url': item.get('url', ''),
            'publish_date': item.get('date', ''), 'qa_pairs': []})
        # Never export local notes, case links or any other record fields.
        batch['qa_pairs'].append({'question': item['question'], 'answer': item['answer']})
    return list(batches.values())


def read_batches(data_path, source_path):
    if data_path.is_file():
        data = json.loads(data_path.read_text(encoding='utf-8'))
        return data if isinstance(data, list) else []
    if source_path.is_file():
        return batches_from_page(source_path.read_text(encoding='utf-8'))
    return []


def render_page(page, batches):
    marker = 'const qaData = '
    start = page.find(marker)
    if start < 0:
        raise ValueError('Missing public Fada answer catalog')
    start += len(marker)
    _, length = json.JSONDecoder().raw_decode(page[start:])
    answers = [{'batch': batch.get('title', ''), 'url': batch.get('url', ''),
                'date': batch.get('publish_date', ''), 'question': qa.get('question', ''),
                'answer': qa.get('answer', '')}
               for batch in batches for qa in batch.get('qa_pairs', [])]
    value = json.dumps(answers, ensure_ascii=False).replace('<', '\\u003c')
    return page[:start] + value + page[start + length:]
