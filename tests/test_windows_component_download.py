import ast
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import requests


class ComponentDownloadTests(unittest.TestCase):
    def test_retries_transient_error_and_replaces_partial_file(self):
        source = Path(__file__).resolve().parents[1] / 'scripts/windows/build_components.py'
        tree = ast.parse(source.read_text())
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('checksum', 'download')]
        bad = Mock()
        bad.__enter__ = Mock(return_value=bad)
        bad.__exit__ = Mock(return_value=False)
        bad.raise_for_status.side_effect = requests.ConnectionError('temporary')
        good = Mock()
        good.__enter__ = Mock(return_value=good)
        good.__exit__ = Mock(return_value=False)
        good.iter_content.return_value = [b'clean component']
        client = Mock(RequestException=requests.RequestException)
        client.get.side_effect = [bad, good]
        clock = Mock()
        env = {'hashlib': hashlib, 'requests': client, 'time': clock}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), 'exec'), env)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'download'
            path.write_bytes(b'partial old download')
            expected = hashlib.sha256(b'clean component').hexdigest()
            self.assertEqual(env['download']('https://example.invalid/file', path, expected)['sha256'], expected)
            self.assertEqual(path.read_bytes(), b'clean component')
            self.assertEqual(client.get.call_count, 2)
            clock.sleep.assert_called_once_with(2)


if __name__ == '__main__':
    unittest.main()
