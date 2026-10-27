"""The JavaScript bridge must not expose the native object graph."""
import unittest
import bootstrap
import sys
from unittest import mock
from junzheng_match import native
from junzheng_match.native import DesktopBridge


class BridgeBoundaryTests(unittest.TestCase):
    def test_native_window_starts_maximized(self):
        webview=mock.MagicMock()
        with mock.patch.dict(sys.modules,{'webview':webview}):native.open_desktop({'url':'http://127.0.0.1:8765'},'/profile')
        self.assertTrue(webview.create_window.call_args.kwargs['maximized'])
    def test_only_bridge_methods_are_public(self):
        bridge=DesktopBridge()
        class NativeWindow:
            pass
        native=NativeWindow();native.owner=native
        bridge._window=native
        public={name:getattr(bridge,name) for name in dir(bridge) if not name.startswith('_')}
        self.assertEqual(set(public),{'choose_data_dir','save_export','close_window'})
        self.assertTrue(all(callable(value) for value in public.values()))
