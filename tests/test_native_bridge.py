"""The JavaScript bridge must not expose the native object graph."""
import unittest
import bootstrap
from junzheng_match.native import DesktopBridge


class BridgeBoundaryTests(unittest.TestCase):
    def test_only_bridge_methods_are_public(self):
        bridge=DesktopBridge()
        class NativeWindow:
            pass
        native=NativeWindow();native.owner=native
        bridge._window=native
        public={name:getattr(bridge,name) for name in dir(bridge) if not name.startswith('_')}
        self.assertEqual(set(public),{'choose_data_dir','save_export','close_window'})
        self.assertTrue(all(callable(value) for value in public.values()))
