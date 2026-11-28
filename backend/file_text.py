"""Lossless text extraction for AI materials, independent of article formatting."""
from __future__ import annotations

from dataclasses import dataclass
from zipfile import ZipFile
from xml.etree import ElementTree as ET
import re

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


@dataclass(frozen=True)
class DocxTextBlock:
    text: str
    location: str
    table: int = 0
    cells: tuple[str, ...] = ()


def _paragraph_text(node):
    parts = []
    for child in node.iter():
        if child.tag == W + 't':
            parts.append(child.text or '')
        elif child.tag == W + 'tab':
            parts.append('\t')
        elif child.tag in (W + 'br', W + 'cr'):
            parts.append('\n')
    return ''.join(parts)


def _row_cells(node):
    return tuple('\n'.join(_blocks(cell)) for cell in node if cell.tag == W + 'tc')


def _blocks(node):
    tag = node.tag
    if tag == W + 'p':
        text = _paragraph_text(node)
        if text.strip():
            yield text
    elif tag == W + 'tr':
        cells = _row_cells(node)
        if any(cells):
            yield '\t'.join(cells)
    else:
        for child in node:
            yield from _blocks(child)


def _body_blocks(body):
    paragraphs = 0
    tables = 0
    rows = {}

    def walk(node, table=0):
        nonlocal paragraphs, tables
        if node.tag == W + 'p':
            paragraphs += 1
            text = _paragraph_text(node)
            if text.strip():
                yield DocxTextBlock(text, f'第{paragraphs}段')
        elif node.tag == W + 'tr':
            rows[table] = rows.get(table, 0) + 1
            cells = _row_cells(node)
            if any(cells):
                location = f'第{table}表第{rows[table]}行' if table else f'表格第{rows[table]}行'
                yield DocxTextBlock('\t'.join(cells), location, table, cells)
        else:
            if node.tag == W + 'tbl':
                tables += 1
                table = tables
            for child in node:
                yield from walk(child, table)

    yield from walk(body)


def read_docx_blocks(path):
    with ZipFile(path) as archive:
        root = ET.fromstring(archive.read('word/document.xml'))
        body = root.find(W + 'body')
        if body is not None:
            yield from _body_blocks(body)
        # Footnotes/endnotes often contain the actual citation or qualification.
        for member, label in [('word/footnotes.xml', '脚注'), ('word/endnotes.xml', '尾注')]:
            if member not in archive.namelist():
                continue
            notes = ET.fromstring(archive.read(member))
            for note in notes:
                if note.get(W + 'type') in {'separator', 'continuationSeparator'}:
                    continue
                text = '\n'.join(_blocks(note))
                if text.strip():
                    location = f'{label} {note.get(W + "id", "")}'
                    yield DocxTextBlock(f'【{location}】\n{text}', location)
        for member in sorted(archive.namelist()):
            match = re.fullmatch(r'word/(header|footer)(\d+)\.xml', member)
            if match:
                text = '\n'.join(_blocks(ET.fromstring(archive.read(member))))
                if text.strip():
                    label = '页眉' if match[1] == 'header' else '页脚'
                    location = f'{label} {match[2]}'
                    yield DocxTextBlock(f'【{location}（不推断物理页码）】\n{text}', location)
        if 'word/comments.xml' in archive.namelist():
            for comment in ET.fromstring(archive.read('word/comments.xml')):
                text = '\n'.join(_blocks(comment))
                if text.strip():
                    location = f'文档批注 {comment.get(W + "id", "")}'
                    yield DocxTextBlock(f'【{location}】\n{text}', location)


def read_docx(path):
    return '\n\n'.join(block.text for block in read_docx_blocks(path))
