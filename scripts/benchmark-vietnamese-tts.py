"""Offline comparison of old/new Vietnamese synthesis; artifacts stay on app drive."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
configuration = json.loads((ROOT / "config" / "models.local.json").read_text(encoding="utf-8")) if (ROOT / "config" / "models.local.json").exists() else {}
for key, env in (("hf_home", "HF_HOME"), ("torch_home", "TORCH_HOME"), ("runtime_temp", "TEMP")):
    location = Path(configuration.get(key, str(ROOT / ".model-cache" / key)))
    if not location.is_absolute():
        location = ROOT / location
    location.mkdir(parents=True, exist_ok=True)
    os.environ[env] = str(location)
os.environ["HF_HUB_OFFLINE"] = "1"

import numpy as np
import soundfile as sf
from supertonic import TTS
from backend.text_segments import split_text

output = ROOT / ".run" / "vietnamese-tts-check"
output.mkdir(parents=True, exist_ok=True)
model = TTS(model_dir=ROOT / ".model-cache" / "supertonic3", auto_download=False, intra_op_num_threads=4)
samples = {
    "short": "Tôi muốn thanh toán hóa đơn này. Vui lòng giữ nguyên số tiền 2.500 đô la và ngày giao hàng thứ Sáu.",
    "long": "Tôi đang có một câu hỏi về phương thức thanh toán bằng chuyển khoản và muốn biết liệu dịch vụ của bạn có hỗ trợ hoàn tiền khi giao hàng chậm hay không vì khách hàng cần giữ nguyên tên sản phẩm số tiền và ngày tháng trong bản dịch đồng thời vui lòng hướng dẫn đầy đủ các bước để tôi có thể kiểm tra hóa đơn cũng như xác nhận rằng toàn bộ nội dung ở cuối đoạn này vẫn được đọc rõ ràng mà không bị bỏ mất câu cuối cùng",
}
(output / "samples.json").write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")
report = []
for voice in ("M1", "F1"):
    style = model.get_voice_style(voice)
    for name, text in samples.items():
        for profile in ("before", "after"):
            started = time.perf_counter()
            pieces = [text] if profile == "before" else split_text(text, 450)
            audio_parts = []
            for index, piece in enumerate(pieces):
                wav, duration = model.synthesize(piece, voice_style=style, lang="vi", total_steps=5 if profile == "before" else 8,
                                                 speed=1.08,
                                                 max_chunk_length=300 if profile == "before" else 450,
                                                 silence_duration=.3 if profile == "before" else .12, verbose=False)
                if index:
                    audio_parts.append(np.zeros(round(model.sample_rate * .12), dtype=np.float32))
                audio_parts.append(np.asarray(wav, dtype=np.float32).reshape(-1))
            audio = np.concatenate(audio_parts)
            elapsed = time.perf_counter() - started
            if not np.isfinite(audio).all() or np.sqrt(np.mean(audio ** 2)) < .0001:
                raise RuntimeError(f"Invalid/silent audio: {voice} {name} {profile}")
            filename = f"{voice}-{name}-{profile}.wav"
            sf.write(output / filename, audio, model.sample_rate, subtype="PCM_16")
            report.append({"voice":voice, "sample":name, "profile":profile, "chars":len(text), "chunks":len(pieces),
                           "generation_seconds":round(elapsed,3), "audio_seconds":round(len(audio)/model.sample_rate,3), "file":filename})
            print(json.dumps(report[-1]), flush=True)
(output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Saved {len(report)} samples to {output}")
