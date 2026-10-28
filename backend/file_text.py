"""Lossless text extraction for AI materials, independent of article formatting."""
from __future__ import annotations

from zipfile import ZipFile
from xml.etree import ElementTree as ET
import re

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def _blocks(node):
    tag = node.tag
    if tag == W + 'p':
        parts = []
        for child in node.iter():
            if child.tag == W + 't':
                parts.append(child.text or '')
            elif child.tag == W + 'tab':
                parts.append('\t')
            elif child.tag in (W + 'br', W + 'cr'):
                parts.append('\n')
        if ''.join(parts).strip():
            yield ''.join(parts)
    elif tag == W + 'tr':
        cells = ['\n'.join(_blocks(cell)) for cell in node if cell.tag == W + 'tc']
        if any(cells):
            yield '\t'.join(cells)
    else:
        for child in node:
            yield from _blocks(child)


def read_docx(path):
    with ZipFile(path) as archive:
        root = ET.fromstring(archive.read('word/document.xml'))
        body = root.find(W + 'body')
        parts = list(_blocks(body)) if body is not None else []
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
                    parts.append(f'【{label} {note.get(W + "id", "")}】\n{text}')
        for member in sorted(archive.namelist()):
            match = re.fullmatch(r'word/(header|footer)(\d+)\.xml', member)
            if match:
                text = '\n'.join(_blocks(ET.fromstring(archive.read(member))))
                if text.strip():
                    label = '页眉' if match[1] == 'header' else '页脚'
                    parts.append(f'【{label} {match[2]}（不推断物理页码）】\n{text}')
        if 'word/comments.xml' in archive.namelist():
            for comment in ET.fromstring(archive.read('word/comments.xml')):
                text = '\n'.join(_blocks(comment))
                if text.strip():
                    parts.append(f'【文档批注 {comment.get(W + "id", "")}】\n{text}')
        return '\n\n'.join(parts)
