"""Display source positions without certifying historical text chunks as paragraphs."""
import re
from pathlib import Path


def display_locator(path, locator):
    if re.fullmatch(r'第\s*\d+\s*段',locator):
        return '未取得原件页码或段落位置，请按引句查找'
    if Path(path).suffix.lower() in {'.doc','.docx'} and re.fullmatch(r'第\s*\d+\s*页',locator):
        return '页码依据尚未确认，请按引句查找'
    return locator
