import bootstrap
import ctypes
import io
import unittest
from unittest import mock
from junzheng_match import entrypoint


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
