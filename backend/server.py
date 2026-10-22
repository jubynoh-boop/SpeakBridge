from __future__ import annotations

import asyncio
import base64
import gc
import io
import json
import logging
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
from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError

from backend.advisor import AdvisorEngine
from backend.screen_ocr import ScreenOCR
from backend.tts_voices import VOICES, SAMPLES, DEFAULT_READ_VOICES, read_voice_choices, local_voice_pack, resolve_voice
from backend.text_segments import split_text
from backend.video_dub import VideoDubManager, ensure_coccoc_cdp, inject_extension_via_cdp, open_extensions_page_via_cdp
from desktop.windows_hotkeys import parse_shortcut, normalize_shortcut

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
SCREEN_READ_LANGUAGES = {"vi", "en", "zh", "ja", "ko"}
HOTKEY_CONFIG_PATH = Path.cwd() / "config" / "hotkey.local.json"
HOTKEY_SETTINGS_LOCK = threading.RLock()


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


class TextTranslationRequest(BaseModel):
    text: str = Field(min_length=1, max_length=6000)
    source_language: str = "vi"
    target_language: str = "en"
    mode: str = "fast"


class ScreenOCRRequest(BaseModel):
    image_base64: str = Field(min_length=16, max_length=12_000_000)
    source_language: str = "zh"
    target_language: str = "vi"
    processor: str = "cpu"
    mode: str = "fast"
    previous_text: str = Field(default="", max_length=6000)


class ScreenReadRequest(BaseModel):
    image_base64: str = Field(min_length=16, max_length=12_000_000)
    source_language: str = "zh"
    target_language: str = "vi"
    processor: str = "cpu"
    read_mode: str = "translation"


class SelectedTextReadRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1500)
    source_language: str = "auto"
    target_language: str = "vi"
    read_mode: str = "source"
    voices: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_READ_VOICES))


class VoiceTestRequest(BaseModel):
    language: str = Field(default="en", max_length=10)
    voice: str = Field(default="am_adam", max_length=50)


class AdvisorConfigRequest(BaseModel):
    enabled: bool = False
    provider: str = "9router"
    base_url: str = Field(default="http://127.0.0.1:20128/v1", max_length=500)
    model: str = Field(default="auto", max_length=200)
    api_key: str = Field(default="", max_length=1000)
    clear_api_key: bool = False
    strict_scope: bool = True
    deal_mode: bool = True
    trigger_mode: str = "silence"
    silence_seconds: float = Field(default=3.0, ge=0.5, le=20.0)
    max_suggestions: int = Field(default=3, ge=1, le=5)
    knowledge_context: str = Field(default="", max_length=12000)


class AdvisorDocumentRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=240)
    content_base64: str = Field(min_length=1, max_length=17_000_000)
    category: str = "knowledge"


class AdvisorHistoryItem(BaseModel):
    speaker: str = Field(default="unknown", max_length=40)
    text: str = Field(default="", max_length=3000)


class AdvisorSuggestRequest(BaseModel):
    customer_text: str = Field(min_length=1, max_length=6000)
    customer_original: str = Field(default="", max_length=6000)
    history: list[AdvisorHistoryItem] = Field(default_factory=list, max_length=40)
    meeting_context: str = Field(default="", max_length=6000)
    knowledge_context: str = Field(default="", max_length=12000)


class HotkeySettings(BaseModel):
    hotkey: str = "ctrl+alt+space"
    text_translate_hotkey: str = "f8"
    text_source_language: str = "vi"
    text_target_language: str = "en"
    microphone: str = "__default__"
    mode: str = "fast"
    source_language: str = "vi"
    target_language: str = "en"
    translate: bool = True
    screen_hotkey: str = "ctrl+alt+t"
    screen_read_hotkey: str = "ctrl+alt+r"
    screen_read_source_language: str = "auto"
    screen_read_target_language: str = "vi"
    screen_read_mode: str = "source"
    screen_read_output_device: str = Field(default="__default__", min_length=1, max_length=300)
    screen_read_voices: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_READ_VOICES))
    screen_source_language: str = "zh"
    screen_target_language: str = "vi"
    screen_processor: str = "cpu"
    screen_font_size: int = Field(default=14, ge=8, le=48)
    screen_text_color: str = Field(default="#ffffff", pattern=r"^#[0-9a-fA-F]{6}$")
    screen_background_color: str = Field(default="#040806", pattern=r"^#[0-9a-fA-F]{6}$")
    screen_continuous: bool = True
    screen_exit_hotkey: str = "esc"
    screen_refresh_seconds: float = Field(default=1.0, ge=0.25, le=10.0)
    screen_overlay_opacity: float = Field(default=0.92, ge=0.2, le=1.0)
    show_status_overlay: bool = True


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
        self.multilingual_tts: Any | None = None
        self.vietnamese_tts: Any | None = None
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

    def _tts_pipeline(self, language: str, voice: str = "") -> Any | None:
        """Return a Kokoro pipeline, sharing one GPU model across languages."""
        if language not in {"en", "zh"}:
            return None
        if "en" not in self.tts:
            from kokoro import KPipeline

            self.tts["en"] = KPipeline(lang_code="a", device=self.device)
        key = "en-gb" if language == "en" and voice.startswith("b") else language
        if key not in self.tts:
            from kokoro import KPipeline

            self.tts[key] = KPipeline(
                lang_code="z" if language == "zh" else "b" if key == "en-gb" else "a",
                model=self.tts["en"].model,
            )
        return self.tts[key]

    def _synthesize_speech(self, translation: str, language: str, voice: str) -> tuple[np.ndarray, int]:
        started = time.perf_counter()
        voice = resolve_voice(language, voice)
        voice_pack = local_voice_pack(language, voice) if voice else None
        if language == "vi":
            from backend.vietnamese_tts import enabled, VietnameseTTS
            if enabled():
                if self.vietnamese_tts is None:
                    self.vietnamese_tts = VietnameseTTS()
                audio, sample_rate = self.vietnamese_tts.synthesize(translation, voice)
                logging.getLogger("uvicorn.error").info(
                    "tts language=vi engine=vieneu-cpu voice=%s chars=%d generation_s=%.3f audio_s=%.3f",
                    voice, len(translation), time.perf_counter() - started, len(audio) / sample_rate,
                )
                return audio, sample_rate
        if language in {"vi", "ja", "ko"}:
            if self.multilingual_tts is None:
                from supertonic import TTS

                # Never fall back to the user profile (C:) or download during a call.
                model_dir = Path.cwd() / ".model-cache" / "supertonic3"
                self.multilingual_tts = TTS(model_dir=model_dir, auto_download=False, intra_op_num_threads=4)
            style = self.multilingual_tts.get_voice_style(voice if voice in {"M1", "F1"} else "M1")
            sample_rate = int(self.multilingual_tts.sample_rate)
            # Vietnamese needs enough context for natural phrasing. Very short
            # arbitrary fragments regressed our local round-trip tests.
            text_chunks = split_text(translation, 450 if language == "vi" else 120 if language == "ko" else 240)
            audio_chunks = []
            pause = np.zeros(round(sample_rate * 0.12), dtype=np.float32)
            for index, text_chunk in enumerate(text_chunks):
                waveform, _ = self.multilingual_tts.synthesize(
                    text_chunk, voice_style=style, lang=language, total_steps=8,
                    speed=1.08, silence_duration=0.12, max_chunk_length=450 if language == "vi" else 300,
                    verbose=False,
                )
                chunk = np.asarray(waveform, dtype=np.float32).reshape(-1)
                if not len(chunk) or not np.isfinite(chunk).all():
                    raise RuntimeError("Speech model produced empty or invalid audio")
                # Do not gate breaths/quiet consonants or truncate by predicted
                # duration: the vocoder's actual waveform is authoritative.
                if index:
                    audio_chunks.append(pause)
                audio_chunks.append(chunk)
            audio = np.concatenate(audio_chunks) if audio_chunks else np.empty(0, dtype=np.float32)
            logging.getLogger("uvicorn.error").info(
                "tts language=%s voice=%s chars=%d chunks=%d steps=8 generation_s=%.3f audio_s=%.3f",
                language, voice, len(translation), len(text_chunks), time.perf_counter() - started,
                len(audio) / sample_rate,
            )
            return audio, sample_rate

        pipeline = self._tts_pipeline(language, voice)
        if pipeline is None:
            return np.empty(0, dtype=np.float32), 24_000
        chunks = []
        for _, _, chunk in pipeline(translation, voice=str(voice_pack), speed=1.08):
            if torch.is_tensor(chunk):
                chunk = chunk.detach().cpu().numpy()
            chunks.append(np.asarray(chunk, dtype=np.float32))
        return np.concatenate(chunks) if chunks else np.empty(0, dtype=np.float32), 24_000

    def synthesize_speech(self, text: str, language: str, voice: str) -> tuple[np.ndarray, int]:
        with self.lock:
            return self._synthesize_speech(text, language, voice)

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
        choice = result["choices"][0]
        if choice.get("finish_reason") == "length":
            # A fluent-looking prefix is not a complete translation. Callers
            # must split/retry the source rather than speak a silently cut result.
            raise RuntimeError("Translation exceeded token budget; select a shorter passage or split it")
        content = choice["message"]["content"].strip()
        content = re.sub(r"^```(?:text)?\s*|\s*```$", "", content, flags=re.IGNORECASE)
        return content.strip().strip('"')

    def _translate(self, source: str, config: SessionConfig) -> str:
        glossary = config.glossary or []
        source_name = LANGUAGE_NAMES.get(config.source_language, config.source_language)
        target_name = LANGUAGE_NAMES.get(config.target_language, config.target_language)
        if config.source_language == config.target_language:
            return source
        if len(source) > 350:
            return " ".join(self._translate(piece, config) for piece in split_text(source, 300))
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
        max_tokens = min(900, max(64, len(source.split()) * 4 + len(source) * 2 + 32))
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

    def _translate_screen_lines(
        self,
        lines: list[str],
        source_language: str,
        target_language: str,
    ) -> list[str]:
        """Translate OCR lines as one batch while preserving positional mapping."""
        if source_language == target_language:
            return lines
        # Bound both input and output budgets. Also used by selected-text read:
        # a long paragraph must not fall back to a 220-token truncated prefix.
        if any(len(line) > 300 for line in lines) or sum(map(len, lines)) > 350:
            translated_lines = []
            for line in lines:
                pieces = split_text(line, 300)
                translated_lines.append(" ".join(
                    self._translate_screen_lines([piece], source_language, target_language)[0]
                    for piece in pieces
                ))
            return translated_lines
        source_name = LANGUAGE_NAMES.get(source_language, source_language)
        target_name = LANGUAGE_NAMES.get(target_language, target_language)
        prompt = (
            f"Translate every JSON array item from {source_name} to {target_name}. "
            "Keep the same item count and order. Each output item must contain only the natural "
            "translation of its matching input item. Preserve names, numbers, UI labels, and punctuation. "
            "Return one valid JSON array of strings only, without markdown or explanation.\n\n"
            f"Input: {json.dumps(lines, ensure_ascii=False)}"
        )
        max_tokens = min(900, max(96, sum(len(line) for line in lines) * 2 + 64))
        try:
            candidate = self._chat([{"role": "user", "content": prompt}], max_tokens=max_tokens)
        except RuntimeError:
            if len(lines) == 1 and len(lines[0]) > 80:
                pieces = split_text(lines[0], max(40, len(lines[0]) // 2))
                return [" ".join(self._translate_screen_lines([piece], source_language, target_language)[0] for piece in pieces)]
            raise
        match = re.search(r"\[[\s\S]*\]", candidate)
        if match:
            try:
                translated = json.loads(match.group(0))
                if (
                    isinstance(translated, list)
                    and len(translated) == len(lines)
                    and all(isinstance(item, str) and item.strip() for item in translated)
                ):
                    return [item.strip() for item in translated]
            except json.JSONDecodeError:
                pass

        # Rare model-format fallback. It is slower but keeps every overlay attached
        # to the correct OCR box instead of showing an ambiguous combined paragraph.
        config = SessionConfig(
            mode="fast",
            source_language=source_language,
            target_language=target_language,
            speak_translation=False,
            meeting_context="On-screen text from a video, livestream, game, or document.",
        )
        return [self._translate(line, config) for line in lines]

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

            waveform, sample_rate = self._synthesize_speech(translation, config.target_language, config.voice) if config.speak_translation else (np.empty(0, dtype=np.float32), 24_000)
            output = io.BytesIO()
            if len(waveform):
                sf.write(output, waveform, sample_rate, format="WAV", subtype="PCM_16")
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
screen_ocr = ScreenOCR(Path.cwd() / ".model-cache" / "rapidocr")
advisor = AdvisorEngine(Path.cwd())
video_dub = VideoDubManager(models, advisor)
system_audio_connection_lock = asyncio.Lock()
app = FastAPI(title="SpeakBridge Local Engine", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def video_dub_extension_cors(request: Request, call_next: Any) -> Response:
    """Allow the browser extension on video sites (TikTok, Douyin, YouTube, Bilibili, Coursera)
    to call /jobs* and /health via Chrome/Edge/CocCoc Private Network Access."""
    path = request.url.path
    is_dub_route = path.startswith("/jobs") or path == "/health"
    if is_dub_route and request.method == "OPTIONS":
        return Response(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "*",
                "Access-Control-Allow-Private-Network": "true",
            },
        )
    response = await call_next(request)
    if is_dub_route:
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "*"
        response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "device": models.device, "cuda": torch.cuda.is_available(), "translator": "hy-mt2" if models._llm_is_ready() else "loading", "asr_loaded_modes": list(models.asr), "engine_loaded": True}


@app.get("/advisor/config")
def advisor_config() -> dict[str, Any]:
    return {"ok": True, **advisor.public_config()}


@app.post("/advisor/config")
def save_advisor_config(request: AdvisorConfigRequest) -> dict[str, Any]:
    try:
        return {"ok": True, **advisor.save_config(request.model_dump())}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/advisor/test")
async def test_advisor_provider() -> dict[str, Any]:
    try:
        return await asyncio.to_thread(advisor.test_provider)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/advisor/documents")
def advisor_documents() -> dict[str, Any]:
    return {"ok": True, "documents": advisor.documents()}


@app.post("/advisor/documents")
async def upload_advisor_document(request: AdvisorDocumentRequest) -> dict[str, Any]:
    try:
        document = await asyncio.to_thread(advisor.add_document, request.filename, request.content_base64, request.category)
        return {"ok": True, "document": document}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/advisor/documents/{document_id}")
def delete_advisor_document(document_id: str) -> dict[str, Any]:
    if not advisor.delete_document(document_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy tài liệu")
    return {"ok": True}


@app.post("/advisor/suggest")
async def advisor_suggest(request: AdvisorSuggestRequest) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            advisor.suggest,
            request.customer_text,
            request.customer_original,
            [item.model_dump() for item in request.history],
            request.meeting_context,
            request.knowledge_context,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/ocr/status")
def ocr_status() -> dict[str, Any]:
    try:
        import rapidocr

        installed = True
        version = getattr(rapidocr, "__version__", "installed")
    except ImportError:
        installed = False
        version = ""
    return {
        "ok": True,
        "installed": installed,
        "version": version,
        "gpu_available": torch.cuda.is_available(),
        "processors": ["cpu", "gpu"],
    }


@app.post("/ocr/prepare/{processor}")
async def prepare_ocr(processor: str, language: str = "zh") -> dict[str, Any]:
    try:
        prepared = await asyncio.to_thread(screen_ocr.prepare, processor, language)
        return {"ok": True, **prepared}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/ocr/translate")
async def translate_screen(request: ScreenOCRRequest) -> dict[str, Any]:
    if request.source_language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported OCR source language")
    if request.target_language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported OCR target language")
    try:
        image_bytes = base64.b64decode(request.image_base64, validate=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid screenshot data") from exc
    if not 100 <= len(image_bytes) <= 8_000_000:
        raise HTTPException(status_code=413, detail="Screenshot must be between 100 bytes and 8 MB")

    started = time.perf_counter()
    try:
        result = await asyncio.to_thread(screen_ocr.recognize, image_bytes, request.processor, request.source_language)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"OCR lỗi: {exc}") from exc

    source = str(result["text"])
    normalized_source = re.sub(r"\s+", " ", source).strip().casefold()
    normalized_previous = re.sub(r"\s+", " ", request.previous_text).strip().casefold()
    unchanged = bool(source and normalized_source == normalized_previous)
    translation = ""
    translation_ms = 0
    if source and not unchanged:
        await asyncio.to_thread(models._wait_for_llm)
        translate_started = time.perf_counter()
        regions = list(result.get("regions") or ())[:24]
        translated_lines = await asyncio.to_thread(
            models._translate_screen_lines,
            [str(region["source"]) for region in regions],
            request.source_language,
            request.target_language,
        ) if regions else []
        for region, translated_line in zip(regions, translated_lines):
            region["translation"] = translated_line
        result["regions"] = regions
        translation = "\n".join(translated_lines)
        translation_ms = round((time.perf_counter() - translate_started) * 1000)

    return {
        "ok": True,
        **result,
        "source": source,
        "translation": translation,
        "source_language": request.source_language,
        "target_language": request.target_language,
        "unchanged": unchanged,
        "translation_ms": translation_ms,
        "latency_ms": round((time.perf_counter() - started) * 1000),
    }


@app.post("/ocr/read")
async def read_screen_text(request: ScreenReadRequest) -> dict[str, Any]:
    """OCR one selected region and return a WAV for local Windows playback."""
    if request.source_language not in SCREEN_READ_LANGUAGES or request.target_language not in SCREEN_READ_LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported OCR or speech language")
    if request.processor not in {"cpu", "gpu"} or request.read_mode not in {"source", "translation"}:
        raise HTTPException(status_code=400, detail="Invalid screen reader settings")
    try:
        image_bytes = base64.b64decode(request.image_base64, validate=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid screenshot data") from exc
    if not 100 <= len(image_bytes) <= 8_000_000:
        raise HTTPException(status_code=413, detail="Screenshot must be between 100 bytes and 8 MB")

    try:
        result = await asyncio.to_thread(screen_ocr.recognize, image_bytes, request.processor, request.source_language)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Screen OCR failed: {exc}") from exc
    lines = [str(region["source"]).strip() for region in result.get("regions", []) if str(region.get("source", "")).strip()][:20]
    if not lines:
        lines = [line.strip() for line in str(result.get("text", "")).splitlines() if line.strip()][:20]
    remaining = 900
    bounded_lines: list[str] = []
    for line in lines:
        if remaining <= 0:
            break
        bounded = line[:remaining]
        if bounded:
            bounded_lines.append(bounded)
            remaining -= len(bounded)
    lines = bounded_lines
    source = "\n".join(lines)
    if not source:
        raise HTTPException(status_code=422, detail="No readable text found in the selected region")

    spoken_language = request.source_language
    spoken_text = source
    if request.read_mode == "translation" and request.source_language != request.target_language:
        try:
            await asyncio.to_thread(models._wait_for_llm)
            translated = await asyncio.to_thread(
                models._translate_screen_lines, lines,
                request.source_language, request.target_language,
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Screen translation failed: {exc}") from exc
        spoken_text = "\n".join(translated)[:1200]
        if not spoken_text.strip() or models._is_bad_translation(source, spoken_text):
            raise HTTPException(status_code=422, detail="Screen translation was empty or unreliable")
        spoken_language = request.target_language

    voice = "zm_yunxi" if spoken_language == "zh" else "am_adam" if spoken_language == "en" else "F1"
    try:
        waveform, sample_rate = await asyncio.to_thread(
            models.synthesize_speech, spoken_text, spoken_language, voice,
        )
        if not len(waveform):
            raise RuntimeError("Speech model produced no audio")
        output = io.BytesIO()
        sf.write(output, waveform, sample_rate, format="WAV", subtype="PCM_16")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Screen speech failed: {exc}") from exc
    return {
        "ok": True,
        "source": source,
        "text": spoken_text,
        "spoken_language": spoken_language,
        "processor": result["processor"],
        "audio_base64": base64.b64encode(output.getvalue()).decode("ascii"),
    }


def detect_selected_text_language(text: str) -> str:
    """Best-effort script detection for five locally supported speech voices."""
    if re.search(r"[\uac00-\ud7af]", text):
        return "ko"
    if re.search(r"[\u3040-\u30ff]", text):
        return "ja"
    if re.search(r"[\u3400-\u9fff]", text):
        return "zh"
    if re.search(r"[ăâđêôơưĂÂĐÊÔƠƯàáạảãầấậẩẫằắặẳẵèéẹẻẽềếệểễìíịỉĩòóọỏõồốộổỗờớợởỡùúụủũừứựửữỳýỵỷỹ]", text):
        return "vi"
    return "en"


@app.post("/text/read")
async def read_selected_text(request: SelectedTextReadRequest) -> dict[str, Any]:
    """Speak only explicitly selected, copyable text; no screen capture or OCR."""
    started = time.perf_counter()
    translation_seconds = 0.0
    source = request.text.strip()
    if not source:
        raise HTTPException(status_code=400, detail="No selected text")
    if request.source_language not in SCREEN_READ_LANGUAGES | {"auto"}:
        raise HTTPException(status_code=400, detail="Unsupported selected-text language")
    if request.target_language not in SCREEN_READ_LANGUAGES or request.read_mode not in {"source", "translation"}:
        raise HTTPException(status_code=400, detail="Invalid selected-text reader settings")
    try:
        voices = read_voice_choices(request.voices)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    source_language = detect_selected_text_language(source) if request.source_language == "auto" else request.source_language
    spoken_language = source_language
    spoken_text = source
    if request.read_mode == "translation" and source_language != request.target_language:
        try:
            await asyncio.to_thread(models._wait_for_llm)
            translated = await asyncio.to_thread(models._translate_screen_lines, [source], source_language, request.target_language)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Selected text translation failed: {exc}") from exc
        spoken_text = translated[0].strip() if translated else ""
        if not spoken_text or models._is_bad_translation(source, spoken_text):
            raise HTTPException(status_code=422, detail="Selected text translation was empty or unreliable")
        spoken_language = request.target_language
        translation_seconds = time.perf_counter() - started

    voice = voices[spoken_language]
    tts_started = time.perf_counter()
    try:
        waveform, sample_rate = await asyncio.to_thread(models.synthesize_speech, spoken_text, spoken_language, voice)
        if not len(waveform):
            raise RuntimeError("Speech model produced no audio")
        output = io.BytesIO()
        sf.write(output, waveform, sample_rate, format="WAV", subtype="PCM_16")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Selected text speech failed: {exc}") from exc
    timing = {"translation_seconds": round(translation_seconds, 3),
              "tts_seconds": round(time.perf_counter() - tts_started, 3),
              "audio_seconds": round(len(waveform) / sample_rate, 3)}
    logging.getLogger("uvicorn.error").info(
        "selected_read source_lang=%s spoken_lang=%s voice=%s source_chars=%d spoken_chars=%d translation_s=%.3f tts_s=%.3f audio_s=%.3f",
        source_language, spoken_language, voice, len(source), len(spoken_text),
        timing["translation_seconds"], timing["tts_seconds"], timing["audio_seconds"],
    )
    return {
        "ok": True,
        "source": source,
        "text": spoken_text,
        "source_language": source_language,
        "spoken_language": spoken_language,
        "voice": voice,
        "timing": timing,
        "audio_base64": base64.b64encode(output.getvalue()).decode("ascii"),
    }


@app.get("/models/status")
def model_status() -> dict[str, Any]:
    from backend.model_inventory import inventory
    cache, assets = inventory()
    installed = {asset["name"] for asset in assets if asset["installed"]}
    from backend.vietnamese_tts import enabled
    vietnamese_ready = "VieNeu v3 Turbo" in installed if enabled() else "Supertonic 3" in installed
    return {"ok": True, "cache_root": str(cache), "assets": assets,
            "verified_languages": ["vi", "en", "zh"], "supported_languages": sorted(SUPPORTED_LANGUAGES),
            "tts_languages": (["en", "zh"] if "Kokoro-82M" in installed else []) +
                             (["ja", "ko"] if "Supertonic 3" in installed else []) +
                             (["vi"] if vietnamese_ready else [])}


@app.get("/tts/voices")
def voice_catalog() -> dict[str, Any]:
    languages = {}
    for language, voices in VOICES.items():
        options = []
        for voice, label in voices.items():
            try:
                local_voice_pack(language, voice)
                if language == "vi":
                    from backend.vietnamese_tts import enabled, voice_label
                    if enabled():
                        label = voice_label(voice)
                installed, error = True, ""
            except (OSError, RuntimeError, ValueError) as exc:
                installed, error = False, str(exc)
            options.append({"id": voice, "label": label, "installed": installed, "error": error})
        languages[language] = options
    return {"ok": True, "languages": languages}


@app.post("/tts/test")
async def test_voice(request: VoiceTestRequest) -> dict[str, Any]:
    if request.voice not in VOICES.get(request.language, {}):
        raise HTTPException(status_code=400, detail="Voice does not support the selected language")
    started = time.perf_counter()
    try:
        waveform, rate = await asyncio.to_thread(models.synthesize_speech, SAMPLES[request.language], request.language, request.voice)
        rms = float(np.sqrt(np.mean(waveform ** 2))) if len(waveform) else 0
        if not len(waveform) or not np.isfinite(waveform).all() or rms < 0.0001:
            raise RuntimeError("Speech model returned empty, invalid or silent audio")
        output = io.BytesIO()
        sf.write(output, waveform, rate, format="WAV", subtype="PCM_16")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"TTS {request.language}/{request.voice}: {exc}") from exc
    return {"ok": True, "language": request.language, "voice": request.voice,
            "text": SAMPLES[request.language], "duration_seconds": round(len(waveform) / rate, 2),
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "audio_base64": base64.b64encode(output.getvalue()).decode("ascii")}


@app.post("/models/open-folder")
def open_model_folder(request: dict[str, str]) -> dict[str, Any]:
    from backend.model_inventory import inventory
    _, assets = inventory()
    asset = next((item for item in assets if item["name"] == request.get("name")), None)
    if asset is None:
        raise HTTPException(status_code=400, detail="Unknown model")
    path = Path(asset["path"])
    folder = path if path.is_dir() else path.parent
    if not folder.is_dir():
        raise HTTPException(status_code=404, detail="Model folder does not exist")
    if os.name != "nt":
        raise HTTPException(status_code=501, detail="Open folder is available on Windows")
    try:
        os.startfile(str(folder))
    except OSError as exc:
        raise HTTPException(status_code=503, detail=f"Could not open model folder: {exc}") from exc
    return {"ok": True, "path": str(folder)}


@app.get("/hotkey/settings")
def hotkey_settings() -> dict[str, Any]:
    return {"ok": True, **load_hotkey_settings().model_dump()}


@app.get("/hotkey/status")
def hotkey_runtime_status() -> dict[str, Any]:
    try:
        payload = json.loads((Path.cwd() / ".run" / "hotkey-status.json").read_text(encoding="utf-8"))
        fresh = 0 <= time.time() - float(payload.get("updated_at", 0)) < 8
        return {**payload, "ok": True, "running": fresh and bool(payload.get("listener_alive"))}
    except (OSError, ValueError, TypeError):
        return {"ok": True, "running": False, "hotkeys": {}, "status": "Helper chưa chạy"}


@app.post("/hotkey/settings")
def save_hotkey_settings(settings: HotkeySettings) -> dict[str, Any]:
    try:
        settings.screen_read_voices = read_voice_choices(settings.screen_read_voices)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if settings.source_language not in SUPPORTED_LANGUAGES | {"auto"}:
        raise HTTPException(status_code=400, detail="Unsupported source language")
    if settings.target_language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported target language")
    if settings.text_source_language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported text source language")
    if settings.text_target_language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported text target language")
    if settings.screen_source_language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported screen source language")
    if settings.screen_target_language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported screen target language")
    if settings.screen_read_source_language not in SCREEN_READ_LANGUAGES | {"auto"}:
        raise HTTPException(status_code=400, detail="Unsupported screen reader source language")
    if settings.screen_read_target_language not in SCREEN_READ_LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported screen reader voice language")
    if settings.screen_read_mode not in {"source", "translation"}:
        raise HTTPException(status_code=400, detail="Invalid screen reader mode")
    if settings.screen_processor not in {"cpu", "gpu"}:
        raise HTTPException(status_code=400, detail="Unsupported screen OCR processor")
    if settings.mode not in {"fast", "quality"}:
        raise HTTPException(status_code=400, detail="Unsupported mode")
    try:
        for field_name in ("hotkey", "text_translate_hotkey", "screen_hotkey", "screen_read_hotkey", "screen_exit_hotkey"):
            setattr(settings, field_name, normalize_shortcut(getattr(settings, field_name)))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    normalized_hotkey = settings.hotkey.strip().lower()
    if not normalized_hotkey or len(normalized_hotkey) > 80:
        raise HTTPException(status_code=400, detail="Invalid hotkey")
    normalized_text_hotkey = settings.text_translate_hotkey.strip().lower()
    if not normalized_text_hotkey or len(normalized_text_hotkey) > 80:
        raise HTTPException(status_code=400, detail="Invalid text translation hotkey")
    normalized_screen_hotkey = settings.screen_hotkey.strip().lower()
    if not normalized_screen_hotkey or len(normalized_screen_hotkey) > 80:
        raise HTTPException(status_code=400, detail="Invalid screen hotkey")
    normalized_screen_read_hotkey = settings.screen_read_hotkey.strip().lower()
    if not normalized_screen_read_hotkey or len(normalized_screen_read_hotkey) > 80:
        raise HTTPException(status_code=400, detail="Invalid screen reader hotkey")
    if len({normalized_hotkey, normalized_text_hotkey, normalized_screen_hotkey, normalized_screen_read_hotkey}) != 4:
        raise HTTPException(status_code=400, detail="Voice, text, screen translation and screen reader hotkeys must be different")
    normalized_screen_exit_hotkey = settings.screen_exit_hotkey.strip().lower()
    if not normalized_screen_exit_hotkey or len(normalized_screen_exit_hotkey) > 80:
        raise HTTPException(status_code=400, detail="Invalid screen exit hotkey")
    if normalized_screen_exit_hotkey in {normalized_hotkey, normalized_text_hotkey, normalized_screen_hotkey, normalized_screen_read_hotkey}:
        raise HTTPException(status_code=400, detail="Screen exit hotkey must be different")
    try:
        for shortcut in (normalized_hotkey, normalized_text_hotkey, normalized_screen_hotkey, normalized_screen_read_hotkey, normalized_screen_exit_hotkey):
            parse_shortcut(shortcut)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    settings.hotkey = normalized_hotkey
    settings.text_translate_hotkey = normalized_text_hotkey
    settings.screen_hotkey = normalized_screen_hotkey
    settings.screen_read_hotkey = normalized_screen_read_hotkey
    settings.screen_exit_hotkey = normalized_screen_exit_hotkey
    with HOTKEY_SETTINGS_LOCK:
        HOTKEY_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = HOTKEY_CONFIG_PATH.with_suffix(".tmp")
        temporary.write_text(json.dumps(settings.model_dump(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, HOTKEY_CONFIG_PATH)
    return {"ok": True, **settings.model_dump()}


@app.patch("/hotkey/settings")
def patch_hotkey_settings(changes: dict[str, Any]) -> dict[str, Any]:
    """Save only the current feature, preserving other features' persisted settings."""
    unknown = changes.keys() - HotkeySettings.model_fields.keys()
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown settings: {', '.join(sorted(unknown))}")
    with HOTKEY_SETTINGS_LOCK:
        try:
            merged = HotkeySettings.model_validate({**load_hotkey_settings().model_dump(), **changes})
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return save_hotkey_settings(merged)


@app.post("/text/translate")
async def translate_typed_text(request: TextTranslationRequest) -> dict[str, Any]:
    source = request.text.strip()
    if not source:
        raise HTTPException(status_code=400, detail="Text is empty")
    if request.source_language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported source language")
    if request.target_language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported target language")
    if request.mode not in {"fast", "quality"}:
        raise HTTPException(status_code=400, detail="Unsupported mode")
    if request.source_language == request.target_language:
        return {"ok": True, "source": source, "text": source}

    config = SessionConfig(
        mode=request.mode,
        source_language=request.source_language,
        target_language=request.target_language,
        speak_translation=False,
    )
    try:
        await asyncio.to_thread(models._wait_for_llm)
        translated = await asyncio.to_thread(models._translate, source, config)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Text translation failed: {exc}") from exc
    translated = translated.strip()
    if not translated or models._is_bad_translation(source, translated):
        raise HTTPException(status_code=422, detail="Translation was empty or unreliable")
    return {
        "ok": True,
        "source": source,
        "text": translated,
        "source_language": request.source_language,
        "target_language": request.target_language,
    }


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


class OutputTestRequest(BaseModel):
    output_device: str = Field(default="__default__", min_length=1, max_length=300)
    language: str = Field(default="en", max_length=10)
    voice: str = Field(default="", max_length=50)


@app.post("/hotkey/test-output")
async def test_hotkey_output(request: OutputTestRequest) -> dict[str, Any]:
    from desktop.speech_output import output_test_wav, play_wav

    audio = output_test_wav()
    if request.voice:
        sample = await test_voice(VoiceTestRequest(language=request.language, voice=request.voice))
        audio = base64.b64decode(sample["audio_base64"])
    try:
        device = await asyncio.to_thread(play_wav, audio, request.output_device)
        return {"ok": True, "output_device": device, "voice": request.voice}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
    if mode not in {"fast", "quality"}:
        raise HTTPException(status_code=400, detail="Mode must be fast or quality")
    try:
        await asyncio.to_thread(models.prepare, mode)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Cannot prepare {mode} on {models.device}: {exc}") from exc
    return {"ok": True, "mode": mode, "ready": True, "device": models.device,
            "asr_model": "large-v3" if mode == "quality" else "large-v3-turbo",
            "beam_size": 5 if mode == "quality" else 1}


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
                    requested_voice = str(payload.get("voice", "am_adam"))
                    config.voice = resolve_voice(config.target_language, requested_voice)
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
            last_meter_at = 0.0
            while not disconnect_task.done():
                chunk = await asyncio.to_thread(capture.get_audio, 0.25)
                if chunk is None:
                    if time.monotonic() - last_meter_at >= 0.2:
                        await send({"type": "level", "rms": 0.0})
                        last_meter_at = time.monotonic()
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
                if last_audio_at - last_meter_at >= 0.08:
                    rms = float(np.sqrt(np.mean(np.square(chunk)))) if len(chunk) else 0.0
                    await send({"type": "level", "rms": rms})
                    last_meter_at = last_audio_at
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


class NewDubJobRequest(BaseModel):
    urls: list[str]
    exact: bool = False
    duration: float = 0.0
    referer: str | None = None
    start: float = 0.0
    transcript: list[dict[str, Any]] | None = None
    transcript_lang: str | None = None
    source_language: str = "auto"
    target_language: str = "vi"
    voice: str = "F1"
    bgm_mode: str = "mute"
    translator_engine: str = "local"
    asr_mode: str = "fast"
    download_video: bool = False
    title: str = ""


class DubSeekRequest(BaseModel):
    t: float


@app.post("/jobs")
def create_dub_job(req: NewDubJobRequest) -> dict[str, Any]:
    if not req.urls:
        raise HTTPException(status_code=400, detail="Missing video URLs")
    job = video_dub.create_job(
        urls=req.urls,
        duration=req.duration,
        referer=req.referer,
        exact=req.exact,
        start=req.start,
        transcript=req.transcript,
        transcript_lang=req.transcript_lang,
        source_language=req.source_language,
        target_language=req.target_language,
        voice=req.voice,
        bgm_mode=req.bgm_mode,
        translator_engine=req.translator_engine,
        asr_mode=req.asr_mode,
        download_video=req.download_video,
        title=req.title,
    )
    return {"ok": True, **video_dub.serialize_job(job)}


@app.post("/jobs/upload")
async def upload_dub_job(request: Request) -> dict[str, Any]:
    filename = Path(request.headers.get("x-filename", "video.mp4")).name
    suffix = Path(filename).suffix.lower() or ".mp4"
    if suffix not in {".mp4", ".mkv", ".webm", ".mov", ".avi", ".mp3", ".wav", ".m4a"}:
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ định dạng MP4, MKV, WEBM, MOV, AVI, MP3, WAV, M4A")
    source_language = request.headers.get("x-source-language", "auto")
    target_language = request.headers.get("x-target-language", "vi")
    voice = request.headers.get("x-voice", "F1")
    bgm_mode = request.headers.get("x-bgm-mode", "mute")
    translator_engine = request.headers.get("x-translator-engine", "local")
    asr_mode = request.headers.get("x-asr-mode", "fast")

    upload_dir = video_dub.s.workspace / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    target_path = upload_dir / f"{uuid.uuid4().hex[:8]}_{filename}"
    total_bytes = 0
    with target_path.open("wb") as f:
        async for chunk in request.stream():
            total_bytes += len(chunk)
            if total_bytes > 800_000_000:
                f.close()
                target_path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="File video vượt quá giới hạn 800 MB")
            f.write(chunk)
    if total_bytes < 512:
        target_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="File video rỗng hoặc không hợp lệ")

    job = video_dub.create_job(
        urls=[str(target_path)],
        local_video_path=target_path,
        source_language=source_language,
        target_language=target_language,
        voice=voice,
        bgm_mode=bgm_mode,
        translator_engine=translator_engine,
        asr_mode=asr_mode,
        download_video=False,
        title=filename,
    )
    return {"ok": True, **video_dub.serialize_job(job)}


@app.get("/jobs/active")
def get_active_dub_job() -> dict[str, Any]:
    job = video_dub.current
    if job is None:
        return {"ok": True, "active": False}
    return {"ok": True, "active": True, **video_dub.serialize_job(job)}


@app.post("/jobs/stop-all")
def stop_all_dub_jobs() -> dict[str, Any]:
    count = video_dub.stop_all()
    return {"ok": True, "cancelled": count}


@app.post("/jobs/cleanup")
def cleanup_dub_storage() -> dict[str, Any]:
    count = video_dub.stop_all()
    info = video_dub.cleanup_storage(keep_job_id=None)
    return {"ok": True, "cancelled": count, **info}


@app.post("/jobs/open-extension-folder")
def open_extension_folder() -> dict[str, Any]:
    import subprocess

    ext_dir = (Path.cwd() / "extension").resolve()
    if not ext_dir.is_dir():
        raise HTTPException(status_code=404, detail="Không tìm thấy thư mục extension")
    opened_browser = False
    if os.name == "nt":
        try:
            subprocess.run(["clip"], input=str(ext_dir).encode("utf-16le"), check=False, timeout=3)
        except Exception:
            pass
        try:
            opened_browser = open_extensions_page_via_cdp()
        except Exception:
            pass
        try:
            subprocess.Popen(["explorer.exe", str(ext_dir)])
        except Exception:
            try:
                os.startfile(str(ext_dir))
            except OSError:
                pass
    return {
        "ok": True,
        "path": str(ext_dir),
        "clipboard_copied": True,
        "opened_extensions_tab": opened_browser,
    }


@app.post("/jobs/inject-extension")
async def inject_extension_to_browser(request: dict[str, Any] | None = None) -> dict[str, Any]:
    open_url = str((request or {}).get("url") or "").strip() or None
    if not open_url and video_dub.current and video_dub.current.url.startswith("http"):
        cur_u = video_dub.current.url
        if any(d in cur_u for d in ("douyin.com", "tiktok.com", "youtube.com", "bilibili.com", "coursera.org")):
            open_url = cur_u
    try:
        return await asyncio.to_thread(inject_extension_via_cdp, open_url)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Không thể kích hoạt nút Thuyết minh trên Cốc Cốc: {exc}") from exc


@app.get("/jobs/{job_id}")
def get_dub_job_status(job_id: str) -> dict[str, Any]:
    job = video_dub.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown job")
    return video_dub.serialize_job(job)


@app.post("/jobs/{job_id}/seek")
def seek_dub_job(job_id: str, req: DubSeekRequest) -> dict[str, Any]:
    job = video_dub.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown job")
    job.pointer = next((c.index for c in job.chunks if c.start <= req.t < c.end), 0)
    return {"ok": True, "pointer": job.pointer}


@app.post("/jobs/{job_id}/stop")
@app.delete("/jobs/{job_id}")
def stop_dub_job(job_id: str) -> dict[str, Any]:
    if not video_dub.stop_job(job_id):
        return {"ok": False, "error": "unknown job"}
    job = video_dub.jobs.get(job_id)
    return {"ok": True, **(video_dub.serialize_job(job) if job else {"job_id": job_id, "state": "cancelled"})}


@app.get("/jobs/{job_id}/chunks/{index}.wav")
def get_dub_chunk_audio(job_id: str, index: int) -> Response:
    job = video_dub.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown job")
    with job.lock:
        data = job.audio.get(index)
    if data is None:
        raise HTTPException(status_code=404, detail="chunk not ready")
    return Response(data, media_type="audio/wav")


@app.get("/jobs/{job_id}/video")
def get_dub_source_video(job_id: str) -> FileResponse:
    job = video_dub.jobs.get(job_id)
    if job is None or job.video_path is None or not job.video_path.is_file():
        raise HTTPException(status_code=404, detail="Video file not available")
    return FileResponse(str(job.video_path), filename=job.video_path.name)


@app.get("/jobs/{job_id}/export")
async def export_dub_video(job_id: str) -> FileResponse:
    job = video_dub.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown job")
    try:
        out_path, media_type = await asyncio.to_thread(video_dub.export_dubbed_file, job)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Lỗi xuất file: {exc}") from exc
    ext = ".mp4" if media_type == "video/mp4" else ".wav"
    safe_title = re.sub(r"[^\w\-]+", "_", job.title)[:40] or job.id
    return FileResponse(str(out_path), media_type=media_type, filename=f"SpeakBridge_Dub_{safe_title}{ext}")


@app.get("/jobs/{job_id}/subs.srt")
def export_dub_srt(job_id: str) -> Response:
    job = video_dub.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown job")
    srt_content = video_dub.export_srt(job)
    safe_title = re.sub(r"[^\w\-]+", "_", job.title)[:40] or job.id
    return Response(
        content=srt_content.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="SpeakBridge_Sub_{safe_title}.srt"'},
    )
