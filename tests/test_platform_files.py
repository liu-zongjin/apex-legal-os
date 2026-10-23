import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from backend import platform_files as files
from backend import windows_secrets
from backend import windows_picker
import threading


class DesktopFilesTests(unittest.TestCase):
    def test_existing_mac_subprocess_contract_is_preserved(self):
        with patch.object(files.sys,'platform','darwin'), patch.object(files.subprocess,'run') as run:
            files.run(['open','-R','/anonymous/file.pdf'],check=True,timeout=10)
            run.assert_called_once_with(['open','-R','/anonymous/file.pdf'],check=True,timeout=10)

    def test_windows_opens_exact_existing_path_without_shell_interpolation(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'材料 $x test.txt';path.write_text('anonymous')
            with patch.object(files.sys,'platform','win32'), patch.object(files.os,'startfile',create=True) as start:
                result=files.run(['open','--',str(path)])
                start.assert_called_once_with(str(path.resolve()))
                self.assertEqual(result.returncode,0)

    def test_windows_picker_cancellation_is_not_an_error_or_saved_binding(self):
        with patch.object(files.sys,'platform','win32'), patch.object(windows_picker,'select_path',return_value=None), patch.object(files.subprocess,'run') as run:
            result=files.run(['osascript','-e','POSIX path of (choose folder)'],text=True,capture_output=True,timeout=10)
        run.assert_not_called()
        self.assertEqual(result.returncode,128)
        self.assertEqual(result.stderr,'-128')

    def test_windows_unicode_drive_and_unc_selection_never_launches_powershell(self):
        for kind, path in [('folder', 'C:\\'), ('folder', r'\\server\共享材料'), ('file', r'C:\案件 材料\证据.pdf')]:
            with self.subTest(path=path), patch.object(files.sys,'platform','win32'), \
                    patch.object(windows_picker,'select_path',return_value=path) as choose, \
                    patch.object(files.subprocess,'run') as run:
                value=files.run(['osascript','-e','POSIX path of (choose '+kind+')'],capture_output=True,text=True,timeout=120)
                self.assertEqual(value.stdout,path)
                self.assertEqual(value.returncode,0)
                choose.assert_called_once_with(kind)
                run.assert_not_called()

    def test_picker_uses_dedicated_thread_and_releases_lock_after_failure(self):
        caller = threading.get_ident()
        def choose(kind, **kwargs):
            self.assertNotEqual(threading.get_ident(), caller)
            raise OSError('anonymous native error')
        with patch.object(windows_picker,'_dialog',side_effect=choose):
            with self.assertRaisesRegex(OSError,'anonymous native error'):
                windows_picker.select_path('folder')
        with patch.object(windows_picker,'_dialog',return_value=None):
            self.assertIsNone(windows_picker.select_path('file'))

    def test_parallel_picker_does_not_open_another_window(self):
        with windows_picker._selection_lock:
            with self.assertRaisesRegex(OSError,'已有文件选择窗口'):
                windows_picker.select_path('folder')

    @unittest.skipUnless(os.name=='nt','Windows native COM picker')
    def test_windows_native_picker_can_be_created_without_powershell_or_visible_modal(self):
        for kind in ('folder','file'):
            windows_picker.select_path(kind,show=False)

    def test_arbitrary_applescript_is_not_executed_on_windows(self):
        with patch.object(files.sys,'platform','win32'),patch.object(files.subprocess,'run') as run:
            with self.assertRaises(OSError): files.run(['osascript','-e','do shell script "anything"'])
            run.assert_not_called()

    @unittest.skipUnless(os.name=='nt','DPAPI must run on Windows')
    def test_windows_credentials_are_encrypted_and_scoped_to_runtime(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'LEGAL_KB_CONFIG_DIR':d}):
            value={'account':'anonymous','password':'disposable fixture secret'}
            windows_secrets.write('test-service','test-account',value)
            self.assertEqual(windows_secrets.read('test-service','test-account'),value)
            content=next((Path(d)/'credentials').iterdir()).read_bytes()
            self.assertNotIn(b'disposable fixture secret',content)
            windows_secrets.delete('test-service','test-account')
            self.assertEqual(windows_secrets.read('test-service','test-account'),{})


if __name__=='__main__': unittest.main()
