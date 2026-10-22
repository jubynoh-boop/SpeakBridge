"""Prepare optional CPU Vietnamese speech; never silently activate it."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "models" / "vieneu-v3-turbo"
os.environ.update(HF_HOME=str(MODEL / "huggingface"), HF_HUB_CACHE=str(MODEL / "huggingface" / "hub"),
                  HF_HUB_DISABLE_SYMLINKS="1", HF_HUB_DISABLE_TELEMETRY="1",
                  XDG_CACHE_HOME=str(ROOT / ".model-cache" / "vieneu"),
                  NUMBA_CACHE_DIR=str(ROOT / ".model-cache" / "vieneu" / "numba"))
sys.path.insert(0, str(ROOT))


def main():
    import importlib.metadata
    import numpy as np
    from huggingface_hub import hf_hub_download
    from vieneu import Vieneu
    from backend.vietnamese_tts import GRAPH_FILES, CODEC_FILES

    version = importlib.metadata.version("vieneu")
    if version != "3.8.3":
        raise RuntimeError("Install the tested VieNeu SDK 3.8.3 in its isolated runtime first")
    backbone = Path(hf_hub_download("pnnbao-ump/VieNeu-TTS-v3-Turbo", "onnx_update/config.json")).parent
    codec = Path(hf_hub_download("OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX", CODEC_FILES[-1])).parent
    tts = Vieneu(mode="v3turbo", device="cpu", backend="onnx", precision="fp32", threads=4)
    voices = {"M1":{"name":"Hải Đăng","label":"Hải Đăng · Nam · VieNeu"},
              "F1":{"name":"Trúc Ly","label":"Trúc Ly · Nữ · VieNeu"}}
    try:
        for profile in voices.values():
            if tts.resolve_voice_name(profile["name"]) != profile["name"]:
                raise RuntimeError(f"Missing voice: {profile['name']}")
            audio = tts.infer("Xin chào. Chúng ta có thể trao đổi về thanh toán ngày mai.",
                              voice=profile["name"], apply_watermark=False)
            if not len(audio) or not np.isfinite(audio).all() or np.max(np.abs(audio)) < .0001:
                raise RuntimeError(f"Invalid audio: {profile['name']}")
        for folder, files in ((backbone, GRAPH_FILES), (codec, CODEC_FILES)):
            for name in files:
                if not (folder / name).is_file() or (folder / name).stat().st_size == 0:
                    raise RuntimeError(f"Missing asset: {folder/name}")
        manifest = {"sdk_version":version,"backend":"onnx","precision":"fp32","processor":"CPU",
                    "backbone":str(backbone.relative_to(MODEL)),"codec":str(codec.relative_to(MODEL)),
                    "voices":voices}
        temporary = MODEL / "installed.json.tmp"
        temporary.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
        temporary.replace(MODEL / "installed.json")
        print("VieNeu assets verified:", MODEL, flush=True)
        print("Not activated. Opt in with config/speech.local.json: vietnamese_engine=vieneu",flush=True)
    finally:
        tts.close()


if __name__ == "__main__":
    main()
