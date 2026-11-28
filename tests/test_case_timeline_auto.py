import json
import sqlite3
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from docx import Document

from backend.case_timeline_discovery import discover, side_for
from backend.case_workflows import register_case_workflow_routes
from backend import ask_combined


class AutoTimelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='timeline-auto-fixture-')
        self.root = Path(self.tmp.name) / 'case'; self.root.mkdir()
        db = str(Path(self.tmp.name) / 'case.sqlite')
        conn = sqlite3.connect(db)
        conn.execute('CREATE TABLE case_manager_cases(id INTEGER PRIMARY KEY,title TEXT)')
        conn.execute("INSERT INTO case_manager_cases VALUES(1,'匿名案件')")
        conn.execute('CREATE TABLE case_manager_folder_bindings(case_id INTEGER PRIMARY KEY,real_path TEXT,inode INTEGER,device_id INTEGER)')
        conn.execute('INSERT INTO case_manager_folder_bindings VALUES(1,?,?,?)',(str(self.root),self.root.stat().st_ino,self.root.stat().st_dev))
        conn.execute('CREATE TABLE case_manager_parties(case_id INTEGER,name TEXT,role TEXT,party_group TEXT,sort_order INTEGER,id INTEGER)')
        conn.executemany('INSERT INTO case_manager_parties VALUES(?,?,?,?,?,?)',[(1,'甲公司','原告','client',0,1),(1,'乙公司','被告','other',1,2)])
        conn.commit(); conn.close()
        @contextmanager
        def get_db():
            conn=sqlite3.connect(db);conn.row_factory=sqlite3.Row
            try: yield conn
            finally: conn.close()
        async def ai(model, messages):
            data=json.loads(messages[-1]['content'])
            if 'events' in data:
                return json.dumps({'conflicts':[]}), '', model
            return json.dumps({'events':[{'source_id':row['id'],'date_text':'2026年1月1日','actors':'甲公司','description':'双方发生事项','topic':'付款','category':'履行付款','quote':row['text'].strip()} for row in data['sources']]}), '', model
        self.app=FastAPI()
        self.service=register_case_workflow_routes(self.app,get_db,Path(__file__).resolve().parents[1]/'frontend',parse_file=lambda path,consent:{'content':path.read_text()},call_ai=ai,require_action=lambda request:None)
        async def fake_parse(path, consent, model=''):
            return {'content':'【第 1 页】\n2026年1月1日甲公司付款。'}
        self.service.parse = fake_parse
        self.client=TestClient(self.app).__enter__()
    def tearDown(self):
        self.client.__exit__(None,None,None);self.tmp.cleanup()
    def done(self, job):
        for _ in range(300):
            row=self.client.get(f'/api/case-workflows/cases/1/tasks/{job["id"]}').json()
            if row['status'] not in ('queued','running'): return row
            time.sleep(.02)
        self.fail('task did not finish')
    def test_discovery_and_idempotent_auto_creation(self):
        (self.root/'原告方材料').mkdir();(self.root/'被告方材料').mkdir()
        for folder,name in [('原告方材料','民事起诉状.docx'),('被告方材料','民事答辩状.docx')]:
            document=Document();document.add_paragraph('2026年1月1日甲公司付款。');document.save(self.root/folder/name)
        (self.root/'被告方材料'/'证据清单.docx').write_bytes(b'fixture')
        (self.root/'Stella办案成果').mkdir();(self.root/'Stella办案成果'/'起诉状.docx').write_bytes(b'not input')
        scan=discover(self.root,[{'name':'甲公司','role':'原告'},{'name':'乙公司','role':'被告'}])
        self.assertEqual({x['party'] for x in scan['candidates']},{'原告方','被告方'})
        self.assertEqual(len(scan['candidates']),2)
        response=self.client.post('/api/case-workflows/cases/1/timeline-auto',json={})
        self.assertEqual(response.status_code,200,response.text); self.assertTrue(response.json()['created'])
        self.assertEqual(response.json()['party_sides'], {'原告方':'client','被告方':'other'})
        job=self.done(response.json()['job']);self.assertEqual(job['status'],'completed',job)
        self.assertEqual({row['party'] for row in job['timeline_events']},{'原告方','被告方'})
        second=self.client.post('/api/case-workflows/cases/1/timeline-auto',json={}).json()
        self.assertFalse(second['created']);self.assertEqual(second['job']['id'],job['id'])
        self.assertEqual(len(self.service.list(1)['items']),1)
    def test_simultaneous_auto_requests_start_only_one_task(self):
        from concurrent.futures import ThreadPoolExecutor
        (self.root/'原告起诉状.docx').write_text('fixture')
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses=list(pool.map(lambda _:self.client.post('/api/case-workflows/cases/1/timeline-auto',json={}), range(2)))
        self.assertTrue(all(response.status_code==200 for response in responses))
        self.assertEqual(len({response.json()['job']['id'] for response in responses}),1)
        self.assertEqual(sum(bool(response.json()['created']) for response in responses),1)
    def test_existing_timeline_automatically_appends_new_pleading(self):
        (self.root/'原告起诉状.docx').write_text('original')
        first=self.done(self.client.post('/api/case-workflows/cases/1/timeline-auto',json={}).json()['job'])
        event=first['timeline_events'][0]
        prefix=f'/api/case-workflows/cases/1/tasks/{first["id"]}'
        reviewed=self.client.put(prefix+'/timeline',json={'revision':first['revision'],'events':[{'id':event['id'],'status':'excluded','note':'用户移出'}]}).json()
        (self.root/'被告答辩状.docx').write_text('new')
        response=self.client.post('/api/case-workflows/cases/1/timeline-auto',json={})
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.json()['created'])
        job=self.done(response.json()['job'])
        self.assertEqual(job['status'],'completed',job)
        self.assertEqual(job['parent_revision'],reviewed['revision'])
        self.assertEqual(len(job['timeline_events']),2)
        self.assertEqual(next(row for row in job['timeline_events'] if row['id']==event['id'])['review_status'],'excluded')
        self.assertEqual(len(job['timeline_batches']),1)
        self.assertFalse(self.client.post('/api/case-workflows/cases/1/timeline-auto',json={}).json()['created'])
    def test_no_pleadings_offers_evidence_without_starting_ai(self):
        (self.root/'合同.txt').write_text('证据材料')
        result=self.client.post('/api/case-workflows/cases/1/timeline-auto',json={}).json()
        self.assertIsNone(result['job']);self.assertEqual(result['scan']['evidence'][0]['path'],'合同.txt')
        self.assertEqual(self.service.list(1)['items'],[])
    def test_client_side_comes_from_party_group_and_ambiguous_roles_stay_unknown(self):
        with self.service.get_db() as conn:
            conn.execute("UPDATE case_manager_parties SET party_group=CASE WHEN role='被告' THEN 'client' ELSE 'other' END")
            conn.commit()
        result=self.client.post('/api/case-workflows/cases/1/timeline-auto',json={}).json()
        self.assertEqual(result['party_sides'], {'原告方':'other','被告方':'client'})
        with self.service.get_db() as conn:
            conn.execute("INSERT INTO case_manager_parties VALUES(1,'丙','原告','client',2,3)")
            conn.commit()
        result=self.client.post('/api/case-workflows/cases/1/timeline-auto',json={}).json()
        self.assertNotIn('原告方', result['party_sides'])
    def test_discovery_checks_headings_and_skips_large_pdf(self):
        generic=Document();generic.add_paragraph('民 事 起 诉 状');generic.save(self.root/'文书一.docx')
        exhibit=Document();exhibit.add_paragraph('这是一份证据材料，收到民事起诉状之后对方通知我。');exhibit.save(self.root/'材料.docx')
        with (self.root/'很大的起诉状.pdf').open('wb') as large: large.truncate(13*1024*1024)
        scan=discover(self.root)
        self.assertEqual([row['path'] for row in scan['candidates']],['文书一.docx'])
        self.assertEqual(scan['skipped_large'],1)
        self.assertIn('材料.docx',[item['path'] for item in scan['evidence']])
    def test_whole_case_selection_avoids_reingesting_generated_outputs(self):
        from backend.case_files import _expand_ai_paths
        (self.root/'原件.txt').write_text('原件')
        (self.root/'Stella办案成果').mkdir();(self.root/'Stella办案成果'/'生成.docx').write_text('生成结果')
        self.assertEqual(_expand_ai_paths(self.root,['__CASE_ROOT__']),['原件.txt'])
    def test_incremental_job_preserves_user_exclusions_and_only_extracts_new_material(self):
        (self.root/'原告起诉状.docx').write_text('old')
        first=self.done(self.client.post('/api/case-workflows/cases/1/timeline-auto',json={}).json()['job'])
        old=first['timeline_events'][0]
        prefix=f'/api/case-workflows/cases/1/tasks/{first["id"]}'
        update={'id':old['id'],'status':'excluded','note':'用户移出'}
        reviewed=self.client.put(prefix+'/timeline',json={'revision':1,'events':[update]}).json()
        (self.root/'新增证据.txt').write_text('new')
        created=self.client.post('/api/case-workflows/cases/1/tasks',json={'kind':'timeline','paths':['新增证据.txt'],'parent_timeline_id':first['id'],'parent_revision':reviewed['revision']})
        self.assertEqual(created.status_code,200,created.text)
        job=self.done(created.json());self.assertEqual(job['status'],'completed',job)
        self.assertEqual(len(job['timeline_events']),2)
        self.assertEqual(next(row for row in job['timeline_events'] if row['id']==old['id'])['review_status'],'excluded')
        self.assertEqual(job['timeline_coverage']['processed_chunks'],2)
        self.assertEqual(len(job['timeline_batches']),1)
        self.assertEqual(self.client.post('/api/case-workflows/cases/1/tasks',json={'kind':'timeline','paths':['新增证据.txt'],'parent_timeline_id':first['id'],'parent_revision':1}).status_code,409)
    def test_material_party_can_be_corrected_when_adding_to_timeline(self):
        (self.root/'原告起诉状.docx').write_text('old')
        first=self.done(self.client.post('/api/case-workflows/cases/1/timeline-auto',json={}).json()['job'])
        (self.root/'被告方材料').mkdir()
        (self.root/'被告方材料'/'新增证据.txt').write_text('new')
        path='被告方材料/新增证据.txt'
        classification=self.client.post('/api/case-workflows/cases/1/timeline-classify',json={'paths':[path]})
        self.assertEqual(classification.json()['items'][0]['party'],'被告方')
        folder=self.client.post('/api/case-workflows/cases/1/timeline-classify',json={'paths':['被告方材料']})
        self.assertEqual([row['path'] for row in folder.json()['items']],[path])
        unnamed=self.root/'补充材料.docx';document=Document();document.add_paragraph('甲公司提交的补充材料');document.save(unnamed)
        identified=self.client.post('/api/case-workflows/cases/1/timeline-classify',json={'paths':[unnamed.name]})
        self.assertEqual(identified.json()['items'][0]['party'],'原告方')
        created=self.client.post('/api/case-workflows/cases/1/tasks',json={'kind':'timeline','paths':[path],'parent_timeline_id':first['id'],'parent_revision':first['revision'],'source_parties':{path:'原告方'}})
        self.assertEqual(created.status_code,200,created.text)
        job=self.done(created.json()); self.assertEqual(job['status'],'completed',job)
        self.assertEqual(next(row for row in job['timeline_events'] if row['evidence'][0]['path']==path)['party'],'原告方')
        self.assertEqual(next(row for row in job['sources'] if row['path']==path)['party'],'原告方')
    def test_vision_model_reads_pages_without_cloud_ocr(self):
        import asyncio
        import fitz
        path=self.root/'scan.pdf';pdf=fitz.open();pdf.new_page();pdf.save(path);pdf.close()
        original_service=register_case_workflow_routes(FastAPI(),self.service.get_db,Path(__file__).resolve().parents[1]/'frontend',parse_file=AsyncMock(),call_ai=AsyncMock(),require_action=lambda request:None)
        with patch('backend.ai_capabilities.resolve_image_input',AsyncMock(return_value=True)), \
             patch('backend.file_vision.profile',return_value={'text':'','visual_pages':[0]}), \
             patch('backend.file_vision.read_visual_pages',AsyncMock(return_value=[{'chunk_index':0,'chunk_text':'原页识读'}])):
            parsed=asyncio.run(original_service.parse(path,False,'visual-model'))
        self.assertIn('原页识读',parsed['content']);self.assertEqual(parsed['visual_pages'],[1])
        original_service.parse_file.assert_not_called()

    def test_word_preview_falls_back_to_numbered_paragraphs_without_converter(self):
        path=self.root/'原告起诉状.docx'
        document=Document();document.add_paragraph('2026年1月1日甲公司付款。');document.save(path)
        job=self.done(self.client.post('/api/case-workflows/cases/1/timeline-auto',json={}).json()['job'])
        with patch('backend.case_workflows._convert_word',side_effect=RuntimeError('未安装转换程序')):
            response=self.client.get(f'/api/case-workflows/cases/1/tasks/{job["id"]}/material-preview',params={'path':path.name,'event_id':job['timeline_events'][0]['id']})
        self.assertEqual(response.status_code,200,response.text)
        self.assertIn('第1段',response.text)
        self.assertIn('<mark>2026年1月1日甲公司付款。</mark>',response.text)

    def test_word_preview_locates_a_citation_across_table_cells(self):
        from bs4 import BeautifulSoup
        from backend.file_text import read_docx

        path = self.root/'被告答辩状.docx'
        document = Document()
        document.add_paragraph('匿名答辩材料')
        table = document.add_table(rows=3, cols=3)
        for row, values in zip(table.rows, [
            ('日期', '金额', '用途'),
            ('2026年1月1日', '112550', '购房款 & 尾款'),
            ('2026年1月1日', '１２，５５０', '购房款 & 尾款'),
        ]):
            for cell, value in zip(row.cells, values):
                cell.text = value
        document.add_paragraph('凭证附后')
        document.save(path)
        self.assertEqual(read_docx(path),
                         '匿名答辩材料\n\n日期\t金额\t用途\n\n2026年1月1日\t112550\t购房款 & 尾款'
                         '\n\n2026年1月1日\t１２，５５０\t购房款 & 尾款\n\n凭证附后')
        self.service.parse = AsyncMock(return_value={'content':'2026年1月1日\t12550\t购房款 & 尾款'})
        endpoint = '/api/case-workflows/cases/1'
        job = self.done(self.client.post(endpoint+'/timeline-auto',json={}).json()['job'])
        event = job['timeline_events'][0]
        context = self.client.post(endpoint+'/timeline-auto',json={}).json()
        self.assertEqual(context['word_locations'], {event['id']:'Word 第1表第3行'})
        response = self.client.get(f'{endpoint}/tasks/{job["id"]}/material-preview',
                                   params={'path':path.name,'event_id':event['id']})
        self.assertEqual(response.status_code,200,response.text)
        soup = BeautifulSoup(response.text, 'html.parser')
        self.assertEqual(soup.select_one('#textSummary')['data-location'], 'Word 第1表第3行')
        self.assertEqual([node.text for node in soup.select('tr.match mark')],
                         ['2026年1月1日', '１２，５５０', '购房款 & 尾款'])
        self.assertEqual([node.text for node in soup.select('.text-paper section p')],
                         ['匿名答辩材料', '凭证附后'])
        self.assertEqual(len(soup.select('mark')), 3)

    def test_pdf_citation_highlight_preserves_the_original(self):
        import fitz

        path = self.root/'被告答辩状.pdf'
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((60, 550), 'Receipt 12,550', fontsize=16)
            document.save(path)
        original = path.read_bytes()
        self.service.parse = AsyncMock(return_value={'content':'【第 1 页】\nReceipt 12550'})
        prefix = '/api/case-workflows/cases/1'
        job = self.done(self.client.post(prefix+'/timeline-auto',json={}).json()['job'])
        url = f'{prefix}/tasks/{job["id"]}/material-page'
        plain = self.client.get(url, params={'path':path.name})
        marked = self.client.get(url, params={'path':path.name,'event_id':job['timeline_events'][0]['id']})
        self.assertEqual(marked.status_code,200,marked.text if marked.status_code != 200 else '')
        self.assertGreater(float(marked.headers['x-stella-citation-y']), .5)
        self.assertNotEqual(marked.content, plain.content)
        self.assertEqual(path.read_bytes(), original)

    def test_party_subject_is_saved_through_review_and_can_be_cleared(self):
        path = self.root/'被告答辩状.docx'
        document = Document()
        document.add_paragraph('2026年1月1日收到款项。')
        document.save(path)
        self.service.parse = AsyncMock(return_value={'content':'2026年1月1日收到款项。'})
        prefix = '/api/case-workflows/cases/1'
        result = self.client.post(prefix+'/timeline-auto',json={}).json()
        self.assertEqual(result['party_subjects']['被告方'],'乙公司')
        job = self.done(result['job'])
        event, = job['timeline_events']
        self.assertEqual(event['actors'], '')
        url = f'{prefix}/tasks/{job["id"]}/timeline'

        def review(revision, **changes):
            return self.client.put(url,json={'revision':revision,'events':[{'id':event['id'],'status':'confirmed',**changes}]})

        self.assertEqual(review(job['revision'],actors='甲公司',use_source_actor=True).status_code,409)
        response = review(job['revision'],actors='乙公司',use_source_actor=True)
        self.assertEqual(response.status_code,200,response.text)
        saved = response.json()
        self.assertEqual(saved['timeline_events'][0]['original']['actors'],'')
        self.assertEqual(saved['timeline_events'][0]['actors'],'乙公司')
        unchanged = review(saved['revision']).json()
        self.assertEqual(unchanged['timeline_events'][0]['actors'],'乙公司')
        self.assertEqual(review(unchanged['revision'],actors='',actors_edited=True).status_code,422)
        response = review(unchanged['revision'],actors='',actors_edited=True,status='amended',note='复核后清空主体')
        self.assertEqual(response.status_code,200,response.text)
        cleared = response.json()
        self.assertEqual(cleared['timeline_events'][0]['actors'],'')
        self.assertTrue(cleared['timeline_events'][0]['actors_edited'])
        self.assertEqual(review(cleared['revision'],actors='乙公司',use_source_actor=True).status_code,409)


class CombinedVisionTests(unittest.IsolatedAsyncioTestCase):
    async def test_combined_uses_visual_pages_instead_of_silently_dropping_them(self):
        image={'path':Path('/fixture/scan.pdf'),'name':'scan.pdf','relative_path':'scan.pdf','visual_pages':[0]}
        transcript={'relative_path':'scan.pdf','display_name':'scan.pdf','chunk_index':0,'chunk_text':'2026年1月1日支付价款','locator':'第 1 页（模型视觉识读，待核对）','vision':True}
        with patch('backend.case_files.collect_ai_file_rows',AsyncMock(return_value=([],[image],[]))), \
             patch('backend.file_vision.read_visual_pages',AsyncMock(return_value=[transcript])) as visual:
            found, warnings=await ask_combined.file_evidence('付款', 'visual-model', {'case_id':1}, 12000, lambda:None, None, call_ai=AsyncMock())
        self.assertEqual(len(found),1);self.assertTrue(found[0]['vision'])
        self.assertIn('视觉识读',found[0]['locator']);self.assertTrue(any('核对' in note for note in warnings))
        visual.assert_awaited_once()

    async def test_vision_reader_sends_every_page_to_model_without_ocr(self):
        from backend.file_vision import read_visual_pages
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'scan.pdf';path.write_bytes(b'fixture')
            call=AsyncMock(return_value=('原页识读文字','', 'visual-model'))
            with patch('backend.file_vision.render_page',return_value='data:image/jpeg;base64,fixture'):
                result=await read_visual_pages([{'path':path,'name':'scan.pdf','relative_path':'scan.pdf','visual_pages':[0,2]}], 'visual-model', call)
            self.assertEqual(call.await_count,2)
            self.assertEqual([row['locator'] for row in result],['第 1 页（模型视觉识读，待核对）','第 3 页（模型视觉识读，待核对）'])
            self.assertTrue(all(any(block.get('type')=='image_url' for block in invocation.args[1][-1]['content']) for invocation in call.await_args_list))


if __name__=='__main__': unittest.main()
