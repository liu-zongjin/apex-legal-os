"""Pure text-format transformations shared by series table write paths."""
from copy import deepcopy


def remap_text_format(previous, current, format_data):
    """Retain unaffected runs around an edit; offsets match browser UTF-16 units."""
    result = deepcopy(format_data or {})
    old = list(previous.encode('utf-16-le', errors='surrogatepass'))
    new = list(current.encode('utf-16-le', errors='surrogatepass'))
    old = [tuple(old[i:i + 2]) for i in range(0, len(old), 2)]
    new = [tuple(new[i:i + 2]) for i in range(0, len(new), 2)]
    left = 0
    while left < min(len(old), len(new)) and old[left] == new[left]:
        left += 1
    right = 0
    while right < min(len(old), len(new)) - left and old[-right - 1] == new[-right - 1]:
        right += 1
    old_end, new_end = len(old) - right, len(new) - right
    return _map_interval(result, len(old), left, old_end, new_end - left)


def _map_interval(format_data, length, left, old_end, inserted_length):
    result = deepcopy(format_data)
    delta = inserted_length - (old_end - left)
    new_end = left + inserted_length
    runs = []
    for run in result.pop('runs', []):
        start, end = max(0, run['start']), min(length, run['end'])
        pieces = []
        if start < left:
            pieces.append((start, min(end, left)))
        if new_end > left and start <= left and end >= old_end and (old_end > left or start < left or not length):
            pieces.append((left, new_end))
        if end > old_end:
            pieces.append((max(start, old_end) + delta, end + delta))
        for a, b in pieces:
            if b > a:
                style = {key: value for key, value in run.items() if key not in ('start', 'end')}
                if runs and runs[-1]['end'] == a and {key: value for key, value in runs[-1].items() if key not in ('start', 'end')} == style:
                    runs[-1]['end'] = b
                else:
                    runs.append({'start': a, 'end': b, **style})
    if runs:
        result['runs'] = runs
    return result


def remap_format_edits(previous, current, format_data, edits):
    """Apply known non-overlapping UTF-16 edits without losing styles between edits."""
    if not isinstance(edits, list) or len(edits) > 1000:
        raise ValueError('替换次数过多，请缩小范围')
    data = previous.encode('utf-16-le')
    length = len(data) // 2
    boundary = length
    result = deepcopy(format_data or {})
    if any(not isinstance(edit, dict) or type(edit.get('start')) is not int for edit in edits):
        raise ValueError('替换位置无效')
    for edit in sorted(edits, key=lambda item: item['start'], reverse=True):
        if not isinstance(edit, dict):
            raise ValueError('替换位置无效')
        start, end, text = edit.get('start'), edit.get('end'), edit.get('text')
        if type(start) is not int or type(end) is not int or not 0 <= start <= end <= boundary or not isinstance(text, str):
            raise ValueError('替换位置无效或重叠')
        inserted = text.encode('utf-16-le')
        result = _map_interval(result, length, start, end, len(inserted) // 2)
        data = data[:start * 2] + inserted + data[end * 2:]
        length += len(inserted) // 2 - (end - start)
        boundary = start
    if data.decode('utf-16-le') != current:
        raise ValueError('替换内容与原文不一致，请刷新后重试')
    return result


def sanitize_table_metadata(raw):
    """Bounded optional view metadata; absent keys never affect existing records."""
    result = {}
    heights = raw.get('row_heights')
    if isinstance(heights, dict):
        cleaned = {}
        for key, value in list(heights.items())[:5000]:
            try:
                if str(key).isdigit() and int(key) > 0:
                    cleaned[str(int(key))] = max(80, min(600, int(value)))
            except (ValueError, TypeError, OverflowError):
                continue
        result['row_heights'] = cleaned
    rules = raw.get('conditional_rules')
    if isinstance(rules, list):
        result['conditional_rules'] = [
            {'key': rule['key'][:200], 'kind': rule['kind'], 'value': str(rule.get('value', ''))[:1000], 'color': rule.get('color') if rule.get('color') in {'red', 'yellow'} else 'yellow'}
            for rule in rules[:200] if isinstance(rule, dict) and isinstance(rule.get('key'), str) and rule.get('kind') in {'contains', 'empty', 'greater', 'less', 'date_before'}
        ]
    views = raw.get('views')
    if isinstance(views, dict):
        cleaned = {}
        for name, view in list(views.items())[:10]:
            if not isinstance(name, str) or not name.strip() or name.strip() in {'__proto__', 'constructor', 'prototype'} or not isinstance(view, dict):
                continue
            columns = []
            for column in (view.get('columns') if isinstance(view.get('columns'), list) else [])[:500]:
                if not isinstance(column, dict) or not isinstance(column.get('key'), str):
                    continue
                try:
                    width = max(80, min(420, int(column.get('width', 160))))
                except (ValueError, TypeError, OverflowError):
                    width = 160
                columns.append({'key': column['key'][:200], 'width': width, 'manual_width': bool(column.get('manual_width')), 'hidden': bool(column.get('hidden'))})
            sorts = [{'key': sort['key'][:200], 'direction': 'desc' if sort.get('direction') == 'desc' else 'asc'} for sort in (view.get('sorts') if isinstance(view.get('sorts'), list) else [])[:10] if isinstance(sort, dict) and isinstance(sort.get('key'), str)]
            filters = {}
            for key, value in list((view.get('filters') if isinstance(view.get('filters'), dict) else {}).items())[:500]:
                if not isinstance(key, str) or not isinstance(value, dict):
                    continue
                filtered = {}
                if isinstance(value.get('values'), list):
                    filtered['values'] = [v[:2000] for v in value['values'][:1000] if isinstance(v, str)]
                condition = value.get('condition')
                if isinstance(condition, dict) and condition.get('kind') in {'empty', 'nonempty', 'number', 'date', 'contains'}:
                    filtered['condition'] = {'kind': condition['kind'], 'min': str(condition.get('min', ''))[:100], 'max': str(condition.get('max', ''))[:100], 'value': str(condition.get('value', ''))[:1000]}
                filters[key[:200]] = filtered
            cleaned[name.strip()[:80]] = {'columns': columns, 'sorts': sorts, 'filters': filters}
        result['views'] = cleaned
    return result


def validate_table_value(value, column):
    """Opt-in validation accepts values without converting identifiers or money."""
    import datetime
    import re
    validation = column.get('validation') or {}
    if not isinstance(validation, dict):
        return
    if not value:
        if validation.get('required'):
            raise ValueError('此列不允许空白')
        return
    kind = validation.get('type')
    if kind in {'number', 'amount'} and not re.fullmatch(r'[+-]?\d+(?:\.\d+)?', value.replace(',', '')):
        raise ValueError('请输入普通数字，不使用科学计数法或单位文字')
    if kind == 'date':
        try:
            if datetime.date.fromisoformat(value).isoformat() != value:
                raise ValueError()
        except ValueError:
            raise ValueError('日期应为有效的 YYYY-MM-DD')
    if kind == 'choice' and value not in validation.get('values', []):
        raise ValueError('请选择此列允许的候选值')
