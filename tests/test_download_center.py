import asyncio
import sqlite3
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
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
        app = FastAPI()
        app.add_middleware(GZipMiddleware, minimum_size=1024)
        dc.register_download_center_routes(app, get_db)
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
        self.store.update(identity, created_at='2026-11-19T16:00:00Z')
        self.assertTrue(Path(item['path']).is_file())
        endpoint='/api/download-center/records/'+identity+'/save-case'
        self.assertEqual(self.client.post(endpoint,json={'case_id':1}).status_code,400)
        self.assertEqual(self.client.post(endpoint,json={'case_id':2,'confirmed':True}).status_code,409)
        result=self.client.post(endpoint,json={'case_id':1,'confirmed':True})
        self.assertEqual(result.status_code,200,result.text)
        item=result.json();self.assertEqual(item['case_title'],'匿名测试案件')
        self.assertEqual(Path(item['path']).parent,self.case_root/'#下载材料')
        original=Path(item['path']);content=original.read_bytes()
        self.assertEqual(original.name, '20261120_测试材料.pdf')
        self.assertEqual(item['name'], original.name)
        again=self.client.post(endpoint,json={'case_id':1,'confirmed':True}).json()
        self.assertEqual(again['name'], '20261120_测试材料_2.pdf')
        self.assertEqual(again['name'], Path(again['path']).name)
        self.assertEqual(original.read_bytes(),content)
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
        calls = []

        def collect(uid, account, attachment_ids, destination_dir, progress, folder):
            calls.append((account, destination_dir, folder, attachment_ids))
            directory = Path(destination_dir)
            directory.mkdir(exist_ok=True)
            names = ['匿名材料.pdf', 'a' * 200 + '.docx']
            selected = attachment_ids or ['1', '2']
            saved = []
            for index in selected:
                name = names[int(index) - 1]
                target = directory / name
                content = f'{account}:{index}'.encode()
                target.write_bytes(content)
                saved.append({'path': str(target), 'filename': name, 'size': len(content)})
            progress(status='saving', total_files=len(saved))
            return {'saved': saved, 'skipped': [], 'folder': str(directory)}

        with patch.object(qq_mail_mcp, 'collect_attachments', side_effect=collect), patch.object(
            qq_mail_mcp, '_collect_month_dir', return_value=self.store.root / 'invoice'
        ), patch.object(dc, 'now', return_value='2026-11-19T16:00:00Z'):
            rejected = self.client.post('/api/download-center/mail-jobs', json={
                'uid': '10', 'account': 'qq_mail', 'purpose': 'case', 'case_id': 1,
            })
            self.assertEqual(rejected.status_code, 400)
            jobs = [
                ('case', 'qq_mail', ['1']),
                ('case', 'netease_exmail', ['1', '2']),
                ('case', 'qq_exmail', []),
                ('invoice', 'qq_mail', ['1']),
                ('other', 'qq_mail', ['1']),
            ]
            for purpose, account, selected in jobs:
                response = self.client.post('/api/download-center/mail-jobs', json={
                    'uid': '10', 'account': account, 'purpose': purpose,
                    'case_id': 1 if purpose == 'case' else 0, 'confirmed': True,
                    'folder': 'sent', 'attachment_ids': selected,
                })
                self.assertEqual(response.status_code, 200, response.text)
                job_id = response.json()['id']
                for _ in range(40):
                    state = self.client.get('/api/download-center/records/' + job_id).json()
                    if state['status'] not in dc.ACTIVE:
                        break
                    time.sleep(.025)
                self.assertEqual(state['status'], 'completed', state)
                children = [row for row in self.store.all() if row.get('parent_id') == job_id]
                self.assertEqual(len(children), len(selected) or 2)

        self.assertEqual([call[3] for call in calls], [job[2] for job in jobs])
        self.assertTrue(all(call[2] == 'sent' for call in calls))
        rows = [row for row in self.store.all() if row.get('parent_id')]
        materials = [row for row in rows if row['purpose'] == 'case']
        self.assertEqual(len(materials), 5)
        for material in materials:
            path = Path(material['path'])
            self.assertEqual(path.parent, self.case_root / '#邮箱案件材料')
            self.assertEqual(material['name'], path.name)
            self.assertTrue(path.name.startswith('20261120_'))
            self.assertEqual(material['case_id'], 1)
            response = self.client.get('/api/download-center/records/' + material['id'] + '/file')
            self.assertEqual(response.content, path.read_bytes())
        case_directory = self.case_root / '#邮箱案件材料'
        self.assertEqual((case_directory / '20261120_匿名材料.pdf').read_bytes(), b'qq_mail:1')
        self.assertEqual((case_directory / '20261120_匿名材料_2.pdf').read_bytes(), b'netease_exmail:1')
        self.assertEqual((case_directory / '20261120_匿名材料_3.pdf').read_bytes(), b'qq_exmail:1')
        self.assertEqual(len(list(case_directory.glob('*.docx'))), 2)
        with self.get_db() as conn:
            original_names = [row[0] for row in conn.execute(
                'SELECT original_filename FROM case_manager_files ORDER BY id'
            )]
        self.assertEqual(original_names, ['匿名材料.pdf', '匿名材料.pdf', 'a' * 200 + '.docx',
                                          '匿名材料.pdf', 'a' * 200 + '.docx'])
        for purpose in ('invoice', 'other'):
            row = next(row for row in rows if row['purpose'] == purpose)
            self.assertEqual(Path(row['path']).name, '匿名材料.pdf')
            self.assertEqual(row['case_id'], 0)

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

    def test_scanner_staged_for_native_save_preserves_bytes_and_pending_status(self):
        identity = self.create(category='scanner', purpose='other')
        endpoint = '/api/download-center/records/' + identity
        content = b'%PDF-1.7\n' + b'fixture' * 300
        upload = self.client.post(
            endpoint + '/file',
            params={'await_native': 'true'},
            files={'file': ('scanner-fixture.pdf', content, 'application/pdf')},
        )
        self.assertEqual(upload.status_code, 200, upload.text)
        staged = upload.json()
        self.assertEqual(staged['status'], 'saving')
        self.assertEqual(staged['total_bytes'], len(content))
        self.assertEqual(staged['received_bytes'], 0)
        self.assertEqual(staged['completed_files'], 0)
        self.assertEqual(Path(staged['path']).read_bytes(), content)

        download = self.client.get(endpoint + '/file', headers={'Accept-Encoding': 'gzip'})
        self.assertEqual(download.status_code, 200, download.text)
        self.assertEqual(download.headers['content-encoding'], 'identity')
        self.assertEqual(int(download.headers['content-length']), len(content))
        self.assertEqual(download.content, content)
        self.assertEqual(self.client.get(endpoint).json()['status'], 'saving')

        saved = self.root / 'scanner-saved.pdf'
        saved.write_bytes(download.content)
        response = self.client.post(endpoint + '/native-saved', json={'path': str(saved)})
        self.assertEqual(response.status_code, 200, response.text)
        completed = response.json()
        self.assertEqual(completed['status'], 'completed')
        self.assertEqual(completed['received_bytes'], len(content))
        self.assertEqual(completed['completed_files'], 1)
        self.assertEqual(completed['destination'], str(saved.resolve()))

    def test_default_scanner_upload_finishes_without_native_confirmation(self):
        item = self.upload(self.create(category='scanner', purpose='other'))
        self.assertEqual(item['status'], 'completed')
        self.assertEqual(item['received_bytes'], item['total_bytes'])
        self.assertEqual(item['completed_files'], 1)

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

    def test_size_sort_is_global_and_uses_disk_size_not_transfer_counters(self):
        for index in range(4):
            path=self.store.root/f'{index}.pdf';path.write_bytes(b'x'*(index+1))
            self.store.create(path=str(path),status='completed',total_bytes=999-index,created_at=f'2026-10-{10+index}T10:00:00+08:00')
        self.store.create(status='completed',total_bytes=99999)
        page=self.client.get('/api/download-center/records?sort=largest&page_size=2&page=2').json()
        self.assertEqual([r['size_bytes'] for r in page['items']],[2,1])
        smallest=self.client.get('/api/download-center/records?sort=smallest').json()['items']
        self.assertEqual([r['size_bytes'] for r in smallest],[1,2,3,4,None])
        filtered=self.client.get('/api/download-center/records?min_bytes=2&max_bytes=3').json()
        self.assertEqual(filtered['total'],2)
        self.assertEqual(self.client.get('/api/download-center/records?min_bytes=4&max_bytes=2').status_code,400)

    def test_date_range_includes_entire_shanghai_day(self):
        for stamp in ['2026-10-19T00:00:00+08:00','2026-10-19T15:59:59Z','2026-10-19T16:00:00Z']:
            self.store.create(created_at=stamp,status='completed')
        rows=self.client.get('/api/download-center/records?date_from=2026-10-19&date_to=2026-10-19').json()
        self.assertEqual(rows['total'],2)
        self.assertEqual(self.client.get('/api/download-center/records?date_from=bad').status_code,400)
        self.assertEqual(self.client.get('/api/download-center/records?date_from=2026-10-20&date_to=2026-10-19').status_code,400)

    def test_analysis_and_cleanup_recheck_missing_but_preserve_unknown_and_unavailable(self):
        missing=self.store.create(path=str(self.store.root/'gone.pdf'),status='completed')
        recovered=self.store.create(path=str(self.store.root/'restored.pdf'),status='completed')
        unavailable=self.store.create(path=str(self.root/'offline-volume'/'file.pdf'),status='completed')
        active=self.store.create(path=str(self.store.root/'active.pdf'),status='downloading')
        unknown=self.store.create(status='completed')
        batch=self.store.create(status='completed',is_batch=True)
        analysis=self.client.post('/api/download-center/analyze').json()
        self.assertEqual({r['id'] for r in analysis['items']},{missing['id'],recovered['id']})
        Path(recovered['path']).write_bytes(b'restored')
        ids=[r['id'] for r in self.store.all()]
        self.assertEqual(self.client.post('/api/download-center/clean-missing',json={'ids':ids}).status_code,400)
        result=self.client.post('/api/download-center/clean-missing',json={'confirmed':True,'ids':ids}).json()
        self.assertEqual(result,{'removed':1,'skipped':5})
        self.assertTrue(Path(recovered['path']).is_file())
        self.assertEqual(len(dc.DownloadStore(self.store.root).all()),5)

    def test_trash_rejects_changed_files_and_untrusted_symlinks(self):
        identity=self.create(category='knowledge',purpose='other');saved=self.upload(identity)
        row=self.client.get('/api/download-center/records').json()['items'][0]
        self.assertTrue(row['file_revision'])
        Path(saved['path']).write_bytes(b'changed')
        with patch('subprocess.run') as run:
            result=self.client.post('/api/download-center/trash',json={'confirmed':True,'items':[{'id':identity,'revision':row['file_revision']}]}).json()
            self.assertEqual(result['moved'],[]);self.assertEqual(len(result['errors']),1);run.assert_not_called()
        row=self.client.get('/api/download-center/records').json()['items'][0]
        with patch('subprocess.run') as run:
            result=self.client.post('/api/download-center/trash',json={'confirmed':True,'items':[{'id':identity,'revision':row['file_revision']}]}).json()
            self.assertEqual(result['moved'],[identity]);self.assertEqual(run.call_args[0][0][-1],str(Path(saved['path']).resolve()))
        target=self.store.root/'target';target.write_bytes(b'target')
        link=self.store.root/'linked';link.symlink_to(target)
        linked=self.store.create(path=str(link),status='completed')
        rows=self.client.get('/api/download-center/records').json()['items']
        row=next(r for r in rows if r['id']==linked['id'])
        with patch('subprocess.run') as run:
            result=self.client.post('/api/download-center/trash',json={'confirmed':True,'items':[{'id':row['id'],'revision':row['file_revision']}]}).json()
            self.assertEqual(result['moved'],[]);run.assert_not_called()


    def test_generated_archive_history_is_listed_before_any_download_click(self):
        directory=self.case_root/'exports'/'version';directory.mkdir(parents=True)
        (directory/'结案材料.pdf').write_bytes(b'%PDF-archive')
        with self.get_db() as conn:
            conn.execute('CREATE TABLE case_archive_exports(id INTEGER PRIMARY KEY,case_id INTEGER,category TEXT,relative_directory TEXT,created_at TEXT)')
            conn.execute("INSERT INTO case_archive_exports VALUES(1,1,'criminal','exports/version',?)",(dc.now(),))
            conn.commit()
        rows=self.client.get('/api/download-center/records?category=archive').json()['items']
        self.assertEqual(len(rows),3)
        record=next(r for r in rows if r['id']=='archive-1-pdf')
        self.assertEqual(record['case_title'],'匿名测试案件');self.assertTrue(record['case_saved'])
        self.assertEqual(record['size_bytes'],12)
        self.assertEqual(self.client.get('/api/download-center/records/archive-1-pdf/file').content,b'%PDF-archive')
        (directory/'结案材料.pdf').unlink()
        result=self.client.post('/api/download-center/clean-missing',json={'confirmed':True,'ids':['archive-1-pdf']})
        self.assertEqual(result.json()['removed'],1)
        self.assertNotIn('archive-1-pdf',[r['id'] for r in self.client.get('/api/download-center/records?category=archive').json()['items']])


    def test_missing_file_error_names_the_page_for_restarting_download(self):
        identity=self.create(category='invoice',purpose='invoice')
        response=self.client.get('/api/download-center/records/'+identity+'/file')
        self.assertEqual(response.status_code,404)
        self.assertIn('打开发票中心',response.json()['detail'])
        self.assertNotIn('返回来源',response.json()['detail'])
