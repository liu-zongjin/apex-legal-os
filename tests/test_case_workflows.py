"""Isolated anonymous fixtures; never import the live application's database."""
import asyncio
import json
import sqlite3
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import fitz
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from docx import Document

from backend.case_workflows import register_case_workflow_routes, validate_classification, claims_from_draft


def pdf(path, pages=1, rotation=0):
    with fitz.open() as doc:
        for i in range(pages):
            page = doc.new_page()
            page.insert_text((60,80), f'Anonymous evidence page {i+1}')
            if rotation:
                page.set_rotation(rotation)
        doc.save(path)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='stella-workflow-tests-')
        self.folder = Path(self.temp.name)
        self.root = self.folder / 'case'
        self.root.mkdir()
        db = self.folder / 'test.db'
        conn = sqlite3.connect(db)
        conn.execute('CREATE TABLE case_manager_cases(id INTEGER PRIMARY KEY,title TEXT,case_type TEXT,source_status TEXT)')
        conn.executemany('INSERT INTO case_manager_cases VALUES(?,?,?,?)', [(1,'匿名案件','民事','active'),(2,'另案','民事','active')])
        conn.execute('CREATE TABLE case_manager_folder_bindings(case_id INTEGER PRIMARY KEY,real_path TEXT,inode INTEGER,device_id INTEGER)')
        conn.execute('INSERT INTO case_manager_folder_bindings VALUES(1,?,?,?)',(str(self.root),self.root.stat().st_ino,self.root.stat().st_dev))
        conn.execute('INSERT INTO case_manager_folder_bindings VALUES(2,?,?,?)',(str(self.root),self.root.stat().st_ino,self.root.stat().st_dev))
        conn.commit();conn.close()
        @contextmanager
        def get_db():
            conn = sqlite3.connect(db);conn.row_factory=sqlite3.Row
            try:yield conn
            finally:conn.close()
        def parse(path, consent):
            return {'content':path.read_text()}
        async def ai(model, messages):
            data=json.loads(messages[-1]['content'])
            if 'document_items' in data:
                source=data['sources'][0]
                return json.dumps({'title':'匿名证据','summary':'材料摘要','purpose':'证明合同事实','quotes':[{'source_id':source['id'],'quote':source['text'].strip()}]}), '', 'fixture-model'
            results=[]
            for claim in data['claims']:
                quote=data['sources'][0]['text'].strip()
                results.append({'id':claim['id'],'status':'supported','reason':'匿名测试结果','evidence':[{'source_id':data['sources'][0]['id'],'quote':quote}]})
            return json.dumps({'results':results}), '', 'fixture-model'
        self.app=FastAPI()
        self.service=register_case_workflow_routes(self.app,get_db,Path(__file__).resolve().parents[1]/'frontend',parse_file=parse,call_ai=ai,require_action=lambda request:None)
        self.client=TestClient(self.app).__enter__()
        (self.root/'合同.txt').write_text('合同约定价款10000元。付款日为2026年1月1日。')

    def tearDown(self):
        self.client.__exit__(None,None,None)
        self.temp.cleanup()

    def create(self,body):
        return self.client.post('/api/case-workflows/cases/1/tasks',json=body)

    def done(self,job):
        for _ in range(200):
            result=self.client.get(f'/api/case-workflows/cases/1/tasks/{job["id"]}').json()
            if result['status'] not in {'queued','running'}:return result
            time.sleep(.01)
        self.fail('task did not finish')

    def fact(self):
        response=self.create({'kind':'fact_check','paths':['合同.txt'],'draft':'价款10000元。付款日为2026年1月1日。'})
        self.assertEqual(response.status_code,200,response.text)
        return self.done(response.json())

    def plan(self):
        pdf(self.root/'证据A.pdf',3)
        pdf(self.root/'证据B.pdf',2)
        response=self.create({'kind':'evidence_plan','paths':['证据A.pdf','证据B.pdf'],'draft':'合同约定价款。\n请求返还价款。'})
        self.assertEqual(response.status_code,200,response.text)
        job=self.done(response.json())
        self.assertEqual(job['status'],'completed',job)
        return job

    def test_document_plan_save_group_select_pages_compile_and_reference(self):
        job=self.plan()
        self.assertEqual(len(job['plan_entries']),2)
        self.assertTrue(job['plan_entries'][0]['summary_refs'])
        self.assertEqual(job['claims'][1]['document_locator'],'第2段 · 事项2')
        prefix=f'/api/case-workflows/cases/1/tasks/{job["id"]}'
        self.assertEqual(self.client.get(prefix+'/material-info',params={'path':'证据A.pdf'}).json()['pages'],3)
        self.assertEqual(self.client.get(prefix+'/material-preview',params={'path':'证据A.pdf'}).status_code,200)
        pixels=self.client.get(prefix+'/material-page',params={'path':'证据A.pdf','page':3})
        self.assertEqual(pixels.status_code,200);self.assertTrue(pixels.content.startswith(b'\x89PNG'))
        self.assertEqual(self.client.get(prefix+'/material-page',params={'path':'证据A.pdf','page':4}).status_code,422)
        self.assertEqual(self.client.get(prefix+'/material-info',params={'path':'合同.txt'}).status_code,404)
        self.assertEqual(self.client.get(prefix.replace('/cases/1/','/cases/2/')+'/material-info',params={'path':'证据A.pdf'}).status_code,404)
        entry={'title':'合同及付款','purpose':'证明履行情况','summary':'各材料的客观摘要','origin':'当事人提供','group':'履行情况',
            'claim_ids':['1'], 'materials':[{'path':'证据A.pdf','pages':'1,3'},{'path':'证据B.pdf','pages':'2'}]}
        saved=self.client.put(prefix+'/plan',json={'revision':1,'entries':[entry]})
        self.assertEqual(saved.status_code,200,saved.text)
        self.assertEqual(saved.json()['revision'],2)
        self.assertEqual(self.client.put(prefix+'/plan',json={'revision':1,'entries':[entry]}).status_code,409)
        body={'kind':'evidence_book','plan_id':job['id'],'plan_revision':2,'paths':['证据A.pdf','证据B.pdf'],'entries':[entry],'confirmed':True}
        self.assertEqual(self.create(body).status_code,422)  # Unassociated matter must be acknowledged.
        body['gaps_acknowledged']=True
        response=self.create(body);self.assertEqual(response.status_code,200,response.text)
        book=self.done(response.json());self.assertEqual(book['status'],'completed',book)
        mapping=book['mapping'][0]
        self.assertEqual((mapping['start'],mapping['end']),(1,3))
        self.assertEqual(mapping['source_mappings'][0]['selected_pages'],[1,3])
        self.assertEqual(mapping['source_mappings'][1]['start'],3)
        directory=self.root/'Stella办案成果'/book['id']
        with fitz.open(directory/next(a['path'] for a in book['artifacts'] if a['name']=='证据册.pdf')) as compiled:
            self.assertIn('page 1',compiled[0].get_text());self.assertIn('page 3',compiled[1].get_text());self.assertIn('page 2',compiled[2].get_text())
        workbook=load_workbook(directory/next(a['path'] for a in book['artifacts'] if a['name']=='证据目录.xlsx'))
        self.assertEqual(workbook['证据目录'].cell(2,9).value,'各材料的客观摘要')
        self.assertEqual(workbook['证据目录'].cell(2,10).value,'当事人提供')
        self.assertEqual(workbook['文书对应（内部）'].cell(2,6).value,'1-3')
        workbook.close()
        self.assertEqual(book['plan_revision'],2)

    def test_pages_invalid_fail_without_publishing_partial_book(self):
        from backend.evidence_planning import page_selection
        for value in ['0','3-1','1,1','2,1','4','1-2,2','abc']:
            with self.assertRaises(HTTPException):page_selection(value,3)
        job=self.plan()
        entry=job['plan_entries'][0]
        entry['materials'][0]['pages']='99'
        entry['purpose']='证明事实'
        response=self.create({'kind':'evidence_book','plan_id':job['id'],'plan_revision':1,'paths':['证据A.pdf','证据B.pdf'],
            'entries':[entry],'confirmed':True,'gaps_acknowledged':True})
        self.assertEqual(response.status_code,200,response.text)
        failed=self.done(response.json());self.assertEqual(failed['status'],'failed');self.assertFalse(failed['artifacts'])
        self.assertIn('选页',failed['error'])

    def test_legal_claim_cannot_be_certified_as_fact_and_omitted_page_is_gap(self):
        from backend.evidence_planning import gaps
        source={'id':'1','text':'合同约定价款10000元。','path':'a.pdf','sha256':'h','locator':'第 3 页','chunk_index':0}
        row=validate_classification({'id':'1','claim':'应返还价款。'},{'status':'supported','statement_type':'legal','evidence':[{'source_id':'1','quote':source['text']}]},[source])
        self.assertEqual(row['status'],'inference');self.assertEqual(gaps([row],[]),[])
        row['statement_type']='fact';row['status']='supported'
        entry={'claim_ids':['1'],'materials':[{'path':'a.pdf','pages':'1-2'}]}
        self.assertIn('选页',gaps([row],[entry])[0]['gap'])
        entry['materials'][0]['pages']='1,3';self.assertEqual(gaps([row],[entry]),[])

    def test_fact_review_carries_into_plan_without_another_classification(self):
        pdf(self.root/'证据A.pdf')
        fact=self.done(self.create({'kind':'fact_check','paths':['证据A.pdf'],'draft':'合同事实。'}).json())
        prefix=f'/api/case-workflows/cases/1/tasks/{fact["id"]}'
        self.client.put(prefix+'/review',json={'revision':1,'reviews':[{'id':'1','status':'rejected','note':'证明范围不足'}]})
        plan=self.done(self.create({'kind':'evidence_plan','paths':['证据A.pdf'],'draft':'合同事实。','reference_task_id':fact['id']}).json())
        self.assertEqual(plan['status'],'completed',plan)
        self.assertEqual(plan['results'][0]['review_status'],'rejected')
        self.assertEqual(plan['results'][0]['review_note'],'证明范围不足')
        self.assertEqual(plan['reference_revision'],2)
        response=self.create({'kind':'evidence_plan','paths':['证据A.pdf'],'draft':'新事实。','reference_task_id':fact['id']})
        self.assertEqual(response.status_code,409)

    def test_plan_summary_failure_resumes_without_reclassifying_or_duplicating_entries(self):
        pdf(self.root/'a.pdf');pdf(self.root/'b.pdf')
        original=self.service.call_ai
        calls={'summary':0,'classification':0}
        async def provider(model,messages):
            data=json.loads(messages[-1]['content'])
            if 'document_items' in data:
                calls['summary']+=1
                if calls['summary']==2:return 'invalid-json','','fixture'
            else:calls['classification']+=1
            return await original(model,messages)
        self.service.call_ai=provider
        job=self.done(self.create({'kind':'evidence_plan','paths':['a.pdf','b.pdf'],'draft':'合同事实。'}).json())
        self.assertEqual(job['status'],'failed');self.assertEqual(len(job['plan_entries']),1);self.assertFalse(job['artifacts'])
        prefix=f'/api/case-workflows/cases/1/tasks/{job["id"]}'
        resumed=self.client.post(prefix+'/resume')
        self.assertEqual(resumed.status_code,200)
        finished=self.done(resumed.json());self.assertEqual(finished['status'],'completed',finished)
        self.assertEqual(len(finished['plan_entries']),2)
        self.assertEqual(calls,{'summary':3,'classification':1})

    def test_plan_rejects_forged_associations_and_changed_document(self):
        job=self.plan();prefix=f'/api/case-workflows/cases/1/tasks/{job["id"]}'
        entries=job['plan_entries'];entries[0]['claim_ids']=['999']
        self.assertEqual(self.client.put(prefix+'/plan',json={'revision':1,'entries':entries}).status_code,422)
        entries[0]['claim_ids']=['1'];entries[0]['materials'][0]['path']='../outside.pdf'
        self.assertEqual(self.client.put(prefix+'/plan',json={'revision':1,'entries':entries}).status_code,422)
        # An actual document file remains a provenance input even after its text is parsed.
        (self.root/'定稿.txt').write_text('合同事实。')
        response=self.create({'kind':'evidence_plan','paths':['证据A.pdf'],'draft_path':'定稿.txt'})
        plan=self.done(response.json());self.assertEqual(plan['status'],'completed',plan)
        (self.root/'定稿.txt').write_text('改动后的定稿。')
        body={'kind':'evidence_book','plan_id':plan['id'],'plan_revision':1,'paths':['证据A.pdf'],
            'entries':[{'title':'证据','purpose':'证明合同事实','claim_ids':['1'],'materials':[{'path':'证据A.pdf','pages':''}]}],
            'confirmed':True,'gaps_acknowledged':True}
        self.assertEqual(self.create(body).status_code,409)

    def test_document_paragraph_numbers_do_not_shift_between_sentences(self):
        rows=claims_from_draft('第一句。第二句。\n\n第三句。')
        self.assertEqual([row['document_locator'] for row in rows],['第1段 · 事项1','第1段 · 事项2','第2段 · 事项3'])

    def test_legacy_stopped_book_resumes_after_document_plan_upgrade(self):
        pdf(self.root/'a.pdf')
        root,job=self.service.create(1,{'kind':'evidence_book','paths':['a.pdf'],'confirmed':True,
            'entries':[{'path':'a.pdf','title':'旧证据','purpose':'证明事实'}]})
        job['entries']=[{'path':'a.pdf','title':'旧证据','purpose':'证明事实'}]
        job['status']='cancelled'
        self.service.save(root,job)
        response=self.client.post(f'/api/case-workflows/cases/1/tasks/{job["id"]}/resume')
        self.assertEqual(response.status_code,200,response.text)
        finished=self.done(response.json())
        self.assertEqual(finished['status'],'completed',finished)
        self.assertEqual(finished['mapping'][0]['source_mappings'][0]['selected_pages'],[1])

    def test_converted_preview_tamper_is_rejected(self):
        from PIL import Image
        Image.new('RGB',(120,160),'white').save(self.root/'scan.png')
        root,job=self.service.create(1,{'kind':'evidence_book','paths':['scan.png'],'confirmed':True,
            'entries':[{'path':'scan.png','title':'图片','purpose':'证明事实'}]})
        job['status']='cancelled';self.service.save(root,job)
        prefix=f'/api/case-workflows/cases/1/tasks/{job["id"]}'
        self.assertEqual(self.client.get(prefix+'/material-info',params={'path':'scan.png'}).status_code,200)
        preview=root/'Stella办案成果'/job['id']/('preview-'+job['sources'][0]['sha256'][:20])/'material.pdf'
        preview.write_bytes(b'not the original preview')
        self.assertEqual(self.client.get(prefix+'/material-info',params={'path':'scan.png'}).status_code,409)

    def test_new_task_is_not_marked_interrupted_before_launch(self):
        root,job=self.service.create(1,{'kind':'fact_check','paths':['合同.txt'],'draft':'合同事实。'})
        self.assertEqual(self.service.load(1,job['id'])[1]['status'],'queued')
        self.service.pending[job['id']]=0  # An abandoned creation can still recover.
        self.assertEqual(self.service.load(1,job['id'])[1]['status'],'interrupted')

    def test_partial_reference_coverage_requires_review(self):
        from backend.evidence_planning import gaps
        row={'id':'1','claim':'合同与履行事实','statement_type':'fact','status':'supported','review_status':'pending',
            'evidence':[{'path':'a.pdf','locator':'第1页'},{'path':'b.pdf','locator':'第2页'}]}
        entry={'claim_ids':['1'],'materials':[{'path':'a.pdf','pages':'1'}]}
        self.assertTrue(gaps([row],[entry]))
        entry['materials'].append({'path':'b.pdf','pages':'2'})
        self.assertEqual(gaps([row],[entry]),[])

    def test_input_snapshot_is_independent_and_tampering_fails(self):
        root, job = self.service.create(1, {'kind':'fact_check','paths':['合同.txt'],'draft':'价款10000元。'})
        item = job['sources'][0]
        original = (root / item['path']).read_bytes()
        (root / item['path']).write_text('原件后来变化')
        copied = self.service.input_path(root, job, item)
        self.assertEqual(copied.read_bytes(), original)
        copied.write_text('篡改副本')
        with self.assertRaises(HTTPException) as failure:
            self.service.input_path(root, job, item)
        self.assertEqual(failure.exception.status_code, 409)

    def test_pdf_visible_annotations_and_widgets_survive_without_mutating_source(self):
        from backend.pdf_assembly import numbered_copy, append_document
        with fitz.open() as source:
            page = source.new_page(width=300, height=300)
            page.insert_text((20,40), 'Evidence')
            annotation = page.add_rect_annot(fitz.Rect(30,70,210,130))
            annotation.set_colors(stroke=(1,0,0), fill=(1,1,0))
            annotation.update()
            widget = fitz.Widget()
            widget.field_name = 'amount'
            widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
            widget.rect = fitz.Rect(30,170,200,210)
            widget.field_value = '10000'
            page.add_widget(widget)
            before = page.get_pixmap(alpha=False).samples
            with fitz.open() as merged:
                append_document(merged, source, Path('source.pdf'))
                output = numbered_copy(merged)
            with output:
                actual = output[0].get_pixmap(clip=fitz.Rect(0,0,300,300),alpha=False).samples
                self.assertEqual(actual, before)
                self.assertEqual(output[0].rect.height, 324)
            self.assertIsNotNone(source[0].first_annot)
            self.assertIsNotNone(source[0].first_widget)

    def test_fact_delivers_quotes_review_versions_and_cross_case_denial(self):
        job=self.fact();self.assertEqual(job['status'],'completed',job)
        self.assertEqual(len(job['results']),2)
        self.assertTrue(all(row['review_status']=='pending' for row in job['results']))
        prefix=f'/api/case-workflows/cases/1/tasks/{job["id"]}'
        self.assertEqual(self.client.get(prefix+'/source?source_id=1').status_code,200)
        self.assertEqual(self.client.get(f'/api/case-workflows/cases/2/tasks/{job["id"]}').status_code,404)
        response=self.client.put(prefix+'/review',json={'revision':1,'reviews':[{'id':row['id'],'status':'confirmed','note':'已核'} for row in job['results']]})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['revision'],2)
        self.assertEqual(self.client.get(prefix+'/artifacts/0?revision=1').status_code,200)
        self.assertEqual(self.client.get(prefix+'/artifacts/0?revision=99').status_code,404)
        self.assertEqual(self.client.put(prefix+'/review',json={'revision':1,'reviews':[]}).status_code,409)
        for artifact in response.json()['artifacts']:
            path=self.root/'Stella办案成果'/job['id']/artifact['path']
            if path.suffix=='.xlsx':
                wb=load_workbook(path);self.assertEqual(wb.active.max_row,3);wb.close()
            if path.suffix=='.docx':self.assertIn('事实核对',Document(path).paragraphs[0].text)

    def test_hallucinated_quote_is_never_support(self):
        row=validate_classification({'id':'1','claim':'主张'}, {'status':'supported','evidence':[{'source_id':'1','quote':'原文中没有这一句'}]}, [{'id':'1','text':'合同价款10000元。','path':'a','sha256':'h','locator':'第1页','chunk_index':0}])
        self.assertEqual(row['status'],'not_found');self.assertEqual(row['evidence'],[])

    def test_material_change_blocks_reference_review_and_resume(self):
        job=self.fact();(self.root/'合同.txt').write_text('新的材料')
        prefix=f'/api/case-workflows/cases/1/tasks/{job["id"]}'
        self.assertEqual(self.client.get(prefix+'/source?source_id=1').status_code,409)
        response=self.client.put(prefix+'/review',json={'revision':1,'reviews':[{'id':row['id'],'status':'confirmed','note':''} for row in job['results']]})
        self.assertEqual(response.status_code,409)

    def test_evidence_order_page_mapping_sources_and_unique_outputs(self):
        pdf(self.root/'a.pdf',2);pdf(self.root/'b.pdf',1,90)
        before={name:(self.root/name).read_bytes() for name in ['a.pdf','b.pdf']}
        body={'kind':'evidence_book','paths':['b.pdf','a.pdf'],'confirmed':True,'entries':[{'path':'b.pdf','title':'第二份先编','purpose':'证明事实B'},{'path':'a.pdf','title':'第一份后编','purpose':'证明事实A'}]}
        jobs=[]
        for _ in range(2):
            response=self.create(body);self.assertEqual(response.status_code,200,response.text);jobs.append(self.done(response.json()))
        for job in jobs:
            self.assertEqual(job['status'],'completed',job)
            self.assertEqual([(m['start'],m['end']) for m in job['mapping']],[(1,1),(2,3)])
            directory=self.root/'Stella办案成果'/job['id']
            artifact=next(a for a in job['artifacts'] if a['name']=='证据册.pdf')
            with fitz.open(directory/artifact['path']) as doc:
                self.assertEqual(len(doc),3);self.assertEqual(len(doc.get_toc()),2)
                self.assertIn('Stella',doc[0].get_text());self.assertIn('Anonymous',doc[0].get_text())
            workbook=load_workbook(directory/next(a for a in job['artifacts'] if a['name']=='证据目录.xlsx')['path'])
            self.assertEqual(workbook.active.cell(2,5).value,1);self.assertEqual(workbook.active.cell(3,6).value,3);workbook.close()
        self.assertNotEqual(jobs[0]['id'],jobs[1]['id'])
        for name,value in before.items():self.assertEqual((self.root/name).read_bytes(),value)

    def test_validation_traversal_symlinks_empty_and_unconfirmed(self):
        for path in ['../outside.txt','/tmp/file','Stella办案成果/a']:
            self.assertGreaterEqual(self.create({'kind':'fact_check','paths':[path],'draft':'事实。'}).status_code,400)
        (self.root/'alias.txt').symlink_to(self.root/'合同.txt')
        self.assertEqual(self.create({'kind':'fact_check','paths':['alias.txt'],'draft':'事实。'}).status_code,409)
        pdf(self.root/'a.pdf')
        self.assertEqual(self.create({'kind':'evidence_book','paths':['a.pdf'],'entries':[]}).status_code,422)
        self.assertEqual(self.create({'kind':'fact_check','paths':['合同.txt'],'draft':''}).status_code,422)

    def test_model_missing_claim_fails_without_publishing(self):
        async def broken(*args):return '{"results":[]}', '', 'fixture'
        self.service.call_ai=broken
        job=self.fact();self.assertEqual(job['status'],'failed');self.assertFalse(job['artifacts'])

    def test_stop_and_resume_checkpoint_and_restart(self):
        started=thread_event=__import__('threading').Event()
        async def slow(model,messages):
            started.set();await asyncio.sleep(100)
        self.service.call_ai=slow
        response=self.create({'kind':'fact_check','paths':['合同.txt'],'draft':'价款10000元。'})
        job=response.json();self.assertTrue(started.wait(2))
        prefix=f'/api/case-workflows/cases/1/tasks/{job["id"]}'
        result=self.client.post(prefix+'/cancel');self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['status'],'cancelled')
        async def good(model,messages):
            data=json.loads(messages[-1]['content']);return json.dumps({'results':[{'id':c['id'],'status':'not_found','reason':'未找到','evidence':[]} for c in data['claims']]}),'','fixture'
        self.service.call_ai=good
        self.assertEqual(self.client.post(prefix+'/resume').status_code,200)
        self.assertEqual(self.done(job)['status'],'completed')
        root,record=self.service.load(1,job['id']);record['status']='running';self.service.save(root,record)
        self.assertEqual(self.client.get(prefix).json()['status'],'interrupted')

    def test_formula_text_is_not_executable_in_workbook(self):
        job=self.done(self.create({'kind':'fact_check','paths':['合同.txt'],'draft':'=HYPERLINK("bad","x")'}).json())
        artifact=next(a for a in job['artifacts'] if a['name'].endswith('.xlsx'))
        wb=load_workbook(self.root/'Stella办案成果'/job['id']/artifact['path']);self.assertEqual(wb.active.cell(2,2).data_type,'s');wb.close()

    def test_draft_file_is_parsed(self):
        (self.root/'草稿.txt').write_text('价款10000元。')
        response=self.create({'kind':'fact_check','paths':['合同.txt'],'draft_path':'草稿.txt'})
        self.assertEqual(response.status_code,200,response.text)
        job=self.done(response.json());self.assertEqual(job['status'],'completed');self.assertEqual(len(job['claims']),1)

    def test_evidence_conversion_failure_never_publishes(self):
        (self.root/'invalid.docx').write_bytes(b'not-a-word-file')
        body={'kind':'evidence_book','paths':['invalid.docx'],'confirmed':True,'entries':[{'path':'invalid.docx','title':'匿名文书','purpose':'核验转换失败'}]}
        with patch('backend.case_workflows._convert_word',side_effect=RuntimeError('failed')):
            job=self.done(self.create(body).json())
        self.assertEqual(job['status'],'failed');self.assertEqual(job['artifacts'],[])
        self.assertEqual((self.root/'invalid.docx').read_bytes(),b'not-a-word-file')

    def test_entry_cannot_override_source_identity_and_review_requires_note(self):
        pdf(self.root/'a.pdf')
        body={'kind':'evidence_book','paths':['a.pdf'],'confirmed':True,'entries':[{'path':'a.pdf','title':'=Danger','purpose':'目的','sha256':'forged','start':999}]}
        job=self.done(self.create(body).json())
        self.assertNotEqual(job['mapping'][0]['sha256'],'forged');self.assertEqual(job['mapping'][0]['start'],1)
        fact=self.fact();prefix=f'/api/case-workflows/cases/1/tasks/{fact["id"]}'
        response=self.client.put(prefix+'/review',json={'revision':1,'reviews':[{'id':r['id'],'status':'rejected','note':''} for r in fact['results']]})
        self.assertEqual(response.status_code,422)

    def test_rotation_and_crop_preserve_visible_source_pixels(self):
        from PIL import Image, ImageChops
        from backend.pdf_assembly import numbered_copy
        for rotation in [0,90,180,270]:
            for cropped in [False,True]:
                with fitz.open() as source:
                    page=source.new_page();page.insert_text((60,80),'Anonymous orientation')
                    if cropped:page.set_cropbox(fitz.Rect(20,20,550,780))
                    page.set_rotation(rotation)
                    result=numbered_copy(source)
                    try:
                        a=page.get_pixmap();b=result[0].get_pixmap()
                        before=Image.frombytes('RGB',[a.width,a.height],a.samples)
                        after=Image.frombytes('RGB',[b.width,b.height],b.samples).crop((0,0,a.width,a.height))
                        self.assertIsNone(ImageChops.difference(before,after).getbbox())
                        self.assertEqual(page.rotation,rotation)
                    finally:result.close()

    def test_spreadsheet_coordinates_and_missing_formula_cache(self):
        from openpyxl import Workbook
        path=self.root/'表.xlsx';wb=Workbook();ws=wb.active
        ws['A1']='价款';ws['C1']=10000;ws['D1']='=C1*2';wb.save(path)
        parsed=asyncio.run(self.service.parse(path,False))
        self.assertIn('C1: 10000',parsed['content']);self.assertIn('无缓存，未验算',parsed['content'])
        self.assertNotIn('B1:',parsed['content'])

    def test_mixed_pdf_requires_explicit_ocr(self):
        with fitz.open() as document:
            page=document.new_page();page.insert_text((50,80),'Enough readable material in the first page of this anonymous document.')
            document.new_page();document.save(self.root/'mixed.pdf')
        job=self.done(self.create({'kind':'fact_check','paths':['mixed.pdf'],'draft':'事实。'}).json())
        self.assertEqual(job['status'],'failed');self.assertIn('OCR',job['error']);self.assertFalse(job['artifacts'])

if __name__=='__main__':unittest.main()
