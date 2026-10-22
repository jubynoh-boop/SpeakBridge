"""Evaluate an isolated, CPU-only Vietnamese TTS. Never activate on download.

Run with runtime/vieneu/.venv/Scripts/python.exe; all downloaded assets and
artifacts stay in the project. ASR roundtrip is diagnostic, not a listening test.
"""
import argparse
import base64
import json
import os
import re
import time
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "models" / "vieneu-v3-turbo"
os.environ["HF_HOME"] = str(MODEL / "huggingface")
os.environ["HF_HUB_CACHE"] = str(MODEL / "huggingface" / "hub")
os.environ["XDG_CACHE_HOME"] = str(ROOT / ".model-cache" / "vieneu")
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"


def post(path, payload):
    request = urllib.request.Request("http://127.0.0.1:8765" + path,
                                    data=json.dumps(payload).encode(),
                                    headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--voices", nargs="+", default=[])
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    import numpy as np
    import soundfile as sf
    from vieneu import Vieneu

    started = time.perf_counter()
    tts = Vieneu(mode="v3turbo", device="cpu", backend="onnx", precision="fp32", threads=4)
    print("Loaded in", round(time.perf_counter() - started, 3), "seconds", flush=True)
    print("Available presets:", tts.list_preset_voices(), flush=True)
    if args.list:
        return
    if not args.voices:
        parser.error("Choose actual installed presets with --voices (use --list first)")
    folder = ROOT / ".run" / "vieneu-check"
    folder.mkdir(parents=True, exist_ok=True)
    fixtures = [
        "Sẽ mất hai tuần, vì chúng tôi dự định dừng chân ở nhiều nơi dọc theo đường đi.",
        "Xin chào. Chúng ta có thể trao đổi về thanh toán ngày mai.",
        "Tôi muốn thanh toán hóa đơn này. Bạn có thể hướng dẫn tôi không?",
    ]
    report = []
    for voice in args.voices:
        for index, text in enumerate(fixtures):
            for attempt in range(1, (args.attempts if index == 0 else 1) + 1):
                started = time.perf_counter()
                wav = np.asarray(tts.infer(text=text, voice=voice, apply_watermark=False), dtype="float32")
                generation = time.perf_counter() - started
                rate = int(tts.sample_rate)
                if not wav.size or not np.isfinite(wav).all():
                    raise RuntimeError("TTS returned empty/non-finite audio")
                filename = f"{voice}-{index}-{attempt}.wav"
                sf.write(str(folder / filename), wav, rate)
                pcm = np.clip(wav * 32767, -32768, 32767).astype("<i2")
                heard = post("/dictate", {"pcm16_base64":base64.b64encode(pcm.tobytes()).decode(),
                             "sample_rate":rate,"source_language":"vi","target_language":"vi",
                             "translate":False,"mode":"fast"})["transcript"]
                expected = re.findall(r"\w+", text.casefold())
                actual = re.findall(r"\w+", heard.casefold())
                repeats = lambda words: Counter(b for a,b in zip(words, words[1:]) if a == b)
                item = {"voice":voice,"fixture":index,"attempt":attempt,"intended":text,"heard":heard,
                        "unexpected_adjacent_repeats":list((repeats(actual)-repeats(expected)).elements()),
                        "generation_seconds":round(generation,3),"audio_seconds":round(wav.size/rate,3),
                        "wav":filename}
                report.append(item)
                (folder / "report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
                print(json.dumps(item,ensure_ascii=True),flush=True)
    print("Repeat flags:",sum(bool(row["unexpected_adjacent_repeats"]) for row in report),"/",len(report),flush=True)


if __name__ == "__main__":
    main()
