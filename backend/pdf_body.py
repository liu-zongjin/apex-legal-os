"""Conservative page furniture removal for analysis, never edits original PDFs.

Layout is preferred. OCR without coordinates only drops a repeated bilingual
masthead or an isolated trailing page number; ambiguous text remains in the body.
"""
import math
import re
from collections import Counter


def _key(text):
    return re.sub(r'\s+', '', text).casefold()


def _page_number(text, page):
    value = text.strip()
    # A bare amount at the bottom is not necessarily a page number.
    return value == str(page) or bool(re.fullmatch(
        r'(?:[-—–]\s*\d{1,4}\s*[-—–]|第\s*\d+\s*页(?:\s*[共/／]\s*\d+\s*页?)?|\d+\s*[/／]\s*\d+)', value))


def _substantive(text):
    return bool(re.search(r'\d|元|应当|不得|必须|支付|履行|同意|约定|原告|被告|申请人|上诉人|被执行人|'
                          r'案号|合同编号|法定代表人|诉讼请求|事实与理由|第.{1,5}条|'
                          r'plaintiff|defendant|claimant|respondent', _key(text)))


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
        chinese = any(re.fullmatch(r'[\u4e00-\u9fff·（）()]{2,30}律师事务所', _key(line['text'])) for line in head)
        english = any(re.fullmatch(r"[a-z &.,'’-]{2,60}(?:lawoffices|lawfirm)", _key(line['text'])) for line in head)
        body = []
        for index, line in enumerate(page):
            text, key = line['text'], _key(line['text'])
            top, bottom = line.get('top'), line.get('bottom')
            reason = ''
            if top is not None:
                if bottom <= .12 and frequency[('top', key)] >= threshold and not _substantive(text):
                    reason = 'repeated_header'
                elif top >= .90 and (_page_number(text, number) or (frequency[('bottom', key)] >= threshold
                                                          and not _substantive(text))):
                    reason = 'footer'
            elif index == len(page) - 1 and _page_number(text, number) and len(page) > 2:
                reason = 'page_number'
            if chinese and english and line in head and (
                    re.fullmatch(r'[\u4e00-\u9fff·（）()]{2,30}律师事务所', key)
                    or re.fullmatch(r"[a-z &.,'’-]{2,60}(?:lawoffices|lawfirm)", key)):
                reason = 'bilingual_masthead'
            if reason:
                exclusions.append({'page': number, 'text': text, 'reason': reason})
            else:
                body.append(text)
        output.append('\n'.join(body).strip())
    return output, exclusions
