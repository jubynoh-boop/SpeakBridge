"""Real-time / near-real-time chunked video dubbing & subtitling pipeline for SpeakBridge.

Combines the architecture of `anpc849/real-time-video-subs` (Silero VAD chunking,
read-ahead Whisper ASR, Story Bible context-aware translation, Demucs BGM separation,
VieNeu-TTS / local TTS slot-fitting via FFmpeg `atempo`, and smoothed envelope ducking)
with SpeakBridge's resident local models (Faster-Whisper, Hy-MT2-7B / Advisor LLM,
VieNeu v3 Turbo / Supertonic / Kokoro).

Exposes the exact HTTP contract expected by both:
1. The SpeakBridge Web UI ("Video Dub" tab)
2. The Chromium Browser Extension (`extension/` for TikTok, Douyin, YouTube, Bilibili, Coursera)
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf


@dataclass
class DubSettings:
    workspace: Path = field(default_factory=lambda: Path.cwd() / ".run" / "video_dub")
    demucs_model: str = "htdemucs"
    demucs_margin_sec: float = 1.0
    chunk_min_sec: float = 8.0
    chunk_target_sec: float = 12.0
    chunk_max_sec: float = 16.0
    mix_sr: int = 44100
    chars_per_sec: float = 18.0
    duck_gain: float = 0.32
    duck_gain_no_demucs: float = 0.18
    bgm_gain: float = 1.0
    tts_gain: float = 1.4
    context_pairs: int = 8
    story_lookahead_sec: float = 90.0
    bible_every: int = 3
    transcript_max_chars: int = 16000


@dataclass
class Chunk:
    index: int
    start: float
    end: float


@dataclass
class Seg:
    start: float
    end: float
    zh: str  # source text (kept as 'zh' for 100% browser extension compatibility)
    vi: str = ""  # translated text (kept as 'vi' for 100% browser extension compatibility)


def decode_audio(path: str | Path, sr: int, ch: int, input_args: list[str] | None = None) -> np.ndarray:
    cmd = [
        "ffmpeg", "-v", "error", *(input_args or []),
        "-i", str(path), "-vn", "-ac", str(ch), "-ar", str(sr), "-f", "f32le", "-",
    ]
    raw = subprocess.run(cmd, capture_output=True, check=True, timeout=180).stdout
    arr = np.frombuffer(raw, dtype=np.float32)
    return arr.reshape(-1, ch).copy() if ch > 1 else arr.copy()


def probe_duration(url: str, referer: str | None = None) -> float | None:
    """Duration of a URL that carries an audio stream; None for unreachable or video-only URLs."""
    base = ["ffprobe", "-v", "error"]
    if referer:
        base += ["-headers", f"Referer: {referer}\r\nUser-Agent: Mozilla/5.0\r\n"]
    try:
        audio = subprocess.run(
            base + ["-select_streams", "a", "-show_entries", "stream=codec_type", "-of", "csv=p=0", url],
            capture_output=True, text=True, timeout=20,
        ).stdout.strip()
        if not audio:
            return None
        out = subprocess.run(
            base + ["-show_entries", "format=duration", "-of", "default=nw=1:nk=1", url],
            capture_output=True, text=True, timeout=20,
        ).stdout.strip()
        return float(out)
    except Exception:
        return None


def normalize_page_url(url: str) -> str:
    """Normalize modal/feed URLs (e.g. Douyin modal_id=...) into canonical video URLs."""
    u = (url or "").strip()
    if "douyin.com" in u:
        m = re.search(r"[?&]modal_id=(\d+)", u)
        if m:
            return f"https://www.douyin.com/video/{m.group(1)}"
        m_note = re.search(r"douyin\.com/note/(\d+)", u)
        if m_note:
            return f"https://www.douyin.com/video/{m_note.group(1)}"
    return u


def ensure_coccoc_cdp(port: int = 9222) -> bool:
    """Ensure Cốc Cốc debug port 9222 is reachable, launching it if needed."""
    version_url = f"http://127.0.0.1:{port}/json/version"
    try:
        with urllib.request.urlopen(version_url, timeout=1.5) as resp:
            if resp.status == 200:
                return True
    except Exception:
        pass

    coccoc_exe = Path(r"C:\Program Files\CocCoc\Browser\Application\browser.exe")
    if not coccoc_exe.is_file():
        return False

    profile_dir = Path(os.environ.get("TEMP", str(Path.cwd() / ".model-cache" / "temp"))) / "coccoc-codex-debug"
    try:
        subprocess.Popen(
            [
                str(coccoc_exe),
                f"--user-data-dir={profile_dir}",
                "--remote-debugging-address=127.0.0.1",
                f"--remote-debugging-port={port}",
                "--remote-allow-origins=*",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(15):
            time.sleep(0.4)
            try:
                with urllib.request.urlopen(version_url, timeout=1.0) as resp:
                    if resp.status == 200:
                        return True
            except Exception:
                pass
    except Exception:
        pass
    return False


def resolve_media_via_cdp(
    url: str, cancel_event: threading.Event | None = None, port: int = 9222
) -> tuple[list[str], str, str]:
    """Use Cốc Cốc CDP port 9222 to resolve direct CDN video/audio streams from Douyin/TikTok/Bilibili."""
    import asyncio
    import websockets

    norm_url = normalize_page_url(url)
    if not ensure_coccoc_cdp(port):
        raise RuntimeError("Không kết nối được trình duyệt Cốc Cốc (CDP 9222) để giải mã link Douyin/TikTok.")

    referer = "https://www.douyin.com/" if "douyin.com" in norm_url else norm_url

    async def _extract() -> tuple[list[str], str]:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?about:blank", method="PUT")
        with urllib.request.urlopen(req, timeout=5) as resp:
            tab = json.loads(resp.read().decode("utf-8"))
        tid = tab["id"]
        ws_url = tab["webSocketDebuggerUrl"]
        media_urls: list[str] = []
        title = ""
        try:
            async with websockets.connect(ws_url, max_size=10_000_000) as ws:
                await ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
                await ws.send(json.dumps({"id": 2, "method": "Page.enable"}))
                await ws.send(json.dumps({"id": 3, "method": "Page.navigate", "params": {"url": norm_url}}))
                t0 = time.time()
                while time.time() - t0 < 7.5:
                    if cancel_event and cancel_event.is_set():
                        break
                    try:
                        raw_msg = await asyncio.wait_for(ws.recv(), timeout=0.25)
                        msg = json.loads(raw_msg)
                        if msg.get("method") == "Network.responseReceived":
                            r_info = msg.get("params", {}).get("response", {})
                            u = str(r_info.get("url") or "")
                            mime = str(r_info.get("mimeType") or "").lower()
                            if (
                                any(k in u for k in ("douyinvod", "bytevod", "zjcdn", "/video/tos/", "bilivideo", "googlevideo"))
                                or mime.startswith("video/")
                                or mime.startswith("audio/")
                            ) and not any(ext in u for ext in (".js", ".css", ".png", ".jpg", ".webp", ".svg")):
                                if u not in media_urls:
                                    media_urls.append(u)
                    except asyncio.TimeoutError:
                        pass
                    if len(media_urls) >= 2 and time.time() - t0 >= 2.2:
                        break

                await ws.send(
                    json.dumps({
                        "id": 99,
                        "method": "Runtime.evaluate",
                        "params": {"expression": "document.title || ''", "returnByValue": True},
                    })
                )
                for _ in range(8):
                    try:
                        raw_msg = await asyncio.wait_for(ws.recv(), timeout=0.2)
                        msg = json.loads(raw_msg)
                        if msg.get("id") == 99:
                            title = str(msg.get("result", {}).get("result", {}).get("value") or "").strip()
                            break
                    except asyncio.TimeoutError:
                        break
        finally:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/json/close/{tid}", timeout=3).read()
            except Exception:
                pass
        return media_urls, title

    urls, page_title = asyncio.run(_extract())
    if not urls:
        raise RuntimeError("Không bắt được luồng phát video từ trang này (có thể video yêu cầu đăng nhập hoặc captcha).")
    return urls, page_title, referer


def download_from_cdp_urls(
    media_urls: list[str], referer: str, work: Path, need_video: bool
) -> Path:
    """Download and mux video + audio streams captured via CDP into source.mp4 or source.wav."""
    hdr = f"Referer: {referer}\r\nUser-Agent: Mozilla/5.0\r\n"
    audio_url: str | None = None
    video_url: str | None = None

    for u in media_urls:
        if audio_url is None and probe_duration(u, referer) is not None:
            audio_url = u
        elif video_url is None:
            video_url = u

    if audio_url is None:
        audio_url = media_urls[0]
    if video_url is None:
        video_url = audio_url

    out_mp4 = work / "source.mp4"
    if need_video:
        try:
            if video_url != audio_url:
                cmd = [
                    "ffmpeg", "-v", "error", "-y",
                    "-headers", hdr, "-i", video_url,
                    "-headers", hdr, "-i", audio_url,
                    "-map", "0:v:0", "-map", "1:a:0",
                    "-c", "copy", "-shortest", str(out_mp4),
                ]
            else:
                cmd = [
                    "ffmpeg", "-v", "error", "-y",
                    "-headers", hdr, "-i", audio_url,
                    "-c", "copy", str(out_mp4),
                ]
            subprocess.run(cmd, capture_output=True, check=True, timeout=180)
            if out_mp4.is_file() and out_mp4.stat().st_size > 1024:
                return out_mp4
        except Exception:
            pass

    out_wav = work / "source.wav"
    cmd_wav = [
        "ffmpeg", "-v", "error", "-y",
        "-headers", hdr, "-i", audio_url,
        "-vn", "-ac", "2", "-ar", "44100", str(out_wav),
    ]
    subprocess.run(cmd_wav, capture_output=True, check=True, timeout=180)
    return out_wav


def open_extensions_page_via_cdp(port: int = 9222) -> bool:
    """Open chrome://extensions in Cốc Cốc via CDP WebSocket Page.navigate and bring window to front."""
    import asyncio
    import websockets

    if not ensure_coccoc_cdp(port):
        return False

    async def _nav() -> bool:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?about:blank", method="PUT")
        with urllib.request.urlopen(req, timeout=4) as resp:
            tab = json.loads(resp.read().decode("utf-8"))
        ws_url = tab.get("webSocketDebuggerUrl")
        if not ws_url:
            return False
        async with websockets.connect(ws_url, max_size=4_000_000) as ws:
            await ws.send(json.dumps({"id": 1, "method": "Page.enable"}))
            await ws.send(json.dumps({"id": 2, "method": "Page.bringToFront"}))
            await ws.send(json.dumps({"id": 3, "method": "Page.navigate", "params": {"url": "chrome://extensions"}}))
            await asyncio.sleep(0.25)
        return True

    try:
        return asyncio.run(_nav())
    except Exception:
        return False


def inject_extension_via_cdp(open_url: str | None = None, port: int = 9222) -> dict[str, Any]:
    """Inject extension/page_hook.js and extension/content.js into open Cốc Cốc video tabs via CDP 9222."""
    import asyncio
    import websockets

    ext_dir = (Path.cwd() / "extension").resolve()
    hook_js = (ext_dir / "page_hook.js").read_text(encoding="utf-8")
    content_js = (ext_dir / "content.js").read_text(encoding="utf-8")

    ensure_coccoc_cdp(port)

    if open_url:
        norm = normalize_page_url(open_url)
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?{norm}", method="PUT")
            urllib.request.urlopen(req, timeout=4).read()
            time.sleep(1.5)
        except Exception:
            pass

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=3) as resp:
        tabs = json.loads(resp.read().decode("utf-8"))

    target_domains = ("douyin.com", "tiktok.com", "youtube.com", "bilibili.com", "coursera.org")
    video_tabs = [
        t for t in tabs
        if t.get("type") == "page"
        and any(d in str(t.get("url") or "") for d in target_domains)
        and t.get("webSocketDebuggerUrl")
    ]

    highlight_js = """
    (() => {
      const btns = document.querySelectorAll('.rtdub-btn');
      btns.forEach((b) => {
        b.style.display = 'inline-flex';
        b.style.transform = 'scale(1.18)';
        b.style.boxShadow = '0 0 24px #ef4444, 0 0 12px #ffffff';
        setTimeout(() => { b.style.transform = ''; b.style.boxShadow = ''; }, 1800);
      });
      const st = document.querySelector('.rtdub-status');
      if (st) {
        st.textContent = '✅ Đã bật nút 🇻🇳 VI · Thuyết minh (góc trên bên trái video)!';
        st.style.display = 'block';
        st.style.left = '50%';
        st.style.top = '28px';
        st.style.transform = 'translateX(-50%)';
        setTimeout(() => { if (st.textContent.includes('Đã bật nút')) st.style.display = 'none'; }, 4000);
      }
    })();
    """

    async def _inject_all() -> list[str]:
        injected: list[str] = []
        for idx, t in enumerate(video_tabs):
            ws_url = t["webSocketDebuggerUrl"]
            try:
                async with websockets.connect(ws_url, max_size=10_000_000) as ws:
                    await ws.send(json.dumps({"id": 1, "method": "Page.enable"}))
                    if idx == 0:
                        await ws.send(json.dumps({"id": 2, "method": "Page.bringToFront"}))
                    await ws.send(
                        json.dumps({
                            "id": 3,
                            "method": "Page.addScriptToEvaluateOnNewDocument",
                            "params": {"source": hook_js + "\n;\n" + content_js},
                        })
                    )
                    await ws.send(
                        json.dumps({
                            "id": 4,
                            "method": "Runtime.evaluate",
                            "params": {"expression": hook_js + "\n;\n" + content_js + "\n;\n" + highlight_js},
                        })
                    )
                    await asyncio.sleep(0.2)
                    injected.append(str(t.get("title") or t.get("url") or "")[:80])
            except Exception:
                pass
        return injected

    injected_titles = asyncio.run(_inject_all()) if video_tabs else []
    return {
        "ok": True,
        "injected_count": len(injected_titles),
        "tabs": injected_titles,
    }


def pick_url(urls: list[str], duration: float, referer: str | None, exact: bool = False) -> str:
    if exact:
        for u in urls:
            d = probe_duration(u, referer)
            if d is not None:
                return u
        raise RuntimeError("Luồng video không có kênh âm thanh hoặc không truy cập được")
    best, best_err = None, 1e9
    for u in urls:
        d = probe_duration(u, referer)
        if d is None:
            continue
        err = abs(d - duration) if duration > 0 else 0.0
        if err < best_err:
            best, best_err = u, err
        if duration > 0 and err < 0.3:
            break
    if best is None:
        raise RuntimeError("Không tìm thấy URL media nào có âm thanh trong danh sách ứng viên")
    if duration > 0 and best_err > 2.5:
        raise RuntimeError(f"Không có URL nào khớp thời lượng video ({duration:.1f}s, lệch {best_err:.1f}s)")
    return best


def speech_timestamps(audio16k: np.ndarray) -> list[tuple[float, float]]:
    if not len(audio16k):
        return []
    try:
        import torch
        from silero_vad import get_speech_timestamps, load_silero_vad

        model = load_silero_vad(onnx=True)
        ts = get_speech_timestamps(
            torch.from_numpy(audio16k),
            model,
            sampling_rate=16000,
            min_silence_duration_ms=250,
            speech_pad_ms=100,
            return_seconds=True,
        )
        return [(float(t["start"]), float(t["end"])) for t in ts]
    except Exception:
        duration = len(audio16k) / 16000.0
        return [(0.0, duration)] if duration > 0 else []


def plan_chunks(duration: float, speech: list[tuple[float, float]], s: DubSettings) -> list[Chunk]:
    gaps = [(speech[i][1], speech[i + 1][0]) for i in range(len(speech) - 1)]
    chunks: list[Chunk] = []
    start = 0.0
    while start < duration - 1e-3:
        if duration - start <= s.chunk_max_sec:
            chunks.append(Chunk(len(chunks), round(start, 3), round(duration, 3)))
            break
        lo, hi = start + s.chunk_min_sec, start + s.chunk_max_sec
        cands = [(g1 - g0, (g0 + g1) / 2) for g0, g1 in gaps if lo <= (g0 + g1) / 2 <= hi]
        if cands:
            cut = max(cands, key=lambda c: (c[0] > 0.4, -abs(c[1] - start - s.chunk_target_sec), c[0]))[1]
        else:
            cut = hi
        chunks.append(Chunk(len(chunks), round(start, 3), round(cut, 3)))
        start = cut
    return chunks


class DemucsSeparator:
    """Optional Demucs vocal stripper with automatic fallback to original stereo bed."""

    def __init__(self, s: DubSettings) -> None:
        self.s = s
        self._model: Any | None = None
        self._sources: list[str] = []
        self._sr: int = s.mix_sr
        self._lock = threading.Lock()
        self._failed = False

    def _ensure_loaded(self) -> bool:
        if self._model is not None:
            return True
        if self._failed:
            return False
        with self._lock:
            if self._model is not None:
                return True
            if self._failed:
                return False
            try:
                import torch
                from demucs.pretrained import get_model

                device = "cuda" if torch.cuda.is_available() else "cpu"
                model = get_model(self.s.demucs_model)
                model = model.to(device).eval()
                self._model = model
                self._sources = list(model.sources)
                self._sr = int(model.samplerate)
                return True
            except Exception as exc:
                print(f"[video_dub] Demucs unavailable, falling back to fast ducking: {exc}", flush=True)
                self._failed = True
                return False

    def bgm(self, audio: np.ndarray, start: float, end: float, mode: str = "mute") -> tuple[np.ndarray, bool]:
        """Returns (stereo_bgm_chunk, used_demucs)."""
        sr = self.s.mix_sr
        a, b = int(start * sr), int(end * sr)
        n_len = max(0, b - a)
        if mode in ("mute", "none", "off"):
            return np.zeros((n_len, 2), dtype=np.float32), False

        raw_slice = audio[max(0, a) : min(len(audio), b)]
        if len(raw_slice) < n_len:
            pad = np.zeros((n_len - len(raw_slice), 2), dtype=np.float32)
            raw_slice = np.vstack([raw_slice, pad]) if len(raw_slice) else pad

        if mode == "duck":
            # Keep raw unseparated audio at a very low bed (10%) so original vocals never overpower or play at 100% in gaps
            return (raw_slice * 0.10).astype(np.float32), False

        if mode != "demucs" or not self._ensure_loaded():
            return np.zeros((n_len, 2), dtype=np.float32), False

        try:
            import torch
            from demucs.apply import apply_model

            device = "cuda" if torch.cuda.is_available() else "cpu"
            m = int(self.s.demucs_margin_sec * sr)
            lo, hi = max(0, a - m), min(len(audio), b + m)
            x = torch.from_numpy(audio[lo:hi].T.copy())
            ref = x.mean(0)
            std = ref.std() + 1e-8
            x_norm = (x - ref.mean()) / std
            with torch.no_grad():
                y = apply_model(self._model, x_norm[None].to(device), shifts=0, split=True, overlap=0.1, device=device)[0]
            keep = [i for i, n in enumerate(self._sources) if n != "vocals"]
            y_bgm = y[keep].sum(0) * std.to(device) + ref.mean().to(device)
            y_np = y_bgm.cpu().numpy().T
            cropped = y_np[a - lo : a - lo + n_len].astype(np.float32)
            if len(cropped) == n_len:
                return cropped, True
            return np.zeros((n_len, 2), dtype=np.float32), False
        except Exception as exc:
            print(f"[video_dub] Demucs chunk error, silencing raw vocals: {exc}", flush=True)
            return np.zeros((n_len, 2), dtype=np.float32), False


def load_fitted_waveform(
    waveform: np.ndarray, sample_rate: int, slot: float, target_sr: int
) -> tuple[np.ndarray, float]:
    """Trim leading/trailing silence and fit a TTS mono waveform into `slot` seconds using FFmpeg `atempo`."""
    if not len(waveform):
        return np.zeros(0, dtype=np.float32), 1.0
    # Trim leading & trailing silence so TTS starts immediately at segment timestamp
    active = np.flatnonzero(np.abs(waveform) > 0.006)
    if len(active) > 0:
        pad = int(0.012 * sample_rate)
        lo = max(0, int(active[0]) - pad)
        hi = min(len(waveform), int(active[-1]) + pad)
        waveform = waveform[lo:hi]
    if not len(waveform):
        return np.zeros(0, dtype=np.float32), 1.0
    dur = len(waveform) / float(sample_rate)
    tempo = max(1.0, dur / max(slot, 0.25))
    buf = io.BytesIO()
    sf.write(buf, waveform, sample_rate, format="WAV", subtype="PCM_16")
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", "pipe:0"]
    if tempo > 1.01:
        chain, f = [], min(tempo, 3.2)  # cap extreme speedups at 3.2x for intelligibility
        while f > 2.0:
            chain.append(2.0)
            f /= 2.0
        chain.append(f)
        cmd += ["-filter:a", ",".join(f"atempo={v:.6f}" for v in chain)]
    cmd += ["-ac", "1", "-ar", str(target_sr), "-f", "f32le", "-"]
    proc = subprocess.run(cmd, input=buf.getvalue(), capture_output=True, check=True, timeout=30)
    return np.frombuffer(proc.stdout, dtype=np.float32).copy(), tempo


def mix_chunk(
    bgm: np.ndarray,
    clips: list[tuple[float, np.ndarray]],
    s: DubSettings,
    used_demucs: bool = False,
) -> np.ndarray:
    """Mix mono voiceover clips onto stereo BGM with smoothed envelope ducking."""
    sr, n = s.mix_sr, len(bgm)
    if n == 0:
        return np.zeros((0, 2), dtype=np.float32)
    voice = np.zeros(n, dtype=np.float32)
    for off, clip in clips:
        a = max(0, int(off * sr))
        b = min(n, a + len(clip))
        if a < b:
            voice[a:b] += clip[: b - a]
    env = (np.abs(voice) > 0.008).astype(np.float32)
    k = max(1, int(0.15 * sr))
    env = np.convolve(env, np.ones(k, dtype=np.float32) / k, mode="same").clip(0.0, 1.0)
    duck_target = s.duck_gain if used_demucs else s.duck_gain_no_demucs
    gain = 1.0 - env * (1.0 - duck_target)
    out = bgm * (s.bgm_gain * gain)[:, None] + (voice * s.tts_gain)[:, None]
    return np.clip(out, -1.0, 1.0).astype(np.float32)


UNDERSTAND_SYSTEM = """Bạn là biên tập viên kịch bản và thuật ngữ chuyên nghiệp. Bạn nhận TRANSCRIPT (có mốc thời gian) của một video sắp được thuyết minh, và lập STORY BIBLE / BẢNG THUẬT NGỮ để dịch nhất quán.

Trả về DUY NHẤT một JSON object hợp lệ (không Markdown):
{
  "synopsis": "tóm tắt nội dung (tối đa 60 từ)",
  "genre_tone": "thể loại và giọng điệu (tối đa 15 từ)",
  "characters": [{"zh": "tên/vai gốc", "vi": "tên/cách gọi khi dịch", "gender": "nam|nữ|?", "role": "vai trò", "calls": "cách xưng hô"}],
  "terminology": {"thuật ngữ gốc": "cách dịch"},
  "asr_fixes": {"từ nghe nhầm": "từ đúng"}
}"""

TRANSLATE_SYSTEM = """Bạn là dịch giả lồng tiếng chuyên nghiệp, dịch lời thoại video sang ngôn ngữ đích tự nhiên, trôi chảy, súc tích để máy đọc to (TTS) khớp khung thời gian.
Quy tắc:
1. Bám sát STORY BIBLE và ngữ cảnh các câu trước.
2. Mỗi câu dịch phải trọn nghĩa, khẩu ngữ tự nhiên, không vượt quá max_chars.
3. Không kết thúc câu bằng dấu phẩy hay hai chấm.
4. Chỉ trả về JSON hợp lệ, không Markdown: {"items":[{"id":0,"vi":"..."}]}"""


def _extract_json_obj(content: str) -> dict[str, Any]:
    raw = (content or "").strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    idx = raw.find("{")
    if idx < 0:
        raise ValueError("No JSON object found")
    return json.JSONDecoder().raw_decode(raw[idx:])[0]


def _clean_line(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip().strip('"“”')
    text = re.sub(r"[,;:，；：、\s]+$", "", text)
    if text and text[-1].isalnum():
        text += "."
    return text


class VideoTranslator:
    """Translates video chunks using either SpeakBridge's Local Hy-MT2-7B or Advisor/OpenRouter LLM with Story Bible."""

    def __init__(
        self,
        s: DubSettings,
        models: Any,
        advisor: Any,
        source_language: str = "auto",
        target_language: str = "vi",
        engine_mode: str = "local",
    ) -> None:
        self.s = s
        self.models = models
        self.advisor = advisor
        self.source_language = source_language
        self.target_language = target_language
        self.engine_mode = engine_mode  # "local" (Hy-MT2) or "llm" (Advisor/OpenAI-compatible)
        self.history: list[tuple[str, str]] = []
        self._lock = threading.Lock()
        self.bible: dict[str, Any] = {}
        self._bible_text = "[STORY BIBLE]\n(chưa có)\n[HẾT STORY BIBLE]"
        self._transcript_text = ""

    def _call_external_llm(self, messages: list[dict[str, str]], max_tokens: int = 2500) -> str | None:
        cfg = self.advisor.config() if self.advisor else {}
        base_url = os.environ.get("TRANSLATION_BASE_URL", "").strip() or str(cfg.get("base_url", "")).strip()
        api_key = os.environ.get("OPENAI_API_KEY", "").strip() or str(cfg.get("api_key", "")).strip() or "dummy"
        model = os.environ.get("TRANSLATION_MODEL", "").strip() or str(cfg.get("model", "")).strip() or "auto"
        if not base_url:
            return None
        url = f"{base_url.rstrip('/')}/chat/completions"
        payload = json.dumps({
            "model": model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": max_tokens,
        }).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return str(data["choices"][0]["message"]["content"]).strip()

    def understand(self, lines: list[tuple[float, str]], complete: bool) -> None:
        if not lines:
            return
        body, used = [], 0
        for start, zh in lines:
            row = f"[{start:.1f}s] {zh}"
            if used + len(row) > self.s.transcript_max_chars:
                break
            body.append(row)
            used += len(row) + 1
        note = "(toàn bộ video)" if complete and len(body) == len(lines) else f"(mới đến câu {len(body)}/{len(lines)})"
        transcript_msg = f"[TRANSCRIPT {note}]\n" + "\n".join(body) + "\n[HẾT TRANSCRIPT]"

        with self._lock:
            self._transcript_text = transcript_msg

        if self.engine_mode != "llm":
            # Build a lightweight summary bible locally so UI can still inspect video context
            sample_lines = [zh for _, zh in lines[:12]]
            with self._lock:
                self.bible = {
                    "synopsis": " · ".join(sample_lines)[:240],
                    "genre_tone": "Thuyết minh trực tiếp qua Hy-MT2 Local",
                    "characters": [],
                    "terminology": {},
                    "asr_fixes": {},
                }
            return

        messages = [
            {"role": "system", "content": UNDERSTAND_SYSTEM},
            {"role": "user", "content": transcript_msg},
        ]
        for _ in range(2):
            try:
                raw = self._call_external_llm(messages, max_tokens=2000)
                if not raw:
                    break
                parsed = _extract_json_obj(raw)
                bible = {
                    "synopsis": str(parsed.get("synopsis") or "").strip(),
                    "genre_tone": str(parsed.get("genre_tone") or "").strip(),
                    "characters": [c for c in (parsed.get("characters") or []) if isinstance(c, dict)][:15],
                    "terminology": dict(list((parsed.get("terminology") or {}).items())[:40])
                    if isinstance(parsed.get("terminology"), dict) else {},
                    "asr_fixes": dict(list((parsed.get("asr_fixes") or {}).items())[:30])
                    if isinstance(parsed.get("asr_fixes"), dict) else {},
                }
                with self._lock:
                    self.bible = bible
                    self._bible_text = "[STORY BIBLE]\n" + json.dumps(bible, ensure_ascii=False) + "\n[HẾT STORY BIBLE]"
                break
            except Exception as exc:
                print(f"[video_dub] Story bible LLM retry: {exc}", flush=True)

    def translate(self, segs: list[Seg], slots: list[float], effective_source_lang: str) -> None:
        if not segs:
            return
        if all(bool(g.vi) for g in segs):
            for g in segs:
                self.history.append((g.zh, g.vi))
            return
        if effective_source_lang == self.target_language:
            for g in segs:
                g.vi = _clean_line(g.zh)
                self.history.append((g.zh, g.vi))
            return

        # 1. Try Story-Bible LLM if selected
        if self.engine_mode == "llm":
            ctx = self.history[-self.s.context_pairs :]
            req = {
                "target_language": self.target_language,
                "previous_lines": [{"zh": z, "vi": v} for z, v in ctx],
                "translate": [
                    {"id": i, "zh": g.zh, "max_chars": max(12, int(slots[i] * self.s.chars_per_sec))}
                    for i, g in enumerate(segs)
                ],
            }
            with self._lock:
                bible_text, transcript_text = self._bible_text, self._transcript_text
            messages = [
                {"role": "system", "content": TRANSLATE_SYSTEM},
                {"role": "user", "content": bible_text},
            ]
            if transcript_text:
                messages.append({"role": "user", "content": transcript_text})
            messages.append({"role": "user", "content": json.dumps(req, ensure_ascii=False)})
            for _ in range(2):
                try:
                    raw = self._call_external_llm(messages, max_tokens=2500)
                    if not raw:
                        break
                    data = _extract_json_obj(raw)
                    result = {
                        int(item["id"]): str(item["vi"]).strip()
                        for item in data.get("items", [])
                        if str(item.get("vi", "")).strip()
                    }
                    if result:
                        for i, g in enumerate(segs):
                            if i in result:
                                g.vi = _clean_line(result[i])
                                self.history.append((g.zh, g.vi))
                        if all(bool(g.vi) for g in segs):
                            return
                except Exception as exc:
                    print(f"[video_dub] LLM translate fallback to Hy-MT2: {exc}", flush=True)

        # 2. Local Hy-MT2-7B batch/line translation
        self.models._wait_for_llm()
        missing_indices = [i for i, g in enumerate(segs) if not g.vi]
        missing_lines = [segs[i].zh for i in missing_indices]
        try:
            translated_lines = self.models._translate_screen_lines(
                missing_lines,
                effective_source_lang if effective_source_lang != "auto" else "zh",
                self.target_language,
            )
            for idx, trans in zip(missing_indices, translated_lines):
                segs[idx].vi = _clean_line(trans)
                self.history.append((segs[idx].zh, segs[idx].vi))
        except Exception as exc:
            print(f"[video_dub] Batch translate fallback: {exc}", flush=True)
            from backend.server import SessionConfig

            cfg = SessionConfig(
                mode="fast",
                source_language=effective_source_lang if effective_source_lang != "auto" else "zh",
                target_language=self.target_language,
                speak_translation=False,
                history=list(self.history[-4:]),
            )
            for idx in missing_indices:
                try:
                    t_line = self.models._translate(segs[idx].zh, cfg)
                    segs[idx].vi = _clean_line(t_line)
                except Exception:
                    segs[idx].vi = _clean_line(segs[idx].zh)
                self.history.append((segs[idx].zh, segs[idx].vi))


class VideoSession:
    """Manages one video's chunked ASR, read-ahead Story Bible, translation, TTS, and BGM mixing."""

    def __init__(
        self,
        s: DubSettings,
        models: Any,
        separator: DemucsSeparator,
        translator: VideoTranslator,
        a16: np.ndarray,
        a44: np.ndarray,
        chunks: list[Chunk],
        source_language: str = "auto",
        target_language: str = "vi",
        voice: str = "F1",
        bgm_mode: str = "duck",
        asr_mode: str = "fast",
        transcript: list[dict[str, Any]] | None = None,
        transcript_lang: str | None = None,
    ) -> None:
        self.s = s
        self.models = models
        self.sep = separator
        self.tr = translator
        self.a16 = a16
        self.a44 = a44
        self.chunks = chunks
        self.source_language = source_language
        self.detected_language = source_language if source_language != "auto" else ""
        self.target_language = target_language
        self.voice = voice
        self.bgm_mode = bgm_mode
        self.asr_mode = asr_mode if asr_mode in {"fast", "quality"} else "fast"
        self.transcript = transcript
        self.transcript_lang = (transcript_lang or "").lower()
        self._segs: dict[int, list[Seg]] = {}
        self._asr_time: dict[int, float] = {}
        self._asr_lock = threading.Lock()
        self.cancel = threading.Event()
        self.play_time = 0.0
        self._ahead: threading.Thread | None = None
        self._pool = ThreadPoolExecutor(max_workers=1)

        if self.transcript:
            self._init_from_transcript()

    def _init_from_transcript(self) -> None:
        is_target = self.transcript_lang.startswith(self.target_language)
        if not is_target and self.target_language == "vi" and self.transcript:
            sample = " ".join(str(c.get("text", "")) for c in self.transcript[:10])
            vi_chars = set("àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ")
            if any(ch in vi_chars for ch in sample.lower()):
                is_target = True

        for c in self.chunks:
            self._segs[c.index] = []
            self._asr_time[c.index] = 0.0

        for cue in self.transcript or []:
            start = float(cue.get("start", 0.0))
            end = float(cue.get("end", start + 2.0))
            text = str(cue.get("text", "")).strip()
            if not text:
                continue
            mid = (start + end) / 2.0
            target_chunk = next((c for c in self.chunks if c.start <= mid < c.end), None)
            if target_chunk is None and self.chunks:
                target_chunk = min(self.chunks, key=lambda c: abs(c.start - start))
            if target_chunk:
                self._segs[target_chunk.index].append(
                    Seg(start=start, end=end, zh=text, vi=text if is_target else "")
                )
        if self.transcript_lang and not self.detected_language:
            self.detected_language = self.transcript_lang[:2]

    def _transcribe_slice(self, audio_slice: np.ndarray, offset: float) -> list[Seg]:
        if not len(audio_slice):
            return []
        with self.models.lock:
            self.models._load(self.asr_mode)
            whisper_model = self.models.asr[self.asr_mode]
            lang_arg = None if self.source_language == "auto" and not self.detected_language else (self.detected_language or self.source_language)
            segs_iter, info = whisper_model.transcribe(
                audio_slice,
                language=lang_arg,
                beam_size=1 if self.asr_mode == "fast" else 5,
                vad_filter=True,
                condition_on_previous_text=False,
                no_speech_threshold=0.6,
            )
            out: list[Seg] = []
            for g in segs_iter:
                text = g.text.strip()
                if text and g.no_speech_prob < 0.82:
                    out.append(Seg(offset + float(g.start), offset + float(g.end), text))
            if not self.detected_language and getattr(info, "language", None):
                self.detected_language = str(info.language)
            return out

    def segs_for(self, i: int) -> list[Seg]:
        with self._asr_lock:
            if i not in self._segs:
                c = self.chunks[i]
                t0 = time.time()
                slice_16k = self.a16[int(c.start * 16000) : int(c.end * 16000)]
                self._segs[i] = self._transcribe_slice(slice_16k, c.start)
                self._asr_time[i] = time.time() - t0
            return self._segs[i]

    def _lines(self) -> list[tuple[float, str]]:
        return [(g.start, g.zh) for i in sorted(self._segs) for g in self._segs[i]]

    def warm_up(self, start_index: int = 0) -> None:
        if self.cancel.is_set() or not self.chunks:
            return
        if self.transcript:
            is_done = any(bool(g.vi) for segs in self._segs.values() for g in segs)
            if not is_done:
                self.tr.understand(self._lines(), complete=True)
            return

        first_idx = min(max(0, start_index), len(self.chunks) - 1)
        self.segs_for(first_idx)
        if self.cancel.is_set():
            return
        self.tr.understand(self._lines(), complete=len(self.chunks) == 1)
        if len(self.chunks) > 1 and not self.cancel.is_set():
            self._ahead = threading.Thread(target=self._read_ahead, daemon=True)
            self._ahead.start()

    def _read_ahead(self) -> None:
        last_bible = 1
        for c in self.chunks:
            while not self.cancel.is_set() and c.start > self.play_time + self.s.story_lookahead_sec:
                if self.cancel.wait(0.5):
                    return
            if self.cancel.is_set():
                return
            self.segs_for(c.index)
            if self.cancel.is_set():
                return
            done = len(self._segs)
            if done - last_bible >= self.s.bible_every or done == len(self.chunks):
                last_bible = done
                self.tr.understand(self._lines(), complete=done == len(self.chunks))

    def process(self, i: int) -> tuple[np.ndarray, list[dict[str, Any]], dict[str, Any]]:
        c = self.chunks[i]
        self.play_time = c.start
        segs = self.segs_for(i)
        t_asr = self._asr_time.get(i, 0.0)
        t_start = time.time()

        bgm_future = self._pool.submit(self.sep.bgm, self.a44, c.start, c.end, self.bgm_mode)
        slots = [max(0.6, min(g.end, c.end) - g.start) for g in segs]

        if self.cancel.is_set():
            bgm_future.cancel()
            return np.zeros((int((c.end - c.start) * self.s.mix_sr), 2), dtype=np.float32), [], {}

        t_tr0 = time.time()
        effective_src = self.detected_language or (self.source_language if self.source_language != "auto" else "zh")
        if all(bool(g.vi) for g in segs):
            t_tr = 0.0
        else:
            self.tr.translate(segs, slots, effective_src)
            t_tr = time.time() - t_tr0

        t_tts0 = time.time()
        clips: list[tuple[float, np.ndarray]] = []
        subs: list[dict[str, Any]] = []
        tempos: list[float] = []
        chunk_dur = max(0.1, c.end - c.start)
        cursor = 0.0
        for idx, g in enumerate(segs):
            if self.cancel.is_set():
                bgm_future.cancel()
                break
            seg_start_rel = max(0.0, g.start - c.start)
            seg_end_rel = min(chunk_dur, max(seg_start_rel + 0.4, g.end - c.start))
            next_start_rel = (
                max(seg_end_rel, min(chunk_dur, segs[idx + 1].start - c.start))
                if idx + 1 < len(segs)
                else chunk_dur
            )
            # Align voiceover to the true start of the utterance (never right-aligned to end!)
            off = min(max(seg_start_rel, cursor), max(0.0, chunk_dur - 0.25))
            # Allow using up to 0.35s of natural pause after the segment before the next utterance starts
            avail_end = min(next_start_rel, max(seg_end_rel, seg_end_rel + 0.35))
            avail_slot = max(0.55, avail_end - off)

            if not g.vi.strip():
                subs.append({
                    "start": round(c.start + seg_start_rel, 2),
                    "end": round(c.start + seg_end_rel, 2),
                    "zh": g.zh,
                    "vi": g.vi,
                })
                continue
            try:
                waveform, sr = self.models.synthesize_speech(g.vi, self.target_language, self.voice)
                fitted_audio, tempo = load_fitted_waveform(waveform, sr, avail_slot, self.s.mix_sr)
            except Exception as exc:
                print(f"[video_dub] TTS skipped {g.vi!r}: {exc}", flush=True)
                subs.append({
                    "start": round(c.start + seg_start_rel, 2),
                    "end": round(c.start + seg_end_rel, 2),
                    "zh": g.zh,
                    "vi": g.vi,
                })
                continue

            clip_dur = len(fitted_audio) / float(self.s.mix_sr)
            actual_end_rel = min(chunk_dur, max(seg_end_rel, off + clip_dur))
            subs.append({
                "start": round(c.start + off, 2),
                "end": round(c.start + actual_end_rel, 2),
                "zh": g.zh,
                "vi": g.vi,
            })
            clips.append((off, fitted_audio))
            tempos.append(tempo)
            cursor = min(chunk_dur, off + clip_dur + 0.03)
        t_tts = time.time() - t_tts0

        if self.cancel.is_set():
            bgm_future.cancel()
            return np.zeros((int((c.end - c.start) * self.s.mix_sr), 2), dtype=np.float32), [], {}

        bgm_audio, used_demucs = bgm_future.result()
        mixed = mix_chunk(bgm_audio, clips, self.s, used_demucs=used_demucs)
        timing = {
            "asr": round(t_asr, 2),
            "translate": round(t_tr, 2),
            "tts": round(t_tts, 2),
            "total": round(time.time() - t_start + t_asr, 2),
            "max_atempo": round(max(tempos, default=1.0), 2),
            "demucs": used_demucs,
        }
        return mixed, subs, timing


class DubJob:
    def __init__(
        self,
        urls: list[str],
        duration: float = 0.0,
        referer: str | None = None,
        exact: bool = False,
        start: float = 0.0,
        transcript: list[dict[str, Any]] | None = None,
        transcript_lang: str | None = None,
        source_language: str = "auto",
        target_language: str = "vi",
        voice: str = "F1",
        bgm_mode: str = "mute",
        translator_engine: str = "local",
        asr_mode: str = "fast",
        download_video: bool = False,
        local_video_path: Path | None = None,
        title: str = "",
    ) -> None:
        self.id = uuid.uuid4().hex[:8]
        self.created_at = time.time()
        self.urls = urls
        self.expected = duration
        self.referer = referer
        self.exact = exact
        self.url = urls[0] if urls else ""
        self.title = title or (local_video_path.name if local_video_path else (urls[0][:80] if urls else self.id))
        self.state = "loading"  # loading | running | done | error | cancelled
        self.stage = "Đang khởi tạo..."
        self.error = ""
        self.duration = 0.0
        self.chunks: list[Chunk] = []
        self.audio: dict[int, bytes] = {}
        self.raw_audio: dict[int, np.ndarray] = {}
        self.subs: dict[int, list[dict[str, Any]]] = {}
        self.timing: dict[int, dict[str, Any]] = {}
        self.pointer = 0
        self.initial_start = start
        self.transcript = transcript
        self.transcript_lang = transcript_lang
        self.source_language = source_language
        self.target_language = target_language
        self.voice = voice
        self.bgm_mode = bgm_mode
        self.translator_engine = translator_engine
        self.asr_mode = asr_mode
        self.download_video = download_video
        self.video_path: Path | None = local_video_path
        self.session: VideoSession | None = None
        self.cancel = threading.Event()
        self.lock = threading.Lock()

    def next_chunk(self) -> int | None:
        todo = [c.index for c in self.chunks if c.index not in self.audio]
        if not todo:
            return None
        return next((i for i in todo if i >= self.pointer), todo[0])


class VideoDubManager:
    """Manages active & recent video dubbing jobs inside SpeakBridge."""

    def __init__(self, models: Any, advisor: Any) -> None:
        self.s = DubSettings()
        self.s.workspace.mkdir(parents=True, exist_ok=True)
        self.models = models
        self.advisor = advisor
        self.separator = DemucsSeparator(self.s)
        self.jobs: dict[str, DubJob] = {}
        self.current: DubJob | None = None
        self.worker_lock = threading.Lock()
        self.cleanup_storage(keep_job_id=None)

    def cleanup_storage(self, keep_job_id: str | None = None) -> dict[str, Any]:
        """Remove temporary video/audio files and RAM buffers of old jobs so disk/RAM never bloats."""
        import gc

        removed_dirs = 0
        freed_bytes = 0
        keep_files: set[Path] = set()
        if keep_job_id and keep_job_id in self.jobs:
            kj = self.jobs[keep_job_id]
            if kj.video_path:
                keep_files.add(kj.video_path.resolve())

        for old_id in list(self.jobs.keys()):
            if old_id != keep_job_id:
                old_job = self.jobs.pop(old_id, None)
                if old_job:
                    old_job.cancel.set()
                    if old_job.session:
                        old_job.session.cancel.set()
                        old_job.session.a16 = np.empty(0, dtype=np.float32)
                        old_job.session.a44 = np.empty((0, 2), dtype=np.float32)
                    old_job.audio.clear()
                    old_job.raw_audio.clear()

        if keep_job_id is None:
            self.current = None

        if self.s.workspace.is_dir():
            for child in list(self.s.workspace.iterdir()):
                try:
                    if child.name == "uploads" and child.is_dir():
                        for uf in list(child.iterdir()):
                            if uf.resolve() not in keep_files:
                                sz = uf.stat().st_size if uf.is_file() else 0
                                uf.unlink(missing_ok=True)
                                freed_bytes += sz
                    elif child.is_dir() and child.name != keep_job_id:
                        for f in child.rglob("*"):
                            if f.is_file():
                                freed_bytes += f.stat().st_size
                        shutil.rmtree(child, ignore_errors=True)
                        removed_dirs += 1
                except Exception:
                    pass

        gc.collect()
        return {
            "ok": True,
            "removed_dirs": removed_dirs,
            "freed_mb": round(freed_bytes / (1024 * 1024), 2),
        }

    def create_job(self, **kwargs: Any) -> DubJob:
        if self.current and self.current.state in ("loading", "running"):
            self.stop_job(self.current.id)
        job = DubJob(**kwargs)
        self.jobs[job.id] = self.current = job
        self.cleanup_storage(keep_job_id=job.id)
        threading.Thread(target=self._run_job, args=(job,), daemon=True).start()
        return job

    def stop_job(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job:
            return False
        job.cancel.set()
        if job.session:
            job.session.cancel.set()
            job.session.a16 = np.empty(0, dtype=np.float32)
            job.session.a44 = np.empty((0, 2), dtype=np.float32)
        job.state = "cancelled"
        job.stage = "Đã dừng"
        return True

    def stop_all(self) -> int:
        count = 0
        for job in list(self.jobs.values()):
            if job.state in ("loading", "running"):
                self.stop_job(job.id)
                count += 1
        self.cleanup_storage(keep_job_id=None)
        return count

    def _download_with_ytdlp(self, url: str, work: Path, job: DubJob, need_video: bool) -> Path:
        import yt_dlp

        def _hook(d: dict[str, Any]) -> None:
            if job.cancel.is_set():
                raise yt_dlp.utils.DownloadCancelled("Cancelled by user")

        fmt = (
            "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/b/ba"
            if need_video
            else "ba/b"
        )
        ydl_opts: dict[str, Any] = {
            "format": fmt,
            "outtmpl": str(work / "source.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "progress_hooks": [_hook],
        }
        if need_video:
            ydl_opts["merge_output_format"] = "mp4"
        if job.referer:
            ydl_opts["http_headers"] = {"Referer": job.referer, "User-Agent": "Mozilla/5.0"}

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info and isinstance(info, dict) and info.get("title"):
                job.title = str(info["title"])[:120]

        src_files = [f for f in work.glob("source.*") if not f.name.endswith(".part")]
        if not src_files:
            raise RuntimeError("Không tải được luồng media từ URL đã nhập")
        return src_files[0]

    def _run_job(self, job: DubJob) -> None:
        try:
            if job.cancel.is_set():
                job.state = "cancelled"
                return

            work = self.s.workspace / job.id
            work.mkdir(parents=True, exist_ok=True)

            # 1. Ingest media into a16 (16kHz mono) & a44 (44.1kHz stereo)
            if job.video_path and job.video_path.is_file():
                job.stage = "Đang giải mã file video..."
                a16 = decode_audio(job.video_path, 16000, 1)
                if job.cancel.is_set():
                    job.state = "cancelled"
                    return
                a44 = decode_audio(job.video_path, self.s.mix_sr, 2)
            else:
                # Direct CDN URLs from the browser extension have media extensions or vod hosts
                is_direct_cdn = any(
                    re.search(r"douyinvod|bytevod|zjcdn|\.mp4|\.m4s|\.m3u8|\.ts|\.webm|mime_type=video|video_mp4|\/video\/tos\/", u, re.I)
                    for u in job.urls
                )
                if not is_direct_cdn:
                    job.urls = [normalize_page_url(u) for u in job.urls]
                is_page_url = any(
                    domain in u
                    for u in job.urls
                    for domain in ("youtube.com", "youtu.be", "tiktok.com", "douyin.com", "bilibili.com", "coursera.org")
                )
                if job.download_video or (is_page_url and not is_direct_cdn):
                    target_url = job.urls[0]
                    job.url = target_url
                    media_file: Path | None = None
                    ydl_err: Exception | None = None

                    if "douyin.com" not in target_url:
                        job.stage = "Đang tải luồng video/audio qua yt-dlp..."
                        try:
                            media_file = self._download_with_ytdlp(target_url, work, job, need_video=job.download_video)
                        except Exception as exc:
                            ydl_err = exc

                    if media_file is None:
                        if job.cancel.is_set():
                            job.state = "cancelled"
                            return
                        if is_page_url:
                            try:
                                job.stage = "Đang lấy luồng video qua Cốc Cốc (CDP 9222)..."
                                cdp_urls, cdp_title, cdp_referer = resolve_media_via_cdp(target_url, job.cancel)
                                if cdp_title and not job.title:
                                    job.title = cdp_title[:120]
                                job.stage = "Đang tải luồng video/audio từ CDN..."
                                media_file = download_from_cdp_urls(
                                    cdp_urls, cdp_referer, work, need_video=job.download_video
                                )
                            except Exception as cdp_exc:
                                ydl_err = ydl_err or cdp_exc

                    if media_file is not None and media_file.is_file():
                        if job.download_video and media_file.suffix.lower() in (".mp4", ".webm", ".mkv", ".mov"):
                            job.video_path = media_file
                        job.stage = "Đang giải mã âm thanh..."
                        a16 = decode_audio(media_file, 16000, 1)
                        if job.cancel.is_set():
                            job.state = "cancelled"
                            return
                        a44 = decode_audio(media_file, self.s.mix_sr, 2)
                    else:
                        if job.cancel.is_set():
                            job.state = "cancelled"
                            return
                        args = ["-headers", f"Referer: {job.referer}\r\nUser-Agent: Mozilla/5.0\r\n"] if job.referer else []
                        try:
                            a16 = decode_audio(target_url, 16000, 1, args)
                            a44 = decode_audio(target_url, 16000 if self.s.mix_sr <= 0 else self.s.mix_sr, 2, args)
                        except Exception:
                            raise RuntimeError(f"Không thể tải video từ URL này: {ydl_err}") from ydl_err
                else:
                    job.stage = "Đang dò luồng âm thanh CDN..."
                    job.url = pick_url(job.urls, job.expected, job.referer, job.exact)
                    if job.cancel.is_set():
                        job.state = "cancelled"
                        return
                    args = ["-headers", f"Referer: {job.referer}\r\nUser-Agent: Mozilla/5.0\r\n"] if job.referer else []
                    job.stage = "Đang giải mã âm thanh..."
                    a16 = decode_audio(job.url, 16000, 1, args)
                    if job.cancel.is_set():
                        job.state = "cancelled"
                        return
                    a44 = decode_audio(job.url, self.s.mix_sr, 2, args)

            if job.cancel.is_set():
                job.state = "cancelled"
                return

            job.duration = round(len(a16) / 16000.0, 2)
            job.stage = "Đang phân đoạn câu thoại (Silero VAD)..."

            if job.transcript and len(job.transcript) > 0:
                speech = [
                    (float(c["start"]), float(c["end"]))
                    for c in job.transcript
                    if float(c.get("end", 0)) > float(c.get("start", 0))
                ]
                if not speech:
                    speech = speech_timestamps(a16)
            else:
                speech = speech_timestamps(a16)

            job.chunks = plan_chunks(job.duration, speech, self.s)
            if job.initial_start > 0:
                for c in job.chunks:
                    if c.start <= job.initial_start < c.end:
                        job.pointer = c.index
                        break

            if job.cancel.is_set():
                job.state = "cancelled"
                return

            translator = VideoTranslator(
                self.s,
                self.models,
                self.advisor,
                source_language=job.source_language,
                target_language=job.target_language,
                engine_mode=job.translator_engine,
            )
            session = VideoSession(
                self.s,
                self.models,
                self.separator,
                translator,
                a16,
                a44,
                job.chunks,
                source_language=job.source_language,
                target_language=job.target_language,
                voice=job.voice,
                bgm_mode=job.bgm_mode,
                asr_mode=job.asr_mode,
                transcript=job.transcript,
                transcript_lang=job.transcript_lang,
            )
            job.session = session

            job.stage = "Đang nhận diện đoạn đầu & lập Story Bible..."
            with self.worker_lock:
                if job.cancel.is_set():
                    job.state = "cancelled"
                    return
                session.warm_up(start_index=job.pointer)

            if job.cancel.is_set():
                job.state = "cancelled"
                session.cancel.set()
                return

            job.state = "running"
            while not job.cancel.is_set():
                i = job.next_chunk()
                if i is None or job.cancel.is_set():
                    break
                c = job.chunks[i]
                job.stage = f"Đang thuyết minh đoạn {i + 1}/{len(job.chunks)} ({c.start:.0f}s–{c.end:.0f}s)..."
                with self.worker_lock:
                    if job.cancel.is_set():
                        break
                    mixed, subs, timing = session.process(i)
                if job.cancel.is_set():
                    break
                buf = io.BytesIO()
                sf.write(buf, mixed, self.s.mix_sr, format="WAV", subtype="PCM_16")
                with job.lock:
                    job.audio[i] = buf.getvalue()
                    job.raw_audio[i] = mixed
                    job.subs[i] = subs
                    job.timing[i] = timing
                dur = max(0.1, c.end - c.start)
                print(
                    f"[video_dub {job.id}] chunk {i}/{len(job.chunks)} ({dur:.1f}s) {timing} RTF={timing.get('total', 0) / dur:.2f}",
                    flush=True,
                )

            session.cancel.set()
            job.state = "cancelled" if job.cancel.is_set() else "done"
            job.stage = "Đã dừng" if job.cancel.is_set() else "Hoàn tất thuyết minh toàn bộ video"
        except Exception as exc:
            if job.cancel.is_set():
                job.state = "cancelled"
                job.stage = "Đã dừng"
                return
            job.state = "error"
            job.error = str(exc)
            job.stage = f"Lỗi: {exc}"
            print(f"[video_dub {job.id}] error: {exc}", flush=True)
        finally:
            if job.session:
                job.session.cancel.set()
                # Release raw source PCM arrays from RAM immediately once processing finishes
                job.session.a16 = np.empty(0, dtype=np.float32)
                job.session.a44 = np.empty((0, 2), dtype=np.float32)

    def serialize_job(self, job: DubJob) -> dict[str, Any]:
        with job.lock:
            subs = [s for i in sorted(job.subs) for s in job.subs[i]]
            bible = job.session.tr.bible if job.session else {}
            detected = job.session.detected_language if job.session else job.source_language
            timings = dict(job.timing)
            return {
                "job_id": job.id,
                "title": job.title,
                "url": job.url,
                "state": job.state,
                "stage": job.stage,
                "error": job.error,
                "duration": job.duration,
                "has_video": bool(job.video_path and job.video_path.is_file()),
                "source_language": detected or job.source_language,
                "target_language": job.target_language,
                "voice": job.voice,
                "bgm_mode": job.bgm_mode,
                "translator_engine": job.translator_engine,
                "chunks": [
                    {
                        "i": c.index,
                        "start": c.start,
                        "end": c.end,
                        "ready": c.index in job.audio,
                        "timing": timings.get(c.index),
                    }
                    for c in job.chunks
                ],
                "subs": subs,
                "bible": bible,
                "sample_rate": self.s.mix_sr,
            }

    def export_srt(self, job: DubJob) -> str:
        with job.lock:
            subs = [s for i in sorted(job.subs) for s in job.subs[i]]

        def _fmt_srt_time(seconds: float) -> str:
            ms = int(round((seconds % 1) * 1000))
            total_s = int(seconds)
            s = total_s % 60
            m = (total_s // 60) % 60
            h = total_s // 3600
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        blocks = []
        for idx, s in enumerate(subs, 1):
            start_t = _fmt_srt_time(float(s["start"]))
            end_t = _fmt_srt_time(float(s["end"]))
            vi = str(s.get("vi") or "").strip()
            zh = str(s.get("zh") or "").strip()
            text = f"{vi}\n({zh})" if vi and zh and vi != zh else (vi or zh)
            blocks.append(f"{idx}\n{start_t} --> {end_t}\n{text}\n")
        return "\n".join(blocks)

    def export_dubbed_file(self, job: DubJob) -> tuple[Path, str]:
        """Returns (file_path, media_type) — either muxed MP4 if video exists or full WAV."""
        work = self.s.workspace / job.id
        work.mkdir(parents=True, exist_ok=True)
        with job.lock:
            pieces = []
            for c in job.chunks:
                if c.index in job.raw_audio:
                    pieces.append(job.raw_audio[c.index])
                else:
                    n_samples = int((c.end - c.start) * self.s.mix_sr)
                    pieces.append(np.zeros((n_samples, 2), dtype=np.float32))
        full_audio = np.concatenate(pieces) if pieces else np.zeros((self.s.mix_sr, 2), dtype=np.float32)
        wav_path = work / "dubbed_full.wav"
        sf.write(str(wav_path), full_audio, self.s.mix_sr, format="WAV", subtype="PCM_16")

        if job.video_path and job.video_path.is_file():
            mp4_path = work / "dubbed_full.mp4"
            subprocess.run(
                [
                    "ffmpeg", "-v", "error", "-y",
                    "-i", str(job.video_path),
                    "-i", str(wav_path),
                    "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-shortest", str(mp4_path),
                ],
                check=True,
                timeout=180,
            )
            return mp4_path, "video/mp4"
        return wav_path, "audio/wav"
