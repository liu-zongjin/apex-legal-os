"""Immutable workbench URLs must identify the exact CSS and scripts served."""
import hashlib
from pathlib import Path
import re
import unittest


class WorkbenchAssetVersionsTests(unittest.TestCase):
    def test_workbench_asset_urls_match_content_hashes(self):
        frontend = Path(__file__).resolve().parents[1] / 'frontend'
        html = (frontend / 'case-workflows.html').read_text(encoding='utf-8')
        for name in ('case-workflows.css', 'case-workflows.js', 'agent-tasks.js'):
            with self.subTest(asset=name):
                versions = re.findall(r'/static/' + re.escape(name) + r'\?v=([^"\s]+)', html)
                version = hashlib.sha256((frontend / name).read_bytes()).hexdigest()[:16]
                self.assertEqual(versions, [version],
                                 f'Update {name} URL to its content hash; versioned assets are immutable.')
