"""Optional Vietnamese engine in an isolated, torch-free environment.

No downloads in the backend. An explicit local opt-in is required; other
languages retain their existing engines. IDs M1/F1 keep saved helper settings.
"""
from __future__ import annotations

import atexit
import base64
import json
import os
import queue
import subprocess
import threading
from pathlib import Path

import numpy as np

MODEL_RELATIVE = Path("models") / "vieneu-v3-turbo"
GRAPH_FILES = ("config.json", "tokenizer.json", "vieneu_prefill.onnx", "vieneu_decode_step.onnx",
               "vieneu_acoustic_cached.onnx", "vieneu_backbone_shared.data", "vieneu_v3_heads.npz")
CODEC_FILES = ("moss_audio_tokenizer_decode_full.onnx", "moss_audio_tokenizer_decode_shared.data",
               "moss_audio_tokenizer_decode_step.onnx", "codec_browser_onnx_meta.json",
               "moss_audio_tokenizer_encode.onnx", "moss_audio_tokenizer_encode.data")


def enabled() -> bool:
    path = Path.cwd() / "config" / "speech.local.json"
    if not path.is_file():
        return False
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    engine = data.get("vietnamese_engine", "supertonic")
    if engine not in {"supertonic", "vieneu"}:
        raise RuntimeError("Unknown Vietnamese speech engine in config/speech.local.json")
    return engine == "vieneu"


def model_manifest() -> tuple[Path, dict]:
    root = (Path.cwd() / MODEL_RELATIVE).resolve()
    path = root / "installed.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("sdk_version") != "3.8.3" or not isinstance(data.get("voices"), dict) or set(data["voices"]) != {"M1", "F1"}:
        raise RuntimeError("Invalid VieNeu manifest; run scripts/prepare-vieneu.ps1")
    for name, files in (("backbone", GRAPH_FILES), ("codec", CODEC_FILES)):
        if not isinstance(data.get(name), str) or not data[name]:
            raise RuntimeError("Invalid VieNeu model path in manifest")
        folder = (root / data[name]).resolve()
        if not folder.is_relative_to(root):
            raise RuntimeError("VieNeu model must remain inside its model folder")
        for filename in files:
            asset = folder / filename
            if not asset.is_file() or asset.stat().st_size == 0:
                raise RuntimeError(f"VieNeu model file missing: {asset}")
    for voice in data["voices"].values():
        if not isinstance(voice, dict) or not isinstance(voice.get("name"), str) or not isinstance(voice.get("label"), str):
            raise RuntimeError("Invalid Vietnamese voice profile in manifest")
    return path, data


def voice_pack(voice: str) -> Path:
    interpreter = Path.cwd() / "runtime" / "vieneu" / ".venv" / "Scripts" / "python.exe"
    if not interpreter.is_file():
        raise RuntimeError("VieNeu runtime missing; run scripts/prepare-vieneu.ps1")
    path, data = model_manifest()
    if voice not in data["voices"]:
        raise ValueError("Unknown Vietnamese voice")
    return path


def voice_label(voice: str) -> str:
    _, data = model_manifest()
    return data["voices"][voice]["label"]


class VietnameseTTS:
    def __init__(self):
        self.process = None
        self.responses = queue.Queue()
        self.lock = threading.Lock()
        self.stderr = None
        self.sequence = 0
        atexit.register(self.close)

    @staticmethod
    def _read_output(stream, responses):
        try:
            for line in stream:
                responses.put(json.loads(line))
        except Exception as exc:
            responses.put({"error": str(exc)})
        finally:
            responses.put({"error": "VieNeu worker exited; see .run/vieneu.stderr.log"})

    def _start(self):
        root = Path.cwd()
        model_root = root / MODEL_RELATIVE
        env = os.environ.copy()
        env.update(HF_HOME=str(model_root / "huggingface"),
                   HF_HUB_CACHE=str(model_root / "huggingface" / "hub"),
                   HF_HUB_OFFLINE="1", HF_HUB_DISABLE_SYMLINKS="1", HF_HUB_DISABLE_TELEMETRY="1",
                   XDG_CACHE_HOME=str(root / ".model-cache" / "vieneu"),
                   NUMBA_CACHE_DIR=str(root / ".model-cache" / "vieneu" / "numba"),
                   PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        # A plain python start (without start.ps1) must not put temp files on C:.
        temporary = root / ".model-cache" / "vieneu" / "temp"
        temporary.mkdir(parents=True, exist_ok=True)
        env.update(TEMP=str(temporary), TMP=str(temporary))
        (root / ".run").mkdir(exist_ok=True)
        self.stderr = (root / ".run" / "vieneu.stderr.log").open("a", encoding="utf-8")
        self.responses = queue.Queue()
        try:
            self.process = subprocess.Popen(
                [str(root / "runtime" / "vieneu" / ".venv" / "Scripts" / "python.exe"),
                 "-u", str(root / "backend" / "vieneu_worker.py")],
                cwd=root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr,
                text=True, encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            self.stderr.close()
            self.stderr = None
            raise
        threading.Thread(target=self._read_output, args=(self.process.stdout, self.responses), daemon=True).start()

    def synthesize(self, text: str, voice: str) -> tuple[np.ndarray, int]:
        voice_pack(voice)
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                self.close()
                self._start()
            self.sequence += 1
            try:
                self.process.stdin.write(json.dumps({"id": self.sequence, "text": text, "voice": voice}) + "\n")
                self.process.stdin.flush()
                result = self.responses.get(timeout=180)
                if result.get("error"):
                    raise RuntimeError(result["error"])
                if result.get("id") != self.sequence or result.get("rate") != 48000:
                    raise RuntimeError("Invalid VieNeu worker response")
                audio = np.frombuffer(base64.b64decode(result["pcm_f32"], validate=True), dtype="<f4").copy()
                if not audio.size or not np.isfinite(audio).all() or np.max(np.abs(audio)) < .0001:
                    raise RuntimeError("VieNeu returned empty, invalid or silent audio")
                return audio, result["rate"]
            except Exception as exc:
                self.close()
                raise RuntimeError(f"Vietnamese TTS failed: {exc}") from exc

    def close(self):
        process, self.process = self.process, None
        if process is not None:
            if process.stdin:
                try:
                    process.stdin.close()  # Worker exits on EOF when parent closes normally.
                except OSError:
                    pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            if process.stdout:
                process.stdout.close()
        if self.stderr is not None:
            self.stderr.close()
            self.stderr = None
