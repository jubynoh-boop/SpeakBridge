"""Private JSON-lines worker. SDK diagnostics go to stderr, never to protocol.

This script must be launched with runtime/vieneu/.venv, not the main .venv.
The parent owns stdin: closing it releases the worker and loaded CPU sessions.
"""
import base64
import contextlib
import json
import sys
from pathlib import Path


def main():
    import numpy as np
    output = sys.stdout
    with contextlib.redirect_stdout(sys.stderr):
        from vieneu import Vieneu
        root = Path.cwd() / "models" / "vieneu-v3-turbo"
        manifest = json.loads((root / "installed.json").read_text(encoding="utf-8"))
        tts = Vieneu(mode="v3turbo", device="cpu", backend="onnx", precision="fp32", threads=4,
                     onnx_dir=str(root / manifest["backbone"]))
    try:
        for line in sys.stdin:
            request = {}
            try:
                request = json.loads(line)
                text = request["text"]
                if not isinstance(text, str) or not text.strip() or len(text) > 10000:
                    raise ValueError("Invalid speech text")
                name = manifest["voices"][request["voice"]]["name"]
                with contextlib.redirect_stdout(sys.stderr):
                    audio = np.asarray(tts.infer(text=text, voice=name, apply_watermark=False), dtype="<f4").reshape(-1)
                response = {"id": request["id"], "rate": int(tts.sample_rate),
                            "pcm_f32": base64.b64encode(audio.tobytes()).decode("ascii")}
            except Exception as exc:
                response = {"id": request.get("id"), "error": str(exc)}
            output.write(json.dumps(response) + "\n")
            output.flush()
    finally:
        tts.close()


if __name__ == "__main__":
    main()
