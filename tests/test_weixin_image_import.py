"""Anonymous extraction fixtures; load pure helpers without starting the app/database."""
import ast
import asyncio
from io import BytesIO
from pathlib import Path
import re
import unittest
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from PIL import Image
import requests
from backend.article_structure import classify_article_block


NAMES = {
    'clean_article_text_noise', 'html_to_processing_text', 'is_meaningful_article_text',
    'ensure_meaningful_weixin_content', '_ocr_weixin_images', '_complete_weixin_content',
    '_extract_weixin_html', '_launch_weixin_browser', 'fetch_webpage', 'extract_author',
    'sanitize_author_name',
}
tree = ast.parse((Path(__file__).resolve().parents[1] / 'backend/main.py').read_text())
scope = dict(re=re, BeautifulSoup=BeautifulSoup, requests=requests, HEADERS={}, Path=Path, urlparse=urlparse)
scope['classify_article_block'] = classify_article_block
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                              and n.name in NAMES], type_ignores=[]), '<weixin-helpers>', 'exec'), scope)


class WeixinImageImportTests(unittest.TestCase):
    def test_static_image_only_article_uses_body_and_ocr_before_validation(self):
        response = Mock(text='<h1>匿名文章</h1><div id="js_content"><figure><img '
                        'src="/placeholder.gif" data-src="https://example.com/page.jpg"></figure>'
                        '<p>来源：匿名资料</p></div><img src="https://example.com/footer.jpg">')
        response.headers = {}
        response.content = response.text.encode()
        text = '<p>' + '仲裁协议的效力应当根据当事人的约定依法审查。' * 15 + '</p>'
        with patch.object(requests, 'get', return_value=response), patch.dict(
                scope, _ocr_weixin_images=Mock(return_value=text)):
            result = scope['fetch_webpage']('https://mp.weixin.qq.com/s/anonymous')
            self.assertEqual(result['title'], '匿名文章')
            self.assertIn(text, result['content'])
            self.assertIn('https://example.com/page.jpg', result['content'])
            self.assertNotIn('placeholder', result['content'])
            self.assertNotIn('footer.jpg', result['content'])

    def test_extractor_preserves_downloaded_embedded_images(self):
        embedded = 'data:image/png;base64,' + 'a' * 600
        soup = BeautifulSoup('<div><img src="' + embedded + '" data-src="https://example.com/original"></div>', 'html.parser')
        self.assertIn(embedded, scope['_extract_weixin_html'](soup.div))

    def test_footer_images_without_recognizable_body_still_fail(self):
        with patch.dict(scope, _ocr_weixin_images=Mock(return_value='')):
            with self.assertRaisesRegex(Exception, '质量不足'):
                scope['_complete_weixin_content']('<p>来源：匿名</p><img src="footer.jpg">', '')

    def test_text_article_does_not_need_ocr(self):
        content = '<p>' + '依法保障合同当事人的合法权益。' * 20 + '</p><img src="figure.jpg">'
        ocr = Mock()
        with patch.dict(scope, _ocr_weixin_images=ocr):
            self.assertEqual(scope['_complete_weixin_content'](content, ''), content)
        ocr.assert_not_called()

    def test_ocr_includes_seventh_image_and_rejects_limit_without_truncation(self):
        buf = BytesIO()
        Image.new('RGB', (600, 220), 'white').save(buf, format='PNG')
        response = Mock(content=buf.getvalue())
        content = ''.join('<img src="https://example.com/%d.png">' % i for i in range(7))
        with patch('backend.court_directory._vision_ocr_image', return_value=''), patch.object(requests, 'get', return_value=response) as get, patch(
                'pytesseract.image_to_string', return_value='合同应当依法履行。' * 20):
            self.assertTrue(scope['_ocr_weixin_images'](content))
            self.assertEqual(get.call_count, 7)
            get.reset_mock()
            with self.assertRaisesRegex(ValueError, '分批导入'):
                scope['_ocr_weixin_images'](content, max_images=6)
            get.assert_not_called()

    def test_missing_bundled_browser_falls_back_to_installed_chrome(self):
        browser = object()
        chromium = Mock(launch=AsyncMock(side_effect=[Exception("Executable doesn't exist"), browser]))
        self.assertIs(asyncio.run(scope['_launch_weixin_browser'](chromium)), browser)
        self.assertEqual(chromium.launch.call_args.kwargs, dict(headless=True, channel='chrome'))

    def test_unrelated_browser_failure_is_not_hidden(self):
        chromium = Mock(launch=AsyncMock(side_effect=Exception('permission denied')))
        with self.assertRaisesRegex(Exception, 'permission denied'):
            asyncio.run(scope['_launch_weixin_browser'](chromium))
        self.assertEqual(chromium.launch.call_count, 1)
