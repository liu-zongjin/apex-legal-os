"""Record HTML must export as readable text without losing source URLs."""
import ast
from io import BytesIO
from pathlib import Path
import re
import unittest
import openpyxl
from bs4 import BeautifulSoup

SOURCE = Path(__file__).resolve().parents[1] / 'backend' / 'main.py'
TREE = ast.parse(SOURCE.read_text())
NAMES = {'_case_timeline_export_text', '_case_timeline_xlsx_bytes'}
ENV = {'re': re, 'BeautifulSoup': BeautifulSoup, 'openpyxl': openpyxl, 'BytesIO': BytesIO}
exec(compile(ast.Module(body=[n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name in NAMES],type_ignores=[]),str(SOURCE),'exec'), ENV)

class CaseRecordExportTests(unittest.TestCase):
    def test_formatted_content_keeps_paragraphs_inline_words_and_source_url(self):
        html='<h2>争议焦点</h2><p>合同<strong>效力</strong>与付款凭证。</p><p><a href="https://example.org/case">案例来源</a></p><ol><li data-list-label="一、">核对证据</li></ol>'
        result=ENV['_case_timeline_xlsx_bytes']('匿名案件',[{'content':html}], '案件备忘录')
        workbook=openpyxl.load_workbook(BytesIO(result))
        content=workbook.active['E2'].value
        self.assertNotIn('<p>',content)
        self.assertIn('合同效力与付款凭证。',content)
        self.assertIn('https://example.org/case',content)
        self.assertIn('一、 核对证据',content)
        self.assertIn('\n',content)

    def test_plain_and_markdown_content_is_preserved(self):
        for text in ['费用 < 100 元\n下一步安排', '### 争议焦点\n\n**合同效力**']:
            self.assertEqual(ENV['_case_timeline_export_text'](text),text)

    def test_inline_only_formatting_does_not_export_tags(self):
        self.assertEqual(ENV['_case_timeline_export_text']('<strong>直接编辑加粗</strong>'),'直接编辑加粗')

    def test_non_content_nodes_are_not_exported(self):
        self.assertEqual(ENV['_case_timeline_export_text']('<p>正文</p><script>bad()</script><style>p{}</style>'),'正文')
