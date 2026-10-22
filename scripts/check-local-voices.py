"""Offline synthesis smoke test; WAVs/report stay under the repo's .run folder."""
import json
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.server import LocalModels
from backend.tts_voices import SAMPLES, VOICES

folder = Path.cwd() / ".run" / "voice-check"
folder.mkdir(parents=True, exist_ok=True)
models = LocalModels()
results = []
for language, options in VOICES.items():
    for voice in options:
        started = time.perf_counter()
        item = {"language": language, "voice": voice}
        try:
            waveform, rate = models.synthesize_speech(SAMPLES[language], language, voice)
            rms = float(np.sqrt(np.mean(waveform ** 2))) if len(waveform) else 0.0
            if not len(waveform) or not np.isfinite(waveform).all() or rms < 0.0001:
                raise RuntimeError(f"Invalid or silent audio: samples={len(waveform)} rms={rms}")
            sf.write(folder / f"{language}-{voice}.wav", waveform, rate, subtype="PCM_16")
            item.update(ok=True, duration_seconds=round(len(waveform) / rate, 2), rms=round(rms, 5))
        except Exception as exc:
            item.update(ok=False, error=str(exc))
        item["latency_seconds"] = round(time.perf_counter() - started, 2)
        results.append(item)
        print(json.dumps(item, ensure_ascii=True), flush=True)
(folder / "report.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
sys.exit(0 if all(item["ok"] for item in results) else 1)
