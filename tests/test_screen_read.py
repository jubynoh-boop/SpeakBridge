from __future__ import annotations

import asyncio
import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi import HTTPException

from backend import server


class ScreenReadTests(unittest.TestCase):
    def test_selected_text_respects_all_configured_voices(self) -> None:
        for language, options in server.VOICES.items():
            for voice in options:
                with self.subTest(language=language, voice=voice), \
                     patch.object(server.models, "synthesize_speech", return_value=(np.ones(240, dtype=np.float32) * .05, 24_000)) as speak, \
                     patch.object(server.models, "_wait_for_llm") as llm:
                    result = asyncio.run(server.read_selected_text(server.SelectedTextReadRequest(
                        text=server.SAMPLES[language], source_language=language, voices={language:voice})))
                    speak.assert_called_once_with(server.SAMPLES[language], language, voice)
                    self.assertEqual(result["voice"], voice)
                    llm.assert_not_called()

    def test_selected_text_translation_uses_target_voice(self) -> None:
        with patch.object(server.models, "_wait_for_llm"), \
             patch.object(server.models, "_translate_screen_lines", return_value=["こんにちは"]), \
             patch.object(server.models, "synthesize_speech", return_value=(np.ones(240, dtype=np.float32) * .05, 24_000)) as speak:
            result = asyncio.run(server.read_selected_text(server.SelectedTextReadRequest(
                text="Hello", source_language="en", target_language="ja", read_mode="translation", voices={"en":"af_heart", "ja":"M1"})))
            speak.assert_called_once_with("こんにちは", "ja", "M1")
            self.assertEqual(result["voice"], "M1")

    def setUp(self) -> None:
        self.request = server.ScreenReadRequest(
            image_base64=base64.b64encode(b"image" * 30).decode("ascii"),
            source_language="zh",
            target_language="vi",
            processor="cpu",
            read_mode="translation",
        )
        self.ocr_result = {"processor": "cpu", "regions": [{"source": "你好"}], "text": "你好"}

    def test_translate_and_read_uses_target_language(self) -> None:
        with patch.object(server.screen_ocr, "recognize", return_value=self.ocr_result), \
             patch.object(server.models, "_wait_for_llm"), \
             patch.object(server.models, "_translate_screen_lines", return_value=["Xin chào"]) as translate, \
             patch.object(server.models, "synthesize_speech", return_value=(np.zeros(240, dtype=np.float32), 24_000)) as speak:
            result = asyncio.run(server.read_screen_text(self.request))
        self.assertEqual(result["spoken_language"], "vi")
        self.assertEqual(result["text"], "Xin chào")
        self.assertTrue(base64.b64decode(result["audio_base64"]).startswith(b"RIFF"))
        translate.assert_called_once_with(["你好"], "zh", "vi")
        speak.assert_called_once_with("Xin chào", "vi", "F1")

    def test_original_mode_skips_translation(self) -> None:
        request = self.request.model_copy(update={"read_mode": "source"})
        with patch.object(server.screen_ocr, "recognize", return_value=self.ocr_result), \
             patch.object(server.models, "_wait_for_llm") as wait_llm, \
             patch.object(server.models, "synthesize_speech", return_value=(np.zeros(240, dtype=np.float32), 24_000)) as speak:
            result = asyncio.run(server.read_screen_text(request))
        self.assertEqual(result["spoken_language"], "zh")
        self.assertEqual(result["text"], "你好")
        wait_llm.assert_not_called()
        speak.assert_called_once_with("你好", "zh", "zm_yunxi")

    def test_blank_ocr_does_not_speak(self) -> None:
        with patch.object(server.screen_ocr, "recognize", return_value={"processor": "cpu", "regions": [], "text": ""}), \
             patch.object(server.models, "synthesize_speech") as speak:
            with self.assertRaises(HTTPException) as error:
                asyncio.run(server.read_screen_text(self.request))
        self.assertEqual(error.exception.status_code, 422)
        speak.assert_not_called()

    def test_screen_read_hotkey_cannot_collide(self) -> None:
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(server, "HOTKEY_CONFIG_PATH", Path(folder) / "hotkey.json"):
            settings = server.HotkeySettings(screen_read_hotkey="ctrl+alt+t")
            with self.assertRaises(HTTPException) as error:
                server.save_hotkey_settings(settings)
            self.assertEqual(error.exception.status_code, 400)
            settings.screen_read_hotkey = "ctrl+alt+r"
            result = server.save_hotkey_settings(settings)
            self.assertEqual(result["screen_read_mode"], "source")

    def test_selected_text_language_detection(self) -> None:
        self.assertEqual(server.detect_selected_text_language("Hello world"), "en")
        self.assertEqual(server.detect_selected_text_language("Xin chào"), "vi")
        self.assertEqual(server.detect_selected_text_language("你好"), "zh")
        self.assertEqual(server.detect_selected_text_language("こんにちは"), "ja")
        self.assertEqual(server.detect_selected_text_language("안녕하세요"), "ko")

    def test_highlighted_text_is_spoken_without_ocr(self) -> None:
        request = server.SelectedTextReadRequest(text="Hello world", source_language="auto", read_mode="source")
        with patch.object(server.screen_ocr, "recognize") as ocr, \
             patch.object(server.models, "_wait_for_llm") as wait_llm, \
             patch.object(server.models, "synthesize_speech", return_value=(np.zeros(240, dtype=np.float32), 24_000)) as speak:
            result = asyncio.run(server.read_selected_text(request))
        self.assertEqual(result["source"], "Hello world")
        self.assertEqual(result["source_language"], "en")
        self.assertTrue(base64.b64decode(result["audio_base64"]).startswith(b"RIFF"))
        ocr.assert_not_called()
        wait_llm.assert_not_called()
        speak.assert_called_once_with("Hello world", "en", "am_adam")

    def test_highlighted_text_can_translate_before_speaking(self) -> None:
        request = server.SelectedTextReadRequest(text="Hello", source_language="en", target_language="vi", read_mode="translation")
        with patch.object(server.models, "_wait_for_llm"), \
             patch.object(server.models, "_translate_screen_lines", return_value=["Xin chào"]) as translate, \
             patch.object(server.models, "synthesize_speech", return_value=(np.zeros(240, dtype=np.float32), 24_000)) as speak:
            result = asyncio.run(server.read_selected_text(request))
        self.assertEqual(result["spoken_language"], "vi")
        translate.assert_called_once_with(["Hello"], "en", "vi")
        speak.assert_called_once_with("Xin chào", "vi", "F1")


if __name__ == "__main__":
    unittest.main()
