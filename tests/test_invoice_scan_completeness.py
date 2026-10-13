"""Invoice discovery regressions using anonymous mail and temporary storage."""
import datetime as dt
import io
import tempfile
import unittest
import zipfile
from contextlib import ExitStack
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import Mock, patch
from backend import qq_mail_mcp as m


class InvoiceCompletenessTests(unittest.TestCase):
    def scan(self, account, message, names, links=None, metadata=None, scan_cache=None, summaries=None, download_bundle=None):
        client = Mock()
        client.list.return_value = ('OK', [b'(\\Inbox) "/" "INBOX"'])
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            for name, value in {
                '_connect': client, '_uid_set_between': ['42'], '_collect_month_dir': Path(directory),
                '_load_summary_cache': {'mails': summaries or {}},
                '_load_scan_cache': scan_cache or {'version': m._SCAN_CACHE_VERSION, 'by_uid': {}},
                '_mail_attachment_names_map': {'42': names},
                '_mail_subjects_map': {'42': str(message['Subject'] or '')},
                '_fetch_message': (message, b''), '_extract_invoice_links': links or [],
                '_meta_for_file': metadata or {'amount': '120.00', 'issuer': '匿名销售方', 'parsed': True},
                '_save_scan_cache': None, '_save_summary_cache': None,
            }.items():
                stack.enter_context(patch.object(m, name, return_value=value))
            download = stack.enter_context(patch.object(m, '_download_invoice_link', side_effect=lambda url, *a, **k: download_bundle or {
                'filename': '链接发票.pdf', 'content': url.encode(), 'meta_hint': {},
            }))
            result = m.scan_invoices(account, start_date='2026-09-01', end_date='2026-09-30')
            paths = [row['path'] for row in result['invoices']]
            self.assertEqual(len(paths), len(set(paths)))
            contents = [Path(path).read_bytes() for path in paths]
            return result, contents, download.call_count

    def test_generic_attachment_and_multiple_same_name_links_all_survive_for_three_accounts(self):
        message = EmailMessage()
        message['Subject'] = '电子发票'
        message.set_content('请下载')
        message.add_attachment(b'%PDF-anonymous', maintype='application', subtype='pdf', filename='document.pdf')
        for account in m.MAILBOX_CONFIGS:
            with self.subTest(account=account):
                result, contents, calls = self.scan(account, message, ['document.pdf'], ['https://example.com/a.pdf','https://example.com/b.pdf'])
                self.assertEqual(result['total'], 3)
                self.assertEqual(calls, 2)
                self.assertEqual(len(set(contents)), 3)

    def test_generic_attachment_without_subject_hint_reaches_content_parser(self):
        message = EmailMessage()
        message['Subject'] = '您的文件'
        message.set_content('附件')
        message.add_attachment(b'%PDF-anonymous', maintype='application', subtype='pdf', filename='document.pdf')
        result, _, _ = self.scan('qq_mail', message, ['document.pdf'])
        self.assertEqual(result['total'], 1)

    def test_zip_invoice_discovery_and_path_isolation(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('../发票.pdf', b'%PDF-a')
            archive.writestr('nested/发票.pdf', b'%PDF-b')
            archive.writestr('readme.txt', b'ignored')
        message = EmailMessage()
        message['Subject'] = '文件包'
        message.set_content('附件')
        message.add_attachment(stream.getvalue(), maintype='application', subtype='zip', filename='files.zip')
        result, contents, _ = self.scan('netease_exmail', message, ['files.zip'])
        self.assertEqual(result['total'], 2)
        self.assertEqual(set(contents), {b'%PDF-a',b'%PDF-b'})

    def test_literal_continuations_do_not_drop_second_attachment(self):
        client = Mock()
        client.uid.return_value = ('OK', [
            (b'1 (UID 42 BODYSTRUCTURE (("APPLICATION" "PDF" ("NAME" {5}', b'a.pdf'),
            (b') NIL NIL "BASE64" 100)("APPLICATION" "PDF" ("NAME" {5}', b'b.pdf'),
            b') NIL NIL "BASE64" 100) "MIXED"))',
            b'2 (UID 43 BODYSTRUCTURE ("TEXT" "PLAIN" NIL NIL NIL "7BIT" 100 1))',
        ])
        self.assertEqual(m._mail_attachment_names_map(client, ['42','43']), {'42':['a.pdf','b.pdf'], '43':[]})

    def test_rfc2231_filename_is_percent_decoded(self):
        text = '("FILENAME*0*" "utf-8\'\'%E5%8F%91" "FILENAME*1*" "%E7%A5%A8.pdf")'
        self.assertEqual(m._extract_attachment_names_text(text), ['发票.pdf'])
        self.assertEqual(m._extract_attachment_names_text("(\"FILENAME*\" \"gbk''%B7%A2%C6%B1.pdf\")"), ['发票.pdf'])

    def test_failed_bodystructure_is_not_negative_cached(self):
        client = Mock()
        client.uid.return_value = ('NO', [b'unavailable'])
        self.assertEqual(m._mail_attachment_names_map(client,['42']), {})

    def test_mailbox_list_preserves_chinese_imap_names_and_skips_noselect(self):
        client = Mock()
        client.list.return_value = ('OK', [b'(\\Inbox) "/" "INBOX"', b'() "/" "&XfJT0ZAB-"', b'(\\Noselect) "/" "Parent"'])
        self.assertEqual(m._invoice_mailboxes(client), ['INBOX','"&XfJT0ZAB-"'])

    def test_folder_uids_do_not_share_storage_or_cache(self):
        client = Mock()
        client.list.return_value = ('OK', [b'() "/" "INBOX"', b'() "/" "Archive"'])
        message = EmailMessage()
        message['Subject'] = '电子发票'
        message.set_content('附件')
        message.add_attachment(b'%PDF-anonymous', maintype='application', subtype='pdf', filename='发票.pdf')
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            for name, value in {
                '_connect': client, '_uid_set_between': ['42'], '_collect_month_dir': Path(directory),
                '_load_summary_cache': {'mails': {}}, '_load_scan_cache': {'by_uid': {}},
                '_mail_attachment_names_map': {'42':['发票.pdf']}, '_mail_subjects_map': {'42':'电子发票'},
                '_fetch_message': (message,b''), '_extract_invoice_links': [],
                '_meta_for_file': {'amount':'120.00'}, '_save_scan_cache': None, '_save_summary_cache': None,
            }.items():
                stack.enter_context(patch.object(m,name, side_effect=lambda *a,_v=value,**k: __import__('copy').deepcopy(_v) if isinstance(_v,dict) else _v))
            result = m.scan_invoices('qq_exmail')
            self.assertEqual(result['total'],2)
            self.assertEqual(len(set(row['path'] for row in result['invoices'])),2)
            self.assertEqual(result['scanned_folders'],2)

    def test_sender_only_invoice_hint_loads_from_lightweight_headers(self):
        client=Mock()
        client.uid.return_value=('OK',[(b'1 (UID 42 BODY[HEADER.FIELDS (SUBJECT DATE FROM)] {100}',b'Subject: Your document\r\nFrom: invoice@info.nuonuo.com\r\nDate: Tue, 13 Oct 2026 09:00:00 +0800\r\n\r\n'), b')'])
        summaries={}
        m._mail_subjects_map(client,['42'],summaries)
        self.assertTrue(m._is_invoice_mail_hint(summaries['42']['subject'],summaries['42']['from']))

    def test_missing_cached_link_file_does_not_suppress_retry(self):
        message=EmailMessage();message['Subject']='电子发票';message.set_content('下载')
        cache={'by_uid':{'42':[]},'linked_uids':{'42':{'links':['https://example.com/a.pdf','https://example.com/b.pdf'], 'files':[{'filename':'missing.pdf','source_url':'https://example.com/a.pdf'}]}}}
        result,_,calls=self.scan('qq_mail',message,[],scan_cache=cache)
        self.assertEqual(calls,2)
        self.assertEqual(result['total'],2)

    def test_timeout_resumes_remaining_mail_and_retains_prior_rows(self):
        client=Mock()
        cache={'version':m._SCAN_CACHE_VERSION,'by_uid':{}}
        summary={'mails':{}}
        now=[0]
        first_run=[True]
        order=[]
        def fetch(client,uid,**kwargs):
            order.append(uid)
            message=EmailMessage();message['Subject']='附件';message.set_content('附件')
            message.add_attachment(('PDF-'+uid).encode(),maintype='application',subtype='pdf',filename='document.pdf')
            if first_run[0]:now[0]=6
            return message,b''
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            for name,value in {
                '_uid_set_between':['43','42'], '_collect_month_dir':Path(directory),
                '_load_scan_cache':cache,'_load_summary_cache':summary,
                '_mail_attachment_names_map':{'43':['document.pdf'],'42':['document.pdf']},
                '_mail_subjects_map':{'43':'附件','42':'附件'}, '_meta_for_file':{'amount':'120.00'},
                '_save_scan_cache':None,'_save_summary_cache':None,
            }.items():stack.enter_context(patch.object(m,name,return_value=value))
            stack.enter_context(patch.object(m,'_fetch_message',side_effect=fetch))
            stack.enter_context(patch.object(m._time,'monotonic',side_effect=lambda:now[0]))
            first=m._scan_invoice_mailbox('qq_mail',_client=client,_deadline=5)
            self.assertTrue(first['timed_out'])
            self.assertEqual(first['total'],1)
            now[0]=0;first_run[0]=False
            second=m._scan_invoice_mailbox('qq_mail',_client=client,_deadline=5)
            self.assertFalse(second['timed_out'])
            self.assertEqual(second['total'],2)
            self.assertEqual(order,['43','42'])
            self.assertEqual(cache['remaining_uids'],[])

    def test_folder_continuation_skips_already_completed_folders(self):
        client=Mock();cache={'version':m._SCAN_CACHE_VERSION,'by_uid':{}}
        clock=[0];visited=[]
        def scan(*args,**kwargs):
            mailbox=kwargs['_mailbox'];visited.append(mailbox)
            if mailbox=='INBOX':clock[0]=6
            return {'invoices':[{'uid':'42','filename':mailbox+'.pdf','path':'/anonymous/'+mailbox+'.pdf'}],
                    'total':1,'scanned_mails':1,'mailbox':mailbox,'timed_out':False,'warnings':[]}
        with tempfile.TemporaryDirectory() as directory,ExitStack() as stack:
            stack.enter_context(patch.object(m,'_connect',return_value=client))
            stack.enter_context(patch.object(m,'_invoice_mailboxes',return_value=['INBOX','Archive']))
            stack.enter_context(patch.object(m,'_collect_month_dir',return_value=Path(directory)))
            stack.enter_context(patch.object(m,'_load_scan_cache',return_value=cache))
            stack.enter_context(patch.object(m,'_save_scan_cache'))
            stack.enter_context(patch.object(m,'_scan_invoice_mailbox',side_effect=scan))
            stack.enter_context(patch.object(m,'_INVOICE_SCAN_MAX_SECONDS',5))
            stack.enter_context(patch.object(m._time,'monotonic',side_effect=lambda:clock[0]))
            first=m.scan_invoices('qq_mail')
            self.assertTrue(first['timed_out'])
            self.assertEqual(cache['remaining_mailboxes'],['Archive'])
            clock[0]=0
            second=m.scan_invoices('qq_mail')
            self.assertFalse(second['timed_out'])
            self.assertEqual(second['total'],2)
            self.assertEqual(visited,['INBOX','Archive'])
            self.assertEqual(cache['remaining_mailboxes'],[])

    def test_every_linked_zip_invoice_is_saved_and_listed(self):
        message=EmailMessage();message['Subject']='电子发票';message.set_content('下载发票')
        bundle={'filename':'发票1.xml','content':b'<Invoice>1</Invoice>',
                'additional_files':[{'filename':'发票2.xml','content':b'<Invoice>2</Invoice>'}]}
        result,contents,calls=self.scan('qq_exmail',message,[],['https://example.com/files.zip'],download_bundle=bundle)
        self.assertEqual(calls,1)
        self.assertEqual(result['total'],2)
        self.assertEqual(set(contents),{b'<Invoice>1</Invoice>',b'<Invoice>2</Invoice>'})

    def test_socket_timeout_reconnects_without_losing_scan_results(self):
        client=Mock();replacement=Mock();ref=[client]
        message=EmailMessage();message['Subject']='附件';message.set_content('附件')
        message.add_attachment(b'%PDF-anonymous',maintype='application',subtype='pdf',filename='document.pdf')
        with tempfile.TemporaryDirectory() as directory,ExitStack() as stack:
            for name,value in {'_connect':replacement,'_uid_set_between':['42'],'_collect_month_dir':Path(directory),
                '_load_scan_cache':{'by_uid':{}},'_load_summary_cache':{'mails':{}},
                '_mail_attachment_names_map':{'42':['document.pdf']},'_mail_subjects_map':{'42':'附件'},
                '_meta_for_file':{'amount':'120.00'},'_save_scan_cache':None,'_save_summary_cache':None,
            }.items():stack.enter_context(patch.object(m,name,return_value=value))
            fetch=stack.enter_context(patch.object(m,'_fetch_message',side_effect=[OSError('timed out'),(message,b'')]))
            result=m._scan_invoice_mailbox('qq_exmail',_client=client,_client_ref=ref)
            self.assertEqual(result['total'],1)
            self.assertEqual(result['warnings'],[])
            self.assertEqual(fetch.call_count,2)
            self.assertIs(ref[0],replacement)
            self.assertTrue(fetch.call_args.kwargs['_peek'])


if __name__ == '__main__':
    unittest.main()
