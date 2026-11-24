"""Local rules for choosing and comparing normative documents."""
import re
from difflib import SequenceMatcher

_DRAFT = re.compile(r'征求意见稿|修订草案|草案|送审稿')
_COMMENTARY = re.compile(r'培训|课件|pptx?\b|解读|详解|答记者问|案例|裁判要旨|汇编|条文释义|研讨|实务|会议讲话|研究报告|[？?｜|：:]')
_ENDING = re.compile(r'(?:法典|法|条例|解释|规定|办法|规则|细则|批复|决定|指引|意见|公告|通知|纪要)$')
_EDITION = re.compile(r'[（(](?:[一二三四五六七八九十\d]+|\d{4}年?修[正订]|试行|暂行|\d{4}年)[）)]$')
_ARTICLE = re.compile(r'第[一二三四五六七八九十百千零〇两0-9]+条(?:之[一二三四五六七八九十0-9]+)?')


def meeting_minutes_source(title):
    """Match a small set of independently verified official court sources."""
    name = re.sub(r'\s+', '', title or '')
    if _DRAFT.search(name) or _COMMENTARY.search(name):
        return None
    name = re.sub(r'^【(?:九民|八民)(?:会)?纪要】', '', name).strip('《》')
    nine = '全国法院民商事审判工作会议纪要'
    eight = '第八次全国法院民事商事审判工作会议（民事部分）纪要'
    def exact(document):
        return name in {document, f'最高人民法院关于印发《{document}》的通知',
                        f'最高人民法院关于印发{document}的通知'}
    if exact(nine):
        return {'key': 'nine', 'title': '全国法院民商事审判工作会议纪要', 'url': 'https://www.court.gov.cn/zixun/xiangqing/199691.html', 'source': '最高人民法院'}
    if exact(eight):
        return {'key': 'eight', 'title': '第八次全国法院民事商事审判工作会议（民事部分）纪要', 'url': 'https://www.sdcourt.gov.cn/dzdcqfy/391933/392086/1456599/index.html', 'source': '山东法院网'}
    return None


def law_candidate(row):
    if row.get('bbbs'):
        return True
    title = (row.get('title') or '').strip().strip('《》')
    if not title or _DRAFT.search(title) or _COMMENTARY.search(title) or _COMMENTARY.search(row.get('source_filename') or ''):
        return False
    title = _EDITION.sub('', title)
    return bool(_ENDING.search(title) and (
        title.endswith(('法', '法典', '条例', '规定', '办法', '细则', '规则'))
        or re.match(r'^(?:最高人民法院|最高人民检察院|全国人民代表大会|国务院|关于(?:审理|适用|印发|进一步|企业))', title)
        or re.search(r'(?:委员会|人民法院|人民政府|税务局|管理局)', title[:35])
    ))


def strip_printed_contents(text):
    """Remove a front-matter contents list only when every entry is a heading."""
    article = re.search(r'(?m)^ *' + _ARTICLE.pattern, text)
    marker = re.search(r'(?m)^\s*目[ \t　]*录[ \t　]*$', text[:article.start()] if article else '')
    if not marker:
        return text
    headings = [line.strip() for line in text[marker.end():article.start()].splitlines() if line.strip()]
    if len(headings) >= 2 and all(re.match(r'^第[一二三四五六七八九十百千零〇两0-9]+[编章节部分]', line) for line in headings):
        return text[:marker.start()].rstrip() + '\n' + text[article.start():]
    return text


def law_text_evidence(local, official):
    """Bounded excerpts, grouped by article when both texts have numbered provisions."""
    def sections(text):
        return [segment.strip() for segment in re.split(r'(?m)(?=^\s*' + _ARTICLE.pattern + r')', text) if segment.strip()]

    def compact(text):
        return re.sub(r'\s+', '', text)

    if compact(local) == compact(official):
        return []
    if re.search(r'(?m)^\s*目[ \t　]*录[ \t　]*$', local) or re.search(r'(?m)^\s*目[ \t　]*录[ \t　]*$', official):
        def without_opening_heading(text):
            first = re.search(r'(?m)^ *' + _ARTICLE.pattern, text)
            if not first:
                return text
            intro = re.sub(r'(?m)^ *第[一二三四五六七八九十百千零〇两0-9]+[编章节部分][^\n]*$', '', text[:first.start()])
            return intro + text[first.start():]

        normalized = [strip_printed_contents(text) for text in (local, official)]
        if normalized != [local, official] and compact(without_opening_heading(normalized[0])) == compact(without_opening_heading(normalized[1])):
            return []

    old, new = sections(local), sections(official)
    if len(old) < 2 or len(new) < 2 or max(len(old), len(new)) > 2500:
        old, new = [local], [official]
    changes = []
    for operation, a, b, c, d in SequenceMatcher(None, list(map(compact, old)), list(map(compact, new)), autojunk=False).get_opcodes():
        if operation == 'equal':
            continue
        before, after = ''.join(old[a:b]), ''.join(new[c:d])
        left, right = compact(before), compact(after)
        start = 0
        while start < min(len(left), len(right)) and left[start] == right[start]:
            start += 1
        end = max(0, start - 45)
        changes.append({'local': left[end:start + 160], 'official': right[end:start + 160],
                        'location': (_ARTICLE.match(before or after).group() if _ARTICLE.match(before or after) else '正文片段')})
        if len(changes) == 8:
            break
    return changes


def meeting_minutes_evidence(local, official):
    """Compare numbered meeting points individually when both texts have them."""
    pattern = re.compile(r'(?m)^\s*(\d{1,3})[.．、]')
    def split(text):
        matches = list(pattern.finditer(text))
        numbers = [int(match.group(1)) for match in matches]
        if len(matches) < 3 or numbers != sorted(set(numbers)):
            return None
        result = {0: text[:matches[0].start()]}
        for i, match in enumerate(matches):
            result[numbers[i]] = text[match.start():matches[i + 1].start() if i + 1 < len(matches) else len(text)]
        return result
    old, new = split(local), split(official)
    if old is None or new is None:
        return law_text_evidence(local, official)
    changes = []
    for number in sorted(old.keys() | new.keys()):
        before = re.sub(r'\s+', '', old.get(number, ''))
        after = re.sub(r'\s+', '', new.get(number, ''))
        if before == after:
            continue
        start = 0
        while start < min(len(before), len(after)) and before[start] == after[start]:
            start += 1
        left = max(0, start - 45)
        changes.append({'location': '引言或印发通知' if number == 0 else f'第 {number} 点',
                        'local': before[left:start + 160], 'official': after[left:start + 160]})
        if len(changes) == 8:
            break
    return changes
