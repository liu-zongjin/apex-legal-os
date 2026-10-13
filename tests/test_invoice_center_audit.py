"""Exercise invoice exports/automation without importing the live application's DB."""
import __future__
import ast
import asyncio
import datetime
import functools
import hashlib
import io
import json
import os
import re
from urllib.parse import quote
import tempfile
import threading
import unittest
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from typing import Any, Dict, Optional
from fastapi import HTTPException
from backend import qq_mail_mcp as mail

ROOT=Path(__file__).resolve().parents[1]
TREE=ast.parse((ROOT/'backend/main.py').read_text())
NAMES={'_invoice_export_history_path','_invoice_export_key','_load_invoice_export_history',
       '_save_invoice_export_history','_repair_invoice_export_history','_prepare_invoice_export',
       '_invoice_history_payload','_invoice_automation_store','_save_invoice_automation_store',
       '_invoice_previous_month_range','_invoice_automation_archive_path','_run_invoice_automation_task',
       '_invoice_automation_due','qq_mail_invoice_download'}

class InvoiceServiceAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.configs={account:{'attachment_root':self.root/account} for account in mail.MAILBOX_CONFIGS}
        for config in self.configs.values():config['attachment_root'].mkdir()
        self.patch=patch.object(mail,'MAILBOX_CONFIGS',self.configs);self.patch.start()
        self.ns=dict(__file__=str(self.root/'backend/main.py'),Path=Path,Any=Any,Dict=Dict,Optional=Optional,
                     os=os,re=re,quote=quote,json=json,uuid=uuid,datetime=datetime,hashlib=hashlib,threading=threading,
                     zipfile=zipfile,BytesIO=io.BytesIO,qq_mail_mcp=mail,HTTPException=HTTPException,
                     asyncio=asyncio,functools=functools,_INVOICE_EXPORT_LOCK=threading.RLock(),
                     _INVOICE_AUTOMATION_LOCK=threading.RLock(),_INVOICE_AUTOMATION_FILE=self.root/'automation.json',
                     _INVOICE_AUTOMATION_ARCHIVE_DIR=self.root/'archives')
        nodes=[]
        for node in TREE.body:
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in NAMES:
                node.decorator_list=[];nodes.append(node)
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'<invoice-service>', 'exec',flags=__future__.annotations.compiler_flag),self.ns)

    def tearDown(self):self.patch.stop();self.temp.cleanup()

    def file(self,name,data=b'%PDF-anonymous',account='qq_mail'):
        path=self.configs[account]['attachment_root']/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);return path

    def payload(self,paths,account='qq_mail',invoices=None):
        return SimpleNamespace(account=account,paths=[str(p) for p in paths],invoices=invoices or [])

    def test_export_contains_all_501_selected_files(self):
        paths=[self.file(f'invoice-{i}.pdf',f'%PDF-{i}'.encode()) for i in range(501)]
        archive=self.ns['_prepare_invoice_export'](self.payload(paths))
        with zipfile.ZipFile(archive) as z:
            self.assertEqual(len(z.namelist()),501)
            self.assertEqual(z.read('invoice-500.pdf'),b'%PDF-500')
        self.assertEqual(len(self.ns['_load_invoice_export_history']('qq_mail')),501)

    def test_wrong_mailbox_and_missing_files_fail_without_recording_export(self):
        wrong=self.file('wrong.pdf',account='qq_exmail')
        for paths in ([wrong],[self.root/'missing.pdf']):
            with self.assertRaises(HTTPException):self.ns['_prepare_invoice_export'](self.payload(paths))
        self.assertEqual(self.ns['_load_invoice_export_history']('qq_mail'),[])

    def test_archive_names_never_collide_with_already_suffixed_names(self):
        paths=[self.file('a.pdf',b'%PDF-a'),self.file('a_2.pdf',b'%PDF-b'),self.file('nested/a.pdf',b'%PDF-c')]
        with zipfile.ZipFile(self.ns['_prepare_invoice_export'](self.payload(paths))) as z:
            self.assertEqual(len(z.namelist()),len(set(z.namelist())))
            self.assertEqual({z.read(n) for n in z.namelist()},{b'%PDF-a',b'%PDF-b',b'%PDF-c'})

    def test_export_identity_survives_file_copy_but_distinguishes_other_invoices_and_formats(self):
        a=self.file('a.pdf',b'%PDF-a');copy=self.file('nested/copy.pdf',b'%PDF-a');b=self.file('b.pdf',b'%PDF-b')
        key=self.ns['_invoice_export_key']
        meta={'issuer':'匿名销售方','amount':'100.00','issue_time':'2026年09月01日'}
        self.assertEqual(key(meta,a),key(meta,copy));self.assertNotEqual(key(meta,a),key(meta,b))
        meta['invoice_number']='26442000010000000001'
        self.assertEqual(key(meta,a),key(meta,b))
        xml=self.file('other.xml',b'<Invoice/>');self.assertNotEqual(key(meta,a),key(meta,xml))

    def test_history_migration_retains_legacy_key_and_corrects_negative_amount(self):
        path=self.file('invoice.pdf')
        record={'path':str(path),'filename':'invoice.pdf','export_key':'old','amount':'100.00'}
        self.ns['_save_invoice_export_history']('qq_mail',[record])
        with patch.object(mail,'parse_invoice_metadata',return_value={'invoice_number':'26442000010000000001','amount':'-100.00','issue_time':'2026年09月01日'}):
            result=self.ns['_invoice_history_payload']('qq_mail')
        self.assertIn('old',result['export_keys']);self.assertEqual(result['records'][0]['amount'],'-100.00')
        self.assertEqual(result['records'][0]['key_version'],3)

    def test_history_write_failure_does_not_destroy_previous_file(self):
        save=self.ns['_save_invoice_export_history'];save('qq_mail',[{'export_key':'old'}])
        with patch.object(os,'replace',side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):save('qq_mail',[{'export_key':'new'}])
        self.assertEqual(self.ns['_load_invoice_export_history']('qq_mail'),[{'export_key':'old'}])

    def test_concurrent_exports_do_not_lose_history(self):
        from concurrent.futures import ThreadPoolExecutor
        a=self.file('a.pdf',b'%PDF-a');b=self.file('b.pdf',b'%PDF-b')
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda p:self.ns['_prepare_invoice_export'](self.payload([p])),[a,b]))
        self.assertEqual(len(results),2);self.assertEqual(len(self.ns['_load_invoice_export_history']('qq_mail')),2)

    def test_automation_continues_partial_scan_and_archives_all_rows(self):
        a=self.file('a.pdf',b'%PDF-a');b=self.file('b.pdf',b'%PDF-b')
        task={'id':'anonymous','account':'qq_mail','name':'匿名归集','extensions':['.pdf'],'keyword':''}
        self.ns['_save_invoice_automation_store']({'tasks':[task],'collections':[]})
        results=[{'invoices':[{'path':str(a)}],'timed_out':True,'warnings':['扫描超时'],'scanned_mails':1},
                 {'invoices':[{'path':str(b)}],'timed_out':False,'warnings':[],'scanned_mails':2}]
        with patch.object(mail,'scan_invoices',side_effect=results) as scan:
            result=self.ns['_run_invoice_automation_task']('anonymous')
        self.assertEqual(scan.call_count,2);self.assertEqual(result['status'],'completed',result); self.assertEqual(result['invoice_count'],2)
        with zipfile.ZipFile(result['archive_path']) as z:self.assertEqual(len(z.namelist()),2)
        task=self.ns['_invoice_automation_store']()['tasks'][0];self.assertEqual(task['last_period'],result['period'])

    def test_missing_archive_source_is_not_reported_as_successful_collection(self):
        task={'id':'anonymous','account':'qq_mail','name':'匿名归集','extensions':['.pdf'],'keyword':''}
        self.ns['_save_invoice_automation_store']({'tasks':[task],'collections':[]})
        missing=self.configs['qq_mail']['attachment_root']/'gone.pdf'
        with patch.object(mail,'scan_invoices',return_value={'invoices':[{'path':str(missing)}],'warnings':[],'timed_out':False}):
            result=self.ns['_run_invoice_automation_task']('anonymous')
        self.assertEqual(result['status'],'partial');self.assertEqual(result['invoice_count'],0)
        self.assertNotIn('last_period',self.ns['_invoice_automation_store']()['tasks'][0])

    def test_automation_retries_with_backoff_and_catches_up_after_due_day(self):
        due=self.ns['_invoice_automation_due'];now=datetime.datetime(2026,10,13,9)
        task={'enabled':True,'day':1,'hour':18,'minute':0,'last_attempt_period':'2026-09',
              'last_attempt_at':(now-datetime.timedelta(minutes=16)).isoformat()}
        self.assertTrue(due(task,now,'2026-09'))
        task['last_attempt_at']=(now-datetime.timedelta(minutes=5)).isoformat();self.assertFalse(due(task,now,'2026-09'))
        task['last_period']='2026-09';self.assertFalse(due(task,now+datetime.timedelta(days=1),'2026-09'))

    def test_zip_work_does_not_block_api_event_loop(self):
        started=threading.Event();release=threading.Event()
        def build(payload):started.set();release.wait(2);return io.BytesIO(b'zip')
        self.ns['_prepare_invoice_export']=build
        async def run():
            task=asyncio.create_task(self.ns['qq_mail_invoice_download'](self.payload([])))
            for _ in range(100):
                if started.is_set():break
                await asyncio.sleep(.001)
            self.assertTrue(started.is_set());self.assertFalse(task.done());release.set();return await task
        response=asyncio.run(run());self.assertEqual(response.media_type,'application/zip')
