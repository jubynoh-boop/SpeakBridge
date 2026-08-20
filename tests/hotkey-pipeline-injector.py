from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop.hotkey_helper import VoiceTypingHelper
from kokoro import KPipeline


window = int(sys.argv[1])
control = int(sys.argv[2])
pipeline = KPipeline(lang_code="z", device="cpu")
chunks = []
for _, _, chunk in pipeline("今天我们讨论实时翻译。", voice="zm_yunxi", speed=1.0):
    if torch.is_tensor(chunk):
        chunk = chunk.detach().cpu().numpy()
    chunks.append(np.asarray(chunk, dtype=np.float32))
audio = np.concatenate(chunks)
pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()

helper = VoiceTypingHelper()
helper.sample_rate = 24_000
helper.target_window = window
helper.target_control = control
helper.settings.update({
    "source_language": "zh",
    "target_language": "vi",
    "translate": True,
    "mode": "fast",
})
helper._process_recording(pcm)
