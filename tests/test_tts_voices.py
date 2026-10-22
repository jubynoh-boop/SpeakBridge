import asyncio
import base64
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
from fastapi import HTTPException
from backend import server
from backend.tts_voices import VOICES, resolve_voice


class VoiceTests(unittest.TestCase):
    def test_all_twelve_ui_choices_are_language_specific(self):
        self.assertEqual(sum(map(len, VOICES.values())), 12)
        self.assertEqual(resolve_voice("zh", "af_heart"), "zm_yunxi")
        self.assertEqual(resolve_voice("vi", "am_adam"), "M1")
        self.assertEqual(resolve_voice("en", "af_heart"), "af_heart")

    def test_british_voices_share_model_but_use_british_phonemes(self):
        models = server.LocalModels()
        shared_model = object()
        models.tts["en"] = types.SimpleNamespace(model=shared_model)
        pipeline = MagicMock()
        fake_kokoro = types.SimpleNamespace(KPipeline=pipeline)
        with patch.dict(sys.modules, {"kokoro": fake_kokoro}):
            first = models._tts_pipeline("en", "bm_george")
            second = models._tts_pipeline("en", "bm_lewis")
        self.assertIs(first, second)
        pipeline.assert_called_once_with(lang_code="b", model=shared_model)

    def test_voice_test_returns_real_wav_without_asr_or_translation(self):
        with patch.object(server.models, "synthesize_speech", return_value=(np.ones(240, dtype=np.float32) * 0.1, 24000)) as speak, patch.object(server.models, "_wait_for_llm") as llm:
            result = asyncio.run(server.test_voice(server.VoiceTestRequest(language="en", voice="af_heart")))
        self.assertTrue(base64.b64decode(result["audio_base64"]).startswith(b"RIFF"))
        self.assertEqual(result["voice"], "af_heart")
        speak.assert_called_once_with(server.SAMPLES["en"], "en", "af_heart")
        llm.assert_not_called()

    def test_invalid_or_silent_voice_is_reported(self):
        with self.assertRaises(HTTPException):
            asyncio.run(server.test_voice(server.VoiceTestRequest(language="ko", voice="af_heart")))
        with patch.object(server.models, "synthesize_speech", return_value=(np.zeros(240), 24000)):
            with self.assertRaises(HTTPException) as error:
                asyncio.run(server.test_voice(server.VoiceTestRequest()))
        self.assertIn("silent", error.exception.detail)
