import base64
import io
import tempfile
import unittest
import zipfile
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import Mock, patch

from backend import qq_mail_mcp as m


class InvoiceSizeFilterTests(unittest.TestCase):
    def test_exact_decoded_boundaries_and_soft_threshold(self):
        self.assertTrue(m._invoice_size_allowed('document.pdf', 1024 * 1024))
        self.assertFalse(m._invoice_size_allowed('evidence.pdf', 1024 * 1024 + 1))
        self.assertTrue(m._invoice_size_allowed('document.pdf', 2 * 1024 * 1024, True))
        self.assertTrue(m._invoice_size_allowed('电子发票.pdf', 5 * 1024 * 1024))
        self.assertFalse(m._invoice_size_allowed('电子发票.pdf', 5 * 1024 * 1024 + 1, True))
        self.assertTrue(m._invoice_size_allowed('发票.xml', 2048))

    def test_mixed_mail_keeps_small_invoices_and_skips_large_named_invoices(self):
        message = EmailMessage(); message['Subject'] = '电子发票'; message.set_content('附件')
        message.add_attachment(b'x' * (m._INVOICE_MAX_BYTES + 1), maintype='application', subtype='pdf', filename='大发票.pdf')
        message.add_attachment(b'%PDF-small', maintype='application', subtype='pdf', filename='小发票.pdf')
        self.assertEqual([name for name, _ in m._invoice_parts(message)], ['小发票.pdf'])

    def test_zip_member_is_checked_before_decompression(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('大发票.pdf', b'x' * (m._INVOICE_MAX_BYTES + 1))
            archive.writestr('小发票.xml', b'<Invoice/>')
        message = EmailMessage(); message.set_content('附件')
        message.add_attachment(stream.getvalue(), maintype='application', subtype='zip', filename='发票.zip')
        self.assertEqual([name.split('_', 1)[1] for name, _ in m._invoice_parts(message)], ['小发票.xml'])

    def test_existing_oversized_file_is_not_parsed_or_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '42_发票.pdf'
            with path.open('wb') as file:
                file.truncate(m._INVOICE_MAX_BYTES + 1)
            with patch.object(m, 'parse_invoice_metadata') as parse:
                self.assertFalse(m._meta_for_file(path, {})['parsed'])
                result, _ = m._invoice_attachment_file(Path(directory), '42', '发票.pdf', b'', {}, True)
                self.assertIsNone(result)
                parse.assert_not_called()
            self.assertTrue(path.exists())

    def test_bodystructure_parser_preserves_nested_sections_and_encoded_sizes(self):
        text = '1 (UID 42 BODYSTRUCTURE (("TEXT" "PLAIN" ("CHARSET" "UTF-8") NIL NIL "7BIT" 50 1)( ("APPLICATION" "PDF" ("NAME" "evidence.pdf") NIL NIL "BASE64" 12000000)("APPLICATION" "XML" ("NAME" "发票.xml") NIL NIL "BASE64" 3000) "MIXED") "MIXED"))'
        parts = m._invoice_bodystructure_parts(text)
        self.assertEqual([part['section'] for part in parts], ['1', '2.1', '2.2'])
        self.assertEqual(parts[1]['filename'], 'evidence.pdf')
        self.assertFalse(m._invoice_wire_size_allowed(parts[1], True))
        self.assertTrue(m._invoice_wire_size_allowed(parts[2], True))
        self.assertEqual(m._invoice_bodystructure_parts('broken BODYSTRUCTURE ("PDF")'), [])

    def test_selective_fetch_never_requests_oversized_sibling(self):
        parts = m._invoice_bodystructure_parts('1 (UID 42 BODYSTRUCTURE (("TEXT" "PLAIN" ("CHARSET" "UTF-8") NIL NIL "7BIT" 30 1)("APPLICATION" "PDF" ("NAME" "大发票.pdf") NIL NIL "BASE64" 12000000)("APPLICATION" "PDF" ("NAME" "小发票.pdf") NIL NIL "BASE64" 200) "MIXED"))')
        client = Mock(); client.select.return_value = ('OK', [b'1'])
        def fetch(command, uid, section):
            if 'HEADER' in section:
                data = b'Subject: invoice\r\nFrom: anonymous@example.com\r\nDate: Sat, 17 Oct 2026 10:30:00 +0800\r\n\r\n'
            elif '[1]' in section:
                data = b'Invoice download: https://example.com/a.pdf'
            elif '[3]' in section:
                data = base64.b64encode(b'%PDF-small')
            else:
                self.fail('Oversized attachment or whole message was requested: ' + section)
            return 'OK', [(b'1 (UID 42 BODY[] {1}', data), b')']
        client.uid.side_effect = fetch
        message, _ = m._fetch_size_filtered_invoice_message(client, '42', 'INBOX', parts)
        self.assertEqual(m._message_date(message), '2026-10-17 10:30')
        self.assertEqual(list(m._invoice_parts(message)), [('小发票.pdf', b'%PDF-small')])
        self.assertIn('https://example.com/a.pdf', m._extract_invoice_links(message))


if __name__ == '__main__':
    unittest.main()
