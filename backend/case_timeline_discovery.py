"""Find likely pleadings inside a bound case folder without moving user files."""
from __future__ import annotations

import os
import re
from pathlib import Path

# Larger PDFs are usually exhibits; never read them automatically as pleadings.
MAX_PDF_BYTES = 12 * 1024 * 1024
MAX_WORD_BYTES = 12 * 1024 * 1024
MAX_SCANNED_FILES = 3000
PLEADING = re.compile(r'(民事起诉状|民事答辩状|民事反诉状|民事上诉状|二审答辩状|仲裁申请书|仲裁反请求申请书|反诉起诉状|反诉答辩状|起诉状|答辩状|反诉状|上诉状|仲裁反请求|仲裁答辩)', re.I)
EXHIBIT = re.compile(r'证据册|证据目录|证据清单|证据汇编|授权委托|身份证|营业执照|律师事务所函')


def side_for(path, title='', parties=()):
    """Use the actual path or a uniquely named case party; ambiguous stays unknown."""
    text = str(path)
    roles = []
    for row in parties:
        name = str(row.get('name') or '').strip()
        if name and name in text:
            role = str(row.get('role') or '')
            if '被告' in role:
                roles.append('被告方')
            elif '原告' in role:
                roles.append('原告方')
            else:
                for label in ('被上诉人','上诉人','被申请人','申请人'):
                    if label in role:
                        roles.append(label)
                        break
    if len(set(roles)) == 1:
        return roles[0]
    has_plaintiff = bool(re.search(r'原告方|原告材料|原告[\\/]|申请人材料', text))
    has_defendant = bool(re.search(r'被告方|被告材料|被告[\\/]|被申请人材料', text))
    if has_plaintiff != has_defendant:
        return '原告方' if has_plaintiff else '被告方'
    if re.search(r'二审|上诉|仲裁|反诉', title):
        return '待确认'
    if '起诉状' in title:
        return '原告方'
    if '答辩状' in title:
        return '被告方'
    return '待确认'


def _content_head(path):
    try:
        if path.suffix.lower() == '.docx':
            from docx import Document
            doc = Document(path)
            return '\n'.join(p.text for p in doc.paragraphs[:30])[:5000]
        if path.suffix.lower() == '.pdf':
            import fitz
            with fitz.open(path) as pdf:
                return '\n'.join(pdf[i].get_text() for i in range(min(2, len(pdf))))[:5000]
    except Exception:
        return ''
    return ''


def discover(root, parties=()):
    candidates, evidence, skipped_large = [], [], 0
    count = 0
    for current, dirs, names in os.walk(root, followlinks=False):
        folder = Path(current)
        dirs[:] = sorted(name for name in dirs if not name.startswith('.') and name != 'Stella办案成果' and not (folder/name).is_symlink())
        for name in sorted(names):
            path = folder/name
            if name.startswith('.') or path.is_symlink() or not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix not in {'.doc', '.docx', '.pdf', '.txt', '.md', '.png', '.jpg', '.jpeg'}:
                continue
            count += 1
            if count > MAX_SCANNED_FILES:
                return {'candidates': candidates, 'evidence': evidence[:100], 'skipped_large':skipped_large, 'scan_incomplete':True}
            relative = path.relative_to(root).as_posix()
            size = path.stat().st_size
            if suffix == '.pdf' and size > MAX_PDF_BYTES or suffix in {'.doc', '.docx'} and size > MAX_WORD_BYTES:
                skipped_large += 1
                continue
            title = ''
            if suffix in {'.doc', '.docx', '.pdf'} and not EXHIBIT.search(name):
                match = PLEADING.search(name)
                if not match:
                    # Generic filenames: require a short heading, not a passing
                    # reference to a pleading inside an unrelated exhibit.
                    head = _content_head(path)
                    for line in head[:1800].splitlines()[:20]:
                        heading = re.sub(r'\s+', '', line)
                        if len(heading) > 45 or re.search(r'[。；;：:]', heading):
                            continue
                        candidate = PLEADING.search(heading)
                        if candidate:
                            match = candidate
                            break
                if match:
                    title = match.group()
            if title:
                candidates.append({'path':relative, 'document_type':title, 'party':side_for(relative,title,parties), 'size':size})
            else:
                evidence.append({'path':relative, 'name':name, 'size':size})
    return {'candidates':candidates, 'evidence':evidence[:100], 'skipped_large':skipped_large, 'scan_incomplete':False}
