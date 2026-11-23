import unittest
from unittest.mock import AsyncMock, patch

from backend import main
from backend import national_law_mcp


class NationalLawComparisonTests(unittest.IsolatedAsyncioTestCase):
    async def evaluate(self, local, official):
        check = {'current': {'bbbs': 'law-1'}, 'preferred': None,
                 'status_changed': False, 'new_version_available': False}
        with patch.object(main, 'check_national_law_update', AsyncMock(return_value=check)), \
             patch.object(main, '_load_official_law_document', AsyncMock(return_value=({'bbbs': 'law-1'}, official, 'hash'))):
            return await main._evaluate_bound_national_law(
                {'title': '示例法规', 'content': local}, {'bbbs': 'law-1'})

    async def test_formatting_differences_do_not_report_revision(self):
        status, details = await self.evaluate('<p>第一条　示例规定。</p>', '<div><span>第一条</span> 示例规定。</div>')
        self.assertEqual(status, 'current')
        self.assertFalse(details['content_changed'])

    async def test_substantive_change_is_detected(self):
        status, details = await self.evaluate('<p>第一条 应当履行。</p>', '<p>第一条 可以履行。</p>')
        self.assertEqual(status, 'update_available')
        self.assertTrue(details['content_changed'])

    async def test_empty_text_requires_review(self):
        with self.assertRaises(main.NationalLawError):
            await self.evaluate('<p> </p>', '<p>第一条 示例规定。</p>')

    async def test_search_order_does_not_make_an_older_version_new(self):
        current = {'bbbs': 'new', 'published_at': '2024-01-01', 'status_code': 3}
        rows = [{'bbbs': 'old', 'published_at': '2020-01-01', 'status_code': 3,
                 'normalized_title': '示例法规'}, {**current, 'normalized_title': '示例法规'}]
        with patch.object(national_law_mcp, 'get_national_law_detail', AsyncMock(return_value=current)), \
             patch.object(national_law_mcp, 'search_national_laws', AsyncMock(return_value={'results': rows})):
            result = await national_law_mcp.check_national_law_update('new', '示例法规')
        self.assertFalse(result['new_version_available'])

    async def test_newer_published_version_is_detected(self):
        current = {'bbbs': 'old', 'published_at': '2020-01-01', 'status_code': 2}
        rows = [{'bbbs': 'new', 'published_at': '2024-01-01', 'status_code': 3,
                 'normalized_title': '示例法规'}]
        with patch.object(national_law_mcp, 'get_national_law_detail', AsyncMock(return_value=current)), \
             patch.object(national_law_mcp, 'search_national_laws', AsyncMock(return_value={'results': rows})):
            result = await national_law_mcp.check_national_law_update('old', '示例法规')
        self.assertTrue(result['new_version_available'])
        self.assertEqual(result['preferred']['bbbs'], 'new')
