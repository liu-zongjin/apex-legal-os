"""Locate literal citations and map them back to the original readable text."""
import re
from array import array
from bisect import bisect_right
from collections import defaultdict
from html import escape
from itertools import groupby

from .file_text import read_docx_blocks

_PAGE_MARKER = re.compile(r'(?m)^【第[ \t]*\d+[ \t]*页】[ \t]*\r?(?:\n|$)')
_FULLWIDTH_ASCII = {code: code - 0xFEE0 for code in range(0xFF01, 0xFF5F)}
_LAYOUT_CHARACTERS = frozenset('\u00ad\u200b\u200c\u200d\u200e\u200f\ufeff')
_GROUPED_NUMBER = re.compile(r'(?<![\d.,，])\d{1,3}(?:[,，]\d{3})+(?!\d|[,，]\d)')


def _compact(text):
    text = text.translate(_FULLWIDTH_ASCII)
    separators = {i for match in _GROUPED_NUMBER.finditer(text) for i in range(*match.span()) if text[i] in ',，'}
    chars = []
    offsets = array('I')
    gap = None
    for i, char in enumerate(text):
        if char.isspace():
            gap = i
            continue
        if char in _LAYOUT_CHARACTERS or i in separators:
            continue
        # Word cells and paragraph breaks must not join two independent numbers.
        if gap is not None and chars and chars[-1].isdigit() and char.isdigit():
            chars.append(' ')
            offsets.append(gap)
        chars.append(char)
        offsets.append(i)
        gap = None
    return ''.join(chars), offsets


class CitationIndex:
    def __init__(self, parts):
        self.parts = tuple(parts)
        self.starts = []
        offset = 0
        for part in self.parts:
            self.starts.append(offset)
            offset += len(part) + 1
        self.text, self.offsets = _compact('\n'.join(self.parts))

    def find(self, quote):
        needle, _ = _compact(_PAGE_MARKER.sub('', quote))
        if len(needle) < 4:
            return []
        hits = []
        offset = 0
        while (start := self.text.find(needle, offset)) >= 0:
            end = start + len(needle)
            offset = end
            if needle[0].isdigit() and self._number_continues(start - 1, -1):
                continue
            if needle[-1].isdigit() and self._number_continues(end, 1):
                continue
            left, right = self.offsets[start], self.offsets[end - 1] + 1
            first = bisect_right(self.starts, left) - 1
            last = bisect_right(self.starts, right - 1) - 1
            ranges = []
            for part in range(first, last + 1):
                beginning = self.starts[part]
                lo, hi = max(0, left - beginning), min(len(self.parts[part]), right - beginning)
                if lo < hi:
                    ranges.append((part, lo, hi))
            if ranges:
                hits.append(ranges)
        return hits

    def _number_continues(self, position, direction):
        if not 0 <= position < len(self.text):
            return False
        adjacent = self.text[position]
        next_position = position + direction
        return adjacent.isdigit() or (adjacent == '.' and 0 <= next_position < len(self.text)
                                     and self.text[next_position].isdigit()
                                     and abs(self.offsets[next_position] - self.offsets[position]) == 1
                                     and abs(self.offsets[position - direction] - self.offsets[position]) == 1)


def _marked(text, ranges):
    parts = []
    offset = 0
    for start, end in ranges:
        parts.extend((escape(text[offset:start]), '<mark>', escape(text[start:end]), '</mark>'))
        offset = end
    parts.append(escape(text[offset:]))
    return ''.join(parts)


class WordPreview:
    def __init__(self, path):
        self.blocks = list(read_docx_blocks(path))
        parts = []
        self.part_blocks = []
        for block in self.blocks:
            cells = block.cells or (block.text,)
            parts.extend(cells)
            self.part_blocks.extend([block] * len(cells))
        self.index = CitationIndex(parts)

    def locator(self, hits):
        if len(hits) > 1:
            return f'Word · 匹配 {len(hits)} 处'
        if not hits:
            return ''
        first = self.part_blocks[hits[0][0][0]].location
        last = self.part_blocks[hits[0][-1][0]].location
        return f'Word {first}' if first == last else f'Word {first}至{last}'

    def html(self, hits):
        ranges = defaultdict(list)
        for hit in hits:
            for part, start, end in hit:
                ranges[part].append((start, end))
        parts = []
        index = 0
        for table, blocks in groupby(self.blocks, key=lambda block: block.table):
            if table:
                parts.append(f'<div class="word-table"><table><caption>第{table}表</caption><tbody>')
            for block in blocks:
                if block.cells:
                    end = index + len(block.cells)
                    styled = ' class="match"' if any(i in ranges for i in range(index, end)) else ''
                    label = escape(block.location.rsplit('表', 1)[-1])
                    cells = ''.join(f'<td>{_marked(cell, ranges.get(i, ()))}</td>'
                                    for i, cell in enumerate(block.cells, index))
                    parts.append(f'<tr{styled}><th scope="row">{label}</th>{cells}</tr>')
                    index = end
                else:
                    styled = ' class="match"' if index in ranges else ''
                    body = _marked(block.text, ranges.get(index, ()))
                    parts.append(f'<section{styled}><header><small>{escape(block.location)}</small></header><p>{body}</p></section>')
                    index += 1
            if table:
                parts.append('</tbody></table></div>')
        return ''.join(parts)


def highlight_pdf_citation(page, quote):
    """Annotate the in-memory display page and return its first hit as a vertical fraction."""
    import fitz

    lines = []
    for block in page.get_text('rawdict', flags=fitz.TEXTFLAGS_TEXT, sort=True)['blocks']:
        for line in block.get('lines', []):
            lines.append([char for span in line['spans'] for char in span['chars']])
    index = CitationIndex(''.join(char['c'] for char in line) for line in lines)
    rectangles = []
    for hit in index.find(quote):
        for line, start, end in hit:
            rect = fitz.Rect()
            for glyph in lines[line][start:end]:
                rect |= fitz.Rect(glyph['bbox'])
            if not rect.is_empty:
                rectangles.append(rect)
    if not rectangles:
        return None
    mark = page.add_highlight_annot(rectangles)
    mark.update(opacity=.42)
    first = rectangles[0] * page.rotation_matrix
    return ((first.y0 + first.y1) / 2 - page.rect.y0) / page.rect.height
