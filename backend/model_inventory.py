"""Local inventory: required files, shared cache locations, no downloads."""
from __future__ import annotations

import os
from pathlib import Path


def inventory() -> tuple[Path, list[dict]]:
    root = Path.cwd()
    cache = Path(os.environ.get("HF_HOME", str(root / "models" / "huggingface")))
    hub = Path(os.environ.get("HF_HUB_CACHE", str(cache / "hub")))
    hy = Path(os.environ.get("SPEAKBRIDGE_HY_MODEL", str(root / "models" / "HY-MT2-7B-Q6_K.gguf")))
    whisper = ("model.bin", "config.json", "tokenizer.json")
    definitions = [
        ("Whisper large-v3-turbo", "ASR FAST", "GPU", hub / "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo", whisper, True),
        ("Whisper large-v3", "ASR QUALITY", "GPU", hub / "models--Systran--faster-whisper-large-v3", whisper, True),
        ("Hy-MT2 7B Q6", "Translation", "GPU (configured llama.cpp device)", hy, (), False),
        ("Kokoro-82M", "English/Chinese TTS", "GPU", hub / "models--hexgrad--Kokoro-82M", ("config.json", "kokoro-v1_0.pth", "voices/am_adam.pt", "voices/zm_yunxi.pt"), True),
        ("RapidOCR PP-OCRv6", "Screen text OCR", "CPU / GPU", root / ".model-cache" / "rapidocr", ("PP-OCRv6_det_small.onnx", "PP-OCRv6_rec_small.onnx", "ch_ppocr_mobile_v2.0_cls_mobile.onnx", "PP-OCRv6_det_small.pth", "PP-OCRv6_rec_small.pth", "ch_ptocr_mobile_v2.0_cls_mobile.pth"), False),
        ("PP-OCRv5 Korean", "Korean screen OCR (shares RapidOCR folder)", "CPU", root / ".model-cache" / "rapidocr", ("korean_PP-OCRv5_rec_mobile.onnx", "ch_PP-OCRv5_det_mobile.onnx", "ch_ppocr_mobile_v2.0_cls_mobile.onnx"), False),
        ("Supertonic 3", "Vietnamese/Japanese/Korean TTS", "CPU", root / ".model-cache" / "supertonic3", ("config.json", "onnx/tts.json", "onnx/unicode_indexer.json", "onnx/duration_predictor.onnx", "onnx/text_encoder.onnx", "onnx/vector_estimator.onnx", "onnx/vocoder.onnx", "voice_styles/F1.json"), False),
    ]

    def usable(file: Path) -> bool:
        try:
            return file.is_file() and file.stat().st_size > 0
        except OSError:
            return False

    assets = []
    for name, role, processor, path, required, hf in definitions:
        candidates = sorted((path / "snapshots").glob("*")) if hf else [path]
        candidate = min(candidates, key=lambda item: sum(not usable(item / file) for file in required), default=path)
        missing = [file for file in required if not usable(candidate / file)]
        installed = not missing if required else usable(path)
        if not required and not installed:
            missing = [path.name]
        # Resolve HF symlinks so blobs and snapshot references are not counted twice.
        resolved = set()
        size = 0
        files = path.rglob("*") if path.is_dir() else [path]
        for file in files:
            if usable(file):
                target = file.resolve()
                if target not in resolved:
                    resolved.add(target)
                    size += target.stat().st_size
        assets.append({"name": name, "role": role, "processor": processor, "installed": installed,
                       "size_gb": round(size / 1024**3, 2), "path": str(candidate), "missing_files": missing})
    from backend.vietnamese_tts import MODEL_RELATIVE, model_manifest, voice_pack
    model = root / MODEL_RELATIVE
    if model.exists():
        try:
            model_manifest()
            voice_pack("M1")
            installed, missing = True, []
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            installed, missing = False, [str(exc)]
        resolved = {file.resolve() for file in model.rglob("*") if usable(file)}
        assets.append({"name":"VieNeu v3 Turbo", "role":"Vietnamese TTS (optional)", "processor":"CPU",
                       "installed":installed,"size_gb":round(sum(file.stat().st_size for file in resolved)/1024**3,2),
                       "path":str(model),"missing_files":missing})
    return cache, assets
