import bootstrap
from pathlib import Path
from types import SimpleNamespace
import subprocess
import unittest
from unittest import mock
from junzheng_match import native


class RuntimeBootstrapTests(unittest.TestCase):
    def test_existing_runtime_never_launches_installer(self):
        with mock.patch.object(native,'os',SimpleNamespace(name='nt')),mock.patch.object(native,'webview2_version',return_value='140.0.0.1'),mock.patch.object(native.subprocess,'run') as run:
            native.ensure_webview2()
            run.assert_not_called()

    def test_missing_runtime_uses_only_bundled_bootstrapper(self):
        with mock.patch.object(native,'os',SimpleNamespace(name='nt')),mock.patch.object(native,'webview2_version',side_effect=[None,'140.0.0.1']),mock.patch.object(native.sys,'executable','/program/JunZhengMatch.exe'),mock.patch.object(Path,'is_file',return_value=True),mock.patch.object(native.subprocess,'run') as run:
            native.ensure_webview2()
            self.assertEqual(run.call_args.args[0],[str(Path('/program')/'MicrosoftEdgeWebview2Setup.exe'),'/silent','/install'])

    def test_missing_bootstrapper_does_not_launch_setup(self):
        with mock.patch.object(native,'os',SimpleNamespace(name='nt')),mock.patch.object(native,'webview2_version',return_value=None),mock.patch.object(Path,'is_file',return_value=False),mock.patch.object(native.subprocess,'run') as run:
            with self.assertRaisesRegex(RuntimeError,'缺少运行组件引导器'):native.ensure_webview2()
            run.assert_not_called()

    def test_success_exit_requires_detectable_runtime(self):
        with mock.patch.object(native,'os',SimpleNamespace(name='nt')),mock.patch.object(native,'webview2_version',return_value=None),mock.patch.object(Path,'is_file',return_value=True),mock.patch.object(native.subprocess,'run'):
            with self.assertRaisesRegex(RuntimeError,'仍未检测到'):native.ensure_webview2()

    def test_failed_component_setup_is_reported(self):
        with mock.patch.object(native,'os',SimpleNamespace(name='nt')),mock.patch.object(native,'webview2_version',return_value=None),mock.patch.object(Path,'is_file',return_value=True),mock.patch.object(native.subprocess,'run',side_effect=subprocess.CalledProcessError(7,'component-setup')):
            with self.assertRaisesRegex(RuntimeError,'运行组件未准备完成'):native.ensure_webview2()
