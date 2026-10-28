import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import case_intake


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        (self.root / 'contract.txt').write_text('甲公司与乙公司签署合同。', encoding='utf-8')
        (self.root / 'nested').mkdir()
        (self.root / 'nested' / 'notice.txt').write_text('案号为（2026）某1号。', encoding='utf-8')
        self.calls = []
        self.models = []
        async def model(model, messages):
            self.models.append(model)
            self.calls.append(messages)
            return json.dumps({'parties': [{'name':'甲公司', 'role':'原告', 'type':'单位', 'file':'contract.txt', 'source':'甲公司与乙公司签署合同'}],
                               'questions':[{'field':'case_type','question':'案由是？','value':'合同纠纷','file':'contract.txt','source':'甲公司与乙公司签署合同'},
                                            {'field':'memo','question':'无来源','value':'不应采用','source':''},
                                            {'field':'unknown','value':'不应采用','source':'notice.txt'},
                                            {'field':'case_no','question':'案号是？','value':'伪造案号','file':'contract.txt','source':'甲公司与乙公司签署合同'},
                                            {'field':'current_stage','value':'一审','file':'notice.txt','source':'案号为（2026）某1号'}]}, ensure_ascii=False), '', model
        app = FastAPI()
        case_intake.register_case_intake_routes(app, parse_file=lambda path, consent: {'content':path.read_text()},
                                                call_ai=model, require_management=lambda request: None)
        self.client = TestClient(app)
        self.token = 'a' * 32
        case_intake._SESSIONS[self.token] = (self.root, __import__('time').monotonic())

    def tearDown(self):
        case_intake._SESSIONS.clear()
        self.tmp.cleanup()

    def test_only_selected_material_reaches_model_and_missing_evidence_is_filtered(self):
        response = self.client.post('/api/case-manager/intake/recognize', json={'session':self.token,'paths':['contract.txt']})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('甲公司与乙公司签署合同', self.calls[0][1]['content'])
        self.assertNotIn('某1号', self.calls[0][1]['content'])
        self.assertEqual([x['field'] for x in response.json()['questions']], ['case_type'])
        self.assertEqual(response.json()['parties'][0]['name'], '甲公司')

    def test_recognition_uses_purpose_model_and_follows_default_when_unset(self):
        from backend import ai_config
        with patch.object(ai_config, 'AI_PREFS_PATH', self.root / 'preferences.json'):
            ai_config.save_ai_prefs({'default_model':'deepseek-v4-pro', 'purpose_models':{'case_intake':'deepseek-flash'}})
            response = self.client.post('/api/case-manager/intake/recognize', json={'session':self.token,'paths':['contract.txt']})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(self.models[-1], 'deepseek-flash')
            ai_config.save_ai_prefs({'default_model':'deepseek-v4-pro', 'purpose_models':{}})
            response = self.client.post('/api/case-manager/intake/recognize', json={'session':self.token,'paths':['contract.txt']})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(self.models[-1], 'deepseek-v4-pro')

    def test_outside_and_unselected_paths_are_rejected(self):
        (self.root / 'link.txt').symlink_to(self.root / 'contract.txt')
        for path in ('../outside.txt', 'link.txt', '/etc/passwd'):
            response = self.client.post('/api/case-manager/intake/recognize', json={'session':self.token,'paths':[path]})
            self.assertEqual(response.status_code, 400, path)
        self.assertFalse(self.calls)

    def test_ocr_requires_consent_and_no_model_call_before_consent(self):
        (self.root / 'scan.png').write_bytes(b'image')
        with patch.object(case_intake, 'resolve_image_input', AsyncMock(return_value=False)), \
             patch.object(case_intake, '_parse_ai_file', return_value={'needs_ocr':True, 'content':''}):
            response = self.client.post('/api/case-manager/intake/recognize', json={'session':self.token,'paths':['scan.png']})
        self.assertEqual(response.json()['consent_required'], ['scan.png'])
        self.assertFalse(self.calls)

    def test_text_pdf_uses_no_vision_probe_and_sends_complete_native_text(self):
        import fitz
        pdf = fitz.open()
        for text in ('FIRST_PAGE_NATIVE_TEXT', 'SECOND_PAGE_NATIVE_TEXT'):
            pdf.new_page().insert_text((50, 60), text)
        pdf.save(self.root / 'text.pdf'); pdf.close()
        with patch.object(case_intake, 'resolve_image_input', AsyncMock(side_effect=AssertionError('unneeded capability probe'))):
            response = self.client.post('/api/case-manager/intake/recognize', json={'session':self.token,'paths':['text.pdf']})
        self.assertEqual(response.status_code, 200, response.text)
        payload = json.dumps(self.calls, ensure_ascii=False)
        self.assertIn('FIRST_PAGE_NATIVE_TEXT', payload)
        self.assertIn('SECOND_PAGE_NATIVE_TEXT', payload)
        self.assertNotIn('image_url', payload)

    def test_mixed_pdf_uses_native_text_and_only_scanned_page_as_image(self):
        import fitz, io
        from PIL import Image
        buf = io.BytesIO(); Image.new('RGB', (400, 400), 'white').save(buf, format='PNG')
        pdf = fitz.open()
        pdf.new_page().insert_text((50, 60), 'NATIVE_CONTRACT_DETAILS')
        pdf.new_page().insert_image(fitz.Rect(0, 0, 400, 400), stream=buf.getvalue())
        pdf.save(self.root / 'mixed.pdf'); pdf.close()
        calls = []
        async def vision(model, messages):
            calls.append(messages)
            return json.dumps({'parties':[{'name':'甲公司','role':'原告','type':'单位','file':'mixed.pdf','page':2,'source':'原告甲公司'}],
                'questions':[{'field':'case_no','question':'案号是？','value':'（2026）某1号','file':'mixed.pdf','page':2,'source':'案号（2026）某1号'},
                             {'field':'current_stage','value':'一审','file':'mixed.pdf','page':5,'source':'一审案件'}]},ensure_ascii=False), '', model
        app = FastAPI()
        case_intake.register_case_intake_routes(app, parse_file=lambda *_: self.fail('OCR must not run'), call_ai=vision, require_management=lambda _:None)
        with patch.object(case_intake, 'resolve_image_input', AsyncMock(return_value=True)):
            response = TestClient(app).post('/api/case-manager/intake/recognize', json={'session':self.token,'paths':['mixed.pdf']})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['parties'][0]['source_mode'], 'vision')
        self.assertIn('第 2 页，模型视觉识别，请核对原件', response.json()['parties'][0]['source'])
        self.assertEqual([x['field'] for x in response.json()['questions']], ['case_no'])
        self.assertIn('NATIVE_CONTRACT_DETAILS', json.dumps(calls, ensure_ascii=False))
        images = [block for message in calls[0] if isinstance(message['content'],list) for block in message['content'] if block['type']=='image_url']
        self.assertEqual(len(images), 1)
        self.assertNotIn('base64', response.text)

    def test_unavailable_vision_falls_back_to_ocr_only_after_explicit_consent(self):
        (self.root / 'scan.png').write_bytes(b'fake')
        calls = []
        async def parse(_parser, path, consent):
            calls.append(consent)
            return {'content':'甲公司与乙公司签署合同。'} if consent else {'needs_ocr':True}
        with patch.object(case_intake, 'resolve_image_input', AsyncMock(return_value=False)), \
             patch.object(case_intake, '_parse_ai_file', side_effect=parse):
            pending = self.client.post('/api/case-manager/intake/recognize', json={'session':self.token,'paths':['scan.png'],'allow_cloud_ocr':'false'})
            self.assertEqual(pending.json()['consent_required'], ['scan.png'])
            result = self.client.post('/api/case-manager/intake/recognize', json={'session':self.token,'paths':['scan.png'],'allow_cloud_ocr':True})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(calls, [False, True])

    def test_material_changed_during_reading_discards_the_result(self):
        async def change_file(model, messages):
            (self.root / 'contract.txt').write_text('材料已经更改', encoding='utf-8')
            return '{"parties":[],"questions":[]}', '', model
        app = FastAPI()
        case_intake.register_case_intake_routes(app, parse_file=lambda path, consent:{'content':path.read_text()},
                                                call_ai=change_file, require_management=lambda _:None)
        response = TestClient(app).post('/api/case-manager/intake/recognize', json={'session':self.token,'paths':['contract.txt']})
        self.assertEqual(response.status_code, 409)
        self.assertIn('发生变化', response.json()['detail'])

    def test_ocr_text_is_labeled_for_original_review(self):
        (self.root / 'scan.png').write_bytes(b'fake')
        async def model(name, messages):
            return json.dumps({'parties':[{'name':'甲公司','file':'scan.png','source':'原告甲公司'}]}, ensure_ascii=False), '', name
        app = FastAPI()
        case_intake.register_case_intake_routes(app, parse_file=lambda *_:{'content':'原告甲公司','ocr_used':True},
                                                call_ai=model, require_management=lambda _:None)
        with patch.object(case_intake, 'resolve_image_input', AsyncMock(return_value=False)):
            response = TestClient(app).post('/api/case-manager/intake/recognize', json={'session':self.token,'paths':['scan.png'],'allow_cloud_ocr':True})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['parties'][0]['source_mode'], 'ocr')
        self.assertIn('OCR识别文字，请核对原件', response.json()['parties'][0]['source'])

    def test_invalid_model_json_fails_instead_of_writing_a_case(self):
        with self.assertRaises(Exception):
            case_intake._parse_result('无法识别')

    def test_duplicate_case_title_does_not_reach_case_creation(self):
        import ast
        from contextlib import contextmanager
        from typing import Any, Dict, List
        from fastapi import HTTPException, Request
        source = (Path(__file__).resolve().parents[1] / 'backend/case_manager.py').read_text()
        tree = ast.parse(source)
        register = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'register_case_manager_routes')
        create = next(n for n in register.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'create_case')
        app = FastAPI()
        @contextmanager
        def db():
            yield object()
        def fail(*args, **kwargs):
            raise AssertionError('duplicate case must not be modified')
        env = {'app':app, 'Request':Request, 'HTTPException':HTTPException, 'List':List, 'Dict':Dict, 'Any':Any,
               'norm':lambda value: str(value or '').strip(), 'get_db':db,
               'db_get_case':lambda conn,title: {'id':1}, 'ensure_case':fail}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[create], type_ignores=[])), '<case-manager>', 'exec'), env)
        response = TestClient(app).post('/api/case-manager/cases', json={'title':'已有案件','require_new_case':True})
        self.assertEqual(response.status_code, 409)
        self.assertIn('同名案件', response.json()['detail'])

    def test_invalid_session_and_too_many_files(self):
        self.assertEqual(self.client.post('/api/case-manager/intake/recognize', json={'session':'missing','paths':['contract.txt']}).status_code, 404)
        self.assertEqual(self.client.post('/api/case-manager/intake/recognize', json={'session':self.token,'paths':['contract.txt']*101}).status_code, 400)

if __name__ == '__main__':
    unittest.main()

class IntakeVisionBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_multiple_visual_batches_do_not_repeat_text_material(self):
        from backend import file_vision, ai_context, ai_input
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = []
            for index in range(3):
                path = root / f'{index}.png'; path.write_bytes(b'fixture')
                files.append({'name':path.name, 'path':path, 'relative_path':path.name, 'visual_pages':[0]})
            rows = [{'relative_path':'native.txt','display_name':'native.txt','chunk_index':0,
                     'chunk_text':'UNIQUE_NATIVE_SOURCE_CONTENT', 'locator':'第 1 页'}]
            async def run(repeat):
                captured = []
                async def model(name, messages):
                    captured.append(messages)
                    return '本批结果', '', name
                with patch.object(ai_context, 'model_budget', return_value=20000), \
                     patch.object(file_vision, 'render_page', return_value='data:image/jpeg;base64,YQ=='):
                    await file_vision.answer('提取案件信息', rows, files, 'fixture', '', model, repeat_text=repeat)
                visual = [batch for batch in captured if any(isinstance(message['content'], list) for message in batch)]
                return visual
            normal = await run(True)
            economical = await run(False)
            self.assertGreater(len(economical), 1)
            self.assertLessEqual(len(economical), len(normal))
            def occurrences(batches):
                return sum(json.dumps(batch, ensure_ascii=False).count('UNIQUE_NATIVE_SOURCE_CONTENT') for batch in batches)
            self.assertEqual(occurrences(economical), 1)
            self.assertGreater(occurrences(normal), 1)
            self.assertLess(sum(ai_input.size(batch) for batch in economical), sum(ai_input.size(batch) for batch in normal))
