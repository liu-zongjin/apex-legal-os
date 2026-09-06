import datetime as dt
import json
import tempfile
import unittest
from email.message import EmailMessage
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

from backend import qq_mail_mcp


class QQMailCacheTests(unittest.TestCase):
    def test_inbox_summary_cache_keeps_legacy_per_account_path(self):
        self.assertEqual(qq_mail_mcp._summary_cache_path("qq_mail").name, "mail_summary_qq_mail.json")
        self.assertEqual(qq_mail_mcp._summary_cache_path("qq_mail", "sent").name, "mail_summary_qq_mail_sent.json")

    def test_mostly_english_requires_substantial_english_visible_text(self):
        self.assertTrue(qq_mail_mcp._mostly_english("This is an English email body with enough words to be classified as English."))
        self.assertTrue(qq_mail_mcp._mostly_english("Your authentication code 482913"))
        self.assertFalse(qq_mail_mcp._mostly_english("您好，this is a short English note，正文仍以中文为主。"))

    def test_issue_date_discards_appended_timestamp(self):
        self.assertEqual(qq_mail_mcp._clean_issue_time("2026-08-11 23:20:45"), "2026年08月11日")
        self.assertEqual(qq_mail_mcp._clean_issue_time("2026-03-0814:49:"), "2026年03月08日")
        self.assertEqual(qq_mail_mcp._clean_issue_time("2026年8月12日"), "2026年08月12日")

    def test_set_mail_read_updates_imap_seen_flag_and_summary_cache(self):
        client = Mock()
        client.select.return_value = ("OK", [b"1"])
        client.uid.return_value = ("OK", [b""])
        cache = {"mails": {"42": {"uid": "42", "read": False}}}
        with ExitStack() as stack:
            stack.enter_context(patch.object(qq_mail_mcp, "_connect", return_value=client))
            stack.enter_context(patch.object(qq_mail_mcp, "_load_summary_cache", return_value=cache))
            save = stack.enter_context(patch.object(qq_mail_mcp, "_save_summary_cache"))
            result = qq_mail_mcp.set_mail_read("42", True, "qq_mail")

        self.assertTrue(result["read"])
        self.assertTrue(cache["mails"]["42"]["read"])
        client.uid.assert_called_once_with("store", "42", "+FLAGS.SILENT", r"(\Seen)")
        save.assert_called_once_with("qq_mail", cache, "inbox")

    def test_raw_utf8_headers_are_not_replaced_with_garbled_text(self):
        raw = (
            b"From: \xe7\xa4\xba\xe4\xb8\x8a\xe6\x9f\x90 <message@gzac.org>\r\n"
            b"Subject: \xe5\x85\xb3\xe4\xba\x8e\xe6\x82\xa8\xe5\x8a\x9e\xe7\x90\x86\xe7\x9a\x84\xe7\x94\xb3\xe8\xaf\xb7\r\n\r\nbody"
        )
        message = __import__("email").message_from_bytes(raw)

        self.assertEqual(qq_mail_mcp._message_header(message, raw, "From"), "示上某 <message@gzac.org>")
        self.assertEqual(qq_mail_mcp._message_header(message, raw, "Subject"), "关于您办理的申请")

    def test_extracts_invoice_download_link_from_html_body(self):
        message = EmailMessage()
        message.set_content("点击链接查看发票：https://nnfp.jss.com.cn/example-token")
        message.add_alternative(
            '<p>您的发票已开具</p><a href="https://nnfp.jss.com.cn/example-token">下载发票</a>'
            '<a href="https://example.com/unsubscribe">退订</a>',
            subtype="html",
        )

        links = qq_mail_mcp._extract_invoice_links(message)

        self.assertEqual(links, ["https://nnfp.jss.com.cn/example-token"])

    def test_resolves_nuonuowang_page_to_real_pdf(self):
        page_url = (
            "https://nnfp.jss.com.cn/scan-invoice/printQrcode?"
            "paramList=tax!!!invoice!false&aliView=true&shortLinkSource=1"
        )
        api_payload = {
            "status": "0000",
            "data": {"invoiceSimpleVo": {
                "fphm": "12345678", "saleName": "测试销售方", "orderTotal": 88.5,
                "invoiceDate": "2026-08-12 10:00:00",
                "url": "https://inv.jss.com.cn/fp2/invoice.pdf",
            }},
        }
        responses = [
            (page_url, {"content-type": "text/html"}, b"<html></html>"),
            ("https://nnfp.jss.com.cn/sapi/scan2/getIvcDetailShow.do",
             {"content-type": "application/json"}, json.dumps(api_payload).encode()),
            ("https://inv.jss.com.cn/fp2/invoice.pdf",
             {"content-type": "application/pdf"}, b"%PDF-test"),
        ]
        with patch.object(qq_mail_mcp, "_safe_http_request", side_effect=responses):
            result = qq_mail_mcp._download_invoice_link(
                "https://nnfp.jss.com.cn/example-token", [".pdf"]
            )

        self.assertEqual(result["content"], b"%PDF-test")
        self.assertIn("12345678", result["filename"])
        self.assertEqual(result["meta_hint"]["amount"], "88.50")

    def test_list_mails_reuses_summary_cache_for_filtered_views(self):
        client = Mock()
        client.logout = Mock()
        cached = {"mails": {"42": {
            "uid": "42", "date": "2026-08-20 10:00", "from": "sender@example.com",
            "subject": "电子发票", "attachments": ["发票.pdf"],
            "attachment_count": 1, "read": True,
        }}}
        forbidden = Mock(side_effect=AssertionError("cached filtered mail must not be downloaded"))
        with ExitStack() as stack:
            stack.enter_context(patch.object(qq_mail_mcp, "_connect", return_value=client))
            stack.enter_context(patch.object(qq_mail_mcp, "_uid_set", return_value=["42"]))
            stack.enter_context(patch.object(qq_mail_mcp, "_all_unread_uids", return_value={"42"}))
            stack.enter_context(patch.object(qq_mail_mcp, "_load_summary_cache", return_value=cached))
            stack.enter_context(patch.object(qq_mail_mcp, "_fetch_message", forbidden))
            stack.enter_context(patch.object(qq_mail_mcp, "_fetch_summaries", forbidden))
            rows = qq_mail_mcp.list_mails(
                limit=30, unread_only=True, keyword="发票", account="qq_mail"
            )

        self.assertEqual([row["uid"] for row in rows], ["42"])
        self.assertFalse(rows[0]["read"])
        forbidden.assert_not_called()
        client.logout.assert_called_once()

    def test_uid_set_between_uses_server_side_complete_date_range(self):
        client = Mock()
        client.select.return_value = ("OK", [b"10"])
        client.uid.return_value = ("OK", [b"10 11 12"])

        result = qq_mail_mcp._uid_set_between(
            client, dt.date(2026, 7, 1), dt.date(2026, 7, 31), limit=2000
        )

        self.assertEqual(result, ["12", "11", "10"])
        client.uid.assert_called_once_with(
            "search", None, "SINCE 01-Jul-2026 BEFORE 01-Aug-2026"
        )

    def test_scan_invoices_reuses_downloaded_file_and_metadata(self):
        client = Mock()
        client.logout = Mock()
        summary = {
            "uid": "88", "date": "2026-08-12 09:00", "from": "billing@example.com",
            "subject": "电子发票", "attachments": ["电子发票.pdf"],
            "attachment_count": 1, "read": True,
        }
        scan_cache = {
            "version": qq_mail_mcp._SCAN_CACHE_VERSION,
            "by_uid": {"88": ["电子发票.pdf"]},
        }
        metadata = {
            "issuer": "测试公司", "amount": "100.00", "issue_time": "2026年08月12日",
            "parsed": True, "method": "pdf",
        }
        forbidden = Mock(side_effect=AssertionError("downloaded invoice must not be fetched again"))
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "invoices"
            folder.mkdir()
            target = folder / qq_mail_mcp._safe_filename("88", "电子发票.pdf")
            target.write_bytes(b"already downloaded")
            with ExitStack() as stack:
                stack.enter_context(patch.object(qq_mail_mcp, "_connect", return_value=client))
                stack.enter_context(patch.object(qq_mail_mcp, "_uid_set_between", return_value=["88"]))
                stack.enter_context(patch.object(qq_mail_mcp, "_collect_month_dir", return_value=folder))
                stack.enter_context(patch.object(qq_mail_mcp, "_load_summary_cache", return_value={"mails": {"88": summary}}))
                stack.enter_context(patch.object(qq_mail_mcp, "_load_scan_cache", return_value=scan_cache))
                stack.enter_context(patch.object(qq_mail_mcp, "_save_scan_cache"))
                stack.enter_context(patch.object(qq_mail_mcp, "_save_summary_cache"))
                stack.enter_context(patch.object(qq_mail_mcp, "_meta_for_file", return_value=metadata))
                stack.enter_context(patch.object(qq_mail_mcp, "_fetch_message", forbidden))
                result = qq_mail_mcp.scan_invoices(
                    "qq_mail", start_date="2026-08-01", end_date="2026-08-20"
                )

            self.assertEqual(result["total"], 1)
            self.assertEqual(result["invoices"][0]["path"], str(target))
        forbidden.assert_not_called()
        client.logout.assert_called_once()


if __name__ == "__main__":
    unittest.main()
