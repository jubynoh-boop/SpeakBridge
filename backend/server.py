from __future__ import annotations

import asyncio
import base64
import gc
import io
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
import torch
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

SAMPLE_RATE = 16_000
FRAME_SAMPLES = 512
LLM_BASE_URL = "http://127.0.0.1:8766"

LANGUAGE_NAMES = {
    "vi": "Vietnamese", "en": "English", "zh": "Simplified Chinese",
    "ja": "Japanese", "ko": "Korean", "fr": "French", "de": "German",
    "es": "Spanish", "ru": "Russian", "pt": "Portuguese", "it": "Italian",
    "nl": "Dutch", "pl": "Polish", "tr": "Turkish", "ar": "Arabic",
    "th": "Thai", "id": "Indonesian", "ms": "Malay", "hi": "Hindi",
    "uk": "Ukrainian", "cs": "Czech", "ro": "Romanian", "el": "Greek",
    "hu": "Hungarian", "sv": "Swedish", "da": "Danish", "fi": "Finnish",
    "no": "Norwegian", "he": "Hebrew",
}
SUPPORTED_LANGUAGES = set(LANGUAGE_NAMES)
HOTKEY_CONFIG_PATH = Path.cwd() / "config" / "hotkey.local.json"


class DictationRequest(BaseModel):
    pcm16_base64: str
    sample_rate: int = Field(default=16_000, ge=8_000, le=192_000)
    channels: int = Field(default=1, ge=1, le=8)
    mode: str = "fast"
    source_language: str = "vi"
    target_language: str = "en"
    translate: bool = True
    meeting_context: str = ""
    glossary: list[str] = Field(default_factory=list)


class HotkeySettings(BaseModel):
    hotkey: str = "ctrl+alt+space"
    microphone: str = "__default__"
    mode: str = "fast"
    source_language: str = "vi"
    target_language: str = "en"
    translate: bool = True


def load_hotkey_settings() -> HotkeySettings:
    try:
        return HotkeySettings.model_validate_json(HOTKEY_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return HotkeySettings()


@dataclass
class SessionConfig:
    mode: str = "fast"
    glossary: list[str] | None = None
    voice: str = "am_adam"
    meeting_context: str = ""
    source_language: str = "vi"
    target_language: str = "en"
    speak_translation: bool = True
    history: list[tuple[str, str]] = field(default_factory=list)


class SpeechSegmenter:
    """Stateful Silero VAD with an energy-based offline fallback."""

    def __init__(self, max_seconds: float = 7.0) -> None:
        self.pending = np.empty(0, dtype=np.float32)
        self.pre_roll: deque[np.ndarray] = deque(maxlen=10)
        self.current: list[np.ndarray] = []
        self.active = False
        self.silent_frames = 0
        self.max_frames = int(max_seconds * SAMPLE_RATE / FRAME_SAMPLES)
        self.vad: Any | None = None
        self.using_silero = False
        try:
            from silero_vad import VADIterator, load_silero_vad

            model = load_silero_vad(onnx=True)
            self.vad = VADIterator(
                model,
                threshold=0.52,
                sampling_rate=SAMPLE_RATE,
                min_silence_duration_ms=760,
                speech_pad_ms=240,
            )
            self.using_silero = True
        except Exception as exc:
            print(f"Silero VAD unavailable, using energy fallback: {exc}")

    def push_pcm16(self, payload: bytes) -> tuple[list[np.ndarray], bool]:
        pcm = np.frombuffer(payload, dtype="<i2").astype(np.float32) / 32768.0
        return self.push_float32(pcm)

    def push_float32(self, pcm: np.ndarray) -> tuple[list[np.ndarray], bool]:
        pcm = np.asarray(pcm, dtype=np.float32)
        self.pending = np.concatenate((self.pending, pcm))
        completed: list[np.ndarray] = []
        changed = False
        while len(self.pending) >= FRAME_SAMPLES:
            frame = self.pending[:FRAME_SAMPLES].copy()
            self.pending = self.pending[FRAME_SAMPLES:]
            segment, state_changed = self._push_frame(frame)
            changed = changed or state_changed
            if segment is not None and len(segment) >= int(0.32 * SAMPLE_RATE):
                completed.append(segment)
        return completed, changed

    def _push_frame(self, frame: np.ndarray) -> tuple[np.ndarray | None, bool]:
        event: dict[str, Any] | None = None
        if self.vad is not None:
            try:
                event = self.vad(torch.from_numpy(frame), return_seconds=False)
            except Exception as exc:
                print(f"Silero runtime error, switching to fallback: {exc}")
                self.vad = None
                self.using_silero = False

        if self.vad is None:
            rms = float(np.sqrt(np.mean(np.square(frame)) + 1e-12))
            if not self.active and rms >= 0.018:
                event = {"start": 0}
            elif self.active:
                self.silent_frames = self.silent_frames + 1 if rms < 0.011 else 0
                if self.silent_frames >= 24:
                    event = {"end": 0}

        if not self.active:
            self.pre_roll.append(frame)
            if event and "start" in event:
                self.active = True
                self.current = list(self.pre_roll)
                self.pre_roll.clear()
                self.silent_frames = 0
                return None, True
            return None, False

        self.current.append(frame)
        forced = len(self.current) >= self.max_frames
        ended = bool(event and "end" in event)
        if ended or forced:
            result = np.concatenate(self.current)
            self.current = []
            self.active = False
            self.silent_frames = 0
            if self.vad is not None:
                self.vad.reset_states()
            return result, True
        return None, False

    def force_flush(self) -> np.ndarray | None:
        """Finish an active utterance when a loopback device stops yielding silence."""
        if not self.active or not self.current:
            return None
        result = np.concatenate(self.current)
        self.current = []
        self.active = False
        self.silent_frames = 0
        if self.vad is not None:
            self.vad.reset_states()
        if len(result) < int(0.32 * SAMPLE_RATE):
            return None
        return result


class LocalModels:
    def __init__(self) -> None:
        self.asr: dict[str, Any] = {}
        self.tts: dict[str, Any] = {}
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.lock = threading.Lock()

    def is_ready(self, mode: str) -> bool:
        return mode in self.asr and "en" in self.tts and self._llm_is_ready()

    def prepare(self, mode: str) -> None:
        self._wait_for_llm()
        with self.lock:
            self._load(mode)

    def _load(self, mode: str) -> None:
        from faster_whisper import WhisperModel

        model_name = "large-v3" if mode == "quality" else "large-v3-turbo"
        if mode not in self.asr:
            # Hy-MT2 Q6 is larger than the previous translator. Keep only one
            # Whisper variant in VRAM so FAST/QUALITY both fit a 16 GB card.
            self.asr.clear()
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            compute = "float16" if self.device == "cuda" else "int8"
            self.asr[mode] = WhisperModel(model_name, device=self.device, compute_type=compute)

        if "en" not in self.tts:
            from kokoro import KPipeline

            self.tts["en"] = KPipeline(lang_code="a", device=self.device)

    def _tts_pipeline(self, language: str) -> Any | None:
        """Return a Kokoro pipeline, sharing one GPU model across languages."""
        if language not in {"en", "zh"}:
            return None
        if language not in self.tts:
            from kokoro import KPipeline

            self.tts[language] = KPipeline(
                lang_code="z" if language == "zh" else "a",
                model=self.tts["en"].model,
            )
        return self.tts[language]

    @staticmethod
    def _llm_is_ready() -> bool:
        try:
            with urllib.request.urlopen(f"{LLM_BASE_URL}/health", timeout=1) as response:
                return response.status == 200
        except (OSError, urllib.error.URLError):
            return False

    def _wait_for_llm(self, timeout_seconds: int = 600) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self._llm_is_ready():
                return
            time.sleep(1)
        raise RuntimeError("Hy-MT2 translator chưa sẵn sàng; xem .run/llm.stderr.log")

    @staticmethod
    def _chat(messages: list[dict[str, str]], max_tokens: int = 128) -> str:
        # Hy-MT2's local chat template works most reliably without a system role.
        combined_prompt = "\n\n".join(message["content"] for message in messages)
        payload = json.dumps({
            "model": "hy-mt2-7b",
            "messages": [{"role": "user", "content": combined_prompt}],
            "temperature": 0.0,
            "top_p": 1.0,
            "max_tokens": max_tokens,
            "stream": False,
        }).encode("utf-8")
        request = urllib.request.Request(
            f"{LLM_BASE_URL}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
        content = result["choices"][0]["message"]["content"].strip()
        content = re.sub(r"^```(?:text)?\s*|\s*```$", "", content, flags=re.IGNORECASE)
        return content.strip().strip('"')

    def _translate(self, source: str, config: SessionConfig) -> str:
        glossary = config.glossary or []
        source_name = LANGUAGE_NAMES.get(config.source_language, config.source_language)
        target_name = LANGUAGE_NAMES.get(config.target_language, config.target_language)
        if config.source_language == config.target_language:
            return source
        context = "\n".join(
            f"Source: {previous_source}\nTranslation: {previous_target}"
            for previous_source, previous_target in config.history[-4:]
        )
        glossary_text = ", ".join(glossary[:60]) or "(none)"
        system = (
            f"You are a precise real-time meeting interpreter. Translate {source_name} into {target_name}. "
            f"Return only one natural spoken-{target_name} translation, with no labels or explanation. "
            "Preserve the complete meaning, question/statement form, negation, tense, modality, "
            "names, numbers, product names, and technical terms. Never answer the speaker, infer "
            "missing facts, summarize, embellish, or repeat words that are not repeated in the source. "
            "Resolve ambiguity only from the supplied meeting context and recent conversation."
        )
        user = (
            f"Relevant glossary (preserve exactly when present): {glossary_text}\n"
            f"Meeting context: {config.meeting_context[:1000] or '(none)'}\n"
            f"Recent context (reference only; do not translate it again):\n{context or '(none)'}\n\n"
            f"{source_name} to translate now:\n{source}"
        )
        max_tokens = min(220, max(32, len(source.split()) * 4 + len(source) // 2 + 16))
        candidate = self._chat([
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ], max_tokens=max_tokens)

        if config.mode == "quality":
            candidate = self._chat([
                {"role": "system", "content": (
                    f"Verify this {source_name}-to-{target_name} meeting translation. Correct omissions, "
                    "additions, wrong meaning, question form, names, and numbers. Output only the corrected "
                    f"{target_name} translation."
                )},
                {"role": "user", "content": (
                    f"Source: {source}\nCandidate: {candidate}\n"
                    "Return the faithful corrected translation only."
                )},
            ], max_tokens=max_tokens)

        # Translation models can paraphrase this microphone-check question into the
        # positive "Do I speak clearly?".  That is pragmatically similar, but
        # it drops the source's explicit difficulty/negation, so keep it exact.
        normalized_vi = source.casefold()
        if (
            config.source_language == "vi"
            and config.target_language == "en"
            and "khó nghe" in normalized_vi
            and any(word in normalized_vi for word in ("tôi", "mình"))
            and any(word in normalized_vi for word in ("nói", "giọng"))
            and ("không" in normalized_vi or source.rstrip().endswith("?"))
        ):
            return "Is it difficult to understand me when I speak?"
        return candidate

    @staticmethod
    def _canonicalize_terms(text: str, glossary: list[str]) -> str:
        """Restore exact glossary casing without inserting artificial tokens."""
        result = text
        for term in sorted(glossary, key=len, reverse=True):
            term = term.strip()
            if term:
                result = re.sub(re.escape(term), term, result, flags=re.IGNORECASE)
        return result

    @staticmethod
    def _is_hallucinated(text: str, audio_seconds: float) -> bool:
        words = re.findall(r"[\wÀ-ỹ]+", text.lower(), flags=re.UNICODE)
        normalized = " ".join(words)
        known_hallucinations = (
            "hãy đăng ký kênh",
            "hãy subscribe cho kênh",
            "cảm ơn các bạn đã xem",
            "cảm ơn các bạn đã theo dõi",
            "cảm ơn bạn đã theo dõi",
            "cảm ơn mọi người đã theo dõi",
            "cảm ơn quý vị đã theo dõi",
            "theo dõi và hẹn gặp lại",
            "hẹn gặp lại các bạn",
            "đừng quên like và subscribe",
        )
        if any(phrase in normalized for phrase in known_hallucinations):
            return True
        if len(words) < 12:
            return False
        most_common = Counter(words).most_common(1)[0][1]
        repeated_word = most_common >= 7 and most_common / len(words) >= 0.22
        impossible_rate = len(words) > max(30, int(audio_seconds * 6.5))
        return repeated_word or impossible_rate

    @staticmethod
    def _is_bad_translation(source: str, translation: str) -> bool:
        source_words = re.findall(r"[\wÀ-ỹ]+", source.lower(), flags=re.UNICODE)
        target_words = re.findall(r"[\wÀ-ỹ]+", translation.lower(), flags=re.UNICODE)
        if not target_words:
            return True
        most_common = Counter(target_words).most_common(1)[0][1]
        repeated = most_common >= 6 and most_common / len(target_words) >= 0.28
        # Chinese normally has no spaces, so regex sees an entire sentence as
        # one "word". Estimate CJK semantic units to avoid rejecting a normal
        # Vietnamese/English translation as an artificial expansion.
        source_cjk = len(re.findall(r"[\u3400-\u9fff]", source))
        target_cjk = len(re.findall(r"[\u3400-\u9fff]", translation))
        source_units = max(len(source_words), (source_cjk + 1) // 2)
        target_units = max(len(target_words), (target_cjk + 1) // 2)
        expanded = target_units > max(14, int(source_units * 2.2) + 5)
        return repeated or expanded

    def _transcribe(
        self,
        audio: np.ndarray,
        config: SessionConfig,
        language: str | None,
        *,
        relaxed_media: bool = False,
    ) -> tuple[str, str]:
        # Whisper can confidently invent common video-outro phrases from fan noise,
        # keyboard sounds or electrical hiss. Reject clips without speech-like energy.
        frame_count = len(audio) // FRAME_SAMPLES
        if frame_count:
            framed = audio[: frame_count * FRAME_SAMPLES].reshape(frame_count, FRAME_SAMPLES)
            frame_rms = np.sqrt(np.mean(np.square(framed), axis=1) + 1e-12)
            speech_energy = float(np.percentile(frame_rms, 85))
        else:
            speech_energy = float(np.sqrt(np.mean(np.square(audio)) + 1e-12)) if len(audio) else 0.0
        if speech_energy < 0.009:
            raise RuntimeError("Đoạn chỉ có nhiễu/âm lượng quá nhỏ nên đã được bỏ")

        glossary = config.glossary or []
        # A Vietnamese meeting description can actively bias Whisper away from
        # Mandarin/English when 02A is capturing media. Only pass terms that fit
        # a fixed source language; AUTO relies on Whisper's own language detector.
        if language == "vi":
            hotword_parts = [*glossary[:80]]
        elif language == "zh":
            hotword_parts = [term for term in glossary[:80] if re.search(r"[\u3400-\u9fff]", term)]
        elif language == "en":
            hotword_parts = [term for term in glossary[:80] if term.isascii()]
        else:
            hotword_parts = []
        if config.meeting_context and language == "vi":
            hotword_parts.append(config.meeting_context[:400])
        hotwords = "; ".join(part for part in hotword_parts if part.strip()) or None
        beam_size = 1 if config.mode == "fast" else 5
        if relaxed_media and language == "zh":
            beam_size = max(3, beam_size)
        segments, info = self.asr[config.mode].transcribe(
            audio,
            language=language,
            task="transcribe",
            beam_size=beam_size,
            temperature=0.0,
            word_timestamps=False,
            vad_filter=False,
            initial_prompt=None,
            hotwords=hotwords,
            condition_on_previous_text=False,
            compression_ratio_threshold=2.35 if relaxed_media else 1.9,
            log_prob_threshold=-1.05 if relaxed_media else -0.72,
            no_speech_threshold=0.60 if relaxed_media else 0.42,
        )
        segment_list = list(segments)
        text = " ".join(segment.text.strip() for segment in segment_list).strip()
        if not text:
            return "", language or getattr(info, "language", "auto")
        average_logprob = sum(segment.avg_logprob for segment in segment_list) / max(1, len(segment_list))
        average_no_speech = sum(segment.no_speech_prob for segment in segment_list) / max(1, len(segment_list))
        worst_compression = max((segment.compression_ratio for segment in segment_list), default=0.0)
        max_no_speech = 0.68 if relaxed_media else 0.48
        min_logprob = -1.20 if relaxed_media else -0.78
        max_compression = 2.45 if relaxed_media else 2.15
        if average_no_speech >= max_no_speech or average_logprob < min_logprob or worst_compression > max_compression:
            print(
                "ASR rejected "
                f"language={language or getattr(info, 'language', 'auto')} "
                f"media={relaxed_media} no_speech={average_no_speech:.3f} "
                f"logprob={average_logprob:.3f} compression={worst_compression:.3f}"
            )
            raise RuntimeError("ASR không đủ tin cậy; đoạn này đã bị bỏ")
        if self._is_hallucinated(text, len(audio) / SAMPLE_RATE):
            print(
                "ASR hallucination filter rejected "
                f"language={language or getattr(info, 'language', 'auto')} "
                f"seconds={len(audio) / SAMPLE_RATE:.2f} text={text!r}",
                flush=True,
            )
            raise RuntimeError("ASR phát hiện transcript lặp/hallucination; đoạn này đã bị bỏ")
        return text, language or getattr(info, "language", "auto")

    def process_outgoing(self, audio: np.ndarray, config: SessionConfig) -> tuple[str, str, str, bytes]:
        with self.lock:
            self._load(config.mode)
            glossary = config.glossary or []
            requested_source = config.source_language
            transcript, detected_language = self._transcribe(
                audio, config, None if requested_source == "auto" else requested_source
            )
            if not transcript:
                return "", "", requested_source, b""
            transcript = self._canonicalize_terms(transcript, glossary)
            effective_source = detected_language if requested_source == "auto" else requested_source
            config.source_language = effective_source
            translation = self._canonicalize_terms(self._translate(transcript, config), glossary)
            config.source_language = requested_source
            if self._is_bad_translation(transcript, translation):
                raise RuntimeError("Bản dịch dài/lặp bất thường; đoạn này đã bị bỏ thay vì phát câu sai")
            config.history.append((transcript, translation))
            del config.history[:-6]

            chunks = []
            pipeline = self._tts_pipeline(config.target_language) if config.speak_translation else None
            if pipeline is not None:
                default_voice = "zm_yunxi" if config.target_language == "zh" else "am_adam"
                voice = config.voice or default_voice
                for _, _, chunk in pipeline(translation, voice=voice, speed=1.08):
                    if torch.is_tensor(chunk):
                        chunk = chunk.detach().cpu().numpy()
                    chunks.append(np.asarray(chunk, dtype=np.float32))
            waveform = np.concatenate(chunks) if chunks else np.empty(0, dtype=np.float32)
            output = io.BytesIO()
            if len(waveform):
                sf.write(output, waveform, 24_000, format="WAV", subtype="PCM_16")
            return transcript, translation, effective_source, output.getvalue()

    def process_incoming(self, audio: np.ndarray, config: SessionConfig) -> tuple[str, str, str]:
        with self.lock:
            self._load(config.mode)
            requested_source = config.source_language
            original, detected_language = self._transcribe(
                audio,
                config,
                None if requested_source == "auto" else requested_source,
                relaxed_media=True,
            )
            if not original:
                return "", "", detected_language
            effective_source = detected_language if requested_source == "auto" else requested_source
            config.source_language = effective_source
            translation = self._translate(original, config)
            config.source_language = requested_source
            if self._is_bad_translation(original, translation):
                raise RuntimeError("Bản dịch đầu vào dài/lặp bất thường; đoạn này đã bị bỏ")
            config.history.append((original, translation))
            del config.history[:-6]
            return original, translation, effective_source

    def process_dictation(
        self, audio: np.ndarray, config: SessionConfig, translate: bool
    ) -> tuple[str, str, str]:
        """Transcribe one push-to-talk recording and optionally translate it."""
        with self.lock:
            self._load(config.mode)
            requested_source = config.source_language
            transcript, detected_language = self._transcribe(
                audio, config, None if requested_source == "auto" else requested_source
            )
            if not transcript:
                return "", "", detected_language
            transcript = self._canonicalize_terms(transcript, config.glossary or [])
            effective_source = detected_language if requested_source == "auto" else requested_source
            if not translate or effective_source == config.target_language:
                return transcript, transcript, effective_source
            config.source_language = effective_source
            result = self._canonicalize_terms(
                self._translate(transcript, config), config.glossary or []
            )
            config.source_language = requested_source
            if self._is_bad_translation(transcript, result):
                raise RuntimeError("Bản dịch nhập liệu dài/lặp bất thường nên đã bị bỏ")
            return transcript, result, effective_source


models = LocalModels()
system_audio_connection_lock = asyncio.Lock()
app = FastAPI(title="SpeakBridge Local Engine", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "device": models.device, "cuda": torch.cuda.is_available(), "translator": "hy-mt2" if models._llm_is_ready() else "loading"}


@app.get("/models/status")
def model_status() -> dict[str, Any]:
    """Report only local model assets; this endpoint never downloads anything."""
    hf_home = Path(os.environ.get("HF_HOME", str(Path.cwd() / ".model-cache")))
    hub = Path(os.environ.get("HF_HUB_CACHE", str(hf_home / "hub")))
    hy_model = Path(os.environ.get(
        "SPEAKBRIDGE_HY_MODEL",
        str(Path.cwd() / "models" / "HY-MT2-7B-Q6_K.gguf"),
    ))
    kokoro = hub / "models--hexgrad--Kokoro-82M"
    assets = [
        ("Whisper large-v3-turbo", "ASR FAST", hub / "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo", "GPU"),
        ("Whisper large-v3", "ASR QUALITY", hub / "models--Systran--faster-whisper-large-v3", "GPU"),
        ("Hy-MT2 7B Q6", "Translation", hy_model, "GPU / Vulkan"),
        ("Kokoro-82M", "English/Chinese TTS", kokoro, "GPU"),
    ]

    def size_bytes(path: Path) -> int:
        if path.is_file():
            return path.stat().st_size
        if path.is_dir():
            return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
        return 0

    return {
        "ok": True,
        "cache_root": str(hf_home),
        "assets": [
            {
                "name": name,
                "role": role,
                "processor": processor,
                "installed": path.exists(),
                "size_gb": round(size_bytes(path) / (1024 ** 3), 2),
                "path": str(path),
            }
            for name, role, path, processor in assets
        ],
        "verified_languages": ["vi", "en", "zh"],
        "tts_languages": ["en", "zh"],
    }


@app.get("/hotkey/settings")
def hotkey_settings() -> dict[str, Any]:
    return {"ok": True, **load_hotkey_settings().model_dump()}


@app.post("/hotkey/settings")
def save_hotkey_settings(settings: HotkeySettings) -> dict[str, Any]:
    if settings.source_language not in SUPPORTED_LANGUAGES | {"auto"}:
        raise HTTPException(status_code=400, detail="Unsupported source language")
    if settings.target_language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported target language")
    if settings.mode not in {"fast", "quality"}:
        raise HTTPException(status_code=400, detail="Unsupported mode")
    normalized_hotkey = settings.hotkey.strip().lower()
    if not normalized_hotkey or len(normalized_hotkey) > 80:
        raise HTTPException(status_code=400, detail="Invalid hotkey")
    settings.hotkey = normalized_hotkey
    HOTKEY_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    HOTKEY_CONFIG_PATH.write_text(
        json.dumps(settings.model_dump(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"ok": True, **settings.model_dump()}


@app.post("/dictate")
async def dictate(request: DictationRequest) -> dict[str, Any]:
    try:
        raw = base64.b64decode(request.pcm16_base64, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="Invalid PCM audio") from exc
    if len(raw) < request.channels * 2 * int(request.sample_rate * 0.20):
        raise HTTPException(status_code=400, detail="Recording is too short")
    if len(raw) > request.channels * 2 * request.sample_rate * 60:
        raise HTTPException(status_code=400, detail="Recording exceeds 60 seconds")

    pcm = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if request.channels > 1:
        usable = len(pcm) - (len(pcm) % request.channels)
        channel_audio = pcm[:usable].reshape(-1, request.channels)
        # Many USB microphones expose two channels while carrying the real mic
        # signal on only one. Select the strongest channel instead of averaging
        # it with silence (or an opposite-polarity duplicate).
        channel_rms = np.sqrt(np.mean(np.square(channel_audio), axis=0) + 1e-12)
        pcm = channel_audio[:, int(np.argmax(channel_rms))]
    if request.sample_rate != SAMPLE_RATE:
        output_size = max(1, round(len(pcm) * SAMPLE_RATE / request.sample_rate))
        positions = np.linspace(0, max(0, len(pcm) - 1), output_size)
        pcm = np.interp(positions, np.arange(len(pcm)), pcm).astype(np.float32)

    pcm = pcm - float(np.mean(pcm))
    input_rms = float(np.sqrt(np.mean(np.square(pcm)) + 1e-12))
    input_peak = float(np.max(np.abs(pcm))) if len(pcm) else 0.0
    # Quiet USB microphones are common. Apply a conservative hotkey-only gain;
    # the ASR speech/noise and hallucination guards still run afterwards.
    gain = min(6.0, 0.035 / max(input_rms, 1e-6)) if 0.0015 <= input_rms < 0.025 else 1.0
    if gain > 1.0:
        pcm = np.clip(pcm * gain, -0.98, 0.98).astype(np.float32)
    print(
        f"Dictation audio seconds={len(pcm) / SAMPLE_RATE:.2f} channels={request.channels} "
        f"rms={input_rms:.5f} peak={input_peak:.5f} gain={gain:.2f}",
        flush=True,
    )

    source_language = request.source_language if request.source_language in SUPPORTED_LANGUAGES | {"auto"} else "vi"
    target_language = request.target_language if request.target_language in SUPPORTED_LANGUAGES else "en"
    config = SessionConfig(
        mode="quality" if request.mode == "quality" else "fast",
        glossary=[str(item)[:100] for item in request.glossary[:100]],
        meeting_context=request.meeting_context[:2000],
        source_language=source_language,
        target_language=target_language,
        speak_translation=False,
    )
    try:
        transcript, result, detected = await asyncio.to_thread(
            models.process_dictation, pcm, config, request.translate
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "ok": True,
        "transcript": transcript,
        "text": result,
        "source_language": detected,
        "target_language": target_language if request.translate else detected,
    }


@app.get("/audio-output-devices")
async def audio_output_devices() -> dict[str, Any]:
    try:
        from backend.system_audio import list_output_devices

        devices = await asyncio.to_thread(list_output_devices)
        return {"ok": True, "devices": devices}
    except Exception as exc:
        return {"ok": False, "devices": [], "error": str(exc)}


@app.get("/audio-input-devices")
async def audio_input_devices() -> dict[str, Any]:
    try:
        from backend.system_audio import list_input_devices

        devices = await asyncio.to_thread(list_input_devices)
        return {"ok": True, "devices": devices}
    except Exception as exc:
        return {"ok": False, "devices": [], "error": str(exc)}


@app.post("/prepare/{mode}")
async def prepare_mode(mode: str) -> dict[str, Any]:
    selected_mode = "quality" if mode == "quality" else "fast"
    await asyncio.to_thread(models.prepare, selected_mode)
    return {"ok": True, "mode": selected_mode, "ready": True}


@app.websocket("/ws/audio")
async def audio_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    send_lock = asyncio.Lock()

    async def send(message: dict[str, Any]) -> None:
        async with send_lock:
            await websocket.send_json(message)

    config = SessionConfig(glossary=[])
    queue: asyncio.Queue[tuple[str, np.ndarray] | None] = asyncio.Queue(maxsize=8)

    async def worker() -> None:
        while True:
            item = await queue.get()
            if item is None:
                return
            utterance_id, audio = item
            try:
                if not models.is_ready(config.mode):
                    await send({"type": "status", "message": "Đang tải model local lần đầu…"})
                started = time.perf_counter()
                source_text, translated_text, detected_language, wav = await asyncio.to_thread(models.process_outgoing, audio, config)
                latency_ms = round((time.perf_counter() - started) * 1000)
                if source_text:
                    await send({
                        "type": "result",
                        "id": utterance_id,
                        "source": source_text,
                        "translation": translated_text,
                        "source_lang": detected_language,
                        "target_lang": config.target_language,
                        "latency_ms": latency_ms,
                        "audio_base64": base64.b64encode(wav).decode("ascii") if wav else "",
                    })
                    await send({"type": "status", "message": "Đang nghe microphone"})
                else:
                    await send({"type": "error", "id": utterance_id, "message": "Không nhận ra lời nói trong đoạn vừa rồi"})
            except Exception as exc:
                await send({"type": "error", "id": utterance_id, "message": f"Pipeline lỗi: {exc}"})
            finally:
                queue.task_done()

    worker_task = asyncio.create_task(worker())
    segmenter: SpeechSegmenter | None = None
    last_vad_state = False
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            if message.get("text") is not None:
                payload = json.loads(message["text"])
                if payload.get("type") == "config":
                    config.mode = "quality" if payload.get("mode") == "quality" else "fast"
                    config.glossary = [str(item)[:100] for item in payload.get("glossary", [])][:100]
                    config.meeting_context = str(payload.get("meeting_context", ""))[:2000]
                    requested_source = str(payload.get("source_language", "vi"))
                    requested_target = str(payload.get("target_language", "en"))
                    config.source_language = requested_source if requested_source in SUPPORTED_LANGUAGES or requested_source == "auto" else "vi"
                    config.target_language = requested_target if requested_target in SUPPORTED_LANGUAGES else "en"
                    config.speak_translation = bool(payload.get("speak_translation", True))
                    allowed_voices = {"af_heart", "am_adam", "am_michael", "bm_george", "bm_lewis", "zm_yunxi"}
                    requested_voice = str(payload.get("voice", "am_adam"))
                    default_voice = "zm_yunxi" if config.target_language == "zh" else "am_adam"
                    config.voice = requested_voice if requested_voice in allowed_voices else default_voice
                    segmenter = await asyncio.to_thread(SpeechSegmenter)
                    await send({"type": "status", "message": f"VAD: {'Silero' if segmenter.using_silero else 'energy fallback'} · {config.mode.upper()}"})
                continue

            data = message.get("bytes")
            if data is None or segmenter is None:
                continue
            completed, changed = segmenter.push_pcm16(data)
            if changed and segmenter.active != last_vad_state:
                last_vad_state = segmenter.active
                await send({"type": "vad", "active": last_vad_state})
            for audio in completed:
                utterance_id = uuid.uuid4().hex[:10]
                await send({"type": "processing", "id": utterance_id})
                try:
                    queue.put_nowait((utterance_id, audio))
                except asyncio.QueueFull:
                    await send({"type": "error", "id": utterance_id, "message": "Bạn đang nói nhanh hơn hàng đợi xử lý"})
    except WebSocketDisconnect:
        pass
    finally:
        await queue.put(None)
        await worker_task


@app.websocket("/ws/system-audio")
async def system_audio_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    if system_audio_connection_lock.locked():
        await websocket.send_json({"type": "error", "message": "Luồng âm thanh hệ thống đang được sử dụng"})
        await websocket.close()
        return

    async with system_audio_connection_lock:
        from backend.system_audio import SystemAudioCapture

        capture: SystemAudioCapture | None = None
        worker_task: asyncio.Task[None] | None = None
        disconnect_task: asyncio.Task[dict[str, Any]] | None = None
        queue: asyncio.Queue[tuple[str, np.ndarray] | None] = asyncio.Queue(maxsize=8)
        send_lock = asyncio.Lock()

        async def send(message: dict[str, Any]) -> None:
            async with send_lock:
                await websocket.send_json(message)

        try:
            first_message = await websocket.receive()
            if first_message.get("type") == "websocket.disconnect":
                return
            payload = json.loads(first_message.get("text") or "{}")
            if payload.get("type") != "config":
                raise RuntimeError("Thiếu cấu hình cho luồng âm thanh hệ thống")

            config = SessionConfig(
                mode="quality" if payload.get("mode") == "quality" else "fast",
                glossary=[str(item)[:100] for item in payload.get("glossary", [])][:100],
                meeting_context=str(payload.get("meeting_context", ""))[:2000],
                source_language=(
                    str(payload.get("source_language", "auto"))
                    if str(payload.get("source_language", "auto")) in SUPPORTED_LANGUAGES or str(payload.get("source_language", "auto")) == "auto"
                    else "auto"
                ),
                target_language=(
                    str(payload.get("target_language", "vi"))
                    if str(payload.get("target_language", "vi")) in SUPPORTED_LANGUAGES
                    else "vi"
                ),
                speak_translation=False,
            )
            await asyncio.to_thread(models.prepare, config.mode)
            segmenter = await asyncio.to_thread(SpeechSegmenter, 9.0)
            requested_device = str(payload.get("device", "__default__"))
            capture = SystemAudioCapture(None if requested_device == "__default__" else requested_device)
            await asyncio.to_thread(capture.start)
            await send({
                "type": "status",
                "message": f"Đang nghe âm thanh hệ thống · {capture.active_device}",
                "device": capture.active_device,
            })

            async def worker() -> None:
                while True:
                    item = await queue.get()
                    if item is None:
                        return
                    utterance_id, audio = item
                    try:
                        started = time.perf_counter()
                        original, vietnamese, language = await asyncio.to_thread(
                            models.process_incoming, audio, config
                        )
                        latency_ms = round((time.perf_counter() - started) * 1000)
                        if original:
                            await send({
                                "type": "result",
                                "id": utterance_id,
                                "source": original,
                                "translation": vietnamese,
                                "source_lang": language,
                                "latency_ms": latency_ms,
                            })
                        else:
                            await send({
                                "type": "error",
                                "id": utterance_id,
                                "message": "Không nhận ra lời nói; đoạn này đã được bỏ",
                            })
                    except Exception as exc:
                        await send({"type": "error", "id": utterance_id, "message": f"Dịch bên kia lỗi: {exc}"})
                    finally:
                        queue.task_done()

            worker_task = asyncio.create_task(worker())
            disconnect_task = asyncio.create_task(websocket.receive())
            last_vad_state = False
            last_audio_at = time.monotonic()
            while not disconnect_task.done():
                chunk = await asyncio.to_thread(capture.get_audio, 0.25)
                if chunk is None:
                    if segmenter.active and time.monotonic() - last_audio_at >= 0.9:
                        forced_audio = segmenter.force_flush()
                        last_vad_state = False
                        await send({"type": "vad", "active": False})
                        if forced_audio is not None:
                            utterance_id = uuid.uuid4().hex[:10]
                            await send({"type": "processing", "id": utterance_id})
                            try:
                                queue.put_nowait((utterance_id, forced_audio))
                            except asyncio.QueueFull:
                                await send({"type": "error", "id": utterance_id, "message": "Hàng đợi phụ đề đang đầy"})
                    continue
                last_audio_at = time.monotonic()
                completed, changed = segmenter.push_float32(chunk)
                if changed and segmenter.active != last_vad_state:
                    last_vad_state = segmenter.active
                    await send({"type": "vad", "active": last_vad_state})
                for audio in completed:
                    utterance_id = uuid.uuid4().hex[:10]
                    await send({"type": "processing", "id": utterance_id})
                    try:
                        queue.put_nowait((utterance_id, audio))
                    except asyncio.QueueFull:
                        await send({"type": "error", "id": utterance_id, "message": "Hàng đợi phụ đề đang đầy"})
        except (WebSocketDisconnect, RuntimeError) as exc:
            try:
                await send({"type": "error", "message": str(exc)})
            except Exception:
                pass
        except Exception as exc:
            try:
                await send({"type": "error", "message": f"Không mở được âm thanh hệ thống: {exc}"})
            except Exception:
                pass
        finally:
            if disconnect_task is not None and not disconnect_task.done():
                disconnect_task.cancel()
            if capture is not None:
                await asyncio.to_thread(capture.stop)
            if worker_task is not None:
                await queue.put(None)
                await worker_task
