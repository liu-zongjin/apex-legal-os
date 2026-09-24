import datetime as dt
import json
import smtplib
import sys
import tempfile
import unittest
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from contextlib import ExitStack
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PyPDF2 import PdfWriter

from backend import qq_mail_mcp


class QQMailCacheTests(unittest.TestCase):
    def test_netease_enterprise_mailbox_is_registered_with_private_credentials(self):
        config = qq_mail_mcp.MAILBOX_CONFIGS["netease_exmail"]

        self.assertEqual(config["label"], "网易企业邮箱")
        self.assertEqual(config["host"], "imap.qiye.163.com")
        self.assertEqual(config["address_env"], "NETEASE_EXMAIL_ADDRESS")
        self.assertEqual(config["code_env"], "NETEASE_EXMAIL_AUTH_CODE")
        self.assertIn("mail.qiye.163.com/static/sirius-web", config["portal_url"])

    def test_netease_enterprise_mailbox_uses_ssl_smtp(self):
        self.assertEqual(qq_mail_mcp.SMTP_HOSTS["netease_exmail"], ("smtp.qiye.163.com", 465))
        self.assertTrue(qq_mail_mcp.MAILBOX_CONFIGS["netease_exmail"]["smtp_server_saves_sent"])

    def test_netease_enterprise_mailbox_uses_its_chinese_imap_folders(self):
        self.assertEqual(qq_mail_mcp._folder_name("sent", "netease_exmail"), "&XfJT0ZAB-")
        self.assertEqual(qq_mail_mcp._folder_name("drafts", "netease_exmail"), "&g0l6P3ux-")
        self.assertEqual(qq_mail_mcp._folder_name("sent", "qq_mail"), '"Sent Messages"')

    def test_enterprise_mail_can_use_separate_internal_login_address(self):
        with patch.object(qq_mail_mcp.ai_config, "EXMAIL_ADDRESS", "alias@example.com"), \
                patch.object(qq_mail_mcp.ai_config, "EXMAIL_LOGIN", "member@tenant.wecom.work"), \
                patch.object(qq_mail_mcp.ai_config, "EXMAIL_AUTH_CODE", "client-password"):
            self.assertEqual(qq_mail_mcp._address("qq_exmail"), "alias@example.com")
            self.assertEqual(qq_mail_mcp._login_address("qq_exmail"), "member@tenant.wecom.work")
            self.assertEqual(qq_mail_mcp._login_credentials("qq_exmail"), ("member@tenant.wecom.work", "client-password"))

    def test_netease_send_does_not_append_a_second_sent_copy(self):
        client = Mock()
        with ExitStack() as stack:
            stack.enter_context(patch.object(qq_mail_mcp, "_credentials", return_value=("sender@example.com", "auth-code")))
            stack.enter_context(patch.object(qq_mail_mcp, "_login_address", return_value="sender@example.com"))
            stack.enter_context(patch.object(smtplib, "SMTP_SSL", return_value=client))
            append = stack.enter_context(patch.object(qq_mail_mcp, "_append_message"))
            stack.enter_context(patch.object(qq_mail_mcp, "_record_contacts"))

            result = qq_mail_mcp.send_mail(
                "netease_exmail", "recipient@example.com", "测试邮件", "正文",
            )

        self.assertTrue(result["success"])
        self.assertTrue(result["submitted_to_smtp"])
        self.assertTrue(result["saved_to_sent"])
        append.assert_not_called()
        client.sendmail.assert_called_once()
        client.quit.assert_called_once()

    def test_netease_cloud_attachment_is_uploaded_before_smtp(self):
        client = Mock()
        client.sendmail.return_value = {}
        calls = []

        def cloud_request(method, path, **kwargs):
            calls.append((method, path, kwargs))
            if method == "GET":
                return {"code": 0, "data": {
                    "bucketName": "bucket", "nosKey": "folder/report.pdf",
                    "fileId": 17, "token": "upload-token",
                }}
            if method == "POST":
                return {"code": 0, "data": {
                    "identity": "cloud-17",
                    "downloadUrl": "https://maild.qiye.163.com/cloud/report.pdf",
                    "expireTime": 1790000000000,
                }}
            return {}

        with ExitStack() as stack:
            stack.enter_context(patch.object(qq_mail_mcp, "_credentials", return_value=("sender@example.com", "auth-code")))
            stack.enter_context(patch.object(qq_mail_mcp, "_login_address", return_value="sender@example.com"))
            stack.enter_context(patch.object(qq_mail_mcp, "_netease_web_cookie", return_value="sid=web-session"))
            stack.enter_context(patch.object(qq_mail_mcp, "_netease_cloud_request", side_effect=cloud_request))
            stack.enter_context(patch.object(smtplib, "SMTP_SSL", return_value=client))
            stack.enter_context(patch.object(qq_mail_mcp, "_record_contacts"))

            result = qq_mail_mcp.send_mail(
                "netease_exmail", "recipient@example.com", "云附件测试", "正文",
                attachments=[{"filename": "report.pdf", "content": b"pdf-bytes"}],
                use_cloud_attachments=True,
            )

        self.assertEqual(result["cloud_attachment_count"], 1)
        self.assertEqual(result["cloud_attachment_mode"], "netease_cloud_link")
        self.assertEqual([item[0] for item in calls], ["GET", "PUT", "POST"])
        self.assertTrue(calls[2][2]["form_body"])
        sent = client.sendmail.call_args.args[2]
        self.assertNotIn(b'Content-Disposition: attachment', sent)
        self.assertNotIn(b"pdf-bytes", sent)
        self.assertIn(b"Content-Type: text/plain", sent)
        parsed = BytesParser(policy=policy.default).parsebytes(sent)
        plain = next(part for part in parsed.walk() if part.get_content_type() == "text/plain").get_content()
        self.assertIn("企业邮箱云附件：", plain)
        self.assertNotIn("网易云附件（文件已上传", plain)
        self.assertIn("0.00M", plain)
        self.assertIn("过期时间：2026-09-21 22:13:20", plain)
        self.assertIn("https://maild.qiye.163.com/cloud/report.pdf", plain)
        html = next(part for part in parsed.walk() if part.get_content_type() == "text/html").get_content()
        self.assertIn("网易企业邮箱云附件", html)
        self.assertIn('data-cloud-expire-at="1790000000000"', html)
        self.assertIn("过期时间：2026-09-21 22:13:20", html)
        self.assertIn(">下载</a>", html)

    def test_netease_cloud_session_check_does_not_upload_a_file(self):
        calls = []

        def cloud_request(method, path, **kwargs):
            calls.append((method, path, kwargs))
            return {"code": 0, "data": {
                "bucketName": "bucket", "nosKey": "session-check", "token": "upload-token",
            }}

        with patch.object(qq_mail_mcp, "_netease_cloud_request", side_effect=cloud_request):
            result = qq_mail_mcp.check_netease_cloud_session()

        self.assertTrue(result["ok"])
        self.assertEqual(result["message"], "网易云附件网页会话有效")
        self.assertEqual([item[0] for item in calls], ["GET"])
        self.assertEqual(calls[0][2]["query"]["fileName"], "apex-cloud-session-check.txt")

    def test_qq_large_attachment_uses_qq_transfer_station_before_smtp(self):
        client = Mock()
        client.sendmail.return_value = {}
        calls = []
        content = b"qq-large-file"

        def qq_request(method, path, **kwargs):
            calls.append((method, path, kwargs))
            if path == qq_mail_mcp.QQ_FTN_CREATE_PATH:
                return {"errcode": 0, "sUploadUrl": "https://gzc-dfsup.mail.ftn.qq.com/upload/abc"}
            return {"errcode": 0, "oFiles": [{
                "sName": "large.pdf", "nSize": len(content), "sFileId": "fid-1",
                "sFetchCode": "fetch-1", "sKey": "key-1", "nExpireTime": 3600,
            }]}

        with ExitStack() as stack:
            stack.enter_context(patch.object(qq_mail_mcp, "_credentials", return_value=("sender@qq.com", "auth-code")))
            stack.enter_context(patch.object(qq_mail_mcp, "_login_address", return_value="sender@qq.com"))
            stack.enter_context(patch.object(qq_mail_mcp, "_qq_web_cookie", return_value="sid=web-session"))
            stack.enter_context(patch.object(qq_mail_mcp, "_qq_sid", return_value="sid-1"))
            stack.enter_context(patch.object(qq_mail_mcp, "_qq_web_request", side_effect=qq_request))
            upload = stack.enter_context(patch.object(qq_mail_mcp, "_qq_upload_bytes", return_value={}))
            stack.enter_context(patch.object(smtplib, "SMTP_SSL", return_value=client))
            stack.enter_context(patch.object(qq_mail_mcp, "_record_contacts"))

            result = qq_mail_mcp.send_mail(
                "qq_mail", "recipient@example.com", "QQ超大附件测试", "正文",
                attachments=[{"filename": "large.pdf", "content": content}],
                use_large_attachments=True,
            )

        self.assertEqual(result["large_attachment_count"], 1)
        self.assertEqual(result["large_attachment_mode"], "qq_ftn_link")
        self.assertEqual([item[1] for item in calls], [qq_mail_mcp.QQ_FTN_CREATE_PATH, qq_mail_mcp.QQ_FTN_LIST_PATH])
        upload.assert_called_once()
        sent = client.sendmail.call_args.args[2]
        self.assertNotIn(b"Content-Disposition: attachment", sent)
        self.assertNotIn(content, sent)
        parsed = BytesParser(policy=policy.default).parsebytes(sent)
        plain = next(part for part in parsed.walk() if part.get_content_type() == "text/plain").get_content()
        self.assertIn("QQ邮箱超大附件：", plain)
        self.assertIn("https://mail.qq.com/cgi-bin/ftnDownload302", plain)
        self.assertIn("剩余有效期：", plain)

    def test_qq_large_attachment_session_check(self):
        with ExitStack() as stack:
            stack.enter_context(patch.object(qq_mail_mcp, "_qq_sid", return_value="sid-1"))
            request = stack.enter_context(patch.object(
                qq_mail_mcp,
                "_qq_current_web_request",
                return_value={"head": {"ret": 0, "msg": ""}, "body": {"space_limited": 1024}},
            ))
            result = qq_mail_mcp.check_qq_large_attachment_session()

        self.assertTrue(result["ok"])
        self.assertEqual(result["message"], "QQ邮箱超大附件网页会话有效")
        request.assert_called_once()
        self.assertEqual(request.call_args.args[0], qq_mail_mcp.QQ_FTN_CURRENT_USERINFO_PATH)
        self.assertEqual(request.call_args.kwargs["params"], {"bizid": 2})

    def test_send_rejects_oversized_mime_message_before_smtp(self):
        client = Mock()
        with ExitStack() as stack:
            stack.enter_context(patch.object(qq_mail_mcp, "_credentials", return_value=("sender@example.com", "auth-code")))
            stack.enter_context(patch.object(qq_mail_mcp, "_login_address", return_value="sender@example.com"))
            stack.enter_context(patch.object(smtplib, "SMTP_SSL", return_value=client))
            stack.enter_context(patch.object(qq_mail_mcp, "MAX_SMTP_MESSAGE_BYTES", 64))

            with self.assertRaisesRegex(qq_mail_mcp.QQMailMCPError, "超过普通 SMTP 安全上限"):
                qq_mail_mcp.send_mail(
                    "qq_mail", "recipient@example.com", "大附件测试", "正文",
                )

        client.assert_not_called()

    def test_send_reports_smtp_refused_recipients(self):
        client = Mock()
        client.sendmail.return_value = {"recipient@example.com": (552, b"message size limit")}
        with ExitStack() as stack:
            stack.enter_context(patch.object(qq_mail_mcp, "_credentials", return_value=("sender@example.com", "auth-code")))
            stack.enter_context(patch.object(qq_mail_mcp, "_login_address", return_value="sender@example.com"))
            stack.enter_context(patch.object(smtplib, "SMTP_SSL", return_value=client))
            stack.enter_context(patch.object(qq_mail_mcp, "_record_contacts"))

            with self.assertRaisesRegex(qq_mail_mcp.QQMailMCPError, "recipient@example.com.*552.*message size limit"):
                qq_mail_mcp.send_mail(
                    "netease_exmail", "recipient@example.com", "拒收测试", "正文",
                )

        client.quit.assert_called_once()

    def test_oversized_pdf_is_split_into_deliverable_messages(self):
        pdf = BytesIO()
        writer = PdfWriter()
        for _ in range(5):
            writer.add_blank_page(width=72, height=72)
        writer.write(pdf)
        client = Mock()
        client.sendmail.return_value = {}
        with ExitStack() as stack:
            stack.enter_context(patch.object(qq_mail_mcp, "_credentials", return_value=("sender@example.com", "auth-code")))
            stack.enter_context(patch.object(qq_mail_mcp, "_login_address", return_value="sender@example.com"))
            stack.enter_context(patch.object(smtplib, "SMTP_SSL", return_value=client))
            stack.enter_context(patch.object(qq_mail_mcp, "_record_contacts"))
            stack.enter_context(patch.object(qq_mail_mcp, "_netease_web_cookie", return_value=""))
            stack.enter_context(patch.object(qq_mail_mcp, "MAX_SMTP_MESSAGE_BYTES", 1500))

            result = qq_mail_mcp.send_mail(
                "netease_exmail", "recipient@example.com", "分卷测试", "正文",
                attachments=[{"filename": "large.pdf", "content": pdf.getvalue()}],
            )

        self.assertTrue(result["split_into_parts"])
        self.assertTrue(result["cloud_attempted"])
        self.assertIn("网页版会话", result["cloud_fallback_reason"])
        self.assertGreater(result["submitted_messages"], 1)
        self.assertEqual(client.sendmail.call_count, result["submitted_messages"])
        self.assertTrue(all(len(call.args[2]) <= 1500 for call in client.sendmail.call_args_list))

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

    def test_invoice_xml_parser_accepts_zip_wrapped_tax_xml(self):
        import zipfile

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "链接发票.xml"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(
                    "invoice.xml",
                    """<?xml version='1.0'?><EInvoice><EInvoiceData>
                    <SellerInformation><SellerName>测试销售方有限公司</SellerName></SellerInformation>
                    <TotalTax-includedAmount>335.00</TotalTax-includedAmount>
                    <IssueTime>20260912</IssueTime></EInvoiceData></EInvoice>""",
                )

            result = qq_mail_mcp.parse_invoice_metadata(path)

        self.assertEqual(result["issuer"], "测试销售方有限公司")
        self.assertEqual(result["amount"], "335.00")
        self.assertEqual(result["issue_time"], "2026年09月12日")
        self.assertTrue(result["parsed"])

    def test_pdf_parser_prefers_seller_and_tax_included_total(self):
        class FakeDocument:
            def __iter__(self):
                return iter([SimpleNamespace(get_text=lambda mode: """价税合计（大写）
（小写）
¥331.68
¥3.32
¥335.00
示例律师事务所（虚构）
东莞市大朗沃平早餐店
销方开户银行:工行广州挹翠支行
开票日期：2026年09月12日""")])

            def close(self):
                pass

        fake_fitz = SimpleNamespace(open=lambda path: FakeDocument())
        with tempfile.NamedTemporaryFile(suffix=".pdf") as file, patch.dict(sys.modules, {"fitz": fake_fitz}):
            result = qq_mail_mcp.parse_invoice_metadata(Path(file.name))

        self.assertEqual(result["issuer"], "东莞市大朗沃平早餐店")
        self.assertEqual(result["amount"], "335.00")
        self.assertEqual(result["issue_time"], "2026年09月12日")

    def test_invoice_hint_accepts_body_link_mail_without_attachment_name(self):
        self.assertTrue(qq_mail_mcp._is_invoice_mail_hint(
            "您收到一张电子发票", "billing@example.com", [],
        ))
        self.assertTrue(qq_mail_mcp._is_invoice_mail_hint(
            "通知", "invoice@info.nuonuo.com", [],
        ))

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
            '<a href="https://example.com/unsubscribe">退订</a>'
            '<img src="https://nnfp.jss.com.cn/nnwzfblogo.png" />',
            subtype="html",
        )

        links = qq_mail_mcp._extract_invoice_links(message)

        self.assertEqual(links, ["https://nnfp.jss.com.cn/example-token"])

    def test_extracts_tax_platform_invoice_links_with_format_query(self):
        message = EmailMessage()
        message.add_alternative(
            '<a href="https://dppt.guangdong.chinatax.gov.cn:8443/kpfw/fpjfzz/v1/'
            'exportDzfpwjEwm?Wjgs=PDF&amp;Fphm=26442000010498484296&amp;Kprq=20260912" '
            'title="点击下载电子发票PDF文件">点击下载PDF</a>',
            subtype="html",
        )

        links = qq_mail_mcp._extract_invoice_links(message)

        self.assertEqual(len(links), 1)
        self.assertIn("Wjgs=PDF", links[0])
        self.assertIn("Fphm=26442000010498484296", links[0])

    def test_linked_file_extension_uses_tax_platform_format_query(self):
        url = "https://dppt.guangdong.chinatax.gov.cn:8443/exportDzfpwjEwm?Wjgs=OFD&Fphm=123"

        self.assertEqual(
            qq_mail_mcp._linked_file_extension(
                url, {"content-type": "application/octet-stream"}, b"PK\x03\x04test"
            ),
            ".ofd",
        )

    def test_download_invoice_link_forwards_timeout_budget(self):
        url = "https://example.com/invoice.pdf"
        with patch.object(
            qq_mail_mcp,
            "_safe_http_request",
            return_value=(url, {"content-type": "application/pdf"}, b"%PDF-test"),
        ) as request:
            result = qq_mail_mcp._download_invoice_link(
                url, [".pdf"], timeout=(1.0, 2.0), deadline=123.0
            )

        self.assertIsNotNone(result)
        self.assertTrue(result["filename"].endswith(".pdf"))
        request.assert_called_once_with(url, timeout=(1.0, 2.0), deadline=123.0)

    def test_tax_platform_8443_is_allowed_but_other_alt_ports_are_not(self):
        with patch.object(qq_mail_mcp.socket, "getaddrinfo", return_value=[(None, None, None, None, ("8.8.8.8", 0))]):
            qq_mail_mcp._validate_public_http_url(
                "https://dppt.guangdong.chinatax.gov.cn:8443/exportDzfpwjEwm?Wjgs=PDF"
            )
            with self.assertRaises(qq_mail_mcp.QQMailMCPError):
                qq_mail_mcp._validate_public_http_url("https://example.com:8443/invoice.pdf")

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

    def test_scan_invoices_downloads_inline_tax_invoice_link(self):
        client = Mock()
        client.logout = Mock()
        message = EmailMessage()
        message["Subject"] = "您收到一张发票"
        message["From"] = "billing@example.com"
        message.set_content("请点击下载发票")
        source_url = "https://dppt.guangdong.chinatax.gov.cn:8443/exportDzfpwjEwm?Wjgs=PDF&Fphm=123"
        metadata = {
            "issuer": "测试销售方", "amount": "335.00", "issue_time": "2026年09月12日",
            "parsed": True, "method": "pdf",
        }
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "invoices"
            folder.mkdir()
            with ExitStack() as stack:
                stack.enter_context(patch.object(qq_mail_mcp, "_connect", return_value=client))
                stack.enter_context(patch.object(qq_mail_mcp, "_uid_set_between", return_value=["5710", "5711"]))
                stack.enter_context(patch.object(qq_mail_mcp, "_collect_month_dir", return_value=folder))
                stack.enter_context(patch.object(qq_mail_mcp, "_load_summary_cache", return_value={"mails": {}}))
                stack.enter_context(patch.object(qq_mail_mcp, "_load_scan_cache", return_value={
                    "version": qq_mail_mcp._SCAN_CACHE_VERSION, "by_uid": {}, "linked_uids": {},
                }))
                stack.enter_context(patch.object(qq_mail_mcp, "_save_scan_cache"))
                stack.enter_context(patch.object(qq_mail_mcp, "_save_summary_cache"))
                stack.enter_context(patch.object(qq_mail_mcp, "_mail_attachment_names_map", return_value={"5710": [], "5711": []}))
                stack.enter_context(patch.object(qq_mail_mcp, "_mail_subjects_map", return_value={"5710": "您收到一张发票", "5711": "转发：您收到一张发票"}))
                stack.enter_context(patch.object(qq_mail_mcp, "_fetch_message", return_value=(message, b"")))
                stack.enter_context(patch.object(qq_mail_mcp, "_extract_invoice_links", return_value=[source_url]))
                download = stack.enter_context(patch.object(qq_mail_mcp, "_download_invoice_link", return_value={
                    "filename": "电子发票_123.pdf", "content": b"%PDF-test",
                    "source_url": source_url, "meta_hint": {},
                }))
                stack.enter_context(patch.object(qq_mail_mcp, "_meta_for_file", return_value=metadata))

                result = qq_mail_mcp.scan_invoices(
                    "qq_mail", start_date="2026-09-01", end_date="2026-09-13"
                )

            self.assertEqual(result["total"], 1)
            self.assertEqual(result["invoices"][0]["source_type"], "link")
            self.assertTrue(result["invoices"][0]["parsed"])
            self.assertEqual(result["invoices"][0]["filename"], "电子发票_123.pdf")
            self.assertEqual(download.call_count, 1)
        client.logout.assert_called_once()


if __name__ == "__main__":
    unittest.main()
