from __future__ import annotations

import ctypes
import threading
import unittest

from desktop.windows_hotkeys import WindowsHotkeys, parse_shortcut


class WindowsHotkeyTests(unittest.TestCase):
    def test_parse_shortcuts(self) -> None:
        self.assertEqual(parse_shortcut("ctrl+shift+f9"), (6, 0x78))
        self.assertEqual(parse_shortcut("ctrl+alt+space"), (3, 32))
        self.assertEqual(parse_shortcut("f8"), (0, 0x77))
        with self.assertRaises(ValueError):
            parse_shortcut("ctrl+alt")

    def test_windows_registration_dispatch_conflict_and_cleanup(self) -> None:
        called = threading.Event()
        first = WindowsHotkeys({"read": ("ctrl+shift+f23", called.set)})
        second = WindowsHotkeys({"read": ("ctrl+shift+f23", lambda: None)})
        try:
            self.assertTrue(first.start()["read"]["active"])
            # A thread message tests listener dispatch without injecting keys
            # into a user app or operating on its selected text.
            self.assertTrue(ctypes.windll.user32.PostThreadMessageW(first.thread_id, 0x0312, 1, 0))
            self.assertTrue(called.wait(2))
            conflict = second.start()["read"]
            self.assertFalse(conflict["active"])
            self.assertIn("ứng dụng khác", conflict["error"])
        finally:
            second.stop()
            first.stop()
        replacement = WindowsHotkeys({"read": ("ctrl+shift+f23", lambda: None)})
        try:
            self.assertTrue(replacement.start()["read"]["active"])
        finally:
            replacement.stop()


if __name__ == "__main__":
    unittest.main()
