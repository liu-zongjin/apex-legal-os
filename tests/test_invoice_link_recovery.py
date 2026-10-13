import io
import json
import tempfile
import unittest
import zipfile
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode
from backend import qq_mail_mcp as m


class InvoiceLinkRecoveryTests(unittest.TestCase):
    def test_qr_generator_unwraps_and_deduplicates_receipt_url(self):
        target='https://nnfp.jss.com.cn/anonymous-receipt'
        qr='https://nnfp.jss.com.cn/allow/service/getEwmImg.do?'+urlencode({'content':target})
        message=EmailMessage();message.set_content(f'下载发票 {target}\n二维码 {qr}')
        self.assertEqual(m._extract_invoice_links(message),[target])
        self.assertEqual(m._canonical_invoice_link('http://[bad'), '')
        with patch.object(m,'_safe_http_request',return_value=(target,{'content-type':'application/pdf'},b'%PDF-test')) as request:
            self.assertEqual(m._download_invoice_link(qr,['.pdf'])['content'],b'%PDF-test')
            self.assertEqual(request.call_args.args[0],target)

    def test_old_scan_cache_normalizes_qr_urls_without_losing_files(self):
        target='https://nnfp.jss.com.cn/anonymous-receipt'
        qr='https://nnfp.jss.com.cn/allow/service/getEwmImg.do?'+urlencode({'content':target})
        cache={'version':m._SCAN_CACHE_VERSION,'by_uid':{'42':[]},'linked_uids':{
            '42':{'links':[qr,target],'files':[{'filename':'匿名.pdf','source_url':target}]}}}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'cache.json';path.write_text(json.dumps(cache))
            with patch.object(m,'_scan_cache_path',return_value=path):result=m._load_scan_cache('qq_mail',Path(directory))
        self.assertEqual(result['linked_uids']['42']['links'],[target])
        self.assertEqual(result['linked_uids']['42']['files'][0]['filename'],'匿名.pdf')

    def test_vpiaotong_receipt_uses_selected_official_file_format(self):
        receipt='https://scan.vpiaotong.com/#/invoiceStatus/anonymous?access_token=anonymous'
        info={'code':'200','data':{'kpzt':'MAKEINVOICESUCCESS','qdFpHm':'12345678901234567890',
                                 'xsfMc':'匿名销售方','jshj':'100.00','kprq':'2026-09-01'}}
        for extension,content in (('.pdf',b'%PDF-test'),('.ofd',b'PK\x03\x04test'),('.xml',b'<?xml version="1.0"?><Invoice/>')):
            with self.subTest(extension=extension):
                responses=[(receipt,{'content-type':'text/html'},b'<html></html>'),
                           ('https://scan.vpiaotong.com/info',{},json.dumps(info).encode()),
                           ('https://scan.vpiaotong.com/file',{'content-type':'application/octet-stream'},content)]
                with patch.object(m,'_safe_http_request',side_effect=responses) as request:
                    result=m._download_invoice_link('https://fpkj.vpiaotong.com/tp/s/v/anonymous.pt',[extension])
                self.assertEqual(result['content'],content)
                self.assertTrue(result['filename'].endswith(extension))
                self.assertIn('getElectronicInvoice.pt?',request.call_args.args[0])
                self.assertIn('fileType='+extension[1:].upper(),request.call_args.args[0])
                self.assertEqual(result['meta_hint']['amount'],'100.00')

    def test_vpiaotong_does_not_use_failed_or_wrong_host_receipt(self):
        with patch.object(m,'_safe_http_request') as request:
            self.assertIsNone(m._resolve_vpiaotong_link('https://scan.vpiaotong.com.evil.example/#/invoiceStatus/x',['.pdf']))
            request.assert_not_called()
        with patch.object(m,'_safe_http_request',return_value=('',{},json.dumps({'code':'200','data':{'kpzt':'MAKEINVOICEFAIL'}}).encode())):
            self.assertIsNone(m._resolve_vpiaotong_link('https://scan.vpiaotong.com/#/invoiceStatus/x',['.pdf']))

    def test_linked_zip_returns_all_selected_members_with_isolated_names(self):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as archive:
            archive.writestr('../发票.xml',b'<?xml version="1.0"?><Invoice/>')
            archive.writestr('folder/发票.xml',b'<?xml version="1.0"?><Invoice>2</Invoice>')
            archive.writestr('发票.pdf',b'%PDF-test')
        with patch.object(m,'_safe_http_request',return_value=('https://example.com/files.zip',{'content-type':'application/zip'},stream.getvalue())):
            result=m._download_invoice_link('https://example.com/files.zip',['.xml'])
        files=[result]+result['additional_files']
        self.assertEqual(len(files),2)
        self.assertEqual(len({f['filename'] for f in files}),2)
        self.assertTrue(all(f['filename'].endswith('.xml') and '/' not in f['filename'] for f in files))

    def test_html_response_cannot_be_saved_as_pdf(self):
        with patch.object(m,'_safe_http_request',return_value=('https://example.com/invoice.pdf',{'content-type':'text/html'},b'<html>expired</html>')):
            self.assertIsNone(m._download_invoice_link('https://example.com/invoice.pdf',['.pdf']))

    def test_interrupted_stream_is_reported_as_retryable_link_failure(self):
        import requests
        from unittest.mock import Mock
        response=Mock();response.status_code=200
        response.iter_content.side_effect=requests.ConnectionError('connection interrupted')
        with patch.object(m,'_validate_public_http_url'),patch.object(requests.Session,'request',return_value=response):
            with self.assertRaises(m.QQMailMCPError):m._safe_http_request('https://example.com/invoice.pdf')
        response.close.assert_called_once()

    def test_linked_archive_limits_are_preserved(self):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as archive:
            for i in range(501):archive.writestr(str(i)+'.xml',b'<Invoice/>')
        with self.assertRaises(m.QQMailMCPError):
            m._linked_archive_invoices('https://example.com/files.zip',{},stream.getvalue(),['.xml'])


if __name__=='__main__':unittest.main()
