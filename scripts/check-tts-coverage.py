"""ASR round-trip diagnostic of synthetic fixtures, not a pronunciation guarantee.

Run benchmark-vietnamese-tts.py first. Reuses the running app's ASR instead of
loading another GPU model. Does not send data to any external service.
"""
import base64
import json
import re
import sys
import urllib.request
from pathlib import Path
import numpy as np
import soundfile as sf

root = Path(__file__).resolve().parents[1]
folder = root / ".run" / "vietnamese-tts-check"
expected_samples = json.loads((folder / "samples.json").read_text(encoding="utf-8"))
report = []
voices = sys.argv[1:] or ["M1"]
for voice in voices:
    for profile in ("before", "after"):
        filename = f"{voice}-long-{profile}.wav"
        wav, rate = sf.read(folder / filename, dtype="float32")
        positions = np.linspace(0, len(wav) - 1, round(len(wav) * 16000 / rate))
        pcm = np.clip(np.interp(positions, np.arange(len(wav)), wav) * 32767, -32768, 32767).astype("<i2")
        payload = {"pcm16_base64":base64.b64encode(pcm.tobytes()).decode("ascii"), "sample_rate":16000,
                   "source_language":"vi", "target_language":"vi", "translate":False, "mode":"fast"}
        request = urllib.request.Request("http://127.0.0.1:8765/dictate", data=json.dumps(payload).encode(), headers={"Content-Type":"application/json"})
        with urllib.request.urlopen(request, timeout=120) as response:
            transcript = json.load(response)["transcript"]
        def words(text):
            return re.findall(r"\w+", text.casefold())
        expected = words(expected_samples["long"])
        actual = words(transcript)
        previous = list(range(len(actual) + 1))
        for index, word in enumerate(expected, 1):
            current = [index]
            for other_index, other in enumerate(actual, 1):
                current.append(min(current[-1] + 1, previous[other_index] + 1, previous[other_index - 1] + (word != other)))
            previous = current
        item = {"voice":voice, "profile":profile, "expected_words":len(expected), "recognized_words":len(actual),
                "word_error_rate":round(previous[-1]/max(1,len(expected)),3), "transcript":transcript}
        report.append(item)
        print(json.dumps({key:value for key,value in item.items() if key != "transcript"}), flush=True)
(folder / "coverage.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
