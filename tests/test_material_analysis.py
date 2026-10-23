import unittest

from backend.material_analysis import InvalidAnalysis, literal_quote, source_passages, validate_items


def source(text, identifier='1'):
    return {'id': identifier, 'text': text, 'path': 'anonymous.pdf', 'sha256': 'fixture-hash',
            'locator': '第1页', 'chunk_index': 0}


def proposal(reference):
    return {'items': [{'title': '付款陈述待核', 'type': 'issue', 'analysis': '陈述是否有凭证支持仍待核对。',
                       'evidence': [reference], 'follow_up': '核对凭证。'}]}


class MaterialAnalysisCitationTests(unittest.TestCase):
    def test_passage_selection_uses_unchanged_original_pdf_text(self):
        row = source('甲方主张：截至\n2026 年 1 月 1 日，\n乙方尚未支付 10000 元。')
        passage = source_passages(row)[0]
        result = validate_items(proposal({'source_id': '1', 'passage_id': passage['id']}), [row])
        ref = result[0]['evidence'][0]
        self.assertEqual(ref['quote'], row['text'])
        self.assertEqual(row['text'][ref['quote_start']:ref['quote_end']], ref['quote'])
        self.assertEqual(ref['match'], 'passage')
        self.assertEqual(result[0]['review_status'], 'pending')

    def test_legacy_quote_aligns_only_layout_and_exports_original(self):
        row = source('前文。乙方尚未\n支付\u00a010000 元。后文。')
        ref = validate_items(proposal({'source_id': '1', 'quote': '乙方尚未支付10000元。'}), [row])[0]['evidence'][0]
        self.assertEqual(ref['quote'], '乙方尚未\n支付\u00a010000 元。')
        self.assertEqual(ref['match'], 'layout_aligned')
        self.assertEqual(row['text'][ref['quote_start']:ref['quote_end']], ref['quote'])

    def test_negation_numbers_and_punctuation_must_not_be_rewritten(self):
        text = '乙方尚未支付10000元。'
        for quote in ('乙方已经支付10000元。', '乙方尚未支付100000元。', '乙方尚未支付10000元！'):
            with self.subTest(quote=quote):
                self.assertIsNone(literal_quote(text, quote))
                with self.assertRaises(InvalidAnalysis):
                    validate_items(proposal({'source_id': '1', 'quote': quote}), [source(text)])

    def test_passage_cannot_be_moved_to_another_source(self):
        with self.assertRaises(InvalidAnalysis):
            validate_items(proposal({'source_id': '2', 'passage_id': '1:1'}),
                           [source('甲方主张未收到款项。'), source('乙方否认欠款。', '2')])

    def test_missing_source_and_invented_passages_fail(self):
        for ref in ({'source_id': '99', 'passage_id': '1:1'}, {'source_id': '1', 'passage_id': '1:99'}):
            with self.subTest(ref=ref), self.assertRaises(InvalidAnalysis):
                validate_items(proposal(ref), [source('匿名材料记载付款争议。')])

    def test_excerpts_remain_bounded_and_deterministic_for_long_pages(self):
        row = source(('匿名原文中保留换行和空格。\n' * 240) + '末尾。')
        passages = source_passages(row)
        self.assertEqual(passages, source_passages(row))
        self.assertGreater(len(passages), 1)
        self.assertTrue(all(len(p['text']) <= 800 for p in passages))
        for part in passages:
            self.assertEqual(row['text'][part['start']:part['end']], part['text'])
        self.assertEqual(''.join(p['text'].replace('\n', '') for p in passages), row['text'].replace('\n', ''))

    def test_existing_literal_quote_contract_stays_compatible(self):
        row = source('匿名材料记载付款争议。')
        result = validate_items(proposal({'source_id': '1', 'quote': row['text']}), [row])
        self.assertEqual(result[0]['evidence'][0]['match'], 'literal')

    def test_invalid_item_never_partially_publishes_the_batch(self):
        data = proposal({'source_id': '1', 'passage_id': '1:1'})
        data['items'].extend(proposal({'source_id': '1', 'passage_id': 'invented'})['items'])
        with self.assertRaises(InvalidAnalysis) as raised:
            validate_items(data, [source('匿名材料记载付款争议。')])
        self.assertEqual(raised.exception.diagnostic['item'], 2)
        self.assertEqual(raised.exception.diagnostic['reference'], 1)
