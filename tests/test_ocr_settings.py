import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend import ocr_service as ocr


def response(status=200, data=None):
    return httpx.Response(status, json=data if data is not None else {
        "code": "0", "data": [{"result": [{"status": 200, "elements": {
            "text": [{"text": "STELLA OCR TEST 123456"}]
        }}]}],
    })


class OcrSettingsTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.values = {"SCNET_API_KEY": "fixture-shared-secret"}
        self.saves = []

        def save(values):
            self.saves.append(dict(values))
            self.values.update(values)

        self.settings = ocr.OcrSettings(lambda name, default="": os.environ.get(name, self.values.get(name, default)), save)
        self.app = FastAPI()
        self.guards = []
        ocr.register_ocr_routes(self.app, self.settings, self.guards.append, Path(self.temp.name))
        self.client = TestClient(self.app)

    def test_default_inherits_existing_key_without_exposing_credentials(self):
        result = self.client.get("/api/ocr-settings")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers['cache-control'], 'no-store')
        self.assertTrue(result.json()["configured"])
        self.assertEqual(self.settings.key(), "fixture-shared-secret")
        self.assertNotIn("fixture-shared-secret", result.text)
        self.assertIsNone(result.json()['test'])

    def test_dedicated_save_and_switch_back_preserve_model_credentials(self):
        result = self.client.put('/api/ocr-settings', json={'key_mode':'dedicated', 'api_key':'fixture-ocr-secret'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.settings.key(), 'fixture-ocr-secret')
        self.assertEqual(self.values['SCNET_API_KEY'], 'fixture-shared-secret')
        self.assertNotIn('fixture-ocr-secret', result.text)
        self.client.put('/api/ocr-settings', json={'key_mode':'dedicated', 'api_key':''})
        self.assertEqual(self.settings.key(), 'fixture-ocr-secret')
        self.client.put('/api/ocr-settings', json={'key_mode':'shared'})
        self.assertEqual(self.settings.key(), 'fixture-shared-secret')
        self.assertEqual(self.values['SCNET_OCR_API_KEY'], 'fixture-ocr-secret')

    def test_missing_and_managed_keys_are_not_silently_overwritten(self):
        self.assertEqual(self.client.put('/api/ocr-settings', json={'key_mode':'dedicated'}).status_code, 400)
        self.assertEqual(self.client.put('/api/ocr-settings', json={'key_mode':'other'}).status_code, 400)
        self.assertEqual(self.saves, [])
        with patch.dict(os.environ, {'SCNET_OCR_API_KEY':'environment-key', 'SCNET_OCR_KEY_MODE':'dedicated'}):
            self.assertTrue(self.client.get('/api/ocr-settings').json()['managed_key'])
            self.assertEqual(self.client.put('/api/ocr-settings', json={'key_mode':'dedicated','api_key':'replacement'}).status_code, 409)
            self.assertEqual(self.client.put('/api/ocr-settings', json={'key_mode':'shared'}).status_code, 409)
            self.assertEqual(self.settings.key(), 'environment-key')
        self.assertEqual(self.saves, [])

    def test_cross_origin_mutations_cannot_save_or_send_test_requests(self):
        with patch.object(ocr.httpx, 'post') as post:
            for method, path in [('put','/api/ocr-settings'),('post','/api/ocr-settings/test')]:
                result = getattr(self.client, method)(path, headers={'Origin':'https://untrusted.example'}, json={'key_mode':'shared'})
                self.assertEqual(result.status_code, 403)
            post.assert_not_called()
        self.assertEqual(self.saves, [])
        self.assertEqual(len(self.guards), 2)

    def test_test_calls_real_ocr_transport_with_synthetic_image(self):
        with patch.object(ocr.httpx, 'post', return_value=response()) as post:
            result = self.client.post('/api/ocr-settings/test').json()
        self.assertTrue(result['ok'])
        self.assertIn('123456', result['text'])
        args, kwargs = post.call_args
        self.assertEqual(args[0], ocr.OCR_URL)
        self.assertEqual(kwargs['data'], {'ocrType':'GENERAL'})
        self.assertEqual(kwargs['headers'], {'Authorization':'Bearer fixture-shared-secret'})
        self.assertEqual(kwargs['files']['file'][0], 'stella_ocr_test.png')
        self.assertTrue(kwargs['files']['file'][1].startswith(b'\x89PNG'))
        self.assertEqual(self.client.get('/api/ocr-settings').json()['test'], result)
        self.values['SCNET_API_KEY'] = 'changed-shared-secret'
        self.assertIsNone(self.client.get('/api/ocr-settings').json()['test'])

    def test_transport_error_and_request_id_are_safe_and_actionable(self):
        error = {'error': {'message':'RAW_PRIVATE_BODY'}, 'request_id':'anonymous-request-123'}
        with patch.object(ocr.httpx, 'post', return_value=response(435, error)) as post:
            result = self.client.post('/api/ocr-settings/test').json()
        self.assertFalse(result['ok'])
        self.assertEqual(post.call_count, 1)
        self.assertIn('435', result['message'])
        self.assertIn('anonymous-request-123', result['message'])
        self.assertNotIn('RAW_PRIVATE_BODY', json.dumps(result))
        self.assertEqual(result['text'], '')

    def test_no_key_prevents_outbound_request_and_empty_response_is_not_success(self):
        self.values.clear()
        with patch.object(ocr.httpx, 'post') as post:
            self.assertFalse(self.client.post('/api/ocr-settings/test').json()['ok'])
            post.assert_not_called()
        self.values['SCNET_API_KEY'] = 'fixture-key'
        with patch.object(ocr.httpx, 'post', return_value=response(data={'code':0,'data':[]})):
            self.assertFalse(self.client.post('/api/ocr-settings/test').json()['ok'])

    def test_retry_policy_is_bounded_and_does_not_retry_invalid_credentials(self):
        with patch.object(ocr.httpx, 'post', side_effect=[response(435), response()]) as post, patch.object(ocr.time, 'sleep'):
            self.assertIn('123456', ocr.recognize(b'fixture', api_key='fixture-key'))
            self.assertEqual(post.call_count, 2)
        for status in (401, 402, 422, 438):
            with self.subTest(status=status), patch.object(ocr.httpx, 'post', return_value=response(status)) as post:
                with self.assertRaises(ocr.OcrError):
                    ocr.recognize(b'fixture', api_key='fixture-key')
                self.assertEqual(post.call_count, 1)

    def test_malformed_response_and_timeout_do_not_expose_server_body(self):
        for data in ([], {'code':0,'data':'bad'}, {'code':0,'data':[{'result':[{'elements':{'text':['bad']}}]}]}):
            with patch.object(ocr.httpx, 'post', return_value=response(data=data)):
                result = self.client.post('/api/ocr-settings/test').json()
                self.assertFalse(result['ok'])
        with patch.object(ocr.httpx, 'post', side_effect=httpx.ConnectError('private diagnostic')):
            result = self.client.post('/api/ocr-settings/test').json()
        self.assertIn('网络',result['message'])
        self.assertNotIn('private diagnostic',result['message'])

    def test_only_one_test_runs_at_a_time(self):
        self.settings.test_lock.acquire()
        try:
            self.assertEqual(self.client.post('/api/ocr-settings/test').status_code,409)
        finally:
            self.settings.test_lock.release()

    def test_normal_parser_uses_the_same_dedicated_key(self):
        from backend import main
        self.values.update(SCNET_OCR_KEY_MODE='dedicated', SCNET_OCR_API_KEY='fixture-dedicated')
        with patch.object(main, 'ocr_settings', self.settings), patch.object(ocr.httpx, 'post', return_value=response()) as post:
            self.assertIn('123456', main._ocr_page_image(b'fixture'))
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer fixture-dedicated')

    def test_private_writer_preserves_other_settings_and_restricts_permissions(self):
        from backend import main
        with patch.object(main.ai_config_module, 'configuration_directory', return_value=Path(self.temp.name)), patch.object(
            main.ai_config_module, '_local_ai_secrets', SimpleNamespace(SCNET_API_KEY='fixture-model-secret', OTHER_SECRET='keep-existing')
        ), patch.object(main, '_reload_ai_runtime') as reload:
            main._save_ocr_secrets({'SCNET_OCR_KEY_MODE':'dedicated','SCNET_OCR_API_KEY':'fixture-ocr-secret'})
        saved=Path(self.temp.name)/'local_ai_secrets.py'
        self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
        self.assertIn('fixture-model-secret', saved.read_text())
        self.assertIn('keep-existing', saved.read_text())
        self.assertIn('fixture-ocr-secret', saved.read_text())
        reload.assert_called_once()


if __name__ == '__main__':
    unittest.main()
