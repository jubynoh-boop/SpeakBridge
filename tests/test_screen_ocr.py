from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from backend.screen_ocr import ScreenOCR


class _FakeEngine:
    def __call__(self, image_bytes: bytes) -> SimpleNamespace:
        assert image_bytes
        return SimpleNamespace(
            txts=("  你好，世界  ", "你好，世界", " English text ", "x"),
            scores=(0.98, 0.97, 0.91, 0.99),
            boxes=(
                ((10, 10), (110, 10), (110, 30), (10, 30)),
                ((10, 40), (110, 40), (110, 60), (10, 60)),
                ((20, 70), (180, 70), (180, 90), (20, 90)),
                ((10, 100), (20, 100), (20, 110), (10, 110)),
            ),
        )


class ScreenOCRTests(unittest.TestCase):
    def test_recognize_cleans_and_deduplicates_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = ScreenOCR(Path(directory))
            service._engines["cpu"] = _FakeEngine()
            image = Image.new("RGB", (200, 120), "white")
            encoded = BytesIO()
            image.save(encoded, format="JPEG")
            result = service.recognize(encoded.getvalue(), "cpu")

        self.assertEqual(result["processor"], "cpu")
        self.assertEqual(result["text"], "你好，世界\nEnglish text")
        self.assertEqual(result["line_count"], 4)
        self.assertGreater(result["confidence"], 0.9)
        self.assertEqual(len(result["regions"]), 2)
        self.assertEqual(result["regions"][0]["x"], 0.05)
        self.assertEqual(result["regions"][1]["width"], 0.8)

    def test_unknown_processor_defaults_to_cpu(self) -> None:
        processor, warning = ScreenOCR.normalize_processor("something-else")
        self.assertEqual(processor, "cpu")
        self.assertIsNone(warning)

    def test_korean_uses_separate_cpu_engine(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = ScreenOCR(Path(directory))
            with patch.object(service, "_create_engine", return_value=_FakeEngine()) as create:
                prepared = service.prepare("gpu", "ko")
            self.assertEqual(prepared["processor"], "cpu")
            self.assertIn("cpu:ko", service._engines)
            create.assert_called_once_with("cpu", "ko")


if __name__ == "__main__":
    unittest.main()
