"""Preserve user-authored article table dimensions and borders in Word exports."""
import re

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt


def apply_docx_table_styles(table, rows):
    def styles(node):
        return {k.strip(): v.strip() for k, _, v in (part.partition(':') for part in node.get('style', '').split(';')) if k.strip()}

    def points(value):
        match = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)(px|pt)', value or '')
        return min(300, float(match[1]) * (.75 if match[2] == 'px' else 1)) if match else None

    for i, row in enumerate(rows):
        row_style = styles(row)
        height = points(row_style.get('height'))
        if height:
            table.rows[i].height = Pt(height)
        for j, source in enumerate(row.find_all(['th', 'td'], recursive=False)):
            cell = table.cell(i, j)
            style = styles(source)
            for paragraph in cell.paragraphs:
                spacing = style.get('line-height', '')
                if re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', spacing):
                    paragraph.paragraph_format.line_spacing = max(1, min(3, float(spacing)))
            borders = OxmlElement('w:tcBorders')
            for side in ('top', 'left', 'bottom', 'right'):
                value = style.get('border-' + side, style.get('border', ''))
                if not value:
                    continue
                edge = OxmlElement('w:' + side)
                match = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)px (solid|dashed) #([0-9a-fA-F]{6})', value)
                if value in ('none', '0', '0px'):
                    edge.set(qn('w:val'), 'nil')
                elif match:
                    edge.set(qn('w:val'), 'dashed' if match[2] == 'dashed' else 'single')
                    edge.set(qn('w:sz'), str(max(1, min(24, round(float(match[1])*6)))))
                    edge.set(qn('w:color'), match[3].upper())
                else:
                    continue
                borders.append(edge)
            if len(borders):
                cell._tc.get_or_add_tcPr().append(borders)
