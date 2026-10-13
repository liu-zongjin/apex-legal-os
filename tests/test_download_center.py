import asyncio
import sqlite3
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import download_center as dc
from backend import qq_mail_mcp
from backend.case_automation import ensure_case_automation_schema


class DownloadCenterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / 'test.db'
        @contextmanager
        def get_db():
            conn=sqlite3.connect(str(self.database));conn.row_factory=sqlite3.Row
            try: yield conn
            finally: conn.close()
        self.get_db=get_db
        with get_db() as conn:
            conn.execute('CREATE TABLE case_manager_cases(id INTEGER PRIMARY KEY,title TEXT)')
            conn.execute("INSERT INTO case_manager_cases VALUES(1,'匿名测试案件')")
            conn.execute("INSERT INTO case_manager_cases VALUES(2,'未绑定案件')")
            conn.commit()
        ensure_case_automation_schema(get_db)
        self.case_root=self.root/'case';self.case_root.mkdir()
        stat=self.case_root.stat()
        with get_db() as conn:
            conn.execute('INSERT INTO case_manager_folder_bindings(case_id,folder_path,real_path,device_id,inode,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(1,str(self.case_root),str(self.case_root),stat.st_dev,stat.st_ino,dc.now(),dc.now()))
            conn.commit()
        self.store=dc.DownloadStore(self.root/'downloads')
        self.patch=patch.object(dc,'_store',self.store);self.patch.start()
        app=FastAPI();dc.register_download_center_routes(app,get_db)
        self.client=TestClient(app);self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None,None,None);self.patch.stop();self.temp.cleanup()

    def create(self, **kwargs):
        result=self.client.post('/api/download-center/records',json={'name':'测试材料.pdf','source':'QQ邮箱','category':'mail','purpose':'case',**kwargs})
        self.assertEqual(result.status_code,200,result.text)
        return result.json()['id']

    def upload(self, identity):
        result=self.client.post('/api/download-center/records/'+identity+'/file',files={'file':('测试材料.pdf',b'%PDF-1.7\nfixture','application/pdf')})
        self.assertEqual(result.status_code,200,result.text)
        return result.json()

    def test_staged_file_case_confirmation_exact_destination_and_no_overwrite(self):
        identity=self.create();item=self.upload(identity)
        self.assertTrue(Path(item['path']).is_file())
        endpoint='/api/download-center/records/'+identity+'/save-case'
        self.assertEqual(self.client.post(endpoint,json={'case_id':1}).status_code,400)
        self.assertEqual(self.client.post(endpoint,json={'case_id':2,'confirmed':True}).status_code,409)
        result=self.client.post(endpoint,json={'case_id':1,'confirmed':True})
        self.assertEqual(result.status_code,200,result.text)
        item=result.json();self.assertEqual(item['case_title'],'匿名测试案件')
        self.assertEqual(Path(item['path']).parent,self.case_root/'#下载材料')
        original=Path(item['path']);content=original.read_bytes()
        again=self.client.post(endpoint,json={'case_id':1,'confirmed':True}).json()
        self.assertNotEqual(again['path'],str(original));self.assertEqual(original.read_bytes(),content)
        download=self.client.get('/api/download-center/records/'+identity+'/file')
        self.assertEqual(download.content,content)
        rows=self.client.get('/api/download-center/records?q=匿名测试案件').json()
        self.assertEqual(rows['total'],1);self.assertTrue(rows['items'][0]['file_available'])

    def test_invoice_cannot_be_silently_saved_as_case_material(self):
        identity=self.create(category='invoice',purpose='invoice');self.upload(identity)
        self.assertEqual(self.client.post('/api/download-center/records/'+identity+'/save-case',json={'case_id':1,'confirmed':True}).status_code,400)
        self.assertFalse((self.case_root/'#下载材料').exists())

    def test_untrusted_paths_and_symlink_escape_are_rejected(self):
        identity=self.create()
        self.client.patch('/api/download-center/records/'+identity,json={'path':'/etc/passwd','status':'completed'})
        self.assertEqual(self.store.get(identity)['path'],'')
        self.assertEqual(self.client.get('/api/download-center/records/'+identity+'/file').status_code,404)
        escaped=self.root/'secret';escaped.write_bytes(b'private')
        linked=self.store.root/'escape.pdf';linked.symlink_to(escaped)
        self.store.update(identity,path=str(linked))
        self.assertEqual(self.client.get('/api/download-center/records/'+identity+'/file').status_code,403)

    def test_upload_bound_and_restart_mark_incomplete_history(self):
        identity=self.create()
        with patch.object(dc,'MAX_BYTES',8):
            response=self.client.post('/api/download-center/records/'+identity+'/file',files={'file':('large.pdf',b'x'*9)})
        self.assertEqual(response.status_code,413)
        self.assertEqual(list((self.store.root/identity).iterdir()),[])
        recovered=dc.DownloadStore(self.store.root)
        self.assertEqual(recovered.get(identity)['status'],'interrupted')

    def test_legacy_import_is_idempotent_and_never_guesses_case(self):
        body={'items':[{'id':'old1','name':'匿名案件材料.pdf','source':'所函生成器','category':'document','createdAt':'2026-10-01T10:00:00'}]}
        self.assertEqual(self.client.post('/api/download-center/import-legacy',json=body).json()['imported'],1)
        self.assertEqual(self.client.post('/api/download-center/import-legacy',json=body).json()['imported'],0)
        row=self.client.get('/api/download-center/records').json()['items'][0]
        self.assertEqual(row['case_id'],0);self.assertIn('未确认',row['destination'])

    def test_mail_jobs_distinguish_invoice_and_confirmed_case_material(self):
        calls=[]
        def collect(uid,account,attachment_ids,destination_dir,progress,folder):
            calls.append((account,destination_dir,folder))
            directory=Path(destination_dir) if destination_dir else self.store.root/'invoice';directory.mkdir(exist_ok=True)
            target=directory/'anonymous.pdf';target.write_bytes(b'%PDF-fixture')
            progress(status='saving',total_files=1,received_bytes=12,total_bytes=12)
            return {'saved':[{'path':str(target),'filename':'anonymous.pdf','size':12}], 'skipped':[], 'folder':str(directory)}
        with patch.object(qq_mail_mcp,'collect_attachments',side_effect=collect), patch.object(qq_mail_mcp,'_collect_month_dir',return_value=self.store.root/'invoice'):
            rejected=self.client.post('/api/download-center/mail-jobs',json={'uid':'10','account':'qq_mail','purpose':'case','case_id':1})
            self.assertEqual(rejected.status_code,400)
            for purpose,case_id in [('case',1),('invoice',0)]:
                job=self.client.post('/api/download-center/mail-jobs',json={'uid':'10','account':'qq_mail','purpose':purpose,'case_id':case_id,'confirmed':True,'folder':'sent'}).json()
                for _ in range(40):
                    state=self.client.get('/api/download-center/records/'+job['id']).json()
                    if state['status'] not in dc.ACTIVE: break
                    time.sleep(.025)
                self.assertEqual(state['status'],'completed',state)
        self.assertNotEqual(calls[0][1],calls[1][1]);self.assertEqual(calls[1][1],self.store.root/'invoice');self.assertEqual(calls[0][2],'sent')
        rows=self.store.all();material=next(r for r in rows if r.get('parent_id') and r['purpose']=='case');invoice=next(r for r in rows if r.get('parent_id') and r['purpose']=='invoice')
        self.assertEqual(Path(material['path']).parent,self.case_root/'#邮箱案件材料')
        self.assertEqual(material['case_id'],1);self.assertEqual(invoice['case_id'],0)
        self.assertNotEqual(Path(invoice['path']).parent,Path(material['path']).parent)

    def test_native_destination_requires_identical_download_content(self):
        identity=self.create();item=self.upload(identity)
        candidate=self.root/'user-selected'/'saved.pdf';candidate.parent.mkdir();candidate.write_bytes(b'different')
        endpoint='/api/download-center/records/'+identity+'/native-saved'
        self.assertEqual(self.client.post(endpoint,json={'path':str(candidate)}).status_code,409)
        candidate.write_bytes(b'%PDF-1.7\nFixture')
        self.assertEqual(self.client.post(endpoint,json={'path':str(candidate)}).status_code,403)
        candidate.write_bytes(Path(item['path']).read_bytes())
        response=self.client.post(endpoint,json={'path':str(candidate)})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['destination'],str(candidate.resolve()))
        self.assertEqual(self.client.get('/api/download-center/records/'+identity+'/file').content,candidate.read_bytes())

    def test_clear_records_preserves_files_and_unassigned_case_material(self):
        retained=self.create();material=self.upload(retained)
        removable=self.create(category='export',purpose='other');export=self.upload(removable)
        response=self.client.post('/api/download-center/clear-completed',json={'confirmed':True})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['removed'],1)
        self.assertEqual(self.client.get('/api/download-center/records/'+retained).status_code,200)
        self.assertTrue(Path(export['path']).is_file());self.assertTrue(Path(material['path']).is_file())

    def test_page_close_interrupts_client_only_not_managed_mail_job(self):
        client_job=self.create()
        managed=self.store.create(source='QQ邮箱',category='mail')
        for identity in (client_job,managed['id']): self.client.post('/api/download-center/records/'+identity+'/interrupt')
        self.assertEqual(self.store.get(client_job)['status'],'interrupted')
        self.assertEqual(self.store.get(managed['id'])['status'],'preparing')

    def test_invoice_scan_results_register_real_files_without_case_or_path_escape(self):
        identity=self.create(category='invoice',purpose='invoice')
        directory=self.root/'invoices';directory.mkdir()
        invoice=directory/'匿名发票.pdf';invoice.write_bytes(b'%PDF-invoice')
        outside=self.root/'private.pdf';outside.write_bytes(b'private')
        with patch.object(qq_mail_mcp,'MAILBOX_CONFIGS',{'qq_mail':{'attachment_root':directory}}):
            response=self.client.post('/api/download-center/invoice-results',json={'identity':identity,'invoices':[{'path':str(invoice)},{'path':str(outside)}]})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['completed_files'],1)
            child=next(r for r in self.store.all() if r.get('parent_id')==identity)
            self.assertEqual(child['case_id'],0)
            self.assertEqual(self.client.get('/api/download-center/records/'+child['id']+'/file').content,b'%PDF-invoice')

    def test_partial_invoice_scan_keeps_downloadable_files_and_warning(self):
        identity=self.create(category='invoice',purpose='invoice')
        directory=self.root/'invoices';directory.mkdir()
        invoice=directory/'匿名发票.pdf';invoice.write_bytes(b'%PDF-invoice')
        with patch.object(qq_mail_mcp,'MAILBOX_CONFIGS',{'qq_mail':{'attachment_root':directory}}):
            response=self.client.post('/api/download-center/invoice-results',json={
                'identity':identity,'invoices':[{'path':str(invoice)}],
                'timed_out':True,'warnings':['部分邮件未扫描'],
            })
        self.assertEqual(response.status_code,200,response.text)
        result=response.json()
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['completed_files'],1)
        self.assertIn('部分邮件未扫描',result['error'])
        child=next(r for r in self.store.all() if r.get('parent_id')==identity)
        with patch.object(qq_mail_mcp,'MAILBOX_CONFIGS',{'qq_mail':{'attachment_root':directory}}):
            self.assertEqual(self.client.get('/api/download-center/records/'+child['id']+'/file').content,b'%PDF-invoice')

    def test_historical_generated_case_file_retains_exact_case_and_directory(self):
        from backend.case_automation import store_case_file
        result=store_case_file(self.get_db,1,'authorization','历史所函.docx',b'anonymous document',source_type='suohan_generator')
        rows=self.client.get('/api/download-center/records?category=document').json()['items']
        row=next(r for r in rows if r['id']=='casefile-'+str(result['id']))
        self.assertEqual(row['case_title'],'匿名测试案件')
        self.assertEqual(row['destination'],result['absolute_path'])
        self.assertEqual(self.client.get('/api/download-center/records/'+row['id']+'/file').content,b'anonymous document')

    def test_issue_filters_and_pagination(self):
        for index in range(45): self.store.create(name=f'file-{index}',status='completed')
        self.store.create(name='failed',status='failed')
        self.store.create(name='case',purpose='case',case_id=0,status='completed')
        page=self.client.get('/api/download-center/records?page=2&page_size=40').json()
        self.assertEqual(len(page['items']),7)
        self.assertEqual(self.client.get('/api/download-center/records?status=issues').json()['total'],1)
        self.assertEqual(self.client.get('/api/download-center/records?status=unassigned').json()['total'],1)
