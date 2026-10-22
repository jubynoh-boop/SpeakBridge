import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from backend import server
from desktop.windows_hotkeys import normalize_shortcut, parse_shortcut


class HotkeySettingsTests(unittest.TestCase):
    def test_read_voice_map_is_saved_without_changing_hotkeys(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(server, "HOTKEY_CONFIG_PATH", Path(folder) / "hotkey.json"):
            server.save_hotkey_settings(server.HotkeySettings(hotkey="f10", screen_read_hotkey="f9"))
            result = server.patch_hotkey_settings({"screen_read_voices":{"en":"af_heart", "ja":"M1"}})
            self.assertEqual(result["hotkey"], "f10")
            self.assertEqual(result["screen_read_hotkey"], "f9")
            self.assertEqual(result["screen_read_voices"]["en"], "af_heart")
            self.assertEqual(server.load_hotkey_settings().screen_read_voices["ja"], "M1")
            previous = server.HOTKEY_CONFIG_PATH.read_bytes()
            with self.assertRaises(HTTPException):
                server.patch_hotkey_settings({"screen_read_voices":{"ja":"af_heart"}})
            self.assertEqual(previous, server.HOTKEY_CONFIG_PATH.read_bytes())

    def test_shifted_symbol_and_physical_key_are_equivalent(self):
        self.assertEqual(parse_shortcut("ctrl+shift+!"), parse_shortcut("ctrl+shift+1"))
        self.assertEqual(normalize_shortcut("control+!"), "ctrl+shift+1")
        self.assertEqual(normalize_shortcut("alt+shift+equal"), "alt+shift+equal")

    def test_partial_save_preserves_other_features(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(server, "HOTKEY_CONFIG_PATH", Path(folder) / "hotkey.json"):
            server.save_hotkey_settings(server.HotkeySettings(target_language="ja", screen_read_mode="translation"))
            result = server.patch_hotkey_settings({"screen_read_hotkey": "ctrl+shift+!", "screen_read_mode": "source"})
            self.assertEqual(result["target_language"], "ja")
            self.assertEqual(result["screen_read_hotkey"], "ctrl+shift+1")
            self.assertEqual(result["screen_read_mode"], "source")
            result = server.patch_hotkey_settings({"text_target_language": "ko"})
            self.assertEqual(result["screen_read_mode"], "source")
            self.assertEqual(json.loads(server.HOTKEY_CONFIG_PATH.read_text())["text_target_language"], "ko")

    def test_alias_conflict_is_rejected_without_writing(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(server, "HOTKEY_CONFIG_PATH", Path(folder) / "hotkey.json"):
            server.save_hotkey_settings(server.HotkeySettings(hotkey="ctrl+shift+1"))
            previous = server.HOTKEY_CONFIG_PATH.read_bytes()
            with self.assertRaises(HTTPException):
                server.patch_hotkey_settings({"screen_read_hotkey": "control+!"})
            self.assertEqual(server.HOTKEY_CONFIG_PATH.read_bytes(), previous)

    def test_invalid_patch_is_not_written(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(server, "HOTKEY_CONFIG_PATH", Path(folder) / "hotkey.json"):
            with self.assertRaises(HTTPException):
                server.patch_hotkey_settings({"screen_read_mode": "wrong"})
            with self.assertRaises(HTTPException):
                server.patch_hotkey_settings({"unrecognized_field": True})
            self.assertFalse(server.HOTKEY_CONFIG_PATH.exists())
