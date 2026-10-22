"""The voices exposed by SpeakBridge, with strictly local voice packs."""
from pathlib import Path

VOICES = {
    "en": {"am_adam": "Adam · US", "am_michael": "Michael · US", "bm_george": "George · UK", "bm_lewis": "Lewis · UK", "af_heart": "Heart · US"},
    "zh": {"zm_yunxi": "Yunxi"},
    "vi": {"M1": "M1 · Male", "F1": "F1 · Female"},
    "ja": {"M1": "M1 · Male", "F1": "F1 · Female"},
    "ko": {"M1": "M1 · Male", "F1": "F1 · Female"},
}
SAMPLES = {"en": "Hello. We can discuss the payment tomorrow.", "zh": "你好，我们明天可以讨论付款。",
           "vi": "Xin chào. Chúng ta có thể trao đổi về thanh toán ngày mai.",
           "ja": "こんにちは。明日、お支払いについて話しましょう。", "ko": "안녕하세요. 내일 결제에 대해 이야기합시다."}

DEFAULT_READ_VOICES = {"en": "am_adam", "zh": "zm_yunxi", "vi": "F1", "ja": "F1", "ko": "F1"}


def read_voice_choices(choices: dict[str, str]) -> dict[str, str]:
    for language, voice in choices.items():
        if voice not in VOICES.get(language, {}):
            raise ValueError(f"Voice {voice} does not support {language}")
    return {**DEFAULT_READ_VOICES, **choices}


def resolve_voice(language: str, voice: str) -> str:
    options = VOICES.get(language, {})
    return voice if voice in options else next(iter(options), "")


def local_voice_pack(language: str, voice: str) -> Path:
    if voice not in VOICES.get(language, {}):
        raise ValueError(f"Voice {voice} does not support {language}")
    if language == "vi":
        from backend.vietnamese_tts import enabled, voice_pack
        if enabled():
            return voice_pack(voice)
    if language in {"vi", "ja", "ko"}:
        path = Path.cwd() / ".model-cache" / "supertonic3" / "voice_styles" / f"{voice}.json"
    else:
        from huggingface_hub import hf_hub_download
        try:
            path = Path(hf_hub_download("hexgrad/Kokoro-82M", f"voices/{voice}.pt", local_files_only=True))
        except Exception as exc:
            raise RuntimeError(f"Local voice pack missing: {language}/{voice}. Run model preparation on the configured model drive.") from exc
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"Local voice pack missing or empty: {path}")
    return path
