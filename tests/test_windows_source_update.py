from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.windows.source_worker import check_source_update


class WindowsSourceUpdateCheckTests(unittest.TestCase):
    def test_missing_directory_git_and_checkout_have_distinct_messages(self):
        with tempfile.TemporaryDirectory() as path:
            root = Path(path)
            self.assertIn('源码目录', check_source_update(root / 'missing')['message'])
            with patch('shutil.which', return_value=None):
                self.assertIn('找不到 Git', check_source_update(root)['message'])
            git_version = subprocess.CompletedProcess([], 0, 'git version 2.50.0', '')
            with patch('shutil.which', return_value='git.exe'), patch('subprocess.run', return_value=git_version):
                self.assertIn('缺少 Git 仓库信息', check_source_update(root)['message'])

    def test_remote_failure_and_success_keep_distinct_results(self):
        current = 'a' * 40
        remote = 'b' * 40
        success = lambda output: subprocess.CompletedProcess([], 0, output, '')
        with tempfile.TemporaryDirectory() as path:
            root = Path(path)
            (root / '.git').mkdir()
            with patch('shutil.which', return_value='git.exe'), patch('subprocess.run') as run:
                run.side_effect = [success('git version 2.50.0'), success(current), subprocess.TimeoutExpired('git', 30)]
                self.assertIn('无法从 GitHub', check_source_update(root)['message'])
                for revision in (current, remote):
                    run.side_effect = [success('git version 2.50.0'), success(current), success(revision + '\trefs/heads/main')]
                    result = check_source_update(root)
                    self.assertEqual(result['available'], revision != current)
                    self.assertEqual(result['build'], revision)
