from __future__ import annotations

import re
import threading
import time
from io import BytesIO
from pathlib import Path
from typing import Any

import torch


class ScreenOCR:
    """Lazy local OCR with an ONNX CPU path and a PyTorch CUDA path."""

    def __init__(self, model_root: Path) -> None:
        self.model_root = model_root
        self.model_root.mkdir(parents=True, exist_ok=True)
        self._engines: dict[str, Any] = {}
        self._engine_lock = threading.Lock()
        self._run_lock = threading.Lock()

    @staticmethod
    def normalize_processor(processor: str) -> tuple[str, str | None]:
        requested = "gpu" if processor.casefold() == "gpu" else "cpu"
        if requested == "gpu" and not torch.cuda.is_available():
            return "cpu", "CUDA không khả dụng; OCR đã chuyển sang CPU"
        return requested, None

    def _create_engine(self, processor: str, source_language: str = "zh") -> Any:
        try:
            from rapidocr import EngineType, LangRec, ModelType, OCRVersion, RapidOCR
        except ImportError as exc:
            raise RuntimeError(
                "Thiếu RapidOCR. Hãy chạy lại cài đặt SpeakBridge để thêm model OCR."
            ) from exc

        engine_type = EngineType.TORCH if processor == "gpu" else EngineType.ONNXRUNTIME
        korean = source_language == "ko"
        params = {
            "Global.model_root_dir": self.model_root,
            "Global.log_level": "warning",
            "Global.max_side_len": 1600,
            "Global.text_score": 0.55,
            "Det.engine_type": engine_type,
            "Det.model_type": ModelType.MOBILE if korean else ModelType.SMALL,
            "Det.ocr_version": OCRVersion.PPOCRV5 if korean else OCRVersion.PPOCRV6,
            "Rec.engine_type": engine_type,
            "Rec.model_type": ModelType.MOBILE if korean else ModelType.SMALL,
            "Rec.ocr_version": OCRVersion.PPOCRV5 if korean else OCRVersion.PPOCRV6,
            "Rec.lang_type": LangRec.KOREAN if korean else LangRec.CH,
            "Cls.engine_type": engine_type,
            "Cls.model_type": ModelType.MOBILE,
            "Cls.ocr_version": OCRVersion.PPOCRV4,
            "EngineConfig.onnxruntime.use_cuda": False,
            "EngineConfig.onnxruntime.intra_op_num_threads": 4,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            "EngineConfig.torch.use_cuda": processor == "gpu",
        }
        return RapidOCR(params=params)

    def prepare(self, requested_processor: str, source_language: str = "zh") -> dict[str, Any]:
        processor, warning = self.normalize_processor(requested_processor)
        if source_language == "ko" and processor == "gpu":
            processor = "cpu"
            warning = "OCR tiếng Hàn dùng PP-OCRv5 ONNX trên CPU; không chiếm VRAM"
        engine_key = f"{processor}:ko" if source_language == "ko" else processor
        started = time.perf_counter()
        with self._engine_lock:
            if engine_key not in self._engines:
                try:
                    self._engines[engine_key] = self._create_engine(processor, source_language)
                except Exception:
                    if processor != "gpu":
                        raise
                    # A CUDA runtime can be present but unusable because of an
                    # incompatible driver or insufficient VRAM. CPU must remain usable.
                    processor = "cpu"
                    warning = "Không khởi tạo được OCR GPU; đã chuyển sang CPU"
                    if processor not in self._engines:
                        self._engines[processor] = self._create_engine(processor, source_language)
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
        return {
            "processor": processor,
            "requested_processor": "gpu" if requested_processor.casefold() == "gpu" else "cpu",
            "warning": warning,
            "load_ms": round((time.perf_counter() - started) * 1000),
        }

    @staticmethod
    def _clean_text(lines: list[str]) -> str:
        cleaned: list[str] = []
        seen: set[str] = set()
        for line in lines:
            value = re.sub(r"\s+", " ", line).strip()
            key = value.casefold()
            if len(value) < 2 or key in seen:
                continue
            cleaned.append(value)
            seen.add(key)
        return "\n".join(cleaned)[:6000]

    @staticmethod
    def _regions(result: Any, image_width: int, image_height: int) -> list[dict[str, Any]]:
        """Return deduplicated OCR lines with normalized image coordinates."""
        regions: list[dict[str, Any]] = []
        seen: set[str] = set()
        boxes = list(result.boxes if result.boxes is not None else ())
        texts = list(result.txts if result.txts is not None else ())
        scores = list(result.scores if result.scores is not None else ())
        for index, (box, line) in enumerate(zip(boxes, texts)):
            value = re.sub(r"\s+", " ", str(line)).strip()
            key = value.casefold()
            if len(value) < 2 or key in seen:
                continue
            try:
                xs = [float(point[0]) for point in box]
                ys = [float(point[1]) for point in box]
            except (TypeError, ValueError, IndexError):
                continue
            left = max(0.0, min(xs) / image_width)
            top = max(0.0, min(ys) / image_height)
            right = min(1.0, max(xs) / image_width)
            bottom = min(1.0, max(ys) / image_height)
            if right <= left or bottom <= top:
                continue
            regions.append({
                "source": value,
                "confidence": round(float(scores[index]), 4) if index < len(scores) else 0.0,
                "x": round(left, 6),
                "y": round(top, 6),
                "width": round(right - left, 6),
                "height": round(bottom - top, 6),
            })
            seen.add(key)
        return regions

    def recognize(self, image_bytes: bytes, requested_processor: str, source_language: str = "zh") -> dict[str, Any]:
        from PIL import Image

        prepared = self.prepare(requested_processor, source_language)
        processor = str(prepared["processor"])
        engine_key = f"{processor}:ko" if source_language == "ko" else processor
        with Image.open(BytesIO(image_bytes)) as image:
            image_width, image_height = image.size
        started = time.perf_counter()
        with self._run_lock:
            result = self._engines[engine_key](image_bytes)
        regions = self._regions(result, image_width, image_height)
        text = "\n".join(region["source"] for region in regions)[:6000]
        if not regions:
            text = self._clean_text(list(result.txts if result.txts is not None else ()))
        scores = [float(score) for score in (result.scores if result.scores is not None else ())]
        confidence = round(sum(scores) / len(scores), 4) if scores else 0.0
        return {
            **prepared,
            "text": text,
            "regions": regions,
            "confidence": confidence,
            "line_count": len(result.txts if result.txts is not None else ()),
            "ocr_ms": round((time.perf_counter() - started) * 1000),
        }
