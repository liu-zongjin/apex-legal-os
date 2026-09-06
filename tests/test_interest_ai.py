import datetime as dt
import unittest

from backend.interest_ai import extraction_messages, normalize_extraction, parse_extraction_content


class InterestAiExtractionTests(unittest.TestCase):
    def test_prompt_includes_current_date_and_user_text(self):
        messages = extraction_messages("自2024年1月1日起至今", dt.date(2026, 8, 9))
        self.assertIn("2026-08-09", messages[0]["content"])
        self.assertEqual(messages[1]["content"], "自2024年1月1日起至今")

    def test_json_response_is_normalized_for_frontend(self):
        result = parse_extraction_content('''```json
        {"common_principal":171620.85,"segments":[{"principal":null,"start_date":"2024-09-04","end_date":"2026-04-10","rate_mode":"lpr","multiplier":1,"spread_bp":0,"fixed_rate":null}],"warnings":[]}
        ```''')
        self.assertEqual(result["commonPrincipal"], 171620.85)
        self.assertEqual(result["segments"][0]["startDate"], "2024-09-04")
        self.assertEqual(result["segments"][0]["mode"], "lpr")

    def test_invalid_dates_are_not_forwarded_to_calculator(self):
        result = normalize_extraction({
            "segments": [{"start_date": "2026-02-31", "end_date": "2026-03-01", "rate_mode": "fixed", "fixed_rate": 6}]
        })
        self.assertEqual(result["segments"], [])
        self.assertIn("缺少完整起止日期", result["warnings"][0])

    def test_fixed_rate_defaults_are_explicitly_warned(self):
        result = normalize_extraction({
            "segments": [{"start_date": "2026-01-01", "end_date": "2026-02-01", "rate_mode": "fixed"}]
        })
        self.assertEqual(result["segments"][0]["fixedRate"], 4.35)
        self.assertTrue(any("未识别到固定年利率" in item for item in result["warnings"]))

    def test_large_legal_claim_amount_is_preserved(self):
        result = normalize_extraction({
            "common_principal": 35_917_647,
            "segments": [{"start_date": "2026-01-01", "end_date": "2026-02-01", "rate_mode": "lpr"}],
        })
        self.assertEqual(result["commonPrincipal"], 35_917_647)


if __name__ == "__main__":
    unittest.main()
