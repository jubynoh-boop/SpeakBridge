"""Windows-owned shortcuts with explicit registration errors and a message loop."""
from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import wintypes
from typing import Callable


def parse_shortcut(shortcut: str) -> tuple[int, int]:
    parts = [part.strip().lower() for part in shortcut.split("+")]
    modifiers = {"ctrl": 2, "control": 2, "alt": 1, "shift": 4, "win": 8, "windows": 8, "meta": 8}
    flags = 0
    keys: list[str] = []
    for part in parts:
        if part in modifiers:
            flags |= modifiers[part]
        else:
            keys.append(part)
    if len(keys) != 1:
        raise ValueError("Use one key with optional Ctrl, Alt or Shift")
    key = keys[0]
    shifted = dict(zip("!@#$%^&*()", "1234567890"))
    if key in shifted:
        flags |= 4
        key = shifted[key]
    named = {"space": 32, "esc": 27, "escape": 27, "enter": 13, "tab": 9,
             "backspace": 8, "delete": 46, "insert": 45, "home": 36, "end": 35,
             "pageup": 33, "pagedown": 34, "up": 38, "down": 40, "left": 37, "right": 39,
             "semicolon": 186, "equal": 187, "comma": 188, "minus": 189, "period": 190,
             "slash": 191, "backquote": 192, "bracketleft": 219, "backslash": 220,
             "bracketright": 221, "quote": 222}
    if key in named:
        virtual_key = named[key]
    elif len(key) == 1 and key.isascii() and key.isalnum():
        virtual_key = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        virtual_key = 111 + int(key[1:])
    else:
        raise ValueError(f"Unsupported shortcut key: {key}")
    return flags, virtual_key


def normalize_shortcut(shortcut: str) -> str:
    flags, key = parse_shortcut(shortcut)
    names = {32: "space", 27: "esc", 13: "enter", 9: "tab", 8: "backspace", 46: "delete", 45: "insert",
             36: "home", 35: "end", 33: "pageup", 34: "pagedown", 38: "up", 40: "down", 37: "left", 39: "right",
             186: "semicolon", 187: "equal", 188: "comma", 189: "minus", 190: "period", 191: "slash",
             192: "backquote", 219: "bracketleft", 220: "backslash", 221: "bracketright", 222: "quote"}
    name = names.get(key) or (f"f{key - 111}" if 112 <= key <= 135 else chr(key).lower())
    return "+".join([name for flag, name in ((2, "ctrl"), (1, "alt"), (4, "shift"), (8, "windows")) if flags & flag] + [name])


def shortcut_pressed(shortcut: str) -> bool:
    flags, virtual_key = parse_shortcut(shortcut)
    user32 = ctypes.windll.user32
    keys = [virtual_key] + [key for flag, key in ((1, 18), (2, 17), (4, 16)) if flags & flag]
    if flags & 8 and not (user32.GetAsyncKeyState(91) & 0x8000 or user32.GetAsyncKeyState(92) & 0x8000):
        return False
    return all(user32.GetAsyncKeyState(key) & 0x8000 for key in keys)


def modifiers_pressed() -> bool:
    return any(ctypes.windll.user32.GetAsyncKeyState(key) & 0x8000 for key in (16, 17, 18, 91, 92))


class WindowsHotkeys:
    def __init__(self, bindings: dict[str, tuple[str, Callable[[], None]]]) -> None:
        self.bindings = bindings
        self.results: dict[str, dict] = {}
        self.thread_id = 0
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, name="SpeakBridge-Hotkeys", daemon=True)

    def start(self) -> dict[str, dict]:
        self.thread.start()
        if not self.ready.wait(5):
            raise RuntimeError("Windows hotkey registration timed out")
        return self.results

    def stop(self) -> None:
        if self.thread_id and self.thread.is_alive():
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)
            self.thread.join(timeout=3)
            if self.thread.is_alive():
                raise RuntimeError("Windows hotkey listener did not stop")

    @staticmethod
    def _invoke(callback: Callable[[], None], shortcut: str) -> None:
        logging.info("Windows hotkey triggered: %s", shortcut)
        try:
            callback()
        except Exception:
            logging.exception("Hotkey callback failed: %s", shortcut)

    def _run(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user32.RegisterHotKey.restype = wintypes.BOOL
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.restype = wintypes.BOOL
        user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
        callbacks: dict[int, tuple[str, Callable[[], None]]] = {}
        self.thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        message = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)  # Create this thread's message queue.
        try:
            for identifier, (name, (shortcut, callback)) in enumerate(self.bindings.items(), start=1):
                try:
                    modifiers, key = parse_shortcut(shortcut)
                    if not user32.RegisterHotKey(None, identifier, modifiers | 0x4000, key):
                        error = ctypes.get_last_error()
                        detail = "Phím tắt đang được ứng dụng khác sử dụng" if error == 1409 else f"Windows error {error}"
                        self.results[name] = {"shortcut": shortcut, "active": False, "error": detail}
                        logging.error("Cannot register %s (%s): %s", name, shortcut, detail)
                    else:
                        callbacks[identifier] = (shortcut, callback)
                        self.results[name] = {"shortcut": shortcut, "active": True, "error": ""}
                        logging.info("Windows registered %s: %s", name, shortcut)
                except ValueError as exc:
                    self.results[name] = {"shortcut": shortcut, "active": False, "error": str(exc)}
            self.ready.set()
            while True:
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result == 0:
                    break
                if result == -1:
                    raise ctypes.WinError(ctypes.get_last_error())
                if message.message == 0x0312 and int(message.wParam) in callbacks:
                    shortcut, callback = callbacks[int(message.wParam)]
                    threading.Thread(target=self._invoke, args=(callback, shortcut), daemon=True).start()
        except Exception:
            logging.exception("Windows hotkey message loop failed")
        finally:
            for identifier in callbacks:
                user32.UnregisterHotKey(None, identifier)
            self.ready.set()
