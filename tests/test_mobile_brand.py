import base64
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from fastapi.testclient import TestClient
from backend import main, mobile_brand


class MobileBrandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'frontend/static').mkdir(parents=True)
        Image.new('RGB', (1024, 1024), 'white').save(self.root/'frontend/static/app-icon-1024.png')
        Image.new('RGBA', (8, 4), 'blue').save(self.root/'frontend/stella-brand.png')
        image = Image.new('RGBA', (8, 4), (0, 0, 0, 0))
        image.putpixel((4, 2), (255, 0, 0, 255))
        raw = io.BytesIO(); image.save(raw, format='PNG')
        self.logo = 'data:image/png;base64,' + base64.b64encode(raw.getvalue()).decode()

    def test_brand_roundtrip_reset_and_corrupt_cache(self):
        first = mobile_brand.save_brand(self.root, self.logo)
        self.assertTrue(first['configured'])
        self.assertEqual(mobile_brand.read_brand(self.root), first)
        self.assertEqual(mobile_brand.save_brand(self.root, self.logo)['revision'], first['revision'])
        for size in (57, 180, 192, 512):
            image = Image.open(io.BytesIO(mobile_brand.icon_bytes(self.root,size)))
            self.assertEqual(image.size, (size,size))
            self.assertEqual(image.mode, 'RGB')
            self.assertEqual(image.getpixel((0,0)), (255,255,255))
        self.assertTrue(mobile_brand.logo_bytes(self.root).startswith(b'\x89PNG'))
        mobile_brand.save_brand(self.root,'')
        self.assertFalse(mobile_brand.read_brand(self.root)['logo'])
        (self.root/'data/mobile-brand.json').write_text('{bad')
        self.assertFalse(mobile_brand.read_brand(self.root)['configured'])

    def test_distribution_default_and_writable_runtime_are_independent(self):
        import os
        image = self.root / 'frontend/distribution-brand.png'
        image.write_bytes(base64.b64decode(self.logo.split(',', 1)[1]))
        first = mobile_brand.read_brand(self.root)
        self.assertEqual(first['logo'], self.logo)
        self.assertFalse(first['configured'])
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LEGAL_KB_RUNTIME_DIR': directory}):
            mobile_brand.save_brand(self.root, self.logo)
            self.assertTrue((Path(directory) / 'data/mobile-brand.json').exists())
            self.assertFalse((self.root / 'data/mobile-brand.json').exists())
        self.assertIn('native && logo ? publish(logo) : read()', (Path(__file__).resolve().parents[1] / 'frontend/mobile-brand.js').read_text())

    def test_bad_upload_does_not_replace_current_logo(self):
        value = mobile_brand.save_brand(self.root,self.logo)
        for bad in ('data:image/svg+xml;base64,AAAA', 'data:image/png;base64,AAAA', None, 'x' * 2100000):
            with self.assertRaises(ValueError): mobile_brand.save_brand(self.root,bad)
            self.assertEqual(mobile_brand.read_brand(self.root),value)

    def test_public_reads_but_authenticated_writes(self):
        with patch.object(main,'_RESOURCE_DIR',self.root), patch.dict('os.environ',{'LEGAL_KB_PRIVATE_MODE':'1','LEGAL_KB_ACCESS_USER':'tester','LEGAL_KB_ACCESS_PASSWORD':'fictional-test-password'}):
            client = TestClient(main.app)
            self.assertEqual(client.get('/api/brand').status_code,200)
            self.assertEqual(client.put('/api/brand',json={'logo':self.logo}).status_code,401)
            response = client.put('/api/brand',json={'logo':self.logo},auth=('tester','fictional-test-password'))
            self.assertEqual(response.status_code,200)
            self.assertTrue(response.json()['custom'])
            image = client.get('/apple-touch-icon.png')
            self.assertEqual(image.headers['cache-control'],'no-cache')
            self.assertEqual(Image.open(io.BytesIO(image.content)).size,(180,180))
            self.assertEqual(client.get('/brand-logo.png').status_code,200)

    def test_shell_and_manifest_brand_are_current(self):
        root = Path(__file__).resolve().parents[1]
        manifest=(root/'frontend/static/site.webmanifest').read_text()
        self.assertIn('Stella',manifest)
        self.assertNotIn('APEX',manifest)
        worker=(root/'frontend/case-manager-sw.js').read_text()
        self.assertIn('event.respondWith(brandResource(request))',worker)
        self.assertIn("'/static/mobile-brand.js?v=2'",worker)
        page=(root/'frontend/case-manager.html').read_text()
        self.assertIn('data-mobile-brand',page)
        self.assertIn('mobile-brand.js?v=2',page)
