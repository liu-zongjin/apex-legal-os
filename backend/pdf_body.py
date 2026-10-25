"""Conservative page furniture removal for analysis, never edits original PDFs.

Layout is preferred. Repetition alone never proves a line is a header. OCR
without coordinates drops recognizable mastheads and explicit page labels only.
"""
import math
import re
from collections import Counter


def _key(text):
    return re.sub(r'\s+', '', text).casefold()


def _page_number(text, page, *, located=True):
    value = text.strip()
    # A bare amount at the bottom is not necessarily a page number.
    return (located and value == str(page)) or bool(re.fullmatch(
        r'(?:[-—–]\s*\d{1,4}\s*[-—–]|第\s*\d+\s*页(?:\s*[共/／]\s*\d+\s*页?)?)', value))


def _masthead(text):
    key = _key(text)
    if re.fullmatch(r'[\u4e00-\u9fff·（）()]{2,30}律师事务所', key):
        return 'chinese'
    if re.fullmatch(r"[a-z &.,'’-]{0,60}(?:lawoffices|lawfirm)", key):
        return 'english'
    return None


def clean_pages(pages):
    """Return body text plus excluded lines, preserving page count and body order.

Each page has lines {text, top, bottom} in fractional page coordinates. Missing
coordinates mean OCR text. Exclusions are retained in the parsed audit cache.
"""
    frequency = Counter()
    for page in pages:
        frequency.update({(edge, _key(line['text'])) for line in page for edge in ('top', 'bottom')
                          if line.get('top') is not None and len(line['text']) <= 120
                          and ((edge == 'top' and line['bottom'] <= .12)
                               or (edge == 'bottom' and line['top'] >= .90))})
    threshold = max(2, math.ceil(len(pages) * .6))
    output, exclusions = [], []
    for number, page in enumerate(pages, 1):
        head = [line for index, line in enumerate(page)
                if (line.get('bottom') is not None and line['bottom'] <= .12)
                or (line.get('top') is None and index < 2)]
        bilingual = {_masthead(line['text']) for line in head} >= {'chinese', 'english'}
        body = []
        for index, line in enumerate(page):
            text, key = line['text'], _key(line['text'])
            top, bottom = line.get('top'), line.get('bottom')
            reason = ''
            if top is not None:
                if bottom <= .12 and frequency[('top', key)] >= threshold and _masthead(text):
                    reason = 'repeated_header'
                elif top >= .90 and (_page_number(text, number) or (frequency[('bottom', key)] >= threshold and _masthead(text))):
                    reason = 'footer'
            elif index == len(page) - 1 and _page_number(text, number, located=False) and len(page) > 2:
                reason = 'page_number'
            if bilingual and line in head and _masthead(text):
                reason = 'bilingual_masthead'
            if reason:
                exclusions.append({'page': number, 'text': text, 'reason': reason})
            else:
                body.append(text)
        output.append('\n'.join(body).strip())
    return output, exclusions
