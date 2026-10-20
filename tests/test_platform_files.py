import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from backend import platform_files as files
from backend import windows_secrets


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
        fake=subprocess.CompletedProcess([],128,b'',b'')
        with patch.object(files.sys,'platform','win32'), patch.object(files.subprocess,'run',return_value=fake):
            result=files.run(['osascript','-e','POSIX path of (choose folder)'],text=True,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,128)
        self.assertEqual(result.stderr,'-128')

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
