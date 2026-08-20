from __future__ import annotations

import base64
import array
import ctypes
import json
import logging
import math
import os
import queue
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
import wave
import winsound
from ctypes import wintypes
from pathlib import Path
from typing import Any

import keyboard
import pyperclip
import pystray
import tkinter as tk
from PIL import Image, ImageDraw
import pyaudiowpatch as pyaudio


class _Rect(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class _GuiThreadInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", _Rect),
    ]


PROJECT_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(sys.executable).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "hotkey.local.json"
RUN_DIR = PROJECT_ROOT / ".run"
API_URL = "http://127.0.0.1:8765"
DEFAULTS: dict[str, Any] = {
    "hotkey": "ctrl+alt+space",
    "microphone": "__default__",
    "mode": "fast",
    "source_language": "vi",
    "target_language": "en",
    "translate": True,
}

RUN_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=RUN_DIR / "hotkey.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    encoding="utf-8",
)


class VoiceTypingHelper:
    def __init__(self) -> None:
        self.settings = self._load_settings()
        self.settings_mtime = self._mtime()
        self.hotkey_handles: list[Any] = []
        self.release_hook: Any | None = None
        self.release_keys: set[str] = set()
        self.recording = False
        self.processing = False
        self.frames: list[bytes] = []
        self.audio: Any | None = None
        self.stream: Any | None = None
        self.sample_rate = 16_000
        self.channels = 1
        self.record_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.icon: pystray.Icon | None = None
        self.target_window: int | None = None
        self.target_control: int | None = None
        self.overlay: tk.Tk | None = None
        self.overlay_canvas: tk.Canvas | None = None
        self.overlay_status: int | None = None
        self.overlay_message: int | None = None
        self.status_queue: queue.SimpleQueue[tuple[str, str]] = queue.SimpleQueue()
        self.sound_dir = RUN_DIR / "sounds"
        self.engine_lock = threading.Lock()
        self._prepare_sounds()

    def _mtime(self) -> float:
        try:
            return CONFIG_PATH.stat().st_mtime
        except OSError:
            return 0.0

    def _load_settings(self) -> dict[str, Any]:
        settings = dict(DEFAULTS)
        try:
            payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            settings.update({key: payload[key] for key in DEFAULTS if key in payload})
        except (OSError, ValueError, TypeError):
            pass
        return settings

    def _register_hotkey(self) -> None:
        for handle in self.hotkey_handles:
            try:
                keyboard.remove_hotkey(handle)
            except (KeyError, ValueError):
                pass
        self.hotkey_handles.clear()
        if self.release_hook is not None:
            try:
                keyboard.unhook(self.release_hook)
            except (KeyError, ValueError):
                pass
            self.release_hook = None
        shortcut = str(self.settings["hotkey"])
        self.release_keys = {part.strip().casefold() for part in shortcut.split("+") if part.strip()}
        self.hotkey_handles.append(
            keyboard.add_hotkey(shortcut, self.start_recording, suppress=True)
        )
        self.release_hook = keyboard.on_release(self._on_key_release, suppress=False)
        logging.info("Registered push-to-talk hotkey: %s", shortcut)

    def _on_key_release(self, event: keyboard.KeyboardEvent) -> None:
        name = (event.name or "").casefold()
        aliases = {name, name.replace("left ", ""), name.replace("right ", "")}
        if self.recording and aliases & self.release_keys:
            self.stop_recording()

    def _watch_settings(self) -> None:
        while not self.stop_event.wait(2):
            current_mtime = self._mtime()
            if current_mtime != self.settings_mtime and not self.recording:
                self.settings_mtime = current_mtime
                self.settings = self._load_settings()
                try:
                    self._register_hotkey()
                    self._notify("Đã cập nhật phím tắt")
                except Exception:
                    logging.exception("Could not reload hotkey")

    def _notify(self, message: str) -> None:
        logging.info(message)

    @staticmethod
    def _api_ready() -> bool:
        try:
            with urllib.request.urlopen(f"{API_URL}/health", timeout=1.2) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return bool(payload.get("ok")) and payload.get("translator") == "hy-mt2"
        except Exception:
            return False

    def _ensure_engine(self) -> bool:
        if self._api_ready():
            return True
        if not self.engine_lock.acquire(blocking=False):
            return False
        try:
            if self._api_ready():
                return True
            start_script = PROJECT_ROOT / "start.ps1"
            if not start_script.is_file():
                self._set_status("error", "THIẾU START.PS1 · chạy bộ cài SpeakBridge")
                logging.error("Cannot auto-start engine; missing %s", start_script)
                return False
            self._set_status("processing", "ĐANG KHỞI ĐỘNG ENGINE · vui lòng chờ")
            logging.info("Starting SpeakBridge engine in the background")
            subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(start_script),
                    "-NoBrowser",
                ],
                cwd=str(PROJECT_ROOT),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            for _ in range(180):
                if self.stop_event.wait(0.5):
                    return False
                if self._api_ready():
                    self._set_status("ready", f"Sẵn sàng · {self.settings['hotkey']}")
                    logging.info("SpeakBridge engine is ready")
                    return True
            self._set_status("error", "ENGINE KHÔNG KHỞI ĐỘNG · xem thư mục .run")
            logging.error("SpeakBridge engine did not become ready within 90 seconds")
            return False
        except Exception:
            logging.exception("Could not auto-start SpeakBridge engine")
            self._set_status("error", "KHÔNG KHỞI ĐỘNG ĐƯỢC ENGINE")
            return False
        finally:
            self.engine_lock.release()

    def _set_status(self, state: str, message: str, notify: bool = False) -> None:
        del notify  # Status is shown by the quiet overlay, never by Windows toast.
        colors = {
            "ready": "#c9ff5d",
            "recording": "#ff685f",
            "processing": "#ffba72",
            "done": "#68f0b8",
            "error": "#ff685f",
        }
        logging.info("%s: %s", state.upper(), message)
        self.status_queue.put((state, message))
        if self.icon:
            self.icon.icon = self._icon_image(colors.get(state, "#c9ff5d"))
            self.icon.title = f"SpeakBridge · {message}"

    def _prepare_sounds(self) -> None:
        """Create low-volume, soft sine chimes instead of harsh PC speaker beeps."""
        self.sound_dir.mkdir(parents=True, exist_ok=True)
        patterns = {
            "start": [(620, 55), (820, 75)],
            "processing": [(540, 55), (690, 65)],
            "done": [(720, 65), (960, 75), (1240, 85)],
            "error": [(360, 85), (260, 110)],
        }
        sample_rate = 24_000
        for name, notes in patterns.items():
            path = self.sound_dir / f"{name}.wav"
            if path.exists():
                continue
            samples: list[int] = []
            for frequency, duration_ms in notes:
                count = int(sample_rate * duration_ms / 1000)
                fade = max(1, int(count * 0.20))
                for index in range(count):
                    envelope = min(1.0, index / fade, (count - index - 1) / fade)
                    # A quiet fundamental plus a small upper harmonic gives a clean tech chime.
                    value = (math.sin(2 * math.pi * frequency * index / sample_rate) * 0.10)
                    value += (math.sin(2 * math.pi * frequency * 2 * index / sample_rate) * 0.018)
                    samples.append(int(32767 * envelope * value))
                samples.extend([0] * int(sample_rate * 0.012))
            with wave.open(str(path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(sample_rate)
                output.writeframes(struct.pack(f"<{len(samples)}h", *samples))

    def _play_sound(self, name: str) -> None:
        path = self.sound_dir / f"{name}.wav"
        try:
            winsound.PlaySound(
                str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT
            )
        except Exception:
            logging.exception("Could not play status sound %s", name)

    def _create_overlay(self) -> None:
        root = tk.Tk()
        self.overlay = root
        root.title("SpeakBridge Status")
        root.overrideredirect(True)
        root.configure(bg="#0b100d")
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.94)
        width, height = 430, 64
        x = max(12, (root.winfo_screenwidth() - width) // 2)
        root.geometry(f"{width}x{height}+{x}+18")
        canvas = tk.Canvas(root, width=width, height=height, bg="#0b100d", highlightthickness=1, highlightbackground="#263229")
        canvas.pack(fill="both", expand=True)
        self.overlay_canvas = canvas
        canvas.create_oval(18, 22, 38, 42, fill="#c9ff5d", outline="", tags="dot")
        self.overlay_status = canvas.create_text(52, 20, anchor="nw", fill="#c9ff5d", font=("Segoe UI Semibold", 10), text="SPEAKBRIDGE · SẴN SÀNG")
        self.overlay_message = canvas.create_text(52, 39, anchor="nw", fill="#b8c0b9", font=("Segoe UI", 9), text=f"Giữ {self.settings['hotkey']} để nói")
        root.update_idletasks()
        hwnd = int(root.winfo_id())
        user32 = ctypes.windll.user32
        parent = int(user32.GetParent(hwnd))
        if parent:
            hwnd = parent
        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_NOACTIVATE = 0x08000000
        style = int(user32.GetWindowLongW(hwnd, GWL_EXSTYLE))
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        root.after(40, self._poll_overlay)

    def _poll_overlay(self) -> None:
        colors = {
            "ready": "#c9ff5d",
            "recording": "#ff685f",
            "processing": "#ffba72",
            "done": "#68f0b8",
            "error": "#ff685f",
        }
        labels = {
            "ready": "SPEAKBRIDGE · SẴN SÀNG",
            "recording": "SPEAKBRIDGE · ĐANG NGHE",
            "processing": "SPEAKBRIDGE · ĐANG DỊCH",
            "done": "SPEAKBRIDGE · HOÀN THÀNH",
            "error": "SPEAKBRIDGE · CẦN THỬ LẠI",
        }
        latest: tuple[str, str] | None = None
        while True:
            try:
                latest = self.status_queue.get_nowait()
            except queue.Empty:
                break
        if latest and self.overlay_canvas is not None:
            state, message = latest
            color = colors.get(state, "#c9ff5d")
            self.overlay_canvas.itemconfigure("dot", fill=color)
            if self.overlay_status is not None:
                self.overlay_canvas.itemconfigure(self.overlay_status, fill=color, text=labels.get(state, labels["ready"]))
            if self.overlay_message is not None:
                self.overlay_canvas.itemconfigure(self.overlay_message, text=message)
        if self.overlay is not None and not self.stop_event.is_set():
            self.overlay.after(40, self._poll_overlay)

    def _find_microphone(self) -> dict[str, Any]:
        assert self.audio is not None
        requested = str(self.settings.get("microphone", "__default__"))
        wasapi_index: int | None = None
        for index in range(self.audio.get_host_api_count()):
            host = self.audio.get_host_api_info_by_index(index)
            if "WASAPI" in str(host["name"]):
                wasapi_index = int(host["index"])
                if requested == "__default__":
                    return self.audio.get_device_info_by_index(int(host["defaultInputDevice"]))
                break
        if requested == "__default__":
            return self.audio.get_default_input_device_info()
        candidates: list[dict[str, Any]] = []
        for index in range(self.audio.get_device_count()):
            device = self.audio.get_device_info_by_index(index)
            if device.get("maxInputChannels", 0) <= 0 or device.get("isLoopbackDevice", False):
                continue
            if requested.casefold() == str(device["name"]).casefold():
                candidates.append(device)
        if candidates:
            return next(
                (device for device in candidates if int(device["hostApi"]) == wasapi_index),
                candidates[0],
            )
        raise RuntimeError(f"Không tìm thấy microphone đã chọn: {requested}")

    def start_recording(self) -> None:
        if self.recording or self.processing:
            return
        if not self._api_ready():
            self._set_status("processing", "ENGINE ĐANG TẮT · tự khởi động lại")
            threading.Thread(target=self._ensure_engine, daemon=True).start()
            return
        try:
            self.target_window, self.target_control = self._focused_target()
            self.audio = pyaudio.PyAudio()
            device = self._find_microphone()
            self.sample_rate = int(device.get("defaultSampleRate", 48_000))
            self.channels = max(1, min(2, int(device.get("maxInputChannels", 1))))
            self.stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                input_device_index=int(device["index"]),
                frames_per_buffer=1024,
            )
            self.frames = []
            self.recording = True
            self.record_thread = threading.Thread(target=self._record_loop, daemon=True)
            self.record_thread.start()
            logging.info("Recording device: %s (%s Hz, %s channel(s))", device.get("name"), self.sample_rate, self.channels)
            self._set_status("recording", "ĐANG NGHE · thả phím để dịch", notify=True)
            self._play_sound("start")
        except Exception as exc:
            logging.exception("Cannot start microphone")
            self._close_audio()
            self._set_status("error", "Không mở được microphone", notify=True)
            self._notify(f"Không mở được microphone: {exc}")

    def _record_loop(self) -> None:
        while self.recording and self.stream is not None:
            try:
                self.frames.append(self.stream.read(1024, exception_on_overflow=False))
            except Exception:
                logging.exception("Microphone read failed")
                break

    def stop_recording(self) -> None:
        if not self.recording:
            return
        self.recording = False
        self._set_status("processing", "ĐANG NHẬN DẠNG VÀ DỊCH", notify=True)
        self._play_sound("processing")
        if self.record_thread:
            self.record_thread.join(timeout=1)
        audio_bytes = b"".join(self.frames)
        logging.info(
            "Recorded %.2f seconds (%s bytes)",
            len(audio_bytes) / max(1, self.sample_rate * self.channels * 2),
            len(audio_bytes),
        )
        samples = array.array("h")
        samples.frombytes(audio_bytes)
        if samples:
            sums = [0.0] * self.channels
            peaks = [0] * self.channels
            counts = [0] * self.channels
            for index, sample in enumerate(samples):
                channel = index % self.channels
                sums[channel] += float(sample) * float(sample)
                peaks[channel] = max(peaks[channel], abs(sample))
                counts[channel] += 1
            rms = [round(math.sqrt(sums[i] / max(1, counts[i])) / 32768.0, 5) for i in range(self.channels)]
            peak = [round(peaks[i] / 32768.0, 5) for i in range(self.channels)]
            logging.info("Audio levels RMS=%s peak=%s", rms, peak)
        self._close_audio()
        if len(audio_bytes) < self.sample_rate * self.channels // 2:
            self._set_status("error", "Đoạn nói quá ngắn", notify=True)
            self._notify("Đoạn nói quá ngắn")
            return
        self.processing = True
        threading.Thread(
            target=self._process_recording, args=(audio_bytes,), daemon=True
        ).start()

    def _close_audio(self) -> None:
        if self.stream is not None:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass
        if self.audio is not None:
            try:
                self.audio.terminate()
            except Exception:
                pass
        self.stream = None
        self.audio = None

    def _process_recording(self, audio_bytes: bytes) -> None:
        restart_engine = False
        try:
            logging.info("Submitting %.2f seconds to %s/dictate", len(audio_bytes) / max(1, self.sample_rate * self.channels * 2), API_URL)
            payload = {
                "pcm16_base64": base64.b64encode(audio_bytes).decode("ascii"),
                "sample_rate": self.sample_rate,
                "channels": self.channels,
                "mode": self.settings["mode"],
                "source_language": self.settings["source_language"],
                "target_language": self.settings["target_language"],
                "translate": bool(self.settings["translate"]),
            }
            request = urllib.request.Request(
                f"{API_URL}/dictate",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=180) as response:
                result = json.loads(response.read().decode("utf-8"))
            logging.info(
                "Dictation response: source=%s target=%s transcript=%r text=%r",
                result.get("source_language"),
                result.get("target_language"),
                str(result.get("transcript", ""))[:200],
                str(result.get("text", ""))[:200],
            )
            text = str(result.get("text", "")).strip()
            if not text:
                raise RuntimeError("Không nhận ra nội dung")
            self._paste_text(text, self.target_window, self.target_control)
            self._set_status("done", "ĐÃ NHẬP XONG", notify=True)
            self._play_sound("done")
            self._notify(f"Đã nhập: {text[:80]}")
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("detail", str(exc))
            except Exception:
                detail = str(exc)
            self._set_status("error", "NHẬN DẠNG LỖI", notify=True)
            self._play_sound("error")
            self._notify(f"Nhận dạng lỗi: {detail}")
        except urllib.error.URLError as exc:
            restart_engine = True
            logging.exception("Voice typing engine connection failed")
            self._set_status("error", "MẤT KẾT NỐI ENGINE · đang khởi động lại")
            self._play_sound("error")
            self._notify(f"Voice typing mất kết nối engine: {exc}")
        except Exception as exc:
            logging.exception("Voice typing failed")
            self._set_status("error", "VOICE TYPING LỖI", notify=True)
            self._play_sound("error")
            self._notify(f"Voice typing lỗi: {exc}")
        finally:
            self.processing = False
            if restart_engine:
                threading.Thread(target=self._ensure_engine, daemon=True).start()
            else:
                time.sleep(0.8)
                self._set_status("ready", f"Sẵn sàng · {self.settings['hotkey']}")

    @staticmethod
    def _focused_target() -> tuple[int | None, int | None]:
        user32 = ctypes.windll.user32
        foreground = int(user32.GetForegroundWindow())
        if not foreground:
            return None, None
        process_id = wintypes.DWORD()
        thread_id = user32.GetWindowThreadProcessId(foreground, ctypes.byref(process_id))
        info = _GuiThreadInfo(cbSize=ctypes.sizeof(_GuiThreadInfo))
        focus = int(info.hwndFocus) if user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)) and info.hwndFocus else None
        return foreground, focus

    @staticmethod
    def _paste_text(text: str, target_window: int | None, target_control: int | None = None) -> None:
        # Keep the generated text in the clipboard. This provides a reliable
        # manual Ctrl+V fallback when a protected/elevated application rejects
        # injected input.
        pyperclip.copy(text)
        logging.info("Clipboard updated with %s characters", len(text))
        user32 = ctypes.windll.user32
        if target_window:
            target_thread = user32.GetWindowThreadProcessId(target_window, None)
            current_thread = ctypes.windll.kernel32.GetCurrentThreadId()
            attached = bool(target_thread and target_thread != current_thread and user32.AttachThreadInput(current_thread, target_thread, True))
            try:
                user32.ShowWindow(target_window, 5)
                user32.BringWindowToTop(target_window)
                user32.SetForegroundWindow(target_window)
                if target_control:
                    user32.SetFocus(target_control)
            finally:
                if attached:
                    user32.AttachThreadInput(current_thread, target_thread, False)
            time.sleep(0.18)

        class_name = ctypes.create_unicode_buffer(256)
        if target_control:
            user32.GetClassNameW(target_control, class_name, len(class_name))
        if target_control and "edit" in class_name.value.casefold():
            user32.SendMessageW(target_control, 0x0302, 0, 0)  # WM_PASTE
            logging.info("Text injection: WM_PASTE to %s", class_name.value)
        else:
            user32.keybd_event(0x11, 0, 0, 0)  # Ctrl down
            user32.keybd_event(0x56, 0, 0, 0)  # V down
            user32.keybd_event(0x56, 0, 2, 0)  # V up
            user32.keybd_event(0x11, 0, 2, 0)  # Ctrl up
            logging.info("Text injection: Win32 Ctrl+V to %s", class_name.value or "focused window")
        time.sleep(0.65)

    @staticmethod
    def _icon_image(color: str = "#c9ff5d") -> Image.Image:
        image = Image.new("RGB", (64, 64), "#10150f")
        draw = ImageDraw.Draw(image)
        draw.ellipse((8, 8, 56, 56), fill=color)
        draw.rounded_rectangle((26, 16, 38, 39), radius=6, fill="#10150f")
        draw.arc((19, 25, 45, 48), 0, 180, fill="#10150f", width=4)
        draw.line((32, 47, 32, 54), fill="#10150f", width=4)
        return image

    def quit(self, icon: pystray.Icon | None = None, item: Any = None) -> None:
        del item
        self.stop_event.set()
        self.recording = False
        self._close_audio()
        keyboard.unhook_all()
        if icon:
            icon.stop()
        if self.overlay is not None:
            try:
                self.overlay.after(0, self.overlay.destroy)
            except Exception:
                pass

    def run(self) -> None:
        (RUN_DIR / "hotkey.pid").write_text(str(os.getpid()), encoding="ascii")
        self._register_hotkey()
        threading.Thread(target=self._watch_settings, daemon=True).start()
        menu = pystray.Menu(
            pystray.MenuItem("Mở SpeakBridge", lambda: webbrowser.open("http://localhost:3000/")),
            pystray.MenuItem("Thoát Voice Typing", self.quit),
        )
        self.icon = pystray.Icon(
            "SpeakBridgeVoiceTyping", self._icon_image(), "SpeakBridge Voice Typing", menu
        )
        self._notify(f"Giữ {self.settings['hotkey']} để nói")
        self._set_status("ready", f"Giữ {self.settings['hotkey']} để nói")
        threading.Thread(target=self.icon.run, daemon=True).start()
        self._create_overlay()
        threading.Thread(target=self._ensure_engine, daemon=True).start()
        assert self.overlay is not None
        self.overlay.mainloop()


if __name__ == "__main__":
    VoiceTypingHelper().run()
