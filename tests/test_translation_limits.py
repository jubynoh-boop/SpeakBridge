import io
import json
import unittest
from unittest.mock import patch
from backend import server


class TranslationLimitTests(unittest.TestCase):
    def test_incomplete_generation_is_not_returned_as_translation(self):
        response = io.BytesIO(json.dumps({"choices": [{"finish_reason": "length", "message": {"content": "Only the beginning"}}]}).encode())
        with patch.object(server.urllib.request, "urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "token budget"):
                server.LocalModels._chat([{"role": "user", "content": "Translate"}], 32)

    def test_long_selection_translates_every_piece_in_order(self):
        model = server.LocalModels()
        source = "This is the complete passage without any missing content " * 22
        captured = []
        def chat(messages, max_tokens):
            items = json.loads(messages[0]["content"].split("Input: ", 1)[1])
            captured.extend(items)
            self.assertLessEqual(max(map(len, items)), 300)
            return json.dumps(items)
        with patch.object(model, "_chat", side_effect=chat):
            result = model._translate_screen_lines([source], "en", "vi")
        self.assertEqual(" ".join(captured).split(), source.split())
        self.assertEqual(result[0].split(), source.split())

    def test_long_speech_uses_eight_steps_and_preserves_words(self):
        import numpy as np
        from types import SimpleNamespace
        model = server.LocalModels()
        captured = []
        def synthesize(text, **options):
            captured.append(text)
            self.assertEqual(options["total_steps"], 8)
            self.assertLessEqual(len(text), 450)
            self.assertEqual(options["speed"], 1.08)
            return np.ones((1, 240), dtype=np.float32) * .1, np.array([.01])
        model.multilingual_tts = SimpleNamespace(sample_rate=24000, get_voice_style=lambda voice: voice, synthesize=synthesize)
        text = ("Tôi muốn thanh toán hóa đơn này bằng chuyển khoản " * 12).strip()
        with patch.object(server, "local_voice_pack", return_value="local"), patch("backend.vietnamese_tts.enabled", return_value=False):
            waveform, rate = model._synthesize_speech(text, "vi", "M1")
        self.assertEqual(" ".join(captured).split(), text.split())
        self.assertEqual(len(waveform), 240 * len(captured) + round(.12 * rate) * (len(captured) - 1))
