import os
from pathlib import Path

from huggingface_hub import hf_hub_download

from backend.server import models


HY_REPO = "tencent/Hy-MT2-7B-GGUF"
HY_FILENAME = "HY-MT2-7B-Q6_K.gguf"


def ensure_hy_model() -> Path:
    destination = Path(
        os.environ.get("SPEAKBRIDGE_HY_MODEL", Path.cwd() / "models" / HY_FILENAME)
    ).resolve()
    if destination.is_file() and destination.stat().st_size > 1_000_000_000:
        print(f"Hy-MT2 da co san: {destination}")
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    print(f"Dang tai {HY_REPO}/{HY_FILENAME} (~6.16 GB)...")
    downloaded = Path(
        hf_hub_download(
            repo_id=HY_REPO,
            filename=HY_FILENAME,
            local_dir=destination.parent,
        )
    ).resolve()
    if downloaded != destination:
        downloaded.replace(destination)
    print(f"Da tai Hy-MT2: {destination}")
    return destination


def main() -> None:
    ensure_hy_model()
    print("Dang tai Faster-Whisper Turbo va Kokoro Anh/Trung...")
    models._load("fast")
    for voice in ("af_heart", "am_adam", "am_michael", "bm_george", "bm_lewis"):
        print(f"Dang tai voice: {voice}")
        models.tts["en"].load_voice(voice)
    print("Dang tai voice Trung: zm_yunxi")
    models._tts_pipeline("zh").load_voice("zm_yunxi")
    print("Da san sang. Model duoc luu trong cache local cua Hugging Face.")


if __name__ == "__main__":
    main()
