import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.native_helpers import macos_helper


class SourceMacHelperTests(unittest.TestCase):
    def test_source_app_uses_its_own_helpers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = root / 'APEXVisionOCR'
            helper.write_text('test', encoding='utf-8')
            with patch('sys.platform', 'darwin'), patch.dict(os.environ, {'STELLA_MACOS_HELPERS_DIR': directory}):
                self.assertEqual(macos_helper('APEXVisionOCR'), helper)
                self.assertIsNone(macos_helper('APEXContactsBridge'))
                with self.assertRaises(ValueError):
                    macos_helper('../secret')


if __name__ == '__main__':
    unittest.main()
