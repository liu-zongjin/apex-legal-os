"""Isolated source runtime default-on settings and sender lifecycle, never real telemetry."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.source_statistics import install_source_statistics


class SourceStatisticsTests(unittest.TestCase):
    def test_default_reporting_origin_and_source_channel(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', {
            'STELLA_SOURCE_STATISTICS': '1', 'LEGAL_KB_RUNTIME_DIR': folder}), patch(
                'scripts.windows.windows_telemetry.post_event', return_value=True) as post:
            app = FastAPI(); install_source_statistics(app)
            with TestClient(app) as client:
                self.assertTrue(client.get('/api/source-statistics').json()['allowed'])
                self.assertEqual(client.put('/api/source-statistics',json={'allowed':True},headers={'Origin':'https://foreign.test'}).status_code,403)
                self.assertEqual(client.put('/api/source-statistics',json={'allowed':'true'},headers={'Origin':'http://testserver'}).status_code,422)
                for _ in range(50):
                    if post.called: break
                    time.sleep(.01)
                post.assert_called_once()
                self.assertEqual(post.call_args[0][0]['channel'],'source')
                self.assertEqual(set(post.call_args[0][0]),{'install_id','version','os','channel'})
                self.assertEqual(client.put('/api/source-statistics',json={'allowed':False},headers={'Origin':'http://testserver'}).status_code,200)

    def test_public_runtime_does_not_enable_second_sender(self):
        with patch.dict('os.environ', {'STELLA_SOURCE_STATISTICS':'0'}):
            app=FastAPI();install_source_statistics(app)
            with TestClient(app) as client:
                self.assertFalse(client.get('/api/source-statistics').json()['enabled'])

    def test_existing_opt_out_is_preserved_on_source_startup(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', {
            'STELLA_SOURCE_STATISTICS':'1','LEGAL_KB_RUNTIME_DIR':folder}), patch(
                'scripts.windows.windows_telemetry.post_event',return_value=True) as post:
            path=Path(folder)/'userdata'/'anonymous-statistics.json'
            path.parent.mkdir();path.write_text(json.dumps({'allowed':False,'install_id':'','last_attempt':None}))
            app=FastAPI();install_source_statistics(app)
            with TestClient(app) as client:
                self.assertFalse(client.get('/api/source-statistics').json()['allowed'])
                self.assertFalse(post.called)
