import base64
import json
import queue
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
from backend import server, vietnamese_tts as vi
from backend.tts_voices import local_voice_pack


class VietnameseTTSTests(unittest.TestCase):
    def test_default_remains_supertonic_and_invalid_opt_in_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(vi.Path, "cwd", return_value=Path(directory)):
            self.assertFalse(vi.enabled())
            folder = Path(directory) / "config"
            folder.mkdir()
            path = folder / "speech.local.json"
            path.write_text('{"vietnamese_engine":"vieneu"}', encoding="utf-8")
            self.assertTrue(vi.enabled())
            path.write_text('{"vietnamese_engine":"unknown"}', encoding="utf-8")
            with self.assertRaises(RuntimeError):
                vi.enabled()

    def test_missing_assets_do_not_appear_installed(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(vi.Path, "cwd", return_value=Path(directory)):
            model = Path(directory) / vi.MODEL_RELATIVE
            model.mkdir(parents=True)
            manifest = {"sdk_version":"3.8.3","voices":{"M1":{},"F1":{}},"backbone":"backbone","codec":"codec"}
            (model / "installed.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(RuntimeError, "missing"):
                vi.model_manifest()
            manifest["backbone"] = "../../outside"
            (model / "installed.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(RuntimeError, "inside"):
                vi.model_manifest()

    def test_only_vietnamese_uses_new_engine(self):
        model = server.LocalModels()
        model.vietnamese_tts = MagicMock()
        model.vietnamese_tts.synthesize.return_value = (np.ones(4800),48000)
        with patch.object(server,"local_voice_pack",return_value="local"), patch.object(vi,"enabled",return_value=True):
            audio, rate = model._synthesize_speech("Đọc nguyên văn.", "vi", "M1")
        model.vietnamese_tts.synthesize.assert_called_once_with("Đọc nguyên văn.", "M1")
        self.assertEqual(rate, 48000)
        self.assertEqual(len(audio),4800)
        self.assertIsNone(model.multilingual_tts)

    def test_catalog_resolves_real_voice_when_enabled(self):
        with patch.object(vi,"enabled",return_value=True), patch.object(vi,"voice_pack",return_value=Path("installed.json")) as pack:
            self.assertEqual(local_voice_pack("vi","M1"),Path("installed.json"))
            pack.assert_called_once_with("M1")

    def test_worker_audio_and_failures_are_validated(self):
        worker = vi.VietnameseTTS()
        process = MagicMock()
        process.poll.return_value = None
        worker.process = process
        encoded = base64.b64encode((np.ones(4,dtype="<f4")*.1).tobytes()).decode()
        worker.responses.put({"id":1,"rate":48000,"pcm_f32":encoded})
        with patch.object(vi,"voice_pack"):
            audio,rate = worker.synthesize("Xin chào","M1")
            self.assertEqual(rate,48000)
            self.assertEqual(audio.size,4)
            worker.responses.put({"id":2,"error":"invalid engine audio"})
            with self.assertRaisesRegex(RuntimeError,"invalid engine audio"):
                worker.synthesize("Xin chào","M1")
        self.assertIsNone(worker.process)

    def test_reader_exits_on_eof(self):
        import io
        responses = queue.Queue()
        vi.VietnameseTTS._read_output(io.StringIO('{"id":1}\n'),responses)
        self.assertEqual(responses.get()["id"],1)
        self.assertIn("exited", responses.get()["error"])
