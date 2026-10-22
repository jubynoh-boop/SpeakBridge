"""Repeat the reported sentence through the running reader and local ASR.

Artifacts contain only fixed public fixtures. ASR is a diagnostic, not a
substitute for listening to the WAVs. Adjacent repetitions are compared with
the intended speech text so legitimate repeated words are not flagged.
"""
import base64
import io
import json
import re
import time
import urllib.request
from collections import Counter
from pathlib import Path

import numpy as np
import soundfile as sf

folder = Path(__file__).resolve().parents[1] / ".run" / "vietnamese-stutter-check"
folder.mkdir(parents=True, exist_ok=True)
sentence = "It will take two weeks, as we plan to stop at many places along the way."


def post(path, payload):
    request = urllib.request.Request("http://127.0.0.1:8765" + path, data=json.dumps(payload).encode(), headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def words(text):
    return re.findall(r"\w+", text.casefold())


report = []
for voice in ("M1", "F1"):
    for attempt in range(1, 4):
        started = time.perf_counter()
        result = post("/text/read", {"text":sentence,"source_language":"en","target_language":"vi","read_mode":"translation","voices":{"vi":voice}})
        raw = base64.b64decode(result.pop("audio_base64"))
        (folder / f"{voice}-{attempt}.wav").write_bytes(raw)
        wav, rate = sf.read(io.BytesIO(raw), dtype="float32")
        pcm = np.clip(wav * 32767, -32768, 32767).astype("<i2")
        heard = post("/dictate", {"pcm16_base64":base64.b64encode(pcm.tobytes()).decode(),"sample_rate":rate,"source_language":"vi","target_language":"vi","translate":False,"mode":"fast"})["transcript"]
        expected, actual = words(result["text"]), words(heard)
        reference_repeats = Counter(word for left, word in zip(expected, expected[1:]) if left == word)
        found_repeats = Counter(word for left, word in zip(actual, actual[1:]) if left == word)
        unwanted = list((found_repeats - reference_repeats).elements())
        item = {"voice":voice,"attempt":attempt,"intended":result["text"],"heard":heard,"unexpected_adjacent_repeats":unwanted,"timing":result["timing"],"elapsed_seconds":round(time.perf_counter()-started,3)}
        report.append(item)
        print(json.dumps(item,ensure_ascii=True),flush=True)
(folder / "report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print("Repeat flags:",sum(bool(item["unexpected_adjacent_repeats"]) for item in report),"/",len(report),flush=True)
