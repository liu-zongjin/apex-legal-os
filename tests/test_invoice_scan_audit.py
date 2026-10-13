import json
import os
import sys
import tempfile
import threading
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from backend import qq_mail_mcp as m


class InvoiceScanAuditTests(unittest.TestCase):
    def test_negative_currency_and_decimal_rounding(self):
        for value,expected in [('￥-1,234.50','-1234.50'),('−￥1,234.50','-1234.50'),('(100.25)','-100.25'),('1.005','1.01'),('invalid','')]:
            self.assertEqual(m._clean_amount(value),expected)
        self.assertEqual(m._clean_issue_time('2026-02-30'),'')
        self.assertEqual(m._clean_issue_time('2024-02-29'),'2024年02月29日')

    def test_capital_rmb_total_recovers_missing_or_rotated_numeric_ocr(self):
        for text,amount in [('壹万贰仟肆佰玖拾圆整','12490.00'),('负壹佰元伍角贰分','-100.52'),('贰亿叁仟万伍佰元整','230000500.00'),('零元零伍分','0.05')]:
            self.assertEqual(m._capital_invoice_amount(text),amount)
        meta=m._parse_invoice_text('电子发票 发票号码：26442000010000000001 价税合计（大写） &壹万贰仟肆佰玖拾圆整 00•06万ZI天')
        self.assertEqual(meta['amount'],'12490.00')

    def test_xml_negative_amount_and_tax_inclusive_total(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'invoice.xml'
            p.write_text('<Invoice><SellerName>匿名销售方</SellerName><InvoiceNumber>26442000010000000001</InvoiceNumber><TotalTaxIncludedAmount>-100.00</TotalTaxIncludedAmount><IssueTime>20260901</IssueTime></Invoice>')
            meta=m.parse_invoice_metadata(p)
            self.assertEqual(meta['amount'],'-100.00');self.assertEqual(meta['invoice_number'],'26442000010000000001')
            p.write_text('<Invoice><TotalAmWithoutTax>300.00</TotalAmWithoutTax><TotalTaxAm>35.00</TotalTaxAm><Items><Amount>10.00</Amount></Items></Invoice>')
            self.assertEqual(m.parse_invoice_metadata(p)['amount'],'335.00')

    def test_pdf_rejects_ordinary_money_document_and_preserves_credit_invoice(self):
        class Document:
            def __iter__(self):return iter([SimpleNamespace(get_text=lambda mode:text[0])])
            def close(self):pass
        text=['合同款 ￥100.00 匿名有限公司 2026年09月01日']
        with patch.dict(sys.modules,{'fitz':SimpleNamespace(open=lambda path:Document())}):
            self.assertEqual(m._parse_pdf_invoice(Path('contract.pdf')),{})
            text[0]='电子发票\n价税合计（小写） -￥100.50\n发票号码：26442000010000000001'
            meta=m._parse_pdf_invoice(Path('invoice.pdf'))
            self.assertEqual(meta['amount'],'-100.50');self.assertEqual(meta['invoice_number'],'26442000010000000001')
            text[0]='增值税电子发票 发票号码：12345678 发票代码：144000123456 价税合计 ￥100.50'
            meta=m._parse_pdf_invoice(Path('invoice.pdf'));self.assertEqual(meta['invoice_number'],'12345678');self.assertEqual(meta['invoice_code'],'144000123456')
            text[0]='法律服务合同 甲方应当依法开具发票 服务费 ￥100.00'
            self.assertEqual(m._parse_pdf_invoice(Path('contract.pdf')),{})

    def test_ofd_negative_currency(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'invoice.ofd'
            with zipfile.ZipFile(path,'w') as archive:
                archive.writestr('Doc_0/Pages/Page_0/Content.xml','<Page><TextCode>电子发票</TextCode><TextCode>-￥100.50</TextCode></Page>')
            self.assertEqual(m._parse_ofd_invoice(path)['amount'],'-100.50')

    def test_tabular_csv_uses_values_not_column_headers(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'invoice.csv'
            path.write_text('发票类型,开票时间,发票金额（元）,付款方,收款方,发票号码,发票代码,费用备注\n电子发票,2026-09-01,-100.50,匿名买方,匿名销售方,26442000010000000001,,服务费\n')
            meta=m.parse_invoice_metadata(path)
            self.assertEqual(meta['issuer'],'匿名销售方');self.assertEqual(meta['amount'],'-100.50')
            self.assertEqual(meta['invoice_number'],'26442000010000000001')

    def test_invoice_image_uses_existing_local_ocr_and_generic_images_are_skipped(self):
        text='电子发票 发票号码：26442000010000000001 价税合计 100.50'
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'发票.png';path.write_bytes(b'image')
            with patch('backend.court_directory._vision_ocr_image',return_value=text) as ocr:
                self.assertEqual(m.parse_invoice_metadata(path)['amount'],'100.50')
                generic=Path(directory)/'logo.png';generic.write_bytes(b'image')
                self.assertFalse(m.parse_invoice_metadata(generic)['parsed']);self.assertEqual(ocr.call_count,1)

    def test_jpg_filter_includes_jpeg(self):
        self.assertEqual(set(m._normalize_invoice_extensions(['.jpg'])),{'.jpg','.jpeg'})
        self.assertEqual(set(m._normalize_invoice_extensions(['.jpeg'])),{'.jpg','.jpeg'})

    def test_unnamed_document_parts_are_discovered_without_affecting_regular_mail_listing(self):
        client=Mock();client.uid.return_value=('OK',[b'1 (UID 42 BODYSTRUCTURE ("APPLICATION" "PDF" NIL NIL NIL "BASE64" 100))'])
        self.assertEqual(m._mail_attachment_names_map(client,['42']),{'42':[]})
        self.assertEqual(m._mail_attachment_names_map(client,['42'],infer_unnamed=True),{'42':['__unnamed_attachment.pdf']})
        msg=EmailMessage();msg.set_content('invoice');msg.add_attachment(b'%PDF-anonymous',maintype='application',subtype='pdf')
        files=list(m._invoice_parts(msg));self.assertEqual(len(files),1);self.assertTrue(files[0][0].endswith('.pdf'))

    def test_bad_zip_does_not_drop_sibling_invoice(self):
        msg=EmailMessage();msg.set_content('invoice')
        msg.add_attachment(b'%PDF-anonymous',maintype='application',subtype='pdf',filename='发票.pdf')
        msg.add_attachment(b'bad archive',maintype='application',subtype='zip',filename='bad.zip')
        errors=[];files=list(m._invoice_parts(msg,errors=errors))
        self.assertEqual(files,[('发票.pdf',b'%PDF-anonymous')]);self.assertEqual(errors[0]['filename'],'bad.zip')

    def test_bounded_passes_eventually_cover_all_older_uids(self):
        client=Mock();ids=[str(i) for i in range(2501,0,-1)]
        cache={'version':m._SCAN_CACHE_VERSION,'by_uid':{}}
        summaries={'mails':{uid:{'uid':uid,'subject':'通知','from':'anonymous@example.com'} for uid in ids}}
        with tempfile.TemporaryDirectory() as directory,ExitStack() as stack:
            for name,value in {'_uid_set_between':ids,'_collect_month_dir':Path(directory),'_load_scan_cache':cache,
                               '_load_summary_cache':summaries,'_save_scan_cache':None,'_save_summary_cache':None}.items():
                stack.enter_context(patch.object(m,name,return_value=value))
            stack.enter_context(patch.object(m,'_mail_attachment_names_map',side_effect=lambda c,u,**k:{uid:[] for uid in u}))
            forbidden=stack.enter_context(patch.object(m,'_fetch_message',side_effect=AssertionError('no body needed')))
            results=[m._scan_invoice_mailbox('qq_mail',limit=1000,_client=client) for _ in range(3)]
        self.assertEqual([r['scanned_mails'] for r in results],[1000,2000,2501])
        self.assertEqual([r['timed_out'] for r in results],[True,True,False]);self.assertEqual(cache['remaining_uids'],[])
        forbidden.assert_not_called()

    def test_uidvalidity_reset_does_not_reuse_old_file_and_summary(self):
        client=Mock();client.response.return_value=('UIDVALIDITY',[b'2'])
        msg=EmailMessage();msg['Subject']='电子发票';msg.set_content('invoice')
        msg.add_attachment(b'%PDF-new',maintype='application',subtype='pdf',filename='发票.pdf')
        cache={'version':m._SCAN_CACHE_VERSION,'uidvalidity':'1','by_uid':{'42':['发票.pdf']}}
        with tempfile.TemporaryDirectory() as directory,ExitStack() as stack:
            root=Path(directory);old=root/m._safe_filename('42','发票.pdf');old.write_bytes(b'%PDF-old')
            for name,value in {'_uid_set_between':['42'],'_collect_month_dir':root,'_load_scan_cache':cache,
                 '_load_summary_cache':{'mails':{'42':{'subject':'old','attachments':['发票.pdf']}}},
                 '_mail_attachment_names_map':{'42':['发票.pdf']},'_mail_subjects_map':{'42':'电子发票'},
                 '_fetch_message':(msg,b''),'_extract_invoice_links':[],'_meta_for_file':{'amount':'100.00'},'_save_summary_cache':None}.items():
                stack.enter_context(patch.object(m,name,return_value=value))
            save=stack.enter_context(patch.object(m,'_save_scan_cache'))
            result=m._scan_invoice_mailbox('qq_mail',_client=client)
            self.assertEqual(result['total'],1);self.assertEqual(Path(result['invoices'][0]['path']).read_bytes(),b'%PDF-new')
            self.assertEqual(old.read_bytes(),b'%PDF-old');self.assertIn('uidvalidity_2',result['invoices'][0]['path'])
            self.assertEqual(save.call_args.args[2]['uidvalidity'],'2')

    def test_scan_cache_write_failure_preserves_previous_complete_json(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(m,'_BASE_DIR',Path(directory)):
            folder=Path(directory)/'invoices'
            m._save_scan_cache('qq_mail',folder,{'version':m._SCAN_CACHE_VERSION,'by_uid':{'42':[]}})
            with patch.object(os,'replace',side_effect=OSError('unavailable')):
                with self.assertRaises(OSError):m._save_scan_cache('qq_mail',folder,{'version':m._SCAN_CACHE_VERSION,'by_uid':{'43':[]}})
            self.assertEqual(m._load_scan_cache('qq_mail',folder)['by_uid'],{'42':[]})

    def test_legacy_invoice_generated_mail_summaries_are_reloaded_once(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(m,'_BASE_DIR',Path(directory)):
            path=m._summary_cache_path('qq_exmail')
            path.write_text(json.dumps({'mails':{'42':{'attachments':['abcdef123456_invoice.xml']},'43':{'attachments':['normal.pdf']}}}))
            self.assertEqual(set(m._load_summary_cache('qq_exmail')['mails']),{'43'})
            fresh={'mails':{'42':{'attachments':['abcdef123456_real.pdf']}}}
            m._save_summary_cache('qq_exmail',fresh)
            self.assertIn('42',m._load_summary_cache('qq_exmail')['mails'])
            own=m._summary_cache_path('qq_exmail','invoice_inbox');own.write_text(json.dumps(fresh))
            self.assertIn('42',m._load_summary_cache('qq_exmail','invoice_inbox')['mails'])

    def test_metadata_refreshes_for_same_size_file_replaced_within_one_second(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'invoice.pdf';path.write_bytes(b'first');os.utime(path,ns=(1000000000000000000,1000000000000000000))
            cache={}
            with patch.object(m,'parse_invoice_metadata',side_effect=[{'amount':'1.00'},{'amount':'2.00'}]):
                self.assertEqual(m._meta_for_file(path,cache)['amount'],'1.00')
                path.write_bytes(b'other');os.utime(path,ns=(1000000000000000001,1000000000000000001))
                self.assertEqual(m._meta_for_file(path,cache)['amount'],'2.00')

    def test_noninvoice_document_staging_leaves_no_file_or_temporary_artifact(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(m,'_meta_for_file',return_value={}):
            target,meta=m._invoice_attachment_file(Path(directory),'42','contract.pdf',b'%PDF-contract',{},False)
            self.assertIsNone(target);self.assertEqual(list(Path(directory).iterdir()),[])

    def test_same_account_scans_are_serialized(self):
        entered=threading.Event();release=threading.Event();second=threading.Event();calls=[]
        def scan(*args):
            calls.append(1)
            if len(calls)==1:entered.set();release.wait(2)
            else:second.set()
            return {}
        with patch.object(m,'_scan_invoices',side_effect=scan),ThreadPoolExecutor(2) as pool:
            first=pool.submit(m.scan_invoices,'qq_mail');self.assertTrue(entered.wait(1))
            other=pool.submit(m.scan_invoices,'qq_mail');self.assertFalse(second.wait(.05))
            release.set();first.result();other.result();self.assertTrue(second.is_set())
