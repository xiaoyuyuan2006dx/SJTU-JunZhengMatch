import bootstrap
import ctypes
import io
from pathlib import Path
import unittest
from unittest import mock
from junzheng_match import entrypoint


class BrowserLaunchTests(unittest.TestCase):
    def test_missing_default_browser_has_a_visible_url_error(self):
        store=mock.MagicMock()
        with mock.patch.object(entrypoint.sys,'argv',['app']),mock.patch.object(entrypoint.preferences,'PreferenceStore',return_value=store),mock.patch.object(entrypoint.preferences,'prepare_folder',return_value=Path('/test-data')),mock.patch.object(entrypoint.runtime,'ensure_backend',return_value={'url':'http://127.0.0.1:8765'}),mock.patch.object(entrypoint.webbrowser,'open',return_value=False),mock.patch.dict(entrypoint.os.environ,{},clear=True):
            with self.assertRaisesRegex(RuntimeError,'http://127.0.0.1:8765'):entrypoint.main()


class StorageValidationTests(unittest.TestCase):
    def test_equal_or_nested_program_data_is_rejected_without_creating_files(self):
        from junzheng_match import preferences
        with mock.patch.object(entrypoint.sys,'frozen',True,create=True),mock.patch.object(entrypoint.sys,'executable',str(Path('/test-program/JunZhengMatch.exe'))):
            for folder in ('/test-program','/test-program/data'):
                with self.subTest(folder=folder),mock.patch.object(Path,'mkdir') as mkdir:
                    with self.assertRaisesRegex(ValueError,'数据目录不能与程序安装目录相同'):preferences.prepare_folder(folder)
                    mkdir.assert_not_called()


class WindowsFailureHandlingTests(unittest.TestCase):
    def exercise(self,arguments):
        native=mock.MagicMock();log_path=mock.MagicMock();stderr=io.StringIO()
        with mock.patch.object(entrypoint,'main',side_effect=ValueError('invalid setup location')),mock.patch.object(entrypoint,'Path',return_value=log_path),mock.patch.object(entrypoint.os,'name','nt'),mock.patch.object(entrypoint.sys,'argv',arguments),mock.patch.object(entrypoint.sys,'stderr',stderr),mock.patch.object(ctypes,'windll',native,create=True):
            with self.assertRaises(SystemExit) as result:entrypoint.launch()
        self.assertEqual(result.exception.code,1)
        return native,stderr.getvalue()
    def test_installer_failure_exits_without_a_hidden_dialog(self):
        native,stderr=self.exercise(['app','--configure-data','invalid'])
        native.user32.MessageBoxW.assert_not_called()
        self.assertIn('invalid setup location',stderr)
    def test_interactive_failure_has_one_explicit_message(self):
        native,_=self.exercise(['app','--desktop'])
        native.user32.MessageBoxW.assert_called_once()
