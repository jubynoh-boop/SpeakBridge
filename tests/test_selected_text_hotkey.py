from __future__ import annotations

import unittest
import json
import queue
from unittest.mock import patch

from desktop.hotkey_helper import VoiceTypingHelper, DEFAULTS


class SelectedTextHotkeyTests(unittest.TestCase):
    def test_helper_sends_the_saved_voice_map_to_reader(self) -> None:
        helper = VoiceTypingHelper.__new__(VoiceTypingHelper)
        helper.settings = {**DEFAULTS, "screen_read_voices":{"en":"af_heart"}}
        helper.screen_job_id = 1
        helper.ui_queue = queue.Queue()
        with patch.object(helper, "_set_status"), \
             patch.object(helper, "_capture_selected_text", return_value="Hello"), \
             patch.object(helper, "_api_ready", return_value=True), \
             patch("desktop.hotkey_helper.urllib.request.urlopen") as api:
            api.return_value.__enter__.return_value.read.return_value = b'{"ok":true}'
            helper._read_selected_text(None, None, 1)
            request = api.call_args.args[0]
            self.assertEqual(json.loads(request.data)["voices"]["en"], "af_heart")
            self.assertEqual(helper.ui_queue.get()[0], "screen_read_result")

    def test_copies_only_highlighted_text_and_restores_clipboard(self) -> None:
        helper = VoiceTypingHelper.__new__(VoiceTypingHelper)
        clipboard = {"text": "previous clipboard"}
        keys: list[str] = []

        def copy(value: str) -> None:
            clipboard["text"] = value

        def press(key: str) -> None:
            keys.append(key)
            if key == "ctrl+c":
                clipboard["text"] = "selected words"

        with patch.object(helper, "_wait_for_modifiers_released"), \
             patch.object(helper, "_focus_target"), \
             patch("desktop.hotkey_helper.modifiers_pressed", return_value=False), \
             patch("desktop.hotkey_helper.keyboard.press_and_release", side_effect=press), \
             patch("desktop.hotkey_helper.pyperclip.paste", side_effect=lambda: clipboard["text"]), \
             patch("desktop.hotkey_helper.pyperclip.copy", side_effect=copy), \
             patch("desktop.hotkey_helper.time.sleep"):
            result = helper._capture_selected_text(100, 200)

        self.assertEqual(result, "selected words")
        self.assertEqual(clipboard["text"], "previous clipboard")
        self.assertEqual(keys, ["ctrl+c"])

    def test_no_selection_never_selects_entire_page(self) -> None:
        helper = VoiceTypingHelper.__new__(VoiceTypingHelper)
        clipboard = {"text": "previous clipboard"}
        keys: list[str] = []

        def copy(value: str) -> None:
            clipboard["text"] = value

        with patch.object(helper, "_wait_for_modifiers_released"), \
             patch.object(helper, "_focus_target"), \
             patch("desktop.hotkey_helper.modifiers_pressed", return_value=False), \
             patch("desktop.hotkey_helper.keyboard.press_and_release", side_effect=keys.append), \
             patch("desktop.hotkey_helper.pyperclip.paste", side_effect=lambda: clipboard["text"]), \
             patch("desktop.hotkey_helper.pyperclip.copy", side_effect=copy), \
             patch("desktop.hotkey_helper.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "bôi đen"):
                helper._capture_selected_text(100, 200)

        self.assertEqual(clipboard["text"], "previous clipboard")
        self.assertEqual(keys, ["ctrl+c"])


if __name__ == "__main__":
    unittest.main()
