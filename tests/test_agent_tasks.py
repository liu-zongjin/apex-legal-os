"""Anonymous, disposable task integration tests; never import backend.main."""
import asyncio
import json
import re
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend import agent_policy
from backend.agent_tasks import add_schema, register_agent_task_routes
from backend.case_workflows import register_case_workflow_routes


class AgentTaskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='stella-agent-tests-')
        self.root = Path(self.temp.name) / 'case'
        self.root.mkdir()
        self.path = Path(self.temp.name) / 'fixture.db'
        with self.db() as conn:
            conn.executescript('''CREATE TABLE case_manager_cases(id INTEGER PRIMARY KEY,title TEXT);
                INSERT INTO case_manager_cases VALUES(1,'匿名合同纠纷'),(2,'另案');
                CREATE TABLE research_projects(id INTEGER PRIMARY KEY,case_id INTEGER,name TEXT);
                INSERT INTO research_projects VALUES(1,1,'匿名研究项目'),(2,2,'另案研究项目');
                CREATE TABLE case_manager_folder_bindings(case_id INTEGER PRIMARY KEY,real_path TEXT,inode INTEGER,device_id INTEGER);''')
            for case_id in (1, 2):
                conn.execute('INSERT INTO case_manager_folder_bindings VALUES(?,?,?,?)',
                             (case_id, str(self.root), self.root.stat().st_ino, self.root.stat().st_dev))
            add_schema(conn)
        (self.root / 'contract.txt').write_text('2026年1月1日，甲方在合同中约定价款10000元。乙方否认已收到价款。', encoding='utf-8')
        self.calls = []
        self.block = False
        self.release = threading.Event()
        self.fail_analysis = False
        self.forge_quote = False
        self.bad_references = 0
        self.fail_on_source = None
        self.analysis_batches_seen = []
        self.provider = 'fixture-model'
        self.start()

    def db(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def start(self):
        async def ai(model, messages):
            agent_policy.before_request(self.provider)
            data = next(json.loads(message['content']) for message in messages if message['role'] == 'user' and 'sources' in json.loads(message['content']))
            kind = 'analysis' if 'goal' in data else 'timeline'
            self.calls.append(kind)
            while self.block and not self.release.is_set():
                await asyncio.sleep(.01)
            if kind == 'analysis':
                self.analysis_batches_seen.append([source['id'] for source in data['sources']])
                if self.fail_analysis:
                    self.fail_analysis -= 1
                    return 'bad-json', '', model
                source = data['sources'][0]
                evidence = {'source_id': source['id'], 'passage_id': source['passages'][0]['id']}
                if self.forge_quote:
                    evidence = {'source_id': source['id'], 'quote': '不存在的引句'}
                if self.bad_references and (self.fail_on_source is None or self.fail_on_source == source['id']):
                    self.bad_references -= 1
                    evidence = {'source_id': source['id'], 'passage_id': 'absent'}
                result = {'items': [{'title': '付款情况待核', 'type': 'issue',
                                     'analysis': '材料记载收款争议，需结合凭证核对。',
                                     'evidence': [evidence],
                                     'follow_up': '核对付款凭证。'}]}
            else:
                result = {'events': [{'source_id': row['id'], 'date_text': '', 'actors': '',
                                      'description': '材料陈述付款约定及争议，待核。', 'topic': '付款',
                                      'quote': row['text'][:1000]} for row in data['sources']]}
            return json.dumps(result), '', model
        self.app = FastAPI()
        self.workflows = register_case_workflow_routes(self.app, self.db, Path(__file__).resolve().parents[1] / 'frontend',
                                                      parse_file=lambda path, consent: {'content': path.read_text()},
                                                      call_ai=ai, require_action=lambda request: None)
        self.service = register_agent_task_routes(self.app, self.db, self.workflows,
                                                  require_action=lambda request: None,
                                                  models=lambda: {'items': [{'value': 'fixture-model', 'label': '匿名模型'}], 'default_model': 'fixture-model'})
        self.client = TestClient(self.app).__enter__()

    def tearDown(self):
        self.release.set()
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def url(self, task_id='', case_id=1):
        return f'/api/agent-tasks/cases/{case_id}/tasks' + ('/' + task_id if task_id else '')

    def body(self, **changes):
        return {'request_key': 'anonymous-task-key-0001', 'paths': ['contract.txt'], 'model': 'fixture-model', **changes}

    def create(self, **changes):
        response = self.client.post(self.url(), json=self.body(**changes))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def done(self, task_id):
        for _ in range(300):
            result = self.client.get(self.url(task_id)).json()
            if result['status'] not in {'queued', 'running'}:
                return result
            time.sleep(.01)
        self.fail('durable task did not settle')

    def wait_call(self):
        for _ in range(200):
            if self.calls:
                return
            time.sleep(.01)
        self.fail('provider was not reached')

    def test_delivery_project_sources_office_and_event_cursor(self):
        job = self.done(self.create(project_id=1)['id'])
        self.assertEqual(job['status'], 'succeeded', job)
        self.assertEqual(job['delivery_status'], 'complete')
        self.assertEqual(job['review_status'], 'unreviewed')
        self.assertEqual(job['calls_used'], 2)
        self.assertEqual([s['status'] for s in job['steps']], ['completed'] * 4)
        self.assertEqual(job['project_id'], 1)
        child = job['child']
        for index, artifact in enumerate(child['artifacts']):
            response = self.client.get(f'/api/case-workflows/cases/1/tasks/{child["id"]}/artifacts/{index}')
            self.assertEqual(response.status_code, 200, response.text)
            if artifact['name'] == '材料分析草稿.docx':
                import io
                from docx import Document
                self.assertIn('材料分析草稿', '\n'.join(p.text for p in Document(io.BytesIO(response.content)).paragraphs))
        events = self.client.get(self.url(job['id']) + '/events').json()
        self.assertEqual([r['sequence'] for r in events['items']], [1, 2, 3])
        self.assertEqual(self.client.get(self.url(job['id']) + '/events', params={'after': events['cursor']}).json()['items'], [])
        ref = child['analysis_items'][0]['evidence'][0]
        self.assertEqual(self.client.get(f'/api/case-workflows/cases/1/tasks/{child["id"]}/source', params={'source_id': ref['id']}).status_code, 200)

    def test_duplicate_key_returns_original_even_after_source_changes(self):
        job = self.done(self.create()['id'])
        (self.root / 'contract.txt').write_text('材料已修改')
        retry = self.create()
        self.assertEqual(retry['id'], job['id'])
        self.assertTrue(retry['source_warning'])
        self.assertEqual(self.calls, ['timeline', 'analysis'])
        response = self.client.post(self.url(), json=self.body(goal='另一目标'))
        self.assertEqual(response.status_code, 409)

    def test_project_and_case_scope_cannot_be_overridden(self):
        self.assertEqual(self.client.post(self.url(), json=self.body(project_id=2)).status_code, 409)
        job = self.done(self.create()['id'])
        self.assertEqual(self.client.get(self.url(job['id'], case_id=2)).status_code, 404)
        self.assertEqual(self.client.post(self.url(), json=self.body(request_key='anonymous-traversal-0001', paths=['../outside.txt'])).status_code, 400)

    def test_budget_includes_requests_and_keeps_partial_checkpoints(self):
        job = self.done(self.create(max_calls=1)['id'])
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(job['calls_used'], 1)
        self.assertEqual(job['delivery_status'], 'partial')
        self.assertIn('请求上限', job['error'])
        self.assertFalse(job['child']['artifacts'])
        self.assertTrue(job['child']['timeline_batches'])
        response = self.client.post(self.url(job['id']) + '/resume', json={'generation': job['generation']})
        self.assertEqual(response.status_code, 409)

    def test_unauthorized_provider_is_rejected_before_send(self):
        self.provider = 'unapproved-provider'
        job = self.done(self.create()['id'])
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(job['calls_used'], 0)
        self.assertEqual(self.calls, [])
        self.assertIn('未向其他模型', job['error'])

    def test_invalid_analysis_can_resume_without_repeating_timeline(self):
        self.fail_analysis = 2
        job = self.done(self.create()['id'])
        self.assertEqual(job['status'], 'failed')
        child_id = job['child_id']
        response = self.client.post(self.url(job['id']) + '/resume', json={'generation': job['generation']})
        self.assertEqual(response.status_code, 200, response.text)
        job = self.done(job['id'])
        self.assertEqual(job['status'], 'succeeded', job)
        self.assertEqual(job['child_id'], child_id)
        self.assertEqual(self.calls, ['timeline', 'analysis', 'analysis', 'analysis'])
        self.assertEqual(job['child']['error'], '')

    def test_forged_quote_prevents_publication(self):
        self.forge_quote = True
        job = self.done(self.create()['id'])
        self.assertEqual(job['status'], 'failed')
        self.assertIn('原文校验', job['error'])
        self.assertEqual(job['child'].get('analysis_items', []), [])
        self.assertFalse(job['child']['artifacts'])
        response_file = self.root / 'Stella办案成果' / job['child_id'] / 'analysis-response-1.json'
        self.assertTrue(response_file.is_file())
        proposal = json.loads(json.loads(response_file.read_text())['response'])
        self.assertEqual(proposal['items'][0]['evidence'][0]['quote'], '不存在的引句')

    def test_bad_reference_is_corrected_once_with_the_original_model(self):
        self.bad_references = 1
        job = self.done(self.create()['id'])
        self.assertEqual(job['status'], 'succeeded', job)
        self.assertEqual(job['calls_used'], 3)
        self.assertEqual(self.calls, ['timeline', 'analysis', 'analysis'])
        self.assertEqual(len(job['child']['analysis_diagnostics']), 1)
        self.assertEqual(job['child']['analysis_items'][0]['evidence'][0]['match'], 'passage')

    def test_bad_json_is_corrected_without_manual_resume(self):
        self.fail_analysis = 1
        job = self.done(self.create()['id'])
        self.assertEqual(job['status'], 'succeeded', job)
        self.assertEqual(job['calls_used'], 3)
        self.assertEqual(job['child']['analysis_diagnostics'][0]['code'], 'json')

    def test_correction_never_exceeds_the_authorized_request_limit(self):
        self.bad_references = 1
        job = self.done(self.create(max_calls=2)['id'])
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(job['calls_used'], 2)
        self.assertEqual(self.calls, ['timeline', 'analysis'])
        self.assertIn('请求上限', job['error'])
        self.assertFalse(job['child']['artifacts'])

    def test_resume_keeps_completed_analysis_batches_and_the_timeline(self):
        (self.root / 'contract.txt').write_text('\n'.join(
            f'【第{index}页】\n匿名材料第{index}页记载付款争议，尚待核实。' for index in range(1, 6)))
        self.bad_references = 2
        self.fail_on_source = '5'
        job = self.done(self.create()['id'])
        self.assertEqual(job['status'], 'failed', job)
        self.assertEqual(job['child']['analysis_batches'], [0])
        self.assertEqual(len(job['child']['analysis_items']), 1)
        before = self.calls.count('timeline')
        response = self.client.post(self.url(job['id']) + '/resume', json={'generation': job['generation']})
        self.assertEqual(response.status_code, 200)
        result = self.done(job['id'])
        self.assertEqual(result['status'], 'succeeded', result)
        self.assertEqual(result['child_id'], job['child_id'])
        self.assertEqual(self.calls.count('timeline'), before)
        self.assertEqual(self.analysis_batches_seen, [['1', '2', '3', '4'], ['5'], ['5'], ['5']])
        self.assertEqual(len(result['child']['analysis_items']), 2)

    def test_one_real_pdf_with_line_wrapping_delivers_verbatim_sources(self):
        import fitz
        document = fitz.open()
        for number in (1, 2):
            page = document.new_page()
            page.insert_text((72, 72), f'Anonymous page {number}: the buyer has not\npaid RMB 10000. The payment remains disputed.')
        document.save(str(self.root / 'simple.pdf'))
        document.close()
        def parse(path, consent):
            with fitz.open(path) as pdf:
                return {'content': '\n'.join(f'【第{i + 1}页】\n' + page.get_text() for i, page in enumerate(pdf))}
        self.workflows.parse_file = parse
        job = self.done(self.create(paths=['simple.pdf'])['id'])
        self.assertEqual(job['status'], 'succeeded', job)
        self.assertEqual(job['calls_used'], 2)
        self.assertEqual(job['child']['coverage']['chunks'], 2)
        parsed = json.loads((self.root / 'Stella办案成果' / job['child_id'] / 'parsed-sources.json').read_text())
        ref = job['child']['analysis_items'][0]['evidence'][0]
        original = next(row['text'] for row in parsed['sources'] if row['id'] == ref['id'])
        self.assertIn(ref['quote'], original)
        self.assertIn('\n', ref['quote'])

    def test_pause_stale_control_resume_and_cancellation(self):
        self.block = True
        job = self.create()
        self.wait_call()
        response = self.client.post(self.url(job['id']) + '/pause', json={'generation': job['generation']})
        self.assertEqual(response.status_code, 200, response.text)
        paused = response.json()
        self.assertEqual(paused['status'], 'paused')
        self.assertEqual(self.client.post(self.url(job['id']) + '/resume', json={'generation': job['generation']}).status_code, 409)
        self.assertEqual(self.client.post(f'/api/case-workflows/cases/1/tasks/{paused["child_id"]}/resume').status_code, 409)
        self.release.set()
        response = self.client.post(self.url(job['id']) + '/resume', json={'generation': paused['generation']})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.done(job['id'])['status'], 'succeeded')

    def test_restart_recovers_and_does_not_auto_send(self):
        self.block = True
        job = self.create()
        self.wait_call()
        self.client.__exit__(None, None, None)
        count = len(self.calls)
        self.start()
        current = self.client.get(self.url(job['id'])).json()
        self.assertEqual(current['status'], 'interrupted', current)
        self.assertEqual(len(self.calls), count)
        self.release.set()
        response = self.client.post(self.url(job['id']) + '/resume', json={'generation': current['generation']})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.done(job['id'])['status'], 'succeeded')
        self.assertEqual(len(list((self.root / 'Stella办案成果').glob('*/task.json'))), 1)

    def test_source_change_blocks_resume_and_old_artifact_download(self):
        job = self.done(self.create()['id'])
        (self.root / 'contract.txt').write_text('变更后材料')
        prefix = f'/api/case-workflows/cases/1/tasks/{job["child_id"]}'
        self.assertEqual(self.client.get(prefix + '/artifacts/0').status_code, 409)
        self.assertTrue(self.client.get(self.url(job['id'])).json()['source_warning'])

    def test_atomic_child_creation_can_be_reconciled_after_parent_gap(self):
        task_id = self.service.create(1, self.body())
        task = self.service.get(1, task_id)
        body = {k: v for k, v in task['config'].items() if k not in {'project_id', 'max_calls', 'model_revision'}}
        args = (1, body, task_id, task['child_id'], [(s['path'], s['sha256']) for s in task['sources']])
        _, first = self.workflows.create_owned(*args)
        _, second = self.workflows.create_owned(*args)
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(len(list((self.root / 'Stella办案成果').glob('*/task.json'))), 1)
        self.assertEqual(self.create()['id'], task_id)
        self.assertEqual(self.done(task_id)['status'], 'succeeded')
        self.assertEqual(self.calls, ['timeline', 'analysis'])

    def test_owned_creation_cannot_be_spoofed_by_legacy_route(self):
        response = self.client.post('/api/case-workflows/cases/1/tasks', json={'kind': 'material_analysis', 'paths': ['contract.txt'], 'owner_task': 'a' * 32})
        self.assertEqual(response.status_code, 422)

    def test_runtime_task_tables_are_not_case_facts(self):
        from backend.case_ai import database_schema
        self.done(self.create()['id'])
        with self.db() as conn:
            schema = database_schema(conn)
        self.assertTrue({'agent_tasks', 'agent_steps', 'agent_commands', 'agent_events'}.isdisjoint(schema))

    def test_export_retry_with_exhausted_budget_does_not_repeat_model_calls(self):
        from unittest.mock import patch
        with patch('backend.material_analysis.build_artifacts', side_effect=OSError('anonymous conversion failure')):
            job = self.done(self.create(max_calls=2)['id'])
        self.assertEqual(job['status'], 'failed')
        self.assertTrue(job['child']['analysis_complete'])
        response = self.client.post(self.url(job['id']) + '/resume', json={'generation': job['generation']})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.done(job['id'])['status'], 'succeeded')
        self.assertEqual(self.calls, ['timeline', 'analysis'])

    def test_changed_model_configuration_prevents_resume(self):
        self.fail_analysis = 2
        job = self.done(self.create()['id'])
        self.service.models = lambda: {'items': [{'value': 'fixture-model', 'revision': 'different-service'}]}
        response = self.client.post(self.url(job['id']) + '/resume', json={'generation': job['generation']})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.calls, ['timeline', 'analysis', 'analysis'])

    def test_history_is_bounded_and_older_tasks_remain_accessible(self):
        created = {self.service.create(1, self.body(request_key=f'anonymous-history-{i:04d}')) for i in range(61)}
        first = self.client.get(self.url()).json()
        second = self.client.get(self.url(), params={'offset': first['next_offset']}).json()
        self.assertEqual(len(first['items']), 60)
        self.assertTrue(first['has_more'])
        self.assertEqual(len(second['items']), 1)
        self.assertFalse(second['has_more'])
        self.assertEqual({row['id'] for row in first['items'] + second['items']}, created)
        self.assertEqual(self.calls, [])

    def test_history_includes_goal_without_exposing_request_configuration(self):
        self.service.create(1, self.body(goal='匿名目标：核对付款期限', draft='只属于本次任务的补充文字。'))
        row = self.client.get(self.url()).json()['items'][0]
        self.assertEqual(row['goal'], '匿名目标：核对付款期限')
        self.assertNotIn('request_json', row)
        self.assertNotIn('draft', row)
        self.assertNotIn('config', row)

    def test_pasted_text_only_is_grounded_citable_and_case_scoped(self):
        draft = '【第999页】\n2026年1月1日，乙方否认已经收取价款10000元。'
        job = self.done(self.create(paths=[], draft=draft)['id'])
        self.assertEqual(job['status'], 'succeeded', job)
        self.assertEqual(self.calls, ['timeline', 'analysis'])
        child = job['child']
        self.assertEqual(child['claims'], [])
        self.assertEqual(child['coverage']['pasted_characters'], len(draft))
        ref = child['analysis_items'][0]['evidence'][0]
        self.assertEqual(ref['path'], '本次粘贴文书')
        self.assertEqual(ref['locator'], '粘贴文字片段1')
        url = f'/api/case-workflows/cases/1/tasks/{child["id"]}/source?source_id={ref["id"]}'
        self.assertEqual(self.client.get(url).text, draft)
        self.assertEqual(self.client.get(url.replace('/cases/1/', '/cases/2/')).status_code, 404)
        (self.root / '本次粘贴文书').write_text('此同名案件文件不属于粘贴来源')
        self.assertEqual(self.client.get(url).text, draft)

    def test_supplementary_text_and_files_are_both_in_the_pinned_sources(self):
        draft = '补充材料：乙方否认收到付款。' * 90
        job = self.done(self.create(draft=draft)['id'])
        self.assertEqual(job['status'], 'succeeded', job)
        self.assertEqual(self.calls, ['timeline', 'analysis'])
        cache = self.root / 'Stella办案成果' / job['child_id'] / 'parsed-sources.json'
        parsed = json.loads(cache.read_text())
        self.assertEqual([row['path'] for row in parsed['sources']], ['contract.txt', '本次粘贴文书'])
        self.assertEqual(parsed['sources'][1]['text'], draft)
        before = cache.read_bytes()
        sources = asyncio.run(self.workflows.read_sources(self.root, job['child']))
        self.assertEqual(len(sources), 2)
        self.assertEqual(cache.read_bytes(), before)

    def test_old_request_keys_keep_old_execution_semantics(self):
        from backend.agent_tasks import packed
        task_id = self.service.create(1, self.body(draft='旧任务参考文字。'))
        row = self.service.get(1, task_id)
        config = row['config']
        config.pop('material_input_version')
        with self.db() as conn:
            conn.execute('UPDATE agent_tasks SET request_json=? WHERE id=?', (packed(config), task_id))
            conn.commit()
        retried = self.service.create(1, self.body(draft='旧任务参考文字。'))
        self.assertEqual(retried, task_id)
        old = self.service.get(1, task_id)
        self.assertNotIn('material_input_version', old['config'])
        body = {k: v for k, v in config.items() if k not in {'project_id', 'max_calls', 'model_revision'}}
        _, child = self.workflows.create_owned(1, body, task_id, old['child_id'],
                    [(s['path'], s['sha256']) for s in old['sources']])
        self.assertNotIn('material_input_version', child)
        self.assertEqual(len(child['claims']), 1)

    def test_empty_text_and_files_still_rejected(self):
        response = self.client.post(self.url(), json=self.body(paths=[], draft='  '))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.calls, [])

    def test_changed_pasted_text_cannot_be_returned_as_an_old_reference(self):
        job = self.done(self.create(paths=[], draft='乙方否认已经收取10000元。')['id'])
        child = job['child']
        ref = child['analysis_items'][0]['evidence'][0]
        child['draft'] = '更改后的文字声称已经收取10000元。'
        self.workflows.save(self.root, child)
        response = self.client.get(f'/api/case-workflows/cases/1/tasks/{child["id"]}/source?source_id={ref["id"]}')
        self.assertEqual(response.status_code, 409)
        with self.assertRaises(HTTPException) as rejected:
            asyncio.run(self.workflows.read_sources(self.root, child))
        self.assertEqual(rejected.exception.status_code, 409)


if __name__ == '__main__':
    unittest.main()
