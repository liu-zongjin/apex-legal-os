import asyncio
import json
import sqlite3
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import httpx
from backend import court_dossiers as dossier
from backend.court_online_service import _validate_download_url
from backend.migrations import migrate_database


class FakeApp:
    def __init__(self): self.routes = {}; self.events = {}; self.state = types.SimpleNamespace()
    def route(self, path):
        def register(fn): self.routes[path] = fn; return fn
        return register
    get = post = route
    def on_event(self, event):
        def register(fn): self.events[event] = fn; return fn
        return register


class ChunkStream(httpx.AsyncByteStream):
    def __init__(self, body, delay=0): self.body = body; self.delay = delay
    async def __aiter__(self):
        for index in range(0, len(self.body), 65536):
            await asyncio.sleep(self.delay)
            yield self.body[index:index+65536]


class DossierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / 'test.db'
        migrate_database(self.database)
        self.owner = 'anonymous'
        self.app = FakeApp()
        self.payload = b'%PDF-1.4\n' + b'x' * (1024 * 1024) + b'\n%%EOF'
        self.mode = 'good'
        self.delay = 0
        self.calls = []
        self.max_transfers = 0
        self.active_transfers = 0
        self.material_count = 2
        with self.db() as conn:
            conn.execute('CREATE TABLE case_manager_cases(id INTEGER PRIMARY KEY,title TEXT)')
            conn.execute("INSERT INTO case_manager_cases VALUES(1,'匿名案件')")
            conn.execute('INSERT INTO court_readings(id,account_id,remote_id,case_number,court_name,status,valid_from,valid_until,case_remote_id,case_type,online,updated_at) VALUES(1,?,?,?,?,?,?,?,?,?,?,?)', ('anonymous','reading','（2026）测试1号','测试法院','11800006-3','2026-01-01 00:00:00','2099-12-31 00:00:00','case','civil',1,dossier.stamp()))
        async def headers(): return {'Authorization': 'anonymous-test-token'}
        dossier.register_dossier_routes(self.app, self.db, account_id=lambda: self.owner,
            session_headers=headers, download_directory=lambda: self.root / 'downloads',
            validate_url=_validate_download_url, court_origin='https://zxfw.court.gov.cn', frontend_dir=self.root)
        client_class = httpx.AsyncClient
        self.client_patch = patch.object(dossier.httpx, 'AsyncClient', side_effect=lambda **kwargs: client_class(transport=httpx.MockTransport(self.respond), **kwargs))
        self.client_patch.start()

    def tearDown(self): self.client_patch.stop(); self.temp.cleanup()

    def db(self):
        conn = sqlite3.connect(self.database); conn.row_factory = sqlite3.Row; return conn

    async def respond(self, request):
        path = request.url.path
        self.calls.append((path, dict(request.headers)))
        if '/wsyjxq/' in path:
            return httpx.Response(200, json={'code': 200, 'data': {'zt': '11800006-3', 'yjfs': 1,
                'yjyxqKssj': '2026-01-01 00:00:00', 'yjyxqJssj': '2099-12-31 00:00:00',
                'wsyjCls': [{'id': str(i), 'name': '介绍信.pdf' if i == 0 else '执业证.pdf', 'url': f'https://test.oss.aliyuncs.com/{i}.pdf'} for i in range(self.material_count)]}})
        if path.endswith('/aj/jzml'):
            return httpx.Response(200, json={'code': 200, 'data': {'name': '卷一', 'children': [
                {'id': '0', 'name': '证据.pdf', 'url': 'https://test.oss.aliyuncs.com/0.pdf'},
                {'id': '1', 'name': '证据.pdf', 'url': 'https://test.oss.aliyuncs.com/1.pdf'},
                {'id': 'denied', 'name': '受限.pdf', 'url': 'https://test.oss.aliyuncs.com/2.pdf', 'canDownload': False}]}})
        if path.endswith('/wsyj'):
            return httpx.Response(200, json={'code': 200, 'data': {'records': [], 'total': 0}})
        if request.url.host == 'test.oss.aliyuncs.com':
            self.assertNotIn('authorization', request.headers)
            if self.mode == 'denied': return httpx.Response(403)
            if self.mode == 'expired-once' and sum(p == path for p, h in self.calls) == 1: return httpx.Response(403)
            if self.mode == 'partial' and path == '/1.pdf': return httpx.Response(500)
            if self.mode == 'html': return httpx.Response(200, headers={'content-type':'text/html'}, content=b'<html>login</html>')
            headers = {'content-type':'application/pdf', 'etag':'"fixture-v1"'}
            body = self.payload
            status = 200
            if 'range' in request.headers and self.mode != 'ignore-range':
                offset = int(request.headers['range'].split('=')[1].split('-')[0])
                body = body[offset:]; status = 206
                headers['content-range'] = f'bytes {offset}-{len(self.payload)-1}/{len(self.payload)}'
            if self.mode != 'unknown-size': headers['content-length'] = str(len(body))
            return httpx.Response(status, headers=headers, stream=ChunkStream(body, self.delay))
        raise AssertionError('unexpected request ' + path)

    async def create(self, source='application-test', ids=None):
        body = {'source': source}
        if ids is not None: body['file_ids'] = ids
        return await self.app.routes[dossier.PREFIX+'/readings/{reading_id}/downloads'](1, body)

    async def wait_done(self, identity):
        for _ in range(500):
            item = await self.app.routes[dossier.PREFIX+'/downloads/{job_id}'](identity)
            if item['state'] in dossier.TERMINAL or item['state'] == 'paused': return item
            await asyncio.sleep(.01)
        self.fail('job did not finish')

    async def control(self, identity, action):
        return await self.app.routes[dossier.PREFIX+'/downloads/{job_id}/{action}'](identity, action)

    def test_real_stream_and_zip_directory_order_and_manifest(self):
        async def exercise():
            created = await self.create('dossier')
            item = await self.wait_done(created['id'])
            self.assertEqual(item['state'], 'completed')
            self.assertEqual(item['file_count'], 2)
            with zipfile.ZipFile(item['zip_path']) as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(archive.namelist()[:2], ['原始文件/卷一/证据.pdf','原始文件/卷一/证据-0002.pdf'])
                self.assertEqual(archive.read(archive.namelist()[0]), self.payload)
                self.assertEqual(json.loads(archive.read('文件清单.json'))['来源'], '法院开放卷宗')
            with self.db() as conn:
                stored = str(conn.execute('SELECT * FROM court_download_files').fetchall())
                self.assertNotIn('https://', stored)
        asyncio.run(exercise())

    def test_application_materials_are_explicit_test_source(self):
        async def exercise():
            item = await self.wait_done((await self.create())['id'])
            self.assertIn('申请材料打包测试', item['title'])
            with zipfile.ZipFile(item['zip_path']) as archive:
                self.assertEqual(json.loads(archive.read('文件清单.json'))['来源'], '申请材料打包测试')
        asyncio.run(exercise())

    def test_pause_then_verified_range_resume(self):
        self.delay = .005
        async def exercise():
            created = await self.create(ids=['0'])
            await asyncio.sleep(.04)
            paused = await self.control(created['id'], 'pause')
            self.assertEqual(paused['state'], 'paused')
            self.assertGreater(paused['downloaded_bytes'], 0)
            await self.control(created['id'], 'resume')
            item = await self.wait_done(created['id'])
            self.assertEqual(item['state'], 'completed')
            self.assertTrue(any('range' in h for p,h in self.calls))
            with zipfile.ZipFile(item['zip_path']) as archive: self.assertEqual(archive.read(archive.namelist()[0]), self.payload)
        asyncio.run(exercise())

    def test_server_ignoring_range_restarts_file(self):
        self.mode = 'ignore-range'; self.delay = .005
        async def exercise():
            created = await self.create(ids=['0']); await asyncio.sleep(.04)
            await self.control(created['id'], 'pause'); await self.control(created['id'], 'resume')
            item = await self.wait_done(created['id'])
            self.assertEqual(item['downloaded_bytes'], len(self.payload))
            with zipfile.ZipFile(item['zip_path']) as archive: self.assertEqual(archive.read(archive.namelist()[0]), self.payload)
        asyncio.run(exercise())

    def test_partial_failure_and_retry_reuses_successful_file(self):
        self.mode = 'partial'
        async def exercise():
            created = await self.create(); item = await self.wait_done(created['id'])
            self.assertEqual(item['state'], 'partial'); self.assertEqual(item['failed_count'], 1)
            with zipfile.ZipFile(item['zip_path']) as archive:
                manifest = json.loads(archive.read('文件清单.json'))['文件']
                self.assertEqual(manifest[1]['状态'], 'failed')
            self.mode = 'good'; await self.control(created['id'], 'retry')
            item = await self.wait_done(created['id']); self.assertEqual(item['state'], 'completed')
            self.assertEqual(sum(p == '/0.pdf' for p,h in self.calls), 1)
        asyncio.run(exercise())

    def test_html_and_invalid_pdf_never_complete_or_create_empty_zip(self):
        for mode in ['html','good']:
            self.mode = mode
            if mode == 'good': self.payload = b'not a pdf'
            async def exercise():
                item = await self.wait_done((await self.create(ids=['0']))['id'])
                self.assertEqual(item['state'], 'failed'); self.assertIsNone(item['zip_path'])
            asyncio.run(exercise())

    def test_unknown_size_is_honest_and_final_size_is_resolved(self):
        self.mode = 'unknown-size'; self.delay = .006
        async def exercise():
            created = await self.create(ids=['0']); await asyncio.sleep(.02)
            progress = await self.app.routes[dossier.PREFIX+'/downloads/{job_id}'](created['id'])
            self.assertIsNone(progress['total_bytes']); self.assertIsNone(progress['download_percent'])
            item = await self.wait_done(created['id']); self.assertEqual(item['total_bytes'],len(self.payload))
        asyncio.run(exercise())

    def test_access_failure_pauses_instead_of_empty_zip(self):
        self.mode='denied'
        async def exercise():
            item=await self.wait_done((await self.create(ids=['0']))['id'])
            self.assertEqual(item['state'],'paused');self.assertIsNone(item['zip_path'])
        asyncio.run(exercise())

    def test_expired_link_is_refreshed_once(self):
        self.mode='expired-once'
        async def exercise():
            item=await self.wait_done((await self.create(ids=['0']))['id'])
            self.assertEqual(item['state'],'completed')
            self.assertEqual(sum('/wsyjxq/' in p for p,h in self.calls), 3)
        asyncio.run(exercise())

    def test_current_account_cannot_read_another_accounts_job(self):
        async def exercise():
            created=await self.create();await self.wait_done(created['id']);self.owner='different'
            with self.assertRaises(Exception) as caught: await self.app.routes[dossier.PREFIX+'/downloads/{job_id}'](created['id'])
            self.assertEqual(caught.exception.status_code,404)
        asyncio.run(exercise())

    def test_duplicate_click_and_cancel(self):
        self.delay=.01
        async def exercise():
            first=await self.create(ids=['0']); second=await self.create(ids=['0'])
            self.assertEqual(first['id'],second['id'])
            await asyncio.sleep(.03);item=await self.control(first['id'],'cancel')
            self.assertEqual(item['state'],'cancelled');self.assertIsNone(item['zip_path'])
        asyncio.run(exercise())

    def test_restart_recovers_as_paused_and_retains_completed_files(self):
        async def exercise():
            created=await self.create();await self.wait_done(created['id'])
            with self.db() as conn:conn.execute("UPDATE court_download_jobs SET state='downloading' WHERE id=?",(created['id'],))
            await self.app.events['startup']()
            item=await self.app.routes[dossier.PREFIX+'/downloads/{job_id}'](created['id'])
            self.assertEqual(item['state'],'paused');self.assertEqual(item['completed_count'],2)
            await self.control(created['id'],'resume');self.assertEqual((await self.wait_done(created['id']))['state'],'completed')
        asyncio.run(exercise())

    def test_many_files_and_big_chunked_file(self):
        self.material_count=120;self.payload=b'%PDF-1.4\n'+b'x'*4096
        async def exercise():
            item=await self.wait_done((await self.create())['id'])
            self.assertEqual(item['state'],'completed');self.assertEqual(item['file_count'],120)
            with zipfile.ZipFile(item['zip_path']) as archive:self.assertEqual(len(archive.namelist()),121)
        asyncio.run(exercise())

    def test_file_larger_than_old_delivery_limit_is_streamed(self):
        class LargeStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'%PDF-1.4\n'
                chunk = b'x' * 65536
                for _ in range(1024): yield chunk
        original = self.respond
        async def large(request):
            if request.url.host == 'test.oss.aliyuncs.com':
                return httpx.Response(200, headers={'content-type':'application/pdf','content-length':str(64*1024*1024+9)}, stream=LargeStream())
            return await original(request)
        self.respond = large
        async def exercise():
            item=await self.wait_done((await self.create(ids=['0']))['id'])
            self.assertEqual(item['state'],'completed')
            self.assertEqual(item['downloaded_bytes'],64*1024*1024+9)
            with zipfile.ZipFile(item['zip_path']) as archive: self.assertIsNone(archive.testzip())
        asyncio.run(exercise())

    def test_account_switch_hook_pauses_running_and_queued_jobs(self):
        self.delay=.01
        async def exercise():
            first=await self.create(ids=['0']);second=await self.create(ids=['1'])
            await asyncio.sleep(.02)
            await self.app.state.pause_court_dossier_jobs()
            for item in [first,second]:
                state=await self.app.routes[dossier.PREFIX+'/downloads/{job_id}'](item['id'])
                self.assertEqual(state['state'],'paused')
        asyncio.run(exercise())

    def test_packing_pause_is_cooperative_and_resume_does_not_redownload(self):
        import threading,time
        entered=threading.Event()
        original=dossier.build_zip
        def slow_pack(directory,files,title,source,stop):
            entered.set()
            for _ in range(100):
                if stop.is_set():raise InterruptedError()
                time.sleep(.002)
            return original(directory,files,title,source,stop)
        async def exercise():
            with patch.object(dossier,'build_zip',side_effect=slow_pack):
                created=await self.create()
                while not entered.is_set():await asyncio.sleep(.005)
                paused=await self.control(created['id'],'pause')
                self.assertEqual(paused['state'],'paused');self.assertIsNone(paused['zip_path'])
                self.assertEqual(paused['completed_count'],2)
                await self.control(created['id'],'resume')
                done=await self.wait_done(created['id']);self.assertEqual(done['state'],'completed')
                self.assertEqual(sum(p=='/0.pdf' for p,h in self.calls),1)
        asyncio.run(exercise())

    def test_missing_successful_original_is_downloaded_again_before_repack(self):
        async def exercise():
            created=await self.create();done=await self.wait_done(created['id'])
            (Path(done['directory'])/'原始文件'/done['files'][0]['relative_path']).unlink()
            with self.db() as conn:conn.execute("UPDATE court_download_jobs SET state='paused' WHERE id=?",(created['id'],))
            await self.control(created['id'],'resume')
            done=await self.wait_done(created['id'])
            self.assertEqual(done['state'],'completed')
            self.assertEqual(sum(p=='/0.pdf' for p,h in self.calls),2)
        asyncio.run(exercise())

    def test_validity_requires_approved_online_and_effective_dates(self):
        row={'status':'11800006-3','online':1,'valid_from':'2026-01-01 00:00:00','valid_until':'2099-01-01 00:00:00'}
        self.assertTrue(dossier.is_open(row))
        for change in [{'online':0},{'status':'11800006-2'},{'valid_until':'2020-01-01 00:00:00'},{'valid_from':None}]:self.assertFalse(dossier.is_open({**row,**change}))

    def test_path_traversal_and_download_denial(self):
        files=dossier.flatten_directory({'name':'../卷','children':[{'id':'a','name':'../../x.pdf','url':'https://test.oss.aliyuncs.com/x.pdf'},{'id':'b','name':'denied.pdf','url':'https://test.oss.aliyuncs.com/y.pdf','canDownload':False}]})
        self.assertEqual(len(files),1)
        self.assertNotIn('..',Path(files[0]['relative_path']).parts)
        with self.assertRaises(Exception):_validate_download_url('http://localhost/private.pdf')
