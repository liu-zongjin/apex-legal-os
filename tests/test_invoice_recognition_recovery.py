"""Anonymous regressions for real-world column-order and outlined OFD invoices."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend import qq_mail_mcp as m


class InvoiceRecognitionRecoveryTests(unittest.TestCase):
    def test_capital_total_wins_over_trailing_tax_and_zero(self):
        for capital, values, expected in [
            ('贰拾伍圆壹角柒分', '¥25.17\n24.44\n¥\n0.73\n¥', '25.17'),
            ('贰仟零陆拾圆整', '¥2060.00\n¥2060.00\n¥0.00', '2060.00'),
            ('负伍拾圆整', '-¥50.00\n-¥2.83', '-50.00'),
        ]:
            self.assertEqual(m._parse_invoice_text('电子发票 发票号码：26442000010000000001\n价税合计（大写）\n' + capital + '\n' + values)['amount'], expected)

    def test_structured_same_invoice_fills_outlined_ofd_and_corrects_pdf(self):
        common = dict(uid='42', mailbox='INBOX')
        rows = [dict(common, filename='发票.pdf', ext='.pdf', invoice_number='26442000010000000001', amount='0.73'),
                dict(common, filename='发票.xml', ext='.xml', invoice_number='26442000010000000001', amount='25.17', issuer='匿名销售方', issue_time='2026年10月17日'),
                dict(common, filename='发票.ofd', ext='.ofd'),
                dict(common, filename='行程单.pdf', ext='.pdf', amount='25.17')]
        m._complete_invoice_metadata(rows)
        for row in rows[:3]:
            self.assertEqual(row['amount'], '25.17')
            self.assertEqual(row['issuer'], '匿名销售方')
            self.assertTrue(row['parsed'])
        self.assertEqual(rows[3]['document_role'], 'supporting')
        self.assertEqual(rows[3]['amount'], '')

    def test_conflicting_numbers_and_same_names_in_different_mails_never_merge(self):
        rows = [dict(uid='1', filename='发票.pdf', ext='.pdf', invoice_number='26442000010000000001', amount='25.17'),
                dict(uid='1', filename='发票.xml', ext='.xml', invoice_number='26442000010000000002', amount='100.00'),
                dict(uid='2', filename='发票.ofd', ext='.ofd')]
        m._complete_invoice_metadata(rows)
        self.assertEqual(rows[0]['amount'], '25.17')
        self.assertFalse(rows[2].get('invoice_number'))

    def test_conflicting_xml_totals_do_not_overwrite_pdf(self):
        rows = [dict(invoice_number='26442000010000000001', filename='a.pdf', ext='.pdf', amount='30.00'),
                dict(invoice_number='26442000010000000001', filename='b.xml', ext='.xml', amount='10.00'),
                dict(invoice_number='26442000010000000001', filename='c.xml', ext='.xml', amount='20.00')]
        m._complete_invoice_metadata(rows)
        self.assertEqual(rows[0]['amount'], '30.00')

    def test_local_recovery_uses_receipt_date_and_deduplicates_historical_months(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for month in ['2026-08', '2026-09']:
                folder = root / month
                folder.mkdir()
                (folder / '42_发票.pdf').write_bytes(b'anonymous')
                (folder / '43_发票.pdf').write_bytes(b'anonymous')
            summaries = {'mails': {'42': {'date': '2026-08-24 10:30', 'subject': '电子发票'},
                                    '43': {'date': '2026-06-01 10:30', 'subject': '电子发票'}}}
            with patch.object(m, '_account_config', return_value={'attachment_root': root}), \
                 patch.object(m, '_load_summary_cache', return_value=summaries), \
                 patch.object(m, '_load_scan_cache', return_value={}), \
                 patch.object(m, '_save_scan_cache'), \
                 patch.object(m, '_meta_for_file', return_value={'invoice_number': '26442000010000000001', 'amount': '100.00'}):
                rows = m._restore_local_invoices('qq_mail', [], ['.pdf'], '2026-07-21', '2026-10-18', '')
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['uid'], '42')
            self.assertEqual(rows[0]['source_type'], 'local')


if __name__ == '__main__':
    unittest.main()
