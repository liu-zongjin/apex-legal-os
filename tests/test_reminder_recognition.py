import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.reminder_recognition import register_reminder_recognition_routes, normalize_draft, local_draft


class ReminderRecognitionTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.fail = False
        self.payload = {'todo_title': '提交材料', 'remind_at': '2026-10-29 09:30', 'recurrence': 'weekly',
                        'appeal_type': '上诉', 'start_at': '2026-10-25', 'period_days': 15,
                        'deadline_at': '', 'case_id': 999, 'case_no': '幻觉案号'}
        async def ai(*args, **kwargs):
            import json
            self.calls.append(args)
            if self.fail:
                raise RuntimeError('测试服务不可用')
            return {'choices': [{'message': {'content': json.dumps(self.payload)}}]}, 'fixture-model'
        async def upload(file):
            text = (await file.read()).decode()
            return {'filename': file.filename, 'text': text, 'error': ''}
        def match(numbers):
            return {'case_id': 1, 'title': '匿名案件'} if '原文案号' in numbers else None
        def merge(item, matched):
            return {**item, **(matched or {})}
        app = FastAPI()
        register_reminder_recognition_routes(app, extract_upload=upload, clean_text=lambda text: text.strip(),
            parse_datetime=lambda text: '', parse_date=lambda text: text[:10],
            extract_numbers=lambda text: ['原文案号'] if '原文案号' in text else [], match_case=match,
            merge_case=merge, call_ai=ai, requested_model=lambda: 'fixture-model')
        self.client = TestClient(app)

    def test_todo_matches_literal_case_and_filters_injected_id(self):
        result = self.client.post('/api/case-manager/todos/recognize', data={'text': '原文案号 会议通知'}).json()
        self.assertTrue(result['ai']['used'])
        self.assertEqual(result['item']['case_id'], 1)
        self.assertEqual(result['item']['todo_title'], '提交材料')
        self.assertEqual(result['item']['remind_at'], '2026-10-29 09:30')

    def test_appeal_does_not_calculate_deadline_or_match_hallucinated_case(self):
        result = self.client.post('/api/case-manager/appeals/recognize', data={'text': '收到判决，请在十五日内上诉'}).json()
        self.assertFalse(result['matched_case'])
        self.assertNotIn('case_id', result['item'])
        self.assertEqual(result['item']['case_no'], '')
        self.assertEqual(result['item']['deadline_at'], '')
        self.assertEqual(result['item']['period_days'], 15)

    def test_unique_source_reference_is_associated(self):
        from backend.case_text_matching import match_case_text
        rows = [{'case_id': 7, 'title': '当代星河置业有限公司合同纠纷'}]
        # Exercise the same matcher independently of AI-extracted names.
        self.assertEqual(match_case_text('当代星河（湖畔）11月19日前提交', rows)['case_id'], 7)

    def test_date_only_fallback_uses_default_time(self):
        import re
        parse_date = lambda value: '2026-11-19' if re.search(r'2026年11月19日', value) else ''
        draft = local_draft('todos', '2026年11月19日之前提交', lambda _: '', parse_date)
        self.assertEqual(draft['remind_at'], '2026-11-19 09:00')
        draft = local_draft('todos', '2026年11月19日收到，2026年12月1日之前提交', lambda _: '', parse_date)
        self.assertEqual(draft['remind_at'], '')

    def test_uploads_use_shared_extractor(self):
        result = self.client.post('/api/case-manager/todos/recognize', files={'files': ('notice.txt', b'notice', 'text/plain')}).json()
        self.assertEqual(result['files'], [{'filename': 'notice.txt', 'error': ''}])
        self.assertEqual(result['raw_text'], 'notice')

    def test_empty_and_oversized_input_never_calls_ai(self):
        for text in ('', '字' * 24001):
            self.assertEqual(self.client.post('/api/case-manager/todos/recognize', data={'text': text}).status_code, 400)
        self.assertEqual(self.calls, [])

    def test_failure_keeps_local_draft_and_reports_ai_unavailable(self):
        self.fail = True
        result = self.client.post('/api/case-manager/appeals/recognize', data={'text': '上诉\n送达日期：2026-10-25\n期限：15日\n落款2026-10-20'}).json()
        self.assertFalse(result['ai']['used'])
        self.assertEqual(result['item']['start_at'], '2026-10-25')
        self.assertEqual(result['item']['deadline_at'], '')
        self.assertEqual(result['item']['period_days'], 15)

    def test_invalid_dates_period_and_recurrence_stay_empty(self):
        self.assertEqual(normalize_draft('todos', {'remind_at': '2026-10-25'})['remind_at'], '')
        self.assertEqual(normalize_draft('todos', {'recurrence': 'daily'})['recurrence'], '')
        draft = normalize_draft('appeals', {'start_at': '2026-02-30', 'period_days': -2})
        self.assertEqual(draft['start_at'], '')
        self.assertEqual(draft['period_days'], '')
        fallback = local_draft('appeals', '2026年10月25日判决，十五日内上诉', lambda _: '', lambda _: '')
        self.assertEqual(fallback['start_at'], '')
        self.assertEqual(fallback['period_days'], '')


if __name__ == '__main__':
    unittest.main()
